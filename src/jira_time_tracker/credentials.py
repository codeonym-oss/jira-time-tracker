"""Where the API token lives.

First choice is the operating system's credential store through `keyring`:
Windows Credential Manager, macOS Keychain, or the Secret Service (GNOME
Keyring, KWallet) on Linux. When none is usable — a headless server, WSL, a
container — the token goes to `credentials.json` in the config directory,
created 0600 inside a 0700 directory.

JTT_CREDENTIAL_BACKEND=file|keyring forces a backend. JTT_API_TOKEN, when set,
is used instead of the stored token (for CI), and is never stored.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from jira_time_tracker.config import config_dir, write_private_file

if TYPE_CHECKING:
    from pathlib import Path

SERVICE = "jira-time-tracker"
KEYRING = "keyring"
FILE = "file"


class CredentialError(RuntimeError):
    """The token could not be stored or read."""


def _username(site: str, email: str) -> str:
    return f"{email}@{site}"


def _credentials_file() -> Path:
    return config_dir() / "credentials.json"


def _keyring_usable() -> bool:
    if os.environ.get("JTT_CREDENTIAL_BACKEND", "").lower() == FILE:
        return False
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return False
        # A chainer with no real backends behind it cannot store anything.
        return getattr(backend, "priority", 1) > 0
    except Exception:
        return False


def save_token(site: str, email: str, token: str) -> str:
    """Store the token, returning the backend used ('keyring' or 'file')."""
    forced = os.environ.get("JTT_CREDENTIAL_BACKEND", "").lower()
    if forced == KEYRING and not _keyring_usable():
        raise CredentialError(
            "JTT_CREDENTIAL_BACKEND=keyring but no usable keyring backend was found"
        )
    if _keyring_usable():
        try:
            import keyring

            keyring.set_password(SERVICE, _username(site, email), token)
            return KEYRING
        except Exception:
            if forced == KEYRING:
                raise
    path = _credentials_file()
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stored[_username(site, email)] = token
    write_private_file(path, json.dumps(stored, indent=2) + "\n")
    return FILE


def load_token(site: str, email: str, backend: str) -> str | None:
    """Return the stored token (or JTT_API_TOKEN), or None when there is none."""
    if env := os.environ.get("JTT_API_TOKEN"):
        return env
    if backend == KEYRING:
        try:
            import keyring

            return keyring.get_password(SERVICE, _username(site, email))
        except Exception as error:
            raise CredentialError(
                f"could not read the token from the system keyring: {error}"
            ) from error
    path = _credentials_file()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get(_username(site, email))


def delete_token(site: str, email: str) -> None:
    """Remove the token from every backend it may be in."""
    try:
        import keyring

        keyring.delete_password(SERVICE, _username(site, email))
    except Exception:
        pass
    path = _credentials_file()
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored.pop(_username(site, email), None)
        if stored:
            write_private_file(path, json.dumps(stored, indent=2) + "\n")
        else:
            path.unlink()


def describe(backend: str) -> str:
    """Return a human description of where the token is kept."""
    if backend == KEYRING:
        try:
            import keyring

            return f"system keyring ({type(keyring.get_keyring()).__module__.split('.')[-1]})"
        except Exception:
            return "system keyring"
    return f"{_credentials_file()} (owner-only file)"
