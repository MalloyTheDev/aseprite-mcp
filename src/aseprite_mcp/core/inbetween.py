"""Inbetweens: the arithmetic behind a tween and a smear, with no Aseprite in sight.

An inbetween is more than a position, which is the whole of `offset_cels`. The other
three things it does are a scale, a rotation and a fade, and a smear is the frame where
the subject is drawn along its own path instead of at one point on it. Both of those read
two cels and write new pixels, so they share a module: the easing, the rounding, the
transform matrix and the ramp matching are the same arithmetic either way.

Two things are worth stating once, because they are the reason this file exists at all.

**An inbetween interpolates a transform, not pixels.** Blending two drawings together
produces a double exposure: two silhouettes at half strength, which the eye reads as a
mistake rather than as motion. So one drawing is the source and every frame is that
drawing resampled, which is also why the error never compounds: frame nine is sampled
from the original, not from frame eight.

**A smear stays on the palette.** A trail made with alpha is a trail made of colours that
are not in the sprite, and that is the difference between pixel art and a screenshot of
pixel art with motion blur. Stepping down a declared ramp is both what keeps
`palette_conformance` at 1.0 and what a pixel artist actually draws. The matching that
does it lives here rather than in Lua, so the generated script never has to make a colour
judgement: it is handed a lookup table and asked to look things up.
"""

from __future__ import annotations

import math
from itertools import pairwise

from . import motion

# Where the transform holds still. A scale about the centre makes a ball grow in every
# direction; a scale about the bottom edge makes it squash *onto the ground*, which is
# the one that reads as weight, and it is the one `validate_loop`'s contact-edge check
# was built to confirm.
ANCHORS = ("center", "top", "bottom", "left", "right")

# Scale is eased in thousandths so it can ride the same integer arithmetic the positions
# do. A thousandth of a pixel is far below anything the raster can show, so the
# quantisation is invisible, and what it buys is a series that never doubles back.
SCALE_PRECISION = 1000

# Nearest-neighbour rotation this far from a quarter turn stops reading as a rotation and
# starts reading as noise: the sampled grid shuffles pixels along the edges without ever
# committing to a diagonal. The quarter turns themselves are exact, so the figure is the
# distance to the nearest one rather than the angle.
MIN_READABLE_ROTATION_DEG = 15

# The weights in `ramps.luminance` and in `shading.py`'s Lua `ramp_match`, repeated here
# so a step chosen in Python and a step matched in Lua agree about which colour is which.
# Unweighted RGB distance picks visibly wrong neighbours on a hue-shifted ramp, and a
# hue-shifted ramp is exactly the kind pixel art uses.
_LUMA_WEIGHTS = (0.299, 0.587, 0.114)

# The faintest a no-ramp trail may get. Alpha that reaches 0 at the tip means the last
# stretch of the smear is not there at all, so the trail measures shorter than it was
# asked for; this keeps the tip visible and the length honest.
MIN_TRAIL_ALPHA = 32

SMEAR_MODES = ("stretch", "echo")


# --------------------------------------------------------------------- eased scalars
def _whole_steps(count: int, delta: int, ease: str) -> list[int]:
    """`delta` spread over `count` frames as whole units, rounded cumulatively.

    This is `motion.plan` doing the work it already does for positions, on its y axis.
    The axis matters: `gravity` is the one easing that treats the two axes differently
    (x stays linear while y accelerates, as a thrown object does), so a scalar riding the
    x axis would silently come out linear for it.

    Rounding the running value rather than each step is the whole point, and the reason
    is in `motion`'s own docstring: a per-step rounding throws the leftover fraction away
    and reintroduces it every frame, which reads as a limp.
    """
    plan = motion.plan(count, 0, int(delta), ease=ease)
    return [dy for _, dy in plan["offsets"]]


def int_ramp(count: int, start: float, end: float, *, ease: str) -> list[int]:
    """Whole numbers from `start` to `end` over `count` frames, eased and cumulative.

    The ends come back exactly as asked for: they were chosen, and the frames between
    them are the only place approximation belongs.
    """
    base = round(start)
    values = [base + step for step in _whole_steps(count, round(end) - base, ease)]
    values[0], values[-1] = base, round(end)
    return values


