"""Shared helpers for tool modules: colour parsing and path handling.

Colour and path logic is defined in `models.py` (the typed validation boundary);
these thin wrappers keep the long-standing `parse_color`/`lua_path` API that the
tool modules import.
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from .models import ColorSpec, SpritePath


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
