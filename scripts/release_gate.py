"""Run the full local release gate, fail-fast, with a summary.

Runs each step in order and stops at the first failure:

  1. ruff check . --select F,E9        (lint: no unused imports / undefined names)
  2. pytest -q                          (pure-Python tests — what CI runs)
  3. pytest -q --run-aseprite           (integration + golden; needs a real Aseprite)
  4. gen_tool_docs.py --check           (docs/TOOLS.md is in sync with the registry)
  5. uv build                           (wheel + sdist build)

Usage:
    uv run python scripts/release_gate.py                 # everything
    uv run python scripts/release_gate.py --skip-aseprite # mirror CI (no Aseprite)

Exits 0 only if every run step passes.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _steps(skip_aseprite: bool) -> list[tuple[str, list[str]]]:
    steps: list[tuple[str, list[str]]] = [
        ("lint (ruff F,E9)", ["uv", "run", "ruff", "check", ".", "--select", "F,E9"]),
        ("pure tests (pytest)", ["uv", "run", "pytest", "-q"]),
    ]
    if not skip_aseprite:
        steps.append(
            ("integration (pytest --run-aseprite)", ["uv", "run", "pytest", "-q", "--run-aseprite"])
        )
    steps += [
        ("docs sync (gen_tool_docs --check)",
         ["uv", "run", "python", "scripts/gen_tool_docs.py", "--check"]),
        ("build (uv build)", ["uv", "build"]),
    ]
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full local release gate.")
    parser.add_argument(
        "--skip-aseprite", action="store_true",
        help="Skip the --run-aseprite integration step (mirrors headless CI).",
    )
    args = parser.parse_args()

    if shutil.which("uv") is None:
        print("release-gate: 'uv' was not found on PATH. Install uv and retry.", file=sys.stderr)
        return 1

    steps = _steps(args.skip_aseprite)
    results: list[tuple[str, bool, float]] = []
    print(f"release-gate: {len(steps)} steps (cwd={PROJECT_ROOT})\n")

    for i, (name, cmd) in enumerate(steps, 1):
        print(f"==> [{i}/{len(steps)}] {name}\n    $ {' '.join(cmd)}")
        start = time.perf_counter()
        completed = subprocess.run(cmd, cwd=PROJECT_ROOT)
        elapsed = time.perf_counter() - start
        ok = completed.returncode == 0
        results.append((name, ok, elapsed))
        if not ok:
            print(f"\nrelease-gate: FAILED at '{name}' (exit {completed.returncode}).")
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
