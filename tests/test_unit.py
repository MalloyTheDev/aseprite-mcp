"""Pure-Python unit tests: no Aseprite required (always run, incl. on CI).

Cover colour parsing, Python->Lua serialization, and the workspace path sandbox.
"""

import itertools

import pytest

from aseprite_mcp.core import config, luagen
from aseprite_mcp.core.errors import WorkspaceError
from aseprite_mcp.tools.common import lua_path, parse_color


# --------------------------------------------------------------- parse_color
def test_parse_color_hex():
    assert parse_color("#ff0000") == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert parse_color("#ff000080") == {"r": 255, "g": 0, "b": 0, "a": 128}
    assert parse_color("#f00") == {"r": 255, "g": 0, "b": 0, "a": 255}


def test_parse_color_numeric_and_names():
    assert parse_color("255,0,0") == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert parse_color("10,20,30,40") == {"r": 10, "g": 20, "b": 30, "a": 40}
    assert parse_color("red") == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert parse_color("transparent")["a"] == 0


def test_parse_color_index_spec():
    assert parse_color("index:5") == {"index": 5}
    assert parse_color("idx:12") == {"index": 12}


def test_parse_color_invalid():
    for bad in ("notacolor", "#zz", "1,2", "1,2,3,4,5", None):
        with pytest.raises(ValueError):
            parse_color(bad)


# ------------------------------------------------------------------- to_lua
def test_to_lua_scalars():
    assert luagen.to_lua(None) == "nil"
    assert luagen.to_lua(True) == "true"
    assert luagen.to_lua(False) == "false"
    assert luagen.to_lua(42) == "42"
    assert luagen.to_lua("hi") == '"hi"'


def test_to_lua_string_escaping():
    assert luagen.to_lua('a"b') == '"a\\"b"'
    assert luagen.to_lua("x\\y") == '"x\\\\y"'
    assert luagen.to_lua("line\n") == '"line\\n"'
    assert luagen.to_lua(chr(7)) == '"\\007"'  # control char -> zero-padded decimal


def test_to_lua_containers():
    assert luagen.to_lua([1, "x", None]) == '{1, "x", nil}'
    assert luagen.to_lua({"a": 1, "b": True}) == '{["a"]=1, ["b"]=true}'
    assert luagen.to_lua({1: "a"}) == '{[1]="a"}'


def test_assemble_script_has_arg_and_sentinels():
    nonce = "0123456789abcdef"
    script = luagen.assemble_script("RESULT = { ok = true }", {"n": 3}, nonce=nonce)
    assert "local ARG = {[\"n\"]=3}" in script
    assert luagen.result_prefix(nonce) in script
    assert luagen.error_prefix(nonce) in script
    assert "pcall(_main)" in script


def test_assemble_script_frames_output_with_the_given_nonce_only():
    """The legacy fixed sentinels must not appear, or a payload could forge one."""
    script = luagen.assemble_script("RESULT = {}", {}, nonce="deadbeefdeadbeef")
    assert f'print("{luagen.RESULT_PREFIX}"' not in script
    assert f'print("{luagen.ERROR_PREFIX}"' not in script


def test_new_nonce_differs_per_call():
    assert luagen.new_nonce() != luagen.new_nonce()


# ----------------------------------------------------------------- lua_path
def test_lua_path_uses_forward_slashes():
    assert lua_path("C:\\a\\b.aseprite") == "C:/a/b.aseprite"
    assert lua_path("already/forward.png") == "already/forward.png"


# -------------------------------------------------------- path sandbox
def test_resolve_relative_under_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    out = config.resolve("sub/sprite.aseprite")
    assert out == (tmp_path / "sub" / "sprite.aseprite").resolve()
    # Resolving creates nothing. It used to mkdir the parent on every call, including
    # pure reads, so a caller could build arbitrary directory trees inside the workspace
    # out of calls that then failed. Directory creation now belongs to the output
    # helpers, which know a write is actually coming.
    assert not out.parent.exists()


def test_resolve_rejects_absolute_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(WorkspaceError, match="Absolute paths are disabled"):
        config.resolve(str(tmp_path.parent / "outside.aseprite"))


def test_resolve_rejects_escape_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(WorkspaceError, match="escapes the workspace"):
        config.resolve("../../etc/passwd.aseprite")


def test_resolve_absolute_allowed_with_optin(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", "1")
    target = tmp_path.parent / "elsewhere" / "ok.aseprite"
    out = config.resolve(str(target))
    assert out == target


# ------------------------------------------------------------ generate_ramp
def _hls(hex_color):
    import colorsys
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def test_generate_ramp_default_output_is_unchanged():
    """The new curve arguments must not move any existing caller's ramp."""
    from aseprite_mcp.tools.palette import generate_ramp
    assert generate_ramp("#a03828", steps=5, hue_shift=40, saturation_shift=30)["colors"] == [
        "#230c10", "#601b1e", "#a03828", "#d66c3f", "#e7ad7a"
    ]


def test_generate_ramp_peak_saturation_is_an_interior_step():
    """Chroma peaks in the midtone and falls at both ends.

    The linear form made the brightest step the most saturated (0.489 rising to 0.694
    across the ramp), which is the opposite of how a hand-built ramp reads: highlights
    desaturate toward the light and deep shadows toward ambient.
    """
    from aseprite_mcp.tools.palette import generate_ramp
    colors = generate_ramp("#a03828", steps=5, saturation_shift=30, sat_curve="peak")["colors"]
    sats = [_hls(c)[2] for c in colors]
    assert sats.index(max(sats)) not in (0, len(sats) - 1), sats
    assert sats[0] < max(sats) and sats[-1] < max(sats)


def test_generate_ramp_hue_targets_pull_the_ends_apart():
    """A symmetric rotation cannot say 'shadows blue, highlights yellow'."""
    from aseprite_mcp.tools.palette import generate_ramp
    colors = generate_ramp(
        "#a03828", steps=5, shadow_hue="#3050c0", light_hue="#ffd070"
    )["colors"]
    shadow_h, light_h = _hls(colors[0])[0] * 360, _hls(colors[-1])[0] * 360
    assert 190 < shadow_h < 270, f"shadow end should trend blue, got {shadow_h:.1f}"
    assert 20 < light_h < 70, f"light end should trend warm, got {light_h:.1f}"


def test_generate_ramp_perceptual_easing_bunches_the_darks():
    from aseprite_mcp.tools.palette import generate_ramp
    colors = generate_ramp("#a03828", steps=5, easing="perceptual")["colors"]
    lums = [_hls(c)[1] for c in colors]
    gaps = [b - a for a, b in itertools.pairwise(lums)]
    assert gaps == sorted(gaps), f"gaps should widen toward the light end: {gaps}"


def test_generate_ramp_rejects_unknown_curve_names():
    import pytest as _pytest

    from aseprite_mcp.core.errors import ValidationFailed
    from aseprite_mcp.tools.palette import generate_ramp
    with _pytest.raises(ValidationFailed, match="sat_curve"):
        generate_ramp("#a03828", sat_curve="bell")
    with _pytest.raises(ValidationFailed, match="easing"):
        generate_ramp("#a03828", easing="cubic")
