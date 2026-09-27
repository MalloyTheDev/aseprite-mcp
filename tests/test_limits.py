"""Pure-Python tests for the per-call work limits (DoS guard), with no Aseprite.

The caps are enforced before any path resolution or Aseprite launch, so the
tool-level cases raise without a real Aseprite (the check fires first).

Three groups:

* **collection limits**: how many items one call may carry;
* **scalar limits**: the loop bounds and repetition counts that buy the same work
  from a single integer (a region's width, an outline's thickness, curve steps, a
  palette size reached through an index);
* **launch limits**: the workflow scaffolds, where one integer used to buy two
  Aseprite process launches per frame.

Where a cap is checked *at* its ceiling the Lua runner is stubbed out (the `lua`
fixture), so the at-the-cap call genuinely succeeds instead of merely failing for a
different reason.
"""

import pytest

from aseprite_mcp.core import limits, oplib
from aseprite_mcp.core.errors import AsepriteMCPError, ValidationFailed
from aseprite_mcp.tools import brushes, drawing, effects, palette, tilemap, workflow


@pytest.fixture
def lua(monkeypatch):
    """Capture Lua bodies/args instead of launching Aseprite.

    Every tool below routes through `run_lua`; `brushes`/`effects` go via
    `drawing._draw`, which reads `drawing.run_lua`.
    """
    calls = []

    def fake_run_lua(body, args=None, timeout=None):
        calls.append({"body": body, "args": args or {}})
        return {"ok": True, "size": 0}

    for mod in (brushes, drawing, effects, palette):
        monkeypatch.setattr(mod, "run_lua", fake_run_lua)
    return calls


# --------------------------------------------------------- check_list_length
def test_at_limit_is_allowed():
    limits.check_list_length("x", [0] * 10, 10)  # exactly the max: no raise


def test_over_limit_message_has_all_parts():
    with pytest.raises(ValidationFailed) as excinfo:
        limits.check_list_length(
            "operations", [0] * 731, 500, remedy="Split the edit into multiple batches."
        )
    msg = str(excinfo.value)
    assert "operations" in msg  # field
    assert "731" in msg         # received count
    assert "500" in msg         # maximum
    assert "Split the edit into multiple batches." in msg  # remedy


def test_default_remedy_present():
    with pytest.raises(ValidationFailed, match="smaller calls"):
        limits.check_list_length("colors", [0] * 2, 1)


# ------------------------------------------------------- wired call sites
def test_set_palette_color_cap():
    colors = ["#000000"] * (limits.MAX_COLOR_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"colors has \d+ items; maximum is 256"):
        palette.set_palette("w/x.aseprite", colors)


def test_draw_pixels_cap():
    pixels = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"pixels has \d+ items; maximum is 65536"):
        drawing.draw_pixels("w/x.aseprite", pixels, color="#ffffff")


def test_draw_polyline_cap():
    points = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"points has \d+ items; maximum is 65536"):
        drawing.draw_polyline("w/x.aseprite", points, color="#ffffff")


def test_set_tiles_cap():
    tiles = [{"column": 0, "row": 0, "index": 0}] * (limits.MAX_TILE_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"tiles has \d+ items; maximum is 65536"):
        tilemap.set_tiles("w/x.aseprite", "tiles", tiles)


def test_paint_tile_pixels_cap():
    pixels = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"pixels has \d+ items; maximum is 65536"):
        tilemap.paint_tile_pixels("w/x.aseprite", "tiles", 1, pixels, color="#ffffff")


def test_oplib_batch_cap_reexposed():
    ops = [{"op": "add_layer", "args": {"name": "x"}}] * (limits.MAX_BATCH_OPERATIONS + 1)
    with pytest.raises(ValidationFailed, match="Split the edit into multiple batches"):
        oplib.validate_operations(ops)


# ============================================================ check_count
def test_check_count_at_the_cap_is_allowed():
    assert limits.check_count("thickness", 64, 64) == 64


def test_check_count_message_has_all_parts():
    with pytest.raises(ValidationFailed) as excinfo:
        limits.check_count("thickness", 4096, 64, remedy="Outline in several calls.")
    msg = str(excinfo.value)
    assert "thickness" in msg          # field
    assert "4096" in msg               # received value
    assert "64" in msg                 # cap
    assert "Outline in several calls." in msg


