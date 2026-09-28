from datetime import date, datetime, timedelta, timezone

import pytest

from jira_time_tracker.period import PeriodError, Window, named_period, resolve_window
from jira_time_tracker.units import Unit, WorkCalendar, convert, fmt_signed

TODAY = date(2026, 9, 28)  # a Monday
PLUS_ONE = timezone(timedelta(hours=1))


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=PLUS_ONE)


def test_window_includes_the_from_day_and_excludes_the_to_day():
    window = Window(date(2026, 9, 25), date(2026, 9, 26))
    assert window.contains(at("2026-09-25T00:00:00"))
    assert window.contains(at("2026-09-25T23:59:59.500"))
    assert not window.contains(at("2026-09-26T00:00:00"))
    assert window.position(at("2026-09-24T23:59:59")) == "before"
    assert window.position(at("2026-09-26T00:00:00")) == "after"


def test_window_uses_the_day_jira_rendered_not_utc():
    # 00:30 at +01:00 is 23:30 UTC the day before; Jira means the 26th.
    window = Window(date(2026, 9, 26), date(2026, 9, 27))
    assert window.contains(at("2026-09-26T00:30:00"))


def test_jql_bounds_carry_explicit_midnight():
    window = Window(date(2026, 9, 25), date(2026, 9, 26))
    assert (window.jql_start, window.jql_end) == ('"2026-09-25 00:00"', '"2026-09-26 00:00"')


def test_empty_or_reversed_window_is_rejected():
    with pytest.raises(PeriodError):
        Window(date(2026, 9, 25), date(2026, 9, 25))


@pytest.mark.parametrize(
    ("name", "start", "end"),
    [
        ("today", date(2026, 9, 28), date(2026, 9, 29)),
        ("yesterday", date(2026, 9, 27), date(2026, 9, 28)),
        ("this-week", date(2026, 9, 28), date(2026, 10, 5)),
        ("last-week", date(2026, 9, 21), date(2026, 9, 28)),
        ("this-month", date(2026, 9, 1), date(2026, 10, 1)),
        ("last-month", date(2026, 8, 1), date(2026, 9, 1)),
        ("this-quarter", date(2026, 7, 1), date(2026, 10, 1)),
        ("last-quarter", date(2026, 4, 1), date(2026, 7, 1)),
        ("this-year", date(2026, 1, 1), date(2027, 1, 1)),
        ("last-7-days", date(2026, 9, 22), date(2026, 9, 29)),
    ],
)
def test_named_periods(name, start, end):
    assert named_period(name, TODAY) == Window(start, end)


def test_last_month_across_new_year():
    assert named_period("last-month", date(2026, 1, 15)) == Window(
        date(2025, 12, 1), date(2026, 1, 1)
    )


def test_resolve_window_defaults_the_end_to_tomorrow_and_rejects_mixing():
    assert resolve_window("2026-09-01", None, None, TODAY) == Window(
        date(2026, 9, 1), date(2026, 9, 29)
    )
    with pytest.raises(PeriodError):
        resolve_window("2026-09-01", None, "this-week", TODAY)
    with pytest.raises(PeriodError):
        resolve_window(None, None, None, TODAY)
    with pytest.raises(PeriodError):
        resolve_window("25/09/2026", None, None, TODAY)


def test_time_conversions_follow_the_work_calendar():
    calendar = WorkCalendar(hours_per_day=8, days_per_week=5)
    assert convert(7200, Unit.SECONDS, Unit.HOURS, calendar) == 2
    assert convert(16, Unit.HOURS, Unit.DAYS, calendar) == 2
    assert convert(1, Unit.WEEKS, Unit.HOURS, calendar) == 40
    assert convert(1, Unit.DAYS, Unit.HOURS, WorkCalendar(7.5, 5)) == 7.5
    with pytest.raises(ValueError, match="cannot convert points to hours"):
        convert(3, Unit.POINTS, Unit.HOURS, calendar)


def test_signed_formatting():
    assert fmt_signed(5.5, Unit.POINTS) == "+5.5 SP"
    assert fmt_signed(-2, Unit.HOURS) == "-2h"
    assert fmt_signed(0, Unit.DAYS) == "±0"
