"""Frame reordering arithmetic, without Aseprite (always runs).

A move is a rotation and a rotation is two reversals, which is a pleasing fact right up
until the indices are off by one and a sprite comes back in the wrong order. The
arithmetic is checked here against lists, where a wrong answer is visible.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import frameops


def reference(order: list[int], frame: int, to: int) -> list[int]:
    """What moving a frame means, written the obvious way."""
    out = list(order)
    out.insert(to - 1, out.pop(frame - 1))
    return out


# --------------------------------------------------------------------------- the move
@pytest.mark.parametrize("frame,to", [
    (2, 5), (5, 2), (1, 6), (6, 1), (3, 4), (4, 3), (1, 2), (6, 5),
])
def test_two_reversals_do_what_a_move_does(frame, to):
    order = [1, 2, 3, 4, 5, 6]
    moved = frameops.apply_reversals(order, frameops.rotation_reversals(frame, to))
    assert moved == reference(order, frame, to)


def test_moving_later_rotates_the_block_left():
    assert frameops.rotation_reversals(2, 5) == [(2, 5), (2, 4)]


def test_moving_earlier_rotates_the_block_right():
    assert frameops.rotation_reversals(5, 2) == [(2, 5), (3, 5)]


def test_moving_a_frame_to_itself_is_refused():
    with pytest.raises(ValueError, match="already where it is"):
        frameops.rotation_reversals(3, 3)


# ---------------------------------------------------------------------- contiguity
def test_a_run_is_accepted_in_any_order():
    assert frameops.check_contiguous([4, 2, 3]) == (2, 4)


def test_a_gap_is_refused_and_names_it():
    """Aseprite reverses everything between the first and the last frame of a selection,
    so accepting a gap would touch frames nobody asked about."""
    with pytest.raises(ValueError, match="3 is followed by 5"):
        frameops.check_contiguous([1, 2, 3, 5])


def test_no_frames_is_refused():
    with pytest.raises(ValueError, match="no frames"):
        frameops.check_contiguous([])


def test_one_frame_is_a_run_of_one():
    assert frameops.check_contiguous([7]) == (7, 7)


# ------------------------------------------------------------------- affected tags
TAGS = [
    {"name": "intro", "from": 1, "to": 2},
    {"name": "walk", "from": 3, "to": 6},
    {"name": "outro", "from": 7, "to": 8},
]


def test_a_tag_over_the_moved_frames_is_named():
    assert frameops.tags_touching(TAGS, 4, 5) == ["walk"]


def test_a_tag_merely_next_to_them_is_not():
    assert frameops.tags_touching(TAGS, 3, 6) == ["walk"]
    assert frameops.tags_touching(TAGS, 7, 8) == ["outro"]


def test_a_span_across_several_tags_names_them_all_in_file_order():
    assert frameops.tags_touching(TAGS, 2, 7) == ["intro", "walk", "outro"]


def test_frames_no_tag_covers_name_nothing():
    assert frameops.tags_touching([{"name": "walk", "from": 3, "to": 4}], 6, 8) == []
