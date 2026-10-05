"""Declarative asset specification - ``aseprite_mcp.asset_spec.v1``.

Lets an agent *describe* the asset it wants in one document instead of orchestrating
dozens of tool calls. This module is pure-Python (no Aseprite, no MCP):

  * ``validate_spec(spec)`` - is the document itself valid? Returns a structured report
    (the same {passed, checks, errors, warnings} shape as game-export validation).
  * ``plan_spec(spec)`` - the **pure inner step**: returns the ordered list of
    ``{tool, args, purpose}`` steps that a build would run, *without* launching Aseprite.

The build tool (``tools.asset_spec.build_asset_from_spec``) simply executes this plan by
dispatching each step to the existing workflow/batch/export tools. Build is **structure
only** - it creates canvas/layers/frames/tags/slices/palette and runs exports, and never
draws pixels; finished art is handed back to the agent.
"""

from __future__ import annotations

import json

from . import minecraft
from .errors import ValidationFailed
from .limits import (
    MAX_BATCH_OPERATIONS,
    MAX_COLOR_LIST_LENGTH,
    MAX_FRAMES_PER_DIRECTION,
    MAX_GRID_CELLS,
    MAX_SPEC_ANIMATION_FRAMES,
    MAX_SPEC_EXPORTS,
    MAX_SPEC_LAYERS,
    MAX_SPEC_SLICES,
    MAX_SPEC_TOTAL_FRAMES,
    check_canvas_size,
)
from .models import ColorSpec

SCHEMA = "aseprite_mcp.asset_spec.v1"

# Each kind maps to a real, deterministic executor (a workflow scaffold). A kind with no
# executor behind it would be a footgun - projectile/vfx/portrait are deferred to v2.
SPEC_KINDS = ("character", "enemy", "item_sheet", "icon_set", "tileset", "walk_8dir",
              "minecraft")
# Kinds whose canvas is given explicitly. The rest derive theirs - from cell size and grid
# for the sheet kinds, from texture_size for minecraft.
CANVAS_KINDS = ("character", "enemy", "walk_8dir")
COLOR_MODES = ("rgb", "indexed", "gray")
EXPORT_FORMATS = ("godot_spriteframes", "slice_metadata", "gif", "spritesheet", "png",
                  "minecraft_texture")
# Exports that only make sense for one kind, so a spec cannot ask for a Godot resource
# from a Minecraft texture (or the reverse) and discover it as a runtime dispatch error.
_KIND_ONLY_EXPORTS = {"minecraft_texture": "minecraft"}

# Layers a kind's scaffold already creates (so spec layers don't duplicate them).
_DEFAULT_LAYERS = {"character": ("body", "details"), "enemy": ("body", "details")}



def sprite_filename(name: str) -> str:
    """The sprite file a spec's ``name`` builds into.

    ``name`` is caller-supplied text with no stated extension rule, so writing
    ``"hero.aseprite"`` is the obvious thing to do. The workflow scaffolds that create the
    file already tolerate it (``tools.workflow._aseprite_name``), so the plan has to agree:
    appending unconditionally created ``hero.aseprite`` in step one and then targeted
    ``hero.aseprite.aseprite`` in every step after it, failing on a missing sprite once the
    file was already on disk. Keep this in step with ``_aseprite_name``.
    """
    return name if name.lower().endswith((".aseprite", ".ase")) else f"{name}.aseprite"


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
        # `detail` describes the FAILURE, so carrying it on a passing check makes a clean
        # report read like a list of problems ("ok": true beside "is not a valid resource
        # path"). Emit it only when it is true.
        # bool(ok) rather than ok: several call sites pass an `isinstance(...) and
        # x.strip()` expression, whose truthy branch is the string, not True. Coercing
        # here makes the report shape correct for every caller instead of relying on each
        # one to wrap its own condition, which is how two of them came to leak strings.
        checks.append({"name": name, "ok": bool(ok), "level": level,
                       "detail": "" if ok else detail})
        if not ok:
            (errors if level == "error" else warnings).append(detail or name)
        return bool(ok)

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
    _check_exports(spec, kind, check)
    _check_planned_work(spec, kind, check)

    return {"passed": len(errors) == 0, "checks": checks, "errors": errors, "warnings": warnings}


