"""Generate Lua scripts for Aseprite's batch interpreter.

Every tool produces a small Lua *body*. `assemble_script` wraps that body with:

  * a `local ARG = {...}` table holding the tool's parameters (serialized from
    Python with `to_lua`),
  * the PRELUDE below (JSON encoder, colour/pixel helpers, deterministic drawing
    primitives, and a sprite-info serializer), and
  * a `pcall` harness that prints either `@@ASEMCP:<nonce>@@<json>` (success, the
    contents of the `RESULT` table) or `@@ASEMCP_ERR:<nonce>@@<message>` (a caught Lua
    error).

The runner parses those sentinel lines back into Python. The nonce is per launch, so a
sentinel that a sprite's own text or a path happened to contain cannot be mistaken for
this harness's output; `RESULT_PREFIX` and `ERROR_PREFIX` below are the un-nonced forms,
kept only for a re-export and no longer used to frame anything.
"""

from __future__ import annotations

import secrets

# Legacy un-nonced sentinels. Retained because `aseprite_mcp.luagen` re-exports them,
# but no longer used to frame real output: see `new_nonce` for why.
RESULT_PREFIX = "@@ASEMCP@@"
ERROR_PREFIX = "@@ASEMCP_ERR@@"


def new_nonce() -> str:
    """A fresh token scoping one run's stdout sentinels to that run.

    Sentinels are recognised by position: the runner treats any stdout line starting
    with the result or error prefix as protocol. With a fixed prefix, any caller-supplied
    string that reaches stdout, a layer name, a tag, a filename, can therefore claim to
    *be* the protocol, and escaping alone is a losing game because it has to enumerate
    every byte sequence the reader might treat as a line break.

    A per-run nonce removes the class instead of patching instances: the payload is
    serialized before the nonce is generated and never appears in the script's input,
    so it cannot name the token it would have to guess. Escaping the line terminators is
    still worth doing (see `_esc`), but it is now defence in depth rather than the
    only thing standing between a layer name and a forged result.
    """
    return secrets.token_hex(8)


def result_prefix(nonce: str) -> str:
    """The success sentinel for `nonce`. Distinct from `error_prefix` by construction."""
    return f"@@ASEMCP:{nonce}@@"


def error_prefix(nonce: str) -> str:
    """The failure sentinel for `nonce`."""
    return f"@@ASEMCP_ERR:{nonce}@@"


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
            out.append(f"\\{o:03d}")
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
-- ===== pixel accounting ===========================================
-- Every write to an image goes through img_set, blend_over or flood_fill_img, so
-- counting here gives every tool an honest report of what it did without each one
-- having to keep its own tally. A draw whose coordinates fall off the canvas used to
-- be silently dropped and still return ok: `draw_rectangle(10,10,20,20)` on a 16x16
-- canvas asked for 400 pixels, landed 36, and said nothing. The counts are attached
-- to RESULT by the harness only when a run actually touched pixels, so a tool that
-- writes nothing does not grow a misleading "0".
local _px_written, _px_clipped, _px_skipped, _px_masked = 0, 0, 0, 0

-- Set by commit_image when the cel it wrote is shared with other frames, so the write
-- landed on all of them. Reported by the harness: the propagation is correct and is what
-- linking means, but a result saying `frame: 2, pixels_written: 1` while four frames
-- changed is not telling the caller what happened.
local _linked_hit_frame, _linked_hit_others = nil, nil

-- The active selection, or nil. Set by open_sprite when a sidecar mask is loaded.
--
-- It has to be consulted by hand: a selection clips app.useTool and the filter commands,
-- but NOT Image:drawPixel, which is what every write in here ultimately calls. Without
-- this check a selection would appear to work for some tools and be silently ignored by
-- others, which is worse than not supporting selections at all.
local _sel = nil

