"""What a tracked field's numbers mean, and converting between time units."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Jira's built-in time tracking fields always hold seconds.
TIME_TRACKING_FIELDS = frozenset(
    {
        "timeoriginalestimate",
        "timeestimate",
        "timespent",
        "aggregatetimeoriginalestimate",
        "aggregatetimeestimate",
        "aggregatetimespent",
    }
)


class Unit(str, Enum):
    """What a tracked field's raw numbers mean."""

    POINTS = "points"
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"

    @property
    def short(self) -> str:
        """Return the suffix reports print after an amount."""
        return {
            "points": "SP",
            "seconds": "s",
            "minutes": "m",
            "hours": "h",
            "days": "d",
            "weeks": "w",
        }[self.value]

    @property
    def is_time(self) -> bool:
        """Return whether the unit measures time, and so converts to other time units."""
        return self is not Unit.POINTS


@dataclass(frozen=True)
class WorkCalendar:
    """How long a working day and week are.

    Jira's defaults, overridden by the site's time tracking settings at init.
    """

    hours_per_day: float = 8.0
    days_per_week: float = 5.0

    def seconds_in(self, unit: Unit) -> float:
        """Return how many seconds one `unit` lasts on this calendar."""
        return {
            Unit.SECONDS: 1.0,
            Unit.MINUTES: 60.0,
            Unit.HOURS: 3600.0,
            Unit.DAYS: 3600.0 * self.hours_per_day,
            Unit.WEEKS: 3600.0 * self.hours_per_day * self.days_per_week,
        }[unit]


def convert(value: float, source: Unit, target: Unit, calendar: WorkCalendar) -> float:
    """Convert `value` between two units; only time units convert."""
    if source is target:
        return value
    if not (source.is_time and target.is_time):
        raise ValueError(f"cannot convert {source.value} to {target.value}")
    return value * calendar.seconds_in(source) / calendar.seconds_in(target)


def fmt_amount(value: float, unit: Unit) -> str:
    """Format an amount with its unit, rounded to two decimals."""
    number = f"{round(value, 2):g}"
    return f"{number} {unit.short}" if unit is Unit.POINTS else f"{number}{unit.short}"


def fmt_signed(value: float, unit: Unit) -> str:
    """Format a change with an explicit sign, or ±0."""
    if value == 0:
        return "±0"
    return ("+" if value > 0 else "") + fmt_amount(value, unit)
