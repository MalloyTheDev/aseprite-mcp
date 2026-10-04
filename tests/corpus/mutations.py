"""Seeded defects: a labelled negative set built by breaking art that was already good.

Hand-labelling hundreds of sprites is not available and is not needed. Take art that is
known good and damage it one defect at a time, and every negative has ground truth by
construction: the label is not a judgement about the result, it is a record of what was
done to it. Ten good sprites times a dozen mutations is a corpus, and the sensitivity it
measures is sensitivity to *that* defect, which is the only kind worth quoting.

Two rules make the labels trustworthy, and both are load-bearing:

**A mutator that changes nothing returns None, and the caller drops it.** `weld_masses` on
a sprite with no gaps, or `collapse_ramp_step` on a two-colour sprite, produces a pixel-
identical copy. Keeping those as negatives would label clean art as defective, which is
the one error a corpus built this way can still make, and it would show up as an
unfixable false-negative rate in every measure at once.

**A mutator seeds one defect and not two.** Several of these decline cases exist only to
hold that line: `offset_lower_half` refuses a shift that would push pixels off the canvas,
because that is a clipping defect and clipping has its own mutator and its own measure. A
negative labelled "offset by 4" that is also clipped tells you nothing about which of the
two a measure noticed.

Detection is judged against the *parent*, never against zero. A measure already firing on
the clean original cannot be credited with noticing the damage: `isolated_pixels` reads 701
on the clean dungeon scene, because dithering is isolated pixels, so it fires on every
mutant of that scene and has detected none of them.
"""

from __future__ import annotations

import colorsys
import random
from typing import NamedTuple

from aseprite_mcp.core import quality

Grid = list[list[str]]

TRANSPARENT = "#00000000"

# Defect names. These are what a measure's claim is checked against, so they are nouns
# describing what was done to the art and never names of measures.
OFFSET = "lower half offset"
WELD = "masses welded"
COLLAPSE = "ramp step collapsed"
KEYLINE = "darkest tone replaced by a mid tone"
STRAYS = "stray single pixels"
CLIP = "figure clipped by the canvas edge"
DESATURATE = "ramp midpoint desaturated toward grey"
LIGHTFLIP = "one region lit from the other side"


class Mutant(NamedTuple):
    """One seeded defect, with the provenance needed to read a result."""

    label: str
    defect: str
    severity: float
    parent: str
    grid: Grid


def _alpha(color: str) -> int:
    body = color.lstrip("#")
    return int(body[6:8], 16) if len(body) >= 8 else 255


def _opaque(color: str) -> bool:
    return _alpha(color) > 0


def _rgb(color: str) -> tuple[int, int, int]:
    body = color.lstrip("#")
    return (int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16))


def _hex(rgb: tuple[int, int, int], alpha: int = 255) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}{alpha:02x}"


def copy(grid: Grid) -> Grid:
    return [list(row) for row in grid]


def size(grid: Grid) -> tuple[int, int]:
    height = len(grid)
    return (len(grid[0]) if height else 0, height)


def bbox(grid: Grid) -> tuple[int, int, int, int] | None:
    """The box around the opaque pixels, as (x0, y0, x1, y1)."""
    xs, ys = [], []
    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            if _opaque(color):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def ramp_of(grid: Grid) -> list[str]:
    """The sprite's opaque colours, darkest first.

    Ordered by `quality.luminance` and not by HLS lightness, for the reason that function
    documents: HLS reports 0.5 for both pure yellow and pure blue, so an HLS ordering can
    put the brightest pixel in the picture at the dark end of the ramp, and a mutator that
    replaced "the darkest tone" would then replace a highlight.
    """
    colors = {color for row in grid for color in row if _opaque(color)}
    return sorted(colors, key=lambda c: quality.luminance((*_rgb(c), 255)))


# ------------------------------------------------------------------ seeded defects


def offset_lower_half(grid: Grid, dx: int) -> Grid | None:
    """Shift everything below the figure's vertical midpoint sideways by `dx` pixels.

    The classic misalignment: legs that do not sit under the body. Declines when the shift
    would push drawn pixels off the canvas, because that is clipping and clipping is a
    separate defect with a separate measure.
    """
    box = bbox(grid)
    if box is None or dx == 0:
        return None
    _x0, y0, _x1, y1 = box
    width, _height = size(grid)
    middle = (y0 + y1) // 2
    lower = [(x, y) for y in range(middle + 1, y1 + 1) for x in range(width) if _opaque(grid[y][x])]
    if not lower:
        return None
    if any(not 0 <= x + dx < width for x, _y in lower):
        return None
    out = copy(grid)
    for x, y in lower:
        out[y][x] = TRANSPARENT
    for x, y in lower:
        out[y][x + dx] = grid[y][x]
    return out if out != grid else None


