"""scripts/verify_showcase.py, the parts that need no editor (pure tier).

Its table of generators and published files is the one thing a regeneration run cannot
check about itself: a generator or an image missing from it is never compared, and the
run reports a pass. So the table is held to the scripts that exist, the images that are
committed, and the README that documents both.

"Exist" and "committed" mean what git tracks, not what is on disk. A generator someone
is still drawing, or an image they have not added yet, is their work in progress and is
not this table's business until `git add` makes it part of the tree.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_showcase.py"
README = REPO / "scripts" / "showcase" / "README.md"


# Git sets these for the hooks it runs, and they point every git command at the repository
# being committed to. A hook that runs this suite would otherwise have the temporary
# repository below staged into the contributor's own index.
_REPOSITORY_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                         "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                         "GIT_NAMESPACE", "GIT_PREFIX")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git on the repository that holds `root`, whatever git itself was told."""
    env = {k: v for k, v in os.environ.items() if k not in _REPOSITORY_VARIABLES}
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


def _tracked(root: Path, directory: str, pattern: str = "*") -> set[Path]:
    """The files directly inside `directory` that git tracks, staged ones included.

    Outside a git checkout (an unpacked sdist), or with no git on PATH, there is no
    notion of tracked, so every file on disk counts, as it did before."""
    on_disk = {p for p in (root / directory).glob(pattern) if p.is_file()}
    if shutil.which("git") is None:
        return on_disk
    proc = _git(root, "ls-files", "-z", "--", directory)
    if proc.returncode != 0:
        return on_disk
    return on_disk & {root / name for name in proc.stdout.split("\0") if name}


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location("verify_showcase", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_generator_script_is_run(verify):
    scripts = {p.stem for p in _tracked(REPO, "scripts/showcase", "*.py")}
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
    tracked = {f"docs/assets/showcase/{p.name}"
               for p in _tracked(REPO, "docs/assets/showcase")}
    uncompared = sorted(tracked - set(published))
    assert not uncompared, (
        f"showcase images no generator in verify_showcase.py accounts for: {uncompared}")


@pytest.fixture
def copy_of_the_showcase(verify, tmp_path, monkeypatch):
    """A repository holding exactly what the table lists, tracked, for the table tests to
    be pointed at. Returns its root and a function that stages a path in it."""
    if shutil.which("git") is None:
        pytest.skip("needs git on PATH to build a repository to look at")
    scripts = tmp_path / "scripts" / "showcase"
    scripts.mkdir(parents=True)
    for name in (*verify.GENERATORS, *verify.HELPERS):
        (scripts / f"{name}.py").write_text("", encoding="utf-8")
    for outs in verify.GENERATORS.values():
        for _, dest in outs:
            (tmp_path / dest).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / dest).write_bytes(b"")

    def git(*args: str) -> None:
        proc = _git(tmp_path, *args)
        assert proc.returncode == 0, proc.stderr

    git("init", "-q")
    git("add", "--", ".")
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    return tmp_path, git


def test_work_in_progress_is_not_held_to_the_table(verify, copy_of_the_showcase):
    """A generator or an image that is on disk but not added to git must not fail a
    contributor's checks. This runs the two table tests themselves, so going back to
    listing the directory fails here."""
    root, _ = copy_of_the_showcase
    (root / "scripts" / "showcase" / "drawing_it_now.py").write_text("", encoding="utf-8")
    (root / "docs" / "assets" / "showcase" / "drawing_it_now.png").write_bytes(b"")

    test_every_generator_script_is_run(verify)
    test_every_published_file_is_committed_and_compared(verify)


def test_once_added_a_generator_and_its_image_must_be_listed(verify, copy_of_the_showcase):
    """The other half: `git add` is the point at which the table has to account for it."""
    root, git = copy_of_the_showcase
    (root / "scripts" / "showcase" / "just_added.py").write_text("", encoding="utf-8")
    (root / "docs" / "assets" / "showcase" / "just_added.png").write_bytes(b"")
    git("add", "--", "scripts/showcase/just_added.py", "docs/assets/showcase/just_added.png")

    with pytest.raises(AssertionError, match="just_added"):
        test_every_generator_script_is_run(verify)
    with pytest.raises(AssertionError, match=r"just_added\.png"):
        test_every_published_file_is_committed_and_compared(verify)


def test_git_is_asked_about_this_tree_even_inside_a_hook(copy_of_the_showcase, tmp_path_factory,
                                                         monkeypatch):
    """Git exports GIT_DIR and GIT_INDEX_FILE to hooks. Left in place they would aim the
    question, and the `git add` above, at the repository being committed to."""
    root, git = copy_of_the_showcase
    elsewhere = tmp_path_factory.mktemp("another-repository")
    assert _git(elsewhere, "init", "-q").returncode == 0
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(elsewhere / ".git" / "index"))

    (root / "scripts" / "showcase" / "added_in_a_hook.py").write_text("", encoding="utf-8")
    git("add", "--", "scripts/showcase/added_in_a_hook.py")
    names = {p.name for p in _tracked(root, "scripts/showcase", "*.py")}

    assert "added_in_a_hook.py" in names and len(names) > 1
    assert _git(elsewhere, "ls-files").stdout == "", "the other repository's index was written"


def test_outside_a_checkout_every_file_on_disk_counts(tmp_path, monkeypatch):
    """An unpacked sdist has no index to ask, and silence there would hide a real gap."""
    (tmp_path / "showcase").mkdir()
    (tmp_path / "showcase" / "one.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert {p.name for p in _tracked(tmp_path, "showcase", "*.py")} == {"one.py"}


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