-- The rule, in one place, because having it in two is how this went wrong. `img_set` used
-- to be the only write that checked the mask, and nine others called `Image:drawPixel`
-- directly: the anti-aliased coverage write, the flood fill, every per-pixel effect pass,
-- `mirror_layer` and the batch runner's replace op. All of them edited the whole layer
-- while the harness stamped `selection_applied: true`, because that flag is set from
-- `_sel ~= nil` and has no way to know whether the body honoured it. A missing count can
-- be noticed; a result that asserts a selection was applied when it was not cannot.
--
-- Counts each refused pixel once, so a caller comparing `pixels_written` against
-- `pixels_outside_selection` gets two numbers that add up.
local function masked_out(x, y)
  -- contains() costs roughly a quarter of a microsecond, so a full 256x256 canvas is
  -- about 16ms: cheap enough to check per pixel rather than precomputing a bitmap.
  if _sel ~= nil and not _sel:contains(math.floor(x), math.floor(y)) then
    _px_masked = _px_masked + 1
    return true
  end
  return false
end

-- The sprite the body opened, for the harness. See open_sprite.
local _sprite = nil

-- For tools that decline a write on purpose (a gradient leaving transparent pixels
-- alone, say). Deliberate and out-of-bounds are different facts and are reported so.
local function note_skipped(n)
  _px_skipped = _px_skipped + (n or 1)
end

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
  s = s:gsub('[%c"\\]', function(ch)
    local b = string.byte(ch)
    if ch == '"' then return '\\"'
    elseif ch == '\\' then return '\\\\'
    elseif b == 10 then return '\\n'
    elseif b == 13 then return '\\r'
    elseif b == 9 then return '\\t'
    elseif b == 8 then return '\\b'
    elseif b == 12 then return '\\f'
    else return string.format('\\u%04x', b) end
  end)
  -- Lua's %c class is byte-wise, so the pattern above covers only 0x00-0x1F and 0x7F.
  -- Bytes 128 and up pass through untouched, which means the UTF-8 encodings of the
  -- Unicode line terminators reach stdout intact. Python's str.splitlines() treats
  -- U+0085, U+2028 and U+2029 as line breaks, so an unescaped one lets a value inside
  -- a JSON string start a new stdout line. Escape them to keep "one result, one line"
  -- true for the reader as well as for Lua.
  s = s:gsub("\194\133", "\\u0085")
  s = s:gsub("\226\128\168", "\\u2028")
  s = s:gsub("\226\128\169", "\\u2029")
  return s
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

