"""End to end: the real CLI and HTTP client against the fake Jira server."""

from __future__ import annotations

import csv
import json
import os
import stat

import pytest
from typer.testing import CliRunner

from jira_time_tracker.cli import app
from jira_time_tracker.config import Config, SiteConfig, config_dir
from tests import fake_jira

runner = CliRunner()
PERIOD = ["--from", "2026-09-24", "--to", "2026-09-30"]


def jtt(*args: str, input: str | None = None):
    result = runner.invoke(app, list(args), input=input)
    return result, result.output


def saved_site() -> SiteConfig:
    site = Config.load().site
    assert site is not None
    return site


def login(url: str, token: str = fake_jira.TOKEN):
    return jtt("login", "--url", url, "--email", fake_jira.EMAIL, "--token", token)


@pytest.fixture
def ready(jira_url):
    result, out = login(jira_url)
    assert result.exit_code == 0, out
    result, out = jtt("init", "-p", "DEMO", "--field", "customfield_10016", "--unit", "points")
    assert result.exit_code == 0, out
    return jira_url


def test_login_stores_the_token_owner_only_and_never_in_the_config(jira_url):
    result, out = login(jira_url)
    assert result.exit_code == 0, out
    assert "Logged in" in out
    assert "Bob Jensen" in out
    token_file = config_dir() / "credentials.json"
    assert fake_jira.TOKEN in token_file.read_text()
    assert fake_jira.TOKEN not in (config_dir() / "config.json").read_text()
    if os.name == "posix":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(config_dir().stat().st_mode) == 0o700
    site = saved_site()
    assert site.time_zone == "Africa/Casablanca"
    assert site.hours_per_day == 8


def test_login_prompts_for_a_hidden_token(jira_url):
    result, out = jtt("login", input=f"{jira_url}\n{fake_jira.EMAIL}\n{fake_jira.TOKEN}\n")
    assert result.exit_code == 0, out
    assert fake_jira.TOKEN not in out


def test_a_rejected_token_is_not_stored(jira_url):
    result, out = login(jira_url, token="wrong")
    assert result.exit_code == 1
    assert "rejected the credentials" in out
    assert not (config_dir() / "credentials.json").exists()


def test_changing_the_token_requires_logout_first(ready):
    result, out = login(ready)
    assert result.exit_code == 1
    assert "jtt logout" in out
    result, out = jtt("logout")
    assert result.exit_code == 0, out
    assert not (config_dir() / "credentials.json").exists()
    assert "DEMO" in saved_site().projects  # settings survive a plain logout
    result, out = jtt("calculate", *PERIOD)
    assert result.exit_code == 1
    assert "Not logged in" in out
    assert login(ready)[0].exit_code == 0


def test_logout_purge_forgets_the_site(ready):
    assert jtt("logout", "--purge")[0].exit_code == 0
    assert Config.load().sites == {}


def test_interactive_init_lists_create_screen_fields_first(jira_url):
    login(jira_url)
    # Create-screen fields sort first: Original estimate, Story point estimate, Time Spent,
    # then the rest.
    # DEMO: pick 2 (Story point estimate), unit points. OPS: skip.
    result, out = jtt("init", input="2\npoints\ns\n")
    assert result.exit_code == 0, out
    assert "★" in out
    projects = saved_site().projects
    assert list(projects) == ["DEMO"]
    assert projects["DEMO"].field_id == "customfield_10016"
    assert projects["DEMO"].unit.value == "points"


def test_init_with_a_time_tracking_field_forces_seconds(jira_url):
    login(jira_url)
    result, out = jtt(
        "init", "-p", "OPS", "--field", "timeoriginalestimate", "--display-unit", "days"
    )
    assert result.exit_code == 0, out
    ops = saved_site().projects["OPS"]
    assert (ops.unit.value, ops.display_unit.value) == ("seconds", "days")


def test_calculate_whole_project(ready):
    result, out = jtt("calculate", *PERIOD)
    assert result.exit_code == 0, out
    assert "+16 SP" in out
    for key in ("DEMO-729", "DEMO-900", "DEMO-727"):
        assert key in out


