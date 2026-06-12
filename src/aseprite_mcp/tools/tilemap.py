"""Tilemap & tileset support (Aseprite 1.3+).

A tilemap layer paints a grid of *tiles* drawn from a *tileset*. Tile index 0 is
always the empty tile. Workflow:
  1. `create_tilemap_layer` (sets the tile size and an empty map sized to the canvas)
  2. `add_tile` / `fill_tile` / `paint_tile_pixels` to define the tileset artwork
  3. `set_tile` / `set_tiles` / `fill_tilemap` to place tiles on the grid
  4. `get_tilemap` to read back the grid of indices
"""

from __future__ import annotations

from ..app import mcp
from ..core.runner import run_lua
from .common import lua_path, parse_color, resolve_path

# Common preamble: open sprite, resolve a tilemap layer, grab tileset + frame.
_TM = """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if not layer.isTilemap then error("Layer '" .. layer.name .. "' is not a tilemap layer.") end
local ts = layer.tileset
local framenum = clamp_frame(spr, ARG.frame)
"""

# Get an editable tilemap cel image (existing copy, or a fresh canvas-sized map).
_TM_CEL = """
local cel = layer:cel(framenum)
local tw = ts.grid.tileSize.width
local th = ts.grid.tileSize.height
local tm
if cel ~= nil and cel.image ~= nil then
  tm = Image(cel.image)
else
  local cols = math.max(1, math.ceil(spr.width / tw))
  local rows = math.max(1, math.ceil(spr.height / th))
  tm = Image(ImageSpec{ width = cols, height = rows, colorMode = ColorMode.TILEMAP })
  tm:clear()
end
"""

_TM_COMMIT = """
if cel ~= nil then cel.image = tm else spr:newCel(layer, framenum, tm, Point(0, 0)) end
save_sprite(spr)
"""


@mcp.tool()
def create_tilemap_layer(
    filename: str,
    name: str,
    tile_width: int = 16,
    tile_height: int = 16,
    columns: int | None = None,
    rows: int | None = None,
    frame: int = 1,
) -> dict:
    """Create a tilemap layer with an empty grid.

    Args:
        name: Layer name.
        tile_width, tile_height: Tile size in pixels (sets the sprite grid).
        columns, rows: Grid size in tiles (default: enough to cover the canvas).
    """
    args = {
        "src": lua_path(resolve_path(filename)),
        "name": name,
        "tw": max(1, int(tile_width)),
        "th": max(1, int(tile_height)),
        "columns": columns,
        "rows": rows,
        "frame": int(frame),
    }
    body = """
    local spr = open_sprite(ARG.src)
    spr.gridBounds = Rectangle(0, 0, ARG.tw, ARG.th)
    app.command.NewLayer{ tilemap = true }
    local layer = app.activeLayer
    layer.name = ARG.name
    local cols = ARG.columns or math.max(1, math.ceil(spr.width / ARG.tw))
    local rows = ARG.rows or math.max(1, math.ceil(spr.height / ARG.th))
    local tm = Image(ImageSpec{ width = cols, height = rows, colorMode = ColorMode.TILEMAP })
    tm:clear()
    local framenum = clamp_frame(spr, ARG.frame)
    spr:newCel(layer, framenum, tm, Point(0, 0))
    save_sprite(spr)
    RESULT = { ok = true, layer = layer.name, columns = cols, rows = rows,
               tileWidth = ARG.tw, tileHeight = ARG.th, tileCount = #layer.tileset }
    """
    return run_lua(body, args)


@mcp.tool()
def add_tile(filename: str, layer: str, color: str | None = None, frame: int = 1) -> dict:
    """Add a new tile to the layer's tileset (optionally filled with a solid colour).
    Returns the new tile's index."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color) if color else None,
    }
    body = _TM + """
    local t = spr:newTile(ts)
    if ARG.color ~= nil then t.image:clear(to_pixel(spr, ARG.color)) end
    save_sprite(spr)
    RESULT = { ok = true, index = t.index, tileCount = #ts }
    """
    return run_lua(body, args)


@mcp.tool()
def fill_tile(filename: str, layer: str, tile_index: int, color: str, frame: int = 1) -> dict:
    """Fill an existing tile's artwork with a solid colour."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "index": int(tile_index), "color": parse_color(color),
    }
    body = _TM + """
    if ARG.index < 0 or ARG.index >= #ts then error("No tile at index " .. ARG.index) end
    ts:tile(ARG.index).image:clear(to_pixel(spr, ARG.color))
    save_sprite(spr)
    RESULT = { ok = true, index = ARG.index }
    """
    return run_lua(body, args)


