"""Pure-Python tests for the batch operation registry — no Aseprite (always run)."""

import pytest

from aseprite_mcp.core import oplib
from aseprite_mcp.core.errors import ValidationFailed


def test_unknown_op_fails():
    with pytest.raises(ValidationFailed, match="unknown operation"):
        oplib.validate_operations([{"op": "explode", "args": {}}])


def test_missing_required_arg_fails():
    with pytest.raises(ValidationFailed, match="missing required arg 'name'"):
        oplib.validate_operations([{"op": "add_layer", "args": {}}])


def test_missing_op_field_fails():
    with pytest.raises(ValidationFailed, match="needs an 'op' field"):
        oplib.validate_operations([{"args": {}}])


def test_empty_list_fails():
    with pytest.raises(ValidationFailed, match="non-empty"):
        oplib.validate_operations([])


def test_bad_color_fails():
    with pytest.raises(ValidationFailed, match="bad value for 'color'"):
        oplib.validate_operations(
            [{"op": "fill_layer", "args": {"color": "notacolor"}}]
        )


def test_bad_int_fails():
    with pytest.raises(ValidationFailed, match="bad value for 'x'"):
        oplib.validate_operations(
            [{"op": "set_pixel", "args": {"x": "abc", "y": 1, "color": "#fff"}}]
        )


def test_error_message_includes_op_index():
    with pytest.raises(ValidationFailed, match=r"op 1 "):
        oplib.validate_operations([
            {"op": "add_layer", "args": {"name": "ok"}},
            {"op": "add_layer", "args": {}},  # index 1 is the bad one
        ])


def test_validation_normalizes_args():
    out = oplib.validate_operations([
        {"op": "draw_rectangle",
         "args": {"x": "2", "y": "3", "width": 4, "height": 5, "color": "#ff0000", "layer": "body"}},
    ])
    a = out[0]["args"]
    assert a["x"] == 2 and a["y"] == 3 and a["width"] == 4  # ints coerced
    assert a["color"] == {"r": 255, "g": 0, "b": 0, "a": 255}  # colour parsed
    assert a["layer"] == "body"


def test_optional_args_omitted_when_absent():
    out = oplib.validate_operations([{"op": "add_layer", "args": {"name": "x"}}])
    assert out[0]["args"] == {"name": "x"}  # opacity/blend_mode/visible omitted


def test_validation_preserves_order():
    ops = [
        {"op": "add_layer", "args": {"name": "a"}},
        {"op": "add_frame", "args": {"duration_ms": 100}},
        {"op": "fill_layer", "args": {"color": "#000"}},
    ]
    out = oplib.validate_operations(ops)
    assert [o["op"] for o in out] == ["add_layer", "add_frame", "fill_layer"]


def test_summarize_is_a_string():
    out = oplib.validate_operations([{"op": "add_layer", "args": {"name": "body"}}])
    assert "add_layer" in oplib.summarize(out[0])


def test_color_index_spec_normalizes():
    out = oplib.validate_operations([{"op": "fill_layer", "args": {"color": "index:3"}}])
    assert out[0]["args"]["color"] == {"index": 3}
