"""Reporting periods: [from, to), the start day included and the end day excluded.

Days are calendar days as Jira renders them. The API writes every timestamp in
the caller's profile time zone, with the same zone rules JQL reads date
literals by, so a timestamp's own date is the day Jira means. The zone is
deliberately never rebuilt from local tzdata: tzdata 2026d keeps
Africa/Casablanca at +00 after Ramadan 2026 while Jira still renders it at +01.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

PERIOD_NAMES = (
    "today",
    "yesterday",
    "this-week",
    "last-week",
    "this-month",
    "last-month",
    "this-quarter",
    "last-quarter",
    "this-year",
    "last-7-days",
    "last-30-days",
)


class PeriodError(ValueError):
    """A period that cannot be understood or is empty."""


@dataclass(frozen=True)
class Window:
    """A reporting period: `date_from` included, `date_to` excluded."""

    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_to <= self.date_from:
            raise PeriodError(
                f"the end ({self.date_to}) must be after the start ({self.date_from})"
            )

    @property
    def days(self) -> int:
        """Return the number of days in the period."""
        return (self.date_to - self.date_from).days

    def position(self, moment: datetime) -> str:
        """'before', 'in' or 'after'. `moment` must keep the offset Jira sent."""
        day = moment.date()
        if day < self.date_from:
            return "before"
        return "in" if day < self.date_to else "after"

    def contains(self, moment: datetime) -> bool:
        """Return whether `moment` falls inside the period."""
        return self.position(moment) == "in"

    def each_day(self) -> Iterator[date]:
        """Yield every day of the period, in order."""
        for offset in range(self.days):
            yield self.date_from + timedelta(days=offset)

    # JQL bounds carry an explicit 00:00. Checked against a live site: with bare
    # dates, `DURING ("2026-09-24", "2026-09-25")` matched issues first assigned
    # at 13:05 on the 25th, and `DURING ("2026-09-25", "2026-09-25")` matched
    # nothing, while the explicit-time form is an exact half-open range.
    @property
    def jql_start(self) -> str:
        """Return the period's start as a quoted JQL datetime literal."""
        return f'"{self.date_from} 00:00"'

    @property
    def jql_end(self) -> str:
        """Return the period's (excluded) end as a quoted JQL datetime literal."""
        return f'"{self.date_to} 00:00"'

    def label(self) -> str:
        """Return a human-readable 'from → to' label."""
        return f"{self.date_from:%a %d %b %Y} → {self.date_to:%a %d %b %Y}"


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def named_period(name: str, today: date) -> Window:
    """Return the window a name like 'last-week' means, relative to `today`."""
    monday = today - timedelta(days=today.weekday())
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    tomorrow = today + timedelta(days=1)
    windows = {
        "today": (today, tomorrow),
        "yesterday": (today - timedelta(days=1), today),
        "this-week": (monday, monday + timedelta(days=7)),
        "last-week": (monday - timedelta(days=7), monday),
        "this-month": (_month_start(today), _add_months(today, 1)),
        "last-month": (_add_months(today, -1), _month_start(today)),
        "this-quarter": (quarter_start, _add_months(quarter_start, 3)),
        "last-quarter": (_add_months(quarter_start, -3), quarter_start),
        "this-year": (date(today.year, 1, 1), date(today.year + 1, 1, 1)),
        "last-7-days": (tomorrow - timedelta(days=7), tomorrow),
        "last-30-days": (tomorrow - timedelta(days=30), tomorrow),
    }
    if name not in windows:
        raise PeriodError(f"unknown period {name!r}; use one of: {', '.join(PERIOD_NAMES)}")
    return Window(*windows[name])


def parse_day(raw: str, flag: str) -> date:
    """Parse a YYYY-MM-DD date, naming `flag` in the error."""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise PeriodError(f"{flag} must be a date like 2026-09-25, got {raw!r}") from None


def resolve_window(
    date_from: str | None,
    date_to: str | None,
    period: str | None,
    today: date | None = None,
) -> Window:
    """Build the window from --from/--to or --period; --to defaults to tomorrow."""
    today = today or date.today()
    if period and (date_from or date_to):
        raise PeriodError("use either --period or --from/--to, not both")
    if period:
        return named_period(period, today)
    if not date_from:
        raise PeriodError(
            "give a period: --period this-week, or --from 2026-09-01 [--to 2026-10-01]"
        )
    start = parse_day(date_from, "--from")
    end = parse_day(date_to, "--to") if date_to else today + timedelta(days=1)
    return Window(start, end)
