# Getting started

## Install

```sh
uv tool install jira-time-tracker      # or: pipx install jira-time-tracker
jtt --version
```

Installing it as a tool, with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/),
gives `jtt` its own environment and puts two identical commands on your `PATH`: `jtt` and
`jira-time-tracker`. If the shell can't find them, run `uv tool update-shell` (or
`pipx ensurepath`) and open a new terminal. `pip install jira-time-tracker` works too, inside a
virtual environment.

To upgrade: `uv tool upgrade jira-time-tracker`, or `pipx upgrade jira-time-tracker`.

## 1. Log in

You need an Atlassian API token: create one at
<https://id.atlassian.com/manage-profile/security/api-tokens>. Then:

```console
$ jtt login
```

`jtt` asks for the site (`your-team.atlassian.net`), your account email and the token, typed
hidden. It checks the token with Jira before storing it in your system's keyring, and never
writes it to the settings file. See [`jtt login`](../commands/login.md).

## 2. Choose what each project tracks

```console
$ jtt init
```

For each project you can see, `jtt init` lists the site's numeric fields, the ones on the
project's create screens first (marked ★). Pick the field that holds your estimates and say
what its numbers mean: points, or a time unit. Type `s` to skip a project and `q` to stop;
each answer is saved as you go. See [`jtt init`](../commands/init.md), which also shows how to
answer everything with options instead.

The first project you set up becomes the default, used whenever you leave out `-p KEY`.
[`jtt config default`](../commands/config-default.md) changes it.

## 3. Report

```console
$ jtt calculate --period last-week
$ jtt contributions --period this-month --by week
```

[`jtt calculate`](../commands/calculate.md) lists what came into being on each issue, and the
net. [`jtt contributions`](../commands/contributions.md) splits it per person, with statistics.
Both take a [period](how-it-counts.md#periods), `-p KEY` for another project, and `--user` for
one person's share.

To hand the numbers to someone else, [`jtt export`](../commands/export.md) writes CSV (it opens
in Excel), JSON or Markdown:

```console
$ jtt export -k contributions -o last-month.csv --period last-month
```

## Next

- [How jtt counts](how-it-counts.md): periods, whose work counts, and where each number comes
  from.
- [Configuration](configuration.md): where settings and the token are kept, and the
  environment variables.
- [Commands](../commands/index.md): every command, its options and a recording of its output.
