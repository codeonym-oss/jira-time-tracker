"""A fictional Jira Cloud site, generated from a seed.

Every name, email and summary is invented. The same seed always gives the same site, so the
docs' recordings and the tests see the same data. The generator keeps each issue's history
as plain events next to the Jira-shaped changelog it serves, and `truth` answers from those
events, never from the changelog: the tests hold jtt's numbers against it.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SEED = 2026
# The site's clock: data runs up to here, and relative JQL (`-90d`) counts back from it.
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone(timedelta(hours=1)))
TIME_ZONE = "Africa/Casablanca"  # +01:00 all through the generated months
EMAIL = "robin.hale@example.com"
TOKEN = "sim-token"

PEOPLE = [
    "Robin Hale",  # the logged-in account
    "Alice Martin",
    "Bob Jensen",
    "Chiara Rossi",
    "Daniel Okafor",
    "Elena Petrova",
    "Farid Haddad",
    "Grace Liu",
    "Hugo Lefèvre",
    "Inès Duarte",
    "Jonas Berg",
    "Kenji Sato",
    "Leila Benali",
]
# Worked on the projects, then left: still in the history, no longer assignable.
FORMER = {"Jonas Berg"}

STATUSES = {
    "todo": {"id": "10000", "name": "To Do", "category": "new"},
    "progress": {"id": "10001", "name": "In Progress", "category": "indeterminate"},
    "review": {"id": "10002", "name": "In Review", "category": "indeterminate"},
    "done": {"id": "10003", "name": "Done", "category": "done"},
}
ISSUE_TYPES = [
    {"id": "10001", "name": "Story", "subtask": False},
    {"id": "10002", "name": "Task", "subtask": False},
    {"id": "10003", "name": "Bug", "subtask": False},
    {"id": "10004", "name": "Subtask", "subtask": True},
]

FLOAT = "com.atlassian.jira.plugin.system.customfieldtypes:float"
FIELDS: list[dict[str, Any]] = [
    {"id": "summary", "name": "Summary", "custom": False, "schema": {"type": "string"}},
    {"id": "status", "name": "Status", "custom": False, "schema": {"type": "status"}},
    {"id": "assignee", "name": "Assignee", "custom": False, "schema": {"type": "user"}},
    {
        "id": "customfield_10016",
        "name": "Story point estimate",
        "custom": True,
        "schema": {"type": "number", "custom": "com.pyxis.greenhopper.jira:jsw-story-points"},
    },
    {
        "id": "customfield_10028",
        "name": "Story Points",
        "custom": True,
        "schema": {"type": "number", "custom": FLOAT},
    },
    {
        "id": "customfield_10041",
        "name": "Effort (days)",
        "custom": True,
        "schema": {"type": "number", "custom": FLOAT},
    },
    {
        "id": "timeoriginalestimate",
        "name": "Original estimate",
        "custom": False,
        "schema": {"type": "number", "system": "timeoriginalestimate"},
    },
    {
        "id": "timeestimate",
        "name": "Remaining Estimate",
        "custom": False,
        "schema": {"type": "number", "system": "timeestimate"},
    },
    {
        "id": "timespent",
        "name": "Time Spent",
        "custom": False,
        "schema": {"type": "number", "system": "timespent"},
    },
]
FIELD_NAMES = {f["id"]: f["name"] for f in FIELDS}


@dataclass(frozen=True)
class ProjectSpec:
    """How a generated project estimates, and how big it is."""

    key: str
    name: str
    field_id: str
    values: tuple[float, ...]
    issues: int
    members: int
    topics: tuple[str, ...]
    # Other numeric fields on its create screens, besides field_id.
    also_on_screen: tuple[str, ...] = ()


HOUR = 3600.0
PROJECT_SPECS = (
    ProjectSpec(
        "DEMO",
        "Demo App",
        "customfield_10016",
        (1, 2, 3, 5, 8, 13),
        150,
        8,
        (
            "report sharing",
            "the dashboard",
            "PDF export",
            "sign-in",
            "notifications",
            "the billing page",
            "search",
            "the onboarding tour",
            "audit logs",
            "team invites",
        ),
    ),
    ProjectSpec(
        "WEB",
        "Website",
        "customfield_10028",
        (0.5, 1, 2, 3, 5, 8),
        90,
        6,
        (
            "the pricing page",
            "the blog",
            "the docs search",
            "the changelog page",
            "the contact form",
            "image loading",
            "the cookie banner",
            "the careers page",
        ),
    ),
    ProjectSpec(
        "OPS",
        "Operations",
        "timeoriginalestimate",
        (HOUR / 2, HOUR, 2 * HOUR, 4 * HOUR, 8 * HOUR, 16 * HOUR, 24 * HOUR),
        80,
        5,
        (
            "the backup job",
            "TLS certificates",
            "the staging cluster",
            "log retention",
            "the on-call rota",
            "database failover",
            "the CI runners",
            "disk alerts",
        ),
        ("timeestimate", "timespent"),
    ),
    ProjectSpec(
        "DATA",
        "Analytics",
        "customfield_10041",
        (0.5, 1, 2, 3, 5),
        40,
        4,
        (
            "the weekly revenue report",
            "the churn model",
            "event tracking",
            "the warehouse schema",
            "the funnel dashboard",
        ),
        ("customfield_10016",),
    ),
)
VERBS = (
    "Add",
    "Fix",
    "Speed up",
    "Refactor",
    "Document",
    "Test",
    "Redesign",
    "Localize",
    "Clean up",
    "Monitor",
    "Migrate",
    "Simplify",
)


@dataclass
class Event:
    """One thing that happened to an issue, as the generator decided it."""

    at: datetime
    author: dict[str, Any]
    estimate: tuple[float | None, float | None] | None = None  # (before, after)
    assignee: tuple[dict | None, dict | None] | None = None
    status: tuple[str, str] | None = None


@dataclass
class Issue:
    """A generated issue: its fields now, and every event since creation."""

    key: str
    project: ProjectSpec
    summary: str
    issue_type: dict[str, Any]
    created: datetime
    created_with: float | None  # entered on the create screen: no changelog entry
    assignee_at_create: dict | None  # likewise
    events: list[Event] = field(default_factory=list)

    @property
    def updated(self) -> datetime:
        """Return the last time anything changed."""
        return self.events[-1].at if self.events else self.created

    @property
    def estimate(self) -> float | None:
        """Return the estimate now."""
        value = self.created_with
        for event in self.events:
            if event.estimate:
                value = event.estimate[1]
        return value

    @property
    def assignee(self) -> dict | None:
        """Return who holds the issue now."""
        holder = self.assignee_at_create
        for event in self.events:
            if event.assignee:
                holder = event.assignee[1]
        return holder

    @property
    def status(self) -> str:
        """Return the status key now."""
        state = "todo"
        for event in self.events:
            if event.status:
                state = event.status[1]
        return state

    def holders(self) -> list[tuple[datetime, dict | None]]:
        """Return (since, holder) from creation on."""
        timeline = [(self.created, self.assignee_at_create)]
        timeline += [(e.at, e.assignee[1]) for e in self.events if e.assignee]
        return timeline

    def holder_at(self, moment: datetime) -> dict | None:
        """Return who held the issue at `moment`."""
        held = None
        for since, holder in self.holders():
            if since <= moment:
                held = holder
        return held


@dataclass
class Site:
    """The whole generated site."""

    users: list[dict[str, Any]]
    me: dict[str, Any]
    automation: dict[str, Any]
    projects: list[ProjectSpec]
    members: dict[str, list[dict[str, Any]]]
    issues: list[Issue]
    now: datetime = NOW

    def project(self, key: str) -> ProjectSpec:
        """Return a project's spec by key."""
        return next(p for p in self.projects if p.key == key)

    def user(self, name: str) -> dict[str, Any]:
        """Return a person by display name."""
        return next(u for u in self.users if u["displayName"] == name)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _account_id(rng: random.Random) -> str:
    hexes = f"{rng.getrandbits(128):032x}"
    return f"712020:{hexes[:8]}-{hexes[8:12]}-4{hexes[13:16]}-a{hexes[17:20]}-{hexes[20:]}"


