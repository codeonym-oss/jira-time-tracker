"""Terminal rendering.

Everything takes raw field amounts and shows them in the project's display unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from jira_time_tracker.units import Unit, WorkCalendar, convert, fmt_amount, fmt_signed

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date, datetime

    from rich.console import RenderableType

    from jira_time_tracker.config import ProjectConfig
    from jira_time_tracker.period import Window
    from jira_time_tracker.tracking import Contribution, IssueReport

console = Console()
errors = Console(stderr=True)
trace = Console(stderr=True, style="dim")

STATUS_COLORS = {"new": "blue", "indeterminate": "yellow", "done": "green"}
BAR = "█"
SPARK = " ▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class Amounts:
    """Converts raw field amounts into the unit a report shows."""

    source: Unit
    target: Unit
    calendar: WorkCalendar

    @classmethod
    def for_project(
        cls, project: ProjectConfig, calendar: WorkCalendar, override: Unit | None = None
    ) -> Amounts:
        """Build for a project, optionally showing another time unit."""
        return cls(project.unit, override or project.display_unit, calendar)

    def value(self, raw: float) -> float:
        """Convert a raw amount to the shown unit."""
        return convert(raw, self.source, self.target, self.calendar)

    def plain(self, raw: float) -> str:
        """Format a raw amount in the shown unit."""
        return fmt_amount(self.value(raw), self.target)

    def signed(self, raw: float) -> Text:
        """Format a raw change with its sign and colour."""
        value = self.value(raw)
        if round(value, 2) == 0:
            return Text("±0", style="dim")
        return Text(fmt_signed(value, self.target), style="bold green" if value > 0 else "bold red")


def when(moment: datetime | None) -> str:
    """Format a timestamp as day/month hour:minute."""
    return moment.strftime("%d/%m %H:%M") if moment else "?"


def header(title: str, rows: Iterable[tuple[str, str]]) -> Panel:
    """Return a titled panel of label/value rows."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", justify="right")
    grid.add_column()
    for label, value in rows:
        grid.add_row(label, value)
    return Panel(
        grid,
        title=f"[bold]{escape(title)}[/]",
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
    )


def period_line(window: Window) -> str:
    """Describe the period, saying which end is included."""
    plural = "s" if window.days > 1 else ""
    return (
        f"{window.date_from:%a %d %b %Y} [green]included[/] → "
        f"{window.date_to:%a %d %b %Y} [red]excluded[/]"
        f"  [dim]· {window.days} day{plural}, Jira profile time zone[/]"
    )


def field_line(project: ProjectConfig, amounts: Amounts) -> str:
    """Describe the tracked field and its units."""
    shown = f", shown in {amounts.target.value}" if amounts.target is not project.unit else ""
    return f"{escape(project.field_name)} [dim]({project.field_id}, {project.unit.value}{shown})[/]"


# ── issues ───────────────────────────────────────────────────────────────────


def delta_source(report: IssueReport) -> str:
    """Say where an issue's delta came from."""
    parts = []
    if report.created_with:
        parts.append("created with value")
    if n := len(report.in_period):
        parts.append(f"{n} edit{'s' if n > 1 else ''}")
    return ", ".join(parts) or "no change"


