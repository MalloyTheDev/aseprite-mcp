"""Generate Lua scripts for Aseprite's batch interpreter.

Every tool produces a small Lua *body*. `assemble_script` wraps that body with:

  * a `local ARG = {...}` table holding the tool's parameters (serialized from
    Python with `to_lua`),
  * the PRELUDE below (JSON encoder, colour/pixel helpers, deterministic drawing
    primitives, and a sprite-info serializer), and
  * a `pcall` harness that prints either `@@ASEMCP@@<json>` (success, the contents
    of the `RESULT` table) or `@@ASEMCP_ERR@@<message>` (a caught Lua error).

The runner parses those sentinel lines back into Python.
"""

from __future__ import annotations

RESULT_PREFIX = "@@ASEMCP@@"
ERROR_PREFIX = "@@ASEMCP_ERR@@"


# --------------------------------------------------------------------------- #
# Python value  ->  Lua literal                                               #
# --------------------------------------------------------------------------- #
def _lua_string(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o == 127:
            # Zero-padded decimal escape is unambiguous regardless of the next char.
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def to_lua(value) -> str:
    """Serialize a JSON-ish Python value to a Lua literal expression."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "0"
        return repr(value)
    if isinstance(value, str):
        return _lua_string(value)
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(to_lua(v) for v in value) + "}"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            key = f"[{k}]" if isinstance(k, int) else f"[{_lua_string(str(k))}]"
            parts.append(f"{key}={to_lua(v)}")
        return "{" + ", ".join(parts) + "}"
    return _lua_string(str(value))


# --------------------------------------------------------------------------- #
# Lua prelude (shared helpers available to every tool body)                   #
# --------------------------------------------------------------------------- #
PRELUDE = r"""
-- ===== number / table helpers =====================================
local function clamp255(x)
  x = math.floor(tonumber(x) + 0.5)
  if x < 0 then return 0 elseif x > 255 then return 255 else return x end
end

local function _is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" then return false, 0 end
    n = n + 1
  end
  for i = 1, n do
    if t[i] == nil then return false, 0 end
  end
  return true, n
end

local function _esc(s)
  return (s:gsub('[%c"\\]', function(ch)
    local b = string.byte(ch)
    if ch == '"' then return '\\"'
    elseif ch == '\\' then return '\\\\'
    elseif b == 10 then return '\\n'
    elseif b == 13 then return '\\r'
    elseif b == 9 then return '\\t'
    elseif b == 8 then return '\\b'
    elseif b == 12 then return '\\f'
    else return string.format('\\u%04x', b) end
  end))
end

local function json_encode(v)
  local tp = type(v)
  if v == nil then return "null"
  elseif tp == "boolean" then return v and "true" or "false"
  elseif tp == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "0" end
    if math.type then
      if math.type(v) == "integer" then return string.format("%d", v) end
      return string.format("%.10g", v)
    else
      if math.floor(v) == v and math.abs(v) < 1e15 then return string.format("%d", v) end
      return string.format("%.10g", v)
    end
  elseif tp == "string" then
    return '"' .. _esc(v) .. '"'
  elseif tp == "table" then
    local isarr, n = _is_array(v)
    if isarr then
      local parts = {}
      for i = 1, n do parts[i] = json_encode(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do
      parts[#parts + 1] = '"' .. _esc(tostring(k)) .. '":' .. json_encode(val)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return "null"
end

-- ===== colour helpers =============================================
local function color_hex(c)
  return string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
end

local function mkcolor(c)
  if c == nil then return Color{ r = 0, g = 0, b = 0, a = 0 } end
  local r = c.r or c[1] or 0
  local g = c.g or c[2] or 0
  local b = c.b or c[3] or 0
  local a = c.a or c[4] or 255
  return Color{ r = clamp255(r), g = clamp255(g), b = clamp255(b), a = clamp255(a) }
end

local function nearest_index(spr, r, g, b)
  local pal = spr.palettes[1]
  local best, bestd = 0, nil
  for i = 0, #pal - 1 do
    local col = pal:getColor(i)
    local dr, dg, db = col.red - r, col.green - g, col.blue - b
    local d = dr * dr + dg * dg + db * db
    if bestd == nil or d < bestd then bestd = d; best = i end
  end
  return best
end

-- Convert a colour spec table (with r,g,b,a and/or index) to a raw pixel value
-- appropriate for the sprite's colour mode.
local function to_pixel(spr, c)
  local cm = spr.colorMode
  if type(c) == "table" and c.index ~= nil and cm == ColorMode.INDEXED then
    return math.floor(c.index)
  end
  local col = mkcolor(c)
  if cm == ColorMode.RGB then
    return app.pixelColor.rgba(col.red, col.green, col.blue, col.alpha)
  elseif cm == ColorMode.GRAY then
    local v = math.floor((col.red + col.green + col.blue) / 3 + 0.5)
    return app.pixelColor.graya(v, col.alpha)
  elseif cm == ColorMode.INDEXED then
    if col.alpha == 0 then return spr.transparentColor end
    return nearest_index(spr, col.red, col.green, col.blue)
  end
  return 0
end

-- Decompose a raw pixel value into r,g,b,a (0-255), regardless of colour mode.
local function px_to_rgba(spr, px)
  local cm = spr.colorMode
  if cm == ColorMode.RGB then
    return app.pixelColor.rgbaR(px), app.pixelColor.rgbaG(px),
           app.pixelColor.rgbaB(px), app.pixelColor.rgbaA(px)
  elseif cm == ColorMode.GRAY then
    local v = app.pixelColor.grayaV(px)
    return v, v, v, app.pixelColor.grayaA(px)
  else
    if px == spr.transparentColor then return 0, 0, 0, 0 end
    local c = spr.palettes[1]:getColor(px)
    return c.red, c.green, c.blue, c.alpha
  end
end

-- Build a raw pixel value from r,g,b,a (0-255), appropriate for the colour mode.
local function rgba_to_px(spr, r, g, b, a)
  r, g, b, a = clamp255(r), clamp255(g), clamp255(b), clamp255(a)
  local cm = spr.colorMode
  if cm == ColorMode.RGB then
    return app.pixelColor.rgba(r, g, b, a)
  elseif cm == ColorMode.GRAY then
    return app.pixelColor.graya(math.floor((r + g + b) / 3 + 0.5), a)
  else
    if a == 0 then return spr.transparentColor end
    return nearest_index(spr, r, g, b)
  end
end

-- Is the pixel at (x,y) opaque (alpha > 0 / not the transparent index)?
local function img_solid(spr, img, x, y)
  if x < 0 or y < 0 or x >= img.width or y >= img.height then return false end
  local _, _, _, a = px_to_rgba(spr, img:getPixel(x, y))
  return a > 0
end

-- Alpha-composite colour (r,g,b) with coverage `cov` (0..1) over the pixel at
-- (x,y). On RGB sprites this anti-aliases; on indexed/gray it thresholds at 0.5.
local function blend_over(spr, img, x, y, r, g, b, cov)
  if x < 0 or y < 0 or x >= img.width or y >= img.height or cov <= 0 then return end
  x, y = math.floor(x), math.floor(y)
  if cov > 1 then cov = 1 end
  if spr.colorMode == ColorMode.RGB then
    local dr, dg, db, da = px_to_rgba(spr, img:getPixel(x, y))
    local sa = cov
    local dfa = da / 255
    local outa = sa + dfa * (1 - sa)
    if outa <= 0 then return end
    local nr = (r * sa + dr * dfa * (1 - sa)) / outa
    local ng = (g * sa + dg * dfa * (1 - sa)) / outa
    local nb = (b * sa + db * dfa * (1 - sa)) / outa
    img:drawPixel(x, y, app.pixelColor.rgba(clamp255(nr), clamp255(ng), clamp255(nb), clamp255(outa * 255)))
  elseif cov >= 0.5 then
    img:drawPixel(x, y, rgba_to_px(spr, r, g, b, 255))
  end
end

-- ===== enum name maps =============================================
local function colormode_name(cm)
  if cm == ColorMode.RGB then return "rgb"
  elseif cm == ColorMode.GRAY then return "gray"
  elseif cm == ColorMode.INDEXED then return "indexed"
  elseif ColorMode.TILEMAP ~= nil and cm == ColorMode.TILEMAP then return "tilemap"
  else return "unknown" end
end

local function colormode_from(name)
  name = tostring(name):lower()
  if name == "rgb" or name == "rgba" then return ColorMode.RGB
  elseif name == "gray" or name == "grayscale" or name == "greyscale" then return ColorMode.GRAY
  elseif name == "indexed" then return ColorMode.INDEXED
  else error("Unknown color mode: " .. tostring(name)) end
end

local BLEND_NAMES = {
  normal = BlendMode.NORMAL, multiply = BlendMode.MULTIPLY, screen = BlendMode.SCREEN,
  overlay = BlendMode.OVERLAY, darken = BlendMode.DARKEN, lighten = BlendMode.LIGHTEN,
  color_dodge = BlendMode.COLOR_DODGE, color_burn = BlendMode.COLOR_BURN,
  hard_light = BlendMode.HARD_LIGHT, soft_light = BlendMode.SOFT_LIGHT,
  difference = BlendMode.DIFFERENCE, exclusion = BlendMode.EXCLUSION,
  hue = BlendMode.HUE, saturation = BlendMode.SATURATION, color = BlendMode.COLOR,
  luminosity = BlendMode.LUMINOSITY, addition = BlendMode.ADDITION,
  subtract = BlendMode.SUBTRACT, divide = BlendMode.DIVIDE,
}
local function blendmode_from(name)
  if name == nil then return BlendMode.NORMAL end
  local bm = BLEND_NAMES[tostring(name):lower()]
  if bm == nil then error("Unknown blend mode: " .. tostring(name)) end
  return bm
end
local function blendmode_name(bm)
  for k, v in pairs(BLEND_NAMES) do if v == bm then return k end end
  return "normal"
end

local ANIDIR_NAMES = { forward = AniDir.FORWARD, reverse = AniDir.REVERSE, pingpong = AniDir.PING_PONG }
if AniDir.PING_PONG_REVERSE ~= nil then ANIDIR_NAMES.pingpong_reverse = AniDir.PING_PONG_REVERSE end
local function anidir_from(name)
  if name == nil then return AniDir.FORWARD end
  local d = ANIDIR_NAMES[tostring(name):lower():gsub("[%-%s]", "_")]
  if d == nil then error("Unknown animation direction: " .. tostring(name)) end
  return d
end
local function anidir_name(d)
  for k, v in pairs(ANIDIR_NAMES) do if v == d then return k end end
  return "forward"
end

-- ===== sprite / layer access ======================================
local function open_sprite(path)
  local spr = app.open(path)
  if spr == nil then error("Could not open sprite: " .. tostring(path)) end
  app.sprite = spr
  return spr
end

local function save_sprite(spr)
  spr:saveAs(spr.filename)
end

local function _search_layers(layers, name)
  for _, lyr in ipairs(layers) do
    if lyr.name == name then return lyr end
    if lyr.isGroup then
      local found = _search_layers(lyr.layers, name)
      if found then return found end
    end
  end
  return nil
end

-- Resolve a layer by name (searched recursively, incl. groups), by 1-based
-- top-level index, or fall back to the active/top layer when ref is nil.
local function find_layer(spr, ref)
  if ref == nil then return spr.layers[#spr.layers] end
  if type(ref) == "number" then
    local lyr = spr.layers[math.floor(ref)]
    if lyr == nil then error("No layer at index " .. tostring(ref)) end
    return lyr
  end
  local lyr = _search_layers(spr.layers, tostring(ref))
  if lyr == nil then error("No layer named '" .. tostring(ref) .. "'") end
  return lyr
end

local function clamp_frame(spr, n)
  n = math.floor(tonumber(n) or 1)
  if n < 1 then n = 1 end
  if n > #spr.frames then n = #spr.frames end
  return n
end

-- ===== drawing primitives (operate on an Image, sprite-space coords) ======
local function img_set(img, x, y, px)
  if x >= 0 and y >= 0 and x < img.width and y < img.height then
    img:drawPixel(math.floor(x), math.floor(y), px)
  end
end

local function draw_line_img(img, x0, y0, x1, y1, px)
  x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.floor(x1), math.floor(y1)
  local dx = math.abs(x1 - x0)
  local dy = -math.abs(y1 - y0)
  local sx = x0 < x1 and 1 or -1
  local sy = y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    img_set(img, x0, y0, px)
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
end

local function draw_rect_img(img, x, y, w, h, px, filled)
  x, y, w, h = math.floor(x), math.floor(y), math.floor(w), math.floor(h)
  if w <= 0 or h <= 0 then return end
  if filled then
    for yy = y, y + h - 1 do
      for xx = x, x + w - 1 do img_set(img, xx, yy, px) end
    end
  else
    for xx = x, x + w - 1 do img_set(img, xx, y, px); img_set(img, xx, y + h - 1, px) end
    for yy = y, y + h - 1 do img_set(img, x, yy, px); img_set(img, x + w - 1, yy, px) end
  end
end

local function draw_ellipse_img(img, cx, cy, rx, ry, px, filled)
  cx, cy, rx, ry = math.floor(cx), math.floor(cy), math.floor(math.abs(rx)), math.floor(math.abs(ry))
  if rx == 0 or ry == 0 then
    draw_line_img(img, cx - rx, cy - ry, cx + rx, cy + ry, px)
    return
  end
  if filled then
    for dy = -ry, ry do
      local t = 1 - (dy * dy) / (ry * ry)
      if t < 0 then t = 0 end
      local hw = math.floor(rx * math.sqrt(t) + 0.5)
      for dx = -hw, hw do img_set(img, cx + dx, cy + dy, px) end
    end
    return
  end
  local rx2, ry2 = rx * rx, ry * ry
  local x, y = 0, ry
  local dpx, dpy = 0, 2 * rx2 * y
  local function plot4(ox, oy)
    img_set(img, cx + ox, cy + oy, px); img_set(img, cx - ox, cy + oy, px)
    img_set(img, cx + ox, cy - oy, px); img_set(img, cx - ox, cy - oy, px)
  end
  local p = ry2 - rx2 * ry + 0.25 * rx2
  while dpx < dpy do
    plot4(x, y)
    x = x + 1
    dpx = dpx + 2 * ry2
    if p < 0 then
      p = p + ry2 + dpx
    else
      y = y - 1; dpy = dpy - 2 * rx2; p = p + ry2 + dpx - dpy
    end
  end
  p = ry2 * (x + 0.5) * (x + 0.5) + rx2 * (y - 1) * (y - 1) - rx2 * ry2
  while y >= 0 do
    plot4(x, y)
    y = y - 1
    dpy = dpy - 2 * rx2
    if p > 0 then
      p = p + rx2 - dpy
    else
      x = x + 1; dpx = dpx + 2 * ry2; p = p + rx2 - dpy + dpx
    end
  end
end

local function flood_fill_img(img, x, y, px)
  x, y = math.floor(x), math.floor(y)
  if x < 0 or y < 0 or x >= img.width or y >= img.height then return end
  local target = img:getPixel(x, y)
  if target == px then return end
  local stack = { { x, y } }
  while #stack > 0 do
    local p = stack[#stack]; stack[#stack] = nil
    local px0, py0 = p[1], p[2]
    if px0 >= 0 and py0 >= 0 and px0 < img.width and py0 < img.height
       and img:getPixel(px0, py0) == target then
      img:drawPixel(px0, py0, px)
      stack[#stack + 1] = { px0 + 1, py0 }
      stack[#stack + 1] = { px0 - 1, py0 }
      stack[#stack + 1] = { px0, py0 + 1 }
      stack[#stack + 1] = { px0, py0 - 1 }
    end
  end
end

-- Bresenham line as a list of {x,y} points.
local function bresenham_points(x0, y0, x1, y1)
  x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.floor(x1), math.floor(y1)
  local pts = {}
  local dx = math.abs(x1 - x0)
  local dy = -math.abs(y1 - y0)
  local sx = x0 < x1 and 1 or -1
  local sy = y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    pts[#pts + 1] = { x0, y0 }
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
  return pts
end

-- Remove L-corner pixels from a line path (Aseprite-style pixel-perfect mode).
local function pp_prune(points)
  local n = #points
  if n < 3 then return points end
  local remove = {}
  for k = 2, n - 1 do
    local a, m, c = points[k - 1], points[k], points[k + 1]
    local dx1, dy1 = m[1] - a[1], m[2] - a[2]
    local dx2, dy2 = c[1] - m[1], c[2] - m[2]
    if (dx1 ~= 0 and dy1 == 0 and dx2 == 0 and dy2 ~= 0)
       or (dy1 ~= 0 and dx1 == 0 and dy2 == 0 and dx2 ~= 0) then
      remove[k] = true
    end
  end
  local out = {}
  for k = 1, n do if not remove[k] then out[#out + 1] = points[k] end end
  return out
end

-- Anti-aliased line (Xiaolin Wu) drawn with coverage blending.
local function aa_line_img(spr, img, x0, y0, x1, y1, r, g, b)
  local function fpart(x) return x - math.floor(x) end
  local function rfpart(x) return 1 - fpart(x) end
  local steep = math.abs(y1 - y0) > math.abs(x1 - x0)
  if steep then x0, y0 = y0, x0; x1, y1 = y1, x1 end
  if x0 > x1 then x0, x1 = x1, x0; y0, y1 = y1, y0 end
  local dx = x1 - x0
  local dy = y1 - y0
  local grad = (dx == 0) and 1 or (dy / dx)
  local function plot(px, py, c)
    if steep then blend_over(spr, img, py, px, r, g, b, c)
    else blend_over(spr, img, px, py, r, g, b, c) end
  end
  local xend = math.floor(x0 + 0.5)
  local yend = y0 + grad * (xend - x0)
  plot(xend, math.floor(yend), rfpart(yend))
  plot(xend, math.floor(yend) + 1, fpart(yend))
  local intery = yend + grad
  local xend2 = math.floor(x1 + 0.5)
  for x = xend + 1, xend2 - 1 do
    plot(x, math.floor(intery), rfpart(intery))
    plot(x, math.floor(intery) + 1, fpart(intery))
    intery = intery + grad
  end
  plot(xend2, math.floor(y1), rfpart(y1))
  plot(xend2, math.floor(y1) + 1, fpart(y1))
end

-- Anti-aliased filled ellipse via 4x4 sub-pixel coverage.
local function aa_ellipse_fill_img(spr, img, cx, cy, rx, ry, r, g, b)
  rx, ry = math.abs(rx), math.abs(ry)
  if rx < 1 then rx = 1 end
  if ry < 1 then ry = 1 end
  for yy = math.floor(cy - ry - 1), math.ceil(cy + ry + 1) do
    for xx = math.floor(cx - rx - 1), math.ceil(cx + rx + 1) do
      local cnt = 0
      for sj = 0, 3 do
        for si = 0, 3 do
          local px = xx + (si + 0.5) / 4 - 0.5
          local py = yy + (sj + 0.5) / 4 - 0.5
          local nx, ny = (px - cx) / rx, (py - cy) / ry
          if nx * nx + ny * ny <= 1 then cnt = cnt + 1 end
        end
      end
      if cnt > 0 then blend_over(spr, img, xx, yy, r, g, b, cnt / 16) end
    end
  end
end

-- Build a full-canvas, editable copy of a layer/frame's cel image.
local function get_draw_image(spr, layer, framenum)
  local img = Image(spr.spec)
  img:clear()
  local cel = layer:cel(framenum)
  if cel ~= nil and cel.image ~= nil then
    img:drawImage(cel.image, cel.position)
  end
  return img
end

-- Write an edited full-canvas image back to a layer/frame cel.
local function commit_image(spr, layer, framenum, img)
  local cel = layer:cel(framenum)
  if cel ~= nil then
    cel.image = img
    cel.position = Point(0, 0)
  else
    spr:newCel(layer, framenum, img, Point(0, 0))
  end
end

-- ===== info serializers ===========================================
local function layer_info(lyr)
  local t = {
    name = lyr.name,
    stackIndex = lyr.stackIndex,
    isGroup = lyr.isGroup,
    isVisible = lyr.isVisible,
    isEditable = lyr.isEditable,
  }
  local ok1, op = pcall(function() return lyr.opacity end)
  if ok1 and op ~= nil then t.opacity = op end
  local ok2, bm = pcall(function() return blendmode_name(lyr.blendMode) end)
  if ok2 then t.blendMode = bm end
  if lyr.isGroup then
    local subs = {}
    for i, sub in ipairs(lyr.layers) do subs[i] = layer_info(sub) end
    t.layers = subs
  end
  return t
end

local function sprite_info(spr)
  local layers = {}
  for i, lyr in ipairs(spr.layers) do layers[i] = layer_info(lyr) end
  local frames = {}
  for i, fr in ipairs(spr.frames) do
    frames[i] = { number = i, duration = fr.duration }
  end
  local tags = {}
  for i, tg in ipairs(spr.tags) do
    tags[i] = {
      name = tg.name,
      from = tg.fromFrame.frameNumber,
      to = tg.toFrame.frameNumber,
      aniDir = anidir_name(tg.aniDir),
      color = color_hex(tg.color),
    }
  end
  local slices = {}
  for i, sl in ipairs(spr.slices) do
    local s = { name = sl.name,
                bounds = { x = sl.bounds.x, y = sl.bounds.y,
                           width = sl.bounds.width, height = sl.bounds.height } }
    if sl.center ~= nil then
      s.center = { x = sl.center.x, y = sl.center.y,
                   width = sl.center.width, height = sl.center.height }
    end
    if sl.pivot ~= nil then s.pivot = { x = sl.pivot.x, y = sl.pivot.y } end
    slices[i] = s
  end
  return {
    filename = spr.filename,
    width = spr.width,
    height = spr.height,
    colorMode = colormode_name(spr.colorMode),
    frameCount = #spr.frames,
    layerCount = #spr.layers,
    paletteSize = #spr.palettes[1],
    layers = layers,
    frames = frames,
    tags = tags,
    slices = slices,
  }
end
"""


def assemble_script(body: str, args: dict | None = None) -> str:
    """Wrap a tool body with the ARG table, the prelude, and the pcall harness."""
    arg_literal = to_lua(args or {})
    return (
        f"local ARG = {arg_literal}\n"
        f"{PRELUDE}\n"
        "local RESULT = {}\n"
        "local function _main()\n"
        f"{body}\n"
        "end\n"
        "local _ok, _err = pcall(_main)\n"
        "if _ok then\n"
        f'  print("{RESULT_PREFIX}" .. json_encode(RESULT))\n'
        "else\n"
        f'  print("{ERROR_PREFIX}" .. tostring(_err))\n'
        "end\n"
    )