def _working_time(rng: random.Random, moment: datetime) -> datetime:
    """Move `moment` into working hours on a weekday, at a random minute."""
    while moment.weekday() >= 5:
        moment += timedelta(days=1)
    start = datetime.combine(moment.date(), time(9, 0), moment.tzinfo)
    if moment < start:
        moment = start + timedelta(minutes=rng.randint(0, 90))
    end = datetime.combine(moment.date(), time(18, 30), moment.tzinfo)
    if moment > end:
        return _working_time(rng, start + timedelta(days=1, minutes=rng.randint(0, 120)))
    return moment.replace(second=rng.randint(0, 59), microsecond=rng.randint(0, 999) * 1000)


def _next_value(rng: random.Random, values: tuple[float, ...], current: float | None) -> float:
    if current is None or current not in values:
        return rng.choice(values)
    index = values.index(current)
    step = rng.choice((-1, 1, 1, 2)) if index else rng.choice((1, 1, 2))
    return values[max(0, min(len(values) - 1, index + step))]


def _history(
    rng: random.Random,
    issue: Issue,
    team: list[dict],
    automation: dict,
    now: datetime,
) -> None:
    """Walk an issue through estimates, assignments and statuses, until `now`."""
    spec = issue.project
    moment = issue.created
    estimate, holder, state = issue.created_with, issue.assignee_at_create, "todo"
    for _ in range(rng.randint(1, 12)):
        moment = _working_time(rng, moment + timedelta(minutes=rng.expovariate(1 / 900) + 1))
        if moment >= now:
            return
        actor = holder or rng.choice(team)
        choices: list[tuple[str, float]] = [
            ("estimate", 5 if estimate is None else (0.4 if state == "done" else 1.2)),
            ("assign", 5 if holder is None else 0.5),
            ("advance", 0 if holder is None or state == "done" else 3),
            ("reopen", 0.6 if state == "done" else 0),
            ("clear", 0.15 if estimate is not None else 0),
        ]
        action = rng.choices([c for c, _ in choices], [w for _, w in choices])[0]
        event = Event(moment, actor)
        if action == "estimate":
            after = _next_value(rng, spec.values, estimate)
            if after == estimate:
                continue
            event.estimate, estimate = (estimate, after), after
        elif action == "clear":
            event.estimate, estimate = (estimate, None), None
        elif action == "assign":
            after = rng.choice([u for u in team if u is not holder])
            event.assignee, holder = (holder, after), after
            event.author = after if rng.random() < 0.6 else rng.choice(team)
            if state == "todo" and rng.random() < 0.3:  # "Assign to me" and start, in one go
                event.status, state = ("todo", "progress"), "progress"
        elif action == "advance":
            after = {"todo": "progress", "progress": "review", "review": "done"}[state]
            if state == "progress" and rng.random() < 0.4:
                after = "done"
            event.status, state = (state, after), after
            if rng.random() < 0.08:
                event.author = automation
        else:
            event.status, state = ("done", "progress"), "progress"
        issue.events.append(event)


