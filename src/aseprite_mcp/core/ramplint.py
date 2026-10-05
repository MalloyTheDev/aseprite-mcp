"""Measurements of a declared ramp, and of the value structure of a drawing.

`core.quality` measures a sprite's silhouette, its stray pixels and its keyline. Two
things it cannot see are measured here.

**A ramp is a thing in its own right.** Every shading tool in this server takes a `ramp`
argument, and until now the only thing anybody asked about one was whether its hue
rotation was visible (`quality.ramp_chroma`). A ramp can rotate a perfectly visible hue
while reversing direction in the middle, or while spending two of its entries on the same
colour. Those are defects of the ramp, measurable before a single pixel is drawn, and a
lint on the declared ramp cannot produce a false positive about the art because it is not
looking at the art.

**Value structure is the presence of craft, not the absence of a defect.** Everything in
`core.quality` is a guardrail: it finds stray pixels, fused masses, a missing keyline.
None of it can say whether a drawing has a value design. The notan test here is the one
measure in this codebase that asks whether something is *there* rather than whether
something is wrong, and it asks it the way a painter does: are the values grouped into a
few large shapes, or scattered.

## The evidence standard these measures are held to

Every measure below records four things in its own docstring, because a measurement that
has not been attacked is a guess with a number on it.

1. **Construct gate.** What defect it detects, and whether a *correct* ramp or sprite can
   produce the same number. Where one can, the measure is discarded and the discard is
   written down instead (see `DISCARDED` at the foot of this module, which is a longer
   list than the one of measures kept).
2. **Ranking gate.** A measure that ranks a known-good example worse than a known-bad one
   is discarded, not inverted and not tuned around.
3. **Specificity.** How many known-good examples it fires on, and the honest bound on what
   it can see.
4. **Threshold honesty.** Every number is tagged `SOURCED:` with its citation or
   `UNVALIDATED:` with the reasoning that produced it. There are far more of the second
   kind than the first, which is the point of tagging them.

The reference examples are this repository's own committed art, measured at native
resolution:

  * known good: `workspace/orb_3_full.png` (32x32), `docs/assets/showcase/dungeon.png`
    (112x72), `docs/assets/showcase/item_sheet.png` (200x40, five 40x40 cells);
  * known bad: `workspace/golem.png` (64x64), `assets/skeleton.png` (32x32), whose
    darkest colour is 50.3 percent of its drawn pixels.

Pure, like `core.quality`: it takes the grid of "#RRGGBBAA" strings that `get_pixels`
returns and a ramp as a list of colours, and touches neither Aseprite nor the filesystem.
The perceptual maths is borrowed rather than rewritten: Oklab comes from `core.ramps` and
relative luminance and the contrast ratio from `core.quality`, so a step judged dark here
and a step judged dark there cannot disagree.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from typing import Literal

from . import quality, ramps

Grid = quality.Grid

# ====================================================================== colour difference
# CIEDE2000 rather than Oklab's own distance, for one reason: the thresholds that make this
# measure worth having are published in CIEDE2000 units, and a threshold compared against a
# different metric is not that threshold. Oklab dE is the better-behaved number and would
# be the right choice if the lint were about ranking ramps against each other; it is about
# comparing one ramp against a perceptibility limit, so the units have to match the limit.
#
# The implementation is the standard formula with kL = kC = kH = 1, and it is checked
# against all 33 of the published test pairs in `tests/test_ramp_lint.py` rather than
# trusted. That matters more than usual here: CIEDE2000 has four separate places where a
# plausible implementation is wrong only for hue pairs that straddle 0 or 360 degrees, and
# the test data exists precisely to catch them.
#
# SOURCED: Sharma, Wu and Dalal (2005), "The CIEDE2000 color-difference formula:
# implementation notes, supplementary test data, and mathematical observations", Color
# Research and Application 30(1), 21-30. The 33 test pairs come from that paper's
# supplementary data.

# D65, which is sRGB's own white point, so no chromatic adaptation is involved.
_D65 = (0.95047, 1.00000, 1.08883)


def _srgb_to_linear(channel: float) -> float:
    """The sRGB electro-optical transfer function, on a 0..1 channel.

    A second copy of four lines that also sit in `core.ramps`, deliberately. What must not
    have two definitions is a *measurement*, and this is not one: it is a published
    transfer function with no judgement in it, and the measurements this module makes
    (`quality.luminance`, `quality.contrast_ratio`, `ramps.to_oklab`) are all imported
    rather than restated.
    """
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel: float) -> float:
    return 12.92 * channel if channel <= 0.0031308 else 1.055 * (channel ** (1 / 2.4)) - 0.055


def to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """CIELAB under D65, which is what CIEDE2000 takes."""
    r, g, b = (_srgb_to_linear(c / 255) for c in rgb)
    xyz = (
        0.4124564 * r + 0.3575761 * g + 0.1804375 * b,
        0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
        0.0193339 * r + 0.1191920 * g + 0.9503041 * b,
    )

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t * (29 / 6) ** 2 / 3 + 4 / 29

    fx, fy, fz = (f(v / w) for v, w in zip(xyz, _D65, strict=True))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """The CIEDE2000 colour difference between two CIELAB colours, with kL = kC = kH = 1."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt(cbar**7 / (cbar**7 + 25.0**7))) if cbar else 0.5
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(a: float, b: float) -> float:
        # Zero rather than atan2's answer when there is no chroma at all: the hue of a
        # neutral is undefined, and atan2(0, 0) would quietly report 0 degrees as if it
        # were a measurement.
        return 0.0 if a == 0.0 and b == 0.0 else math.degrees(math.atan2(b, a)) % 360.0

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)
    delta_l, delta_c = l2 - l1, c2p - c1p
    if c1p * c2p == 0.0:
        delta_h = 0.0
    elif abs(h2p - h1p) <= 180.0:
        delta_h = h2p - h1p
    elif h2p - h1p > 180.0:
        delta_h = h2p - h1p - 360.0
    else:
        delta_h = h2p - h1p + 360.0
    delta_hh = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h) / 2.0)

    lbar, cbarp = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0.0:
        hbar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hbar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hbar = (h1p + h2p + 360.0) / 2.0
    else:
        hbar = (h1p + h2p - 360.0) / 2.0

    t = (1.0
         - 0.17 * math.cos(math.radians(hbar - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hbar))
         + 0.32 * math.cos(math.radians(3.0 * hbar + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hbar - 63.0)))
    delta_theta = 30.0 * math.exp(-(((hbar - 275.0) / 25.0) ** 2))
    rc = 2.0 * math.sqrt(cbarp**7 / (cbarp**7 + 25.0**7)) if cbarp else 0.0
    sl = 1.0 + (0.015 * (lbar - 50.0) ** 2) / math.sqrt(20.0 + (lbar - 50.0) ** 2)
    sc = 1.0 + 0.045 * cbarp
    sh = 1.0 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2.0 * delta_theta)) * rc

    dl, dc, dh = delta_l / sl, delta_c / sc, delta_hh / sh
    return math.sqrt(dl * dl + dc * dc + dh * dh + rt * dc * dh)


