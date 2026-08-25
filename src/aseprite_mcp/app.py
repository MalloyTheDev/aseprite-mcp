"""The shared FastMCP application instance.

Defined in its own module so every tool module can `from ..app import mcp`
without creating an import cycle with `server.py`.
"""

from __future__ import annotations

import inspect
from typing import Any

from mcp.server.fastmcp import FastMCP

from .core.errors import UnknownArgumentError

INSTRUCTIONS = """\
This server drives Aseprite (a pixel-art / sprite editor) headlessly to create and
edit sprite files (.aseprite/.ase), draw pixel art, build animations, manage
palettes, and export to PNG/GIF/sprite sheets.

Workflow notes:
  * Relative filenames are resolved inside the server's workspace directory. Absolute
    paths are REFUSED unless ASEPRITE_MCP_ALLOW_ABSOLUTE=1 is set. Most tools return
    the resolved path.
  * Sprites are real files on disk. Edits open the file, modify it, and save.
  * Frames are 1-based. Colours accept "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a",
    "index:N" (for indexed sprites), or a few names (black, white, red, green,
    blue, yellow, cyan, magenta, transparent, ...).
  * Call `render_preview` to get a PNG image of your work so you can see the result
    before continuing. Call `get_sprite_info` for the structured state of a sprite.
  * Recommended first step for a new asset: `create_sprite`, then draw, then preview.
"""

class StrictFastMCP(FastMCP):
    """FastMCP that rejects arguments its tools do not declare.

    The schema layer validates the arguments a tool *does* declare and silently drops the
    rest, so `create_sprite(colour_mode="indexed")` -- when the parameter is `color_mode` --
    returns ok and an RGB sprite. The caller gets a confidently wrong asset and no signal to
    correct on.

    Accepted names are recorded at registration from each function's own signature, so the
    check cannot drift out of step with the tools. Ported verbatim from pixelprep-mcp, where
    this bug was first found.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._accepted: dict[str, set[str]] = {}

    def tool(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        decorate = super().tool(*args, **kwargs)

        def register(fn):
            parameters = inspect.signature(fn).parameters.values()
            # **kwargs means the tool genuinely takes open-ended names; do not police it.
            if not any(p.kind is p.VAR_KEYWORD for p in parameters):
                name = kwargs.get("name") or (args[0] if args and isinstance(args[0], str) else None)
                self._accepted[name or fn.__name__] = {
                    p.name for p in parameters
                    if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
                }
            return decorate(fn)

        return register

    async def call_tool(self, name: str, arguments: dict[str, Any]):  # type: ignore[override]
        accepted = self._accepted.get(name)
        if accepted is not None:
            unknown = sorted(set(arguments) - accepted)
            if unknown:
                raise UnknownArgumentError(
                    f"{name} does not accept {', '.join(repr(u) for u in unknown)}. "
                    f"Accepted arguments: {', '.join(sorted(accepted))}."
                )
        return await super().call_tool(name, arguments)


mcp = StrictFastMCP("aseprite", instructions=INSTRUCTIONS)
