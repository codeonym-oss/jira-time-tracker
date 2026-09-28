# Security Policy

## Supported versions

jira-time-tracker is pre-1.0. Security fixes are released for the latest minor version only.

| Version         | Supported |
|-----------------|-----------|
| latest `0.x`    | ✅        |
| older           | ❌        |

## Reporting a vulnerability

Please **do not** open a public issue. Report it privately through
[GitHub private vulnerability reporting](https://github.com/codeonym-oss/jira-time-tracker/security/advisories/new).

Include what you found, how to reproduce it, and the affected versions. You can expect an
acknowledgement within 7 days. Once a fix is released, we publish a GitHub Security Advisory
crediting you, unless you prefer to stay anonymous.

Of particular interest: anything that leaks the Jira API token (the keyring entry, the fallback
credentials file, logs or `-vvv` traces), or that sends it anywhere but the configured Jira site.
