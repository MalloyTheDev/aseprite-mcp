"""Inspection & preview: structured info, a visual PNG preview, raw pixels, listing."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from mcp.server.mcpserver import Image

from ..app import mcp
from ..core import config, craft, figure, indexed, quality, ramplint, spritediff
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_ASSESS_PIXELS,
    MAX_COLOR_LIST_LENGTH,
    MAX_DIFF_COLORS,
    MAX_READ_REGION_PIXELS,
    check_list_length,
    check_region_size,
)
from ..core.models import FRAME_GUARD_LUA
from ..core.runner import AsepriteError, run_cli, run_lua
from .common import lua_path, parse_color, resolve_path


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
    # Bounded here as well as in the body, and the two are not redundant. Measured at
    # v0.10.0 with `assemble_script` intercepted: every over-cap region reached Lua, so a
    # request that cannot succeed paid a process launch and came back as an untyped Lua
    # error instead of the typed refusal every other over-cap argument produces. The body
    # keeps its own check because it bounds the *derived* extent (`ARG.width or
    # (spr.width - x0)`), which needs the sprite open; this bounds what the caller stated.
    #
    # The product goes first, ahead of the shared region check, because 4,096 is the
    # tighter of the two whenever both axes are given, so this is the message that tells
    # the caller what to ask for next.
    if width is not None and height is not None:
        try:
            w_asked, h_asked = int(width), int(height)
        except (TypeError, ValueError):
            raise ValidationFailed(
                f"region size must be whole numbers of pixels, got {width!r}x{height!r}."
            ) from None
        if w_asked * h_asked > MAX_READ_REGION_PIXELS:
            raise ValidationFailed(
                f"region size {w_asked}x{h_asked} exceeds the "
                f"{MAX_READ_REGION_PIXELS}-pixel ceiling on one read "
                f"({w_asked * h_asked} px). Max {MAX_READ_REGION_PIXELS} (e.g. 64x64) "
                "per call, because the cost is the serialized payload; read in tiles."
            )
    # Then the region family's own check, for what the product cannot see: an origin
    # further from the canvas than any canvas is wide (which becomes the extent when
    # width/height are unset), and the case where only one axis was given.
    check_region_size(
        width, height, x=x, y=y, field="region",
        remedy=f"Read a smaller region: up to {MAX_READ_REGION_PIXELS} pixels "
               "(e.g. 64x64) per call, in tiles.",
    )
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
    -- The backstop, not the only bound: the pre-flight in Python refuses a stated extent
    -- before Aseprite is launched. This one stays because it measures the DERIVED extent,
    -- so a width left unset with a far-away origin is refused by this route and by no
    -- other. MAX_READ_REGION comes from core.limits through the prelude, so the number
    -- has one definition; "64x64" is the request shape it is sized for, and is the part
    -- of the message that tells the caller what to ask for next.
    if w * h > MAX_READ_REGION then
      error("Region too large (" .. (w * h) .. " px). Max " .. MAX_READ_REGION ..
            " (e.g. 64x64) per call.")
    end
    -- The prelude's decode, not a local copy of it. Two copies of this function used to
    -- live here and both went straight to the palette, missing the transparentColor
    -- check that px_to_rgba does first: on an indexed sprite whose transparent index
    -- points at an opaque palette entry, every transparent pixel read back as that
    -- colour and the whole canvas counted as drawn.
    local img
    if ARG.layer ~= nil then
      -- One layer, not the composite: the surface the drawing tools write to, so what the
      -- caller reads back is what its next edit will modify.
      img = readable_layer(spr, find_layer(spr, ARG.layer), framenum)
    else
      img = readable_composite(spr, framenum)
    end
    -- Decoded in the image's own mode, which for an indexed sprite with a Background is
    -- Aseprite's RGB render: its transparent index is a colour there, and reading it as
    -- "no pixel" returned a whole background as #00000000.
    local mode = img.colorMode
    local function px_hex(px)
      local r, g, b, a = px_to_rgba(spr, px, mode)
      return string.format("#%02x%02x%02x%02x", r, g, b, a)
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


# The whole frame, run-length encoded against a colour table. `get_pixels` caps a read at
# 4096 pixels because its rows go back to the caller and a model should not be handed a
# megabyte of hex; here the pixels never leave the process, only the measurements do, so
# the cap that applies is the one on how long the measuring takes.
_ASSESS_LUA = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local framenum = require_frame(spr, ARG.frame, "frame")
if spr.width * spr.height > ARG.max_pixels then
  error("This frame is " .. spr.width .. "x" .. spr.height .. " (" ..
        (spr.width * spr.height) .. " px); assess_sprite measures at most " ..
        ARG.max_pixels .. ". Assess a smaller sprite, or crop a copy of this one.", 0)
end

local img
if ARG.layer ~= nil then
  img = readable_layer(spr, find_layer(spr, ARG.layer), framenum)
else
  img = readable_composite(spr, framenum)
end
-- In the image's own mode: Aseprite's RGB render for an indexed sprite with a Background,
-- whose transparent index would otherwise measure as empty canvas.
local mode = img.colorMode
local function px_hex(px)
  local r, g, b, a = px_to_rgba(spr, px, mode)
  return string.format("#%02x%02x%02x%02x", r, g, b, a)
end

local palette, seen, rows = {}, {}, {}
for yy = 0, spr.height - 1 do
  local row, n, run, length = {}, 0, nil, 0
  for xx = 0, spr.width - 1 do
    local hex = px_hex(img:getPixel(xx, yy))
    local index = seen[hex]
    if index == nil then
      palette[#palette + 1] = hex
      index = #palette
      seen[hex] = index
    end
    if index == run then
      length = length + 1
    else
      if run ~= nil then
        n = n + 1; row[n] = run
        n = n + 1; row[n] = length
      end
      run, length = index, 1
    end
  end
  n = n + 1; row[n] = run
  n = n + 1; row[n] = length
  rows[yy + 1] = row
end

RESULT = {
  width = spr.width, height = spr.height, frame = framenum,
  palette = palette, rows = rows,
}
"""


