"""Per-cel z-index, custom properties, palette quantization, packed sheet export.

Requires Aseprite (`--run-aseprite`), except for the pre-flight refusals, which are
marked `pure` because they are decided in Python before anything is launched.

Every capability here is reachable only through the editor, so the assertions are about
what the editor actually did rather than about what was returned:

  * a z-index is checked by reading the file back in a later Aseprite run and by looking
    at which colour the composite shows, because a number that round-trips while the
    render order is unchanged would be a z-index in name only;
  * extrude is checked on the sheet's border pixels against the frame's own corners, not
    on the sheet's size or the file's length, both of which a padding flag would also
    change;
  * merge-duplicates is checked on the sheet width and on the frame rectangles in the
    emitted JSON, and on a sprite whose held pose is built with *linked cels* (two frames
    sharing one image), with a second test for the other construction, a duplicated
    frame, since they are different situations in the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import ExportError, ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import (
    cels,
    drawing,
    export,
    frames,
    inspect,
    layers,
    palette,
    slices,
    sprite,
    tags,
    tilemap,
)

CORNERS = {
    (0, 0): "#ff0000ff",
    (3, 0): "#00ff00ff",
    (0, 3): "#0000ffff",
    (3, 3): "#ffff00ff",
}
FIELD = "#0a0a0aff"


def _name(request, suffix: str = ".aseprite") -> str:
    return f"cz/{request.node.name}{suffix}"


def _two_layer_sprite(request) -> str:
    """A 4x4 sprite with two full-canvas layers: "under" is red, "over" is blue.

    With no z-index the composite shows blue, because "over" is above "under" in the
    stack. That is the fact the z-index tests move.
    """
    name = _name(request)
    sprite.create_sprite(name, 4, 4)
    layers.add_layer(name, "over")
    drawing.fill_layer(name, "#ff0000", layer="Layer 1")
    drawing.fill_layer(name, "#0000ff", layer="over")
    return name


def _composite(name: str, frame: int = 1) -> str:
    """The composite colour at (0, 0), which is what the frame renders as."""
    return inspect.get_pixels(name, 0, 0, 1, 1, frame=frame)["pixels"][0][0]


def _corner_sprite(request) -> str:
    """A 4x4 sprite, one frame, a dark field with four differently coloured corners.

    The corners are what makes the extrude assertion meaningful: a border that merely
    exists, or a flat-filled one, cannot be told apart from one that duplicates the
    frame's own edge unless the edge pixels differ from each other.
    """
    name = _name(request)
    sprite.create_sprite(name, 4, 4)
    drawing.fill_layer(name, FIELD)
    drawing.draw_pixels(
        name,
        [{"x": x, "y": y, "color": hexed} for (x, y), hexed in CORNERS.items()],
    )
    return name


# ======================================================================= z-index
def test_a_z_index_round_trips_through_save_and_reload(request):
    """Each tool call is its own Aseprite run, so reading it back with `get_cel` is a
    reload from disk and not a read of anything still in memory."""
    name = _two_layer_sprite(request)
    assert cels.get_cel(name, "Layer 1")["z_index"] == 0

    written = cels.set_cel_z_index(name, "Layer 1", 1, 3)

    assert written["z_index"] == 3
    assert cels.get_cel(name, "Layer 1")["z_index"] == 3


def test_the_extremes_the_file_format_can_hold_survive_it(request):
    """The bound in `core.metadata` exists because of what happens past it. These two
    values are the edge of what the 16-bit field holds, so they are the ones that prove
    the bound is in the right place rather than merely present."""
    name = _two_layer_sprite(request)

    cels.set_cel_z_index(name, "Layer 1", 1, 32767)
    assert cels.get_cel(name, "Layer 1")["z_index"] == 32767

    cels.set_cel_z_index(name, "Layer 1", 1, -32768)
    assert cels.get_cel(name, "Layer 1")["z_index"] == -32768


def test_a_z_index_actually_changes_which_cel_draws_in_front(request):
    """The assertion that makes this a render-order tool and not a number store.

    Both layers cover the canvas, so the composite colour names the winner outright.
    """
    name = _two_layer_sprite(request)
    assert _composite(name) == "#0000ffff", "the upper layer shows to begin with"

    cels.set_cel_z_index(name, "Layer 1", 1, 1)

    assert _composite(name) == "#ff0000ff", (
        "the lower cel was given a z-index that puts it in front, and the composite "
        "still shows the upper layer"
    )

    cels.set_cel_z_index(name, "Layer 1", 1, 0)
    assert _composite(name) == "#0000ffff", "clearing the z-index restores the order"


def test_a_negative_z_index_pushes_the_upper_cel_behind(request):
    name = _two_layer_sprite(request)

    cels.set_cel_z_index(name, "over", 1, -1)

    assert _composite(name) == "#ff0000ff"


def test_the_reported_order_matches_what_the_frame_renders(request):
    """`order` is the only part of the result a caller cannot see for themselves, so it
    has to agree with the pixels rather than with the arithmetic that produced it."""
    name = _two_layer_sprite(request)

    order = cels.set_cel_z_index(name, "Layer 1", 1, 1)["order"]

    assert [row["layer"] for row in order] == ["over", "Layer 1"], (
        "reported back to front, so the last row is the cel that draws in front"
    )
    assert [row["z_index"] for row in order] == [0, 1]
    assert _composite(name) == "#ff0000ff", (
        "the order says Layer 1 draws in front, and the composite disagrees"
    )


def test_one_frame_can_be_reordered_without_touching_the_next(request):
    """The problem the capability exists for: the arm in front this frame and behind the
    next, which a layer move cannot express."""
    name = _two_layer_sprite(request)
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)
    cels.copy_cel(name, "over", 1, 2)

    cels.set_cel_z_index(name, "Layer 1", 1, 1)

    assert _composite(name, frame=1) == "#ff0000ff"
    assert _composite(name, frame=2) == "#0000ffff"
    assert cels.get_cel(name, "Layer 1", 2)["z_index"] == 0


def test_a_z_index_is_not_shared_by_linked_cels(request):
    """Linked cels share one image, their opacity and their properties, and do not share
    this. Pinned because the opposite is the reasonable guess, and because a tool built
    on the guess would silently reorder every frame of a held pose."""
    name = _two_layer_sprite(request)
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)
    cels.link_cels(name, "Layer 1", [1, 2])
    assert cels.get_cel(name, "Layer 1", 2)["linked"] is True

    cels.set_cel_z_index(name, "Layer 1", 1, 4)

    assert cels.get_cel(name, "Layer 1", 1)["z_index"] == 4
    assert cels.get_cel(name, "Layer 1", 2)["z_index"] == 0


def test_a_frame_with_no_cel_on_that_layer_is_refused(request):
    name = _two_layer_sprite(request)
    frames.add_frame(name)

    with pytest.raises(AsepriteError, match="no cel at frame 2"):
        cels.set_cel_z_index(name, "Layer 1", 2, 1)


@pytest.mark.pure
@pytest.mark.parametrize("z", [32768, -32769, 100000])
def test_a_z_index_the_file_cannot_hold_never_reaches_the_editor(z):
    with pytest.raises(ValidationFailed, match="16-bit"):
        cels.set_cel_z_index("unused.aseprite", "Layer 1", 1, z)


@pytest.mark.pure
def test_a_zero_frame_number_is_refused_before_launch():
    with pytest.raises(ValidationFailed, match="1-based"):
        cels.set_cel_z_index("unused.aseprite", "Layer 1", 0, 1)


# ==================================================================== properties
def _metadata_sprite(request) -> str:
    """One sprite carrying all six kinds of object that can hold a property."""
    name = _name(request)
    sprite.create_sprite(name, 16, 16)
    drawing.fill_layer(name, "#804020")
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)
    tags.add_tag(name, "idle", 1, 2)
    slices.add_slice(name, "body", 2, 3, 4, 5)
    tilemap.create_tilemap_layer(name, "ground", 8, 8)
    tilemap.add_tile(name, "ground", color="#00ff00")
    return name


ALL_TARGETS = [
    ("sprite", {}),
    ("layer", {"layer": "Layer 1"}),
    ("cel", {"layer": "Layer 1", "frame": 2}),
    ("tag", {"name": "idle"}),
    ("slice", {"name": "body"}),
    ("tile", {"layer": "ground", "tile": 1}),
]


@pytest.mark.parametrize("target,selectors", ALL_TARGETS)
def test_every_kind_of_object_round_trips_a_property(request, target, selectors):
    name = _metadata_sprite(request)

    written = cels.set_properties(name, target, "owner", f"the {target}", **selectors)
    assert written["properties"]["owner"] == f"the {target}"

    read = cels.get_properties(name, target, **selectors)
    assert read["properties"] == {"owner": f"the {target}"}, (
        f"a property written on the {target} did not come back from the file"
    )


@pytest.mark.parametrize("target,selectors", ALL_TARGETS)
def test_a_namespaced_key_round_trips_and_does_not_collide(request, target, selectors):
    """The namespace is the whole reason two tools can both use the key "anchor". If it
    were ignored, the second write would overwrite the first and both reads would return
    the same value, which is exactly what this asserts against."""
    name = _metadata_sprite(request)

    cels.set_properties(name, target, "anchor", "unnamed group", **selectors)
    cels.set_properties(
        name, target, "anchor", "rig group", namespace="game.rig", **selectors
    )

    assert cels.get_properties(name, target, **selectors)["properties"] == {
        "anchor": "unnamed group"
    }
    scoped = cels.get_properties(name, target, namespace="game.rig", **selectors)
    assert scoped["properties"] == {"anchor": "rig group"}
    assert scoped["namespace"] == "game.rig"


def test_a_property_survives_an_unrelated_edit(request):
    """Properties are only useful if the next edit does not drop them, and every tool
    here opens the file, changes it and saves it over the original."""
    name = _metadata_sprite(request)
    cels.set_properties(
        name, "slice", "hitbox", '{"x": 2, "y": 3, "w": 4, "h": 5}', name="body"
    )

    drawing.draw_rectangle(name, 1, 1, 6, 6, "#ffffff", filled=True, layer="Layer 1")
    layers.add_layer(name, "fx")
    frames.add_frame(name)

    read = cels.get_properties(name, "slice", name="body")
    assert read["properties"]["hitbox"] == {"x": 2, "y": 3, "w": 4, "h": 5}


def test_a_structure_is_stored_as_a_structure(request):
    """Not as the text of one. A property store whose values are all strings is a
    sidecar file with extra steps, and `slice.data` already does that."""
    name = _metadata_sprite(request)

    cels.set_properties(
        name, "layer", "anchor", '{"x": 8, "y": 15, "tags": ["feet"]}', layer="Layer 1"
    )

    value = cels.get_properties(name, "layer", layer="Layer 1")["properties"]["anchor"]
    assert value == {"x": 8, "y": 15, "tags": ["feet"]}
    assert value["x"] == 8 and isinstance(value["x"], int)


def test_a_list_value_comes_back_as_a_list(request):
    """"Which frames of this tag deal damage" is a list, and a list that reads back as
    an object keyed "1", "2" is not the value that was stored. The reporting path got
    this wrong first time round by stringifying every key on the way out."""
    name = _metadata_sprite(request)

    cels.set_properties(name, "tag", "damage_frames", "[2, 5]", name="idle")

    stored = cels.get_properties(name, "tag", name="idle")["properties"]
    assert stored["damage_frames"] == [2, 5]


def test_text_and_numbers_are_told_apart(request):
    name = _metadata_sprite(request)

    cels.set_properties(name, "sprite", "as_text", "7")
    cels.set_properties(name, "sprite", "as_number", "7", as_json=True)
    cels.set_properties(name, "sprite", "as_bool", "true", as_json=True)

    stored = cels.get_properties(name, "sprite")["properties"]
    assert stored["as_text"] == "7"
    assert stored["as_number"] == 7
    assert stored["as_bool"] is True


def test_a_property_can_be_deleted(request):
    name = _metadata_sprite(request)
    cels.set_properties(name, "tag", "events", "hit", name="idle")

    removed = cels.set_properties(name, "tag", "events", name="idle", delete=True)

    assert removed["deleted"] is True
    assert removed["properties"] == {}
    assert cels.get_properties(name, "tag", name="idle")["properties"] == {}


def test_deleting_a_key_that_was_never_there_is_not_an_error(request):
    name = _metadata_sprite(request)
    assert cels.set_properties(
        name, "sprite", "never_set", delete=True
    )["properties"] == {}


def test_a_cel_property_reaches_every_frame_of_a_held_pose(request):
    """Properties live on the record linked cels share, so this write is not scoped to
    the frame it names. Reported rather than refused, because that is what linking
    means, but a result saying `frame: 1` while two frames changed would be wrong."""
    name = _metadata_sprite(request)
    cels.link_cels(name, "Layer 1", [1, 2])

    written = cels.set_properties(name, "cel", "damage", "3", layer="Layer 1", frame=1)

    assert written["linked_frames_also_changed"] == [2]
    assert cels.get_properties(
        name, "cel", layer="Layer 1", frame=2
    )["properties"] == {"damage": "3"}


def test_an_unlinked_cel_property_stays_on_its_own_frame(request):
    name = _metadata_sprite(request)
    assert cels.get_cel(name, "Layer 1", 1)["linked"] is False

    written = cels.set_properties(name, "cel", "damage", "3", layer="Layer 1", frame=1)

    assert "linked_frames_also_changed" not in written
    assert cels.get_properties(
        name, "cel", layer="Layer 1", frame=2
    )["properties"] == {}


def test_an_unknown_namespace_reads_as_empty(request):
    name = _metadata_sprite(request)
    cels.set_properties(name, "sprite", "a", "1")

    read = cels.get_properties(name, "sprite", namespace="nobody.wrote.this")

    assert read["properties"] == {}
    assert read["count"] == 0


def test_an_unknown_tag_name_lists_the_tags_that_exist(request):
    name = _metadata_sprite(request)

    with pytest.raises(AsepriteError, match="the sprite has: 'idle'"):
        cels.set_properties(name, "tag", "k", "v", name="walk")


def test_a_tile_on_a_layer_that_is_not_a_tilemap_is_refused(request):
    name = _metadata_sprite(request)

    with pytest.raises(AsepriteError, match="not a tilemap layer"):
        cels.set_properties(name, "tile", "k", "v", layer="Layer 1", tile=1)


def test_a_tile_index_past_the_tileset_is_refused_with_its_size(request):
    name = _metadata_sprite(request)

    with pytest.raises(AsepriteError, match="tile 99 does not exist"):
        cels.set_properties(name, "tile", "k", "v", layer="ground", tile=99)


def test_a_cel_that_does_not_exist_cannot_carry_a_property(request):
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    layers.add_layer(name, "empty")

    with pytest.raises(AsepriteError, match="no cel at frame 1"):
        cels.set_properties(name, "cel", "k", "v", layer="empty")


@pytest.mark.pure
def test_the_refusals_that_do_not_need_an_editor():
    with pytest.raises(ValidationFailed, match="sprite, layer, cel, tag, slice, tile"):
        cels.set_properties("unused.aseprite", "frame", "k", "v")
    with pytest.raises(ValidationFailed, match="needs"):
        cels.set_properties("unused.aseprite", "layer", "k", "v")
    with pytest.raises(ValidationFailed, match="does not use"):
        cels.set_properties("unused.aseprite", "sprite", "k", "v", layer="Layer 1")
    with pytest.raises(ValidationFailed, match="non-empty"):
        cels.set_properties("unused.aseprite", "sprite", "", "v")
    with pytest.raises(ValidationFailed, match="delete=True"):
        cels.set_properties("unused.aseprite", "sprite", "k")
    with pytest.raises(ValidationFailed, match="not valid JSON"):
        cels.set_properties("unused.aseprite", "sprite", "k", "boss", as_json=True)
    with pytest.raises(ValidationFailed, match="does not use"):
        cels.get_properties("unused.aseprite", "tag", name="idle", layer="Layer 1")


# ================================================================== quantization
def _gradient(request, size: int = 16) -> str:
    """A sprite whose every pixel is a different colour, so a reduction has work to do."""
    name = _name(request)
    sprite.create_sprite(name, size, size)
    drawing.draw_pixels(
        name,
        [
            {"x": x, "y": y,
             "color": f"#{x * 16:02x}{y * 16:02x}{((x + y) * 8) % 256:02x}"}
            for x in range(size)
            for y in range(size)
        ],
    )
    return name


def test_quantization_to_n_colours_produces_at_most_n_entries(request):
    name = _gradient(request)

    result = palette.quantize_palette(name, 16)

    assert result["size"] <= 16
    assert len(result["colors"]) == result["size"]
    assert palette.get_palette(name)["size"] == result["size"], (
        "the palette reported is not the palette left in the file"
    )


@pytest.mark.parametrize("budget", [2, 4, 8, 32])
def test_the_ceiling_holds_at_every_budget(request, budget):
    name = _gradient(request)

    assert palette.quantize_palette(name, budget)["size"] <= budget


def test_the_palette_is_derived_from_the_art_and_not_invented(request):
    """Three colours, a budget with room to spare: all three have to come back exactly,
    or the palette is not a palette for this art."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.fill_layer(name, "#1b2838")
    drawing.draw_rectangle(name, 0, 0, 4, 8, "#c23b22", filled=True)
    drawing.draw_rectangle(name, 4, 0, 4, 4, "#f0e68c", filled=True)

    result = palette.quantize_palette(name, 32)

    assert result["art_colors"] == 3
    assert result["art_colors_exact"] == 3, (
        f"the art's colours are not all in the derived palette: {result['colors']}"
    )
    entries = {c.lower() for c in result["colors"]}
    assert {"#1b2838ff", "#c23b22ff", "#f0e68cff"} <= entries
    assert "warnings" not in result, "a palette that holds the art should say nothing"


