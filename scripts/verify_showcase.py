"""Regenerate the showcase images and compare them byte for byte with the committed ones.

Runs every generator in scripts/showcase/ into one fresh, empty workspace, then compares
the SHA-256 of each published output with the file committed at HEAD (the blob, not the
working tree, so an uncommitted edit to an image cannot make a difference look like a
match). See scripts/showcase/README.md for why the images must reproduce and what to do
when one does not.

Usage:
    uv run --locked python scripts/verify_showcase.py
    uv run --locked python scripts/verify_showcase.py --only items walk
    uv run --locked python scripts/verify_showcase.py --workspace /tmp/showcase

Needs a real Aseprite and takes a few minutes. With no editor it refuses rather than
reporting anything. Exits 0 only when every generator ran and every published image is
identical; 1 on any difference, missing output or generator failure; 2 when it could not
start (no editor, or a workspace that is not empty).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_DIR = PROJECT_ROOT / "scripts" / "showcase"

# Generator -> ((name it writes in the workspace, path the repository commits it at), ...)
# in scripts/showcase/README.md's order. tests/test_verify_showcase.py holds this to that
# README and to the files actually committed. `tiles` publishes nothing but still runs, so
# a generator that stopped working is caught even when no image depends on it.
GENERATORS: dict[str, tuple[tuple[str, str], ...]] = {
    "orb": (("shading_stages.png", "docs/assets/showcase/shading_stages.png"),
            ("orb_3_full.png", "docs/assets/showcase/orb.png")),
    "bounce": (("throw.gif", "docs/assets/showcase/throw.gif"),),
    "items": (("items.png", "docs/assets/showcase/item_sheet.png"),),
    "walk": (("walk8_sheet.png", "docs/assets/showcase/walk8_sheet.png"),
             ("walk8.gif", "docs/assets/showcase/walk8.gif")),
    "skeleton": (("skeleton.png", "assets/skeleton.png"),),
    "zorder": (("zorder.gif", "docs/assets/showcase/zorder.gif"),
               ("zorder_pair.png", "docs/assets/showcase/zorder_pair.png")),
    "quantize": (("quantize_stages.png", "docs/assets/showcase/quantize_stages.png"),),
    "dungeon": (("dungeon.png", "docs/assets/showcase/dungeon.png"),
                ("dungeon.gif", "docs/assets/showcase/dungeon.gif")),
    "lava": (("lava.gif", "docs/assets/showcase/lava.gif"),),
    "attack": (("attack_sheet.png", "docs/assets/showcase/attack_sheet.png"),
               ("attack.gif", "docs/assets/showcase/attack.gif")),
    "smear": (("smear_stages.png", "docs/assets/showcase/smear_stages.png"),
              ("smear.gif", "docs/assets/showcase/smear.gif")),
    "golem": (("golem.png", "docs/assets/showcase/golem.png"),),
    "tiles": (),
}

# Modules in scripts/showcase/ that other generators import and that publish nothing.
HELPERS = ("golem_figure",)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _committed(path: str) -> bytes | None:
    proc = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=PROJECT_ROOT,
                          capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def _editor() -> tuple[str | None, str]:
    """(executable, version) or (None, why not)."""
    from aseprite_mcp.core.config import find_aseprite

    try:
        exe = find_aseprite()
    except FileNotFoundError as exc:
        return None, str(exc)
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
        version = (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        version = f"version unknown ({exc})"
    return exe, version


def _find_output(workspace: Path, name: str) -> Path | None:
    direct = workspace / name
    if direct.is_file():
        return direct
    return next((p for p in sorted(workspace.rglob(name)) if p.is_file()), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the showcase images and compare them with the committed "
                    "ones by SHA-256.")
    parser.add_argument("--only", nargs="+", choices=list(GENERATORS), metavar="GENERATOR",
                        help="Run only these generators and compare only their images "
                             f"(choices: {', '.join(GENERATORS)}).")
    parser.add_argument("--workspace", type=Path,
                        help="Generate into this directory (created if absent, must be "
                             "empty) and keep it. Default: a temporary directory, removed "
                             "afterwards.")
    args = parser.parse_args(argv)

    exe, version = _editor()
    if exe is None:
        print(f"verify-showcase: Aseprite was not found: {version}\n"
              "verify-showcase: the showcase generators drive a real Aseprite, so nothing "
              "was compared. Set ASEPRITE_PATH to the Aseprite executable and retry.",
              file=sys.stderr)
        return 2
    print(f"verify-showcase: aseprite {exe} ({version})")

    if args.workspace:
        workspace = args.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if any(workspace.iterdir()):
            print(f"verify-showcase: {workspace} is not empty; a leftover file could "
                  "stand in for one a generator failed to write.", file=sys.stderr)
            return 2
    else:
        workspace = Path(tempfile.mkdtemp(prefix="aseprite-showcase-"))
    print(f"verify-showcase: workspace {workspace}")

    selected = args.only or list(GENERATORS)
    env = dict(os.environ, ASEPRITE_MCP_WORKSPACE=str(workspace))
    failed: list[str] = []
    try:
        for name in selected:
            start = time.perf_counter()
            proc = subprocess.run([sys.executable, str(SHOWCASE_DIR / f"{name}.py")],
                                  cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            status = "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
            print(f"  [{name}] {status} ({time.perf_counter() - start:.0f}s)")
            if proc.returncode != 0:
                failed.append(name)
                print(proc.stdout[-2000:] + proc.stderr[-3000:])

        identical, different, missing = [], [], []
        for name in selected:
            for written, committed in GENERATORS[name]:
                produced = _find_output(workspace, written)
                blob = _committed(committed)
                if produced is None or blob is None:
                    missing.append(committed)
                    why = ("not produced by the run" if produced is None
                           else "not committed at HEAD")
                    print(f"  MISSING    {committed} ({written} {why})")
                elif _sha256(produced.read_bytes()) == _sha256(blob):
                    identical.append(committed)
                    print(f"  IDENTICAL  {committed}")
                else:
                    different.append(committed)
                    print(f"  DIFFERENT  {committed} (from {written})")
    finally:
        if not args.workspace:
            shutil.rmtree(workspace, ignore_errors=True)

    total = len(identical) + len(different) + len(missing)
    print(f"\nverify-showcase: {len(identical)} identical, {len(different)} different, "
          f"{len(missing)} missing of {total} published files; "
          f"{len(failed)} generator(s) failed{': ' + ', '.join(failed) if failed else ''}. "
          f"Aseprite: {version}")
    ok = not (failed or different or missing)
    print(f"verify-showcase: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("verify-showcase: a tool's output has changed. Find out which tool and why "
              "before recommitting an image (scripts/showcase/README.md).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