def _is_pos_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _check_canvas(spec, kind, check) -> None:
    canvas = spec.get("canvas")
    if kind in CANVAS_KINDS:
        if not check("canvas", isinstance(canvas, dict), "error",
                     f"kind '{kind}' requires a 'canvas' {{width, height, color_mode}}."):
            return
        problem = _canvas_problem(canvas.get("width"), canvas.get("height"))
        check("canvas.size", problem is None, "error", problem or "")
        mode = canvas.get("color_mode", "rgb")
        check("canvas.color_mode", mode in COLOR_MODES, "error",
              f"canvas.color_mode must be one of {list(COLOR_MODES)} (got {mode!r}).")
    elif canvas is not None:
        derived_from = "texture_size" if kind == "minecraft" else "cell size/grid"
        check("canvas.derived", False, "warning",
              f"kind '{kind}' derives its canvas from {derived_from}; 'canvas' is ignored.")


def _canvas_problem(width, height) -> str | None:
    """Why the build would refuse this canvas, or None if it would accept it.

    The ceiling is asked of ``check_canvas_size``, the same guard the build path runs,
    rather than restated here: the spec layer used to carry its own 65535 and so passed a
    canvas the builder then rejected, and a validator that accepts what the build refuses
    is worse than no validator. The type test stays local because ``check_canvas_size``
    coerces its arguments, and ``"32"`` is not a canvas width in a spec document.
    """
    if not (_is_pos_int(width) and _is_pos_int(height)):
        return "canvas width/height must be positive integers."
    try:
        check_canvas_size(width, height)
    except ValidationFailed as exc:
        return str(exc)
    return None


def _check_kind_fields(spec, kind, check) -> None:
    # Where a spec field feeds a capped tool argument, the ceiling is asked of the same
    # constant the tool enforces. A positive-integer check alone let a spec validate and
    # then fail inside the scaffold, after the sprite had already been created: the
    # validator has to know every limit the build will hit, or it is not a pre-flight.
    if kind == "icon_set":
        check("icon_set.icon_size", _is_pos_int(spec.get("icon_size")), "error",
              "icon_set requires a positive integer 'icon_size'.")
        count = spec.get("count")
        if check("icon_set.count", _is_pos_int(count), "error",
                 "icon_set requires a positive integer 'count'."):
            check("icon_set.count.max", count <= MAX_GRID_CELLS, "error",
                  f"icon_set 'count' is {count}; maximum is {MAX_GRID_CELLS}. Each icon is "
                  "a placeholder plus a named slice in the scaffold.")
    elif kind == "item_sheet":
        check("item_sheet.item_size", _is_pos_int(spec.get("item_size")), "error",
              "item_sheet requires a positive integer 'item_size'.")
    elif kind == "tileset":
        for field in ("tile_size", "columns", "rows"):
            check(f"tileset.{field}", _is_pos_int(spec.get(field)), "error",
                  f"tileset requires a positive integer '{field}'.")
        cols, rows = spec.get("columns"), spec.get("rows")
        if _is_pos_int(cols) and _is_pos_int(rows):
            check("tileset.cells", cols * rows <= MAX_GRID_CELLS, "error",
                  f"tileset is {cols}x{rows} = {cols * rows} cells; maximum is "
                  f"{MAX_GRID_CELLS}. Two individually legal axes still multiply.")
    elif kind == "walk_8dir":
        fpd = spec.get("frames_per_direction")
        if fpd is not None and check(
            "walk_8dir.frames_per_direction", _is_pos_int(fpd), "error",
            "frames_per_direction must be a positive integer.",
        ):
            check("walk_8dir.frames_per_direction.max", fpd <= MAX_FRAMES_PER_DIRECTION,
                  "error",
                  f"'frames_per_direction' is {fpd}; maximum is {MAX_FRAMES_PER_DIRECTION}.")
    elif kind == "minecraft":
        minecraft.validate_fields(spec, check)


