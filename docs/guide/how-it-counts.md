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

## Which issues count

Every issue touched in the period counts, parents included. When a team estimates a story and
also its subtasks, that counts the same work twice. `--exclude-parents` (on `fetch`,
`calculate`, `contributions` and `export`) leaves out every issue that has children: stories,
tasks or bugs with subtasks, and epics with child issues. Subtasks, and issues never split,
still count.

```console
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --exclude-parents
```

Use it only when the estimates sit on the subtasks: an estimate kept only on a parent drops
out of the total. Whether an issue has children is read when the report runs, so a story split
into subtasks after the period is left out of that period too.

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

`--user` takes `me`, an account id, or part of a name or email. There are three ways to count
one person's work, chosen with `--attribution`:

| `--attribution` | Credits the person with | Use it to | Totals add up across people |
|---|---|---|---|
| `was` | every change made in the period on issues they held at some point in the period | see all the movement on the issues someone worked on | no: an issue that changed hands counts for each person who held it |
| `holder` | only the changes made while they held the issue | see who held the issue as each change was made | yes, with "Unassigned" |
| `last-holder` | every change made in the period on issues they were the last person assigned to before the period ended | account for each issue's amount once, under one person | yes, with "Unassigned" |

```console
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --user daniel
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --user daniel --attribution holder
$ jtt calculate --from 2026-09-21 --to 2026-09-28 --user daniel --attribution last-holder
```

`calculate` and `export` default to `was`.
[`jtt contributions`](../commands/contributions.md) defaults to `holder`, which gives the value
an issue was created with to the first person ever assigned to it, and also takes
`last-holder`. It doesn't take `was`, whose totals can't add up.

### One person per issue

`holder` credits a change made while nobody is assigned to "Unassigned", so the person who did
the work can lose it. `last-holder` credits an issue's whole net in the period, the value it was
created with included, to one person:

1. **The last person assigned before the period ended.** Stretches without an assignee are
   skipped, and the person may have held the issue only before the period.
2. If nobody had been assigned by then, **the first person ever assigned**.
3. If nobody was ever assigned, **Unassigned**.

For example, Alice creates an issue with 4 points, clears the estimate and unassigns herself;
Bob takes it and sets 2 points, then 2.5. The issue's net is 2.5:

| | Alice | Bob |
|---|---|---|
| `was` | 2.5 | 2.5 |
| `holder` | 0 | 2.5 |
| `last-holder` | 0 | 2.5 |

And if an estimate is set to 0.75 while nobody is assigned, then Bob takes the issue and
corrects it to 0.5, `holder` gives Bob -0.25 and "Unassigned" 0.75, while `last-holder` gives
Bob 0.5.

Reassigning an issue after the period ended never moves its credit from one person to another.
There is one case where a past period can change: an issue nobody had been assigned to by the
end of the period counts as "Unassigned" until someone is first assigned to it, and then as
theirs. The project's net stays the same. Before closing a period, assign the issues it left
under "Unassigned", and keep the exported file.

The people's nets add up to the project's net only together with "Unassigned", which
`--user` can't select: [`jtt contributions`](../commands/contributions.md) shows everyone at
once.

```console
$ jtt contributions --from 2026-09-21 --to 2026-09-28 --attribution last-holder
```

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
