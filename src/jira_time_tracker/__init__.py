"""Track how much estimated work came into being in a Jira project over a period."""

from importlib.metadata import version

__version__: str = version("jira-time-tracker")

__all__ = ["__version__"]