def test_index_zero_is_kept_for_transparency(request):
    """An opaque colour at the transparent index is in the palette and can never be
    drawn, which is the trap `core.indexed` exists to warn about. The quantizer avoids
    it, and that is worth pinning because a palette tool that did not would hand every
    later indexed conversion an undrawable entry."""
    name = _gradient(request)

    result = palette.quantize_palette(name, 8)

    assert result["colors"][0].lower().endswith("00")
    assert result["palette"]["transparent_index"] == 0


def test_a_budget_equal_to_the_number_of_colours_collapses_and_says_so(request):
    """A measured property of the editor's reduction, not of this tool: four distinct
    colours with max_colors=4 come back as one averaged tone, while max_colors=5 returns
    all four. The tool cannot prevent it, so it has to report it; if a future Aseprite
    stops collapsing, this test fails and the warning can go."""
    name = _name(request)
    sprite.create_sprite(name, 2, 2)
    drawing.draw_pixels(name, [
        {"x": 0, "y": 0, "color": "#ff0000"},
        {"x": 1, "y": 0, "color": "#00ff00"},
        {"x": 0, "y": 1, "color": "#0000ff"},
        {"x": 1, "y": 1, "color": "#ffff00"},
    ])

    tight = palette.quantize_palette(name, 4)

    assert tight["art_colors"] == 4
    assert tight["palette"]["drawable"] == 1, (
        "the editor no longer collapses this case; re-read the warning in "
        "core.quantization before deleting it"
    )
    assert "single tone" in " ".join(tight["warnings"])
    assert "max_colors=5" in " ".join(tight["warnings"])