def scale_ramp(count: int, start: float, end: float, *, ease: str) -> list[float]:
    """A scale factor from `start` to `end`, eased in thousandths."""
    units = int_ramp(
        count, start * SCALE_PRECISION, end * SCALE_PRECISION, ease=ease
    )
    values = [unit / SCALE_PRECISION for unit in units]
    values[0], values[-1] = float(start), float(end)
    return values


def is_monotone(values: list[float]) -> bool:
    """Whether a series only ever goes one way. Equal neighbours are allowed.

    A flat spot is what the pixel grid does to a slow scale and is not a fault; a
    reversal is, because it reads as the subject changing its mind.
    """
    steps = list(pairwise(values))
    return all(b >= a for a, b in steps) or all(b <= a for a, b in steps)


# ------------------------------------------------------------------ the transform
def _trig(degrees: float) -> tuple[float, float]:
    """Cosine and sine of a whole-degree rotation, exact at the quarter turns.

    `math.cos(math.radians(90))` is 6.1e-17 rather than 0, and a nearest-neighbour sample
    taken through that lands a quarter turn a pixel out along one axis for no reason the
    caller could see. The quarter turns are the rotations pixel art is actually drawn at,
    so they are the ones that have to be lossless.
    """
    turn = degrees % 360
    exact = {0: (1.0, 0.0), 90: (0.0, 1.0), 180: (-1.0, 0.0), 270: (0.0, -1.0)}
    if turn in exact:
        return exact[turn]
    radians = math.radians(turn)
    return (math.cos(radians), math.sin(radians))


def forward_transform(
    scale_x: float, scale_y: float, rotate_deg: float
) -> tuple[float, float, float, float]:
    """The 2x2 that takes a source offset from the anchor to a destination offset.

    The order is rotate-after-scale: the drawing is squashed along its own axes and the
    squashed result is then tilted, which is how a squash with a tilt is drawn. Scaling
    after rotating would shear it instead.

    Row-major: (m00, m01, m10, m11). A positive angle turns clockwise on screen, because
    y grows downward in image space and clockwise is what "rotate 15 degrees" means to
    the person asking.
    """
    cos, sin = _trig(rotate_deg)
    return (
        cos * scale_x, -sin * scale_y,
        sin * scale_x, cos * scale_y,
    )


def inverse_transform(
    scale_x: float, scale_y: float, rotate_deg: float
) -> tuple[float, float, float, float]:
    """The inverse of `forward_transform`, which is what the sampler needs.

    Resampling walks the *destination* and asks where each pixel came from, because
    walking the source leaves holes wherever the scale is above 1: a 3x scale would write
    one pixel in nine and call the rest transparent.
    """
    cos, sin = _trig(rotate_deg)
    return (
        cos / scale_x, sin / scale_x,
        -sin / scale_y, cos / scale_y,
    )


def rotation_offcut(degrees: float) -> int:
    """How far a rotation sits from the nearest quarter turn, in whole degrees.

    0 means the rotation is a quarter turn and loses nothing. 97 degrees scores 7,
    because a quarter turn plus seven degrees is exactly as mushy as seven degrees.
    """
    within = round(degrees) % 90
    return int(min(within, 90 - within))


