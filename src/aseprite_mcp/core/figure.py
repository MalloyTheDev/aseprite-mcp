"""Structural measurements for a drawn figure: is it built, or is it assembled wrong.

`core.quality` measures a sprite's surface (how many colours, how much canvas, whether a
shading pass stayed inside its ramp). This module measures its *construction*: whether the
parts of a figure line up, whether the silhouette is one body or several, whether anything
is rendered one pixel thick, and whether a standing figure's mass sits over its feet.

Everything here takes a `Mask` (or a `Grid`) and returns numbers. It touches neither
Aseprite nor the filesystem, and it imports only the standard library and
`core.quality`'s shared vocabulary, so it stays usable on a runner with no editor.

**The evidence standard this module is held to.** Each measurement below records, in its
own docstring, the result of four checks, because a structural measure is very easy to
write and very hard to justify:

1. *Construct.* One sentence on the defect, then an attempt to name a CORRECT sprite that
   produces the same number. The attempt succeeding is disqualifying, not interesting.
   This is not hypothetical: a predecessor of this module counted "jaggy corners", and a
   correct raster circle produces 36 of them at 32x32 and 72 at 64x64, so no threshold
   could separate craft from geometry.
2. *Ranking.* The measure is run on the project's reference sprites. If it puts a
   known-good sprite behind a known-bad one, it is discarded rather than inverted or
   re-tuned. One such inversion is recorded below, and the measure that caused it was
   dropped (see `keyline_boundary_share`, which is deliberately absent, and the note under
   `topology`).
3. *Specificity.* How many clean sprites it fires on, with the bound that supports it. n
   clean sprites and zero fires justifies a false-positive rate under z^2/(n + z^2), the
   Wilson 95 percent upper bound, which is 16 percent at n=20 and never zero. The
   reference set here is small, so the claims are correspondingly weak, and each is
   written out so it cannot be mistaken for a stronger one.
4. *Threshold honesty.* Every number in this file is tagged `SOURCED:` with a citation or
   `UNVALIDATED:` with the reason it was picked. There is exactly one SOURCED threshold.

**What this module deliberately does not contain**, because the research that motivated it
ruled each out: a combined score or weighted sum over the measures (it would let a
structural defect be paid for with a clean palette); Hu moments or any rotation- and
scale-invariant descriptor used as a defect test (they are invariant to precisely the
transformations that constitute "this part is in the wrong place"); watershed or
medial-axis part decomposition (documented as unstable to single-pixel boundary changes at
sprite resolution); and principal-axis angle as a single-frame defect test (a leaning
figure and a falling one share it).
"""

from __future__ import annotations

import math
from collections import deque
from typing import NamedTuple

from .errors import ValidationFailed
from .quality import BBox, Grid, Mask, opacity_mask

# ---------------------------------------------------------------------------- thresholds
#
# UNVALIDATED: a row carrying less than a quarter of the widest row's drawn mass is
# ignored by `centerline`. Chosen because the x-extent midpoint of a row crossing only a
# one-pixel antenna is the antenna's position, not the body's, and such a row can swing
# the centre line by half the sprite's width. A quarter is the figure the research used;
# nothing distinguishes it from a fifth or a third. What *is* measured: with no gate at
# all, `workspace/throw_frame.png` (a correct two-part throw pose) reads 10.00 and
# `workspace/golem.png` (the known-bad figure) reads 14.00, a 1.4x separation that no
# threshold survives. With the gate the same pair reads 0.00 and 4.50.
CENTERLINE_MASS_FLOOR = 0.25

# UNVALIDATED: readings at or below this cannot be distinguished from raster quantization
# of a smooth pose, so a caller should not treat them as evidence of anything. Derived by
# measurement rather than chosen, and the measurement has a hole in it that is stated here
# because it bounds every claim this measure can make:
#
#   * 672 figures posed on smooth sine centre lines (amplitude up to 4px, up to one
#     period, heights 32 to 92px): the reading was 0.0 or 1.0 in 95 percent of cases, and
#     never exceeded 2.0.
#   * 800 figures with silhouette detail added in runs of two or more rows, which is the
#     shape good pixel art puts it in and what this project's own `normalize_edge_runs`
#     enforces: never exceeded 2.5.
#   * 400 figures with ISOLATED single-row one-pixel spikes on their edges: reached 4.0.
#     The known-bad golem reads 4.50, so against a silhouette full of single-row spikes
#     this measure has no separation at all. Every clean reference sprite in this
#     repository reads exactly 0.00, so real art of this project's standard does not carry
#     that noise, but a sprite that does cannot be measured by this.
#
# A deliberate 3px offset of a figure's lower half reads 3.00, which puts the gap between
# "raster noise" and "misplaced part" at about half a pixel on well-formed silhouettes and
# at nothing on spiky ones. The constant is reported, never applied: this module returns
# magnitudes and row numbers, and the judgement stays with the caller.
CENTERLINE_RASTER_FLOOR = 2.5