def test_one_more_colour_of_headroom_keeps_the_art(request):
    """The other half of the same measurement, and the remedy the warning names."""
    name = _name(request)
    sprite.create_sprite(name, 2, 2)
    drawing.draw_pixels(name, [
        {"x": 0, "y": 0, "color": "#ff0000"},
        {"x": 1, "y": 0, "color": "#00ff00"},
        {"x": 0, "y": 1, "color": "#0000ff"},
        {"x": 1, "y": 1, "color": "#ffff00"},
    ])

    roomy = palette.quantize_palette(name, 5)

    assert roomy["art_colors_exact"] == 4
    assert "warnings" not in roomy


def test_a_reduction_that_approximates_the_art_says_which_way(request):
    name = _gradient(request)

    result = palette.quantize_palette(name, 8)

    assert result["art_colors_exact"] < result["art_colors"]
    assert "nearest entry" in " ".join(result["warnings"])


def test_an_indexed_sprite_is_refused_with_the_route_that_works(request):
    """Quantizing an indexed sprite replaces the palette without remapping the pixels,
    which changes what every pixel means: measured, the art came back showing different
    colours, and a reduction left pixels pointing past the end of the palette."""
    name = _name(request)
    sprite.create_sprite(name, 8, 8)
    drawing.fill_layer(name, "#c23b22")
    sprite.set_color_mode(name, "indexed")
    before = palette.get_palette(name)

    with pytest.raises(AsepriteError, match="set_color_mode"):
        palette.quantize_palette(name, 4)

    assert palette.get_palette(name) == before, "the refusal left the palette alone"


