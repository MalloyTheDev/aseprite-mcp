"""Selections: scope edits to a region instead of a whole layer.

Without a region, every operation is layer-wide, which is why shading a sprite flattens
its materials: one ramp applied to a whole layer turns steel, brass and leather into the
same colours, while three region-scoped calls keep all three.

**How a selection survives between calls.** It is not stored in the .aseprite file. Open
a sprite that had a selection and `selection.isEmpty` is true again. Since every tool call
here is its own Aseprite process, a selection would otherwise never outlive the call that
made it. So it is written to a `.msk` sidecar beside the sprite, which Aseprite's own
SaveMask and LoadMask round-trip exactly, holes and all, in well under a hundred bytes.
`open_sprite` loads it, so an active selection scopes every later edit until it is
cleared, which is how an image editor behaves.

Two consequences worth knowing. The sidecar is state outside the sprite, so copying or
renaming a sprite leaves its selection behind, and `deselect` is a real step rather than
a formality. And every result that touched pixels reports `selection_applied`, because an
edit that silently affected a fraction of what was asked for is worse than one that
refused.
"""

from __future__ import annotations

from pathlib import Path

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import MAX_PIXEL_LIST_LENGTH, check_list_length
from ..core.paths import selection_sidecar
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

_SHAPES = ("rect", "ellipse", "polygon")
_MODES = ("replace", "add", "subtract", "intersect")
_MODIFY_OPS = ("expand", "contract", "border")


def mask_path_for(sprite_path: Path) -> Path:
    """The sidecar that holds this sprite's selection.

    Defined in `core.paths` alongside the rest of the path policy, because the sprite tools
    need the same answer: replacing a sprite has to throw its selection away, and two
    modules guessing at the same suffix is how that stops being true.
    """
    return selection_sidecar(sprite_path)


def _mask_lua(sprite_path: Path) -> str:
    return lua_path(mask_path_for(sprite_path))


# Shared tail: persist whatever the selection now is, or remove the sidecar when the
# selection was cleared, so an empty selection never lingers as a stale file.
_SAVE_MASK = """
    if spr.selection.isEmpty then
      if app.fs.isFile(ARG.mask) then os.remove(ARG.mask) end
      RESULT.selection = false
    else
      app.command.SaveMask{ filename = ARG.mask }
      local b = spr.selection.bounds
      RESULT.selection = true
      RESULT.bounds = { x = b.x, y = b.y, width = b.width, height = b.height }
    end
    RESULT.ok = true
    RESULT.filename = spr.filename
"""