def _check_palette(spec, check) -> None:
    palette = spec.get("palette")
    if palette is None:
        return
    if not check("palette.type", isinstance(palette, list), "error", "'palette' must be a list."):
        return
    check("palette.size", len(palette) <= MAX_COLOR_LIST_LENGTH, "error",
          f"palette has {len(palette)} colours; maximum is {MAX_COLOR_LIST_LENGTH}.")
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
    if not check("layers", ok, "error", "'layers' must be a list of non-empty strings."):
        return
    check("layers.count", len(layers) <= MAX_SPEC_LAYERS, "error",
          f"'layers' has {len(layers)} entries; maximum is {MAX_SPEC_LAYERS}. Each one is a "
          "layer in every frame of the sprite.")


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
    total = 0
    for i, a in enumerate(anims):
        if not isinstance(a, dict):
            check(f"animations[{i}]", False, "error", f"animation {i} must be an object.")
            continue
        check(f"animations[{i}].name", bool(isinstance(a.get("name"), str) and a["name"].strip()),
              "error", f"animation {i} needs a non-empty 'name'.")
        count = a.get("frame_count")
        if check(f"animations[{i}].frame_count", _is_pos_int(count), "error",
                 f"animation {i} needs a positive integer 'frame_count'."):
            total += count
            check(f"animations[{i}].frame_count.max", count <= MAX_SPEC_ANIMATION_FRAMES, "error",
                  f"animation {i} 'frame_count' is {count}; maximum is {MAX_SPEC_ANIMATION_FRAMES}. "
                  "Split a longer sequence across its own sprite.")
        if "frames" in a:
            check(f"animations[{i}].frames", False, "warning",
                  "use 'frame_count' (a count), not 'frames' - 'frames' is ignored.")
        dur = a.get("duration_ms")
        if dur is not None:
            check(f"animations[{i}].duration_ms", _is_pos_int(dur), "error",
                  f"animation {i} 'duration_ms' must be a positive integer.")
    # The per-animation cap does not bound the sprite: every animation's frames land in the
    # same file, so twenty legal animations still add up to one unreasonable timeline.
    if total:
        check("animations.total_frames", total <= MAX_SPEC_TOTAL_FRAMES, "error",
              f"'animations' frame_count totals {total} frames; maximum is "
              f"{MAX_SPEC_TOTAL_FRAMES} for one sprite. Split the animations across sprites.")


def _check_slices(spec, check) -> None:
    slices = spec.get("slices")
    if slices is None:
        return
    if not check("slices.type", isinstance(slices, list), "error", "'slices' must be a list."):
        return
    if not check("slices.count", len(slices) <= MAX_SPEC_SLICES, "error",
                 f"'slices' has {len(slices)} entries; maximum is {MAX_SPEC_SLICES}. Each one is "
                 "a separate Aseprite launch at build time."):
        return
    for i, sl in enumerate(slices):
        if not isinstance(sl, dict):
            check(f"slices[{i}]", False, "error", f"slice {i} must be an object.")
            continue
        check(f"slices[{i}].name", bool(isinstance(sl.get("name"), str) and sl["name"].strip()),
              "error", f"slice {i} needs a non-empty 'name'.")
        b = sl.get("bounds")
        ok = isinstance(b, dict) and all(isinstance(b.get(k), int) and not isinstance(b.get(k), bool)
                                         for k in ("x", "y", "width", "height"))
        check(f"slices[{i}].bounds", ok, "error",
              f"slice {i} needs integer bounds {{x, y, width, height}}.")


def _check_exports(spec, kind, check) -> None:
    exports = spec.get("exports")
    if exports is None:
        return
    if not check("exports.type", isinstance(exports, list), "error", "'exports' must be a list."):
        return
    if not check("exports.count", len(exports) <= MAX_SPEC_EXPORTS, "error",
                 f"'exports' has {len(exports)} entries; maximum is {MAX_SPEC_EXPORTS}. Each one is "
                 "a separate Aseprite launch at build time."):
        return
    for i, e in enumerate(exports):
        fmt = e.get("format") if isinstance(e, dict) else None
        if not check(f"exports[{i}].format", fmt in EXPORT_FORMATS, "error",
                     f"export {i} 'format' must be one of {list(EXPORT_FORMATS)} (got {fmt!r})."):
            continue
        required_kind = _KIND_ONLY_EXPORTS.get(fmt)
        check(f"exports[{i}].kind", required_kind is None or required_kind == kind, "error",
              f"export format {fmt!r} is only valid for kind '{required_kind}' (this spec is "
              f"kind '{kind}').")
        if kind == "minecraft" and fmt == "minecraft_texture":
            root = e.get("pack_root")
            check(f"exports[{i}].pack_root", isinstance(root, str) and root.strip() != "",
                  "error",
                  f"export {i} needs a 'pack_root' - the resource-pack directory the "
                  "assets/ tree is written under.")