def ramp_step_differences(ramp: list[str]) -> list[float]:
    """CIEDE2000 between each consecutive pair of ramp entries."""
    labs = [to_lab(_rgb(colour)) for colour in ramp]
    return [ciede2000(a, b) for a, b in itertools.pairwise(labs)]


# SOURCED, with the kind of source stated, because it is not the same kind as the formula's.
# These four are the conventional interpretation of a CIEDE2000 difference, as used in
# colour-difference tolerancing: below 1.0 two colours are not distinguishable; about 1.3 is
# the commonly cited perceptibility threshold; about 2.3 the acceptability threshold, the
# "just noticeable difference" of print tolerance work; above 5 the difference is obvious at
# a glance. They are standard published tolerances rather than one experiment's result, so
# the citation is to common practice and not to a paper, and that is a weaker footing than
# `ciede2000` itself stands on: the formula is checked against Sharma's data and these
# numbers cannot be checked against anything offline.
#
# What that weakness costs is bounded by using as few of them as possible. `DE_IMPERCEPTIBLE`
# is the only one attached to a ramp verdict, and it is the safest of the four because it is
# the one that describes something a ramp cannot legitimately do rather than something a
# viewer might or might not notice. `DE_PERCEPTIBLE` and `DE_ACCEPTABILITY` bracket the
# colour-vision pair test, where they are used as a pair ("clearly different before, not
# visible after") so that an error in either one shrinks the finding rather than inventing
# one. `DE_OBVIOUS` carries no verdict at all and is here so that a caller reading a raw
# `step_evenness` figure has the whole scale rather than one end of it.
DE_IMPERCEPTIBLE = 1.0
DE_PERCEPTIBLE = 1.3
DE_ACCEPTABILITY = 2.3
DE_OBVIOUS = 5.0


# ============================================================================ ramp lints


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _rgba(colour: str) -> tuple[int, int, int, int]:
    """Parse "#RRGGBB" or "#RRGGBBAA". A parser, not a measurement; see `_srgb_to_linear`."""
    value = colour.lstrip("#")
    if len(value) == 6:
        value += "ff"
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), int(value[6:8], 16))


def monotone_lightness(ramp: list[str]) -> dict:
    """Whether lightness runs one way along the ramp, and where it does not.

    A ramp is an ordered list of values, and shading tools use the order: `shift_along_ramp`
    moves a block two steps down it, `outline_smart` darkens by `darken_steps`, and
    `specular_highlight` wants the top entry to be the brightest thing available. A ramp
    that reverses in the middle makes all three move a block to a value it did not ask for,
    and the sprite then has a band in the wrong place that no measurement of the sprite can
    explain, because the cause is in the argument.

    Reported as Oklab L, from `core.ramps`, for the reason `quality.luminance` exists: HLS
    lightness reports 0.500 for both pure yellow and pure blue, so a ramp running blue to
    yellow would pass a monotonicity check on HLS by being exactly flat.

    `reversals` carries the size of each reversal, not just its position, because the
    boolean cannot tell a ramp that turns around from one with two steps at the same value.
    `ties` are consecutive entries at identical lightness, which is a different defect: not
    a ramp pointing two ways but a ramp with a step that does not step.

    **Construct gate.** The defect: a ramp whose entries are not ordered by value, so an
    ordinal move along it is not a move in value. Can a correct ramp do this? Not a
    *shading* ramp, which is what every tool here takes one for: its whole contract is that
    index order is value order. A palette row used for hue variation rather than shading
    can of course reverse, and this measure would be wrong about it, which is the honest
    bound below.
    **Ranking gate.** Nothing to rank: the measure reads the ramp, not the art. All eleven
    ramps this repository's showcase scripts declare are monotone with no ties, the eight
    from known-good art and the three from known-bad art alike, so it separates nothing and
    is not offered as a quality signal.
    **Specificity.** Fires on 0 of the 8 known-good ramps, and on 0 of the 3 known-bad ones.
    The bound: it says the entries are not value-ordered, not that the colours are wrong. It
    also cannot see a ramp that is monotone and badly spaced, which is `step_evenness`.
    **Thresholds.** None. The comparison is `L[i + 1] > L[i]`, which is the definition of
    the property rather than a line drawn across a measurement, so there is nothing to
    validate and no false positive available to it.
    """
    if len(ramp) < 2:
        return {"monotone": True, "direction": None, "lightness": [], "reversals": [],
                "ties": [], "max_reversal": 0.0}
    lightness = [ramps.to_oklab(_rgb(colour))[0] for colour in ramp]
    rising = lightness[-1] >= lightness[0]
    reversals, ties = [], []
    for index, (first, second) in enumerate(itertools.pairwise(lightness)):
        delta = second - first
        if delta == 0.0:
            ties.append(index)
        elif (delta < 0.0) if rising else (delta > 0.0):
            reversals.append({"at": index, "delta": round(delta, 6)})
    return {
        "monotone": not reversals and not ties,
        "direction": "lighter" if rising else "darker",
        "lightness": [round(value, 4) for value in lightness],
        "reversals": reversals,
        "ties": ties,
        "max_reversal": round(max((abs(r["delta"]) for r in reversals), default=0.0), 6),
    }


def step_evenness(ramp: list[str]) -> dict:
    """How far apart consecutive ramp entries are, and whether any pair is wasted.

    Two entries closer than one CIEDE2000 unit are the same colour to a viewer, so the
    second of them is a palette slot that buys nothing. On a sprite with sixteen colours to
    spend that is a real cost, and it is invisible in every other measurement here: both
    entries are on the ramp, so `quality.palette_conformance` is 1.0, and the ramp is
    monotone, so the lint above passes.

    `ratio` is max over min step, reported and not judged. See the discard note on
    `DISCARDED` for why: this project's own `generate_ramp(easing="perceptual")` bunches
    the dark steps *on purpose*, because equal steps in HLS lightness are not equal steps
    to the eye, so a threshold on evenness would fire hardest on the setting the
    documentation recommends.

    **Construct gate.** The defect: a palette entry that cannot be told from its
    neighbour. Can a correct ramp have two entries under dE 1.0? A ramp that clipped at an
    end has two *identical* entries, which `ramps.clipped_ends` already names, and that is
    the same defect found a different way rather than a counter-example. A deliberate pair
    of near-identical entries would be a ramp carrying a colour it cannot use. So the
    construct gate holds for the dE 1.0 reading and fails for the evenness ratio, and only
    the first is a reading.
    **Ranking gate.** Measured on the eleven ramps the showcase scripts declare, it fires
    once, on a **known-good** ramp, and that firing is a true positive rather than a gate
    failure. The `item_sheet` parchment ramp's top pair is `#fefdfc` to `#ffffff` at dE
    0.73: a near-clip, two entries that no viewer can tell apart, so the nine-step ramp has
    eight usable steps. `scripts/showcase/items.py` asserts against exactly this and misses
    it, because it asserts `len(set(colors)) == steps`, and two hex strings that differ are
    distinct however identical the colours are. Measured in the committed `item_sheet.png`
    the entry is not merely redundant but **unused**: `#ffffff` covers 8 pixels and
    `#fefdfc` covers none, so the ramp carries a ninth entry nothing is drawn with. The
    next smallest step on any ramp is 3.60 (`GOLD`), so the dE 1.0 line sits inside an
    empty band almost three units wide rather than against a cluster.
    **Specificity.** Fires on 1 of 8 known-good ramps and 0 of 3 known-bad. That is the
    honest bound and it is the wrong way round for a quality signal: this is a lint on a
    wasted palette entry, not a measure of whether a ramp is good. The other bound is that
    it sees two entries that cannot be distinguished and says nothing about whether the ramp
    has enough entries, or the right ones.
    **Thresholds.** `DE_IMPERCEPTIBLE` is SOURCED. The evenness ratio has no threshold.
    """
    if len(ramp) < 2:
        return {"steps": [], "min": 0.0, "max": 0.0, "ratio": 1.0, "imperceptible_pairs": []}
    steps = ramp_step_differences(ramp)
    smallest, largest = min(steps), max(steps)
    return {
        "steps": [round(value, 3) for value in steps],
        "min": round(smallest, 3),
        "max": round(largest, 3),
        # Infinity rather than a divide-by-zero: a ramp with two identical entries has an
        # unboundedly uneven step, and saying so is more use than a crash.
        "ratio": round(largest / smallest, 2) if smallest > 0 else float("inf"),
        "imperceptible_pairs": [
            {"at": index, "de": round(value, 3), "colors": [ramp[index], ramp[index + 1]]}
            for index, value in enumerate(steps)
            if value < DE_IMPERCEPTIBLE
        ],
    }