def generate(seed: int = SEED, now: datetime = NOW) -> Site:
    """Generate the site for `seed`, with every issue's history up to `now`."""
    rng = random.Random(seed)
    users = []
    for name in PEOPLE:
        first, last = _ascii(name).lower().split(" ", 1)
        users.append(
            {
                "accountId": _account_id(rng),
                "accountType": "atlassian",
                "displayName": name,
                "emailAddress": f"{first}.{last.replace(' ', '')}@example.com",
                "active": name not in FORMER,
                "timeZone": TIME_ZONE,
            }
        )
    me = users[0]
    automation = {
        "accountId": _account_id(rng),
        "accountType": "app",
        "displayName": "Automation for Jira",
        "active": True,
    }
    members: dict[str, list[dict]] = {}
    issues: list[Issue] = []
    start = now - timedelta(days=120)
    for spec in PROJECT_SPECS:
        others = users[1:]
        rng.shuffle(others)
        team = [me, *others[: spec.members - 1]]
        members[spec.key] = [u for u in team if u["active"]]
        topics = spec.topics
        for number in range(1, spec.issues + 1):
            # Later issues come faster: most of the activity is in the last weeks.
            offset = timedelta(days=120 * (number / spec.issues) ** 0.7)
            created = _working_time(rng, start + offset - timedelta(hours=rng.uniform(0, 30)))
            if created >= now:
                created = now - timedelta(hours=rng.uniform(1, 20))
            issue = Issue(
                key=f"{spec.key}-{number}",
                project=spec,
                summary=f"{rng.choice(VERBS)} {rng.choice(topics)}",
                issue_type=rng.choices(ISSUE_TYPES, (4, 3, 2, 2))[0],
                created=created,
                created_with=rng.choice(spec.values) if rng.random() < 0.55 else None,
                assignee_at_create=rng.choice(team) if rng.random() < 0.5 else None,
            )
            _history(rng, issue, team, automation, now)
            issues.append(issue)
    return Site(users, me, automation, list(PROJECT_SPECS), members, issues, now)


