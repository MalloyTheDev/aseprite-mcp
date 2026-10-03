"""A sprite written as a character grid, and read back as the same one.

`get_pixels(format="map")` could always hand a caller a legend plus one string per row;
nothing could hand a map back. The server could show per-pixel intent and could not
receive it, so authoring a figure meant a list of `{"x", "y", "color"}` dictionaries, one
per pixel, and a caller facing a thousand-entry list writes a formula rather than a
thousand considered pixels.

Two groups here. The pure ones hold `core.pixelmap.expand` to refusing every way a
hand-written grid goes wrong, because the whole value of the notation is that a mistake in
it is visible and reported rather than silently painted. The editor-tier ones hold the
tool to the claim its docstring makes: that a map goes through the same write path as
`draw_pixels`, so it inherits the selection mask and the clipping counters instead of
growing a second one.
"""
from __future__ import annotations

import pytest

from aseprite_mcp.core import pixelmap
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_PIXEL_LIST_LENGTH
from aseprite_mcp.tools import drawing, inspect, selection, sprite

FACE = [
    "....aaaa....",
    "..aabbbbaa..",
    ".abbbccbbba.",
    ".abbccccbba.",
    ".abbbccbbba.",
    "..aabbbbaa..",
    "....aaaa....",
    "............",
]
LEGEND = {"a": "#1b2b4a", "b": "#4a7ab0", "c": "#dff2ff"}


# ----------------------------------------------------------------- the pure expansion
@pytest.mark.pure
def test_a_map_expands_to_the_pixels_it_describes():
    plan = pixelmap.expand(FACE, LEGEND)
    assert plan["width"] == 12
    assert plan["height"] == 8
    # 96 cells, 42 of them deliberately left alone.
    assert len(plan["pixels"]) + plan["transparent"] == 96
    assert plan["transparent"] == 42
    assert set(plan["colors_used"]) == set(LEGEND.values())
    assert plan["pixels"][0] == {"x": 4, "y": 0, "color": "#1b2b4a"}


@pytest.mark.pure
def test_the_origin_moves_the_whole_map():
    plan = pixelmap.expand(FACE, LEGEND, 10, 7)
    assert plan["pixels"][0] == {"x": 14, "y": 7, "color": "#1b2b4a"}
    assert min(p["x"] for p in plan["pixels"]) == 11
    assert min(p["y"] for p in plan["pixels"]) == 7


@pytest.mark.pure
def test_a_ragged_map_is_refused_and_says_which_row():
    """Padding a short row would shift every pixel after it, which is the one failure a
    hand-written grid actually makes and the one it must not be forgiven."""
    rows = ["aaa", "aa", "aaa"]
    with pytest.raises(ValidationFailed, match=r"rows\[1\] is 2 characters and rows\[0\] is 3"):
        pixelmap.expand(rows, {"a": "red"})


@pytest.mark.pure
def test_a_character_the_legend_does_not_define_is_refused_not_skipped():
    """The whole point of the notation is that a typo is reported. Skipping an unknown
    character would paint nothing there and still return success, which is the failure
    this project treats as worse than an error."""
    rows = ["aaa", "abq", "aaa"]
    with pytest.raises(ValidationFailed) as caught:
        pixelmap.expand(rows, {"a": "red", "b": "blue"})
    message = str(caught.value)
    assert "rows[1][2] is 'q'" in message, message
    assert "'ab'" in message, message


@pytest.mark.pure
def test_a_dot_means_leave_it_alone_without_being_declared():
    plan = pixelmap.expand(["a.a"], {"a": "red"})
    assert [p["x"] for p in plan["pixels"]] == [0, 2]
    assert plan["transparent"] == 1


@pytest.mark.pure
def test_the_word_transparent_says_the_same_for_any_character():
    """Which is what `get_pixels(format="map")` emits in its legend, so its output is
    valid input here."""
    plan = pixelmap.expand(["axa"], {"a": "red", "x": "transparent"})
    assert plan["transparent"] == 1
    assert len(plan["pixels"]) == 2


@pytest.mark.pure
def test_a_map_that_would_draw_nothing_is_refused():
    with pytest.raises(ValidationFailed, match=r"every one of its 6 cells is transparent"):
        pixelmap.expand(["...", "..."], {"a": "red"})


