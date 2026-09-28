"""A thin Jira Cloud REST v3 client covering what the tracker reads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

PAGE_SIZE = 100
TIMEOUT = 30


class JiraError(RuntimeError):
    """A Jira request failed."""


class AuthError(JiraError):
    """Jira rejected the credentials."""


def normalize_url(url: str) -> str:
    """Return the site URL with a scheme and no trailing slash."""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def site_host(url: str) -> str:
    """Return the host part of a site URL, used as the site's key."""
    return normalize_url(url).split("://", 1)[1].split("/", 1)[0]


class JiraClient:
    """The few Jira Cloud REST v3 reads the tracker needs, with retries."""

    def __init__(
        self,
        base_url: str,
        email: str,
        token: str,
        on_response: Callable[[requests.Response], None] | None = None,
        workers: int = 8,
    ) -> None:
        self.base_url = normalize_url(base_url)
        self.workers = max(1, workers)
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, token)
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": "jira-time-tracker"}
        )
        # Jira Cloud rate-limits with 429 + Retry-After; honour it, and ride out 5xx blips.
        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=self.workers)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        if on_response:
            self.session.hooks["response"].append(lambda resp, *args, **kwargs: on_response(resp))

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()

    # ── transport ────────────────────────────────────────────────────────────

    # Jira's JSON is untyped; callers read the few keys they need.
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self.session.request(method, f"{self.base_url}{path}", timeout=TIMEOUT, **kwargs)
        except requests.RequestException as error:
            raise JiraError(f"could not reach {self.base_url}: {error}") from error
        if resp.status_code == 401:
            raise AuthError(
                "Jira rejected the credentials (401). "
                "Run `jtt logout` then `jtt login` with a fresh API token."
            )
        if not resp.ok:
            raise JiraError(f"{method} {path} failed with {resp.status_code}: {_error_text(resp)}")
        return resp.json() if resp.content else None

    def get(self, path: str, **params: Any) -> Any:
        """GET a JSON resource."""
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        """POST a JSON body and return the JSON response."""
        return self._request("POST", path, json=body)

    # ── identity and site ────────────────────────────────────────────────────

    def myself(self) -> dict:
        """Return the calling account's profile."""
        return self.get("/rest/api/3/myself")

    def time_tracking_calendar(self) -> tuple[float, float]:
        """(hours per day, days per week) from the site's time tracking settings."""
        try:
            data = self.get("/rest/api/3/configuration/timetracking/options")
            return float(data.get("workingHoursPerDay", 8)), float(
                data.get("workingDaysPerWeek", 5)
            )
        except JiraError:
            return 8.0, 5.0

    # ── projects and fields ──────────────────────────────────────────────────

    def projects(self) -> list[dict]:
        """Return every project the account can see."""
        projects: list[dict] = []
        start = 0
        while True:
            data = self.get(
                "/rest/api/3/project/search", startAt=start, maxResults=50, orderBy="key"
            )
            page = data.get("values", [])
            projects.extend(page)
            start += len(page)
            if not page or data.get("isLast", start >= data.get("total", 0)):
                return projects

    def fields(self) -> list[dict]:
        """Return every field on the site."""
        return self.get("/rest/api/3/field")

    def project_field_ids(self, project: str) -> set[str]:
        """Ids of the fields on any of the project's create screens."""
        ids: set[str] = set()
        types = self._paged_createmeta(
            f"/rest/api/3/issue/createmeta/{project}/issuetypes", ("issueTypes", "values")
        )
        for issue_type in types:
            fields = self._paged_createmeta(
                f"/rest/api/3/issue/createmeta/{project}/issuetypes/{issue_type['id']}",
                ("fields", "results", "values"),
            )
            ids.update(i for f in fields if (i := f.get("fieldId") or f.get("key")))
        return ids

    def _paged_createmeta(self, path: str, keys: tuple[str, ...]) -> list[dict]:
        items: list[dict] = []
        start = 0
        while True:
            data = self.get(path, startAt=start, maxResults=200)
            page = next((data[k] for k in keys if k in data), [])
            items.extend(page)
            start += len(page)
            if not page or start >= data.get("total", start):
                return items

    def statuses(self) -> dict[str, str]:
        """Status id → status category key ('new', 'indeterminate', 'done')."""
        return {
            s["id"]: (s.get("statusCategory") or {}).get("key", "")
            for s in self.get("/rest/api/3/status")
        }

    # ── users ────────────────────────────────────────────────────────────────

    def user(self, account_id: str) -> dict | None:
        """Return an account's profile, or None when it cannot be read."""
        try:
            return self.get("/rest/api/3/user", accountId=account_id)
        except JiraError:
            return None

    def assignable_users(self, project: str) -> list[dict]:
        """Return everyone who can be assigned issues in `project`."""
        users: list[dict] = []
        start = 0
        while True:
            page = self.get(
                "/rest/api/3/user/assignable/search",
                project=project,
                startAt=start,
                maxResults=PAGE_SIZE,
            )
            users.extend(page)
            start += len(page)
            if len(page) < PAGE_SIZE:
                return users

    # ── issues ───────────────────────────────────────────────────────────────

    def search(self, jql: str, fields: Iterable[str]) -> list[dict]:
        """Return every issue matching `jql`, with only `fields`."""
        issues: list[dict] = []
        token: str | None = None
        while True:
            body: dict[str, object] = {"jql": jql, "maxResults": PAGE_SIZE, "fields": list(fields)}
            if token:
                body["nextPageToken"] = token
            data = self.post("/rest/api/3/search/jql", body)
            issues.extend(data.get("issues", []))
            token = data.get("nextPageToken")
            if not token or data.get("isLast", False):
                return issues

    def approximate_count(self, jql: str) -> int | None:
        """Return Jira's approximate count of issues matching `jql`."""
        try:
            return self.post("/rest/api/3/search/approximate-count", {"jql": jql}).get("count")
        except JiraError:
            return None

    def changelog(self, key: str) -> list[dict]:
        """Every changelog entry for an issue, oldest first."""
        entries: list[dict] = []
        start = 0
        while True:
            data = self.get(
                f"/rest/api/3/issue/{key}/changelog", startAt=start, maxResults=PAGE_SIZE
            )
            page = data.get("values", [])
            entries.extend(page)
            start += len(page)
            if not page or data.get("isLast", start >= data.get("total", 0)):
                return entries

    def changelogs(
        self, keys: list[str], on_done: Callable[[str], None] | None = None
    ) -> dict[str, list[dict]]:
        """Read several changelogs in parallel, keyed by issue key."""

        def one(key: str) -> tuple[str, list[dict]]:
            entries = self.changelog(key)
            if on_done:
                on_done(key)
            return key, entries

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return dict(pool.map(one, keys))


def _error_text(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] or resp.reason
    messages = list(data.get("errorMessages", [])) + [
        f"{k}: {v}" for k, v in (data.get("errors") or {}).items()
    ]
    return "; ".join(messages) or resp.reason
