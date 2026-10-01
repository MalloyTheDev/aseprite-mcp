"""Integration tests for export_slice_metadata — require Aseprite (--run-aseprite)."""

import asyncio
import json
from pathlib import Path

import pytest

import aseprite_mcp.server  # noqa: F401  -- importing registers the real tools
from aseprite_mcp.app import mcp
from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import export_presets, slices, sprite


def _call(name, arguments):
    """Invoke a tool the way a client does, through schema validation."""
    result = asyncio.run(mcp.call_tool(name, arguments))
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple):
        result = result[0]
    blocks = getattr(result, "content", result)
    return json.loads(blocks[0].text)

_REQUIRED = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def _setup(name):
    sprite.create_sprite(f"{name}.aseprite", 32, 32)
    slices.add_slice(f"{name}.aseprite", "hitbox", 8, 12, 16, 14, color="#ff0000ff")
    slices.add_slice(f"{name}.aseprite", "attach:weapon", 20, 14, 1, 1,
                     pivot_x=20, pivot_y=14, color="#00ffffff")
    slices.add_slice(f"{name}.aseprite", "ui:panel", 0, 0, 32, 32,
                     center_x=4, center_y=4, center_width=24, center_height=24)
    slices.add_slice(f"{name}.aseprite", "body", 0, 0, 10, 10,
                     data='{"type":"hurtbox","id":"core"}')


def test_export_slice_metadata_round_trip():
    _setup("w/sl")
    m = export_presets.export_slice_metadata("w/sl.aseprite")
    assert set(m) >= _REQUIRED
    assert m["kind"] == "engine_metadata"

    path = m["created_files"][0]["path"]
    assert path.endswith("sl_slices.json")  # default <sprite>_slices.json
    doc = json.loads(Path(path).read_text(encoding="utf-8"))

    assert doc["schema"] == "aseprite_mcp.slice_metadata.v1"
    assert doc["source"] == {"sprite": "sl.aseprite", "width": 32, "height": 32}

    by_name = {s["name"]: s for s in doc["slices"]}
    assert by_name["hitbox"]["type"] == "hitbox" and by_name["hitbox"]["id"] is None
    assert by_name["hitbox"]["color"] == "#ff0000ff"
    assert by_name["hitbox"]["bounds"] == {"x": 8, "y": 12, "width": 16, "height": 14}

    weapon = by_name["attach:weapon"]
    assert weapon["type"] == "attach" and weapon["id"] == "weapon"
    assert weapon["pivot"] == {"x": 20, "y": 14}

    panel = by_name["ui:panel"]
    assert panel["type"] == "custom" and panel["id"] == "panel"  # "ui" not a known type
    assert panel["nine_slice"] == {"center": {"x": 4, "y": 4, "width": 24, "height": 24}}

    body = by_name["body"]  # data JSON type wins over the name
    assert body["type"] == "hurtbox" and body["id"] == "core"
    assert body["data"] == {"type": "hurtbox", "id": "core"}


def test_export_slice_metadata_no_clobber():
    _setup("w/sl2")
    export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json")
    with pytest.raises(ExportError, match="already exists"):
        export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json")
    export_presets.export_slice_metadata("w/sl2.aseprite", "w/sl2_meta.json", overwrite=True)


def test_export_slice_metadata_no_slices_warns():
    sprite.create_sprite("w/sl3.aseprite", 16, 16)
    m = export_presets.export_slice_metadata("w/sl3.aseprite")
    assert m["warnings"] == ["No slices found in the sprite."]
    doc = json.loads(Path(m["created_files"][0]["path"]).read_text(encoding="utf-8"))
    assert doc["slices"] == []


def _slice_doc(meta):
    return json.loads(Path(meta["created_files"][0]["path"]).read_text(encoding="utf-8"))


def test_dict_slice_data_round_trips_to_type_and_id():
    """A dict is JSON-encoded on the way in, so the export derives type/id from it.

    Without this the slice was stored with no data at all and came back as
    type "custom" with a null id.
    """
    sprite.create_sprite("w/sdict.aseprite", 32, 32)
    slices.add_slice("w/sdict.aseprite", "torso", 8, 8, 16, 16,
                     data={"type": "hitbox", "id": "body"})
    m = export_presets.export_slice_metadata("w/sdict.aseprite", "w/sdict_slices.json")
    torso = next(s for s in _slice_doc(m)["slices"] if s["name"] == "torso")
    assert torso["type"] == "hitbox"
    assert torso["id"] == "body"
    assert torso["data"] == {"type": "hitbox", "id": "body"}


def test_a_client_can_send_slice_data_as_an_object():
    """The same thing over the wire, which is where it used to be refused.

    Calling the Python function proves the coercion; only going through `call_tool` proves
    a client can get a dict past schema validation, and that is the shape a client sends
    (or the shape its JSON-looking string is parsed into before the tool is reached).
    """
    sprite.create_sprite("w/swire.aseprite", 32, 32)
    result = _call("add_slice", {
        "filename": "w/swire.aseprite", "name": "torso",
        "x": 8, "y": 8, "width": 16, "height": 16,
        "data": {"type": "hitbox", "id": "body"},
    })
    # add_slice answers with the sprite's state; reaching it at all is the point, since
    # the dict argument is what used to be refused before the tool ran.
    assert [sl["name"] for sl in result["slices"]] == ["torso"]

    m = export_presets.export_slice_metadata("w/swire.aseprite", "w/swire_slices.json")
    torso = next(s for s in _slice_doc(m)["slices"] if s["name"] == "torso")
    assert (torso["type"], torso["id"]) == ("hitbox", "body")


