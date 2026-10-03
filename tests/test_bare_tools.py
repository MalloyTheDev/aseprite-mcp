"""The eight tools no test named.

A census of the registry against `tests/` turned up eight of the 152 tools that no test
mentioned at all: `adjust_hue_saturation`, `duplicate_layer`, `merge_layer_down`,
`fill_tile`, `fill_tilemap`, `flatten_sprite`, `load_palette` and `plan_asset_spec`.
Untested is not the same as broken, and most of these turn out to work, but a server whose
whole premise is that it measures what it drew should not have eight tools nobody measured.

Each test here asserts the thing its tool is *for*, which is usually a property rather than
a pixel: that a duplicate is independent of its original rather than a second reference to
the same drawing, that a merge keeps what was underneath rather than replacing it, that a
flatten preserves the composite rather than only the top layer, that an in-place palette
load does not move the art. Those are the claims a caller relies on and the ones a
plausible-looking implementation gets wrong.

`plan_asset_spec` needs no editor, so it carries `@pytest.mark.pure` and runs in CI with
the rest of the pure tier. The allowlist in `conftest.py` speaks about whole files and this
file is mostly editor-driven, so the marker is the right half of that mechanism.
"""

from __future__ import annotations

import colorsys

import pytest

from aseprite_mcp.core.errors import LuaToolError
from aseprite_mcp.tools import (
    asset_spec,
    drawing,
    effects,
    inspect,
    layers,
    palette,
    sprite,
    tilemap,
)

RED = "#ff0000"
BLUE = "#0000ff"
GREEN = "#00ff00"


def canvas(request, width: int = 16, height: int = 16, suffix: str = "") -> str:
    name = f"bare/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, width, height, overwrite=True)
    return name


def colours(name: str, width: int = 16, height: int = 16) -> set[str]:
    rows = inspect.get_pixels(name, 0, 0, width, height)["pixels"]
    return {px[:7].lower() for row in rows for px in row if not px.endswith("00")}


def layer_names(name: str) -> list[str]:
    return [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]


def hsl(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


# ===== effects.adjust_hue_saturation ==================================================


def test_a_hue_shift_rotates_the_hue_and_leaves_the_rest_alone(request):
    """Hue in degrees, saturation and lightness in percent, and only one of them moved."""
    name = canvas(request)
    drawing.fill_layer(name, RED)

    effects.adjust_hue_saturation(name, hue=120)

    (after,) = colours(name)
    before_h, before_l, before_s = hsl(RED)
    after_h, after_l, after_s = hsl(after)
    # 120 degrees from red is green, within the rounding of a round trip through 8-bit RGB.
    assert abs(((after_h - before_h) * 360) % 360 - 120) < 2, after
    assert abs(after_l - before_l) < 0.02, f"lightness moved: {after}"
    assert abs(after_s - before_s) < 0.02, f"saturation moved: {after}"


def test_a_negative_saturation_desaturates_without_moving_the_hue(request):
    name = canvas(request)
    drawing.fill_layer(name, "#c04040")

    effects.adjust_hue_saturation(name, saturation=-60)

    (after,) = colours(name)
    before_h, _bl, before_s = hsl("#c04040")
    after_h, _al, after_s = hsl(after)
    assert after_s < before_s, f"saturation should have dropped: {after}"
    assert abs(after_h - before_h) < 0.02, f"hue moved: {after}"


def test_adjusting_by_nothing_changes_nothing(request):
    """The identity case, which is worth pinning on a tool that takes three deltas."""
    name = canvas(request)
    drawing.fill_layer(name, "#3f7fbf")
    before = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]

    effects.adjust_hue_saturation(name)

    assert inspect.get_pixels(name, 0, 0, 16, 16)["pixels"] == before


def test_a_hue_shift_leaves_transparent_pixels_transparent(request):
    """The silhouette is the one thing a colour adjustment must never change."""
    name = canvas(request)
    drawing.draw_rectangle(name, 2, 2, 4, 4, RED, filled=True)

    effects.adjust_hue_saturation(name, hue=90, saturation=40)

    rows = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]
    opaque = {(x, y) for y, row in enumerate(rows)
              for x, px in enumerate(row) if not px.endswith("00")}
    assert opaque == {(x, y) for y in range(2, 6) for x in range(2, 6)}


