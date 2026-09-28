"""
Jira SP Delta Calculator
Fetches the issues an assignee held during a period and computes the *net*
Story Points added inside it — pre-existing SP are never double-counted, only
SP that came into being inside the period are summed.

The period is [--from, --to): the whole --from day is included, the --to day
is excluded (the accounting team's rule). Days are calendar days as Jira
renders them: the API writes every timestamp in the caller's profile zone,
with the same zone rules JQL reads date literals by.

Fixes vs. the original draft:
  1. JQL operator precedence: AND binds tighter than OR in JQL, so
     `... AND assignee in membersOf(x) OR assignee = x AND updated >= ...`
     silently expanded to match ALL issues regardless of date range whenever
     the first branch matched. Fixed by wrapping in parentheses (and the
     `membersOf()` call — which expects a *group* name, not an account ID —
     was dropped as it wasn't valid usage here).
  2. Pagination: /rest/api/3/search/jql (the current endpoint; /rest/api/3/search
     is fully removed) does not return a reliable `total` field — it uses
     `nextPageToken`. The old startAt/total loop silently stopped after page 1.
  3. Changelog timestamps are parsed as timezone-aware, keeping Jira's offset.
  4. `updated` in JQL is the *last* update, so `updated < end` dropped every
     issue that was touched in the period and again after it (VPX-729: SP set
     on 25/09, edited again on 28/09, missing from a run ending 25/09). The
     JQL now only bounds `updated` from below; the changelog enforces the end.
  5. SP entered on the create screen leave no changelog entry (the log starts
     at the first edit), so an issue created in the period with SP counted 0.
     Its value at creation is now added back.
  6. The changelog filter compared UTC instants against UTC-midnight bounds,
     so it disagreed with JQL (profile zone) on where a day starts. It now
     compares the day Jira rendered each timestamp on. It deliberately does
     not rebuild the zone from local tzdata: tzdata 2026d keeps
     Africa/Casablanca at +00 after Ramadan 2026 while Jira still renders it
     at +01.
  7. `assignee = X` is whoever holds the issue *now*, so an issue reassigned
     after the period moved its SP to the new holder. The JQL now asks for
     `assignee WAS X DURING (...)`.

JQL bounds are written as "YYYY-MM-DD 00:00", never as bare dates: checked
against VPX, `DURING ("2026-09-24", "2026-09-25")` matched issues first
assigned at 13:05 on the 25th, and `DURING ("2026-09-25", "2026-09-25")`
matched nothing, while the explicit-time form is an exact half-open range.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests
import typer
from requests.auth import HTTPBasicAuth
from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

app = typer.Typer(help="Calculate net Story Points added in Jira within a date range.")

SP_FIELD_NAMES = {"story points", "story point estimate", "sp"}
SEARCH_PAGE_SIZE = 100
CHANGELOG_PAGE_SIZE = 100

STATUS_COLORS = {"new": "blue", "indeterminate": "yellow", "done": "green"}

console = Console()
trace = Console(stderr=True, style="dim")


@dataclass(frozen=True)
class Window:
    """[date_from, date_to): the from day included, the to day excluded, in Jira's rendering."""

    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_to <= self.date_from:
            raise typer.BadParameter(f"--to ({self.date_to}) must be after --from ({self.date_from})")

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days

    def position(self, moment: datetime) -> str:
        """'before', 'in' or 'after'. `moment` must keep the offset Jira sent,
        so .date() is the day Jira means."""
        day = moment.date()
        if day < self.date_from:
            return "before"
        return "in" if day < self.date_to else "after"

    def contains(self, moment: datetime) -> bool:
        return self.position(moment) == "in"


@dataclass(frozen=True)
class SpChange:
    at: datetime
    author: str
    field: str
    before: float
    after: float
    position: str

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass(frozen=True)
class IssueReport:
    key: str
    summary: str
    issue_type: str
    status: str
    status_category: str
    assignee_id: Optional[str]
    assignee_name: str
    created: Optional[datetime]
    current_sp: float
    # SP the issue was created with, when it was created inside the period.
    created_with: Optional[float]
    changes: tuple[SpChange, ...]

    @property
    def in_window_changes(self) -> list[SpChange]:
        return [c for c in self.changes if c.position == "in"]

    @property
    def delta(self) -> float:
        return (self.created_with or 0.0) + sum(c.delta for c in self.in_window_changes)


def build_session(email: str, api_token: str, trace_http: bool) -> requests.Session:
    session = requests.Session()
    session.auth = HTTPBasicAuth(email, api_token)
    session.headers.update({"Accept": "application/json"})
    if trace_http:
        session.hooks["response"].append(log_response)
    return session


