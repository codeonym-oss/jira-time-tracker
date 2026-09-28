# jtt logout: see docs/commands/logout.md.
Output docs/commands/gifs/logout.gif
Set Height 320
Set Width 1280
Source docs/tapes/_setup.tape

Type "jtt logout" Sleep 500ms Enter Sleep 2000ms
Type "jtt login --url http://127.0.0.1:8765 --email robin.hale@example.com" Sleep 500ms Enter Sleep 1000ms
Type "sim-token" Sleep 400ms Enter Sleep 3000ms
Type "jtt logout --purge" Sleep 500ms Enter Sleep 3000ms
