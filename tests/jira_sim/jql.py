"""The JQL jtt sends, evaluated against generated issues.

Only `AND` of the clauses below; anything else raises `JqlError`, which the server answers
with a 400 as Jira does, so a new query shape in jtt fails loudly here instead of silently
matching everything. Date literals are read in the site's time zone, as Jira reads them.
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.jira_sim.data import Issue, Site


class JqlError(ValueError):
    """A query this simulator does not understand."""


def _moment(site: Site, literal: str) -> datetime:
    literal = literal.strip().strip('"')
    relative = re.fullmatch(r"-(\d+)([dwh])", literal)
    if relative:
        amount, unit = int(relative[1]), relative[2]
        span = {"d": timedelta(days=amount), "w": timedelta(weeks=amount)}.get(
            unit, timedelta(hours=amount)
        )
        return site.now - span
    for layout in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(literal, layout).replace(tzinfo=site.now.tzinfo)
    raise JqlError(f"not a date: {literal!r}")


def _field_value(issue: Issue, ref: str) -> float | None:
    custom = re.fullmatch(r"cf\[(\d+)\]", ref)
    field_id = f"customfield_{custom[1]}" if custom else ref
    return issue.estimate if field_id == issue.project.field_id else None


def _clause(site: Site, text: str) -> Callable[[Issue], bool]:
    text = text.strip()
    if m := re.fullmatch(r"project\s*=\s*\"?(\w+)\"?", text, re.IGNORECASE):
        key = m[1].upper()
        return lambda issue: issue.project.key == key
    if m := re.fullmatch(r"(updated|created)\s*(>=|<|>|<=)\s*(.+)", text, re.IGNORECASE):
        name, op, bound = m[1].lower(), m[2], _moment(site, m[3])
        compare = {
            ">=": lambda a: a >= bound,
            ">": lambda a: a > bound,
            "<": lambda a: a < bound,
            "<=": lambda a: a <= bound,
        }[op]
        return lambda issue: compare(issue.updated if name == "updated" else issue.created)
    if m := re.fullmatch(r"assignee\s+is\s+(not\s+)?EMPTY", text, re.IGNORECASE):
        wanted = bool(m[1])
        return lambda issue: (issue.assignee is not None) == wanted
    if m := re.fullmatch(r"(\S+)\s+is\s+(not\s+)?EMPTY", text, re.IGNORECASE):
        ref, wanted = m[1], bool(m[2])
        return lambda issue: (_field_value(issue, ref) is not None) == wanted
    if m := re.fullmatch(
        r'assignee\s+WAS\s+"([^"]+)"\s+DURING\s*\(\s*("[^"]+")\s*,\s*("[^"]+")\s*\)',
        text,
        re.IGNORECASE,
    ):
        account, lo, hi = m[1], _moment(site, m[2]), _moment(site, m[3])

        def held(issue: Issue) -> bool:
            spans = issue.holders()
            for (since, holder), nxt in zip(spans, [*spans[1:], (None, None)], strict=True):
                until = nxt[0] or datetime.max.replace(tzinfo=since.tzinfo)
                if holder and holder["accountId"] == account and since < hi and until > lo:
                    return True
            return False

        return held
    raise JqlError(f"the simulator does not understand the JQL clause {text!r}")


def compile_jql(site: Site, jql: str) -> Callable[[Issue], bool]:
    """Return a predicate for `jql`, or raise JqlError."""
    clauses = [_clause(site, part) for part in re.split(r"\s+AND\s+", jql.strip(), flags=re.I)]
    return lambda issue: all(clause(issue) for clause in clauses)
