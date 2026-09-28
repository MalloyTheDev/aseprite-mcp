"""Frame durations as a shape in time: pure arithmetic, no Aseprite.

Uniform timing is the placeholder every animation starts with and almost none should keep.
A cycle holds its extremes two to four times as long as the poses it passes through, and
an attack is three separate lengths: a held anticipation, a strike snapped through in
20 to 40ms, and a held impact.

Two things this module refuses to do, because both are how timing is usually got wrong:

  * it never duplicates a frame to make a pose last longer. A hold is a duration. A
    duplicate costs a frame, shifts every tag index, and hides the repeat from the checks
    that look for repeated frames;
  * it will not quietly let an eased duration curve sit on top of eased spacing. The
    curve is then applied twice and the result reads as slow motion rather than as
    weight, so the caller is told when the spacing it is about to ease is already eased.
"""

from __future__ import annotations

from itertools import pairwise

CURVES = ("flat", "ease_in", "ease_out", "hold_extremes", "attack")

# Multiples of the base duration. The numbers come from the range animators actually use:
# an extreme holds two to four times a passing frame, and an anticipation longer still.
HOLD = 3.0
EXTREME = 2.5
IMPACT = 2.5
ANTICIPATION = 3.0
PASSING = 1.0

# A strike reads as an impact only if it is genuinely short. Below 20ms it is invisible
# and above 40ms it stops snapping, so the snap is clamped into that window.
MIN_SNAP_MS = 20
MAX_SNAP_MS = 40

# Aseprite stores a frame duration in milliseconds; these are its bounds, not ours.
MIN_DURATION_MS = 1
MAX_DURATION_MS = 65_535


def _attack_shape(count: int) -> list[tuple[float, str]]:
    """Anticipation, snap, impact, recovery, in that order.

    The impact lands about three fifths of the way through: long enough for the strike to
    have somewhere to travel, early enough to leave frames for the recovery.
    """
    impact = max(1, round(0.6 * (count - 1)))
    shape: list[tuple[float, str]] = []
    for index in range(count):
        if index == 0:
            shape.append((ANTICIPATION, "anticipation"))
        elif index < impact:
            shape.append((0.0, "snap"))  # 0.0 marks "use the snap duration, not a multiple"
        elif index == impact:
            shape.append((IMPACT, "impact"))
        else:
            shape.append((PASSING, "recovery"))
    return shape


def shape(count: int, curve: str) -> list[tuple[float, str]]:
    """The multiplier and the reason for it, one per frame."""
    if count < 1:
        raise ValueError("a timing curve needs at least one frame")
    if curve not in CURVES:
        raise ValueError(f"unknown curve {curve!r}; expected one of {', '.join(CURVES)}")

    if curve == "flat":
        return [(PASSING, "even")] * count
    if curve == "attack":
        return _attack_shape(count)
    if curve == "hold_extremes":
        # The extremes of a cycle are its ends: the first pose, and the one opposite it.
        extremes = {0, count // 2}
        return [((EXTREME, "extreme") if i in extremes else (PASSING, "passing"))
                for i in range(count)]

    # The eased curves stretch time rather than compress it, so the fast end keeps the
    # base duration and the slow end is twice it. "in" starts slow and "out" ends slow,
    # matching what the same words mean for spacing.
    span = max(1, count - 1)
    out = []
    for index in range(count):
        t = index / span
        fraction = (1.0 - t) if curve == "ease_in" else t
        out.append((PASSING + fraction, "eased"))
    return out


def looks_eased(distances: list[float | None], ratio: float = 1.5) -> bool:
    """Whether a spacing series is already carrying a curve.

    Monotone and meaningfully uneven is easing; anything else (steady, or a wobble) is
    not. The ratio keeps a one-pixel rounding difference from counting as a curve.
    """
    known = [d for d in distances if d is not None and d > 0]
    if len(known) < 3:
        return False
    rising = all(b >= a for a, b in pairwise(known))
    falling = all(b <= a for a, b in pairwise(known))
    if not (rising or falling):
        return False
    return max(known) >= min(known) * ratio


def plan(
    frames: list[int],
    *,
    curve: str = "hold_extremes",
    base_ms: int = 100,
    hold_frames: list[int] | None = None,
    snap_frames: list[int] | None = None,
    spacing: list[float | None] | None = None,
) -> dict:
    """Work out a duration for each frame, and say why each one got it.

    `hold_frames` and `snap_frames` name real frame numbers and override the curve for
    those frames: a hold is three times the base, a snap is the shortest duration that
    still registers. Returns the durations, a per-frame role, and any warning the caller
    should see before this lands in a file.
    """
    if not frames:
        raise ValueError("no frames to time")
    if not MIN_DURATION_MS <= base_ms <= MAX_DURATION_MS:
        raise ValueError(
            f"base_ms is {base_ms}; it must be between {MIN_DURATION_MS} and "
            f"{MAX_DURATION_MS} milliseconds"
        )

    holds = set(hold_frames or ())
    snaps = set(snap_frames or ())
    unknown = sorted((holds | snaps) - set(frames))
    if unknown:
        raise ValueError(
            f"hold_frames/snap_frames name frames that are not being timed: {unknown}. "
            f"The frames in play are {frames}."
        )
    both = sorted(holds & snaps)
    if both:
        raise ValueError(
            f"frames {both} are listed as both a hold and a snap, which are opposites."
        )

    snap_ms = min(MAX_SNAP_MS, max(MIN_SNAP_MS, round(base_ms * 0.3)))
    durations: list[int] = []
    roles: list[str] = []
    for number, (multiple, role) in zip(frames, shape(len(frames), curve), strict=True):
        if number in holds:
            value, role = round(base_ms * HOLD), "hold"
        elif number in snaps:
            value, role = snap_ms, "snap"
        elif role == "snap":
            value = snap_ms
        else:
            value = round(base_ms * multiple)
        durations.append(max(MIN_DURATION_MS, min(MAX_DURATION_MS, value)))
        roles.append(role)

    warnings: list[str] = []
    if curve in ("ease_in", "ease_out") and spacing is not None and looks_eased(spacing):
        warnings.append(
            "the spacing between these frames is already eased, and easing the durations "
            "too applies the curve twice: the result reads as slow motion rather than as "
            "weight. Use curve='flat' here, or space the cels evenly with "
            "offset_cels(ease='linear')."
        )
    if len(set(durations)) == 1 and len(durations) > 2:
        warnings.append(
            f"every frame came out at {durations[0]}ms. A cycle reads better when its "
            "extremes are held: try curve='hold_extremes', or name the poses in "
            "hold_frames."
        )
    return {"durations_ms": durations, "roles": roles, "warnings": warnings,
            "snap_ms": snap_ms}
