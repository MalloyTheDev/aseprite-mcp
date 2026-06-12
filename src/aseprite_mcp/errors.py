"""Backwards-compatible shim. Errors now live in `aseprite_mcp.core.errors`."""

from aseprite_mcp.core.errors import (  # noqa: F401
    AsepriteCLIError,
    AsepriteError,
    AsepriteMCPError,
    AsepriteNotFoundError,
    AsepriteTimeoutError,
    ConfigError,
    ExportError,
    LuaToolError,
    ValidationFailed,
    WorkspaceError,
)
