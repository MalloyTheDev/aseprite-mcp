"""Inspection & preview: structured info, a visual PNG preview, raw pixels, listing."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from mcp.server.mcpserver import Image

from ..app import mcp
from ..core import config
from ..core.errors import ValidationFailed
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import AsepriteError, run_cli, run_lua
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
        with contextlib.suppress(OSError):
            os.unlink(out)
    return Image(data=data, format="png")


@mcp.tool()
def get_pixels(
    filename: str,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    frame: int = 1,
    layer: str | None = None,
    format: str = "rows",
) -> dict:
    """Read the pixel colours of a region.

    Args:
        layer: Read this layer alone instead of the composite. This matters more than
            it sounds: drawing tools write to ONE layer, so the composite is not the
            surface your next edit will act on. A fill whose boundary is drawn on a
            different layer will flood the whole canvas while the composite looks as
            though it should have stopped.
        format: "rows" (default) gives rows of "#RRGGBBAA" strings. "map" gives a
            `legend` of symbol to colour plus one string per row, which is around a
            tenth the size: a 16x16 icon of three colours costs roughly 3,400
            characters as rows and 350 as a map, and defects like a one-pixel offset
            are visible in it at a glance.

    The region is capped at 64x64 (4096 pixels) per call to keep responses small, so
    read in tiles for bigger areas.
    """
    if format not in ("rows", "map"):
        raise ValidationFailed('format must be "rows" or "map".')
    src = resolve_path(filename)
    args = {
        "src": lua_path(src),
        "x": int(x),
        "y": int(y),
        "width": width,
        "height": height,
        "frame": int(frame),
        "layer": layer,
    }
    body = FRAME_GUARD_LUA + """
    local spr = open_sprite(ARG.src)
    local framenum = require_frame(spr, ARG.frame, "frame")
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
    if ARG.layer ~= nil then
      -- One layer, not the composite. get_draw_image gives exactly the surface the
      -- drawing tools write to, so what the caller reads back is what its next edit
      -- will modify.
      local lyr = find_layer(spr, ARG.layer)
      img = get_draw_image(spr, lyr, framenum)
    else
      img:drawSprite(spr, framenum)
    end
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
    if ARG.layer ~= nil then RESULT.layer = ARG.layer end
    """
    result = run_lua(body, args)
    if format == "map":
        result = _as_map(result)
    return result


# Transparent reads as a dot because it is the absence of a pixel, and a dot is the
# conventional way to draw that. The rest are assigned in first-seen order so the same
# sprite always produces the same legend.
_MAP_SYMBOLS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _as_map(result: dict) -> dict:
    """Rewrite a rows result as a legend plus one string per row.

    Rows of hex strings are an honest but unreadable shape: a 16x16 of three colours is
    about 3,400 characters, nearly all of it repeated. The same data as a map is about
    350, and a human or a model can see the picture in it, which is the point of
    reading pixels back at all.
    """
    rows = result.get("pixels") or []
    legend: dict[str, str] = {}
    mapped: list[str] = []
    for row in rows:
        chars = []
        for px in row:
            if px.lower().endswith("00"):
                chars.append(".")
                continue
            symbol = legend.get(px)
            if symbol is None:
                if len(legend) >= len(_MAP_SYMBOLS):
                    # More distinct colours than symbols. Fall back rather than lie:
                    # a truncated legend would silently merge different colours.
                    return result
                symbol = _MAP_SYMBOLS[len(legend)]
                legend[px] = symbol
            chars.append(symbol)
        mapped.append("".join(chars))

    out = {k: v for k, v in result.items() if k != "pixels"}
    out["legend"] = {v: k for k, v in legend.items()} | {".": "transparent"}
    out["rows"] = mapped
    return out


def _within(root: str, path: str | Path) -> bool:
    """True if `path`, with every link resolved, is `root` or lives under it.

    `root` must already be `normcase(realpath(...))`-normalised.
    """
    real = os.path.normcase(os.path.realpath(path))
    prefix = root if root.endswith(os.sep) else root + os.sep
    return real == root or real.startswith(prefix)


@mcp.tool()
def list_sprites() -> dict:
    """List sprite/image files in the workspace directory."""
    ws = config.workspace()
    root = os.path.normcase(os.path.realpath(ws))
    exts = {".aseprite", ".ase", ".png", ".gif", ".bmp", ".jpg", ".jpeg", ".tga"}
    files = []
    # An NTFS junction is not a symlink as far as Python is concerned (`is_symlink()` is
    # False for one), so `rglob` walked straight through a junction in the workspace and
    # reported names and byte sizes from outside it. Every directory is re-checked with
    # `realpath` before descending, which stops the disclosure and also stops a junction
    # aimed at C:\ from walking the whole drive; every file is re-checked too, because a
    # file symlink pointing outside is followed by `is_file()` and `stat()`.
    for dirpath, dirnames, filenames in os.walk(ws):
        dirnames[:] = [d for d in dirnames if _within(root, os.path.join(dirpath, d))]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() not in exts or not p.is_file():
                continue
            if not _within(root, p):
                continue
            files.append({
                "name": str(p.relative_to(ws)).replace("\\", "/"),
                "bytes": p.stat().st_size,
            })
    files.sort(key=lambda entry: entry["name"])
    return {"workspace": str(ws), "count": len(files), "files": files}
