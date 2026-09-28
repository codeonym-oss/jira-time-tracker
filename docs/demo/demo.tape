Output docs/demo.gif

Set Shell bash
Set FontSize 14
Set Width 1000
Set Height 760
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set CursorBlink false

# Setup, not recorded: the fake Jira from the test suite (fictional data), login and init.
Hide
Type "export PS1='$ '; cd /tmp; python3 /vhs/docs/demo/serve.py & sleep 1" Enter
Sleep 1s
Type "jtt login --url http://127.0.0.1:8765 --email dev@example.com --token good-token >/dev/null && jtt init -p DEMO --field customfield_10016 --unit points >/dev/null && clear" Enter
Sleep 3s
Show

Type "# How much estimated work came into being this week, and on which issues?" Sleep 600ms Enter
Type "jtt calculate --from 2026-09-24 --to 2026-09-30" Sleep 400ms Enter
Sleep 4.5s
Type "clear" Enter

Type "# Who contributed it, day by day?" Sleep 600ms Enter
Type "jtt contributions --from 2026-09-24 --to 2026-09-30 --by day" Sleep 400ms Enter
Sleep 6.5s
Type "clear" Enter

Type "# Hand it to accounting as CSV, JSON or Markdown" Sleep 600ms Enter
Type "jtt export -k contributions -o contributions.csv --from 2026-09-24 --to 2026-09-30" Sleep 400ms Enter
Sleep 2.5s
Type "cat contributions.csv" Sleep 300ms Enter
Sleep 4.5s