def plan_tween(
    count: int,
    *,
    scale_from: float = 1.0,
    scale_to: float = 1.0,
    scale_y_from: float | None = None,
    scale_y_to: float | None = None,
    rotate_from: float = 0.0,
    rotate_to: float = 0.0,
    opacity_from: int = 255,
    opacity_to: int = 255,
    ease: str = "linear",
) -> dict:
    """One transform per frame, plus whatever the caller should be told about them.

    Returns `steps`, each carrying the frame's scale on both axes, its whole-degree
    rotation, its cel opacity, and the forward and inverse matrices. Both matrices go
    across: the inverse does the sampling and the forward one is what says where the
    result will land, which is how the sampler knows the box to walk and therefore how
    much work it is about to do.
    """
    if count < 2:
        raise ValueError("a tween needs at least 2 frames to be distributed over")
    if ease not in motion.EASINGS:
        raise ValueError(f"unknown easing {ease!r}; expected one of {', '.join(motion.EASINGS)}")

    scale_x = scale_ramp(count, scale_from, scale_to, ease=ease)
    scale_y = scale_ramp(
        count,
        scale_from if scale_y_from is None else scale_y_from,
        scale_to if scale_y_to is None else scale_y_to,
        ease=ease,
    )
    angles = int_ramp(count, rotate_from, rotate_to, ease=ease)
    opacities = int_ramp(count, opacity_from, opacity_to, ease=ease)

    steps = []
    for index in range(count):
        sx, sy, angle = scale_x[index], scale_y[index], angles[index]
        forward = forward_transform(sx, sy, angle)
        inverse = inverse_transform(sx, sy, angle)
        steps.append({
            "scale_x": sx,
            "scale_y": sy,
            "rotate_deg": angle,
            "opacity": max(0, min(255, opacities[index])),
            "f00": forward[0], "f01": forward[1], "f10": forward[2], "f11": forward[3],
            "m00": inverse[0], "m01": inverse[1], "m10": inverse[2], "m11": inverse[3],
        })

    warnings: list[str] = []
    mushy = sorted({
        step["rotate_deg"] for step in steps
        if 0 < rotation_offcut(step["rotate_deg"]) < MIN_READABLE_ROTATION_DEG
    })
    if mushy:
        warnings.append(
            f"frames rotated to {mushy} sit within {MIN_READABLE_ROTATION_DEG} degrees of "
            "a quarter turn, and nearest-neighbour sampling that shallow shuffles the edge "
            "pixels rather than turning the shape. Rotate further per frame (fewer frames "
            "over the same angle), or redraw those poses by hand."
        )
    return {"steps": steps, "warnings": warnings}


# ------------------------------------------------- what the tween pivots and costs
# Both of these are arithmetic over the source cel's drawn bounds, and both used to exist
# only in Lua, where the pure test tier cannot reach them. The bounds themselves are the
# editor's to measure, and `tween_cels` is one Aseprite launch by design (#124), so there
# is no read pass in which Python could learn them and decide before the write happens.
#
# That leaves two options and the repository has already chosen between them once: the
# decision lives here as the authority, the Lua carries a transcription of it, and a test
# asserts the two agree on a real sprite. `lighting.filled_ellipse_points` is the
# precedent. The alternative, two implementations with nothing holding them together, is
# what produced an indexed decode that disagreed with itself (#134) and two slice readers
# of which one was incomplete (#106).
def anchor_point(bounds: dict, mode: str) -> tuple[float, float]:
    """The point a squash or stretch pivots around, within the drawn bounds.

    Measured on the pixel centres rather than the box edges: a 4px wide box spans columns
    0 to 3, so its centre is 1.5 and not 2.0. Half a pixel sounds like nothing and is the
    difference between a scaled shape that stays put and one that creeps a pixel per
    frame, which over an eight frame tween is a shape that has visibly walked.

    A `bottom` anchor is the one that matters most in practice: it is what keeps a
    squashing character's feet on the floor, and `tests/test_animation.py` asserts a
    `contact_drift_px` of 0 for exactly that case.
    """
    if mode not in ANCHORS:
        raise ValueError(f"unknown anchor {mode!r}; expected one of {', '.join(ANCHORS)}")
    centre_x = bounds["x"] + (bounds["width"] - 1) / 2.0
    centre_y = bounds["y"] + (bounds["height"] - 1) / 2.0
    if mode == "top":
        return (centre_x, float(bounds["y"]))
    if mode == "bottom":
        return (centre_x, float(bounds["y"] + bounds["height"] - 1))
    if mode == "left":
        return (float(bounds["x"]), centre_y)
    if mode == "right":
        return (float(bounds["x"] + bounds["width"] - 1), centre_y)
    return (centre_x, centre_y)


