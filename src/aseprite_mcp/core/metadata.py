"""Per-object metadata: what the editor will accept, decided before Aseprite is launched.

Two kinds of thing inside a sprite are neither pixels nor palette, and both are reached
per object rather than per file:

  * a cel's **z-index**, which reorders that one cel against the other layers' cels in
    the same frame without restructuring the layer stack;
  * **custom properties**, a key/value store carried by a sprite, layer, cel, tag, slice
    or tile, optionally grouped under a namespace, and saved inside the .aseprite file.

What lives here is the part that is naming and arithmetic: which object kinds exist and
what names one of them, what range the file format can actually hold, and how a value
that arrived over the wire becomes a typed value to store. The editor work stays in Lua,
where the sprite is.
"""

from __future__ import annotations

import json

from .errors import ValidationFailed

# --------------------------------------------------------------------------- #
# A cel's z-index                                                             #
# --------------------------------------------------------------------------- #
# The .aseprite file stores a cel's z-index in a signed 16-bit field, and the Lua setter
# does not police it: assigning 100000 is accepted, reads back as 100000 for the rest of
# that run, and reopens as -31072. Measured on 1.3.18.6, saving and reloading one cel per
# value: 32767 and -32768 survive, 32768 comes back as -32768, 100000 comes back as
# -31072, -100000 comes back as 31072.
#
# So the range is a refusal rather than a clamp. A tool that passed a larger number
# through would report the z it was given, pass its own read-back check inside the same
# run, and leave a different number (often of the opposite sign, so the cel draws on the
# wrong side) in the file. Clamping would be no better: the caller asked for an order and
# would be told it got one.
Z_INDEX_MIN = -32768
Z_INDEX_MAX = 32767


