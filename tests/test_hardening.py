"""Pure-Python tests for the v0.8.0 hardening pass: no Aseprite (always run).

Each group pins one guard that was missing or unsound before:

* **canvas geometry**: a per-axis cap alone lets 65535x65535 (~17 GB) through, so the
  *area* is capped too; `resize_canvas` / `crop_sprite` / `scale_sprite` had no cap at all.
* **pattern no-clobber**: `export_frames` and friends wrote over existing files silently.
* **inline payloads**: base64 images and text rasterization were unbounded.
* **timeout / executable resolution**: a negative or non-finite timeout disabled the
  guard, and the executable cache outlived an `ASEPRITE_PATH` change.

Every case here fires *before* Aseprite is launched, which is the point: these are
pre-flight checks, so they are testable (and enforced) on a machine with no Aseprite.
"""

import ast
import inspect
import io
import os
import pathlib
import sys

import pytest

from aseprite_mcp import server  # noqa: F401  importing registers every tool
from aseprite_mcp.app import mcp
from aseprite_mcp.core import config, limits, luagen, metadata
from aseprite_mcp.core.errors import ExportError, ValidationFailed, WorkspaceError
from aseprite_mcp.core.paths import ensure_output_pattern, expansion_matches
from aseprite_mcp.core.runner import _run_bounded, _truncate
from aseprite_mcp.tools import brushes, cels, export, image, reference, slices, sprite, text

# `_tool_manager` is the only place a tool's underlying function is reachable, and
# the registry-wide groups below call it directly. `list_tools()` is the wire view.
REGISTERED = {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A sandboxed workspace with absolute paths disabled (overrides conftest)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(workspace))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    return workspace


# =========================================================== canvas geometry
def test_canvas_size_at_limits_is_allowed():
    assert limits.check_canvas_size(4096, 4096) == (4096, 4096)
    assert limits.check_canvas_size(16384, 1024) == (16384, 1024)


def test_canvas_area_caps_two_legal_axes():
    """Both axes are within the per-axis cap, yet the canvas is ~1 GB of pixels."""
    with pytest.raises(ValidationFailed, match=r"pixels; maximum is"):
        limits.check_canvas_size(16384, 16384)


def test_canvas_dimension_cap():
    with pytest.raises(ValidationFailed, match="maximum dimension"):
        limits.check_canvas_size(20000, 1)


@pytest.mark.parametrize("w,h", [(0, 10), (10, 0), (-1, 10)])
def test_canvas_rejects_non_positive(w, h):
    with pytest.raises(ValidationFailed, match="at least 1x1"):
        limits.check_canvas_size(w, h)


def test_canvas_rejects_non_numeric():
    with pytest.raises(ValidationFailed, match="whole numbers"):
        limits.check_canvas_size("wide", 10)


def test_create_sprite_rejects_oversized_canvas(ws):
    """The old bound was 1-65535 per axis, which allowed a ~17 GB allocation."""
    with pytest.raises(ValidationFailed):
        sprite.create_sprite("big.aseprite", 65535, 65535)
    assert not (ws / "big.aseprite").exists()


@pytest.mark.parametrize(
    "call",
    [
        lambda: sprite.resize_canvas("s.aseprite", 65535, 65535),
        lambda: sprite.crop_sprite("s.aseprite", 0, 0, 65535, 65535),
        lambda: sprite.scale_sprite("s.aseprite", width=65535, height=65535),
    ],
)
def test_geometry_tools_reject_oversized_canvas(ws, call):
    """These three had no size validation at all before."""
    with pytest.raises(ValidationFailed):
        call()


@pytest.mark.parametrize("factor", [0, -2.0, float("inf"), float("nan")])
def test_scale_sprite_rejects_bad_factor(ws, factor):
    with pytest.raises(ValidationFailed, match="positive finite"):
        sprite.scale_sprite("s.aseprite", factor=factor)


# ====================================================== pattern no-clobber
def test_pattern_refuses_when_expansion_exists(ws):
    (ws / "frames").mkdir()
    (ws / "frames" / "walk_1.png").write_bytes(b"x")
    with pytest.raises(WorkspaceError, match="would overwrite"):
        ensure_output_pattern("frames/walk_{frame}.png")


def test_pattern_allows_a_clean_directory(ws):
    out = ensure_output_pattern("frames/walk_{frame}.png")
    assert out == (ws / "frames" / "walk_{frame}.png")


def test_pattern_overwrite_opt_in(ws):
    (ws / "frames").mkdir()
    (ws / "frames" / "walk_1.png").write_bytes(b"x")
    assert ensure_output_pattern("frames/walk_{frame}.png", overwrite=True)


def test_pattern_does_not_match_unrelated_files(ws):
    (ws / "frames").mkdir()
    (ws / "frames" / "idle_1.png").write_bytes(b"x")
    ensure_output_pattern("frames/walk_{frame}.png")  # different stem: no conflict


def test_pattern_literals_are_glob_escaped(ws):
    """A literal '[' in the name must match itself, not act as a character class.

    Unescaped, the glob 'a[b]_*.png' matches the file 'ab_1.png', a false conflict
    that would block a perfectly good export. Escaped, it only matches a real
    'a[b]_1.png'.
    """
    (ws / "ab_1.png").write_bytes(b"x")
    ensure_output_pattern("a[b]_{frame}.png")  # no false conflict


def test_pattern_placeholder_in_directory_component(ws):
    (ws / "tag_run").mkdir()
    (ws / "tag_run" / "f.png").write_bytes(b"x")
    with pytest.raises(WorkspaceError, match="would overwrite"):
        ensure_output_pattern("tag_{tag}/f.png")


def test_expansion_matches_handles_plain_paths(ws):
    (ws / "plain.png").write_bytes(b"x")
    assert expansion_matches(ws / "plain.png") == [ws / "plain.png"]
    assert expansion_matches(ws / "absent.png") == []


