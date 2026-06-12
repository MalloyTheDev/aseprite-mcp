"""Typed value models for common low-level concepts.

A small, dependency-free (stdlib `dataclasses` only) validation boundary so parsing
and validation live in one place as the codebase grows. **Public MCP tool signatures
are unchanged** — tools still accept plain `str`/`int`; these models are used
internally (e.g. `common.parse_color` delegates to `ColorSpec.parse`).
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Geometry                                                                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Point:
    x: int
    y: int

    @classmethod
    def of(cls, x, y) -> "Point":
        return cls(int(x), int(y))


@dataclass(frozen=True)
class Size:
    width: int
    height: int

    @classmethod
    def of(cls, width, height) -> "Size":
        w, h = int(width), int(height)
        if w < 1 or h < 1:
            raise ValueError(f"size must be at least 1x1, got {w}x{h}")
        return cls(w, h)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def of(cls, x, y, width, height) -> "Rect":
        return cls(int(x), int(y), int(width), int(height))

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height


# --------------------------------------------------------------------------- #
# Colour                                                                      #
# --------------------------------------------------------------------------- #
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


@dataclass(frozen=True)
class ColorSpec:
    """A parsed colour: either RGBA channels, or a palette `index` (indexed sprites)."""

    r: int | None = None
    g: int | None = None
    b: int | None = None
    a: int = 255
    index: int | None = None

    @classmethod
    def parse(cls, spec: str | None) -> "ColorSpec":
        """Parse a flexible colour string. Accepts "#RGB", "#RGBA", "#RRGGBB",
        "#RRGGBBAA", "r,g,b", "r,g,b,a", "index:N"/"idx:N", or a name (black, white,
        red, transparent, ...). Raises ValueError on anything unparseable."""
        if spec is None:
            raise ValueError("A colour is required (e.g. '#ff0000', '255,0,0', or 'red').")

        s = str(spec).strip().lower()

        if s in _NAMED:
            r, g, b, a = _NAMED[s]
            return cls(r=r, g=g, b=b, a=a)

        if s.startswith(("index:", "idx:")):
            return cls(index=int(s.split(":", 1)[1]))

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
            return cls(r=r, g=g, b=b, a=a)

        if "," in s:
            parts = [p.strip() for p in s.split(",") if p.strip() != ""]
            try:
                nums = [max(0, min(255, int(round(float(p))))) for p in parts]
            except ValueError:
                raise ValueError(f"Invalid numeric colour: {spec!r}")
            if len(nums) == 3:
                return cls(r=nums[0], g=nums[1], b=nums[2], a=255)
            if len(nums) == 4:
                return cls(r=nums[0], g=nums[1], b=nums[2], a=nums[3])
            raise ValueError(f"Numeric colour needs 3 or 4 components: {spec!r}")

        raise ValueError(
            f"Could not parse colour {spec!r}. Use '#RRGGBB', '#RRGGBBAA', 'r,g,b', "
            "'r,g,b,a', 'index:N', or a name like 'red'."
        )

    def as_dict(self) -> dict:
        """The dict shape consumed by the Lua `to_pixel` helper / serializer."""
        if self.index is not None:
            return {"index": self.index}
        return {"r": self.r, "g": self.g, "b": self.b, "a": self.a}


@dataclass(frozen=True)
class Pixel:
    """A single pixel: a position plus an optional colour. `as_dict()` matches the
    shape the drawing tools pass to Lua ({x, y, c?})."""

    x: int
    y: int
    color: ColorSpec | None = None

    @classmethod
    def of(cls, x, y, color=None) -> "Pixel":
        cs = color if (color is None or isinstance(color, ColorSpec)) else ColorSpec.parse(color)
        return cls(int(x), int(y), cs)

    def as_dict(self) -> dict:
        d: dict = {"x": self.x, "y": self.y}
        if self.color is not None:
            d["c"] = self.color.as_dict()
        return d


# --------------------------------------------------------------------------- #
# References                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LayerRef:
    """A layer reference: a name (str), a 1-based top-level index (int), or None
    (meaning the active/top layer). Matches what the Lua `find_layer` accepts."""

    value: str | int | None = None

    @classmethod
    def of(cls, value) -> "LayerRef":
        if value is None or isinstance(value, str):
            return cls(value)
        return cls(int(value))


@dataclass(frozen=True)
class FrameRef:
    """A 1-based frame number."""

    number: int

    @classmethod
    def of(cls, number) -> "FrameRef":
        n = int(number)
        if n < 1:
            raise ValueError(f"frame number is 1-based and must be >= 1, got {n}")
        return cls(n)


@dataclass(frozen=True)
class FrameRange:
    """An inclusive 1-based frame range (start <= end, normalized on construction)."""

    start: int
    end: int

    @classmethod
    def of(cls, start, end) -> "FrameRange":
        a, b = FrameRef.of(start).number, FrameRef.of(end).number
        return cls(min(a, b), max(a, b))

    @property
    def count(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class SpritePath:
    """A sprite/asset path. `lua()` returns the forward-slash form Aseprite's Lua
    accepts on every platform."""

    raw: str

    def lua(self) -> str:
        return str(self.raw).replace("\\", "/")