def weld_masses(grid: Grid, max_gap: int) -> Grid | None:
    """Fill the background gaps between separate masses, up to `max_gap` wide, on both axes.

    This is the defect that produced this project's own first golem: limbs fused into one
    slab. Filled with the colour on the near side of the gap, so the mutation adds no colour
    the sprite did not already have and cannot be detected as a palette change instead.

    Both axes, because one axis is not enough on this art. Scanning rows alone finds gaps in
    exactly two of the twelve known-good sprites: the reference orb is convex, the dungeon
    and the attack panels are full-bleed, and the items are drawn with their masses stacked,
    so the background between their parts runs vertically. A row-only mutator would have
    declined almost everywhere and the measure would have looked untestable when it was
    merely being asked the wrong way round.

    Gaps open to the bounding box's edge are left alone. Those are concavities rather than
    gaps between masses: filling the notch under an item's handle makes the shape convex,
    which is a different defect from fusing two parts that were apart.
    """
    width, height = size(grid)
    out = copy(grid)
    changed = False

    def fill_line(cells: list[tuple[int, int]]) -> None:
        nonlocal changed
        start: int | None = None
        seen = False
        for index, (x, y) in enumerate(cells):
            if _opaque(grid[y][x]):
                if start is not None and seen and index - start <= max_gap:
                    source = cells[start - 1]
                    for gap in range(start, index):
                        gx, gy = cells[gap]
                        out[gy][gx] = grid[source[1]][source[0]]
                    changed = True
                start = None
                seen = True
            elif start is None:
                start = index
        return None

    for y in range(height):
        fill_line([(x, y) for x in range(width)])
    for x in range(width):
        fill_line([(x, y) for y in range(height)])
    return out if changed else None


def collapse_ramp_step(grid: Grid, index: int) -> Grid | None:
    """Repaint ramp step `index` with the step above it, so two values become one.

    A ramp that loses a step loses the gradient between the two it joined, which is what
    makes a rounded surface read as flat. It also *lowers* the colour count, so any reading
    that watches for colours appearing cannot see it even in principle.
    """
    ramp = ramp_of(grid)
    if len(ramp) < 3 or not 0 <= index < len(ramp) - 1:
        return None
    victim, survivor = ramp[index], ramp[index + 1]
    out = [[survivor if color == victim else color for color in row] for row in grid]
    return out if out != grid else None


