"""Every command, run by the real CLI against the simulated Jira site (tests/jira_sim).

The simulator generated the data and knows the answers: the reports are checked against
`jira_sim.truth`, which reads the generator's own events rather than the changelog jtt reads.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from jira_time_tracker.cli import app
from jira_time_tracker.config import Config, SiteConfig, config_dir
from tests import jira_sim
from tests.jira_sim.data import ISSUE_TYPES, Event, Issue

runner = CliRunner()
SITE = jira_sim.generate()
WEEK = ("2026-09-21", "2026-09-28")
# Tracked field and the factor from its raw numbers to what reports show.
PROJECTS = {
    "DEMO": ("customfield_10016", ["--unit", "points"], 1.0),
    "WEB": ("customfield_10028", ["--unit", "points"], 1.0),
    "OPS": ("timeoriginalestimate", ["--display-unit", "hours"], 1 / 3600),
    "DATA": ("customfield_10041", ["--unit", "days"], 1.0),
}


def jtt(*args: str, input: str | None = None):
    result = runner.invoke(app, list(args), input=input)
    return result, result.output


def ok(*args: str, input: str | None = None) -> str:
    result, out = jtt(*args, input=input)
    assert result.exit_code == 0, out
    return out


def period(first: str, end: str) -> list[str]:
    return ["--from", first, "--to", end]


def saved_site() -> SiteConfig:
    site = Config.load().site
    assert site is not None
    return site


def export(tmp_path, kind: str, *args: str) -> list[dict]:
    target = tmp_path / f"{kind}.json"
    ok("export", "-o", str(target), "-k", kind, "--force", *args)
    return json.loads(target.read_text(encoding="utf-8"))["rows"]


@pytest.fixture
def logged_in(sim):
    ok("login", "--url", sim.url, "--email", jira_sim.EMAIL, "--token", jira_sim.TOKEN)
    return sim


@pytest.fixture
def configured(logged_in):
    for key, (field_id, units, _) in PROJECTS.items():
        ok("init", "-p", key, "--field", field_id, *units)
    ok("config", "default", "DEMO")
    return logged_in


# ── account ──────────────────────────────────────────────────────────────────


def test_login_prompts_and_checks_the_token(sim):
    out = ok("login", input=f"{sim.url}\n{jira_sim.EMAIL}\n{jira_sim.TOKEN}\n")
    assert "Logged in to 127.0.0.1" in out
    assert "as Robin Hale" in out
    assert jira_sim.TOKEN not in out
    assert saved_site().time_zone == "Africa/Casablanca"


def test_login_rejects_a_wrong_token(sim):
    result, out = jtt("login", "--url", sim.url, "--email", jira_sim.EMAIL, "--token", "nope")
    assert result.exit_code == 1
    assert "rejected the credentials (401)" in out
    assert Config.load().site is None


def test_logout_keeps_the_projects_and_purge_forgets_them(configured):
    assert "Logged out of 127.0.0.1" in ok("logout")
    assert not (config_dir() / "credentials.json").exists()
    assert set(saved_site().projects) == set(PROJECTS)
    ok("login", "--url", configured.url, "--email", jira_sim.EMAIL, "--token", jira_sim.TOKEN)
    assert "forgot its settings" in ok("logout", "--purge")
    assert Config.load().sites == {}


def test_whoami_shows_the_account_and_checks_the_token(configured):
    out = ok("whoami", "--check")
    assert "Robin Hale" in out
    assert jira_sim.EMAIL in out
    assert "DATA, DEMO, OPS, WEB" in out
    assert "valid for Robin Hale" in out


# ── init and config ──────────────────────────────────────────────────────────


def test_init_asks_per_project_and_ranks_create_screen_fields_first(logged_in):
    # Projects come by key. DATA: skip. DEMO: field 1 (its create screen's only number),
    # points. OPS and WEB: stop.
    out = ok("init", input="s\n1\npoints\nq\n")
    assert out.index("DATA · Analytics (1/4)") < out.index("DEMO · Demo App (2/4)")
    assert "★" in out
    assert list(saved_site().projects) == ["DEMO"]
    assert saved_site().projects["DEMO"].field_id == "customfield_10016"


def test_init_with_a_time_tracking_field_asks_only_the_display_unit(logged_in):
    # OPS's create screen holds three time tracking fields; Original estimate sorts first.
    out = ok("init", "-p", "OPS", input="1\ndays\n")
    assert "values are seconds" in out
    ops = saved_site().projects["OPS"]
    assert (ops.field_id, ops.unit.value, ops.display_unit.value) == (
        "timeoriginalestimate",
        "seconds",
        "days",
    )


def test_init_reconfigure_revisits_configured_projects(configured):
    assert "Every project you can see is configured" in ok("init")
    ok("init", "--reconfigure", "-p", "WEB", "--field", "customfield_10041", "--unit", "days")
    assert saved_site().projects["WEB"].field_name == "Effort (days)"


def test_config_show_path_and_default(configured):
    out = ok("config", "show")
    for key in PROJECTS:
        assert key in out
    assert "8 h/day, 5 days/week" in out
    assert ok("config", "path").strip().endswith("config.json")
    assert "Default project: OPS" in ok("config", "default", "ops")
    assert saved_site().default_project == "OPS"


def test_config_set_changes_units_without_init(configured):
    out = ok("config", "set", "OPS", "--display-unit", "days")
    assert "OPS: Original estimate (timeoriginalestimate) in seconds, shown in days" in out
    result, out = jtt("config", "set", "NEW")
    assert result.exit_code == 1
    assert "pass --field" in out


def test_config_remove_moves_the_default(configured):
    assert "Removed DEMO" in ok("config", "remove", "DEMO")
    assert "DEMO" not in saved_site().projects
    assert saved_site().default_project == "DATA"


def test_config_calendar_changes_time_conversions(configured):
    assert "7.5 h/day, 4 days/week" in ok(
        "config", "calendar", "--hours-per-day", "7.5", "--days-per-week", "4"
    )
    out = ok("calculate", "-p", "OPS", *period(*WEEK), "--as", "days")
    net = sum(jira_sim.truth(SITE, "OPS", *map(date.fromisoformat, WEEK)).per_issue.values())
    assert f"+{round(net / 3600 / 7.5, 2):g}d" in out


# ── projects and fields ──────────────────────────────────────────────────────


def test_projects_lists_every_project_and_what_it_tracks(configured):
    out = ok("projects")
    for spec in SITE.projects:
        assert re.search(rf"{spec.key}\s+{spec.name}", out)
    assert re.search(r"OPS .* seconds → hours", out)
    configured_only = ok("projects", "--configured")
    assert "Analytics" not in configured_only  # no network: names are not known
    assert "DATA" in configured_only


def test_fields_counts_the_issues_holding_a_value(configured):
    out = ok("fields", "-p", "DATA", "--counts")
    holding = sum(1 for i in SITE.issues if i.project.key == "DATA" and i.estimate is not None)
    assert re.search(rf"Effort \(days\).*★\s+{holding}\b", out)
    assert "Tracked now: Effort (days) (customfield_10041)" in out


# ── reports: checked against the generator's own answers ─────────────────────

PERIODS = [
    WEEK,
    ("2026-09-01", "2026-10-01"),
    ("2026-09-25", "2026-09-26"),
    ("2026-06-01", "2026-09-29"),
]


@pytest.fixture(scope="module")
def truths():
    return {
        (key, first, end): jira_sim.truth(
            SITE, key, date.fromisoformat(first), date.fromisoformat(end)
        )
        for key in PROJECTS
        for first, end in PERIODS
    }


@pytest.mark.parametrize("key", PROJECTS)
@pytest.mark.parametrize(("first", "end"), PERIODS)
def test_reports_match_what_the_generator_made(configured, tmp_path, truths, key, first, end):
    truth = truths[key, first, end]
    factor = PROJECTS[key][2]
    args = ["-p", key, *period(first, end)]

    issues = export(tmp_path, "issues", *args)
    assert {r["key"] for r in issues} == truth.touched
    got = {r["key"]: r["delta"] for r in issues if r["delta"]}
    assert got == pytest.approx({k: v * factor for k, v in truth.per_issue.items() if v})

    people = export(tmp_path, "contributions", *args)
    got = {r["person"]: r["net"] for r in people if r["net"]}
    assert got == pytest.approx({k: v * factor for k, v in truth.per_person.items() if v})

    assert len(export(tmp_path, "changes", *args)) == truth.changes
    daily = {r["day"]: r["net"] for r in export(tmp_path, "daily", *args) if r["net"]}
    want = {d.isoformat(): v * factor for d, v in truth.per_day.items() if round(v, 9)}
    assert daily == pytest.approx(want)


def test_exclude_parents_counts_only_issues_without_children(configured, tmp_path):
    first, end = PERIODS[1]
    span = (date.fromisoformat(first), date.fromisoformat(end))
    every, leaves = (
        jira_sim.truth(SITE, "DEMO", *span),
        jira_sim.truth(SITE, "DEMO", *span, exclude_parents=True),
    )
    parents = every.touched - leaves.touched
    assert parents
    assert parents <= SITE.parents

    rows = export(tmp_path, "issues", *period(first, end))
    assert {r["key"] for r in rows} == every.touched
    rows = export(tmp_path, "issues", *period(first, end), "--exclude-parents")
    assert {r["key"] for r in rows} == leaves.touched
    got = {r["key"]: r["delta"] for r in rows if r["delta"]}
    assert got == pytest.approx({k: v for k, v in leaves.per_issue.items() if v})
    people = export(tmp_path, "contributions", *period(first, end), "--exclude-parents")
    got = {r["person"]: r["net"] for r in people if r["net"]}
    assert got == pytest.approx({k: v for k, v in leaves.per_person.items() if v})

    data = json.loads(ok("fetch", *period(first, end), "--json", "--exclude-parents"))
    assert {i["key"] for i in data["issues"]} == leaves.touched


def test_fetch_lists_the_touched_issues(configured):
    first, end = WEEK
    data = json.loads(ok("fetch", *period(first, end), "--json"))
    truth = jira_sim.truth(SITE, "DEMO", date.fromisoformat(first), date.fromisoformat(end))
    assert {i["key"] for i in data["issues"]} == truth.touched
    out = ok("fetch", "-p", "OPS", *period(first, end))
    assert (
        f"Found  {len(jira_sim.truth(SITE, 'OPS', *map(date.fromisoformat, WEEK)).touched)} issues"
        in out
    )


def test_calculate_shows_the_net_and_every_changed_issue(configured):
    truth = jira_sim.truth(SITE, "DEMO", *map(date.fromisoformat, WEEK))
    out = ok("calculate", *period(*WEEK))
    assert f"Net added  +{truth.net:g} SP" in out
    for key, delta in truth.per_issue.items():
        if delta:
            assert re.search(rf"{key}\s+{re.escape(f'{delta:+g}')} SP", out)


@pytest.mark.parametrize("name", ["Daniel Okafor", "Leila Benali"])
def test_calculate_holder_attribution_matches_each_persons_credit(configured, tmp_path, name):
    truth = jira_sim.truth(SITE, "DEMO", *map(date.fromisoformat, WEEK))
    rows = export(
        tmp_path, "issues", *period(*WEEK), "--user", name.split()[1], "--attribution", "holder"
    )
    assert sum(r["delta"] for r in rows) == pytest.approx(truth.per_person.get(name, 0))
    out = ok("calculate", *period(*WEEK), "-u", name.split()[0].lower(), "--attribution", "holder")
    assert f"{name} (only changes made while holding the issue)" in out


@pytest.mark.parametrize("flag", ["-v", "-vv", "-vvv"])
def test_calculate_levels_of_detail(configured, flag):
    out = ok("calculate", *period(*WEEK), flag)
    assert "Assignee now" in out
    assert ("Timeline" in out) is (flag != "-v")
    assert ("HTTP POST 200" in out) is (flag == "-vvv")


def test_calculate_me_and_an_unknown_person(configured):
    assert "Robin Hale (held the issue" in ok("calculate", *period(*WEEK), "--user", "me")
    result, out = jtt("calculate", *period(*WEEK), "--user", "nobody")
    assert result.exit_code == 1
    assert "No collaborator on DEMO matches 'nobody'" in out


def test_collaborators_lists_who_can_be_assigned(configured):
    out = ok("collaborators", "-p", "DEMO")
    members = SITE.members["DEMO"]
    assert f"{len(members)} assignable" in out
    for user in members:
        assert user["displayName"] in out
    assert "Robin Hale (you)" in out
    assert "Jonas Berg" not in out  # left the company: no longer assignable


def test_contributions_by_week_adds_up_to_the_net(configured):
    truth = jira_sim.truth(SITE, "DEMO", date(2026, 9, 1), date(2026, 10, 1))
    out = ok("contributions", *period("2026-09-01", "2026-10-01"), "--by", "week")
    assert "Per week (from Monday)" in out
    assert f"Net added  +{truth.net:g} SP" in out
    for name, net in truth.per_person.items():
        if net:
            assert name in out


@pytest.mark.parametrize("suffix", ["csv", "json", "md"])
def test_export_writes_each_format(configured, tmp_path, suffix):
    target = tmp_path / f"contributions.{suffix}"
    out = ok("export", "-o", str(target), "-k", "contributions", *period(*WEEK))
    assert f"({suffix})" in out
    text = target.read_text(encoding="utf-8-sig")
    if suffix == "csv":
        assert next(csv.reader(text.splitlines()))[:3] == ["person", "account_id", "net"]
    elif suffix == "json":
        assert json.loads(text)["meta"]["project"] == "DEMO"
    else:
        assert text.startswith("# DEMO · contributions · 2026-09-21 → 2026-09-28")
    result, out = jtt("export", "-o", str(target), *period(*WEEK))
    assert result.exit_code == 1
    assert "pass --force" in out


# ── last-holder: every issue credited to one person ──────────────────────────

MONTH = ("2026-09-01", "2026-10-01")
LAST = ("--attribution", "last-holder")
EVERYONE = {u["displayName"]: u["accountId"] for u in SITE.users}


def month_truth(**kwargs) -> jira_sim.Truth:
    return jira_sim.truth(SITE, "DEMO", *map(date.fromisoformat, MONTH), **kwargs)


def shown_net(out: str) -> float:
    """Return the "Net added" of a report's closing panel, in points."""
    found = re.search(r"Net added\s+(±0|[+-]?[\d.]+ SP)", out)
    assert found, out
    return 0.0 if found[1] == "±0" else float(found[1].removesuffix(" SP"))