def check_z_index(value) -> int:
    """Validate a cel z-index and return it as an int, or raise ``ValidationFailed``.

    Fractions are refused rather than truncated: Lua's setter floors 1.7 to 1 silently,
    and a caller who passed a fraction meant something this field cannot express.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationFailed(
                f"z must be a whole number between {Z_INDEX_MIN} and {Z_INDEX_MAX}; "
                f"got {value!r}."
            ) from None
    if isinstance(value, float) and value != int(value):
        raise ValidationFailed(
            f"z must be a whole number; got {value!r}. A z-index is a position in an "
            "order, so there is nothing between two of them."
        )
    number = int(value)
    if not Z_INDEX_MIN <= number <= Z_INDEX_MAX:
        raise ValidationFailed(
            f"z is {number}, outside the range an .aseprite file can hold "
            f"({Z_INDEX_MIN} to {Z_INDEX_MAX}). The editor accepts it in memory and "
            "then stores it in a 16-bit field, so saving and reopening would turn it "
            "into a different number, usually of the opposite sign. Z-indexes only have "
            "to order the cels in one frame, so small numbers are enough."
        )
    return number


# --------------------------------------------------------------------------- #
# Custom properties                                                           #
# --------------------------------------------------------------------------- #
# The six kinds of object that carry properties, verified one by one against 1.3.18.6:
# each one took a plain key and a namespaced key, and both came back after a save and a
# reopen.
PROPERTY_TARGETS = ("sprite", "layer", "cel", "tag", "slice", "tile")

# Which arguments name an object of each kind, and which of those it cannot do without.
#
# A selector the chosen target does not use is refused rather than ignored. An argument
# that is silently discarded is indistinguishable from one that was honoured, so
# `target="sprite", layer="body"` has to be an error: the caller who wrote it believed
# they were addressing the layer, and the sprite would have taken the property instead.
_TARGET_ACCEPTS: dict[str, tuple[str, ...]] = {
    "sprite": (),
    "layer": ("layer",),
    "cel": ("layer", "frame"),
    "tag": ("name",),
    "slice": ("name",),
    "tile": ("layer", "tile"),
}
_TARGET_REQUIRES: dict[str, tuple[str, ...]] = {
    "sprite": (),
    "layer": ("layer",),
    # `frame` defaults to the first frame, which is the only selector with a sensible
    # default: there is exactly one sprite, and a layer or tag or slice has no default.
    "cel": ("layer",),
    "tag": ("name",),
    "slice": ("name",),
    "tile": ("layer", "tile"),
}

_WHAT_EACH_SELECTOR_IS = {
    "layer": "layer (the layer's name)",
    "frame": "frame (a 1-based frame number)",
    "name": "name (the tag's or slice's name)",
    "tile": "tile (an index into the tilemap layer's tileset)",
}


def normalise_property_target(value) -> str:
    """Canonicalise a property target name, or refuse it naming the six that exist."""
    found = str(value).strip().lower()
    if found not in PROPERTY_TARGETS:
        raise ValidationFailed(
            f"target must be one of: {', '.join(PROPERTY_TARGETS)}. Got {value!r}."
        )
    return found


def resolve_property_target(
    target,
    *,
    layer=None,
    frame=None,
    name=None,
    tile=None,
) -> dict:
    """Which object a property request names, as a dict of the selectors that apply.

    Returns `{"target": <kind>, ...}` carrying only the selectors that kind uses, so the
    Lua side has nothing to decide: `{"target": "cel", "layer": "body", "frame": 2}`.

    Raises `ValidationFailed` for a selector the kind needs and did not get, and for one
    it was given and does not use.
    """
    kind = normalise_property_target(target)
    given = {"layer": layer, "frame": frame, "name": name, "tile": tile}
    accepts = _TARGET_ACCEPTS[kind]

    unused = sorted(k for k, v in given.items() if v is not None and k not in accepts)
    if unused:
        takes = ", ".join(accepts) if accepts else "none of them"
        raise ValidationFailed(
            f"target={kind!r} does not use {', '.join(unused)}; it takes {takes}. "
            "The property would have gone onto a different object than the one you "
            "named, so this is refused rather than ignored."
        )

    missing = [k for k in _TARGET_REQUIRES[kind] if given[k] is None]
    if missing:
        wanted = "; ".join(_WHAT_EACH_SELECTOR_IS[k] for k in missing)
        raise ValidationFailed(
            f"target={kind!r} needs {wanted}. Without it there is no one object to put "
            "the property on."
        )

    resolved: dict = {"target": kind}
    if "layer" in accepts:
        resolved["layer"] = str(layer)
    if "frame" in accepts:
        resolved["frame"] = 1 if frame is None else int(frame)
    if "name" in accepts:
        resolved["name"] = str(name)
    if "tile" in accepts:
        index = int(tile)
        if index < 0:
            raise ValidationFailed(f"tile is {index}; a tileset index starts at 0.")
        resolved["tile"] = index
    return resolved


def check_property_key(key) -> str:
    """Validate a property key, which is any non-empty string."""
    text = "" if key is None else str(key)
    if not text.strip():
        raise ValidationFailed(
            "key must be a non-empty property name, e.g. 'hitbox' or 'anchor'."
        )
    return text


def normalise_namespace(namespace) -> str | None:
    """A namespace as the Lua side wants it: a non-empty string, or None.

    Aseprite calls this the extension ID, and the unnamed group is where the editor's
    own UI puts properties a user types in. An empty string means that group, so it is
    folded to None rather than passed on as a second way of spelling the same thing.
    """
    if namespace is None:
        return None
    text = str(namespace).strip()
    return text or None


# A property value is a tree, and `to_lua` walks it recursively, so its depth is the
# depth of that recursion. Eight is far past any hitbox, anchor point or frame-event
# list, and stops a value from being a way to recurse the serializer arbitrarily deep.
MAX_PROPERTY_DEPTH = 8


def _check_tree(value, path: str, depth: int) -> None:
    """Refuse a value tree that cannot be stored faithfully.

    A null anywhere inside is the one case worth refusing rather than accepting: a Lua
    table cannot hold one, so `{"anchor": null}` would arrive as a table with no
    `anchor` key at all and the write would report success having stored something with
    a piece missing.
    """
    if depth > MAX_PROPERTY_DEPTH:
        raise ValidationFailed(
            f"value nests more than {MAX_PROPERTY_DEPTH} levels deep at {path}. "
            "Properties hold game metadata, not documents; flatten it."
        )
    if value is None:
        where = "value" if path == "value" else path
        raise ValidationFailed(
            f"{where} is null, and a property cannot hold one: the key would simply be "
            "absent, so the write would claim to have stored something it had not. Use "
            "delete=True to remove a property, or store false, 0 or \"\" instead."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _check_tree(item, f"{path}[{key!r}]", depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_tree(item, f"{path}[{index}]", depth + 1)


def parse_property_value(value, *, as_json: bool = False):
    """The typed value to store, from the string that arrived on the wire.

    Text by default, so `value="boss"` stores the string `boss` and `value="7"` stores
    the two-character string `7`. With `as_json=True` the text is parsed as JSON first,
    which is how a number, a boolean or a structure is stored: `"7"` becomes the number
    7, `"true"` becomes a boolean, `'{"x": 8, "y": 15}'` becomes a table.

    A value that *starts* like a JSON object or array is parsed whether or not `as_json`
    was passed, because there is no other reading of one and the alternative has already
    cost this project a bug elsewhere: some clients parse a JSON-looking argument before
    the server ever sees it, so a hitbox sent as `{"x": 8}` arrives as a dict, is
    re-encoded to text on the way in, and would otherwise be stored as a string that
    only looks like the structure the caller meant (the same failure
    `tools/slices.py::_coerce_slice_data` exists for).

    Text that merely begins with a bracket and is not JSON, `"[draft]"`, stays text:
    the parse is attempted and its failure is not an error unless `as_json` asked for
    JSON explicitly. The one value this leaves unreachable is the literal *text* of a
    JSON object, which nothing wants in a typed property store.
    """
    if value is None:
        raise ValidationFailed(
            "value is required. Pass delete=True to remove a property instead."
        )
    text = value if isinstance(value, str) else json.dumps(value)
    looks_structured = text.strip()[:1] in ("{", "[")
    if as_json or looks_structured:
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            if as_json:
                raise ValidationFailed(
                    f"value is not valid JSON: {exc}. With as_json=True the value is "
                    'parsed as JSON, so text has to be quoted ("boss"), and a structure '
                    'needs JSON syntax ({"x": 8, "y": 15}).'
                ) from exc
            return text
        _check_tree(parsed, "value", 0)
        return parsed
    return text