def test_a_blank_sprite_says_there_was_nothing_to_derive(request):
    name = _name(request)
    sprite.create_sprite(name, 8, 8)

    result = palette.quantize_palette(name, 8)

    assert result["art_colors"] == 0
    assert "Nothing is drawn" in " ".join(result["warnings"])


@pytest.mark.pure
@pytest.mark.parametrize("budget", [0, 1, 257, 1000])
def test_an_impossible_budget_never_reaches_the_editor(budget):
    with pytest.raises(ValidationFailed, match="max_colors"):
        palette.quantize_palette("unused.aseprite", budget)


# ================================================================= packed export
def _held_pose(request, linked: bool) -> str:
    """Three frames of a 4x4 sprite, the first two showing the same thing.

    `linked=True` makes frames 1 and 2 share one image, which is how a held pose is
    authored in a .aseprite file. `linked=False` gives them separate images with
    identical pixels, which is what duplicating a frame produces. They are different
    situations in the file and the exporter has to merge both.
    """
    name = _name(request)
    sprite.create_sprite(name, 4, 4)
    drawing.fill_layer(name, "#ff0000")
    frames.add_frame(name)
    cels.copy_cel(name, "Layer 1", 1, 2)
    if linked:
        cels.link_cels(name, "Layer 1", [1, 2])
    frames.add_frame(name)
    drawing.fill_layer(name, "#0000ff", frame=3)
    tags.add_tag(name, "hold", 1, 3)
    slices.add_slice(name, "corner", 0, 0, 2, 2)
    return name


