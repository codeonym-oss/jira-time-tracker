from __future__ import annotations

from datetime import date

import pytest

from jira_time_tracker.period import Window
from jira_time_tracker.tracking import build_report, by_week, contributions, daily_net
from tests.fake_jira import ALICE, BOB, CHANGELOGS, ISSUES, STATUSES, assign, sp, status

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


# ── last-holder ──────────────────────────────────────────────────────────────
# One issue's history at a time: every change below happens in September unless it says not.

SEPTEMBER = window("2026-09-01", "2026-10-01")
CAROL = {"accountId": "70121:44444444-dddd-4ddd-8ddd-444444444444", "displayName": "Carol Nguyen"}


def history(
    log, *, created: str | None = "2026-09-10T09:00:00.000+0100", value=None, assignee=None
):
    issue = {
        "key": "X-9",
        "fields": {"created": created, "customfield_10016": value, "assignee": assignee},
    }
    return build_report(issue, log, *SP, SEPTEMBER, CATEGORIES)


def nets(report, **kwargs):
    """Return each credited person's net, leaving out the zeros."""
    return {p.name: p.net for p in contributions([report], **kwargs) if p.net}


# Issue A: Alice created it with 4, cleared it and unassigned herself; Bob set 2, then 2.5.
ISSUE_A = history(
    [
        sp("2026-09-10T10:00:00.000+0100", ALICE, frm="4"),
        assign("2026-09-10T10:01:00.000+0100", ALICE, frm=ALICE),
        assign("2026-09-11T09:00:00.000+0100", BOB, to=BOB),
        sp("2026-09-11T10:00:00.000+0100", BOB, to="2"),
        sp("2026-09-14T10:00:00.000+0100", BOB, "2", "2.5"),
    ],
    value=2.5,
    assignee=BOB,
)
# Issue B: Alice created it without a value and handed it to Bob within a minute.
ISSUE_B = history(
    [
        assign("2026-09-10T09:00:40.000+0100", ALICE, frm=ALICE, to=BOB),
        sp("2026-09-10T15:00:00.000+0100", BOB, to="0.5"),
    ],
    value=0.5,
    assignee=BOB,
)
# Issue C: set to 3 after Bob was unassigned; Bob is back only after the period.
ISSUE_C = history(
    [
        assign("2026-09-10T09:30:00.000+0100", BOB, to=BOB),
        assign("2026-09-11T09:00:00.000+0100", BOB, frm=BOB),
        sp("2026-09-11T10:00:00.000+0100", BOB, to="3"),
        assign("2026-10-05T09:00:00.000+0100", BOB, to=BOB),
    ],
    value=3,
    assignee=BOB,
)
# Issue D: set to 0.75 while unassigned, then assigned to Bob and corrected to 0.5.
ISSUE_D = history(
    [
        sp("2026-09-10T10:00:00.000+0100", BOB, to="0.75"),
        assign("2026-09-10T11:00:00.000+0100", BOB, to=BOB),
        sp("2026-09-10T12:00:00.000+0100", BOB, "0.75", "0.5"),
    ],
    value=0.5,
    assignee=BOB,
)


@pytest.mark.parametrize(
    ("issue", "by_holder", "by_last_holder"),
    [
        (ISSUE_A, {"Bob Jensen": 2.5}, {"Bob Jensen": 2.5}),
        (ISSUE_B, {"Bob Jensen": 0.5}, {"Bob Jensen": 0.5}),
        (ISSUE_C, {"Unassigned": 3}, {"Bob Jensen": 3}),
        (ISSUE_D, {"Unassigned": 0.75, "Bob Jensen": -0.25}, {"Bob Jensen": 0.5}),
    ],
    ids=["A", "B", "C", "D"],
)
def test_last_holder_credits_one_person_with_the_whole_issue(issue, by_holder, by_last_holder):
    assert nets(issue) == by_holder
    assert nets(issue, by_last_holder=True) == by_last_holder
    assert issue.last_holder.account_id == BOB["accountId"]
    assert issue.delta == sum(by_last_holder.values())


def test_last_holder_does_not_move_when_reassigned_after_the_period():
    r = history(
        [
            assign("2026-09-10T09:30:00.000+0100", BOB, to=BOB),
            sp("2026-09-10T10:00:00.000+0100", BOB, to="3"),
            assign("2026-10-02T09:00:00.000+0100", ALICE, frm=BOB, to=ALICE),
        ],
        value=3,
        assignee=ALICE,
    )
    assert r.assignee.name == "Alice Martin"
    assert nets(r, by_last_holder=True) == {"Bob Jensen": 3}