def _frame_counts(spec: dict, kind: str) -> list[int]:
    """The per-animation frame counts this spec's plan would expand into frames.

    Malformed entries are left out rather than coerced: the per-field checks already report
    them, and counting them here would either raise or repeat the same complaint.
    """
    if kind == "minecraft":
        anim = spec.get("animation")
        frames = anim.get("frames") if isinstance(anim, dict) else None
        return [frames] if _is_pos_int(frames) else []
    if kind not in ("character", "enemy"):
        return []                       # other kinds get their frames from their own scaffold
    return [a["frame_count"] for a in (spec.get("animations") or [])
            if isinstance(a, dict) and _is_pos_int(a.get("frame_count"))]


def _planned_operation_count(spec: dict, kind: str) -> int:
    """How many structural operations ``plan_spec`` would emit for ``spec``.

    Arithmetic rather than ``len(_layer_and_animation_ops(spec, kind))`` on purpose: the
    whole point is to refuse an oversized spec before anything expands, and materialising
    400,000 operations to discover there are too many of them is the defect being guarded
    against. ``test_asset_spec`` asserts this stays equal to the real operation list, so the
    two cannot drift apart unnoticed.
    """
    layers = [name for name in (spec.get("layers") or []) if isinstance(name, str)]
    counts = _frame_counts(spec, kind)
    frames = sum(counts)
    if kind == "minecraft":
        # One rename of the generic first layer, then one add_layer per extra layer; then one
        # add_frame per frame after the first, one duration for frame 1, and one tag.
        return max(1, len(layers)) + (frames + 1 if frames else 0)
    defaults = _DEFAULT_LAYERS.get(kind, ())
    ops = len([name for name in layers if name not in defaults])
    if frames:
        # Frame 1 already exists; every frame gets a duration, every animation a tag.
        ops += (frames - 1) + frames + len(counts)
    return ops


def _check_planned_work(spec, kind, check) -> None:
    """Refuse a spec whose *plan* would not fit the one structural batch a build sends.

    Every field can be individually legal and the total still blow ``MAX_BATCH_OPERATIONS``,
    because layers, frames, durations and tags all go out as a single ``apply_operations``
    call. That used to surface from inside the batch layer *after* the sprite and the palette
    had been written, quoting a batch size the caller never chose and leaving a sprite with no
    manifest behind. The count is knowable here, before anything exists.
    """
    count = _planned_operation_count(spec, kind)
    frames = sum(_frame_counts(spec, kind))
    field = "animation.frames" if kind == "minecraft" else "animations[].frame_count"
    check("plan.operations", count <= MAX_BATCH_OPERATIONS, "error",
          f"this spec plans {count} structural operations; a build applies them in one batch "
          f"of at most {MAX_BATCH_OPERATIONS}. Reduce {field} ({frames} frame(s) planned) or "
          f"'layers'.")


# --------------------------------------------------------------------------- #
# Planning (pure)                                                             #
# --------------------------------------------------------------------------- #
def _step(tool: str, args: dict, purpose: str) -> dict:
    return {"tool": tool, "args": args, "purpose": purpose}


def plan_spec(spec: dict) -> list[dict]:
    """Return the ordered build steps for ``spec`` - pure, launches nothing.

    Each step is ``{tool, args, purpose}`` naming an existing MCP tool; the build executor
    dispatches them in order. No drawing tools are ever emitted (structure only).
    """
    kind = spec["kind"]
    name = spec["name"]
    fname = sprite_filename(name)
    canvas = spec.get("canvas") or {}
    width = int(canvas.get("width", 32))
    height = int(canvas.get("height", 32))

    steps: list[dict] = []

    # 1) base sprite - delegate to the kind's scaffold (no placeholder art for character).
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
    elif kind == "minecraft":
        # One Aseprite frame per Minecraft animation frame, at the texture's own size.
        # The vertical strip the game wants is produced at export time, not authored by
        # hand - a hand-built 16x128 canvas cannot be previewed as an animation, and gets
        # its frame boundaries wrong the moment the frame count changes.
        size = int(spec.get("texture_size", 16))
        steps.append(_step("create_sprite", {
            "filename": fname, "width": size, "height": size, "color_mode": "rgb",
        }, f"{size}x{size} RGBA texture canvas"))

    # 2) palette override (structure, not pixels).
    if spec.get("palette"):
        steps.append(_step("set_palette", {"filename": fname, "colors": list(spec["palette"])},
                           "apply the spec palette"))

    # 3) structural batch: extra layers + animation frames/tags (atomic, no pixels).
    ops = _layer_and_animation_ops(spec, kind)
    if ops:
        steps.append(_step("apply_operations", {"filename": fname, "operations": ops},
                           "structural layers / frames / tags (atomic)"))

    # 4) slices - full-fidelity tool (carries 9-slice center, pivot, type/id via data).
    for sl in spec.get("slices", []):
        steps.append(_slice_step(fname, sl))

    # 5) exports.
    for exp in spec.get("exports", []):
        steps.append(_export_step(fname, name, exp, spec))

    return steps