def tween_sample_budget(
    bounds: dict,
    steps: list[dict],
    *,
    anchor: str,
    canvas_width: int,
    canvas_height: int,
) -> dict:
    """How many pixels a tween would resample, and the box each frame lands in.

    The count is what the cap is enforced against, so it has to be the work the sampler
    will actually do rather than an estimate of it:

    * The source box is counted once, as the base. That pass happens whatever the
      transforms are, and on a large canvas it is already millions of reads, so a budget
      that ignored it would not bound the call it exists to bound.
    * Each frame contributes its destination box, found by pushing the source box's four
      corners through that frame's forward matrix. Corners are enough because the
      transform is affine, so the image of a rectangle is a parallelogram and its
      axis-aligned bound is the bound of its corners.
    * A pixel of slop each way, because a nearest-neighbour sample can round into the box
      from just outside it, and a dropped edge row is a shape that loses its outline.
    * Then clipped to the canvas, since nothing off it will be sampled.

    `off_canvas` is reported per frame before the clipping, because "this frame will be
    cut off" is the caller's business and is invisible once the box has been clipped to
    fit.
    """
    anchor_x, anchor_y = anchor_point(bounds, anchor)
    left, top = bounds["x"], bounds["y"]
    right, bottom = left + bounds["width"] - 1, top + bounds["height"] - 1
    corners = ((left, top), (right, top), (left, bottom), (right, bottom))

    samples = bounds["width"] * bounds["height"]
    boxes: list[dict] = []
    for step in steps:
        xs, ys = [], []
        for corner_x, corner_y in corners:
            off_x, off_y = corner_x - anchor_x, corner_y - anchor_y
            xs.append(anchor_x + step["f00"] * off_x + step["f01"] * off_y)
            ys.append(anchor_y + step["f10"] * off_x + step["f11"] * off_y)
        x0, x1 = math.floor(min(xs)), math.ceil(max(xs))
        y0, y1 = math.floor(min(ys)), math.ceil(max(ys))
        off_canvas = x0 < 0 or y0 < 0 or x1 > canvas_width - 1 or y1 > canvas_height - 1
        x0, y0 = max(0, x0 - 1), max(0, y0 - 1)
        x1 = min(canvas_width - 1, x1 + 1)
        y1 = min(canvas_height - 1, y1 + 1)
        boxes.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "off_canvas": off_canvas})
        if x1 >= x0 and y1 >= y0:
            samples += (x1 - x0 + 1) * (y1 - y0 + 1)
    return {"samples": samples, "boxes": boxes}


# ------------------------------------------------------------------------- the smear
def box_centre(bounds: dict) -> tuple[float, float]:
    """The centre of a content box, in pixel coordinates."""
    return (
        bounds["x"] + (bounds["width"] - 1) / 2.0,
        bounds["y"] + (bounds["height"] - 1) / 2.0,
    )


def smear_vector(before: dict, after: dict) -> tuple[int, int]:
    """The movement between two cels, taken from where their drawn content sits.

    The content box, not `cel.position`. Every tool here that writes a whole canvas back
    (and `tween_cels` is one of them) leaves the cel at (0, 0) on every frame, so a
    position diff reads zero while the drawing plainly moved. The box centre is also the
    measure least disturbed by the drawing changing between the two frames, which it does
    in any cycle worth smearing.

    Rounded away from zero rather than to even, like every other rounding here: the two
    centres land on a half pixel whenever the boxes differ by an odd number of pixels on
    an axis, and which way that half goes should not depend on whether the number beside
    it happens to be even.
    """
    bx, by = box_centre(before)
    ax, ay = box_centre(after)
    return (_round_half_up(ax - bx), _round_half_up(ay - by))


