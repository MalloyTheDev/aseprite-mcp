"""Entry point: import every tool module (registering tools) and run the server."""

from __future__ import annotations

import os

from .app import mcp

# Importing each module registers its @mcp.tool() functions on `mcp`.
from .tools import (
    asset_spec,
    batch,
    brushes,
    cels,
    drawing,
    effects,
    export,
    export_presets,
    frames,
    gui,
    health,
    image,
    inspect,
    layers,
    minecraft,
    palette,
    reference,
    slices,
    sprite,
    tags,
    text,
    tilemap,
    transform,
    workflow,
)

_TRANSPORTS = ("stdio", "streamable-http", "sse")


def main() -> None:
    """Run the MCP server, over stdio unless ASEPRITE_MCP_TRANSPORT says otherwise.

    stdio stays the default because it is what every desktop MCP client launches, and
    because it keeps the server reachable only by the process that spawned it.

    The HTTP transports exist for agents that cannot spawn a local process (hosted
    runners, remote agents). They are opt-in for a reason: this server's whole file
    capability is scoped by a workspace directory, not by an identity, so binding it to
    a port hands every caller that can reach that port the same filesystem access the
    local user has. Bind it to loopback, or put authentication in front of it.
    """
    transport = os.environ.get("ASEPRITE_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in _TRANSPORTS:
        raise SystemExit(
            f"ASEPRITE_MCP_TRANSPORT={transport!r} is not one of {', '.join(_TRANSPORTS)}."
        )
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
