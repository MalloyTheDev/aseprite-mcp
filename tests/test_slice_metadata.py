"""Pure-Python tests for the slice-metadata builder — no Aseprite (always run)."""

from aseprite_mcp.core.slice_metadata import SCHEMA, build_slice_metadata


def _raw(name, *, data="", center=None, pivot=None, color="#00000000",
         bounds=None):
    s = {"name": name, "bounds": bounds or {"x": 0, "y": 0, "width": 4, "height": 4},
         "color": color, "data": data}
    if center is not None:
        s["center"] = center
    if pivot is not None:
        s["pivot"] = pivot
    return s


def _one(raw):
    return build_slice_metadata(sprite="s.aseprite", width=32, height=32, slices=[raw])["slices"][0]


# ----------------------------------------------------------------- document shape
def test_document_shape():
    doc = build_slice_metadata(sprite="slime.aseprite", width=32, height=16, slices=[])
    assert doc["schema"] == SCHEMA
    assert doc["source"] == {"sprite": "slime.aseprite", "width": 32, "height": 16}
    assert doc["slices"] == []


def test_entry_key_order_and_fields():
    entry = _one(_raw("hitbox"))
    assert list(entry) == [
        "name", "type", "id", "bounds", "pivot", "nine_slice", "color", "data", "raw_data"
    ]


# -------------------------------------------------------------- name convention
def test_bare_name_supported_type():
    e = _one(_raw("hitbox"))
    assert e["type"] == "hitbox" and e["id"] is None


def test_type_and_id_from_name():
    e = _one(_raw("attach:weapon"))
    assert e["type"] == "attach" and e["id"] == "weapon"


def test_nine_slice_name():
    e = _one(_raw("nine_slice:center"))
    assert e["type"] == "nine_slice" and e["id"] == "center"


def test_unknown_name_is_custom():
    e = _one(_raw("my_weird_slice"))
    assert e["type"] == "custom" and e["id"] is None and e["name"] == "my_weird_slice"


def test_unknown_name_with_id_is_custom_keeps_id():
    e = _one(_raw("weird:thing"))
    assert e["type"] == "custom" and e["id"] == "thing"


# ------------------------------------------------------------------- data field
def test_data_json_type_wins_over_name():
    e = _one(_raw("foo", data='{"type":"hitbox","id":"body"}'))
    assert e["type"] == "hitbox" and e["id"] == "body"
    assert e["data"] == {"type": "hitbox", "id": "body"}
    assert e["raw_data"] == '{"type":"hitbox","id":"body"}'


def test_data_json_without_type_falls_back_to_name():
    e = _one(_raw("attach:hand_r", data='{"socket":"hand_r"}'))
    assert e["type"] == "attach" and e["id"] == "hand_r"
    assert e["data"] == {"socket": "hand_r"}   # full data still preserved


def test_non_json_data_is_kept_raw_only():
    e = _one(_raw("hurtbox", data="just some notes"))
    assert e["type"] == "hurtbox"
    assert e["data"] is None
    assert e["raw_data"] == "just some notes"


def test_empty_data_is_null_and_empty_raw():
    e = _one(_raw("collision"))
    assert e["data"] is None and e["raw_data"] == ""


def test_json_scalar_data_does_not_crash_type_detection():
    e = _one(_raw("interact", data="42"))
    assert e["type"] == "interact" and e["data"] == 42


def test_data_type_non_string_ignored():
    e = _one(_raw("pivot", data='{"type":123}'))
    assert e["type"] == "pivot"   # numeric type ignored -> name wins


# ------------------------------------------------------------ geometry passthrough
def test_nine_slice_from_center():
    center = {"x": 4, "y": 4, "width": 24, "height": 24}
    e = _one(_raw("ui:panel", center=center))
    assert e["nine_slice"] == {"center": center}


def test_pivot_passthrough_and_null():
    e = _one(_raw("origin", pivot={"x": 16, "y": 24}))
    assert e["pivot"] == {"x": 16, "y": 24}
    assert _one(_raw("origin"))["pivot"] is None


def test_color_and_bounds_passthrough():
    e = _one(_raw("hitbox", color="#ff0000ff",
                  bounds={"x": 8, "y": 12, "width": 16, "height": 14}))
    assert e["color"] == "#ff0000ff"
    assert e["bounds"] == {"x": 8, "y": 12, "width": 16, "height": 14}
