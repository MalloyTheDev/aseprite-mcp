"""Slice user-data: structured values must survive the wire (no Aseprite, always runs).

`Slice.data` is a string in Aseprite, and `export_slice_metadata` parses it back to derive
a slice's `type` and `id`, so `{"type": "hitbox", "id": "body"}` is the shape worth
sending. It could not be sent. The parameter was declared `str`, and a client either sends
structured user-data as an object or has a JSON-looking string parsed into one for it, so
the value arrived as a dict and was refused; the slice then carried nothing and exported as
`type: "custom"` with a null id.

The fix has to hold two properties at once, which is what these tests pin:

  * a dict or list is accepted, and reaches Aseprite as JSON;
  * the parameter still advertises a plain `string`. Declaring the union it accepts would
    leave the property with no concrete type on the wire, which is precisely what the
    strict function-calling clients this server aims to support cannot use.
"""

from __future__ import annotations

import asyncio
import json
import typing

import pytest
from pydantic import TypeAdapter, ValidationError

import aseprite_mcp.server  # noqa: F401  -- importing registers the real tools
from aseprite_mcp.app import mcp
from aseprite_mcp.tools import slices
from aseprite_mcp.tools.slices import _coerce_slice_data

SLICE_DATA_TOOLS = ("add_slice", "set_slice")


@pytest.fixture(scope="module")
def data_param():
    """The validator pydantic actually applies to `add_slice(data=...)`."""
    hints = typing.get_type_hints(slices.add_slice, include_extras=True)
    return TypeAdapter(hints["data"])


# ------------------------------------------------------------------ the coercion itself
def test_a_dict_is_json_encoded():
    assert json.loads(_coerce_slice_data({"type": "hitbox", "id": "body"})) == {
        "type": "hitbox", "id": "body",
    }


def test_a_list_is_json_encoded():
    assert json.loads(_coerce_slice_data([1, 2, 3])) == [1, 2, 3]


def test_a_string_is_stored_as_it_arrives():
    assert _coerce_slice_data("hello") == "hello"
    # Already-encoded JSON is not encoded a second time.
    assert _coerce_slice_data('{"type":"hitbox"}') == '{"type":"hitbox"}'


def test_none_stays_none():
    assert _coerce_slice_data(None) is None


def test_a_scalar_is_handed_on_untouched():
    # Not stringified: `data=5` is a mistake, and leaving the value alone lets the
    # ordinary str validation keep saying so.
    assert _coerce_slice_data(5) == 5


# ------------------------------------------------------------- what the parameter accepts
def test_the_parameter_accepts_a_dict(data_param):
    assert data_param.validate_python({"type": "hitbox", "id": "body"}) == (
        '{"type": "hitbox", "id": "body"}'
    )


def test_the_parameter_accepts_a_list(data_param):
    assert data_param.validate_python(["a", "b"]) == '["a", "b"]'


def test_the_parameter_still_takes_a_plain_string(data_param):
    assert data_param.validate_python("hurtbox") == "hurtbox"
    assert data_param.validate_python(None) is None


def test_the_parameter_still_rejects_a_scalar(data_param):
    with pytest.raises(ValidationError, match="valid string"):
        data_param.validate_python(5)


# ------------------------------------------------------------------ what the wire declares
def test_data_is_advertised_as_a_plain_string():
    """The leniency must not cost the property its concrete type.

    A union would be advertised as `anyOf` with no `type`, and a strict client then omits
    the argument or sends the string "null" -- the failure the portability guards exist to
    prevent. So the schema must stay exactly what a `str` parameter produces.
    """
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in SLICE_DATA_TOOLS:
        schema = tools[name].input_schema["properties"]["data"]
        assert schema == {"type": "string"}, f"{name}.data is advertised as {schema}"
        assert "data" not in tools[name].input_schema.get("required", [])