# ── ground truth ─────────────────────────────────────────────────────────────


def _day_start(day: date, tz: Any) -> datetime:
    return datetime.combine(day, time(0, 0), tz)


@dataclass
class Truth:
    """What came into being in a period, per issue and per person, from the events."""

    per_issue: dict[str, float] = field(default_factory=dict)
    per_person: dict[str, float] = field(default_factory=dict)  # by display name
    per_day: dict[date, float] = field(default_factory=dict)
    touched: set[str] = field(default_factory=set)  # issues jtt's search should find
    changes: int = 0  # in-period edits, plus created-with values, as `export -k changes` rows

    @property
    def net(self) -> float:
        """Return the project's net over the period."""
        return sum(self.per_issue.values())


def truth(site: Site, project: str, first: date, end: date) -> Truth:
    """Return what the period [first, end) holds for `project`, as the generator made it.

    The same rules jtt documents: an estimate entered on the create screen counts when the
    issue was created in the period, credited to the first person ever assigned; every
    in-period change counts, credited to whoever held the issue then.
    """
    tz = site.now.tzinfo
    lo, hi = _day_start(first, tz), _day_start(end, tz)
    result = Truth()

    def credit(issue_key: str, person: dict | None, amount: float, day: date) -> None:
        result.per_day[day] = result.per_day.get(day, 0.0) + amount
        result.per_issue[issue_key] = result.per_issue.get(issue_key, 0.0) + amount
        name = person["displayName"] if person else "Unassigned"
        result.per_person[name] = result.per_person.get(name, 0.0) + amount

    for issue in site.issues:
        if issue.project.key != project:
            continue
        if issue.updated >= lo and issue.created < hi:
            result.touched.add(issue.key)
        if lo <= issue.created < hi and issue.created_with:
            first_holder = next((h for _, h in issue.holders() if h), None)
            credit(issue.key, first_holder, issue.created_with, issue.created.date())
            result.changes += 1
        for event in issue.events:
            if event.estimate and lo <= event.at < hi:
                before, after = event.estimate
                delta = (after or 0.0) - (before or 0.0)
                credit(issue.key, issue.holder_at(event.at), delta, event.at.date())
                result.changes += 1
    return result
