"""A refusal must reach the MCP client with its message, not as a masked crash.

A refusal from this server names the way out in its message. The 2.x SDK forwards the
message of its own ToolError into the is_error result and treats every other exception
as a crash, masking it to `Error executing tool <name>` while the text goes to the
server log (mcp.server.mcpserver.exceptions). Measured on the live server before the
fix: a ragged draw_pixel_map grid cost two blind retries, because the row count that
named the defect never arrived.

`StrictMCPServer.call_tool` therefore translates AsepriteMCPError, and the ValueError
with which `core` refuses a value, into ToolError with the message intact and the
original chained as __cause__, and leaves anything else masked exactly as the SDK
intends for a crash. These tests run at that boundary on the real registered server,
the same place test_strict_args.py runs. The step after it, a raised ToolError's text
landing verbatim in the is_error result, is the SDK's own documented contract, not ours
to re-test.
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

import aseprite_mcp.server  # noqa: F401  -- importing registers the real tools
from aseprite_mcp.app import StrictMCPServer, mcp
from aseprite_mcp.core.errors import ValidationFailed


def call(name, arguments, server=mcp):
    return asyncio.run(server.call_tool(name, arguments))


def test_a_tools_own_refusal_arrives_with_its_text():
    """export_motion_trail refuses a tag and a frame list together before any launch."""
    with pytest.raises(ToolError) as excinfo:
        call("export_motion_trail",
             {"filename": "refusals/x.aseprite", "output": "refusals/x.png",
              "tag": "walk", "frames": [1, 2]})
    message = str(excinfo.value)
    assert "ValidationFailed" in message and "not both" in message
    assert "Error executing tool" not in message


def test_the_typed_refusal_rides_along_as_the_cause():
    with pytest.raises(ToolError) as excinfo:
        call("export_motion_trail",
             {"filename": "refusals/x.aseprite", "output": "refusals/x.png",
              "tag": "walk", "frames": [1, 2]})
    assert isinstance(excinfo.value.__cause__, ValidationFailed)


def test_an_unknown_argument_is_anticipated_not_a_crash():
    with pytest.raises(ToolError) as excinfo:
        call("create_sprite",
             {"filename": "refusals/x.aseprite", "width": 16, "height": 16,
              "colour_mode": "indexed"})
    message = str(excinfo.value)
    assert "UnknownArgumentError" in message
    assert "colour_mode" in message and "color_mode" in message


def test_a_crash_stays_masked():
    """Only anticipated refusals are unmasked; an arbitrary bug keeps the SDK's cover."""
    server = StrictMCPServer("crashes")

    @server.tool()
    def implodes() -> dict:
        raise RuntimeError("the private detail")

    with pytest.raises(UnexpectedToolError) as excinfo:
        call("implodes", {}, server=server)
    assert "private detail" not in str(excinfo.value)


def test_a_refusal_buried_under_a_crash_is_still_surfaced():
    """Tool code that re-raises around a refusal keeps the refusal's text reachable."""
    server = StrictMCPServer("wrapped")

    @server.tool()
    def wraps_its_refusal() -> dict:
        try:
            raise ValidationFailed("scale is 0; minimum is 1")
        except ValidationFailed as exc:
            raise RuntimeError("while finishing up") from exc

    with pytest.raises(ToolError) as excinfo:
        call("wraps_its_refusal", {}, server=server)
    assert "minimum is 1" in str(excinfo.value)


def test_a_colour_that_does_not_parse_arrives_with_the_accepted_forms(monkeypatch):
    """`core` refuses a bad value with ValueError by design. It is a refusal, not a crash,
    and a mistyped colour is the commonest mistake a caller makes."""
    from aseprite_mcp.tools import drawing

    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a colour that cannot parse")
    monkeypatch.setattr(drawing, "run_lua", refuse)

    with pytest.raises(ToolError) as excinfo:
        call("draw_rectangle", {"filename": "refusals/x.aseprite", "x": 0, "y": 0,
                                "width": 2, "height": 2, "color": "nope"})
    message = str(excinfo.value)
    assert "ValueError" in message and "'nope'" in message and "#RRGGBB" in message