-- Which palette entry best matches an opaque colour. Entries that cannot draw a
-- visible pixel are not candidates, however near they are.
--
-- Two kinds of entry are excluded. `spr.transparentColor` is an offset that means "no
-- pixel here" rather than a colour, so answering a colour question with it writes
-- nothing; and an entry whose own alpha is 0 draws nothing either, which is the same
-- outcome by a different route. Both used to win: a freshly created indexed sprite had
-- 256 entries of identical black, every one was equidistant from every request, the
-- first index won by being first, and index 0 is the transparent one. Red, white and
-- everything else resolved to "no pixel", so every draw landed invisibly and reported
-- the pixels it had written (#138).
--
-- Only ever reached with an opaque request: `to_pixel` and `rgba_to_px` both return
-- `spr.transparentColor` directly when alpha is 0, so a tool that means to erase still
-- gets the transparent index and never arrives here. That is what makes the exclusion
-- safe rather than a refusal to draw transparency.
--
-- Nearness is still only nearness: a palette with no red in it answers a request for
-- red with whatever it does have, which is what indexed mode means. The refusal below
-- is for the case where it has nothing at all to answer with, because then the only
-- available answer is the invisible one, and silence is how #138 stayed hidden.
local function nearest_index(spr, r, g, b)
  local pal = spr.palettes[1]
  -- Hoisted: a fill resolves a colour per pixel, so a property read inside this loop is
  -- paid palette-size times per pixel. It cannot change while the loop runs.
  local clear_at = spr.transparentColor
  local best, bestd = nil, nil
  for i = 0, #pal - 1 do
    if i ~= clear_at then
      local col = pal:getColor(i)
      if col.alpha > 0 then
        local dr, dg, db = col.red - r, col.green - g, col.blue - b
        local d = dr * dr + dg * dg + db * db
        if bestd == nil or d < bestd then bestd = d; best = i end
      end
    end
  end
  if best == nil then
    local what = (#pal == 1)
      and "its only entry is"
      or string.format("all %d of its entries are", #pal)
    error(string.format(
      "This indexed sprite's palette cannot draw a visible pixel: %s either transparent " ..
      "or the transparent index (%d), so #%02x%02x%02x could only be written as " ..
      "\"no pixel here\". Add a colour with add_palette_color, or set the whole palette " ..
      "with set_palette, then draw again.",
      -- Floored because "%x" on a float with a fractional part is itself an error in
      -- Lua 5.4, and an error path that errors reports nothing useful. Callers pass
      -- whole channels today; this keeps that from being load-bearing.
      what, clear_at, math.floor(r), math.floor(g), math.floor(b)), 0)
  end
  return best
end

-- What a declared ramp actually becomes on this sprite's palette.
--
-- On an indexed sprite a pixel is an offset, so a shading tool cannot write a colour the
-- palette does not hold: rgba_to_px sends it through nearest_index and it lands on the
-- nearest entry that can draw. That is what indexed mode means and refusing it would
-- make these tools unusable on exactly the sprites that most need a fixed palette. What
-- was wrong is that nothing said so, and two consequences are invisible in the result:
-- two ramp steps can resolve to one entry, so a shade between them changes nothing while
-- reporting the pixels it wrote, and palette_conformance stays at 1.0 throughout because
-- the colour it lands on is still a colour on the declared ramp (#145).
--
-- One nearest_index call per ramp entry, not per pixel, so this is free at any sprite
-- size. Measured against the sprite's own palette through the sprite's own resolver, so
-- it cannot drift from where the pixels actually go.
local function ramp_palette_state(spr, ramp)
  local pal = spr.palettes[1]

  -- nearest_index *errors* when no entry can draw, which is right for a tool trying to
  -- write and wrong here: this runs after the body has already succeeded, so raising
  -- would turn a completed call into a failure. A no-op shade on a sprite whose palette
  -- holds one transparent entry did exactly that, failing a call that had done nothing
  -- at all and therefore had nothing to fail about. Answered rather than asked.
  local drawable = 0
  for ix = 0, #pal - 1 do
    if ix ~= spr.transparentColor and pal:getColor(ix).alpha > 0 then
      drawable = drawable + 1
    end
  end
  if drawable == 0 then
    return { steps = {}, declared = #ramp, resolved = 0, exact = 0,
             undrawable_palette = true }
  end

  local steps, distinct, exact = {}, {}, 0
  local resolved = 0
  for i, c in ipairs(ramp) do
    local col = mkcolor(c)
    local index = nearest_index(spr, col.red, col.green, col.blue)
    local got = pal:getColor(index)
    local is_exact = (got.red == col.red and got.green == col.green
                      and got.blue == col.blue)
    if is_exact then exact = exact + 1 end
    if distinct[index] == nil then
      distinct[index] = true
      resolved = resolved + 1
    end
    steps[i] = { step = i, want = color_hex(col), index = index, got = color_hex(got),
                 exact = is_exact }
  end
  return { steps = steps, declared = #ramp, resolved = resolved, exact = exact }
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

-- What "nothing is drawn here" looks like as a raw byte of Image.bytes, for this
-- sprite's colour mode. Returns the stride between pixels, the 1-based offset within a
-- pixel of the byte that decides visibility, and the set of values of that byte which
-- mean empty.
--
-- One function rather than a copy per measurement, because every measurement below has
-- to answer this question the same way and two of them did not. `visible_count` excluded
-- a pixel held in a fully transparent palette entry; `Image:shrinkBounds`, which
-- `diff_sprites` used for the content box, counted it as content. The result reported
-- both numbers side by side, so one diff said "4 drawn pixels" beside a 5x5 box whose
-- corner nothing in the sprite could draw (#172). Sharing the definition is what makes
-- that disagreement unrepresentable rather than merely fixed.
local function clear_bytes(spr)
  local cm = spr.colorMode
  if cm == ColorMode.GRAY then
    -- graya: value, alpha.
    return 2, 2, { [0] = true }
  elseif cm == ColorMode.INDEXED then
    -- Indexed transparency is two separate things and both have to count: the sprite's
    -- transparent index, and any palette entry that is itself fully transparent. Testing
    -- only the first is the bug this server has already been bitten by once (#138). It
    -- is also where Image:shrinkBounds parts company with us: it honours the transparent
    -- index only, so a pixel held in a transparent palette entry counts as content to it
    -- and as nothing here.
    local clear = { [spr.transparentColor] = true }
    local pal = spr.palettes[1]
    for ix = 0, #pal - 1 do
      if pal:getColor(ix).alpha == 0 then clear[ix] = true end
    end
    return 1, 1, clear
  end
  -- rgba: r, g, b, alpha.
  return 4, 4, { [0] = true }
end

-- How many pixels of `img` would show, and the box that holds them, from one pass over
-- the byte buffer. The box is nil when nothing is drawn.
--
-- Every pixel's alpha sits at a fixed stride in Image.bytes, so measuring what is drawn
-- needs no getPixel and no px_to_rgba per pixel. Measured on this machine over a
-- 1024x1024 frame: 0.110us per pixel against 0.566us for the equivalent getPixel loop,
-- so about 5.2x. Reading a block at a time is the trick the frame hash uses: string.byte
-- one index at a time is the slow part, not the loop.
--
-- `shrinkBounds` is native and answers the box question in 0.0009us per pixel, which is
-- 120x cheaper than this, so the trade is real and it is worth being clear about what is
-- bought. Not speed: it honours the transparent index only, so what is paid for here is
-- the count and the box agreeing about one sprite.
local function visible_extent(spr, img)
  local stride, first, clear = clear_bytes(spr)
  local w, h = img.width, img.height
  local s = img.bytes
  local n = 0
  local minx, miny, maxx, maxy

  if #s ~= w * h * stride then
    -- Not the layout assumed above. Measure the slow, certain way rather than a wrong
    -- way: a box computed off a misread buffer is a confident wrong answer, and a
    -- confident wrong answer is what this whole helper exists to stop producing.
    for y = 0, h - 1 do
      for x = 0, w - 1 do
        local _, _, _, alpha = px_to_rgba(spr, img:getPixel(x, y))
        if alpha > 0 then
          n = n + 1
          if minx == nil or x < minx then minx = x end
          if maxx == nil or x > maxx then maxx = x end
          if miny == nil then miny = y end
          maxy = y
        end
      end
    end
  else
    -- 512 is a multiple of every stride above, so `first` stays aligned block to block.
    -- It is a byte count rather than a pixel count on purpose: string.byte returns one
    -- value per byte, and asking it for a few thousand at once is how you find Lua's
    -- result limit.
    --
    -- x and y are carried along rather than divided back out of the byte index: the
    -- deciding bytes are visited in raster order, so two increments and a compare per
    -- pixel beat a division, and that is most of why the box costs only about a quarter
    -- more than the bare count.
    local len, i = #s, 1
    local block = 512
    local x, y = 0, 0
    while i <= len do
      local j = math.min(i + block - 1, len)
      local t = table.pack(string.byte(s, i, j))
      for k = first, t.n, stride do
        if not clear[t[k]] then
          n = n + 1
          if minx == nil or x < minx then minx = x end
          if maxx == nil or x > maxx then maxx = x end
          -- y never decreases, so the first hit fixes the top edge and the last one
          -- fixes the bottom. Neither needs a comparison.
          if miny == nil then miny = y end
          maxy = y
        end
        x = x + 1
        if x >= w then x = 0; y = y + 1 end
      end
      i = j + 1
    end
  end

  if minx == nil then return 0, nil end
  return n, { x = minx, y = miny, width = maxx - minx + 1, height = maxy - miny + 1 }
end

-- Drawn pixels only, in the tightest loop that answers it.
--
-- Kept separate from `visible_extent` rather than discarding its box, because the one
-- caller that measures whole sprites rather than one frame is `set_color_mode`'s
-- verification, which is bounded at 33Mpx: paying the box's extra quarter there would
-- cost most of a second to compute a rectangle nothing reads. Both go through
-- `clear_bytes`, so they cannot drift about what empty means, which is the part that
-- was actually wrong.
local function visible_count(spr, img)
  local stride, first, clear = clear_bytes(spr)
  local s = img.bytes
  if #s ~= img.width * img.height * stride then
    -- Not the layout assumed above. Count the slow, certain way rather than a wrong way.
    local n = 0
    for y = 0, img.height - 1 do
      for x = 0, img.width - 1 do
        local _, _, _, alpha = px_to_rgba(spr, img:getPixel(x, y))
        if alpha > 0 then n = n + 1 end
      end
    end
    return n
  end

  local n, len, i = 0, #s, 1
  local block = 512
  while i <= len do
    local j = math.min(i + block - 1, len)
    local t = table.pack(string.byte(s, i, j))
    for k = first, t.n, stride do
      if not clear[t[k]] then n = n + 1 end
    end
    i = j + 1
  end
  return n
end

-- Drawn pixels across every frame of a sprite, flattened. The composite is what the
-- caller sees, so this is the number a conversion must not change.
local function visible_count_all_frames(spr)
  local n = 0
  for f = 1, #spr.frames do
    local flat = Image(spr.spec)
    flat:clear()
    flat:drawSprite(spr, f)
    n = n + visible_count(spr, flat)
  end
  return n
end

-- Alpha-composite colour (r,g,b) with coverage `cov` (0..1) over the pixel at
-- (x,y). On RGB sprites this anti-aliases; on indexed/gray it thresholds at 0.5.
local function blend_over(spr, img, x, y, r, g, b, cov)
  if cov <= 0 then return end
  if x < 0 or y < 0 or x >= img.width or y >= img.height then
    _px_clipped = _px_clipped + 1
    return
  end
  x, y = math.floor(x), math.floor(y)
  -- Checked here rather than by routing through `img_set`, which is defined further down
  -- the prelude and so is not in scope yet. Once, before both branches, because the
  -- indexed branch below returns without writing on low coverage and a mask refusal is
  -- not the same event as a coverage refusal.
  if masked_out(x, y) then return end
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
    _px_written = _px_written + 1
  elseif cov >= 0.5 then
    img:drawPixel(x, y, rgba_to_px(spr, r, g, b, 255))
    _px_written = _px_written + 1
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
  -- Recorded for the harness, which reports a declared ramp against an indexed palette
  -- after the body has run and has no other way to reach the sprite. The last one wins;
  -- the two tools that open a second sprite (stamp_file, extract_palette with
  -- from_image) take no ramp, so there is nothing to be ambiguous about yet.
  _sprite = spr

  -- A selection is NOT stored in the .aseprite file: reopen a sprite and it is empty
  -- again. Every tool call here is its own Aseprite run, so a selection is kept in a
  -- sidecar beside the sprite and reloaded on open, which is what lets it scope the
  -- edits that follow rather than dying with the process that made it.
  --
  -- ARG.use_selection == false opts out for one call. Whether a mask was applied is
  -- always reported, because an edit that silently touched a fraction of what the
  -- caller asked for is exactly the failure this codebase keeps turning up.
  if ARG.use_selection ~= false then
    local mask_path = tostring(path):gsub("%.[^./\\]+$", "") .. ".msk"
    if app.fs.isFile(mask_path) then
      app.command.LoadMask{ filename = mask_path }
      if not spr.selection.isEmpty then _sel = spr.selection end
    end
  end
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

-- ===== drawing primitives (operate on an Image, sprite-space coords) ======
local function img_set(img, x, y, px)
  if x >= 0 and y >= 0 and x < img.width and y < img.height then
    if masked_out(x, y) then return end
    img:drawPixel(math.floor(x), math.floor(y), px)
    _px_written = _px_written + 1
  else
    _px_clipped = _px_clipped + 1
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

-- The ellipse as offsets from its centre, with nothing said about where that centre is.
-- Two tools need the same shape placed differently: one centres it on a pixel, the other
-- fits it to a bounding box and duplicates the middle row and column when a side is even,
-- which is how an even diameter is drawn by hand. Sharing the offsets is what keeps the
-- two forms the same ellipse rather than two rasterisers that nearly agree.
local function ellipse_offsets(rx, ry, filled)
  rx, ry = math.floor(math.abs(rx)), math.floor(math.abs(ry))
  if rx == 0 or ry == 0 then
    return bresenham_points(-rx, -ry, rx, ry)
  end
  local pts, n = {}, 0
  local function emit(dx, dy) n = n + 1; pts[n] = { dx, dy } end
  -- Filled and outline are one shape rendered two ways. The fill used to have its own
  -- formula, a per-row half-width of floor(rx * sqrt(1 - dy^2/ry^2) + 0.5), which at the
  -- pole gives 0 and drew a disc that came to a one-pixel point while the outline of the
  -- same call had a five-pixel flat top. Now the midpoint pass runs either way, and the
  -- fill is the span between the edges it found.
  local half = filled and {} or nil
  local rx2, ry2 = rx * rx, ry * ry
  local x, y = 0, ry
  local dpx, dpy = 0, 2 * rx2 * y
  local function plot4(ox, oy)
    if filled then
      local row = (oy < 0) and -oy or oy
      if half[row] == nil or ox > half[row] then half[row] = ox end
    else
      emit(ox, oy); emit(-ox, oy); emit(ox, -oy); emit(-ox, -oy)
    end
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
  if filled then
    for dy = -ry, ry do
      local hw = half[(dy < 0) and -dy or dy] or 0
      for dx = -hw, hw do emit(dx, dy) end
    end
  end
  return pts
end

local function draw_ellipse_img(img, cx, cy, rx, ry, px, filled)
  cx, cy = math.floor(cx), math.floor(cy)
  for _, pt in ipairs(ellipse_offsets(rx, ry, filled)) do
    img_set(img, cx + pt[1], cy + pt[2], px)
  end
end

local function flood_fill_img(img, x, y, px)
  x, y = math.floor(x), math.floor(y)
  if x < 0 or y < 0 or x >= img.width or y >= img.height then return end
  local target = img:getPixel(x, y)
  if target == px then return end
  -- A masked pixel is a wall, not a hole. Not painting it is only half the answer: the
  -- fill must not spread *through* it either, or it leaks around the selection and paints
  -- the far side of whatever the region was meant to protect.
  --
  -- Tracked so each refused pixel counts once. A masked pixel is never painted, so it
  -- keeps matching `target` and can be reached again from each of its four neighbours,
  -- which would otherwise report up to four times the boundary.
  local blocked = {}
  local stack = { { x, y } }
  while #stack > 0 do
    local p = stack[#stack]; stack[#stack] = nil
    local px0, py0 = p[1], p[2]
    if px0 >= 0 and py0 >= 0 and px0 < img.width and py0 < img.height
       and img:getPixel(px0, py0) == target then
      if _sel ~= nil and not _sel:contains(px0, py0) then
        if blocked[py0] == nil then blocked[py0] = {} end
        if not blocked[py0][px0] then
          blocked[py0][px0] = true
          _px_masked = _px_masked + 1
        end
      else
        img:drawPixel(px0, py0, px)
        _px_written = _px_written + 1
        stack[#stack + 1] = { px0 + 1, py0 }
        stack[#stack + 1] = { px0 - 1, py0 }
        stack[#stack + 1] = { px0, py0 + 1 }
        stack[#stack + 1] = { px0, py0 - 1 }
      end
    end
  end
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
  if layer.isTilemap then
    error("Layer '" .. layer.name .. "' is a tilemap layer; use the tilemap tools " ..
          "(set_tile, paint_tile_pixels, fill_tilemap, …) instead of pixel drawing.")
  end
  local img = Image(spr.spec)
  img:clear()
  local cel = layer:cel(framenum)
  if cel ~= nil and cel.image ~= nil then
    img:drawImage(cel.image, cel.position)
  end
  return img
end

-- Which other frames share this frame's cel image, by image identity, which is the
-- same test `get_cel` reports `linked_with` from.
local function linked_frames(spr, layer, framenum)
  local cel = layer:cel(framenum)
  if cel == nil or cel.image == nil then return {} end
  local id, out, n = cel.image.id, {}, 0
  for f = 1, #spr.frames do
    if f ~= framenum then
      local other = layer:cel(f)
      if other ~= nil and other.image ~= nil and other.image.id == id then
        n = n + 1
        out[n] = f
      end
    end
  end
  return out
end

-- Write an edited full-canvas image back to a layer/frame cel.
--
-- Linked cels share one CelData, which holds the image, so assigning `cel.image` on one
-- of them writes it to every frame in the group. That is not a bug: it is what linking
-- means here and in Aseprite itself, where painting a linked cel paints every frame
-- sharing it. `link_cels` says so ("editing any of them edits all of them"), and
-- `test_an_edit_to_one_linked_frame_reaches_the_others_and_no_one_else` is the test that
-- would notice if linking ever quietly became copying.
--
-- What was wrong is that nothing said so. `draw_pixels(..., frame=2)` on four linked
-- frames changed all four and returned `frame: 2, pixels_written: 1`, so the only way to
-- know was to have called `get_cel` beforehand and thought about it. The write still
-- propagates; the frames it reached are now reported (#148).
local function commit_image(spr, layer, framenum, img)
  local cel = layer:cel(framenum)
  if cel == nil then
    spr:newCel(layer, framenum, img, Point(0, 0))
    return
  end
  local shared = linked_frames(spr, layer, framenum)
  if #shared > 0 then
    _linked_hit_frame, _linked_hit_others = framenum, shared
  end
  cel.image = img
  cel.position = Point(0, 0)
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
      -- 0 is how the file says "play forever". Reported because a tag that plays a set
      -- number of times is a one-shot, and nothing else in the sprite says so.
      repeats = tg.repeats or 0,
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
    -- A slice's colour and its user-data are part of the slice. Leaving them out meant
    -- a caller could write structured data with add_slice and had no way to read it
    -- back except by writing an export file and parsing that, and list_slices showed
    -- the same thing for a slice with data and one without. It also meant the export
    -- path needed a second slice reader of its own, which is how two readers of the
    -- same thing drift apart.
    s.color = color_hex(sl.color)
    if sl.data ~= nil and sl.data ~= "" then s.data = sl.data end
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


def assemble_script(body: str, args: dict | None = None, *, nonce: str) -> str:
    """Wrap a tool body with the ARG table, the prelude, and the pcall harness.

    `nonce` is required, and must come from `new_nonce()` per run. The caller keeps it
    to parse the output; see `new_nonce` for why a fixed sentinel is not safe.

    The error branch json_encodes the message rather than printing it raw. Lua error
    text embeds caller data (a missing layer name, an unparseable colour), so printing
    `tostring(_err)` unescaped puts an unescaped newline on stdout and splits one
    logical error across lines.
    """
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
        # Attached here rather than by each tool, so every pixel-writing tool reports
        # what it actually did. Only when something was touched: a tool that writes no
        # pixels should not grow a "0" that reads as a claim about pixels.
        #
        # `_px_masked` is part of that test and not only read inside it, which it was not
        # at first. A write whose selection masked out *every* pixel left all three other
        # counters at zero, so the gate skipped the whole block and took
        # `pixels_outside_selection` with it: the result came back `ok: true`, with
        # `selection_applied` and no count anywhere, in exactly the case where the count is
        # the entire answer. A mask that ate ten pixels is not an absence of pixels.
        "  if type(RESULT) == 'table' and\n"
        "     (_px_written > 0 or _px_clipped > 0 or _px_skipped > 0\n"
        "      or _px_masked > 0) then\n"
        "    RESULT.pixels_written = _px_written\n"
        "    if _px_clipped > 0 then RESULT.pixels_clipped = _px_clipped end\n"
        "    if _px_skipped > 0 then RESULT.pixels_skipped = _px_skipped end\n"
        "    if _px_masked > 0 then RESULT.pixels_outside_selection = _px_masked end\n"
        "  end\n"
        # Reported whenever a mask was active, even if it let everything through: the
        # caller needs to know an edit was scoped rather than infer it from counts. An
        # edit that silently touched a fraction of what was asked for is precisely the
        # failure mode this project keeps finding.
        "  if type(RESULT) == 'table' and _sel ~= nil then\n"
        "    RESULT.selection_applied = true\n"
        "  end\n"
        # An edit to a linked cel reaches every frame sharing it, which is the point of
        # linking and is not visible in the frame number the caller passed. Attached here
        # for the same reason the pixel counters are: so every tool that commits an image
        # says what it touched without each one having to remember to.
        "  if type(RESULT) == 'table' and _linked_hit_frame ~= nil then\n"
        "    RESULT.linked_frames_also_changed = _linked_hit_others\n"
        "  end\n"
        # A ramp declared against an indexed palette is resolved, not written: every
        # entry lands on the nearest palette offset that can draw. Attached here because
        # ten tools take a `ramp` and the measurement is the same question for all of
        # them, so putting it in each body would be ten chances to leave it out. The
        # judgement is Python, in core.indexed; this is only the measurement.
        #
        # Keyed on ARG.ramp by convention, which is the convention every ramp tool
        # already follows (a list of parsed colours under exactly that name). A meta-test
        # pins it, so a new tool cannot quietly opt out by naming its argument something
        # else.
        # pcall'd, and that is not defensive habit. This runs *after* the body has
        # succeeded and outside the pcall that guards it, so anything raising in here
        # aborts the script before RESULT is ever printed: a reporting path would turn a
        # completed operation into a failure with no result at all. It has already
        # happened once, when nearest_index refused a palette with nothing drawable
        # during a shade that had written nothing. A measurement that cannot be taken is
        # worth less than the call it describes.
        "  if type(RESULT) == 'table' and _sprite ~= nil and\n"
        "     _sprite.colorMode == ColorMode.INDEXED and\n"
        "     type(ARG.ramp) == 'table' and #ARG.ramp > 0 then\n"
        "    local _rok, _rstate = pcall(ramp_palette_state, _sprite, ARG.ramp)\n"
        "    if _rok then RESULT.ramp_on_palette = _rstate end\n"
        "  end\n"
        f'  print("{result_prefix(nonce)}" .. json_encode(RESULT))\n'
        "else\n"
        f'  print("{error_prefix(nonce)}" .. json_encode(tostring(_err)))\n'
        "end\n"
    )