# UNVALIDATED: a figure whose declared bands all centre within this many pixels of one
# column is reported as a rigid vertical stack. Derived from measured pixel offsets in a
# working pixel artist's posed figure: on a roughly 92px character the torso shears 2px at
# the groin and 3px at the chest, which scales to about 2px of chest-versus-hip lean at
# 64px and about 1px at 32px, so "all three within 1px" is below anything a posed figure
# produces. It is a floor on *observable* lean, not a defect threshold, and this module
# never reports a stack as an error: see `band_stacking`.
STACK_TOLERANCE_PX = 1.0

# UNVALIDATED: below this drawn height the stack observation is suppressed, because the
# lean it looks for is a 1-to-3px effect and a 32px sprite cannot carry it distinguishably
# from rounding. 48 is the figure the research used.
STACK_MIN_HEIGHT = 48

# SOURCED: Derek Yu's "chunky pixels" rule names one-pixel-thick rendering as the thing to
# avoid in a pixel-art design, and names arms, legs and branches as where beginners do it,
# prescribing thicker forms as the fix for stiff "cardboard" shapes. One pixel of erosion,
# taken with a 2x2 square so that the two-pixel form the rule prescribes survives it, is a
# direct transcription of that rule, and is the only hard pixel threshold in this file that
# comes from a named author rather than from sprites in this repository.
CHUNKY_EROSION = 1

# UNVALIDATED: the support band is the bottom 6 percent of a figure's drawn height. The
# research gives 5 to 8 percent and this is the middle of it; the band exists because the
# single lowest row of a drawn figure is often one toe or one pixel of shadow, which is
# not the footprint the figure stands on.
SUPPORT_BAND_FRACTION = 0.06

# UNVALIDATED, in that no published source names it, but measured here rather than picked:
# a contact run has to be at least this wide to count as ground contact. A single
# one-pixel-wide limb hanging to the floor widens a naive base from
# [9, 22] to [3, 22] and so makes the figure read as MORE stable (margin 6.50 rising to
# 6.68 on this project's own orb). A minimum row-mass gate does not fix it, because the
# limb barely changes the row's mass: with a quarter-mass gate the polluted base is still
# [3, 22]. Requiring runs wider than one pixel does fix it, and leaves the base at
# [9, 22]. See `test_figure.py::test_dangling_limb_does_not_widen_the_base`.
SUPPORT_MIN_CONTACT = 2

_NEIGHBOURS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ------------------------------------------------------------------- shared mask helpers
def _dims(mask: Mask) -> tuple[int, int]:
    height = len(mask)
    return (len(mask[0]) if height else 0), height


def _require_mask(mask: Mask) -> tuple[int, int]:
    width, height = _dims(mask)
    if height and any(len(row) != width for row in mask):
        raise ValidationFailed("mask rows have different lengths; it is not rectangular.")
    return width, height