def test_check_count_enforces_a_minimum():
    with pytest.raises(ValidationFailed, match="is 0; minimum is 1"):
        limits.check_count("count", 0, 10, minimum=1)


def test_check_count_rejects_non_numbers():
    with pytest.raises(ValidationFailed, match="whole number"):
        limits.check_count("steps", "lots", 10)


# ==================================== palette: one cap, whichever tool (#57)
# MAX_COLOR_LIST_LENGTH used to bind only `set_palette`, the one tool taking a list.
# `resize_palette(size)` and `set_palette_color(index)` reach the same palette through
# a single integer and had no bound at all.
def test_resize_palette_at_the_palette_cap(lua):
    palette.resize_palette("w/x.aseprite", limits.MAX_COLOR_LIST_LENGTH)
    assert lua[0]["args"]["size"] == 256


def test_resize_palette_past_the_palette_cap(lua):
    with pytest.raises(ValidationFailed, match=r"size is 257; maximum is 256"):
        palette.resize_palette("w/x.aseprite", 257)
    assert not lua, "must be rejected before Aseprite is launched"


def test_resize_palette_realistic_size_still_works(lua):
    palette.resize_palette("w/x.aseprite", 16)
    assert lua[0]["args"]["size"] == 16


def test_set_palette_color_at_the_last_index(lua):
    palette.set_palette_color("w/x.aseprite", 255, "#ff0000")
    assert lua[0]["args"]["index"] == 255


def test_set_palette_color_past_the_last_index(lua):
    """index 256 grows the palette to 257 entries, past the documented ceiling."""
    with pytest.raises(ValidationFailed, match=r"index is 256; maximum is 255"):
        palette.set_palette_color("w/x.aseprite", 256, "#ff0000")
    assert not lua


def test_set_palette_color_rejects_a_negative_index(lua):
    with pytest.raises(ValidationFailed, match="minimum is 0"):
        palette.set_palette_color("w/x.aseprite", -1, "#ff0000")


def test_set_palette_is_unchanged_at_its_cap(lua):
    """The tool that was already capped keeps behaving exactly as before."""
    palette.set_palette("w/x.aseprite", ["#000000"] * limits.MAX_COLOR_LIST_LENGTH)
    assert len(lua[0]["args"]["colors"]) == 256


def test_generate_ramp_steps_cap():
    """Ramp steps are materialized in Python, so this one is spent before any launch."""
    with pytest.raises(ValidationFailed, match=r"steps is 100000; maximum is 256"):
        palette.generate_ramp("#3878c8", steps=100_000)


def test_generate_ramp_realistic_steps_still_work():
    assert len(palette.generate_ramp("#3878c8", steps=8)["colors"]) == 8


def test_extract_palette_max_colors_capped_when_it_becomes_a_palette(lua):
    with pytest.raises(ValidationFailed, match=r"max_colors is 100000; maximum is 256"):
        palette.extract_palette("w/x.aseprite", max_colors=100_000)


def test_extract_palette_may_still_count_colours_without_applying_them(lua):
    """Reporting that an image has 100k colours is a useful answer, not a palette."""
    palette.extract_palette("w/x.aseprite", max_colors=100_000, set_as_palette=False)
    assert lua[0]["args"]["max_colors"] == 100_000


# ================================ scalars that multiply into work (#58)
def test_draw_brush_row_count_cap(lua):
    brush = ["1"] * (limits.MAX_BRUSH_CELLS + 1)
    with pytest.raises(ValidationFailed, match=r"brush has \d+ items; maximum is 65536"):
        brushes.draw_brush("w/x.aseprite", brush, [{"x": 0, "y": 0}], "#ff0000")
    assert not lua


def test_draw_brush_point_count_cap(lua):
    points = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"points has \d+ items; maximum is 65536"):
        brushes.draw_brush("w/x.aseprite", ["1"], points, "#ff0000")
    assert not lua


def test_draw_brush_plots_at_the_product_cap(lua):
    """65,536 filled cells x 256 points is exactly the plot budget."""
    brush = ["1" * 256] * 256
    points = [{"x": 0, "y": 0}] * 256
    brushes.draw_brush("w/x.aseprite", brush, points, "#ff0000")
    assert (len(lua[0]["args"]["offsets"]) * len(lua[0]["args"]["points"])
            == limits.MAX_BRUSH_PLOTS)


