"""Run the full local release gate, fail-fast, with a summary.

Runs each step in order and stops at the first failure:

  1. ruff check src tests scripts       (lint: the same invocation and rules as CI)
  2. pytest -q                          (pure-Python tests, which is what CI runs)
  3. pytest -q --run-aseprite           (integration + golden; needs a real Aseprite)
  4. gen_tool_docs.py --check           (docs/TOOLS.md is in sync with the registry)
  5. uv build                           (wheel + sdist build)

Usage:
    uv run python scripts/release_gate.py                 # everything
    uv run python scripts/release_gate.py --skip-aseprite # mirror CI (no Aseprite)
    uv run python scripts/release_gate.py --no-sync        # server holding the venv open

Each step runs through `uv run`, which syncs the project environment first. On Windows a
live MCP server holds `.venv\\Scripts\\aseprite-mcp.exe` open, the sync cannot replace
it, and the gate then fails at its first step with uv's exit code, reporting a lint
failure when lint is fine. `--no-sync` is for that case.

Exits 0 only if every run step passes.
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _steps(skip_aseprite: bool, no_sync: bool = False) -> list[tuple[str, list[str]]]:
    # `uv run` syncs the project environment before running anything, and on Windows a
    # live MCP server holds `.venv\\Scripts\\aseprite-mcp.exe` open, so the sync cannot
    # replace it and every step fails before it starts. That is the normal state on a
    # machine being used to drive Aseprite, which is also the machine this gate is meant
    # to run on. `--no-sync` skips the sync and uses the environment as it stands.
    #
    # Not the default: a release gate should verify a clean, freshly resolved
    # environment, and quietly skipping that would make the gate weaker than it looks.
    # The caller opts out, and the summary says so.
    run = ["uv", "run"] + (["--no-sync"] if no_sync else [])
    steps: list[tuple[str, list[str]]] = [
        # Exactly what CI runs. `--select F,E9` *overrides* [tool.ruff.lint], so the old
        # invocation checked pyflakes and syntax only and walked more paths while
        # enforcing fewer rules: a release could pass this gate and then fail CI on an
        # import order or a mutable default. A release gate weaker than the pull-request
        # gate inverts the point of having one.
        ("lint (ruff, CI's rule set)", [*run, "ruff", "check", "src", "tests", "scripts"]),
        ("pure tests (pytest)", [*run, "pytest", "-q"]),
    ]
    if not skip_aseprite:
        steps.append(
            ("integration (pytest --run-aseprite)", [*run, "pytest", "-q", "--run-aseprite"])
        )
    steps += [
        ("docs sync (gen_tool_docs --check)",
         [*run, "python", "scripts/gen_tool_docs.py", "--check"]),
        ("build (uv build)", ["uv", "build"]),
    ]
    return steps


def _describe_target(no_sync: bool) -> str:
    """The interpreter and the resolved package path the gate is about to test.

    Printed rather than assumed: every gate run during the 0.9.0 work had to assert this
    separately, because a scratch environment built with uv can silently resolve
    `aseprite_mcp` to a different checkout (a cached editable wheel keyed on name and
    version). A gate that does not say which tree it tested is one you have to verify by
    hand before you can believe it.
    """
    cmd = ["uv", "run"] + (["--no-sync"] if no_sync else []) + [
        "python", "-c",
        "import sys, pathlib, aseprite_mcp as m; "
        "print(f'python {sys.version.split()[0]} | {m.__version__} | "
        "{pathlib.Path(m.__file__).resolve().parent}')",
    ]
    try:
        out = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
                             timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
        return f"could not determine the target environment: {exc}"
    line = (out.stdout or "").strip().splitlines()
    return line[-1] if line else "could not determine the target environment"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full local release gate.")
    parser.add_argument(
        "--skip-aseprite", action="store_true",
        help="Skip the --run-aseprite integration step (mirrors headless CI).",
    )
    parser.add_argument(
        "--no-sync", action="store_true",
        help="Pass --no-sync to uv run, for when a live MCP server holds the venv's "
             "console script open and the sync cannot replace it. Uses the environment "
             "as it stands rather than a freshly resolved one.",
    )
    args = parser.parse_args()

    # Line-buffer our own output. Each step's subprocess inherits this stdout and writes
    # to it unbuffered, so with the default block buffering the parent's headers arrive
    # after the output they are supposed to introduce, and "which tree am I testing"
    # lands at the bottom of the run.
    # Not a reconfigurable stream under every launcher, and the buffering is a
    # readability nicety rather than a correctness one, so failing to set it is fine.
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(line_buffering=True)

    if shutil.which("uv") is None:
        print("release-gate: 'uv' was not found on PATH. Install uv and retry.", file=sys.stderr)
        return 1

    steps = _steps(args.skip_aseprite, args.no_sync)
    results: list[tuple[str, bool, float]] = []
    print(f"release-gate: {len(steps)} steps (cwd={PROJECT_ROOT})")
    # Which tree and which interpreter, stated up front. A scratch environment can
    # resolve the package to a different checkout than the one being gated, and a gate
    # that does not say what it tested has to be re-verified by hand to be believed.
    print(f"release-gate: {_describe_target(args.no_sync)}")
    if args.no_sync:
        print("release-gate: --no-sync, so the environment is used as it stands "
              "rather than freshly resolved")
    print()

    for i, (name, cmd) in enumerate(steps, 1):
        print(f"==> [{i}/{len(steps)}] {name}\n    $ {' '.join(cmd)}")
        start = time.perf_counter()
        completed = subprocess.run(cmd, cwd=PROJECT_ROOT)
        elapsed = time.perf_counter() - start
        ok = completed.returncode == 0
        results.append((name, ok, elapsed))
        if not ok:
            print(f"\nrelease-gate: FAILED at '{name}' (exit {completed.returncode}).")
            if not args.no_sync:
                # The most likely cause on this project, and the one that reports a
                # lint failure when lint is fine, so it is worth naming rather than
                # leaving the reader to doubt the step.
                print("release-gate: if that was a 'file is being used by another "
                      "process' error from uv, a live MCP server is holding the venv's "
                      "console script open. Re-run with --no-sync.")
            _summary(results, total=len(steps))
            return completed.returncode or 1
        print(f"    ok ({elapsed:.1f}s)\n")

    print("release-gate: all steps passed.")
    _summary(results, total=len(steps))
    return 0


def _summary(results: list[tuple[str, bool, float]], *, total: int) -> None:
    print("\n--- summary ---")
    for name, ok, elapsed in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name} ({elapsed:.1f}s)")
    if len(results) < total:
        print(f"  ----  {total - len(results)} step(s) not reached")


if __name__ == "__main__":
    raise SystemExit(main())
