"""Run the full local release gate, fail-fast, with a summary.

Before any step it states what it is about to test: the interpreter, the package version
and the tree it resolves to, and the Aseprite executable and version. Then it runs each
step in order and stops at the first failure:

  1. ruff check src tests scripts       (lint: the same invocation and rules as CI)
  2. pytest                             (the pure tier, which is what CI runs)
  3. pytest --run-aseprite -rs          (pure + editor tier; needs a real Aseprite)
  4. gen_tool_docs.py --check           (docs/TOOLS.md is in sync with the registry)
  5. uv build                           (wheel + sdist build)
  6. verify_showcase.py                 (only with --showcase; regenerates the README art)

Usage:
    uv run --locked python scripts/release_gate.py                 # everything
    uv run --locked python scripts/release_gate.py --skip-aseprite # what CI runs, no editor
    uv run --locked python scripts/release_gate.py --showcase      # plus the showcase check
    uv run --no-sync python scripts/release_gate.py --no-sync      # server holding the venv

Each step runs through `uv run --locked`, which syncs the environment from the committed
uv.lock and fails if the lock is stale instead of rewriting it. On Windows a live MCP
server holds `.venv\\Scripts\\aseprite-mcp.exe` open, the sync cannot replace it, and the
gate then fails at its first step with uv's exit code, reporting a lint failure when lint
is fine. `--no-sync` is for that case.

Without --skip-aseprite, a missing editor fails the gate before any step runs, and the
editor step fails if any editor test was skipped for want of one. Exits 0 only if every
run step passes; the summary says plainly when the editor tier was not run.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INTEGRATION = "integration (pytest --run-aseprite)"

# Skip reasons tests/conftest.py gives an editor test that did not run for want of an
# editor. Seeing one in the editor step means that step tested nothing it exists for.
EDITOR_SKIP_REASONS = ("needs --run-aseprite", "Aseprite was not found")

# Run inside the target environment, so it reports the package and the editor that the
# steps will see rather than the ones this script's own interpreter would.
_PROBE = (
    "import json, pathlib, sys\n"
    "import aseprite_mcp as m\n"
    "from aseprite_mcp.core.config import find_aseprite\n"
    "info = {'python': sys.version.split()[0], 'package': m.__version__,\n"
    "        'tree': str(pathlib.Path(m.__file__).resolve().parent)}\n"
    "try:\n"
    "    info['editor'] = find_aseprite()\n"
    "except FileNotFoundError as exc:\n"
    "    info['editor_error'] = str(exc)\n"
    "print(json.dumps(info))\n"
)


@dataclass
class StepResult:
    name: str
    ok: bool
    elapsed: float
    counts: str = ""  # a pytest step's summary line, e.g. "1731 passed, 837 skipped"
    notes: list[str] = field(default_factory=list)


def _uv_run(no_sync: bool) -> list[str]:
    # `uv run` syncs the project environment before running anything, and on Windows a
    # live MCP server holds `.venv\\Scripts\\aseprite-mcp.exe` open, so the sync cannot
    # replace it and every step fails before it starts. That is the normal state on a
    # machine being used to drive Aseprite, which is also the machine this gate is meant
    # to run on. `--no-sync` skips the sync and uses the environment as it stands.
    #
    # Not the default: a release gate should verify a clean environment resolved from
    # the committed lock, and quietly skipping that would make the gate weaker than it
    # looks. `--locked` because a plain `uv run` rewrites a stale uv.lock in place, and
    # the gate would then pass against versions nobody reviewed.
    return ["uv", "run", "--no-sync"] if no_sync else ["uv", "run", "--locked"]


def _steps(skip_aseprite: bool, no_sync: bool = False,
           showcase: bool = False) -> list[tuple[str, list[str]]]:
    run = _uv_run(no_sync)
    # No `-q` on pytest: pyproject's addopts already sets it, a second one makes -qq, and
    # -qq drops the "N passed, M skipped" line this gate reports.
    steps: list[tuple[str, list[str]]] = [
        # Exactly what CI runs. `--select F,E9` *overrides* [tool.ruff.lint], so the old
        # invocation checked pyflakes and syntax only and walked more paths while
        # enforcing fewer rules: a release could pass this gate and then fail CI on an
        # import order or a mutable default. A release gate weaker than the pull-request
        # gate inverts the point of having one.
        ("lint (ruff, CI's rule set)", [*run, "ruff", "check", "src", "tests", "scripts"]),
        ("pure tests (pytest)", [*run, "pytest"]),
    ]
    if not skip_aseprite:
        # -rs lists every skip with its reason: two expected ones on a healthy run, and
        # the evidence when editor tests were skipped instead of run.
        steps.append((INTEGRATION, [*run, "pytest", "--run-aseprite", "-rs"]))
    steps += [
        ("docs sync (gen_tool_docs --check)",
         [*run, "python", "scripts/gen_tool_docs.py", "--check"]),
        ("build (uv build)", ["uv", "build"]),
    ]
    if showcase:
        steps.append(("showcase (verify_showcase)",
                      [*run, "python", "scripts/verify_showcase.py"]))
    return steps


def _probe_target(no_sync: bool) -> dict:
    """The interpreter, package, tree and editor the gate is about to test.

    Printed rather than assumed: every gate run during the 0.9.0 work had to assert the
    tree separately, because a scratch environment built with uv can silently resolve
    `aseprite_mcp` to a different checkout (a cached editable wheel keyed on name and
    version). A gate that does not say what it tested is one you have to verify by hand
    before you can believe it.
    """
    cmd = [*_uv_run(no_sync), "python", "-c", _PROBE]
    try:
        out = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
                             timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"probe_error": str(exc)}
    lines = (out.stdout or "").strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        tail = (out.stderr or out.stdout or "").strip().splitlines()[-5:]
        return {"probe_error": " | ".join(tail) or f"exit {out.returncode}, no output"}


def _editor_version(exe: str) -> str:
    """`Aseprite 1.3.18.6-x64`, or why it could not be read."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"version unknown ({exc})"
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0] if text else f"version unknown (exit {out.returncode})"


