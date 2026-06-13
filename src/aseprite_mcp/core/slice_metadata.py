"""Generic slice-metadata builder — ``aseprite_mcp.slice_metadata.v1``.

Engine-agnostic: turns raw Aseprite slice records into a clean JSON-able structure that
Godot, Unity, or a custom engine can consume. Each slice gets a semantic ``type``/``id``:

  1. if the slice's user-data is JSON with a string ``type``, that wins (and its ``id``);
  2. else the name convention ``<type>:<id>`` (the part before ``:`` is the type, after is
     the id) — unrecognized types fall back to ``"custom"`` (never an error);
  3. ``nine_slice`` (from Aseprite's 9-patch center rect) and ``pivot`` are emitted whenever
     the slice has them, independent of the type.

Pure-Python (no Aseprite, no IO). The MCP tool gathers the raw slice records and writes
the file; this module just shapes the data.
"""

from __future__ import annotations

import json

SCHEMA = "aseprite_mcp.slice_metadata.v1"

# Recognized semantic slice types (name-convention prefixes). Anything else -> "custom".
SUPPORTED_TYPES = (
    "hitbox", "hurtbox", "collision", "interact", "pivot", "origin",
    "attach", "spawn", "nine_slice", "custom",
)


def _parse_data(raw) -> tuple[object | None, str]:
    """Return (parsed_json_or_None, raw_string). Non-JSON data is kept only as the string."""
    raw_str = raw if isinstance(raw, str) else ""
    if not raw_str.strip():
        return None, raw_str
    try:
        return json.loads(raw_str), raw_str
    except (ValueError, TypeError):
        return None, raw_str


def _resolve_type_id(name: str, data_obj) -> tuple[str, str | None]:
    """Resolve (type, id): JSON data type wins, then the ``<type>:<id>`` name convention,
    then a ``"custom"`` fallback. Unknown names never raise."""
    if isinstance(data_obj, dict) and isinstance(data_obj.get("type"), str):
        data_id = data_obj.get("id")
        return data_obj["type"], (str(data_id) if data_id is not None else None)

    if ":" in name:
        prefix, id_part = name.split(":", 1)
        id_part = id_part or None
    else:
        prefix, id_part = name, None

    if prefix in SUPPORTED_TYPES:
        return prefix, id_part
    return "custom", id_part


def _slice_entry(raw: dict) -> dict:
    name = str(raw.get("name", ""))
    data_obj, raw_data = _parse_data(raw.get("data"))
    slice_type, slice_id = _resolve_type_id(name, data_obj)
    center = raw.get("center")
    pivot = raw.get("pivot")
    return {
        "name": name,
        "type": slice_type,
        "id": slice_id,
        "bounds": raw.get("bounds"),
        "pivot": pivot if pivot else None,
        "nine_slice": {"center": center} if center else None,
        "color": raw.get("color"),
        "data": data_obj,
        "raw_data": raw_data,
    }


def build_slice_metadata(*, sprite: str, width: int, height: int, slices: list[dict]) -> dict:
    """Build the ``aseprite_mcp.slice_metadata.v1`` document from raw Aseprite slice records.

    Each raw slice is ``{name, bounds, color, data, center?, pivot?}`` (center/pivot present
    only when the slice has a 9-patch / pivot).
    """
    return {
        "schema": SCHEMA,
        "source": {"sprite": sprite, "width": int(width), "height": int(height)},
        "slices": [_slice_entry(s) for s in (slices or [])],
    }