def test_draw_brush_plots_past_the_product_cap(lua):
    """Neither list is over its own cap; the *product* is the work, and it is 16.8M."""
    brush = ["1" * 256] * 256
    points = [{"x": 0, "y": 0}] * 257
    with pytest.raises(ValidationFailed,
                       match=r"brush cells x points is 16842752; maximum is 16777216"):
        brushes.draw_brush("w/x.aseprite", brush, points, "#ff0000")
    assert not lua


def test_draw_brush_realistic_stamp_still_works(lua):
    brushes.draw_brush("w/x.aseprite", ["010", "111", "010"],
                       [{"x": i, "y": i} for i in range(64)], "#ff0000")
    assert len(lua[0]["args"]["offsets"]) == 5 and len(lua[0]["args"]["points"]) == 64


def test_draw_symmetric_pixels_at_the_pixel_cap(lua):
    pixels = [{"x": 0, "y": 0}] * limits.MAX_PIXEL_LIST_LENGTH
    brushes.draw_symmetric_pixels("w/x.aseprite", pixels, "#ff0000", mode="both")
    assert len(lua[0]["args"]["points"]) == limits.MAX_PIXEL_LIST_LENGTH


def test_draw_symmetric_pixels_past_the_pixel_cap(lua):
    """Same list as draw_pixels, times up to 4 plots each, and it was uncapped."""
    pixels = [{"x": 0, "y": 0}] * (limits.MAX_PIXEL_LIST_LENGTH + 1)
    with pytest.raises(ValidationFailed, match=r"pixels has \d+ items; maximum is 65536"):
        brushes.draw_symmetric_pixels("w/x.aseprite", pixels, "#ff0000", mode="both")
    assert not lua


def test_add_outline_at_the_thickness_cap(lua):
    effects.add_outline("w/x.aseprite", "#000000", thickness=limits.MAX_OUTLINE_THICKNESS)
    assert lua[0]["args"]["thickness"] == 64


def test_add_outline_past_the_thickness_cap(lua):
    """Each unit of thickness is a full-canvas scan times 8 neighbours."""
    with pytest.raises(ValidationFailed, match=r"thickness is 65; maximum is 64"):
        effects.add_outline("w/x.aseprite", "#000000", thickness=65)
    assert not lua


def test_add_outline_realistic_thickness_still_works(lua):
    effects.add_outline("w/x.aseprite", "#000000", thickness=2)
    assert lua[0]["args"]["thickness"] == 2


def test_draw_curve_at_the_step_cap(lua):
    drawing.draw_curve("w/x.aseprite", 0, 0, 8, 8, 15, 15, "#ff0000",
                       steps=limits.MAX_CURVE_STEPS)
    assert lua[0]["args"]["steps"] == limits.MAX_CURVE_STEPS


def test_draw_curve_past_the_step_cap(lua):
    with pytest.raises(ValidationFailed, match=r"steps is 4097; maximum is 4096"):
        drawing.draw_curve("w/x.aseprite", 0, 0, 8, 8, 15, 15, "#ff0000", steps=4097)
    assert not lua


def test_draw_curve_realistic_steps_still_work(lua):
    drawing.draw_curve("w/x.aseprite", 0, 15, 8, 0, 15, 15, "#ff0000", steps=24)
    assert lua[0]["args"]["steps"] == 24


# --- region width/height: a canvas-shaped quantity, so bounded like a canvas ---
# The fill loops run `for yy = ry, ry + rh - 1` with only an inner on-canvas skip, so
# an oversized region iterates in full on a 16x16 sprite: width=1e9 is 1e9 iterations.
_REGIONS = [
    pytest.param(
        lambda w, h: effects.fill_gradient(
            "w/x.aseprite", ["#000000", "#ffffff"], width=w, height=h),
        id="fill_gradient"),
    pytest.param(
        lambda w, h: effects.fill_checkerboard(
            "w/x.aseprite", "#000000", "#ffffff", width=w, height=h),
        id="fill_checkerboard"),
    pytest.param(
        lambda w, h: brushes.stamp_pattern("w/x.aseprite", "w/t.png", width=w, height=h),
        id="stamp_pattern"),
]