def _editor_line(info: dict) -> str:
    if "editor" in info:
        return f"aseprite {info['editor']} ({_editor_version(info['editor'])})"
    if "editor_error" in info:
        return f"aseprite NOT FOUND: {info['editor_error']}"
    return f"aseprite unknown: could not probe the environment: {info.get('probe_error')}"


def _target_line(info: dict) -> str:
    if "probe_error" in info:
        return f"could not determine the target environment: {info['probe_error']}"
    return f"python {info['python']} | {info['package']} | {info['tree']}"


_SUMMARY = re.compile(r"^=*\s*(\d+ \w+.*?) in [\d.]+s\b")
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)")


def _pytest_summary(lines: list[str]) -> str:
    """The counts from pytest's final line ("1731 passed, 837 skipped"), or ""."""
    for line in reversed(lines):
        m = _SUMMARY.match(line.strip())
        if m:
            return ", ".join(f"{n} {what}" for n, what in _COUNT.findall(m.group(1)))
    return ""


def _editor_skips(lines: list[str]) -> int:
    """How many tests -rs reported as skipped for want of an editor."""
    total = 0
    for line in lines:
        if line.startswith("SKIPPED") and any(r in line for r in EDITOR_SKIP_REASONS):
            m = re.match(r"SKIPPED \[(\d+)\]", line)
            total += int(m.group(1)) if m else 1
    return total