@pytest.mark.pure
def test_a_legend_key_has_to_be_one_character():
    with pytest.raises(ValidationFailed, match=r"is not a single character"):
        pixelmap.expand(["ab"], {"ab": "red"})


@pytest.mark.pure
@pytest.mark.parametrize("rows", [[], "aaa", [123], ["a", 7]])
def test_rows_has_to_be_a_list_of_strings(rows):
    with pytest.raises(ValidationFailed):
        pixelmap.expand(rows, {"a": "red"})


@pytest.mark.pure
def test_a_map_past_the_pixel_cap_is_refused_before_anything_is_drawn():
    side = 300  # 90,000 cells, past the 65,536 per-call cap
    rows = ["a" * side] * side
    with pytest.raises(ValidationFailed, match=rf"maximum per call is {MAX_PIXEL_LIST_LENGTH}"):
        pixelmap.expand(rows, {"a": "red"})


# ------------------------------------------------------------------- the editor tier
@pytest.fixture
def canvas(request):
    name = f"map_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, 12, 8, overwrite=True)
    return name


def test_a_map_draws_what_it_says(canvas):
    result = drawing.draw_pixel_map(canvas, FACE, LEGEND)
    assert result["pixels_written"] == 54
    assert result["pixels_transparent"] == 42
    assert result["map_width"] == 12 and result["map_height"] == 8
    back = inspect.get_pixels(canvas, 0, 0, 12, 8)["pixels"]
    for y, row in enumerate(FACE):
        for x, symbol in enumerate(row):
            got = back[y][x]
            if symbol == ".":
                assert got[7:9] == "00", f"({x},{y}) should be untouched, got {got}"
            else:
                assert got[:7].lower() == LEGEND[symbol].lower(), f"({x},{y}) is {got}"


def test_a_map_read_back_is_the_same_map(canvas):
    """The round trip, which is the reason the input shape matches the output shape.

    The read side assigns its symbols in first-seen order, so a map whose own symbols are
    already in that order comes back character for character. That is what makes a read,
    an edit and a write a usable loop rather than a format conversion.
    """
    drawing.draw_pixel_map(canvas, FACE, LEGEND)
    out = inspect.get_pixels(canvas, 0, 0, 12, 8, format="map")
    assert out["rows"] == FACE, "\n".join(out["rows"])
    assert out["legend"]["."] == "transparent"
    assert {s: c[:7] for s, c in out["legend"].items() if s != "."} == LEGEND


def test_a_map_honours_an_active_selection(canvas):
    """The claim the docstring makes, tested rather than asserted: a map goes through the
    same `img_set` as `draw_pixels`, so the mask is consulted and the refusal is counted.
    A second write path would have had to reimplement that and would have forgotten."""
    selection.select_region(canvas, "rect", x=0, y=0, width=6, height=8)
    result = drawing.draw_pixel_map(canvas, FACE, LEGEND)
    assert result["selection_applied"] is True, result
    assert result["pixels_outside_selection"] > 0, result
    right = inspect.get_pixels(canvas, 6, 0, 6, 8)["pixels"]
    painted = [px for row in right for px in row if px[7:9] != "00"]
    assert not painted, f"the mask was ignored on the right half: {painted[:4]}"


def test_transparent_cells_leave_what_was_there(canvas):
    """So a map can be stamped over existing art, which is the common case."""
    drawing.draw_rectangle(canvas, 0, 0, 12, 8, "#102030", filled=True)
    drawing.draw_pixel_map(canvas, ["..a..", "..a.."], {"a": "#ff0000"}, x=3, y=3)
    back = inspect.get_pixels(canvas, 0, 0, 12, 8)["pixels"]
    assert back[3][5][:7].lower() == "#ff0000"
    assert back[3][3][:7].lower() == "#102030", "a transparent cell erased the art under it"


def test_a_map_hanging_off_the_canvas_clips_and_counts(canvas):
    """`img_set` does the clipping, so the counter is the one every other write reports."""
    result = drawing.draw_pixel_map(canvas, ["aaaa", "aaaa"], {"a": "#00ff00"}, x=10, y=6)
    assert result["pixels_clipped"] > 0, result
    assert result["pixels_written"] < 8, result
