"""Pure-Python tests for the workspace boundary: no Aseprite (always run).

Three defects are pinned here, each of which looked like a working path until the file
system disagreed:

* **installed-layout workspace default** (#54): `parents[3]` of `core/config.py` is the
  repo root only in a source checkout. `uvx aseprite-mcp` put the default workspace
  inside the Python installation.
* **Windows-hostile components** (#55): names that pass containment and then do not
  behave like the file the caller asked for: reserved devices, NTFS streams, trailing
  dots and spaces, and input that names the workspace directory itself.
* **sandbox reach** (#56): a junction disclosing names from outside the workspace, the
  Minecraft `pack_root` checks resolving against the process working directory, and a
  read building directory trees it never writes into.

The Windows-specific rejections are gated on `os.name == "nt"` in the implementation, so
the tests for them are gated the same way; CI runs on ubuntu, where every one of these
component spellings is a legal filename and refusing it would be over-rejection.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import ExportError, WorkspaceError
from aseprite_mcp.core.paths import ensure_output_path
from aseprite_mcp.tools import inspect as inspect_tools
from aseprite_mcp.tools import minecraft as mct

windows_only = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows-only: these spellings are legal POSIX filenames, and the guard that "
           "rejects them is gated on os.name == 'nt' so it never fires on the ubuntu CI "
           "runner.",
)

junction_only = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows-only: NTFS junctions exist only on Windows (`mklink /J`). The "
           "os.symlink test below is the POSIX mirror of the same property.",
)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A sandboxed workspace with absolute paths disabled (overrides conftest).

    The workspace is a *subdirectory* of tmp_path so ``tmp_path / "outside"`` is
    genuinely outside it.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(workspace))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    return workspace


# ============================================ #54 default workspace location
def test_this_checkout_is_detected_as_a_source_layout():
    """The source default must be unchanged, so existing clones behave exactly as now."""
    root = config._source_checkout_root()
    assert root is not None
    assert (root / "pyproject.toml").is_file()
    assert config.default_workspace() == root / "workspace"


@pytest.mark.parametrize(
    "fake_module_file",
    [
        # Simulated, not asserted against the layout this run happens to use: the whole
        # point is that the installed layout was never exercised.
        r"C:\proj\.venv\Lib\site-packages\aseprite_mcp\core\config.py",
        "/usr/lib/python3.12/site-packages/aseprite_mcp/core/config.py",
        "/home/u/.local/lib/python3.12/site-packages/aseprite_mcp/core/config.py",
    ],
)
def test_installed_layout_is_not_mistaken_for_a_checkout(fake_module_file):
    assert config._source_checkout_root(fake_module_file) is None


def test_installed_layout_defaults_to_a_per_user_directory(tmp_path, monkeypatch):
    """With no checkout to sit beside, the default must not be a site-packages sibling."""
    monkeypatch.delenv("ASEPRITE_MCP_WORKSPACE", raising=False)
    monkeypatch.setattr(config, "_source_checkout_root", lambda *a, **k: None)
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    default = config.default_workspace()
    assert home in default.parents, f"{default} is not under the per-user home"
    assert "site-packages" not in str(default)
    assert "aseprite-mcp" in default.parts
    # And it is actually usable, rather than a path that raises on first use.
    assert config.workspace() == default
    assert default.is_dir()


def test_explicit_workspace_wins_over_the_per_user_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_source_checkout_root", lambda *a, **k: None)
    chosen = tmp_path / "chosen"
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(chosen))
    assert config.workspace() == chosen
    assert chosen.is_dir()


def test_unusable_workspace_is_a_typed_error(tmp_path, monkeypatch):
    """Never a raw PermissionError/OSError: the remedy has to be in the message."""
    blocker = tmp_path / "a_file"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(blocker / "ws"))
    with pytest.raises(WorkspaceError, match="ASEPRITE_MCP_WORKSPACE"):
        config.workspace()


def _health_without_aseprite(monkeypatch) -> dict:
    """`health_check` up to the point it would launch Aseprite, which keeps this pure."""
    import asyncio

    from aseprite_mcp.core.errors import AsepriteNotFoundError
    from aseprite_mcp.tools import health

    monkeypatch.setattr(
        config, "find_aseprite", lambda: (_ for _ in ()).throw(AsepriteNotFoundError("stub"))
    )
    return asyncio.run(health.health_check())


def test_health_check_reports_the_resolved_workspace(ws, monkeypatch):
    """`health_check` is how a user finds out where their sprites went."""
    assert _health_without_aseprite(monkeypatch)["workspace"] == str(ws)


def test_health_check_reports_the_per_user_workspace_on_an_installed_layout(
    tmp_path, monkeypatch
):
    """The reported path must be the per-user directory, not a site-packages sibling."""
    monkeypatch.delenv("ASEPRITE_MCP_WORKSPACE", raising=False)
    monkeypatch.setattr(config, "_source_checkout_root", lambda *a, **k: None)
    home = tmp_path / "home"
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    reported = Path(_health_without_aseprite(monkeypatch)["workspace"])
    assert home in reported.parents
    assert reported == config.default_workspace()


# ======================================= #55 Windows-hostile path components
@windows_only
@pytest.mark.parametrize("name", ["NUL", "CON", "COM9", "LPT1", "AUX", "PRN", "nul",
                                  "NUL.png", "CON.aseprite", "sub/NUL", "con.png"])
def test_reserved_device_names_are_rejected(ws, name):
    """A write to NUL is discarded and reported as a success: silent data loss."""
    with pytest.raises(WorkspaceError, match="reserved Windows device name"):
        config.resolve(name)


@windows_only
def test_reserved_device_name_blocks_the_output_helper_too(ws):
    with pytest.raises(WorkspaceError, match="reserved Windows device name"):
        ensure_output_path("NUL", overwrite=True)


@windows_only
def test_nul_write_used_to_report_success_while_writing_nothing(ws):
    """The shape of the defect, pinned so a relaxation is visible.

    ``ensure_output_path("NUL", overwrite=True)`` returned <ws>/NUL, the write went to the
    device, and the workspace stayed empty while the tool reported the path it had
    "written".
    """
    with pytest.raises(WorkspaceError):
        ensure_output_path("NUL", overwrite=True)
    assert list(ws.iterdir()) == []


@windows_only
@pytest.mark.parametrize("name", ["sprite.png:stash", "sprite.png::$DATA", "a/b.png:s"])
def test_alternate_data_streams_are_rejected(ws, name):
    """A stream leaves the main file untouched and is invisible to list_sprites."""
    (ws / "sprite.png").write_bytes(b"MAIN")
    with pytest.raises(WorkspaceError, match="alternate data stream"):
        ensure_output_path(name, overwrite=True)
    assert (ws / "sprite.png").read_bytes() == b"MAIN"


@windows_only
@pytest.mark.parametrize("name", ["brand new.png ", "trail.png.", "dir /x.png", "d./x.png"])
def test_trailing_dot_or_space_is_rejected(ws, name):
    """Windows strips these, so the reported path is not the path that exists."""
    with pytest.raises(WorkspaceError, match="ends with a space or a dot"):
        ensure_output_path(name)


@windows_only
def test_the_reported_path_is_the_path_that_gets_created(ws):
    """The property the trailing-space rejection exists to protect."""
    out = ensure_output_path("brand new.png")
    out.write_bytes(b"x")
    assert out.exists() and out.name in {p.name for p in ws.iterdir()}


@pytest.mark.parametrize("name", ["", ".", "a/..", "./", "  ", "a/b/../.."])
def test_input_naming_no_file_is_rejected(ws, name):
    """Each of these returned the workspace directory, which a read tool then opened."""
    with pytest.raises(WorkspaceError, match=r"No filename|names the workspace directory"):
        config.resolve(name)


# ------------------------------------------- already clean: must stay clean
@pytest.mark.parametrize("name", ["a/b/c.png", "a//b/c.png", "A.PNG", "sprites/hero.ase",
                                  " leading.png", "a.b.c.png", "_under.png"])
def test_ordinary_names_are_still_accepted(ws, name):
    """The fix must not over-reject: duplicated separators, case, dots in the middle."""
    out = config.resolve(name)
    assert out.is_relative_to(ws.resolve())


@windows_only
@pytest.mark.parametrize("name", ["a\\b\\c.png", "mixed/sep\\c.png"])
def test_backslash_separators_still_work(ws, name):
    assert config.resolve(name).is_relative_to(ws.resolve())


@windows_only
@pytest.mark.parametrize(
    "name",
    [r"\\?\C:\x.png", r"\\.\C:\x.png", r"\\server\share\x.png", "x\x00y.png", "C:"],
)
def test_unc_device_and_nul_byte_forms_still_fail_closed(ws, name):
    """All of these were already refused; they must keep raising a *typed* error.

    ``x\\x00y.png`` used to escape as a raw ``ValueError`` from `stat`, which reached the
    client as an untyped failure with no remedy in it.
    """
    with pytest.raises(WorkspaceError):
        config.resolve(name)


@windows_only
def test_drive_relative_paths_stay_contained(ws):
    """``<same drive>:name`` is relative to the workspace, so it must still be allowed.

    The drive letter is taken from the workspace rather than hardcoded: a different drive
    is a genuine escape and is rejected by the containment check.
    """
    drive = ws.resolve().drive  # e.g. "C:"
    assert config.resolve(f"{drive}x.png") == (ws.resolve() / "x.png")
    other = "F:" if drive.upper() != "F:" else "C:"
    with pytest.raises(WorkspaceError, match=r"escapes the workspace|Absolute paths"):
        config.resolve(f"{other}x.png")


@windows_only
def test_permissive_branch_canonicalises(tmp_path, monkeypatch):
    """Returned verbatim before, so '..' segments reached manifests and mkdir."""
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", "1")
    messy = tmp_path / "here" / ".." / "there" / "out.png"
    out = config.resolve(str(messy))
    assert ".." not in out.parts
    assert out == tmp_path / "there" / "out.png"


def test_permissive_relative_paths_still_anchor_on_the_workspace(tmp_path, monkeypatch):
    """Permissive mode widens what is allowed; it does not move the anchor to the CWD."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(workspace))
    monkeypatch.setenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", "1")
    assert config.resolve("sub/x.png") == workspace / "sub" / "x.png"