def _runs(row: list[bool]) -> list[tuple[int, int]]:
    """The inclusive [start, end] spans of consecutive True cells in one row."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for x, filled in enumerate(row):
        if filled and start is None:
            start = x
        elif not filled and start is not None:
            out.append((start, x - 1))
            start = None
    if start is not None:
        out.append((start, len(row) - 1))
    return out


def _drawn_rows(mask: Mask) -> list[int]:
    return [y for y, row in enumerate(mask) if any(row)]


def _centroid_x(mask: Mask, y0: int | None = None, y1: int | None = None) -> tuple[float | None, int]:
    """Mass centroid of the drawn pixels in rows y0..y1 inclusive, and how many there are."""
    total = 0
    count = 0
    for y, row in enumerate(mask):
        if y0 is not None and not (y0 <= y <= y1):  # type: ignore[operator]
            continue
        for x, filled in enumerate(row):
            if filled:
                total += x
                count += 1
    return (total / count if count else None), count


# ------------------------------------------------------- 1. centre-line second difference
class CenterlineBreak(NamedTuple):
    """One row where the centre line bends, with the evidence for what bent it."""

    y: int
    value: float
    center_above: float
    center_at: float
    center_below: float
    x_extent: tuple[int, int]
    runs: int


class CenterlineReading(NamedTuple):
    peak: float
    normalized: float
    breaks: list[CenterlineBreak]
    rows_measured: int
    rows_gated_out: int
    naive_center_deviation: float


def centerline(
    mask: Mask,
    *,
    mass_floor: float = CENTERLINE_MASS_FLOOR,
    max_breaks: int = 8,
) -> CenterlineReading:
    """Is this figure's centre line continuous, or does a part jump sideways.

    For each drawn row, `c(y)` is the midpoint of the row's x-extent. The reading is
    `max |c(y+1) - 2c(y) + c(y-1)|` over rows whose drawn mass clears `mass_floor` of the
    widest row's, counted only where all three of y-1, y and y+1 clear it, so a gap in the
    kept rows cannot be read as a jump across it.

    **The insight four previous attempts missed: a misplaced part is a discontinuity, a
    deliberate lean is a smooth drift.** The magnitude of a part's offset cannot tell those
    apart, because a 6px lean and a 6px misplacement are the same offset. The smoothness
    can: a lean spreads its offset over every row, and a second difference sees only the
    rate of change of the rate of change.

    `naive_center_deviation` is `max |c(y) - mean(c)|`, the measure this one replaced, and
    it is returned alongside on purpose. On four synthetic figures (aligned, lower half
    offset 3px, smooth 6px lean, S-curve pose) this measure reads 0.00 / 3.00 / 1.00 / 1.00
    and the naive one reads 0.00 / 1.55 / 3.03 / 4.00: the naive measure ranks *both* good
    poses worse than the defect, which is exactly the failure that motivated the change.

    `breaks` carries the actionable part, the row numbers, each with the three centres that
    produced the value, the row's x-extent and its run count. They come back worst first,
    capped at `max_breaks`. UNVALIDATED: that cap defaults to 8 because a report longer
    than that is not read; it bounds the length of a list and never whether a row is in it,
    so it is not a detection threshold and no reading depends on it. The run count is there
    because of the limitation below: a break at a row whose run count changes may be a
    second subject entering the row rather than a part out of place.

    Gates:

    * **Construct: PASSED for one subject, FAILED for a composition.** Detects: a part of a
      figure is attached off the axis its neighbours establish. Raster discs (r=2..39),
      raster ellipses (441 shapes, semi-axes 3..23) and raster triangles all read 0.00 or
      0.50, so unlike a jaggy-corner count this one is not a function of resolution. But a
      correct sprite *can* produce a large reading: `workspace/zorder_f2.png`, a correct
      two-subject z-order demo in this repository, reads 8.00, higher than the known-bad
      golem, because a second mass entering a row moves that row's x-extent midpoint. No
      estimator fixes this (the per-row mass centroid reads 3.97 on the same file against
      3.59 on the golem, and a widest-run midpoint reads 11.50 against 32.50 because it
      jumps between a figure's two legs). The measure is therefore defined for ONE
      upright subject, a precondition it cannot verify. `topology` will separate subjects
      that do not touch; two that touch, as in that file, it cannot. A second correct-ish
      input with the same reading is a silhouette carrying isolated single-row spikes:
      two-pixel spikes on alternating sides of three consecutive rows read 4.00, the
      golem's own order of magnitude. See
      `test_figure.py::test_a_spiky_silhouette_reads_as_high_as_the_defect`.
    * **Ranking: FAILED absolutely, PASSED paired.** This replaces an earlier PASSED
      verdict that rested on five hand-picked files (orb 0.00, orb_3_full 0.00, dungeon
      0.00, `workspace/golem.png` 4.50 breaking at row 50 where the legs attach 1.5px
      right of the torso's axis, and `docs/assets/showcase/golem.png` 6.50 at row 58).
      Those readings still hold; the conclusion drawn from them did not survive a
      labelled set.

      Measured over `tests/corpus` (12 good sprites against the 22 "lower half offset"
      mutants) this reading has **14 discordant pairs**, so the hard gate in
      `validation.discordant_pairs` discards it: `good_item_3` reads 3.00 and
      `good_item_4` 1.50, while real offset mutants read as little as 1.00. AUC is 0.930.
      Normalising by width makes it worse (26 discordant pairs) and the naive measure
      sits between them (23). So no threshold on this number is a defect reading, and
      that is a statement about every variant of it, not about the one chosen here.

      Paired against its own parent, the same number inverts nowhere at all: of those 22
      mutants **18 score worse than the sprite they were damaged from, 4 tie, and 0 score
      better**. That is the use this measure has. It is a regression guard for one sprite
      across an edit, reported by `assess_sprite` as a number for exactly that purpose,
      and it is deliberately attached to no reading: a single sprite's value answers no
      question, because the good art in the corpus reaches 3.00 by being small.
    * **Specificity: 0 fires on 14 clean inputs** (3 orb stages, docs orb, dungeon,
      roundblock, facetblock, smear_bare, throw_frame and 5 raster discs), which supports
      "false-positive rate probably under 22 percent", and nothing stronger. With the
      479 synthetic convex shapes added it is 0 fires on 493, supporting "under 0.8
      percent" for convex geometry specifically.
    * **Thresholds:** `CENTERLINE_MASS_FLOOR` and `CENTERLINE_RASTER_FLOOR` above, both
      UNVALIDATED. This function applies the first and does not apply the second.

    Cannot detect: a part misplaced *along* the centre line (too high or too low), a part
    of the wrong size, a discontinuity that falls on a row the mass gate removed (a thin
    neck is the realistic case), or any defect in a figure that is not upright. Cannot
    distinguish: a misplaced part from a second subject entering a row, or from isolated
    single-row silhouette spikes.
    """
    _require_mask(mask)
    if not 0.0 <= mass_floor <= 1.0:
        raise ValidationFailed(f"mass_floor is {mass_floor}; it has to be between 0 and 1.")
    if max_breaks < 1:
        raise ValidationFailed(f"max_breaks is {max_breaks}; it has to be at least 1.")

    rows: dict[int, tuple[float, int, tuple[int, int], int]] = {}
    for y, row in enumerate(mask):
        spans = _runs(row)
        if not spans:
            continue
        extent = (spans[0][0], spans[-1][1])
        mass = sum(b - a + 1 for a, b in spans)
        rows[y] = ((extent[0] + extent[1]) / 2.0, mass, extent, len(spans))
    if not rows:
        return CenterlineReading(0.0, 0.0, [], 0, 0, 0.0)

    widest = max(mass for _, mass, _, _ in rows.values())
    kept = {y: v for y, v in rows.items() if v[1] >= mass_floor * widest}

    found: list[CenterlineBreak] = []
    for y in sorted(kept):
        if y - 1 not in kept or y + 1 not in kept:
            continue
        above, at, below = kept[y - 1][0], kept[y][0], kept[y + 1][0]
        value = abs(below - 2 * at + above)
        if value > 0:
            found.append(CenterlineBreak(y, value, above, at, below, kept[y][2], kept[y][3]))
    found.sort(key=lambda b: (-b.value, b.y))

    centers = [v[0] for v in kept.values()]
    mean = sum(centers) / len(centers)
    naive = max(abs(c - mean) for c in centers)

    peak = found[0].value if found else 0.0
    width = max(v[2][1] for v in rows.values()) - min(v[2][0] for v in rows.values()) + 1
    return CenterlineReading(
        peak=peak,
        normalized=peak / width if width else 0.0,
        breaks=found[:max_breaks],
        rows_measured=len(kept),
        rows_gated_out=len(rows) - len(kept),
        naive_center_deviation=naive,
    )


# ------------------------------------------------------------- 2. vertical-axis stacking
class BandCentroid(NamedTuple):
    name: str
    rows: tuple[int, int]
    centroid_x: float
    pixels: int


class StackReading(NamedTuple):
    bands: list[BandCentroid]
    spread: float
    stacked: bool
    drawn_height: int
    suppressed: str | None


def band_stacking(
    mask: Mask,
    bands: dict[str, tuple[int, int]],
    *,
    tolerance: float = STACK_TOLERANCE_PX,
    min_height: int = STACK_MIN_HEIGHT,
) -> StackReading:
    """Do the caller's declared bands all centre on one column: the stiffness signature.

    The caller declares the bands as `{name: (y0, y1)}` inclusive row ranges, because this
    module does not know where a head ends. Each band's mass centroid x is reported, along
    with `spread`, the largest difference between any two of them.

    **This is an observation and never an error, and the reference set is why.** On
    `workspace/orb_3_full.png`, the project's reference for clean art, three equal bands
    centre on 15.50, 15.50 and 15.50: spread 0.00, a perfect rigid stack, and correct,
    because the subject is a sphere. A statue, an icon, a front-facing idle and a symmetric
    creature all stack legitimately. A caller that turns `stacked` into a failure will fail
    its own best art.

    Gates:

    * **Construct: FAILED as a defect test, which is why it is reported as an observation.**
      Detects: a figure posed as a rigid vertical stack of parts rather than with a
      weight-bearing lean. Correct sprite with the same number: the orb above, spread 0.00.
      There is no repair for this, because the stack is not the defect; it is evidence
      about the pose that only the caller can interpret.
    * **Ranking: not applicable.** A measure that is not a defect test cannot invert, and
      asserting an ordering on it would be asserting that symmetry is bad. The reference
      numbers are recorded instead: orb 0.00, golem 1.52, skeleton 4.20 (bands declared by
      eye from the silhouettes; the declaration is the caller's and changes the number, and
      the orb's 0.00 is suppressed in the returned reading anyway because it is only 26px
      tall).
    * **Specificity: not applicable** for the same reason. It fires, as an observation, on
      1 of 1 clean sprites that is genuinely a rigid stack.
    * **Thresholds:** `STACK_TOLERANCE_PX` (1.0) and `STACK_MIN_HEIGHT` (48), both
      UNVALIDATED, with the derivation from a working artist's measured offsets recorded at
      each constant.

    Cannot detect: whether a lean is the *right* lean, anything about limb placement inside
    a band, or a stack in a figure under `min_height`, where `suppressed` says so.
    """
    _, height = _require_mask(mask)
    if not bands:
        raise ValidationFailed("bands is empty; declare at least one {name: (y0, y1)} row range.")
    if tolerance < 0:
        raise ValidationFailed(f"tolerance is {tolerance}; it cannot be negative.")

    measured: list[BandCentroid] = []
    for name, span in bands.items():
        y0, y1 = span
        if y0 > y1:
            raise ValidationFailed(f"band {name!r} is ({y0}, {y1}); y0 cannot exceed y1.")
        if y0 < 0 or y1 >= height:
            raise ValidationFailed(
                f"band {name!r} is ({y0}, {y1}), outside a mask {height} rows tall."
            )
        centroid, pixels = _centroid_x(mask, y0, y1)
        if centroid is None:
            raise ValidationFailed(f"band {name!r} rows {y0}..{y1} contain no drawn pixels.")
        measured.append(BandCentroid(name, (y0, y1), centroid, pixels))

    drawn = _drawn_rows(mask)
    drawn_height = (drawn[-1] - drawn[0] + 1) if drawn else 0
    xs = [b.centroid_x for b in measured]
    spread = max(xs) - min(xs)

    suppressed = None
    if drawn_height < min_height:
        suppressed = (
            f"drawn height {drawn_height} is under {min_height}px, where a 1-to-3px lean is "
            "not distinguishable from rounding"
        )
    elif len(measured) < 2:
        suppressed = "a single band cannot show a lean"
    stacked = suppressed is None and spread <= tolerance
    return StackReading(measured, spread, stacked, drawn_height, suppressed)


# ---------------------------------------------- 3. connected components and interior holes
class Region(NamedTuple):
    pixels: int
    box: BBox


class Topology(NamedTuple):
    components: list[Region]
    holes: list[Region]


def _label(mask: Mask, *, want: bool) -> tuple[list[Region], list[list[int]]]:
    """4-connected regions of cells equal to `want`, plus the per-cell label map.

    The map is returned because a bounding box is not a membership test: a one-pixel frame
    drawn around a solid blob has a box containing the blob, and any per-component question
    answered over the box would be answered about its neighbour. `thin_parts` is exactly
    that question.

    Regions come back largest first; the map holds each cell's index into the UNSORTED
    discovery order, and the returned regions carry no id, so the map is paired with the
    sort by `_regions_by_label` below.
    """
    width, height = _dims(mask)
    labels = [[-1] * width for _ in range(height)]
    found: list[Region] = []
    for sy in range(height):
        for sx in range(width):
            if labels[sy][sx] >= 0 or mask[sy][sx] != want:
                continue
            index = len(found)
            queue = deque([(sx, sy)])
            labels[sy][sx] = index
            count = 0
            x0 = x1 = sx
            y0 = y1 = sy
            while queue:
                x, y = queue.popleft()
                count += 1
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
                for dx, dy in _NEIGHBOURS_4:
                    nx, ny = x + dx, y + dy
                    if (
                        0 <= nx < width
                        and 0 <= ny < height
                        and labels[ny][nx] < 0
                        and mask[ny][nx] == want
                    ):
                        labels[ny][nx] = index
                        queue.append((nx, ny))
            found.append(Region(count, BBox(x0, y0, x1, y1)))
    return found, labels


def _sorted_regions(found: list[Region]) -> list[Region]:
    return sorted(found, key=lambda r: (-r.pixels, r.box.y0, r.box.x0))


def components(mask: Mask) -> list[Region]:
    """The 4-connected opaque regions, largest first, each with its pixel count and box."""
    _require_mask(mask)
    found, _ = _label(mask, want=True)
    return _sorted_regions(found)


def interior_holes(mask: Mask) -> list[Region]:
    """Background regions fully enclosed by drawn pixels, which is to say pinholes."""
    width, height = _require_mask(mask)
    found, _ = _label(mask, want=False)
    return _sorted_regions(
        [
            region
            for region in found
            # A 4-connected background region reaches the canvas border exactly when it
            # contains a border cell, which is exactly when its box touches the border, so
            # the box test is the enclosure test and needs no second flood fill.
            if region.box.x0 > 0
            and region.box.y0 > 0
            and region.box.x1 < width - 1
            and region.box.y1 < height - 1
        ]
    )


def topology(mask: Mask) -> Topology:
    """Component count and boxes, plus interior holes. Topology, so no thresholds at all.

    A hole is a background region whose bounding box does not touch the canvas border,
    which for a 4-connected background is the same as being enclosed. Both readings are
    integers that a person can verify by looking, which is the whole appeal: they cannot
    drift, and there is no number to tune.

    Gates:

    * **Construct: PASSED.** Detects: a silhouette that is secretly several pieces, or that
      has a pinhole in it. A correct sprite producing the same numbers would have to
      actually have those pieces or that hole, and then the reading is true. Multiple
      components is reported, not judged: `workspace/throw_frame.png` correctly has 2 (a
      figure and the thing it threw), so the count is a fact the caller interprets.
    * **Ranking: PASSED.** Holes: orb 0, dungeon 0, golem 1 and 2. Components: all of the
      above are 1. The known-bad sprite is the only reference with a hole, in both its
      versions: `workspace/golem.png` has one of 60 pixels at x 41..44, y 25..49, and
      `docs/assets/showcase/golem.png` has one of 54 at x 19..22, y 36..54 plus a single
      pixel at (24, 16). `assets/skeleton.png` has one of 2 pixels at (16, 26..27).
    * **Specificity: 0 hole-fires on 8 clean sprites** (3 orb stages, docs orb, dungeon,
      roundblock, facetblock, smear_bare), which supports only "false-positive rate
      probably under 32 percent". The honest claim is that the sample is too small to
      claim a rate; the argument for this measure is that it is near-zero false positive
      *by construction*, not by sample.
    * **Thresholds:** none. That is the point of this one.

    Discarded here, and recorded because it is a result: **keyline boundary share**, the
    proposed "given a declared keyline colour, count boundary pixels that are not that
    colour, as gaps in an outline". It fails the ranking gate outright and was dropped.
    On `workspace/orb_3_full.png`, known good, 32 of 76 boundary pixels (42.1 percent) are
    not the darkest colour, because the orb is lit and its top rim is deliberately drawn in
    two lighter ramp steps (#5A7FD4 17px, #283AA7 15px, #17145D 44px on the boundary). On
    `workspace/golem.png`, known bad, the figure is outlined uniformly and the share is
    0.0 percent. The known-good sprite ranks worse than the known-bad one, so the measure
    does not measure outline integrity; it measures whether the artist used a selective
    outline, which is correct practice. `docs/assets/showcase/dungeon.png` reads 97.0
    percent for a third reason, being a full-bleed scene with no outline at all.
    """
    return Topology(components(mask), interior_holes(mask))


# ------------------------------------------------- 4. chunky pixels, one-pixel thickness
def _solid_block_labels(labels: list[list[int]]) -> set[int]:
    """Which components contain a 2x2 square all four of whose cells are their own."""
    out: set[int] = set()
    for y in range(len(labels) - 1):
        for x in range(len(labels[0]) - 1):
            here = labels[y][x]
            if here >= 0 and labels[y][x + 1] == here == labels[y + 1][x] == labels[y + 1][x + 1]:
                out.add(here)
    return out


def thin_parts(mask: Mask) -> list[Region]:
    """Components that hold no solid 2x2 square: nothing in them is thicker than a pixel.

    This is erosion by a 2x2 structuring element, and the element size is load-bearing
    rather than incidental. The obvious implementation, eroding with the 4-neighbour cross,
    **also deletes a two-pixel-wide limb**, because every pixel of a two-wide bar has a
    background pixel to its left or its right. Two pixels is the thickness the SOURCED
    rule below prescribes as the *fix*, so a cross-shaped element reports the fix as the
    defect. Verified rather than assumed: a 2x4 bar erodes to nothing under the cross and
    survives under the 2x2 square, which is
    `test_figure.py::test_thin_parts_ignores_a_two_pixel_arm`.

    Returned largest first, each with its pixel count and bounding box, because the count
    is what separates the two cases this cannot tell apart on its own: a 1 or 2 pixel
    region is a highlight or a sparkle, and a 16 pixel region spanning 5 rows is a frame
    or an arm drawn as a line.

    Gates:

    * **Construct: PASSED for a solid figure, FAILED for line art.** Detects: a part of a
      design rendered one pixel thick, which reads as cardboard. Correct sprites producing
      the same reading: a one-pixel sparkle, a one-pixel highlight dot, a wireframe or grid
      icon, an unfilled one-pixel-outlined box, and small text glyphs, all of which are
      legitimately one pixel thick everywhere. The pixel count and box are returned so the
      caller can tell a sparkle from a limb; the measure cannot, and the SOURCED rule behind
      it is explicitly about the limbs of a solid figure.
    * **Ranking: PASSED, vacuously, and that word is doing work.** Every reference sprite
      reads 0, both golems included: orb 0, dungeon 0, skeleton 0, golem 0 and 0. There
      is no inversion, but there is also no evidence of sensitivity from the reference set,
      because none of those sprites has this defect. Sensitivity is demonstrated only by
      construction, in `test_figure.py`.
    * **Specificity: 0 fires on 4 reference sprites**, which supports "false-positive rate
      probably under 49 percent" and nothing stronger. That bound is close to useless and
      is written out so it cannot be mistaken for a claim of precision.
    * **Thresholds:** `CHUNKY_EROSION` (1 pixel), the one SOURCED number in this file.

    Cannot detect: a one-pixel-thick *part* of a thicker component, which is the common
    case. An arm drawn as a line but welded to a solid torso is one component, that
    component contains 2x2 squares in the torso, and nothing is reported. Seeing that needs
    part decomposition, which the research ruled out as unstable at this resolution. This
    measure sees only parts that are already separate.
    """
    _require_mask(mask)
    found, labels = _label(mask, want=True)
    solid = _solid_block_labels(labels)
    return _sorted_regions([r for i, r in enumerate(found) if i not in solid])


# ------------------------------------------------------ 5. base of support, with the fix
class SupportReading(NamedTuple):
    centroid_x: float
    base: tuple[int, int] | None
    margin: float | None
    contact_runs: int
    band: tuple[int, int]
    naive_base: tuple[int, int] | None
    naive_margin: float | None


def base_of_support(
    mask: Mask,
    *,
    standing: bool,
    band_fraction: float = SUPPORT_BAND_FRACTION,
    min_contact: int = SUPPORT_MIN_CONTACT,
) -> SupportReading | None:
    """Does a standing figure's mass sit over its feet.

    `margin = min(cx - x_left, x_right - cx)`, where cx is the mass centroid of the whole
    silhouette and [x_left, x_right] is the support base. Negative means the centre of mass
    is outside the base, the published condition for a figure that is falling rather than
    standing.

    The base is taken from contact runs at least `min_contact` wide, over the bottom
    `band_fraction` of the figure's drawn height rather than its single lowest row.
    **Both halves of that are the fix for a measured trap.** A single one-pixel-wide limb
    hanging to the floor widened a naive base from [9, 22] to [3, 22] and so made the
    figure read as MORE stable, margin 6.50 rising to 6.68. A minimum row-mass gate does
    not help, because such a limb barely changes the row's mass; with a quarter-mass gate
    the base is still [3, 22]. Requiring runs wider than one pixel leaves it at [9, 22].
    `naive_base` and `naive_margin` return the unfiltered readings so a caller can see the
    pollution rather than take this function's word for it.

    **`standing` is required and there is no default.** Returns None when it is False,
    because the measure is meaningless for a jump frame, a projectile, a floating orb or an
    item icon, all of which legitimately have their mass outside any base, and a caller
    that cannot say whether the subject is standing has no business reading the number.

    Gates:

    * **Construct: PASSED, given the flag.** Detects: a figure whose centre of mass is not
      over its footprint, which is a figure falling over. A correct sprite with a negative
      margin would have to be mid-fall or mid-jump, which `standing=False` excludes by
      contract rather than by threshold.
    * **Ranking: PASSED.** No reference sprite has a negative margin: `workspace/golem.png`
      +14.12 (base [16, 45], cx 30.12), `docs/assets/showcase/golem.png` +14.43 (base
      [5, 45], cx 30.57), `assets/skeleton.png` +6.75 (base [9, 23], cx 16.25), the orb
      +6.50 (base [9, 22], cx 15.50). No inversion, and as with `thin_parts` no evidence of
      sensitivity either, since none of them is falling over.
    * **Specificity: 0 fires on 3 clean standing subjects**, which supports only "false-
      positive rate probably under 56 percent". That is a near-useless bound and is stated
      so it cannot be mistaken for a claim. The dangling-limb case in the tests is what
      actually demonstrates the measure's behaviour.
    * **Thresholds:** `SUPPORT_BAND_FRACTION` (0.06) UNVALIDATED from the research's 5-to-8
      percent range; `SUPPORT_MIN_CONTACT` (2) measured, with the reproduction above.

    Cannot detect: whether a figure *should* be off balance (a lunge, a lean into a swing),
    balance out of the picture plane, or anything at all about a figure whose feet are off
    the bottom of its own drawn box, since the support band follows the silhouette.
    """
    _require_mask(mask)
    if not 0.0 < band_fraction <= 1.0:
        raise ValidationFailed(f"band_fraction is {band_fraction}; it has to be above 0 and at most 1.")
    if min_contact < 1:
        raise ValidationFailed(f"min_contact is {min_contact}; it has to be at least 1.")
    if not standing:
        return None

    drawn = _drawn_rows(mask)
    if not drawn:
        return None
    top, bottom = drawn[0], drawn[-1]
    band_rows = max(1, math.ceil(band_fraction * (bottom - top + 1)))
    first = max(top, bottom - band_rows + 1)

    spans: list[tuple[int, int]] = []
    for y in range(first, bottom + 1):
        spans.extend(_runs(mask[y]))
    wide = [s for s in spans if s[1] - s[0] + 1 >= min_contact]

    centroid, _ = _centroid_x(mask)
    if centroid is None:  # pragma: no cover - drawn rows exist, so drawn pixels do
        return None

    def span_of(runs: list[tuple[int, int]]) -> tuple[int, int] | None:
        if not runs:
            return None
        return min(a for a, _ in runs), max(b for _, b in runs)

    base = span_of(wide)
    naive = span_of(spans)
    return SupportReading(
        centroid_x=centroid,
        base=base,
        margin=min(centroid - base[0], base[1] - centroid) if base else None,
        contact_runs=len(wide),
        band=(first, bottom),
        naive_base=naive,
        naive_margin=min(centroid - naive[0], naive[1] - centroid) if naive else None,
    )


# ------------------------------------------------------------------------- grid entry point
def mask_from_grid(grid: Grid) -> Mask:
    """`quality.opacity_mask` under this module's name, so a caller holding a grid of
    "#RRGGBBAA" strings (the shape `get_pixels` returns) does not have to know which module
    owns the silhouette definition. There is exactly one definition, and it is
    `core.quality`'s.
    """
    return opacity_mask(grid)
