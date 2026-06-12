"""Entry point: import every tool module (registering tools) and run the server."""

from __future__ import annotations

from .app import mcp

# Importing each module registers its @mcp.tool() functions on `mcp`.
from .tools import (  # noqa: F401,E402
    brushes,
    cels,
    drawing,
    effects,
    export,
    frames,
    image,
    inspect,
    layers,
    palette,
    reference,
    slices,
    sprite,
    tags,
    text,
    tilemap,
    transform,
)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