# ===== layers.duplicate_layer =========================================================


def test_a_duplicated_layer_is_independent_of_its_original(request):
    """The property that matters: a copy, not a second reference to one drawing.

    Aseprite has linked cels, where several frames share one image and an edit to any of
    them changes all of them. A duplicate that linked instead of copying would look right
    until the first edit.
    """
    name = canvas(request)
    layers.rename_layer(name, "Layer 1", "base")
    drawing.fill_layer(name, RED, layer="base")

    result = layers.duplicate_layer(name, "base")

    names = layer_names(name)
    assert len(names) == 2, names
    copy = next(n for n in names if n != "base")
    # This one returns raw sprite info rather than an `ok` flag, which is worth knowing:
    # four of these eight tools report `ok` and two do not. Noted in #203.
    assert result["layerCount"] == 2

    # Paint the copy, and the original must not move with it.
    drawing.fill_layer(name, BLUE, layer=copy)
    base_rows = inspect.get_pixels(name, 0, 0, 16, 16, layer="base")["pixels"]
    assert {px[:7].lower() for row in base_rows for px in row} == {RED}


def test_a_duplicated_layer_lands_above_its_original(request):
    """Documented as "a new layer on top", and the stacking is what the caller then uses."""
    name = canvas(request)
    layers.rename_layer(name, "Layer 1", "base")
    drawing.fill_layer(name, RED, layer="base")

    layers.duplicate_layer(name, "base")

    info = inspect.get_sprite_info(name)["layers"]
    by_name = {lyr["name"]: lyr["stackIndex"] for lyr in info}
    copy = next(n for n in by_name if n != "base")
    assert by_name[copy] > by_name["base"], by_name


def test_duplicating_a_layer_that_is_not_there_is_refused(request):
    name = canvas(request)
    with pytest.raises(LuaToolError, match=r"No layer named"):
        layers.duplicate_layer(name, "nonexistent")


# ===== layers.merge_layer_down ========================================================


def test_merging_down_keeps_what_was_underneath(request):
    """The failure a plausible implementation has: replacing the lower layer, not merging.

    The upper layer covers only part of the canvas, so a merge that simply moved the top
    layer's image down would lose the rest of the bottom one, and a merge that composited
    the wrong way round would lose the top.
    """
    name = canvas(request)
    layers.rename_layer(name, "Layer 1", "bottom")
    drawing.fill_layer(name, RED, layer="bottom")
    layers.add_layer(name, "top")
    drawing.draw_rectangle(name, 0, 0, 8, 16, BLUE, filled=True, layer="top")

    layers.merge_layer_down(name, "top")

    assert layer_names(name) == ["bottom"], "the merged layer should be gone"
    rows = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]
    left = {px[:7].lower() for row in rows for px in row[:8]}
    right = {px[:7].lower() for row in rows for px in row[8:]}
    assert left == {BLUE}, f"the upper layer should have won where it drew: {left}"
    assert right == {RED}, f"the lower layer should survive where it did not: {right}"


def test_merging_the_bottom_layer_down_is_refused(request):
    """There is nothing underneath, so the only honest answer is a refusal.

    Every neighbouring refusal in this codebase is loud: `duplicate_layer` on a missing
    name raises `No layer named`, `fill_tile` on a missing index raises `No tile at index`.
    This is the same class of impossible request and the only one that answers by
    pretending, which is why it is pinned here rather than left to be rediscovered.
    """
    name = canvas(request)
    layers.rename_layer(name, "Layer 1", "only")
    drawing.fill_layer(name, RED)

    with pytest.raises(LuaToolError):
        layers.merge_layer_down(name, "only")

    assert layer_names(name) == ["only"], "a refused merge must change nothing"


# ===== sprite.flatten_sprite ==========================================================


