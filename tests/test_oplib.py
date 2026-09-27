"""Pure-Python tests for the batch operation registry — no Aseprite (always run)."""

import pytest

from aseprite_mcp.core import oplib
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.limits import MAX_BATCH_OPERATIONS


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


# ----------------------------------------------------------------- size limits
def test_batch_at_limit_validates():
    ops = [{"op": "add_layer", "args": {"name": "x"}}] * MAX_BATCH_OPERATIONS
    out = oplib.validate_operations(ops)
    assert len(out) == MAX_BATCH_OPERATIONS  # exactly the cap is allowed


def test_batch_over_limit_fails_with_split_hint():
    ops = [{"op": "add_layer", "args": {"name": "x"}}] * (MAX_BATCH_OPERATIONS + 1)
    with pytest.raises(ValidationFailed, match=r"operations has \d+ items; maximum is 500"):
        oplib.validate_operations(ops)


# ------------------------------------------------- frame arguments (issue #61)
def test_frame_arg_below_one_is_rejected_with_the_op_index():
    # clamp_frame folded 0 into 1 and the summary then quoted the requested number.
    with pytest.raises(ValidationFailed, match=r"op 0 \(set_frame_duration\).*1-based"):
        oplib.validate_operations(
            [{"op": "set_frame_duration", "args": {"frame": 0, "duration_ms": 50}}]
        )


def test_add_tag_frame_zero_is_rejected():
    with pytest.raises(ValidationFailed, match="1-based frame number"):
        oplib.validate_operations(
            [{"op": "add_tag", "args": {"name": "t", "from": 0, "to": 50000}}]
        )


def test_optional_frame_argument_is_still_validated():
    with pytest.raises(ValidationFailed, match="1-based frame number"):
        oplib.validate_operations(
            [{"op": "fill_layer", "args": {"color": "#fff", "frame": -1}}]
        )


def test_valid_frame_is_normalized_to_an_int():
    out = oplib.validate_operations([{"op": "duplicate_frame", "args": {"frame": "2"}}])
    assert out[0]["args"]["frame"] == 2


def test_every_frame_argument_uses_the_frame_kind():
    # A frame argument typed as a plain int would skip the 1-based check entirely.
    frame_args = {"frame", "copy_from", "from_frame", "to_frame"}
    for op, spec in oplib.OP_SPECS.items():
        for arg, (kind, _required) in spec.items():
            if arg in frame_args or (op == "add_tag" and arg in ("from", "to")):
                assert kind == "frame", f"{op}.{arg} should be the frame kind, not {kind}"


# ---------------------------------------- op argument names / aliases (issue #62)
def test_add_tag_accepts_the_standalone_tool_spelling():
    # `add_tag(from_frame=..., to_frame=...)` as a tool; `from`/`to` as an op. Both work.
    out = oplib.validate_operations(
        [{"op": "add_tag", "args": {"name": "walk", "from_frame": 1, "to_frame": 3}}]
    )
    assert out[0]["args"] == {"name": "walk", "from": 1, "to": 3}


def test_replace_color_accepts_the_standalone_tool_spelling():
    out = oplib.validate_operations(
        [{"op": "replace_color", "args": {"from_color": "#ff0000", "to_color": "#00ff00"}}]
    )
    args = out[0]["args"]
    assert args["from"] == {"r": 255, "g": 0, "b": 0, "a": 255}
    assert args["to"] == {"r": 0, "g": 255, "b": 0, "a": 255}


def test_canonical_spelling_still_works():
    out = oplib.validate_operations(
        [{"op": "add_tag", "args": {"name": "walk", "from": 1, "to": 2}}]
    )
    assert out[0]["args"]["from"] == 1


def test_both_spellings_at_once_is_rejected():
    with pytest.raises(ValidationFailed, match="not both"):
        oplib.validate_operations(
            [{"op": "add_tag", "args": {"name": "w", "from": 1, "from_frame": 2, "to": 2}}]
        )


def test_unknown_arg_message_lists_the_alias_too():
    with pytest.raises(ValidationFailed, match="from_frame"):
        oplib.validate_operations([{"op": "add_tag", "args": {"nope": 1}}])


def test_add_layer_op_accepts_group_like_the_standalone_tool():
    out = oplib.validate_operations(
        [{"op": "add_layer", "args": {"name": "fx", "group": "body"}}]
    )
    assert out[0]["args"] == {"name": "fx", "group": "body"}


def test_operations_reference_covers_every_op_and_argument():
    """The generated listing is the only documentation of op arguments, so it must not
    be able to drift from the registry it documents."""
    text = oplib.operations_reference()
    lines = text.splitlines()
    assert len(lines) == len(oplib.OP_SPECS)
    for op, spec in oplib.OP_SPECS.items():
        matching = [ln for ln in lines if ln.strip().startswith(f"{op}(")]
        assert len(matching) == 1, f"{op} is not listed exactly once"
        line = matching[0]
        for arg, (kind, required) in spec.items():
            assert f"{arg}={kind}" in line, f"{op}: '{arg}={kind}' missing from {line!r}"
            # '?' marks optional, so a required argument must not carry one.
            assert (f"{arg}={kind}?" in line) is (not required), f"{op}.{arg}: wrong optionality"


def test_operations_reference_lists_no_unknown_ops():
    listed = {ln.strip().split("(", 1)[0] for ln in oplib.operations_reference().splitlines()}
    assert listed == set(oplib.OP_SPECS)


def test_operations_reference_documents_every_alias():
    text = oplib.operations_reference()
    for op, aliases in oplib.OP_ARG_ALIASES.items():
        line = next(ln for ln in text.splitlines() if ln.strip().startswith(f"{op}("))
        for alias, target in aliases.items():
            assert f"{alias} for {target}" in line


def test_apply_operations_docstring_carries_the_generated_listing():
    from aseprite_mcp.tools import batch
    doc = batch.apply_operations.__doc__ or ""
    for line in oplib.operations_reference().splitlines():
        assert line.strip() in doc
