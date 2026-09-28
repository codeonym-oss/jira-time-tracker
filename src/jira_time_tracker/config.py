r"""Non-secret settings: the logged-in site and, per project, the tracked field.

Stored as JSON in the user config directory (JTT_CONFIG_DIR overrides it):
  Linux    ~/.config/jira-time-tracker/config.json
  macOS    ~/Library/Application Support/jira-time-tracker/config.json
  Windows  %LOCALAPPDATA%\\jira-time-tracker\\config.json
The API token is never written here; see credentials.py.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_dir

from jira_time_tracker.units import Unit, WorkCalendar

APP_NAME = "jira-time-tracker"
CONFIG_VERSION = 1


def config_dir() -> Path:
    """Return the settings directory (JTT_CONFIG_DIR overrides the platform default)."""
    override = os.environ.get("JTT_CONFIG_DIR")
    return Path(override) if override else Path(user_config_dir(APP_NAME, appauthor=False))


def ensure_private_dir(path: Path) -> Path:
    """Create `path` if needed, owner-only on POSIX."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(stat.S_IRWXU)
    return path


def write_private_file(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, readable by the owner only.

    0600 on POSIX; on Windows the per-user profile directory's ACL is what keeps it private.
    """
    ensure_private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        if os.name == "posix":
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class ProjectConfig:
    """Which field a project tracks and in what units."""

    field_id: str
    field_name: str
    # What the field's raw numbers mean. Built-in time tracking fields hold seconds.
    unit: Unit
    # What reports show; only differs from `unit` for time units.
    display_unit: Unit

    @classmethod
    def from_json(cls, data: dict) -> ProjectConfig:
        """Build from the saved JSON form."""
        unit = Unit(data["unit"])
        return cls(
            data["field_id"], data["field_name"], unit, Unit(data.get("display_unit", unit.value))
        )

    def to_json(self) -> dict:
        """Return the JSON form saved in config.json."""
        return {
            "field_id": self.field_id,
            "field_name": self.field_name,
            "unit": self.unit.value,
            "display_unit": self.display_unit.value,
        }


@dataclass
class SiteConfig:
    """The logged-in account on one Jira site, and its projects' settings."""

    url: str
    email: str = ""
    account_id: str = ""
    display_name: str = ""
    time_zone: str = ""
    token_backend: str = ""
    hours_per_day: float = 8.0
    days_per_week: float = 5.0
    default_project: str | None = None
    projects: dict[str, ProjectConfig] = field(default_factory=dict)

    @property
    def logged_in(self) -> bool:
        """Return whether a token is stored for this site."""
        return bool(self.email and self.token_backend)

    @property
    def calendar(self) -> WorkCalendar:
        """Return the site's working day and week."""
        return WorkCalendar(self.hours_per_day, self.days_per_week)

    @classmethod
    def from_json(cls, data: dict) -> SiteConfig:
        """Build from the saved JSON form, ignoring unknown keys."""
        projects = {
            key: ProjectConfig.from_json(value) for key, value in data.get("projects", {}).items()
        }
        plain = {k: v for k, v in data.items() if k != "projects" and k in cls.__dataclass_fields__}
        return cls(**plain, projects=projects)

    def to_json(self) -> dict:
        """Return the JSON form saved in config.json."""
        data = asdict(self)
        data["projects"] = {key: value.to_json() for key, value in self.projects.items()}
        return data


@dataclass
class Config:
    """Every site the user has logged in to, and which one is active."""

    active_site: str | None = None
    sites: dict[str, SiteConfig] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        """Return the path of config.json."""
        return config_dir() / "config.json"

    @property
    def site(self) -> SiteConfig | None:
        """Return the active site, if any."""
        return self.sites.get(self.active_site) if self.active_site else None

    @classmethod
    def load(cls) -> Config:
        """Read config.json, or return an empty config when there is none."""
        path = config_dir() / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        sites = {host: SiteConfig.from_json(site) for host, site in data.get("sites", {}).items()}
        return cls(active_site=data.get("active_site"), sites=sites)

    def save(self) -> None:
        """Write config.json atomically, owner-only."""
        data = {
            "version": CONFIG_VERSION,
            "active_site": self.active_site,
            "sites": {host: site.to_json() for host, site in self.sites.items()},
        }
        write_private_file(self.path, json.dumps(data, indent=2) + "\n")
