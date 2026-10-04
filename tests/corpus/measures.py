"""The measures `core/quality.py` actually emits, each with a scalar, a cut, and a claim.

`quality.readings` turns thirteen measurements into prose. To gate them, each one has to be
pulled back apart into three separable things, because they fail separately:

* a **scalar**, oriented so that higher is worse, which is what AUC and the discordant-pair
  gate read. A measure can be a perfectly good ordering with its cut in the wrong place.
* a **cut**, which is what sensitivity and specificity read, and which is where a threshold
  fitted to one example does its damage.
* a **claim**: the defect the measure says it detects, named in the vocabulary of
  `mutations`, so that a measure is scored against the damage it claims to see and not
  against damage nobody said it would notice.

The gating logic below is reimplemented from `quality.readings` rather than scraped out of
its prose, and the thresholds are *imported* from `quality` rather than copied, so a
retuned constant follows automatically and only a change to the gating shape can drift. The
drift is then caught rather than trusted: `test_metric_validation.py` asserts that this
table fires exactly as many readings as `quality.readings` returns, over every sprite in the
corpus, which is a few hundred comparisons.

One structural detail worth knowing before reading a result: the three separator readings
are an `elif` chain in `quality.readings`, so at most one of them can fire on any sprite. A
sprite whose keyline is both too thin and too low in contrast reports only the first.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import NamedTuple

from aseprite_mcp.core import quality
from aseprite_mcp.core.validation import SOURCED, UNVALIDATED

from .mutations import CLIP, COLLAPSE, DESATURATE, KEYLINE, LIGHTFLIP, OFFSET, STRAYS, WELD, ramp_of

Grid = list[list[str]]


class Sample(NamedTuple):
    """One sprite plus everything the measures need, computed once.

    `declared_ramp` is the palette the art was *supposed* to use, which for a mutant is its
    parent's. That is the declaration `palette_conformance` is asking about: a pixel is off
    the ramp relative to the ramp somebody declared, not relative to whatever the damaged
    art now happens to contain.
    """

    name: str
    label: str
    grid: Grid
    metrics: dict
    width: int
    height: int
    defect: str | None = None
    parent: str | None = None


class Measure(NamedTuple):
    """One reading, split into the things that fail separately.

    `applies` is the reading's own gate, and it belongs in the corpus construction rather
    than in the analysis. `quality.readings` says nothing at all about a full-bleed scene's
    keyline, so a scene must not contribute a keyline score either: including it ranks the
    measure on sprites it declines to speak about, and the result is a discordant-pair count
    that describes the gate instead of the measure. The dungeon scene has 364 border pixels
    because it is a 112x72 painting that reaches its own edges, and `edge_contact` correctly
    stays silent about it; scoring it anyway produced 134 discordant pairs that were entirely
    an artefact of asking.
    """

    name: str
    defect: str
    targets: tuple[str, ...]
    score: Callable[[Sample], float]
    fires: Callable[[Sample], bool]
    thresholds: Mapping[str, str]
    note: str = ""
    applies: Callable[[Sample], bool] = lambda _s: True


def make_sample(
    name: str,
    label: str,
    grid: Grid,
    *,
    declared_ramp: list[str] | None = None,
    defect: str | None = None,
    parent: str | None = None,
) -> Sample:
    height = len(grid)
    width = len(grid[0]) if height else 0
    metrics = quality.score(grid, ramp=declared_ramp)
    return Sample(name, label, grid, metrics, width, height, defect, parent)


# ------------------------------------------------------------------- shared gates


def _has_silhouette(s: Sample) -> bool:
    cells = max(1, s.width * s.height)
    return (
        s.metrics.get("drawn_pixels", 0) / cells < quality.SILHOUETTE_MAX_OPAQUE
        and s.metrics.get("colors", 0) >= quality.SHADED_MIN_COLORS
    )


def _articulated(s: Sample) -> bool:
    # Mirrors the gate in `quality.readings`, gutters included: a sheet of panels has
    # background between its panels and so satisfies every other clause here while
    # containing no figure. Keeping this in step with that one is what the consistency
    # test in test_metric_validation exists to enforce, and it is how the gutter clause
    # was found to be missing from this copy.
    rows = s.metrics.get("row_structure") or {}
    if rows.get("gutters", 0):
        return False
    return rows.get("rows_with_air", 0) > 0 or rows.get("waists", 0) > 0


def _separator(s: Sample) -> dict:
    """What `quality.readings` would look at, which is nothing unless both gates pass."""
    if _has_silhouette(s) and _articulated(s):
        return s.metrics.get("separator") or {}
    return {}


def _drawn_extent(s: Sample) -> tuple[int, int]:
    box = s.metrics.get("bbox")
    if not box:
        return (0, 0)
    return (box[2] - box[0] + 1, box[3] - box[1] + 1)


# ------------------------------------------------------------------- the measures


def _centring_error(s: Sample) -> float:
    box = s.metrics.get("bbox")
    if not box:
        return 0.0
    return float(
        max(abs(box[0] - (s.width - 1 - box[2])), abs(box[1] - (s.height - 1 - box[3])))
    )


def _welded_share(s: Sample) -> float:
    rows = s.metrics.get("row_structure") or {}
    drawn = rows.get("rows_drawn", 0)
    return rows.get("welded_rows", 0) / drawn if drawn else 0.0


def _welded_fires(s: Sample) -> bool:
    rows = s.metrics.get("row_structure") or {}
    drawn = rows.get("rows_drawn", 0)
    if not (_has_silhouette(s) and _articulated(s) and drawn):
        return False
    air = rows.get("rows_with_air", 0) / drawn
    return air < quality.OPEN_ROW_SHARE or _welded_share(s) > quality.WELDED_ROWS_SHARE


def _separator_low_fires(s: Sample) -> bool:
    sep = _separator(s)
    return bool(sep.get("separator")) and sep["share"] < quality.SEPARATOR_BAND[0]


def _separator_high_fires(s: Sample) -> bool:
    sep = _separator(s)
    if not sep.get("separator") or sep["share"] < quality.SEPARATOR_BAND[0]:
        return False
    return sep["share"] > quality.SEPARATOR_BAND[1] * 2


def _separator_contrast_fires(s: Sample) -> bool:
    sep = _separator(s)
    if not sep.get("separator"):
        return False
    low, high = quality.SEPARATOR_BAND
    if sep["share"] < low or sep["share"] > high * 2:
        return False  # an earlier arm of the elif chain already spoke
    return bool(sep["contrast"]) and sep["contrast"] < quality.WCAG_GRAPHICAL_CONTRAST


def _near_symmetry_fires(s: Sample) -> bool:
    asymmetry = s.metrics.get("silhouette_asymmetry", 0)
    drawn_w, drawn_h = _drawn_extent(s)
    drawn = s.metrics.get("drawn_pixels", drawn_w * drawn_h)
    return 0 < asymmetry <= quality.NEARLY_SYMMETRIC * drawn


SPRITE_MEASURES: tuple[Measure, ...] = (
    Measure(
        name="sparse_canvas",
        defect="art drawn much smaller than the canvas asked for",
        targets=(CLIP,),
        score=lambda s: -s.metrics.get("canvas_usage", 0.0),
        fires=lambda s: s.metrics.get("canvas_usage", 0.0) < quality.SPARSE_CANVAS,
        thresholds={"SPARSE_CANVAS": UNVALIDATED},
        applies=lambda s: s.metrics.get("bbox") is not None,
        note="0.3 is round-number, with no example cited for it in the module.",
    ),
    Measure(
        name="off_centre",
        defect="content not centred on its canvas",
        targets=(OFFSET, CLIP),
        score=_centring_error,
        fires=lambda s: not s.metrics.get("centred", True),
        thresholds={"centring tolerance (1px)": SOURCED},
        applies=lambda s: s.metrics.get("bbox") is not None,
        note="The 1px tolerance is a parity fact: an odd extent on an even canvas "
        "cannot be exactly centred, so a tighter cut would fire on arithmetic.",
    ),
    Measure(
        name="welded_rows",
        defect="separate masses fused into one slab",
        targets=(WELD,),
        score=_welded_share,
        fires=_welded_fires,
        applies=lambda s: _has_silhouette(s) and _articulated(s)
        and bool((s.metrics.get("row_structure") or {}).get("rows_drawn")),
        thresholds={"WELDED_ROW_SHARE": UNVALIDATED, "WELDED_ROWS_SHARE": UNVALIDATED,
                    "OPEN_ROW_SHARE": UNVALIDATED},
        note="All three constants are calibrated on one figure, which the module says so "
        "in as many words: 'Calibrated on the figure that failed, which ran 42 percent'.",
    ),
    Measure(
        name="edge_contact",
        defect="silhouette cut off by the canvas border",
        targets=(CLIP,),
        score=lambda s: float(s.metrics.get("edge_contact", 0)),
        fires=lambda s: _has_silhouette(s) and s.metrics.get("edge_contact", 0) > 0,
        applies=_has_silhouette,
        thresholds={"any border pixel": SOURCED},
        note="Definitional rather than fitted: a pixel on the border has no room outside "
        "it for an outline, so the cut is at one pixel because one pixel is the defect.",
    ),
    Measure(
        name="separator_share_low",
        defect="keyline too thin or absent",
        targets=(KEYLINE,),
        score=lambda s: -(_separator(s).get("share", 1.0)),
        fires=_separator_low_fires,
        applies=lambda s: bool(_separator(s).get("separator")),
        thresholds={"SEPARATOR_BAND lower (0.10)": UNVALIDATED},
        note="From two sprites: 'Reference art runs about 18 percent; the sprite that "
        "failed ran 7.6'.",
    ),
    Measure(
        name="separator_share_high",
        defect="outline so heavy it replaces the interior",
        targets=(KEYLINE,),
        score=lambda s: _separator(s).get("share", 0.0),
        fires=_separator_high_fires,
        applies=lambda s: bool(_separator(s).get("separator"))
        and _separator(s)["share"] >= quality.SEPARATOR_BAND[0],
        thresholds={"SEPARATOR_BAND upper doubled (0.48)": UNVALIDATED},
        note="Twice the top of the band, chosen rather than measured, because the band "
        "describes what is usual and this has to describe what is wrong.",
    ),
    Measure(
        name="separator_contrast",
        defect="keyline not distinguishable from what it separates",
        targets=(KEYLINE,),
        score=lambda s: -(_separator(s).get("contrast", 21.0)),
        fires=_separator_contrast_fires,
        applies=lambda s: bool(_separator(s).get("separator"))
        and quality.SEPARATOR_BAND[0] <= _separator(s)["share"]
        <= quality.SEPARATOR_BAND[1] * 2,
        thresholds={"WCAG_GRAPHICAL_CONTRAST": SOURCED},
        note="WCAG 2.1 SC 1.4.11: 3:1 between a graphical object and adjacent colours. "
        "The only threshold in the module that comes from a published standard.",
    ),
    Measure(
        name="isolated_pixels",
        defect="lone pixels reading as dirt rather than texture",
        targets=(STRAYS,),
        score=lambda s: float(s.metrics.get("isolated_pixels", 0)),
        fires=lambda s: s.metrics.get("isolated_pixels", 0) > quality.NOISY_ISOLATED,
        thresholds={"NOISY_ISOLATED": UNVALIDATED},
        note="'A handful is texture; more than this reads as noise' is the whole "
        "justification given for 8.",
    ),
    Measure(
        name="jaggy_corners",
        defect="diagonals stepping unevenly rather than running",
        targets=(),
        score=lambda s: s.metrics.get("jaggy_corners", 0) / max(1, sum(_drawn_extent(s))),
        fires=lambda s: s.metrics.get("jaggy_corners", 0)
        > quality.JAGGY_SHARE * sum(_drawn_extent(s)),
        thresholds={"JAGGY_SHARE": UNVALIDATED},
        note="Construct validity, not calibration: a correct raster circle produces 36 of "
        "these at 32x32 and 72 at 64x64, so the count tracks geometry and no threshold "
        "separates it from craft. No seeded defect is assigned to it, because none of them "
        "is the thing it counts.",
    ),
    Measure(
        name="palette_conformance",
        defect="pixels off the declared ramp",
        targets=(DESATURATE,),
        score=lambda s: 1.0 - s.metrics.get("palette_conformance", 1.0),
        fires=lambda s: s.metrics.get("palette_conformance", 1.0) < 1.0,
        applies=lambda s: "palette_conformance" in s.metrics,
        thresholds={"exact ramp membership": SOURCED},
        note="Definitional, and its specificity is untestable with this corpus: the "
        "declared ramp for a clean sprite is derived from that sprite, so conformance is "
        "1.0 by construction and the measure cannot be observed to false-positive here.",
    ),
    Measure(
        name="colors_per_ramp",
        defect="more colours than a pixel-art palette carries",
        targets=(),
        score=lambda s: s.metrics.get("colors", 0) / max(1, s.metrics.get("ramps", 0)),
        fires=lambda s: bool(s.metrics.get("ramps", 0))
        and s.metrics.get("colors", 0) > s.metrics.get("ramps", 0) * 8,
        applies=lambda s: bool(s.metrics.get("ramps", 0)),
        thresholds={"8 colours per hue cluster": UNVALIDATED},
        note="No seeded defect adds colours, and two of them (collapse, keyline) remove "
        "one, so this measure moves the wrong way on the damage it is nearest to.",
    ),
    Measure(
        name="near_symmetry",
        defect="nearly symmetric art with a few mirror mismatches",
        targets=(OFFSET, LIGHTFLIP),
        score=lambda s: s.metrics.get("silhouette_asymmetry", 0)
        / max(1, s.metrics.get("drawn_pixels", 1)),
        fires=_near_symmetry_fires,
        thresholds={"NEARLY_SYMMETRIC": UNVALIDATED},
        note="A band and not a cut: asymmetry above 12 percent of the drawn pixels stops "
        "firing again, so the scalar is not monotone in the defect and AUC understates it.",
    ),
)

# `ramp_chroma` is not a measure of a sprite. It reads a *declared palette* and asks whether
# that palette's hue rotation is visible or routes through grey, so it cannot be scored on a
# sprite corpus at all: the pixels never reach it. It gets its own corpus of palettes, built
# from each good sprite's colour list against the same list with its midpoint desaturated.
#
# Whether handing it a 47-colour scene palette is a fair question is a construct issue the
# harness cannot settle. It is reported, not hidden.
RAMP_MEASURE = Measure(
    name="ramp_grey_steps",
    defect="declared ramp passing through grey",
    targets=(DESATURATE,),
    score=lambda s: float(s.metrics.get("ramp_chroma", {}).get("grey_steps", 0)),
    fires=lambda s: bool(s.metrics.get("ramp_chroma", {}).get("grey_steps", 0)),
    thresholds={"HUE_INVISIBLE_SAT": UNVALIDATED},
    note="From one ramp: 'fell to 2.4 percent at its midtone while rotating 227 degrees'.",
    applies=lambda s: "ramp_chroma" in s.metrics,
)

# Thirteen readings, which is the number `family_wise_error` should be given. `ramp_chroma`
# is counted here because `quality.readings` emits a line for it like any other, even though
# it is scored on a palette corpus rather than a sprite one: leaving it out of this tuple
# made the cross-check against `quality.readings` fail on the attack panels, whose own
# palettes carry two grey steps apiece, and the cross-check was right.

# ------------------------------------------------- a candidate of my own, rejected
#
# Two seeded defects pass through all thirteen existing readings untouched: welding and a
# flipped light direction. This is a measure proposed for the second of them, tested against
# the corpus, and **discarded by the gate it was written to pass**. It is kept rather than
# deleted because a harness whose only output is a verdict on somebody else's work has not
# been tried on anything.
#
# The idea: light that comes from one side puts the bright pixels on that side, so compare
# where the luminance sits against where the mass sits, independently for the figure's upper
# and lower halves, and report how far the two halves disagree. `flip_light` reverses the
# colour order along each row of the upper half only, so the upper half's offset should
# negate while the lower half's holds, and the disagreement should roughly double.
#
# It does. AUC 0.931, and eleven of its twelve matched pairs move the right way. And it is
# discarded anyway, because there are **10 discordant pairs**: the clean attack panel scores
# 0.332 while the flipped item_3 scores 0.167, so a fixed threshold that caught the flipped
# sprite would already have fired on undamaged published art. One of the twelve matched pairs
# also inverts outright.
#
# The honest reading is the one the four withdrawn alignment measures got: a high AUC with
# discordant pairs is a measure that works on average over a corpus and cannot be given a
# threshold, and "works on average" is not what a reading does. No cut is proposed for it
# here, because proposing one would be fitting it to the examples that happened to separate.


def _luminance_of(color: str) -> float:
    return quality.luminance((*_rgb_of(color), 255))


def _rgb_of(color: str) -> tuple[int, int, int]:
    body = color.lstrip("#")
    return (int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16))


def _light_offset(grid: Grid, y0: int, y1: int) -> float | None:
    """Where the light sits in this band, as a signed fraction of its half-width.

    The luminance-weighted horizontal centroid minus the geometric one. Zero means the
    bright pixels sit where the mass sits, which is flat lighting; positive means the light
    comes from the right.
    """
    xs: list[int] = []
    weights: list[float] = []
    for y in range(y0, y1 + 1):
        for x, color in enumerate(grid[y]):
            if color.lstrip("#")[6:8] != "00":
                xs.append(x)
                weights.append(_luminance_of(color))
    if not xs or sum(weights) <= 0:
        return None
    span = max(xs) - min(xs)
    if span < 2:
        return None
    weighted = sum(w * x for w, x in zip(weights, xs, strict=True)) / sum(weights)
    return (weighted - sum(xs) / len(xs)) / (span / 2)


def light_direction_split(sample: Sample) -> float:
    """How far the upper and lower halves of a figure disagree about the light direction."""
    box = sample.metrics.get("bbox")
    if not box:
        return 0.0
    _x0, y0, _x1, y1 = box
    middle = (y0 + y1) // 2
    upper = _light_offset(sample.grid, y0, middle)
    lower = _light_offset(sample.grid, middle + 1, y1)
    if upper is None or lower is None:
        return 0.0
    return abs(upper - lower)


REJECTED_CANDIDATE = Measure(
    name="light_direction_split",
    defect=LIGHTFLIP,
    targets=(LIGHTFLIP,),
    score=light_direction_split,
    fires=lambda _s: False,
    thresholds={},
    note="Proposed here, tested here, DISCARDED here: AUC 0.931 with 10 discordant pairs.",
    applies=lambda s: s.metrics.get("bbox") is not None
    and light_direction_split(s) is not None,
)

ALL_MEASURES: tuple[Measure, ...] = (*SPRITE_MEASURES, RAMP_MEASURE)


def fired(sample: Sample) -> set[str]:
    """Which readings fire on this sample, as `quality.readings` would emit them."""
    return {m.name for m in ALL_MEASURES if m.fires(sample)}


def declared_ramp(grid: Grid) -> list[str]:
    """The palette a sprite is taken to have declared, which is the one it uses."""
    return ramp_of(grid)


__all__ = [
    "ALL_MEASURES",
    "COLLAPSE",
    "RAMP_MEASURE",
    "REJECTED_CANDIDATE",
    "SPRITE_MEASURES",
    "Measure",
    "Sample",
    "declared_ramp",
    "fired",
    "make_sample",
]
