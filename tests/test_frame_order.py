"""Reordering frames and tag repeat counts: require Aseprite (--run-aseprite).

Aseprite has no command that moves a frame, so a move is built from the one that reverses
a range. What needs a real editor is whether the pieces that travel with a frame actually
travel: its cels on every layer, its duration, and its links.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import animation, cels, drawing, frames, inspect, layers, sprite, tags


def _strip(request, count: int = 6, suffix: str = "") -> str:
    """One marked pixel per frame, so the order of the frames is readable."""
    name = f"fo/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, 16, 16)
    for _ in range(count - 1):
        frames.add_frame(name)
    for f in range(1, count + 1):
        drawing.draw_pixels(name, [{"x": f, "y": 1}], "#ff0000", frame=f)
    return name


def _order(name: str, count: int = 6) -> list[int]:
    out = []
    for f in range(1, count + 1):
        row = inspect.get_pixels(name, 0, 0, 12, 2, frame=f)["pixels"][1]
        out.append(next(x for x, px in enumerate(row) if px[7:9] != "00"))
    return out


def _durations(name: str) -> list[float]:
    return [round(f["duration"], 3) for f in inspect.get_sprite_info(name)["frames"]]


# ------------------------------------------------------------------------- reversing
def test_reversing_a_run_turns_it_round(request):
    name = _strip(request)
    result = frames.reverse_frames(name, frames=[2, 3, 4, 5])

    assert _order(name) == [1, 5, 4, 3, 2, 6]
    assert result["frames_reversed"] == 4
    assert result["frame_count"] == 6


def test_reversing_a_tag_uses_its_own_range(request):
    name = _strip(request)
    tags.add_tag(name, "middle", 3, 5)

    result = frames.reverse_frames(name, tag="middle")

    assert (result["first"], result["last"]) == (3, 5)
    assert _order(name) == [1, 2, 5, 4, 3, 6]


def test_reversing_the_whole_sprite_is_the_default(request):
    name = _strip(request)
    frames.reverse_frames(name)
    assert _order(name) == [6, 5, 4, 3, 2, 1]


def test_each_frame_keeps_its_own_duration(request):
    """A frame is its picture and its timing, and reordering must carry both."""
    name = _strip(request)
    frames.set_frame_duration(name, 2, 250)
    frames.set_frame_duration(name, 5, 400)
    assert _durations(name) == [0.1, 0.25, 0.1, 0.1, 0.4, 0.1]

    frames.reverse_frames(name, frames=[2, 3, 4, 5])

    assert _durations(name) == [0.1, 0.4, 0.1, 0.1, 0.25, 0.1]


def test_every_layer_travels_together(request):
    """A frame is all of its layers. Reversing must not leave one layer behind."""
    name = _strip(request, 4)
    layers.add_layer(name, "top")
    for f in range(1, 5):
        drawing.draw_pixels(name, [{"x": f, "y": 8}], "#00ff00", layer="top", frame=f)

    frames.reverse_frames(name)

    for f in range(1, 5):
        rows = inspect.get_pixels(name, 0, 0, 12, 10, frame=f)["pixels"]
        bottom = next(x for x, px in enumerate(rows[1]) if px[7:9] != "00")
        top = next(x for x, px in enumerate(rows[8]) if px[7:9] != "00")
        assert bottom == top, f"frame {f}: layers came apart"


# ----------------------------------------------------------------------------- moving
def test_moving_a_frame_later(request):
    name = _strip(request)
    result = frames.move_frame(name, 2, 5)

    assert _order(name) == [1, 3, 4, 5, 2, 6]
    assert result["frame_count"] == 6


def test_moving_a_frame_earlier(request):
    name = _strip(request)
    frames.move_frame(name, 5, 2)
    assert _order(name) == [1, 5, 2, 3, 4, 6]


def test_a_moved_frame_takes_its_duration_with_it(request):
    name = _strip(request)
    frames.set_frame_duration(name, 2, 300)

    frames.move_frame(name, 2, 5)

    assert _durations(name) == [0.1, 0.1, 0.1, 0.1, 0.3, 0.1]


def test_linked_cels_are_still_linked_afterwards(request):
    """Nothing is copied, so the frame keeps its identity and its links with it."""
    name = _strip(request)
    cels.link_cels(name, "Layer 1", [1, 2, 3])

    frames.move_frame(name, 5, 1)

    linked = cels.get_cel(name, "Layer 1", 2)["linked_with"]
    assert len(linked) == 2, "the three linked frames should still be a group of three"


# ------------------------------------------------------------- what it warns about
def test_the_tags_over_the_affected_frames_are_named(request):
    """Tags mark positions, not pictures, so a tag over reordered frames now covers
    different drawings. Naming them is the whole warning."""
    name = _strip(request)
    tags.add_tag(name, "intro", 1, 2)
    tags.add_tag(name, "walk", 3, 6)

    result = frames.move_frame(name, 4, 6)

    assert result["tags_affected"] == ["walk"]
    assert "intro" not in result["tags_affected"]


# --------------------------------------------------- refused before Aseprite is launched
@pytest.mark.pure
def test_a_gapped_frame_list_is_refused(request):
    with pytest.raises(ValidationFailed, match="unbroken run"):
        frames.reverse_frames("unused.aseprite", frames=[1, 2, 4])


@pytest.mark.pure
def test_reversing_one_frame_is_refused():
    with pytest.raises(ValidationFailed, match="at least two frames"):
        frames.reverse_frames("unused.aseprite", frames=[3])


@pytest.mark.pure
def test_giving_both_a_tag_and_frames_is_refused():
    with pytest.raises(ValidationFailed, match="not both"):
        frames.reverse_frames("unused.aseprite", tag="walk", frames=[1, 2])


@pytest.mark.pure
def test_moving_a_frame_onto_itself_is_refused():
    with pytest.raises(ValidationFailed, match="already there"):
        frames.move_frame("unused.aseprite", 3, 3)


def test_an_unknown_tag_says_so(request):
    name = _strip(request, 2)
    with pytest.raises(AsepriteError, match="No tag named 'nope'"):
        frames.reverse_frames(name, tag="nope")


def test_a_frame_that_does_not_exist_says_so(request):
    name = _strip(request, 3)
    with pytest.raises(AsepriteError, match="does not exist"):
        frames.move_frame(name, 1, 9)


# ------------------------------------------------------------------ tag repeat counts
def test_a_tag_can_say_it_plays_once(request):
    name = _strip(request)
    tags.add_tag(name, "attack", 1, 4, repeats=1)

    tag = inspect.get_sprite_info(name)["tags"][0]
    assert tag["repeats"] == 1


def test_the_default_is_forever_which_is_how_a_cycle_is_marked(request):
    name = _strip(request)
    tags.add_tag(name, "walk", 1, 4)
    assert inspect.get_sprite_info(name)["tags"][0]["repeats"] == 0


def test_validate_loop_reads_the_tag_instead_of_being_told(request):
    """The point of storing it: the sprite answers for itself whether these frames wrap."""
    name = _strip(request)
    tags.add_tag(name, "walk", 1, 3)
    tags.add_tag(name, "attack", 4, 6, repeats=1)

    assert animation.validate_loop(name, tag="walk")["animation"]["loops"] is True
    assert animation.validate_loop(name, tag="attack")["animation"]["loops"] is False


def test_a_range_edit_does_not_turn_a_one_shot_into_a_loop(request):
    """set_tag recreates the tag to change its range, and a new tag starts at 0, which
    means forever. The count has to be carried across explicitly."""
    name = _strip(request)
    tags.add_tag(name, "attack", 4, 6, repeats=1)

    tags.set_tag(name, "attack", from_frame=3, to_frame=6)

    tag = inspect.get_sprite_info(name)["tags"][0]
    assert (tag["from"], tag["to"], tag["repeats"]) == (3, 6, 1)


@pytest.mark.pure
def test_a_negative_repeat_count_is_refused_rather_than_inverted():
    """Aseprite stores -1 as 0, which means forever: the opposite of what was asked."""
    with pytest.raises(ValidationFailed, match="opposite of a one-shot"):
        tags.add_tag("unused.aseprite", "attack", 1, 2, repeats=-1)


@pytest.mark.pure
def test_a_repeat_count_past_the_format_is_refused():
    with pytest.raises(ValidationFailed, match="at most 65535"):
        tags.add_tag("unused.aseprite", "attack", 1, 2, repeats=70000)


# --- issue #222: where a copy lands, which frame it is, and saying so -----------------


def _solid_frames(name: str, colours: list[str]) -> None:
    """A sprite whose frames are solid colours, so a frame's content can be read back."""
    sprite.create_sprite(name, 4, 4, overwrite=True)
    for i, colour in enumerate(colours):
        if i:
            frames.add_frame(name)
        drawing.draw_rectangle(name, 0, 0, 4, 4, colour, filled=True, frame=i + 1)


