"""Pure-Python tests for the typed error hierarchy: no Aseprite (always run)."""

import json
import subprocess

import pytest

from aseprite_mcp.core import config, errors, runner
from aseprite_mcp.core.errors import (
    AsepriteCLIError,
    AsepriteError,
    AsepriteMCPError,
    AsepriteNotFoundError,
    AsepriteTimeoutError,
    ConfigError,
    ExportError,
    LuaToolError,
    ValidationFailed,
    WorkspaceError,
)
from aseprite_mcp.core.luagen import error_prefix, result_prefix

_ALL = [
    ConfigError, AsepriteNotFoundError, WorkspaceError, AsepriteTimeoutError,
    LuaToolError, AsepriteCLIError, ExportError, ValidationFailed,
]


# ------------------------------------------------------------------ hierarchy
def test_alias_and_base():
    assert AsepriteError is AsepriteMCPError


def test_every_error_is_an_aseprite_error():
    for cls in _ALL:
        assert issubclass(cls, AsepriteMCPError)
        assert issubclass(cls, AsepriteError)  # alias
        assert isinstance(cls("x"), AsepriteError)


def test_specific_relationships():
    assert issubclass(AsepriteNotFoundError, ConfigError)
    assert issubclass(WorkspaceError, ConfigError)
    assert issubclass(ExportError, AsepriteCLIError)
    # Back-compat: AsepriteNotFoundError is also a FileNotFoundError so existing
    # `except FileNotFoundError` call sites keep catching it.
    assert issubclass(AsepriteNotFoundError, FileNotFoundError)


def test_runner_reexports_aseprite_error():
    assert runner.AsepriteError is AsepriteError


def test_message_preserved():
    assert str(LuaToolError("bad layer 'foo'")) == "bad layer 'foo'"


# ------------------------------------------------------------------- config
def test_invalid_aseprite_path_raises_not_found(monkeypatch):
    monkeypatch.setattr(config, "_cached_exe", None)
    monkeypatch.setenv("ASEPRITE_PATH", "/definitely/not/here/aseprite.exe")
    with pytest.raises(AsepriteNotFoundError, match="ASEPRITE_PATH"):
        config.find_aseprite()


def test_invalid_aseprite_path_also_filenotfound(monkeypatch):
    monkeypatch.setattr(config, "_cached_exe", None)
    monkeypatch.setenv("ASEPRITE_PATH", "/definitely/not/here/aseprite.exe")
    with pytest.raises(FileNotFoundError):  # back-compat catch
        config.find_aseprite()


# ----------------------------------------------------------------- workspace
def test_workspace_absolute_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(WorkspaceError, match="Absolute paths are disabled"):
        config.resolve(str(tmp_path.parent / "x.aseprite"))


def test_workspace_escape_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    with pytest.raises(WorkspaceError, match="escapes the workspace"):
        config.resolve("../../etc/passwd.aseprite")


def test_workspace_safe_relative_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    out = config.resolve("sub/ok.aseprite")
    assert out == (tmp_path / "sub" / "ok.aseprite").resolve()