# ==================================================== #56 list_sprites reach
def _junction(link: Path, target: Path) -> None:
    """Create an NTFS junction, skipping the test if the OS refuses."""
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"cannot create a junction here: {proc.stdout} {proc.stderr}")


@junction_only
def test_list_sprites_does_not_follow_a_junction_out_of_the_workspace(ws, tmp_path):
    """`is_symlink()` is False for a junction, so rglob walked straight through one.

    This is the Windows mirror of the `os.symlink` escape tests in test_output_paths.py,
    which skip on an unprivileged Windows account and so never covered this.
    """
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "tax_return.png").write_bytes(b"x" * 11)
    (outside / "nested").mkdir()
    (outside / "nested" / "passport.jpg").write_bytes(b"y" * 7)
    (ws / "mine.aseprite").write_bytes(b"ok")
    _junction(ws / "refs", outside)

    out = inspect_tools.list_sprites()
    names = [entry["name"] for entry in out["files"]]
    assert names == ["mine.aseprite"], f"disclosed outside the workspace: {names}"
    assert out["count"] == 1


@junction_only
def test_list_sprites_still_lists_through_a_junction_that_stays_inside(ws):
    """Not every junction escapes; an internal one must keep working."""
    real = ws / "real"
    real.mkdir()
    (real / "hero.aseprite").write_bytes(b"ok")
    _junction(ws / "alias", real)

    names = {entry["name"] for entry in inspect_tools.list_sprites()["files"]}
    assert "real/hero.aseprite" in names
    assert "alias/hero.aseprite" in names


