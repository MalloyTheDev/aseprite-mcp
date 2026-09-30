"""Computable quality metrics for pixel art.

Every proposal to improve output quality is unfalsifiable without a measurement, and
there was not one. These functions supply the part that a machine can judge, so a change
can be shown to have helped rather than asserted to have.

**What this can and cannot see.** The metrics below are guardrails against regression,
not a score for how good a sprite is. They can tell you that a silhouette has stray
pixels, that a shading pass left colours outside its ramp, or that a tile does not wrap.
They cannot tell you whether the sprite reads as a potion, whether the light direction is
coherent, whether shading follows the form or pillows around the outline, or whether a
walk cycle has weight. Those need a person looking at two versions of the same prompt.
Treating a metric vector as a quality score is the way to optimise a sprite into
something that measures well and looks worse.

Two sprites are only comparable when they answer the same prompt. `canvas_usage` of 0.47
is meaningless on its own and meaningful against the same icon drawn twice.

Everything here is pure: it takes a grid of "#RRGGBBAA" strings, the shape `get_pixels`
returns, and touches neither Aseprite nor the filesystem. That keeps it testable on a
runner with no editor installed.
"""

from __future__ import annotations

import colorsys
import itertools
from typing import NamedTuple

Grid = list[list[str]]

# Hue distance, in degrees, above which two colours are counted as belonging to separate
# ramps. Pixel-art ramps hue-shift as they go light or dark, commonly by 20 to 40 degrees
# end to end, so the threshold has to sit above that or one ramp reads as several.
_RAMP_HUE_GAP = 45.0


class BBox(NamedTuple):
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.y1 - self.y0 + 1


def _rgba(color: str) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 6:
        c += "ff"
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def _opaque_cells(grid: Grid) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    out = []
    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            px = _rgba(color)
            if px[3] > 0:
                out.append((x, y, px))
    return out


def distinct_colors(grid: Grid) -> int:
    """How many distinct opaque colours the sprite uses.

    A rising count across a change usually means a filter has introduced colours that
    are not on any ramp, which is the most common way pixel art stops looking like
    pixel art.
    """
    return len({px for _, _, px in _opaque_cells(grid)})


def ramp_count(grid: Grid) -> int:
    """Roughly how many separate hue families are present.

    Approximate by construction: it clusters hues and cannot know which colours the
    artist meant as one ramp. Useful for spotting a jump (a shading pass that invented a
    new hue family), not as an absolute.
    """
    # Greys are excluded: their hue is arbitrary (colorsys reports 0 for any neutral),
    # so a black outline would otherwise register as a red ramp and inflate the count.
    hues = sorted(
        colorsys.rgb_to_hls(*(v / 255 for v in px[:3]))[0] * 360
        for _, _, px in _opaque_cells(grid)
        if len(set(px[:3])) > 1
    )
    if not hues:
        return 0
    clusters = 1
    for previous, current in itertools.pairwise(hues):
        if current - previous > _RAMP_HUE_GAP:
            clusters += 1
    return clusters