def test_extrude_duplicates_the_frames_own_edge_pixels(request):
    """Asserted on the border pixels against the frame's four distinct corners.

    A size check would pass for a border of anything at all, including transparent, and
    transparent is exactly the border that causes the bleeding extrude exists to fix.
    """
    name = _corner_sprite(request)
    plain = f"cz/{request.node.name}_plain.png"
    extruded = f"cz/{request.node.name}_extruded.png"

    export.export_spritesheet_packed(name, plain, sheet_type="horizontal")
    result = export.export_spritesheet_packed(
        name, extruded, sheet_type="horizontal", extrude=True
    )

    assert result["sheet_size"] == {"width": 6, "height": 6}, (
        "a 4x4 frame extruded by one pixel on every side is a 6x6 cell"
    )
    rows = inspect.get_pixels(extruded, 0, 0, 6, 6)["pixels"]

    # The frame itself sits at (1, 1) in the cell, so the border row 0 and column 0
    # duplicate the frame's row 0 and column 0.
    assert rows[1][1] == CORNERS[(0, 0)], "the frame is not where the data file says"
    assert rows[0][0] == CORNERS[(0, 0)], "the top-left border pixel is not the corner"
    assert rows[0][1] == CORNERS[(0, 0)], "the top border does not repeat the row above"
    assert rows[1][0] == CORNERS[(0, 0)], "the left border does not repeat the column"
    assert rows[0][5] == CORNERS[(3, 0)]
    assert rows[5][0] == CORNERS[(0, 3)]
    assert rows[5][5] == CORNERS[(3, 3)]
    # ...and the border over the middle of the top edge is the dark field, not a corner
    # bled sideways.
    assert rows[0][2] == FIELD
    assert rows[2][0] == FIELD