def _expand(measured: dict) -> quality.Grid:
    """Turn the run-length rows back into the grid the metrics read.

    The colour strings are shared rather than copied, so a 512x512 frame of twelve
    colours costs twelve strings and a list of references to them.
    """
    palette = measured["palette"]
    grid: quality.Grid = []
    for row in measured["rows"]:
        line: list[str] = []
        for i in range(0, len(row), 2):
            line.extend([palette[row[i] - 1]] * row[i + 1])
        grid.append(line)
    return grid


@mcp.tool()
def assess_sprite(
    filename: str,
    frame: int = 1,
    layer: str | None = None,
    ramp: list[str] | None = None,
    check_tiling: bool = False,
    standing: bool = False,
    check_cvd: bool = False,
) -> dict:
    """Measure the drawing itself and say what is worth fixing.

    `get_sprite_info` says what a sprite contains and `render_preview` returns a picture
    a text-only model cannot read. This answers the question in between: is the art any
    good, in the ways that can be counted.

    Reports how many colours are in use and roughly how many ramps they form, pixels with
    no neighbour of their own colour (noise), jagged corners on diagonals, the drawn
    bounding box, how much of the canvas it fills, whether it sits centred, and how far
    the silhouette is from its own mirror.

    It also reports five things about whether the drawing has *form*, which were added
    because every measurement above passed on a figure that read as one grey slab:

    * `row_structure`: how many drawn rows have background between two parts of the
      silhouette, how many are a single run across most of the width, and the widest run.
      A creature reads because air cuts between its limbs, and nothing else here notices
      when it does not.
    * `edge_contact`: drawn pixels sitting on the canvas border, where a silhouette is cut
      off and cannot take an outline.
    * `tone_shares`: the most-used colour and what share of the drawing it covers. One
      tone over a large share of a surface is a fill, not a form.
    * `separator`: what share of the drawing is its darkest colour, and how dark that is.
      In this medium the dark keyline is structural rather than a fallback.
    * `ramp_chroma`, when a `ramp` is declared: its hue span, its saturation floor, and
      how many of its steps are below the chroma at which hue is visible at all. The
      floor is an HLS saturation, the same scale `generate_ramp`'s `chroma` takes, and
      not the HSV saturation a colour picker shows: #ff8080 reads 1.00 here and 0.50
      there. A ramp
      interpolated between two endpoints on opposite sides of the colour wheel routes
      through the neutral axis, so it can rotate hue a long way and render as greys.

    The silhouette and form readings are withheld for art that fills its canvas (a scene
    has no silhouette) and for art using fewer than three colours (a flat shape is not a
    surface without form), because a reading that cannot be acted on is noise.

    Each measurement that is worth acting on comes back with a line saying why, so the
    numbers do not have to be interpreted.

    Args:
        ramp: Declare the ramp the art should be on and the report adds palette
            conformance: the fraction of drawn pixels sitting exactly on it. This is the
            measurement that separates shading from filtering, and it is omitted rather
            than reported as a meaningless 1.0 when no ramp is given. On an **indexed**
            sprite the readings also say how much of the ramp the palette can actually
            hold, because conformance cannot see a ramp step that collapsed onto its
            neighbour: the colour it collapsed to is still on the ramp, so banded
            shading still scores 1.0.
        check_tiling: For a tile, also measure how much worse the wrapping edge looks
            than the interior, per axis. Near 1.0 wraps; much above 1.0 has a seam.
        layer: Measure one layer instead of the flattened frame.
        standing: Say that the subject is a figure standing on its feet, and the report
            adds whether its mass sits over them: the signed margin between the mass
            centroid and the support base. There is no sensible answer for an item, a
            tile or a scene, so this is asked for rather than guessed.
        check_cvd: Also re-measure the drawing through red-green and blue-yellow colour
            vision deficiency, and report where two colours that are distinct to most
            viewers collapse into one. Off by default because it is the one measurement
            here that costs about half again as much as everything else at the size cap.

    Reads the whole frame in one Aseprite launch. None of the pixels are returned, only
    the measurements, so this is cheap to call after every pass.
    """
    if ramp:
        # The cap its seven siblings apply, and the only route to a palette that was
        # missing it. The cost here is linear in the ramp rather than quadratic
        # (`quality.palette_conformance` builds a set once and then does O(pixels)
        # membership tests, and the prelude's `ramp_palette_state` is O(ramp x palette)
        # with the palette capped at 256), so this is consistency and not a weakness: a
        # cap that holds for seven of eight call sites is a cap nobody can rely on.
        check_list_length("ramp", ramp, MAX_COLOR_LIST_LENGTH)
    src = resolve_path(filename)
    measured = run_lua(_ASSESS_LUA, {
        "src": lua_path(src), "frame": int(frame), "layer": layer,
        "max_pixels": MAX_ASSESS_PIXELS,
        # Passed through so the harness can report what the ramp becomes on an indexed
        # palette. Conformance against a ramp the palette cannot hold is not a
        # meaningful number, and it is the misleading direction: a pixel that snapped to
        # a neighbouring ramp step is still on the ramp, so conformance reads 1.0 for
        # shading that banded. The Lua does nothing else with it.
        "ramp": [parse_color(c) for c in ramp] if ramp else None,
    })
    grid = _expand(measured)
    metrics = quality.score(grid, ramp)
    # The form and colour measures, which live in `core.figure` and `core.ramplint`
    # because they are judgement over a grid and nothing else.
    #
    # What is unconditional here and what is a flag was decided by timing them, at the
    # size cap and at a real size, rather than by taste.
    #
    # At 1024x1024, MAX_ASSESS_PIXELS, `quality.score` above already costs about 39
    # seconds. The figure measures add roughly 4 and the notan about 4, a tenth each of a
    # cost already being paid, while the colour-vision recheck adds 18 and so nearly half
    # again: that one is the flag. On the 64x64 golem the same list reads 119ms for
    # `quality.score`, 21ms for the figure measures, 13ms for the notan and 48ms for the
    # recheck, so the unconditional additions are a worse *proportion* at a small size
    # and irrelevant in absolute terms, because the `run_lua` above launches Aseprite and
    # that subprocess dominates both. The flag is therefore chosen for the cap, where the
    # cost is real, and nothing here is withheld to save tens of milliseconds.
    mask = figure.mask_from_grid(grid)
    line = figure.centerline(mask)
    topo = figure.topology(mask)
    metrics["form"] = {
        # A deliberate lean drifts smoothly and a misplaced part jumps, so this is the
        # second difference of the row midpoints and not their spread.
        "centerline_peak": round(line.peak, 2),
        "centerline_normalized": round(line.normalized, 3),
        "centerline_rows_measured": line.rows_measured,
        "components": len(topo.components),
        "holes": len(topo.holes),
        "thin_parts": len(figure.thin_parts(mask)),
    }
    metrics["notan"] = ramplint.notan(grid)
    # How the drawing was made, as opposed to what it depicts. Cheap (one pass for the
    # regions, one for the edges) and reported without judgement: every threshold
    # proposed for these failed the ranking gate on the corpus, which `core.craft`
    # records rather than hides.
    metrics["craft"] = craft.score(grid)
    if standing:
        # Only when the caller says the subject stands. `base_of_support` is about
        # whether the mass sits over the feet, and that question has no answer for an
        # item, a tile or a scene, so the module takes the claim as an argument rather
        # than guessing it from the pixels.
        support = figure.base_of_support(mask, standing=True)
        if support is not None:
            metrics["form"]["support"] = {
                "centroid_x": round(support.centroid_x, 2),
                "base": list(support.base) if support.base else None,
                "margin": round(support.margin, 2) if support.margin is not None else None,
                "contact_runs": support.contact_runs,
            }
    if ramp:
        # The ramp itself, as opposed to how well the pixels sit on it. Conformance
        # cannot fault a declared ramp that is not monotone in lightness or that steps
        # unevenly, because every pixel is on it: the ramp is the thing at fault.
        metrics["ramp_lints"] = ramplint.ramp_lints(ramp)
    if check_cvd:
        metrics["cvd"] = ramplint.cvd_recheck(grid)
    if check_tiling:
        horizontal, vertical = quality.tile_seam_ratio(grid)
        metrics["tile_seam"] = {"horizontal": round(horizontal, 3),
                                "vertical": round(vertical, 3)}

    notes = quality.readings(metrics, width=measured["width"], height=measured["height"])
    # Before the tiling note, because it changes how palette_conformance above should be
    # read: on an indexed sprite whose palette does not hold the declared ramp, the
    # conformance number is measuring the palette rather than the shading.
    notes.extend(indexed.ramp_readings(measured.get("ramp_on_palette") or {}))
    # Qualified rather than imported bare, because `indexed` has a function of the same
    # name immediately above and the two answer different questions: that one is about
    # what an indexed palette can hold, this one about whether the ramp is well formed.
    if "ramp_lints" in metrics:
        notes.extend(ramplint.ramp_readings(metrics["ramp_lints"]))
    if "cvd" in metrics:
        notes.extend(ramplint.cvd_readings(metrics["cvd"]))
    if check_tiling and "tile_seam" in metrics:
        seam = metrics["tile_seam"]
        for axis in ("horizontal", "vertical"):
            if seam[axis] > 1.5:
                notes.append(
                    f"The {axis} wrap is {seam[axis]:.1f}x as different as the interior, "
                    "so this tile shows a seam on that axis."
                )
    return {
        "ok": True,
        "frame": measured["frame"],
        "layer": layer,
        "width": measured["width"],
        "height": measured["height"],
        "metrics": metrics,
        "readings": notes,
    }