@pytest.mark.parametrize("call", _REGIONS)
def test_region_at_the_canvas_cap(lua, call):
    call(4096, 4096)
    assert lua[0]["args"]["width"] == 4096


@pytest.mark.parametrize("call", _REGIONS)
def test_region_area_past_the_canvas_cap(lua, call):
    """Both axes are legal on their own; the area is one row over."""
    with pytest.raises(ValidationFailed, match=r"pixels; maximum is 16777216"):
        call(4096, 4097)
    assert not lua


@pytest.mark.parametrize("call", _REGIONS)
def test_region_single_axis_past_the_dimension_cap(lua, call):
    """One axis given, the other left to the canvas: the given axis is still bounded."""
    with pytest.raises(ValidationFailed, match=r"width is 1000000000; maximum is 16384"):
        call(10**9, None)
    assert not lua


@pytest.mark.parametrize("call", _REGIONS)
def test_region_single_axis_at_the_dimension_cap(lua, call):
    call(limits.MAX_CANVAS_DIMENSION, None)
    assert lua[0]["args"]["width"] == limits.MAX_CANVAS_DIMENSION


@pytest.mark.parametrize("call", _REGIONS)
def test_region_whole_canvas_default_still_works(lua, call):
    call(None, None)
    assert lua[0]["args"]["width"] is None


@pytest.mark.parametrize("call", _REGIONS)
def test_region_realistic_size_still_works(lua, call):
    call(32, 32)
    assert (lua[0]["args"]["width"], lua[0]["args"]["height"]) == (32, 32)


def test_region_height_only_is_bounded_too(lua):
    with pytest.raises(ValidationFailed, match=r"height is 1000000000; maximum is 16384"):
        effects.fill_checkerboard("w/x.aseprite", "#000", "#fff", height=10**9)


# ============================== workflow launch limits (#59) ================
# `make_8_direction_walk_template` used to call add_frame + get_sprite_info once per
# frame: two Aseprite process launches per frame, with nothing bounding the call as a
# whole (the per-operation timeout applies to each launch individually). The fixture
# below replaces every tool that would launch Aseprite with a counter, so the launch
# count is observable without Aseprite.
@pytest.fixture
def launches(monkeypatch):
    """Count the calls that would each be one Aseprite process launch."""
    log = []
    state = {"frames": 1}

    def info(filename):
        log.append(("get_sprite_info", None))
        return {"path": filename, "width": 16, "height": 16, "colorMode": "rgb",
                "frameCount": state["frames"], "layers": [{"name": "body"}],
                "tags": [], "slices": []}

    def apply_operations(filename, operations, dry_run=False):
        log.append(("apply_operations", [op["op"] for op in operations]))
        state["frames"] += sum(1 for op in operations if op["op"] == "add_frame")
        return {"ok": True}

    def durations(filename, duration_ms):
        log.append(("set_all_frame_durations", duration_ms))
        return {"ok": True}

    def add_frame(filename, duration_ms=100, copy_from=None):
        log.append(("add_frame", None))
        state["frames"] += 1
        return {"ok": True}

    monkeypatch.setattr(workflow.inspect, "get_sprite_info", info)
    monkeypatch.setattr(workflow.batch, "apply_operations", apply_operations)
    monkeypatch.setattr(workflow.frames, "set_all_frame_durations", durations)
    monkeypatch.setattr(workflow.frames, "add_frame", add_frame)
    return log


def _kinds(log):
    return [name for name, _ in log]


def _ops(log):
    """Every batched op, in order, flattened across batches."""
    return [op for name, payload in log if name == "apply_operations" for op in payload]


def test_walk_template_past_the_frames_per_direction_cap():
    with pytest.raises(ValidationFailed,
                       match=r"frames_per_direction is 100; maximum is 32"):
        workflow.make_8_direction_walk_template("w/x.aseprite", frames_per_direction=100)


def test_walk_template_rejects_zero_frames_per_direction():
    with pytest.raises(ValidationFailed, match=r"frames_per_direction is 0; minimum is 1"):
        workflow.make_8_direction_walk_template("w/x.aseprite", frames_per_direction=0)


