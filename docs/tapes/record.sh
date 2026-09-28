#!/usr/bin/env bash
# Record the docs' GIFs with VHS in Docker: every tape, or the ones named (without .tape).
#   docs/tapes/record.sh [calculate config-show …]
set -euo pipefail
cd "$(dirname "$0")/../.."

rm -rf docs/tapes/.dist
uv build --wheel --quiet --out-dir docs/tapes/.dist
docker build --quiet --tag jtt-tapes docs/tapes >/dev/null

if [ $# -eq 0 ]; then
    set -- $(basename -s .tape docs/tapes/[!_]*.tape)
fi
# Each tape runs in its own container, with its own simulated Jira: four at a time.
printf '%s\n' "$@" | xargs -P 4 -I{} sh -c \
    'docker run --rm --user "$(id -u):$(id -g)" --env HOME=/tmp -v "$PWD":/vhs jtt-tapes \
        "docs/tapes/{}.tape" >/dev/null 2>&1 && echo "recorded {}" || echo "FAILED {}"'