@mcp.tool()
def select_region(
    filename: str,
    shape: str = "rect",
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    points: list[dict] | None = None,
    mode: str = "replace",
) -> dict:
    """Select a region, so later edits only affect that area.

    The selection persists until `deselect`, and every pixel-writing tool honours it.
    There is no per-call override: to draw outside the selection, clear it first. Tools
    that wrote fewer pixels than asked report `selection_applied` and
    `pixels_outside_selection`, so a forgotten selection shows up in the result rather
    than as a mysteriously incomplete edit.

    Args:
        shape: "rect", "ellipse" (both use x/y/width/height) or "polygon" (uses points).
        x, y, width, height: The region. width/height default to the rest of the canvas.
        points: For "polygon", a list of {"x": int, "y": int}, at least 3.
        mode: "replace" the selection, or "add"/"subtract"/"intersect" with the current
            one. Building a selection from several shapes is how you scope an edit to
            an awkward area, such as everything except a character's eyes.
    """
    if shape not in _SHAPES:
        raise ValidationFailed(f"shape must be one of {list(_SHAPES)}.")
    if mode not in _MODES:
        raise ValidationFailed(f"mode must be one of {list(_MODES)}.")
    if shape == "polygon":
        if not points or len(points) < 3:
            raise ValidationFailed("polygon needs at least 3 points.")
        check_list_length("points", points, MAX_PIXEL_LIST_LENGTH)

    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "mask": _mask_lua(src),
        "shape": shape,
        "mode": mode,
        "x": int(x), "y": int(y), "width": width, "height": height,
        "points": [{"x": int(p["x"]), "y": int(p["y"])} for p in (points or [])],
        # This tool defines the selection, so it must not be scoped by the one it is
        # replacing. add/subtract/intersect read the current selection explicitly below.
        "use_selection": False,
    }
    body = """
    local spr = open_sprite(ARG.src)
    local rx, ry = ARG.x, ARG.y
    local rw = ARG.width or (spr.width - rx)
    local rh = ARG.height or (spr.height - ry)

    -- Start from the existing selection for every mode except replace, which is why the
    -- sidecar is loaded here by hand rather than by open_sprite.
    if ARG.mode ~= "replace" and app.fs.isFile(ARG.mask) then
      app.command.LoadMask{ filename = ARG.mask }
    elseif ARG.mode == "replace" then
      spr.selection:deselect()
    end

    local shape_sel
    if ARG.shape == "polygon" then
      -- Aseprite's Selection has no polygon primitive, so the polygon is rasterised
      -- into a mask image and the covered pixels are unioned in. Slower than a
      -- rectangle and the only way to express a non-convex region.
      local minx, miny, maxx, maxy = math.huge, math.huge, -math.huge, -math.huge
      for _, p in ipairs(ARG.points) do
        if p.x < minx then minx = p.x end
        if p.y < miny then miny = p.y end
        if p.x > maxx then maxx = p.x end
        if p.y > maxy then maxy = p.y end
      end
      shape_sel = Selection()
      for yy = math.max(0, miny), math.min(spr.height - 1, maxy) do
        local crossings = {}
        local n = #ARG.points
        for i = 1, n do
          local a = ARG.points[i]
          local b = ARG.points[(i % n) + 1]
          if (a.y <= yy and b.y > yy) or (b.y <= yy and a.y > yy) then
            local t = (yy - a.y) / (b.y - a.y)
            crossings[#crossings + 1] = a.x + t * (b.x - a.x)
          end
        end
        table.sort(crossings)
        for i = 1, #crossings - 1, 2 do
          local x0 = math.max(0, math.floor(crossings[i] + 0.5))
          local x1 = math.min(spr.width - 1, math.floor(crossings[i + 1] + 0.5))
          if x1 >= x0 then
            shape_sel:add(Selection(Rectangle(x0, yy, x1 - x0 + 1, 1)))
          end
        end
      end
    elseif ARG.shape == "ellipse" then
      -- Also rasterised: Selection takes rectangles, so an ellipse is built row by row
      -- from the ellipse equation.
      shape_sel = Selection()
      local cx, cy = rx + (rw - 1) / 2, ry + (rh - 1) / 2
      local ax, by = rw / 2, rh / 2
      for yy = math.max(0, ry), math.min(spr.height - 1, ry + rh - 1) do
        local dy = (yy - cy) / by
        local inside = 1 - dy * dy
        if inside >= 0 then
          local half = ax * math.sqrt(inside)
          local x0 = math.max(0, math.ceil(cx - half))
          local x1 = math.min(spr.width - 1, math.floor(cx + half))
          if x1 >= x0 then
            shape_sel:add(Selection(Rectangle(x0, yy, x1 - x0 + 1, 1)))
          end
        end
      end
    else
      shape_sel = Selection(Rectangle(rx, ry, rw, rh))
    end

    if ARG.mode == "replace" or ARG.mode == "add" then
      spr.selection:add(shape_sel)
    elseif ARG.mode == "subtract" then
      spr.selection:subtract(shape_sel)
    else
      spr.selection:intersect(shape_sel)
    end
""" + _SAVE_MASK
    return run_lua(body, args)


@mcp.tool()
def select_by_color(
    filename: str,
    color: str,
    tolerance: int = 0,
    frame: int = 1,
) -> dict:
    """Select every pixel matching a colour, the magic-wand selection.

    The usual way to scope an edit to one material: select the armour's base colour and
    every later operation touches only the armour. Pair it with `shift_along_ramp` to
    shade one material without disturbing its neighbours.

    Args:
        color: The colour to match.
        tolerance: 0 matches exactly. Higher values also catch nearby colours, which is
            useful on artwork that was anti-aliased or converted from a photo.
        frame: Which frame to sample, 1-based.

    Matching is done on the composited image, so what is selected is what you see rather
    than what happens to be on the active layer.
    """
    if tolerance < 0 or tolerance > 255:
        raise ValidationFailed("tolerance must be between 0 and 255.")

    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "mask": _mask_lua(src),
        "color": parse_color(color),
        "tolerance": int(tolerance),
        "frame": int(frame),
        "use_selection": False,
    }
    body = """
    local spr = open_sprite(ARG.src)
    app.frame = spr.frames[math.max(1, math.min(#spr.frames, ARG.frame))]
    local c = ARG.color
    app.command.MaskByColor{
      color = Color{ r = c.r, g = c.g, b = c.b, a = c.a },
      tolerance = ARG.tolerance,
    }
""" + _SAVE_MASK
    return run_lua(body, args)