def test_without_extrude_the_sheet_is_the_frame_and_nothing_else(request):
    """The control for the test above: the same assertions have to fail here, or they
    were not testing extrude."""
    name = _corner_sprite(request)
    out = f"cz/{request.node.name}.png"

    result = export.export_spritesheet_packed(name, out, sheet_type="horizontal")

    assert result["sheet_size"] == {"width": 4, "height": 4}
    rows = inspect.get_pixels(out, 0, 0, 4, 4)["pixels"]
    assert rows[0][0] == CORNERS[(0, 0)]
    assert rows[3][3] == CORNERS[(3, 3)]


def test_merge_duplicates_shrinks_a_sheet_of_linked_cels(request):
    """The held pose built the way a .aseprite file holds one: two frames, one image."""
    name = _held_pose(request, linked=True)
    assert cels.get_cel(name, "Layer 1", 1)["linked_with"] == [2]
    plain = f"cz/{request.node.name}_plain.png"
    merged = f"cz/{request.node.name}_merged.png"
    merged_data = f"cz/{request.node.name}_merged.json"

    loose = export.export_spritesheet_packed(name, plain, sheet_type="horizontal")
    tight = export.export_spritesheet_packed(
        name, merged, sheet_type="horizontal", merge_duplicates=True,
        data_output=merged_data,
    )

    assert loose["sheet_size"] == {"width": 12, "height": 4}, "three cells of 4x4"
    assert tight["sheet_size"] == {"width": 8, "height": 4}, "two cells of 4x4"
    written = json.loads(Path(tight["data_output"]).read_text(encoding="utf-8"))
    rects = [(f["frame"]["x"], f["frame"]["y"]) for f in written["frames"]]
    assert len(rects) == 3, "every frame is still listed"
    assert rects[0] == rects[1], "the two frames of the hold share one rectangle"
    assert rects[2] != rects[0], "the third frame is different art and keeps its own"


