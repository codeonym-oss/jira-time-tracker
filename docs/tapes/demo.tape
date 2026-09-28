# The README's and the docs home page's demo.
Output docs/demo.gif
Set Height 1000
Set Width 1280
Source docs/tapes/_setup.tape

Type "# How much estimated work came into being last week, and on which issues?" Sleep 600ms Enter
Type "jtt calculate --from 2026-09-21 --to 2026-09-28" Sleep 500ms Enter Sleep 5s
Hide
Type "clear" Enter Sleep 300ms
Show
Type "# Who contributed it, day by day?" Sleep 600ms Enter
Type "jtt contributions --from 2026-09-21 --to 2026-09-28 --by day" Sleep 500ms Enter Sleep 7s
Hide
Type "clear" Enter Sleep 300ms
Show
Type "# Hand it to accounting as CSV, JSON or Markdown" Sleep 600ms Enter
Type "jtt export -k contributions -o week.csv --from 2026-09-21 --to 2026-09-28" Sleep 500ms Enter Sleep 2s
Type "cat week.csv" Sleep 400ms Enter Sleep 5s