def test_walk_template_past_the_direction_cap():
    dirs = [f"d{i}" for i in range(limits.MAX_WALK_DIRECTIONS + 1)]
    with pytest.raises(ValidationFailed,
                       match=r"directions has 33 items; maximum is 32"):
        workflow.make_8_direction_walk_template("w/x.aseprite", directions=dirs)


def test_walk_template_caps_fire_before_anything_launches(launches):
    with pytest.raises(ValidationFailed):
        workflow.make_8_direction_walk_template(
            "w/x.aseprite", frames_per_direction=1000,
            directions=[f"d{i}" for i in range(1000)])
    assert launches == [], "1000x1000 must be rejected pre-flight"


def test_walk_template_at_both_caps_is_allowed(launches):
    """32 directions x 32 frames = 1,024 frames, the most the two caps can ask for."""
    dirs = [f"d{i}" for i in range(limits.MAX_WALK_DIRECTIONS)]
    workflow.make_8_direction_walk_template(
        "w/x.aseprite", frames_per_direction=limits.MAX_FRAMES_PER_DIRECTION,
        directions=dirs)
    assert len(_ops(launches)) == 1023 + 32  # 1024 frames (one existed) + a tag each


def test_walk_template_default_still_works(launches):
    m = workflow.make_8_direction_walk_template("w/walk.aseprite", frames_per_direction=4)
    assert m["kind"] == "walk_template"
    assert m["animation"]["directions"] == ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    assert len(_ops(launches)) == 31 + 8  # 32 frames (frame 1 exists) + 8 tags


def test_walk_template_does_not_reread_state_per_frame(launches):
    """The per-frame get_sprite_info was re-reading a count we can keep ourselves."""
    workflow.make_8_direction_walk_template("w/walk.aseprite", frames_per_direction=4)
    assert _kinds(launches).count("get_sprite_info") == 2  # opening count + final
    assert "add_frame" not in _kinds(launches)             # no per-frame launch


def test_walk_template_launches_scale_with_batches_not_frames(launches):
    """4 frames and 1,024 frames must cost the same handful of launches."""
    workflow.make_8_direction_walk_template("w/walk.aseprite", frames_per_direction=1,
                                            directions=["N", "S"])
    small = len(launches)
    launches.clear()
    workflow.make_8_direction_walk_template(
        "w/walk.aseprite", frames_per_direction=limits.MAX_FRAMES_PER_DIRECTION,
        directions=[f"d{i}" for i in range(limits.MAX_WALK_DIRECTIONS)])
    big = len(launches)
    # 1,024 frames is 1,055 ops, i.e. 3 batches of at most MAX_BATCH_OPERATIONS.
    assert small == 4 and big == 6
    batches = _kinds(launches).count("apply_operations")
    assert batches == 3


def test_walk_template_batches_respect_the_batch_cap(launches):
    workflow.make_8_direction_walk_template(
        "w/walk.aseprite", frames_per_direction=limits.MAX_FRAMES_PER_DIRECTION,
        directions=[f"d{i}" for i in range(limits.MAX_WALK_DIRECTIONS)])
    sizes = [len(payload) for name, payload in launches if name == "apply_operations"]
    assert all(n <= limits.MAX_BATCH_OPERATIONS for n in sizes)


def test_walk_template_adds_every_frame_before_any_tag(launches):
    """Tags span frames that must already exist, so order inside the batch matters."""
    workflow.make_8_direction_walk_template("w/walk.aseprite", frames_per_direction=2)
    assert _ops(launches) == ["add_frame"] * 15 + ["add_tag"] * 8


# --- the sibling grid-sheet scaffolds have the same per-item launch shape ---
def test_icon_set_past_the_grid_cell_cap():
    with pytest.raises(ValidationFailed, match=r"count is 1025; maximum is 1024"):
        workflow.create_icon_set("w/icons", count=limits.MAX_GRID_CELLS + 1)


def test_icon_set_rejects_zero_icons():
    with pytest.raises(ValidationFailed, match=r"count is 0; minimum is 1"):
        workflow.create_icon_set("w/icons", count=0)


def test_rpg_item_sheet_past_the_grid_cell_cap():
    items = [f"item{i}" for i in range(limits.MAX_GRID_CELLS + 1)]
    with pytest.raises(ValidationFailed, match=r"cells has 1025 items; maximum is 1024"):
        workflow.create_rpg_item_sheet("w/items", items=items)


