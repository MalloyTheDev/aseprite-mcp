"""Declarative asset specification — ``aseprite_mcp.asset_spec.v1``.

Lets an agent *describe* the asset it wants in one document instead of orchestrating
dozens of tool calls. This module is pure-Python (no Aseprite, no MCP):

  * ``validate_spec(spec)`` — is the document itself valid? Returns a structured report
    (the same {passed, checks, errors, warnings} shape as game-export validation).
  * ``plan_spec(spec)`` — the **pure inner step**: returns the ordered list of
    ``{tool, args, purpose}`` steps that a build would run, *without* launching Aseprite.

The build tool (``tools.asset_spec.build_asset_from_spec``) simply executes this plan by
dispatching each step to the existing workflow/batch/export tools. Build is **structure
only** — it creates canvas/layers/frames/tags/slices/palette and runs exports, and never
draws pixels; finished art is handed back to the agent.
"""

from __future__ import annotations

import json

from .models import ColorSpec

SCHEMA = "aseprite_mcp.asset_spec.v1"

# Each kind maps to a real, deterministic executor (a workflow scaffold). A kind with no
# executor behind it would be a footgun — projectile/vfx/portrait are deferred to v2.
SPEC_KINDS = ("character", "enemy", "item_sheet", "icon_set", "tileset", "walk_8dir")
# Kinds whose canvas is given explicitly (the grid kinds derive their canvas from cells).
CANVAS_KINDS = ("character", "enemy", "walk_8dir")
COLOR_MODES = ("rgb", "indexed", "gray")
EXPORT_FORMATS = ("godot_spriteframes", "slice_metadata", "gif", "spritesheet", "png")

# Layers a kind's scaffold already creates (so spec layers don't duplicate them).
_DEFAULT_LAYERS = {"character": ("body", "details"), "enemy": ("body", "details")}