def shown_people(out: str) -> dict[str, float]:
    """Return the net of each person in a contributions table, in points."""
    rows = re.findall(r"^ *([^\d\n│]+?) +(±0|[+-][\d.]+ SP) ", out.split("Statistics")[0], re.M)
    return {name: 0.0 if net == "±0" else float(net.removesuffix(" SP")) for name, net in rows}


@pytest.mark.parametrize("key", PROJECTS)
@pytest.mark.parametrize(("first", "end"), PERIODS)
def test_last_holder_nets_match_the_generator_and_add_up(
    configured, tmp_path, truths, key, first, end
):
    truth = truths[key, first, end]
    factor = PROJECTS[key][2]
    args = ["-p", key, *period(first, end), *LAST]
    people = export(tmp_path, "contributions", *args)
    got = {r["person"]: r["net"] for r in people if r["net"]}
    assert got == pytest.approx({k: v * factor for k, v in truth.per_last_holder.items() if v})
    assert sum(r["net"] for r in people) == pytest.approx(truth.net * factor)


def test_the_generated_site_exercises_the_last_holder_rule(truths):
    truth = month_truth()
    assert truth.per_last_holder != truth.per_person
    every = [t.per_last_holder for t in truths.values()]
    assert any(nets.get("Unassigned") for nets in every)
    first, end = PERIODS[2]
    first_assigned_later = [
        i.key
        for i in SITE.issues
        if i.key in truths["DEMO", first, end].per_issue
        and i.assignee
        and all(since.date() >= date.fromisoformat(end) for since, who in i.holders() if who)
    ]
    assert first_assigned_later