def test_tileset_project_past_the_grid_cell_cap():
    tiles = [{"name": f"t{i}", "color": "#000000"} for i in range(limits.MAX_GRID_CELLS + 1)]
    with pytest.raises(ValidationFailed, match=r"tiles has 1025 items; maximum is 1024"):
        workflow.create_tileset_project("w/tiles", tiles=tiles)


# ================= argument rejection is typed, not bare ValueError (#60) ===
# `ValueError` is not an `AsepriteMCPError`, so `except AsepriteError` missed these.
# One case per converted site in the five modules this workstream owns.
_REJECTIONS = [
    pytest.param(lambda: brushes.draw_brush("w/x.aseprite", [], [], "#fff"), id="brush-empty"),
    pytest.param(lambda: brushes.draw_brush("w/x.aseprite", ["..."], [{"x": 0, "y": 0}],
                                            "#fff"), id="brush-no-cells"),
    pytest.param(lambda: brushes.mirror_layer("w/x.aseprite", "body", direction="sideways"),
                 id="mirror-direction"),
    pytest.param(lambda: brushes.mirror_layer("w/x.aseprite", "body", source_side="middle"),
                 id="mirror-source-side"),
    pytest.param(lambda: brushes.draw_symmetric_pixels("w/x.aseprite", [{"x": 0, "y": 0}],
                                                       "#fff", mode="radial"),
                 id="symmetric-mode"),
    pytest.param(lambda: brushes.draw_symmetric_pixels("w/x.aseprite", [], "#fff"),
                 id="symmetric-empty"),
    pytest.param(lambda: drawing.draw_pixels("w/x.aseprite", []), id="pixels-empty"),
    pytest.param(lambda: drawing.draw_pixels("w/x.aseprite", [{"x": 0, "y": 0}]),
                 id="pixels-no-colour"),
    pytest.param(lambda: drawing.draw_polyline("w/x.aseprite", [{"x": 0, "y": 0}], "#fff"),
                 id="polyline-too-few"),
    pytest.param(lambda: effects.fill_gradient("w/x.aseprite", ["#000", "#fff"],
                                               gradient_type="spiral"), id="gradient-type"),
    pytest.param(lambda: effects.fill_gradient("w/x.aseprite", ["#000"]), id="gradient-stops"),
    pytest.param(lambda: effects.fill_gradient("w/x.aseprite", ["#000", "#fff", "#f00"],
                                               dither=True), id="gradient-dither"),
    pytest.param(lambda: effects.add_outline("w/x.aseprite", "#000", connectivity=6),
                 id="outline-connectivity"),
    pytest.param(lambda: effects.add_outline("w/x.aseprite", "#000", where="around"),
                 id="outline-where"),
    pytest.param(lambda: palette.set_palette("w/x.aseprite", []), id="palette-empty"),
    pytest.param(lambda: palette.sort_palette("w/x.aseprite", by="vibes"), id="palette-sort-by"),
    pytest.param(lambda: palette.generate_ramp("#fff", apply="prepend"), id="ramp-apply"),
    pytest.param(lambda: palette.generate_ramp("#fff", apply="append"), id="ramp-no-filename"),
    pytest.param(lambda: workflow.create_tileset_project("w/t", tiles=[]), id="tiles-empty"),
    pytest.param(lambda: workflow.create_rpg_item_sheet("w/i", items=[]), id="items-empty"),
    pytest.param(lambda: workflow.create_icon_set("w/i", count=0), id="icon-count"),
    pytest.param(lambda: workflow.make_8_direction_walk_template("w/x.aseprite",
                                                                 frames_per_direction=0),
                 id="walk-fpd"),
]


@pytest.mark.parametrize("call", _REJECTIONS)
def test_argument_rejection_is_typed(call):
    """A rejected argument must land inside the hierarchy, whichever tool it reached."""
    with pytest.raises(AsepriteMCPError) as excinfo:
        call()
    assert not isinstance(excinfo.value, ValueError), "a bare ValueError escaped"


def test_duplicate_grid_cell_names_are_typed():
    with pytest.raises(AsepriteMCPError, match="unique"):
        workflow.create_rpg_item_sheet("w/i", items=["sword", "sword"])
