"""Evening out the run lengths along a silhouette's diagonals.

The claim `normalize_edge_runs` makes is geometric and this project already owns the
measurement: `quality.jaggy_corners` counts 2x2 windows holding exactly three drawn
pixels, which on a boundary that steps one way is the number of steps. So every test here
counts something. The pure ones work on a silhouette of booleans, where a stumble can be
written down exactly; the editor-tier ones build a sprite, run the tool and measure the
result with `assess_sprite`, which is a different code path from the one the tool reports
from and therefore an independent check on it.

Two properties are asserted everywhere rather than in one place, because they are what
makes the pass safe to run on finished art: the bounding box does not move, and no pixel
is ever removed. The third, that no new colour appears, is checked off the sprite, since
only the editor knows what colour the neighbour was.

The refusals get as much room as the successes. A tool that evens out edges will be
pointed at a clean 1:1 diagonal, at a spike somebody drew on purpose and at a
one-pixel-wide limb, and in all three cases the right answer is to decline and say which
rule declined. A pass that touched any of them would be destroying work while reporting a
lower number.
"""
from __future__ import annotations

import pytest

from aseprite_mcp.core import edges, quality
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, effects, inspect, palette, selection, sprite

W = H = 40
STONE = "#6b6477"
SHADE = "#3d3848"

# A flank whose runs go 3, 1, 2, 1, 4 and 4, 1, 2, 1, 3 coming back, where a hand would
# have drawn an even slope. Both sides wander, so the pass has something to do on each.
LEFT = [14, 14, 14, 13, 12, 12, 11, 10, 10, 10, 10, 10, 10, 10, 11, 12, 12, 13, 14, 14]
RIGHT = [25, 25, 25, 26, 27, 27, 28, 29, 29, 29, 29, 29, 29, 29, 28, 27, 27, 26, 25, 25]
BLOB_Y = 8


def _mask(left, right, *, width=W, height=None):
    """A solid shape spanning left[i] to right[i] on each row, as rows of booleans."""
    height = height if height is not None else len(left)
    return [[left[y] <= x <= right[y] for x in range(width)] for y in range(height)]


def _blob_rows():
    """The wandering blob as a character map, which is how this project authors a figure."""
    return ["".join("a" if LEFT[i] <= x <= RIGHT[i] else "." for x in range(W))
            for i in range(len(LEFT))]


# ------------------------------------------------------------------ the metric is shared
@pytest.mark.pure
def test_the_mask_metric_is_the_one_assess_sprite_reports():
    """`core.edges` scores the silhouette it is planning against, and the only honest way
    to do that is with the same function the report uses. Two transcriptions of a metric
    are two metrics, and the one that drifts is always the one nobody is looking at."""
    mask = _mask(LEFT, RIGHT)
    grid = [[("#6b6477ff" if cell else "#00000000") for cell in row] for row in mask]
    assert quality.jaggy_corners(grid) == quality.jaggy_corners_in_mask(mask)
    assert quality.opacity_mask(grid) == mask


# ------------------------------------------------------------------------ the plan itself
@pytest.mark.pure
def test_merging_a_stray_one_row_run_costs_a_step_each_time():
    """The mechanic, stated as a number. Runs of 3, 1, 2, 1, 4 hold four steps; merging
    the two one-row runs into the neighbours below them leaves two."""
    plan = edges.plan(_mask(LEFT, RIGHT))
    assert plan["runs_merged"] == len(plan["add"])
    assert plan["jaggy_after"] == plan["jaggy_before"] - plan["runs_merged"], plan
    assert plan["by_side"] == {"left": 4, "right": 4}, plan["by_side"]


@pytest.mark.pure
def test_the_plan_only_ever_paints_a_pixel_that_was_not_there():
    """Why the extent cannot move and why nothing can be eaten. Each entry also names an
    already-drawn neighbour to take the colour from, so the write cannot invent one."""
    mask = _mask(LEFT, RIGHT)
    plan = edges.plan(mask)
    for pixel in plan["add"]:
        assert not mask[pixel["y"]][pixel["x"]], f"{pixel} was already drawn"
        assert mask[pixel["from_y"]][pixel["from_x"]], (
            f"{pixel} takes its colour from a pixel that is not drawn")
        assert abs(pixel["x"] - pixel["from_x"]) + abs(pixel["y"] - pixel["from_y"]) == 1, (
            f"{pixel} copies from something that is not its own neighbour")


@pytest.mark.pure
def test_the_plan_cannot_move_the_bounding_box():
    """Asserted here as well as guarded in `plan`, because the guard is the thing that
    would be deleted by somebody who believed the comment above it."""
    mask = _mask(LEFT, RIGHT)
    before = quality.bounding_box(
        [[("#ffffffff" if c else "#00000000") for c in row] for row in mask])
    plan = edges.plan(mask)
    assert plan["bbox"] == list(before)
    for pixel in plan["add"]:
        assert before.x0 <= pixel["x"] <= before.x1, pixel
        assert before.y0 <= pixel["y"] <= before.y1, pixel


