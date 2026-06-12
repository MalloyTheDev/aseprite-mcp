"""Inspection & preview: structured info, a visual PNG preview, raw pixels, listing."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import Image

from .. import config
from ..app import mcp
from ..runner import AsepriteError, run_cli, run_lua
from .common import lua_path, resolve_path


@mcp.tool()
def get_sprite_info(filename: str) -> dict:
    """Return structured info about a sprite: size, colour mode, frames (with
    durations), the full layer tree (names, opacity, blend mode, visibility),
    animation tags, and palette size."""
    src = resolve_path(filename)
    body = """
    local spr = open_sprite(ARG.src)
    RESULT = sprite_info(spr)
    """
    info = run_lua(body, {"src": lua_path(src)})
    info["path"] = str(src)
    return info


@mcp.tool()
def render_preview(filename: str, frame: int = 1, scale: int = 8) -> Image:
    """Render a single frame to a PNG and return it as an image you can view.

    Use this to *see* your work. frame is 1-based; scale enlarges small sprites
    (default 8x) so individual pixels are visible.
    """
    src = resolve_path(filename)
    if not src.exists():
        raise AsepriteError(f"No such sprite: {src}")
    scale = max(1, min(int(scale), 32))
    f0 = max(0, int(frame) - 1)

    fd, out = tempfile.mkstemp(suffix=".png", prefix="asemcp_prev_")
    os.close(fd)
    try:
        run_cli([
            str(src),
            "--frame-range", f"{f0},{f0}",
            "--scale", str(scale),
            "--save-as", out,
        ])
        data = Path(out).read_bytes()
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    return Image(data=data, format="png")


@mcp.tool()
def get_pixels(
    filename: str,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    frame: int = 1,
) -> dict:
    """Read the composited (all visible layers) pixel colours of a region.

    Returns rows of "#RRGGBBAA" hex strings. The region is capped at 64x64
    (4096 pixels) per call to keep responses small — read in tiles for bigger areas.
    """
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "x": int(x),
        "y": int(y),
        "width": width,
        "height": height,
        "frame": int(frame),
    }
    body = """
    local spr = open_sprite(ARG.src)
    local framenum = clamp_frame(spr, ARG.frame)
    local x0 = ARG.x
    local y0 = ARG.y
    local w = ARG.width or (spr.width - x0)
    local h = ARG.height or (spr.height - y0)
    if w * h > 4096 then
      error("Region too large (" .. (w * h) .. " px). Max 4096 (e.g. 64x64) per call.")
    end
    local function px_hex(px)
      local cm = spr.colorMode
      local r, g, b, a
      if cm == ColorMode.RGB then
        r = app.pixelColor.rgbaR(px); g = app.pixelColor.rgbaG(px)
        b = app.pixelColor.rgbaB(px); a = app.pixelColor.rgbaA(px)
      elseif cm == ColorMode.GRAY then
        local v = app.pixelColor.grayaV(px)
        r = v; g = v; b = v; a = app.pixelColor.grayaA(px)
      else
        local col = spr.palettes[1]:getColor(px)
        r = col.red; g = col.green; b = col.blue; a = col.alpha
      end
      return string.format("#%02x%02x%02x%02x", r, g, b, a)
    end
    local img = Image(spr.spec)
    img:clear()
    img:drawSprite(spr, framenum)
    local rows = {}
    for yy = 0, h - 1 do
      local row = {}
      for xx = 0, w - 1 do
        local sx, sy = x0 + xx, y0 + yy
        if sx >= 0 and sy >= 0 and sx < img.width and sy < img.height then
          row[xx + 1] = px_hex(img:getPixel(sx, sy))
        else
          row[xx + 1] = "#00000000"
        end
      end
      rows[yy + 1] = row
    end
    RESULT = { x = x0, y = y0, width = w, height = h, frame = framenum, pixels = rows }
    """
    return run_lua(body, args)


@mcp.tool()
def list_sprites() -> dict:
    """List sprite/image files in the workspace directory."""
    ws = config.workspace()
    exts = {".aseprite", ".ase", ".png", ".gif", ".bmp", ".jpg", ".jpeg", ".tga"}
    files = []
    for p in sorted(ws.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts:
            files.append({
                "name": str(p.relative_to(ws)).replace("\\", "/"),
                "bytes": p.stat().st_size,
            })
    return {"workspace": str(ws), "count": len(files), "files": files}
