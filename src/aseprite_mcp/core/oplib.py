"""Batch operation registry + one-script Lua assembler.

Pure-Python (no Aseprite): validates a list of `{"op": str, "args": {...}}` operations
against a curated registry, then provides the Lua body that runs them all in a single
process inside one `app.transaction` (open once -> all ops -> save once, atomically).

Validation happens before any Aseprite launch and is the basis of `dry_run`. It checks
*shape*: unknown op, unknown/missing/mistyped args, bad colour or number, and a frame
number below 1. What needs the open sprite stays an execute-time failure (a missing
layer, or a frame past the end, which `FRAME_GUARD_LUA` rejects inside Aseprite).
"""

from __future__ import annotations

from .errors import ValidationFailed
from .limits import MAX_BATCH_OPERATIONS, MAX_PIXEL_LIST_LENGTH, check_list_length
from .models import FRAME_GUARD_LUA, ColorSpec, FrameRef

# Arg kinds. `frame` is an int that must name an existing 1-based frame: the lower bound
# is checked here, the upper bound inside Aseprite (see FRAME_GUARD_LUA).
_INT, _STR, _BOOL, _COLOR, _FRAME = "int", "str", "bool", "color", "frame"
_LIST = "list"

# Curated v1 op set. Each entry maps arg name -> (kind, required).
_DRAW_TARGET = {"layer": (_STR, False), "frame": (_FRAME, False)}
OP_SPECS: dict[str, dict] = {
    # layers
    "add_layer": {"name": (_STR, True), "group": (_STR, False), "opacity": (_INT, False),
                  "blend_mode": (_STR, False), "visible": (_BOOL, False)},
    "rename_layer": {"layer": (_STR, True), "new_name": (_STR, True)},
    "set_layer_visible": {"layer": (_STR, True), "visible": (_BOOL, True)},
    "set_layer_opacity": {"layer": (_STR, True), "opacity": (_INT, True)},
    "remove_layer": {"layer": (_STR, True)},
    # frames
    "add_frame": {"duration_ms": (_INT, False), "copy_from": (_FRAME, False)},
    "duplicate_frame": {"frame": (_FRAME, True)},
    "set_frame_duration": {"frame": (_FRAME, True), "duration_ms": (_INT, True)},
    "remove_frame": {"frame": (_FRAME, True)},
    "set_all_frame_durations": {"duration_ms": (_INT, True)},
    # cels
    #
    # These are what animation is made of, and none of them was batchable. Moving one
    # drawn cel across eight frames cost eight Aseprite launches and 1.75s, against two
    # launches and 0.24s for the same work in one batch: seven times faster, on the path
    # every animation tool has to walk.
    "set_cel_position": {"layer": (_STR, True), "frame": (_FRAME, True),
                         "x": (_INT, True), "y": (_INT, True)},
    "set_cel_opacity": {"layer": (_STR, True), "frame": (_FRAME, True),
                        "opacity": (_INT, True)},
    "copy_cel": {"layer": (_STR, True), "from": (_FRAME, True), "to": (_FRAME, True),
                 "to_layer": (_STR, False)},
    "delete_cel": {"layer": (_STR, True), "frame": (_FRAME, True)},
    # tags
    "add_tag": {"name": (_STR, True), "from": (_FRAME, True), "to": (_FRAME, True),
                "direction": (_STR, False), "color": (_COLOR, False)},
    "remove_tag": {"name": (_STR, True)},
    # drawing
    "set_pixel": {**_DRAW_TARGET, "x": (_INT, True), "y": (_INT, True), "color": (_COLOR, True)},
    "draw_line": {**_DRAW_TARGET, "x1": (_INT, True), "y1": (_INT, True),
                  "x2": (_INT, True), "y2": (_INT, True), "color": (_COLOR, True)},
    "draw_rectangle": {**_DRAW_TARGET, "x": (_INT, True), "y": (_INT, True),
                       "width": (_INT, True), "height": (_INT, True), "color": (_COLOR, True)},
    "fill_rectangle": {**_DRAW_TARGET, "x": (_INT, True), "y": (_INT, True),
                       "width": (_INT, True), "height": (_INT, True), "color": (_COLOR, True)},
    "draw_ellipse": {**_DRAW_TARGET, "cx": (_INT, True), "cy": (_INT, True),
                     "rx": (_INT, True), "ry": (_INT, True), "color": (_COLOR, True)},
    "fill_ellipse": {**_DRAW_TARGET, "cx": (_INT, True), "cy": (_INT, True),
                     "rx": (_INT, True), "ry": (_INT, True), "color": (_COLOR, True)},
    "fill_layer": {**_DRAW_TARGET, "color": (_COLOR, True)},
    "clear_layer": {**_DRAW_TARGET},
    # A list of {"x", "y", "color"?}, so a whole sprite's worth of plotting is one op
    # rather than one op per pixel against the 500-operation batch cap.
    "draw_pixels": {**_DRAW_TARGET, "pixels": (_LIST, True), "color": (_COLOR, False)},
    # slices
    "add_slice": {"name": (_STR, True), "x": (_INT, True), "y": (_INT, True),
                  "width": (_INT, True), "height": (_INT, True), "color": (_COLOR, False)},
    "remove_slice": {"name": (_STR, True)},
    # palette / colour
    "replace_color": {**_DRAW_TARGET, "from": (_COLOR, True), "to": (_COLOR, True),
                      "tolerance": (_INT, False)},
}

