"""A sprite written as a character grid, which is how a pixel artist thinks about one.

`get_pixels(format="map")` has always been able to hand a caller a legend and one string
per row, on the stated grounds that a 16x16 of three colours is about 3,400 characters as
rows of hex and about 350 as a map, and that "defects like a one-pixel offset are visible
in it at a glance". Nothing could hand a map back. The server could show per-pixel intent
and could not receive it, so the only way to author a figure was a list of
`{"x", "y", "color"}` dictionaries, one per pixel.

That asymmetry had a cost in the art. A caller reaching for a thousand-entry dictionary
list does not write a thousand considered pixels; it writes a formula that emits them, and
a formula produces smooth monotone surfaces. Hand-placed pixel art is the opposite: a
highlight nudged two pixels off the geometric centre, an outline that thickens on the
shadow side, three pixels clustered to imply a chip in the stone. A grid is the notation
those decisions can actually be written in.

This module is the expansion, and it is pure: no Aseprite, no MCP, no Lua. It turns a
legend and rows into the same pixel list `draw_pixels` already takes, so a map inherits
every guarantee that write path has rather than growing a second one: the selection mask
is consulted, off-canvas writes are clipped and counted, and the result says how many
pixels landed.

The shape it accepts is deliberately the shape `get_pixels(format="map")` returns, so a
read, an edit and a write round-trip. That is the point of matching it exactly rather than
inventing a tidier format.
"""
from __future__ import annotations

from .errors import ValidationFailed
from .limits import MAX_CANVAS_DIMENSION, MAX_PIXEL_LIST_LENGTH

# The character the read side emits for a pixel with zero alpha, and the one a caller can
# rely on meaning "leave this alone" without declaring it.
TRANSPARENT_CHAR = "."
# What the read side puts in the legend against that character.
TRANSPARENT_VALUE = "transparent"


def _check_legend(legend: dict) -> dict[str, str | None]:
    """The legend as {character: colour or None}, with None meaning leave the pixel alone."""
    if not isinstance(legend, dict):
        raise ValidationFailed(
            f"legend must be a mapping of one-character symbols to colours; got "
            f"{type(legend).__name__}."
        )
    resolved: dict[str, str | None] = {TRANSPARENT_CHAR: None}
    for symbol, value in legend.items():
        if not isinstance(symbol, str) or len(symbol) != 1:
            raise ValidationFailed(
                f"legend key {symbol!r} is not a single character. A map is read one "
                "character per pixel, so every key has to be exactly one."
            )
        if value is None or (isinstance(value, str) and value.strip().lower() in
                             (TRANSPARENT_VALUE, "none", "")):
            resolved[symbol] = None
            continue
        if not isinstance(value, str):
            raise ValidationFailed(
                f"legend[{symbol!r}] is {value!r}; a legend value has to be a colour "
                f'string or "{TRANSPARENT_VALUE}".'
            )
        resolved[symbol] = value
    return resolved


def read_rows(rows) -> tuple[list[str], int, int]:
    """A character grid checked for being a grid, as `(lines, width, height)`.

    Separated from `expand` so that a second reader of this notation inherits these
    refusals rather than writing its own: `core.occlusion` reads the same shape of map but
    its legend names masses rather than colours, and the ragged-row message below is the
    one a hand-written grid actually earns. Two copies of it would be two messages, and the
    one that drifts is the one nobody is reading.
    """
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValidationFailed(
            "rows must be a non-empty list of strings, one per row of the map."
        )
    lines = []
    for index, row in enumerate(rows):
        if not isinstance(row, str):
            raise ValidationFailed(
                f"rows[{index}] is {type(row).__name__}, not a string. A map is one "
                "string per row, one character per pixel."
            )
        lines.append(row)

    width = len(lines[0])
    if width == 0:
        raise ValidationFailed("rows[0] is empty, so the map has no width.")
    for index, row in enumerate(lines):
        if len(row) != width:
            # Named precisely because this is the mistake a hand-written grid actually
            # makes, and a ragged map that was silently padded would shift every pixel
            # after the short row.
            raise ValidationFailed(
                f"rows[{index}] is {len(row)} characters and rows[0] is {width}. Every "
                "row of a map has to be the same length, or the grid is not a grid."
            )

    height = len(lines)
    if width > MAX_CANVAS_DIMENSION or height > MAX_CANVAS_DIMENSION:
        raise ValidationFailed(
            f"map is {width}x{height}; the maximum is {MAX_CANVAS_DIMENSION} per axis."
        )
    return lines, width, height


def expand(rows, legend, origin_x: int = 0, origin_y: int = 0) -> dict:
    """The pixel list a character grid describes, plus what it says about itself.

    Returns `pixels` in the shape `draw_pixels` takes, with `width`, `height`, the count
    of cells deliberately left alone, and the colours actually used. Colours are passed
    through as written: parsing them is the tool layer's job, so this module stays free of
    anything that knows what a colour is.
    """
    lines, width, height = read_rows(rows)
    resolved = _check_legend(legend)
    pixels: list[dict] = []
    transparent = 0
    used: dict[str, int] = {}
    for row_index, row in enumerate(lines):
        for col_index, symbol in enumerate(row):
            if symbol not in resolved:
                known = "".join(sorted(k for k in resolved if k != TRANSPARENT_CHAR))
                raise ValidationFailed(
                    f"rows[{row_index}][{col_index}] is {symbol!r}, which the legend does "
                    f"not define. The legend has {known!r} plus "
                    f"{TRANSPARENT_CHAR!r} for a pixel to leave alone. A character with "
                    "no colour is refused rather than skipped, because a typo in a grid "
                    "would otherwise paint nothing and report success."
                )
            colour = resolved[symbol]
            if colour is None:
                transparent += 1
                continue
            pixels.append({"x": origin_x + col_index, "y": origin_y + row_index,
                           "color": colour})
            used[colour] = used.get(colour, 0) + 1

    if not pixels:
        raise ValidationFailed(
            f"the map is {width}x{height} and every one of its {transparent} cells is "
            "transparent, so it would draw nothing. Give it at least one colour, or do "
            "not call this."
        )
    if len(pixels) > MAX_PIXEL_LIST_LENGTH:
        raise ValidationFailed(
            f"the map describes {len(pixels)} pixels to draw; the maximum per call is "
            f"{MAX_PIXEL_LIST_LENGTH}. Split it into bands and draw them with an origin "
            "each."
        )
    return {
        "pixels": pixels,
        "width": width,
        "height": height,
        "transparent": transparent,
        "colors_used": used,
    }