def log_response(resp: requests.Response, *args: object, **kwargs: object) -> None:
    ms = resp.elapsed.total_seconds() * 1000
    url = requests.utils.unquote(resp.request.url or "")
    trace.print(f"  HTTP {resp.request.method} {resp.status_code} {ms:6.0f} ms  {escape(url)}", soft_wrap=True)


def parse_jira_timestamp(raw: str) -> Optional[datetime]:
    """Jira sends e.g. '2026-07-21T16:20:00.000+0100'. Python's fromisoformat
    wants a ':' in the UTC offset, so normalize before parsing. The offset is
    kept, not converted, so the date stays the one Jira rendered."""
    if not raw:
        return None
    normalized = raw
    if len(normalized) >= 5 and normalized[-5] in "+-" and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_sp(raw: object) -> float:
    """An SP value as the changelog or the field holds it; empty means 0."""
    if raw in (None, ""):
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def fetch_sp_fields(session: requests.Session, base_url: str) -> dict[str, str]:
    """Story points field id → name. Ids differ per site (VPX: customfield_10016)."""
    resp = session.get(f"{base_url}/rest/api/3/field")
    resp.raise_for_status()
    fields = {f["id"]: f["name"] for f in resp.json() if f.get("name", "").lower() in SP_FIELD_NAMES}
    if not fields:
        raise typer.BadParameter(f"No story points field named any of {sorted(SP_FIELD_NAMES)}")
    return fields


def fetch_display_name(session: requests.Session, base_url: str, account_id: str) -> str:
    resp = session.get(f"{base_url}/rest/api/3/user", params={"accountId": account_id})
    return resp.json().get("displayName", account_id) if resp.ok else account_id


def build_jql(project: str, assignee_id: str, window: Window) -> str:
    """Issues the assignee held at some point in the period that can have an SP
    change inside it.

    `updated` is the *last* update, so it only bounds from below: anything
    changed inside the period was last updated at or after its start, but may
    have been updated again since. `created` bounds from above: an issue
    created after the period cannot have changed inside it. The changelog walk
    is what enforces the precise period.
    """
    start, end = f'"{window.date_from} 00:00"', f'"{window.date_to} 00:00"'
    return (
        f'project = {project} '
        f'AND assignee WAS "{assignee_id}" DURING ({start}, {end}) '
        f'AND updated >= {start} '
        f'AND created < {end}'
    )