def _frame_colours(name: str) -> list[str]:
    count = inspect.get_sprite_info(name)["frameCount"]
    return [inspect.get_pixels(name, 0, 0, 1, 1, frame=f)["pixels"][0][0][:7]
            for f in range(1, count + 1)]


def _durations_ms(name: str) -> list[int]:
    return [round(f["duration"] * 1000) for f in inspect.get_sprite_info(name)["frames"]]


@pytest.mark.parametrize("copy_from, expected, renumbered_from", [
    (1, ["#ff0000", "#ff0000", "#0000ff", "#00ff00"], 2),
    (2, ["#ff0000", "#0000ff", "#0000ff", "#00ff00"], 3),
    # Copying the last frame has nothing after it to move.
    (3, ["#ff0000", "#0000ff", "#00ff00", "#00ff00"], None),
])
def test_a_copy_reports_where_it_landed_and_what_moved(copy_from, expected, renumbered_from):
    """The result used to be only {ok, newFrame, frameCount}, so a caller holding frame
    numbers from before the call had no way to learn they were stale (#222). Checked
    against the frames read back off the saved sprite, not against the call's own claim."""
    name = f"fo/c222_{copy_from}.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff", "#00ff00"])
    result = frames.add_frame(name, copy_from=copy_from)

    assert _frame_colours(name) == expected
    assert result["newFrame"] == copy_from + 1
    assert result["inserted"] is (renumbered_from is not None)
    assert result.get("renumbered_from") == renumbered_from