# Accepted spellings for an argument whose canonical op name differs from the equivalent
# standalone tool's parameter name (`add_tag(from_frame=...)`, `replace_color(from_color=...)`).
#
# Aliases rather than a rename: undeclared arguments are now rejected outright, so
# dropping `from`/`to` would turn every working batch call into a hard failure. Aliases
# make the tool spelling work too, and cost one lookup. The canonical names stay as they
# are, and `operations_reference()` lists both.
OP_ARG_ALIASES: dict[str, dict[str, str]] = {
    "add_tag": {"from_frame": "from", "to_frame": "to"},
    "replace_color": {"from_color": "from", "to_color": "to"},
    "copy_cel": {"from_frame": "from", "to_frame": "to"},
}


def operations_reference() -> str:
    """A generated listing of every operation and its argument names/kinds.

    Generated, not hand-written: the docstring's hand-written list of op *names* had
    already drifted from this registry, and the argument names were never documented at
    all, which is how a caller ends up guessing `from_frame` inside a batch. A test
    asserts this listing covers OP_SPECS exactly, so it cannot go stale.
    """
    lines = []
    for name in sorted(OP_SPECS):
        args = ", ".join(
            f"{arg}={kind}" if required else f"{arg}={kind}?"
            for arg, (kind, required) in OP_SPECS[name].items()
        )
        line = f"  {name}({args})"
        aliases = OP_ARG_ALIASES.get(name)
        if aliases:
            spellings = ", ".join(f"{alias} for {target}" for alias, target in sorted(aliases.items()))
            line += f"  [also accepts {spellings}]"
        lines.append(line)
    return "\n".join(lines)


def _canonical_args(index: int, name: str, args: dict) -> dict:
    """Rewrite accepted alias spellings to their canonical arg names."""
    aliases = OP_ARG_ALIASES.get(name)
    if not aliases or not any(alias in args for alias in aliases):
        return args
    out = dict(args)
    for alias, target in aliases.items():
        if alias not in out:
            continue
        if target in out:
            raise ValidationFailed(
                f"op {index} ({name}): pass either '{target}' or '{alias}', not both."
            )
        out[target] = out.pop(alias)
    return out