def step_contrast(ramp: list[str]) -> dict:
    """WCAG contrast ratios between adjacent ramp entries, and across the whole ramp.

    **This reports APCA's question and not APCA's number, and the difference is worth
    stating.** APCA scores perceptual lightness contrast from 0 to about 106 and sets
    Lc 15 as the absolute minimum for a non-text element that must be discernible, which is
    the right shape of threshold for a ramp step. It is not used here. APCA's exponents,
    its soft black clamp and its scaling constants are specific to a formula revision, the
    revisions differ from each other by more than the precision a lint needs, and this
    module cannot check an implementation of it against a reference the way `ciede2000`
    above is checked against 33 published pairs. A threshold quoted from a standard and
    applied to a half-remembered implementation of it is worse than no threshold, so the
    ratio from `quality.contrast_ratio` is used instead and the Lc 15 anchor is not
    applied to anything.

    What that costs is worth naming too: **WCAG's ratio overstates contrast near black**,
    because the `+ 0.05` flare term in the denominator dominates when both luminances are
    tiny. Two near-black colours can report a comfortable ratio while being invisibly
    different, and the dark end is exactly where ramp steps crowd together, because equal
    perceptual steps are small luminance steps down there. So `adjacent` is least
    trustworthy at `index 0`, which is the one place a ramp lint most wants to look. That
    gap is why `step_evenness` exists and is the measure that actually reads on crowding:
    CIEDE2000's lightness term is CIELAB's, which has no flare term in it.

    **Nothing here carries a reading. Both candidate thresholds were built and discarded.**

    **Construct gate, adjacent ratios: failed.** A smooth eight-step ramp from near-black to
    near-white has adjacent ratios around 1.2 by arithmetic, and a ramp whose adjacent steps
    all cleared WCAG's 3:1 for graphical objects would have at most three steps. Measured,
    the eleven showcase ramps have minimum adjacent ratios from 1.02 to 1.66, so a single
    threshold anywhere at or above 1.7 fires on all eleven. There is no threshold.
    **Construct gate, the span: also failed, and less obviously.** `span_clears_3to1` is
    computed and reported, and the reading that was written on it has been withdrawn. It
    looked good: of the eleven ramps exactly one fails, at 2.70, and that one is `BONE`,
    from the known-bad `skeleton`, while the other ten run 7.67 to 15.43. But a correct ramp
    can produce 2.70. A high-key material, bone or snow or white cloth, is legitimately
    declared as a ramp covering the top of the value range, with the dark end of the picture
    supplied by a separately declared keyline, and that is not a hypothetical: it is exactly
    what `scripts/showcase/skeleton.py` does, declaring `BONE` for the material and
    `DARK = "#241f2b"` beside it. So the number the reading fired on is a description of the
    workflow and not of a defect, the sprite's actual recorded defect is that its keyline
    covers 50.3 percent of it, and firing on the right sprite for the wrong reason is not
    evidence. Discarded. See `DISCARDED`.
    **Ranking gate.** Not reached for the adjacent ratios. For the span it would have failed
    too, as a continuous ordering: the golem's `STONE` (known bad) spans 12.51 against the
    item sheet's `WOOD` (known good) at 7.67.
    **Specificity.** No reading, so none. As a measurement the bound is that a ramp can span
    15:1 and still put every one of its entries in the top two stops, which is
    `step_evenness`'s question rather than this one's.
    **Thresholds.** `WCAG_GRAPHICAL_CONTRAST` (3:1) is SOURCED and imported from
    `core.quality` so this module and `separator_share` cannot drift apart. It is used to
    label `span_clears_3to1` for the caller and is attached to no verdict.
    """
    if len(ramp) < 2:
        return {"adjacent": [], "min_adjacent": 0.0, "span": 1.0, "span_clears_3to1": False}
    pixels = [_rgba(colour) for colour in ramp]
    adjacent = [
        quality.contrast_ratio(first, second)
        for first, second in itertools.pairwise(pixels)
    ]
    span = quality.contrast_ratio(pixels[0], pixels[-1])
    return {
        "adjacent": [round(value, 2) for value in adjacent],
        "min_adjacent": round(min(adjacent), 2),
        "span": round(span, 2),
        "span_clears_3to1": span >= quality.WCAG_GRAPHICAL_CONTRAST,
    }


def hue_shift_direction(ramp: list[str]) -> dict:
    """Which way the ramp's hue moves as it lightens. Reported, never failed.

    Craft practice is cool shadows and warm highlights: the shadow end goes toward blue and
    the light end toward yellow, which is what `generate_ramp`'s `shadow_hue` and
    `light_hue` arguments exist to express. Measured on Oklab's b axis, which runs blue
    negative to yellow positive, so a warm highlight is simply `delta_b > 0`. The a axis
    (green negative, red positive) comes back too, because the other half of the convention
    is that the light end goes toward red as well as toward yellow.

    **There is no reading on this and there will not be one.** A fire, a lava flow, a
    glowing core and a bioluminescent anything all invert the convention correctly: their
    light *is* the warm thing, so the shadow is the cooler colour only in the sense that it
    is the absence of the fire. Measured on the eleven showcase ramps, six report a warm
    highlight and **five report a cool one**, and four of those five belong to known-good
    art: `GOLD`, `PAINT` and `PARCH` from the item sheet and `FLAME` from the dungeon.
    `FLAME` is the clearest case at delta_b -0.0477: it runs from a deep orange-brown to a
    near-white, so its top entry is *less* yellow than its bottom one while being the
    correct top of a fire ramp. A lint on the sign would fire on half the known-good art in
    this repository, so the sign is reported and a person decides.

    `chroma_ends` is reported alongside because the sign is meaningless without it: a ramp
    whose ends are both near-neutral has a b axis made of rounding, and `quality.ramp_chroma`
    exists because that case is common rather than exotic.

    **Construct gate.** Deliberately not passed, which is why this is reported and not
    judged. The counter-examples are not edge cases; they are a whole category of sprite.
    **Ranking gate.** Not applicable: no verdict to rank by.
    **Specificity.** Not applicable, for the same reason.
    **Thresholds.** None.
    """
    if len(ramp) < 2:
        return {"warm_highlight": None, "delta_b": 0.0, "delta_a": 0.0, "chroma_ends": [0.0, 0.0]}
    dark = ramps.to_oklab(_rgb(ramp[0]))
    light = ramps.to_oklab(_rgb(ramp[-1]))
    return {
        "warm_highlight": light[2] > dark[2],
        "delta_b": round(light[2] - dark[2], 4),
        "delta_a": round(light[1] - dark[1], 4),
        "chroma_ends": [round(math.hypot(dark[1], dark[2]), 4),
                        round(math.hypot(light[1], light[2]), 4)],
    }


