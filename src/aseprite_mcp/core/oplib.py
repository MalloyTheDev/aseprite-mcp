"""Batch operation registry + one-script Lua assembler.

Pure-Python (no Aseprite): validates a list of `{"op": str, "args": {...}}` operations
against a curated registry, then provides the Lua body that runs them all in a single
process inside one `app.transaction` (open once -> all ops -> save once, atomically).

Validation happens before any Aseprite launch and is the basis of `dry_run`. It checks
*shape* (unknown op, missing/typed args, bad colour/number) — not runtime sprite state
(a missing layer/frame is an execute-time failure).
"""

from __future__ import annotations

from .errors import ValidationFailed
from .models import ColorSpec

# Arg kinds.
_INT, _STR, _BOOL, _COLOR = "int", "str", "bool", "color"

# Curated v1 op set. Each entry maps arg name -> (kind, required).
_DRAW_TARGET = {"layer": (_STR, False), "frame": (_INT, False)}
OP_SPECS: dict[str, dict] = {
    # layers
    "add_layer": {"name": (_STR, True), "opacity": (_INT, False),
                  "blend_mode": (_STR, False), "visible": (_BOOL, False)},
    "rename_layer": {"layer": (_STR, True), "new_name": (_STR, True)},
    "set_layer_visible": {"layer": (_STR, True), "visible": (_BOOL, True)},
    "set_layer_opacity": {"layer": (_STR, True), "opacity": (_INT, True)},
    "remove_layer": {"layer": (_STR, True)},
    # frames
    "add_frame": {"duration_ms": (_INT, False), "copy_from": (_INT, False)},
    "duplicate_frame": {"frame": (_INT, True)},
    "set_frame_duration": {"frame": (_INT, True), "duration_ms": (_INT, True)},
    # tags
    "add_tag": {"name": (_STR, True), "from": (_INT, True), "to": (_INT, True),
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
    # slices
    "add_slice": {"name": (_STR, True), "x": (_INT, True), "y": (_INT, True),
                  "width": (_INT, True), "height": (_INT, True), "color": (_COLOR, False)},
    "remove_slice": {"name": (_STR, True)},
    # palette / colour
    "replace_color": {**_DRAW_TARGET, "from": (_COLOR, True), "to": (_COLOR, True),
                      "tolerance": (_INT, False)},
}


def validate_operations(operations) -> list[dict]:
    """Validate + normalize a list of operations. Raises ValidationFailed (with the
    offending op index) on shape errors. Colours are parsed to dicts; ints coerced."""
    if not isinstance(operations, list) or not operations:
        raise ValidationFailed("operations must be a non-empty list.")

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
                elif kind == _STR:
                    norm[arg] = str(value)
                elif kind == _BOOL:
                    norm[arg] = bool(value)
                elif kind == _COLOR:
                    norm[arg] = ColorSpec.parse(value).as_dict()
            except (ValueError, TypeError) as exc:
                raise ValidationFailed(f"op {i} ({name}): bad value for '{arg}': {exc}") from exc
        normalized.append({"op": name, "args": norm})
    return normalized


def summarize(op: dict) -> str:
    """A short human/agent-readable summary of a (normalized) op."""
    args = op.get("args", {})
    inner = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{op['op']}({inner})"


# The Lua body run via core.runner.run_lua. It reads ARG.operations (a list of
# {op, args}) and applies them atomically. On any op failure it raises a JSON-encoded
# error (level 0, no position prefix) so Python can surface a structured message; the
# transaction rolls back and the file is never saved.
BATCH_LUA_BODY = r"""
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
    if a.copy_from ~= nil then fr = spr:newFrame(clamp_frame(spr, a.copy_from))
    else fr = spr:newEmptyFrame(#spr.frames + 1) end
    if a.duration_ms ~= nil then fr.duration = a.duration_ms / 1000.0 end
    return "added frame " .. fr.frameNumber
  elseif name == "duplicate_frame" then
    local fr = spr:newFrame(clamp_frame(spr, a.frame))
    return "duplicated frame -> " .. fr.frameNumber
  elseif name == "set_frame_duration" then
    spr.frames[clamp_frame(spr, a.frame)].duration = a.duration_ms / 1000.0
    return "set frame " .. a.frame .. " duration"
  -- tags
  elseif name == "add_tag" then
    local f1, f2 = clamp_frame(spr, a["from"]), clamp_frame(spr, a.to)
    if f1 > f2 then f1, f2 = f2, f1 end
    local t = spr:newTag(f1, f2); t.name = a.name
    if a.direction ~= nil then t.aniDir = anidir_from(a.direction) end
    if a.color ~= nil then t.color = mkcolor(a.color) end
    return "added tag '" .. a.name .. "'"
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
    local n = clamp_frame(spr, a.frame or 1)
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
    local n = clamp_frame(spr, a.frame or 1)
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
