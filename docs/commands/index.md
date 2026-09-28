# Commands

Every command prints its options with `-h`: `jtt calculate -h`. Each page below shows the
command running, against the [simulated Jira site](../development/simulator.md).

| Command | What it does |
|---|---|
| [`login`](login.md) | Check an API token with Jira and store it securely |
| [`logout`](logout.md) | Remove the stored token; `--purge` also forgets the project settings |
| [`whoami`](whoami.md) | The logged-in account, where the token is kept, and the configured projects |
| [`init`](init.md) | Choose, per project, the field that holds the estimate, and its unit |
| [`fields`](fields.md) | A project's numeric fields, optionally with how many issues hold a value |
| [`projects`](projects.md) | The projects you can see, and what each one tracks |
| [`config show`](config-show.md) | Every setting |
| [`config path`](config-path.md) | Where the settings file is |
| [`config default`](config-default.md) | The project used when `-p` is left out |
| [`config set`](config-set.md) | Change a project's field or units without `init` |
| [`config remove`](config-remove.md) | Forget a project's settings |
| [`config calendar`](config-calendar.md) | The working day and week used to convert time units |
| [`fetch`](fetch.md) | The issues touched in a period, with their current value |
| [`calculate`](calculate.md) | The net amount that came into being in a period, per issue |
| [`contributions`](contributions.md) | The net per person, with statistics and a daily or weekly breakdown |
| [`collaborators`](collaborators.md) | Who can be assigned in a project, with their current load |
| [`export`](export.md) | Issues, changes, contributions or a daily series, to CSV, JSON or Markdown |

## Options every report takes

`fetch`, `calculate`, `contributions` and `export` share these:

`-p KEY`, `--project KEY`
: The project; without it, the default one (see [`config default`](config-default.md)).

`--from DAY`, `--to DAY`, `--period NAME`
: The [period](../guide/how-it-counts.md#periods): the start day is included, the end day
  excluded.

`-u WHO`, `--user WHO`
: One person's share: `me`, an account id, or part of a name or email
  ([whose work counts](../guide/how-it-counts.md#whose-work-counts)).

`--as UNIT`
: Show time amounts in another time unit ([units](../guide/how-it-counts.md#units)).
