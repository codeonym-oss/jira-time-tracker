# How jtt counts

Every report answers the same question: how much of the tracked field came into being during
the period? That is the sum of every change made to the field inside the period, plus the
value of each issue created inside it. Estimates that grew add, estimates that shrank or were
cleared subtract, and the result is the **net**.

## Where each number comes from

For each issue touched in the period, `jtt` reads the issue's full change history from Jira
and places each change of the tracked field before, inside or after the period. Two Jira
behaviours shape this:

**The search can't end at the period's end.** Jira only records when an issue was *last*
updated. An issue edited inside the period and again afterwards would drop out of a search
bounded by the period's end, so the search only bounds that date from below
(`updated >= start AND created < end`), and the change history decides what falls inside.

**A value entered when an issue is created leaves no history.** Jira's history starts at the
first edit. For an issue created inside the period, `jtt` adds back the value it was created
with: the "before" side of its first later change, or its current value if the field was
never edited.

Dates in queries always carry an explicit `00:00`. Checked on a live site, bare dates did not
give exact bounds: `assignee WAS X DURING ("2026-09-24", "2026-09-25")` matched issues first
assigned in the afternoon of the 25th, and `DURING ("2026-09-25", "2026-09-25")` matched
nothing.

## Periods

Periods are **half-open: the start day is included and the end day is excluded.**
`--from 2026-09-01 --to 2026-10-01` is all of September. Leave out `--to` and the period runs
through today.

```console
$ jtt calculate --from 2026-09-01 --to 2026-10-01
$ jtt calculate --from 2026-09-21
```

A named period can replace `--from` and `--to`: `today`, `yesterday`, `this-week`,
`last-week`, `this-month`, `last-month`, `this-quarter`, `last-quarter`, `this-year`,
`last-7-days` and `last-30-days`. Weeks start on Monday.

```console
$ jtt calculate --period last-week
```

Days are the calendar days Jira shows in *your Jira profile's* time zone, which is also how
Jira reads dates in queries. `jtt` never works out time zone offsets itself, because local time
zone data can disagree with Jira's: tzdata 2026d keeps Morocco at +00 after Ramadan 2026, while
Jira still shows +01.

## Whose work counts

`--user` takes `me`, an account id, or part of a name or email. There are two ways to count one
person's work:

- **`--attribution was`** (the default for `calculate` and `export`) counts every change made
  in the period on issues the person held at some point in the period.
- **`--attribution holder`** counts only the changes made while the person held the issue.

```console
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --user daniel
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --user daniel --attribution holder
```

[`jtt contributions`](../commands/contributions.md) always credits each change to whoever held
the issue when it happened, and the value an issue was created with to the first person ever
assigned to it. That way the per-person nets add up to the project's net, "Unassigned"
included.

## Units

A project's tracked field holds either **points** or a **time** amount: seconds, minutes,
hours, days or weeks. Jira's own time tracking fields (original estimate, remaining estimate,
time spent) always hold seconds, and `jtt` shows them in hours unless you choose otherwise.

Time amounts convert between units with the site's working calendar, read from Jira's time
tracking settings at login: by default a day is 8 hours and a week is 5 days.
`--as UNIT` shows one report in another time unit, and
[`jtt config calendar`](../commands/config-calendar.md) overrides the calendar.

```console
$ jtt calculate -p OPS --from 2026-09-21 --to 2026-09-28 --as days
```

## Levels of detail

`calculate` and `contributions` take `-v`, `-vv` (or `--vv`) and `-vvv` (or `--vvv`):

- **`-v`** adds each issue's current value, type, status and assignee (↪ marks an issue that
  has since moved to someone else), and where each amount came from.
- **`-vv`** also lists issues with no change, and a timeline per issue: each change, when it
  happened, the value before and after, and who made it.
- **`-vvv`** also shows the query sent to Jira, a trace of every API request, and the changes
  outside the period, struck through.

```console
$ jtt calculate --from 2026-09-25 --to 2026-09-26 -vv
```
