"""Backwards-compatible shim. The runner now lives in `aseprite_mcp.core.runner`.

Preserves long-standing imports like `from aseprite_mcp.runner import AsepriteError`.
"""

from aseprite_mcp.core.runner import (  # noqa: F401
    AsepriteCLIError,
    AsepriteError,
    AsepriteTimeoutError,
    LuaToolError,
    run_cli,
    run_lua,
)