def black_floor(ramp: list[str]) -> dict:
    """How close the ramp's darkest step comes to pure black, and whether it arrives.

    Written because the same fault appeared three times in one piece, from three
    different ramps, and nothing in this module or `quality` could see it. A ramp built
    with a wide `light_range` around a dark base clips its first step to #000000 or close
    to it. That step is then darker than any sensible keyline, so the drawing's darkest
    colour becomes a few pixels of interior shadow, `separator_share` reports the outline
    at under one percent, and the keyline stops being measurable at all.

    `ramp_chroma` cannot catch it: a step at pure black has no hue, so it is not a grey
    step, and the ramp passes. That is the specific hole this fills.

    Reported as a luminance rather than a verdict, because how dark is too dark depends
    on the keyline the art will use. `craft.ramp_floor_clears` answers that question when
    the keyline is known.
    """
    if not ramp:
        return {"floor": 0.0, "floor_color": None, "is_black": False, "near_black": False}
    floors = sorted(ramp, key=lambda c: quality.luminance(_rgba(c)))
    darkest = floors[0]
    lum = quality.luminance(_rgba(darkest))
    return {
        "floor": round(lum, 5),
        "floor_color": darkest,
        # Exactly #000000: no keyline can be darker, so the ramp is guaranteed to win.
        "is_black": darkest.lstrip("#")[:6].lower() == "000000",
        # SOURCED: 0.0015 is the luminance of #060509, below the #07080f and #05060c
        # keylines this project has used, so a step under it will beat a plausible
        # outline even when it is not literally black.
        "near_black": lum < 0.0015,
    }


def ramp_lints(ramp: list[str]) -> dict:
    """Every ramp measurement at once, as a plain dict."""
    return {
        "steps": len(ramp),
        "distinct": len(set(ramp)),
        "black_floor": black_floor(ramp),
        "monotone_lightness": monotone_lightness(ramp),
        "step_evenness": step_evenness(ramp),
        "step_contrast": step_contrast(ramp),
        "hue_shift": hue_shift_direction(ramp),
    }


def ramp_readings(lints: dict) -> list[str]:
    """One sentence per ramp measurement worth acting on, and nothing for the rest.

    `black_floor` deliberately produces none, although it was written to. A step at pure
    black is only a fault *relative to a keyline that ought to be darker than it*, and a
    ramp does not know what keyline the art will use. Asked to judge on its own it fired
    on two of this project's eleven known-good showcase ramps, WOOD at #060402 and RIBBON
    at #000000, both of which are correct: that art uses black as its own darkest value
    and has no separate outline to lose. The judgement belongs where the keyline is known,
    which is `craft.ramp_floor_clears(ramp, keyline)`.

    Two of the four original ramp measures produce a sentence: `monotone_lightness`, which is
    threshold-free, and the dE 1.0 pair of `step_evenness`, whose threshold is sourced.
    `step_contrast` and `hue_shift_direction` produce none, the first because both of its
    candidate thresholds failed the construct gate and the second by design.
    """
    out: list[str] = []
    mono = lints.get("monotone_lightness") or {}
    for reversal in mono.get("reversals", []):
        index = reversal["at"]
        out.append(
            f"The ramp reverses direction between entry {index} and entry {index + 1}: "
            f"lightness moves {reversal['delta']:+.4f} in Oklab L against a ramp that "
            f"otherwise runs {mono.get('direction')}. Index order is value order for every "
            "tool that takes a ramp, so shift_along_ramp and outline_smart will move a "
            "block the wrong way here."
        )
    for tie in mono.get("ties", []):
        out.append(
            f"Entries {tie} and {tie + 1} sit at the same lightness, so a step along the "
            "ramp between them is not a step in value."
        )
    for pair in (lints.get("step_evenness") or {}).get("imperceptible_pairs", []):
        first, second = pair["colors"]
        out.append(
            f"Entries {pair['at']} and {pair['at'] + 1} ({first} and {second}) differ by "
            f"dE {pair['de']:.2f}, under the {DE_IMPERCEPTIBLE:.1f} below which a colour "
            "difference is not visible at all. One of the two is a palette entry that buys "
            "nothing; drop it, or widen light_range so the step lands somewhere."
        )
    # Deliberately nothing from `step_contrast` or `hue_shift_direction`: both are reported
    # and neither is judged. The reasons are in their docstrings and in `DISCARDED`.
    return out


# ================================================================ value structure (notan)
# The one measure here that asks whether craft is present rather than whether a defect is.
#
# SOURCED, for why this is measured on value and not on hue: Huang (2007), "Effects of icon
# size, hue, saturation, background colour and luminance contrast on icon legibility",
# Perceptual and Motor Skills 104(1), a factorial study over exactly those five factors. It
# found that higher luminance contrast promotes legibility while chromaticity does not. At
# sprite scale that is the whole argument for grouping by luminance: value is the
# measurement and hue is decoration.

# Luminance levels are clustered exactly, by dynamic programming, which costs O(k n^2) in
# the number of *distinct* luminances. Pixel art has a palette, so n is small: the five
# reference sprites run 5, 36, 47, 49 and 5 distinct colours. Above this cap the levels are
# merged pairwise into weighted buckets first, so a photograph degrades instead of hanging.
#
# UNVALIDATED: 256 is chosen as a number that cannot fire on pixel art, not as a number
# with a perceptual meaning. It is five times the largest reference palette here and twice
# the largest palette Aseprite's indexed mode offers for a sprite of this kind. Nothing in
# this repository reaches it, so nothing in this repository is measured through the fallback.
MAX_CLUSTER_LEVELS = 256

# UNVALIDATED: "grouped, not scattered" needs a summary of a component-size distribution,
# and the count of components needed to cover this share of a value group is the summary
# chosen. It is not a pass/fail line: it is reported, and the reason for a share rather than
# a pixel count is that a pixel count would be a second threshold that scales with sprite
# size. 90 percent leaves room for the single-pixel specular highlights and the odd
# anti-aliased corner that correct art has, without needing a minimum component size, which
# would be a threshold of its own.
COVERAGE_SHARE = 0.90


