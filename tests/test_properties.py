"""Property-based tests (Hypothesis) for the security-critical pure boundaries.

These fuzz the three places where untrusted input crosses into generated Lua, into
colour parsing, and into the path sandbox:

  * ``to_lua`` — generated strings must never break out of their quoted Lua literal
    (no injection), and arbitrary nested values must serialize to a structurally
    sound literal (balanced tables, self-contained strings).
  * ``ColorSpec.parse`` / ``parse_color`` — valid colours normalize; arbitrary text
    never raises anything but ``ValueError``; channels stay in 0–255.
  * ``config.resolve`` / ``ensure_output_path`` — a relative path either resolves
    inside the workspace or is rejected; it never escapes. Absolute paths are rejected.

Pure-Python (no Aseprite); always run. Profiles are kept tight (max_examples=100,
deadline=None) so the suite stays fast in CI.
"""

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import WorkspaceError
from aseprite_mcp.core.luagen import to_lua
from aseprite_mcp.core.models import ColorSpec
from aseprite_mcp.core.paths import ensure_output_path
from aseprite_mcp.tools.common import parse_color

FAST = settings(max_examples=100, deadline=None)


# ====================================================================== to_lua
# An independent decoder/scanner for exactly the escapes `_lua_string` emits.
# If a generated string round-trips through this, it provably stayed inside the
# quoted literal (could not break out to inject Lua).
def _consume_lua_string(text: str, i: int) -> tuple[str, int]:
    """Decode the Lua string literal starting at text[i] == '"'. Returns (value, end)."""
    assert text[i] == '"', "expected opening quote"
    i += 1
    out: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch == "\\":
            nxt = text[i + 1]
            simple = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
            elif nxt.isdigit():
                j, digits = i + 1, ""
                while j < len(text) and len(digits) < 3 and text[j].isdigit():
                    digits += text[j]
                    j += 1
                out.append(chr(int(digits)))
                i = j
            else:
                raise ValueError(f"unexpected escape \\{nxt!r}")
        else:
            assert not (ord(ch) < 32 or ord(ch) == 127), "raw control char inside literal"
            out.append(ch)
            i += 1
    raise ValueError("unterminated string literal")


def _decode_lua_string(literal: str) -> str:
    value, end = _consume_lua_string(literal, 0)
    assert end == len(literal), "trailing data after string literal"
    return value


def _assert_well_formed(literal: str) -> None:
    """Scan a to_lua output: balanced tables, self-contained string literals, no raw
    control chars outside strings."""
    i, depth = 0, 0
    while i < len(literal):
        ch = literal[i]
        if ch == '"':
            _, i = _consume_lua_string(literal, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, "unbalanced closing brace"
        else:
            assert not (ord(ch) < 32 or ord(ch) == 127), "raw control char outside string"
        i += 1
    assert depth == 0, "unbalanced braces"


@FAST
@given(st.text())
@example('"); app.command.Exit() --')   # classic break-out attempt
@example("@@ASEMCP@@injected")            # success-sentinel injection
@example("@@ASEMCP_ERR@@boom")            # error-sentinel injection
@example('back\\slash "quote"')
@example("\x00\x1f\x7f")                  # control chars
@example("\n\r\t")
def test_to_lua_string_never_breaks_out(s):
    lit = to_lua(s)
    assert lit.startswith('"') and lit.endswith('"')
    assert _decode_lua_string(lit) == s   # payload stayed inside the literal


@FAST
@given(st.integers())
def test_to_lua_int_is_exact(n):
    assert to_lua(n) == str(n)


def test_to_lua_bool_and_none():
    assert to_lua(True) == "true"
    assert to_lua(False) == "false"
    assert to_lua(None) == "nil"


@FAST
@given(st.floats())
def test_to_lua_float_finite_or_zero(x):
    out = to_lua(x)
    if x != x or x in (float("inf"), float("-inf")):
        assert out == "0"          # non-finite collapses to 0 (matches the JSON encoder)
    else:
        assert float(out) == x     # finite floats round-trip


_JSON_LEAVES = (
    st.none() | st.booleans() | st.integers()
    | st.floats(allow_nan=True, allow_infinity=True) | st.text(max_size=8)
)
_JSON_VALUES = st.recursive(
    _JSON_LEAVES,
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(st.text(max_size=4) | st.integers(), children, max_size=4)
    ),
    max_leaves=20,
)


@FAST
@given(_JSON_VALUES)
def test_to_lua_nested_is_structurally_sound(value):
    literal = to_lua(value)
    assert isinstance(literal, str)
    _assert_well_formed(literal)   # balanced tables, self-contained strings


# ================================================================ colour parsing
_CHANNEL = st.integers(min_value=0, max_value=255)


@FAST
@given(_CHANNEL, _CHANNEL, _CHANNEL, _CHANNEL)
def test_hex_rgba_roundtrips(r, g, b, a):
    cs = ColorSpec.parse(f"#{r:02x}{g:02x}{b:02x}{a:02x}")
    assert (cs.r, cs.g, cs.b, cs.a) == (r, g, b, a)


@FAST
@given(_CHANNEL, _CHANNEL, _CHANNEL, _CHANNEL)
def test_comma_rgba_roundtrips(r, g, b, a):
    cs = ColorSpec.parse(f"{r},{g},{b},{a}")
    assert (cs.r, cs.g, cs.b, cs.a) == (r, g, b, a)


@FAST
@given(st.text())
def test_parse_color_never_crashes_and_stays_in_range(s):
    try:
        d = parse_color(s)
    except ValueError:
        return  # rejecting unparseable input is the documented contract
    if "index" in d:
        assert isinstance(d["index"], int)
    else:
        assert set(d) == {"r", "g", "b", "a"}
        assert all(0 <= d[k] <= 255 for k in "rgba")


# =================================================================== path sandbox
@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A workspace with absolute paths disabled (overrides the conftest session env)."""
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ASEPRITE_MCP_ALLOW_ABSOLUTE", raising=False)
    return tmp_path


_SEGMENT = st.text(alphabet="abcXYZ._", min_size=1, max_size=6) | st.just("..")
_REL_PATH = st.lists(_SEGMENT, min_size=1, max_size=6).map("/".join)
_SANDBOX_HEALTH = settings(
    max_examples=100, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@_SANDBOX_HEALTH
@given(_REL_PATH)
def test_resolve_relative_never_escapes(sandbox, rel):
    try:
        out = config.resolve(rel)
    except (WorkspaceError, OSError):
        return  # rejected (escape) or unwritable name — both acceptable
    ws = config.workspace().resolve()
    assert out.is_relative_to(ws)   # resolved paths are always inside the workspace


@_SANDBOX_HEALTH
@given(_REL_PATH)
def test_ensure_output_path_relative_never_escapes(sandbox, rel):
    try:
        out = ensure_output_path(rel, overwrite=True)
    except (WorkspaceError, OSError):
        return
    assert out.is_relative_to(config.workspace().resolve())


@_SANDBOX_HEALTH
@given(st.text(alphabet="abcXYZ._", min_size=1, max_size=10))
def test_absolute_paths_always_rejected(sandbox, name):
    abs_path = str(sandbox.parent / name)  # an absolute path outside the workspace
    with pytest.raises(WorkspaceError):
        config.resolve(abs_path)