def issues_table(
    reports: list[IssueReport],
    amounts: Amounts,
    level: int,
    deltas: dict[str, float] | None = None,
    highlight_user: str | None = None,
) -> Table:
    """`deltas` overrides each issue's delta (e.g. only the part a user held)."""
    deltas = deltas or {r.key: r.delta for r in reports}
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
    table.add_column("Issue", style="bold", no_wrap=True)
    table.add_column(f"Δ {amounts.target.short}", justify="right", no_wrap=True, min_width=6)
    if level >= 1:
        table.add_column("Now", justify="right", style="dim", no_wrap=True, min_width=5)
        table.add_column("Type", style="dim", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Assignee now", no_wrap=True)
        table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Summary", overflow="ellipsis", no_wrap=True, ratio=1)

    shown = reports if level >= 2 else [r for r in reports if deltas[r.key] != 0]
    for r in sorted(shown, key=lambda r: (deltas[r.key] == 0, -abs(deltas[r.key]), r.key)):
        cells: list[RenderableType] = [r.key, amounts.signed(deltas[r.key])]
        if level >= 1:
            moved = highlight_user is not None and r.assignee.account_id != highlight_user
            cells += [
                amounts.plain(r.current_value),
                r.issue_type,
                Text(r.status, style=STATUS_COLORS.get(r.status_category, "")),
                Text(r.assignee.name + (" ↪" if moved else ""), style="magenta" if moved else ""),
                delta_source(r),
            ]
        cells.append(r.summary)
        table.add_row(*cells, style="dim" if deltas[r.key] == 0 else "")
    return table


def timelines(reports: list[IssueReport], amounts: Amounts, level: int) -> Tree:
    """Return a tree of each issue's changes, one branch per issue."""
    note = "in-period changes" + (", out-of-period struck through" if level >= 3 else "")
    root = Tree(f"[bold]Timeline[/] [dim]({note})[/]")
    for r in sorted(reports, key=lambda r: r.key):
        visible = r.changes if level >= 3 else tuple(r.in_period)
        if not visible and r.created_with is None and r.completed_at is None:
            continue
        branch = root.add(
            Text.assemble(
                (r.key, "bold"), "  ", amounts.signed(r.delta), ("  " + r.summary[:70], "dim")
            )
        )
        if r.created_with:
            branch.add(
                Text.assemble(
                    (when(r.created), "cyan"),
                    "  created with ",
                    (amounts.plain(r.created_with), "bold"),
                    "  ",
                    amounts.signed(r.created_with),
                    (f"  credited to {r.first_holder.name}", "dim"),
                )
            )
        elif r.created_with is not None:
            branch.add(
                Text.assemble((when(r.created), "cyan"), ("  created without a value", "dim"))
            )
        for c in visible:
            before = amounts.plain(c.before) if c.before else "—"
            after = amounts.plain(c.after) if c.after else "—"
            line = Text.assemble(
                (when(c.at), "cyan"),
                "  ",
                (f"{before} → {after}", "bold"),
                "  ",
                amounts.signed(c.delta),
                (f"  by {c.author}", "dim"),
            )
            if level >= 3 and c.holder.name != c.author:
                line.append(f"  (held by {c.holder.name})", "dim")
            if c.position != "in":
                line.stylize("dim strike")
                line.append(f"  ({c.position} period)", "dim italic")
            branch.add(line)
        if r.completed_at is not None:
            branch.add(
                Text.assemble(
                    (when(r.completed_at), "cyan"),
                    ("  ✔ done", "green"),
                    f" at {amounts.plain(r.completed_value)}",
                    (f"  held by {r.completed_by.name if r.completed_by else '?'}", "dim"),
                )
            )
    return root


def totals(
    reports: list[IssueReport],
    deltas: dict[str, float],
    amounts: Amounts,
    level: int,
    elapsed: float,
) -> Panel:
    """Return the closing panel of a calculate run."""
    net = sum(deltas.values())
    added = sum(d for d in deltas.values() if d > 0)
    removed = sum(d for d in deltas.values() if d < 0)
    changed = sum(1 for d in deltas.values() if d != 0)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="bold")
    grid.add_column()
    grid.add_row(
        "Net added",
        Text(
            fmt_signed(amounts.value(net), amounts.target),
            style="bold bright_green" if net >= 0 else "bold red",
        ),
    )
    if level >= 1:
        grid.add_row(
            "Added / removed",
            Text.assemble((amounts.plain(added), "green"), " / ", (amounts.plain(removed), "red")),
        )
        created = [r for r in reports if r.created_with is not None]
        created_value = sum(r.created_with or 0 for r in created)
        grid.add_row(
            "Created in period",
            f"{len(created)} issues [dim](bringing {amounts.plain(created_value)})[/]",
        )
        done = [r for r in reports if r.completed_at is not None]
        if done:
            grid.add_row(
                "Done in period",
                f"{len(done)} issues "
                f"[dim]({amounts.plain(sum(r.completed_value for r in done))})[/]",
            )
    grid.add_row("Issues with a change", f"{changed} [dim]of {len(reports)} scanned[/]")
    if level >= 1:
        grid.add_row("Took", f"{elapsed:.1f} s")
    return Panel(
        grid, border_style="bright_green" if net >= 0 else "red", box=box.ROUNDED, expand=False
    )


# ── people ───────────────────────────────────────────────────────────────────


def contributions_table(people: list[Contribution], amounts: Amounts) -> Table:
    """Return the per-person table with a bar per person."""
    total_added = sum(p.added for p in people) or 1.0
    widest = max((abs(p.net) for p in people), default=0) or 1.0
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
    table.add_column("Person", style="bold", no_wrap=True)
    table.add_column(f"Net {amounts.target.short}", justify="right", no_wrap=True)
    table.add_column("Added", justify="right", style="green", no_wrap=True)
    table.add_column("Removed", justify="right", style="red", no_wrap=True)
    table.add_column("Share", justify="right", no_wrap=True)
    table.add_column("Issues", justify="right", no_wrap=True)
    table.add_column("Created", justify="right", no_wrap=True)
    table.add_column("Done", justify="right", no_wrap=True)
    table.add_column("", ratio=1, no_wrap=True)
    for p in people:
        bar = BAR * max(1, round(20 * abs(p.net) / widest)) if p.net else ""
        table.add_row(
            p.name,
            amounts.signed(p.net),
            amounts.plain(p.added) if p.added else "",
            amounts.plain(p.removed) if p.removed else "",
            f"{100 * p.added / total_added:.0f}%" if p.added else "",
            str(len(p.issues)),
            f"{p.created_count}"
            + (f" [dim]({amounts.plain(p.created_value)})[/]" if p.created_value else ""),
            f"{p.completed_count}"
            + (f" [dim]({amounts.plain(p.completed_value)})[/]" if p.completed_value else ""),
            Text(bar, style="green" if p.net >= 0 else "red"),
        )
    return table


