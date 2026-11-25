"""scripts/release_gate.py has to say what it tested (pure tier, no Aseprite).

It exited 0 and printed "PASS integration" on a machine with no editor, where every
editor test had been skipped; it ran `pytest -q` on top of pyproject's `-q`, which drops
the "N passed, M skipped" line; and its unlocked `uv run` rewrote a stale uv.lock in
place. These pin the step construction and the editor preflight without running a gate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("release_gate",
                                                  REPO / "scripts" / "release_gate.py")
    module = importlib.util.module_from_spec(spec)
    # Registered first: @dataclass looks its own module up in sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _uv_steps(steps):
    return [cmd for _, cmd in steps if cmd[:2] == ["uv", "run"]]


@pytest.mark.parametrize("skip_aseprite", [False, True])
def test_no_step_stacks_a_q_on_the_configured_one(gate, skip_aseprite):
    for name, cmd in gate._steps(skip_aseprite):
        assert "-q" not in cmd and "-qq" not in cmd, (
            f"{name}: pyproject's addopts already has -q, and -qq hides the summary line")


def test_the_gate_runs_every_script_ci_runs(gate):
    """`--skip-aseprite` is documented as everything CI runs. A check CI has and the gate
    lacks means a gate that passes and a pull request that fails."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    in_ci = set(re.findall(r"scripts/\w+\.py", workflow))
    assert in_ci, "CI runs no script, so this test is reading the wrong file"
    in_gate = {arg for _, cmd in gate._steps(skip_aseprite=True) for arg in cmd}
    assert in_ci <= in_gate, f"CI runs these and the gate does not: {sorted(in_ci - in_gate)}"


def test_synced_steps_run_from_the_committed_lock(gate):
    steps = _uv_steps(gate._steps(skip_aseprite=False))
    assert steps, "no `uv run` steps were found"
    for cmd in steps:
        assert cmd[2] == "--locked", f"unlocked `uv run` can rewrite uv.lock: {cmd}"


def test_no_sync_still_skips_the_sync(gate):
    for cmd in _uv_steps(gate._steps(skip_aseprite=False, no_sync=True)):
        assert cmd[2] == "--no-sync" and "--locked" not in cmd, cmd


def test_the_editor_step_runs_the_editor_tier_and_lists_skips(gate):
    with_editor = dict(gate._steps(skip_aseprite=False))
    assert with_editor[gate.INTEGRATION][-2:] == ["--run-aseprite", "-rs"]
    without = dict(gate._steps(skip_aseprite=True))
    assert gate.INTEGRATION not in without
    assert not any("--run-aseprite" in cmd for cmd in without.values())


def test_the_showcase_check_is_opt_in(gate):
    assert not any("verify_showcase.py" in " ".join(c) for _, c in gate._steps(False))
    assert any("scripts/verify_showcase.py" in c for _, c in gate._steps(False, showcase=True))


@pytest.mark.parametrize(("line", "counts"), [
    ("1731 passed, 837 skipped in 45.11s", "1731 passed, 837 skipped"),
    ("2566 passed, 2 skipped in 1156.87s (0:19:16)", "2566 passed, 2 skipped"),
    ("===== 2 failed, 1760 passed, 837 skipped in 48.33s =====",
     "2 failed, 1760 passed, 837 skipped"),
    ("1 error in 0.68s", "1 error"),
])
def test_the_pytest_summary_is_read_back(gate, line, counts):
    assert gate._pytest_summary(["....  [100%]", line]) == counts


def test_editor_skips_are_counted_from_the_skip_report(gate):
    lines = [
        "SKIPPED [1] tests\\test_figure.py:770: workspace/ is untracked",
        "SKIPPED [3] tests\\test_tools.py:12: needs --run-aseprite (Aseprite integration test)",
        "SKIPPED [2] tests\\test_golden.py:9: --run-aseprite was given but Aseprite was not "
        "found: no file",
    ]
    assert gate._editor_skips(lines) == 5


def test_an_editor_tier_that_skipped_for_want_of_an_editor_fails(gate, monkeypatch):
    output = ["s" * 40, "SKIPPED [837] tests\\test_tools.py:1: needs --run-aseprite "
              "(Aseprite integration test)", "1731 passed, 837 skipped in 43.50s"]
    monkeypatch.setattr(gate, "_run", lambda cmd: (0, output))
    code, result = gate._run_step(gate.INTEGRATION, ["uv", "run", "pytest"])
    assert code == 0 and not result.ok
    assert result.counts == "1731 passed, 837 skipped"
    assert "837 editor test(s) were skipped" in result.notes[0]


def _probe_with(gate, aseprite_path: str) -> dict:
    env = dict(os.environ, ASEPRITE_PATH=aseprite_path)
    out = subprocess.run([sys.executable, "-c", gate._PROBE], env=env, capture_output=True,
                         text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_preflight_reports_a_missing_editor(gate, tmp_path):
    missing = str(tmp_path / "nowhere" / "aseprite")
    info = _probe_with(gate, missing)
    assert "editor" not in info and missing in info["editor_error"]
    assert gate._editor_line(info).startswith("aseprite NOT FOUND: ")


def test_no_step_runs_when_the_editor_is_missing(gate, tmp_path, monkeypatch, capsys):
    info = _probe_with(gate, str(tmp_path / "nowhere" / "aseprite"))
    ran = []
    monkeypatch.setattr(gate.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(gate, "_probe_target", lambda no_sync: info)
    monkeypatch.setattr(gate, "_run_step", lambda name, cmd: ran.append(name))
    assert gate.main(["--no-sync"]) == 1
    out = capsys.readouterr().out
    assert not ran, f"steps ran with no editor: {ran}"
    assert "aseprite NOT FOUND" in out and "--skip-aseprite" in out
    assert "FAIL  editor preflight" in out


def test_a_failed_probe_is_not_reported_as_a_missing_editor(gate, monkeypatch, capsys):
    """The lock on the console script is an environment problem; telling the reader to
    set ASEPRITE_PATH would send them after the wrong thing."""
    ran = []
    monkeypatch.setattr(gate.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(gate, "_probe_target", lambda no_sync: {"probe_error": "os error 32"})
    monkeypatch.setattr(gate, "_run_step", lambda name, cmd: ran.append(name))
    assert gate.main([]) == 1
    out = capsys.readouterr().out
    assert not ran
    assert "os error 32" in out and "Re-run with --no-sync" in out
    assert "none was found" not in out
    assert "FAIL  environment probe" in out


def test_skip_aseprite_says_the_editor_tier_was_not_run(gate, monkeypatch, capsys):
    def fake_run_step(name, cmd):
        return 0, gate.StepResult(name, True, 0.0, counts="1 passed" if "pytest" in cmd else "")

    monkeypatch.setattr(gate.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(gate, "_probe_target", lambda no_sync: {
        "python": "3.12", "package": "0", "tree": "src", "editor_error": "absent"})
    monkeypatch.setattr(gate, "_run_step", fake_run_step)
    assert gate.main(["--skip-aseprite", "--no-sync"]) == 0
    out = capsys.readouterr().out
    assert "editor tier was NOT run" in out
    assert "NOT RUN (--skip-aseprite)" in out.split("--- summary ---")[1]
