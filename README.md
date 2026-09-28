# jira-time-tracker

[![PyPI](https://img.shields.io/pypi/v/jira-time-tracker)](https://pypi.org/project/jira-time-tracker/)
[![Python](https://img.shields.io/pypi/pyversions/jira-time-tracker)](https://pypi.org/project/jira-time-tracker/)
[![CI](https://github.com/codeonym-oss/jira-time-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/codeonym-oss/jira-time-tracker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/pypi/l/jira-time-tracker)](https://github.com/codeonym-oss/jira-time-tracker/blob/main/LICENSE)

`jtt` answers one question about a Jira Cloud project: **how much estimated work
came into being over a period, on which issues, and by whom?**

The estimate is whatever field your organisation tracks. That could be story
points, an hours or days custom field, or Jira's own original estimate or time
spent. You pick the field once per project.

![jtt calculate, jtt contributions --by day and jtt export, run against a simulated Jira site](https://raw.githubusercontent.com/codeonym-oss/jira-time-tracker/main/docs/demo.gif)

Every command is documented, with a recording of its output, in
[`docs/`](https://github.com/codeonym-oss/jira-time-tracker/tree/main/docs): start at
[Getting started](https://github.com/codeonym-oss/jira-time-tracker/blob/main/docs/guide/getting-started.md)
or the [command list](https://github.com/codeonym-oss/jira-time-tracker/blob/main/docs/commands/index.md).

## Install

`jtt` is [on PyPI](https://pypi.org/project/jira-time-tracker/). It needs Python 3.10 or
newer and works the same on Linux, macOS and Windows. Install it as a tool, in its own
environment, with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```sh
uv tool install jira-time-tracker      # or: pipx install jira-time-tracker
jtt --version
```

That puts two identical commands on your `PATH`: `jtt` and `jira-time-tracker`. If the
shell can't find them, run `uv tool update-shell` (or `pipx ensurepath`) and open a new
terminal. `pip install jira-time-tracker` works too, inside a virtual environment.

To upgrade: `uv tool upgrade jira-time-tracker` or `pipx upgrade jira-time-tracker`.
Releases and their changes are listed in the [changelog](https://github.com/codeonym-oss/jira-time-tracker/blob/main/CHANGELOG.md).

**Status:** pre-1.0. It targets Jira Cloud (not Server or Data Center), and commands
or options may still change between minor versions; the changelog says when they do.

## Getting started

```sh
jtt login     # site URL, account email, API token (typed hidden)
jtt init      # for each project: choose the field that holds the estimate, and its unit
jtt calculate --period last-week
```

1. **`jtt login`** checks the token against Jira before storing it. Create a
   token at <https://id.atlassian.com/manage-profile/security/api-tokens>. To
   switch account or rotate the token, run `jtt logout` first, then `jtt login`
   again.
2. **`jtt init`** walks through every project you can see and lists its numeric
   fields. A ★ marks the fields on the project's create screens, and those come
   first. You pick one and say what its numbers mean: points, seconds, minutes,
   hours, days or weeks. For time units you also pick the unit reports should
   show. Jira's built-in time tracking fields always hold seconds, so the tool
   sets that unit for you. Your last choice is offered as the default for the
   next project. Type `s` to skip a project or `q` to stop; progress is saved
   after each project.

   To skip the questions, pass everything as options:
   `jtt init -p DEMO --field customfield_10016 --unit points`.

## Commands

| Command | What it does |
|---|---|
| `login` / `logout [--purge]` / `whoami [--check]` | Manage the account. `logout` keeps project settings; `--purge` forgets them too |
| `init [-p KEY…] [--reconfigure]` | Choose each project's tracked field and unit |
| `config show \| path \| default KEY \| set KEY … \| remove KEY \| calendar …` | Inspect or edit settings without re-running `init` |
| `projects [--configured]` | Projects you can see and what each one tracks |
| `fields [-p KEY] [--counts]` | A project's numeric fields, optionally with how many issues hold a value |
| `fetch` | Issues touched in a period, with their current value (`--json` for raw output) |
| `calculate` | Net amount per issue for the whole project or one person, at four levels of detail |
| `collaborators` | People who can be assigned to the project, with their current open, in-progress and done issues |
| `contributions [--by day\|week]` | Per-person net, added, removed, share, issues created and issues finished, plus statistics and a daily trend |
| `export -o FILE [-k issues\|changes\|contributions\|daily]` | Write CSV (opens in Excel), JSON or Markdown |

Every report takes `-p KEY` (default: the project set by `init`), a period, and
`--as hours|days|…` to show time amounts in another unit.

### Periods

Periods are **half-open: the start day is included and the end day is
excluded.** `--from 2026-09-01 --to 2026-10-01` is all of September. Leave out
`--to` and the period runs through today.

You can also use a named period instead:
`--period today | yesterday | this-week | last-week | this-month | last-month | this-quarter | last-quarter | this-year | last-7-days | last-30-days`.
Weeks start on Monday.

Days are the calendar days Jira shows in *your* Jira profile's time zone, which
is also how Jira reads dates in queries. The tool never works out time zone
offsets itself, because local time zone data can disagree with Jira's. For
example, tzdata 2026d keeps Morocco at +00 after Ramadan 2026, while Jira still
shows +01.

### Choosing whose work to count (`--user`)

`--user` accepts `me`, an account id, or part of a name or email.

- `calculate --user X` (the default, `--attribution was`) counts every change
  made in the period on issues X held at some point in the period.
- `--attribution holder` only counts changes made while X held the issue.
- `contributions` always credits each change to whoever held the issue when it
  happened. The value an issue was created with goes to the first person
  assigned to it. That way the per-person totals add up to the project total.

### Levels of detail

`-v`, `-vv` (or `--vv`) and `-vvv` (or `--vvv`) work on `calculate` and
`contributions`:

- **`-v`** adds current value, type, status and current assignee (↪ marks a
  task that has since moved to someone else), and where each amount came from.
- **`-vv`** also lists issues with no change, and adds a per-issue timeline of
  each change: when it happened, the value before and after, and who made it.
- **`-vvv`** also shows the query sent to Jira, a trace of every API request,
  and changes outside the period (struck through).

## How the delta is computed

For each issue touched in the period, the tool reads its full change history
from Jira and adds up the changes to the tracked field that happened inside the
period. Two Jira behaviours shape this:

- **The query can't use "last updated" as an end date.** Jira only records when
  an issue was *last* updated. An issue edited inside the period and again
  afterwards would drop out of a query ending at the period's end. So the query
  only filters on that date from below, and the change history decides what
  falls inside the period.
- **A value entered when an issue is created leaves no history entry.** Jira's
  history starts at the first edit. For an issue created inside the period, the
  tool adds back the value it was created with. That value is the "before" side
  of its first later change, or its current value if the field was never
  edited.

Dates in queries are always sent with an explicit `00:00`. Tested on a live
site, bare dates did not give exact bounds: `assignee WAS X DURING ("2026-09-24",
"2026-09-25")` matched issues first assigned in the afternoon of the 25th, and
`DURING ("2026-09-25", "2026-09-25")` matched nothing.

## Where things are kept

| What | Where |
|---|---|
| Settings (site, projects, fields, units) | `config.json` in the user config directory; `jtt config path` prints it. On Linux: `~/.config/jira-time-tracker`, macOS: `~/Library/Application Support/jira-time-tracker`, Windows: `%LOCALAPPDATA%\jira-time-tracker` |
| API token | The system keyring: Windows Credential Manager, macOS Keychain, or Secret Service (GNOME Keyring / KWallet) on Linux. Where no keyring is available (headless servers, WSL, containers), it goes in `credentials.json` next to the settings, created **0600** inside a **0700** directory |

The token is never written to `config.json` or printed.

Environment overrides:
- `JTT_CREDENTIAL_BACKEND=file|keyring` forces where the token is stored.
- `JTT_API_TOKEN` supplies a token for CI; it is never stored.
- `JTT_CONFIG_DIR` moves the settings directory.

## Development

```sh
git clone https://github.com/codeonym-oss/jira-time-tracker.git && cd jira-time-tracker
uv sync
uv run pytest
```

The tests run the real CLI and HTTP client against local fake Jira sites with fictional
people and issues: one replays the shape of real issue data, and a
[simulated site](https://github.com/codeonym-oss/jira-time-tracker/blob/main/docs/development/simulator.md)
generates hundreds of issues and checks every report against what it generated. See
[CONTRIBUTING.md](https://github.com/codeonym-oss/jira-time-tracker/blob/main/CONTRIBUTING.md)
for the conventions CI enforces, the docs site, and re-recording the GIFs.

`legacy/jira_tasks.py` is the single-file script this project grew from, kept
unchanged.

## License

[MIT](https://github.com/codeonym-oss/jira-time-tracker/blob/main/LICENSE)