_MAX_PALETTE = 256


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #
def validate_spec(spec) -> dict:
    """Validate an asset-spec document. Returns {passed, checks, errors, warnings}.

    ``passed`` is True iff no error-level problem was found (warnings never fail).
    """
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, level: str, detail: str = "") -> bool:
        checks.append({"name": name, "ok": ok, "level": level, "detail": detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)
        return ok

    if not isinstance(spec, dict):
        check("type", False, "error", "spec must be an object.")
        return {"passed": False, "checks": checks, "errors": errors, "warnings": warnings}

    schema = spec.get("schema")
    if schema is None:
        check("schema", False, "warning", "no 'schema' field; assuming aseprite_mcp.asset_spec.v1")
    else:
        check("schema", schema == SCHEMA, "error", f"unknown schema {schema!r}; expected {SCHEMA!r}")

    name = spec.get("name")
    check("name", isinstance(name, str) and name.strip() != "", "error",
          "'name' is required and must be a non-empty string.")

    kind = spec.get("kind")
    if not check("kind", kind in SPEC_KINDS, "error",
                 f"'kind' must be one of {list(SPEC_KINDS)} (got {kind!r})."):
        return {"passed": False, "checks": checks, "errors": errors, "warnings": warnings}

    _check_canvas(spec, kind, check)
    _check_kind_fields(spec, kind, check)
    _check_palette(spec, check)
    _check_layers(spec, check)
    _check_animations(spec, kind, check)
    _check_slices(spec, check)
    _check_exports(spec, check)

    return {"passed": len(errors) == 0, "checks": checks, "errors": errors, "warnings": warnings}


def _is_pos_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _check_canvas(spec, kind, check) -> None:
    canvas = spec.get("canvas")
    if kind in CANVAS_KINDS:
        if not check("canvas", isinstance(canvas, dict), "error",
                     f"kind '{kind}' requires a 'canvas' {{width, height, color_mode}}."):
            return
        w, h = canvas.get("width"), canvas.get("height")
        check("canvas.size", _is_pos_int(w) and _is_pos_int(h) and w <= 65535 and h <= 65535,
              "error", "canvas width/height must be integers in 1..65535.")
        mode = canvas.get("color_mode", "rgb")
        check("canvas.color_mode", mode in COLOR_MODES, "error",
              f"canvas.color_mode must be one of {list(COLOR_MODES)} (got {mode!r}).")
    elif canvas is not None:
        check("canvas.derived", False, "warning",
              f"kind '{kind}' derives its canvas from cell size/grid; 'canvas' is ignored.")


def _check_kind_fields(spec, kind, check) -> None:
    if kind == "icon_set":
        check("icon_set.icon_size", _is_pos_int(spec.get("icon_size")), "error",
              "icon_set requires a positive integer 'icon_size'.")
        check("icon_set.count", _is_pos_int(spec.get("count")), "error",
              "icon_set requires a positive integer 'count'.")
    elif kind == "item_sheet":
        check("item_sheet.item_size", _is_pos_int(spec.get("item_size")), "error",
              "item_sheet requires a positive integer 'item_size'.")
    elif kind == "tileset":
        for field in ("tile_size", "columns", "rows"):
            check(f"tileset.{field}", _is_pos_int(spec.get(field)), "error",
                  f"tileset requires a positive integer '{field}'.")
    elif kind == "walk_8dir":
        fpd = spec.get("frames_per_direction")
        if fpd is not None:
            check("walk_8dir.frames_per_direction", _is_pos_int(fpd), "error",
                  "frames_per_direction must be a positive integer.")


def _check_palette(spec, check) -> None:
    palette = spec.get("palette")
    if palette is None:
        return
    if not check("palette.type", isinstance(palette, list), "error", "'palette' must be a list."):
        return
    check("palette.size", len(palette) <= _MAX_PALETTE, "error",
          f"palette has {len(palette)} colours; maximum is {_MAX_PALETTE}.")
    bad = []
    for c in palette:
        try:
            ColorSpec.parse(c)
        except (ValueError, TypeError):
            bad.append(c)
    check("palette.colors", not bad, "error", f"unparseable palette colours: {bad}")


def _check_layers(spec, check) -> None:
    layers = spec.get("layers")
    if layers is None:
        return
    ok = isinstance(layers, list) and all(isinstance(s, str) and s.strip() for s in layers)
    check("layers", ok, "error", "'layers' must be a list of non-empty strings.")


def _check_animations(spec, kind, check) -> None:
    anims = spec.get("animations")
    if anims is None:
        return
    if not check("animations.type", isinstance(anims, list), "error",
                 "'animations' must be a list."):
        return
    if anims and kind not in ("character", "enemy"):
        check("animations.kind", False, "warning",
              f"kind '{kind}' defines its own frames/tags; 'animations' is ignored.")
    for i, a in enumerate(anims):
        if not isinstance(a, dict):
            check(f"animations[{i}]", False, "error", f"animation {i} must be an object.")
            continue
        check(f"animations[{i}].name", isinstance(a.get("name"), str) and a["name"].strip(),
              "error", f"animation {i} needs a non-empty 'name'.")
        check(f"animations[{i}].frame_count", _is_pos_int(a.get("frame_count")), "error",
              f"animation {i} needs a positive integer 'frame_count'.")
        if "frames" in a:
            check(f"animations[{i}].frames", False, "warning",
                  "use 'frame_count' (a count), not 'frames' — 'frames' is ignored.")
        dur = a.get("duration_ms")
        if dur is not None:
            check(f"animations[{i}].duration_ms", _is_pos_int(dur), "error",
                  f"animation {i} 'duration_ms' must be a positive integer.")


def _check_slices(spec, check) -> None:
    slices = spec.get("slices")
    if slices is None:
        return
    if not check("slices.type", isinstance(slices, list), "error", "'slices' must be a list."):
        return
    for i, sl in enumerate(slices):
        if not isinstance(sl, dict):
            check(f"slices[{i}]", False, "error", f"slice {i} must be an object.")
            continue
        check(f"slices[{i}].name", isinstance(sl.get("name"), str) and sl["name"].strip(),
              "error", f"slice {i} needs a non-empty 'name'.")
        b = sl.get("bounds")
        ok = isinstance(b, dict) and all(isinstance(b.get(k), int) and not isinstance(b.get(k), bool)
                                         for k in ("x", "y", "width", "height"))
        check(f"slices[{i}].bounds", ok, "error",
              f"slice {i} needs integer bounds {{x, y, width, height}}.")


def _check_exports(spec, check) -> None:
    exports = spec.get("exports")
    if exports is None:
        return
    if not check("exports.type", isinstance(exports, list), "error", "'exports' must be a list."):
        return
    for i, e in enumerate(exports):
        fmt = e.get("format") if isinstance(e, dict) else None
        check(f"exports[{i}].format", fmt in EXPORT_FORMATS, "error",
              f"export {i} 'format' must be one of {list(EXPORT_FORMATS)} (got {fmt!r}).")


# --------------------------------------------------------------------------- #
# Planning (pure)                                                             #
# --------------------------------------------------------------------------- #
def _step(tool: str, args: dict, purpose: str) -> dict:
    return {"tool": tool, "args": args, "purpose": purpose}


def plan_spec(spec: dict) -> list[dict]:
    """Return the ordered build steps for ``spec`` — pure, launches nothing.

    Each step is ``{tool, args, purpose}`` naming an existing MCP tool; the build executor
    dispatches them in order. No drawing tools are ever emitted (structure only).
    """
    kind = spec["kind"]
    name = spec["name"]
    fname = f"{name}.aseprite"
    canvas = spec.get("canvas") or {}
    width = int(canvas.get("width", 32))
    height = int(canvas.get("height", 32))

    steps: list[dict] = []

    # 1) base sprite — delegate to the kind's scaffold (no placeholder art for character).
    if kind in ("character", "enemy"):
        steps.append(_step("create_character_sprite", {
            "name": name, "width": width, "height": height,
            "base_color": spec.get("base_color", "#c83737" if kind == "enemy" else "#3878c8"),
            "with_placeholder": False,
        }, f"scaffold {kind} base: canvas + body/details layers + palette ramp (no art)"))
    elif kind == "walk_8dir":
        steps.append(_step("create_character_sprite", {
            "name": name, "width": width, "height": height, "with_placeholder": False,
        }, "scaffold base sprite (no art)"))
        steps.append(_step("make_8_direction_walk_template", {
            "filename": fname, "frames_per_direction": int(spec.get("frames_per_direction", 4)),
        }, "8-direction frames + one tag per direction"))
    elif kind == "icon_set":
        steps.append(_step("create_icon_set", {
            "name": name, "icon_size": int(spec["icon_size"]),
            "count": int(spec["count"]), "columns": spec.get("columns"),
        }, "icon grid + named slices (placeholder cells to draw over)"))
    elif kind == "item_sheet":
        steps.append(_step("create_rpg_item_sheet", {
            "name": name, "item_size": int(spec["item_size"]),
            "items": spec.get("items"), "columns": spec.get("columns"),
        }, "item grid + named slices (placeholder cells to draw over)"))
    elif kind == "tileset":
        steps.append(_step("create_tileset_project", {
            "name": name, "tile_size": int(spec["tile_size"]),
            "columns": int(spec["columns"]), "rows": int(spec["rows"]),
            "tiles": spec.get("tiles"),
        }, "tilemap layer + starter tileset"))

    # 2) palette override (structure, not pixels).
    if spec.get("palette"):
        steps.append(_step("set_palette", {"filename": fname, "colors": list(spec["palette"])},
                           "apply the spec palette"))

    # 3) structural batch: extra layers + animation frames/tags (atomic, no pixels).
    ops = _layer_and_animation_ops(spec, kind)
    if ops:
        steps.append(_step("apply_operations", {"filename": fname, "operations": ops},
                           "structural layers / frames / tags (atomic)"))

    # 4) slices — full-fidelity tool (carries 9-slice center, pivot, type/id via data).
    for sl in spec.get("slices", []):
        steps.append(_slice_step(fname, sl))

    # 5) exports.
    for exp in spec.get("exports", []):
        steps.append(_export_step(fname, name, exp))

    return steps


def _layer_and_animation_ops(spec: dict, kind: str) -> list[dict]:
    ops: list[dict] = []
    defaults = _DEFAULT_LAYERS.get(kind, ())
    for layer in spec.get("layers", []):
        if layer not in defaults:
            ops.append({"op": "add_layer", "args": {"name": layer}})

    anims = spec.get("animations") or []
    if anims and kind in ("character", "enemy"):
        total = sum(int(a["frame_count"]) for a in anims)
        for _ in range(max(0, total - 1)):  # frame 1 already exists
            ops.append({"op": "add_frame", "args": {}})
        frame = 1
        for a in anims:
            count = int(a["frame_count"])
            duration = int(a.get("duration_ms", 100))
            for f in range(frame, frame + count):
                ops.append({"op": "set_frame_duration", "args": {"frame": f, "duration_ms": duration}})
            ops.append({"op": "add_tag", "args": {
                "name": a["name"], "from": frame, "to": frame + count - 1,
                "direction": a.get("direction", "forward"),
            }})
            frame += count
    return ops


def _slice_data_string(sl: dict) -> str | None:
    """Encode type/id into the slice's data so export_slice_metadata round-trips them."""
    data = sl.get("data")
    obj = dict(data) if isinstance(data, dict) else {}
    if sl.get("type") and "type" not in obj:
        obj["type"] = sl["type"]
    if sl.get("id") is not None and "id" not in obj:
        obj["id"] = sl["id"]
    if obj:
        return json.dumps(obj)
    return data if isinstance(data, str) and data else None


def _slice_step(fname: str, sl: dict) -> dict:
    b = sl["bounds"]
    args: dict = {"filename": fname, "name": sl["name"],
                  "x": int(b["x"]), "y": int(b["y"]),
                  "width": int(b["width"]), "height": int(b["height"])}
    center = (sl.get("nine_slice") or {}).get("center") or sl.get("center")
    if center:
        args.update(center_x=int(center["x"]), center_y=int(center["y"]),
                    center_width=int(center["width"]), center_height=int(center["height"]))
    pivot = sl.get("pivot")
    if pivot:
        args.update(pivot_x=int(pivot["x"]), pivot_y=int(pivot["y"]))
    if sl.get("color"):
        args["color"] = sl["color"]
    data_str = _slice_data_string(sl)
    if data_str is not None:
        args["data"] = data_str
    return _step("add_slice", args, f"slice '{sl['name']}'")


def _export_step(fname: str, name: str, exp: dict) -> dict:
    fmt = exp["format"]
    scale = int(exp.get("scale", 1))
    if fmt == "godot_spriteframes":
        return _step("export_godot_spriteframes",
                     {"filename": fname, "output": exp.get("output", f"{name}.tres"), "scale": scale},
                     "Godot 4 SpriteFrames resource")
    if fmt == "slice_metadata":
        return _step("export_slice_metadata",
                     {"filename": fname, "output": exp.get("output", f"{name}_slices.json")},
                     "engine-agnostic slice metadata")
    if fmt == "gif":
        return _step("export_gif",
                     {"filename": fname, "output": exp.get("output", f"{name}.gif"), "scale": scale},
                     "animated GIF")
    if fmt == "spritesheet":
        return _step("export_spritesheet",
                     {"filename": fname, "output": exp.get("output", f"{name}_sheet.png"),
                      "data_output": exp.get("data_output", f"{name}_sheet.json")},
                     "packed sprite sheet + JSON")
    if fmt == "png":
        return _step("export_png",
                     {"filename": fname, "output": exp.get("output", f"{name}.png"), "scale": scale},
                     "flattened PNG")
    raise ValueError(f"unknown export format: {fmt!r}")