# ---------------------------------------------------------------------------- refusals
@pytest.mark.pure
def test_a_clean_diagonal_is_refused_rather_than_evened():
    """A 1:1 slope is the most consistent edge there is, and every one of its runs is a
    single row. Touching it would be vandalism reported as an improvement."""
    left = list(range(18, 8, -1))
    with pytest.raises(ValidationFailed) as caught:
        edges.plan(_mask(left, [30] * len(left)))
    message = str(caught.value)
    assert "1:1 diagonal" in message, message
    assert "no edge run qualified" in message, message


@pytest.mark.pure
@pytest.mark.parametrize("left,label", [
    ([14, 14, 14, 12, 14, 14, 14], "spike"),
    ([12, 12, 12, 14, 12, 12, 12], "notch"),
])
def test_a_local_extremum_is_a_feature_and_is_left_alone(left, label):
    """A run further out than both neighbours is a horn or a finger; one further in is a
    chip. Neither is a step, and the monotonicity rule is what tells them apart."""
    with pytest.raises(ValidationFailed, match="a spike or a notch"):
        edges.plan(_mask(left, [30] * len(left)))


@pytest.mark.pure
def test_a_step_of_more_than_one_pixel_is_a_change_of_slope():
    with pytest.raises(ValidationFailed, match="step by more than one pixel"):
        edges.plan(_mask([16, 16, 14, 12, 12], [30] * 5))


@pytest.mark.pure
def test_a_hairline_is_protected_by_min_span_and_the_floor_is_two():
    """The same stumble on a two-pixel limb and on a wide mass. At the default the limb is
    left alone, because a pixel added to something two wide is half again as wide; at
    min_span=2 it is treated as an edge. The knob is the whole difference, so both
    directions are asserted rather than only the refusal."""
    limb = _mask([10, 10, 9, 8, 8], [11, 11, 10, 9, 9])
    with pytest.raises(ValidationFailed, match="thinner than min_span 3"):
        edges.plan(limb)
    # Two, not one: the limb wanders on both flanks, so each side has a run to merge.
    allowed = edges.plan([list(row) for row in limb], min_span=2)
    assert allowed["runs_merged"] == 2, allowed
    assert allowed["jaggy_after"] < allowed["jaggy_before"], allowed

    with pytest.raises(ValidationFailed, match=r"min_span is 1; the minimum is 2"):
        edges.plan(limb, min_span=1)


@pytest.mark.pure
def test_an_empty_silhouette_and_a_ragged_one_are_both_refused():
    with pytest.raises(ValidationFailed, match="nothing is drawn"):
        edges.plan([[False] * 6 for _ in range(6)])
    with pytest.raises(ValidationFailed, match="has to be rectangular"):
        edges.plan([[True, True, True], [True, True]])


@pytest.mark.pure
def test_a_gap_in_the_profile_does_not_join_two_shapes_into_one_staircase():
    """Two blobs stacked with a clear row between them are two staircases. Carrying the
    profile across the gap would invent a step that is not on either of them, and the
    merge it justified would paint a pixel into empty canvas."""
    rows = _mask([14, 14, 13, 12, 12], [20] * 5)
    rows += [[False] * W]
    rows += _mask([14, 14, 13, 12, 12], [20] * 5)
    plan = edges.plan(rows)
    for pixel in plan["add"]:
        assert pixel["y"] != 5, f"a pixel was planned into the empty row: {pixel}"
    assert plan["jaggy_after"] < plan["jaggy_before"], plan


# -------------------------------------------------------------------- the editor tier
@pytest.fixture
def blob(request):
    """The wandering blob on a real sprite, drawn from the same character map."""
    name = f"runs_{request.node.name.replace('[', '_').replace(']', '')}.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_pixel_map(name, _blob_rows(), {"a": STONE}, x=0, y=BLOB_Y)
    return name


def _measured(name):
    return inspect.assess_sprite(name)["metrics"]


def test_the_jagged_corner_count_drops_on_a_real_sprite(blob):
    """The headline, measured twice by two different routes: the count the tool reports
    and the count `assess_sprite` reads back off the file afterwards."""
    before = _measured(blob)
    result = effects.normalize_edge_runs(blob)
    after = _measured(blob)

    assert result["jaggy_corners_before"] == before["jaggy_corners"], (result, before)
    assert after["jaggy_corners"] < before["jaggy_corners"], (
        f"the pass merged {result['runs_merged']} runs and the measured count went from "
        f"{before['jaggy_corners']} to {after['jaggy_corners']}")
    assert result["jaggy_corners_after"] == after["jaggy_corners"], (
        f"the tool reported {result['jaggy_corners_after']} jagged corners after the pass "
        f"and the sprite measures {after['jaggy_corners']}, so the plan and the file "
        "disagree")