def test_merge_duplicates_also_catches_a_duplicated_frame(request):
    """The other construction: separate images with identical pixels. The exporter
    compares pixels rather than image identity, so both merge, and saying which was
    tested matters because only one of them is what "linked" means."""
    name = _held_pose(request, linked=False)
    assert cels.get_cel(name, "Layer 1", 1)["linked"] is False
    out = f"cz/{request.node.name}.png"

    tight = export.export_spritesheet_packed(
        name, out, sheet_type="horizontal", merge_duplicates=True
    )

    assert tight["sheet_size"] == {"width": 8, "height": 4}


def test_a_packed_sheet_merges_duplicates_whatever_the_flag_says(request):
    """Measured, and worth a test because it makes the flag look broken: a packed sheet
    deduplicates on its own, so a caller comparing packed exports with and without the
    flag sees no difference at all."""
    name = _held_pose(request, linked=False)
    out = f"cz/{request.node.name}.png"

    result = export.export_spritesheet_packed(name, out, sheet_type="packed")

    assert result["sheet_size"] == {"width": 8, "height": 4}
    assert "merges identical frames" in " ".join(result["warnings"])


def test_trim_drops_the_empty_margin(request):
    name = _name(request)
    sprite.create_sprite(name, 16, 16)
    drawing.draw_rectangle(name, 6, 6, 3, 3, "#ff00ff", filled=True)
    out = f"cz/{request.node.name}.png"

    result = export.export_spritesheet_packed(
        name, out, sheet_type="horizontal", trim=True
    )

    assert result["sheet_size"] == {"width": 3, "height": 3}


def test_padding_and_extrude_compose(request):
    name = _corner_sprite(request)
    out = f"cz/{request.node.name}.png"

    result = export.export_spritesheet_packed(
        name, out, sheet_type="horizontal", extrude=True, padding=2
    )

    # One 4x4 frame, a one-pixel extruded border on each side, and two pixels of border
    # padding around the lot.
    assert result["sheet_size"] == {"width": 10, "height": 10}