def _drawn_histogram(grid: Grid) -> dict[tuple[int, int, int, int], int]:
    counts: dict[tuple[int, int, int, int], int] = {}
    for row in grid:
        for colour in row:
            pixel = _rgba(colour)
            if pixel[3] > 0:
                counts[pixel] = counts.get(pixel, 0) + 1
    return counts


def _levels(counts: dict[tuple[int, int, int, int], int]) -> list[tuple[float, int]]:
    """Distinct relative luminances and how many pixels carry each, darkest first."""
    merged: dict[float, int] = {}
    for pixel, n in counts.items():
        value = quality.luminance(pixel)
        merged[value] = merged.get(value, 0) + n
    levels = sorted(merged.items())
    while len(levels) > MAX_CLUSTER_LEVELS:
        folded: list[tuple[float, int]] = []
        for index in range(0, len(levels) - 1, 2):
            (lum_a, n_a), (lum_b, n_b) = levels[index], levels[index + 1]
            total = n_a + n_b
            folded.append(((lum_a * n_a + lum_b * n_b) / total, total))
        if len(levels) % 2:
            folded.append(levels[-1])
        levels = folded
    return levels


def _natural_breaks(levels: list[tuple[float, int]], groups: int) -> list[int]:
    """Jenks natural breaks over weighted 1-D points: the exact optimum, by DP.

    Equivalent to 1-D k-means run to the global optimum rather than to a fixed point from
    some initialisation: both minimise the within-class weighted sum of squared deviations,
    and in one dimension the classes of the optimum are contiguous in sorted order, so a
    dynamic program finds it outright. Deterministic by construction, which `cluster_by_luminance`
    in `core.ramps` achieves a different way, by seeding k-means at weighted quantiles.

    Returns the index in `levels` at which each group starts.
    """
    n = len(levels)
    groups = min(groups, n)
    if groups <= 1:
        return [0]
    # Prefix sums of weight, weight * x and weight * x^2, so the cost of any contiguous run
    # is O(1): sum(w x^2) - sum(w x)^2 / sum(w) is its weighted sum of squared deviations.
    weight = [0.0] * (n + 1)
    first = [0.0] * (n + 1)
    second = [0.0] * (n + 1)
    for index, (value, count) in enumerate(levels):
        weight[index + 1] = weight[index] + count
        first[index + 1] = first[index] + count * value
        second[index + 1] = second[index] + count * value * value

    def cost(lo: int, hi: int) -> float:
        """Within-class deviation of levels[lo:hi]."""
        w = weight[hi] - weight[lo]
        if w <= 0:
            return 0.0
        s = first[hi] - first[lo]
        return max(0.0, (second[hi] - second[lo]) - s * s / w)

    best = [[math.inf] * (n + 1) for _ in range(groups + 1)]
    cut = [[0] * (n + 1) for _ in range(groups + 1)]
    best[0][0] = 0.0
    for k in range(1, groups + 1):
        for hi in range(k, n + 1):
            for lo in range(k - 1, hi):
                if best[k - 1][lo] == math.inf:
                    continue
                candidate = best[k - 1][lo] + cost(lo, hi)
                if candidate < best[k][hi]:
                    best[k][hi], cut[k][hi] = candidate, lo
    starts, hi = [], n
    for k in range(groups, 0, -1):
        starts.append(cut[k][hi])
        hi = cut[k][hi]
    return sorted(starts)


def _components(labelled: list[list[int]], label: int) -> list[int]:
    """Sizes of the 4-connected components carrying `label`, largest first.

    Orthogonal connectivity, the same choice `quality.isolated_pixels` makes and for the
    same reason: a checkerboard dither is connected diagonally and nothing else, so counting
    diagonals would score a dithered band as one solid shape when it is the one thing in
    pixel art that deliberately is not.
    """
    height = len(labelled)
    width = len(labelled[0]) if height else 0
    seen = [[False] * width for _ in range(height)]
    sizes = []
    for y in range(height):
        for x in range(width):
            if labelled[y][x] != label or seen[y][x]:
                continue
            size = 0
            queue = deque([(x, y)])
            seen[y][x] = True
            while queue:
                cx, cy = queue.popleft()
                size += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if (0 <= nx < width and 0 <= ny < height
                            and not seen[ny][nx] and labelled[ny][nx] == label):
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            sizes.append(size)
    return sorted(sizes, reverse=True)


def _shape(sizes: list[int]) -> dict:
    """The component-size distribution of one value group, summarised."""
    total = sum(sizes)
    if not total:
        return {"pixels": 0, "components": 0, "largest_share": 0.0, "components_for_90pct": 0}
    needed, seen = 0, 0
    for size in sizes:
        needed += 1
        seen += size
        if seen >= total * COVERAGE_SHARE:
            break
    return {
        "pixels": total,
        "components": len(sizes),
        "largest_share": round(sizes[0] / total, 3),
        "components_for_90pct": needed,
    }


def _label_grid(grid: Grid, bounds: list[float]) -> list[list[int]]:
    """A grid of group indices, with -1 where nothing is drawn.

    `bounds` are the upper luminances of every group but the last, ascending.
    """
    labelled = []
    for row in grid:
        out_row = []
        for colour in row:
            pixel = _rgba(colour)
            if pixel[3] == 0:
                out_row.append(-1)
                continue
            value = quality.luminance(pixel)
            group = 0
            while group < len(bounds) and value > bounds[group]:
                group += 1
            out_row.append(group)
        labelled.append(out_row)
    return labelled