def test_the_silhouette_grows_and_its_extent_does_not_move(blob):
    """The two promises, off the sprite rather than off the plan. A pass that shrank a
    figure or moved its box would be a redraw, whatever it did to the metric."""
    before = _measured(blob)
    result = effects.normalize_edge_runs(blob)
    after = _measured(blob)

    assert after["bbox"] == before["bbox"], (
        f"the extent moved from {before['bbox']} to {after['bbox']}")
    assert after["drawn_pixels"] == before["drawn_pixels"] + result["runs_merged"], (
        f"{before['drawn_pixels']} pixels became {after['drawn_pixels']} for "
        f"{result['runs_merged']} merges, so something was removed as well as added")


def test_no_colour_that_was_not_already_in_the_sprite_appears(blob):
    """Each added pixel copies the neighbour its run is merging into, so art on a ramp
    stays on it and the tool never has to know what a ramp is."""
    def colours(name):
        rows = inspect.get_pixels(name, 0, 0, W, H)["pixels"]
        return {px.lower() for row in rows for px in row}

    before = colours(blob)
    effects.normalize_edge_runs(blob)
    assert colours(blob) <= before, f"new colours appeared: {colours(blob) - before}"


def test_a_rasterised_disc_is_declined_rather_than_smoothed():
    """Conservatism, measured on the shape most likely to be handed to this tool. A disc
    drawn by Aseprite's own ellipse scores 32 jagged corners at this size and every one of
    its one-row runs sits beside another one-row run, which is a circle's 45-degree arc and
    not a stumble. Declining is the correct answer and the refusal says so."""
    name = "runs_disc.aseprite"
    sprite.create_sprite(name, W, H, overwrite=True)
    drawing.draw_ellipse(name, 20, 20, 13, 13, STONE, filled=True)
    before = _measured(name)
    assert before["jaggy_corners"] > 0, "a raster disc with no jagged corners is not a disc"

    with pytest.raises(ValidationFailed) as caught:
        effects.normalize_edge_runs(name)
    assert "1:1 diagonal" in str(caught.value), str(caught.value)
    assert _measured(name)["jaggy_corners"] == before["jaggy_corners"], (
        "the refusal still changed the sprite")


def test_an_empty_frame_is_refused_by_name(blob):
    """Named for the layer and frame, because "nothing is drawn" on a sprite with four
    layers is not a finding anyone can act on."""
    sprite.create_sprite("runs_empty.aseprite", W, H, overwrite=True)
    with pytest.raises(ValidationFailed) as caught:
        effects.normalize_edge_runs("runs_empty.aseprite")
    message = str(caught.value)
    assert "nothing drawn on frame 1" in message, message


def test_a_selection_that_masks_the_plan_withholds_the_after_figure(blob):
    """The plan is scored against a silhouette with every merge in it. With the mask
    refusing some of them the shape on disk is a different one, and reporting the planned
    figure against it would be a measurement of something that was not painted."""
    selection.select_region(blob, x=0, y=0, width=2, height=2)
    try:
        result = effects.normalize_edge_runs(blob)
    finally:
        selection.deselect(blob)

    assert result["pixels_written"] == 0, result
    assert "jaggy_corners_after" not in result, (
        f"an after figure was reported for a pass that wrote nothing: {result}")
    assert any("withheld" in note for note in result.get("warnings", [])), result


def test_an_indexed_sprite_needs_no_colour_resolution_at_all(request):
    """The one place copying the neighbour rather than naming a colour pays off twice. On an
    indexed sprite a colour has to be resolved against the palette and can land on a
    different entry than the one asked for; copying the neighbour's pixel copies its
    *index*, so the merged run is the same palette entry as the run it merged into, exactly
    and with nothing to resolve."""
    name = f"runs_indexed_{request.node.name}.aseprite"
    sprite.create_sprite(name, W, H, color_mode="indexed", overwrite=True)
    palette.set_palette(name, ["#00000000", SHADE, STONE])
    drawing.draw_pixel_map(name, _blob_rows(), {"a": STONE}, x=0, y=BLOB_Y)

    before = _measured(name)
    result = effects.normalize_edge_runs(name)
    after = _measured(name)
    assert result["runs_merged"] > 0, result
    assert after["jaggy_corners"] < before["jaggy_corners"], (before, after)
    assert after["colors"] == before["colors"], (
        f"the merge introduced a palette entry: {before['colors']} became "
        f"{after['colors']}")