@pytest.mark.parametrize(
    "call",
    [
        lambda: export.export_frames("s.aseprite", "out/f_{frame}.png"),
        lambda: export.export_tags("s.aseprite", "out/{tag}.png"),
        lambda: export.export_layers("s.aseprite", "out/{layer}.png"),
    ],
)
def test_pattern_exports_are_no_clobber(ws, call):
    """Previously these wrote straight over existing files with no way to object."""
    (ws / "out").mkdir()
    (ws / "out" / "f_1.png").write_bytes(b"x")
    (ws / "out" / "run.png").write_bytes(b"x")
    with pytest.raises(ExportError, match="would overwrite"):
        call()


@pytest.mark.parametrize(
    "call",
    [
        lambda: export.export_layer("s.aseprite", "body", "taken.png"),
        lambda: export.export_onion_skin("s.aseprite", 1, "taken.png"),
        lambda: export.import_image("flat.png", "taken.png"),
    ],
)
def test_single_file_exports_are_no_clobber(ws, call):
    (ws / "taken.png").write_bytes(b"x")
    with pytest.raises((ExportError, WorkspaceError), match="already exists"):
        call()


# ========================================================= inline payloads
def test_base64_payload_cap(ws):
    oversized = "A" * (limits.MAX_IMAGE_BYTES * 4 // 3 + 8)
    with pytest.raises(ValidationFailed, match="maximum is"):
        image.draw_image_base64("s.aseprite", oversized, 0, 0)


def test_decoded_size_is_exact_for_every_length():
    """The pre-decode size check must not overestimate.

    An overestimate rejects a payload that decodes to exactly MAX_IMAGE_BYTES, since
    base64 pads up to a multiple of 4 and the naive (len * 3) // 4 inverse counts the
    padding as data.
    """
    import base64

    wrong = [
        n for n in range(0, 300)
        if image.decoded_size(base64.b64encode(b"x" * n).decode()) != n
    ]
    assert not wrong, f"decoded_size wrong for lengths: {wrong[:10]}"


def test_payload_exactly_at_the_cap_is_not_rejected():
    """A payload decoding to exactly the cap is allowed; one byte over is not."""
    import base64

    at_cap = base64.b64encode(b"x" * 3002).decode()
    assert image.decoded_size(at_cap) == 3002
    limits.check_size_bytes("payload", image.decoded_size(at_cap), 3002)  # no raise
    with pytest.raises(ValidationFailed):
        limits.check_size_bytes("payload", image.decoded_size(at_cap), 3001)


def test_base64_small_payload_passes_the_size_gate(ws):
    """A tiny payload must fail later (bad image / no Aseprite), never on size."""
    with pytest.raises(Exception) as excinfo:
        image.draw_image_base64("s.aseprite", "aGVsbG8=", 0, 0)
    assert "maximum is" not in str(excinfo.value)


def test_text_scale_cap(ws):
    with pytest.raises(ValidationFailed, match="scale is"):
        text.draw_text("s.aseprite", "hi", 0, 0, "red", scale=1000)


def test_text_font_size_cap(ws):
    with pytest.raises(ValidationFailed, match="font_size is"):
        text.draw_text("s.aseprite", "hi", 0, 0, "red", font_size=5000)


def test_text_budget_is_enforced_while_rendering():
    """The cap must fire during rasterization, not after the list is materialized."""
    from PIL import ImageFont

    font = ImageFont.load_default()
    with pytest.raises(ValidationFailed, match="maximum is"):
        text._render_text_pixels("x" * 400, limits.MAX_TEXT_SCALE, font, 1, 128)


# ================================================ timeout & exe resolution
def test_timeout_default_when_unset(monkeypatch):
    monkeypatch.delenv("ASEPRITE_MCP_TIMEOUT", raising=False)
    assert config.timeout() == config.DEFAULT_TIMEOUT


@pytest.mark.parametrize("raw", ["not-a-number", "", "  ", "nan", "inf", "-inf"])
def test_timeout_falls_back_on_garbage(monkeypatch, raw):
    monkeypatch.setenv("ASEPRITE_MCP_TIMEOUT", raw)
    assert config.timeout() == config.DEFAULT_TIMEOUT


@pytest.mark.parametrize(
    "raw,expected",
    [("0", config.MIN_TIMEOUT), ("-5", config.MIN_TIMEOUT), ("99999", config.MAX_TIMEOUT)],
)
def test_timeout_is_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv("ASEPRITE_MCP_TIMEOUT", raw)
    assert config.timeout() == expected


def test_timeout_honours_a_sane_value(monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_TIMEOUT", "30")
    assert config.timeout() == 30.0


def test_aseprite_path_pointing_at_a_directory_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_cached_exe", None)
    monkeypatch.setattr(config, "_cached_for_env", None)
    monkeypatch.setenv("ASEPRITE_PATH", str(tmp_path))
    with pytest.raises(config.AsepriteNotFoundError, match="directory"):
        config.find_aseprite()


def test_exe_cache_follows_aseprite_path_changes(tmp_path, monkeypatch):
    """A cached executable must not survive a change to ASEPRITE_PATH."""
    first, second = tmp_path / "one", tmp_path / "two"
    first.write_text("#!/bin/sh\n")
    second.write_text("#!/bin/sh\n")
    monkeypatch.setattr(config, "_cached_exe", None)
    monkeypatch.setattr(config, "_cached_for_env", None)

    monkeypatch.setenv("ASEPRITE_PATH", str(first))
    assert config.find_aseprite() == str(first)
    monkeypatch.setenv("ASEPRITE_PATH", str(second))
    assert config.find_aseprite() == str(second)


# ==================================================== process output bound
def test_truncate_keeps_short_output_verbatim():
    assert _truncate("short", 100) == "short"


def test_truncate_bounds_long_output_and_keeps_the_tail():
    out = _truncate("A" * 500 + "TAIL", 10)
    assert out.endswith("TAIL")
    assert "truncated" in out
    assert len(out) < 200


def test_truncate_bound_is_in_characters():
    """The cap counts characters, and the notice says so.

    Multibyte input must not be measured as if it were bytes, or the reported unit
    and the constant's name would disagree with what is actually enforced.
    """
    out = _truncate("\u4e00" * 100, 10)
    assert len(out.replace("[... 90 characters truncated ...]\n", "")) == 10
    assert "characters truncated" in out
    assert limits.MAX_PROCESS_OUTPUT_CHARS == 8 * 1024 * 1024


# ================================ bounded process capture (codex P1) ========
# subprocess.run(capture_output=True) accumulates the whole stream before any
# post-hoc truncation can run, so the guard has to apply while reading. These
# drive a real child process, so they need no Aseprite.

_FLOOD = (
    "import sys\n"
    "for _ in range(200): sys.stdout.write('A' * 100000)\n"
    "sys.stdout.write('\\nSENTINEL_AT_END\\n')\n"
)


def test_capture_is_bounded_while_reading():
    """A child emitting ~20M characters must not be retained in full."""
    proc = _run_bounded([sys.executable, "-c", _FLOOD], timeout=60, limit=4096)
    assert proc.returncode == 0
    assert len(proc.stdout) < 8192, "retained far more than the cap"


def test_capture_keeps_the_tail_so_the_result_sentinel_survives():
    """Truncation must drop the head: the RESULT/ERROR sentinels are printed last."""
    proc = _run_bounded([sys.executable, "-c", _FLOOD], timeout=60, limit=4096)
    assert proc.stdout.strip().endswith("SENTINEL_AT_END")
    assert "characters truncated" in proc.stdout


def test_capture_does_not_deadlock_when_both_pipes_fill():
    """Draining one pipe to EOF before the other deadlocks once the child fills it."""
    both = (
        "import sys\n"
        "for _ in range(200):\n"
        "    sys.stdout.write('O' * 100000)\n"
        "    sys.stderr.write('E' * 100000)\n"
    )
    proc = _run_bounded([sys.executable, "-c", both], timeout=30, limit=4096)
    assert proc.returncode == 0
    assert len(proc.stdout) < 8192 and len(proc.stderr) < 8192


def test_capture_preserves_timeout_semantics():
    import subprocess

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        _run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert excinfo.value.timeout == 1


def test_capture_reports_a_nonzero_exit():
    proc = _run_bounded([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert proc.returncode == 3


# ============================= image dimension bomb guard (codex P1) ========
def _png(width: int, height: int) -> bytes:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("L", (width, height), 0).save(buf, format="PNG")
    return buf.getvalue()


def test_small_image_is_allowed(tmp_path):
    f = tmp_path / "ok.png"
    f.write_bytes(_png(64, 64))
    assert image.check_image_dimensions(str(f)) == (64, 64)


def test_image_at_the_canvas_cap_is_allowed(tmp_path):
    f = tmp_path / "cap.png"
    f.write_bytes(_png(4096, 4096))
    assert image.check_image_dimensions(str(f)) == (4096, 4096)


def test_decompression_bomb_is_rejected_despite_passing_the_byte_cap(tmp_path):
    """A solid-colour PNG is tiny on disk but declares a huge raster.

    The 32 MB byte cap cannot see this: the file is well under it, yet opening it
    would make Aseprite allocate hundreds of megabytes.
    """
    data = _png(6000, 6000)
    assert len(data) < limits.MAX_IMAGE_BYTES, "fixture must pass the byte cap"
    f = tmp_path / "bomb.png"
    f.write_bytes(data)
    with pytest.raises(ValidationFailed, match=r"pixels|per axis"):
        image.check_image_dimensions(str(f))


def test_pillow_bomb_error_becomes_a_typed_error(tmp_path):
    """Past Pillow's own threshold it raises DecompressionBombError at open()."""
    f = tmp_path / "huge.png"
    f.write_bytes(_png(20000, 20000))
    with pytest.raises(ValidationFailed, match="decompression bomb"):
        image.check_image_dimensions(str(f))


def test_unrecognized_format_is_skipped_not_rejected(tmp_path):
    """Aseprite's own formats are not Pillow-readable; make no claim about them."""
    f = tmp_path / "sprite.aseprite"
    f.write_bytes(b"\x00" * 64)
    assert image.check_image_dimensions(str(f)) is None


# Every tool that opens an outside image, not only the two stamping tools the guard was
# written for. `import_image`, `stamp_pattern` and both reference tools opened theirs with
# no header check at all, so a few-kilobyte PNG declaring 6000x6000 reached Aseprite
# through any of them. Asserted before launch: the guard is only worth having if the
# refusal comes before the allocation it exists to prevent.
_OPENS_AN_OUTSIDE_IMAGE = [
    ("import_image", lambda bomb: export.import_image(bomb, "never.aseprite")),
    ("stamp_pattern", lambda bomb: brushes.stamp_pattern("never.aseprite", bomb)),
    ("add_reference_layer", lambda bomb: reference.add_reference_layer("never.aseprite", bomb)),
    ("import_reference_sequence",
     lambda bomb: reference.import_reference_sequence("never.aseprite", [bomb])),
    ("import_spritesheet",
     lambda bomb: image.import_spritesheet("never.aseprite", bomb, 8, 8, layout="grid")),
]


@pytest.mark.parametrize("name, call", _OPENS_AN_OUTSIDE_IMAGE,
                         ids=[n for n, _ in _OPENS_AN_OUTSIDE_IMAGE])
def test_every_tool_that_opens_an_outside_image_refuses_a_bomb_before_launch(
        tmp_path, monkeypatch, name, call):
    def launched(*_args, **_kwargs):
        raise AssertionError(f"{name} launched Aseprite on an image the guard refuses")

    for module in (export, brushes, reference, image):
        monkeypatch.setattr(module, "run_lua", launched)
    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(_png(6000, 6000))

    with pytest.raises(ValidationFailed, match=r"pixels|per axis"):
        call(str(bomb))


# ====================== text bitmap bound vs plot budget (codex P2) =========
def test_sparse_text_at_high_scale_is_not_rejected_by_its_bounding_box():
    """Only threshold-passing pixels are plotted, so the budget must count those.

    Folding scale**2 into the glyph bounding box rejected a 7x7 box at scale 64
    (200,704 > 200,000) even when the line plots nothing at all.
    """
    from PIL import ImageFont

    coords, _, _ = text._render_text_pixels(
        "       ", limits.MAX_TEXT_SCALE, ImageFont.load_default(), 1, 128
    )
    assert coords == []


def test_text_bitmap_allocation_still_bounded():
    assert limits.MAX_TEXT_BITMAP_PIXELS < limits.MAX_CANVAS_PIXELS


# ================== aggregate cel area on scale (codex P1) =================
def test_scale_sprite_passes_the_aggregate_cel_budget_to_lua(ws, monkeypatch):
    """SpriteSize rescales every cel, so the guard needs the aggregate cap.

    The bound itself is enforced in Lua, where the cel images are visible; this
    pins that the limit actually reaches it.
    """
    seen = {}

    def fake_run_lua(body, args=None, timeout=None):
        seen["body"], seen["args"] = body, args or {}
        return {}

    monkeypatch.setattr(sprite, "run_lua", fake_run_lua)
    sprite.scale_sprite("s.aseprite", factor=2.0)
    assert seen["args"]["max_total_pixels"] == limits.MAX_SPRITE_TOTAL_PIXELS
    assert "max_total_pixels" in seen["body"]
    assert "spr.cels" in seen["body"]


# ============ error-message hygiene on the paths that carry raw output ======
def test_no_result_branch_strips_our_temp_script_location():
    """A Lua *compile* error never reaches the pcall harness, so no sentinel is printed
    and `_parse_result` falls through to the raw interpreter line. That line names the
    temp script this server wrote, an absolute host path carrying the account name, for
    a failure that is entirely ours. `strip_script_location` existed and was applied
    only in `_decode_error`, the branch that handles a *caught* Lua error.
    """
    import subprocess

    from aseprite_mcp.core.errors import LuaToolError
    from aseprite_mcp.core.runner import _parse_result

    leak = (
        r"C:\Users\someone\AppData\Local\Temp\asemcp_abcd1234.lua:12: "
        "unexpected symbol near one of the delimiters"
    )
    for stdout, stderr in (("", leak), (leak, "")):
        proc = subprocess.CompletedProcess(["aseprite"], 1, stdout, stderr)
        with pytest.raises(LuaToolError) as caught:
            _parse_result(proc, nonce="deadbeefdeadbeef")
        message = str(caught.value)
        assert "asemcp_" not in message, message
        assert "AppData" not in message, message
        assert "unexpected symbol" in message, message


def test_cli_failure_strips_our_temp_script_location(monkeypatch):
    """Same hygiene on the CLI route, which builds its message from raw stderr too."""
    import subprocess

    from aseprite_mcp.core import runner as runner_module
    from aseprite_mcp.core.errors import AsepriteCLIError

    leak = "/tmp/asemcp_zz99.lua:3: the layer was not found"
    monkeypatch.setattr(runner_module.config, "find_aseprite", lambda: "aseprite")

    def stub(code):
        # Bound per iteration rather than closed over the loop variable: both exit codes
        # are error paths here (Aseprite's CLI exits 0 for arguments it rejected), and a
        # late-binding lambda would test the last one twice.
        def run(*a, **k):
            return subprocess.CompletedProcess(["aseprite"], code, "", leak)
        return run

    for exit_code in (1, 0):
        monkeypatch.setattr(runner_module, "_run_bounded", stub(exit_code))
        with pytest.raises(AsepriteCLIError) as caught:
            runner_module.run_cli(["--version"])
        assert "asemcp_" not in str(caught.value), str(caught.value)
        assert "layer was not found" in str(caught.value)


# ===================== the generated script is always removed ==============
def test_a_script_that_cannot_be_removed_is_retried_on_the_next_run(tmp_path):
    """The unlink used to be a lone call inside `contextlib.suppress(OSError)`.

    On Windows that is a likely failure, not a rare one: unlinking a file another
    process still holds raises PermissionError, and a killed Aseprite has not always
    released its handle by the time the timeout path gets here. Measured at v0.10.0:
    ten `asemcp_*.lua` scripts left in the system temp directory over four days, each
    carrying the caller's resolved paths and colours. Suppressing the error is still
    right, because failing a successful call over cleanup would be worse; never trying
    again was not.
    """
    from aseprite_mcp.core import runner as runner_module

    stubborn = tmp_path / "asemcp_stuck.lua"
    stubborn.write_text("local ARG = {}")
    later = tmp_path / "asemcp_fine.lua"
    later.write_text("local ARG = {}")

    real_unlink = os.unlink
    refuse = {"on": True}

    def flaky_unlink(target):
        if refuse["on"] and str(target) == str(stubborn):
            raise PermissionError(32, "being used by another process")
        real_unlink(target)

    runner_module._PENDING_UNLINK.clear()
    try:
        os.unlink = flaky_unlink
        runner_module._drop_script(str(stubborn))
        assert stubborn.exists(), "the stubborn script should still be there"
        assert str(stubborn) in runner_module._PENDING_UNLINK, (
            "a failed removal has to be remembered, or the file is leaked silently"
        )

        refuse["on"] = False
        runner_module._drop_script(str(later))
    finally:
        os.unlink = real_unlink
        runner_module._PENDING_UNLINK.clear()

    assert not later.exists()
    assert not stubborn.exists(), "the next run must retry what the last one could not"


def test_dropping_a_script_that_is_already_gone_is_not_an_error(tmp_path):
    from aseprite_mcp.core import runner as runner_module

    runner_module._drop_script(str(tmp_path / "never_existed.lua"))


# ======================= the selection sidecar is injective ================
_SIDECAR_NAMES = (
    "hero.aseprite", "hero.png", "hero.gif", "hero", "hero.v2.aseprite",
    ".hidden", ".aseprite", ".png", "sub.dir/hero", "sub.dir/hero.png",
)


def test_two_sprites_of_one_stem_do_not_share_a_selection(tmp_path):
    """`with_suffix(".msk")` mapped `hero.aseprite` and `hero.png` onto one `hero.msk`.

    Three things came out of that single name. A selection set on the sprite scoped
    every edit to the PNG beside it, measured against the wrong sprite's dimensions, and
    both calls reported `selection_applied: true`. `save_sprite_as("hero.aseprite",
    "hero.png")` deleted the *source's* sidecar while the comment at that call site said
    the source was untouched. And the Lua derivation, which stripped the last extension,
    disagreed with `with_suffix` for a dotfile name.
    """
    from aseprite_mcp.core.paths import selection_sidecar

    sidecars = {n: selection_sidecar(tmp_path / n) for n in _SIDECAR_NAMES}
    assert len(set(sidecars.values())) == len(sidecars), (
        "two sprites share one sidecar: "
        + repr({n: str(p) for n, p in sidecars.items()})
    )
    assert selection_sidecar(tmp_path / "hero.aseprite").name == "hero.aseprite.msk"


def test_the_prelude_derives_the_sidecar_exactly_as_python_does():
    """The write side is derived in Python and the read side in Lua, so the two
    derivations are one invariant in two languages. They disagreed for any name whose
    final component begins with a dot: `.hidden` was saved to `.hidden.msk` and loaded
    from `.msk`, so the selection was written and then never read.

    Transcribed rather than executed, because there is no Lua here. The literal is
    asserted too, so the prelude's half cannot change without this test noticing.
    """
    import pathlib as _pathlib

    from aseprite_mcp.core import luagen
    from aseprite_mcp.core.paths import SELECTION_SUFFIX, selection_sidecar

    assert 'local mask_path = tostring(path) .. ".msk"' in luagen.PRELUDE, (
        "the prelude no longer appends the suffix to the whole filename; if that was "
        "deliberate, core.paths.selection_sidecar has to make the same change"
    )
    assert SELECTION_SUFFIX == ".msk"

    for name in _SIDECAR_NAMES:
        sprite_path = _pathlib.PurePosixPath("/ws") / name
        # The Lua half is `tostring(path) .. ".msk"` on the forward-slashed path that
        # `lua_path` hands the prelude.
        lua_half = str(sprite_path) + SELECTION_SUFFIX
        python_half = str(selection_sidecar(sprite_path)).replace("\\", "/")
        assert lua_half == python_half, name


# ===================== drawing extents are bounded in the prelude ==========
def test_the_draw_extent_cap_reaches_the_prelude():
    """A shape's cost is the extent it was given, not the canvas it lands on: `img_set`
    discards the off-canvas writes, but only after the loop has run. Measured at
    v0.10.0, `draw_rectangle(width=1000000, height=1000000, filled=True)` was accepted
    and asked Lua for 1e12 `img_set` calls, and `draw_ellipse(radius_x=1000000,
    radius_y=1000000, filled=True)` for about 3.1e12 point tables, which is memory
    rather than patience. The number lives in core.limits; this pins that the Lua the
    editor runs carries the same one rather than a copy that can drift.
    """
    from aseprite_mcp.core import luagen

    assert f"local MAX_DRAW_EXTENT = {limits.MAX_DRAW_EXTENT_PIXELS}" in luagen.PRELUDE
    assert "local function check_extent(" in luagen.PRELUDE


@pytest.mark.parametrize("primitive", [
    "bresenham_points", "draw_line_img", "draw_rect_img", "ellipse_offsets",
    "aa_line_img", "aa_ellipse_fill_img",
])
def test_every_extent_driven_primitive_checks_its_extent(primitive):
    """The guard sits in the shared primitives rather than at each tool's entry, because
    six primitives serve a dozen drawing tools and a new tool reaching one of them has
    to inherit the bound instead of having to remember it. One missing call puts the
    hole back for every tool that reaches that primitive.
    """
    from aseprite_mcp.core import luagen

    start = luagen.PRELUDE.index(f"local function {primitive}(")
    end = luagen.PRELUDE.index("\nend\n", start)
    assert "check_extent(" in luagen.PRELUDE[start:end], (
        f"{primitive} derives its work from a caller-supplied extent and no longer "
        "bounds it"
    )


def test_a_full_canvas_shape_still_fits_under_the_cap():
    """The cap has to refuse the attack without refusing the picture: a filled rectangle
    and a filled ellipse covering a maximum-size canvas are both legitimate requests.
    """
    import math

    area = limits.MAX_CANVAS_PIXELS
    assert area <= limits.MAX_DRAW_EXTENT_PIXELS
    radius = math.isqrt(area) // 2
    assert math.ceil(math.pi * (radius + 1) ** 2) <= limits.MAX_DRAW_EXTENT_PIXELS
    assert (2 * radius + 3) ** 2 <= limits.MAX_DRAW_EXTENT_PIXELS
    assert limits.MAX_CANVAS_DIMENSION <= limits.MAX_DRAW_EXTENT_PIXELS


# ================= a property value too deep to store is typed =============
# Which guard catches an over-deep value is a property of the platform and not of the
# value: `json` walks the nesting in C, and how much of that walk fits before the
# interpreter gives up differs, so a 5,000-deep *text* is caught by the depth cap on the
# CI runners and by the RecursionError branch on Windows. The first version of this test
# asserted the Windows wording and so passed here and failed on all five runners. Both
# refusals lead with the clause below, and these assert that rather than whichever
# branch happened to run.
DEPTH_REFUSAL = f"nests more than {metadata.MAX_PROPERTY_DEPTH} levels deep"


@pytest.mark.parametrize("depth", [9, 1200, 5000])
def test_a_property_value_too_deep_is_a_typed_refusal_as_json_text(depth):
    """`json.loads` walks the nesting itself, so a value nested past the interpreter's
    recursion limit never reached `_check_tree`. RecursionError is a RuntimeError, not a
    ValueError, so the invalid-JSON branch did not catch it either, and
    `set_properties(value='{"a":' * 5000 + ..., as_json=True)` surfaced as an untyped
    internal failure with no remedy in it.
    """
    deep = '{"a":' * depth + "0" + "}" * depth
    with pytest.raises(ValidationFailed, match=DEPTH_REFUSAL):
        metadata.parse_property_value(deep, as_json=True)


@pytest.mark.parametrize("depth", [9, 1200, 5000])
def test_a_property_value_too_deep_is_a_typed_refusal_arriving_pre_parsed(depth):
    """The other side of the same cap. Some clients parse a JSON-looking argument before
    the server sees it, so the value arrives as a dict and is encoded on the way in, and
    that encode was a second recursive walk which ran *before* the cap.

    `_check_tree` stops descending at nine levels and so cannot recurse away itself,
    which is why it now runs first: this refusal names the path at depth nine on every
    platform, however deep the value actually goes.
    """
    deep = 0
    for _ in range(depth):
        deep = {"a": deep}
    with pytest.raises(ValidationFailed, match=DEPTH_REFUSAL):
        metadata.parse_property_value(deep)
    with pytest.raises(ValidationFailed, match=DEPTH_REFUSAL):
        cels._coerce_property_value(deep)


def test_slice_user_data_too_deep_to_encode_is_a_typed_refusal(monkeypatch):
    """`_coerce_slice_data` holds the same unguarded `json.dumps`, one layer earlier: it
    runs as a `BeforeValidator`, so it failed ahead of any cap.

    The RecursionError is injected rather than provoked with a deep value, because the
    depth at which `json.dumps` gives up is the platform-dependent part. What is under
    test is the translation into a typed refusal, which is not.
    """

    def boom(*_args, **_kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(slices.json, "dumps", boom)
    with pytest.raises(ValidationFailed, match=r"too deeply to encode"):
        slices._coerce_slice_data({"type": "hitbox", "id": "body"})


# ======================= supply chain: the lock and the workflows ==========
def _repo_root():
    import pathlib as _pathlib

    return _pathlib.Path(__file__).resolve().parents[1]


def test_uv_lock_records_the_version_in_pyproject():
    """A release that bumps `pyproject.toml` and forgets `uv.lock` leaves the lock
    describing a version that no longer exists. v0.10.0 shipped exactly that: the lock
    still said 0.9.0, so `uv lock --check` failed on a clean checkout of `main` while CI
    stayed green, because `uv sync` silently re-resolves instead of refusing.

    Parsed with regular expressions rather than `tomllib`, which arrived in 3.11, so
    this runs on every interpreter in the matrix.
    """
    import re

    root = _repo_root()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    lock = (root / "uv.lock").read_text(encoding="utf-8")

    declared = re.search(r'(?m)^version = "([^"]+)"', pyproject)
    assert declared, "could not find the project version in pyproject.toml"
    locked = re.search(
        r'(?ms)^\[\[package\]\]\nname = "aseprite-mcp"\nversion = "([^"]+)"', lock)
    assert locked, "could not find the aseprite-mcp entry in uv.lock"
    assert declared.group(1) == locked.group(1), (
        f"pyproject.toml says {declared.group(1)} and uv.lock says "
        f"{locked.group(1)}; run `uv lock`"
    )


def test_ci_installs_from_the_committed_lock():
    """Without `--locked`, `uv sync` updates the lock when pyproject has moved on, so a
    PR that loosens a constraint is tested against versions nobody reviewed and the
    committed lock stops describing what passed.
    """
    workflow = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    assert "uv sync --locked" in workflow, (
        "CI must assert the committed uv.lock rather than letting uv re-resolve"
    )


@pytest.mark.parametrize("name", ["ci.yml", "codeql.yml"])
def test_checkout_does_not_leave_the_token_in_the_checkout(name):
    """`actions/checkout` writes the job's GITHUB_TOKEN into .git/config by default, and
    the steps after it run third-party code: `uv sync` executes the build backends of
    whatever the lock resolves to. The top-level `permissions: contents: read` makes
    that token nearly useless, which is why this is defence in depth; the CodeQL job
    also holds `security-events: write`, and neither workflow pushes anything.
    """
    workflow = (_repo_root() / ".github" / "workflows" / name).read_text(
        encoding="utf-8")
    assert "actions/checkout@" in workflow
    assert "persist-credentials: false" in workflow, (
        f"{name} checks out with the default credential persistence"
    )


# ===== no caller data reaches the Lua as code =========================================
# The whole architecture rests on one property: a tool's Lua *body* is a static string, and
# everything the caller supplied arrives through the `local ARG = {...}` table that `to_lua`
# escapes. If a body were ever built by interpolation, the escaping would be bypassed and
# the caller would be writing Lua that runs with the Aseprite process's privileges.
#
# An audit established that this holds across the repository. An audit is a measurement
# taken once, and this is the measurement taken on every run: the property was true the day
# it was checked and nothing was stopping the next edit from breaking it.

RUNNERS = frozenset({"run_lua", "assemble_script", "run_ramp_lua", "_draw", "run_cli"})

# The one f-string that legitimately becomes Lua. It injects a cap from `core.limits` so
# the number is not duplicated in a Lua string where nothing imports it and no test can see
# the two copies disagree. It is named here rather than pattern-matched so that adding a
# second one is a deliberate edit to this test with a reason attached.
LUA_FSTRING_ALLOWED = {("core/luagen.py", "_LIMITS_LUA")}


def _source_files():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aseprite_mcp"
    return sorted(root.rglob("*.py")), root


def _interpolation_kind(node):
    """How this expression was built, if it was built out of parts at runtime."""
    if isinstance(node, ast.JoinedStr):
        return "an f-string"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return "percent formatting"
    if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "format":
        return "str.format()"
    if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "join":
        return "str.join()"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # Concatenating Lua constants is how every body in here is assembled, and is fine:
        # the parts are module-level strings. What is not fine is a part built at runtime.
        for side in (node.left, node.right):
            kind = _interpolation_kind(side)
            if kind:
                return f"{kind} inside a concatenation"
    return None


def test_no_lua_body_is_built_by_interpolation():
    """Every runner call is handed a static body, never one assembled from values.

    Checked at the call site rather than by looking for Lua-shaped strings, because this
    codebase has well over a hundred f-strings and every one of them is prose for an error
    message. The call site is the place where the distinction is unambiguous: whatever is
    handed to `run_lua` is what Aseprite executes.
    """
    files, root = _source_files()
    offenders, sites = [], 0
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in RUNNERS:
                continue
            sites += 1
            kind = _interpolation_kind(node.args[0])
            if kind:
                rel = path.relative_to(root).as_posix()
                offenders.append(f"{rel}:{node.lineno} passes {name}() a body built by {kind}")

    assert sites > 100, f"only found {sites} runner call sites, so this test is not looking"
    assert not offenders, (
        "a Lua body built out of parts bypasses the ARG table that `to_lua` escapes:\n  "
        + "\n  ".join(offenders)
    )


def test_the_only_f_string_that_becomes_lua_interpolates_an_integer_constant():
    """The one exception, held to the reason it was allowed.

    `_LIMITS_LUA` exists so a cap is not written out twice. That is a good reason and it
    survives only while the holes in it are integers from `core.limits`: a hole that took a
    caller's value would be the injection this file's sibling test exists to prevent, and it
    would be invisible there because the interpolation happens at import rather than at the
    call site.
    """
    files, root = _source_files()
    found = set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.JoinedStr)):
                continue
            literal = "".join(
                part.value for part in node.value.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if not any(marker in literal for marker in ("local ", "function ", "--")):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                found.add((rel, target.id))
                assert (rel, target.id) in LUA_FSTRING_ALLOWED, (
                    f"{rel}:{node.lineno} builds Lua with an f-string assigned to "
                    f"{target.id!r}. If that is deliberate, add it to "
                    "LUA_FSTRING_ALLOWED with the reason."
                )
            for part in node.value.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                assert isinstance(part.value, ast.Name), (
                    f"{rel}:{node.lineno} interpolates an expression into Lua. Only a bare "
                    "name holding an integer constant is allowed here."
                )
                value = getattr(limits, part.value.id, None)
                assert isinstance(value, int) and not isinstance(value, bool), (
                    f"{rel}:{node.lineno} interpolates {part.value.id!r} into Lua, which is "
                    f"{type(value).__name__} rather than an int from core.limits."
                )

    assert found == LUA_FSTRING_ALLOWED, (
        f"the allowlist names {LUA_FSTRING_ALLOWED} but the source has {found}. "
        "Remove the stale entry, so the allowlist cannot outlive what it excuses."
    )


# ========= every ramp and every region is bounded before Aseprite is launched =========
# Registry-wide on purpose. Neither gap was introduced by editing a tool; both arrived
# with a new one. `assess_sprite` grew a `ramp` without the line its seven siblings
# have, and `shift_along_ramp`, `gradient_map` and `select_region` take a region without
# the line the three fill tools have. A test of one example would have caught neither,
# and the cost of the worst of them was not a slow call: a selection's stored mask is one
# bit per pixel of the region *as asked for*, not of the canvas, so the 1e6 x 1e6 region
# that reached Aseprite was asking it for 125 GB.
#
# `assemble_script` is intercepted, so "reached Lua" means every pre-flight check passed
# and the script was handed over. Nothing in this group launches Aseprite.

HUGE = 1_000_000


class _ReachedLua(Exception):
    """The script was assembled, so every pre-flight check passed."""


@pytest.fixture
def no_lua(monkeypatch):
    """Intercept where Python hands over, so a refusal here is a pre-flight refusal."""

    def reached(*_args, **_kwargs):
        raise _ReachedLua

    monkeypatch.setattr("aseprite_mcp.core.runner.assemble_script", reached)


def _params(name):
    return inspect.signature(REGISTERED[name].fn).parameters


def _is_region_shaped(name):
    """Takes an origin and an extent, with the extent defaulting to "rest of canvas"."""
    p = _params(name)
    return ({"x", "y", "width", "height"} <= set(p)
            and p["width"].default is None and p["height"].default is None)


# Only what each tool needs to get *past* its other validation, so the refusal under
# test can only be the region's. The baseline case asserts exactly that.
REGION_TOOLS = {
    "fill_gradient": {"colors": ["#101010", "#f0f0f0"]},
    "fill_checkerboard": {"color1": "#101010", "color2": "#f0f0f0"},
    "stamp_pattern": {"source": "stamp.aseprite"},
    "gradient_map": {"ramp": ["#101010", "#808080", "#f0f0f0"]},
    "shift_along_ramp": {"ramp": ["#101010", "#808080", "#f0f0f0"], "steps": -1},
    "select_region": {},
    # Joined the family in #220. It was capped in Lua alone, at a bare `4096`, which is a
    # sound bound in the wrong language: the request still launched Aseprite in order to
    # be refused, and came back as an untyped Lua error. Its own tighter cap is pinned
    # separately below; here it is held to the same two refusals as its siblings.
    "get_pixels": {},
}

REGION_CAP_EXEMPT = {
    # A slice's bounds are metadata: `sl.bounds = Rectangle(...)` is O(1) and allocates
    # nothing proportional to the size, so there is no loop or buffer to bound here.
    "set_slice",
}


def test_the_region_family_is_exactly_the_table(no_lua):
    """So the next tool that takes a region cannot quietly be the next gap.

    A new tool with this parameter shape fails here until it is either given the cap and
    listed, or exempted with the reason it needs none.
    """
    shaped = {name for name in REGISTERED if _is_region_shaped(name)}
    assert shaped == set(REGION_TOOLS) | REGION_CAP_EXEMPT


@pytest.mark.parametrize("tool_name", sorted(REGION_TOOLS))
def test_a_valid_region_reaches_lua(tool_name, ws, no_lua):
    """The teeth for the two cases below: with a sane region these same arguments get all
    the way to the handover, so a refusal there is caused by the region and nothing else.
    """
    extra = REGION_TOOLS[tool_name]
    with pytest.raises(_ReachedLua):
        REGISTERED[tool_name].fn(filename="probe.aseprite", x=0, y=0, width=4, height=4,
                                 **extra)


@pytest.mark.parametrize("tool_name", sorted(REGION_TOOLS))
def test_an_absurd_region_is_refused_before_aseprite(tool_name, ws, no_lua):
    extra = REGION_TOOLS[tool_name]
    with pytest.raises(ValidationFailed, match=rf"region size {HUGE}x{HUGE} exceeds"):
        REGISTERED[tool_name].fn(filename="probe.aseprite", x=0, y=0,
                                 width=HUGE, height=HUGE, **extra)


@pytest.mark.parametrize("tool_name", sorted(REGION_TOOLS))
def test_a_far_origin_cannot_inflate_a_defaulted_region(tool_name, ws, no_lua):
    """The route the cap used to miss. With the extent left to default, the body derives
    it as `spr.width - rx` at run time, after the check, so a far-away origin inflates
    the extent the check just approved.
    """
    extra = REGION_TOOLS[tool_name]
    with pytest.raises(ValidationFailed, match=rf"region x is -{HUGE}"):
        REGISTERED[tool_name].fn(filename="probe.aseprite", x=-HUGE, y=0,
                                 width=None, height=None, **extra)


# ----- get_pixels reads back a payload, so its own cap is tighter than the family's ----
# The three tests above hold it to the family's bound (a region cannot be canvas-sized).
# These four hold it to its own, which is the number that was a bare literal in a Lua
# string until #220, and to the division the issue asks for: Python refuses what the
# caller stated, the body stays as the backstop for what it derives.


def test_get_pixels_refuses_an_over_cap_region_before_aseprite(ws, no_lua):
    """Just over the cap, so this cannot pass because of the family's canvas-sized bound.

    64x65 is 4,160 pixels: inside every per-axis cap and inside the canvas area cap, and
    refused only by the read cap. The remedy is asserted too, because "Max 4096 (e.g.
    64x64) per call" is what tells the caller what to ask for next.
    """
    over = limits.MAX_READ_REGION_PIXELS + 64
    with pytest.raises(ValidationFailed) as exc:
        REGISTERED["get_pixels"].fn(filename="probe.aseprite", x=0, y=0,
                                    width=64, height=65)
    assert f"({over} px)" in str(exc.value)
    assert f"Max {limits.MAX_READ_REGION_PIXELS} (e.g. 64x64) per call" in str(exc.value)


def test_get_pixels_at_the_cap_still_reaches_lua(ws, no_lua):
    """The teeth for the test above, and the issue's "still returns 4,096 pixels".

    64x64 is exactly the cap, so an off-by-one in the comparison shows up here rather
    than as a tool that quietly stopped being able to read a 64x64 tile.
    """
    assert limits.MAX_READ_REGION_PIXELS == 64 * 64
    with pytest.raises(_ReachedLua):
        REGISTERED["get_pixels"].fn(filename="probe.aseprite", x=0, y=0,
                                    width=64, height=64)


def test_get_pixels_refuses_a_far_origin_with_no_extent(ws, no_lua):
    """Named for this tool on purpose, not left to the family's parametrized case.

    This is the route the Lua check covers and a check on `width`/`height` alone does
    not: with the extent unset the body derives it as `spr.width - x0`, so a far-away
    origin *is* the size. The issue calls losing this coverage a regression, so it is
    asserted here as well, where a future edit to `REGION_TOOLS` cannot take it away.
    """
    with pytest.raises(ValidationFailed, match=rf"region x is -{HUGE}"):
        REGISTERED["get_pixels"].fn(filename="probe.aseprite", x=-HUGE, y=0,
                                    width=None, height=None)


def test_the_read_region_cap_has_one_definition():
    """The body reads the cap from the prelude rather than holding a second copy.

    It held `4096` twice in one Lua string (the comparison and the message) and
    `core/limits.py` could see neither, so nothing could tell a doc, a test or a reader
    what the number was. `_LIMITS_LUA` is the one sanctioned route for a Python limit
    into Lua, and the two tests above this group pin that it stays the only one.
    """
    _, root = _source_files()
    tree = ast.parse((root / "tools" / "inspect.py").read_text(encoding="utf-8"))
    # The Lua, found by something only the Lua says, so the docstring (which quotes the
    # cap as prose, correctly) cannot be mistaken for it.
    lua = [
        node.value
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and fn.name == "get_pixels"
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "getPixel" in node.value
    ]
    assert len(lua) == 1, f"expected one Lua body in get_pixels, found {len(lua)}"
    assert "MAX_READ_REGION" in lua[0], "the body no longer reads the injected cap"
    assert str(limits.MAX_READ_REGION_PIXELS) not in lua[0], (
        "the Lua body holds a literal copy of the cap again"
    )
    assert f"local MAX_READ_REGION = {limits.MAX_READ_REGION_PIXELS}" in luagen.PRELUDE


# Only what each tool needs to reach its ramp check, same as above.
RAMP_TOOLS = {
    "assess_sprite": {},
    "cast_shadow": {"layer": "art"},
    "contact_shadow": {"occluder_color": "#101010"},
    "dither_band": {"from_step": 0, "to_step": 1},
    "glow": {},
    "shade_facets": {"rows": ["ab"], "legend": {"a": 90, "b": 0}},
    "seam_occlusion": {"rows": ["ab"], "legend": {"a": 1, "b": 0}},
    "gradient_map": {},
    "outline_smart": {},
    "shade_region_by_light": {},
    "shift_along_ramp": {"steps": -1},
    # frame 2 because the refusal for frame 1 ("no earlier frame to have moved from")
    # is its own check and fires first, which would pass this test for the wrong reason.
    "smear_frame": {"layer": "art", "frame": 2},
    "specular_highlight": {},
    "surface_emission": {"source_color": "#ff8a2a"},
}


def test_the_ramp_family_is_exactly_the_table():
    """Same reasoning: `assess_sprite` was the one of eight without the cap."""
    assert {name for name in REGISTERED if "ramp" in _params(name)} == set(RAMP_TOOLS)


@pytest.mark.parametrize("tool_name", sorted(RAMP_TOOLS))
def test_an_over_cap_ramp_is_refused_before_aseprite(tool_name, ws, no_lua):
    """The message names `ramp` and its count, so this cannot pass for another reason."""
    over = ["#101010"] * (limits.MAX_COLOR_LIST_LENGTH + 1)
    extra = RAMP_TOOLS[tool_name]
    with pytest.raises(ValidationFailed,
                       match=rf"ramp has {limits.MAX_COLOR_LIST_LENGTH + 1} items"):
        REGISTERED[tool_name].fn(filename="probe.aseprite", ramp=over, **extra)
