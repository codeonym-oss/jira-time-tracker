"""Write report rows to CSV, JSON or Markdown."""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from pathlib import Path

    from jira_time_tracker.render import Amounts
    from jira_time_tracker.tracking import Contribution, IssueReport

KINDS = ("issues", "changes", "contributions", "daily")
FORMATS = ("csv", "json", "md")


def _iso(moment: datetime | None) -> str:
    return moment.isoformat() if moment else ""


def _num(amounts: Amounts, raw: float) -> float:
    return round(amounts.value(raw), 4)


def issue_rows(
    reports: list[IssueReport], amounts: Amounts, deltas: dict[str, float]
) -> list[dict]:
    """Return one row per issue, with its delta in the report's unit."""
    return [
        {
            "key": r.key,
            "summary": r.summary,
            "type": r.issue_type,
            "status": r.status,
            "assignee": r.assignee.name,
            "assignee_id": r.assignee.account_id,
            "created": _iso(r.created),
            "value_now": _num(amounts, r.current_value),
            "created_with": _num(amounts, r.created_with) if r.created_with is not None else "",
            "changes_in_period": len(r.in_period),
            "delta": _num(amounts, deltas[r.key]),
            "completed_at": _iso(r.completed_at),
        }
        for r in sorted(reports, key=lambda r: r.key)
    ]


def change_rows(reports: list[IssueReport], amounts: Amounts) -> list[dict]:
    """Return one row per in-period change, created-with values included."""
    rows = []
    for r in sorted(reports, key=lambda r: r.key):
        if r.created_with:
            rows.append(
                {
                    "key": r.key,
                    "at": _iso(r.created),
                    "kind": "created",
                    "author": "",
                    "holder": r.first_holder.name,
                    "holder_id": r.first_holder.account_id,
                    "before": 0,
                    "after": _num(amounts, r.created_with),
                    "delta": _num(amounts, r.created_with),
                }
            )
        rows.extend(
            {
                "key": r.key,
                "at": _iso(c.at),
                "kind": "edit",
                "author": c.author,
                "holder": c.holder.name,
                "holder_id": c.holder.account_id,
                "before": _num(amounts, c.before),
                "after": _num(amounts, c.after),
                "delta": _num(amounts, c.delta),
            }
            for c in r.in_period
        )
    return rows


def contribution_rows(people: list[Contribution], amounts: Amounts) -> list[dict]:
    """Return one row per credited person."""
    return [
        {
            "person": p.name,
            "account_id": p.account_id,
            "net": _num(amounts, p.net),
            "added": _num(amounts, p.added),
            "removed": _num(amounts, p.removed),
            "issues": len(p.issues),
            "created": p.created_count,
            "created_value": _num(amounts, p.created_value),
            "done": p.completed_count,
            "done_value": _num(amounts, p.completed_value),
        }
        for p in people
    ]


def daily_rows(series: dict[date, float], amounts: Amounts) -> list[dict]:
    """Return one row per day of the period."""
    return [{"day": day.isoformat(), "net": _num(amounts, value)} for day, value in series.items()]


def infer_format(path: Path, explicit: str | None) -> str:
    """Return the explicit format, or the one the file extension implies."""
    if explicit:
        return explicit
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "markdown":
        return "md"
    if suffix not in FORMATS:
        raise ValueError(
            f"cannot tell the format from {path.name!r}; pass --format {'|'.join(FORMATS)}"
        )
    return suffix


def write(path: Path, fmt: str, rows: list[dict], meta: dict) -> None:
    """Write `rows` and `meta` to `path` as CSV, JSON or Markdown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0]) if rows else []
    if fmt == "json":
        path.write_text(
            json.dumps({"meta": meta, "rows": rows}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif fmt == "csv":
        # utf-8-sig so Excel on Windows opens accented names correctly.
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "md":
        lines = [f"# {meta['title']}", ""]
        lines += [
            f"- **{k.replace('_', ' ').capitalize()}:** {v}"
            for k, v in meta.items()
            if k != "title"
        ]
        lines.append("")
        if rows:
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("|" + "|".join("---" for _ in columns) + "|")
            lines.extend(
                "| " + " | ".join(str(row[c]).replace("|", "\\|") for c in columns) + " |"
                for row in rows
            )
        else:
            lines.append("_No rows._")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"unknown format {fmt!r}")
