"""Text rendering. Renders text with Pillow (built-in bitmap font by default, or
any TrueType font you point it at), thresholds it to crisp pixels, and plots it
onto the sprite in a single colour, ideal for pixel-art labels and HUDs."""

from __future__ import annotations

from ..app import mcp
from ..core.errors import ValidationFailed
from ..core.limits import (
    MAX_FONT_SIZE,
    MAX_TEXT_BITMAP_PIXELS,
    MAX_TEXT_PIXELS,
    MAX_TEXT_SCALE,
    check_list_length,
)
from .common import lua_path, parse_color, resolve_path
from .drawing import _draw

# Kept as a module-level alias: the old private name is referenced by tests and
# was the documented ceiling before the limits module existed.
_MAX_TEXT_PIXELS = MAX_TEXT_PIXELS


def _render_text_pixels(text: str, scale: int, font, spacing: int, threshold: int):
    """Rasterize `text` to a list of (x, y) pixel offsets to plot.

    The plot list is budgeted *as it grows*: every source pixel becomes `scale ** 2`
    entries, so a large scale or font size can multiply a modest glyph into hundreds
    of millions of coordinates. Raising once the budget is gone would mean the memory
    has already been spent, so this bails out the moment the cap is crossed.
    """
    from PIL import Image as PILImage
    from PIL import ImageDraw

    measure = ImageDraw.Draw(PILImage.new("L", (1, 1)))
    try:
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
    except Exception:
        line_h = 12

    coords: list[tuple[int, int]] = []
    budget = MAX_TEXT_PIXELS
    per_source_pixel = scale * scale
    max_w = 0
    y_src = 0
    for line in text.split("\n"):
        if line:
            bbox = measure.textbbox((0, 0), line, font=font)
            w, h = max(1, bbox[2] + 1), max(1, bbox[3] + 1)
            # Bound the intermediate bitmap on its own (unscaled) size. The scale
            # factor belongs to the plotted-pixel budget below, not here: only
            # threshold-passing pixels are ever appended, so multiplying the whole
            # glyph box by scale**2 would reject sparse or whitespace-heavy text
            # that plots far fewer pixels than its bounding box suggests.
            if w * h > MAX_TEXT_BITMAP_PIXELS:
                raise ValidationFailed(
                    f"Text line needs a {w}x{h} ({w * h} pixel) bitmap to rasterize; "
                    f"maximum is {MAX_TEXT_BITMAP_PIXELS}. Reduce font_size or shorten "
                    "the line."
                )
            img = PILImage.new("L", (w, h), 0)
            ImageDraw.Draw(img).text((0, 0), line, fill=255, font=font)
            px = img.load()
            for cy in range(img.height):
                for cx in range(img.width):
                    if px[cx, cy] >= threshold:
                        if len(coords) + per_source_pixel > budget:
                            raise _too_large(len(coords) + per_source_pixel)
                        bx, by = cx * scale, (cy + y_src) * scale
                        for sy in range(scale):
                            for sx in range(scale):
                                coords.append((bx + sx, by + sy))
            max_w = max(max_w, img.width)
        y_src += line_h + spacing
    return coords, max_w * scale, y_src * scale


def _too_large(count: int) -> ValidationFailed:
    return ValidationFailed(
        f"Text would draw at least {count} pixels; maximum is {MAX_TEXT_PIXELS}. "
        "Reduce scale/font_size or shorten the text."
    )


@mcp.tool()
def draw_text(
    filename: str,
    text: str,
    x: int,
    y: int,
    color: str,
    scale: int = 1,
    font_path: str | None = None,
    font_size: int = 16,
    spacing: int = 1,
    threshold: int = 128,
    layer: str | None = None,
    frame: int = 1,
) -> dict:
    """Draw text onto a layer at (x, y) in a single colour.

    Args:
        text: The string (supports "\\n" for multiple lines).
        x, y: Top-left position of the text.
        color: Text colour.
        scale: Integer pixel-scaling of the rendered glyphs (default 1).
        font_path: Optional path to a .ttf/.otf font. If omitted, a built-in
            bitmap font is used (best for tiny pixel text).
        font_size: Point size when a TrueType font_path is given.
        spacing: Extra pixels between lines.
        threshold: 0-255 cutoff; pixels brighter than this are drawn (lower =
            heavier text). Keeps glyphs crisp (no anti-aliasing artefacts).

    scale is capped at 64, font_size at 512, and the rendered text at 200,000
    pixels; the pixel budget is enforced while rasterizing, not afterwards.

    Returns the standard draw result plus the rendered text's pixel size.
    """
    from PIL import ImageFont

    scale = max(1, int(scale))
    font_size = max(1, int(font_size))
    if scale > MAX_TEXT_SCALE:
        raise ValidationFailed(f"scale is {scale}; maximum is {MAX_TEXT_SCALE}.")
    if font_size > MAX_FONT_SIZE:
        raise ValidationFailed(f"font_size is {font_size}; maximum is {MAX_FONT_SIZE}.")
    if font_path:
        font = ImageFont.truetype(str(resolve_path(font_path)), font_size)
    else:
        font = ImageFont.load_default()

    coords, w, h = _render_text_pixels(text, scale, font, max(0, int(spacing)), int(threshold))
    if not coords:
        raise ValidationFailed("Text rendered no pixels (empty string or threshold too high).")
    check_list_length(
        "text pixels", coords, MAX_TEXT_PIXELS,
        remedy="Reduce scale/font_size or shorten the text.",
    )

    pixels = [[x + cx, y + cy] for cx, cy in coords]
    args = {
        "src": lua_path(resolve_path(filename)),
        "layer": layer, "frame": int(frame),
        "color": parse_color(color),
        "pixels": pixels,
    }
    snippet = """
    local px = to_pixel(spr, ARG.color)
    for _, p in ipairs(ARG.pixels) do img_set(img, p[1], p[2], px) end
    """
    out = _draw(args, snippet)
    out["text_width"] = w
    out["text_height"] = h
    return out