def _unit(vector: tuple[int, int]) -> tuple[float, float]:
    length = math.hypot(*vector)
    if length == 0:
        return (0.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def perpendicular(vector: tuple[int, int]) -> tuple[float, float]:
    """The unit normal to the movement, which is the axis a smear thins across."""
    ux, uy = _unit(vector)
    return (-uy, ux)


# A smear thins across the movement: full width where it leaves the subject, a single
# pixel at the tip. What it thins *against* used to be `box_half_extent`, one figure for
# the whole subject taken from its content box, and that is only the subject's own width
# where the subject fills its box.
#
# For anything concave the two diverge, and the failure is not the gentle one the issue
# predicted. The rule was `|perp| <= half * (1 - t) + 0.5` with `perp` measured from the
# *box centre*, so trail length is governed by distance from the box's centre line rather
# than by local width. Measured on an L (a 4px bar 20 tall, a 16px foot 4 tall, moved 6px
# right): the foot, which is the widest part of the shape and should trail most, got one
# pixel of trail on its top row and nothing on the other three, while the bar got a
# lens-shaped trail centred on an arbitrary row in its middle. The whole thing reads as a
# smeared ellipse rather than a smeared L.
#
# So the taper is measured per line across the movement, against that line's own span.
def trail_span(span_lo: float, span_hi: float, t: float) -> tuple[float, float]:
    """The perpendicular range a trail copy keeps, for a line spanning `lo` to `hi`.

    `t` runs 0 at the subject to 1 at the tip. At 0 the whole span is kept, so the trail
    leaves the subject at the subject's own width; at 1 only the span's centre survives,
    which is the single pixel a smear tapers to.

    The half pixel of slack is what makes the tip one pixel wide rather than zero: a span
    of integer pixel positions has its centre on a half-integer when the span is even, and
    without the slack an even span would taper to nothing and the trail would end in a gap.

    Each line is tapered toward **its own** centre, not the subject's. That is the whole
    fix: a shape's thin parts and wide parts both narrow toward themselves, so an L smears
    as an L.
    """
    centre = (span_lo + span_hi) / 2.0
    half = (span_hi - span_lo) / 2.0
    reach = half * (1.0 - t) + 0.5
    return (centre - reach, centre + reach)


def keeps_in_trail(perp: float, span_lo: float, span_hi: float, t: float) -> bool:
    """Whether a source pixel at `perp` survives into the trail copy at `t`."""
    low, high = trail_span(span_lo, span_hi, t)
    return low <= perp <= high


def trail_offsets(vector: tuple[int, int], strength: float) -> list[tuple[int, int]]:
    """Whole-pixel offsets stepping back along `vector`, nearest end first.

    One step per pixel of travel along the longer axis, so a horizontal movement gives a
    horizontal run of pixels and a diagonal one gives a staircase, with no repeats and no
    gaps. The same shape Bresenham draws, generated here because the length and the
    spacing are a decision rather than a raster.
    """
    reach_x, reach_y = vector[0] * strength, vector[1] * strength
    count = max(abs(round(reach_x)), abs(round(reach_y)))
    offsets = []
    for step in range(1, count + 1):
        fraction = step / count
        offsets.append((
            -_round_half_up(reach_x * fraction),
            -_round_half_up(reach_y * fraction),
        ))
    return offsets


def echo_offsets(
    vector: tuple[int, int], strength: float, steps: int
) -> list[tuple[int, int]]:
    """Whole-pixel offsets for `steps` copies spread back along `vector`.

    `motion.plan` again, so the copies are spaced by the same cumulative rounding the
    positions of a real movement get: evenly, and never doubling back.

    Empty when the reach rounds to nothing, which is the same answer `trail_offsets`
    gives: the alternative is `steps` copies all stamped on the subject at (0, 0), a call
    that draws nothing and reports success for it.
    """
    reach = (
        -_round_half_up(vector[0] * strength),
        -_round_half_up(vector[1] * strength),
    )
    if reach == (0, 0):
        return []
    plan = motion.plan(steps + 1, reach[0], reach[1], ease="linear")
    return [tuple(offset) for offset in plan["offsets"][1:]]


def _round_half_up(value: float) -> int:
    """Round .5 away from zero, matching `motion`'s own rounding."""
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def plan_smear(
    vector: tuple[int, int],
    *,
    mode: str,
    strength: float,
    steps: int,
    ramp_length: int,
) -> dict:
    """Where each copy of the subject goes, how far down the ramp, and how faint.

    Returns `plots` in the order they must be drawn: furthest from the subject first, so
    the nearer and lighter copies land on top of the further and darker ones, and the
    subject itself goes on last and comes out untouched. `shift` is how many ramp entries
    darker that copy is; `alpha` is the no-ramp fallback, applied to the source pixel's
    own alpha.
    """
    if mode not in SMEAR_MODES:
        raise ValueError(f"unknown smear mode {mode!r}; expected one of {', '.join(SMEAR_MODES)}")

    offsets = (
        trail_offsets(vector, strength) if mode == "stretch"
        else echo_offsets(vector, strength, steps)
    )

    total = len(offsets)
    plots = []
    for index, (dx, dy) in enumerate(offsets, start=1):
        fraction = index / total
        if ramp_length >= 2:
            # At least one step darker even at the near end, or the trail is invisible
            # against the subject it is trailing from.
            shift = max(1, round(fraction * (ramp_length - 1)))
            shift = min(shift, ramp_length - 1)
        else:
            shift = 0
        plots.append({
            "dx": dx, "dy": dy,
            "t": round(fraction, 6),
            "shift": shift,
            "alpha": max(MIN_TRAIL_ALPHA, round(255 * (1.0 - fraction))),
        })
    plots.reverse()

    warnings: list[str] = []
    distinct = len({(plot["dx"], plot["dy"]) for plot in plots})
    if distinct < total:
        # They are all still drawn, nearest last, so the result is right; what would be
        # wrong is reporting `copies` as a number of copies anyone can see.
        warnings.append(
            f"{total} copies were asked for but they only land on {distinct} distinct "
            "positions, because the movement is too short to space them out: the rest sit "
            "on top of each other. Ask for fewer steps, or raise strength."
        )
    return {"plots": plots, "copies": total, "distinct_positions": distinct,
            "warnings": warnings}


# ------------------------------------------------------------------- ramp matching
def nearest_ramp_index(rgb: tuple[int, int, int], ramp: list[tuple[int, int, int]]) -> int:
    """Which entry of `ramp` a colour belongs to: 0-based, weighted for the eye.

    The same weighted distance `shading.py` matches with, so a colour routed through
    here and a colour routed through there land on the same step.
    """
    best, best_distance = 0, None
    for index, entry in enumerate(ramp):
        distance = sum(
            weight * (a - b) ** 2
            for weight, a, b in zip(_LUMA_WEIGHTS, rgb, entry, strict=True)
        )
        if best_distance is None or distance < best_distance:
            best, best_distance = index, distance
    return best


def ramp_headroom(colors: list[dict], ramp: list[tuple[int, int, int]]) -> int:
    """How many steps of ramp the art has below it, at its lightest.

    A copy shifted further than this lands on the darkest entry whatever colour it came
    from, so several copies come out the same colour and read as one band. The ramp's
    length is the wrong figure to check that against: a subject sitting on the second
    step of a nine-colour ramp has one step of headroom, not eight.
    """
    if len(ramp) < 2 or not colors:
        return 0
    return max(
        nearest_ramp_index((entry["r"], entry["g"], entry["b"]), ramp)
        for entry in colors
    )


def shift_table(
    colors: list[dict], ramp: list[tuple[int, int, int]], shifts: list[int]
) -> dict[int, dict[int, dict]]:
    """For every shift in use and every colour in the art, the colour it becomes.

    Keyed by the shift first and then by the raw pixel value the sprite stores, so the
    generated Lua picks one small table per copy of the subject and then looks a colour
    up in it, deciding nothing: one matcher, in one language, with tests.

    Clamped at the dark end rather than wrapped. A trail that wraps round to the
    highlight is never what was meant and produces the opposite of the request, which is
    the same reason `shift_along_ramp` clamps.
    """
    matched = {
        int(entry["px"]): nearest_ramp_index(
            (entry["r"], entry["g"], entry["b"]), ramp
        )
        for entry in colors
    }
    table: dict[int, dict[int, dict]] = {}
    for shift in shifts:
        per_colour = {}
        for raw, index in matched.items():
            red, green, blue = ramp[max(0, index - shift)]
            per_colour[raw] = {"r": red, "g": green, "b": blue}
        table[int(shift)] = per_colour
    return table