def test_every_changed_issue_is_credited_to_exactly_one_person(configured, tmp_path):
    truth = month_truth()
    credited: list[str] = []
    for name, account_id in EVERYONE.items():
        rows = export(tmp_path, "issues", *period(*MONTH), "-u", account_id, *LAST)
        keys = [r["key"] for r in rows]
        assert set(keys) == {k for k, who in truth.last_holder.items() if who == name}
        credited += keys
    assert len(credited) == len(set(credited))
    nobodys = {k for k, who in truth.last_holder.items() if who == "Unassigned"}
    assert set(credited) | nobodys == truth.touched
    assert set(truth.per_issue) <= truth.touched


@pytest.mark.parametrize("flags", [[], ["--exclude-parents"]], ids=["all", "exclude-parents"])
def test_last_holder_calculate_is_the_persons_row_in_contributions(configured, flags):
    truth = month_truth(exclude_parents=bool(flags))
    out = ok("contributions", *period(*MONTH), *LAST, *flags)
    assert "goes to the last person assigned before the period ended" in out
    people = shown_people(out)
    assert {k: v for k, v in people.items() if v} == pytest.approx(
        {k: v for k, v in truth.per_last_holder.items() if v}
    )
    for name, account_id in EVERYONE.items():
        out = ok("calculate", *period(*MONTH), "-u", account_id, *LAST, *flags)
        assert f"{name} (last person assigned before the period ended)" in out
        assert shown_net(out) == pytest.approx(people.get(name, 0))
        scanned = sum(1 for who in truth.last_holder.values() if who == name)
        assert f"of {scanned} scanned" in out or f"across {scanned} scanned" in out
    whole = shown_net(ok("calculate", *period(*MONTH), *flags))
    assert sum(people.values()) == pytest.approx(whole)


