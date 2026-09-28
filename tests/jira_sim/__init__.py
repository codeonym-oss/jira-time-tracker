"""A simulated Jira Cloud site with generated, fictional data, for the tests and the docs.

`python -m tests.jira_sim` serves it; see `docs/tapes/README.md`.
"""

from tests.jira_sim.data import EMAIL, NOW, SEED, TOKEN, Site, generate, truth
from tests.jira_sim.server import SimServer, start

__all__ = ["EMAIL", "NOW", "SEED", "TOKEN", "SimServer", "Site", "generate", "start", "truth"]