# ------------------------------------------------------------- runner parsing
def _proc(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["aseprite"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# Sentinels are per-run (see luagen.new_nonce), so these build the prefixes the
# parser will actually be looking for rather than the legacy fixed tokens.
_NONCE = "0123456789abcdef"
_OK = result_prefix(_NONCE)
_ERR = error_prefix(_NONCE)


def test_lua_error_sentinel_raises_lua_tool_error():
    # The harness json_encodes the message, so the parser decodes it.
    with pytest.raises(LuaToolError, match="bad layer"):
        runner._parse_result(_proc(stdout=f'{_ERR}"bad layer"'), nonce=_NONCE)


def test_lua_error_sentinel_tolerates_an_unencoded_message():
    with pytest.raises(LuaToolError, match="bad layer"):
        runner._parse_result(_proc(stdout=f"{_ERR}bad layer"), nonce=_NONCE)


def test_malformed_result_json_raises_lua_tool_error():
    with pytest.raises(LuaToolError, match="parse"):
        runner._parse_result(_proc(stdout=f"{_OK}{{not json"), nonce=_NONCE)


def test_missing_result_raises_lua_tool_error():
    with pytest.raises(LuaToolError):
        runner._parse_result(_proc(stdout="", stderr="boom", returncode=1), nonce=_NONCE)


def test_sentinel_for_another_nonce_is_not_our_result():
    """A line framed with a different run's nonce must not be read as this run's."""
    other = error_prefix("ffffffffffffffff")
    with pytest.raises(LuaToolError, match="boom"):
        runner._parse_result(
            _proc(stdout=f'{other}"forged"', stderr="boom"), nonce=_NONCE
        )


def test_duplicate_sentinels_are_refused_rather_than_resolved():
    with pytest.raises(LuaToolError, match="more than one"):
        runner._parse_result(
            _proc(stdout=f'{_OK}{{"a": 1}}\n{_OK}{{"a": 2}}'), nonce=_NONCE
        )


def test_non_object_result_is_refused():
    with pytest.raises(LuaToolError, match="object was expected"):
        runner._parse_result(_proc(stdout=f"{_OK}1337"), nonce=_NONCE)


# ------------------------------------------------------- runner cli / timeout
# These patch `runner._run_bounded`, the seam that actually launches Aseprite.
# It replaced a direct `subprocess.run(capture_output=True)` call so that output is
# bounded while it is read rather than truncated after the fact; the behaviour being
# pinned here (typed errors on non-zero exit and on timeout) is unchanged.
def test_cli_nonzero_raises_cli_error(monkeypatch):
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    monkeypatch.setattr(runner, "_run_bounded",
                        lambda *a, **k: _proc(stderr="export failed", returncode=1))
    with pytest.raises(AsepriteCLIError, match="export failed"):
        runner.run_cli(["x.aseprite", "--save-as", "y.png"])


def test_cli_timeout_raises_timeout_error(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="aseprite", timeout=5)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    monkeypatch.setattr(runner, "_run_bounded", boom)
    with pytest.raises(AsepriteTimeoutError, match="timed out"):
        runner.run_cli(["x.aseprite"])


def test_lua_timeout_raises_timeout_error(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="aseprite", timeout=5)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    monkeypatch.setattr(runner, "_run_bounded", boom)
    with pytest.raises(AsepriteTimeoutError, match="timed out"):
        runner.run_lua("RESULT = {}")


# ------------------------------------------------------------------ unused-ok
def test_validation_failed_exists():
    assert issubclass(ValidationFailed, AsepriteMCPError)
    assert isinstance(errors.ValidationFailed("nope"), AsepriteError)


# ------------------------------------------------ temp script path hygiene (#62)
# A Lua `error("msg")` without level 0 is prefixed by the interpreter with the script's
# own path, and that script is a temp file this server wrote and has already deleted.
# It reached the caller verbatim:
#   Batch aborted at op 0 (rename_layer): C:\...\Temp\asemcp_vqwcklpp.lua:264: No layer
def test_strip_script_location_removes_windows_temp_prefix():
    msg = r"C:\Users\me\AppData\Local\Temp\asemcp_vqwcklpp.lua:264: No layer named 'ghost'"
    assert errors.strip_script_location(msg) == "No layer named 'ghost'"


def test_strip_script_location_removes_posix_prefix():
    assert errors.strip_script_location("/tmp/asemcp_ab12cd.lua:7: boom") == "boom"


def test_strip_script_location_handles_a_directory_with_spaces():
    msg = r"C:\Program Files\tmp dir\asemcp_ab12.lua:12: No tag named 'walk'"
    assert errors.strip_script_location(msg) == "No tag named 'walk'"


def test_strip_script_location_removes_an_embedded_occurrence():
    msg = (
        "Batch aborted at op 0 (rename_layer): "
        r"C:\Temp\asemcp_x1.lua:264: No layer named 'ghost'"
        " - the sprite was not modified (rolled back)."
    )
    cleaned = errors.strip_script_location(msg)
    assert "asemcp_" not in cleaned and ".lua" not in cleaned
    assert cleaned.startswith("Batch aborted at op 0 (rename_layer): No layer named 'ghost'")


def test_strip_script_location_keeps_paths_that_are_part_of_the_message():
    # A sprite/export path the caller passed in must survive; only this server's own
    # temp scripts are stripped.
    for msg in (
        "Could not open sprite: C:/sprites/hero.aseprite",
        "export failed: /home/me/out.lua:3: nope",
        "No layer named 'asemcp_x.lua'",
    ):
        assert errors.strip_script_location(msg) == msg


def test_decode_error_strips_the_generated_script_location():
    """Lua error() at level 1 prepends `<script>:<line>:`, which is noise and a path leak.

    Stripping happens in the runner's one decode seam rather than per call site, so it
    covers standalone tools and not only the batch runner. The temp file is gone by the
    time anyone reads the message, and the line number refers to generated code.
    """
    payload = json.dumps(
        r"C:\Users\someone\AppData\Local\Temp\asemcp_i5f2dp0f.lua:264: "
        r"No layer named 'ghost'"
    )
    assert runner._decode_error(payload) == "No layer named 'ghost'"


def test_decode_error_strips_the_location_from_an_unencoded_message():
    """The tolerant branch (a message that is not valid JSON) must strip it too."""
    raw = r"C:\Temp\asemcp_abc.lua:12: boom"
    assert runner._decode_error(raw) == "boom"


def test_decode_error_leaves_an_ordinary_message_alone():
    assert runner._decode_error(json.dumps("No layer named 'ghost'")) == (
        "No layer named 'ghost'"
    )
