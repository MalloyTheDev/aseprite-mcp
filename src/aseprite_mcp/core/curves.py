"""Tone curves: a list of control points turned into a 256-entry lookup table.

The precise tonal control `adjust_brightness_contrast` lacks. Brightness moves every tone
by the same amount and contrast pivots them all around the middle; a curve says what each
input tone becomes, so the shadows can be lifted without touching the highlights, or a
flat midrange pulled apart while the ends stay pinned.

**Why this is here rather than a call to Aseprite's own `ColorCurve` command.** Two
reasons, and the second is the one that decided it:

1. Every other per-pixel effect in this server runs through the drawing path, so it is
   clipped to the selection, counted in `pixels_written`, and resolved against an indexed
   palette or a grayscale sprite the same way a drawn pixel is. A command runs outside
   all of that, on whatever Aseprite considers the active cel.
2. The curve itself is arithmetic, and arithmetic belongs where it can be tested without
   launching an editor.

Nothing is lost by reimplementing it, because the behaviour was measured rather than
guessed: Aseprite's Color Curve interpolates **linearly** between control points and
**truncates**, and outside the span of the points it **holds the end values**. Checked
against the editor on a grey ramp: with points (0,0) (128,192) (255,255) it sends 36 to
54, 73 to 109 and 146 to 200, which is linear with truncation and not rounding (200.93
arrives as 200, not 201); with points (64,0) (192,255) it sends everything at or below 64
to 0 and everything at or above 192 to 255. `test_curves.py` pins all of it.
"""

from __future__ import annotations

from itertools import pairwise

# A curve is described by its corners, and a tone has 256 possible values, so more
# control points than that cannot describe anything new.
MAX_CURVE_POINTS = 256


def curve_table(points: list) -> list[int]:
    """The 256 output tones a curve maps its inputs to, index 0 to 255.

    `points` is a list of `[x, y]` pairs, each from 0 to 255, ordered by a strictly
    increasing `x`. One point alone is a constant: every tone becomes its `y`, which is
    what Aseprite does and is occasionally what you want (flattening a channel).

    Raises `ValueError` for a malformed curve, which is the type `core` refuses values
    with, so the message reaches the caller rather than being masked as a crash.
    """
    cleaned = _checked(points)
    if len(cleaned) == 1:
        return [cleaned[0][1]] * 256

    table: list[int] = []
    for tone in range(256):
        if tone <= cleaned[0][0]:
            table.append(cleaned[0][1])
            continue
        if tone >= cleaned[-1][0]:
            table.append(cleaned[-1][1])
            continue
        for (x0, y0), (x1, y1) in pairwise(cleaned):
            if x0 <= tone <= x1:
                # Truncated, not rounded: measured against the editor, which sends 200.93
                # to 200. int() rather than math.floor because y never goes negative.
                table.append(int(y0 + (y1 - y0) * (tone - x0) / (x1 - x0)))
                break
    return table


def _checked(points: list) -> list[tuple[int, int]]:
    """`points` as integer pairs, or a refusal naming what is wrong with them."""
    if not isinstance(points, list) or not points:
        raise ValueError(
            "points is empty; give a curve as [[x, y], ...] with each value from 0 to "
            "255, for example [[0, 0], [128, 192], [255, 255]] to lift the midtones.")
    if len(points) > MAX_CURVE_POINTS:
        raise ValueError(
            f"points has {len(points)} control points; a tone has only 256 possible "
            f"values, so at most {MAX_CURVE_POINTS} can describe anything.")

    out: list[tuple[int, int]] = []
    for position, point in enumerate(points):
        pair = list(point) if isinstance(point, (list, tuple)) else None
        if pair is None or len(pair) != 2:
            raise ValueError(
                f"points[{position}] is {point!r}; each control point is a pair "
                "[input, output], as in [128, 192].")
        for value in pair:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"points[{position}] is {point!r}; a control point is two whole "
                    "numbers, and a tone is not fractional.")
            if not 0 <= value <= 255:
                raise ValueError(
                    f"points[{position}] is {point!r}; a tone runs from 0 to 255.")
        out.append((pair[0], pair[1]))

    for position, ((x0, _), (x1, _)) in enumerate(pairwise(out)):
        if x1 <= x0:
            # Named rather than sorted silently: two outputs for one input is not a
            # curve, and reordering what the caller wrote would hide the mistake.
            raise ValueError(
                f"points[{position}] and points[{position + 1}] have inputs {x0} and "
                f"{x1}; the inputs have to climb, so each one has a single output.")
    return out
