"""Turn an issue and its changelog into the amount that came into being in a period.

It also records who held the issue when each change happened.

Two facts about Jira shape this module:
  - `updated` in JQL is the *last* update, so it can only bound a search from
    below; the changelog is what places each change inside or outside the
    period.
  - A value entered on the create screen leaves no changelog entry: the log
    starts at the first edit. The value an issue was created with is the
    `from` side of the first later change, or the current value if the field
    was never changed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jira_time_tracker.period import Window

UNASSIGNED = ("", "Unassigned")


def parse_timestamp(raw: str | None) -> datetime | None:
    """Parse a Jira timestamp such as '2026-07-21T16:20:00.000+0100'.

    The offset is kept, not converted, so the date stays the one Jira rendered.
    """
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    if len(normalized) >= 5 and normalized[-5] in "+-" and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_amount(raw: object) -> float | None:
    """Parse a raw field or changelog value; empty means None."""
    if raw == "" or not isinstance(raw, (int, float, str)):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def item_amount(item: dict, side: str) -> float:
    """Return one side ('from' or 'to') of a changelog item.

    Number custom fields only fill fromString/toString; time tracking fields fill both
    with seconds.
    """
    raw = parse_amount(item.get(side))
    if raw is None:
        raw = parse_amount(item.get(f"{side}String"))
    return raw or 0.0


def matches_field(item: dict, field_id: str, field_name: str) -> bool:
    """Return whether a changelog item changed the tracked field."""
    if item.get("fieldId"):
        return item["fieldId"] == field_id
    # Old entries can lack fieldId.
    return item.get("field") in (field_id, field_name)


@dataclass(frozen=True)
class Holder:
    """Who held (was assigned) an issue, from `since` on."""

    since: datetime | None
    account_id: str
    name: str


@dataclass(frozen=True)
class Change:
    """One change of the tracked field, placed against the period."""

    at: datetime
    author: str
    before: float
    after: float
    position: str
    holder: Holder

    @property
    def delta(self) -> float:
        """Return how much the change added (negative when it removed)."""
        return self.after - self.before


@dataclass(frozen=True)
class IssueReport:
    """An issue's tracked-field history, placed against the period."""

    key: str
    summary: str
    issue_type: str
    status: str
    status_category: str
    assignee: Holder
    created: datetime | None
    current_value: float
    # The amount the issue was created with, when it was created inside the period.
    created_with: float | None
    # Who is credited with created_with: the first person ever assigned.
    first_holder: Holder
    changes: tuple[Change, ...]
    holders: tuple[Holder, ...]
    # When the issue last moved into a done status inside the period, and who held it.
    completed_at: datetime | None = None
    completed_by: Holder | None = None
    completed_value: float = 0.0

    @property
    def in_period(self) -> list[Change]:
        """Return the changes made inside the period."""
        return [c for c in self.changes if c.position == "in"]

    @property
    def delta(self) -> float:
        """Return the net amount that came into being inside the period."""
        return (self.created_with or 0.0) + sum(c.delta for c in self.in_period)

    def delta_for(self, account_id: str) -> float:
        """Return the part of the delta that happened while `account_id` held the issue."""
        total = sum(c.delta for c in self.in_period if c.holder.account_id == account_id)
        if self.created_with and self.first_holder.account_id == account_id:
            total += self.created_with
        return total

    def value_at(self, moment: datetime) -> float:
        """Return the field's value right after `moment`."""
        value = self.changes[0].before if self.changes else self.current_value
        for change in self.changes:
            if change.at <= moment:
                value = change.after
        return value


def holder_timeline(fields: dict, changelog: list[dict], created: datetime | None) -> list[Holder]:
    """Return who held the issue over time, from its creation on."""
    moves = sorted(
        (
            (at, item)
            for entry in changelog
            if (at := parse_timestamp(entry.get("created"))) is not None
            for item in entry.get("items", [])
            if (item.get("fieldId") or item.get("field")) == "assignee"
        ),
        key=lambda move: move[0],
    )
    if moves:
        first = moves[0][1]
        initial = Holder(created, first.get("from") or "", first.get("fromString") or UNASSIGNED[1])
    else:
        current = fields.get("assignee") or {}
        initial = Holder(
            created, current.get("accountId", ""), current.get("displayName", UNASSIGNED[1])
        )
    timeline = [initial]
    for at, item in moves:
        timeline.append(Holder(at, item.get("to") or "", item.get("toString") or UNASSIGNED[1]))
    return timeline


def holder_at(timeline: list[Holder], moment: datetime) -> Holder:
    """Return who held the issue at `moment`."""
    held = timeline[0]
    for holder in timeline[1:]:
        if holder.since is not None and holder.since <= moment:
            held = holder
    return held