def series_table(
    title: str, series: dict[date, float], amounts: Amounts, label_format: str
) -> Table:
    """Return a per-day or per-week table with bars."""
    widest = max((abs(v) for v in series.values()), default=0) or 1.0
    table = Table(
        title=title,
        title_justify="left",
        title_style="bold",
        box=box.SIMPLE,
        pad_edge=False,
        expand=True,
    )
    table.add_column("When", no_wrap=True, style="cyan")
    table.add_column(f"Net {amounts.target.short}", justify="right", no_wrap=True)
    table.add_column("", ratio=1, no_wrap=True)
    for day, value in series.items():
        bar = BAR * max(1, round(30 * abs(value) / widest)) if value else ""
        table.add_row(
            day.strftime(label_format),
            amounts.signed(value),
            Text(bar, style="green" if value >= 0 else "red"),
        )
    return table


def sparkline(values: list[float]) -> str:
    """Return a one-line block-character chart of `values`."""
    top = max((abs(v) for v in values), default=0)
    if not top:
        return SPARK[0] * len(values)
    return "".join(SPARK[round(8 * abs(v) / top)] for v in values)


def stats_panel(
    reports: list[IssueReport],
    people: list[Contribution],
    daily: dict[date, float],
    amounts: Amounts,
) -> Panel:
    """Return the statistics panel of a contributions run."""
    net = sum(p.net for p in people)
    changed = [r for r in reports if r.delta]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="bold")
    grid.add_column()
    grid.add_row(
        "Net added",
        Text(
            fmt_signed(amounts.value(net), amounts.target),
            style="bold bright_green" if net >= 0 else "bold red",
        ),
    )
    grid.add_row(
        "People",
        f"{sum(1 for p in people if p.net or p.completed_count)} active "
        f"[dim]of {len(people)} credited[/]",
    )
    if changed:
        grid.add_row(
            "Per changed issue",
            f"{amounts.plain(sum(r.delta for r in changed) / len(changed))} "
            f"[dim]average over {len(changed)}[/]",
        )
        biggest = max(changed, key=lambda r: abs(r.delta))
        grid.add_row(
            "Biggest",
            f"{biggest.key} {fmt_signed(amounts.value(biggest.delta), amounts.target)} "
            f"[dim]{escape(biggest.summary[:50])}[/]",
        )
    done = [r for r in reports if r.completed_at is not None]
    grid.add_row(
        "Done in period",
        f"{len(done)} issues [dim]({amounts.plain(sum(r.completed_value for r in done))})[/]",
    )
    if daily:
        busiest = max(daily, key=lambda d: daily[d])
        active_days = sum(1 for v in daily.values() if v)
        grid.add_row("Daily trend", f"[green]{sparkline(list(daily.values()))}[/]")
        grid.add_row(
            "Busiest day",
            f"{busiest:%a %d %b} "
            f"[dim]({amounts.plain(daily[busiest])}, {active_days} active days)[/]",
        )
    return Panel(
        grid,
        title="[bold]Statistics[/]",
        title_align="left",
        border_style="bright_green",
        box=box.ROUNDED,
        expand=False,
    )


def collaborators_table(users: list[dict], counts: dict[str, dict[str, int]], me: str) -> Table:
    """Return the table of assignable people and their load."""
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
    table.add_column("Name", style="bold", no_wrap=True)
    table.add_column("To do", justify="right", style="blue")
    table.add_column("In progress", justify="right", style="yellow")
    table.add_column("Done", justify="right", style="green")
    table.add_column("Email", style="dim", no_wrap=True)
    table.add_column("Account id", style="dim", overflow="fold")
    for user in users:
        seen = counts.get(user["accountId"], {})
        name = user.get("displayName", "?") + (" (you)" if user["accountId"] == me else "")
        table.add_row(
            Text(name, style="" if user.get("active", True) else "dim strike"),
            str(seen.get("new", 0) or ""),
            str(seen.get("indeterminate", 0) or ""),
            str(seen.get("done", 0) or ""),
            user.get("emailAddress", ""),
            user["accountId"],
        )
    return table
