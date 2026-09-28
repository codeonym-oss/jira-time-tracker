"""Serve the simulated site: `python -m tests.jira_sim [--port 8765] [--seed 2026]`."""

import argparse

from tests.jira_sim.data import EMAIL, SEED, TOKEN, generate
from tests.jira_sim.server import SimServer

parser = argparse.ArgumentParser(prog="python -m tests.jira_sim", description=__doc__)
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--seed", type=int, default=SEED)
args = parser.parse_args()

server = SimServer(("127.0.0.1", args.port), generate(args.seed))
print(f"Simulated Jira on {server.url} · log in with {EMAIL} and the token {TOKEN}", flush=True)
server.serve_forever()