def _run(cmd: list[str]) -> tuple[int, list[str]]:
    """Run a step, streaming its output and keeping a copy to read the summary from."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    lines: list[str] = []
    with subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace") as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            lines.append(line.rstrip("\n"))
    return proc.returncode, lines


def _run_step(name: str, cmd: list[str]) -> tuple[int, StepResult]:
    start = time.perf_counter()
    code, lines = _run(cmd)
    result = StepResult(name, code == 0, time.perf_counter() - start)
    if "pytest" in cmd:
        result.counts = _pytest_summary(lines)
        if not result.counts:
            result.ok = False
            result.notes.append("no pytest summary line was found in the output")
    if name == INTEGRATION and code == 0:
        skipped = _editor_skips(lines)
        if skipped:
            result.ok = False
            result.notes.append(f"{skipped} editor test(s) were skipped for want of an "
                                "editor, so the editor tier did not run")
        elif " passed" not in result.counts:
            result.ok = False
            result.notes.append("no test passed, so the editor tier tested nothing")
    return code, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full local release gate.")
    parser.add_argument(
        "--skip-aseprite", action="store_true",
        help="Skip the --run-aseprite integration step (mirrors headless CI). The summary "
             "then says the editor tier was NOT run.",
    )
    parser.add_argument(
        "--no-sync", action="store_true",
        help="Run every step with `uv run --no-sync` instead of `uv run --locked`, for "
             "when a live MCP server holds the venv's console script open and the sync "
             "cannot replace it. Uses the environment as it stands rather than one "
             "synced from uv.lock.",
    )
    parser.add_argument(
        "--showcase", action="store_true",
        help="Also run scripts/verify_showcase.py, which regenerates the README images "
             "and compares them with the committed ones (needs Aseprite; minutes).",
    )
    args = parser.parse_args(argv)
    if args.showcase and args.skip_aseprite:
        parser.error("--showcase needs Aseprite, so it cannot be combined with "
                     "--skip-aseprite")

    # Line-buffer our own output, so each step's header arrives before the output it
    # introduces. Not a reconfigurable stream under every launcher, and the buffering is
    # a readability nicety rather than a correctness one, so failing to set it is fine.
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(line_buffering=True, errors="backslashreplace")

    if shutil.which("uv") is None:
        print("release-gate: 'uv' was not found on PATH. Install uv and retry.", file=sys.stderr)
        return 1

    steps = _steps(args.skip_aseprite, args.no_sync, args.showcase)
    print(f"release-gate: {len(steps)} steps (cwd={PROJECT_ROOT})")
    info = _probe_target(args.no_sync)
    print(f"release-gate: {_target_line(info)}")
    editor = _editor_line(info)
    print(f"release-gate: {editor}")
    if args.no_sync:
        print("release-gate: --no-sync, so the environment is used as it stands "
              "rather than synced from uv.lock")
    if args.skip_aseprite:
        print("release-gate: --skip-aseprite, so the editor tier will NOT be run")
    print()

    results: list[StepResult] = []
    if not args.skip_aseprite and "editor" not in info:
        print("release-gate: FAILED before any step: the integration step needs a real "
              "Aseprite and none was found. Set ASEPRITE_PATH to the Aseprite executable, "
              "or pass --skip-aseprite to run only what CI runs.")
        results.append(StepResult("editor preflight", False, 0.0))
        _summary(results, steps, args, editor)
        return 1

    for i, (name, cmd) in enumerate(steps, 1):
        print(f"==> [{i}/{len(steps)}] {name}\n    $ {' '.join(cmd)}")
        code, result = _run_step(name, cmd)
        results.append(result)
        if not result.ok:
            print(f"\nrelease-gate: FAILED at '{name}' (exit {code}).")
            for note in result.notes:
                print(f"release-gate: {note}")
            if not args.no_sync and code != 0:
                # The most likely cause on this project, and the one that reports a
                # lint failure when lint is fine, so it is worth naming rather than
                # leaving the reader to doubt the step.
                print("release-gate: if that was a 'file is being used by another "
                      "process' error from uv, a live MCP server is holding the venv's "
                      "console script open. Re-run with --no-sync.")
            _summary(results, steps, args, editor)
            return code or 1
        counts = f": {result.counts}" if result.counts else ""
        print(f"    ok ({result.elapsed:.1f}s){counts}\n")

    if args.skip_aseprite:
        print("release-gate: all run steps passed; the editor tier was NOT run "
              "(--skip-aseprite).")
    else:
        print("release-gate: all steps passed.")
    _summary(results, steps, args, editor)
    return 0


def _summary(results: list[StepResult], steps: list[tuple[str, list[str]]],
             args: argparse.Namespace, editor: str) -> None:
    print("\n--- summary ---")
    for r in results:
        counts = f": {r.counts}" if r.counts else ""
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.name} ({r.elapsed:.1f}s){counts}")
        for note in r.notes:
            print(f"        {note}")
    ran = {r.name for r in results}
    unreached = [name for name, _ in steps if name not in ran]
    if unreached:
        print(f"  ----  {len(unreached)} step(s) not reached")
    if args.skip_aseprite:
        print(f"  SKIP  {INTEGRATION}: NOT RUN (--skip-aseprite); nothing was tested "
              "against Aseprite")
    print(f"  {editor}")


if __name__ == "__main__":
    raise SystemExit(main())