def test_the_emitted_json_parses_and_carries_the_sections_asked_for(request):
    name = _held_pose(request, linked=True)
    out = f"cz/{request.node.name}.png"
    data = f"cz/{request.node.name}.json"

    result = export.export_spritesheet_packed(
        name, out, sheet_type="horizontal", data_output=data
    )

    assert result["data_format"] == "json-array"
    parsed = json.loads(Path(result["data_output"]).read_text(encoding="utf-8"))
    assert isinstance(parsed["frames"], list), "json-array lists frames in order"
    assert [layer["name"] for layer in parsed["meta"]["layers"]] == ["Layer 1"]
    assert [tag["name"] for tag in parsed["meta"]["frameTags"]] == ["hold"], (
        "the tag section is called frameTags, not tags"
    )
    assert [sl["name"] for sl in parsed["meta"]["slices"]] == ["corner"]
    assert parsed["meta"]["size"] == {"w": 12, "h": 4}


def test_the_hash_format_keys_frames_by_name(request):
    name = _held_pose(request, linked=True)
    out = f"cz/{request.node.name}.png"
    data = f"cz/{request.node.name}.json"

    result = export.export_spritesheet_packed(
        name, out, sheet_type="horizontal", data_output=data, data_format="json-hash"
    )

    parsed = json.loads(Path(result["data_output"]).read_text(encoding="utf-8"))
    assert isinstance(parsed["frames"], dict), "json-hash keys frames by name"
    assert len(parsed["frames"]) == 3
    assert "frameTags" in parsed["meta"]


def test_the_export_does_not_modify_the_source_sprite(request):
    """An export that silently rewrote the sprite would make `trim` destructive, and a
    caller would discover it the next time they opened the file."""
    name = _held_pose(request, linked=True)
    source = config.resolve(name)
    before = source.read_bytes()
    out = f"cz/{request.node.name}.png"

    export.export_spritesheet_packed(
        name, out, sheet_type="packed", trim=True, extrude=True, merge_duplicates=True
    )

    assert source.read_bytes() == before, "the export changed the sprite it exported"
    assert inspect.get_sprite_info(name)["frameCount"] == 3


def test_the_sheet_and_the_data_file_are_both_no_clobber(request):
    name = _held_pose(request, linked=True)
    out = f"cz/{request.node.name}.png"
    other = f"cz/{request.node.name}_other.png"
    data = f"cz/{request.node.name}.json"

    export.export_spritesheet_packed(name, out, data_output=data)

    with pytest.raises(ExportError, match="already exists"):
        export.export_spritesheet_packed(name, out, data_output=data)
    with pytest.raises(ExportError, match="already exists"):
        export.export_spritesheet_packed(name, other, data_output=data)
    export.export_spritesheet_packed(name, out, data_output=data, overwrite=True)


def test_an_unwritten_sheet_is_not_reported_as_a_success(request):
    """`run_cli` catches an Aseprite that exits 0 having done nothing; this path does not
    go through `run_cli`, so the check has to be made again here.

    Measured: `ExportSpriteSheet` given a texture filename whose extension it cannot
    encode writes no file, raises nothing, and its own return value is still true. The
    export would otherwise answer `ok: true` with a path to nothing.
    """
    name = _held_pose(request, linked=True)

    with pytest.raises(ExportError, match="wrote nothing"):
        export.export_spritesheet_packed(
            name, f"cz/{request.node.name}.xyz", sheet_type="horizontal"
        )


@pytest.mark.pure
def test_the_export_refusals_that_do_not_need_an_editor():
    with pytest.raises(ValidationFailed, match="sheet_type"):
        export.export_spritesheet_packed("unused.aseprite", "o.png", sheet_type="grid")
    with pytest.raises(ValidationFailed, match="data_format"):
        export.export_spritesheet_packed(
            "unused.aseprite", "o.png", data_output="o.json", data_format="xml"
        )
    with pytest.raises(ValidationFailed, match="no data_output"):
        export.export_spritesheet_packed(
            "unused.aseprite", "o.png", data_format="json-hash"
        )
    with pytest.raises(ValidationFailed, match="padding"):
        export.export_spritesheet_packed("unused.aseprite", "o.png", padding=-1)


@pytest.mark.pure
def test_the_packed_dedupe_note_is_only_made_for_packed_sheets():
    assert export._packed_sheet_notes("packed", False)
    assert export._packed_sheet_notes("packed", True) == []
    assert export._packed_sheet_notes("rows", False) == []
    assert export._packed_sheet_notes("horizontal", False) == []
