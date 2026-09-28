"""Check that a branch name follows `<type>/<issue>-<slug>`.

Used by the `pre-push` hook (current branch) and by CI (the PR's head branch).
Usage: check_branch_name.py [BRANCH]
"""

import re
import subprocess
import sys

TYPES = ("feat", "fix", "perf", "build", "docs", "refactor", "test", "ci", "chore", "revert")
PATTERN = re.compile(rf"^(?:{'|'.join(TYPES)})/[1-9]\d*-[a-z0-9]+(?:-[a-z0-9]+)*$")
EXEMPT = re.compile(r"^(?:main|release-please--.+|dependabot/.+)$")


def is_valid(branch: str) -> bool:
    """Return whether `branch` follows the convention or is exempt."""
    return bool(EXEMPT.match(branch) or PATTERN.match(branch))


def main(argv: list[str]) -> int:
    """Check the given branch, or the current one, and explain any violation."""
    branch = argv[0] if argv else _current_branch()
    if is_valid(branch):
        return 0
    print(
        f"Branch name {branch!r} does not follow <type>/<issue>-<slug>.\n"
        f"  type:  one of {', '.join(TYPES)}\n"
        "  issue: the GitHub issue number\n"
        "  slug:  lowercase words separated by hyphens\n"
        "  e.g.   feat/5-package-scan, fix/23-duplicate-handler-message\n"
        "Rename with: git branch -m <new-name>",
        file=sys.stderr,
    )
    return 1


def _current_branch() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
