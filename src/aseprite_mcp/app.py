"""The shared FastMCP application instance.

Defined in its own module so every tool module can `from ..app import mcp`
without creating an import cycle with `server.py`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

INSTRUCTIONS = """\
This server drives Aseprite (a pixel-art / sprite editor) headlessly to create and
edit sprite files (.aseprite/.ase), draw pixel art, build animations, manage
palettes, and export to PNG/GIF/sprite sheets.

Workflow notes:
  * Relative filenames are resolved inside the server's workspace directory;
    absolute paths are honoured as-is. Most tools return the resolved path.
  * Sprites are real files on disk. Edits open the file, modify it, and save.
  * Frames are 1-based. Colours accept "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a",
    or a few names (black, white, red, green, blue, transparent, ...).
  * Call `render_preview` to get a PNG image of your work so you can see the result
    before continuing. Call `get_sprite_info` for the structured state of a sprite.
  * Recommended first step for a new asset: `create_sprite`, then draw, then preview.
"""

mcp = FastMCP("aseprite", instructions=INSTRUCTIONS)
