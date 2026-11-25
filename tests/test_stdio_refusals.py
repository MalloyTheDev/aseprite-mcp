"""Refusals reach a real MCP client over stdio, with the text that names the way out.

`test_refusals_reach_clients.py` checks the translation at `StrictMCPServer.call_tool`, in
process. This file checks the same promise from the other side of the wire: it launches the
installed `aseprite-mcp` console script, speaks the protocol to it through the SDK's own
stdio client, and reads what a client reads, `is_error` and the first text block. An agent
sees only that, so a refusal whose message never arrives is a refusal that costs a blind
retry, however well the server phrases it.

Every case here is refused in Python before Aseprite is launched, so none of them needs an
editor. The server is given an `ASEPRITE_PATH` that points at nothing: if a refusal were
ever to fall through to a launch, the reply would be about a missing Aseprite instead of
the argument, and the assertions would fail rather than pass by accident. That is also why
the module is marked `pure` and runs on CI, where there is no Aseprite.

The cases:

* `generate_ramp` with `sat_curve="ease_out"` is the control. It already refuses, and it
  must name both accepted values (this is the translation fixed in #237).
* `assess_sprite` and `export_game_asset_bundle` with an unknown `subject` must come back as
  an error naming both accepted values, "character" and "prop", before anything is written.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.pure

_TIMEOUT = 90  # seconds for one whole session; a launch plus a call is normally under 3


def _server_command() -> tuple[str, list[str]]:
    """The `aseprite-mcp` console script of the environment running the tests.

    It sits beside the interpreter (`Scripts/aseprite-mcp.exe` on Windows, `bin/aseprite-mcp`
    elsewhere). If a layout does not have it there, `python -m aseprite_mcp` starts the same
    server from the same interpreter, so the test never depends on the PATH.
    """
    scripts = Path(sys.executable).resolve().parent
    for name in ("aseprite-mcp.exe", "aseprite-mcp"):
        candidate = scripts / name
        if candidate.is_file():
            return str(candidate), []
    found = shutil.which("aseprite-mcp")
    if found:
        return found, []
    return sys.executable, ["-m", "aseprite_mcp"]


def _call(tmp_path: Path, tool: str, arguments: dict) -> tuple[bool, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    env = {
        "ASEPRITE_MCP_WORKSPACE": str(workspace),
        # Points at nothing, so a refusal that fell through to a launch would be loud.
        "ASEPRITE_PATH": str(tmp_path / "no-such-aseprite" / "aseprite"),
    }
    command, args = _server_command()
    params = StdioServerParameters(command=command, args=args, env=env)

    async def session() -> tuple[bool, str]:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool(tool, arguments)
            text = result.content[0].text if result.content else ""
            return bool(result.is_error), text

    async def bounded() -> tuple[bool, str]:
        return await asyncio.wait_for(session(), timeout=_TIMEOUT)

    return asyncio.run(bounded())


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def test_control_a_bad_sat_curve_names_the_accepted_values(tmp_path):
    is_error, text = _call(tmp_path, "generate_ramp",
                           {"base_color": "#3060a0", "sat_curve": "ease_out"})
    assert is_error, text
    assert "linear" in text and "peak" in text, text
    assert "Error executing tool" not in text, text


@pytest.mark.parametrize("tool", ["assess_sprite", "export_game_asset_bundle"])
def test_an_unknown_subject_is_refused_naming_both_values(tmp_path, tool):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # A file that exists, so a refusal cannot be mistaken for "no such sprite". It is not a
    # real sprite: nothing may open it, which is what an early refusal guarantees.
    (workspace / "vase.aseprite").write_bytes(b"not a sprite")
    before = _files(workspace)

    is_error, text = _call(tmp_path, tool,
                           {"filename": "vase.aseprite", "subject": "monster"})

    assert is_error, text
    assert "character" in text and "prop" in text, text
    assert "monster" in text, text
    assert "Error executing tool" not in text, text
    assert "Could not locate Aseprite" not in text and "ASEPRITE_PATH" not in text, text
    assert _files(workspace) == before, "a refused call must not write anything"
