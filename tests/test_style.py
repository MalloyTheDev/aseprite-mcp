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


def _tracked_files() -> list[pathlib.Path]:
    """Every file git tracks, which is the definition the rule is about.

    Not a filesystem walk: that would have to re-implement .gitignore to avoid the
    workspace's sprites, the virtualenv and the caches, and a second copy of the ignore
    list is a second thing to get wrong.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "could not list tracked files with git, so this rule cannot be checked: "
            f"{result.stderr.strip() or f'git exited {result.returncode}'}"
        )
    names = [name for name in result.stdout.split("\0") if name]
    assert names, "git listed no tracked files, which cannot be right"
    return [REPO_ROOT / name for name in names]


def test_no_tracked_file_contains_an_em_dash():
    """The project prohibits U+2014 anywhere in tracked content.

    Reported as file:line with the offending text, because "there is an em dash
    somewhere in 43 files" is not a finding anyone can act on. Binary and
    non-UTF-8 files are skipped rather than guessed at: the rule is about prose and
    source, and a decode error is not a style violation.
    """
    offenders: list[str] = []
    for path in _tracked_files():
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

    Asserted as a tracked file rather than assumed, because if it ever stopped being
    tracked the rule above would stop seeing it and a regression could land through the
    generator with nothing failing.
    """
    tracked = {p.relative_to(REPO_ROOT).as_posix() for p in _tracked_files()}

    assert "docs/TOOLS.md" in tracked