def test_flattening_preserves_the_composite_rather_than_the_top_layer(request):
    """What the viewer saw before must be what the single layer holds after."""
    name = canvas(request)
    layers.rename_layer(name, "Layer 1", "bottom")
    drawing.fill_layer(name, RED, layer="bottom")
    layers.add_layer(name, "middle")
    drawing.draw_rectangle(name, 0, 0, 16, 8, BLUE, filled=True, layer="middle")
    layers.add_layer(name, "top")
    drawing.draw_rectangle(name, 0, 0, 4, 4, GREEN, filled=True, layer="top")
    before = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]

    sprite.flatten_sprite(name)

    assert len(layer_names(name)) == 1, layer_names(name)
    assert inspect.get_pixels(name, 0, 0, 16, 16)["pixels"] == before, (
        "flattening changed what the sprite looks like"
    )


def test_flattening_one_layer_is_harmless(request):
    name = canvas(request)
    drawing.fill_layer(name, RED)
    before = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]

    sprite.flatten_sprite(name)

    assert len(layer_names(name)) == 1
    assert inspect.get_pixels(name, 0, 0, 16, 16)["pixels"] == before


# ===== palette.load_palette ===========================================================


def test_loading_a_palette_replaces_the_palette_and_not_the_art(request):
    """An RGB sprite's pixels are colours, not indices, so the art must not move.

    The mirror of this is what made indexed mode unusable before v0.9.0: a palette the art
    does not reference is harmless in RGB and destructive in indexed, and the difference is
    worth a test on the tool that loads one.
    """
    name = canvas(request)
    drawing.fill_layer(name, RED)
    source = "bare/palette_source.aseprite"
    sprite.create_sprite(source, 4, 4, overwrite=True)
    palette.set_palette(source, [GREEN, BLUE, "#ffff00"])

    before = inspect.get_pixels(name, 0, 0, 16, 16)["pixels"]
    result = palette.load_palette(name, source)

    assert result["ok"] is True
    loaded = [c[:7].lower() for c in palette.get_palette(name)["colors"]]
    assert GREEN in loaded and BLUE in loaded, loaded
    assert inspect.get_pixels(name, 0, 0, 16, 16)["pixels"] == before, (
        "loading a palette repainted an RGB sprite"
    )


def test_loading_a_palette_that_is_not_there_is_refused(request):
    name = canvas(request)
    with pytest.raises(LuaToolError, match=r"Could not load palette"):
        palette.load_palette(name, "bare/no_such_palette.gpl")


# ===== tilemap.fill_tile and fill_tilemap =============================================


@pytest.fixture()
def tilemap_sprite(request):
    """A 2x2 grid of 8px tiles with one painted tile in the tileset."""
    name = f"bare/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16, overwrite=True)
    tilemap.create_tilemap_layer(name, "tiles", 8, 8)
    tilemap.add_tile(name, "tiles")
    return name


def paint_whole_tile(name: str, index: int, colour: str) -> None:
    """Fill a tile's artwork, which is what `fill_tile` is for.

    These went through `paint_tile_pixels` while #204 was open, because `fill_tile` paints
    nothing and the tilemap claims below needed to be testing something real. The fix has
    landed, so they go back through the tool they are about.
    """
    tilemap.fill_tile(name, "tiles", index, colour)


def test_fill_tile_actually_fills_the_tile(tilemap_sprite):
    """The tool's entire job, asserted on the canvas rather than on its return value.

    `fill_tile` used to return `ok: true` while doing nothing (#204), so the return value
    cannot be the assertion. Compare with `paint_tile_pixels`, which reaches the same tile
    image by the same accessor and whose writes always stuck.
    """
    tilemap.fill_tilemap(tilemap_sprite, "tiles", 1)

    tilemap.fill_tile(tilemap_sprite, "tiles", 1, RED)

    assert colours(tilemap_sprite) == {RED}


