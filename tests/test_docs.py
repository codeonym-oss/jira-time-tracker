"""The docs: every command documented and recorded, and every example in them runs.

Examples are the `$ jtt …` lines of the `console` blocks in docs/. A page's examples run in
order, in a fresh config directory, against the simulated Jira, and must succeed. Each page
starts logged in with DEMO (the default), OPS and WEB set up, as the recordings do, except
the pages in START_LOGGED_OUT and START_UNCONFIGURED. Prompts get the answers in `answers`,
and `your-team.atlassian.net` and `you@example.com` stand for the simulated site and account.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jira_time_tracker.cli import app
from tests import jira_sim

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

_spec = importlib.util.spec_from_file_location("cli_docs", ROOT / "scripts" / "cli_docs.py")
assert _spec
assert _spec.loader
cli_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli_docs)

COMMANDS = cli_docs.commands()
START_LOGGED_OUT = {"guide/getting-started", "commands/login"}
START_UNCONFIGURED = {"commands/init"}
# jtt init's questions on the simulated site: projects come by key. DATA: skip. DEMO and OPS:
# the first field, with the default units. WEB: stop.
INIT_ANSWERS = "s\n1\n\n1\n\nq\n"

runner = CliRunner()


def examples(page: Path) -> list[list[str]]:
    """Return the page's `$ jtt …` lines, each split into its arguments."""
    found = []
    for block in re.findall(r"^```console\n(.*?)^```", page.read_text("utf-8"), re.M | re.S):
        for line in block.splitlines():
            if line.startswith("$ "):
                args = shlex.split(line[2:])
                assert args[0] == "jtt", f"{page.name}: not a jtt command: {line}"
                found.append(args[1:])
    return found


def answers(args: list[str], url: str) -> str:
    """Return what the command's prompts are answered with."""
    if args[0] == "login":
        given = {"--url": url, "--email": jira_sim.EMAIL, "--token": jira_sim.TOKEN}
        return "".join(f"{value}\n" for flag, value in given.items() if flag not in args)
    if args[0] == "init" and "--field" not in args:
        return "1\n\n\n" if "-p" in args else INIT_ANSWERS
    return ""


def run(args: list[str], url: str) -> None:
    args = [
        {"your-team.atlassian.net": url, "you@example.com": jira_sim.EMAIL}.get(a, a) for a in args
    ]
    result = runner.invoke(app, args, input=answers(args, url))
    assert result.exit_code == 0, f"jtt {shlex.join(args)}\n{result.output}"


PAGES = sorted(
    str(page.relative_to(DOCS).with_suffix(""))
    for page in DOCS.rglob("*.md")
    if "_build" not in page.parts and examples(page)
)


@pytest.mark.parametrize("page", PAGES)
def test_examples_run(sim, tmp_path, monkeypatch, page):
    monkeypatch.chdir(tmp_path)  # export examples write files
    if page not in START_LOGGED_OUT:
        run(["login", "--url", sim.url, "--email", jira_sim.EMAIL, "--token", jira_sim.TOKEN], "")
    if page not in START_LOGGED_OUT | START_UNCONFIGURED:
        run(["init", "-p", "DEMO", "--field", "customfield_10016", "--unit", "points"], "")
        run(["init", "-p", "OPS", "--field", "timeoriginalestimate", "--display-unit", "hours"], "")
        run(["init", "-p", "WEB", "--field", "customfield_10028", "--unit", "points"], "")
    for args in examples(DOCS / f"{page}.md"):
        run(args, sim.url)


@pytest.mark.parametrize("name", COMMANDS)
def test_every_command_has_a_page_a_tape_and_a_gif(name):
    slug = cli_docs.slug(name)
    page = DOCS / "commands" / f"{slug}.md"
    assert page.exists(), f"jtt {name} has no page: add {page.relative_to(ROOT)}"
    text = page.read_text("utf-8")
    assert text.startswith(f"# jtt {name}\n")
    assert f"(gifs/{slug}.gif)" in text, "the page shows its recording"
    assert examples(page), "the page has a console block of examples"
    assert f"commands/{slug}\n" in (DOCS / "index.md").read_text("utf-8"), "in a toctree"

    tape = DOCS / "tapes" / f"{slug}.tape"
    assert tape.exists(), f"jtt {name} has no tape: add {tape.relative_to(ROOT)}"
    assert f"Output docs/commands/gifs/{slug}.gif\n" in tape.read_text("utf-8")
    assert (DOCS / "commands" / "gifs" / f"{slug}.gif").exists(), "record it: see docs/tapes"


def test_every_page_in_commands_is_a_command():
    pages = {p.stem for p in (DOCS / "commands").glob("*.md")} - {"index"}
    assert pages == {cli_docs.slug(name) for name in COMMANDS}


def test_the_options_in_the_pages_match_the_cli(capsys):
    stale = cli_docs.main(check=True)
    assert stale == 0, f"run: uv run python scripts/cli_docs.py\n{capsys.readouterr().out}"