def test_a_client_can_also_send_it_as_a_json_string():
    """The other half of the same call, kept because clients differ in which one they
    send: some pass the string through, some parse it into an object first. The stored
    text may be re-spaced by that round trip, so what has to survive is the data."""
    sprite.create_sprite("w/sstr.aseprite", 32, 32)
    _call("add_slice", {
        "filename": "w/sstr.aseprite", "name": "torso",
        "x": 8, "y": 8, "width": 16, "height": 16,
        "data": '{"type":"hurtbox","id":"core"}',
    })
    m = export_presets.export_slice_metadata("w/sstr.aseprite", "w/sstr_slices.json")
    torso = next(s for s in _slice_doc(m)["slices"] if s["name"] == "torso")
    assert (torso["type"], torso["id"]) == ("hurtbox", "core")
    assert torso["data"] == {"type": "hurtbox", "id": "core"}


# ------------------------------------------- reading a slice back without exporting (#106)
def test_list_slices_reads_structured_data_back_on_its_own():
    """The gap that made confirming PR #24 inconclusive: `list_slices` showed the same thing
    for a slice with data and one without, so the only way to see what a slice carried
    was to write an export file and parse it."""
    sprite.create_sprite("w/read.aseprite", 16, 16)
    slices.add_slice("w/read.aseprite", "body", 0, 0, 8, 8,
                     data={"type": "hitbox", "id": "body"}, color="#ff0000ff")
    slices.add_slice("w/read.aseprite", "plain", 8, 8, 4, 4)

    by_name = {s["name"]: s for s in slices.list_slices("w/read.aseprite")["slices"]}

    assert by_name["body"]["data_parsed"] == {"type": "hitbox", "id": "body"}
    assert json.loads(by_name["body"]["data"]) == {"type": "hitbox", "id": "body"}
    assert by_name["body"]["color"] == "#ff0000ff"
    assert "data" not in by_name["plain"], "a slice that carries nothing says nothing"
    assert "data_parsed" not in by_name["plain"]


def test_user_data_that_is_not_json_comes_back_as_the_string():
    """User-data is a free string in Aseprite and a slice labelled by convention rather
    than by JSON is ordinary, so this is not a parse failure to report."""
    sprite.create_sprite("w/plainstr.aseprite", 16, 16)
    slices.add_slice("w/plainstr.aseprite", "body", 0, 0, 8, 8, data="hitbox")

    entry = slices.list_slices("w/plainstr.aseprite")["slices"][0]

    assert entry["data"] == "hitbox"
    assert "data_parsed" not in entry


def test_the_data_string_round_trips_through_set_slice_unchanged():
    """`data` is reported as stored rather than re-encoded, so reading and writing it
    back is not an edit."""
    sprite.create_sprite("w/trip.aseprite", 16, 16)
    slices.add_slice("w/trip.aseprite", "body", 0, 0, 8, 8, data='{"type":"hurtbox"}')

    first = slices.list_slices("w/trip.aseprite")["slices"][0]["data"]
    slices.set_slice("w/trip.aseprite", "body", data=first)
    second = slices.list_slices("w/trip.aseprite")["slices"][0]["data"]

    assert first == second == '{"type":"hurtbox"}'


def test_get_sprite_info_reports_the_data_too():
    """`list_slices` returns `sprite_info`'s slices, so the fix belongs in the shared
    serializer rather than in the one tool that was noticed to be missing it."""
    from aseprite_mcp.tools import inspect as inspect_tools

    sprite.create_sprite("w/info.aseprite", 16, 16)
    slices.add_slice("w/info.aseprite", "body", 0, 0, 8, 8, data={"type": "hitbox"})

    entry = inspect_tools.get_sprite_info("w/info.aseprite")["slices"][0]

    assert json.loads(entry["data"]) == {"type": "hitbox"}
    assert entry["color"].startswith("#")


def test_the_export_still_reads_colour_and_data_from_the_shared_serializer():
    """The export had a private slice reader that was the only thing reporting colour and
    user-data, and launched Aseprite a second time to use it. Deleting it must not cost
    the exported document either field."""
    _setup("w/shared")

    doc = _slice_doc(export_presets.export_slice_metadata("w/shared.aseprite"))
    by_name = {s["name"]: s for s in doc["slices"]}

    assert by_name["hitbox"]["color"] == "#ff0000ff"
    assert by_name["body"]["data"] == {"type": "hurtbox", "id": "core"}
    assert by_name["body"]["raw_data"] == '{"type":"hurtbox","id":"core"}'
    assert by_name["hitbox"]["raw_data"] == "", "no data is an empty string, as before"
