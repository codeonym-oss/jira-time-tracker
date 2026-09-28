import os
import stat

import pytest

from jira_time_tracker import credentials
from jira_time_tracker.config import config_dir


def test_file_backend_round_trip_and_delete():
    assert credentials.save_token("site.atlassian.net", "a@b.c", "secret") == credentials.FILE
    assert credentials.load_token("site.atlassian.net", "a@b.c", credentials.FILE) == "secret"
    credentials.delete_token("site.atlassian.net", "a@b.c")
    assert credentials.load_token("site.atlassian.net", "a@b.c", credentials.FILE) is None
    assert not (config_dir() / "credentials.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_file_backend_is_owner_only():
    credentials.save_token("site.atlassian.net", "a@b.c", "secret")
    path = config_dir() / "credentials.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_env_token_wins_and_is_never_stored(monkeypatch):
    monkeypatch.setenv("JTT_API_TOKEN", "from-env")
    assert credentials.load_token("site", "a@b.c", credentials.FILE) == "from-env"
    assert not (config_dir() / "credentials.json").exists()