# How a diff finds its differences, and why it is not one pass over both images.
#
# The expensive part of reading a frame is the per-pixel work in Lua: a getPixel, a
# px_to_rgba and a string.format at the size cap take seconds. Almost none of it is
# needed, because almost no pixel changes. So the scan narrows three times:
#
#   1. `Image:isEqual` over the whole frame. It is native, and it settles the common
#      "did anything happen at all" case outright.
#   2. One row of `Image.bytes` against the same row of the other buffer, as a single
#      string comparison per row. That reduces the pixels worth looking at to the rows
#      that actually hold a difference.
#   3. px_to_rgba on the pixels of those rows, which is where a pixel is classified and
#      the only place a colour mode is interpreted.
#
# Step 3 is the authority on what counts as changed; steps 1 and 2 may only ever skip
# work. That ordering is the point: isEqual treats two fully transparent pixels as equal
# whatever bytes sit under them and a byte comparison does not, so a tool that trusted
# the bytes would report "identical" and "47 pixels differ" in the same breath.
_DIFF_LUA = FRAME_GUARD_LUA + """
-- app.open rather than the prelude's open_sprite, deliberately. open_sprite loads a
-- .msk sidecar into the shared _sel global, so opening a second sprite here would leave
-- one sprite's selection in place for a tool that writes no pixels at all, and the
-- harness would go on to report selection_applied on a read-only result. A diff is also
-- a question about the whole frame: scoping it to whatever happened to be selected
-- would quietly answer a different one.
local function load_sprite(path, what)
  local spr = app.open(path)
  if spr == nil then error("Could not open the " .. what .. ": " .. tostring(path), 0) end
  if spr.width * spr.height > ARG.max_pixels then
    error("The " .. what .. " is " .. spr.width .. "x" .. spr.height .. " (" ..
          (spr.width * spr.height) .. " px); diff_sprites compares at most " ..
          ARG.max_pixels .. " pixels per frame.", 0)
  end
  return spr
end

local function box_text(box)
  if box == nil then return "empty" end
  return box.width .. "x" .. box.height .. " at " .. box.x .. "," .. box.y
end

local function frame_image(spr, framenum, layer_ref)
  if layer_ref ~= nil then
    -- One layer, the same surface the drawing tools write to. The composite is not it:
    -- an edit that landed on the wrong layer is invisible in the composite of a sprite
    -- whose other layer happens to cover it.
    return readable_layer(spr, find_layer(spr, layer_ref), framenum)
  end
  return readable_composite(spr, framenum)
end

local a = load_sprite(ARG.a, "sprite")
-- Opening the same path twice gives two independent documents, which is what lets a
-- frame-to-frame diff inside one sprite be this same code rather than a second tool.
local b = load_sprite(ARG.b, "sprite to compare against")
local fa = require_frame(a, ARG.frame_a, "frame")
local fb = require_frame(b, ARG.frame_b, "other_frame")

local ia = frame_image(a, fa, ARG.layer_a)
local ib = frame_image(b, fb, ARG.layer_b)

-- One measurement per side for both numbers this result reports about it. They used to
-- come from two: the count from the prelude's byte scan and the box from
-- `Image:shrinkBounds`, which honours an indexed sprite's transparent index but not a
-- palette entry whose own alpha is 0. On an 8x8 indexed sprite with one pixel held in
-- such an entry that reported `drawn_pixels: 4` beside a 5x5 `content` box whose corner
-- nothing in the sprite could draw (#172). Measuring once removes the chance of the two
-- disagreeing rather than correcting one of them.
local a_drawn, a_box = visible_extent(a, ia)
local b_drawn, b_box = visible_extent(b, ib)

if a.width ~= b.width or a.height ~= b.height then
  error("These frames cannot be compared pixel for pixel: " .. ARG.a_name .. " is " ..
        a.width .. "x" .. a.height .. " and " .. ARG.b_name .. " is " .. b.width .. "x" ..
        b.height .. ". The art inside them is " .. box_text(a_box) .. " and " ..
        box_text(b_box) .. ", so if the canvases differ only in padding, " ..
        "trim_sprite or resize_canvas on a copy will line them up.", 0)
end

-- Which rows are worth looking at.
local rows = {}
-- The images' modes rather than the sprites': an indexed sprite with a Background is read
-- as Aseprite's RGB render, so two indexed sprites can arrive in different modes.
if not (ia.colorMode == ib.colorMode and ia:isEqual(ib)) then
  local sa, sb = ia.bytes, ib.bytes
  local per = a.width * a.height
  local narrowed = false
  if ia.colorMode == ib.colorMode and #sa == #sb and per > 0 and #sa % per == 0 then
    local stride = math.floor(#sa / per) * a.width
    for y = 0, a.height - 1 do
      local off = y * stride
      if string.sub(sa, off + 1, off + stride) ~= string.sub(sb, off + 1, off + stride) then
        rows[#rows + 1] = y
      end
    end
    narrowed = true
  end
  if not narrowed then
    -- Different colour modes, or a buffer that is not the shape assumed above. Every
    -- row, and px_to_rgba decides, because it is the one thing that reads both modes.
    for y = 0, a.height - 1 do rows[#rows + 1] = y end
  end
end

local changed, added, removed, interior, coverage = 0, 0, 0, 0, 0
local minx, miny, maxx, maxy = nil, nil, nil, nil
local was, now = {}, {}

for _, y in ipairs(rows) do
  for x = 0, a.width - 1 do
    local r1, g1, b1, a1 = px_to_rgba(a, ia:getPixel(x, y), ia.colorMode)
    local r2, g2, b2, a2 = px_to_rgba(b, ib:getPixel(x, y), ib.colorMode)
    local same
    if a1 == 0 and a2 == 0 then
      -- Both absent. Whatever colour an invisible pixel carries underneath is not art,
      -- and counting it would mean a diff that disagrees with every preview of the two
      -- frames it just compared.
      same = true
    else
      same = (a1 == a2 and r1 == r2 and g1 == g2 and b1 == b2)
    end
    if not same then
      changed = changed + 1
      if a1 == 0 then
        added = added + 1
      elseif a2 == 0 then
        removed = removed + 1
      elseif r1 == r2 and g1 == g2 and b1 == b2 then
        coverage = coverage + 1
      else
        interior = interior + 1
      end
      if minx == nil or x < minx then minx = x end
      if maxx == nil or x > maxx then maxx = x end
      if miny == nil or y < miny then miny = y end
      if maxy == nil or y > maxy then maxy = y end
      if a1 > 0 then
        local k = string.format("#%02x%02x%02x%02x", r1, g1, b1, a1)
        was[k] = (was[k] or 0) + 1
      end
      if a2 > 0 then
        local k = string.format("#%02x%02x%02x%02x", r2, g2, b2, a2)
        now[k] = (now[k] or 0) + 1
      end
    end
  end
end

-- pairs() has no defined order, so the colour is the tiebreak: the same two frames have
-- to produce the same list every time or nothing downstream can be tested.
local function tally(t)
  local out = {}
  for color, count in pairs(t) do out[#out + 1] = { color = color, pixels = count } end
  table.sort(out, function(p, q)
    if p.pixels ~= q.pixels then return p.pixels > q.pixels end
    return p.color < q.color
  end)
  return out
end

local box = nil
if minx ~= nil then
  box = { x = minx, y = miny, width = maxx - minx + 1, height = maxy - miny + 1 }
end

RESULT = {
  width = a.width, height = a.height,
  a = { frame = fa, color_mode = colormode_name(a.colorMode), frames = #a.frames,
        drawn_pixels = a_drawn, content = a_box },
  b = { frame = fb, color_mode = colormode_name(b.colorMode), frames = #b.frames,
        drawn_pixels = b_drawn, content = b_box },
  changed_pixels = changed,
  silhouette_added = added,
  silhouette_removed = removed,
  interior_changed = interior,
  coverage_changed = coverage,
  change_box = box,
  colors_before = tally(was),
  colors_after = tally(now),
}
"""


