# Aseprite MCP — Tool Reference

Auto-generated from the live tool registry by `scripts/gen_tool_docs.py`. **98 tools.**

Colours accept `#RRGGBB`, `#RRGGBBAA`, `r,g,b`, `r,g,b,a`, `index:N`, or a name (black, white, red, green, blue, yellow, cyan, magenta, transparent, …). Frames are 1-based; palette indices are 0-based. Relative paths resolve inside the workspace.

## Contents

- [Sprite lifecycle](#sprite-lifecycle) (10)
- [Inspection & preview](#inspection--preview) (4)
- [Layers](#layers) (8)
- [Frames (animation)](#frames-animation) (5)
- [Animation tags](#animation-tags) (3)
- [Cels](#cels) (5)
- [Drawing](#drawing) (9)
- [Brushes & symmetry](#brushes--symmetry) (4)
- [Effects & colour adjustments](#effects--colour-adjustments) (9)
- [Text](#text) (1)
- [Tilemaps](#tilemaps) (8)
- [Image stamping](#image-stamping) (2)
- [Palette](#palette) (10)
- [Slices](#slices) (4)
- [Transforms](#transforms) (2)
- [Export & import](#export--import) (10)
- [Reference / rotoscope](#reference--rotoscope) (2)
- [GUI companion mode](#gui-companion-mode) (2)

## Sprite lifecycle

### `convert_background_to_layer`

Convert the Background layer back into a normal (transparent-capable) layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `convert_layer_to_background`

Convert a normal layer into the sprite's opaque Background layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |


### `create_sprite`

Create a new sprite file and save it.

    Args:
        filename: Output path. Relative paths go in the workspace. Use a
            .aseprite/.ase extension to keep layers & frames editable.
        width, height: Canvas size in pixels (1-65535).
        color_mode: "rgb" (default), "indexed", or "gray".
        background: Optional fill colour for the first layer (e.g. "#1d2b53").
            Omit for a transparent canvas.

    Returns the new sprite's structured info.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `color_mode` | string | no | rgb |
| `background` | string | null | no | None |


### `crop_sprite`

Crop the canvas to the rectangle (x, y, width, height).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |


### `flatten_sprite`

Flatten all layers into a single layer (in place).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `resize_canvas`

Resize the canvas WITHOUT scaling the artwork (adds or trims space).

    anchor controls where existing content sits in the new canvas:
    "top_left" (default) or "center".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `anchor` | string | no | top_left |


### `save_sprite_as`

Save a copy of a sprite under a new path (optionally flattened).

    The original file is left untouched. Useful for exporting an editable
    .aseprite to another .aseprite, or snapshotting a version.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `new_filename` | string | yes |  |
| `flatten` | boolean | no | False |


### `scale_sprite`

Scale the whole sprite (artwork included).

    Provide either `factor` (e.g. 2.0 to double) OR explicit `width`/`height`.
    method: "nearest" (crisp pixels, default) or "bilinear" (smooth).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `factor` | number | null | no | None |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `method` | string | no | nearest |


### `set_color_mode`

Convert a sprite between colour modes ("rgb", "indexed", "gray").

    When converting to "indexed", dithering can be "none", "ordered", or
    "old" to control how RGB colours are mapped to the palette.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color_mode` | string | yes |  |
| `dithering` | string | no | none |


### `trim_sprite`

Auto-crop the canvas to the bounding box of all non-transparent content
    (across every frame).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


## Inspection & preview

### `get_pixels`

Read the composited (all visible layers) pixel colours of a region.

    Returns rows of "#RRGGBBAA" hex strings. The region is capped at 64x64
    (4096 pixels) per call to keep responses small — read in tiles for bigger areas.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `frame` | integer | no | 1 |


### `get_sprite_info`

Return structured info about a sprite: size, colour mode, frames (with
    durations), the full layer tree (names, opacity, blend mode, visibility),
    animation tags, and palette size.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `list_sprites`

List sprite/image files in the workspace directory.

_No parameters._


### `render_preview`

Render a single frame to a PNG and return it as an image you can view.

    Use this to *see* your work. frame is 1-based; scale enlarges small sprites
    (default 8x) so individual pixels are visible.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | no | 1 |
| `scale` | integer | no | 8 |


## Layers

### `add_group_layer`

Add a new (empty) group layer on top of the stack. Nest layers into it
    with add_layer(group=...) or move_layer(group=...).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |


### `add_layer`

Add a new (empty) normal layer on top of the stack.

    Args:
        name: Layer name.
        group: Optional name of an existing group layer to nest the new layer in.
        opacity: 0-255.
        blend_mode: normal, multiply, screen, overlay, darken, lighten,
            color_dodge, color_burn, hard_light, soft_light, difference,
            exclusion, hue, saturation, color, luminosity, addition, subtract, divide.
        visible: Initial visibility.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `group` | string | null | no | None |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `visible` | boolean | no | True |


### `duplicate_layer`

Duplicate a layer (including its cels) as a new layer on top.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |


### `merge_layer_down`

Merge a layer down into the layer directly beneath it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |


### `move_layer`

Reorder a layer to a new 1-based stack index (1 = bottom-most).

    Note: moves within the layer's current parent group.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `to_index` | integer | yes |  |


### `remove_layer`

Delete a layer (or group, including its children) by name or 1-based index.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |


### `rename_layer`

Rename a layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `new_name` | string | yes |  |


### `set_layer_properties`

Update one or more layer properties. Only the arguments you pass are changed.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `opacity` | integer | null | no | None |
| `blend_mode` | string | null | no | None |
| `visible` | boolean | null | no | None |
| `editable` | boolean | null | no | None |
| `name` | string | null | no | None |


## Frames (animation)

### `add_frame`

Append a new frame to the animation.

    Args:
        duration_ms: Frame duration in milliseconds (default 100).
        copy_from: If given (1-based), duplicate the content of that frame;
            otherwise the new frame is empty.

    Returns the new frame number and updated frame count.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `duration_ms` | integer | no | 100 |
| `copy_from` | integer | null | no | None |


### `duplicate_frame`

Duplicate an existing frame (1-based); the copy is inserted after it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |


### `remove_frame`

Delete a frame (1-based). The sprite must have more than one frame.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |


### `set_all_frame_durations`

Set every frame's duration in milliseconds (uniform animation speed).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `duration_ms` | integer | yes |  |


### `set_frame_duration`

Set a single frame's duration in milliseconds (1-based frame).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |
| `duration_ms` | integer | yes |  |


## Animation tags

### `add_tag`

Create an animation tag spanning frames [from_frame, to_frame] (1-based).

    direction: "forward" (default), "reverse", "pingpong", or "pingpong_reverse".
    color: optional tag colour (shown in the timeline).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `from_frame` | integer | yes |  |
| `to_frame` | integer | yes |  |
| `direction` | string | no | forward |
| `color` | string | null | no | None |


### `remove_tag`

Delete an animation tag by name.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |


### `set_tag`

Update an existing tag. Only the arguments you pass are changed.

    Note: changing from_frame/to_frame recreates the tag in place to update its
    range reliably across Aseprite versions.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `from_frame` | integer | null | no | None |
| `to_frame` | integer | null | no | None |
| `new_name` | string | null | no | None |
| `direction` | string | null | no | None |
| `color` | string | null | no | None |


## Cels

### `copy_cel`

Copy a cel's image (and position) from one frame to another on the same layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `from_frame` | integer | yes |  |
| `to_frame` | integer | yes |  |


### `delete_cel`

Delete a cel (the layer becomes empty at that frame).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | yes |  |


### `get_cel`

Inspect a cel: whether it exists, its position, bounds, and opacity.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | no | 1 |


### `set_cel_opacity`

Set a cel's opacity (0-255).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | yes |  |
| `opacity` | integer | yes |  |


### `set_cel_position`

Move a cel's image to position (x, y) within the canvas.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |


## Drawing

### `clear_layer`

Erase the target layer/frame cel to full transparency.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_curve`

Draw a quadratic Bézier curve from (x0,y0) to (x1,y1) bending toward the
    control point (control_x, control_y). `steps` controls smoothness.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x0` | integer | yes |  |
| `y0` | integer | yes |  |
| `control_x` | integer | yes |  |
| `control_y` | integer | yes |  |
| `x1` | integer | yes |  |
| `y1` | integer | yes |  |
| `color` | string | yes |  |
| `steps` | integer | no | 32 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_ellipse`

Draw an ellipse centred at (center_x, center_y) with the given radii.

    For a circle, use the same value for radius_x and radius_y. filled=False
    draws a 1px outline. antialias smooths a *filled* ellipse with sub-pixel
    coverage (RGB sprites only; ignored otherwise).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `center_x` | integer | yes |  |
| `center_y` | integer | yes |  |
| `radius_x` | integer | yes |  |
| `radius_y` | integer | yes |  |
| `color` | string | yes |  |
| `filled` | boolean | no | False |
| `antialias` | boolean | no | False |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_line`

Draw a straight line from (x1,y1) to (x2,y2).

    Args:
        pixel_perfect: Remove L-shaped corner pixels for a clean 1px pixel-art line.
        antialias: Smooth (Xiaolin Wu) line with alpha blending — RGB sprites only;
            ignored on indexed/gray. Takes precedence over pixel_perfect.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x1` | integer | yes |  |
| `y1` | integer | yes |  |
| `x2` | integer | yes |  |
| `y2` | integer | yes |  |
| `color` | string | yes |  |
| `pixel_perfect` | boolean | no | False |
| `antialias` | boolean | no | False |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_pixels`

Plot individual pixels.

    Args:
        pixels: List of {"x": int, "y": int, "color": "#hex"?}. If a pixel omits
            "color", the shared `color` argument is used.
        color: Default colour for pixels that don't specify their own.
        layer: Target layer name or 1-based index (default: top layer).
        frame: Target frame, 1-based (default 1).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `pixels` | array<object> | yes |  |
| `color` | string | null | no | None |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_polyline`

Draw connected line segments through a list of points.

    points: list of {"x": int, "y": int}. Set closed=True to connect the last
    point back to the first (outline a polygon). pixel_perfect removes L-corner
    pixels across the whole path for a clean pixel-art outline.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `points` | array<object> | yes |  |
| `color` | string | yes |  |
| `closed` | boolean | no | False |
| `pixel_perfect` | boolean | no | False |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_rectangle`

Draw a rectangle. filled=False draws a 1px outline, True fills it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `color` | string | yes |  |
| `filled` | boolean | no | False |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `fill_area`

Flood fill (paint bucket): replace the contiguous region of matching
    colour starting at (x,y) on the target layer with `color`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `color` | string | yes |  |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `fill_layer`

Fill the entire target layer/frame cel with a solid colour.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


## Brushes & symmetry

### `draw_brush`

Stamp a custom brush shape at a list of points.

    Args:
        brush: The brush as rows of characters. Any character other than space,
            '.', or '0' is a filled cell. e.g. a plus brush: ["010", "111", "010"].
        points: Positions to stamp at, list of {"x": int, "y": int}.
        color: Colour to stamp the brush in.
        anchor: "center" (default) or "topleft" — where each point sits in the brush.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `brush` | array<string> | yes |  |
| `points` | array<object> | yes |  |
| `color` | string | yes |  |
| `anchor` | string | no | center |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `draw_symmetric_pixels`

Plot pixels together with their mirror image(s).

    mode: "horizontal" (mirror across vertical axis_x), "vertical" (across axis_y),
    or "both" (4-way radial symmetry). Axes default to the canvas centre.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `pixels` | array<object> | yes |  |
| `color` | string | yes |  |
| `mode` | string | no | horizontal |
| `axis_x` | integer | null | no | None |
| `axis_y` | integer | null | no | None |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `mirror_layer`

Mirror one half of a layer onto the other (build symmetric artwork).

    Args:
        direction: "horizontal" (reflect left<->right) or "vertical" (top<->bottom).
        source_side: which half is copied: "first" (left/top) or "second" (right/bottom).
        axis: mirror line position (x for horizontal, y for vertical); default = centre.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `direction` | string | no | horizontal |
| `source_side` | string | no | first |
| `axis` | integer | null | no | None |
| `frame` | integer | no | 1 |


### `stamp_pattern`

Tile an image/sprite across a region to fill it with a repeating pattern.

    Args:
        source: Image/sprite to tile.
        x, y, width, height: Region to fill (defaults to the whole canvas).
        spacing_x, spacing_y: Gap between tiles.
        opacity, blend_mode: Compositing of each tile.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `source` | string | yes |  |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `spacing_x` | integer | no | 0 |
| `spacing_y` | integer | no | 0 |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


## Effects & colour adjustments

### `add_drop_shadow`

Add a hard drop shadow for a layer's artwork on a new layer placed beneath it.

    Args:
        layer: The layer casting the shadow.
        offset_x, offset_y: Shadow offset in pixels.
        color: Shadow colour (often semi-transparent black, the default).
        opacity: Opacity (0-255) of the shadow layer.
        frame: Frame to build the shadow for.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `offset_x` | integer | no | 1 |
| `offset_y` | integer | no | 1 |
| `color` | string | no | #00000080 |
| `opacity` | integer | no | 255 |
| `frame` | integer | no | 1 |


### `add_outline`

Add a pixel outline around the artwork on a layer.

    Args:
        color: Outline colour.
        thickness: Outline width in pixels (default 1).
        connectivity: 4 (orthogonal only) or 8 (includes diagonals, default).
        where: "outside" (grow into transparency, default) or "inside"
            (recolour the shape's border pixels).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |
| `thickness` | integer | no | 1 |
| `connectivity` | integer | no | 8 |
| `where` | string | no | outside |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `adjust_brightness_contrast`

Adjust brightness (-255..255, additive) and contrast (-255..255) of a layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `brightness` | integer | no | 0 |
| `contrast` | integer | no | 0 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `adjust_hue_saturation`

Shift hue (degrees) and scale saturation/lightness (percent, -100..100).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `hue` | integer | no | 0 |
| `saturation` | integer | no | 0 |
| `lightness` | integer | no | 0 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `desaturate`

Desaturate toward grayscale by `amount` percent (0-100).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `amount` | integer | no | 100 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `fill_checkerboard`

Fill a region with a 2-colour checkerboard of `size`-pixel squares.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color1` | string | yes |  |
| `color2` | string | yes |  |
| `size` | integer | no | 1 |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `fill_gradient`

Fill a region with a gradient.

    Args:
        colors: 2+ colour stops, e.g. ["#000000", "#ff004d", "#ffec27"], spread
            evenly. For dither=True, provide exactly 2 colours.
        gradient_type: "linear" or "radial".
        angle: Direction in degrees for linear gradients (0 = left->right).
        dither: Ordered (Bayer 4x4) dithering between 2 colours instead of smooth
            interpolation — great for limited palettes / retro looks.
        x, y, width, height: Region (defaults to the whole canvas).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `colors` | array<string> | yes |  |
| `gradient_type` | string | no | linear |
| `angle` | number | no | 0.0 |
| `dither` | boolean | no | False |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `invert_colors`

Invert the RGB colours of a layer's pixels (alpha preserved).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `replace_color`

Replace every pixel matching `from_color` (within `tolerance` per channel)
    with `to_color`, on the chosen layer + frame.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `from_color` | string | yes |  |
| `to_color` | string | yes |  |
| `tolerance` | integer | no | 0 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


## Text

### `draw_text`

Draw text onto a layer at (x, y) in a single colour.

    Args:
        text: The string (supports "\n" for multiple lines).
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

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `text` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `color` | string | yes |  |
| `scale` | integer | no | 1 |
| `font_path` | string | null | no | None |
| `font_size` | integer | no | 16 |
| `spacing` | integer | no | 1 |
| `threshold` | integer | no | 128 |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


## Tilemaps

### `add_tile`

Add a new tile to the layer's tileset (optionally filled with a solid colour).
    Returns the new tile's index.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `color` | string | null | no | None |
| `frame` | integer | no | 1 |


### `create_tilemap_layer`

Create a tilemap layer with an empty grid.

    Args:
        name: Layer name.
        tile_width, tile_height: Tile size in pixels (sets the sprite grid).
        columns, rows: Grid size in tiles (default: enough to cover the canvas).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `tile_width` | integer | no | 16 |
| `tile_height` | integer | no | 16 |
| `columns` | integer | null | no | None |
| `rows` | integer | null | no | None |
| `frame` | integer | no | 1 |


### `fill_tile`

Fill an existing tile's artwork with a solid colour.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `tile_index` | integer | yes |  |
| `color` | string | yes |  |
| `frame` | integer | no | 1 |


### `fill_tilemap`

Fill the entire tilemap grid with a single tile index.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `tile_index` | integer | yes |  |
| `frame` | integer | no | 1 |


### `get_tilemap`

Read the tilemap as a 2D grid of tile indices, plus tile size and count.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | no | 1 |


### `paint_tile_pixels`

Draw individual pixels into a tile's artwork (tile-local coordinates).

    pixels: list of {"x", "y", "color"?}; falls back to the shared `color`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `tile_index` | integer | yes |  |
| `pixels` | array<object> | yes |  |
| `color` | string | null | no | None |
| `frame` | integer | no | 1 |


### `set_tile`

Place a tile (by tileset index, 0 = empty) at grid cell (column, row).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `column` | integer | yes |  |
| `row` | integer | yes |  |
| `tile_index` | integer | yes |  |
| `frame` | integer | no | 1 |


### `set_tiles`

Place many tiles at once. tiles: list of {"column", "row", "index"}.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `tiles` | array<object> | yes |  |
| `frame` | integer | no | 1 |


## Image stamping

### `draw_image_base64`

Composite an inline base64-encoded PNG (or other image) onto a layer at (x, y).

    Useful for pasting externally generated artwork. `image_base64` may include a
    `data:image/png;base64,` prefix.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `image_base64` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


### `stamp_file`

Composite another image/sprite file onto a layer at (x, y).

    Args:
        source: Path to a .aseprite/.png/.bmp/... to stamp in.
        x, y: Top-left placement on the target canvas.
        source_frame: Which frame of the source to use (1-based).
        opacity: 0-255.
        blend_mode: Blend mode for compositing (normal, multiply, …).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `source` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `source_frame` | integer | no | 1 |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `layer` | string | null | no | None |
| `frame` | integer | no | 1 |


## Palette

### `add_palette_color`

Append a colour to the end of the palette.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |


### `extract_palette`

Extract the unique colours used in a sprite (or another image).

    Args:
        from_image: Optional image/sprite to scan instead of `filename`.
        set_as_palette: Apply the extracted colours as `filename`'s palette.
        include_alpha: Treat differing alpha as distinct colours (default off).
        max_colors: Error out if more unique colours than this are found.

    Returns the list of "#RRGGBBAA" colours found.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `from_image` | string | null | no | None |
| `set_as_palette` | boolean | no | True |
| `include_alpha` | boolean | no | False |
| `max_colors` | integer | no | 256 |


### `generate_ramp`

Generate a shading ramp from a base colour (dark -> light).

    Produces `steps` colours by varying lightness across `light_range`, optionally
    rotating hue by `hue_shift` total degrees across the ramp (classic pixel-art
    hue shifting: cool shadows / warm highlights) and scaling saturation by
    `saturation_shift` percent across the ramp.

    Args:
        filename: If set with apply, write the ramp into that sprite's palette.
        apply: "none" (just return), "append" (add to palette), or "replace".

    Returns the ramp as a list of "#RRGGBB" colours (darkest first).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `base_color` | string | yes |  |
| `steps` | integer | no | 5 |
| `hue_shift` | number | no | 0.0 |
| `saturation_shift` | number | no | 0.0 |
| `light_range` | number | no | 0.6 |
| `filename` | string | null | no | None |
| `apply` | string | no | none |


### `get_palette`

Return the sprite's palette as a list of "#RRGGBBAA" colours.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `load_palette`

Load a palette from a file (.gpl, .pal, .aseprite, .png, ...) and apply it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `palette_file` | string | yes |  |


### `resize_palette`

Resize the palette to `size` entries (new entries are black).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `size` | integer | yes |  |


### `set_palette`

Replace the entire palette with the given list of colours.

    colors: list of colour strings, e.g. ["#000000", "#ffffff", "255,0,0"].

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `colors` | array<string> | yes |  |


### `set_palette_color`

Set a single palette entry by index (0-based). Grows the palette if needed.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `index` | integer | yes |  |
| `color` | string | yes |  |


### `set_transparent_color`

Set which palette index is treated as transparent (indexed sprites only).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `index` | integer | yes |  |


### `sort_palette`

Sort the palette by "hue", "luminance" (default), "saturation", or "value".

    For indexed sprites the pixel indices are remapped so the image looks identical.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `by` | string | no | luminance |
| `reverse` | boolean | no | False |


## Slices

### `add_slice`

Create a slice (named region) at (x, y, width, height).

    Args:
        center_*: Optional 9-patch center rectangle, **relative to the slice's
            top-left**. Provide all four to mark the stretchable middle.
        pivot_*: Optional pivot point (relative to the slice).
        color: Optional slice colour shown in the editor.
        data: Optional user data string.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `center_x` | integer | null | no | None |
| `center_y` | integer | null | no | None |
| `center_width` | integer | null | no | None |
| `center_height` | integer | null | no | None |
| `pivot_x` | integer | null | no | None |
| `pivot_y` | integer | null | no | None |
| `color` | string | null | no | None |
| `data` | string | null | no | None |


### `list_slices`

List all slices in the sprite with their bounds, center, and pivot.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `remove_slice`

Delete a slice by name.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |


### `set_slice`

Update an existing slice's bounds, name, colour, or data.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `x` | integer | null | no | None |
| `y` | integer | null | no | None |
| `width` | integer | null | no | None |
| `height` | integer | null | no | None |
| `new_name` | string | null | no | None |
| `color` | string | null | no | None |
| `data` | string | null | no | None |


## Transforms

### `flip_sprite`

Flip the entire sprite. direction: "horizontal" or "vertical".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `direction` | string | no | horizontal |


### `rotate_sprite`

Rotate the entire sprite by 90, 180, or 270 degrees (clockwise).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `angle` | integer | yes |  |


## Export & import

### `export_frames`

Export each frame to its own image file.

    output_pattern must contain "{frame}" (and optionally "{tag}", "{layer}"),
    e.g. "frames/walk_{frame}.png". Aseprite substitutes the values.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |


### `export_gif`

Export the full animation as an animated GIF (honours frame durations & tags).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `scale` | integer | no | 1 |


### `export_layer`

Export a single layer of one frame as a PNG (others excluded).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `output` | string | yes |  |
| `frame` | integer | no | 1 |
| `scale` | integer | no | 1 |


### `export_layers`

Export each layer to its own image file.

    output_pattern must contain "{layer}" (e.g. "layers/{layer}.png"); add
    "{frame}" too for animations. include_hidden also exports hidden layers.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |
| `include_hidden` | boolean | no | False |


### `export_onion_skin`

Export a frame with neighbouring frames ghosted behind it (onion skin).

    Args:
        frame: The in-focus frame (drawn fully opaque), 1-based.
        previous, next: How many earlier/later frames to ghost.
        ghost_opacity: Max opacity (0-255) of the nearest ghost; further frames fade.
        scale: Integer upscaling factor for the output PNG.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |
| `output` | string | yes |  |
| `previous` | integer | no | 2 |
| `next` | integer | no | 0 |
| `ghost_opacity` | integer | no | 80 |
| `scale` | integer | no | 4 |


### `export_png`

Export one frame as a flattened PNG.

    Args:
        output: Destination .png path.
        frame: Frame to export, 1-based (default 1).
        scale: Integer upscaling factor (default 1).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `frame` | integer | no | 1 |
| `scale` | integer | no | 1 |


### `export_spritesheet`

Export frames into a single sprite-sheet image.

    Args:
        output: Destination sheet image (.png).
        sheet_type: one of horizontal, vertical, rows, columns, packed.
        scale: Integer upscaling factor.
        data_output: Optional .json path to also write frame/tag/slice metadata
            (JSON-array format) describing each frame's rectangle in the sheet.
        padding: Pixels of padding around/between frames.
        layer: Only include this layer.
        ignore_layer: Exclude this layer (e.g. a "reference" layer).
        split_layers: Lay out each layer as separate cels in the sheet.
        split_tags: Treat each tag as a separate set in the sheet.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `sheet_type` | string | no | packed |
| `scale` | integer | no | 1 |
| `data_output` | string | null | no | None |
| `padding` | integer | no | 0 |
| `layer` | string | null | no | None |
| `ignore_layer` | string | null | no | None |
| `split_layers` | boolean | no | False |
| `split_tags` | boolean | no | False |


### `export_tag_gif`

Export only the frames of a named animation tag as an animated GIF.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `tag` | string | yes |  |
| `output` | string | yes |  |
| `scale` | integer | no | 1 |


### `export_tags`

Export each animation tag's frames to their own files.

    output_pattern must contain "{tag}" (and usually "{frame}"),
    e.g. "anim/{tag}_{frame}.png".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |


### `import_image`

Create an editable .aseprite sprite from a flat image (.png/.bmp/.jpg/...).

    Args:
        input_image: Source raster image.
        output: Destination .aseprite path.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `input_image` | string | yes |  |
| `output` | string | yes |  |


## Reference / rotoscope

### `add_reference_layer`

Add a dimmed, locked layer holding a reference image to trace over.

    Args:
        image_file: The reference image/sprite.
        layer_name: Name for the new layer (default "reference").
        opacity: Layer opacity (0-255); dim it so your art stands out.
        scale_to_fit: Resize the reference to the canvas size (smooth).
        x, y: Placement when not scaling to fit.

    Exclude this layer from exports with ignore_layer="<layer_name>".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `image_file` | string | yes |  |
| `layer_name` | string | no | reference |
| `opacity` | integer | no | 128 |
| `scale_to_fit` | boolean | no | False |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `frame` | integer | no | 1 |


### `import_reference_sequence`

Import a sequence of images as per-frame references for rotoscoping.

    Each image is placed on its own frame in a single dimmed, locked layer
    (frames are created as needed). Draw your animation on a layer above, then
    exclude this layer at export with ignore_layer="<layer_name>".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `images` | array<string> | yes |  |
| `layer_name` | string | no | rotoscope |
| `opacity` | integer | no | 128 |
| `scale_to_fit` | boolean | no | False |
| `start_frame` | integer | no | 1 |


## GUI companion mode

### `gui_available`

Check whether the Aseprite GUI can be launched (executable resolvable).

_No parameters._


### `open_in_editor`

Open a sprite in the Aseprite GUI window (non-blocking) for live viewing.

    The window stays open and runs independently of this server. Keep editing the
    file with the other tools — Aseprite detects the on-disk change and prompts to
    reload (or reloads automatically, depending on your Aseprite preferences), so
    you can watch edits land without re-opening.

    Returns the launched process id. To stop watching, just close the Aseprite
    window yourself.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |

