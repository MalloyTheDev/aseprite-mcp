"""Repository style rules that are mechanical enough to enforce (#48).

Pure Python. Two rules so far, and the point of having them as tests rather than as a note
in CONTRIBUTING is that a convention nobody checks is a convention that drifts: the
em dash ban was stated, respected in new work, and still had 121 occurrences across 43
tracked files, because a `git grep` over a dirty baseline reports the same hits on every
run and gives no way to tell a new violation from an old one.

Cleaning the baseline is what makes the check possible; this is the check.
"""

from __future__ import annotations

import ast
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


# --- a module-level name defined twice ------------------------------------------------
#
# The second `def` of a name replaces the first for every caller in the module, including
# the ones written above it, because they look the name up when they run. Ruff's F811
# reports only the case where the first definition was never used, which is the harmless
# one: in a test module the first helper *is* used, so a later helper given the same name
# silently rewires the earlier tests. That happened twice in one piece of work with ruff
# passing both times: a second `_strip` broke sixteen tests in tests/test_frame_order.py,
# and a second `_durations` broke two more in the same file.


def _is_overload(node: ast.AST) -> bool:
    """`@overload` stubs repeat a name on purpose, and they are the only module-level
    repeat Python means to allow."""
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name == "overload":
            return True
    return False


def _redefinitions(source: str, filename: str = "<source>") -> list[tuple[str, int, int]]:
    """(name, first line, later line) for each module-level def or class defined again."""
    first: dict[str, int] = {}
    found: list[tuple[str, int, int]] = []
    for node in ast.parse(source, filename=filename).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _is_overload(node):
            continue
        if node.name in first:
            found.append((node.name, first[node.name], node.lineno))
        else:
            first[node.name] = node.lineno
    return found


def test_no_module_defines_the_same_name_twice():
    """Every Python file under src/, tests/ and scripts/, tracked or not, for the reason
    the em dash rule lists untracked files too: a new helper is written before anyone
    stages it. A file that does not parse is skipped rather than reported, because it
    fails loudly wherever it is imported and is not this rule's finding."""
    offenders: list[str] = []
    for path in _files_under_the_rule():
        relative = path.relative_to(REPO_ROOT)
        if path.suffix != ".py" or relative.parts[0] not in ("src", "tests", "scripts"):
            continue
        try:
            found = _redefinitions(path.read_text(encoding="utf-8"), str(relative))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        offenders += [f"  {relative.as_posix()}:{later}: '{name}' is already defined at "
                      f"line {earlier}" for name, earlier, later in found]

    assert not offenders, (
        f"{len(offenders)} module-level name(s) defined twice. The later definition "
        "replaces the earlier one for every caller in the module, including the ones above "
        "it. Rename one of them:\n" + "\n".join(offenders)
    )


def test_the_rule_catches_the_case_ruff_lets_through():
    """Asserted on source rather than trusted, since a rule that never fires looks exactly
    like a clean repository: a helper used before it is redefined, which F811 does not
    report, must be caught, and `@overload` stubs must not be."""
    used_then_redefined = (
        "def _helper():\n    return 1\n\n"
        "def test_a():\n    assert _helper() == 1\n\n"
        "def _helper():\n    return 2\n"
    )
    overloads = (
        "from typing import overload\n\n"
        "@overload\ndef f(x: int) -> int: ...\n"
        "@overload\ndef f(x: str) -> str: ...\n"
        "def f(x):\n    return x\n"
    )

    assert _redefinitions(used_then_redefined) == [("_helper", 1, 7)]
    assert _redefinitions(overloads) == []