@pytest.fixture
def handed_over():
    """A site where two people held an issue only outside the period.

    Alice was unassigned from DEMO-901 in August, and Bob assigned to DEMO-902 in October;
    both issues were estimated in September, while nobody was assigned.
    """
    site = jira_sim.generate(now=datetime(2026, 10, 20, 12, 0, tzinfo=jira_sim.NOW.tzinfo))
    site.issues.clear()
    alice, bob = site.user("Alice Martin"), site.user("Bob Jensen")
    site.members["DEMO"] = [site.me, alice, bob]

    def at(month: int, day: int) -> datetime:
        return datetime(2026, month, day, 10, 0, tzinfo=site.now.tzinfo)

    def issue(number: int, created: datetime, holder: dict | None, *events: Event) -> None:
        site.issues.append(
            Issue(
                key=f"DEMO-{number}",
                project=site.project("DEMO"),
                summary=f"Handed over {number}",
                issue_type=ISSUE_TYPES[1],
                created=created,
                created_with=None,
                assignee_at_create=holder,
                events=list(events),
            )
        )

    issue(
        901,
        at(8, 10),
        alice,
        Event(at(8, 20), alice, assignee=(alice, None)),
        Event(at(9, 10), alice, estimate=(None, 3)),
    )
    issue(
        902,
        at(9, 10),
        None,
        Event(at(9, 11), bob, estimate=(None, 5)),
        Event(at(10, 2), bob, assignee=(None, bob)),
    )
    server = jira_sim.start(site)
    ok("login", "--url", server.url, "--email", jira_sim.EMAIL, "--token", jira_sim.TOKEN)
    ok("init", "-p", "DEMO", "--field", "customfield_10016", "--unit", "points")
    yield server
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("who", "mine", "other", "net"), [("alice", 901, 902, 3), ("bob", 902, 901, 5)]
)
def test_last_holder_finds_who_held_the_issue_only_outside_the_period(
    handed_over, who, mine, other, net
):
    args = ["calculate", *period(*MONTH), "--user", who]
    assert "Nothing changed in the period across 0 scanned issues" in ok(*args)
    out = ok(*args, *LAST, "-vv")
    assert shown_net(out) == net
    assert f"DEMO-{mine}" in out
    assert f"DEMO-{other}" not in out
    assert "1 of 1 scanned" in out
    out = ok("contributions", *period(*MONTH), "--user", who, *LAST, "-vv", "--by", "day")
    assert shown_net(out) == net
    assert f"DEMO-{mine}" in out
    assert f"DEMO-{other}" not in out
    assert "1 issues scanned" in out


