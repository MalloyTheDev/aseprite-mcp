"""Text rendering. Renders text with Pillow (built-in bitmap font by default, or
any TrueType font you point it at), thresholds it to crisp pixels, and plots it
onto the sprite in a single colour — ideal for pixel-art labels and HUDs."""

from __future__ import annotations

from ..app import mcp
from .common import lua_path, parse_color, resolve_path
from .drawing import _draw

_MAX_TEXT_PIXELS = 200_000


def _render_text_pixels(text: str, scale: int, font, spacing: int, threshold: int):
    from PIL import Image as PILImage, ImageDraw

    measure = ImageDraw.Draw(PILImage.new("L", (1, 1)))
    try:
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
    except Exception:
        line_h = 12

    coords: list[tuple[int, int]] = []
    max_w = 0
    y_src = 0
    for line in text.split("\n"):
        if line:
            bbox = measure.textbbox((0, 0), line, font=font)
            w, h = bbox[2] + 1, bbox[3] + 1
            img = PILImage.new("L", (max(1, w), max(1, h)), 0)
            ImageDraw.Draw(img).text((0, 0), line, fill=255, font=font)
            px = img.load()
            for cy in range(img.height):
                for cx in range(img.width):
                    if px[cx, cy] >= threshold:
                        bx, by = cx * scale, (cy + y_src) * scale
                        for sy in range(scale):
                            for sx in range(scale):
                                coords.append((bx + sx, by + sy))
            max_w = max(max_w, img.width)
        y_src += line_h + spacing
    return coords, max_w * scale, y_src * scale


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

    Returns the standard draw result plus the rendered text's pixel size.
    """
    from PIL import ImageFont

    scale = max(1, int(scale))
    if font_path:
        font = ImageFont.truetype(str(resolve_path(font_path)), max(1, int(font_size)))
    else:
        font = ImageFont.load_default()

    coords, w, h = _render_text_pixels(text, scale, font, max(0, int(spacing)), int(threshold))
    if not coords:
        raise ValueError("Text rendered no pixels (empty string or threshold too high).")
    if len(coords) > _MAX_TEXT_PIXELS:
        raise ValueError(
            f"Text is too large ({len(coords)} pixels). Reduce scale/font_size or shorten it."
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