def _tally(colors) -> list[dict]:
    """A colour tally as a list, whatever shape Lua handed it back in.

    An empty Lua table carries no evidence of whether it was meant as a list or a map, so
    one arrives here as `{}` rather than `[]`. Coercing is cheaper than teaching the
    encoder to guess, and a diff that found nothing changed is the common case.
    """
    return colors if isinstance(colors, list) else []


@mcp.tool()
def diff_sprites(
    filename: str,
    frame: int = 1,
    layer: str | None = None,
    other: str | None = None,
    other_frame: int = 1,
    other_layer: str | None = None,
    expect: str | None = None,
) -> dict:
    """Compare two frames pixel for pixel and say what changed.

    This is the tool for the question an editing agent cannot otherwise answer: *did my
    last call do what I meant?* `assess_sprite` judges one frame on its own and
    `render_preview` returns a picture a text-only model cannot read. This reports the
    difference between two frames as counts, which is the only form in which "the shading
    pass moved the outline" is visible without eyes.

    **Nothing changed is the loudest result, not the quiet one.** An edit that silently
    went nowhere, to the wrong layer, inside a stale selection, off the canvas, looks
    exactly like an edit that was not needed. When the two frames are identical this says
    so first and names the usual causes.

    A difference is never reported as a fault, because different is not wrong. Pass
    `expect` to turn the measurement into a check.

    Args:
        filename: The sprite to compare, and the "before" side of the report.
        frame: Which frame of it (1-based).
        layer: Compare this layer alone instead of the composite, on both sides unless
            `other_layer` says otherwise. Worth reaching for: drawing tools write to ONE
            layer, so a composite diff can show nothing while the layer underneath
            changed completely, and the reverse.
        other: The sprite to compare against. Defaults to `filename`, which is what makes
            a frame-to-frame diff inside one animation this same call.
        other_frame: Which frame of `other` (1-based).
        other_layer: The layer to read on the `other` side, when it is named differently.
        expect: What the change should be: "identical", "silhouette", "interior",
            "coverage" or "mixed". Adds a verdict block with a pass or a fail, and is
            omitted rather than guessed at.

    Returns counts in four buckets that add up to `changed_pixels`, so a change is never
    reported as a single number that could mean two different things:

    * `silhouette_added` / `silhouette_removed`: pixels that entered or left the shape.
      These are the ones that move a collision box, an outline and a trimmed export box.
    * `interior_changed`: pixels that were visible before and after and changed colour.
    * `coverage_changed`: pixels that kept their colour and changed only their alpha,
      which is an opacity or anti-aliasing change rather than a repaint.

    Both frames must be the same size; a mismatch is refused with both canvas sizes and
    both content boxes, because a diff of differently sized frames is an offset question
    in disguise. Different colour modes compare fine: both sides are read as RGBA, so an
    indexed sprite and its RGB export can be checked against each other.
    """
    if expect is not None and expect not in spritediff.CLASSIFICATIONS:
        raise ValidationFailed(
            f"expect must be one of {', '.join(spritediff.CLASSIFICATIONS)}; "
            f"got {expect!r}."
        )
    src = resolve_path(filename)
    dst = resolve_path(other) if other is not None else src
    layer_b = other_layer if other_layer is not None else layer
    if src == dst and int(frame) == int(other_frame) and layer_b == layer:
        raise ValidationFailed(
            "This would compare a frame with itself, which always reports identical. "
            "Pass other= for a second sprite, or other_frame= for another frame of this "
            "one. To check whether an edit landed, diff against a copy taken before it "
            "(save_sprite_as) rather than against the same frame."
        )

    measured = run_lua(_DIFF_LUA, {
        "a": lua_path(src), "b": lua_path(dst),
        "a_name": filename, "b_name": other if other is not None else filename,
        "frame_a": int(frame), "frame_b": int(other_frame),
        "layer_a": layer, "layer_b": layer_b,
        "max_pixels": MAX_ASSESS_PIXELS,
    })

    # Pixels drawn in either frame, which is the denominator that makes `changed_share`
    # mean something. It is exact rather than estimated: a pixel visible in the second
    # frame and not the first is precisely one that was counted into silhouette_added.
    counts = {k: v for k, v in measured.items() if k not in ("a", "b", "width", "height")}
    counts["drawn_union"] = measured["a"]["drawn_pixels"] + measured["silhouette_added"]

    # The full tallies are what the readings reason over; the capped ones are what goes
    # back to the caller. A diff that says "introduced 40 colours" while listing 24 is
    # honest about both, and `colors_total` below says so explicitly.
    counts["colors_before"] = _tally(measured.get("colors_before"))
    counts["colors_after"] = _tally(measured.get("colors_after"))
    new = spritediff.introduced(counts)
    before, after = counts["colors_before"], counts["colors_after"]

    metrics = {
        "changed_pixels": measured["changed_pixels"],
        "silhouette_added": measured["silhouette_added"],
        "silhouette_removed": measured["silhouette_removed"],
        "interior_changed": measured["interior_changed"],
        "coverage_changed": measured["coverage_changed"],
        **spritediff.shares(counts),
        "change_box": measured.get("change_box"),
        "drawn_union": counts["drawn_union"],
        "colors_before": before[:MAX_DIFF_COLORS],
        "colors_after": after[:MAX_DIFF_COLORS],
        "colors_introduced": new[:MAX_DIFF_COLORS],
    }
    if max(len(before), len(after), len(new)) > MAX_DIFF_COLORS:
        # The lists are capped but the counts are not, so a diff of a photo import says
        # how many colours were involved without returning the histogram.
        metrics["colors_total"] = {
            "before": len(before), "after": len(after), "introduced": len(new),
        }

    names = {
        "before": f"{filename} frame {measured['a']['frame']}",
        "after": f"{other or filename} frame {measured['b']['frame']}",
    }
    result = {
        "ok": True,
        "identical": measured["changed_pixels"] == 0,
        "change": spritediff.classify(counts),
        "width": measured["width"],
        "height": measured["height"],
        "a": {"path": str(src), "layer": layer, **measured["a"]},
        "b": {"path": str(dst), "layer": layer_b, **measured["b"]},
        "metrics": metrics,
        "readings": spritediff.readings(counts, names=names),
    }
    if expect is not None:
        result["verdict"] = spritediff.verdict(counts, expect)
    return result
