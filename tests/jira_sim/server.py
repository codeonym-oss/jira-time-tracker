"""Serve a generated site over the Jira Cloud REST v3 endpoints jtt reads.

Responses have Jira's shapes, and pages are small on purpose (Jira's own limits are larger),
so every paging loop in jtt runs.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlparse

from tests.jira_sim.data import EMAIL, FIELD_NAMES, FIELDS, ISSUE_TYPES, STATUSES, TOKEN, generate
from tests.jira_sim.jql import JqlError, compile_jql

if TYPE_CHECKING:
    from datetime import datetime

    from tests.jira_sim.data import Event, Issue, ProjectSpec, Site

SEARCH_PAGE = 40
CHANGELOG_PAGE = 5
PROJECTS_PAGE = 2
API = "/rest/api/3"


def stamp(moment: datetime) -> str:
    """Format a timestamp the way Jira does: '2026-09-24T14:37:18.679+0100'."""
    return (
        moment.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{moment.microsecond // 1000:03d}"
        + (moment.strftime("%z"))
    )


def _user(user: dict | None) -> dict | None:
    if user is None:
        return None
    return {k: user[k] for k in ("accountId", "accountType", "displayName", "active") if k in user}


def _status(key: str) -> dict:
    status = STATUSES[key]
    return {
        "id": status["id"],
        "name": status["name"],
        "statusCategory": {"key": status["category"]},
    }


def _number(value: float | None) -> str | None:
    return None if value is None else f"{value:g}"


def _estimate_item(spec: ProjectSpec, before: float | None, after: float | None) -> dict:
    """Custom number fields fill only the strings; time tracking fills both, in seconds."""
    time_tracking = not spec.field_id.startswith("customfield_")
    return {
        "field": spec.field_id if time_tracking else FIELD_NAMES[spec.field_id],
        "fieldtype": "jira" if time_tracking else "custom",
        "fieldId": spec.field_id,
        "from": _number(before) if time_tracking else None,
        "fromString": _number(before),
        "to": _number(after) if time_tracking else None,
        "toString": _number(after),
    }


def changelog_entry(issue: Issue, index: int, event: Event) -> dict:
    """Return the changelog entry Jira would hold for `event`."""
    items = []
    if event.estimate:
        items.append(_estimate_item(issue.project, *event.estimate))
    if event.assignee:
        before, after = event.assignee
        items.append(
            {
                "field": "assignee",
                "fieldtype": "jira",
                "fieldId": "assignee",
                "from": before["accountId"] if before else None,
                "fromString": before["displayName"] if before else None,
                "to": after["accountId"] if after else None,
                "toString": after["displayName"] if after else None,
            }
        )
    if event.status:
        before, after = (STATUSES[s] for s in event.status)
        items.append(
            {
                "field": "status",
                "fieldtype": "jira",
                "fieldId": "status",
                "from": before["id"],
                "fromString": before["name"],
                "to": after["id"],
                "toString": after["name"],
            }
        )
    return {
        "id": str(100000 + index),
        "author": _user(event.author),
        "created": stamp(event.at),
        "items": items,
    }


def issue_json(issue: Issue, fields: list[str] | None) -> dict:
    """Return the issue as the search endpoint returns it, with only `fields`."""
    every: dict[str, Any] = {
        "summary": issue.summary,
        "created": stamp(issue.created),
        "updated": stamp(issue.updated),
        "status": _status(issue.status),
        "issuetype": issue.issue_type,
        "assignee": _user(issue.assignee),
        "project": {"key": issue.project.key, "name": issue.project.name},
        issue.project.field_id: issue.estimate,
    }
    wanted = every if not fields or "*all" in fields else {f: every.get(f) for f in fields}
    return {"id": issue.key.split("-")[1], "key": issue.key, "fields": wanted}


class SimServer(ThreadingHTTPServer):
    """An HTTP server holding the site it serves."""

    daemon_threads = True
    # jtt opens up to 32 connections at once; the default backlog (5) drops the rest, which
    # then wait a second to retry.
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], site: Site) -> None:
        super().__init__(address, Handler)
        self.site = site
        self.requests_seen: list[str] = []

    @property
    def url(self) -> str:
        """Return the base URL to log in with."""
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    """Routes one request to the site."""

    @property
    def sim(self) -> SimServer:
        """Return the server, with its site."""
        return cast("SimServer", self.server)

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, body: object, code: int = 200) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, message: str) -> None:
        self._send({"errorMessages": [message], "errors": {}}, code)

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        return self.headers.get("Authorization") == expected

    def do_GET(self) -> None:
        self._handle("GET", None)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self._handle("POST", json.loads(self.rfile.read(length) or b"{}"))

    def _handle(self, method: str, body: dict | None) -> None:
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.sim.requests_seen.append(f"{method} {url.path}")
        if not self._authorized():
            self._error(401, "Client must be authenticated to access this resource.")
            return
        try:
            self._route(url.path, query, body or {})
        except JqlError as error:
            self._error(400, str(error))

    def _route(self, path: str, query: dict[str, str], body: dict) -> None:
        site = self.sim.site
        start = int(query.get("startAt", 0))
        if path == f"{API}/myself":
            return self._send(site.me)
        if path == f"{API}/configuration/timetracking/options":
            return self._send({"workingHoursPerDay": 8, "workingDaysPerWeek": 5})
        if path == f"{API}/project/search":
            ordered = sorted(site.projects, key=lambda p: p.key)  # jtt asks orderBy=key
            page = ordered[start : start + PROJECTS_PAGE]
            return self._send(
                {
                    "startAt": start,
                    "total": len(site.projects),
                    "isLast": start + len(page) >= len(site.projects),
                    "values": [
                        {"id": str(10000 + i), "key": p.key, "name": p.name}
                        for i, p in enumerate(page, start)
                    ],
                }
            )
        if path == f"{API}/field":
            return self._send(FIELDS)
        if path.startswith(f"{API}/issue/createmeta/"):
            return self._createmeta(path.split("/")[6:], start)
        if path == f"{API}/status":
            return self._send([_status(k) for k in STATUSES])
        if path == f"{API}/user":
            user = next((u for u in site.users if u["accountId"] == query.get("accountId")), None)
            if user is None:
                return self._error(404, "Specified user does not exist or you do not have access")
            return self._send(user)
        if path == f"{API}/user/assignable/search":
            members = site.members.get(query.get("project", "").upper(), [])
            size = min(int(query.get("maxResults", 50)), 1000)
            return self._send(members[start : start + size])
        if path == f"{API}/search/jql":
            return self._search(body)
        if path == f"{API}/search/approximate-count":
            match = compile_jql(site, body.get("jql", ""))
            return self._send({"count": sum(1 for i in site.issues if match(i))})
        if path.startswith(f"{API}/issue/") and path.endswith("/changelog"):
            return self._changelog(path.split("/")[-2], start)
        return self._error(404, f"No route for {path}")

    def _createmeta(self, parts: list[str], start: int) -> None:
        site = self.sim.site
        key = parts[0].upper()
        spec = next((p for p in site.projects if p.key == key), None)
        if spec is None or parts[1:2] != ["issuetypes"]:
            return self._error(404, f"No project could be found with key '{parts[0]}'.")
        if len(parts) == 2:
            return self._send({"issueTypes": ISSUE_TYPES, "total": len(ISSUE_TYPES)})
        ids = ["summary", "issuetype", "assignee", spec.field_id, *spec.also_on_screen]
        if spec.field_id in {"timeoriginalestimate"}:
            ids.append("timetracking")
        fields = [{"fieldId": i, "name": FIELD_NAMES.get(i, i)} for i in ids]
        return self._send({"fields": fields[start:], "total": len(fields), "startAt": start})

    def _search(self, body: dict) -> None:
        site = self.sim.site
        match = compile_jql(site, body.get("jql", ""))
        found = sorted((i for i in site.issues if match(i)), key=lambda i: i.updated, reverse=True)
        offset = int(body.get("nextPageToken") or 0)
        size = min(int(body.get("maxResults", 50)), SEARCH_PAGE)
        page = found[offset : offset + size]
        response: dict[str, Any] = {
            "issues": [issue_json(i, body.get("fields")) for i in page],
            "isLast": offset + size >= len(found),
        }
        if not response["isLast"]:
            response["nextPageToken"] = str(offset + size)
        return self._send(response)

    def _changelog(self, key: str, start: int) -> None:
        issue = next((i for i in self.sim.site.issues if i.key == key), None)
        if issue is None:
            return self._error(404, "Issue does not exist or you do not have permission to see it.")
        entries = [changelog_entry(issue, n, e) for n, e in enumerate(issue.events)]
        page = entries[start : start + CHANGELOG_PAGE]
        return self._send(
            {
                "startAt": start,
                "maxResults": CHANGELOG_PAGE,
                "total": len(entries),
                "isLast": start + len(page) >= len(entries),
                "values": page,
            }
        )


def start(site: Site | None = None, port: int = 0) -> SimServer:
    """Serve `site` (the default seed's when None) on a background thread."""
    server = SimServer(("127.0.0.1", port), site or generate())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