def isolated_pixels(grid: Grid) -> int:
    """Opaque pixels with no orthogonal neighbour of the same colour.

    Reads as noise or dirt at sprite scale. A deliberate single-pixel highlight counts
    here too, so a small non-zero number is normal and a jump is the signal.
    """
    lookup = {(x, y): px for x, y, px in _opaque_cells(grid)}
    count = 0
    for (x, y), px in lookup.items():
        if not any(lookup.get((x + dx, y + dy)) == px
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            count += 1
    return count


def jaggy_corners(grid: Grid) -> int:
    """Staircase corners in the silhouette.

    Counts 2x2 windows where exactly three cells are opaque, which is the shape a
    single-pixel step makes. It is what Aseprite's own pixel-perfect mode exists to
    avoid. Curves legitimately produce some, so compare rather than aim for zero.
    """
    height = len(grid)
    width = len(grid[0]) if height else 0

    def opaque(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and _rgba(grid[y][x])[3] > 0

    return sum(
        1
        for y in range(height - 1)
        for x in range(width - 1)
        if sum((opaque(x, y), opaque(x + 1, y), opaque(x, y + 1), opaque(x + 1, y + 1))) == 3
    )


def bounding_box(grid: Grid) -> BBox | None:
    """The box around the opaque pixels, or None for an empty sprite."""
    cells = _opaque_cells(grid)
    if not cells:
        return None
    xs = [x for x, _, _ in cells]
    ys = [y for _, y, _ in cells]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def canvas_usage(grid: Grid) -> float:
    """Fraction of the canvas the content's bounding box covers.

    A very low value usually means the sprite was drawn smaller than the canvas asked
    for, which is a common failure when a model picks coordinates without checking.
    """
    box = bounding_box(grid)
    if box is None:
        return 0.0
    height = len(grid)
    width = len(grid[0]) if height else 0
    return (box.width * box.height) / (width * height) if width and height else 0.0


def is_centred(grid: Grid) -> bool:
    """Whether the content sits centred on the canvas, within a pixel.

    The tolerance is there because an odd-sized shape on an even canvas cannot be
    exactly centred, which is a real constraint of the drawing primitives rather than a
    mistake by the caller.
    """
    box = bounding_box(grid)
    if box is None:
        return False
    height = len(grid)
    width = len(grid[0]) if height else 0
    return (abs(box.x0 - (width - 1 - box.x1)) <= 1
            and abs(box.y0 - (height - 1 - box.y1)) <= 1)


def silhouette_asymmetry(grid: Grid) -> int:
    """Pixels whose opacity differs from their horizontal mirror.

    Zero for a symmetric character. Non-zero is only a defect when symmetry was
    intended, which the metric cannot know, so read it as a difference between two
    versions rather than as a verdict.
    """
    height = len(grid)
    width = len(grid[0]) if height else 0
    return sum(
        1
        for y in range(height)
        for x in range(width)
        if (_rgba(grid[y][x])[3] > 0) != (_rgba(grid[y][width - 1 - x])[3] > 0)
    )


def palette_conformance(grid: Grid, ramp: list[str]) -> float:
    """Fraction of opaque pixels whose colour is exactly on `ramp`.

    The sharpest single measurement available here, because it is objective and it is
    what separates a shading operation from an image filter. A global brightness or
    contrast adjustment scores near zero by construction: it moves every pixel off the
    palette. A ramp-aware operation scores 1.0.
    """
    cells = _opaque_cells(grid)
    if not cells:
        return 1.0
    allowed = {_rgba(c) for c in ramp}
    return sum(1 for _, _, px in cells if px in allowed) / len(cells)


def tile_seam_ratio(grid: Grid) -> tuple[float, float]:
    """How much worse the wrap edge is than the interior, horizontally and vertically.

    A value near 1.0 means the wrap transition looks like any interior transition, so
    the tile wraps. Much above 1.0 means a visible seam. Returned per axis because a
    tile commonly wraps on one axis and not the other, and knowing which is broken is
    most of the fix.
    """
    height = len(grid)
    width = len(grid[0]) if height else 0
    if width < 3 or height < 3:
        return (0.0, 0.0)

    def distance(a: str, b: str) -> float:
        pa, pb = _rgba(a), _rgba(b)
        return sum(abs(x - y) for x, y in zip(pa, pb, strict=True)) / 4.0

    def axis(columns: list[list[str]]) -> float:
        interior = [
            sum(distance(columns[i][j], columns[i + 1][j]) for j in range(len(columns[i])))
            / len(columns[i])
            for i in range(len(columns) - 1)
        ]
        wrap = (
            sum(distance(columns[-1][j], columns[0][j]) for j in range(len(columns[0])))
            / len(columns[0])
        )
        mean_interior = sum(interior) / len(interior) if interior else 0.0
        if mean_interior < 1e-9:
            # Every interior transition is identical, so the tile is flat. A non-zero
            # wrap then cannot happen; reporting a huge ratio would be an artefact.
            return 0.0 if wrap < 1e-9 else float("inf")
        return wrap / mean_interior

    columns = [[grid[y][x] for y in range(height)] for x in range(width)]
    rows = [list(row) for row in grid]
    return (axis(columns), axis(rows))


def loop_closure(frames: list[Grid]) -> float:
    """Mean per-pixel difference between the last frame and the first.

    Near zero means the last frame duplicates the first, which is the classic loop
    defect: it produces a double-length hold at the seam. A cycle should lead back into
    frame one, not repeat it. Higher is not automatically better, so read it alongside
    the neighbouring frame differences.
    """
    if len(frames) < 2:
        return 0.0
    first, last = frames[0], frames[-1]
    height = min(len(first), len(last))
    width = min(len(first[0]), len(last[0])) if height else 0
    if not width:
        return 0.0
    total = 0.0
    for y in range(height):
        for x in range(width):
            a, b = _rgba(first[y][x]), _rgba(last[y][x])
            total += sum(abs(p - q) for p, q in zip(a, b, strict=True)) / 4.0
    return total / (width * height)


def score(grid: Grid, ramp: list[str] | None = None) -> dict:
    """Every single-frame metric at once, as a plain dict.

    `ramp` enables palette conformance, which is omitted rather than reported as a
    meaningless 1.0 when no ramp was declared.
    """
    box = bounding_box(grid)
    result = {
        "colors": distinct_colors(grid),
        "drawn_pixels": len(_opaque_cells(grid)),
        "ramps": ramp_count(grid),
        "isolated_pixels": isolated_pixels(grid),
        "jaggy_corners": jaggy_corners(grid),
        "canvas_usage": round(canvas_usage(grid), 3),
        "centred": is_centred(grid),
        "silhouette_asymmetry": silhouette_asymmetry(grid),
        "bbox": list(box) if box else None,
    }
    if ramp:
        result["palette_conformance"] = round(palette_conformance(grid, ramp), 3)
    return result

# --------------------------------------------------------------------------- readings
# A number is not a verdict. These turn each measurement into the sentence a pixel artist
# would say about it, with the thresholds written down rather than implied, because the
# caller cannot see the sprite and "isolated_pixels: 14" means nothing on its own.

# Under a third of the canvas drawn on usually means the art is lost in it, which matters
# because a sprite is normally exported at its canvas size.
SPARSE_CANVAS = 0.3
# A handful of lone pixels is texture; more than this reads as noise at any zoom.
NOISY_ISOLATED = 8
# Corners where two diagonal runs meet, as a share of the drawn box's half-perimeter. A
# raster circle is made of steps and always scores some; the threshold is relative so a
# 28px disc does not get told off for being round.
JAGGY_SHARE = 0.6
# Asymmetry is only worth a word when the art is *nearly* symmetric, which reads as a
# mistake. Wildly asymmetric art is just art, and saying so on every sprite is noise.
NEARLY_SYMMETRIC = 0.12


def readings(metrics: dict, *, width: int, height: int) -> list[str]:
    """One line per measurement worth acting on, and nothing for the ones that are fine."""
    out: list[str] = []
    box = metrics.get("bbox")
    if box is None:
        out.append("Nothing is drawn on this frame.")
        return out

    usage = metrics.get("canvas_usage", 0.0)
    if usage < SPARSE_CANVAS:
        drawn_w = box[2] - box[0] + 1
        drawn_h = box[3] - box[1] + 1
        out.append(
            f"The art fills {usage:.0%} of the canvas ({drawn_w}x{drawn_h} of "
            f"{width}x{height}). trim_sprite or resize_canvas would centre it."
        )
    if not metrics.get("centred", True):
        out.append("The drawn content is off-centre, which shows up when the sprite is "
                   "scaled or flipped.")
    isolated = metrics.get("isolated_pixels", 0)
    if isolated > NOISY_ISOLATED:
        out.append(f"{isolated} pixels have no neighbour of their own colour, which reads "
                   "as noise rather than as texture.")
    jaggies = metrics.get("jaggy_corners", 0)
    drawn_w, drawn_h = box[2] - box[0] + 1, box[3] - box[1] + 1
    if jaggies > JAGGY_SHARE * (drawn_w + drawn_h):
        out.append(f"{jaggies} jagged corners across a {drawn_w}x{drawn_h} shape: the "
                   "diagonals are stepping rather than running evenly.")
    conformance = metrics.get("palette_conformance")
    if conformance is not None and conformance < 1.0:
        out.append(f"{1 - conformance:.0%} of the drawn pixels are off the declared ramp. "
                   "shift_along_ramp and gradient_map put pixels back on it; a brightness "
                   "or hue filter is what usually takes them off.")
    colours = metrics.get("colors", 0)
    ramps = metrics.get("ramps", 0)
    if ramps and colours > ramps * 8:
        out.append(f"{colours} colours across about {ramps} ramps, which is more than a "
                   "pixel-art palette usually carries.")
    asymmetry = metrics.get("silhouette_asymmetry", 0)
    # Against the painted pixels, not the box: a small sprite with a few stray dots has a
    # large box and is not nearly anything.
    drawn = metrics.get("drawn_pixels", drawn_w * drawn_h)
    if 0 < asymmetry <= NEARLY_SYMMETRIC * drawn:
        out.append(f"Nearly symmetric, but {asymmetry} pixels differ from their horizontal "
                   "mirror. If that was meant to be symmetric, mirror_layer fixes it.")
    return out
