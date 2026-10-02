"""Repository style rules that are mechanical enough to enforce (#48).

Pure Python. One rule so far, and the point of having it as a test rather than as a note
in CONTRIBUTING is that a convention nobody checks is a convention that drifts: the
em dash ban was stated, respected in new work, and still had 121 occurrences across 43
tracked files, because a `git grep` over a dirty baseline reports the same hits on every
run and gives no way to tell a new violation from an old one.

Cleaning the baseline is what makes the check possible; this is the check.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

# Built from its code point on purpose. Writing the character here would make this file
# the thing it forbids, and the test would then have to exempt itself, which is how a
# rule starts collecting exceptions.
EM_DASH = chr(0x2014)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _git(*args: str) -> list[str]:
    """Run a git listing command and return its NUL-separated names."""
    result = subprocess.run(
        ["git", *args, "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"could not list files with 'git {' '.join(args)}', so this rule cannot be "
            f"checked: {result.stderr.strip() or f'git exited {result.returncode}'}"
        )
    return [name for name in result.stdout.split("\0") if name]


def _files_under_the_rule() -> list[pathlib.Path]:
    """Every file the rule applies to: tracked, plus untracked and not ignored.

    Not a filesystem walk: that would have to re-implement .gitignore to avoid the
    workspace's sprites, the virtualenv, the caches and the agent worktrees under
    `.claude/`, and a second copy of the ignore list is a second thing to get wrong.

    The untracked half was missing at first, and that made the check useless in the one
    situation it exists for. A new file is where a new violation comes from, and a new
    file is untracked until somebody stages it: the first person to run this against a
    freshly written document had to `git add` it before the test would look at it, which
    means a local run passed on content that CI would then reject. Tracked-only was a
    defensible reading of "tracked content" and the wrong tool for the job.
    """
    names = _git("ls-files") + _git("ls-files", "--others", "--exclude-standard")
    assert names, "git listed no files at all, which cannot be right"
    return [REPO_ROOT / name for name in names]


def test_no_file_in_the_repository_contains_an_em_dash():
    """The project prohibits U+2014 anywhere in the repository's own content.

    Reported as file:line with the offending text, because "there is an em dash
    somewhere in 43 files" is not a finding anyone can act on. Binary and
    non-UTF-8 files are skipped rather than guessed at: the rule is about prose and
    source, and a decode error is not a style violation.
    """
    offenders: list[str] = []
    for path in _files_under_the_rule():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if EM_DASH not in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                relative = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"  {relative}:{number}: {line.strip()[:100]}")

    assert not offenders, (
        f"{len(offenders)} line(s) contain U+2014, which this project does not use. "
        "Use a comma, colon, semicolon, parentheses or a plain hyphen instead:\n"
        + "\n".join(offenders)
    )


def test_the_generated_tool_reference_is_covered_by_that_rule():
    """`docs/TOOLS.md` is generated from docstrings, so it is the one file where fixing
    the symptom is wrong: it comes back on the next `gen_tool_docs.py` run.

    Asserted to be listed rather than assumed, because if it ever stopped being
    tracked the rule above would stop seeing it and a regression could land through the
    generator with nothing failing.
    """
    listed = {p.relative_to(REPO_ROOT).as_posix() for p in _files_under_the_rule()}

    assert "docs/TOOLS.md" in listed


def test_a_file_nobody_has_staged_yet_is_still_checked():
    """The gap that made this rule miss the case it exists for.

    A new document is untracked until somebody stages it, so a tracked-only listing
    looked at everything except the file most likely to carry a fresh violation. This
    writes a throwaway file into the repository root and asserts the listing finds it.

    The temporary file deliberately contains no em dash. If this test were ever
    interrupted between writing and cleaning up, a file carrying one would fail the rule
    above for everybody until someone found it; a harmless file just gets deleted.
    """
    probe = REPO_ROOT / "untracked-probe-for-test-style.txt"
    assert not probe.exists(), f"{probe.name} already exists; clean it up"
    probe.write_text("placeholder, no prohibited characters here\n", encoding="utf-8")
    try:
        listed = {p.relative_to(REPO_ROOT).as_posix() for p in _files_under_the_rule()}
        assert probe.name in listed, (
            "an untracked file is not being checked, so a new file carrying a "
            "prohibited character would pass locally and fail on CI"
        )
    finally:
        probe.unlink()
