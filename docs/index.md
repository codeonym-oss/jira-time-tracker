# jira-time-tracker

`jtt` answers one question about a Jira Cloud project: **how much estimated work came into
being over a period, on which issues, and by whom?**

The estimate is whatever field your organisation tracks: story points, an hours or days
custom field, or Jira's own original estimate or time spent. You pick the field once per
project, and every report reads it from each issue's change history.

![jtt calculate, jtt contributions --by day and jtt export, run against a simulated Jira site](demo.gif)

## Install

```sh
uv tool install jira-time-tracker      # or: pipx install jira-time-tracker
jtt --version
```

`jtt` needs Python 3.10 or newer and works the same on Linux, macOS and Windows. It targets
Jira Cloud, not Server or Data Center. It is pre-1.0: commands and options may still change
between minor versions, and the [changelog](changelog.md) says when they do.

## Three commands to a first report

```sh
jtt login                                 # site, email, API token (checked, then stored securely)
jtt init                                  # per project: the field holding the estimate, and its unit
jtt calculate --period last-week          # what came into being last week, issue by issue
```

[Getting started](guide/getting-started.md) walks through them, and
[How jtt counts](guide/how-it-counts.md) explains what the numbers mean. Every command has its
own page under [Commands](commands/index.md), with a recording of its output.

Every recording in these docs is made against a [simulated Jira site](development/simulator.md)
with invented people and issues, and every example runs in the test suite, as written.

```{toctree}
:hidden:
:caption: Guide

guide/getting-started
guide/how-it-counts
guide/configuration
commands/index
```

```{toctree}
:hidden:
:caption: Account

commands/login
commands/logout
commands/whoami
```

```{toctree}
:hidden:
:caption: Setup

commands/init
commands/fields
commands/projects
commands/config-show
commands/config-path
commands/config-default
commands/config-set
commands/config-remove
commands/config-calendar
```

```{toctree}
:hidden:
:caption: Reports

commands/fetch
commands/calculate
commands/contributions
commands/collaborators
commands/export
```

```{toctree}
:hidden:
:caption: Development

development/simulator
changelog
```
