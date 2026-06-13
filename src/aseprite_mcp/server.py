"""Entry point: import every tool module (registering tools) and run the server."""

from __future__ import annotations

from .app import mcp

# Importing each module registers its @mcp.tool() functions on `mcp`.
from .tools import (  # noqa: F401,E402
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


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
