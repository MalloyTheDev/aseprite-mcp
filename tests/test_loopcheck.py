"""Pure tests for the animation verdict (no Aseprite, always run).

Every rule here exists because the fault it names is invisible in a still frame and cheap
to ship: a loop that stutters once per cycle, a pose held by repeating a frame, timing
that never got past the placeholder, a character that sinks a pixel as it lands. Breaking
them on purpose in a real sprite is slow; breaking them in a dict is not, so the judgement
lives apart from the measuring.
"""

from __future__ import annotations

from aseprite_mcp.core import loopcheck


def frame(number: int, *, digest: str | None = None, duration_ms: int = 100,
          bounds: tuple[int, int, int, int] | None = (10, 40, 8, 8)) -> dict:
    return {
        "frame": number,
        "hash": digest if digest is not None else f"hash{number}",
        "duration_ms": duration_ms,
        "bounds": None if bounds is None
        else {"x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3]},
    }


def failed(report: dict) -> set[str]:
    return {c["name"] for c in report["checks"] if not c["ok"]}


def detail(report: dict, name: str) -> str:
    return next(c["detail"] for c in report["checks"] if c["name"] == name)


def walk_cycle() -> list[dict]:
    """Four distinct poses, varied timing, one shared contact row."""
    return [
        frame(1, duration_ms=150, bounds=(10, 40, 8, 8)),
        frame(2, duration_ms=80, bounds=(14, 40, 8, 8)),
        frame(3, duration_ms=150, bounds=(18, 40, 8, 8)),
        frame(4, duration_ms=80, bounds=(22, 40, 8, 8)),
    ]


# --------------------------------------------------------------------- a clean cycle
def test_a_clean_cycle_passes_with_nothing_to_report():
    report, _ = loopcheck.evaluate(walk_cycle())
    assert report["passed"] is True
    assert failed(report) == set()
    assert report["errors"] == [] and report["warnings"] == []


def test_the_measurements_come_back_alongside_the_verdict():
    _, measured = loopcheck.evaluate(walk_cycle(), tag="walk")
    assert measured["tag"] == "walk"
    assert measured["frame_count"] == 4
    assert measured["total_duration_ms"] == 460
    assert measured["durations_ms"] == [150, 80, 150, 80]
    # Centroid of an 8px box at x=10 is 13.5, and each pose moves 4px right.
    assert [f["centroid"]["x"] for f in measured["frames"]] == [13.5, 17.5, 21.5, 25.5]
    assert [s["distance"] for s in measured["spacing"]] == [4.0, 4.0, 4.0]
    assert [f["bottom"] for f in measured["frames"]] == [47, 47, 47, 47]


# ------------------------------------------------------------------------- the seam
def test_a_repeated_wrap_frame_fails_a_loop():
    frames = walk_cycle()
    frames[-1]["hash"] = frames[0]["hash"]
    report, measured = loopcheck.evaluate(frames, loops=True)
    assert report["passed"] is False
    assert "no_seam_duplicate" in failed(report)
    assert measured["seam_duplicate"] is True
    assert "twice at the wrap" in detail(report, "no_seam_duplicate")


def test_a_repeated_last_frame_is_only_a_warning_for_a_one_shot():
    """An attack or a death does not wrap, so the same measurement is not a fault."""
    frames = walk_cycle()
    frames[-1]["hash"] = frames[0]["hash"]
    report, _ = loopcheck.evaluate(frames, loops=False)
    assert report["passed"] is True
    assert "no_seam_duplicate" in failed(report)
    assert report["warnings"] and not report["errors"]


# ------------------------------------------------------------------ duplicate frames
def test_identical_adjacent_frames_fail_and_name_the_pair():
    frames = walk_cycle()
    frames[2]["hash"] = frames[1]["hash"]
    report, measured = loopcheck.evaluate(frames)
    assert report["passed"] is False
    assert measured["duplicate_pairs"] == [[2, 3]]
    assert "2 and 3" in detail(report, "no_duplicate_adjacent_frames")
    # The point is not that it is a duplicate but that there is a cheaper way to hold.
    assert "set_frame_duration" in detail(report, "no_duplicate_adjacent_frames")


def test_a_single_frame_is_reported_rather_than_compared():
    report, measured = loopcheck.evaluate([frame(1)])
    assert failed(report) == {"comparable_frames"}
    assert report["passed"] is True
    assert measured["duplicate_pairs"] == [] and measured["seam_duplicate"] is False


# ------------------------------------------------------------------------- timing
def test_uniform_timing_is_a_warning_not_a_failure():
    frames = [frame(n, duration_ms=100) for n in range(1, 5)]
    for n, f in enumerate(frames):
        f["bounds"] = {"x": 10 + 4 * n, "y": 40, "width": 8, "height": 8}
    report, measured = loopcheck.evaluate(frames)
    assert measured["uniform_timing"] is True
    assert "timing_varies" in failed(report)
    assert report["passed"] is True


def test_two_frames_of_equal_length_are_not_called_uniform():
    """A two-frame flicker has nowhere to put a hold; flagging it would be noise."""
    frames = [frame(1, duration_ms=100), frame(2, duration_ms=100)]
    frames[1]["bounds"] = {"x": 14, "y": 40, "width": 8, "height": 8}
    _, measured = loopcheck.evaluate(frames)
    assert measured["uniform_timing"] is False


# ------------------------------------------------------------------------ spacing
def test_an_eased_run_up_is_not_called_jitter():
    """Spacing that grows and then shrinks turns once. That is easing, not a limp."""
    xs = [0, 2, 6, 12, 20, 28, 34, 38, 40]
    frames = [frame(n + 1, bounds=(x, 40, 8, 8)) for n, x in enumerate(xs)]
    report, measured = loopcheck.evaluate(frames)
    assert measured["spacing_direction_changes"] <= 1
    assert "spacing_steady" not in failed(report)


def test_a_limp_is_visible_once_the_tolerance_is_dropped():
    """5,4,5,5,4,5 is the rounding wobble that reads as a limp. One pixel is also what
    integer cel positions cost, so the default tolerance ignores it and 0 does not."""
    xs, position = [], 0
    for step in (5, 4, 5, 5, 4, 5):
        position += step
        xs.append(position)
    frames = [frame(1, bounds=(0, 40, 8, 8))]
    frames += [frame(n + 2, bounds=(x, 40, 8, 8)) for n, x in enumerate(xs)]
    lenient, _ = loopcheck.evaluate(frames)
    strict, measured = loopcheck.evaluate(frames, jitter_tolerance=0)
    assert "spacing_steady" not in failed(lenient)
    assert "spacing_steady" in failed(strict)
    assert measured["spacing_direction_changes"] >= 2


# ------------------------------------------------------------------- the contact row
def test_a_moving_contact_edge_is_reported_with_the_distance():
    frames = walk_cycle()
    frames[2]["bounds"] = {"x": 18, "y": 38, "width": 8, "height": 8}  # 2px up
    report, measured = loopcheck.evaluate(frames)
    assert measured["contact_drift_px"] == 2
    assert "contact_edge_stable" in failed(report)
    assert "2px" in detail(report, "contact_edge_stable")
    assert report["passed"] is True  # expected while airborne, so never a failure


def test_contact_rows_skip_frames_with_nothing_drawn():
    frames = walk_cycle()
    frames[1]["bounds"] = None
    report, measured = loopcheck.evaluate(frames)
    assert measured["empty_frames"] == [2]
    assert measured["contact_rows"] == [47, 47, 47]
    assert "no_empty_frames" in failed(report)
    # An empty frame has no centroid, so its spacing entries are blank rather than zero:
    # calling a gap "no movement" would be a measurement the tool did not make.
    assert measured["spacing"][0]["distance"] is None
    assert measured["spacing"][1]["distance"] is None
