"""Pure-Python tests for the v0.7.1 hardening pass: no Aseprite (always run).

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

import pytest

from aseprite_mcp.core import config, limits
from aseprite_mcp.core.errors import ExportError, ValidationFailed, WorkspaceError
from aseprite_mcp.core.paths import ensure_output_pattern, expansion_matches
from aseprite_mcp.core.runner import _truncate
from aseprite_mcp.tools import export, image, sprite, text


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
    with pytest.raises(ValidationFailed, match="pixels; maximum is"):
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