def test_last_holder_export_matches_the_truth_for_every_kind(configured, tmp_path):
    truth = month_truth()
    name = "Daniel Okafor"
    mine = {k for k, who in truth.last_holder.items() if who == name}
    args = [*period(*MONTH), *LAST]
    one = [*args, "--user", EVERYONE[name]]

    rows = export(tmp_path, "issues", *one)
    assert {r["key"]: r["delta"] for r in rows} == pytest.approx(
        {k: truth.per_issue.get(k, 0) for k in mine}
    )
    rows = export(tmp_path, "changes", *one)
    assert len(rows) == sum(n for k, n in truth.changes_of.items() if k in mine)
    assert {r["key"] for r in rows} == mine & set(truth.changes_of)
    assert sum(r["delta"] for r in rows) == pytest.approx(truth.per_last_holder[name])
    (row,) = export(tmp_path, "contributions", *one)
    assert (row["person"], row["net"]) == (name, pytest.approx(truth.per_last_holder[name]))
    assert row["issues"] == len(mine & set(truth.changes_of))
    rows = export(tmp_path, "daily", *one)
    want = {d.isoformat(): v for (who, d), v in truth.per_last_holder_day.items() if who == name}
    assert {r["day"]: r["net"] for r in rows if r["net"]} == pytest.approx(
        {day: v for day, v in want.items() if v}
    )

    # Without --user: every row, and only the credit of `contributions` changes.
    assert len(export(tmp_path, "issues", *args)) == len(truth.touched)
    assert len(export(tmp_path, "changes", *args)) == truth.changes
    assert sum(r["net"] for r in export(tmp_path, "daily", *args)) == pytest.approx(truth.net)


