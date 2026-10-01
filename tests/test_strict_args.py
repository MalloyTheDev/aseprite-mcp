"""Unknown arguments must fail loudly rather than be dropped.

This server has 147 tools and 173 parameter names used by exactly one tool each, so the
guess-the-name surface is large -- and until now a wrong guess produced no feedback at all.
`create_sprite(colour_mode="indexed")` returned ok and an RGB sprite, because the parameter
is `color_mode` and the schema layer discards keys it does not recognise.

The same bug was found and fixed in pixelprep-mcp first; this is the port, with the op-level
equivalent inside apply_operations covered too.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import aseprite_mcp.server  # noqa: F401  -- importing registers the real tools
from aseprite_mcp.app import StrictMCPServer, mcp
from aseprite_mcp.core import oplib
from aseprite_mcp.core.errors import AsepriteMCPError, UnknownArgumentError, ValidationFailed


def call(server, name, arguments):
    """Invoke a tool and return its parsed dict, whatever shape the SDK hands back.

    mcp 2.x returns a CallToolResult carrying a `content` list; earlier versions
    returned the content sequence itself. The text block is the tool's JSON either way,
    so parse that rather than `structured_content`, which wraps the payload.
    """
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple):
        result = result[0]
    blocks = getattr(result, "content", result)
    return json.loads(blocks[0].text)


@pytest.fixture()
def server():
    s = StrictMCPServer("test")

    @s.tool()
    def sprite(width: int = 16, color_mode: str = "rgb") -> dict:
        return {"width": width, "color_mode": color_mode}

    return s


def test_a_declared_argument_is_passed_through(server):
    assert call(server, "sprite", {"width": 64})["width"] == 64


def test_an_unknown_argument_raises(server):
    with pytest.raises(UnknownArgumentError):
        call(server, "sprite", {"colour_mode": "indexed"})


def test_the_message_names_the_offender_and_the_alternatives(server):
    with pytest.raises(UnknownArgumentError) as excinfo:
        call(server, "sprite", {"colour_mode": "indexed"})
    message = str(excinfo.value)
    assert "colour_mode" in message and "color_mode" in message and "width" in message


def test_a_valid_argument_alongside_an_invalid_one_still_raises(server):
    with pytest.raises(UnknownArgumentError):
        call(server, "sprite", {"width": 64, "colour_mode": "indexed"})


def test_it_is_an_aseprite_error_so_existing_handling_reports_it(server):
    with pytest.raises(AsepriteMCPError):
        call(server, "sprite", {"nope": 1})


def test_the_real_server_rejects_a_misspelled_parameter():
    """Regression: this exact call created an RGB sprite and reported success."""
    with pytest.raises(UnknownArgumentError) as excinfo:
        call(mcp, "create_sprite",
             {"filename": "x.aseprite", "width": 64, "height": 64, "colour_mode": "indexed"})
    assert "color_mode" in str(excinfo.value)


def test_var_keyword_tools_are_not_policed(server):
    """A **kwargs tool takes open-ended names, so it must not get an accepted-set.

    Asserted at registration rather than through a call: the SDK models **kwargs as a single
    required `kwargs` field, so such a tool cannot be invoked with loose names end-to-end
    anyway. What matters is that the guard does not invent a whitelist for a signature that
    deliberately has none.
    """

    @server.tool()
    def anything(**kwargs) -> dict:
        return {"got": sorted(kwargs)}

    assert "anything" not in server._accepted
    assert "sprite" in server._accepted


def test_every_registered_tool_has_an_accepted_set():
    """A tool registered by another route would be silently unpoliced."""
    assert len(mcp._accepted) > 100


# --------------------------------------------------------------- batch operation arguments


def test_an_unknown_op_arg_is_rejected():
    """validate_operations walked the SPEC, so a misspelled optional arg simply vanished."""
    with pytest.raises(ValidationFailed) as excinfo:
        oplib.validate_operations(
            [{"op": "add_layer", "args": {"name": "L1", "blendmode": "multiply"}}])
    assert "blendmode" in str(excinfo.value)


def test_the_op_error_names_the_accepted_arguments():
    with pytest.raises(ValidationFailed) as excinfo:
        oplib.validate_operations([{"op": "add_layer", "args": {"name": "L1", "opacty": 10}}])
    message = str(excinfo.value)
    assert "opacty" in message and "opacity" in message


def test_a_correctly_spelled_op_still_validates():
    """Guards against over-correction breaking every legitimate batch."""
    got = oplib.validate_operations(
        [{"op": "add_layer", "args": {"name": "L1", "opacity": 128, "blend_mode": "multiply"}}])
    assert got[0]["op"] == "add_layer"
