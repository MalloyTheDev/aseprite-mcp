"""Hard size limits on user-supplied work: a DoS guard at the validation boundary.

These are conservative ceilings, not tuning knobs: they bound the worst-case memory and
time of a single tool call while staying well above any legitimate pixel-art workload.
There is intentionally **no environment/config override**: raise the relevant constant
(and document it) only if real demand appears. Exceeding a limit raises ``ValidationFailed``
with the field name, the received size, the cap, and how to recover.

Two families live here:

* **Collection limits**: how many items a single call may carry (``check_list_length``).
* **Geometry limits**: how big a canvas a single call may ask Aseprite to allocate
  (``check_canvas_size``). A dimension alone is a weak guard: 65535x65535 is within any
  per-axis bound yet is ~17 GB of RGBA pixels, so the *area* is capped too.
"""

from __future__ import annotations

from collections.abc import Sized

from .errors import ValidationFailed

# Maximum number of operations in a single apply_operations batch.
MAX_BATCH_OPERATIONS = 500
# Maximum length of an explicit pixel/point coordinate list in one call
# (65,536 == a full 256x256 sprite's worth of pixels).
MAX_PIXEL_LIST_LENGTH = 65_536
# Maximum number of tile placements in one set_tiles call.
MAX_TILE_LIST_LENGTH = 65_536
# Maximum number of palette colours in one set_palette call (indexed-palette ceiling).
MAX_COLOR_LIST_LENGTH = 256

# --- Geometry -------------------------------------------------------------- #
# Maximum length of either canvas axis. Aseprite's own file format tops out at
# 65535, but a single axis that long is never a pixel-art workload.
MAX_CANVAS_DIMENSION = 16_384
# Maximum canvas *area* in pixels (~67 MB of RGBA). A 4096x4096 sheet passes;
# 16384x16384 (1 GB) does not, even though both axes are within the per-axis cap.
MAX_CANVAS_PIXELS = 16_777_216  # 4096 * 4096

# --- Inline payloads ------------------------------------------------------- #
# Maximum decoded size of an inline base64 image handed to draw_image_base64.
MAX_IMAGE_BYTES = 32 * 1024 * 1024
# Maximum number of pixels one draw_text call may plot.
MAX_TEXT_PIXELS = 200_000
# Bounds on the text-rendering knobs that multiply into that pixel count.
MAX_TEXT_SCALE = 64
MAX_FONT_SIZE = 512
# Maximum characters of Aseprite stdout/stderr retained for a single invocation.
# Characters, not bytes: subprocess.run has already decoded the stream into a str by
# the time this applies, so the guard bounds what is carried into an error message
# rather than what is read. Measuring characters keeps that check free; measuring
# bytes would re-encode every captured stream, including the small common case.
MAX_PROCESS_OUTPUT_CHARS = 8 * 1024 * 1024


def check_list_length(
    field: str,
    items: Sized,
    maximum: int,
    *,
    remedy: str = "Split the request into smaller calls.",
) -> None:
    """Raise ``ValidationFailed`` if ``items`` is longer than ``maximum``.

    The message names the field, the received count, the cap, and how to recover, e.g.
    ``operations has 731 items; maximum is 500. Split the edit into multiple batches.``
    """
    count = len(items)
    if count > maximum:
        raise ValidationFailed(
            f"{field} has {count} items; maximum is {maximum}. {remedy}"
        )


def check_size_bytes(
    field: str,
    size: int,
    maximum: int = MAX_IMAGE_BYTES,
    *,
    remedy: str = "Use a smaller payload, or write the file to the workspace and pass its path.",
) -> None:
    """Raise ``ValidationFailed`` if ``size`` bytes exceeds ``maximum``."""
    if size > maximum:
        raise ValidationFailed(
            f"{field} is {size} bytes; maximum is {maximum}. {remedy}"
        )


def check_canvas_size(
    width: int,
    height: int,
    *,
    field: str = "canvas",
    max_dimension: int = MAX_CANVAS_DIMENSION,
    max_pixels: int = MAX_CANVAS_PIXELS,
) -> tuple[int, int]:
    """Validate a canvas size and return it as ``(width, height)`` ints.

    Rejects non-positive axes, either axis over ``max_dimension``, and any canvas whose
    ``width * height`` exceeds ``max_pixels``. The area check is the one that matters,
    since a pair of individually-legal axes can still be gigabytes of pixels.
    """
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        raise ValidationFailed(
            f"{field} size must be whole numbers of pixels, got {width!r}x{height!r}."
        ) from None

    if w < 1 or h < 1:
        raise ValidationFailed(
            f"{field} size must be at least 1x1, got {w}x{h}."
        )
    if w > max_dimension or h > max_dimension:
        raise ValidationFailed(
            f"{field} size {w}x{h} exceeds the maximum dimension of {max_dimension}px "
            f"per axis. Work at a smaller size, or export an upscaled copy instead."
        )
    if w * h > max_pixels:
        raise ValidationFailed(
            f"{field} size {w}x{h} is {w * h} pixels; maximum is {max_pixels} "
            f"(e.g. 4096x4096). Reduce the canvas, or split the work across sprites."
        )
    return w, h
