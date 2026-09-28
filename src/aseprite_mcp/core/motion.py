"""Spreading one movement across frames: pure arithmetic, no Aseprite.

Cel positions are whole pixels, so a smooth curve has to become integers somewhere, and
where that happens decides whether the motion reads as motion. Rounding each step on its
own produced a measured series of 5, 4, 5, 5, 4, 5, 5, 4, 5 for a straight slide: the
total is right and it reads as a limp, because the discarded fraction is thrown away and
reintroduced at every step. Rounding the running position instead lets each step carry the
last one's leftover, which is what a Bresenham line does, and the same slide comes out as
5, 5, 4, 5, 5, 5, 4, 5, 5: never more than a pixel from the ideal, and never doubling back
along an axis.

The other thing worth stating once: easing belongs in spacing, not in duration. A curve
applied to both is applied twice, and reads as slow motion rather than as weight.
"""

from __future__ import annotations

import math
from itertools import pairwise

# Named for the movement they model rather than for their algebra, because that is what
# the caller is choosing.
EASINGS = ("linear", "ease_in", "ease_out", "ease_in_out", "gravity")


def _eased(ease: str, t: float) -> float:
    if ease == "linear":
        return t
    if ease == "ease_in":
        return t * t
    if ease == "ease_out":
        return 1.0 - (1.0 - t) ** 2
    if ease == "ease_in_out":
        return t * t * (3.0 - 2.0 * t)
    if ease == "gravity":
        return t * t
    raise ValueError(f"unknown easing {ease!r}; expected one of {', '.join(EASINGS)}")


def _axis_fractions(ease: str, t: float) -> tuple[float, float]:
    """How far along each axis the movement has come at `t`.

    Every easing but one moves both axes together. `gravity` does not: a thrown object
    keeps its horizontal speed and gains vertical speed, so x stays linear while y
    accelerates. Easing both axes would make it arrive sideways, in slow motion.
    """
    if ease == "gravity":
        return t, t * t
    value = _eased(ease, t)
    return value, value


def _round_half_up(value: float) -> int:
    """Round .5 away from zero rather than to even.

    Python rounds 0.5 down and 1.5 up, so a half-pixel step would land one way or the
    other depending on where along the path it fell. Spacing should not depend on that.
    """
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def plan(
    count: int,
    dx: int,
    dy: int,
    *,
    ease: str = "linear",
    arc_height: float = 0.0,
) -> dict:
    """Place `count` frames along a movement of (dx, dy), and say how well it fits.

    Returns the integer `offsets` from the first frame (the first is always (0, 0) and
    the last is always exactly (dx, dy), whatever the rounding did on the way), the
    real-valued `ideal` path they were placed on, and `max_error_px`: the furthest any
    frame sits from where it ideally would. That last number is the honest measure of the
    rounding, and it stays below a pixel.

    `arc_height` bends the path into a parabola peaking halfway along, perpendicular to
    the straight line between the ends, on the side that lifts the cel.
    """
    if count < 2:
        raise ValueError("a movement needs at least 2 frames to be distributed over")
    if ease not in EASINGS:
        raise ValueError(f"unknown easing {ease!r}; expected one of {', '.join(EASINGS)}")

    span = count - 1
    length = math.hypot(dx, dy)
    # The normal to the path, pointing up in image space (y grows downward), so a positive
    # arc_height always arcs over the line rather than under it. A movement that goes
    # nowhere has no direction to be perpendicular to, so it simply lifts.
    if length == 0:
        normal = (0.0, -1.0)
    else:
        nx, ny = -dy / length, dx / length
        normal = (nx, ny) if ny <= 0 else (-nx, -ny)

    ideal: list[tuple[float, float]] = []
    for index in range(count):
        t = index / span
        fx, fy = _axis_fractions(ease, t)
        x, y = fx * dx, fy * dy
        if arc_height:
            bulge = 4.0 * t * (1.0 - t) * arc_height
            x += normal[0] * bulge
            y += normal[1] * bulge
        ideal.append((x, y))

    offsets = [(_round_half_up(x), _round_half_up(y)) for x, y in ideal]
    # The ends are what the caller asked for and must not be approximate.
    offsets[0] = (0, 0)
    offsets[-1] = (dx, dy)

    error = max(
        math.hypot(px - ix, py - iy)
        for (px, py), (ix, iy) in zip(offsets, ideal, strict=True)
    )
    return {"offsets": offsets, "ideal": ideal, "max_error_px": round(error, 2)}


def deltas(offsets: list[tuple[int, int]]) -> list[dict]:
    """The step between each pair of positions, which is the spacing a viewer sees."""
    series = []
    for (x0, y0), (x1, y1) in pairwise(offsets):
        step_x, step_y = x1 - x0, y1 - y0
        series.append({
            "dx": step_x,
            "dy": step_y,
            "distance": round(math.hypot(step_x, step_y), 2),
        })
    return series