def validate_operations(operations) -> list[dict]:
    """Validate + normalize a list of operations. Raises ValidationFailed (with the
    offending op index) on shape errors. Colours are parsed to dicts; ints coerced."""
    if not isinstance(operations, list) or not operations:
        raise ValidationFailed("operations must be a non-empty list.")
    check_list_length(
        "operations", operations, MAX_BATCH_OPERATIONS,
        remedy="Split the edit into multiple batches.",
    )

    normalized: list[dict] = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict) or "op" not in op:
            raise ValidationFailed(f"op {i}: each operation needs an 'op' field.")
        name = op["op"]
        spec = OP_SPECS.get(name)
        if spec is None:
            raise ValidationFailed(
                f"op {i}: unknown operation '{name}'. Known ops: {sorted(OP_SPECS)}."
            )
        args = op.get("args", {})
        if not isinstance(args, dict):
            raise ValidationFailed(f"op {i} ({name}): 'args' must be an object.")
        args = _canonical_args(i, name, args)

        # The loop below walks the SPEC, so anything the caller sent that is not in the spec
        # simply never gets looked at. A misspelled optional arg -- "blendmode" for
        # "blend_mode", "opacty" for "opacity" -- vanished silently and the op reported
        # success having ignored it. Required args were caught; optional ones were not.
        unknown = sorted(set(args) - set(spec))
        if unknown:
            accepted = sorted(set(spec) | set(OP_ARG_ALIASES.get(name, {})))
            raise ValidationFailed(
                f"op {i} ({name}): unknown arg(s) {', '.join(repr(u) for u in unknown)}. "
                f"Accepted: {', '.join(accepted)}."
            )

        norm: dict = {}
        for arg, (kind, required) in spec.items():
            if arg not in args or args[arg] is None:
                if required:
                    raise ValidationFailed(f"op {i} ({name}): missing required arg '{arg}'.")
                continue
            value = args[arg]
            try:
                if kind == _INT:
                    norm[arg] = int(value)
                elif kind == _FRAME:
                    norm[arg] = FrameRef.arg(f"'{arg}'", value)
                elif kind == _STR:
                    norm[arg] = str(value)
                elif kind == _BOOL:
                    norm[arg] = bool(value)
                elif kind == _COLOR:
                    norm[arg] = ColorSpec.parse(value).as_dict()
                elif kind == _LIST:
                    if not isinstance(value, list) or not value:
                        raise ValidationFailed(f"'{arg}' must be a non-empty list.")
                    # Capped per op, not just per batch: the batch cap counts operations,
                    # so one op carrying a million pixels would slip straight past it.
                    check_list_length(f"'{arg}'", value, MAX_PIXEL_LIST_LENGTH)
                    norm[arg] = _normalize_pixels(value, name, i)
            except ValidationFailed as exc:
                # Already a full sentence from FrameRef; just place it in the batch.
                raise ValidationFailed(f"op {i} ({name}): {exc}") from exc
            except (ValueError, TypeError) as exc:
                raise ValidationFailed(f"op {i} ({name}): bad value for '{arg}': {exc}") from exc
        normalized.append({"op": name, "args": norm})
    return normalized


def _normalize_pixels(pixels: list, op_name: str, index: int) -> list[dict]:
    """Validate a pixel list the same way the standalone draw_pixels tool does.

    Done here rather than in Lua so a malformed entry is refused before Aseprite is
    launched, which is the difference between a clear message and a Lua type error
    quoting generated code.
    """
    out = []
    for n, pixel in enumerate(pixels):
        if not isinstance(pixel, dict) or "x" not in pixel or "y" not in pixel:
            raise ValidationFailed(
                f"op {index} ({op_name}): pixels[{n}] must be "
                '{"x": int, "y": int, "color": "#hex"?}.'
            )
        entry = {"x": int(pixel["x"]), "y": int(pixel["y"])}
        if pixel.get("color") is not None:
            entry["color"] = ColorSpec.parse(pixel["color"]).as_dict()
        out.append(entry)
    return out


def summarize(op: dict) -> str:
    """A short human/agent-readable summary of a (normalized) op."""
    args = op.get("args", {})
    inner = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{op['op']}({inner})"