def test_list_sprites_lists_nested_workspace_files(ws):
    (ws / "a").mkdir()
    (ws / "a" / "one.png").write_bytes(b"1")
    (ws / "two.gif").write_bytes(b"22")
    (ws / "notes.txt").write_bytes(b"ignored")
    out = inspect_tools.list_sprites()
    assert [e["name"] for e in out["files"]] == ["a/one.png", "two.gif"]
    assert [e["bytes"] for e in out["files"]] == [1, 2]


def test_list_sprites_does_not_follow_a_symlink_out_of_the_workspace(ws, tmp_path):
    """The POSIX mirror of the junction test; skips on an unprivileged Windows account."""
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"s")
    try:
        os.symlink(outside, ws / "refs", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks on this system: {exc}")
    assert inspect_tools.list_sprites()["files"] == []


# ============================================= #56 Minecraft pack_root sandbox
@pytest.fixture
def stub_export(monkeypatch):
    """Stand in for the Aseprite-backed export calls, writing a stub PNG where asked."""
    def fake_info(filename):
        return {"path": filename, "width": 16, "height": 16, "colorMode": "rgb",
                "frameCount": 1, "layers": [{"name": "base"}], "tags": [], "slices": []}

    def fake_png(**kw):
        out = ensure_output_path(kw["output"], overwrite=True)
        out.write_bytes(b"\x89PNG stub")
        return {"ok": True, "output": str(out)}

    monkeypatch.setattr(mct.inspect, "get_sprite_info", fake_info)
    monkeypatch.setattr(mct.export, "export_png", fake_png)


def test_export_finds_pack_mcmeta_inside_the_workspace(ws, stub_export):
    """The plain bug: the texture lands under <ws>/<pack_root>/, so an unresolved
    `Path(pack_root)` checked the process working directory and a correctly built pack
    always reported a missing pack.mcmeta."""
    mct.write_pack_mcmeta("packs/good", overwrite=True)
    assert (ws / "packs" / "good" / "pack.mcmeta").is_file()
    out = mct.export_minecraft_texture("grate.aseprite", pack_root="packs/good",
                                       namespace="mcsc", category="block", overwrite=True)
    assert not [w for w in out["warnings"] if "pack.mcmeta" in w]


def test_export_still_warns_when_the_pack_is_not_initialised(ws, stub_export):
    out = mct.export_minecraft_texture("grate.aseprite", pack_root="packs/bare",
                                       namespace="mcsc", category="block", overwrite=True)
    assert any("pack.mcmeta" in w for w in out["warnings"])


def test_export_pack_root_cannot_escape_the_workspace(ws, stub_export):
    """An escaping pack_root must be refused, not turned into an existence oracle."""
    with pytest.raises((WorkspaceError, ExportError)):
        mct.export_minecraft_texture("grate.aseprite", pack_root="../outside",
                                     namespace="mcsc", category="block", overwrite=True)


def _animated_info(filename):
    return {"path": filename, "width": 16, "height": 16, "colorMode": "rgb",
            "frameCount": 4, "layers": [{"name": "base"}], "tags": [], "slices": []}


def test_export_does_not_write_the_png_when_the_sidecar_is_in_the_way(ws, monkeypatch):
    """Up-front validation: an existing sidecar used to leave a stripped PNG behind."""
    def exploding_sheet(**kw):
        raise AssertionError("export ran despite an existing sidecar")

    monkeypatch.setattr(mct.inspect, "get_sprite_info", _animated_info)
    monkeypatch.setattr(mct.export, "export_spritesheet", exploding_sheet)
    sidecar = ensure_output_path("packs/p/assets/mcsc/textures/block/lava.png.mcmeta",
                                 overwrite=True)
    sidecar.write_text("{}", encoding="utf-8")
    with pytest.raises(ExportError, match="already exists"):
        mct.export_minecraft_texture("lava.aseprite", pack_root="packs/p",
                                     namespace="mcsc", category="block",
                                     texture_name="lava")


def test_validate_finds_the_sidecar_inside_the_workspace(ws, monkeypatch):
    """`validate_minecraft_texture` had the same unresolved pack_root."""
    monkeypatch.setattr(mct.inspect, "get_sprite_info", _animated_info)
    png = ensure_output_path("packs/v/assets/mcsc/textures/block/lava.png", overwrite=True)
    png.write_bytes(b"stub")
    png.with_suffix(".png.mcmeta").write_text(json.dumps({"animation": {}}), encoding="utf-8")
    out = mct.validate_minecraft_texture("lava.aseprite", category="block",
                                        pack_root="packs/v", namespace="mcsc",
                                        texture_name="lava")
    assert out["validation"]["passed"], out["validation"]["errors"]


def test_validate_refuses_a_pack_root_outside_the_workspace(ws, stub_export):
    with pytest.raises(ExportError, match="cannot be checked"):
        mct.validate_minecraft_texture("lava.aseprite", category="block",
                                       pack_root="../outside", namespace="mcsc",
                                       texture_name="lava")


# ================================================ #56 create_parent on reads
def test_read_resolve_creates_no_directories(ws):
    """Five directories used to appear from a call that wrote nothing."""
    out = config.resolve("a/b/c/d/e/never_written.png")
    assert out == (ws / "a" / "b" / "c" / "d" / "e" / "never_written.png").resolve()
    assert not (ws / "a").exists()
    assert list(ws.iterdir()) == []


def test_failing_read_tool_creates_no_directories(ws, monkeypatch):
    """`get_sprite_info` on an absent nested path built the tree before raising."""
    monkeypatch.setattr(inspect_tools, "run_lua",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no such file")))
    with pytest.raises(RuntimeError):
        inspect_tools.get_sprite_info("deep/nested/absent.aseprite")
    assert not (ws / "deep").exists()


def test_output_path_still_creates_its_parent(ws):
    out = ensure_output_path("nested/deep/sheet.png")
    assert out.parent.is_dir()


def test_create_parent_false_is_no_longer_a_no_op(ws):
    out = ensure_output_path("nested/deep/sheet.png", create_parent=False)
    assert not out.parent.exists()
    assert out == (ws / "nested" / "deep" / "sheet.png").resolve()


# --------------------------------------------- the two spellings of one workspace (#99)
# `resolve` canonicalises before it checks containment, which is what stops a junction
# from reaching outside the workspace and also what makes every tool hand back a path
# that need not look like the configured one. `health_check` reported the configured
# value, so behind a relocated Documents folder the two disagreed on the drive letter and
# read as a sandbox escape. `describe_workspace` takes both paths rather than reading
# them, which is what lets the differing case be tested on a runner with no junction.
def test_one_spelling_is_reported_as_one_field():
    report = config.describe_workspace("/work/ws", "/work/ws")
    assert report == {"workspace": "/work/ws"}


def test_a_differing_resolution_reports_both_and_says_they_are_one_place():
    report = config.describe_workspace(
        r"C:\Users\x\Documents\ws", r"F:\Users\x\Documents\ws")

    assert report["workspace"] == r"F:\Users\x\Documents\ws", "files land at the resolved one"
    assert report["workspace_configured"] == r"C:\Users\x\Documents\ws"
    note = report["workspace_note"]
    assert r"C:\Users\x\Documents\ws" in note and r"F:\Users\x\Documents\ws" in note
    assert "one directory" in note, "the note has to defuse the sandbox-escape reading"


def test_the_resolved_path_is_the_one_called_workspace():
    """Not a cosmetic choice. Every other tool returns resolved paths, so `workspace`
    has to mean the same thing here or the report cannot be compared with them."""
    report = config.describe_workspace("configured", "resolved")
    assert report["workspace"] == "resolved"


def test_a_path_object_is_described_as_its_string():
    report = config.describe_workspace(Path("/a/b"), Path("/a/b"))
    assert report == {"workspace": str(Path("/a/b"))}


def test_the_comparison_does_not_depend_on_the_platform():
    """`Path` equality is case-insensitive on Windows and case-sensitive elsewhere, so a
    report built on it would differ by machine. A spelling that differs only in case is
    still worth showing: it is the spelling the other tools will return."""
    report = config.describe_workspace("/Work/WS", "/work/ws")
    assert report["workspace_configured"] == "/Work/WS"


def test_the_resolved_workspace_is_the_one_the_sandbox_uses(ws):
    """One definition of where the workspace is, so the report and the containment check
    cannot drift apart about it."""
    assert config.resolved_workspace() == ws.resolve()
    assert config.resolve("a.aseprite").parent == config.resolved_workspace()