def value_groups(grid: Grid, groups: int = 3) -> dict:
    """The drawn pixels clustered into `groups` values, with the shape of each group.

    The notan test. A painting is designed in three values before it is coloured, and the
    craft rule about them is not what the shares are but how they are *arranged*: a value
    group should be a few large shapes, not a scatter. A sprite whose three value groups
    shatter into dozens of components has no value structure, whatever its palette is, and
    nothing else in this codebase notices. `quality.row_structure` sees a silhouette fuse;
    this sees a silhouette that is articulated and has no design inside it.

    Each group comes back with its share of the drawn pixels, its luminance range, how many
    4-connected components it breaks into, the largest one's share of the group, and how
    many components it takes to cover 90 percent of it. The last number is the one to read:
    a component count alone is dominated by single-pixel highlights, and the coverage count
    is not.

    **Construct gate.** The defect: a drawing with no value design, where light and dark are
    distributed per-pixel rather than massed. Can correct art produce a high component
    count? **Yes, easily, and this is the measure's hard limit.** A dithered band is a
    checkerboard of two values and is correct practice; this repository's reference orb has
    one. A 112x72 scene of masonry is correct and has as many components as it has stones.
    **Ranking gate: failed, and the measured numbers are not close.** Components per value
    group, darkest first:

        orb        (good)    1,  1,  1
        item_sheet (good)   15, 32, 19
        dungeon    (good)   25, 75, 53
        golem      (bad)     3, 33, 23
        skeleton   (bad)     5,  6, 19

    The known-good dungeon scatters into 75 components in its middle value where the
    known-bad golem scatters into 33, and the known-bad skeleton is tidier than the
    known-good item sheet in two groups of three. No threshold on the count can order
    these, so there is no threshold and no reading. Normalising by drawn area or by sprite
    size would be tuning around the gate rather than passing it, and it would not help: a
    room with things in it and a figure are different kinds of picture, and this measure
    cannot tell which it is looking at.
    **Specificity.** As a reading, none, because there is no reading. As a measurement it is
    exact, and it is worth reporting: the orb's three groups being one component each is the
    cleanest value structure available, and the golem's darkest group holding 74 percent of
    the drawing with 99.8 percent of that in a single component is its recorded defect
    (a keyline that has become the drawing) visible from a second direction.
    **Thresholds.** `COVERAGE_SHARE` is UNVALIDATED and is a summary statistic rather than
    a line. `MAX_CLUSTER_LEVELS` is UNVALIDATED and unreachable by pixel art. The clustering
    itself has no threshold: the breaks are wherever the optimum puts them.
    """
    if groups < 2:
        raise ValueError("a value grouping needs at least 2 groups")
    counts = _drawn_histogram(grid)
    if not counts:
        return {"groups": [], "breaks": [], "drawn_pixels": 0, "distinct_colors": 0}
    levels = _levels(counts)
    starts = _natural_breaks(levels, groups)
    # The boundary between two groups is the midpoint of the gap between them, so a
    # luminance that is not in the art still lands in the group a person would put it in.
    bounds = [
        (levels[start - 1][0] + levels[start][0]) / 2.0
        for start in starts[1:]
    ]
    labelled = _label_grid(grid, bounds)
    drawn = sum(counts.values())
    out = []
    for index in range(len(starts)):
        members = levels[starts[index]:(starts[index + 1] if index + 1 < len(starts) else None)]
        shape = _shape(_components(labelled, index))
        out.append({
            "share": round(shape["pixels"] / drawn, 3) if drawn else 0.0,
            "lum_range": [round(members[0][0], 4), round(members[-1][0], 4)] if members else None,
            **shape,
        })
    return {
        "groups": out,
        "breaks": [round(value, 4) for value in bounds],
        "drawn_pixels": drawn,
        "distinct_colors": len(counts),
    }


def notan(grid: Grid) -> dict:
    """The two-value reduction: everything posterised at the median drawn luminance.

    Notan in the strict sense is two values, not three, and the reduction is the oldest
    test in the trade: squint until the picture is black and white and see whether the
    shapes still read. Posterising at the *median* rather than at the midpoint of the range
    is what makes it a test of design rather than of exposure, because it splits the pixels
    in half by construction, so a sprite cannot pass by being uniformly dark.

    Reported per half: the share, the component count, the largest component's share and the
    components needed to cover 90 percent. The candidate reading was the light half's
    largest component share, on the grounds that it asks the "is there one read" question: a
    figure lit from one side has one large light mass, and a figure with light scattered
    over it has none.

    **Construct gate.** The defect: a drawing whose two-value reduction has no large shapes,
    so there is nothing to read at a glance. Can correct art produce a low largest-component
    share? A deliberately dispersed texture can, and a tiling noise tile certainly would, so
    the gate holds only for pictures with a subject. That bound alone would have been
    survivable. The next gate was not.
    **Ranking gate: failed.** The light half's largest component share, measured:

        orb        (good)   1.000
        skeleton   (bad)    0.496
        dungeon    (good)   0.461
        item_sheet (good)   0.249
        golem      (bad)    0.226

    The known-bad skeleton sits **above two of the three known-good examples**, and the two
    known-bad sprites sit at opposite ends of the range. There is no threshold that orders
    this, in either direction, so the reading is discarded outright rather than inverted or
    scoped. The reason it fails generalises: the skeleton's light half is a compact skull
    and the item sheet's is five separate objects on one sheet, and "how many lit masses are
    there" is a property of the subject, not of the craft.
    **Specificity.** No reading, so none. The measurements are reported.
    **Thresholds.** The median is not a threshold; it is a property of the data, and that is
    the point of using it. `COVERAGE_SHARE` is UNVALIDATED as above.
    """
    counts = _drawn_histogram(grid)
    if not counts:
        return {"median": 0.0, "dark": _shape([]), "light": _shape([]), "drawn_pixels": 0}
    levels = _levels(counts)
    drawn = sum(counts.values())
    # The weighted median: the luminance at which half the drawn pixels are no brighter.
    seen = 0
    median = levels[-1][0]
    for value, count in levels:
        seen += count
        if seen * 2 >= drawn:
            median = value
            break
    # Dark is "no brighter than the median", so the median level itself is dark. A sprite
    # whose median colour covers most of it therefore comes back lopsided, which is true of
    # it rather than an artefact of the split.
    labelled = _label_grid(grid, [median])
    return {
        "median": round(median, 4),
        "dark": _shape(_components(labelled, 0)),
        "light": _shape(_components(labelled, 1)),
        "drawn_pixels": drawn,
    }


# ====================================================== colour vision deficiency re-check
# A sprite that separates its parts by hue alone passes every other measurement in this
# module and in `core.quality`, and is unreadable to about one man in twelve.
#
# SOURCED: Vienot, Brettel and Mollon (1999), "Digital video colourmaps for checking the
# legibility of displays by dichromats", Color Research and Application 24(4), 243-252. For
# protanopia and deuteranopia the paper gives a simplified single-matrix form, documented as
# giving results reasonably similar to the full Brettel-Vienot-Mollon method for those two
# types. Tritanopia is deliberately absent: the simplification does not hold for it, it
# needs the two-plane method, and it is an order of magnitude rarer.
#
# The matrices below are the projection composed with the RGB-to-LMS transforms, so they act
# on **linear** RGB. Two structural invariants say so, and `tests/test_ramp_lint.py` asserts
# both rather than taking them on trust:
#
#   * every row sums to 1, so the white point is a fixed point, and with it the whole
#     neutral axis. A projection that moved grey would not be a dichromat simulation, it
#     would be a tint;
#   * rows 0 and 1 are identical, so red and green outputs are always equal. That is what it
#     means for two primaries to be confused: the simulated image lies on the dichromatic
#     surface, which is a two-dimensional subspace of the display's gamut.
#
# The same coefficients are often seen applied to gamma-encoded values, which is a shortcut
# rather than a variant: the projection is linear in LMS, LMS is linear in linear RGB, and
# it is linear in neither of those in sRGB's encoding. Applying it to encoded values
# lightens the shadows, and the shadows are where a keyline lives.
_CVD_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": (
        (0.11238, 0.88762, 0.00000),
        (0.11238, 0.88762, 0.00000),
        (0.00401, -0.00401, 1.00000),
    ),
    "deuteranopia": (
        (0.29275, 0.70725, 0.00000),
        (0.29275, 0.70725, 0.00000),
        (-0.02234, 0.02234, 1.00000),
    ),
}

CvdKind = Literal["protanopia", "deuteranopia"]