def test_calculate_the_end_day_is_excluded(ready):
    result, out = jtt("calculate", "--from", "2026-09-25", "--to", "2026-09-26")
    assert result.exit_code == 0, out
    assert "+8.5 SP" in out  # DEMO-729 +5.5, DEMO-727 +3


def test_calculate_for_a_user_by_name_with_holder_attribution(ready):
    result, out = jtt("calculate", *PERIOD, "--user", "jensen", "--attribution", "holder")
    assert result.exit_code == 0, out
    # Bob only took DEMO-900 after every change on it.
    assert "Nothing changed" in out


@pytest.mark.parametrize("flag", ["-v", "--vv", "-vvv"])
def test_calculate_verbosity_levels(ready, flag):
    result, out = jtt("calculate", *PERIOD, flag)
    assert result.exit_code == 0, out
    assert "Assignee now" in out
    if flag != "-v":
        assert "Timeline" in out
        assert "created with" in out
    if flag == "-vvv":
        assert "JQL" in out
        assert 'updated >= "2026-09-24 00:00"' in out
        assert "HTTP POST 200" in out
        assert "/changelog" in out


def test_contributions_with_daily_breakdown(ready):
    result, out = jtt("contributions", *PERIOD, "--by", "day")
    assert result.exit_code == 0, out
    assert "Alice Martin" in out
    assert "+16 SP" in out
    assert "Per day" in out
    assert "Statistics" in out
    assert "Busiest day" in out


def test_fetch_json(ready):
    result, out = jtt("fetch", *PERIOD, "--json")
    assert result.exit_code == 0, out
    data = json.loads(out)
    assert "updated >=" in data["jql"]
    assert len(data["issues"]) == 4


def test_collaborators(ready):
    result, out = jtt("collaborators")
    assert result.exit_code == 0, out
    assert "Alice Martin" in out
    assert "Bob Jensen (you)" in out


def test_fields_with_counts(ready):
    result, out = jtt("fields", "--counts")
    assert result.exit_code == 0, out
    assert "Story point estimate" in out
    assert "Tracked now" in out


@pytest.mark.parametrize(
    ("kind", "suffix"),
    [("issues", "csv"), ("changes", "json"), ("contributions", "md"), ("daily", "csv")],
)
def test_export(ready, tmp_path, kind, suffix):
    target = tmp_path / f"out.{suffix}"
    result, out = jtt("export", "-o", str(target), "-k", kind, *PERIOD)
    assert result.exit_code == 0, out
    text = target.read_text(encoding="utf-8-sig")
    if suffix == "csv":
        rows = list(csv.DictReader(text.splitlines()))
        column = "delta" if kind == "issues" else "net"
        assert sum(float(r[column]) for r in rows) == 16
    elif suffix == "json":
        data = json.loads(text)
        assert data["meta"]["period_to_excluded"] == "2026-09-30"
        assert sum(r["delta"] for r in data["rows"]) == 16
    else:
        assert "| Alice Martin |" in text


def test_export_refuses_to_overwrite(ready, tmp_path):
    target = tmp_path / "out.csv"
    target.write_text("keep")
    result, _out = jtt("export", "-o", str(target), *PERIOD)
    assert result.exit_code == 1
    assert target.read_text() == "keep"


def test_display_unit_conversion(jira_url):
    login(jira_url)
    jtt(
        "init",
        "-p",
        "DEMO",
        "--field",
        "customfield_10016",
        "--unit",
        "hours",
        "--display-unit",
        "days",
    )
    result, out = jtt("calculate", *PERIOD)
    assert result.exit_code == 0, out
    assert "+2d" in out  # 16 hours at 8 h/day


def test_unconfigured_project_points_to_init(ready):
    result, out = jtt("calculate", "-p", "OPS", *PERIOD)
    assert result.exit_code == 1
    assert "jtt init -p OPS" in out


def test_whoami_check(ready):
    result, out = jtt("whoami", "--check")
    assert result.exit_code == 0, out
    assert "valid" in out
    assert "owner-only file" in out
