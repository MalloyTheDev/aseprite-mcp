"""Tone curves (#92): the arithmetic, and the pass that applies it.

The curve is built in Python so it can be checked without an editor, and the tests that
do that are marked `pure`. The rest need Aseprite (--run-aseprite).

The numbers the pure tests assert are not invented. Aseprite's own `ColorCurve` command
was run headless over a grey ramp and its output recorded, which is what established that
it interpolates linearly, truncates rather than rounds, and holds the end values outside
the span of the control points. The tool is then held to the command itself on a real
sprite, so the reimplementation cannot drift from the editor it mirrors.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.curves import MAX_CURVE_POINTS, curve_table
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import run_lua
from aseprite_mcp.tools import drawing, effects, inspect, selection, sprite
from aseprite_mcp.tools.common import lua_path, resolve_path

LIFT = [[0, 0], [128, 192], [255, 255]]
ORB = ["#17145d", "#283aa7", "#5a7fd4", "#a6c4e6", "#f0f7fb"]


# --- the arithmetic, measured against the editor -------------------------------------


@pytest.mark.pure
@pytest.mark.parametrize("tone, want", [(36, 54), (73, 109), (146, 200)])
def test_a_curve_interpolates_the_way_the_editor_does(tone, want):
    """Linear between the corners, and truncated: 146 arrives at 200, not 201."""
    assert curve_table(LIFT)[tone] == want


@pytest.mark.pure
def test_the_ends_are_pinned_where_the_curve_pins_them():
    table = curve_table(LIFT)
    assert (table[0], table[128], table[255]) == (0, 192, 255)


@pytest.mark.pure
@pytest.mark.parametrize("tone, want", [(0, 0), (32, 0), (96, 63), (128, 127),
                                        (160, 191), (224, 255), (255, 255)])
def test_outside_the_control_points_the_end_values_hold(tone, want):
    """With corners at 64 and 192, everything below and above is flattened to them."""
    assert curve_table([[64, 0], [192, 255]])[tone] == want


@pytest.mark.pure
def test_a_descending_curve_inverts():
    table = curve_table([[0, 255], [255, 0]])
    assert (table[0], table[128], table[255]) == (255, 127, 0)


@pytest.mark.pure
def test_one_control_point_flattens_every_tone():
    assert set(curve_table([[128, 64]])) == {64}


@pytest.mark.pure
def test_a_curve_is_a_function_so_it_can_never_add_a_tone():
    """The property the tool's docstring rests on: 256 inputs, one output each, so a
    drawing cannot come out with more colours than it went in with."""
    table = curve_table([[0, 0], [60, 10], [200, 250], [255, 255]])
    assert len(table) == 256
    assert all(0 <= value <= 255 for value in table)
    assert len({table[t] for t in range(256)}) <= 256


@pytest.mark.pure
@pytest.mark.parametrize("points, match", [
    ([], "points is empty"),
    ([[0, 0], [0, 255]], "the inputs have to climb"),
    ([[128, 0], [64, 255]], "the inputs have to climb"),
    ([[0, 300]], "a tone runs from 0 to 255"),
    ([[-1, 0], [255, 255]], "a tone runs from 0 to 255"),
    ([[1, 2, 3]], "a pair"),
    ([["0", "255"]], "two whole numbers"),
    ([[0, 0], [128, 1.5], [255, 255]], "not fractional"),
])
def test_a_malformed_curve_is_refused_by_name(points, match):
    with pytest.raises(ValueError, match=match):
        curve_table(points)


@pytest.mark.pure
def test_more_control_points_than_tones_is_refused():
    with pytest.raises(ValueError, match="at most"):
        curve_table([[0, 0]] * (MAX_CURVE_POINTS + 1))


# --- the pass, against Aseprite ------------------------------------------------------


def _orb(name: str) -> str:
    """The showcase orb's five colours, as a strip: one pixel per colour."""
    sprite.create_sprite(name, len(ORB), 1, overwrite=True)
    for i, colour in enumerate(ORB):
        drawing.draw_pixels(name, [{"x": i, "y": 0}], colour)
    return name


def _colours(name: str) -> list[str]:
    row = inspect.get_pixels(name, 0, 0, len(ORB), 1)["pixels"][0]
    return [px[:7] for px in row]