def test_a_tile_is_painted_once_and_drawn_in_every_cell_using_it(tilemap_sprite):
    """A tile is painted once and drawn many times, which is the point of a tileset.

    So this is the claim worth asserting: paint tile 1, and *every* cell referencing it
    changes, because they are the same tile and not four copies of it.
    """
    tilemap.fill_tilemap(tilemap_sprite, "tiles", 1)
    paint_whole_tile(tilemap_sprite, 1, RED)

    assert colours(tilemap_sprite) == {RED}

    # And repainting the one tile moves every cell again.
    paint_whole_tile(tilemap_sprite, 1, BLUE)
    assert colours(tilemap_sprite) == {BLUE}


def test_filling_the_grid_puts_the_named_tile_in_every_cell(tilemap_sprite):
    paint_whole_tile(tilemap_sprite, 1, GREEN)

    result = tilemap.fill_tilemap(tilemap_sprite, "tiles", 1)

    assert result["ok"] is True
    grid = tilemap.get_tilemap(tilemap_sprite, "tiles")["tiles"]
    assert {cell for row in grid for cell in row} == {1}, grid
    assert colours(tilemap_sprite) == {GREEN}


def test_filling_the_grid_with_the_empty_tile_clears_it(tilemap_sprite):
    """Index 0 is the empty tile, so this is how a tilemap is cleared."""
    paint_whole_tile(tilemap_sprite, 1, GREEN)
    tilemap.fill_tilemap(tilemap_sprite, "tiles", 1)
    assert colours(tilemap_sprite) == {GREEN}

    tilemap.fill_tilemap(tilemap_sprite, "tiles", 0)

    assert colours(tilemap_sprite) == set(), "index 0 should leave nothing drawn"


def test_a_tile_index_the_tileset_does_not_have_is_refused(tilemap_sprite):
    """Refused rather than clamped: a silently substituted tile is wrong art."""
    with pytest.raises(LuaToolError, match=r"No tile at index"):
        tilemap.fill_tile(tilemap_sprite, "tiles", 99, RED)
    with pytest.raises(LuaToolError, match=r"No tile at index"):
        tilemap.fill_tilemap(tilemap_sprite, "tiles", 99)


# ===== asset_spec.plan_asset_spec, which launches nothing =============================


# A spec the validator accepts. The first draft used `kind: "icon"`, which is not one of
# the seven, and `validate_spec` said so with the list of valid kinds: that refusal is
# itself the behaviour the invalid-spec test below pins.
SPEC = {
    "schema": "aseprite_mcp.asset_spec.v1",
    "name": "plan_probe",
    "kind": "icon_set",
    "icon_size": 16,
    "count": 4,
    "palette": ["#1d2b53", "#ff004d"],
}


@pytest.mark.pure
def test_planning_a_spec_launches_nothing_and_names_real_tools():
    """The dry run's whole value is that it is checkable without an editor.

    So the assertion is that every step names a tool that actually exists in the registry.
    A plan that names a tool nobody can call is worse than no plan: it reads as a promise.
    """
    import asyncio

    from aseprite_mcp.server import mcp

    result = asset_spec.plan_asset_spec(SPEC)

    assert result["dry_run"] is True
    assert result["kind"] == "asset_spec"
    steps = result["plan"]
    assert steps, "a valid spec should plan at least one step"

    registry = {tool.name for tool in asyncio.run(mcp.list_tools())}
    named = [step["tool"] for step in steps]
    assert set(named) <= registry, f"plan names tools that do not exist: {set(named) - registry}"
    for step in steps:
        assert step["purpose"].strip(), f"a step with no stated purpose: {step}"


@pytest.mark.pure
def test_planning_an_invalid_spec_returns_the_validation_report_instead():
    """Documented behaviour, and the branch a caller hits by getting the spec wrong."""
    result = asset_spec.plan_asset_spec({"name": "broken"})

    assert "plan" not in result
    assert result["validation"]["passed"] is False
    assert result["validation"]["errors"], "a failed validation must say what is wrong"


@pytest.mark.pure
def test_planning_is_a_pure_function_of_the_spec():
    """Called twice, the same plan. A dry run that is not reproducible is not a plan."""
    first = asset_spec.plan_asset_spec(SPEC)
    second = asset_spec.plan_asset_spec(SPEC)
    assert first["plan"] == second["plan"]
