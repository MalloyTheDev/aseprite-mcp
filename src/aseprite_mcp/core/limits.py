"""Hard size limits on user-supplied work: a DoS guard at the validation boundary.

These are conservative ceilings, not tuning knobs: they bound the worst-case memory and
time of a single tool call while staying well above any legitimate pixel-art workload.
There is intentionally **no environment/config override**: raise the relevant constant
(and document it) only if real demand appears. Exceeding a limit raises ``ValidationFailed``
with the field name, the received size, the cap, and how to recover.

Three families live here:

* **Collection limits**: how many items a single call may carry (``check_list_length``).
* **Geometry limits**: how big a canvas a single call may ask Aseprite to allocate
  (``check_canvas_size``). A dimension alone is a weak guard: 65535x65535 is within any
  per-axis bound yet is ~17 GB of RGBA pixels, so the *area* is capped too.
* **Scalar limits**: how large a loop bound, repetition count or index a single call may
  set (``check_count``). A scalar is as expensive as a list of the same length: it *is*
  the bound the generated Lua loop runs to, so one integer buys the same work as 1e9
  list items without carrying them over the wire.
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
# Maximum number of palette colours in one call (indexed-palette ceiling). This is the
# palette ceiling for *every* route to a palette, not just the one tool that takes a
# list: `resize_palette(size)` and `set_palette_color(index)` reach the same palette
# through a single integer, so they are bounded by the same number.
MAX_COLOR_LIST_LENGTH = 256

# --- Scalars that multiply into work --------------------------------------- #
# A brush is a stamp, not an image. 65,536 cells is a 256x256 stamp: far larger than
# anything anyone writes out as rows of characters, and already the whole pixel budget
# of a 256x256 sprite. Bigger belongs in stamp_pattern or draw_image_base64. The same
# number bounds the row count, since a 1-cell-wide brush of N rows is N cells.
MAX_BRUSH_CELLS = 65_536
# Maximum cell plots one draw_brush may perform: filled cells times stamp points. The
# two list caps do not bound this product, and the product is the work. Generous by
# construction: a 16x16 brush over 65,536 points, or a 64x64 brush over 4,096 points.
MAX_BRUSH_PLOTS = 16_777_216
# Maximum outline width in pixels. Each unit of thickness is a full-canvas scan times
# 8 neighbours, so thickness is a repeat count, not a size. A chunky pixel-art outline
# is 1-3px; 64 is wider than any sprite this server draws is likely to be tall.
MAX_OUTLINE_THICKNESS = 64
# Maximum sample steps for one quadratic Bezier. Steps beyond the curve's own length in
# pixels add nothing visible, and the longest on-canvas curve is ~23,000px end to end;
# 4,096 is smooth for any curve that fits in a sprite (the default is 32).
MAX_CURVE_STEPS = 4_096

# --- Assessment ------------------------------------------------------------ #
# Pixels one `assess_sprite` call will measure. The metrics are O(pixels) in Python and
# the grid is read in a single launch, so the cap is about the caller's patience rather
# than about correctness: a 1024x1024 frame is already far past any sprite, and a photo
# imported at full size is the case that would otherwise stall for a minute.
MAX_ASSESS_PIXELS = 1_048_576

# Distinct colours `diff_sprites` lists per side. A diff names the colours involved in
# the change so the odd one out is visible; past a couple of dozen that list is a photo
# histogram rather than a finding, and the count still says how many there were.
MAX_DIFF_COLORS = 24

# --- Lighting and effects -------------------------------------------------- #
# These three guard the *picture* rather than the process, which makes them the odd family
# in this module: none of them bounds an allocation or a loop. They are here because the
# alternative is three magic numbers buried in three tool bodies, and a cap nobody can
# find is a cap nobody can raise.
#
# How strong a fill light may be, as a fraction of the key light. A fill that matches the
# key cancels the form: the two terminators land on opposite sides and the result is the
# flat fill the shading was meant to replace. Pixel art conventionally fills at a third to
# a half of key, so this leaves plenty of headroom above the usual choice while refusing
# the value that destroys the thing being asked for.
MAX_FILL_LIGHT_STRENGTH = 0.75
# Pixels in one specular highlight. A specular is two or three pixels on most sprites,
# and a glint spread wide enough to need a cap has stopped being a glint and become a
# second lit region, which shade_region_by_light describes properly. The number is also
# what bounds the blob-growing loop, which is quadratic in it.
MAX_SPECULAR_PIXELS = 64
# Rings in one glow. The distance field is a chamfer transform over the whole canvas, so
# the cost is the same whatever the radius and this is not a work bound. It is a craft
# bound: a glow wider than a sprite is tall has stopped being a halo and become a
# background fill, which fill_gradient does better.
MAX_GLOW_RADIUS = 32
# Pixels of penumbra around a cast shadow's core. Each one is another whole ellipse
# rasterised and another ramp step consumed, and a shadow whose soft edge is wider than
# the hard core reads as a gradient rather than as a shadow.
MAX_SHADOW_SOFTNESS = 8
# Points one cast shadow's ellipse may rasterise. Unlike the four above, this one guards
# the *allocation* rather than the picture, which is why it is a large round number rather
# than a craft judgement.
#
# `ellipse_offsets` emits one two-element Lua table per pixel of a filled ellipse's area
# and builds the entire list before returning it, so the point count IS the memory. The
# radii are quadratic in the inputs and the canvas cap is generous: a 16,384-wide sprite
# with a near-full-width subject under a low light reaches roughly 1.5e8 points, which is
# an out-of-memory with no partial result, reached from arguments that are each
# individually valid. A per-axis check cannot see it, exactly as a canvas dimension cannot
# see a 17 GB canvas.
#
# 2^21 points is a few hundred megabytes at Lua's per-table overhead, and an ellipse that
# large is already far past what any sprite displays usefully, so this refuses the
# allocation without second-guessing a genuinely large sprite.
MAX_SHADOW_ELLIPSE_POINTS = 2_097_152

# --- Animation ------------------------------------------------------------- #
# How many times a tag may say it plays. Aseprite stores the count in 16 bits and treats
# 0 as "forever", which is how a cycle is marked; the cap is the format's, not ours.
MAX_TAG_REPEATS = 65_535

# Frames one call may move a cel across. The distribution is computed in Python and
# applied inside a single transaction, so the work is one launch whatever the count; the
# cap is here because the frame list comes from the caller, and a request for more frames
# than the longest hand-drawn cycle (well under 100) is a mistake worth naming early.
MAX_MOTION_FRAMES = 512

# --- Workflow scaffolding -------------------------------------------------- #
# These bound the most expensive calls in the server: one integer asks for frames, and
# each frame used to cost two Aseprite launches.
# 8 is the classic direction set and 16 is as fine-grained as directional sprite sheets
# get drawn; 32 is double the finest.
MAX_WALK_DIRECTIONS = 32
# A hand-drawn walk cycle is 4-12 frames; 32 covers the most detailed run cycle. With
# the direction cap this bounds a template at 1,024 frames.
MAX_FRAMES_PER_DIRECTION = 32
# Maximum cells in a scaffolded grid sheet (icon set / item sheet / tileset starter).
# Each cell is a placeholder plus a named slice, so cells cost launches. 1,024 cells is
# a 32x32 grid: a larger atlas than any of these scaffolds is meant to start.
MAX_GRID_CELLS = 1_024

# --- Declarative asset specs ----------------------------------------------- #
# The spec layer amplifies harder than any tool: one integer becomes two batch operations
# per frame, and one list entry becomes a whole Aseprite launch at build time. Uncapped,
# `frame_count: 200000` planned 400,000 operations in a third of a second and returned
# every one of them inside the manifest, so the dry run that exists to be a cheap
# pre-flight was neither cheap nor safe to point at an untrusted document.
#
# The frame caps sit well under MAX_BATCH_OPERATIONS (two operations per frame) so a spec
# inside them normally fits one structural batch; the planner still checks the aggregate,
# because per-field caps do not bound the sum.
MAX_SPEC_ANIMATION_FRAMES = 120
MAX_SPEC_TOTAL_FRAMES = 240
MAX_SPEC_LAYERS = 64
# Slices and exports each cost a separate Aseprite launch rather than one batch operation,
# so a long list costs process launches, not memory.
MAX_SPEC_SLICES = 256
MAX_SPEC_EXPORTS = 32

# --- Geometry -------------------------------------------------------------- #
# Maximum length of either canvas axis. Aseprite's own file format tops out at
# 65535, but a single axis that long is never a pixel-art workload.
MAX_CANVAS_DIMENSION = 16_384
# Maximum canvas *area* in pixels (~67 MB of RGBA). A 4096x4096 sheet passes;
# 16384x16384 (1 GB) does not, even though both axes are within the per-axis cap.
MAX_CANVAS_PIXELS = 16_777_216  # 4096 * 4096

# Maximum total pixel storage a single sprite operation may ask Aseprite to hold.
# A canvas cap alone is not enough: SpriteSize rescales every cel, so a sprite with
# many independent full-frame cels multiplies one legal target canvas by the cel
# count (100 cels at 4096x4096 is ~1.7 Gpx, several GB of RGBA).
MAX_SPRITE_TOTAL_PIXELS = 67_108_864  # 4x one max canvas

# --- Inline payloads ------------------------------------------------------- #
# Maximum decoded size of an inline base64 image handed to draw_image_base64.
MAX_IMAGE_BYTES = 32 * 1024 * 1024
# Maximum number of pixels one draw_text call may plot.
MAX_TEXT_PIXELS = 200_000
# Maximum size of the intermediate (unscaled) Pillow bitmap used to rasterize one
# line. This bounds the allocation only. It is deliberately separate from
# MAX_TEXT_PIXELS: the plotted-pixel budget counts pixels that pass the threshold,
# so folding the scale factor into the bitmap check would reject sparse or
# whitespace-heavy text that plots almost nothing.
MAX_TEXT_BITMAP_PIXELS = 4_194_304
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


def check_count(
    field: str,
    value: int,
    maximum: int,
    *,
    minimum: int = 0,
    remedy: str = "Use a smaller value.",
) -> int:
    """Validate a scalar count and return it as an int.

    The scalar counterpart of :func:`check_list_length`, with the same message shape
    (field, received value, cap, how to recover), e.g.
    ``thickness is 4096; maximum is 64. Outline in several calls if you need more.``
    A loop bound or repetition count costs whatever a list of that length would, so it
    is checked the same way.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationFailed(
            f"{field} must be a whole number, got {value!r}."
        ) from None
    if n < minimum:
        raise ValidationFailed(f"{field} is {n}; minimum is {minimum}.")
    if n > maximum:
        raise ValidationFailed(f"{field} is {n}; maximum is {maximum}. {remedy}")
    return n


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


def check_region_size(
    width: int | None,
    height: int | None,
    *,
    field: str = "region",
) -> None:
    """Validate an optional fill region, where ``None`` on an axis means "to the edge".

    A region is a canvas-shaped quantity and is bounded like one. The generated fill
    loops read ``for yy = ry, ry + rh - 1`` with only an inner on-canvas skip, so an
    oversized region iterates in full even when every pixel is off-canvas and nothing
    is drawn: ``width=1e9`` is 1e9 iterations on a 16x16 sprite. When one axis is
    omitted the canvas supplies it at run time and is already bounded, so only the
    given axis is checked.
    """
    remedy = "Fill a smaller region, or leave width/height unset for the whole canvas."
    if width is not None and height is not None:
        check_canvas_size(width, height, field=field)
    elif width is not None:
        check_count(f"{field} width", width, MAX_CANVAS_DIMENSION, minimum=1, remedy=remedy)
    elif height is not None:
        check_count(f"{field} height", height, MAX_CANVAS_DIMENSION, minimum=1, remedy=remedy)
