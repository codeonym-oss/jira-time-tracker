from datetime import date

import pytest

from jira_time_tracker.period import Window
from jira_time_tracker.tracking import build_report, by_week, contributions, daily_net
from tests.fake_jira import ALICE, BOB, CHANGELOGS, ISSUES, STATUSES

SP = ("customfield_10016", "Story point estimate")
CATEGORIES = {s["id"]: s["statusCategory"]["key"] for s in STATUSES}


def window(start: str, end: str) -> Window:
    return Window(date.fromisoformat(start), date.fromisoformat(end))


def report(key: str, win: Window, categories=None):
    issue = next(i for i in ISSUES if i["key"] == key)
    return build_report(issue, CHANGELOGS[key], *SP, win, categories)


def reports(win: Window):
    return [report(i["key"], win, CATEGORIES) for i in ISSUES]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            "2026-09-25",
            "2026-09-26",
            5.5,
        ),  # the bug that started it: SP set on the 25th, edited again on the 28th
        ("2026-09-24", "2026-09-25", 0.0),  # the end day is excluded
        ("2026-09-26", "2026-09-29", 2.5),
        ("2026-09-25", "2026-09-29", 8.0),
    ],
)
def test_demo_729_deltas(start, end, expected):
    assert report("DEMO-729", window(start, end)).delta == expected


def test_value_typed_on_the_create_screen_counts_once():
    # DEMO-900 was created with 2 (no changelog entry) and bumped to 5 the same day.
    r = report("DEMO-900", window("2026-09-24", "2026-09-25"))
    assert r.created_with == 2
    assert r.delta == 5


def test_create_screen_value_is_the_current_value_when_never_edited():
    issue = {
        "key": "X-1",
        "fields": {"created": "2026-09-25T09:00:00.000+0100", "customfield_10016": 3},
    }
    assert build_report(issue, [], *SP, window("2026-09-25", "2026-09-26")).delta == 3


def test_removing_a_value_counts_negative():
    issue = {
        "key": "X-2",
        "fields": {"created": "2026-09-01T09:00:00.000+0100", "customfield_10016": None},
    }
    log = [
        {
            "created": "2026-09-25T10:00:00.000+0100",
            "items": [{"fieldId": "customfield_10016", "fromString": "4"}],
        }
    ]
    assert build_report(issue, log, *SP, window("2026-09-25", "2026-09-26")).delta == -4


def test_time_tracking_fields_read_raw_seconds():
    issue = {
        "key": "X-3",
        "fields": {"created": "2026-09-01T09:00:00.000+0100", "timeoriginalestimate": 10800},
    }
    log = [
        {
            "created": "2026-09-25T10:00:00.000+0100",
            "items": [
                {
                    "field": "timeoriginalestimate",
                    "fieldId": "timeoriginalestimate",
                    "from": "3600",
                    "fromString": "3600",
                    "to": "10800",
                    "toString": "10800",
                }
            ],
        }
    ]
    r = build_report(
        issue, log, "timeoriginalestimate", "Original estimate", window("2026-09-25", "2026-09-26")
    )
    assert r.delta == 7200


def test_changes_are_credited_to_whoever_held_the_issue():
    r = report("DEMO-900", window("2026-09-24", "2026-09-30"))
    assert r.first_holder.account_id == ALICE["accountId"]
    assert (
        r.delta_for(ALICE["accountId"]) == 5
    )  # created with 2 + edit of 3, both while she held it
    assert r.delta_for(BOB["accountId"]) == 0
    assert r.assignee.account_id == BOB["accountId"]


def test_unassigned_at_creation_credits_the_first_assignee():
    # DEMO-729 was created unassigned and assigned 7 seconds later.
    r = report("DEMO-729", window("2026-09-25", "2026-09-26"))
    assert r.first_holder.name == "Alice Martin"


def test_completion_in_period_is_detected_with_the_value_at_that_time():
    r = report("DEMO-729", window("2026-09-28", "2026-09-29"), CATEGORIES)
    assert r.completed_at is not None
    assert r.completed_value == 8
    assert report("DEMO-729", window("2026-09-25", "2026-09-26"), CATEGORIES).completed_at is None


def test_per_person_nets_add_up_to_the_project_net():
    win = window("2026-09-24", "2026-09-30")
    rs = reports(win)
    people = contributions(rs)
    assert sum(p.net for p in people) == sum(r.delta for r in rs) == 16
    alice = next(p for p in people if p.account_id == ALICE["accountId"])
    assert alice.net == 16
    assert alice.completed_count == 2
    assert alice.created_count == 4


def test_daily_series_sums_to_the_net_and_weeks_start_on_monday():
    win = window("2026-09-24", "2026-09-30")
    series = daily_net(reports(win), win)
    assert series[date(2026, 9, 24)] == 5
    assert series[date(2026, 9, 25)] == 8.5
    assert series[date(2026, 9, 28)] == 2.5
    assert sum(series.values()) == 16
    assert by_week(series) == {date(2026, 9, 21): 13.5, date(2026, 9, 28): 2.5}