def _layer_and_animation_ops(spec: dict, kind: str) -> list[dict]:
    if kind == "minecraft":
        return _minecraft_layer_ops(spec) + _minecraft_frame_ops(spec)

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


# The layer `create_sprite` leaves behind. Unlike the character/enemy scaffolds, which
# name their layers, the generic sprite tool produces a single "Layer 1" - a name this
# project's own game-export validation flags as suspicious. It is renamed rather than
# left beside the spec's layers, so a spec asking for two layers gets two.
_GENERIC_FIRST_LAYER = "Layer 1"


def _minecraft_layer_ops(spec: dict) -> list[dict]:
    layers = list(spec.get("layers") or [])
    first = layers[0] if layers else "texture"
    ops: list[dict] = [{"op": "rename_layer",
                        "args": {"layer": _GENERIC_FIRST_LAYER, "new_name": first}}]
    ops += [{"op": "add_layer", "args": {"name": name}} for name in layers[1:]]
    return ops


def _minecraft_frame_ops(spec: dict) -> list[dict]:
    """Frames + timing for an animated Minecraft texture.

    Frame durations are set from `frametime` so the Aseprite timeline previews at the
    speed the game will actually play - the sidecar counts ticks, Aseprite counts
    milliseconds, and an un-converted timeline is a preview of the wrong animation.
    """
    anim = spec.get("animation")
    if not anim:
        return []
    frames = int(anim["frames"])
    duration = int(anim.get("frametime", 1)) * minecraft.MS_PER_TICK
    ops: list[dict] = [{"op": "add_frame", "args": {"duration_ms": duration}}
                       for _ in range(frames - 1)]  # frame 1 already exists
    ops.append({"op": "set_frame_duration", "args": {"frame": 1, "duration_ms": duration}})
    ops.append({"op": "add_tag", "args": {
        "name": spec["name"].rsplit("/", 1)[-1], "from": 1, "to": frames, "direction": "forward",
    }})
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


def _export_step(fname: str, name: str, exp: dict, spec: dict) -> dict:
    fmt = exp["format"]
    scale = int(exp.get("scale", 1))
    if fmt == "minecraft_texture":
        anim = spec.get("animation")
        args = {
            "filename": fname,
            "pack_root": exp["pack_root"],
            "namespace": spec.get("namespace", "minecraft"),
            "category": spec["category"],
            "texture_name": name,
        }
        if anim:
            args["frametime"] = int(anim.get("frametime", 1))
            args["interpolate"] = bool(anim.get("interpolate", False))
            if anim.get("frame_order"):
                args["frame_order"] = list(anim["frame_order"])
        purpose = (
            f"{minecraft.texture_rel_path(args['namespace'], args['category'], name)}"
            + (" + .png.mcmeta (vertical frame strip)" if anim else "")
        )
        return _step("export_minecraft_texture", args, purpose)
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


# ============================================================ the loop closer
# `validate_spec` asks whether a document is well formed and `plan_spec` asks what it
# would do. Neither asks the question that actually bites: **did the thing that got built
# match what was asked for?**
#
# That gap is not theoretical. In one session a figure shipped with no keyline at all
# because `add_outline` was pointed at an empty layer, and every count in the result
# reported success; three ramps clipped to pure black and beat their own outline while
# passing every check that existed; a measured report claimed a 2.33:1 waist on a figure
# whose waist measured 1.64:1. In each case the declaration and the artifact disagreed and
# nothing was watching the gap.
#
# This is deliberately structure-only, for the same reason `build_asset_from_spec` is:
# the spec layer declares canvas, layers, frames, tags, slices, palette and exports, and
# says nothing about pixels. A pixel-level counterpart belongs with `quality` and `craft`,
# which already have the measurements for it.


