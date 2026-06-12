"""Pure-Python unit tests — no Aseprite required (always run, incl. on CI).

Cover colour parsing, Python->Lua serialization, and the workspace path sandbox.
"""

import pytest

from aseprite_mcp import config, luagen
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
    script = luagen.assemble_script("RESULT = { ok = true }", {"n": 3})
    assert "local ARG = {[\"n\"]=3}" in script
    assert luagen.RESULT_PREFIX in script
    assert luagen.ERROR_PREFIX in script
    assert "pcall(_main)" in script


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
    assert out.parent.exists()


def test_resolve_rejects_absolute_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(ValueError, match="Absolute paths are disabled"):
        config.resolve(str(tmp_path.parent / "outside.aseprite"))


def test_resolve_rejects_escape_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(ValueError, match="escapes the workspace"):
        config.resolve("../../etc/passwd.aseprite")


def test_resolve_absolute_allowed_with_optin(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", "1")
    target = tmp_path.parent / "elsewhere" / "ok.aseprite"
    out = config.resolve(str(target))
    assert out == target