def darkest_to_mid(grid: Grid) -> Grid | None:
    """Repaint the darkest tone with the ramp's middle tone, which removes the keyline.

    The separator is what keeps a silhouette from dissolving on a light background, so this
    is a defect even though it changes no shape at all and leaves the colour count one
    lower rather than higher.
    """
    ramp = ramp_of(grid)
    if len(ramp) < 3:
        return None
    victim, survivor = ramp[0], ramp[len(ramp) // 2]
    if victim == survivor:
        return None
    out = [[survivor if color == victim else color for color in row] for row in grid]
    return out if out != grid else None


def add_strays(grid: Grid, count: int, seed: int = 0) -> Grid | None:
    """Scatter `count` lone pixels around the figure, each with no neighbour of its colour.

    Placed so that `quality.isolated_pixels` must count every one of them: a candidate site
    is transparent, and none of its four orthogonal neighbours already holds the colour
    being painted, and no later stray is placed orthogonally adjacent to an earlier one.
    Without that last condition two strays side by side are neighbours of the same colour
    and the metric correctly counts neither, so the mutation would seed `count` pixels and
    `count - 2` defects.

    The canvas border is excluded, and that exclusion is what keeps the label honest rather
    than being tidiness. Four of the twelve good sprites are background-plated panels whose
    only transparent cells are the top and bottom rows of the canvas, so an unrestricted
    scatter put every stray on the border and seeded `edge_contact` at the same time. The
    mutant was then labelled "stray pixels" while carrying two defects, and either measure
    firing would have been scored as a detection of the other. Those sprites now decline the
    defect instead, which is the truth: there is nowhere in them to put a lone pixel.
    """
    box = bbox(grid)
    if box is None or count <= 0:
        return None
    ramp = ramp_of(grid)
    if not ramp:
        return None
    paint = ramp[-1]
    width, height = size(grid)
    x0, y0, x1, y1 = box
    margin = 2
    sites = [
        (x, y)
        for y in range(max(1, y0 - margin), min(height - 1, y1 + margin + 1))
        for x in range(max(1, x0 - margin), min(width - 1, x1 + margin + 1))
        if not _opaque(grid[y][x])
    ]
    random.Random(seed).shuffle(sites)
    out = copy(grid)
    placed = 0
    for x, y in sites:
        if placed == count:
            break
        neighbours = [
            out[y + dy][x + dx]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= x + dx < width and 0 <= y + dy < height
        ]
        if paint in neighbours:
            continue
        out[y][x] = paint
        placed += 1
    return out if placed == count else None


def clip_to_edge(grid: Grid, lost: int) -> Grid | None:
    """Slide the figure left until `lost` columns of it fall off the canvas.

    Both halves of the defect at once, and deliberately: the silhouette is cut, and what
    remains sits on the border where it cannot take an outline. That is what happens when a
    part is placed at a negative coordinate, which is how this repository's own figure
    acquired eighteen border pixels.
    """
    box = bbox(grid)
    if box is None or lost <= 0:
        return None
    x0, _y0, x1, _y1 = box
    if x1 - x0 + 1 <= lost:
        return None
    width, height = size(grid)
    shift = x0 + lost
    out = [[TRANSPARENT] * width for _ in range(height)]
    dropped = False
    for y in range(height):
        for x in range(width):
            if not _opaque(grid[y][x]):
                continue
            target = x - shift
            if target < 0:
                dropped = True
            else:
                out[y][target] = grid[y][x]
    if not dropped or bbox(out) is None:
        return None
    return out


def desaturate_midpoint(grid: Grid, amount: float) -> Grid | None:
    """Pull the ramp's middle tone toward grey by `amount`, from 0 (none) to 1 (neutral).

    The midpoint and not an endpoint, for the reason `quality.ramp_chroma` gives: a
    hand-built ramp desaturates both ends on purpose, so damage there is indistinguishable
    from correct practice. The middle is where most of a sprite's pixels live, and a ramp
    that is grey in the middle reads as a value ramp whatever its endpoints claim.

    Declines when the new colour collides with one the sprite already uses, which would
    collapse a step as well as desaturate it and make the label a lie.
    """
    ramp = ramp_of(grid)
    pair = _faded_midpoint(ramp, amount)
    if pair is None:
        return None
    victim, replacement = pair
    out = [[replacement if color == victim else color for color in row] for row in grid]
    return out if out != grid else None


def _faded_midpoint(ramp: list[str], amount: float) -> tuple[str, str] | None:
    """The ramp's middle colour and its desaturated replacement, or None if that is a no-op.

    Shared by the sprite mutator above and `desaturate_ramp` below, so the palette corpus
    and the pixel corpus are damaged in exactly the same way and a difference in what a
    measure sees cannot be a difference in what was done to it.
    """
    if len(ramp) < 3 or not 0.0 < amount <= 1.0:
        return None
    victim = ramp[len(ramp) // 2]
    r, g, b = (v / 255 for v in _rgb(victim))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    faded = colorsys.hls_to_rgb(hue, lightness, saturation * (1.0 - amount))
    replacement = _hex(tuple(round(v * 255) for v in faded))  # type: ignore[arg-type]
    if replacement == victim or replacement in ramp:
        return None
    return (victim, replacement)


def desaturate_ramp(ramp: list[str], amount: float) -> list[str] | None:
    """The same midpoint damage applied to a declared palette rather than to pixels.

    `quality.ramp_chroma` reads a palette and never sees the art, so the only way to put
    that measure in front of this defect is to damage the palette itself.
    """
    pair = _faded_midpoint(ramp, amount)
    if pair is None:
        return None
    victim, replacement = pair
    return [replacement if color == victim else color for color in ramp]


def flip_light(grid: Grid) -> Grid | None:
    """Reverse the order of the colours along each row of the figure's upper half.

    The silhouette is untouched: each row keeps exactly the pixels it had, and only the
    values move, so what changes is which side the light appears to come from. Mirroring the
    region instead would move the shape as well, and a measure that noticed would have
    noticed the shape.
    """
    box = bbox(grid)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    middle = (y0 + y1) // 2
    out = copy(grid)
    changed = False
    for y in range(y0, middle + 1):
        xs = [x for x in range(x0, x1 + 1) if _opaque(grid[y][x])]
        if len(xs) < 2:
            continue
        colors = [grid[y][x] for x in xs]
        for x, color in zip(xs, reversed(colors), strict=True):
            if out[y][x] != color:
                changed = True
            out[y][x] = color
    return out if changed else None


# -------------------------------------------------- label-preserving transforms


def mirror(grid: Grid) -> Grid:
    """Flip horizontally. Good art stays good art, which is what makes it a relation."""
    return [list(reversed(row)) for row in grid]


def translate(grid: Grid, dx: int, dy: int) -> Grid | None:
    """Move the whole drawing within its canvas, or None when that would clip it.

    None rather than a clipped result on purpose: a translation that loses pixels is not a
    translation, and a shape metric is entitled to change when the shape does.
    """
    box = bbox(grid)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    width, height = size(grid)
    if not (x0 + dx >= 0 and x1 + dx < width and y0 + dy >= 0 and y1 + dy < height):
        return None
    out = [[TRANSPARENT] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if _opaque(grid[y][x]):
                out[y + dy][x + dx] = grid[y][x]
    return out


def repair_strays(grid: Grid) -> Grid:
    """Erase every pixel with no orthogonal neighbour of its own colour.

    The inverse of `add_strays`, and deliberately the same definition `quality`'s
    `isolated_pixels` counts, so the repair and the measurement cannot disagree about what
    was repaired. One pass is not a fixed point: erasing a stray can orphan the pixel that
    was keeping another one company, which is why idempotence is worth asserting rather
    than assuming.
    """
    width, height = size(grid)
    out = copy(grid)
    for y in range(height):
        for x in range(width):
            color = grid[y][x]
            if not _opaque(color):
                continue
            kin = any(
                0 <= x + dx < width and 0 <= y + dy < height and grid[y + dy][x + dx] == color
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            if not kin:
                out[y][x] = TRANSPARENT
    return out


# ------------------------------------------------------------------- the plan

# One entry per (defect, severity). The severities are the ones the brief for this harness
# names, and they are a ladder rather than a sample: the point of offsetting by 1, 2, 3 and
# 4 is that a measure claiming to see misalignment has to rank them in that order, which is
# the monotonicity relation, and a single severity could not test it.
PLAN: tuple[tuple[str, float, str], ...] = (
    (OFFSET, 1, "offset_1"),
    (OFFSET, 2, "offset_2"),
    (OFFSET, 3, "offset_3"),
    (OFFSET, 4, "offset_4"),
    (WELD, 2, "weld_2"),
    (WELD, 4, "weld_4"),
    (WELD, 8, "weld_8"),
    (COLLAPSE, 0, "collapse_0"),
    (COLLAPSE, 1, "collapse_1"),
    (KEYLINE, 1, "keyline"),
    (STRAYS, 5, "strays_5"),
    (STRAYS, 10, "strays_10"),
    (STRAYS, 20, "strays_20"),
    (CLIP, 2, "clip_2"),
    (CLIP, 4, "clip_4"),
    (DESATURATE, 0.5, "desat_50"),
    (DESATURATE, 1.0, "desat_100"),
    (LIGHTFLIP, 1, "lightflip"),
)


def apply_defect(grid: Grid, defect: str, severity: float) -> Grid | None:
    """Seed one defect at one severity, or None when this sprite cannot carry it."""
    if defect == OFFSET:
        return offset_lower_half(grid, int(severity))
    if defect == WELD:
        return weld_masses(grid, int(severity))
    if defect == COLLAPSE:
        return collapse_ramp_step(grid, int(severity))
    if defect == KEYLINE:
        return darkest_to_mid(grid)
    if defect == STRAYS:
        return add_strays(grid, int(severity))
    if defect == CLIP:
        return clip_to_edge(grid, int(severity))
    if defect == DESATURATE:
        return desaturate_midpoint(grid, severity)
    if defect == LIGHTFLIP:
        return flip_light(grid)
    raise ValueError(f"unknown defect {defect!r}")


def seed_defects(name: str, grid: Grid) -> list[Mutant]:
    """Every defect in `PLAN` that this sprite can actually carry, labelled."""
    out: list[Mutant] = []
    for defect, severity, suffix in PLAN:
        mutated = apply_defect(grid, defect, severity)
        if mutated is None:
            continue
        out.append(Mutant(f"{name}:{suffix}", defect, severity, name, mutated))
    return out