def _editor_curve(name: str, points: list, channels: int | None = None) -> list[str]:
    """The same curve through Aseprite's own command, for the tool to be held to."""
    run_lua("""
    local spr = app.open(ARG.src)
    local pts = {}
    for i, p in ipairs(ARG.points) do pts[i] = { p[1], p[2] } end
    app.command.ColorCurve{ ui=false, channels=ARG.channels, curve=pts }
    spr:saveAs(spr.filename)
    RESULT = { ok = true }
    """, {"src": lua_path(resolve_path(name)), "points": points, "channels": channels})
    return _colours(name)


@pytest.mark.parametrize("points, channel, flag", [
    (LIFT, "rgb", None),
    ([[0, 0], [128, 200], [255, 255]], "red", 1),
    ([[0, 0], [128, 200], [255, 255]], "green", 2),
    ([[0, 0], [128, 200], [255, 255]], "blue", 4),
    ([[0, 255], [255, 0]], "rgb", None),
])
def test_the_pass_lands_where_aseprites_own_command_lands(points, channel, flag):
    """The reimplementation is only worth having if it matches the editor exactly."""
    mine = _orb(f"cc/mine_{channel}_{abs(hash(str(points)))% 999}.aseprite")
    effects.apply_color_curve(mine, points, channel=channel)
    theirs = _editor_curve(_orb(f"cc/theirs_{channel}_{abs(hash(str(points)))% 999}.aseprite"),
                           points, flag)
    assert _colours(mine) == theirs


def test_a_curve_adds_no_colour_and_no_transparency():
    """What separates a curve from a convolution kernel, which on this same art produced
    89 colours and 208 semi-transparent pixels."""
    name = _orb("cc/count.aseprite")
    effects.apply_color_curve(name, LIFT)

    row = inspect.get_pixels(name, 0, 0, len(ORB), 1)["pixels"][0]
    assert len({px[:7] for px in row}) <= len(ORB)
    assert all(px[7:9] == "ff" for px in row), "a curve never makes a pixel part transparent"


def test_a_single_channel_leaves_the_others_alone():
    name = _orb("cc/channel.aseprite")
    effects.apply_color_curve(name, [[0, 0], [128, 200], [255, 255]], channel="red")

    for before, after in zip(ORB, _colours(name), strict=True):
        assert after[3:] == before[3:], "green and blue moved"
        assert after[1:3] >= before[1:3], "red should have risen"


def test_the_pass_is_clipped_to_a_selection():
    """It runs through the shared drawing path, so the selection applies as it does to
    every other per-pixel pass."""
    name = _orb("cc/selected.aseprite")
    before = _colours(name)
    selection.select_region(name, shape="rect", x=0, y=0, width=2, height=1)
    result = effects.apply_color_curve(name, LIFT)

    after = _colours(name)
    assert after[:2] != before[:2], "the selected pixels should have moved"
    assert after[2:] == before[2:], "the rest should not have"
    assert result["pixels_outside_selection"] == len(ORB) - 2


@pytest.mark.pure
def test_an_unknown_channel_is_refused_before_launch(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a channel that does not exist")
    monkeypatch.setattr(effects, "run_lua", refuse)

    with pytest.raises(ValidationFailed, match="channel is 'alpha'"):
        effects.apply_color_curve("cc/x.aseprite", LIFT, channel="alpha")


def test_a_curve_on_a_grayscale_sprite_maps_through_the_table():
    """The two halves of this session's work meeting: a grayscale sprite's single value
    is read as r=g=b, curved, and written back through the luma conversion, which sums to
    one, so the tone that comes out is exactly the one the table names."""
    values = [0, 36, 73, 109, 146, 182, 219, 255]
    name = "cc/grayscale.aseprite"
    sprite.create_sprite(name, len(values), 1, color_mode="gray", overwrite=True)
    for i, value in enumerate(values):
        drawing.draw_pixels(name, [{"x": i, "y": 0}], f"#{value:02x}{value:02x}{value:02x}")

    effects.apply_color_curve(name, LIFT)

    row = inspect.get_pixels(name, 0, 0, len(values), 1)["pixels"][0]
    table = curve_table(LIFT)
    assert [int(px[1:3], 16) for px in row] == [table[v] for v in values]
