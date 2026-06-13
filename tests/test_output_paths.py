"""Pure-Python tests for the no-clobber output-path policy — no Aseprite (always run).

Covers `core.paths.ensure_output_path`: existing targets are refused by default,
`overwrite=True` allows replacement, parent directories are created, and the
workspace sandbox (absolute paths, ``..`` escapes, and symlink escapes) is enforced.
"""

import os

import pytest

from aseprite_mcp.core.errors import ExportError, WorkspaceError
from aseprite_mcp.core.paths import ensure_output_path


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A sandboxed workspace with absolute paths disabled (overrides conftest)."""
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    return tmp_path


# ---------------------------------------------------------------- no-clobber
def test_existing_output_rejected_by_default(ws):
    (ws / "taken.png").write_bytes(b"x")
    with pytest.raises(WorkspaceError, match="already exists"):
        ensure_output_path("taken.png")


def test_existing_output_uses_caller_error_type(ws):
    (ws / "taken.png").write_bytes(b"x")
    with pytest.raises(ExportError, match="already exists"):
        ensure_output_path("taken.png", error_type=ExportError)


def test_overwrite_true_allows_replacement(ws):
    (ws / "taken.png").write_bytes(b"x")
    out = ensure_output_path("taken.png", overwrite=True)
    assert out == (ws / "taken.png").resolve()


def test_fresh_output_allowed(ws):
    out = ensure_output_path("brand_new.png")
    assert out == (ws / "brand_new.png").resolve()
    assert not out.exists()  # we only resolve/validate; we don't create the file


# ------------------------------------------------------------ parent creation
def test_parent_dirs_created(ws):
    out = ensure_output_path("nested/deep/sheet.png")
    assert out.parent.is_dir()
    assert out == (ws / "nested" / "deep" / "sheet.png").resolve()


# -------------------------------------------------------------- sandbox: paths
def test_absolute_path_rejected(ws):
    with pytest.raises(WorkspaceError, match="Absolute paths are disabled"):
        ensure_output_path(str(ws.parent / "outside.png"))


def test_dotdot_escape_rejected(ws):
    with pytest.raises(WorkspaceError, match="escapes the workspace"):
        ensure_output_path("../escape.png")


# ----------------------------------------------------------- sandbox: symlink
def _make_symlink(link, target):
    """Create a directory symlink, skipping the test if the OS/permissions disallow it."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # Windows w/o privilege, etc.
        pytest.skip(f"cannot create symlinks on this system: {exc}")


def test_symlink_escape_rejected(ws, tmp_path):
    """A symlink inside the workspace pointing outside must not let writes escape.

    Regression guard: ``config.resolve`` calls ``.resolve()`` (following symlinks)
    before the ``relative_to(workspace)`` check, so a path tunnelling through an
    escaping symlink is rejected rather than silently writing outside the sandbox.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    link = ws / "escape"
    _make_symlink(link, outside)

    with pytest.raises(WorkspaceError, match="escapes the workspace"):
        ensure_output_path("escape/evil.png")
    # Nothing was written through the symlink.
    assert not (outside / "evil.png").exists()


def test_symlink_within_workspace_allowed(ws):
    """A symlink that stays inside the workspace is fine (not every symlink escapes)."""
    inside = ws / "real_subdir"
    inside.mkdir()
    link = ws / "alias"
    _make_symlink(link, inside)

    out = ensure_output_path("alias/ok.png")
    assert out == (inside / "ok.png").resolve()