@pytest.mark.parametrize("mode", ["was", "holder"])
def test_export_per_person_kinds_ignore_the_other_modes(configured, tmp_path, mode):
    truth = month_truth()
    rows = export(tmp_path, "contributions", *period(*MONTH), "--attribution", mode)
    got = {r["person"]: r["net"] for r in rows if r["net"]}
    assert got == pytest.approx({k: v for k, v in truth.per_person.items() if v})


@pytest.mark.parametrize("kind", ["issues", "changes", "contributions", "daily"])
def test_export_says_when_last_holder_decided_the_rows(configured, tmp_path, kind):
    def meta(*args: str) -> dict:
        export(tmp_path, kind, *period(*WEEK), *args)
        return json.loads((tmp_path / f"{kind}.json").read_text(encoding="utf-8"))["meta"]

    me = ["--user", "me"]
    assert meta(*me, *LAST)["attribution"] == "last-holder"
    for other in ([], me, [*me, "--attribution", "was"], [*me, "--attribution", "holder"]):
        assert "attribution" not in meta(*other)
    # Without --user, the mode has no effect on issues and changes.
    assert ("attribution" in meta(*LAST)) is (kind in ("contributions", "daily"))

    target = tmp_path / "report.md"
    ok("export", "-o", str(target), "-k", kind, *period(*WEEK), *me, *LAST)
    assert "- **Attribution:** last-holder\n" in target.read_text(encoding="utf-8")


