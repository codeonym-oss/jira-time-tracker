"""The `jtt` command line."""

from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote

import requests
import typer
from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table

from jira_time_tracker import __version__, credentials, render
from jira_time_tracker import export as exporter
from jira_time_tracker.client import JiraClient, JiraError, normalize_url, site_host
from jira_time_tracker.config import Config, ProjectConfig, SiteConfig
from jira_time_tracker.period import PERIOD_NAMES, PeriodError, Window, resolve_window
from jira_time_tracker.render import Amounts, console, errors
from jira_time_tracker.tracking import IssueReport, build_report, by_week, contributions, daily_net
from jira_time_tracker.units import TIME_TRACKING_FIELDS, Unit

app = typer.Typer(
    name="jtt",
    help="Track how much estimated work (story points, hours, days…) came into being in Jira "
    "over a period.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
config_app = typer.Typer(help="Show or change the saved configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


class Attribution(str, Enum):
    """Which changes count for --user."""

    was = "was"
    holder = "holder"


class GroupBy(str, Enum):
    """How contributions break the net down over time."""

    none = "none"
    day = "day"
    week = "week"


class ExportKind(str, Enum):
    """What each exported row is."""

    issues = "issues"
    changes = "changes"
    contributions = "contributions"
    daily = "daily"


class ExportFormat(str, Enum):
    """The file formats export writes."""

    csv = "csv"
    json = "json"
    md = "md"


# ── shared options ───────────────────────────────────────────────────────────

ProjectOpt = Annotated[
    str | None,
    typer.Option("--project", "-p", help="Project key; defaults to the one set by init."),
]
FromOpt = Annotated[str | None, typer.Option("--from", help="First day, included (YYYY-MM-DD).")]
ToOpt = Annotated[
    str | None,
    typer.Option(
        "--to", help="Last bound, excluded (YYYY-MM-DD). Defaults to tomorrow, so today counts."
    ),
]
PeriodOpt = Annotated[
    str | None,
    typer.Option(
        "--period", help=f"Named period instead of --from/--to: {', '.join(PERIOD_NAMES)}."
    ),
]
UserOpt = Annotated[
    str | None,
    typer.Option("--user", "-u", help="Account id, 'me', or part of a name or email."),
]
AsOpt = Annotated[Unit | None, typer.Option("--as", help="Show time amounts in another time unit.")]
WorkersOpt = Annotated[
    int, typer.Option("--workers", min=1, max=32, help="Parallel changelog requests.")
]
VerboseOpt = Annotated[
    int,
    typer.Option(
        "--v",
        "-v",
        count=True,
        help="More detail, repeatable. -v adds columns, "
        "-vv (--vv) adds per-issue timelines and unchanged issues, "
        "-vvv (--vvv) adds the JQL, the HTTP trace and out-of-period changes.",
    ),
]
VvOpt = Annotated[bool, typer.Option("--vv", hidden=True)]
VvvOpt = Annotated[bool, typer.Option("--vvv", hidden=True)]


def verbosity(count: int, vv: bool, vvv: bool) -> int:
    """Return the verbosity level (0-3) from -v counts and the --vv/--vvv spellings."""
    return min(3, max(count, 2 if vv else 0, 3 if vvv else 0))


# ── plumbing ─────────────────────────────────────────────────────────────────


def fail(message: str) -> typer.Exit:
    """Print an error line and return the exit to raise."""
    errors.print(f"[bold red]✘[/] {message}")
    return typer.Exit(1)


def guarded(command: Callable) -> Callable:
    """Turn the errors a user can act on into one red line instead of a traceback."""

    @functools.wraps(command)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return command(*args, **kwargs)
        except (JiraError, PeriodError, credentials.CredentialError, ValueError) as error:
            raise fail(escape(str(error))) from None

    return wrapper


def logged_in_site() -> tuple[Config, SiteConfig]:
    """Return the config and its active site, or exit when not logged in."""
    config = Config.load()
    site = config.site
    if site is None or not site.logged_in:
        raise fail("Not logged in. Run [bold]jtt login[/] first.")
    return config, site


def open_client(site: SiteConfig, level: int = 0, workers: int = 8) -> JiraClient:
    """Return a client for the site, closed when the command ends."""
    token = credentials.load_token(site_host(site.url), site.email, site.token_backend)
    if not token:
        raise fail(
            "The saved API token is missing. Run [bold]jtt logout[/] then [bold]jtt login[/]."
        )
    return closed_on_exit(
        JiraClient(
            site.url,
            site.email,
            token,
            on_response=trace_response if level >= 3 else None,
            workers=workers,
        )
    )


_open_clients: list[JiraClient] = []


def closed_on_exit(client: JiraClient) -> JiraClient:
    """Close the client's HTTP session when the running command ends (see `main`)."""
    _open_clients.append(client)
    return client


def close_clients() -> None:
    """Close every client the command opened."""
    while _open_clients:
        _open_clients.pop().close()


def trace_response(resp: requests.Response) -> None:
    """Print one line per HTTP response (-vvv)."""
    ms = resp.elapsed.total_seconds() * 1000
    url = unquote(resp.request.url or "")
    render.trace.print(
        f"  HTTP {resp.request.method} {resp.status_code} {ms:6.0f} ms  {escape(url)}",
        soft_wrap=True,
    )


def project_config(site: SiteConfig, key: str | None) -> tuple[str, ProjectConfig]:
    """Return the project key and its settings, or exit with what to run."""
    key = (key or site.default_project or "").upper()
    if not key:
        raise fail(
            "No project given and no default set. Pass [bold]-p KEY[/] or run [bold]jtt init[/]."
        )
    if key not in site.projects:
        raise fail(f"Project {key} has no tracked field yet. Run [bold]jtt init -p {key}[/].")
    return key, site.projects[key]


def resolve_user(client: JiraClient, site: SiteConfig, project: str, query: str) -> tuple[str, str]:
    """Return (account id, name) for 'me', an account id, or part of a name/email."""
    if query.lower() == "me":
        return site.account_id, site.display_name
    if ":" in query or (len(query) >= 24 and " " not in query and "@" not in query):
        user = client.user(query)
        return query, (user or {}).get("displayName", query)
    needle = query.lower()
    matches = [
        u
        for u in client.assignable_users(project)
        if needle in u.get("displayName", "").lower() or needle in u.get("emailAddress", "").lower()
    ]
    if len(matches) == 1:
        return matches[0]["accountId"], matches[0].get("displayName", query)
    if not matches:
        raise fail(
            f"No collaborator on {project} matches {query!r}. "
            f"See [bold]jtt collaborators -p {project}[/]."
        )
    names = ", ".join(u.get("displayName", "?") for u in matches[:8])
    raise fail(
        f"{query!r} matches several people ({names}). Be more specific or pass the account id."
    )


def build_jql(project: str, window: Window, user: str | None = None) -> str:
    """Return the JQL for the issues that can hold a change inside the period.

    `updated` is the *last* update, so it only bounds from below; `created` bounds from above.
    """
    jql = f"project = {project}"
    if user:
        jql += f' AND assignee WAS "{user}" DURING ({window.jql_start}, {window.jql_end})'
    return jql + f" AND updated >= {window.jql_start} AND created < {window.jql_end}"


REPORT_FIELDS = ["summary", "created", "updated", "status", "issuetype", "assignee"]


def collect(
    client: JiraClient,
    project: ProjectConfig,
    window: Window,
    jql: str,
    with_completions: bool = True,
) -> list[IssueReport]:
    """Search the issues, read their changelogs in parallel, and build reports."""
    with console.status("Searching issues…"):
        issues = client.search(jql, [*REPORT_FIELDS, project.field_id])
        categories = client.statuses() if with_completions and issues else None
    with Progress(
        SpinnerColumn(),
        TextColumn("Reading changelogs"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("changelogs", total=len(issues))
        logs = client.changelogs(
            [i["key"] for i in issues], on_done=lambda _: progress.advance(task)
        )
    return [
        build_report(
            issue, logs[issue["key"]], project.field_id, project.field_name, window, categories
        )
        for issue in issues
    ]


# ── account ──────────────────────────────────────────────────────────────────


def version_callback(value: bool) -> None:
    """Print the version and exit."""
    if value:
        console.print(f"jira-time-tracker {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Show the version."
        ),
    ] = None,
) -> None:
    """Log in once, pick each project's field with [bold]jtt init[/], then report freely."""
    ctx.call_on_close(close_clients)


@app.command()
@guarded
def login(
    url: Annotated[
        str,
        typer.Option(
            prompt="Jira site URL (e.g. your-team.atlassian.net)", help="Jira Cloud site URL."
        ),
    ],
    email: Annotated[
        str, typer.Option(prompt="Account email", help="The email of the Atlassian account.")
    ],
    token: Annotated[
        str,
        typer.Option(
            prompt="API token (https://id.atlassian.com/manage-profile/security/api-tokens)",
            hide_input=True,
            help="An Atlassian API token. Prompted, hidden, when omitted.",
        ),
    ],
) -> None:
    """Verify an API token against the site and store it securely."""
    config = Config.load()
    if config.site and config.site.logged_in:
        raise fail(
            f"Already logged in as {escape(config.site.email)} on {escape(config.site.url)}. "
            "Run [bold]jtt logout[/] first to change the account or the token."
        )
    url = normalize_url(url)
    host = site_host(url)
    with console.status("Checking the token with Jira…"):
        client = closed_on_exit(JiraClient(url, email.strip(), token.strip()))
        me = client.myself()
        hours_per_day, days_per_week = client.time_tracking_calendar()
    backend = credentials.save_token(host, email.strip(), token.strip())

    site = config.sites.get(host) or SiteConfig(url=url)
    site.url = url
    site.email = email.strip()
    site.account_id = me.get("accountId", "")
    site.display_name = me.get("displayName", "")
    site.time_zone = me.get("timeZone", "")
    site.token_backend = backend
    site.hours_per_day, site.days_per_week = hours_per_day, days_per_week
    config.sites[host] = site
    config.active_site = host
    config.save()

    console.print(
        f"[bold green]✔[/] Logged in to [bold]{escape(host)}[/] "
        f"as [bold]{escape(site.display_name)}[/]"
    )
    console.print(f"  Token stored in: {escape(credentials.describe(backend))}")
    if site.projects:
        console.print(
            f"  {len(site.projects)} project(s) already configured from an earlier login."
        )
    else:
        console.print("  Next: [bold]jtt init[/] to choose the tracked field for your projects.")


@app.command()
@guarded
def logout(
    purge: Annotated[
        bool, typer.Option("--purge", help="Also forget this site's project settings.")
    ] = False,
) -> None:
    """Remove the stored API token (project settings are kept unless --purge)."""
    config = Config.load()
    site = config.site
    if site is None or not site.logged_in:
        raise fail("Not logged in.")
    host = site_host(site.url)
    credentials.delete_token(host, site.email)
    if purge:
        del config.sites[host]
        config.active_site = None
    else:
        site.email = site.token_backend = ""
    config.save()
    console.print(
        f"[bold green]✔[/] Logged out of {escape(host)}"
        + (" and forgot its settings." if purge else ".")
    )


@app.command()
@guarded
def whoami(
    check: Annotated[
        bool, typer.Option("--check", help="Also verify the token with Jira.")
    ] = False,
) -> None:
    """Show the logged-in account, where the token is kept, and configured projects."""
    config, site = logged_in_site()
    rows = [
        ("Site", escape(site.url)),
        (
            "Account",
            f"{escape(site.display_name)} [dim]<{escape(site.email)}> · {site.account_id}[/]",
        ),
        ("Time zone", f"{site.time_zone or '?'} [dim](periods use the days Jira renders in it)[/]"),
        ("Token", escape(credentials.describe(site.token_backend))),
        ("Work calendar", f"{site.hours_per_day:g} h/day, {site.days_per_week:g} days/week"),
        ("Projects", ", ".join(sorted(site.projects)) or "[dim]none yet — run jtt init[/]"),
        ("Default project", site.default_project or "[dim]none[/]"),
        ("Config", escape(str(config.path))),
    ]
    if check:
        with console.status("Checking the token…"):
            me = open_client(site).myself()
        rows.append(("Token check", f"[green]valid[/] for {escape(me.get('displayName', '?'))}"))
    console.print(render.header("jira-time-tracker", rows))


# ── init and config ──────────────────────────────────────────────────────────


def numeric_fields(all_fields: list[dict]) -> list[dict]:
    """Return the site's number fields, time tracking included."""
    return [f for f in all_fields if (f.get("schema") or {}).get("type") == "number"]


def field_kind(field: dict) -> str:
    """Describe what kind of number field `field` is."""
    if field["id"] in TIME_TRACKING_FIELDS:
        return "time tracking (seconds)"
    return "custom number" if field.get("custom") else "system number"


def candidate_fields(
    client: JiraClient, project: str, numbers: list[dict]
) -> list[tuple[dict, bool]]:
    """Numeric fields, the ones on the project's create screens first."""
    try:
        on_screen = client.project_field_ids(project)
    except JiraError:
        on_screen = set()
    if "timetracking" in on_screen:
        on_screen |= {"timeoriginalestimate", "timeestimate", "timespent"}
    ranked = [(f, f["id"] in on_screen) for f in numbers]
    return sorted(ranked, key=lambda pair: (not pair[1], pair[0].get("name", "").lower()))


def fields_table(
    candidates: list[tuple[dict, bool]], counts: dict[str, int | None] | None = None
) -> Table:
    """Return the numbered table init and fields print."""
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Id", style="dim")
    table.add_column("Kind", style="dim")
    table.add_column("On create screen", justify="center")
    if counts is not None:
        table.add_column("Issues with a value", justify="right")
    for index, (field, on_screen) in enumerate(candidates, 1):
        row = [
            str(index),
            field.get("name", "?"),
            field["id"],
            field_kind(field),
            "[green]★[/]" if on_screen else "",
        ]
        if counts is not None:
            count = counts.get(field["id"])
            row.append("" if count is None else str(count))
        table.add_row(*row)
    return table


def ask_unit(field_id: str, field_name: str, previous: ProjectConfig | None) -> tuple[Unit, Unit]:
    """Ask what the field's numbers mean and which unit reports show."""
    time_units = [u.value for u in Unit if u.is_time]
    if field_id in TIME_TRACKING_FIELDS:
        console.print("  This is a Jira time tracking field: its values are [bold]seconds[/].")
        unit = Unit.SECONDS
    else:
        default = (
            previous.unit.value
            if previous
            else ("points" if "point" in field_name.lower() else "hours")
        )
        unit = Unit(
            Prompt.ask(
                "  What do its numbers mean?", choices=[u.value for u in Unit], default=default
            )
        )
    if not unit.is_time:
        return unit, unit
    default_display = (
        previous.display_unit.value
        if previous and previous.display_unit.is_time
        else ("hours" if unit is Unit.SECONDS else unit.value)
    )
    display = Unit(Prompt.ask("  Show amounts in", choices=time_units, default=default_display))
    return unit, display


def field_usage_jql(project: str, field_id: str) -> str:
    """Return JQL for the project's issues holding a value in `field_id`."""
    ref = f"cf[{field_id.split('_', 1)[1]}]" if field_id.startswith("customfield_") else field_id
    return f"project = {project} AND {ref} is not EMPTY"


@app.command()
@guarded
def init(
    projects: Annotated[
        list[str] | None,
        typer.Option(
            "--project",
            "-p",
            help="Only these projects (repeatable). Default: every project you can see.",
        ),
    ] = None,
    field: Annotated[
        str | None,
        typer.Option("--field", help="Field id to use without asking, e.g. customfield_10016."),
    ] = None,
    unit: Annotated[
        Unit | None, typer.Option("--unit", help="What the field's numbers mean (with --field).")
    ] = None,
    display_unit: Annotated[
        Unit | None, typer.Option("--display-unit", help="Time unit reports use (with --field).")
    ] = None,
    reconfigure: Annotated[
        bool, typer.Option("--reconfigure", help="Also revisit projects already configured.")
    ] = False,
) -> None:
    """Choose, per project, which field holds the estimate (story points, hours…) and its unit."""
    config, site = logged_in_site()
    client = open_client(site)
    with console.status("Loading projects and fields…"):
        visible = client.projects()
        numbers = numeric_fields(client.fields())
    wanted = {p.upper() for p in projects or []}
    missing = wanted - {p["key"] for p in visible}
    if missing:
        raise fail(f"Not visible to your account: {', '.join(sorted(missing))}")
    todo = [
        p
        for p in visible
        if (not wanted or p["key"] in wanted)
        and (reconfigure or wanted or p["key"] not in site.projects)
    ]
    if not todo:
        console.print(
            "[green]✔[/] Every project you can see is configured. "
            "Use [bold]--reconfigure[/] or [bold]-p KEY[/] to change one."
        )
        return
    if field and not any(f["id"] == field for f in numbers):
        raise fail(f"{field} is not a numeric field on this site. See [bold]jtt fields[/].")

    last_choice: str | None = None
    for index, project in enumerate(todo, 1):
        key = project["key"]
        console.rule(
            f"[bold]{escape(key)}[/] · {escape(project.get('name', ''))} "
            f"[dim]({index}/{len(todo)})[/]"
        )
        with console.status(f"Reading {key}'s create screens…"):
            candidates = candidate_fields(client, key, numbers)
        previous = site.projects.get(key)

        if field:
            chosen = next(f for f, _ in candidates if f["id"] == field)
            chosen_unit = Unit.SECONDS if field in TIME_TRACKING_FIELDS else (unit or Unit.POINTS)
            chosen_display = (
                display_unit
                if (display_unit and chosen_unit.is_time and display_unit.is_time)
                else (Unit.HOURS if chosen_unit is Unit.SECONDS else chosen_unit)
            )
        else:
            console.print(render_fields_hint())
            console.print(fields_table(candidates))
            ids = [f["id"] for f, _ in candidates]
            preferred = previous.field_id if previous else last_choice
            default = str(ids.index(preferred) + 1) if preferred in ids else None
            answer = (
                (
                    Prompt.ask(
                        "  Field number, [bold]s[/] to skip, [bold]q[/] to stop",
                        default=default,
                        show_default=default is not None,
                    )
                    or ""
                )
                .strip()
                .lower()
            )
            if answer == "q":
                break
            if answer in ("s", ""):
                console.print("  [dim]Skipped.[/]")
                continue
            if not answer.isdigit() or not 1 <= int(answer) <= len(candidates):
                console.print("  [red]Not a field number; skipped.[/]")
                continue
            chosen = candidates[int(answer) - 1][0]
            chosen_unit, chosen_display = ask_unit(chosen["id"], chosen.get("name", ""), previous)

        site.projects[key] = ProjectConfig(
            chosen["id"], chosen.get("name", chosen["id"]), chosen_unit, chosen_display
        )
        site.default_project = site.default_project or key
        last_choice = chosen["id"]
        config.save()
        console.print(
            f"  [green]✔[/] {escape(key)} tracks [bold]{escape(chosen.get('name', ''))}[/] "
            f"in {chosen_unit.value}"
            + (f", shown in {chosen_display.value}" if chosen_display is not chosen_unit else "")
        )
    console.print(
        f"\nConfigured: {', '.join(sorted(site.projects)) or 'none'} "
        f"· default project: {site.default_project or 'none'}"
    )


def render_fields_hint() -> str:
    """Return the legend printed above a fields table."""
    return (
        "  [dim]Numeric fields on this site; "
        "[green]★[/] = on one of the project's create screens.[/]"
    )


@app.command()
@guarded
def fields(
    project: ProjectOpt = None,
    counts: Annotated[
        bool,
        typer.Option(
            "--counts", help="Count issues holding a value, for fields on the create screens."
        ),
    ] = False,
) -> None:
    """List the numeric fields a project can track."""
    _, site = logged_in_site()
    client = open_client(site)
    key = (project or site.default_project or "").upper()
    if not key:
        raise fail("Pass [bold]-p KEY[/].")
    with console.status("Loading fields…"):
        candidates = candidate_fields(client, key, numeric_fields(client.fields()))
        usage = (
            {
                f["id"]: client.approximate_count(field_usage_jql(key, f["id"]))
                for f, on_screen in candidates
                if on_screen
            }
            if counts
            else None
        )
    console.print(render_fields_hint())
    console.print(fields_table(candidates, usage))
    if key in site.projects:
        console.print(
            f"  Tracked now: [bold]{escape(site.projects[key].field_name)}[/] "
            f"({site.projects[key].field_id})"
        )


@config_app.command("show")
@guarded
def config_show() -> None:
    """Print the configuration (never the token)."""
    config, site = logged_in_site()
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    for column in ("Project", "Field", "Id", "Unit", "Shown in", "Default"):
        table.add_column(column)
    for key, project in sorted(site.projects.items()):
        table.add_row(
            key,
            project.field_name,
            project.field_id,
            project.unit.value,
            project.display_unit.value,
            "★" if key == site.default_project else "",
        )
    console.print(
        render.header(
            f"{site_host(site.url)}",
            [
                ("Config file", escape(str(config.path))),
                ("Token", escape(credentials.describe(site.token_backend))),
                (
                    "Work calendar",
                    f"{site.hours_per_day:g} h/day, {site.days_per_week:g} days/week",
                ),
            ],
        )
    )
    console.print(table if site.projects else "[dim]No projects configured. Run jtt init.[/]")


@config_app.command("path")
def config_path() -> None:
    """Print where the configuration file lives."""
    console.print(str(Config().path))


@config_app.command("default")
@guarded
def config_default(project: Annotated[str, typer.Argument(help="Project key.")]) -> None:
    """Set the project used when -p is omitted."""
    config, site = logged_in_site()
    key, _ = project_config(site, project)
    site.default_project = key
    config.save()
    console.print(f"[green]✔[/] Default project: {key}")


@config_app.command("set")
@guarded
def config_set(
    project: Annotated[str, typer.Argument(help="Project key.")],
    field: Annotated[str | None, typer.Option("--field", help="Field id.")] = None,
    unit: Annotated[
        Unit | None, typer.Option("--unit", help="What the field's numbers mean.")
    ] = None,
    display_unit: Annotated[
        Unit | None, typer.Option("--display-unit", help="Time unit reports use.")
    ] = None,
) -> None:
    """Change a project's tracked field or units without the interactive init."""
    config, site = logged_in_site()
    key = project.upper()
    current = site.projects.get(key)
    if field is None and current is None:
        raise fail(f"{key} is not configured; pass --field (see jtt fields -p {key}).")
    field_id, field_name = (current.field_id, current.field_name) if current else ("", "")
    if field:
        with console.status("Checking the field…"):
            match = next(
                (f for f in numeric_fields(open_client(site).fields()) if f["id"] == field), None
            )
        if match is None:
            raise fail(f"{field} is not a numeric field on this site.")
        field_id, field_name = match["id"], match.get("name", match["id"])
    new_unit = (
        Unit.SECONDS
        if field_id in TIME_TRACKING_FIELDS
        else (unit or (current.unit if current else Unit.POINTS))
    )
    new_display = display_unit or (
        current.display_unit if current else (Unit.HOURS if new_unit is Unit.SECONDS else new_unit)
    )
    if not (new_unit.is_time and new_display.is_time):
        new_display = new_unit
    site.projects[key] = ProjectConfig(field_id, field_name, new_unit, new_display)
    site.default_project = site.default_project or key
    config.save()
    console.print(
        f"[green]✔[/] {key}: {escape(field_name)} ({field_id}) in {new_unit.value}, "
        f"shown in {new_display.value}"
    )


@config_app.command("remove")
@guarded
def config_remove(project: Annotated[str, typer.Argument(help="Project key.")]) -> None:
    """Forget a project's settings."""
    config, site = logged_in_site()
    key, _ = project_config(site, project)
    del site.projects[key]
    if site.default_project == key:
        site.default_project = next(iter(sorted(site.projects)), None)
    config.save()
    console.print(f"[green]✔[/] Removed {key}.")


@config_app.command("calendar")
@guarded
def config_calendar(
    hours_per_day: Annotated[float | None, typer.Option("--hours-per-day", min=0.5, max=24)] = None,
    days_per_week: Annotated[float | None, typer.Option("--days-per-week", min=0.5, max=7)] = None,
) -> None:
    """Override the working day and week used to convert hours ↔ days ↔ weeks."""
    config, site = logged_in_site()
    if hours_per_day:
        site.hours_per_day = hours_per_day
    if days_per_week:
        site.days_per_week = days_per_week
    config.save()
    console.print(f"[green]✔[/] {site.hours_per_day:g} h/day, {site.days_per_week:g} days/week")


# ── reading ──────────────────────────────────────────────────────────────────


@app.command("projects")
@guarded
def list_projects(
    configured: Annotated[
        bool, typer.Option("--configured", help="Only projects with a tracked field (no network).")
    ] = False,
) -> None:
    """List the projects you can see and what each one tracks."""
    _, site = logged_in_site()
    if configured:
        visible = [{"key": key, "name": ""} for key in sorted(site.projects)]
    else:
        with console.status("Loading projects…"):
            visible = open_client(site).projects()
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    for column in ("Key", "Name", "Tracked field", "Unit", ""):
        table.add_column(column)
    for p in visible:
        tracked = site.projects.get(p["key"])
        table.add_row(
            f"[bold]{p['key']}[/]",
            escape(p.get("name", "")),
            escape(tracked.field_name) if tracked else "[dim]not configured[/]",
            (
                tracked.unit.value
                + (
                    f" → {tracked.display_unit.value}"
                    if tracked.display_unit is not tracked.unit
                    else ""
                )
            )
            if tracked
            else "",
            "default" if p["key"] == site.default_project else "",
        )
    console.print(table)


@app.command()
@guarded
def fetch(
    project: ProjectOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    period: PeriodOpt = None,
    user: UserOpt = None,
    as_unit: AsOpt = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print raw JSON instead of a table.")
    ] = False,
) -> None:
    """List the issues touched in a period with their current tracked value (no changelog walk)."""
    _, site = logged_in_site()
    key, tracked = project_config(site, project)
    window = resolve_window(date_from, date_to, period)
    client = open_client(site)
    account = resolve_user(client, site, key, user) if user else None
    jql = build_jql(key, window, account[0] if account else None)
    with console.status("Searching issues…"):
        issues = client.search(jql, [*REPORT_FIELDS, tracked.field_id])
    if as_json:
        print(json.dumps({"jql": jql, "issues": issues}, indent=2, ensure_ascii=False))
        return
    amounts = Amounts.for_project(tracked, site.calendar, as_unit)
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
    columns: list[tuple[str, dict[str, Any]]] = [
        ("Issue", {"style": "bold", "no_wrap": True}),
        (tracked.field_name, {"justify": "right", "no_wrap": True}),
        ("Status", {"no_wrap": True}),
        ("Assignee", {"no_wrap": True}),
        ("Updated", {"style": "dim", "no_wrap": True}),
        ("Summary", {"ratio": 1, "no_wrap": True, "overflow": "ellipsis"}),
    ]
    for column, kwargs in columns:
        table.add_column(column, **kwargs)
    total = 0.0
    for issue in sorted(issues, key=lambda i: i["key"]):
        f = issue["fields"]
        value = float(f.get(tracked.field_id) or 0)
        total += value
        status = f.get("status") or {}
        color = render.STATUS_COLORS.get((status.get("statusCategory") or {}).get("key", ""), "")
        table.add_row(
            issue["key"],
            amounts.plain(value) if value else "[dim]—[/]",
            f"[{color}]{escape(status.get('name', ''))}[/]",
            escape((f.get("assignee") or {}).get("displayName", "Unassigned")),
            (f.get("updated") or "")[:16].replace("T", " "),
            escape(f.get("summary", "")),
        )
    console.print(
        render.header(
            f"Issues touched · {key}",
            [
                ("Period", render.period_line(window)),
                (
                    "Assignee",
                    escape(account[1]) + " [dim](held it at some point in the period)[/]"
                    if account
                    else "[dim]anyone[/]",
                ),
                ("Found", f"{len(issues)} issues, {amounts.plain(total)} tracked now"),
            ],
        )
    )
    console.print(table)


@app.command()
@guarded
def calculate(
    project: ProjectOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    period: PeriodOpt = None,
    user: UserOpt = None,
    attribution: Annotated[
        Attribution,
        typer.Option(
            "--attribution",
            help="With --user: 'was' credits every in-period change on issues they held "
            "at some point; 'holder' only the changes made while they held the issue.",
        ),
    ] = Attribution.was,
    as_unit: AsOpt = None,
    workers: WorkersOpt = 8,
    verbose: VerboseOpt = 0,
    vv: VvOpt = False,
    vvv: VvvOpt = False,
) -> None:
    """Net amount that came into being in a period, per issue (whole project, or one person)."""
    level = verbosity(verbose, vv, vvv)
    started = time.monotonic()
    _, site = logged_in_site()
    key, tracked = project_config(site, project)
    window = resolve_window(date_from, date_to, period)
    client = open_client(site, level, workers)
    account = resolve_user(client, site, key, user) if user else None
    amounts = Amounts.for_project(tracked, site.calendar, as_unit)
    jql = build_jql(key, window, account[0] if account else None)

    rows = [
        ("Project", key),
        ("Field", render.field_line(tracked, amounts)),
        ("Period", render.period_line(window)),
    ]
    if account:
        how = (
            "held the issue at some point in the period"
            if attribution is Attribution.was
            else "only changes made while holding the issue"
        )
        rows.insert(1, ("Assignee", f"{escape(account[1])} [dim]({how})[/]"))
    if level:
        rows.append(("Verbosity", f"-{'v' * level}"))
    console.print(render.header("Tracked amount delta", rows))
    if level >= 3:
        console.print(Panel(escape(jql), title="JQL", title_align="left", border_style="dim"))

    reports = collect(client, tracked, window, jql)
    if account and attribution is Attribution.holder:
        deltas = {r.key: r.delta_for(account[0]) for r in reports}
    else:
        deltas = {r.key: r.delta for r in reports}

    if any(deltas.values()) or (level >= 2 and reports):
        console.print(
            render.issues_table(reports, amounts, level, deltas, account[0] if account else None)
        )
    else:
        console.print(
            f"\n  [dim]Nothing changed in the period across {len(reports)} scanned issues.[/]\n"
        )
    if level >= 2 and any(r.changes or r.created_with is not None for r in reports):
        console.print(render.timelines(reports, amounts, level))
        console.print()
    console.print(render.totals(reports, deltas, amounts, level, time.monotonic() - started))


@app.command()
@guarded
def collaborators(
    project: ProjectOpt = None,
    since: Annotated[
        int, typer.Option("--since", min=1, help="Count issues updated in the last N days.")
    ] = 90,
) -> None:
    """List the people who can be assigned in a project, with their current issue load."""
    _, site = logged_in_site()
    key = (project or site.default_project or "").upper()
    if not key:
        raise fail("Pass [bold]-p KEY[/].")
    client = open_client(site)
    with console.status("Loading collaborators…"):
        users = client.assignable_users(key)
        issues = client.search(
            f"project = {key} AND assignee is not EMPTY AND updated >= -{since}d",
            ["assignee", "status"],
        )
    counts: dict[str, dict[str, int]] = {}
    for issue in issues:
        f = issue["fields"]
        account_id = (f.get("assignee") or {}).get("accountId", "")
        category = ((f.get("status") or {}).get("statusCategory") or {}).get("key", "")
        counts.setdefault(account_id, {}).setdefault(category, 0)
        counts[account_id][category] += 1
    users.sort(
        key=lambda u: (
            -sum(counts.get(u["accountId"], {}).values()),
            u.get("displayName", "").lower(),
        )
    )
    console.print(
        render.header(
            f"Collaborators · {key}",
            [
                ("People", f"{len(users)} assignable"),
                (
                    "Load",
                    f"issues assigned to each, updated in the last {since} days, "
                    "by status category",
                ),
            ],
        )
    )
    console.print(render.collaborators_table(users, counts, site.account_id))


@app.command("contributions")
@guarded
def contributions_command(
    project: ProjectOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    period: PeriodOpt = None,
    user: UserOpt = None,
    group_by: Annotated[
        GroupBy, typer.Option("--by", help="Add a breakdown of the net per day or week.")
    ] = GroupBy.none,
    as_unit: AsOpt = None,
    workers: WorkersOpt = 8,
    verbose: VerboseOpt = 0,
    vv: VvOpt = False,
    vvv: VvvOpt = False,
) -> None:
    """Per-person contributions and statistics for a period.

    Each in-period change is credited to whoever held the issue when it
    happened, and an issue's created-with amount to the first person assigned,
    so the per-person nets add up to the project net.
    """
    level = verbosity(verbose, vv, vvv)
    started = time.monotonic()
    _, site = logged_in_site()
    key, tracked = project_config(site, project)
    window = resolve_window(date_from, date_to, period)
    client = open_client(site, level, workers)
    account = resolve_user(client, site, key, user) if user else None
    amounts = Amounts.for_project(tracked, site.calendar, as_unit)
    jql = build_jql(key, window)

    console.print(
        render.header(
            f"Contributions · {key}",
            [
                ("Field", render.field_line(tracked, amounts)),
                ("Period", render.period_line(window)),
                ("Credit", "[dim]each change goes to whoever held the issue when it happened[/]"),
            ],
        )
    )
    if level >= 3:
        console.print(Panel(escape(jql), title="JQL", title_align="left", border_style="dim"))
    reports = collect(client, tracked, window, jql)
    people = contributions(reports)
    if account:
        people = [p for p in people if p.account_id == account[0]]
    daily = daily_net(reports, window, account[0] if account else None)

    if people:
        console.print(render.contributions_table(people, amounts))
    else:
        console.print("\n  [dim]No contributions in the period.[/]\n")
    if group_by is GroupBy.day:
        console.print(render.series_table("Per day", daily, amounts, "%a %d %b"))
    elif group_by is GroupBy.week:
        console.print(
            render.series_table("Per week (from Monday)", by_week(daily), amounts, "wk of %d %b")
        )
    if level >= 1 and reports:
        shown = [r for r in reports if (r.delta_for(account[0]) if account else r.delta)]
        deltas = {r.key: (r.delta_for(account[0]) if account else r.delta) for r in reports}
        if shown or level >= 2:
            console.print(render.issues_table(reports, amounts, level, deltas))
    if level >= 2:
        console.print(render.timelines(reports, amounts, level))
    console.print(render.stats_panel(reports, people, daily, amounts))
    if level >= 1:
        console.print(
            f"[dim]Took {time.monotonic() - started:.1f} s · {len(reports)} issues scanned[/]"
        )


@app.command("export")
@guarded
def export_command(
    output: Annotated[
        Path, typer.Option("--output", "-o", help="File to write; the extension picks the format.")
    ],
    kind: Annotated[
        ExportKind, typer.Option("--kind", "-k", help="What each row is.")
    ] = ExportKind.issues,
    fmt: Annotated[
        ExportFormat | None, typer.Option("--format", "-f", help="Override the format.")
    ] = None,
    project: ProjectOpt = None,
    date_from: FromOpt = None,
    date_to: ToOpt = None,
    period: PeriodOpt = None,
    user: UserOpt = None,
    attribution: Annotated[
        Attribution, typer.Option("--attribution", help="As in calculate.")
    ] = Attribution.was,
    as_unit: AsOpt = None,
    workers: WorkersOpt = 8,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write issues, changes, per-person contributions or a daily series to a file.

    CSV, JSON or Markdown, from --format or the file extension.
    """
    file_format = exporter.infer_format(output, fmt.value if fmt else None)
    if output.exists() and not force:
        raise fail(f"{output} exists; pass --force to overwrite.")
    _, site = logged_in_site()
    key, tracked = project_config(site, project)
    window = resolve_window(date_from, date_to, period)
    client = open_client(site, 0, workers)
    account = resolve_user(client, site, key, user) if user else None
    amounts = Amounts.for_project(tracked, site.calendar, as_unit)
    # Per-person views credit by holder over the whole project;
    # issue views follow --user/--attribution.
    per_person = kind in (ExportKind.contributions, ExportKind.daily)
    jql = build_jql(key, window, None if per_person or not account else account[0])
    reports = collect(client, tracked, window, jql)

    if kind is ExportKind.issues:
        deltas = {
            r.key: r.delta_for(account[0])
            if account and attribution is Attribution.holder
            else r.delta
            for r in reports
        }
        rows = exporter.issue_rows(reports, amounts, deltas)
    elif kind is ExportKind.changes:
        rows = exporter.change_rows(reports, amounts)
        if account and attribution is Attribution.holder:
            rows = [row for row in rows if row["holder_id"] == account[0]]
    elif kind is ExportKind.contributions:
        people = contributions(reports)
        rows = exporter.contribution_rows(
            [p for p in people if not account or p.account_id == account[0]], amounts
        )
    else:
        rows = exporter.daily_rows(
            daily_net(reports, window, account[0] if account else None), amounts
        )

    meta = {
        "title": f"{key} · {kind.value} · {window.date_from} → {window.date_to}",
        "project": key,
        "field": f"{tracked.field_name} ({tracked.field_id})",
        "unit": amounts.target.value,
        "period_from_included": window.date_from.isoformat(),
        "period_to_excluded": window.date_to.isoformat(),
        "user": account[1] if account else "",
        "jql": jql,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    exporter.write(output, file_format, rows, meta)
    console.print(
        f"[bold green]✔[/] Wrote {len(rows)} {kind.value} rows "
        f"to [bold]{escape(str(output))}[/] ({file_format})"
    )


if __name__ == "__main__":
    app()
