# The simulated Jira

The tests, the recordings and the examples in these docs all run the real `jtt` against a
simulated Jira Cloud site, `tests/jira_sim`, never against a real one. Everything on it is
invented: the people, the projects, the issues and their histories.

## The site

A seeded generator builds the site, so the same seed always gives the same data:

| Project | Tracks | Issues | People |
|---|---|---|---|
| `DEMO` Demo App | Story point estimate (`customfield_10016`), points | 150 | 8 |
| `WEB` Website | Story Points (`customfield_10028`), points | 90 | 6 |
| `OPS` Operations | Original estimate (`timeoriginalestimate`), seconds | 80 | 5 |
| `DATA` Analytics | Effort (days) (`customfield_10041`), days | 40 | 4 |

Thirteen people share the projects, and one of them has left: still in the histories, no
longer assignable. Over the 120 days up to Monday 28 September 2026, each issue is created,
sometimes with an estimate and an assignee, then goes through estimates, re-estimates,
reassignments and status changes, a few made by an automation account. You log in as
Robin Hale.

The server answers the Jira Cloud REST v3 endpoints `jtt` uses, with Jira's response shapes.
It evaluates the JQL `jtt` sends, and answers any other query with an error, as Jira does, so a
new query in `jtt` fails the tests instead of silently matching everything. Its pages are
smaller than Jira's, so that every paging loop in `jtt` runs.

## Checked against the generator

The generator keeps each issue's history as the events it decided, next to the Jira changelog
it serves. `jira_sim.truth()` computes each report's answer from those events, never from the
changelog `jtt` reads, and `tests/test_commands.py` holds `jtt`'s numbers against it: per issue,
per person, per day and per change, for every project over several periods.

## Running it

```sh
uv run python -m tests.jira_sim                 # on http://127.0.0.1:8765; --port, --seed
```

Then, in another terminal, with settings kept apart from your real ones:

```sh
export JTT_CONFIG_DIR=/tmp/jtt-sim JTT_CREDENTIAL_BACKEND=file
uv run jtt login --url http://127.0.0.1:8765 --email robin.hale@example.com --token sim-token
uv run jtt init
```

## The recordings

Each command's GIF is recorded with [VHS](https://github.com/charmbracelet/vhs) from a tape in
`docs/tapes/`, named after the command's page. The tapes run a wheel built from the working
tree, in Docker, against the simulator. To record them all, or only the ones named:

```sh
docs/tapes/record.sh
docs/tapes/record.sh calculate config-show
```

Re-record the affected GIFs when a command's output changes. The tests check that every
command has a page, a tape and a GIF, that the page's options match the CLI, and that every
`$ jtt …` line of a `console` block in these docs runs.

## Writing a command page

A new command needs, in the same change:

1. `docs/commands/<command>.md` (`config-show.md` for `jtt config show`), in a toctree of
   `docs/index.md`, with a `console` block of examples, the GIF, and an empty
   `<!-- options -->` `<!-- /options -->` block. Fill that in with
   `uv run python scripts/cli_docs.py`.
2. `docs/tapes/<command>.tape`, recorded to `docs/commands/gifs/<command>.gif`.
