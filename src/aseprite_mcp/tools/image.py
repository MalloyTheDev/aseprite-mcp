"""Bring outside images in: stamp one onto a sprite, from a file path or inline base64 PNG,
or slice a sprite sheet into frames."""

from __future__ import annotations

import base64
import binascii
import contextlib
import os
import tempfile

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_CANVAS_DIMENSION,
    MAX_CANVAS_PIXELS,
    MAX_IMAGE_BYTES,
    MAX_SHEET_FRAMES,
    check_count,
    check_size_bytes,
)
from ..core.models import FRAME_GUARD_LUA
from ..core.paths import discard_selection_sidecar, ensure_output_path
from ..core.runner import run_lua
from .common import lua_path, resolve_path

_STAMP_BODY = FRAME_GUARD_LUA + """
local spr = open_sprite(ARG.src)
local layer = find_layer(spr, ARG.layer)
if layer.isGroup then error("Cannot stamp onto a group layer: " .. layer.name) end
local framenum = require_frame(spr, ARG.frame, "frame")
local img = get_draw_image(spr, layer, framenum)

local source = app.open(ARG.source)
if source == nil then error("Could not open source image: " .. ARG.source) end
local sframe = ARG.source_frame
if sframe < 1 then sframe = 1 end
if sframe > #source.frames then sframe = #source.frames end

local srcimg = Image(ImageSpec{ width = source.width, height = source.height, colorMode = spr.colorMode })
srcimg:clear()
srcimg:drawSprite(source, sframe)
img:drawImage(srcimg, Point(ARG.x, ARG.y), ARG.opacity, blendmode_from(ARG.blend_mode))

commit_image(spr, layer, framenum, img)
save_sprite(spr)
RESULT = { ok = true, layer = layer.name, frame = framenum,
           stamped = { width = source.width, height = source.height, x = ARG.x, y = ARG.y } }
"""


def _stamp(args: dict) -> dict:
    return run_lua(_STAMP_BODY, args)