@mcp.tool()
def modify_selection(filename: str, op: str, quantity: int = 1) -> dict:
    """Grow, shrink, or outline the current selection.

    Args:
        op: "expand" grows by `quantity` pixels, "contract" shrinks, "border" replaces
            the selection with a band of that width around its edge. A border selection
            is how you scope an outline or a contact shadow to where two forms meet.
        quantity: How many pixels, at least 1.
    """
    if op not in _MODIFY_OPS:
        raise ValidationFailed(f"op must be one of {list(_MODIFY_OPS)}.")
    if quantity < 1:
        raise ValidationFailed("quantity must be at least 1.")

    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "mask": _mask_lua(src),
        "op": op,
        "quantity": int(quantity),
        "use_selection": False,
    }
    body = """
    local spr = open_sprite(ARG.src)
    if not app.fs.isFile(ARG.mask) then
      error("There is no selection to modify. Call select_region or select_by_color first.")
    end
    app.command.LoadMask{ filename = ARG.mask }
    app.command.ModifySelection{ modifier = ARG.op, quantity = ARG.quantity }
""" + _SAVE_MASK
    return run_lua(body, args)


@mcp.tool()
def invert_selection(filename: str) -> dict:
    """Swap what is selected for what is not.

    Selecting a character's silhouette and inverting gives the background, which is
    usually easier than describing the background directly.
    """
    src = resolve_path(filename)
    args = {"src": lua_path(src), "mask": _mask_lua(src), "use_selection": False}
    body = """
    local spr = open_sprite(ARG.src)
    if app.fs.isFile(ARG.mask) then
      app.command.LoadMask{ filename = ARG.mask }
    end
    app.command.InvertMask()
""" + _SAVE_MASK
    return run_lua(body, args)


@mcp.tool()
def deselect(filename: str) -> dict:
    """Clear the selection, so edits affect the whole layer again.

    A real step, not a formality: the selection lives in a sidecar beside the sprite and
    persists across calls, so leaving one active will silently scope every later edit.
    """
    src = resolve_path(filename)
    mask = mask_path_for(src)
    existed = mask.exists()
    if existed:
        mask.unlink()
    return {
        "ok": True,
        "filename": str(src),
        "selection": False,
        "cleared": existed,
    }


@mcp.tool()
def get_selection(filename: str) -> dict:
    """Describe the current selection: whether there is one, and what it covers.

    Returns `bounds`, the pixel `area` actually inside the selection, and a `map` of
    the selected region using `#` for selected and `.` for not, in the same shape
    `get_pixels(format="map")` uses. The map is capped, and omitted for a selection
    larger than the cap, since a wall of characters is not feedback.

    Worth calling before a large edit: a selection you forgot about is the difference
    between changing what you meant and changing a corner of it.
    """
    src = resolve_path(filename)
    args = {"src": lua_path(src), "mask": _mask_lua(src), "use_selection": False}
    body = """
    local spr = open_sprite(ARG.src)
    if not app.fs.isFile(ARG.mask) then
      RESULT = { ok = true, filename = spr.filename, selection = false }
      return
    end
    app.command.LoadMask{ filename = ARG.mask }
    local sel = spr.selection
    if sel.isEmpty then
      RESULT = { ok = true, filename = spr.filename, selection = false }
      return
    end
    local b = sel.bounds
    local area = 0
    for yy = b.y, b.y + b.height - 1 do
      for xx = b.x, b.x + b.width - 1 do
        if sel:contains(xx, yy) then area = area + 1 end
      end
    end
    RESULT = {
      ok = true, filename = spr.filename, selection = true,
      bounds = { x = b.x, y = b.y, width = b.width, height = b.height },
      area = area,
    }
    -- 4096 matches the get_pixels read cap, for the same reason: past that the answer
    -- is too big to be read and too big to be useful.
    if b.width * b.height <= 4096 then
      local rows = {}
      for yy = b.y, b.y + b.height - 1 do
        local row = {}
        for xx = b.x, b.x + b.width - 1 do
          row[#row + 1] = sel:contains(xx, yy) and "#" or "."
        end
        rows[#rows + 1] = table.concat(row)
      end
      RESULT.map = rows
    end
    """
    return run_lua(body, args)
