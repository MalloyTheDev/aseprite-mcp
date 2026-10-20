"""squash_stretch_pass (#90): the contact edge stays where it is.

Scaling a shape about its centre shortens it from both ends, so the thing lifts off the
surface at the moment it should be pressed into it. Measured on a hand-built squash
before this tool existed, the contact row rose from 56 to 54: the ball went *up* two
pixels on impact. Every test here turns on the anchored edge keeping its coordinate.

The other two properties are about staying pixel art. Resizing is nearest neighbour,
always, because bilinear returned 50 colours and 40 semi-transparent pixels on a
5-colour sprite when it was measured, and a single pass would cost a sprite its palette.

Most of this needs Aseprite (--run-aseprite); the argument refusals are `pure`.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import animation, drawing, inspect, sprite
from aseprite_mcp.tools import frames as frame_tools

W = H = 40
FILL, LINE = "#c84050", "#5a1020"


def _ball(name: str, *, cy: int = 24, frames: int = 1) -> str:
    """A two-colour disc resting with its bottom edge well inside the canvas."""
    sprite.create_sprite(name, W, H, overwrite=True)
    for number in range(1, frames + 1):
        if number > 1:
            frame_tools.add_frame(name)
        drawing.draw_ellipse(name, 19, cy, 9, 9, FILL, filled=True, frame=number)
        drawing.draw_ellipse(name, 19, cy, 9, 9, LINE, frame=number)
    return name


def _shape(name: str, frame: int = 1) -> dict:
    grid = inspect.get_pixels(name, 0, 0, W, H, frame=frame)["pixels"]
    rows = [y for y, row in enumerate(grid) if any(px[7:9] != "00" for px in row)]
    cols = [x for x in range(W) if any(grid[y][x][7:9] != "00" for y in range(H))]
    return {
        "top": rows[0], "bottom": rows[-1], "left": cols[0], "right": cols[-1],
        "height": rows[-1] - rows[0] + 1, "width": cols[-1] - cols[0] + 1,
        "colours": {px[:7] for row in grid for px in row if px[7:9] == "ff"},
        "semi": sum(1 for row in grid for px in row if px[7:9] not in ("ff", "00")),
    }


# --- refused before launch -----------------------------------------------------------


@pytest.fixture
def no_launch(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a call that is refused before it")
    monkeypatch.setattr(animation, "run_lua", refuse)


@pytest.mark.pure
@pytest.mark.parametrize("kwargs, match", [
    ({"anchor": "middle"}, "names the edge that stays put"),
    ({"amount": 0.95}, "runs from -0.8"),
    ({"amount": -0.95}, "runs from -0.8"),
    ({"amount": 0}, "would do nothing"),
    ({"frames": []}, "leave it out to work on every frame"),
])
def test_a_bad_argument_is_refused_by_name(no_launch, kwargs, match):
    with pytest.raises(ValidationFailed, match=match):
        animation.squash_stretch_pass("sq/x.aseprite", **kwargs)


# --- against Aseprite ----------------------------------------------------------------


@pytest.mark.parametrize("anchor", ["bottom", "top", "left", "right"])
def test_the_anchored_edge_does_not_move(anchor):
    """The whole point. Checked for every edge, not only the contact one, because the
    same arithmetic places all four."""
    name = _ball(f"sq/anchor_{anchor}.aseprite")
    before = _shape(name)

    animation.squash_stretch_pass(name, anchor=anchor, amount=0.25)

    assert _shape(name)[anchor] == before[anchor]


def test_a_squash_loses_height_and_gains_width():
    """Volume preserving: what the anchored axis gives up, the other one takes."""
    name = _ball("sq/volume.aseprite")
    before = _shape(name)

    animation.squash_stretch_pass(name, amount=0.25)

    after = _shape(name)
    assert after["height"] < before["height"]
    assert after["width"] > before["width"]


def test_a_negative_amount_stretches_instead():
    name = _ball("sq/stretch.aseprite")
    before = _shape(name)

    animation.squash_stretch_pass(name, amount=-0.25)

    after = _shape(name)
    assert after["height"] > before["height"]
    assert after["width"] < before["width"]
    assert after["bottom"] == before["bottom"], "the anchor holds when stretching too"


def test_the_pass_adds_no_colour_and_no_transparency():
    """Nearest neighbour, never bilinear, which on this art returns 50 colours and 40
    semi-transparent pixels."""
    name = _ball("sq/pixels.aseprite")
    before = _shape(name)

    animation.squash_stretch_pass(name, amount=0.3)

    after = _shape(name)
    assert after["colours"] <= before["colours"]
    assert after["semi"] == 0


def test_every_frame_is_passed_over_when_none_are_named():
    name = _ball("sq/allframes.aseprite", frames=3)
    before = [_shape(name, f)["height"] for f in (1, 2, 3)]

    result = animation.squash_stretch_pass(name, amount=0.25)

    assert [entry["frame"] for entry in result["frames"]] == [1, 2, 3]
    assert all(_shape(name, f)["height"] < before[f - 1] for f in (1, 2, 3))


def test_only_the_named_frames_are_touched():
    name = _ball("sq/some.aseprite", frames=3)
    before = [_shape(name, f)["height"] for f in (1, 2, 3)]

    animation.squash_stretch_pass(name, frames=[2], amount=0.25)

    after = [_shape(name, f)["height"] for f in (1, 2, 3)]
    assert after[1] < before[1]
    assert (after[0], after[2]) == (before[0], before[2])


def test_an_empty_frame_is_reported_rather_than_failing_the_pass():
    """A pass over a whole animation should not die on a frame that holds nothing."""
    name = _ball("sq/gap.aseprite", frames=2)
    drawing.clear_layer(name, frame=2)

    result = animation.squash_stretch_pass(name, amount=0.25)

    done, skipped = result["frames"][0], result["frames"][1]
    assert "skipped" not in done and done["frame"] == 1
    assert skipped["frame"] == 2 and "nothing is drawn" in skipped["skipped"]


def test_a_shape_pushed_off_the_canvas_says_how_much_was_lost():
    """Widening is what runs a shape off the edge, and drawImage drops it silently."""
    name = "sq/clipped.aseprite"
    sprite.create_sprite(name, 32, 32, overwrite=True)
    drawing.draw_rectangle(name, 1, 10, 30, 12, FILL, filled=True)

    result = animation.squash_stretch_pass(name, amount=0.5)

    assert result["frames"][0]["clipped"] > 0


def test_a_pass_that_fits_reports_no_clipping():
    """The counter is absent rather than zero, as every counter here is, so its presence
    means something was actually lost."""
    name = _ball("sq/fits.aseprite")
    result = animation.squash_stretch_pass(name, amount=0.2)

    assert "clipped" not in result["frames"][0]