@mcp.tool()
def paint_tile_pixels(
    filename: str,
    layer: str,
    tile_index: int,
    pixels: list[dict],
    color: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw individual pixels into a tile's artwork (tile-local coordinates).

    pixels: list of {"x", "y", "color"?}; falls back to the shared `color`.
    """
    if not pixels:
        raise ValueError("pixels must be non-empty.")
    default = parse_color(color) if color else None
    lua_pixels = []
    for p in pixels:
        item = {"x": int(p["x"]), "y": int(p["y"])}
        if p.get("color") is not None:
            item["c"] = parse_color(p["color"])
        elif default is None:
            raise ValueError("A pixel lacks its own colour and no shared `color` was given.")
        lua_pixels.append(item)
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "index": int(tile_index), "color": default, "pixels": lua_pixels,
    }
    body = _TM + """
    if ARG.index < 0 or ARG.index >= #ts then error("No tile at index " .. ARG.index) end
    local im = ts:tile(ARG.index).image
    local default = nil
    if ARG.color ~= nil then default = to_pixel(spr, ARG.color) end
    for _, p in ipairs(ARG.pixels) do
      local px = default
      if p.c ~= nil then px = to_pixel(spr, p.c) end
      if p.x >= 0 and p.y >= 0 and p.x < im.width and p.y < im.height then
        im:drawPixel(p.x, p.y, px)
      end
    end
    save_sprite(spr)
    RESULT = { ok = true, index = ARG.index }
    """
    return run_lua(body, args)


@mcp.tool()
def set_tile(
    filename: str, layer: str, column: int, row: int, tile_index: int, frame: int = 1
) -> dict:
    """Place a tile (by tileset index, 0 = empty) at grid cell (column, row)."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "col": int(column), "row": int(row), "index": int(tile_index),
    }
    body = _TM + _TM_CEL + """
    if ARG.index < 0 or ARG.index >= #ts then error("No tile at index " .. ARG.index) end
    if ARG.col < 0 or ARG.row < 0 or ARG.col >= tm.width or ARG.row >= tm.height then
      error("Cell (" .. ARG.col .. "," .. ARG.row .. ") is outside the " ..
            tm.width .. "x" .. tm.height .. " tilemap.")
    end
    tm:drawPixel(ARG.col, ARG.row, ARG.index)
    """ + _TM_COMMIT + """
    RESULT = { ok = true, column = ARG.col, row = ARG.row, index = ARG.index }
    """
    return run_lua(body, args)


@mcp.tool()
def set_tiles(filename: str, layer: str, tiles: list[dict], frame: int = 1) -> dict:
    """Place many tiles at once. tiles: list of {"column", "row", "index"}."""
    if not tiles:
        raise ValueError("tiles must be non-empty.")
    lua_tiles = [
        {"col": int(t["column"]), "row": int(t["row"]), "index": int(t["index"])}
        for t in tiles
    ]
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame), "tiles": lua_tiles,
    }
    body = _TM + _TM_CEL + """
    for _, t in ipairs(ARG.tiles) do
      if t.index >= 0 and t.index < #ts
         and t.col >= 0 and t.row >= 0 and t.col < tm.width and t.row < tm.height then
        tm:drawPixel(t.col, t.row, t.index)
      end
    end
    """ + _TM_COMMIT + """
    RESULT = { ok = true, placed = #ARG.tiles }
    """
    return run_lua(body, args)


@mcp.tool()
def fill_tilemap(filename: str, layer: str, tile_index: int, frame: int = 1) -> dict:
    """Fill the entire tilemap grid with a single tile index."""
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame), "index": int(tile_index),
    }
    body = _TM + _TM_CEL + """
    if ARG.index < 0 or ARG.index >= #ts then error("No tile at index " .. ARG.index) end
    for r = 0, tm.height - 1 do
      for c = 0, tm.width - 1 do tm:drawPixel(c, r, ARG.index) end
    end
    """ + _TM_COMMIT + """
    RESULT = { ok = true, columns = tm.width, rows = tm.height, index = ARG.index }
    """
    return run_lua(body, args)


@mcp.tool()
def get_tilemap(filename: str, layer: str, frame: int = 1) -> dict:
    """Read the tilemap as a 2D grid of tile indices, plus tile size and count."""
    args = {"src": lua_path(resolve_path(filename)), "layer": layer, "frame": int(frame)}
    body = _TM + """
    local cel = layer:cel(framenum)
    if cel == nil or cel.image == nil then
      RESULT = { columns = 0, rows = 0, tileCount = #ts, tiles = {} }
      return
    end
    local tm = cel.image
    local grid = {}
    for r = 0, tm.height - 1 do
      local rowt = {}
      for c = 0, tm.width - 1 do rowt[c + 1] = app.pixelColor.tileI(tm:getPixel(c, r)) end
      grid[r + 1] = rowt
    end
    RESULT = {
      columns = tm.width, rows = tm.height, tileCount = #ts,
      tileWidth = ts.grid.tileSize.width, tileHeight = ts.grid.tileSize.height,
      tiles = grid,
    }
    """
    return run_lua(body, args)
