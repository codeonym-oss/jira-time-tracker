# Configuration

## Where things are kept

**Settings** (the site, and per project the tracked field and its units) are in
`config.json` in your user config directory. [`jtt config path`](../commands/config-path.md)
prints where:

| System | Directory |
|---|---|
| Linux | `~/.config/jira-time-tracker` |
| macOS | `~/Library/Application Support/jira-time-tracker` |
| Windows | `%LOCALAPPDATA%\jira-time-tracker` |

**The API token** goes to the system keyring: Windows Credential Manager, the macOS Keychain,
or the Secret Service (GNOME Keyring, KWallet) on Linux. Where no keyring is usable, as on
headless servers, WSL or in containers, it goes to `credentials.json` next to the settings,
created readable by you only (0600, in a 0700 directory). It is never written to `config.json`,
and never printed.

[`jtt whoami`](../commands/whoami.md) shows which one holds your token.

## Changing settings

[`jtt init`](../commands/init.md) sets projects up interactively. The `jtt config` commands
change one setting at a time:

| Command | Changes |
|---|---|
| [`jtt config show`](../commands/config-show.md) | nothing: prints every setting |
| [`jtt config default KEY`](../commands/config-default.md) | the project used when `-p` is left out |
| [`jtt config set KEY …`](../commands/config-set.md) | a project's field, unit or display unit |
| [`jtt config remove KEY`](../commands/config-remove.md) | forgets a project |
| [`jtt config calendar …`](../commands/config-calendar.md) | the working day and week for time conversions |

## Environment variables

`JTT_CONFIG_DIR`
: Moves the settings directory (and `credentials.json`, when the token is kept in a file).

`JTT_CREDENTIAL_BACKEND`
: `keyring` or `file`: forces where the token is stored.

`JTT_API_TOKEN`
: A token to use instead of the stored one, for CI. It is never stored.