def test_contributions_by_last_holder_for_one_person(configured):
    truth = month_truth()
    name = "Daniel Okafor"
    mine = {k: v for k, v in truth.per_issue.items() if truth.last_holder[k] == name}
    args = ["contributions", *period(*MONTH), "--user", "daniel", *LAST]
    out = ok(*args, "-v", "--by", "day")
    assert shown_people(out)[name] == pytest.approx(truth.per_last_holder[name])
    assert shown_net(out) == pytest.approx(truth.per_last_holder[name])
    keys = set(re.findall(r"^\s*(DEMO-\d+)\s", out, re.M))
    assert keys == {k for k, v in mine.items() if v}
    assert f"average over {len(keys)}" in out
    for (who, day), net in truth.per_last_holder_day.items():
        if who == name and net:
            assert re.search(rf"{day:%a %d %b}\s+{re.escape(f'{net:+g}')} SP", out)


def test_contributions_rejects_was_and_defaults_to_holder(configured):
    result, out = jtt("contributions", *period(*MONTH), "--attribution", "was")
    assert result.exit_code == 2
    assert "'was' is not one of 'holder', 'last-holder'" in out
    default = ok("contributions", *period(*MONTH))
    assert "each change goes to whoever held the issue when it happened" in default
    assert ok("contributions", *period(*MONTH), "--attribution", "holder") == default


def test_calculate_notes_that_was_counts_a_handover_for_each_person(configured):
    note = "an issue that changed hands counts for each person who held it"
    args = ["calculate", *period(*WEEK)]
    out = ok(*args, "--user", "me")
    assert note in out
    assert "--attribution last-holder" in out
    for other in ([], ["--user", "me", "--attribution", "holder"], ["--user", "me", *LAST]):
        assert note not in ok(*args, *other)


def test_attribution_has_no_effect_on_calculate_without_user(configured):
    def report(*args: str) -> str:
        out = ok("calculate", *period(*WEEK), "-vv", *args)
        return re.sub(r"Took.*", "", out)

    assert report(*LAST) == report()


@pytest.mark.parametrize(("extra", "credited"), [([], "Alice Martin"), (LAST, "Bob Jensen")])
def test_timelines_say_who_the_created_with_amount_is_credited_to(handed_over, extra, credited):
    # Alice typed 8 when creating DEMO-903, then handed it to Bob.
    site = handed_over.site
    alice, bob = site.user("Alice Martin"), site.user("Bob Jensen")
    created = datetime(2026, 9, 14, 10, 0, tzinfo=site.now.tzinfo)
    handover = Event(created + timedelta(minutes=5), alice, assignee=(alice, bob))
    site.issues.append(
        Issue(
            key="DEMO-903",
            project=site.project("DEMO"),
            summary="Handed over 903",
            issue_type=ISSUE_TYPES[1],
            created=created,
            created_with=8,
            assignee_at_create=alice,
            events=[handover],
        )
    )
    out = ok("contributions", *period(*MONTH), "-vv", *extra)
    assert f"credited to {credited}" in out
    if extra:
        assert f"credited to {credited}" in ok(
            "calculate", *period(*MONTH), "-u", "bob", "-vv", *extra
        )
