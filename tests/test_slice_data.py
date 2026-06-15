"""Pure-Python tests for slice user-data coercion — no Aseprite (always run)."""

import json

from aseprite_mcp.tools.slices import _coerce_slice_data


def test_none_passthrough():
    assert _coerce_slice_data(None) is None


def test_string_passthrough():
    assert _coerce_slice_data("hello") == "hello"
    # A JSON-looking string is kept verbatim (not re-encoded).
    assert _coerce_slice_data('{"type":"hitbox"}') == '{"type":"hitbox"}'


def test_dict_is_json_encoded():
    out = _coerce_slice_data({"type": "hitbox", "id": "body"})
    assert isinstance(out, str)
    assert json.loads(out) == {"type": "hitbox", "id": "body"}


def test_list_is_json_encoded():
    out = _coerce_slice_data([1, 2, 3])
    assert isinstance(out, str)
    assert json.loads(out) == [1, 2, 3]
