"""Linked cels: require Aseprite (--run-aseprite).

A linked cel is one image appearing on several frames. It is how a held pose is drawn:
the file stores the image once, and editing any of those frames edits all of them. The
feature is in every Aseprite file and was not reachable from here at all.

The property under test is behavioural, not structural: linking is only real if an edit
to one frame shows up on the others and nowhere else.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import cels, drawing, frames, inspect, sprite


def _strip(request, count: int = 5) -> str:
    """One drawn square copied onto every frame, each frame its own copy to begin with."""
    name = f"lc/{request.node.name}.aseprite"
    sprite.create_sprite(name, 24, 24)
    drawing.draw_rectangle(name, 4, 4, 8, 8, "#ff4040", filled=True)
    for _ in range(count - 1):
        frames.add_frame(name)
    for frame in range(2, count + 1):
        cels.copy_cel(name, "Layer 1", 1, frame)
    return name


def _opaque(name: str, frame: int) -> int:
    rows = inspect.get_pixels(name, 0, 0, 24, 24, frame=frame)["pixels"]
    return sum(1 for row in rows for px in row if px[7:9] != "00")


# ----------------------------------------------------------------------- linking works
def test_linked_frames_share_one_image(request):
    name = _strip(request)
    result = cels.link_cels(name, "Layer 1", [1, 2, 3])

    assert result["groups"] == [[1, 2, 3], [4], [5]]
    assert cels.get_cel(name, "Layer 1", 2)["linked_with"] == [1, 3]
    assert cels.get_cel(name, "Layer 1", 4)["linked"] is False


def test_an_edit_to_one_linked_frame_reaches_the_others_and_no_one_else(request):
    """The whole point, and the only test that would notice if linking silently became
    copying: the frames have to move together afterwards."""
    name = _strip(request)
    cels.link_cels(name, "Layer 1", [1, 2, 3])
    before = [_opaque(name, f) for f in range(1, 6)]

    drawing.draw_rectangle(name, 14, 14, 4, 4, "#40ff40", filled=True, frame=2)

    after = [_opaque(name, f) for f in range(1, 6)]
    assert after[0] == after[1] == after[2] > before[0]
    assert after[3:] == before[3:], "unlinked frames must be untouched"


def test_frames_do_not_have_to_be_next_to_each_other(request):
    name = _strip(request)
    assert cels.link_cels(name, "Layer 1", [1, 3, 5])["groups"] == [[1, 3, 5], [2], [4]]


def test_the_first_listed_frame_is_the_one_that_survives(request):
    """Documented and therefore pinned: linking keeps one drawing and drops the rest."""
    name = _strip(request)
    drawing.draw_rectangle(name, 14, 14, 6, 6, "#40ff40", filled=True, frame=2)
    first, second = _opaque(name, 1), _opaque(name, 2)
    assert second > first, "frame 2 starts with more drawn on it"

    cels.link_cels(name, "Layer 1", [1, 2])

    assert _opaque(name, 2) == first, "frame 2 now shows frame 1's image"


# --------------------------------------------------------------------------- unlinking
def test_unlinking_gives_a_frame_its_own_copy_back(request):
    name = _strip(request)
    cels.link_cels(name, "Layer 1", [1, 2, 3])

    result = cels.unlink_cels(name, "Layer 1", [3])

    assert result["groups"] == [[1, 2], [3], [4], [5]]
    assert cels.get_cel(name, "Layer 1", 3)["linked"] is False


def test_unlinking_keeps_what_the_frame_was_showing(request):
    """Nothing is lost: the image is copied, not moved."""
    name = _strip(request)
    cels.link_cels(name, "Layer 1", [1, 2])
    drawing.draw_rectangle(name, 14, 14, 4, 4, "#40ff40", filled=True, frame=1)
    shared = _opaque(name, 2)

    cels.unlink_cels(name, "Layer 1", [2])

    assert _opaque(name, 2) == shared
    drawing.draw_rectangle(name, 1, 18, 3, 3, "#4040ff", filled=True, frame=2)
    assert _opaque(name, 2) > shared
    assert _opaque(name, 1) == shared, "frame 1 no longer follows frame 2"


# ---------------------------------------------------------------------------- refusals
def test_linking_a_single_frame_is_refused():
    with pytest.raises(ValidationFailed, match="at least 2"):
        cels.link_cels("unused.aseprite", "Layer 1", [1])


def test_a_repeated_frame_is_refused():
    with pytest.raises(ValidationFailed, match="more than once"):
        cels.link_cels("unused.aseprite", "Layer 1", [1, 2, 2])


def test_frame_zero_is_refused():
    with pytest.raises(ValidationFailed, match="1-based"):
        cels.link_cels("unused.aseprite", "Layer 1", [0, 1])


def test_a_frame_with_nothing_on_it_says_so(request):
    name = _strip(request, 3)
    cels.delete_cel(name, "Layer 1", 2)
    with pytest.raises(AsepriteError, match="no cel on frame 2"):
        cels.link_cels(name, "Layer 1", [1, 2])


def test_a_frame_that_does_not_exist_says_so(request):
    name = _strip(request, 2)
    with pytest.raises(AsepriteError, match="does not exist"):
        cels.link_cels(name, "Layer 1", [1, 9])
