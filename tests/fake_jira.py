"""A local stand-in for Jira Cloud, serving data captured from a real site.

DEMO-727/729/730 replay the shape of real issues (timestamps, offsets, the
order and form of changelog items) with invented people and summaries; DEMO-729
is the case that exposed the `updated < end` bug. DEMO-900 is synthetic:
created with 2 SP on the create screen, bumped to 5, then reassigned. JQL is not
evaluated: the search returns every issue, and the tracker's own changelog walk
decides what is in the period.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

EMAIL = "dev@example.com"
TOKEN = "good-token"
ALICE = {
    "accountId": "70121:11111111-aaaa-4aaa-8aaa-111111111111",
    "displayName": "Alice Martin",
    "active": True,
}
BOB = {
    "accountId": "70121:22222222-bbbb-4bbb-8bbb-222222222222",
    "displayName": "Bob Jensen",
    "active": True,
    "emailAddress": EMAIL,
}
AUTOMATION = {
    "accountId": "557058:33333333-cccc-4ccc-8ccc-333333333333",
    "displayName": "Automation for Jira",
}

STATUSES = [
    {"id": "10102", "name": "To Do", "statusCategory": {"key": "new"}},
    {"id": "10103", "name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    {"id": "10104", "name": "Done", "statusCategory": {"key": "done"}},
]
DONE, PROGRESS, TODO = (
    {"name": "Done", "statusCategory": {"key": "done"}},
    {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    {"name": "To Do", "statusCategory": {"key": "new"}},
)
SUBTASK = {"id": "10109", "name": "Subtask"}


def sp(ts, who, frm=None, to=None):
    item = {"field": "Story point estimate", "fieldId": "customfield_10016"}
    if frm is not None:
        item["fromString"] = frm
    if to is not None:
        item["toString"] = to
    return {"created": ts, "author": who, "items": [item]}


def assign(ts, who, frm=None, to=None):
    item = {"field": "assignee", "fieldId": "assignee"}
    if frm:
        item.update({"from": frm["accountId"], "fromString": frm["displayName"]})
    if to:
        item.update({"to": to["accountId"], "toString": to["displayName"]})
    return {"created": ts, "author": who, "items": [item]}


def status(ts, who, frm, to):
    return {
        "created": ts,
        "author": who,
        "items": [{"field": "status", "fieldId": "status", "from": frm, "to": to}],
    }


ISSUES = [
    {
        "key": "DEMO-727",
        "fields": {
            "summary": "Publish and unpublish reports",
            "created": "2026-09-24T14:37:18.679+0100",
            "updated": "2026-09-25T14:07:50.860+0100",
            "status": DONE,
            "issuetype": SUBTASK,
            "assignee": ALICE,
            "customfield_10016": 3,
        },
    },
    {
        "key": "DEMO-729",
        "fields": {
            "summary": "Share a published report through a public link",
            "created": "2026-09-25T13:05:37.254+0100",
            "updated": "2026-09-28T10:26:45.824+0100",
            "status": DONE,
            "issuetype": SUBTASK,
            "assignee": ALICE,
            "customfield_10016": 8,
        },
    },
    {
        "key": "DEMO-730",
        "fields": {
            "summary": "Let a user duplicate a shared report into their own workspace",
            "created": "2026-09-25T13:21:27.019+0100",
            "updated": "2026-09-28T10:26:31.768+0100",
            "status": PROGRESS,
            "issuetype": SUBTASK,
            "assignee": ALICE,
            "customfield_10016": None,
        },
    },
    {
        "key": "DEMO-900",
        "fields": {
            "summary": "Synthetic: created with SP, later reassigned",
            "created": "2026-09-24T09:00:00.000+0100",
            "updated": "2026-09-27T10:00:00.000+0100",
            "status": TODO,
            "issuetype": {"id": "10001", "name": "Task"},
            "assignee": BOB,
            "customfield_10016": 5,
        },
    },
]
CHANGELOGS = {
    "DEMO-727": [
        assign("2026-09-24T14:37:30.768+0100", ALICE, to=ALICE),
        status("2026-09-24T14:37:27.290+0100", ALICE, "10102", "10103"),
        status("2026-09-25T13:08:46.128+0100", ALICE, "10103", "10104"),
        sp("2026-09-25T14:07:48.900+0100", ALICE, to="3"),
    ],
    "DEMO-729": [
        assign("2026-09-25T13:05:44.535+0100", ALICE, to=ALICE),
        status("2026-09-25T13:08:41.532+0100", ALICE, "10102", "10103"),
        sp("2026-09-25T14:50:52.116+0100", ALICE, to="5.5"),
        sp("2026-09-28T10:26:19.145+0100", ALICE, "5.5", "8"),
        status("2026-09-28T10:26:26.928+0100", ALICE, "10103", "10104"),
    ],
    "DEMO-730": [
        assign("2026-09-25T13:25:38.254+0100", ALICE, to=ALICE),
        status("2026-09-28T10:26:31.768+0100", ALICE, "10102", "10103"),
    ],
    "DEMO-900": [
        assign("2026-09-24T09:00:05.000+0100", ALICE, to=ALICE),
        sp("2026-09-24T16:00:00.000+0100", ALICE, "2", "5"),
        assign("2026-09-27T10:00:00.000+0100", BOB, frm=ALICE, to=BOB),
    ],
}
FIELDS = [
    {
        "id": "customfield_10016",
        "name": "Story point estimate",
        "custom": True,
        "schema": {"type": "number"},
    },
    {
        "id": "customfield_10028",
        "name": "Story Points",
        "custom": True,
        "schema": {"type": "number"},
    },
    {
        "id": "timeoriginalestimate",
        "name": "Original estimate",
        "custom": False,
        "schema": {"type": "number", "system": "timeoriginalestimate"},
    },
    {
        "id": "timespent",
        "name": "Time Spent",
        "custom": False,
        "schema": {"type": "number", "system": "timespent"},
    },
    {"id": "summary", "name": "Summary", "custom": False, "schema": {"type": "string"}},
]
PROJECTS = [
    {"id": "10050", "key": "DEMO", "name": "Demo App"},
    {"id": "10060", "key": "OPS", "name": "Operations"},
]


class Handler(BaseHTTPRequestHandler):
    requests_seen: ClassVar[list[str]] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        return self.headers.get("Authorization") == expected

    def _send(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self, method: str):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        Handler.requests_seen.append(f"{method} {path}")
        if not self._authorized():
            return self._send({"errorMessages": ["Client must be authenticated"]}, 401)
        api = "/rest/api/3"
        if path == f"{api}/myself":
            return self._send({**BOB, "timeZone": "Africa/Casablanca"})
        if path == f"{api}/configuration/timetracking/options":
            return self._send({"workingHoursPerDay": 8, "workingDaysPerWeek": 5})
        if path == f"{api}/project/search":
            return self._send({"values": PROJECTS, "isLast": True, "total": len(PROJECTS)})
        if path == f"{api}/field":
            return self._send(FIELDS)
        if path.startswith(f"{api}/issue/createmeta/"):
            parts = path.split("/")
            if parts[-1] == "issuetypes":
                return self._send({"issueTypes": [SUBTASK], "total": 1})
            return self._send(
                {
                    "fields": [
                        {"fieldId": "summary"},
                        {"fieldId": "customfield_10016"},
                        {"fieldId": "timetracking"},
                    ],
                    "total": 3,
                }
            )
        if path == f"{api}/status":
            return self._send(STATUSES)
        if path == f"{api}/user":
            account = query.get("accountId", [""])[0]
            match = next((u for u in (ALICE, BOB) if u["accountId"] == account), None)
            return self._send(match or {"errorMessages": ["no user"]}, 200 if match else 404)
        if path == f"{api}/user/assignable/search":
            return self._send([ALICE, BOB] if query.get("startAt", ["0"])[0] == "0" else [])
        if path == f"{api}/search/jql":
            return self._send({"issues": ISSUES, "isLast": True})
        if path == f"{api}/search/approximate-count":
            return self._send({"count": 3})
        if path.startswith(f"{api}/issue/") and path.endswith("/changelog"):
            values = CHANGELOGS[path.split("/")[-2]]
            return self._send(
                {"startAt": 0, "total": len(values), "isLast": True, "values": values}
            )
        return self._send({"errorMessages": [f"no route {path}"]}, 404)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self._route("POST")


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