def simulate_cvd(rgb: tuple[int, int, int], kind: CvdKind) -> tuple[int, int, int]:
    """One colour as a protanope or a deuteranope sees it.

    The matrix acts on linear RGB, so the sRGB transfer function is undone first and redone
    after. Applying it to gamma-encoded values instead is a common error and produces
    simulations that are too light in the shadows, which for this module would be the worst
    possible direction to be wrong in: the shadows are where a keyline lives.
    """
    if kind not in _CVD_MATRICES:
        raise ValueError(f"unknown deficiency {kind!r}; expected one of {sorted(_CVD_MATRICES)}")
    linear = [_srgb_to_linear(channel / 255) for channel in rgb]
    matrix = _CVD_MATRICES[kind]
    out = []
    for row in matrix:
        value = sum(coefficient * channel for coefficient, channel in zip(row, linear, strict=True))
        out.append(max(0, min(255, round(_linear_to_srgb(max(0.0, min(1.0, value))) * 255))))
    return (out[0], out[1], out[2])


def _simulate_grid(grid: Grid, kind: CvdKind) -> Grid:
    cache: dict[str, str] = {}
    out = []
    for row in grid:
        out_row = []
        for colour in row:
            if colour not in cache:
                r, g, b, a = _rgba(colour)
                sr, sg, sb = simulate_cvd((r, g, b), kind)
                cache[colour] = f"#{sr:02x}{sg:02x}{sb:02x}{a:02x}"
            out_row.append(cache[colour])
        out.append(out_row)
    return out