def _layer_names(observed: dict) -> list[str]:
    """Every layer name in the observed tree, groups and children alike."""
    found: list[str] = []

    def walk(nodes) -> None:
        for node in nodes or ():
            if isinstance(node, dict):
                name = node.get("name")
                if isinstance(name, str):
                    found.append(name)
                walk(node.get("layers"))

    walk(observed.get("layers"))
    return found


def compare_to_built(spec: dict, observed: dict) -> dict:
    """Does a built sprite match the spec it was built from.

    Pure, so it is testable without launching Aseprite: `observed` is whatever
    `get_sprite_info` returned. That split is the same one `plan_spec` keeps, and for the
    same reason, which is that the interesting logic should not need an editor to exercise.

    Reports every field it checked, not only the ones that failed, because "nothing was
    reported" and "nothing was checked" look identical otherwise and that is precisely the
    failure this exists to stop.
    """
    mismatches: list[dict] = []
    checked: list[str] = []

    def note(field: str, declared, actual, detail: str) -> None:
        mismatches.append({"field": field, "declared": declared,
                           "observed": actual, "detail": detail})

    canvas = spec.get("canvas") or {}
    if isinstance(canvas, dict) and canvas.get("width") and canvas.get("height"):
        checked.append("canvas")
        if (observed.get("width"), observed.get("height")) != (canvas["width"],
                                                               canvas["height"]):
            note("canvas", f"{canvas['width']}x{canvas['height']}",
                 f"{observed.get('width')}x{observed.get('height')}",
                 "the sprite is not the size the spec declared")

    declared_layers = [n for n in (spec.get("layers") or []) if isinstance(n, str)]
    if declared_layers:
        checked.append("layers")
        present = set(_layer_names(observed))
        missing = [n for n in declared_layers if n not in present]
        if missing:
            note("layers", declared_layers, sorted(present),
                 f"declared layer(s) not in the sprite: {', '.join(missing)}")

    anims = [a for a in (spec.get("animations") or []) if isinstance(a, dict)]
    if anims:
        checked.append("animations")
        want = sum(a.get("frame_count", 0) for a in anims)
        got = len(observed.get("frames") or ())
        if want and got < want:
            note("animations", f"{want} frame(s)", f"{got} frame(s)",
                 "the sprite has fewer frames than the animations declare")
        tags = {t.get("name") for t in (observed.get("tags") or ())
                if isinstance(t, dict)}
        absent = [a["name"] for a in anims
                  if isinstance(a.get("name"), str) and a["name"] not in tags]
        if absent:
            note("tags", [a.get("name") for a in anims], sorted(n for n in tags if n),
                 f"declared animation(s) with no tag: {', '.join(absent)}")

    slices = [s for s in (spec.get("slices") or []) if isinstance(s, dict)]
    if slices:
        checked.append("slices")
        have = {s.get("name") for s in (observed.get("slices") or ())
                if isinstance(s, dict)}
        absent = [s["name"] for s in slices
                  if isinstance(s.get("name"), str) and s["name"] not in have]
        if absent:
            note("slices", [s.get("name") for s in slices],
                 sorted(n for n in have if n),
                 f"declared slice(s) not in the sprite: {', '.join(absent)}")

    declared_palette = [c for c in (spec.get("palette") or []) if isinstance(c, str)]
    if declared_palette and observed.get("palette") is not None:
        checked.append("palette")
        size = observed.get("palette")
        size = size.get("size") if isinstance(size, dict) else size
        if isinstance(size, int) and size < len(declared_palette):
            note("palette", f"{len(declared_palette)} colour(s)", f"{size} entries",
                 "the palette holds fewer entries than the spec declares, so some "
                 "declared colours cannot be on it")

    return {
        "ok": not mismatches,
        "checked": checked,
        "mismatches": mismatches,
        # Said explicitly, because a spec that declares nothing verifiable would otherwise
        # come back clean and look like a passing check rather than an absent one.
        "verifiable": bool(checked),
    }
