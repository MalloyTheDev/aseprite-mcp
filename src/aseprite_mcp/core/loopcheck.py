"""Pure judgement about an animation, from measurements taken in one Aseprite launch.

`validate_loop` renders each frame, hashes it, and measures its content box and duration;
this module decides what those numbers mean. The split keeps every rule testable against a
handful of dicts, including the broken cases that are tedious to draw on purpose.

What the rules are worth knowing for:

  * a loop whose last frame repeats its first shows that image twice at the wrap. It reads
    as a stutter once per cycle and is invisible frame by frame;
  * two identical adjacent frames are a hold authored the expensive way. A hold is a
    longer duration on one frame; duplicating wastes a frame, shifts every tag index, and
    hides the repeat from this check;
  * uniform durations are almost always a placeholder. Real cycles hold their extremes;
  * a contact edge that moves during a grounded cycle is the character sliding or sinking.
    It is expected while airborne, so it is reported rather than failed.
"""

from __future__ import annotations

import math
from itertools import pairwise

# A 1px wobble is inherent to integer cel positions, so the default tolerance ignores it.
DEFAULT_JITTER_TOLERANCE = 1.0


def _centroid(bounds: dict | None) -> dict | None:
    if not bounds:
        return None
    return {
        "x": round(bounds["x"] + (bounds["width"] - 1) / 2, 1),
        "y": round(bounds["y"] + (bounds["height"] - 1) / 2, 1),
    }


def _bottom(bounds: dict | None) -> int | None:
    if not bounds:
        return None
    return bounds["y"] + bounds["height"] - 1


def _spacing(measured: list[dict]) -> list[dict]:
    series = []
    for previous, current in pairwise(measured):
        a, b = previous["centroid"], current["centroid"]
        if a is None or b is None:
            series.append({"from": previous["frame"], "to": current["frame"],
                           "dx": None, "dy": None, "distance": None})
            continue
        dx, dy = round(b["x"] - a["x"], 1), round(b["y"] - a["y"], 1)
        series.append({"from": previous["frame"], "to": current["frame"],
                       "dx": dx, "dy": dy, "distance": round(math.hypot(dx, dy), 2)})
    return series


def _direction_changes(distances: list[float]) -> tuple[int, float]:
    """Count the reversals in a spacing series, and measure the largest.

    A reversal is a step up followed by a step down, or the other way round. Steady motion
    has none, easing has one at the turn, and the jitter that reads as a limp has several
    small ones. The count separates those shapes; the amplitude says whether the wobble is
    larger than integer rounding can explain.
    """
    steps = [round(b - a, 2) for a, b in pairwise(distances)]
    changes, largest, previous = 0, 0.0, None
    for step in steps:
        if step == 0:
            continue
        if previous is not None and (step > 0) != (previous > 0):
            changes += 1
            largest = max(largest, min(abs(step), abs(previous)))
        previous = step
    return changes, largest


def evaluate(
    frames: list[dict],
    *,
    tag: str | None = None,
    loops: bool = True,
    jitter_tolerance: float = DEFAULT_JITTER_TOLERANCE,
) -> tuple[dict, dict]:
    """Turn per-frame measurements into a (report, measurements) pair.

    `frames` is what the Lua side gathers: one dict per frame with `frame`, `hash`,
    `duration_ms` and `bounds`, the last being None for a frame with nothing drawn on it.
    The report is the {passed, checks, errors, warnings} shape the other validators use,
    and `passed` is False only for the faults that are wrong whatever the animation is
    trying to do.
    """
    measured = [
        {
            "frame": f["frame"],
            "hash": f["hash"],
            "duration_ms": f["duration_ms"],
            "bounds": f.get("bounds"),
            "centroid": _centroid(f.get("bounds")),
            "bottom": _bottom(f.get("bounds")),
        }
        for f in frames
    ]
    durations = [f["duration_ms"] for f in measured]
    spacing = _spacing(measured)
    distances = [s["distance"] for s in spacing if s["distance"] is not None]
    direction_changes, flip_amplitude = _direction_changes(distances)
    duplicate_pairs = [
        [a["frame"], b["frame"]]
        for a, b in pairwise(measured)
        if a["hash"] == b["hash"]
    ]
    empty_frames = [f["frame"] for f in measured if f["bounds"] is None]
    bottoms = [f["bottom"] for f in measured if f["bottom"] is not None]
    contact_drift = (max(bottoms) - min(bottoms)) if len(bottoms) >= 2 else 0
    seam_duplicate = len(measured) >= 2 and measured[0]["hash"] == measured[-1]["hash"]
    uniform_timing = len(durations) >= 3 and len(set(durations)) == 1
    jitter = direction_changes >= 2 and flip_amplitude > jitter_tolerance

    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, level: str, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "level": level, "detail": detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)

    check("comparable_frames", len(measured) >= 2, "warning",
          "" if len(measured) >= 2 else
          "only one frame, so there is nothing to compare across frames")

    if len(measured) >= 2:
        first, last = measured[0]["frame"], measured[-1]["frame"]
        check(
            "no_seam_duplicate", not seam_duplicate, "error" if loops else "warning",
            "" if not seam_duplicate else
            f"frames {first} and {last} are identical, so the loop shows that image twice "
            "at the wrap; drop the last frame",
        )
        check(
            "no_duplicate_adjacent_frames", not duplicate_pairs, "error",
            "" if not duplicate_pairs else
            "identical adjacent frames: " +
            ", ".join(f"{a} and {b}" for a, b in duplicate_pairs) +
            ". Hold a pose with a longer duration on one frame (set_frame_duration), not "
            "with a repeated frame",
        )
        check(
            "timing_varies", not uniform_timing, "warning",
            "" if not uniform_timing else
            f"every frame lasts {durations[0]}ms; real cycles hold their extremes two to "
            "four times as long as the passing frames",
        )
        check(
            "spacing_steady", not jitter, "warning",
            "" if not jitter else
            f"the spacing series reverses {direction_changes} times, by up to "
            f"{flip_amplitude}px, which reads as a limp rather than as easing",
        )
        check(
            "contact_edge_stable", contact_drift == 0, "warning",
            "" if contact_drift == 0 else
            f"the bottom row of the drawn content moves by {contact_drift}px across these "
            "frames: a character sliding or sinking in a grounded cycle, and expected "
            "while airborne",
        )

    check(
        "no_empty_frames", not empty_frames, "warning",
        "" if not empty_frames else
        f"frames {empty_frames} have nothing drawn on them; deliberate for a flicker, a "
        "hole in the cycle otherwise",
    )

    report = {
        "passed": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
    measurements = {
        "tag": tag,
        "loops": loops,
        "frame_count": len(measured),
        "total_duration_ms": sum(durations),
        "frames": measured,
        "durations_ms": durations,
        "spacing": spacing,
        "spacing_direction_changes": direction_changes,
        "duplicate_pairs": duplicate_pairs,
        "seam_duplicate": seam_duplicate,
        "uniform_timing": uniform_timing,
        "empty_frames": empty_frames,
        "contact_rows": bottoms,
        "contact_drift_px": contact_drift,
    }
    return report, measurements