# The Lua body run via core.runner.run_lua. It reads ARG.operations (a list of
# {op, args}) and applies them atomically. On any op failure it raises a JSON-encoded
# error (level 0, no position prefix) so Python can surface a structured message; the
# transaction rolls back and the file is never saved.
BATCH_LUA_BODY = FRAME_GUARD_LUA + r"""
local spr = open_sprite(ARG.src)
local applied = {}

local function run_op(op)
  local a = op.args
  local name = op.op
  -- layers
  if name == "add_layer" then
    local l = spr:newLayer(); l.name = a.name
    if a.opacity ~= nil then l.opacity = a.opacity end
    if a.blend_mode ~= nil then l.blendMode = blendmode_from(a.blend_mode) end
    if a.visible ~= nil then l.isVisible = a.visible end
    if a.group ~= nil then
      local grp = find_layer(spr, a.group)
      if not grp.isGroup then error("'" .. tostring(a.group) .. "' is not a group layer", 0) end
      l.parent = grp
      return "added layer '" .. a.name .. "' in group '" .. a.group .. "'"
    end
    return "added layer '" .. a.name .. "'"
  elseif name == "rename_layer" then
    find_layer(spr, a.layer).name = a.new_name
    return "renamed '" .. tostring(a.layer) .. "' -> '" .. a.new_name .. "'"
  elseif name == "set_layer_visible" then
    find_layer(spr, a.layer).isVisible = a.visible
    return "set '" .. tostring(a.layer) .. "' visible=" .. tostring(a.visible)
  elseif name == "set_layer_opacity" then
    find_layer(spr, a.layer).opacity = a.opacity
    return "set '" .. tostring(a.layer) .. "' opacity=" .. a.opacity
  elseif name == "remove_layer" then
    if #spr.layers <= 1 then error("cannot delete the only layer", 0) end
    spr:deleteLayer(find_layer(spr, a.layer))
    return "removed layer '" .. tostring(a.layer) .. "'"
  -- frames
  elseif name == "add_frame" then
    local fr
    if a.copy_from ~= nil then fr = spr:newFrame(require_frame(spr, a.copy_from, "copy_from"))
    else fr = spr:newEmptyFrame(#spr.frames + 1) end
    if a.duration_ms ~= nil then fr.duration = a.duration_ms / 1000.0 end
    return "added frame " .. fr.frameNumber
  elseif name == "duplicate_frame" then
    local fr = spr:newFrame(require_frame(spr, a.frame, "frame"))
    return "duplicated frame -> " .. fr.frameNumber
  elseif name == "set_frame_duration" then
    local n = require_frame(spr, a.frame, "frame")
    spr.frames[n].duration = a.duration_ms / 1000.0
    return "set frame " .. n .. " duration to " .. a.duration_ms .. "ms"
  elseif name == "remove_frame" then
    if #spr.frames <= 1 then error("cannot delete the only frame", 0) end
    local n = require_frame(spr, a.frame, "frame")
    spr:deleteFrame(n)
    return "removed frame " .. n
  elseif name == "set_all_frame_durations" then
    for _, fr in ipairs(spr.frames) do fr.duration = a.duration_ms / 1000.0 end
    return "set all " .. #spr.frames .. " frames to " .. a.duration_ms .. "ms"
  -- cels
  elseif name == "set_cel_position" then
    local layer = find_layer(spr, a.layer)
    local n = require_frame(spr, a.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then
      error("layer '" .. tostring(a.layer) .. "' has no cel on frame " .. n, 0)
    end
    cel.position = Point(a.x, a.y)
    return "moved cel on frame " .. n .. " to (" .. a.x .. "," .. a.y .. ")"
  elseif name == "set_cel_opacity" then
    local layer = find_layer(spr, a.layer)
    local n = require_frame(spr, a.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then
      error("layer '" .. tostring(a.layer) .. "' has no cel on frame " .. n, 0)
    end
    cel.opacity = math.max(0, math.min(255, a.opacity))
    return "set cel opacity on frame " .. n .. " to " .. cel.opacity
  elseif name == "copy_cel" then
    local from_layer = find_layer(spr, a.layer)
    local to_layer = (a.to_layer ~= nil) and find_layer(spr, a.to_layer) or from_layer
    local fromn = require_frame(spr, a["from"], "from")
    local ton = require_frame(spr, a["to"], "to")
    local src_cel = from_layer:cel(fromn)
    if src_cel == nil then
      error("layer '" .. tostring(a.layer) .. "' has no cel on frame " .. fromn, 0)
    end
    -- A copy, not a link: an independent image, so editing the destination later does
    -- not silently change the source. Linking is a separate, deliberate operation.
    local copy = Image(src_cel.image)
    spr:newCel(to_layer, ton, copy, src_cel.position)
    return "copied cel frame " .. fromn .. " -> " .. ton
  elseif name == "delete_cel" then
    local layer = find_layer(spr, a.layer)
    local n = require_frame(spr, a.frame, "frame")
    local cel = layer:cel(n)
    if cel == nil then
      error("layer '" .. tostring(a.layer) .. "' has no cel on frame " .. n, 0)
    end
    spr:deleteCel(cel)
    return "deleted cel on frame " .. n
  -- tags
  elseif name == "add_tag" then
    local f1 = require_frame(spr, a["from"], "from")
    local f2 = require_frame(spr, a.to, "to")
    if f1 > f2 then f1, f2 = f2, f1 end
    local t = spr:newTag(f1, f2); t.name = a.name
    if a.direction ~= nil then t.aniDir = anidir_from(a.direction) end
    if a.color ~= nil then t.color = mkcolor(a.color) end
    return "added tag '" .. a.name .. "' on frames " .. f1 .. "-" .. f2
  elseif name == "remove_tag" then
    local found = nil
    for _, tg in ipairs(spr.tags) do if tg.name == a.name then found = tg end end
    if found == nil then error("no tag named '" .. tostring(a.name) .. "'", 0) end
    spr:deleteTag(found)
    return "removed tag '" .. a.name .. "'"
  -- slices
  elseif name == "add_slice" then
    local sl = spr:newSlice(Rectangle(a.x, a.y, a.width, a.height)); sl.name = a.name
    if a.color ~= nil then sl.color = mkcolor(a.color) end
    return "added slice '" .. a.name .. "'"
  elseif name == "remove_slice" then
    local found = nil
    for _, s in ipairs(spr.slices) do if s.name == a.name then found = s end end
    if found == nil then error("no slice named '" .. tostring(a.name) .. "'", 0) end
    spr:deleteSlice(found)
    return "removed slice '" .. a.name .. "'"
  -- palette / colour
  elseif name == "replace_color" then
    local layer = find_layer(spr, a.layer)
    if layer.isGroup then error("cannot edit a group layer: " .. layer.name, 0) end
    local n = require_frame(spr, a.frame or 1, "frame")
    local img = get_draw_image(spr, layer, n)
    local fr, fg, fb, fa = a["from"].r, a["from"].g, a["from"].b, a["from"].a or 255
    local tol = a.tolerance or 0
    local tp = to_pixel(spr, a.to)
    for yy = 0, img.height - 1 do
      for xx = 0, img.width - 1 do
        local r, g, b, al = px_to_rgba(spr, img:getPixel(xx, yy))
        if math.abs(r - fr) <= tol and math.abs(g - fg) <= tol
           and math.abs(b - fb) <= tol and math.abs(al - fa) <= tol then
          img:drawPixel(xx, yy, tp)
        end
      end
    end
    commit_image(spr, layer, n, img)
    return "replaced colour"
  -- drawing (shared open/commit)
  else
    local layer = find_layer(spr, a.layer)
    if layer.isGroup then error("cannot draw on a group layer: " .. layer.name, 0) end
    local n = require_frame(spr, a.frame or 1, "frame")
    local img = get_draw_image(spr, layer, n)
    if name == "set_pixel" then
      img_set(img, a.x, a.y, to_pixel(spr, a.color))
    elseif name == "draw_line" then
      draw_line_img(img, a.x1, a.y1, a.x2, a.y2, to_pixel(spr, a.color))
    elseif name == "draw_rectangle" then
      draw_rect_img(img, a.x, a.y, a.width, a.height, to_pixel(spr, a.color), false)
    elseif name == "fill_rectangle" then
      draw_rect_img(img, a.x, a.y, a.width, a.height, to_pixel(spr, a.color), true)
    elseif name == "draw_ellipse" then
      draw_ellipse_img(img, a.cx, a.cy, a.rx, a.ry, to_pixel(spr, a.color), false)
    elseif name == "fill_ellipse" then
      draw_ellipse_img(img, a.cx, a.cy, a.rx, a.ry, to_pixel(spr, a.color), true)
    elseif name == "fill_layer" then
      draw_rect_img(img, 0, 0, spr.width, spr.height, to_pixel(spr, a.color), true)
    elseif name == "clear_layer" then
      img:clear()
    elseif name == "draw_pixels" then
      local fallback = (a.color ~= nil) and to_pixel(spr, a.color) or nil
      for _, pixel in ipairs(a.pixels) do
        local px = (pixel.color ~= nil) and to_pixel(spr, pixel.color) or fallback
        if px == nil then
          error("draw_pixels: pixel at (" .. pixel.x .. "," .. pixel.y ..
                ") has no colour and no shared `color` was given", 0)
        end
        img_set(img, pixel.x, pixel.y, px)
      end
    else
      error("unknown op '" .. tostring(name) .. "'", 0)
    end
    commit_image(spr, layer, n, img)
    return name
  end
end

app.transaction(function()
  for i, op in ipairs(ARG.operations) do
    local ok, ret = pcall(run_op, op)
    if not ok then
      error(json_encode({ failed_op_index = i - 1, failed_op = op.op, error = tostring(ret) }), 0)
    end
    applied[i] = { index = i - 1, op = op.op, status = "applied", summary = ret }
  end
end)

save_sprite(spr)
RESULT = { sprite = sprite_info(spr), operations = applied }
"""