@pytest.mark.parametrize(
    ("assigned", "credited"),
    [
        ("2026-09-30T23:59:59.000+0100", "Bob Jensen"),  # the last day
        ("2026-10-01T00:00:00.000+0100", "Alice Martin"),  # the excluded end day
        # The day is Jira's own, whatever it would be in UTC.
        ("2026-10-01T00:30:00.000+0100", "Alice Martin"),
        ("2026-09-30T23:30:00.000-0500", "Bob Jensen"),
    ],
)
def test_last_holder_is_whoever_was_assigned_by_the_last_day(assigned, credited):
    r = history([assign(assigned, ALICE, frm=ALICE, to=BOB)], value=3, assignee=BOB)
    assert nets(r, by_last_holder=True) == {credited: 3}


def test_last_holder_assigned_before_the_period_counts():
    r = history(
        [
            assign("2026-08-20T09:00:00.000+0100", BOB, frm=BOB),
            sp("2026-09-10T10:00:00.000+0100", ALICE, to="3"),
        ],
        created="2026-08-10T09:00:00.000+0100",
        value=3,
    )
    assert nets(r, by_last_holder=True) == {"Bob Jensen": 3}


def test_last_holder_first_assigned_after_the_period_is_the_first_person():
    r = history(
        [
            assign("2026-10-02T09:00:00.000+0100", BOB, to=BOB),
            assign("2026-10-03T09:00:00.000+0100", CAROL, frm=BOB, to=CAROL),
        ],
        value=3,
        assignee=CAROL,
    )
    assert nets(r, by_last_holder=True) == {"Bob Jensen": 3}


def test_last_holder_never_assigned_is_unassigned():
    r = history([sp("2026-09-11T10:00:00.000+0100", ALICE, "3", "5")], value=5)
    assert (r.last_holder.account_id, r.last_holder.name) == ("", "Unassigned")
    assert nets(r, by_last_holder=True) == {"Unassigned": 5}


def test_last_holder_with_no_creation_date_counts_as_held_before_the_end():
    r = history([sp("2026-09-11T10:00:00.000+0100", BOB, to="2")], created=None, assignee=BOB)
    assert r.last_holder.account_id == BOB["accountId"]


def test_last_holder_takes_the_created_with_amount_and_the_completion_too():
    r = history(
        [
            sp("2026-09-11T10:00:00.000+0100", ALICE, "5", "3"),
            status("2026-09-12T10:00:00.000+0100", ALICE, "10103", "10104"),
            assign("2026-09-14T10:00:00.000+0100", ALICE, frm=ALICE, to=BOB),
        ],
        value=3,
        assignee=BOB,
    )
    alice, *others = contributions([r])
    assert (alice.name, others) == ("Alice Martin", [])
    (bob,) = contributions([r], by_last_holder=True)
    assert bob.name == "Bob Jensen"
    # Added and removed stay gross.
    assert (bob.net, bob.added, bob.removed, bob.issues) == (3, 5, -2, {"X-9"})
    assert (bob.created_count, bob.created_value) == (1, 5)
    assert (bob.completed_count, bob.completed_value) == (1, 3)


def test_last_holder_daily_series_keeps_each_change_on_its_own_day():
    bob, alice = BOB["accountId"], ALICE["accountId"]

    def days(account_id, **kwargs):
        series = daily_net([ISSUE_A], SEPTEMBER, account_id, **kwargs)
        return {day.day: net for day, net in series.items() if net}

    # Alice's 4 was typed and cleared on the 10th, so every day nets out the same in all.
    assert days(bob) == {11: 2, 14: 0.5}
    assert days(bob, by_last_holder=True) == {11: 2, 14: 0.5}
    assert days(alice, by_last_holder=True) == {}
    everyone = daily_net([ISSUE_A, ISSUE_C, ISSUE_D], SEPTEMBER)
    assert daily_net([ISSUE_A, ISSUE_C, ISSUE_D], SEPTEMBER, bob, by_last_holder=True) == everyone
    assert daily_net([ISSUE_C], SEPTEMBER, bob)[date(2026, 9, 11)] == 0
