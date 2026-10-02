"""Selections, and the fact that they outlive the process that made them.

The property worth testing hardest is persistence: a selection is not stored in the
.aseprite file, so without the sidecar it would die with the Aseprite run that created
it, and every one of these tools is a separate run.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, inspect, selection, shading, sprite
from aseprite_mcp.tools.common import resolve_path
from aseprite_mcp.tools.selection import mask_path_for


@pytest.fixture()
def canvas(request):
    name = f"sel/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    return name


def test_a_selection_survives_into_a_later_tool_call(canvas):
    """The whole point. Each call is its own Aseprite process.

    A selection lives in memory and is not written to the .aseprite file, so without the
    sidecar this fill would cover the whole canvas.
    """
    selection.select_region(canvas, "rect", x=4, y=4, width=8, height=8)

    result = drawing.fill_layer(canvas, "#ff0000")

    assert result["selection_applied"] is True
    assert result["pixels_written"] == 64
    assert result["pixels_outside_selection"] == 192
    assert result["pixels_written"] + result["pixels_outside_selection"] == 16 * 16

    rows = inspect.get_pixels(canvas, 0, 0, 16, 16)["pixels"]
    assert rows[0][0].lower().endswith("00"), "outside the selection must be untouched"
    assert not rows[8][8].lower().endswith("00"), "inside the selection must be filled"


def test_drawing_without_a_selection_is_unaffected(canvas):
    """The feature must cost nothing when it is not in use."""
    result = drawing.fill_layer(canvas, "#ff0000")
    assert "selection_applied" not in result
    assert "pixels_outside_selection" not in result
    assert result["pixels_written"] == 16 * 16


def test_a_non_rectangular_selection_round_trips(canvas):
    """A hole has to survive the sidecar, or subtract mode is decorative."""
    selection.select_region(canvas, "rect", x=2, y=2, width=12, height=12)
    selection.select_region(canvas, "rect", x=6, y=6, width=4, height=4, mode="subtract")

    described = selection.get_selection(canvas)
    assert described["area"] == 12 * 12 - 4 * 4

    result = drawing.fill_layer(canvas, "#ff0000")
    assert result["pixels_written"] == 12 * 12 - 4 * 4

    rows = inspect.get_pixels(canvas, 0, 0, 16, 16)["pixels"]
    assert not rows[3][3].lower().endswith("00"), "inside the ring should be filled"
    assert rows[7][7].lower().endswith("00"), "the hole should have stayed empty"


def test_ellipse_selection_is_round_not_rectangular(canvas):
    selection.select_region(canvas, "ellipse", x=3, y=3, width=10, height=10)
    described = selection.get_selection(canvas)
    assert described["bounds"] == {"x": 3, "y": 3, "width": 10, "height": 10}
    # A rectangle of that box would be 100; a disc inscribed in it is materially less.
    assert 60 <= described["area"] < 100, described["area"]
    assert described["map"][0].count("#") < described["map"][5].count("#")


def test_polygon_selection_covers_its_interior(canvas):
    selection.select_region(
        canvas,
        "polygon",
        points=[{"x": 8, "y": 2}, {"x": 14, "y": 13}, {"x": 2, "y": 13}],
    )
    described = selection.get_selection(canvas)
    assert described["selection"] is True
    assert described["area"] > 30
    # A triangle's apex row is narrower than its base row.
    assert described["map"][0].count("#") < described["map"][-1].count("#")


def test_select_by_color_scopes_an_edit_to_one_material(canvas):
    """The reason regions matter: one ramp per material, not one ramp per layer."""
    red_ramp = ["#2a1a1a", "#603030", "#a05050", "#c98a8a"]
    drawing.draw_rectangle(canvas, 1, 1, 6, 14, red_ramp[2], filled=True)
    drawing.draw_rectangle(canvas, 9, 1, 6, 14, "#50a050", filled=True)

    selection.select_by_color(canvas, red_ramp[2], tolerance=0)
    shading.shift_along_ramp(canvas, red_ramp, steps=-1)

    rows = inspect.get_pixels(canvas, 0, 0, 16, 16)["pixels"]
    present = {p.lower()[:7] for row in rows for p in row if not p.lower().endswith("00")}
    assert "#50a050" in present, "the other material must be untouched"
    assert red_ramp[1] in present, "the selected material should have darkened a step"
    assert red_ramp[2] not in present, "no pixel of the original shade should remain"


def test_modify_selection_grows_and_shrinks(canvas):
    selection.select_region(canvas, "rect", x=4, y=4, width=8, height=8)
    grown = selection.modify_selection(canvas, "expand", 2)
    assert grown["bounds"] == {"x": 2, "y": 2, "width": 12, "height": 12}
    shrunk = selection.modify_selection(canvas, "contract", 4)
    assert shrunk["bounds"] == {"x": 6, "y": 6, "width": 4, "height": 4}


def test_modify_selection_refuses_when_there_is_nothing_to_modify(canvas):
    from aseprite_mcp.core.errors import AsepriteError

    with pytest.raises(AsepriteError, match="no selection"):
        selection.modify_selection(canvas, "expand", 1)


def test_invert_selection_swaps_inside_for_outside(canvas):
    selection.select_region(canvas, "rect", x=4, y=4, width=8, height=8)
    selection.invert_selection(canvas)
    described = selection.get_selection(canvas)
    assert described["area"] == 16 * 16 - 64

    result = drawing.fill_layer(canvas, "#ff0000")
    assert result["pixels_written"] == 16 * 16 - 64


def test_deselect_removes_the_sidecar_so_edits_are_whole_layer_again(canvas):
    from aseprite_mcp.tools.common import resolve_path

    selection.select_region(canvas, "rect", x=4, y=4, width=8, height=8)
    mask = mask_path_for(resolve_path(canvas))
    assert mask.exists(), "a selection should leave a sidecar"

    cleared = selection.deselect(canvas)
    assert cleared["cleared"] is True
    assert not mask.exists(), "deselect must remove the sidecar, not just empty it"

    assert selection.get_selection(canvas)["selection"] is False
    assert drawing.fill_layer(canvas, "#ff0000")["pixels_written"] == 16 * 16


def test_deselect_is_harmless_when_nothing_is_selected(canvas):
    assert selection.deselect(canvas)["cleared"] is False


def test_get_selection_reports_absence_rather_than_guessing(canvas):
    described = selection.get_selection(canvas)
    assert described["selection"] is False
    assert "bounds" not in described


def test_selection_tools_reject_arguments_that_cannot_mean_anything(canvas):
    with pytest.raises(ValidationFailed, match="shape"):
        selection.select_region(canvas, "triangle")
    with pytest.raises(ValidationFailed, match="mode"):
        selection.select_region(canvas, "rect", mode="toggle")
    with pytest.raises(ValidationFailed, match="3 points"):
        selection.select_region(canvas, "polygon", points=[{"x": 1, "y": 1}])
    with pytest.raises(ValidationFailed, match="op"):
        selection.modify_selection(canvas, "blur")
    with pytest.raises(ValidationFailed, match="quantity"):
        selection.modify_selection(canvas, "expand", 0)
    with pytest.raises(ValidationFailed, match="tolerance"):
        selection.select_by_color(canvas, "#ff0000", tolerance=999)


def test_a_write_the_mask_ate_entirely_still_reports_the_count(canvas):
    """The count matters most when it is the whole answer, and it used to vanish there.

    The result harness attaches the pixel counters under one gate, and `_px_masked` was
    read inside that gate without being part of it. A write whose selection excluded every
    pixel left the other three counters at zero, so the block was skipped and
    `pixels_outside_selection` went with it: the call came back `ok: true` with
    `selection_applied` and no number anywhere.
    """
    selection.select_region(canvas, "rect", x=12, y=0, width=4, height=16)

    asked = [{"x": x, "y": 5} for x in range(10)]
    result = drawing.draw_pixels(canvas, asked, "#ff0000")

    assert result["selection_applied"] is True
    assert result["pixels_written"] == 0
    assert result["pixels_outside_selection"] == len(asked)

    row = inspect.get_pixels(canvas, 0, 5, 10, 1)["pixels"][0]
    assert all(px.lower().endswith("00") for px in row), "nothing should have been drawn"


def test_a_write_with_no_selection_grows_no_selection_fields(canvas):
    """The other half of the gate: absence still reports nothing, which is why it exists."""
    result = drawing.draw_pixels(canvas, [{"x": 1, "y": 1}], "#ff0000")

    assert "selection_applied" not in result
    assert "pixels_outside_selection" not in result


def test_replacing_a_sprite_forgets_its_selection(canvas):
    """A selection belongs to a sprite, so replacing the sprite has to replace it too.

    `create_sprite(overwrite=True)` left the sidecar in place, and the brand new sprite
    then opened with a selection inherited from a sprite that no longer existed. Every
    edit outside that rectangle was dropped, and the error surfaced calls later.
    """
    selection.select_region(canvas, "rect", x=12, y=0, width=4, height=16)
    assert mask_path_for(resolve_path(canvas)).exists()

    replaced = sprite.create_sprite(canvas, 16, 16, overwrite=True)

    assert replaced["discarded_selection"] is True
    assert not mask_path_for(resolve_path(canvas)).exists()
    # The real test is the next edit, not the missing file.
    assert drawing.fill_layer(canvas, "#ff0000")["pixels_written"] == 16 * 16


def test_a_fresh_sprite_says_nothing_about_a_selection_it_never_had(canvas):
    made = sprite.create_sprite(f"sel/{'fresh'}.aseprite", 8, 8, overwrite=True)
    assert "discarded_selection" not in made


def test_saving_under_a_name_does_not_inherit_that_name_s_selection(canvas):
    """A copy is a different sprite, so a sidecar already at its path is not its."""
    other = "sel/save_as_target.aseprite"
    sprite.create_sprite(other, 16, 16, overwrite=True)
    selection.select_region(other, "rect", x=12, y=0, width=4, height=16)
    assert mask_path_for(resolve_path(other)).exists()

    sprite.save_sprite_as(canvas, other, overwrite=True)

    assert not mask_path_for(resolve_path(other)).exists()
    assert drawing.fill_layer(other, "#00ff00")["pixels_written"] == 16 * 16