def check_image_dimensions(path: str) -> tuple[int, int] | None:
    """Reject an image whose declared dimensions exceed the canvas limits.

    A byte cap does not bound the raster: PNG and friends compress a solid colour
    to almost nothing, so a payload well under the size limit can declare
    16384x16384 and make Aseprite allocate gigabytes the moment it opens the file.
    Pillow parses only the header here, so the dimensions are read without decoding
    any pixels.

    Returns the (width, height) that were checked, or None when the format is not
    one Pillow recognizes (notably Aseprite's own .aseprite/.ase), in which case no
    claim is made and the caller proceeds.
    """
    from PIL import Image as PILImage
    from PIL import UnidentifiedImageError

    try:
        # open() parses the header only, no pixel decode. Pillow applies its own
        # bomb guard here too, but its threshold (2x MAX_IMAGE_PIXELS, ~179 Mpx) is
        # an order of magnitude above this project's canvas cap, so the explicit
        # check below is what rejects anything in between.
        with PILImage.open(path) as img:
            width, height = img.size
    except PILImage.DecompressionBombError as exc:
        raise ValidationFailed(
            f"Source image rejected as a decompression bomb by Pillow: {exc}"
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    if width > MAX_CANVAS_DIMENSION or height > MAX_CANVAS_DIMENSION:
        raise ValidationFailed(
            f"Source image is {width}x{height}; maximum is {MAX_CANVAS_DIMENSION}px "
            "per axis. Resize it before bringing it in."
        )
    if width * height > MAX_CANVAS_PIXELS:
        raise ValidationFailed(
            f"Source image is {width}x{height} ({width * height} pixels); maximum is "
            f"{MAX_CANVAS_PIXELS}. Resize it before bringing it in."
        )
    return width, height


def decoded_size(b64: str) -> int:
    """Decoded byte count of a base64 string, without decoding it.

    Base64 encodes N bytes as ceil(4N/3) characters, then pads to a multiple of 4.
    Dropping the padding makes the inverse exact for every N, so this is not an
    estimate: it lets an oversized payload be rejected before the decoded copy is
    allocated, without rejecting a payload that lands exactly on the cap.
    """
    return (len(b64.rstrip("=")) * 3) // 4


@mcp.tool()
def stamp_file(
    filename: str,
    source: str,
    x: int,
    y: int,
    source_frame: int = 1,
    opacity: int = 255,
    blend_mode: str = "normal",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Composite another image/sprite file onto a layer at (x, y).

    Args:
        source: Path to a .aseprite/.png/.bmp/... to stamp in.
        x, y: Top-left placement on the target canvas.
        source_frame: Which frame of the source to use (1-based).
        opacity: 0-255.
        blend_mode: Blend mode for compositing (normal, multiply, …).
    """
    source_path = resolve_path(source)
    check_image_dimensions(str(source_path))
    args = {
        "src": lua_path(resolve_path(filename)),
        "source": lua_path(source_path),
        "layer": layer, "frame": int(frame),
        "source_frame": int(source_frame),
        "x": int(x), "y": int(y),
        "opacity": max(0, min(255, int(opacity))),
        "blend_mode": blend_mode,
    }
    return _stamp(args)


@mcp.tool()
def draw_image_base64(
    filename: str,
    image_base64: str,
    x: int,
    y: int,
    opacity: int = 255,
    blend_mode: str = "normal",
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Composite an inline base64-encoded PNG (or other image) onto a layer at (x, y).

    Useful for pasting externally generated artwork. `image_base64` may include a
    `data:image/png;base64,` prefix. The decoded image is capped at 32 MB; for
    anything larger, write the file into the workspace and use `stamp_file`.
    """
    data = image_base64.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    # Size-check before decoding so an oversized payload never allocates its
    # decoded copy. The post-decode check below still runs as a backstop.
    check_size_bytes(
        "image_base64 (decoded)", decoded_size(data), MAX_IMAGE_BYTES,
        remedy="Write the image into the workspace and use stamp_file instead.",
    )
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationFailed(f"image_base64 is not valid base64: {exc}") from exc
    check_size_bytes(
        "image_base64 (decoded)", len(raw), MAX_IMAGE_BYTES,
        remedy="Write the image into the workspace and use stamp_file instead.",
    )

    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="asemcp_stamp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        check_image_dimensions(tmp)
        args = {
            "src": lua_path(resolve_path(filename)),
            "source": lua_path(tmp),
            "layer": layer, "frame": int(frame),
            "source_frame": 1,
            "x": int(x), "y": int(y),
            "opacity": max(0, min(255, int(opacity))),
            "blend_mode": blend_mode,
        }
        return _stamp(args)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


# ---------------------------------------------------------------- sprite sheets (#93)
SHEET_LAYOUTS = ("horizontal", "vertical", "grid")


def _divisors(n: int) -> str:
    """The sizes that divide `n` exactly, for a refusal to offer. The first twelve are
    plenty to choose from."""
    found = [d for d in range(1, n + 1) if n % d == 0]
    return ", ".join(str(d) for d in found[:12]) + (", ..." if len(found) > 12 else "")


def sheet_cells(width: int, height: int, frame_width: int, frame_height: int,
                layout: str) -> tuple[int, int]:
    """The (columns, rows) a `width` x `height` sheet gives in cells of this size.

    Raises ValidationFailed saying what to change when the cells do not fit the layout
    exactly. Pure, so the refusal costs no launch and is tested without one.
    """
    if layout == "horizontal" and height != frame_height:
        raise ValidationFailed(
            f"layout 'horizontal' reads one row, so frame_height must be the sheet's "
            f"height, {height}; got {frame_height}. For a sheet of several rows use "
            f"layout='grid'."
        )
    if layout == "vertical" and width != frame_width:
        raise ValidationFailed(
            f"layout 'vertical' reads one column, so frame_width must be the sheet's "
            f"width, {width}; got {frame_width}. For a sheet of several columns use "
            f"layout='grid'."
        )
    for axis, size, cell in (("width", width, frame_width), ("height", height, frame_height)):
        if size % cell:
            raise ValidationFailed(
                f"frame_{axis} {cell} does not divide the sheet's {axis} of {size} "
                f"({size} / {cell} leaves {size % cell} pixels over), so the last cell "
                f"would be partial, and a partial cell is refused rather than cropped or "
                f"padded. Sizes that divide {size}: {_divisors(size)}."
            )
    columns, rows = width // frame_width, height // frame_height
    if columns * rows > MAX_SHEET_FRAMES:
        raise ValidationFailed(
            f"a {width}x{height} sheet in {frame_width}x{frame_height} cells is "
            f"{columns * rows} frames; maximum is {MAX_SHEET_FRAMES}. Check the cell size: "
            f"a sheet with more cells than that is not an animation."
        )
    return columns, rows


_SHEET_LUA = """
local spr = app.open(ARG.source)
if spr == nil then error("Could not open the sheet: " .. ARG.source, 0) end
if #spr.frames > 1 then
  error("the sheet has " .. #spr.frames .. " frames; import_spritesheet slices one flat " ..
        "image into frames. Export one frame of it as a PNG first.", 0)
end
local fw, fh, W, H = ARG.frame_width, ARG.frame_height, spr.width, spr.height
-- The backstop for sheets Pillow cannot read the header of (.aseprite, .ase), so that no
-- route reaches a partial cell or an unbounded frame count. Python refuses the rest
-- before launching, with the longer message.
if (ARG.layout == "horizontal" and H ~= fh) or (ARG.layout == "vertical" and W ~= fw)
   or W % fw ~= 0 or H % fh ~= 0 then
  error(string.format("%dx%d cells do not divide this %dx%d sheet as layout '%s' reads " ..
        "it, so a cell would be partial.", fw, fh, W, H, ARG.layout), 0)
end
if (W // fw) * (H // fh) > ARG.max_frames then
  error(string.format("%dx%d cells make %d frames of this %dx%d sheet; maximum is %d.",
        fw, fh, (W // fw) * (H // fh), W, H, ARG.max_frames), 0)
end

local opaque = false
for _, lyr in ipairs(spr.layers) do
  if lyr.isBackground then opaque = true end
end
local types = { horizontal = SpriteSheetType.HORIZONTAL, vertical = SpriteSheetType.VERTICAL,
                grid = SpriteSheetType.ROWS }
app.command.ImportSpriteSheet{ ui = false, type = types[ARG.layout],
  frameBounds = Rectangle(0, 0, fw, fh), padding = Size(0, 0), partialTiles = false }

if opaque then
  -- The importer renders the cells onto a new, transparent layer, where the transparent
  -- palette index means "no pixel". On an opaque indexed sheet that index is a real
  -- colour, so whatever was drawn in it vanished: a whole frame of the test sheet.
  -- Making the layer a Background again, with the fill set to that same index, rewrites
  -- those pixels with the value they already hold, and a Background draws it opaque, as
  -- the sheet did. Aseprite's default fill painted them with an entry the palette did
  -- not have. An opaque RGB sheet has no such index and no transparent pixel to fill.
  if spr.colorMode == ColorMode.INDEXED then
    app.bgColor = Color{ index = spr.transparentColor }
  end
  app.activeLayer = spr.layers[1]
  app.command.BackgroundFromLayer()
end

local layer = spr.layers[1]
local empty = {}
if not opaque then
  for i = 1, #spr.frames do
    local cel = layer:cel(i)
    if cel == nil or cel.image:isEmpty() then empty[#empty + 1] = i end
  end
end
spr:saveAs(ARG.dst)
RESULT = sprite_info(spr)
RESULT.layer = layer.name
RESULT.empty_frames = empty
"""


@mcp.tool()
def import_spritesheet(
    filename: str,
    source: str,
    frame_width: int,
    frame_height: int,
    layout: str = "horizontal",
    overwrite: bool = False,
) -> dict:
    """Turn a sprite sheet image into an animated sprite, one frame per cell.

    The inbound seam for art made elsewhere, such as a PixelPrep strip, and the reverse of
    `export_spritesheet`. Aseprite's own Import Sprite Sheet does the slicing.

    Args:
        filename: The .aseprite file to create.
        source: The sheet: a PNG, or anything else Aseprite opens, in the workspace.
        frame_width: One cell's width in pixels.
        frame_height: One cell's height in pixels. Both must divide the sheet exactly in
            the direction the layout reads it: a partial cell is refused, never cropped
            or padded, and the refusal names the sizes that would divide.
        layout: "horizontal" reads one row left to right, so frame_height must be the
            sheet's height. "vertical" reads one column top to bottom, so frame_width
            must be its width. "grid" reads rows left to right, top to bottom.
        overwrite: Replace `filename` if it already exists (default False = no-clobber).

    The sprite is one cell in size, with one layer holding every frame, in the sheet's
    colour mode and palette. An opaque sheet keeps its Background layer, which on an
    indexed sheet is what keeps the colour at the transparent palette index visible.
    Frames are 100ms: time them with `set_all_frame_durations` or `apply_timing_curve`.
    A cell with nothing in it still becomes a frame, and `empty_frames` lists them, so a
    grid's spare cells are visible as such. A sheet with frames of its own, such as a
    GIF, is refused rather than sliced from its first frame. At most 4,096 frames.

    Returns the sprite's info, plus `layer` and `empty_frames`.
    """
    if layout not in SHEET_LAYOUTS:
        raise ValidationFailed(
            f"layout must be one of {', '.join(SHEET_LAYOUTS)}; got {layout!r}."
        )
    fw = check_count("frame_width", frame_width, MAX_CANVAS_DIMENSION, minimum=1)
    fh = check_count("frame_height", frame_height, MAX_CANVAS_DIMENSION, minimum=1)
    src = resolve_path(source)
    if not src.is_file():
        raise ValidationFailed(f"source '{source}' does not exist in the workspace.")
    # The header check doubles as the decompression-bomb guard that the stamping tools
    # run. None means Pillow cannot read this format (.aseprite), and the Lua backstop
    # then makes the same refusals once the sheet is open.
    size = check_image_dimensions(str(src))
    if size is not None:
        sheet_cells(size[0], size[1], fw, fh, layout)
    dst = ensure_output_path(filename, overwrite=overwrite)
    # It writes a sprite, so a selection left beside that path belongs to the file being
    # replaced and must not outlive it (see `import_image`).
    discard_selection_sidecar(dst)
    info = run_lua(_SHEET_LUA, {
        "source": lua_path(src), "dst": lua_path(dst), "layout": layout,
        "frame_width": fw, "frame_height": fh, "max_frames": MAX_SHEET_FRAMES,
    })
    info["path"] = str(dst)
    return info
