"""Shared helpers for tool modules: colour parsing and path handling.

Colour and path logic is defined in `models.py` (the typed validation boundary);
these thin wrappers keep the long-standing `parse_color`/`lua_path` API that the
tool modules import.
"""

from __future__ import annotations

from pathlib import Path

from ..core import config, indexed
from ..core.models import ColorSpec, SpritePath
from ..core.runner import run_lua


def parse_color(spec: str | None) -> dict:
    """Parse a flexible colour string into the dict the Lua side consumes
    ({r, g, b, a} or {index: N}). Delegates to `models.ColorSpec`.

    Accepts: "#RGB", "#RGBA", "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a",
    "index:N" (for indexed sprites), or a name such as black/white/red/transparent.
    """
    return ColorSpec.parse(spec).as_dict()


def resolve_path(filename: str) -> Path:
    """Resolve a user filename to an absolute path under the workspace if relative."""
    return config.resolve(filename)


def lua_path(p: Path | str) -> str:
    """Path string for embedding in Lua. Forward slashes work on every platform."""
    return SpritePath(str(p)).lua()


def run_ramp_lua(body: str, args: dict) -> dict:
    """`run_lua` for a tool that takes a declared `ramp`, with the palette reading added.

    On an indexed sprite a ramp colour the palette does not hold is not written: it is
    resolved to the nearest entry that can draw. The harness measures what the ramp
    became (`ramp_on_palette`); this turns that into the sentence a caller can act on and
    drops it in `warnings`.

    Every tool with a `ramp` parameter goes through here rather than through `run_lua`,
    and `test_imports.py` pins that, because a tool that forgets is a tool whose shading
    silently bands on indexed art. Absent rather than empty when there is nothing to say,
    so a `warnings` key always means there is something.
    """
    result = run_lua(body, args)
    if not isinstance(result, dict):
        return result
    notes = indexed.ramp_readings(result.get("ramp_on_palette") or {})
    if notes:
        # Appended rather than assigned: a tool may already have warnings of its own, and
        # dropping those to report this one would trade a finding for a finding.
        existing = result.get("warnings")
        result["warnings"] = [*existing, *notes] if isinstance(existing, list) else notes
    return result
