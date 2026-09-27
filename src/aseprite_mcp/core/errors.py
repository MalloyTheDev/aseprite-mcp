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

import re


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


class UnknownArgumentError(AsepriteMCPError):
    """A tool was called with an argument it does not accept.

    Worth its own type because the failure is silent otherwise: the schema layer drops
    unrecognised keys, so a renamed or misspelled argument does not raise -- the tool just
    runs with its defaults and reports success. With 117 tools and 125 parameter names used
    by exactly one tool each, that is a large surface to guess at with no feedback.
    """


# --------------------------------------------------------------------------- #
# Message hygiene                                                             #
# --------------------------------------------------------------------------- #
# A Lua `error("msg")` raised without level 0 is prefixed by the interpreter with the
# script's own location, and the script is a temp file this server wrote:
#     C:\Users\me\AppData\Local\Temp\asemcp_vqwcklpp.lua:264: No layer named 'ghost'
# The line number refers to a file that has already been deleted, and the directory is
# a host path the caller has no business seeing. The message after it is the useful
# part, so strip the prefix and keep the text.
#
# Scoped to this server's own `asemcp_*.lua` temp scripts on purpose: a path that some
# other part of the message legitimately mentions (a sprite, an export target) must
# survive.
_SCRIPT_LOCATION = re.compile(
    r"""(?:[A-Za-z]:[\\/]|[\\/])?   # optional drive letter, or a POSIX root
        (?:[^\n:]*[\\/])?           # optional directory part (may contain spaces)
        asemcp_[A-Za-z0-9_]+\.lua
        :\d+:[ \t]*                 # ":<line>: "
    """,
    re.VERBOSE,
)


def strip_script_location(message: str) -> str:
    """Remove `<temp script>.lua:<line>:` prefixes from a Lua error message.

    Every occurrence is removed, not just a leading one, because the batch runner
    embeds one op's error inside its own summary line.
    """
    return _SCRIPT_LOCATION.sub("", str(message)).strip()