def _touching_pairs(grid: Grid) -> set[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """Every pair of distinct drawn colours that are orthogonally adjacent somewhere.

    Pairs that touch, not every pair in the palette: a contrast ratio between two colours on
    opposite sides of a sprite says nothing about whether those two regions come apart,
    which is the judgement `quality.separator_share` already makes for the keyline and the
    same one made here for every boundary.
    """
    at = {}
    for y, row in enumerate(grid):
        for x, colour in enumerate(row):
            pixel = _rgba(colour)
            if pixel[3] > 0:
                at[(x, y)] = pixel
    pairs = set()
    for (x, y), pixel in at.items():
        for dx, dy in ((1, 0), (0, 1)):
            other = at.get((x + dx, y + dy))
            if other is not None and other != pixel:
                pairs.add((pixel, other) if pixel < other else (other, pixel))
    return pairs


def cvd_recheck(grid: Grid) -> dict:
    """Whether the sprite's boundaries survive protanopia and deuteranopia.

    Two measurements of the same simulated image, because they answer different questions.

    `collapsed_pairs` is the sharp one: pairs of colours that **touch** in the sprite, are
    comfortably distinct in normal vision (CIEDE2000 at or above the acceptability
    threshold), and fall under the perceptibility threshold once simulated. A pair like that
    is a boundary the artist drew in a channel the dichromat does not have, and it is
    invisible to every other measurement here, because in normal vision the sprite is
    correct.

    `notan` is the broader one, the two-value reduction re-run on the simulated image: if
    the value design survives, the two-value shapes come back nearly unchanged, and if the
    design was carried by hue they do not. **It is much the weaker of the two and its
    sensitivity is worth stating exactly.** It came back unchanged on all five reference
    sprites, and unchanged on a sprite built deliberately to separate two equal halves by
    hue alone, because the two-value split is defined by the *median* and a two-colour
    image is split in half by its median whatever the colours are. What it does detect is a
    simulation **reordering** luminances across the median: on a constructed sprite whose
    bright red outranks a mid grey normally and falls below it once simulated, the light
    half goes from 15 pixels in 5 scattered components to 39 pixels in 1. So it is a real
    measure of a narrower thing than its name suggests, and the pair test below is what
    actually catches hue-only separation.

    **Why the pair test is CIEDE2000 and not the contrast ratio.** It was written with
    `quality.contrast_ratio` first, and the measurement showed that to be the wrong
    instrument. Composing the Vienot projection with WCAG's own luminance coefficients gives
    effective weights of (0.270, 0.658, 0.072) for deuteranopia against (0.213, 0.715,
    0.072) normally: **deuteranopia barely changes relative luminance at all**, so a
    luminance ratio measured on a deuteranopia simulation is nearly the ratio measured on the
    original, and the test is blind to the commonest deficiency. Protanopia does move
    luminance, halving red's weight to 0.105, so a ratio test would have found protanopic
    collapse and reported deuteranopia as clean, which is a confident wrong answer rather
    than a gap. A dichromat loses *hue*, and the measure has to be one that can see hue.
    The contrast ratio is reported alongside each pair so the effect is visible in the data
    rather than only in this paragraph, and on the two constructed collapses below it is
    stark: `#c00000` against `#008000` goes from dE 68.04 to dE 1.11 under deuteranopia
    while its contrast ratio goes from 1.26:1 to 1.00:1, which is to say the ratio was
    already under 3:1 and a WCAG-gated test would never have looked at the pair at all.

    **Construct gate.** The defect: a boundary that exists only in a channel a dichromat
    does not have. Can correct art produce a collapsed pair? The gate is passed only because
    of the *distinct in normal vision* condition. Without it the measure would fire on every
    sprite in existence, because adjacent steps of one ramp touch everywhere and are
    deliberately close; with it, the only pairs counted are ones the artist made clearly
    distinguishable and the simulation takes apart. The residual false positive is a pair
    that touches along a few pixels incidentally rather than as a boundary, which is why the
    pairs are reported and not merely counted.
    **Ranking gate.** Not applicable and should not be forced: accessibility is a different
    axis from craft, and this says nothing about whether a sprite is good. It fires on none
    of the five references, so it orders nothing.
    **Specificity.** Fires on **0 of 3 known-good and 0 of 2 known-bad**, across 584
    touching colour pairs in total, which is the highest specificity of anything in this
    module. It is not vacuous: on a constructed 16x8 sprite of two hue-separated halves it
    fires, at dE 68.04 to 1.11 under deuteranopia for `#c00000` against `#008000`, and at dE
    69.91 to 1.23 under protanopia for `#fe0000` against `#006400`. That the protanopic
    collapse needs the darker green is itself a check on the matrices: a protanope sees red
    much darker, so a darker green is what matches it.
    The bound: it says two touching colours become hard to tell apart, not that the sprite
    is unreadable. A sprite whose parts are also separated by a keyline survives a collapsed
    pair, and the measure cannot see the keyline doing that work. It is also blind to a
    perfectly isoluminant hue boundary in the sense that matters least: such a pair is
    caught, but a pair that is *already* indistinguishable in normal vision is skipped by
    the precondition, correctly, since nothing was lost.
    **Thresholds.** `DE_ACCEPTABILITY` and `DE_PERCEPTIBLE` are SOURCED. The Vienot matrices
    are SOURCED. No other number.
    """
    pairs = _touching_pairs(grid)
    labs = {}

    def lab(pixel: tuple[int, int, int, int], kind: CvdKind | None) -> tuple[float, float, float]:
        key = (pixel, kind)
        if key not in labs:
            rgb = pixel[:3] if kind is None else simulate_cvd(pixel[:3], kind)
            labs[key] = to_lab(rgb)  # type: ignore[arg-type]
        return labs[key]

    result: dict = {
        "touching_pairs": len(pairs),
        "normal": {"notan": notan(grid)},
    }
    for kind in ("deuteranopia", "protanopia"):
        collapsed = []
        for first, second in pairs:
            before = ciede2000(lab(first, None), lab(second, None))
            if before < DE_ACCEPTABILITY:
                continue
            after = ciede2000(lab(first, kind), lab(second, kind))  # type: ignore[arg-type]
            if after >= DE_PERCEPTIBLE:
                continue
            collapsed.append({
                "colors": [f"#{first[0]:02x}{first[1]:02x}{first[2]:02x}",
                           f"#{second[0]:02x}{second[1]:02x}{second[2]:02x}"],
                "de_before": round(before, 2),
                "de_after": round(after, 2),
                # Reported to show what a luminance-only test would have said about the
                # same pair, which for deuteranopia is "nothing changed".
                "ratio_before": round(quality.contrast_ratio(first, second), 2),
                "ratio_after": round(quality.contrast_ratio(
                    (*simulate_cvd(first[:3], kind), 255),  # type: ignore[arg-type]
                    (*simulate_cvd(second[:3], kind), 255),  # type: ignore[arg-type]
                ), 2),
            })
        collapsed.sort(key=lambda item: item["de_after"])
        result[kind] = {
            "collapsed_pairs": len(collapsed),
            "worst": collapsed[:4],
            "notan": notan(_simulate_grid(grid, kind)),  # type: ignore[arg-type]
        }
    return result


def cvd_readings(recheck: dict) -> list[str]:
    """One sentence per deficiency whose boundaries collapsed."""
    out = []
    for kind in ("deuteranopia", "protanopia"):
        found = recheck.get(kind) or {}
        collapsed = found.get("collapsed_pairs", 0)
        if not collapsed:
            continue
        worst = (found.get("worst") or [{}])[0]
        colours = worst.get("colors", ["?", "?"])
        out.append(
            f"{collapsed} pair(s) of touching colours are clearly different in normal "
            f"vision and not under {kind}: {colours[0]} against {colours[1]} goes from "
            f"dE {worst.get('de_before', 0):.1f} to dE {worst.get('de_after', 0):.1f}, "
            f"below the {DE_PERCEPTIBLE:.1f} at which a difference becomes visible at all. "
            "That boundary is drawn in hue, so it is not there for roughly one viewer in "
            "twelve. Separate those two in value as well, or put a keyline between them."
        )
    return out


# ============================================================================== DISCARDED
# Measures that were built, measured and thrown away. They are results: the reason each one
# fails generalises, and the next person to think of it should find out here rather than by
# shipping it.
#
# 1. **A threshold on step evenness (max over min CIEDE2000 step).** Discarded on the
#    construct gate. This project's own `generate_ramp(easing="perceptual")` bunches the
#    dark steps deliberately, because equal steps in HLS lightness are not equal steps to
#    the eye, and `sat_curve="peak"` makes the ends uneven on purpose as well. Measured on
#    the eleven showcase ramps the ratio runs 1.41 (`WOOD`) to 18.80 (`PARCH`), and setting
#    `PARCH` aside as a near-clip the top is 4.18 (`GOLD`). Both of those belong to
#    known-good art, so a threshold inside the range fires on correct practice and a
#    threshold above it fires on nothing. The ratio is reported.
#
# 2. **A minimum contrast between adjacent ramp steps.** Discarded on the construct gate,
#    before any threshold was chosen. A smooth eight-step ramp has adjacent WCAG ratios
#    around 1.2 by arithmetic, and any ramp whose adjacent steps all cleared 3:1 would have
#    at most three steps. The eleven showcase ramps have minimum adjacent ratios from 1.02
#    to 1.66: a single threshold at 1.7 or above fires on all eleven. APCA's Lc 15 for
#    non-text is the right *shape* of threshold for this question and is not used, because
#    this module cannot verify an APCA implementation against a reference the way it
#    verifies CIEDE2000 against 33 published pairs. The ratios are reported.
#
# 3. **A 3:1 minimum on the ramp's end-to-end span.** Discarded on the construct gate, after
#    it looked like the best reading in the module. Exactly one of the eleven ramps fails
#    it, at 2.70, and that one belongs to a known-bad sprite while the other ten run 7.67 to
#    15.43. It was withdrawn because a correct ramp reaches 2.70: a high-key material is
#    legitimately declared as a ramp over the top of the value range with the dark supplied
#    by a separate keyline, which is what `scripts/showcase/skeleton.py` does, declaring
#    `BONE` and `DARK = "#241f2b"` side by side. The skeleton's recorded defect is a keyline
#    covering 50.3 percent of it, so the reading fired on the right sprite for the wrong
#    reason. As a continuous ordering it fails the ranking gate as well: the golem's `STONE`
#    (bad) spans 12.51 against the item sheet's `WOOD` (good) at 7.67.
#
# 4. **A threshold on components per value group.** Discarded on the ranking gate. Counting
#    4-connected components per value group, darkest first, the known-good `dungeon` runs
#    25, 75, 53 while the known-bad `golem` runs 3, 33, 23 and the known-bad `skeleton` runs
#    5, 6, 19 against the known-good `item_sheet`'s 15, 32, 19. The good examples occupy
#    both ends of the range. Normalising by area or by sprite size was not attempted: it
#    would be tuning around the gate, and a scene and a figure are different kinds of
#    picture that this measure cannot tell apart. The counts are reported.
#
# 5. **A threshold on the notan light half's largest component share.** Discarded on the
#    ranking gate. Measured: orb (good) 1.000, skeleton (bad) 0.496, dungeon (good) 0.461,
#    item_sheet (good) 0.249, golem (bad) 0.226. A known-bad sprite outranks two of the
#    three known-good ones and the two known-bad sprites sit at opposite ends, so no
#    threshold orders this in either direction. The reason generalises: how many lit masses
#    a picture has is a property of its subject.
#
# 6. **The simulated two-value reduction as a reading.** Kept as a measurement, given no
#    reading. It moved on none of the five references and on none of the constructed
#    hue-separated sprites, because a two-colour image is split in half by its own median
#    whatever its colours are. It does move when a simulation reorders luminances across the
#    median, which is a narrower thing than "the value design collapsed", and the pair test
#    in `cvd_recheck` is what carries that question.
#
# 7. **A threshold on the most-used colour's share, in any form.** Not rebuilt here. It was
#    withdrawn from `core.quality` once already, with the numbers written into that module:
#    it fired at 40 percent on the clean reference orb, which spends 51 percent on one
#    midtone because a five-step ramp on a sphere must, and never fired on the figure it was
#    written for, which spends 19.9. Dominance relative to an even split fails the same way,
#    2.0 for the orb against 1.8 for the figure. Value grouping above is the measure that
#    question was reaching for.
#
# 8. **Colour harmony template fitting.** Not built. Harmony is a property of the palette,
#    the palette is declared by the caller, and fitting a hue template to the eight colours
#    of a sprite fits more parameters than there is data to fit them with.
#
# 9. **Colourfulness category boundaries.** Not built. The metric and its category
#    boundaries were fitted on natural photographs, and indexed art with a 16-colour palette
#    is not a sample from that population.
