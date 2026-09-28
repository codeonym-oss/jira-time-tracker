"""Every command, run by the real CLI against the simulated Jira site (tests/jira_sim).

The simulator generated the data and knows the answers: the reports are checked against
`jira_sim.truth`, which reads the generator's own events rather than the changelog jtt reads.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date

import pytest
from typer.testing import CliRunner

from jira_time_tracker.cli import app
from jira_time_tracker.config import Config, SiteConfig, config_dir
from tests import jira_sim

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
