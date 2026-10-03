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
# A silhouette: one boolean per pixel, True where something is drawn.
Mask = list[list[bool]]

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

    Orthogonal on purpose: a checkerboard dither is diagonally connected and nothing
    else, so counting diagonals would score a dithered band as clean. `remove_stray_pixels`
    takes the opposite view for the same reason, replacing only pixels with no neighbour
    of their colour in any of the eight directions, so it cannot eat a dither.
    """
    lookup = {(x, y): px for x, y, px in _opaque_cells(grid)}
    count = 0
    for (x, y), px in lookup.items():
        if not any(lookup.get((x + dx, y + dy)) == px
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            count += 1
    return count


def opacity_mask(grid: Grid) -> Mask:
    """The silhouette as rows of booleans, which is all the shape metrics actually read.

    Separated out because `core.edges` plans a change to a silhouette and has to score the
    silhouette it is planning, and the alternative was a second transcription of the
    window test below. A metric with two definitions is a metric that drifts, and the one
    here is the one `assess_sprite` reports.
    """
    return [[_rgba(px)[3] > 0 for px in row] for row in grid]


def jaggy_corners_in_mask(mask: Mask) -> int:
    """`jaggy_corners`, counted on a silhouette rather than on colours."""
    height = len(mask)
    width = len(mask[0]) if height else 0
    return sum(
        1
        for y in range(height - 1)
        for x in range(width - 1)
        if mask[y][x] + mask[y][x + 1] + mask[y + 1][x] + mask[y + 1][x + 1] == 3
    )


def jaggy_corners(grid: Grid) -> int:
    """Staircase corners in the silhouette.

    Counts 2x2 windows where exactly three cells are opaque, which is the shape a
    single-pixel step makes. It is what Aseprite's own pixel-perfect mode exists to
    avoid. Curves legitimately produce some, so compare rather than aim for zero.

    A step of two pixels scores the same as a step of one, which is worth knowing before
    reading the number as a quality score: on a staircase that only ever goes one way the
    count is exactly the number of steps, whatever their size. That is the property
    `normalize_edge_runs` works against, and it is why merging a stray one-row run into
    its neighbour lowers this by one.
    """
    return jaggy_corners_in_mask(opacity_mask(grid))


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


# A row that is one unbroken run this wide, as a share of the drawn width, is a row with
# no air in it. Measured against reference art: a creature that reads has limbs separated
# by background on most of its rows, and the sprite that failed this review had six rows
# of forty with three or more separate runs and one row that was a single run spanning the
# whole canvas.
WELDED_ROW_SHARE = 0.70
# A figure wants air on more rows than not. Below this, the masses have fused.
OPEN_ROW_SHARE = 0.25
# And separately: this share of rows being a single wide run is a slab even if other rows
# do have gaps. Calibrated on the figure that failed, which ran 42 percent (16 of its 38
# drawn rows), against 37 percent of its rows that did have a gap somewhere.
WELDED_ROWS_SHARE = 0.30
# How many pixels a narrowing has to lose before it counts as a waist rather than as the
# stair-stepping of a curve. An ellipse's rows change width by a pixel at a time near its
# poles, so one pixel of dip is a circle and two is a neck.
WAIST_MIN_DEPTH = 2
# Above this share of the canvas actually painted, the art has no silhouette to judge: it
# is a scene or a full-bleed tile, and "the masses have fused" is true and meaningless. The
# first version of these readings fired on a lava cavern, correctly measuring that all 64
# of its rows were one run, which is what a cavern is.
#
# It is the *opaque* share and not `canvas_usage`, which measures the bounding box. Gating
# on the box suppressed the readings for a figure whose box filled its canvas, which is to
# say for exactly the figure that was clipped by it: the symptom hid the diagnosis. A scene
# is distinguished by having no transparency anywhere, not by being large.
SILHOUETTE_MAX_OPAQUE = 0.98
# And these readings are about *form*, so they are only given to art that is attempting
# form. A flat one-colour test shape is genuinely one unbroken run with one tone and no
# keyline, and all three statements are true and useless: telling a square to separate its
# limbs is not advice. Three tones is the floor at which something is being shaded.
SHADED_MIN_COLORS = 3
# There is deliberately no threshold here on the share of the drawn pixels taken by the
# most-used colour, although `tone_shares` measures it. The reading this module first
# shipped with fired above 40 percent, on the stated grounds that "the mass that failed
# ran 61". Measured against the two sprites afterwards, that does not hold: the clean,
# well-shaded reference orb runs 51 percent on its midtone, because a five-step ramp on a
# sphere has to, and the figure the reading was written for runs 19. So the threshold
# caught the good sprite and missed the bad one, in the wrong direction and by a wide
# margin.
#
# Dominance relative to an even split across the tones in use was the obvious repair, and
# it fails the same way: 2.0 for the orb against 1.8 for the figure. The measurement is
# kept because it is worth reporting, and the reading is not, because a number that
# cannot tell these two sprites apart has nothing to say about a third.
#
# What share of a sprite the darkest colour occupies in this style. Reference art runs
# about 18 percent; the sprite that failed ran 7.6, and its "outline" was two ramp steps
# down rather than near-black, so the silhouette dissolved on a light background.
SEPARATOR_BAND = (0.10, 0.24)
# Saturation below which a hue is no longer visible, so a ramp that passes through it is a
# value ramp whatever its endpoints say. The ramp that failed fell to 2.4 percent at its
# midtone while rotating 227 degrees end to end, and read as eight greys.
HUE_INVISIBLE_SAT = 0.10


def _waists(widths: list[int], min_depth: int = WAIST_MIN_DEPTH) -> int:
    """How many times the silhouette narrows and then widens again.

    A single convex mass widens once and narrows once: one bulge and no waist. A figure
    built from stacked masses has at least one, because a neck, a waist, or the gap above
    a pair of legs is a narrowing with more shape below it.

    This is the measurement that separates "this is a ball" from "this is a creature
    whose parts have fused", and without it the welding reading fires on every circle: a
    disc genuinely is one unbroken run on every row, which is what a disc is. It also
    catches the case counting gaps cannot, a figure welded so completely that no row has
    any background in it at all, which is what the first draft of this project's own
    golem was.
    """
    waists = 0
    peak = 0            # the widest row since the last waist
    trough: int | None = None   # the narrowest row since that peak, once falling
    for width in widths:
        if trough is None:
            if width >= peak:
                peak = width
            elif peak - width >= min_depth:
                trough = width
        elif width < trough:
            trough = width
        elif width - trough >= min_depth:
            waists += 1
            peak, trough = width, None
    return waists


def row_structure(grid: Grid) -> dict:
    """How the silhouette breaks up, row by row.

    A creature reads because background cuts between its limbs. This counts the separate
    opaque runs on each row, because that is the thing a human sees instantly and that no
    other measurement here notices: a figure can have a perfect bounding box, a sensible
    colour count and no stray pixels while being one welded slab.

    `waists` is reported alongside, because the run counts alone cannot tell an
    articulated figure from a convex one and the readings need to know which they are
    looking at.
    """
    box = bounding_box(grid)
    if box is None:
        return {"rows_drawn": 0, "rows_with_air": 0, "welded_rows": 0, "widest_run": 0,
                "waists": 0}
    rows_drawn = welded = with_air = 0
    widest = 0
    widths: list[int] = []
    for row in grid[box.y0:box.y1 + 1]:
        runs = []
        run = 0
        for color in row[box.x0:box.x1 + 1]:
            if _rgba(color)[3] > 0:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        if run:
            runs.append(run)
        if not runs:
            continue
        rows_drawn += 1
        widest = max(widest, max(runs))
        # The drawn mass on this row rather than its widest run: a row crossing both
        # arms and the torso is wide because of all three, and it is that profile which
        # dips at the waist.
        widths.append(sum(runs))
        if len(runs) >= 2:
            with_air += 1
        if max(runs) >= box.width * WELDED_ROW_SHARE:
            welded += 1
    return {
        "rows_drawn": rows_drawn,
        "rows_with_air": with_air,
        "welded_rows": welded,
        "widest_run": widest,
        "waists": _waists(widths),
    }


def edge_contact(grid: Grid) -> int:
    """Drawn pixels sitting on the canvas border, where a silhouette gets cut off.

    A figure touching the edge cannot take an outline there, so its silhouette dissolves
    on exactly the side that touches. Cheap to measure and easy to miss: the sprite that
    failed this review had eighteen such pixels because one of its parts was placed at a
    negative coordinate and was quietly clipped.
    """
    if not grid or not grid[0]:
        return 0
    height, width = len(grid), len(grid[0])
    count = 0
    for y in range(height):
        for x in range(width):
            if (y in (0, height - 1) or x in (0, width - 1)) and _rgba(grid[y][x])[3] > 0:
                count += 1
    return count


def tone_shares(grid: Grid) -> dict:
    """The most-used drawn colour and what share of the drawing it covers.

    One tone over a large share of a mass means the surface has no form: the light is not
    describing anything, it is filling. Reported with the colour so the reading can name
    it.
    """
    cells = _opaque_cells(grid)
    if not cells:
        return {"top_color": None, "top_share": 0.0, "tones": 0}
    counts: dict[tuple[int, int, int, int], int] = {}
    for _, _, px in cells:
        counts[px] = counts.get(px, 0) + 1
    px, n = max(counts.items(), key=lambda kv: kv[1])
    return {
        "top_color": f"#{px[0]:02x}{px[1]:02x}{px[2]:02x}",
        "top_share": round(n / len(cells), 3),
        "tones": len(counts),
    }


def separator_share(grid: Grid) -> dict:
    """What share of the drawing is its darkest colour, and how dark that is.

    In this style the dark separator is structural rather than a fallback: it is what
    makes a mass countable and keeps a silhouette from dissolving. Reference art spends
    roughly a fifth of a sprite on it, near black. A sprite whose darkest colour is a
    couple of ramp steps down and covers under a tenth has no keyline.
    """
    cells = _opaque_cells(grid)
    if not cells:
        return {"separator": None, "share": 0.0, "lightness": 0.0}
    def light(px):
        r, g, b, _ = px
        return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[1]
    darkest = min((px for _, _, px in cells), key=light)
    n = sum(1 for _, _, px in cells if px == darkest)
    return {
        "separator": f"#{darkest[0]:02x}{darkest[1]:02x}{darkest[2]:02x}",
        "share": round(n / len(cells), 3),
        "lightness": round(light(darkest), 3),
    }


def ramp_chroma(ramp: list[str]) -> dict:
    """Whether a ramp's hue rotation is visible, or whether it passes through grey.

    A ramp can rotate hue a long way and show none of it. Interpolating between two
    endpoints on opposite sides of the wheel routes straight through the neutral axis, and
    the midpoint of that path is by definition grey: the ramp this was written for
    rotated 227 degrees end to end and fell to 2.4 percent saturation in the middle, so it
    rendered as eight greys. The number that matters is therefore not the hue span but the
    saturation floor, and both are reported so the two cannot be confused again.

    The saturation figures cover the ramp's interior, not its ends, whenever it is long
    enough to have an interior. A hand-built ramp desaturates both endpoints on purpose:
    the highlight washes out toward the light and the deepest shadow toward ambient, which
    is exactly what `sat_curve="peak"` is for. Counting those two steps against a ramp
    would mark correct practice as a defect. What cannot be grey is the middle, because
    that is where most of a sprite's pixels live.
    """
    if not ramp:
        return {"hue_span": 0.0, "sat_floor": 0.0, "grey_steps": 0}
    hues, sats = [], []
    for color in ramp:
        r, g, b, _ = _rgba(color)
        h, _l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        hues.append(h * 360)
        sats.append(s)
    span = 0.0
    for a, b in itertools.combinations(hues, 2):
        gap = abs(a - b) % 360
        span = max(span, min(gap, 360 - gap))
    # Four is the shortest ramp that still has two steps left after dropping its ends. A
    # three-step ramp is shadow, midtone, light, and dropping the ends would leave the
    # measurement resting on a single colour.
    body = sats[1:-1] if len(sats) >= 4 else sats
    return {
        "hue_span": round(span, 1),
        "sat_floor": round(min(body), 3),
        "grey_steps": sum(1 for s in body if s < HUE_INVISIBLE_SAT),
    }


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
        # The five below were added after a review found that every existing metric here
        # passed on a figure that read as one welded slab: it had a sensible colour count,
        # no stray pixels, a reasonable bounding box and no form at all.
        "row_structure": row_structure(grid),
        "edge_contact": edge_contact(grid),
        "tone_shares": tone_shares(grid),
        "separator": separator_share(grid),
    }
    if ramp:
        result["palette_conformance"] = round(palette_conformance(grid, ramp), 3)
        result["ramp_chroma"] = ramp_chroma(ramp)
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
    # The two silhouette readings below only mean something for art that has a
    # silhouette. A scene fills its canvas on purpose.
    cells = max(1, width * height)
    has_silhouette = (metrics.get("drawn_pixels", 0) / cells < SILHOUETTE_MAX_OPAQUE
                      and metrics.get("colors", 0) >= SHADED_MIN_COLORS)
    rows = metrics.get("row_structure") or {}
    drawn_rows = rows.get("rows_drawn", 0)
    # Both readings below are about how well several masses are told apart, so they are
    # only given to a shape that has several. A disc has no limbs to separate and no
    # keyline to be missing: it is one convex form, every row of it is correctly one
    # unbroken run, and saying so measures a circle for being circular. The first version
    # of these readings said exactly that about this project's own reference orb, which is
    # some of the cleanest art in the repository.
    #
    # Evidence of more than one mass is either a row with background between two parts, or
    # a waist: a narrowing with more shape below it. The second matters on its own, because
    # the worst case for the welding reading is the figure so completely fused that no row
    # has any gap at all, and counting gaps alone would let exactly that one through.
    articulated = rows.get("rows_with_air", 0) > 0 or rows.get("waists", 0) > 0
    if has_silhouette and articulated and drawn_rows:
        air = rows.get("rows_with_air", 0) / drawn_rows
        welded = rows.get("welded_rows", 0) / drawn_rows
        # Either condition on its own is enough, and the second is why: the figure this
        # was calibrated against had air on 37% of its rows, which passed the first test,
        # while 42% of its rows were a single run and one of them spanned the whole
        # canvas. A figure can have gaps in places and still be a slab where it counts.
        if air < OPEN_ROW_SHARE or welded > WELDED_ROWS_SHARE:
            out.append(
                f"{rows['welded_rows']} of {drawn_rows} drawn rows are a single unbroken "
                f"run across most of the width, the widest spanning {rows['widest_run']}px, "
                f"and only {rows['rows_with_air']} have background between two parts of "
                "the silhouette. The masses have fused, so the shape reads as one object "
                "however well it is shaded: separate the limbs by two or three pixels of "
                "background before shading anything."
            )
    contact = metrics.get("edge_contact", 0)
    if has_silhouette and contact:
        out.append(
            f"{contact} drawn pixel(s) sit on the canvas border, so the silhouette is cut "
            "off there and cannot take an outline. resize_canvas, or move the art inward."
        )
    # Likewise the keyline: a scene has no outline to be missing, and nor has a single
    # convex mass, so this takes the same gate as the welding reading above.
    sep = metrics.get("separator") or {} if has_silhouette and articulated else {}
    if sep.get("separator"):
        low, high = SEPARATOR_BAND
        if sep["share"] < low:
            out.append(
                f"The darkest colour {sep['separator']} is {sep['share']:.0%} of the "
                f"drawing, against the {low:.0%} to {high:.0%} that work in this style "
                "spends on separating its masses. A thin or absent keyline is what makes "
                "a silhouette dissolve on a light background. add_outline, or outline_smart."
            )
        elif sep["share"] > high * 2:
            # The other direction, which this reading shipped without and which cost it a
            # real defect: a figure in this gallery spends 50.3 percent of its drawn pixels
            # on a near-black outline, and passed silently because the band was only ever
            # checked from below. An outline carrying half a sprite is not separating
            # masses, it is replacing them, and the form then has to be read entirely from
            # a keyline. Twice the top of the band rather than the top itself, because the
            # band describes what is usual and this has to describe what is wrong.
            out.append(
                f"The darkest colour {sep['separator']} is {sep['share']:.0%} of the "
                f"drawing, well past the {high:.0%} that work in this style spends on "
                "separating its masses. An outline that heavy is doing the drawing: the "
                "interior has no values left to describe form with. Thin it to one pixel "
                "with add_outline, or spend the difference on mid tones."
            )
        elif sep["lightness"] > 0.25 and sep["share"] > low:
            out.append(
                f"The darkest colour {sep['separator']} has lightness "
                f"{sep['lightness']:.0%}, so what is doing the separating is a mid tone. "
                "A separator needs to be near black to read as one."
            )
    chroma = metrics.get("ramp_chroma") or {}
    if chroma and chroma.get("grey_steps"):
        out.append(
            f"The declared ramp rotates {chroma['hue_span']:.0f} degrees of hue but falls "
            f"to {chroma['sat_floor']:.0%} saturation, with {chroma['grey_steps']} step(s) "
            "below the level where hue is visible at all. Interpolating between endpoints "
            "on opposite sides of the colour wheel routes through the neutral axis, and "
            "the middle of that path is grey: generate_ramp with shadow_hue, light_hue and "
            "sat_curve=\"peak\" holds the chroma instead."
        )

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
