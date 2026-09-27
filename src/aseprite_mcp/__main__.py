"""Allow `python -m aseprite_mcp`.

Several MCP clients document that invocation form rather than the console script, and
it is also the form that avoids holding `Scripts/aseprite-mcp.exe` open, which blocks
`uv sync` on Windows while the server is running.
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
