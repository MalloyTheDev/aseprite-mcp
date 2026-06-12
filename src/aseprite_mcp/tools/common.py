"""Shared helpers for tool modules: colour parsing and path handling."""

from __future__ import annotations

from pathlib import Path

from .. import config

# A small set of convenience colour names.
_NAMED = {
    "transparent": (0, 0, 0, 0),
    "none": (0, 0, 0, 0),
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "red": (255, 0, 0, 255),
    "green": (0, 255, 0, 255),
    "lime": (0, 255, 0, 255),
    "blue": (0, 0, 255, 255),
    "yellow": (255, 255, 0, 255),
    "cyan": (0, 255, 255, 255),
    "magenta": (255, 0, 255, 255),
    "gray": (128, 128, 128, 255),
    "grey": (128, 128, 128, 255),
    "silver": (192, 192, 192, 255),
    "orange": (255, 165, 0, 255),
    "purple": (128, 0, 128, 255),
    "pink": (255, 192, 203, 255),
    "brown": (139, 69, 19, 255),
}


def parse_color(spec: str | None) -> dict:
    """Parse a flexible colour string into an {r, g, b, a} dict (0-255 each).

    Accepts: "#RGB", "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a", "index:N"
    (for indexed sprites), or a name such as black/white/red/transparent.
    """
    if spec is None:
        raise ValueError("A colour is required (e.g. '#ff0000', '255,0,0', or 'red').")

    s = str(spec).strip().lower()

    if s in _NAMED:
        r, g, b, a = _NAMED[s]
        return {"r": r, "g": g, "b": b, "a": a}

    if s.startswith(("index:", "idx:")):
        return {"index": int(s.split(":", 1)[1])}

    if s.startswith("#"):
        h = s[1:]
        try:
            if len(h) == 3:
                r, g, b = (int(c * 2, 16) for c in h)
                a = 255
            elif len(h) == 4:
                r, g, b, a = (int(c * 2, 16) for c in h)
            elif len(h) == 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                a = 255
            elif len(h) == 8:
                r, g, b, a = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
            else:
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid hex colour: {spec!r}")
        return {"r": r, "g": g, "b": b, "a": a}

    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip() != ""]
        try:
            nums = [max(0, min(255, int(round(float(p))))) for p in parts]
        except ValueError:
            raise ValueError(f"Invalid numeric colour: {spec!r}")
        if len(nums) == 3:
            return {"r": nums[0], "g": nums[1], "b": nums[2], "a": 255}
        if len(nums) == 4:
            return {"r": nums[0], "g": nums[1], "b": nums[2], "a": nums[3]}
        raise ValueError(f"Numeric colour needs 3 or 4 components: {spec!r}")

    raise ValueError(
        f"Could not parse colour {spec!r}. Use '#RRGGBB', '#RRGGBBAA', 'r,g,b', "
        "'r,g,b,a', 'index:N', or a name like 'red'."
    )


def resolve_path(filename: str) -> Path:
    """Resolve a user filename to an absolute path under the workspace if relative."""
    return config.resolve(filename)


def lua_path(p: Path | str) -> str:
    """Path string for embedding in Lua. Forward slashes work on every platform."""
    return str(p).replace("\\", "/")
