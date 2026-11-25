"""The two test tiers have to fail loudly in both directions (pure tier, no Aseprite).

A skip looks like a pass in a summary line, and each of these was a way to get one:

* `--run-aseprite` on a machine with no editor skipped every editor test and exited 0;
* a new test file on no list was skipped in silence, on CI as a lone `s`;
* a test marked `pure` that launches Aseprite passed on any machine with Steam's copy
  installed and failed only on CI.

Several of these run pytest in a subprocess against a scratch suite holding a copy of
tests/conftest.py, because the behaviour under test is what a whole run reports.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
from aseprite_mcp.core import config

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent


def _pytest(args, *, cwd, env_overrides):
    env = dict(os.environ, **env_overrides)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _scratch_suite(tmp_path: Path, files: dict[str, str]) -> Path:
    """A throwaway suite that uses the real conftest, so the run is the real gate."""
    tests = tmp_path / "tests"
    tests.mkdir()
    shutil.copy(TESTS / "conftest.py", tests / "conftest.py")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = -q\nmarkers =\n    pure: needs no Aseprite\n", encoding="utf-8")
    for name, body in files.items():
        (tests / name).write_text(body, encoding="utf-8")
    return tmp_path


# ------------------------------------------------- --run-aseprite with no editor at all
def test_run_aseprite_without_an_editor_is_a_usage_error(tmp_path):
    """A set-but-wrong ASEPRITE_PATH never falls through to PATH or the Steam candidates,
    so it is the portable way to stage "no editor" on a machine that has one."""
    missing = tmp_path / "nowhere" / "aseprite"
    code, out = _pytest(["--run-aseprite", "--collect-only", "tests/test_gui.py"],
                        cwd=REPO, env_overrides={"ASEPRITE_PATH": str(missing)})
    assert code != 0, f"--run-aseprite with no editor exited 0:\n{out[-2000:]}"
    assert "--run-aseprite was given but Aseprite was not found" in out, out[-2000:]
    assert str(missing) in out, "the error must say which path was tried"
    assert "ASEPRITE_PATH" in out and "leave out --run-aseprite" in out, out[-2000:]


# ------------------------------------------------------------ forward: undeclared files
def test_every_test_file_declares_exactly_one_tier():
    problems = [p for path in sorted(TESTS.glob("test_*.py"))
                if (p := conftest.registration_problem(path))]
    assert not problems, "\n\n".join(problems)


@pytest.mark.parametrize("listing", ["PURE_PYTHON_TESTS", "EDITOR_ONLY_TESTS"])
def test_every_listed_module_exists(listing):
    """A renamed or deleted file leaves its old name behind, and a stale name is how a
    list stops describing the suite."""
    stale = [n for n in getattr(conftest, listing) if not (TESTS / f"{n}.py").is_file()]
    assert not stale, f"{listing} names files that do not exist: {stale}"


def test_the_two_lists_do_not_overlap():
    both = set(conftest.PURE_PYTHON_TESTS) & set(conftest.EDITOR_ONLY_TESTS)
    assert not both, f"on both PURE_PYTHON_TESTS and EDITOR_ONLY_TESTS: {sorted(both)}"


@pytest.mark.parametrize(("body", "declared"), [
    ("def test_x():\n    pass\n", False),
    ('"""Mentions @pytest.mark.pure in prose only."""\n\ndef test_x():\n    pass\n', False),
    ("import pytest\n\n@pytest.mark.pure\ndef test_x():\n    pass\n", True),
    ("import pytest\n\npytestmark = pytest.mark.pure\n\ndef test_x():\n    pass\n", True),
    ("import pytest\n\npytestmark = [\n    pytest.mark.pure,\n    pytest.mark.slow,\n]\n",
     True),
    ("import pytest\n\nclass TestX:\n    pytestmark = pytest.mark.pure\n", True),
])
def test_how_a_file_declares_itself_pure(tmp_path, body, declared):
    """The decorator and module-level `pytestmark` both count; a marker quoted in a
    docstring does not. A file nobody listed with the module form must be accepted as
    it is, without also being put on a list."""
    path = tmp_path / "test_not_on_any_list.py"
    path.write_text(body, encoding="utf-8")
    problem = conftest.registration_problem(path)
    if declared:
        assert problem is None, problem
    else:
        assert problem and "PURE_PYTHON_TESTS" in problem and "EDITOR_ONLY_TESTS" in problem


def test_an_undeclared_file_fails_instead_of_skipping(tmp_path):
    root = _scratch_suite(tmp_path, {"test_brand_new.py": "def test_new():\n    pass\n"})
    code, out = _pytest(["tests/test_brand_new.py"], cwd=root, env_overrides={})
    assert code != 0, f"an undeclared test file did not fail the run:\n{out}"
    assert "1 error" in out and "1 skipped" not in out, out
    assert "add 'test_brand_new' to PURE_PYTHON_TESTS" in out, out


# ---------------------------------------------------- reverse: pure tests that need one
def test_the_editor_is_unreachable_without_run_aseprite(request):
    if request.config.getoption("--run-aseprite"):
        assert os.environ.get("ASEPRITE_PATH") != conftest.NO_EDITOR_SENTINEL
        return
    assert os.environ.get("ASEPRITE_PATH") == conftest.NO_EDITOR_SENTINEL
    with pytest.raises(FileNotFoundError, match="editor-disabled-without--run-aseprite"):
        config.find_aseprite()


def test_a_mislabelled_pure_test_fails_even_with_an_editor_installed(tmp_path):
    """Stands in an existing file (this interpreter) for an installed editor: the lookup
    only asks whether the file exists, so without the session override the test below
    would find "Aseprite" and pass, which is what happened on any machine with Steam."""
    body = (
        "import pytest\n\nfrom aseprite_mcp.core import config\n\n\n"
        "@pytest.mark.pure\ndef test_launches_the_editor():\n"
        "    config.find_aseprite()\n"
    )
    root = _scratch_suite(tmp_path, {"test_mislabelled.py": body})
    code, out = _pytest(["tests/test_mislabelled.py"], cwd=root,
                        env_overrides={"ASEPRITE_PATH": sys.executable})
    assert code != 0, f"a pure-marked test reached an editor:\n{out}"
    assert "1 failed" in out and "editor-disabled-without--run-aseprite" in out, out


# ------------------------------------------------------------- CI has to show its counts
def _workflow_run_lines() -> list[str]:
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return [line.split("run:", 1)[1].strip() for line in workflow.splitlines()
            if line.strip().startswith("run:")]


def test_ci_does_not_stack_a_q_on_the_configured_one():
    """pyproject's addopts sets -q; `pytest -q` on top is -qq, which prints no
    "N passed, M skipped" line, so the CI log had no count in it at all."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    addopts = re.search(r'(?m)^addopts\s*=\s*"([^"]*)"', pyproject)
    configured = addopts.group(1).split() if addopts else []
    pytest_runs = [r for r in _workflow_run_lines() if re.search(r"\bpytest\b", r)]
    assert pytest_runs, "CI runs no pytest step"
    for run in pytest_runs:
        args = run.split()
        quiet = configured.count("-q") + args.count("-q") + 2 * args.count("-qq")
        assert quiet <= 1, f"CI's pytest is -{'q' * quiet}, which hides the summary: {run}"


def test_ci_checks_the_documentation():
    runs = [r for r in _workflow_run_lines() if "scripts/check_docs.py" in r]
    assert runs, "CI does not run scripts/check_docs.py"
    assert (REPO / "scripts" / "check_docs.py").is_file()