def build_report(
    issue: dict,
    changelog: list[dict],
    field_id: str,
    field_name: str,
    window: Window,
    status_categories: dict[str, str] | None = None,
) -> IssueReport:
    """Place an issue's tracked-field changes against the period."""
    fields = issue["fields"]
    created = parse_timestamp(fields.get("created"))
    holders = holder_timeline(fields, changelog, created)

    changes = sorted(
        (
            Change(
                at=at,
                author=(entry.get("author") or {}).get("displayName", "?"),
                before=item_amount(item, "from"),
                after=item_amount(item, "to"),
                position=window.position(at),
                holder=holder_at(holders, at),
            )
            for entry in changelog
            if (at := parse_timestamp(entry.get("created"))) is not None
            for item in entry.get("items", [])
            if matches_field(item, field_id, field_name)
        ),
        key=lambda change: change.at,
    )
    current_value = parse_amount(fields.get(field_id)) or 0.0
    created_inside = created is not None and window.contains(created)
    created_value = changes[0].before if changes else current_value
    first_holder = next((h for h in holders if h.account_id), Holder(None, *UNASSIGNED))

    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    report = IssueReport(
        key=issue["key"],
        summary=fields.get("summary", ""),
        issue_type=(fields.get("issuetype") or {}).get("name", ""),
        status=status.get("name", ""),
        status_category=(status.get("statusCategory") or {}).get("key", ""),
        assignee=Holder(
            None, assignee.get("accountId", ""), assignee.get("displayName", UNASSIGNED[1])
        ),
        created=created,
        current_value=current_value,
        created_with=created_value if created_inside else None,
        first_holder=first_holder,
        changes=tuple(changes),
        holders=tuple(holders),
    )
    if status_categories:
        completion = last_completion(changelog, window, status_categories)
        if completion:
            holder = holder_at(holders, completion)
            report = _with_completion(report, completion, holder)
    return report


def last_completion(
    changelog: list[dict], window: Window, categories: dict[str, str]
) -> datetime | None:
    """Return when the issue last moved into a done status inside the period."""
    done = [
        at
        for entry in changelog
        if (at := parse_timestamp(entry.get("created"))) is not None and window.contains(at)
        for item in entry.get("items", [])
        if (item.get("fieldId") or item.get("field")) == "status"
        and categories.get(str(item.get("to"))) == "done"
    ]
    return max(done) if done else None


def _with_completion(report: IssueReport, at: datetime, holder: Holder) -> IssueReport:
    return replace(
        report, completed_at=at, completed_by=holder, completed_value=report.value_at(at)
    )


# ── aggregation ──────────────────────────────────────────────────────────────


@dataclass
class Contribution:
    """What one person is credited with over the period."""

    account_id: str
    name: str
    added: float = 0.0
    removed: float = 0.0
    issues: set[str] = field(default_factory=set)
    created_count: int = 0
    created_value: float = 0.0
    completed_count: int = 0
    completed_value: float = 0.0

    @property
    def net(self) -> float:
        """Return what the person added minus what they removed."""
        return self.added + self.removed


def contributions(reports: list[IssueReport]) -> list[Contribution]:
    """Credit each change to whoever held the issue when it happened.

    A created-with amount goes to the first person ever assigned, so the per-person nets
    add up to the project's net.
    """
    people: dict[str, Contribution] = {}

    def person(holder: Holder) -> Contribution:
        if holder.account_id not in people:
            people[holder.account_id] = Contribution(holder.account_id, holder.name)
        return people[holder.account_id]

    for report in reports:
        if report.created_with is not None:
            credited = person(report.first_holder)
            credited.created_count += 1
            credited.created_value += report.created_with
            _credit(credited, report.created_with)
            if report.created_with:
                credited.issues.add(report.key)
        for change in report.in_period:
            credited = person(change.holder)
            _credit(credited, change.delta)
            credited.issues.add(report.key)
        if report.completed_by is not None:
            credited = person(report.completed_by)
            credited.completed_count += 1
            credited.completed_value += report.completed_value
    return sorted(people.values(), key=lambda c: (-c.net, c.name.lower()))


def _credit(contribution: Contribution, amount: float) -> None:
    if amount > 0:
        contribution.added += amount
    else:
        contribution.removed += amount


def daily_net(
    reports: list[IssueReport], window: Window, account_id: str | None = None
) -> dict[date, float]:
    """Return the net amount per day, for everyone or one account."""
    days = dict.fromkeys(window.each_day(), 0.0)
    for report in reports:
        if (
            report.created_with
            and report.created
            and (account_id is None or report.first_holder.account_id == account_id)
        ):
            days[report.created.date()] += report.created_with
        for change in report.in_period:
            if account_id is None or change.holder.account_id == account_id:
                days[change.at.date()] += change.delta
    return days


def by_week(days: dict[date, float]) -> dict[date, float]:
    """Sum a daily series into ISO weeks, keyed by each week's Monday."""
    weeks: dict[date, float] = defaultdict(float)
    for day, value in days.items():
        weeks[date.fromordinal(day.toordinal() - day.weekday())] += value
    return dict(sorted(weeks.items()))
