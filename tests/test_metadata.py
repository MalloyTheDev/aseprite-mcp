"""Per-object metadata judgement: pure Python, always runs (CI tier).

These cover `core.metadata`, which decides three things before Aseprite is launched:
whether a z-index is a number the file can actually hold, which object a property request
names, and what a value arriving over the wire means.

Each one guards a failure that is invisible in the result otherwise:

  * the editor accepts `cel.zIndex = 100000`, reads it back as 100000 for the rest of
    that run, and reopens the saved file as -31072, so an unbounded tool reports the
    number it was given and leaves a different one on disk;
  * a selector the chosen target does not use would put the property on another object
    than the one the caller named;
  * a hitbox sent as a structure by a client that pre-parses JSON arguments would be
    stored as a string that only looks like the structure.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import metadata
from aseprite_mcp.core.errors import ValidationFailed


# ------------------------------------------------------------------ the z-index range
def test_the_bounds_themselves_are_accepted():
    assert metadata.check_z_index(metadata.Z_INDEX_MAX) == 32767
    assert metadata.check_z_index(metadata.Z_INDEX_MIN) == -32768
    assert metadata.check_z_index(0) == 0


@pytest.mark.parametrize("value", [32768, -32769, 100000, -100000, 1 << 40])
def test_a_z_index_the_file_cannot_hold_is_refused(value):
    """The one that matters. 32768 reloads as -32768 and 100000 as -31072, measured on
    1.3.18.6, so passing these through would report an order the file does not have."""
    with pytest.raises(ValidationFailed, match="16-bit"):
        metadata.check_z_index(value)


def test_the_refusal_names_the_range_a_caller_has_to_stay_in():
    with pytest.raises(ValidationFailed, match="-32768 to 32767"):
        metadata.check_z_index(40000)


@pytest.mark.parametrize("value", [1.5, -0.5, "2.5"])
def test_a_fractional_z_index_is_refused_rather_than_truncated(value):
    """Lua floors 1.7 to 1 without a word, so a caller who passed a fraction would be
    told their z was 1 and never learn the editor had rounded for them."""
    with pytest.raises(ValidationFailed):
        metadata.check_z_index(value)


def test_a_whole_number_written_as_text_is_accepted():
    # Some clients send every argument as a string; 3 and "3" are the same z.
    assert metadata.check_z_index("3") == 3
    assert metadata.check_z_index("-4") == -4
    assert metadata.check_z_index(2.0) == 2


@pytest.mark.parametrize("value", ["front", "", None, True, [1]])
def test_a_z_index_that_is_not_a_number_is_refused(value):
    with pytest.raises(ValidationFailed):
        metadata.check_z_index(value)


# ------------------------------------------------------------------ which object
def test_every_kind_the_editor_supports_is_addressable():
    assert set(metadata.PROPERTY_TARGETS) == {
        "sprite", "layer", "cel", "tag", "slice", "tile"
    }


def test_the_sprite_needs_no_selector():
    assert metadata.resolve_property_target("sprite") == {"target": "sprite"}


def test_a_cel_resolves_to_its_layer_and_frame():
    assert metadata.resolve_property_target("cel", layer="body", frame=3) == {
        "target": "cel", "layer": "body", "frame": 3,
    }


def test_a_cel_with_no_frame_means_the_first_one():
    assert metadata.resolve_property_target("cel", layer="body")["frame"] == 1


def test_a_tag_and_a_slice_are_named():
    assert metadata.resolve_property_target("tag", name="idle") == {
        "target": "tag", "name": "idle",
    }
    assert metadata.resolve_property_target("slice", name="hitbox") == {
        "target": "slice", "name": "hitbox",
    }


def test_a_tile_needs_both_the_layer_and_the_index():
    assert metadata.resolve_property_target("tile", layer="ground", tile=4) == {
        "target": "tile", "layer": "ground", "tile": 4,
    }


@pytest.mark.parametrize(
    "target,kwargs",
    [
        ("layer", {}),
        ("cel", {"frame": 2}),
        ("tag", {}),
        ("slice", {}),
        ("tile", {"layer": "ground"}),
        ("tile", {"tile": 2}),
    ],
)
def test_a_missing_selector_is_refused_and_named(target, kwargs):
    with pytest.raises(ValidationFailed, match="needs"):
        metadata.resolve_property_target(target, **kwargs)


@pytest.mark.parametrize(
    "target,kwargs,unused",
    [
        ("sprite", {"layer": "body"}, "layer"),
        ("layer", {"name": "idle"}, "name"),
        ("layer", {"frame": 2}, "frame"),
        ("tag", {"layer": "body"}, "layer"),
        ("slice", {"tile": 1}, "tile"),
        ("cel", {"layer": "body", "name": "idle"}, "name"),
    ],
)
def test_a_selector_the_target_does_not_use_is_refused_not_ignored(target, kwargs, unused):
    """`target="sprite", layer="body"` means the caller believed they were addressing the
    layer. Ignoring the argument would put the property on the sprite and report success,
    and the caller would find out when something read the layer and found nothing.

    The match is on "does not use" rather than on the selector's name: "needs layer (the
    layer's name)" also contains the word "name", so a looser pattern let one case pass
    on the message for a missing selector instead.
    """
    with pytest.raises(ValidationFailed, match=f"does not use {unused}"):
        metadata.resolve_property_target(target, **kwargs)


def test_an_unknown_target_lists_the_ones_that_exist():
    with pytest.raises(ValidationFailed, match="sprite, layer, cel, tag, slice, tile"):
        metadata.resolve_property_target("frame")


def test_a_target_is_case_and_space_insensitive():
    assert metadata.resolve_property_target(" Sprite ")["target"] == "sprite"


def test_a_negative_tile_index_is_refused():
    with pytest.raises(ValidationFailed, match="starts at 0"):
        metadata.resolve_property_target("tile", layer="ground", tile=-1)


# ------------------------------------------------------------------ keys and namespaces
@pytest.mark.parametrize("key", ["", "   ", None])
def test_an_empty_key_is_refused(key):
    with pytest.raises(ValidationFailed, match="non-empty"):
        metadata.check_property_key(key)


def test_a_key_is_kept_exactly_as_given():
    # Including surrounding spaces: it is somebody's key, and trimming it would mean a
    # write and a read of the same string reached different properties.
    assert metadata.check_property_key(" odd key ") == " odd key "


def test_the_unnamed_group_has_one_spelling():
    """An empty namespace and no namespace are the same group in Aseprite, so folding
    them together is what stops the same property being written twice under two names."""
    assert metadata.normalise_namespace(None) is None
    assert metadata.normalise_namespace("") is None
    assert metadata.normalise_namespace("   ") is None
    assert metadata.normalise_namespace(" game.rig ") == "game.rig"


# ------------------------------------------------------------------ values
def test_a_value_is_text_by_default():
    assert metadata.parse_property_value("boss") == "boss"
    assert metadata.parse_property_value("7") == "7"
    assert metadata.parse_property_value("true") == "true"


def test_as_json_stores_the_type_the_text_describes():
    assert metadata.parse_property_value("7", as_json=True) == 7
    assert metadata.parse_property_value("7.5", as_json=True) == 7.5
    assert metadata.parse_property_value("true", as_json=True) is True
    assert metadata.parse_property_value('"boss"', as_json=True) == "boss"


def test_a_structure_is_read_as_one_without_being_asked():
    """The failure this prevents has already happened once in this codebase, to slice
    data: a client that pre-parses a JSON-looking argument hands the tool a dict, which
    is re-encoded to text on the way in, and storing that text would give the caller a
    string where they asked for a structure."""
    assert metadata.parse_property_value('{"x": 8, "y": 15}') == {"x": 8, "y": 15}
    assert metadata.parse_property_value("[1, 2, 3]") == [1, 2, 3]


def test_text_that_merely_starts_with_a_bracket_stays_text():
    assert metadata.parse_property_value("[draft]") == "[draft]"
    assert metadata.parse_property_value("{not json") == "{not json"


def test_as_json_with_text_that_is_not_json_is_refused():
    with pytest.raises(ValidationFailed, match="not valid JSON"):
        metadata.parse_property_value("boss", as_json=True)


def test_a_missing_value_points_at_delete():
    with pytest.raises(ValidationFailed, match="delete=True"):
        metadata.parse_property_value(None)


def test_a_null_is_refused_because_a_property_cannot_hold_one():
    with pytest.raises(ValidationFailed, match="delete=True"):
        metadata.parse_property_value("null", as_json=True)


def test_a_null_buried_inside_a_structure_is_refused_too():
    """A Lua table cannot hold a null, so `{"anchor": null}` would arrive with no
    `anchor` key at all and the write would report success with a piece missing."""
    with pytest.raises(ValidationFailed, match=r"anchor"):
        metadata.parse_property_value('{"anchor": null, "id": "a"}')
    with pytest.raises(ValidationFailed, match=r"\[1\]"):
        metadata.parse_property_value("[1, null, 3]")


def test_a_value_nested_past_the_cap_is_refused():
    deep = "[" * 10 + "1" + "]" * 10
    with pytest.raises(ValidationFailed, match="levels deep"):
        metadata.parse_property_value(deep)


def test_a_value_nested_within_the_cap_is_accepted():
    ok = "[" * 4 + "1" + "]" * 4
    assert metadata.parse_property_value(ok) == [[[[1]]]]


def test_a_non_string_value_is_serialized_before_it_is_parsed():
    # What the BeforeValidator in tools/cels.py does to a dict, done directly: both
    # routes have to reach the same stored value.
    assert metadata.parse_property_value({"x": 1}) == {"x": 1}
    assert metadata.parse_property_value([1, 2]) == [1, 2]
