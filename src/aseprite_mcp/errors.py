"""Typed error hierarchy for aseprite-mcp.

A single base (`AsepriteMCPError`) with specific subclasses so callers and agents can
distinguish configuration failures, a missing Aseprite, workspace/path-sandbox
rejection, process timeouts, Lua tool failures, and CLI/export failures — and recover
accordingly.

Backwards compatibility: `AsepriteError` is an alias of the base, so existing
`from aseprite_mcp.runner import AsepriteError` imports and `isinstance(err, AsepriteError)`
checks keep working for every error type below.
"""

from __future__ import annotations


class AsepriteMCPError(RuntimeError):
    """Base error for all aseprite-mcp failures."""


# Long-standing public name. Kept as an alias so existing imports / isinstance
# checks (`from aseprite_mcp.runner import AsepriteError`) remain valid.
AsepriteError = AsepriteMCPError


class ConfigError(AsepriteMCPError):
    """Invalid environment / configuration (e.g. bad ASEPRITE_PATH, no workspace)."""


class AsepriteNotFoundError(ConfigError, FileNotFoundError):
    """The Aseprite executable could not be located.

    Also subclasses `FileNotFoundError` for backwards compatibility: several call
    sites (`gui.gui_available`, `health.health_check`, the test collection hook)
    already do `except FileNotFoundError` around `config.find_aseprite()`, and this
    keeps that behaviour unchanged.
    """


class WorkspaceError(ConfigError):
    """Workspace path / sandbox / path-resolution failure (e.g. absolute path blocked,
    or a path that escapes the workspace via ``..``)."""


class AsepriteTimeoutError(AsepriteMCPError):
    """An Aseprite process exceeded the configured timeout."""


class LuaToolError(AsepriteMCPError):
    """A Lua tool body reported an error (via the ``@@ASEMCP_ERR@@`` sentinel), or its
    result could not be parsed."""


class AsepriteCLIError(AsepriteMCPError):
    """An Aseprite CLI command failed (non-zero exit)."""


class ExportError(AsepriteCLIError):
    """An export/render-specific CLI failure."""


class ValidationFailed(AsepriteMCPError):
    """Validation failed, when failure is represented as an exception.

    Note: the `validate_sprite_for_game_export` tool reports failures in its returned
    manifest (`validation.passed == False`) rather than raising; this exists for any
    future exception-style validation path.
    """
