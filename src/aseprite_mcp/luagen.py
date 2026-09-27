"""Backwards-compatible shim. Lua generation now lives in `aseprite_mcp.core.luagen`."""

from aseprite_mcp.core.luagen import (
    ERROR_PREFIX,
    PRELUDE,
    RESULT_PREFIX,
    assemble_script,
    to_lua,
)
