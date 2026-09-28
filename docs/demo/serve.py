"""Serve the test suite's fake Jira on a fixed port for the README demo.

The data is fictional. Two tweaks, made here in memory so the tests' data stays as it is:
a real-looking summary for the synthetic issue, and DEMO-727 handed to Bob so that the
contributions table credits two people.
"""

import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import fake_jira

for issue in fake_jira.ISSUES:
    if issue["key"] == "DEMO-900":
        issue["fields"]["summary"] = "Export a report as PDF"
    if issue["key"] == "DEMO-727":
        issue["fields"]["assignee"] = fake_jira.BOB
for entry in fake_jira.CHANGELOGS["DEMO-727"]:
    entry["author"] = fake_jira.BOB
    for item in entry["items"]:
        if item["field"] == "assignee":
            item.update(to=fake_jira.BOB["accountId"], toString=fake_jira.BOB["displayName"])

ThreadingHTTPServer(("127.0.0.1", 8765), fake_jira.Handler).serve_forever()
