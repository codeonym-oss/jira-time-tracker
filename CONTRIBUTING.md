# Contributing to jira-time-tracker

Thanks for helping! This guide covers the local setup and the conventions CI enforces.

## Setup

You need [uv](https://docs.astral.sh/uv/). Python versions are installed by uv as needed.

```sh
git clone git@github.com:codeonym-oss/jira-time-tracker.git && cd jira-time-tracker
uv sync                                  # .venv with the locked dev tools
uv run pre-commit install --install-hooks -t pre-commit -t commit-msg -t pre-push
uv run jtt --help                        # the CLI, from your checkout
```

The hooks run the same checks as CI:

| Stage        | Checks                                                   |
|--------------|----------------------------------------------------------|
| `pre-commit` | ruff lint + format, pyright, file hygiene                |
| `commit-msg` | the message is a [Conventional Commit](#commits)         |
| `pre-push`   | the branch name follows [`<type>/<issue>-<slug>`](#branches) |

Run the full suite with `uv run pytest`; a coverage below `fail_under` in `pyproject.toml` fails.
The tests never reach a real Jira, and every test gets its own config directory and a file
credential store. They use two local fake sites:

- `tests/fake_jira.py` serves a few issues shaped like real data, for the precise cases.
- `tests/jira_sim` generates a whole site from a seed (people, projects, hundreds of issues and
  their histories) and knows what each report should say; `tests/test_commands.py` holds `jtt`
  to it. See [the simulated Jira](docs/development/simulator.md).

Keep test data fictional, since the repository is public. To test another Python version:
`uv run --isolated --python 3.14 pytest`.

CI runs the tests on Linux for Python 3.10 to 3.14, and on macOS and Windows for 3.12.

## Workflow

1. **Start from an issue.** Open one first if none exists.
2. **Branch** from `main` using the [branch convention](#branches).
3. **Commit** using [Conventional Commits](#commits).
4. **Open a PR** whose [title](#pull-requests) ends with the issue key and whose body says `Fixes #N`.
5. CI must be green. PRs are **squash-merged**, so the PR title becomes the commit on `main`.

`main` is protected: no direct pushes, no force-pushes, linear history, and these required checks:
`ci-ok`, `branch-name`, `commits`, `pr-title`.

## Conventions

The allowed types are the same everywhere:

| Type       | Use for                                          | In changelog |
|------------|--------------------------------------------------|--------------|
| `feat`     | a new feature                                    | Features     |
| `fix`      | a bug fix                                        | Bug Fixes    |
| `perf`     | a performance improvement                        | Performance  |
| `docs`     | documentation only                               | Documentation|
| `build`    | packaging, dependencies, build tooling           | Build        |
| `refactor` | code change that neither fixes nor adds          | hidden       |
| `test`     | tests only                                       | hidden       |
| `ci`       | CI and release workflows                         | hidden       |
| `chore`    | repo maintenance                                 | hidden       |
| `revert`   | reverting a previous commit                      | shown        |

### Branches

`<type>/<issue>-<slug>`: a type from the table, the GitHub issue number, and a short lowercase
hyphenated slug.

```text
feat/5-export-xlsx
fix/23-week-boundary
docs/12-readme-quickstart
```

Branches opened by bots (`release-please--*`, `dependabot/*`) are exempt.

### Commits

Every commit follows [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/):

```text
<type>(<optional scope>)<optional !>: <summary>

<optional body>

<optional footer(s)>
```

```text
feat(export): write contributions as Markdown
fix: count a value set on the create screen once
feat!: rename --attribution holder to --attribution owner

BREAKING CHANGE: --attribution holder was removed.
```

- Summary in the imperative, lowercase, no trailing period.
- `!` or a `BREAKING CHANGE:` footer marks a breaking change.
- The issue key is **not** required in commit messages; the branch and PR carry it.

### Pull requests

The title is a conventional commit summary **ending with the issue key**, and the body links the
issue:

```text
feat: export contributions as CSV (#5)
```

```text
Fixes #5
```

Keep a PR to one issue. Fill in the PR template's checklist.

## Documentation

The docs site is built with [Sphinx](https://www.sphinx-doc.org/), the
[Shibuya](https://shibuya.lepture.com/) theme and [MyST](https://myst-parser.readthedocs.io/)
Markdown from `docs/`. Preview it, rebuilt on every save, at http://127.0.0.1:8000:

```sh
uv run --isolated --python 3.13 --group docs sphinx-autobuild -b dirhtml docs docs/_build/html
```

Sphinx 9 needs Python 3.12+, hence `--python 3.13`; `--isolated` keeps it out of `.venv`.
CI builds the site with `-W`, so broken links and references fail the build.

**Every command has a page** in `docs/commands/`, with examples, a GIF of its output and its
options. The options block is generated from the CLI: after changing an option or a help text,
run `uv run python scripts/cli_docs.py`. The GIFs are recorded with
[VHS](https://github.com/charmbracelet/vhs) in Docker, from the tapes in `docs/tapes/`,
against the simulated Jira; re-record the ones whose output changed:

```sh
docs/tapes/record.sh calculate export   # or no names, for all of them
```

`tests/test_docs.py` checks that every command has a page, a tape and a GIF, that the options
match the CLI, and runs every `$ jtt …` line of the docs' `console` blocks against the
simulated Jira. [Writing a command page](docs/development/simulator.md#writing-a-command-page)
lists what a new command needs.

[Read the Docs](https://app.readthedocs.org/) builds and hosts the site from
`.readthedocs.yaml`: `latest` is `main`, each release tag gets its own version, and `stable`
is the newest release.

## Releases

Releases are automated with [release-please](https://github.com/googleapis/release-please). Merges
to `main` keep a `chore(main): release X.Y.Z` PR up to date; merging it tags the release, updates
`CHANGELOG.md` and publishes to PyPI through Trusted Publishing. Never edit the version by hand.

Versions follow [SemVer](https://semver.org/). Before 1.0.0, breaking changes bump the minor version.

## Reporting bugs and security issues

- Bugs and feature ideas: [open an issue](https://github.com/codeonym-oss/jira-time-tracker/issues/new/choose).
- Security vulnerabilities: see [SECURITY.md](SECURITY.md). Please don't open public issues for them.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