def test_an_append_says_nothing_moved():
    name = "fo/a222.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff"])
    result = frames.add_frame(name)

    assert _frame_colours(name)[:2] == ["#ff0000", "#0000ff"], "existing frames kept their numbers"
    assert result["newFrame"] == 3
    assert result["inserted"] is False
    assert "renumbered_from" not in result


def test_new_frame_names_the_copy_and_not_the_frame_it_copied():
    """`newFrame` named the original for as long as it existed, because Aseprite's
    `newFrame(n)` returns frame n after putting the copy at n + 1 (#222). Pixels cannot
    show that, since the two frames are identical. A link can: the original keeps sharing
    its image with the frame it was linked to and the copy does not, so the frame
    `newFrame` names must be the unlinked one, and drawing on it must not reach the
    linked frame."""
    name = "fo/identity222.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff", "#00ff00", "#ffffff"])
    cels.link_cels(name, "Layer 1", [2, 4])

    result = frames.add_frame(name, copy_from=2)

    assert result["newFrame"] == 3
    assert cels.get_cel(name, "Layer 1", 3)["linked_with"] == []
    assert cels.get_cel(name, "Layer 1", 2)["linked_with"] == [5], "the original kept its link"
    drawing.draw_pixels(name, [{"x": 0, "y": 0}], "#123456", frame=result["newFrame"])
    assert _frame_colours(name) == ["#ff0000", "#0000ff", "#123456", "#00ff00", "#0000ff"]


def test_the_duration_goes_on_the_copy():
    """It went on the frame copied (#222). Four `add_frame(500, copy_from=1)` calls on a
    100ms frame left 500, 500, 500, 500, 100: the frame no call gave a duration had one,
    and the last frame added kept the 100 it was copied with."""
    name = "fo/duration222.aseprite"
    sprite.create_sprite(name, 4, 4, overwrite=True)
    for _ in range(4):
        frames.add_frame(name, 500, copy_from=1)

    assert _durations_ms(name) == [100, 500, 500, 500, 500]


def test_duplicate_frame_names_the_copy_too():
    """The same Aseprite call, so the same wrong `newFrame` until #222: duplicating frame 2
    reported 2 while its own docstring said the copy goes after it."""
    name = "fo/dup222.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff", "#00ff00"])
    result = frames.duplicate_frame(name, 2)

    assert _frame_colours(name) == ["#ff0000", "#0000ff", "#0000ff", "#00ff00"]
    assert result["newFrame"] == 3
    assert result["inserted"] is True
    assert result["renumbered_from"] == 3


def test_tags_follow_their_frames_and_grow_to_take_in_a_copy():
    """Stated in `add_frame`'s docstring, so pinned against the saved file: a tag covering
    the copied frame grows by one, a tag after it moves up by one, and a tag before it is
    left alone."""
    name = "fo/tags222.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff", "#00ff00", "#ffffff"])
    tags.add_tag(name, "before", 1, 1)
    tags.add_tag(name, "around", 1, 3)
    tags.add_tag(name, "on", 2, 2)
    tags.add_tag(name, "after", 3, 4)

    frames.add_frame(name, copy_from=2)

    ranges = {t["name"]: (t["from"], t["to"]) for t in inspect.get_sprite_info(name)["tags"]}
    assert ranges == {"before": (1, 1), "around": (1, 4), "on": (2, 3), "after": (4, 5)}


def test_the_batch_ops_place_report_and_time_a_copy_the_same_way():
    """A batch and a direct call must not disagree about where a frame landed or which
    frame took the duration (#222)."""
    from aseprite_mcp.tools import batch

    name = "fo/b222.aseprite"
    _solid_frames(name, ["#ff0000", "#0000ff"])
    manifest = batch.apply_operations(name, [
        {"op": "add_frame", "args": {"copy_from": 1, "duration_ms": 300}},
        {"op": "add_frame", "args": {"copy_from": 3}},
        {"op": "add_frame", "args": {}},
        {"op": "duplicate_frame", "args": {"frame": 1}},
    ])

    assert [op["summary"] for op in manifest["operations"]] == [
        "added frame 2, a copy of frame 1; the old frames 2 and later moved up by one",
        "added frame 4, a copy of frame 3",
        "added frame 5",
        "duplicated frame 1 as frame 2; the old frames 2 and later moved up by one",
    ]
    assert _frame_colours(name)[:5] == ["#ff0000", "#ff0000", "#ff0000", "#0000ff", "#0000ff"]
    assert _durations_ms(name) == [100, 100, 300, 100, 100, 100]
