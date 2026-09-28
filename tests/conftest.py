from __future__ import annotations

import pytest

from tests import fake_jira


@pytest.fixture(scope="session")
def jira_url():
    server, url = fake_jira.start()
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own config directory and the file credential backend."""
    monkeypatch.setenv("JTT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("JTT_CREDENTIAL_BACKEND", "file")
    monkeypatch.delenv("JTT_API_TOKEN", raising=False)
    monkeypatch.setenv("COLUMNS", "200")
    return tmp_path
