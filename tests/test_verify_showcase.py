"""scripts/verify_showcase.py, the parts that need no editor (pure tier).

Its table of generators and published files is the one thing a regeneration run cannot
check about itself: a generator or an image missing from it is never compared, and the
run reports a pass. So the table is held to the scripts that exist, the images that are
committed, and the README that documents both.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_showcase.py"
README = REPO / "scripts" / "showcase" / "README.md"


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location("verify_showcase", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_generator_script_is_run(verify):
    scripts = {p.stem for p in (REPO / "scripts" / "showcase").glob("*.py")}
    unlisted = scripts - set(verify.GENERATORS) - set(verify.HELPERS)
    assert not unlisted, (
        f"scripts/showcase has generators verify_showcase.py does not run: {sorted(unlisted)}."
        " Add them to GENERATORS (with the files they publish) or to HELPERS.")
    gone = (set(verify.GENERATORS) | set(verify.HELPERS)) - scripts
    assert not gone, f"verify_showcase.py lists scripts that do not exist: {sorted(gone)}"


def test_every_published_file_is_committed_and_compared(verify):
    published = [dest for outs in verify.GENERATORS.values() for _, dest in outs]
    assert len(published) == len(set(published)), "a committed path is listed twice"
    absent = [p for p in published if not (REPO / p).is_file()]
    assert not absent, f"listed as published but not in the repository: {absent}"
    on_disk = {f"docs/assets/showcase/{p.name}"
               for p in (REPO / "docs" / "assets" / "showcase").iterdir() if p.is_file()}
    uncompared = sorted(on_disk - set(published))
    assert not uncompared, (
        f"showcase images no generator in verify_showcase.py accounts for: {uncompared}")


def test_the_table_matches_the_showcase_readme(verify):
    """Loose on purpose: each generator, each name it writes and each name it is
    committed under has to appear in the README, so a rename on either side fails here
    without pinning the README's layout."""
    text = README.read_text(encoding="utf-8")
    absent = []
    for name, outs in verify.GENERATORS.items():
        absent += [f"{name}.py"] if f"{name}.py" not in text else []
        for written, dest in outs:
            absent += [w for w in (written, Path(dest).name) if w not in text]
            if Path(dest).parent.as_posix() + "/" not in text:
                absent.append(dest)
    assert not absent, f"in verify_showcase.py but not in scripts/showcase/README.md: {absent}"


def test_it_refuses_without_an_editor(tmp_path):
    env = dict(os.environ, ASEPRITE_PATH=str(tmp_path / "nowhere" / "aseprite"))
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out
    assert "Aseprite was not found" in out and "nothing was compared" in out, out
    assert "identical" not in out.lower() and "PASS" not in out, out


def test_a_non_empty_workspace_is_refused(verify, tmp_path, monkeypatch):
    """A leftover image could stand in for one a generator failed to write."""
    (tmp_path / "items.png").write_bytes(b"stale")
    monkeypatch.setattr(verify, "_editor", lambda: ("aseprite", "Aseprite 0"))
    monkeypatch.setattr(verify.subprocess, "run",
                        lambda *a, **k: pytest.fail("a generator ran"))
    assert verify.main(["--workspace", str(tmp_path)]) == 2