def fetch_issues(session: requests.Session, base_url: str, jql: str, sp_field_ids: list[str]) -> list[dict]:
    """Fetch all issues matching the JQL query via token-based pagination."""
    issues: list[dict] = []
    next_page_token: Optional[str] = None

    while True:
        params: dict[str, object] = {
            "jql": jql,
            "maxResults": SEARCH_PAGE_SIZE,
            "fields": ",".join(["summary", "created", "status", "issuetype", "assignee", *sp_field_ids]),
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        resp = session.get(f"{base_url}/rest/api/3/search/jql", params=params)
        resp.raise_for_status()
        data = resp.json()

        issues.extend(data.get("issues", []))
        next_page_token = data.get("nextPageToken")

        if not next_page_token or data.get("isLast", not next_page_token):
            break

    return issues


def fetch_changelog(session: requests.Session, base_url: str, issue_key: str) -> list[dict]:
    """Every changelog entry for an issue, oldest first."""
    entries: list[dict] = []
    start_at = 0

    while True:
        resp = session.get(
            f"{base_url}/rest/api/3/issue/{issue_key}/changelog",
            params={"startAt": start_at, "maxResults": CHANGELOG_PAGE_SIZE},
        )
        resp.raise_for_status()
        data = resp.json()
        page = data.get("values", [])
        entries.extend(page)

        start_at += len(page)
        if not page or data.get("isLast", start_at >= data.get("total", 0)):
            break

    return entries


def build_report(issue: dict, changelog: list[dict], sp_fields: dict[str, str], window: Window) -> IssueReport:
    """An issue's SP changes, each placed against the period.

    The net delta is every SP change logged inside the period plus, for an
    issue created inside it, the SP it was created with: the changelog starts
    at the first edit, so a value set on the create screen is only visible as
    the `from` side of the first later change, or as the current value if it
    was never changed.
    """
    fields = issue["fields"]
    created = parse_jira_timestamp(fields.get("created", ""))
    created_inside = created is not None and window.contains(created)
    changes: list[SpChange] = []
    created_with = 0.0

    for field_id, field_name in sp_fields.items():
        field_changes = sorted(
            (
                SpChange(
                    at=changed_at,
                    author=entry.get("author", {}).get("displayName", "?"),
                    field=field_name,
                    before=parse_sp(item.get("fromString")),
                    after=parse_sp(item.get("toString")),
                    position=window.position(changed_at),
                )
                for entry in changelog
                if (changed_at := parse_jira_timestamp(entry.get("created", ""))) is not None
                for item in entry.get("items", [])
                if item.get("fieldId") == field_id
            ),
            key=lambda change: change.at,
        )
        changes.extend(field_changes)
        created_with += field_changes[0].before if field_changes else parse_sp(fields.get(field_id))

    assignee = fields.get("assignee") or {}
    status = fields.get("status") or {}
    return IssueReport(
        key=issue["key"],
        summary=fields.get("summary", ""),
        issue_type=(fields.get("issuetype") or {}).get("name", ""),
        status=status.get("name", ""),
        status_category=(status.get("statusCategory") or {}).get("key", ""),
        assignee_id=assignee.get("accountId"),
        assignee_name=assignee.get("displayName", "Unassigned"),
        created=created,
        current_sp=sum(parse_sp(fields.get(field_id)) for field_id in sp_fields),
        created_with=created_with if created_inside else None,
        changes=tuple(sorted(changes, key=lambda change: change.at)),
    )


# ── rendering ────────────────────────────────────────────────────────────────


def fmt_sp(value: float) -> str:
    return f"{value:g}"


def fmt_delta(value: float) -> Text:
    if value == 0:
        return Text("±0", style="dim")
    return Text(f"{value:+g}", style="bold green" if value > 0 else "bold red")


def fmt_when(moment: Optional[datetime]) -> str:
    return moment.strftime("%d/%m %H:%M") if moment else "?"


def delta_source(report: IssueReport) -> str:
    parts = []
    if report.created_with:
        parts.append(f"created with {fmt_sp(report.created_with)}")
    if n := len(report.in_window_changes):
        parts.append(f"{n} edit{'s' if n > 1 else ''}")
    return ", ".join(parts) or "no SP change"


def render_header(project: str, assignee_name: str, window: Window, level: int) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", justify="right")
    grid.add_column()
    grid.add_row("Project", project)
    grid.add_row("Assignee", f"{escape(assignee_name)} [dim](held the issue at any point in the period)[/]")
    grid.add_row(
        "Period",
        f"{window.date_from:%a %d %b %Y} [green]included[/] → {window.date_to:%a %d %b %Y} [red]excluded[/]"
        f"  [dim]· {window.days} day{'s' if window.days > 1 else ''}, Jira profile time zone[/]",
    )
    if level:
        grid.add_row("Verbosity", f"-{'v' * level}")
    return Panel(grid, title="[bold]Story points delta[/]", title_align="left", border_style="cyan", box=box.ROUNDED)


def render_table(reports: list[IssueReport], assignee_id: str, level: int) -> Table:
    # Summary is the only flexible column: everything else keeps its natural width.
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
    table.add_column("Issue", style="bold", no_wrap=True)
    table.add_column("Δ SP", justify="right", no_wrap=True, min_width=5)
    if level >= 1:
        table.add_column("SP now", justify="right", style="dim", no_wrap=True, min_width=6)
        table.add_column("Type", style="dim", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Assignee now", no_wrap=True)
        table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Summary", overflow="ellipsis", no_wrap=True, ratio=1)

    shown = reports if level >= 2 else [r for r in reports if r.delta != 0]
    for r in sorted(shown, key=lambda r: (r.delta == 0, -abs(r.delta), r.key)):
        cells: list[object] = [r.key, fmt_delta(r.delta)]
        if level >= 1:
            reassigned = r.assignee_id != assignee_id
            cells += [
                fmt_sp(r.current_sp),
                r.issue_type,
                Text(r.status, style=STATUS_COLORS.get(r.status_category, "")),
                Text(r.assignee_name + (" ↪" if reassigned else ""), style="magenta" if reassigned else ""),
                delta_source(r),
            ]
        cells.append(r.summary)
        table.add_row(*cells, style="dim" if r.delta == 0 else "")
    return table


def render_timelines(reports: list[IssueReport], level: int) -> Tree:
    root = Tree("[bold]SP timeline[/] [dim](in-period changes" + (", out-of-period dimmed" if level >= 3 else "") + ")[/]")
    for r in sorted(reports, key=lambda r: r.key):
        visible = r.changes if level >= 3 else tuple(r.in_window_changes)
        if not visible and r.created_with is None:
            continue
        branch = root.add(Text.assemble((r.key, "bold"), "  ", fmt_delta(r.delta), ("  " + r.summary[:60], "dim")))
        if r.created_with:
            branch.add(
                Text.assemble(
                    (fmt_when(r.created), "cyan"), "  created with ", (fmt_sp(r.created_with), "bold"),
                    " SP  ", fmt_delta(r.created_with),
                )
            )
        elif r.created_with is not None:
            branch.add(Text.assemble((fmt_when(r.created), "cyan"), ("  created without SP", "dim")))
        for c in visible:
            line = Text.assemble(
                (fmt_when(c.at), "cyan"), "  ",
                (f"{fmt_sp(c.before) if c.before else '—'} → {fmt_sp(c.after) if c.after else '—'}", "bold"),
                "  ", fmt_delta(c.delta), (f"  by {c.author}", "dim"),
            )
            if len({ch.field for ch in r.changes}) > 1:
                line.append(f"  [{c.field}]", "dim")
            if c.position != "in":
                line.stylize("dim strike")
                line.append(f"  ({c.position} period)", "dim italic")
            branch.add(line)
    return root


def render_summary(reports: list[IssueReport], elapsed: float, level: int) -> Panel:
    total = sum(r.delta for r in reports)
    added = sum(r.delta for r in reports if r.delta > 0)
    removed = sum(r.delta for r in reports if r.delta < 0)
    changed = sum(1 for r in reports if r.delta != 0)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="bold")
    grid.add_column()
    grid.add_row("Net SP added", Text(f"{total:+.2f} SP", style="bold bright_green" if total >= 0 else "bold red"))
    if level >= 1:
        grid.add_row("Added / removed", Text.assemble((f"+{added:g}", "green"), " / ", (f"{removed:g}", "red")))
        created = [r for r in reports if r.created_with is not None]
        grid.add_row("Issues created in period", f"{len(created)} [dim](bringing {sum(r.created_with or 0 for r in created):g} SP)[/]")
    grid.add_row("Issues with SP change", f"{changed} [dim]of {len(reports)} scanned[/]")
    if level >= 1:
        grid.add_row("Took", f"{elapsed:.1f} s")
    return Panel(grid, border_style="bright_green" if total >= 0 else "red", box=box.ROUNDED, expand=False)


@app.command()
def main(
    base_url: str = typer.Option(..., "--url", help="Jira base URL, e.g. https://your-domain.atlassian.net"),
    email: str = typer.Option(..., "--email", help="Your Jira account email"),
    token: str = typer.Option(..., "--token", help="Your Jira API token (https://id.atlassian.com/manage-api-tokens)"),
    project: str = typer.Option("VPX", "--project", help="Jira project key"),
    assignee: str = typer.Option(..., "--assignee", help="Assignee account ID"),
    date_from: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD), included"),
    date_to: str = typer.Option(..., "--to", help="End date (YYYY-MM-DD), excluded"),
    verbose: int = typer.Option(
        0, "--v", "-v", count=True,
        help="More detail, repeatable. -v: status, assignee and SP source columns. "
        "-vv (or --vv): per-issue SP timeline, zero-delta issues. -vvv (or --vvv): JQL, fields, HTTP trace, out-of-period changes.",
    ),
    vv: bool = typer.Option(False, "--vv", hidden=True),
    vvv: bool = typer.Option(False, "--vvv", hidden=True),
) -> None:
    level = min(3, max(verbose, 2 if vv else 0, 3 if vvv else 0))
    started = time.monotonic()
    window = Window(date.fromisoformat(date_from), date.fromisoformat(date_to))
    base_url = base_url.rstrip("/")
    session = build_session(email, token, trace_http=level >= 3)

    with console.status("Resolving fields and assignee…"):
        sp_fields = fetch_sp_fields(session, base_url)
        assignee_name = fetch_display_name(session, base_url, assignee)
    jql = build_jql(project, assignee, window)

    console.print(render_header(project, assignee_name, window, level))
    if level >= 3:
        console.print(Panel(escape(jql), title="JQL", title_align="left", border_style="dim"))
        console.print("[dim]Story points fields:[/] " + ", ".join(f"{escape(name)} [dim]({fid})[/]" for fid, name in sp_fields.items()))

    with console.status("Searching issues…"):
        issues = fetch_issues(session, base_url, jql, list(sp_fields))

    reports: list[IssueReport] = []
    with console.status("") as status:
        for i, issue in enumerate(issues, 1):
            status.update(f"Reading changelogs {i}/{len(issues)} · {issue['key']}")
            reports.append(build_report(issue, fetch_changelog(session, base_url, issue["key"]), sp_fields, window))

    if any(r.delta != 0 for r in reports) or (level >= 2 and reports):
        console.print(render_table(reports, assignee, level))
    else:
        console.print(f"\n  [dim]No story points changed in the period across {len(reports)} scanned issues.[/]\n")
    if level >= 2 and any(r.changes or r.created_with is not None for r in reports):
        console.print(render_timelines(reports, level))
        console.print()
    console.print(render_summary(reports, time.monotonic() - started, level))


if __name__ == "__main__":
    app()
