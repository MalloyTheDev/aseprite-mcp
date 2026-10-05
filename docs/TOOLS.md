# Aseprite MCP Tool Reference

Auto-generated from the live tool registry by `scripts/gen_tool_docs.py`. **161 tools.**

Colours accept `#RRGGBB`, `#RRGGBBAA`, `r,g,b`, `r,g,b,a`, `index:N`, or a name (black, white, red, green, blue, yellow, cyan, magenta, transparent, …). Frames are 1-based; palette indices are 0-based. Relative paths resolve inside the workspace.

## Contents

- [Sprite lifecycle](#sprite-lifecycle) (10)
- [Inspection & preview](#inspection--preview) (6)
- [Layers](#layers) (8)
- [Frames (animation)](#frames-animation) (7)
- [Animation (motion, timing, checks)](#animation-motion-timing-checks) (5)
- [Animation tags](#animation-tags) (3)
- [Cels](#cels) (10)
- [Drawing](#drawing) (11)
- [Brushes & symmetry](#brushes--symmetry) (4)
- [Shading & light](#shading--light) (10)
- [Selections](#selections) (6)
- [Effects & colour adjustments](#effects--colour-adjustments) (13)
- [Text](#text) (1)
- [Tilemaps](#tilemaps) (8)
- [Image stamping](#image-stamping) (2)
- [Palette](#palette) (15)
- [Slices](#slices) (4)
- [Transforms](#transforms) (2)
- [Export & import](#export--import) (11)
- [Engine export presets](#engine-export-presets) (2)
- [Minecraft resource packs](#minecraft-resource-packs) (4)
- [Reference / rotoscope](#reference--rotoscope) (2)
- [Workflows (high-level scaffolding)](#workflows-high-level-scaffolding) (9)
- [Asset spec (declarative build)](#asset-spec-declarative-build) (4)
- [Batch operations](#batch-operations) (1)
- [GUI companion mode](#gui-companion-mode) (2)
- [Health & self-test](#health--self-test) (1)

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
    width, height: Canvas size in pixels. Each axis is capped at 16384px
        and the total area at 16,777,216 pixels (e.g. 4096x4096).
    color_mode: "rgb" (default), "indexed", or "gray".
    background: Optional fill colour for the first layer (e.g. "#1d2b53").
        Omit for a transparent canvas.
    overwrite: Replace `filename` if it already exists (default False = no-clobber).

An **indexed** sprite is created with a usable 33-colour palette: a transparent
entry at index 0 (the index that means "no pixel here"), then the 32 colours
Aseprite ships as its default. Aseprite's own new indexed sprite has 256 entries of
identical black instead, which made every colour equidistant from every entry, so
every draw resolved to index 0 and was invisible while reporting success. A
`background` colour that the default palette does not contain is appended to it, so
the background is the exact colour asked for rather than the nearest one available.
Replace the whole palette with `set_palette` when you have one in mind.

Returns the new sprite's structured info.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `color_mode` | string | no | rgb |
| `background` | string | no | _none_ |
| `overwrite` | boolean | no | False |


### `crop_sprite`

Crop the canvas to the rectangle (x, y, width, height).

The resulting canvas is subject to the same dimension/area caps as `create_sprite`
(a "crop" to a larger rectangle grows the canvas).

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
"top_left" (default) or "center". The new canvas is subject to the same
dimension/area caps as `create_sprite`.

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

overwrite: Replace `new_filename` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `new_filename` | string | yes |  |
| `flatten` | boolean | no | False |
| `overwrite` | boolean | no | False |


### `scale_sprite`

Scale the whole sprite (artwork included).

Provide either `factor` (e.g. 2.0 to double) OR explicit `width`/`height`.
method: "nearest" (crisp pixels, default) or "bilinear" (smooth).

The scaled canvas is subject to the same dimension/area caps as `create_sprite`.
With `factor` the result depends on the sprite's current size, so that check runs
inside Aseprite and reports the size it would have produced.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `factor` | number | no | _none_ |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `method` | string | no | nearest |


### `set_color_mode`

Convert a sprite between colour modes ("rgb", "indexed", "gray").

Converting **to indexed** builds the palette from the sprite's own colours first,
which is what the editor does and what makes the art survive. Mapping art against
whatever palette the sprite happened to carry is how this tool used to empty a
sprite: a saved RGB sprite carries a single transparent entry, so every pixel
resolved to it and the whole image became transparent while the call reported ok.

Args:
    color_mode: "rgb", "indexed", or "gray".
    dithering: "none" (default), "ordered", or "old". How a colour between two
        palette entries is resolved. Indexed conversions only.
    palette_source: "from_art" (default) quantizes the sprite's colours into a new
        palette and maps onto that, so flat colours convert exactly. "keep" maps
        against the palette the sprite already has, for when you loaded or built one
        deliberately; snapping the art to that palette is the point, so expect
        colours to shift, and expect two art colours to merge where the palette has
        only one entry near them. Indexed conversions only; the other modes have no
        palette to choose.

**Refuses** a conversion to indexed that would make drawn pixels disappear, naming
how many, and leaves the file untouched when it does. Losing colour accuracy is what
indexed mode is for and is allowed; losing pixels is not recoverable and is the one
thing a mode change must never do quietly. `set_palette` or `add_palette_color` fix a
palette that has nothing to draw with.

That check counts every pixel of every frame, twice. Past `MAX_VERIFY_PIXELS` the
conversion still runs and reports `verified: false` with the reason, rather than
being refused: a capability that declines to work on a large sheet because the check
is unaffordable is worse than one that works and says what it did not check.
`diff_sprites` against a copy taken beforehand answers the same question by hand.

Returns the sprite's structured info, plus `drawn_pixels` and `verified` (whether
that count was actually compared across the conversion) and the `palette_source`
used, for indexed targets.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color_mode` | string | yes |  |
| `dithering` | string | no | none |
| `palette_source` | string | no | from_art |


### `trim_sprite`

Auto-crop the canvas to the bounding box of all non-transparent content
(across every frame).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


## Inspection & preview

### `assess_sprite`

Measure the drawing itself and say what is worth fixing.

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

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | no | 1 |
| `layer` | string | no | _none_ |
| `ramp` | array<string> | no | _none_ |
| `check_tiling` | boolean | no | False |
| `standing` | boolean | no | False |
| `check_cvd` | boolean | no | False |


### `diff_sprites`

Compare two frames pixel for pixel and say what changed.

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

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | no | 1 |
| `layer` | string | no | _none_ |
| `other` | string | no | _none_ |
| `other_frame` | integer | no | 1 |
| `other_layer` | string | no | _none_ |
| `expect` | string | no | _none_ |


### `get_pixels`

Read the pixel colours of a region.

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

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `frame` | integer | no | 1 |
| `layer` | string | no | _none_ |
| `format` | string | no | rows |


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
| `group` | string | no | _none_ |
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

Refuses rather than doing nothing when there is nothing to merge into. Aseprite's
`MergeDownLayer` is a no-op in five cases, and it raises in none of them, so this used
to report a result indistinguishable from a merge that happened. Measured, naming the
layer stack before and after:

    bottom layer of the sprite        ['only']                   -> ['only']
    lowest layer inside a group       ['Layer 1', 'grp/a', 'b']  -> unchanged
    the layer below is a group        ['Layer 1', 'grp', 'a']    -> unchanged
    the layer named is a group        ['Layer 1', 'grp/a']       -> unchanged
    the layer below is a tilemap      ['Layer 1', 'tiles', 'px'] -> unchanged

All five returned sprite info describing the stack they had failed to change, which is
the same shape a successful merge returns. Only the ordinary case worked, so an agent
flattening a stack by merging downward in a loop was told the loop had finished when it
had stopped.

Returns `merged_into`, the name of the layer the artwork went into, so the result says
what happened rather than only what the sprite now looks like.

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
| `opacity` | integer | no | _none_ |
| `blend_mode` | string | no | _none_ |
| `visible` | boolean | no | _none_ |
| `editable` | boolean | no | _none_ |
| `name` | string | no | _none_ |


## Frames (animation)

### `add_frame`

Add a frame: appended when it is empty, inserted when it copies another.

Args:
    duration_ms: Frame duration in milliseconds (default 100).
    copy_from: If given (1-based), duplicate the content of that frame; otherwise the
        new frame is empty and goes at the end. Must name an existing frame: an
        out-of-range number is rejected, not clamped. **A copy is inserted, not
        appended**, so every frame from that point on is renumbered: on a two-frame
        sprite, `copy_from=1` gives three frames whose second is the original first.
        Pass no `copy_from` and the sprite's existing frames keep their numbers.

Returns the new frame number and updated frame count. With `copy_from`, `newFrame` is
where the copy landed, which is also the number the frames after it shifted from.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `duration_ms` | integer | no | 100 |
| `copy_from` | integer | no | _none_ |


### `duplicate_frame`

Duplicate an existing frame (1-based); the copy is inserted after it.

`frame` must already exist: an out-of-range number is rejected with the sprite's
valid range rather than clamped to it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |


### `move_frame`

Move one frame to another position, taking its cels and its duration with it.

Fixing an ordering mistake otherwise means deleting and redrawing. Nothing is copied:
the frame keeps its identity, so linked cels stay linked.

Args:
    frame: The frame to move, 1-based.
    to: Where it should end up, 1-based, in the numbering *after* the move. Moving
        frame 2 to 5 on a six-frame sprite gives 1, 3, 4, 5, 2, 6.

**Tags mark positions, not pictures.** A tag between the two positions keeps its own
range and now covers a different set of drawings. The result names every tag that
overlapped the frames in between, because that is the part worth checking and it is
invisible in the frame count.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |
| `to` | integer | yes |  |


### `remove_frame`

Delete a frame (1-based). The sprite must have more than one frame.

`frame` must already exist: an out-of-range number is rejected with the sprite's
valid range rather than clamped to it (which used to delete a different frame).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |


### `reverse_frames`

Reverse the order of a run of frames, keeping their timing with them.

Reversing a walk to get its mirror, or a grow to get a shrink, is a normal move and
otherwise means re-authoring the whole thing. Whole frames move: every layer's cel
travels together, and each frame keeps its own duration.

Args:
    tag: Reverse one tag's frames.
    frames: Reverse these frames instead. They must be one unbroken run, because
        Aseprite reverses everything between the first and the last: a gapped list
        would silently take in the frames in between.

Defaults to the whole sprite when neither is given.

**Tags mark positions, not pictures.** A tag over the reversed frames keeps its own
range and now covers them in their new order, which is usually what was wanted for a
tag that spans the whole run and rarely what was wanted for one that spans part of
it. The result lists every tag that overlapped, so the ones worth revisiting are
named rather than left to be discovered later.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `tag` | string | no | _none_ |
| `frames` | array<integer> | no | _none_ |


### `set_all_frame_durations`

Set every frame's duration in milliseconds (uniform animation speed).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `duration_ms` | integer | yes |  |


### `set_frame_duration`

Set a single frame's duration in milliseconds (1-based frame).

`frame` must already exist: an out-of-range number is rejected with the sprite's
valid range rather than clamped to it (which used to report the requested number
while changing frame 1).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |
| `duration_ms` | integer | yes |  |


## Animation (motion, timing, checks)

### `apply_timing_curve`

Give an animation a shape in time, by setting durations and never duplicating frames.

Uniform timing is the placeholder every animation starts with and almost none should
keep. A cycle holds its extremes two to four times as long as the poses it passes
through; an attack holds the anticipation, snaps through the strike in 20 to 40ms, and
holds the impact.

Args:
    curve: `hold_extremes` (the ends of a cycle are held, the passing frames are not),
        `attack` (anticipation, snap, impact, recovery), `ease_in` (starts slow),
        `ease_out` (ends slow), or `flat` (every frame the same, to start over).
    frames: The frames to time, in order. Defaults to a tag's frames, or all of them.
    tag: Time one tag's frames instead of naming them.
    base_ms: The duration of a passing frame. Everything else is a multiple of it.
    hold_frames: Frames to hold whatever the curve says, at three times `base_ms`.
    snap_frames: Frames to snap through, at the shortest duration that still registers.

A hold is a longer duration on one frame, never a repeated frame: duplicating costs a
frame, shifts every tag index, and hides the repeat from `validate_loop`. The returned
`frames_added` is always 0, and it is returned so that claim can be checked.

Easing here and easing the spacing elsewhere are the same curve applied twice, which
reads as slow motion rather than as weight. The cels are measured on the way through,
so asking for an eased curve over spacing that is already eased comes back with a
warning rather than quietly doing it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `curve` | string | no | hold_extremes |
| `frames` | array<integer> | no | _none_ |
| `tag` | string | no | _none_ |
| `base_ms` | integer | no | 100 |
| `hold_frames` | array<integer> | no | _none_ |
| `snap_frames` | array<integer> | no | _none_ |


### `offset_cels`

Move one layer's drawn cel along a path across frames, in one Aseprite launch.

The cel on the first listed frame stays where it is; every later frame is placed
along the way to `(dx, dy)` from it, and the last frame lands exactly there. This is
the same work as one `set_cel_position` per frame, minus the launches and minus
computing the intermediate positions by hand.

Args:
    frames: The frames to place, in the order the movement passes through them.
    dx, dy: The whole movement, in pixels, from the first frame to the last.
    ease: How the movement is *spaced*: `linear`, `ease_in` (starts slow),
        `ease_out` (arrives slow), `ease_in_out`, or `gravity` (horizontal speed
        stays even while the vertical accelerates, as a thrown object does).
    arc_height: Bend the path into an arc this many pixels high at its midpoint,
        perpendicular to the straight line between the ends. A jump or a thrown
        object needs this; a slide does not.

Easing belongs here, in the spacing, and not in the frame durations. Applying a curve
to both applies it twice, and the result reads as slow motion rather than as weight.

Positions are whole pixels, so it is the running position that gets rounded and not
each step: the leftover fraction carries forward instead of being reintroduced every
frame, which is the difference between spacing that reads as speed and spacing that
reads as a limp. The returned `deltas` are the spacing a viewer actually sees, and
`max_error_px` is how far the furthest frame sits from the ideal curve, which stays
below one pixel.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frames` | array<integer> | yes |  |
| `dx` | integer | no | 0 |
| `dy` | integer | no | 0 |
| `ease` | string | no | linear |
| `arc_height` | number | no | 0.0 |


### `smear_frame`

Draw one frame's subject along its own path, so fast movement reads as speed.

Between two frames of a fast movement the eye expects a **smear**: one frame where the
subject is stretched along where it came from, or drawn several times faintly, so the
movement reads as speed rather than as teleportation. `offset_cels` produces the
movement; this describes one frame of it.

The movement vector is taken from the sprite rather than restated by the caller: it is
the shift between the centre of the drawn content on `from_frame` and on `frame`. The
*content* box, not `cel.position`, because any tool here that writes a whole canvas
back leaves the position at (0, 0) on every frame, and a position diff would then read
zero while the drawing plainly moved.

Args:
    frame: The frame to smear. Its own cel is the subject and stays on top, unchanged;
        the trail is drawn behind it. Only this frame is written.
    from_frame: The frame the movement came from. Defaults to the one before `frame`.
    mode: `stretch` draws the subject once, elongated back along the vector and
        thinning to a single pixel at the tip, which is the classic one-frame smear.
        `echo` draws it `steps` times along the vector, each copy a step further down
        the ramp, which is the multiple-exposure smear.
    strength: How far back the smear reaches, as a fraction of the movement. 0.6 is a
        trail that clearly trails; 1.0 reaches all the way to the previous position;
        above 1 it overshoots, which is a real choice an animator makes.
    steps: How many copies `echo` draws. Defaults to 3, and is refused with
        `mode="stretch"` rather than silently ignored.
    ramp: The colours, darkest first, the trail is allowed to use, as `generate_ramp`
        returns them. **Pass this.** Each pixel of the trail is the nearest ramp entry
        to the subject's own colour there, stepped toward the dark end and clamped
        (never wrapped), so `palette_conformance` stays at 1.0, which is the property
        every shading tool here holds to and what a pixel artist actually draws.
        Without it the fallback is opacity, and the fallback **leaves the palette**:
        the trail is then made of colours that are not in the sprite, which is motion
        blur rather than a smear. On an *indexed* sprite the ramp is required rather
        than preferred, and the call is refused without one: an indexed pixel is an
        offset into a palette and carries no alpha, so the fallback would snap every
        copy back to the subject's own colour and draw a solid blob.

Refuses rather than producing a blur of nothing: a frame with no movement to smear
(the two content boxes sit at the same place, and the message says where they are), a
movement too short to smear at this strength (it names the pixels and the length that
would result), `frame` 1 with no earlier frame, `from_frame` equal to `frame`, either
frame undrawn, a group or tilemap layer, a ramp of fewer than two colours or one given
as palette indices, `steps` with `stretch`, and a frame that shares its image with
another frame, since a linked cel would put the smear on every frame in the group and
the whole point is that the unsmeared frames are untouched.

Returns the vector it measured and where it came from, the plots it drew, and the
cel's bounds before and after, so the claim that the smear lies along the movement can
be checked. On an indexed sprite it also returns `trail_on_palette`: what the trail's
own target colours resolve to on this palette, and a warning naming the copies that
will come out the same colour because two of those targets landed on one entry. That
is a different finding from the ramp headroom one above it, which measures the art.
`validate_loop` will now report this frame as breaking the spacing series, which is
correct: a smear frame is one that legitimately does.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | yes |  |
| `from_frame` | integer | no | _none_ |
| `mode` | string | no | stretch |
| `strength` | number | no | 0.6 |
| `steps` | integer | no | _none_ |
| `ramp` | array<string> | no | _none_ |


### `tween_cels`

Scale, turn and fade one drawn cel across frames, in one Aseprite launch.

`offset_cels` moves a cel along a path, which is one of the four things an inbetween
does. This is the other three. The cel on the **first listed frame is the source**,
and every listed frame becomes that one drawing resampled by its share of the change:
frame nine is sampled from the original and not from frame eight, so the rounding
never compounds.

**It interpolates a transform, not pixels.** Blending two different drawings gives a
double exposure, two silhouettes at half strength, which reads as a mistake rather
than as motion. So this takes one drawing, and when two cels genuinely differ in shape
there is no honest automatic inbetween: draw the second pose and tween each one out
from its own extreme, or express the difference as a scale and a turn, which most of
them are.

Args:
    frames: The frames to write, in the order the change passes through them. The
        first is the source, and it is rewritten too when `scale_from`, `rotate_from`
        or `opacity_from` is not the identity.
    scale_from, scale_to: The scale at the first and last frame, on both axes.
    scale_y_from, scale_y_to: Override the vertical scale, for squash and stretch,
        where the two axes go opposite ways (0.7 tall against 1.25 wide is a squash
        that keeps its volume). Unset means the same as the horizontal, which is a
        zoom and not a squash.
    rotate_from, rotate_to: Clockwise degrees at the first and last frame, snapped to
        whole degrees. Quarter turns are exact and lose nothing; sampling within about
        15 degrees of one shuffles the edge pixels rather than turning the shape, and
        the result says so in `warnings` instead of pretending otherwise.
    opacity_from, opacity_to: Cel opacity, 0 to 255. This sets the cel's own opacity
        and never bakes alpha into the pixels: a baked fade invents colours that are
        not on the palette. It is the per-frame `set_cel_opacity` done in one call.
    ease: How the change is *spaced*: `linear`, `ease_in` (starts slow), `ease_out`
        (arrives slow), `ease_in_out`, or `gravity` (accelerating, as a falling object
        does). Easing belongs in one place at a time, and `apply_timing_curve` carries
        the durations.
    anchor: The point the transform holds still, taken from the cel's own drawn
        bounds: `center`, `top`, `bottom`, `left` or `right`. This matters more than it
        looks. A scale about the centre makes a ball grow in every direction; a scale
        about `bottom` makes it squash *onto the ground*, which is the one that reads
        as weight, and `validate_loop`'s contact-edge check then confirms that the
        contact row did not move.

Refuses rather than doing something approximate: fewer than two frames, a frame listed
twice, a from and to that are identical on every channel (each frame would be
rewritten with the drawing the source already holds), a scale of zero or below, a
group or tilemap layer, a source frame with no cel or nothing drawn on it, a frame
whose transform lands entirely off the canvas, and any frame that shares its image
with another frame. That last one is the sharp edge: linked cels share one image, one
position and one opacity, so a tween written into a link group would change every
frame in it. The refusal names the frames and points at `unlink_cels`.

Every listed frame after the first is **overwritten** with the transformed source
rather than blended with what was there. `steps[].bounds` is the written cel's own
content box, so a scale series can be checked instead of trusted: `rendered_monotone`
is that check, and it is omitted while the cel is also rotating, because a turning
shape's bounding box oscillates by design. `steps[].drawn_pixels` is how many opaque
samples that frame took; `pixels_written` is what landed, and the two differ only when
an active selection masked part of it, which `pixels_outside_selection` then reports.

Sampling is nearest-neighbour and copies the source pixel whole, so no colour appears
that the drawing did not already contain and `palette_conformance` is unchanged.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frames` | array<integer> | yes |  |
| `scale_from` | number | no | 1.0 |
| `scale_to` | number | no | 1.0 |
| `scale_y_from` | number | no | _none_ |
| `scale_y_to` | number | no | _none_ |
| `rotate_from` | number | no | 0.0 |
| `rotate_to` | number | no | 0.0 |
| `opacity_from` | integer | no | 255 |
| `opacity_to` | integer | no | 255 |
| `ease` | string | no | linear |
| `anchor` | string | no | center |


### `validate_loop`

Measure an animation and report what is wrong with it, without playing it.

Renders each frame once (one Aseprite launch), then reports per-frame hashes, content
bounding boxes, centroids, the bottom row of the drawn content, the spacing series
between frames, and the durations. On top of the numbers it checks for: a last frame
identical to the first (a loop's wrap showing one image twice), identical adjacent
frames (a pose held by repeating a frame instead of lengthening one), uniform frame
durations, a spacing series that wobbles rather than eases, a contact edge that moves,
and frames with nothing drawn on them.

Args:
    tag: Limit the check to one animation tag's frames. Its repeat setting also
        decides whether the seam is treated as a loop's wrap.
    layer: Measure one layer's cels instead of the flattened frame, so a moving
        character can be measured without the background it sits on.
    loops: Override whether these frames are a cycle. One-shots (attack, hurt, death)
        do not wrap, so a repeated last frame is only a warning for them.
    jitter_tolerance: Pixels of spacing wobble to ignore. Integer cel positions make
        1px unavoidable, so that is the default; pass 0 to see every reversal.

Returns a ``workflow_manifest.v1`` manifest (kind "validation") whose `validation`
section is `{passed, checks[], errors[], warnings[]}` and whose `animation` section
carries every measurement. `validation.passed` is the verdict and is false only for
faults that are wrong whatever the animation is doing; the rest are warnings, because
a bouncing ball is meant to leave the ground and a flicker is meant to go blank.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `tag` | string | no | _none_ |
| `layer` | string | no | _none_ |
| `loops` | boolean | no | _none_ |
| `jitter_tolerance` | number | no | 1.0 |


## Animation tags

### `add_tag`

Create an animation tag spanning frames [from_frame, to_frame] (1-based).

Both frames must already exist: an out-of-range number is rejected with the sprite's
valid range rather than clamped to it (which used to report a tag added while
creating it over a different range).

Args:
    direction: "forward" (default), "reverse", "pingpong", or "pingpong_reverse".
    color: Optional tag colour, shown in the timeline.
    repeats: How many times the tag plays. **0, the default, means forever**, which
        is how a cycle is marked in the file; 1 is a one-shot such as an attack, a
        hurt or a death. This is the sprite's own answer to whether these frames
        loop, and `validate_loop` reads it: a repeated last frame is an error for a
        cycle and only a warning for a one-shot.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `from_frame` | integer | yes |  |
| `to_frame` | integer | yes |  |
| `direction` | string | no | forward |
| `color` | string | no | _none_ |
| `repeats` | integer | no | 0 |


### `remove_tag`

Delete an animation tag by name.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |


### `set_tag`

Update an existing tag. Only the arguments you pass are changed.

Note: changing from_frame/to_frame recreates the tag in place to update its
range reliably across Aseprite versions. A frame that does not exist is rejected
with the sprite's valid range rather than clamped into it.

`repeats` is how many times the tag plays, with 0 meaning forever. It survives the
recreate above along with the name, direction and colour.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `from_frame` | integer | no | _none_ |
| `to_frame` | integer | no | _none_ |
| `new_name` | string | no | _none_ |
| `direction` | string | no | _none_ |
| `color` | string | no | _none_ |
| `repeats` | integer | no | _none_ |


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

Inspect a cel: whether it exists, its position, bounds, opacity, and links.

`linked_with` lists the other frames sharing this cel's image, so a held pose is
visible as what it is. An edit to any of them changes all of them.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | no | 1 |


### `get_properties`

Read the custom properties stored on one object inside the sprite.

The counterpart to `set_properties`, and the only way to read that metadata back:
neither `get_sprite_info` nor the sprite-sheet export reports custom properties.

Args:
    target, layer, frame, name, tile: Which object, exactly as `set_properties`
        takes them.
    namespace: Read a named group instead of the unnamed one. Aseprite offers no way
        to list the namespaces an object has, so a group can only be read by a caller
        who knows its name; an unknown name reads as empty rather than as an error.

Returns `properties` as an object of key to value, each value in the type it was
stored as. A value of a type JSON cannot describe (the editor can store a point or a
rectangle) is reported as text rather than dropped.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `target` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | _none_ |
| `name` | string | no | _none_ |
| `tile` | integer | no | _none_ |
| `namespace` | string | no | _none_ |


### `link_cels`

Make several frames share one image, which is how a held pose is authored.

A linked cel is one image appearing on several frames: editing any of them edits all
of them, and the file stores the image once instead of once per frame. Use it for a
pose that genuinely repeats, such as the two extremes of a cycle that return to the
same drawing.

**The first listed frame's image is the one kept.** Every other listed frame loses
whatever was drawn on it and shows the first frame's image instead, which is the point
of linking and is not undoable from here, so check with `get_cel` first if the frames
differ.

To hold a pose for longer rather than to repeat a drawing, lengthen the frame instead
(`set_frame_duration`, or `apply_timing_curve`): a duration costs nothing, while a
repeated frame shifts every tag index.

Returns the layer's link groups: the frames that now share an image, in groups.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frames` | array<integer> | yes |  |


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


### `set_cel_z_index`

Reorder one cel against the other cels in its frame, without moving any layer.

This is the fix for "the arm is in front of the body this frame and behind it the
next". The alternatives are to restructure the layer stack, which changes every other
frame too, or to duplicate the arm onto a second layer and hide one of them per
frame; a z-index is per cel, so it says exactly what it means and only where it
applies.

`z` is an offset, not a position: 0 (the default for every cel) means "wherever this
cel's layer sits in the stack", a positive number moves the cel towards the front and
a negative one towards the back. A cel draws at its layer's stack position plus `z`,
and when two cels land on the same number the one with the larger `z` draws in front.
So `z=1` on a cel one layer below another is enough to put it in front of that one.

The ordering is scoped to the layer's siblings: a layer inside a group is ordered
against that group's other layers, and the group as a whole keeps its place. Returns
`order`, the frame's competing cels back to front, which is the part a caller cannot
see for themselves.

A z-index is per cel even when the cel is linked: two frames sharing one image share
their opacity and their properties, and do not share this. Verified against the
editor, because the opposite is the reasonable guess.

`z` must be between -32768 and 32767. The editor accepts a larger number in memory
and then stores it in a 16-bit field, so saving and reopening would silently turn it
into a different one, usually of the opposite sign.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frame` | integer | yes |  |
| `z` | integer | yes |  |


### `set_properties`

Store a custom property on an object inside the sprite, in the .aseprite file.

This is where game metadata belongs: a hitbox on a slice, an anchor point on a layer,
"this frame deals damage" on a cel, a surface kind on a tile. It travels with the art
instead of living in a sidecar file that the next edit desynchronises, and the editor
shows it and keeps it.

Args:
    target: Which kind of object: "sprite", "layer", "cel", "tag", "slice" or "tile".
    key: The property name, e.g. "hitbox".
    value: What to store. Text by default, so value="7" stores the two-character
        string "7". Pass as_json=True to store a number, a boolean or a structure:
        then "7" stores the number 7, "true" stores a boolean, and
        '{"x": 8, "y": 15}' stores a table. A value that begins like a JSON object or
        array is read as JSON either way, since there is no other reading of one.
    layer: The layer's name. Needed for target "layer", "cel" and "tile".
    frame: 1-based frame number, for target "cel" (default: the first frame).
    name: The tag's or slice's name, for target "tag" and "slice".
    tile: An index into the layer's tileset, for target "tile". 0 is the empty tile.
    namespace: Keep the property in a named group rather than in the unnamed one the
        editor's own property panel uses. Two tools can then both use the key
        "anchor" without colliding. Namespaces cannot be listed back, so a caller has
        to know the name to read one again.
    as_json: Parse `value` as JSON before storing it (see `value`).
    delete: Remove the property instead of setting it. `value` is then ignored, and
        removing a key that was not there is not an error.

A selector the target does not use is refused rather than ignored, because the
property would otherwise land on a different object than the one that was named.

Properties live on the record that linked cels share, so setting one on a held pose
sets it on every frame of the hold. The result says which frames those were.

Returns the whole property group after the write, so the stored value is visible as
the type it was stored as.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `target` | string | yes |  |
| `key` | string | yes |  |
| `value` | string | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | _none_ |
| `name` | string | no | _none_ |
| `tile` | integer | no | _none_ |
| `namespace` | string | no | _none_ |
| `as_json` | boolean | no | False |
| `delete` | boolean | no | False |


### `unlink_cels`

Give frames their own copy of a shared image again, so they can differ again.

The reverse of `link_cels`: each listed frame keeps what it currently shows and stops
following the others. Nothing is lost; the image is copied rather than moved.

Returns the layer's link groups afterwards.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `frames` | array<integer> | yes |  |


## Drawing

### `clear_layer`

Erase the target layer/frame cel to full transparency.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_curve`

Draw a quadratic Bézier curve from (x0,y0) to (x1,y1) bending toward the
control point (control_x, control_y). `steps` controls smoothness.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

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
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_ellipse`

Draw an ellipse centred at (center_x, center_y) with the given radii.

For a circle, use the same value for radius_x and radius_y. filled=False draws a 1px
outline, and a filled ellipse is exactly that outline with its interior: the two are
one shape rendered two ways, so a fill and an outline of the same call line up.
antialias smooths a *filled* ellipse with sub-pixel coverage (RGB sprites only;
ignored otherwise).

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

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
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_ellipse_in_box`

Draw an ellipse that fills the given bounding box exactly.

Takes the same box as draw_rectangle, so the two share a centre and an extent: this is
how to draw a disc centred on an even canvas, or a circle that lines up with a
rectangle. draw_ellipse takes a centre and radii instead, which can only ever be an odd
2*radius+1 across.

An even side is drawn the way it is drawn by hand: the odd ellipse one pixel smaller,
with its middle row or column repeated. Give an odd width and height and the result is
pixel for pixel what draw_ellipse produces for the same shape, because both use the
same geometry.

filled=False draws a 1px outline. antialias smooths a *filled* ellipse with sub-pixel
coverage (RGB sprites only; ignored otherwise).

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `color` | string | yes |  |
| `filled` | boolean | no | False |
| `antialias` | boolean | no | False |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_line`

Draw a straight line from (x1,y1) to (x2,y2).

Args:
    pixel_perfect: Remove L-shaped corner pixels for a clean 1px pixel-art line.
    antialias: Smooth (Xiaolin Wu) line with alpha blending, RGB sprites only;
        ignored on indexed/gray. Takes precedence over pixel_perfect.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

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
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_pixel_map`

Draw from a character grid, one character per pixel: the way pixel art is authored.

This is the write side of `get_pixels(format="map")` and takes exactly the shape that
returns, a `legend` plus one string per row, so a read, an edit and a write
round-trip. Until this existed the server could *show* a caller per-pixel intent and
could not receive it: the only way to author a figure was a list of
`{"x", "y", "color"}` dictionaries, one per pixel.

That asymmetry shaped the art it produced, which is the real reason this is here. A
caller reaching for a thousand-entry dictionary list does not write a thousand
considered pixels, it writes a formula that emits them, and a formula produces smooth
monotone surfaces. Hand-placed pixel art is the opposite of that: a highlight nudged
two pixels off the geometric centre, an outline that thickens on the shadow side,
three pixels clustered to imply a chip in the stone. A grid is the notation those
decisions can be written in, and it is about a tenth the size: a 16x16 of three
colours is roughly 3,400 characters as dictionaries and 350 as a map.

Args:
    rows: One string per row, one character per pixel, **every row the same length**.
        A ragged map is refused rather than padded, because padding would shift every
        pixel after the short row.
    legend: Symbol to colour, as `{"a": "#1b2b4a", "b": "red"}`. `"."` means leave
        that pixel alone and needs no entry; any other character can say the same
        with the value `"transparent"`, which is what the read side emits. A
        character the legend does not define is **refused**, not skipped: a typo in a
        grid would otherwise paint nothing and report success.
    x, y: Where the map's top-left corner lands on the canvas. Defaults to the
        canvas origin.
    layer: Target layer name or 1-based index (default: top layer).
    frame: Target frame, 1-based (default 1).

Transparent cells are left untouched rather than erased, so a map can be stamped over
existing art; clear the layer first if you want the map to be the whole of it.

Returns the usual write counters plus `map_width`, `map_height`,
`pixels_transparent` (cells deliberately left alone) and `colors_used`.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `rows` | array<string> | yes |  |
| `legend` | object | yes |  |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_pixels`

Plot individual pixels.

Args:
    pixels: List of {"x": int, "y": int, "color": "#hex"?}. If a pixel omits
        "color", the shared `color` argument is used.
    color: Default colour for pixels that don't specify their own.
    layer: Target layer name or 1-based index (default: top layer).
    frame: Target frame, 1-based (default 1).

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `pixels` | array<object> | yes |  |
| `color` | string | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_polyline`

Draw connected line segments through a list of points.

points: list of {"x": int, "y": int}. Set closed=True to connect the last
point back to the first (outline a polygon). pixel_perfect removes L-corner
pixels across the whole path for a clean pixel-art outline.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `points` | array<object> | yes |  |
| `color` | string | yes |  |
| `closed` | boolean | no | False |
| `pixel_perfect` | boolean | no | False |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `draw_rectangle`

Draw a rectangle. filled=False draws a 1px outline, True fills it.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `color` | string | yes |  |
| `filled` | boolean | no | False |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `fill_area`

Flood fill (paint bucket): replace the contiguous region of matching
colour starting at (x,y) on the target layer with `color`.

Coordinates: (0, 0) is the top-left pixel. x grows right, y grows DOWN. A span given as
position plus size covers x .. x + width - 1, so width is a count of pixels, not an
offset to the far edge.

Centring differs between primitives, so check this when aligning two shapes:
  * draw_rectangle(x, width) spans x .. x+width-1, centred on x + (width-1)/2. An even
    width therefore centres on a half pixel.
  * draw_ellipse(center, radius) spans center-radius .. center+radius, which is always
    an ODD 2*radius+1 pixels wide and always centred on a whole pixel.
  * draw_ellipse_in_box(x, y, width, height) takes the same bounding box as
    draw_rectangle and fills it exactly, so it is the one to use for an even diameter, a
    disc centred on an even canvas, or a circle that has to line up with a rectangle.
  * draw_symmetric_pixels mirrors about the canvas, not about either of the above.

Writes falling outside the canvas are dropped rather than raising. Every drawing tool
reports pixels_written, and pixels_clipped when anything was dropped, so compare those
against what you asked for rather than trusting ok.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `color` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `fill_layer`

Fill the entire target layer/frame cel with a solid colour.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


## Brushes & symmetry

### `draw_brush`

Stamp a custom brush shape at a list of points.

Args:
    brush: The brush as rows of characters. Any character other than space,
        '.', or '0' is a filled cell. e.g. a plus brush: ["010", "111", "010"].
    points: Positions to stamp at, list of {"x": int, "y": int}.
    color: Colour to stamp the brush in.
    anchor: "center" (default) or "topleft", where each point sits in the brush.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `brush` | array<string> | yes |  |
| `points` | array<object> | yes |  |
| `color` | string | yes |  |
| `anchor` | string | no | center |
| `layer` | string | no | _none_ |
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
| `axis_x` | integer | no | _none_ |
| `axis_y` | integer | no | _none_ |
| `layer` | string | no | _none_ |
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
| `axis` | integer | no | _none_ |
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
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `spacing_x` | integer | no | 0 |
| `spacing_y` | integer | no | 0 |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


## Shading & light

### `contact_shadow`

Darken the pixels where one form meets another, along its ramp.

Ambient occlusion as pixel artists actually draw it: a line one or two steps darker
where two shapes touch. It is what stops a shaded object looking like it is floating
in front of the thing it is standing on.

Args:
    ramp: Colours darkest first. Darkened pixels stay on this ramp.
    occluder_color: The colour of the form casting the occlusion, for example the
        ground a character stands on, or the blade a crossguard meets.
    radius: How far the darkening reaches from the occluder, in pixels. 1 or 2 is
        usually right; beyond that it reads as a drop shadow rather than contact.
    depth: How many ramp steps darker, at the contact line. 1 is the common choice.
    direction: Degrees, restricting occlusion to one side. Omit for all directions,
        which is what you want for a contact line; set it when only one side of the
        form is actually touching something.
    tolerance: How close a pixel must be to a ramp entry to be darkened. Pixels
        further away are left alone, so this does not spill onto other materials.
    occluder_tolerance: How close a pixel must be to `occluder_color` to count as the
        occluder, as a weighted RGB distance. Defaults to `tolerance`, which is what
        this did before it was a separate argument. It wants to be **tight**: the
        occluder is a flat fill you named, while `tolerance` has to stay loose enough
        for shaded art that varies, and one number cannot be both. At the shared
        default of 24 a ground colour within 24 of the subject's own ramp makes the
        subject its own occluder: measured on a 24x24 sprite with a subject painted
        `#5a5a7a` and ground `#60607e`, `occluder_pixels` came back as 312 (the 144
        ground pixels plus all 168 of the subject) and nothing was darkened at all.
        The result carries a warning naming any ramp entry this cannot be told apart
        from, because that overlap is invisible otherwise.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

Refuses a pass that darkened nothing rather than reporting `darkened_pixels: 0` as a
success, and the refusal carries the three counts that say which of the possible
causes it was. A contact shadow that changed no pixel is not a contact shadow.

Run this **before** the passes that repaint the occluder, not after. The occluder is
found by colour, so a `shade_region_by_light` or `shift_along_ramp` that has already
moved the ground off `occluder_color` leaves this matching a handful of pixels and
reporting the handful as a success.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `occluder_color` | string | yes |  |
| `radius` | integer | no | 1 |
| `depth` | integer | no | 1 |
| `direction` | number | no | _none_ |
| `tolerance` | number | no | 24.0 |
| `occluder_tolerance` | number | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `dither_band`

Dither the boundary between two adjacent ramp steps, widening the transition.

Dithering in pixel art is a limited-palette necessity rather than a style: it buys
an apparent extra shade between two you already have. It reads as dated when applied
globally, which is why this is scoped to one boundary rather than offered as a
filter over the whole sprite.

Args:
    ramp: Colours darkest first.
    from_step, to_step: 1-based indices into `ramp`, and they must be adjacent.
        Dithering between distant steps produces visible noise, not a gradient.
        **1-based, while `ramp` is a list the caller indexes from 0**, so the pair
        that dithers `ramp[3]` against `ramp[4]` is `from_step=4, to_step=5`. The two
        conventions usually sit a line apart:

            shade_region_by_light(f, GOLD, base_color=GOLD[4], ...)
            dither_band(f, GOLD, from_step=5, to_step=6, ...)   # GOLD[4], GOLD[5]

        Off by one still names an adjacent pair, so the call succeeds and dithers the
        wrong boundary. The result reports `from_color` and `to_color` for that
        reason: it is the only way to check the intent from the output.
    pattern: "bayer4" (finest, the usual choice), "bayer2" (chunkier) or "checker"
        (a hard 50/50 that suits a sharp material change).
    width: How far the dithered zone reaches into each band, in pixels. This is what
        widens the transition, which is the point of dithering: at width=1 only the
        seam itself alternates, and every pattern collapses to the same result
        because a one-pixel-deep band can only alternate.
    tolerance: How close a pixel must be to one of the two colours to take part.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

Only pixels of the two named colours that border each other are touched, so the
rest of the sprite is untouched even where it uses the same ramp.

Returns `dithered_pixels`, and `from_color`/`to_color`, the two colours the steps
actually resolved to.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `from_step` | integer | yes |  |
| `to_step` | integer | yes |  |
| `pattern` | string | no | bayer4 |
| `width` | integer | no | 2 |
| `tolerance` | number | no | 24.0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `gradient_map`

Put every pixel on a ramp by its brightness, whatever it started as.

The other shading tools all begin with art that is *already* on a ramp:
`shift_along_ramp` moves pixels between steps they already belong to, and
`shade_region_by_light` shades a flat region painted in one of the ramp's colours.
This is the one that brings art onto a ramp in the first place, which is what an
imported image, a photo traced over, or a gradient fill actually needs.

Each pixel's luminance decides its step: darkest to `ramp[0]`, lightest to the last
entry, the rest in between. Afterwards the art uses the ramp's colours and nothing
else, so `assess_sprite(..., ramp=...)` reports a palette conformance of 1.0.

Args:
    ramp: The ramp, darkest first. Order is the mapping, so a reversed ramp inverts
        the image.
    contrast: Stretch the mapping around mid-grey. Above 1.0 pushes pixels toward
        the ends of the ramp and drops the middle steps; below 1.0 crowds everything
        into the middle. The interesting control is not which colours are used but
        how much of the art each step takes.
    bias: Shift the whole mapping after contrast, from -1.0 to 1.0. Positive is
        lighter. Use it when an image maps too dark to read.
    dither: "bayer4", "bayer2" or "checker" to break the bands. A pixel landing
        between two steps takes the darker or the lighter one by an ordered pattern,
        which reads as a gradient without adding a colour.
    x, y, width, height: Restrict the change to a region.

Luminance is weighted 0.299/0.587/0.114, the same weighting the ramp matching uses,
so a saturated red and a dull red of the same weight land on the same step. Alpha is
carried through untouched, so the silhouette does not move and anti-aliased edges
keep their coverage, even though their colour is now a ramp entry.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `contrast` | number | no | 1.0 |
| `bias` | number | no | 0.0 |
| `dither` | string | no | _none_ |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `outline_smart`

Outline a shape in colours drawn from its own ramp, not one flat colour.

`add_outline` paints a single colour all the way round, which reads as a sticker.
Pixel artists vary the outline: darker where the form turns away from the light,
and often dropped entirely on the lit side so the shape breathes.

Args:
    ramp: Colours darkest first. Outline pixels come from here.
    mode: "colormatched" takes each outline pixel from the adjacent interior colour
        shifted `darken_steps` down the ramp. "selective" does the same but leaves
        the lit side unoutlined, which needs `light_angle`. "single" uses the
        darkest ramp entry all round, the classic look.
    darken_steps: How many ramp steps below the neighbouring interior colour.
    light_angle: Degrees, required for "selective". 135 is the usual key light.
    tolerance: How close an interior pixel must be to a ramp entry to be used as
        the source for its outline pixel.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

The outline is drawn outside the silhouette, into transparency, so it never eats
into the artwork.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `mode` | string | no | colormatched |
| `darken_steps` | integer | no | 2 |
| `light_angle` | number | no | _none_ |
| `tolerance` | number | no | 32.0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `seam_occlusion`

Darken the seam where two masses of the **same** material overlap, along its ramp.

`contact_shadow` does ambient occlusion already and finds the form doing the occluding
by colour, which is the one case a figure never presents. An arm against a torso, a
pauldron over a shoulder, a thigh against a hip: both sides are the same stone under
the same light and no colour separates them, so there is nothing for `occluder_color`
to match. Measured on this project's own golem, an armpit where an artist darkens the
contact came out +131 in luminance, because nothing here could see the seam.

What a colour cannot say, the caller can. The map is the same notation
`draw_pixel_map` and `shade_facets` take, one character per pixel, except that the
legend names **masses** instead of colours or directions, and gives each one a `z`.

Args:
    rows: One string per row of the map, one character per pixel. "." is a pixel that
        belongs to no mass, and is neither darkened nor treated as an occluder.
    legend: {symbol: z}, where a **higher z is nearer the viewer**. `{"a": 1, "b": 0}`
        says mass "a" overlaps mass "b", so the seam darkens on "b" and not on "a".
        Occlusion is asymmetric and that is the whole point: darken both sides of a
        seam and you have drawn brickwork, darken the side behind and you have put one
        mass in front of another.
    ramp: Colours darkest first. Darkened pixels stay on this ramp, so conformance is
        preserved by construction.
    radius: How far the darkening reaches from the seam, in pixels. 2 is usually right
        and is what gives the falloff somewhere to happen.
    depth: How many ramp steps darker, against the seam itself, tapering to nothing at
        `radius`. Refused at or above the ramp's length, which would slam the seam to
        the darkest entry whatever was there.
    tolerance: How close a pixel must be to a ramp entry to be darkened, as a weighted
        RGB distance. A pixel further off is left alone, so a seam crossing another
        material does not drag it onto this ramp.
    x, y: Where the map's top-left corner lands on the canvas.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

The darkening **falls off with distance** from the seam rather than being a hard line,
on the same curve `contact_shadow` uses so the two cannot disagree about what a contact
falloff is. That matters more here than it does there: the workaround this replaces, in
this project's golem generator, read seam pixels back in Python and slammed them two
steps down at a fixed width, and the result read as masonry. A combination that cannot
produce a falloff, such as `depth=1` over `radius=2`, is reported as a flat band rather
than passed off as one.

Refuses rather than darkening nothing: a map with one mass, a map whose masses all sit
at the same z, masses that do not come within `radius` of each other, and a pass where
every pixel it reached was already at the ramp's darkest step are each their own
refusal, and each one names the counts behind it.

Reports `masses` (pixels per symbol), `depths` (the z each resolved to), `by_steps`
(how many pixels moved how far, which is the falloff) and `darkened_pixels`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `rows` | array<string> | yes |  |
| `legend` | object | yes |  |
| `ramp` | array<string> | yes |  |
| `radius` | integer | no | 2 |
| `depth` | integer | no | 2 |
| `tolerance` | number | no | 24.0 |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `shade_facets`

Shade a form built from flat planes, one tone per plane, from a map of directions.

Args:
    rows: One string per row of the map, one character per pixel, as `draw_pixel_map`
        takes. "." leaves a pixel alone.
    legend: {symbol: facet direction}. A direction is an angle in degrees in the same
        convention as `light_angle` (0 faces right, 90 up, 135 up and to the left),
        the word "front" for a plane square to the viewer, or `[angle, z]` to tilt a
        plane toward the viewer as well, which is how a chamfer is said.
    ramp: Colours darkest first. Facet tones are entries of this and nothing else.
    light_angle, light_z: The key light.
    fill_strength: How much bounce comes back from roughly opposite, as a share of the
        key. Without it every plane facing away from the key clamps to the same
        ambient value and the whole shadow side comes out one flat colour.
    ambient: The floor, so a plane facing away is dark rather than black.
    x, y: Where the map's top-left corner lands.

`shade_region_by_light` reads a surface normal out of how far each pixel sits from the
silhouette's edge. That is right for anything round and wrong for everything hard: a
distance field cannot know where an edge is, so it rounds the form over, and a crate
comes out as a cushion. This takes the normals from the caller instead, because which
way a plane faces is a fact about the drawing that only the person drawing it knows.

Every pixel of one facet gets the same value. That flatness is the point: it is what
reads as cut rather than inflated, and it is the thing a gradient cannot imitate.

Returns the usual write counts plus `facet_steps`, the ramp step each symbol resolved
to, so a caller can see the value structure it just asked for. A pass whose facets all
land on the same step is refused rather than painting a flat fill.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `rows` | array<string> | yes |  |
| `legend` | object | yes |  |
| `ramp` | array<string> | yes |  |
| `light_angle` | number | no | 135.0 |
| `light_z` | number | no | 0.5 |
| `fill_strength` | number | no | 0.35 |
| `ambient` | number | no | 0.16 |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `shade_region_by_light`

Shade a flat region as a lit form, using a ramp and a light direction.

Turns a flat fill into a shaded one: an asymmetric terminator, a darker core away
from the light, and optional rim light. Every output pixel comes from `ramp`.

Scope this to one material. Shading a whole layer flattens materials together: a
sword shaded in one pass turns steel, brass and leather into the same colours, where
three scoped calls keep all three. Scope it by passing `base_color`, by making a
selection first (`select_by_color` is the usual way), or both.

What it cannot do: a distance field measures depth inside a silhouette, so it cannot
invent form boundaries that are not in the outline. An overlapping head and torso
drawn as one flat shape become one mass. Shade them as separate regions.

Args:
    ramp: Colours darkest first, as from `generate_ramp`. Output uses only these.
    base_color: Only shade pixels near this colour. Defaults to every opaque pixel
        in scope, which is usually what you want once a selection is active.
    light_angle: Degrees. 0 is from the right, 90 from above, 135 from the upper
        left, which is the conventional pixel-art key light.
    light_z: How much the light comes from the viewer, 0 to 1. Higher flattens the
        terminator and lights more of the form.
    bulge: How rounded the form reads. 1.0 is sphere-like; lower is flatter, which
        suits cloth and flat panels; higher exaggerates the curvature.
    ambient: Floor brightness in shadow, 0 to 1. Pixel art rarely wants true black
        in shadow, so this sits well above zero by default.
    rim: Light wrapping the edge away from the key, 0 to 1. A little reads as a
        bounce; a lot reads as backlight.
    bias: Shift the whole result along the ramp, in steps. Use this when the result
        is uniformly a shade too dark or light, rather than re-tuning the lighting.
    fill_angle: Degrees, a second light. Omitted by default, which leaves the result
        exactly as it was before this argument existed. Set it opposite `light_angle`
        for the fill or bounce light that keeps a shadow side readable instead of
        letting it go flat dark: the shadow side is where a sprite stops describing
        its form, and one light can only ever leave it at `ambient`.
    fill_strength: How strong the fill is next to the key, 0 to 1 and capped below 1.
        A fill that matches the key cancels the form entirely, because the two
        terminators land on opposite sides of the same shape and sum to a flat fill,
        so the cap refuses the value that destroys what the tool is for. A third to a
        half is the conventional choice.
    tolerance: How close a pixel must be to `base_color` to count as part of the
        region, as a weighted RGB distance. Ignored when `base_color` is omitted.
        **A distance between colours, not between materials.** Two ramps of different
        materials are routinely closer than the default 24: every step of a gold ramp
        generated by `generate_ramp` is within 24 of a step of a brass one, so a pass
        scoped to the brass matched the gold as readily. Art whose fills came from
        `generate_ramp` is exact, so scope it with a tolerance near zero and keep the
        wide default for hand-drawn art that varies.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

The two lights are summed and clamped, not averaged: averaging would dim the key side
as the fill came up, so adding a fill light would make the whole sprite darker and
quietly cost the ramp's top step. Clamping leaves the key side as it was and lightens
only what the key did not reach, which is what a fill light is.

`per_step` in the result counts pixels per ramp entry, which is how to check a fill
actually lightened the shadow side rather than trusting that it did.

`region_components` and `region_bounds` say whether the pass went where it was meant
to, which `region_pixels` cannot: it counts matches without saying whether they are in
one place or four. A call scoped to a 27px coin that comes back with a box spanning 200
pixels of canvas has matched something else as well, and that is the mistake
`tolerance` invites.

Refuses a region with no interior to shade: below roughly 6px across, the distance
field never exceeds a pixel and there is no form to describe. The honest answer
there is two hand-placed pixels, which `draw_pixels` already does.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `base_color` | string | no | _none_ |
| `light_angle` | number | no | 135.0 |
| `light_z` | number | no | 0.45 |
| `bulge` | number | no | 1.0 |
| `ambient` | number | no | 0.35 |
| `rim` | number | no | 0.0 |
| `bias` | number | no | 0.0 |
| `fill_angle` | number | no | _none_ |
| `fill_strength` | number | no | 0.35 |
| `tolerance` | number | no | 24.0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `shift_along_ramp`

Move pixels along a colour ramp, keeping every one of them on the palette.

This is the operation to use for "put this in shadow", "make the night variant" or
"deepen the shadow side". Each pixel is matched to its nearest ramp entry, moved
`steps` along the ramp, and clamped at the ends, so the result uses only colours
that were already on the ramp.

Prefer this over `adjust_brightness_contrast` for anything that should still look
like pixel art: that tool does colour arithmetic and lands almost every pixel
between palette entries.

Args:
    ramp: The ramp, darkest first, as produced by `generate_ramp`. Order matters:
        negative `steps` moves toward the front of this list.
    steps: How far to move. Negative darkens (toward the front of `ramp`), positive
        lightens. Pixels already at an end stay there rather than wrapping.
    x, y, width, height: Restrict the change to a region. Defaults to the whole
        canvas. Scope this when a sprite has several materials: one ramp applied to
        everything flattens steel, brass and leather into the same colours.
    tolerance: How far a pixel may be from a ramp entry and still be treated as
        belonging to it, as a weighted RGB distance. Pixels further away than this
        are left alone and counted in `pixels_skipped`, so shading one material does
        not disturb its neighbours.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

Returns `pixels_written` and `pixels_skipped`. A high skip count usually means the
ramp does not match the artwork, not that the sprite was already correct.

`pixels_matched` counts the pixels that both matched the ramp and were written, so it
agrees with `pixels_written` rather than counting matches an active selection then
refused.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `steps` | integer | yes |  |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `tolerance` | number | no | 48.0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `specular_highlight`

Place a small specular highlight where the light actually reflects at the viewer.

`shade_region_by_light` spreads the ramp's top step over the whole lit side, which is
what a matte surface does and why its output reads as plastic. A specular is the other
thing at the top of the ramp: a two or three pixel glint on the one part of the form
whose normal sends the light straight back at you. It is the difference between a
stone and a gem, and it is small by definition.

Run this **after** `shade_region_by_light`, on the same region and the same light: it
reuses that tool's region mask, distance field and surface normals, so the glint lands
inside the highlight rather than beside it.

**Reserve the top step for it.** Shade the form with the ramp *minus its last entry*
and then call this with the whole ramp:

    shade_region_by_light(f, ramp[:-1], light_angle=135)
    specular_highlight(f, ramp, light_angle=135, size=2)

Shading with the full ramp spreads its top step over the entire lit side, which leaves
nothing above it for a glint to be: the specular then paints pixels the colour they
already are, and that call is refused rather than reported as a success that changed
nothing. The refusal says this and names the way out, so it is a reminder rather than
a puzzle.

Where it goes: on the normal closest to the half-vector between the light and the
viewer, not on the normal closest to the light. That offset toward the viewer is what
makes a specular sit inside the lit side instead of out on its shoulder, and it is the
whole reason this is a separate tool rather than a brighter `bias`.

What it will not do: touch an edge pixel. A specular on the silhouette's border reads
as a hole punched in the form rather than as a shine, so only pixels with all eight
neighbours inside the region are candidates. On a region with no such pixel there is
nothing to put a glint on, and the call is refused with the same message
`shade_region_by_light` gives for a region too thin to shade.

Args:
    ramp: Colours darkest first, the same ramp the form was shaded with.
    light_angle: Degrees, and it must match the shading pass or the glint contradicts
        the form. 0 is from the right, 90 from above, 135 from the upper left.
    light_z: How much the light comes from the viewer, 0 to 1. Match the shading pass.
    size: How many pixels the glint covers. A count, not a radius: a specular is two
        or three pixels on most sprites, and the point of this tool is that it stays
        that small. The pixels are grown outward from the brightest one and stay
        touching, so the result is one glint rather than scattered dots.
    tightness: How narrowly the surface has to face the reflection to count, 0 to 1,
        as a threshold on the normal against the half-vector. High is a tiny hard
        glint on a polished surface; low lets a broader shoulder qualify, from which
        `size` still takes only the best pixels. If nothing clears it the call is
        refused and the message names the best alignment the form actually offers, so
        the number to lower it to is in the error rather than a guess.
    bulge: How rounded the form reads. Match the shading pass, or the normals this
        works from are not the normals the shading used.
    highlight_color: The glint's colour, defaulting to the ramp's top step so
        `palette_conformance` stays at 1.0. This is the flag for metal, which is the
        one material whose specular is genuinely brighter than its own ramp: name a
        near-white there. A colour that is not on `ramp` will drop conformance against
        that ramp, which is the honest trade rather than a bug, and the result says
        whether it happened.
    base_color: Only consider pixels near this colour, as for `shade_region_by_light`.
        Scope it the same way you scoped the shading.
    tolerance: How close a pixel must be to `base_color` to count as part of the
        region. Ignored when `base_color` is omitted.
    layer: Target layer (default: top layer).
    frame: Target frame, 1-based.

Returns `specular_pixels` (how many were placed, which is below `size` when the
eligible area is smaller than the budget), `pixels` (where they went, so a later
`remove_stray_pixels` can be told to protect them), `pixels_changed` (how many were
not already that colour) and `peak_alignment`, the best normal against the
half-vector found anywhere in the region.

Also `region_components` and `region_bounds`, which say whether the region is where it
was meant to be. Worth reading on this tool in particular: the normals come from the
*whole* region, so scoping a glint to a compound object rather than to one of its parts
puts it wherever that object's overall mass bulges. A sword scoped by its whole cell
got its only glint on the leather grip, with none on the blade, and
`specular_pixels: 2` said nothing about that.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `light_angle` | number | no | 135.0 |
| `light_z` | number | no | 0.45 |
| `size` | integer | no | 2 |
| `tightness` | number | no | 0.7 |
| `bulge` | number | no | 1.0 |
| `highlight_color` | string | no | _none_ |
| `base_color` | string | no | _none_ |
| `tolerance` | number | no | 24.0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `surface_emission`

Light an interior source onto the surface around it, up that surface's own ramp.

`glow` builds a halo on a layer **below** the artwork, and its docstring says plainly
that "a body blocks the halo of a gem inside it". So a glowing core inside a silhouette
gets nothing at all: on this project's golem, `glow` contributed zero pixels to the
export, which was confirmed by counting the colours in the committed PNG (nine: eight
stone steps and one core colour), and the longest comment in the old generator defended
a layer with nothing on it. What light from an interior source actually does is warm the
surface it sits in, and that is this.

It is neither a halo nor a gradient. Each pixel within `radius` of the source is moved
**up the ramp it is already on**, by a number of steps that falls off with distance, so
the surface keeps its own form: a crack near the core stays darker than the stone around
it, and both brighten. Painting a colour per ring instead, which is what a hand-rolled
bloom does, flattens every tone inside the radius to one value and reads as a gradient
laid over the figure.

Args:
    ramp: Colours darkest first, and **the ramp the surface is painted on**: this moves
        pixels along it, so a pixel further than `tolerance` from every entry is left
        alone rather than dragged onto a palette it was never on. The warmth therefore
        comes from the ramp's upper end, which is where a hue-shifted ramp is warm
        (`generate_ramp` with `light_hue`). To tint as well as brighten, hand it a ramp
        built from the surface's midtone up into the source's colour and the lift walks
        into that hue.
    source_color: The colour of the thing emitting, for example a gem or a molten core.
        Source pixels are never repainted; they are where the light comes from.
    radius: How many rings of surface the light reaches, in pixels.
    depth: How many ramp steps the ring touching the source is lifted. The outermost
        ring is always lifted by at least 1, because a ring that moves nothing should
        not be in the radius. Refused at or above the ramp's length.
    falloff: "quadratic" keeps the lift concentrated near the source, which is how light
        falls off and what reads as a source; "linear" spreads it evenly.
    tolerance: How close a pixel must be to a ramp entry to be lifted, as a weighted RGB
        distance.
    source_tolerance: How close a pixel must be to `source_color` to count as the
        source. Defaults to `tolerance`, and it wants to be **tight** for the reason
        `contact_shadow` documents at `occluder_tolerance`: the source is a flat colour
        you named, while `tolerance` has to stay loose enough for shaded art that
        varies, and one number cannot be both. The result warns when `source_color`
        cannot be told apart from a ramp entry, because then the surface is partly its
        own source and the light spreads from the wrong pixels.
    layer: The layer whose surface is lit, and the one written (default: top layer).
    frame: Target frame, 1-based.

**Why this is not an argument to `glow`.** `glow` writes a new layer below the subject
and promises the subject's cel is untouched, so deleting one layer removes the effect;
this writes into the subject's cel, because light landing on a surface is part of that
surface. `glow` paints only where the art is not; this paints only where the art is.
`glow` refuses when it runs out of room outside the silhouette; this refuses when it
finds no surface on the ramp inside it. An argument that reversed all three would be two
tools sharing one name, and it would make `glow`'s central promise conditional on a flag.

Refuses rather than reporting a pass that did nothing: no pixel matching `source_color`
is an error, and so is a source with no surface on the declared ramp around it. The
refusal carries the counts that say which it was.

Reports `per_ring`, how many pixels were lifted at each distance, which is the number
that says the falloff happened, alongside `lifts`, the steps each ring was given.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `source_color` | string | yes |  |
| `radius` | integer | no | 4 |
| `depth` | integer | no | 3 |
| `falloff` | string | no | quadratic |
| `tolerance` | number | no | 24.0 |
| `source_tolerance` | number | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


## Selections

### `deselect`

Clear the selection, so edits affect the whole layer again.

A real step, not a formality: the selection lives in a sidecar beside the sprite and
persists across calls, so leaving one active will silently scope every later edit.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `get_selection`

Describe the current selection: whether there is one, and what it covers.

Returns `bounds`, the pixel `area` actually inside the selection, and a `map` of
the selected region using `#` for selected and `.` for not, in the same shape
`get_pixels(format="map")` uses. The map is capped, and omitted for a selection
larger than the cap, since a wall of characters is not feedback.

Worth calling before a large edit: a selection you forgot about is the difference
between changing what you meant and changing a corner of it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `invert_selection`

Swap what is selected for what is not.

Selecting a character's silhouette and inverting gives the background, which is
usually easier than describing the background directly.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `modify_selection`

Grow, shrink, or outline the current selection.

Args:
    op: "expand" grows by `quantity` pixels, "contract" shrinks, "border" replaces
        the selection with a band of that width around its edge. A border selection
        is how you scope an outline or a contact shadow to where two forms meet.
    quantity: How many pixels, at least 1.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `op` | string | yes |  |
| `quantity` | integer | no | 1 |


### `select_by_color`

Select every pixel of one layer matching a colour, the magic-wand selection.

The usual way to scope an edit to one material: select the armour's base colour and
every later operation touches only the armour. Pair it with `shift_along_ramp` to
shade one material without disturbing its neighbours.

Args:
    color: The colour to match.
    tolerance: 0 matches exactly. Higher values also catch nearby colours, which is
        useful on artwork that was anti-aliased or converted from a photo.
    frame: Which frame to sample, 1-based.
    layer: Which layer to match on. Defaults to the top layer, which is the layer the
        drawing and shading tools also default to, so a selection made here scopes
        the call that follows it.

**One layer, not the composite**, and that is deliberate for the same reason
`get_pixels` takes a layer: the tools this selection is for write to one layer, so a
pixel selected on a different one is selected and unreachable. Select on the layer you
are about to edit.

This used to run Aseprite's `MaskByColor` without saying which layer it meant, and the
layer it got was whichever one Aseprite made active on opening the file, which is the
*bottom* one. Measured on an 8x8 sprite with red on the bottom layer and an opaque
blue square over half of it on the layer above: matching red selected all 64 pixels,
including the 32 nothing can see, and matching blue (32 pixels, plainly visible, and
on the layer every drawing tool writes to) selected nothing at all.

Refuses when no pixel matches, rather than reporting a success with no selection. The
old behaviour cleared the sidecar on the way through, so a mistyped colour silently
unscoped every edit that followed it, which is the opposite of what asking for a
selection means. A refusal leaves the previous selection as it was.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |
| `tolerance` | integer | no | 0 |
| `frame` | integer | no | 1 |
| `layer` | string | no | _none_ |


### `select_region`

Select a region, so later edits only affect that area.

The selection persists until `deselect`, and every pixel-writing tool honours it.
There is no per-call override: to draw outside the selection, clear it first. Tools
that wrote fewer pixels than asked report `selection_applied` and
`pixels_outside_selection`, so a forgotten selection shows up in the result rather
than as a mysteriously incomplete edit.

Args:
    shape: "rect", "ellipse" (both use x/y/width/height) or "polygon" (uses points).
    x, y, width, height: The region. width/height default to the rest of the canvas.
    points: For "polygon", a list of {"x": int, "y": int}, at least 3.
    mode: "replace" the selection, or "add"/"subtract"/"intersect" with the current
        one. Building a selection from several shapes is how you scope an edit to
        an awkward area, such as everything except a character's eyes.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `shape` | string | no | rect |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `points` | array<object> | no | _none_ |
| `mode` | string | no | replace |


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

Add a pixel outline around the artwork on a layer, optionally weighted by light.

The outline is drawn around the art **already on the layer given, onto that same
layer**. It does not outline other layers, so it cannot draw a keyline onto a fresh
empty layer of its own; a layer with no drawn pixels on the frame is refused rather
than reported as an outline that drew nothing.

Args:
    color: Outline colour.
    thickness: Outline width in pixels (default 1). With `light_angle`, this is the
        width on the edges that face away from the light.
    connectivity: 4 (orthogonal only) or 8 (includes diagonals, default).
    where: "outside" (grow into transparency, default) or "inside"
        (recolour the shape's border pixels).
    light_angle: Degrees, 0 from the right and 90 from above, as the shading tools
        state it. Given, the outline's width varies by which way each edge faces:
        `thickness` where the form turns away from the light, `lit_thickness` where
        it faces into it, and **everything between the two across the band of edge in
        between**.
    lit_thickness: Width on the edges facing the light. 0 drops the outline there
        entirely. Defaults to one pixel less than `thickness`. A value above
        `thickness` is allowed and puts the weight on the lit side instead, which is
        a rim light rather than a weighted outline.

A constant-width border is the single thing that most reliably makes a sprite read as
a die-cut sticker: nothing lit has an edge of uniform darkness, so the eye sees card
stamped out with a punch rather than a form in light. Hand-drawn work in this style
gathers the weight where the surface turns away and lets it vanish on the lit top
faces. `thickness=2, light_angle=135, lit_thickness=0` is that look.

The weight **tapers** rather than switching. The lit and shadow widths are the two ends
of a run of integers, and each edge pixel takes the one its facing selects, so a 2-to-0
keyline passes through 2, then 1, then 0 across a band of edge instead of flipping
between two values at the terminator. Facing is measured over a neighbourhood rather
than over the touching pixels, which is what makes the band continuous on a lumpy
silhouette: at a radius of one, a single-pixel bump swings the facing by ninety degrees
and the keyline comes apart into scraps. Measured by walking the boundary ring of a disc
with twelve bumps on it, the old per-pixel test crossed between outlined and bare 30
times, which is fifteen separate pieces of keyline; the taper crosses twice, which is
one arc. That fragmenting is why `lit_thickness=0` had to be reverted to 1 on this
project's own golem, where it measured better and looked damaged.

With the two widths one apart there are only two integers to choose from and the
changeover sits at the same facing the old comparison used, so
`thickness=2, lit_thickness=1` draws exactly what it drew before. The taper appears once
they differ by two or more, which is the case that was broken.

Reports `outline_weights` alongside the lit and shadow counts: how many of the
silhouette's own boundary pixels took each thickness, from 0 upward. That is the number
that says whether a pass tapered or switched, since a switch leaves the entries between
its two widths empty.

For an outline in colours taken from the artwork's own ramp rather than one flat
colour, see `outline_smart`, which varies hue instead of width.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |
| `thickness` | integer | no | 1 |
| `connectivity` | integer | no | 8 |
| `where` | string | no | outside |
| `light_angle` | number | no | _none_ |
| `lit_thickness` | integer | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `adjust_brightness_contrast`

Adjust brightness (-255..255, additive) and contrast (-255..255) of a layer.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `brightness` | integer | no | 0 |
| `contrast` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `adjust_hue_saturation`

Shift hue (degrees) and scale saturation/lightness (percent, -100..100).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `hue` | integer | no | 0 |
| `saturation` | integer | no | 0 |
| `lightness` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `cast_shadow`

Lay a subject's shadow on the ground, away from the light and made of ramp steps.

`add_drop_shadow` offsets a copy of the artwork and tints it, which is a sticker of
the subject floating beside it. A cast shadow is a different thing: it falls on a
*surface*, away from the light, and flattens as it goes, so on the ground it is a
foreshortened ellipse under the subject rather than a second copy of its silhouette.

Built entirely of ramp steps, which is the point. A shadow made by multiplying alpha
lands every pixel of it between palette entries, and then `palette_conformance` drops
and nothing downstream holds together: indexed export, tileset reuse, a consistent
look between two sprites. The core is `ramp[0]` and each pixel of `softness` around it
is one step lighter, so the whole effect is ramp entries arranged in space.

Where it falls: the direction is away from `light_angle`, and the length comes from
`light_height` as the actual cotangent of the light's elevation. An overhead light
casts an ellipse straight underneath; a low light throws it far to one side.

Onto what: `ground_layer`. Name the layer holding the floor and the shadow is clipped
to it, so it cannot run off the edge of a platform and hang in the air, and if that
layer has nothing where the shadow would land the call is refused rather than drawing
a shadow onto nothing.

Args:
    layer: The layer casting the shadow. Its cel is never modified. A background
        layer is refused: it is opaque and covers the canvas, so it has no silhouette
        to cast. `convert_background_to_layer` first if the subject is one.
    ramp: Colours darkest first, normally the *ground's* ramp rather than the
        subject's, since the shadow is a darkening of the surface it lies on.
        Required, and deliberately so: a shadow built out of alpha instead is
        `add_drop_shadow`, which already exists.
    light_angle: Degrees. 0 is from the right, 90 from above, 135 from the upper left.
        The shadow falls the opposite way.
    light_height: The light's elevation, above 0 and up to 1. 1.0 is directly
        overhead and casts no length at all; small values are a low sun and throw a
        long shadow. This is the control that changes the shadow's length.
    ground_y: The row the shadow lies on. Defaults to the subject's own contact row,
        the lowest row it has a pixel on, which is the same measurement
        `validate_loop` reports as `contact_rows`. Refused if it sits above that row,
        because a floor running through the subject is not a floor.
    ground_layer: The layer holding the surface. When given, the shadow is clipped to
        that layer's pixels and the call is refused if there is nothing there to
        catch it. Consulted for its pixels, not for whether the picture shows them: a
        hidden layer, or one at a low opacity, still holds the pixels the clip asks
        about, so the shadow is drawn and the result reports what the floor actually
        is (see below) rather than the call being refused over it.
    softness: Pixels of penumbra around the core, each one ramp step lighter. 0 is a
        hard-edged shadow, 1 or 2 is the usual soft contact.
    opacity: The shadow *layer's* opacity, 0 to 255. Left at 255 the shadow's pixels
        are exactly ramp entries, which is what keeps conformance at 1.0; lowering it
        blends them with whatever is underneath and takes the composite off the ramp,
        so prefer a lighter ramp step over a lower opacity.
    new_layer: Name for the shadow's own layer, created directly below `layer`, or
        reused when a previous call of this tool made it and `frame` has no cel on it
        yet. That is how one shadow layer carries a whole walk cycle. A second call for
        the same layer *and* frame is refused, because two effects composited into one
        cel are a picture neither call describes, and so is a layer of that name this
        tool did not create.
    frame: Frame to build the shadow for, 1-based.

Returns the ellipse it used as `shadow_ellipse` (`[cx, cy, rx, ry]`), the
`contact_row` it measured, and `shadow_pixels`. A shadow that landed entirely off the
canvas is refused rather than reported as a success that drew nothing.

With a `ground_layer` the result also says what that floor is: `ground_layer_visible`,
`ground_layer_opacity`, and `ground_layer_hidden` naming the layer and any group whose
flag is off, which is present only when something is. A floor the picture does not
show, or shows faintly, is reported in `warnings` as well, because a crisp shadow on
an invisible surface is usually a layer named by mistake rather than an intent.

`clipped_pixels` is routinely large next to `shadow_pixels` when `ground_layer` is a
thin floor, and that is arithmetic rather than a fault: the ellipse is centred on the
contact row and so half of it lies above the floor's top edge, where there is no
surface. Pass `ground_y` at the floor's own top row to push it down, or leave
`ground_layer` out and let the subject hide the upper half.

A shadow is refused when rasterising it would allocate more points than the limit,
which is reachable from legal arguments on a large canvas: the ellipse's radii grow
with the subject's size and with how low the light sits, and the point list is built
in full before any pixel is drawn, so that cost is memory rather than patience. The
message names both radii and the remedy. `ellipse_points` in the result says how close
an accepted shadow came.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `light_angle` | number | no | 135.0 |
| `light_height` | number | no | 0.6 |
| `ground_y` | integer | no | _none_ |
| `ground_layer` | string | no | _none_ |
| `softness` | integer | no | 1 |
| `opacity` | integer | no | 255 |
| `new_layer` | string | no | shadow |
| `frame` | integer | no | 1 |


### `desaturate`

Desaturate toward grayscale by `amount` percent (0-100).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `amount` | integer | no | 100 |
| `layer` | string | no | _none_ |
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
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `fill_gradient`

Fill a region with a gradient, by default only where pixels already exist.

Args:
    colors: 2+ colour stops, e.g. ["#000000", "#ff004d", "#ffec27"], spread
        evenly. For dither=True, provide exactly 2 colours.
    gradient_type: "linear" or "radial".
    angle: Direction in degrees for linear gradients (0 = left->right).
    dither: Ordered (Bayer 4x4) dithering between 2 colours instead of smooth
        interpolation, great for limited palettes / retro looks.
    x, y, width, height: Region (defaults to the whole canvas).
    respect_alpha: Leave transparent pixels transparent (default). The gradient
        then shades the artwork inside the region rather than filling the region.
        Pass False to paint the whole rectangle, background included.

Returns `pixels_written` and `pixels_skipped` so the caller can tell how much of
the region was actually covered.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `colors` | array<string> | yes |  |
| `gradient_type` | string | no | linear |
| `angle` | number | no | 0.0 |
| `dither` | boolean | no | False |
| `x` | integer | no | 0 |
| `y` | integer | no | 0 |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |
| `respect_alpha` | boolean | no | True |


### `glow`

Halo a shape in rings of ramp steps, so it glows without leaving the palette.

`add_outline` gives one flat ring, which reads as a sticker. A glow is several rings,
each a step further down a ramp: hottest against the artwork, fading outward, with the
outer ring optionally dithered so it ends in something softer than a hard edge.

The ramp is what makes this different from a glow in an image editor. A halo made of
alpha, or of colours interpolated between two others, takes the art off its palette,
and then `palette_conformance` drops and the sprite no longer exports to an indexed
format, reuses a tileset, or matches the sprite beside it. Every pixel this writes is
exactly one of the colours you passed in.

The glow goes on its own layer below the artwork, so the subject's cel is untouched
and deleting one layer removes the effect.

Args:
    ramp: Colours darkest first. Ring 1, touching the artwork, takes the top step and
        the outermost ring takes `ramp[0]`, so a longer ramp fades more finely. For a
        glow that reads as light rather than as a coloured border this usually wants
        its own bright ramp (a gem's or a flame's), not the subject's body ramp.
    radius: How many rings, in pixels. 2 or 3 reads as a glow; much more reads as fog.
    falloff: "linear" spaces the steps evenly. "quadratic" drops away faster, keeping
        a hotter core and a dimmer skirt, which is the one that reads as a light
        source rather than as an outline.
    dither_edge: Dither the outermost ring, so the glow ends in a half-density
        scatter instead of a hard line. This is binary coverage, a pixel either drawn
        or not, rather than a partial alpha, so every drawn pixel is still exactly a
        ramp step and conformance stays at 1.0.
    base_color: Glow only around pixels near this colour, which is how a gem glows
        while the hand holding it does not. Distance is measured out from those
        pixels, but the glow is never painted over any part of the subject layer, so
        a body blocks the halo of a gem inside it.
    tolerance: How close a pixel must be to `base_color` to be treated as a source,
        as a weighted RGB distance. Ignored when `base_color` is omitted.
    new_layer: Name for the glow's own layer, created directly below `layer`, or
        reused when a previous call of this tool made it and `frame` has no cel on it
        yet. That is how one glow layer carries a flickering torch across four frames
        rather than needing four layers with one cel each. A second call for the same
        layer *and* frame is refused, because two halos composited into one cel are a
        picture neither call describes, and so is a layer of that name this tool did
        not create.
    layer: The layer to glow around (default: top layer). Its cel is never modified.
    frame: Target frame, 1-based.

Refuses rather than drawing nothing: no pixel matching `base_color` is an error, and
so is a subject that leaves the glow nowhere to go.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `ramp` | array<string> | yes |  |
| `radius` | integer | no | 3 |
| `falloff` | string | no | linear |
| `dither_edge` | boolean | no | True |
| `base_color` | string | no | _none_ |
| `tolerance` | number | no | 24.0 |
| `new_layer` | string | no | glow |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `invert_colors`

Invert the RGB colours of a layer's pixels (alpha preserved).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `normalize_edge_runs`

Even out the run lengths along a silhouette's diagonals, conservatively.

A hand-drawn diagonal is built from runs of consistent length: a 1:2 slope is two
pixels, two pixels, two pixels, held steady, and broken only on purpose. A generated
one wanders, runs of 3, 1, 2, 1, 4 where a person would have drawn 2, 2, 2, 2, and
that wander is the most recognisable tell in generated pixel art, ahead of both colour
and shading. `assess_sprite` already counts it as `jaggy_corners`, which on a boundary
stepping one way is exactly the number of steps; this is what to do about the count.

What it changes is narrow on purpose: a run of **exactly one**, with a run of at least
two on either side, stepping the same way on both sides, by exactly one pixel each
time. That run is merged into whichever neighbour lies further out, which paints one
pixel in the colour of the pixel beside it. Everything else is left alone and counted
under `kept`, so a pass that declines to touch something says which rule stopped it:

* `diagonal`: the run sits next to another one-pixel run, so this is a 1:1 diagonal,
  already the most even edge there is;
* `feature`: the run is further out, or further in, than both its neighbours. That is a
  spike or a notch, a local extremum, and somebody drew it: a horn, a finger, a chip
  in the stone;
* `step`: the step either side is more than one pixel, so this is a change of slope;
* `thin`: the edge belongs to something thinner than `min_span`, where adding a pixel
  reshapes the feature instead of smoothing its edge;
* `no_gain`: the merge would not lower the jagged-corner count, measured over the four
  2x2 windows the one new pixel can change.

Because it only ever adds a pixel, and only ever a value the boundary already held
somewhere else, **the silhouette's extent cannot move and nothing can be eaten**. Both
are checked rather than promised: a plan whose bounding box differs from the
original's is refused and nothing is written.

Args:
    min_span: How thick the mass behind an edge has to be before its edge is treated
        as an edge, measured as the unbroken run of drawn pixels inward from the
        boundary. The default of 3 is the smallest value at which the added pixel is a
        minority of what it joins. Raise it to protect thin limbs; 2 is the floor.
    layer: The layer whose silhouette is read and written (default: top layer).
    frame: Target frame, 1-based.

Returns `jaggy_corners_before` and `jaggy_corners_after` every call, so the claim is in
the result rather than in this docstring, along with `runs_merged` and `by_side`. A
pass with nothing to merge is **refused**, and the refusal carries the tally above: a
silhouette this cannot improve is the normal case for art that was drawn by hand.

Two Aseprite launches, one to read the silhouette and one to paint: the decision about
which runs are stumbles is arithmetic over the whole shape, and the shape is only
knowable with the file open. The read ignores any active selection, because the
geometry is a fact about the whole silhouette, while the write honours it like every
other drawing tool. When the mask refuses some of the planned pixels, the after figure
is withheld rather than reported against a shape that was not painted.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `min_span` | integer | no | 3 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


### `remove_stray_pixels`

Replace pixels that have no neighbour of their own colour with the colour around them.

A stray pixel is one whose eight neighbours are all a different colour. They are what
a shading pass leaves behind at a band boundary, and at any zoom they read as dirt
rather than as texture. `assess_sprite` counts them as `isolated_pixels`; this is what
to do about the count.

Each stray takes the most common colour among its opaque neighbours, so **no new
colour can appear**: the result uses a subset of the colours already there, and art on
a ramp stays on it. Transparent pixels are left alone, so the silhouette does not
change.

A stray with no opaque neighbour at all has no colour to take, so by default it is
skipped: inventing one would be drawing rather than cleaning. That is the right answer
inside the art and the wrong one for the commonest dirt an effects pass leaves, which
is a lone pixel *outside* the art on empty canvas. `erase_isolated` is for that.

Args:
    protect: Colours never to replace. A one-pixel eye highlight or a specular dot is
        a stray by this definition and is meant to be there, so name its colour. Also
        keeps a cluster `erase_isolated` would otherwise erase, if the colour is in it.
    erase_isolated: Erase a cluster that stands clear of everything else instead of
        skipping it. **Opt-in, because this changes the silhouette**, which is the one
        thing the tool otherwise never does: a one-pixel spark, a floating highlight,
        the dot of an "i" drawn as its own element and a dither sparser than a
        checkerboard are all clusters by this rule and are all meant to be there. What
        it erases is reported as `erased`, apart from `replaced`, for the same reason.
    min_cluster: How many pixels a detached cluster may have and still count as dirt.
        1, the default, is a lone pixel, which is all "isolated" means by itself; 2
        catches the two-pixel speck these passes usually leave, where neither pixel is
        isolated because each has the other for company. Capped low, and the refusal
        names the cap: past a handful of pixels a thing standing clear of the artwork
        is a mark somebody drew. Only means anything with `erase_isolated`, and is
        refused without it rather than ignored.

Erasure is decided over clusters of **opaque** pixels, connected in all eight
directions, that have nothing but transparency around them. That is what makes it safe
at any `min_cluster`: the artwork is connected to itself, so it is never a cluster, and
only something standing clear of it can go. It is also why the two halves of this tool
barely meet: a cluster touches no other opaque pixel, so nothing else's replacement can
be reading a colour off one. Where they do meet, erasing wins, since recolouring dirt
on its way out is work with no result.

A pixel whose only same-colour neighbour is **diagonal** is part of a dither pattern,
not dirt, and is left alone. `assess_sprite` counts isolation orthogonally, which is
the stricter reading, so a dithered sprite still reports some `isolated_pixels` after
this has run and that count is the dithering rather than anything to fix.

This is not Aseprite's own Despeckle, which is a median filter: that one averages
neighbourhoods, introduces colours that were not in the palette, and on a measured
test left *more* stray pixels than it found. This changes only the pixels that are
strays, and only to colours already next to them.

Returns how many were replaced, so a second call can be skipped when it says 0. With
`erase_isolated` it also returns `erased` and `erased_clusters`, which are absent
otherwise: a count of work nobody asked for reads as a finding.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |
| `protect` | array<string> | no | _none_ |
| `erase_isolated` | boolean | no | False |
| `min_cluster` | integer | no | 1 |


### `replace_color`

Replace every pixel matching `from_color` (within `tolerance` per channel)
with `to_color`, on the chosen layer + frame.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `from_color` | string | yes |  |
| `to_color` | string | yes |  |
| `tolerance` | integer | no | 0 |
| `layer` | string | no | _none_ |
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

scale is capped at 64, font_size at 512, and the rendered text at 200,000
pixels; the pixel budget is enforced while rasterizing, not afterwards.

Returns the standard draw result plus the rendered text's pixel size.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `text` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `color` | string | yes |  |
| `scale` | integer | no | 1 |
| `font_path` | string | no | _none_ |
| `font_size` | integer | no | 16 |
| `spacing` | integer | no | 1 |
| `threshold` | integer | no | 128 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


## Tilemaps

### `add_tile`

Add a new tile to the layer's tileset (optionally filled with a solid colour).
Returns the new tile's index.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `color` | string | no | _none_ |
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
| `columns` | integer | no | _none_ |
| `rows` | integer | no | _none_ |
| `frame` | integer | no | 1 |


### `fill_tile`

Fill an existing tile's artwork with a solid colour.

Returns `pixels` (the tile's area, all of which is written) so the result says the fill
reached the tile rather than only that the call returned.

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
| `color` | string | no | _none_ |
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
`data:image/png;base64,` prefix. The decoded image is capped at 32 MB; for
anything larger, write the file into the workspace and use `stamp_file`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `image_base64` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `opacity` | integer | no | 255 |
| `blend_mode` | string | no | normal |
| `layer` | string | no | _none_ |
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
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


## Palette

### `add_palette_color`

Append a colour to the end of the palette.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `color` | string | yes |  |


### `cycle_palette`

Animate a sprite by cycling a run of palette colours, the oldest trick in the
medium: the pixels do not move, the colours do, and water flows.

**What this ships, and why.** Aseprite's file format carries a palette per frame, but
its Lua API does not expose one, so the real thing cannot be authored from here.
Measured on 1.3.18.6: `#spr.palettes` is 1 and stays 1, the collection is read-only
(`spr.palettes[2] = ...` and `table.insert` both raise "attempt to index a nil value
(field '__setters')"), `Palette` has no `frame` property, `Sprite:newPalette` does not
exist, and `Sprite:setPalette` replaces the single sprite-wide palette no matter which
frame `app.frame` is on, as does `app.command.LoadPalette`. So this is the fallback:
the frames are generated, it costs one frame of storage each, and it works everywhere
a frame does, including in a GIF or a PNG sequence.

What rotates is the pixels' own indices, not the palette. On an indexed sprite those
are the same picture, and the index move is exact: no colour matching, nothing routed
through `nearest_index`, and the palette comes back byte for byte as it went in, so
`get_palette` still shows the ramp that was authored.

Args:
    indices: The palette indices to rotate, **in the order the colours travel**. At
        least two, distinct, each one in the palette, and none of them an entry that
        cannot draw (the sprite's transparent index, or an entry whose alpha is 0):
        rotating one of those through the cycle would make drawn pixels vanish.
        `list_palette_usage` reports the contiguous runs worth passing here.
    frame_count: How many frames the cycle occupies. Defaults to `len(indices)`, which
        is one frame per colour, and is capped there: past that the rotation repeats a
        frame already written, so the extra frames cost storage and show nothing new.
    step: How far the colours travel per frame. Positive moves them forward along
        `indices`; negative moves them back. A multiple of `len(indices)` is refused
        rather than silently producing identical frames.
    layer: Cycle only this layer's pixels. Default: every pixel layer.

The sprite must have exactly one frame. A cycle generates the whole timeline from the
one drawn frame, so a sprite that already animates would have its timeline redefined,
and that is refused rather than guessed at: `duplicate_frame` the pose into a sprite
of its own first.

Refuses, before anything is written, an index outside the palette (it names the size),
an index that cannot draw, a repeated index, a step that is a whole number of laps, and
a cycle none of whose indices appear in the art, which would write identical frames and
animate nothing. That last refusal names the indices the art *is* drawn with.

Returns the frames it wrote and how many pixels moved on each, `closes` (whether the
rotation returns to where it started at the wrap), and `warnings` when the cycle does
not close, or when an index in it has no pixels to travel through. `warnings` is
absent rather than empty when there is nothing to say.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `indices` | array<integer> | yes |  |
| `frame_count` | integer | no | _none_ |
| `step` | integer | no | 1 |
| `layer` | string | no | _none_ |


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
| `from_image` | string | no | _none_ |
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
    chroma: The saturation the ramp holds, 0 to 1, in place of the base colour's own.
        **HLS saturation**, which is what `colorsys.rgb_to_hls` reports and not the
        HSV saturation an eyedropper usually shows. The two part company at the light
        end: #ff8080 is 1.00 saturated in HLS and 0.50 in HSV, so a caller passing a
        number read off a colour picker will get a more colourful ramp than intended.

Returns the ramp as a list of "#RRGGBB" colours (darkest first), with `distinct`, how
many of them are different from each other, and `hue_span`, `sat_floor` and
`grey_steps` measuring whether the hue rotation can actually be seen.

**`chroma` is usually the argument that matters, and it is easy to miss.** Every hue
control here rotates hue; none of them creates saturation, which is inherited from
`base_color` and only scaled from there. So a base picked for its *value*, the way a
base is usually picked ("stone is grey", so `#8a7f74`), carries almost no saturation,
and the ramp built from it rotates a hue that cannot be seen: the ramp this argument
was added for turned 143 degrees of hue at a 0.08 saturation floor and rendered as
eight greys, which is what `grey_steps` now says out loud. Reference work in this
style runs its apparent greys at 0.17 to 0.30. Setting `chroma` is how a ramp gets
that without the caller having to reverse-engineer a saturated base colour they did
not want to name.

**`distinct` is not always `steps`.** Lightness is clamped at both ends, so a base
already near white or near black spends its outermost steps on the same colour: nine
steps in, eight colours out. The ramp is still returned, because clamping is the honest
result of the inputs and a caller may not care, but `warnings` then names which end
collapsed and the nearest `light_range` that would not.

It is worth caring about at least once. `specular_highlight` needs the ramp's top step
to be brighter than what `shade_region_by_light` spread across the lit side, so a ramp
whose top two entries are both `#ffffff` makes that call refuse, with a message about
the shading pass. The cause is two calls earlier, in this one, which used to report
success either way.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `base_color` | string | yes |  |
| `steps` | integer | no | 5 |
| `hue_shift` | number | no | 0.0 |
| `saturation_shift` | number | no | 0.0 |
| `light_range` | number | no | 0.6 |
| `filename` | string | no | _none_ |
| `apply` | string | no | none |
| `shadow_hue` | string | no | _none_ |
| `light_hue` | string | no | _none_ |
| `sat_curve` | string | no | linear |
| `easing` | string | no | linear |
| `chroma` | number | no | _none_ |


### `get_palette`

Return the sprite's palette as a list of "#RRGGBBAA" colours.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


### `list_palette_usage`

Which palette indices the art is drawn with, how many pixels each covers, and
which runs of them are worth cycling.

Indexed sprites only: an RGB or grayscale pixel carries its own colour rather than an
offset into a palette, so there is no index to count. `extract_palette` lists the
colours such a sprite uses and `assess_sprite` counts them.

The answer `cycle_palette` needs and the answer `get_palette` cannot give. A palette
says what colours exist; this says which of them the picture actually uses, so a
256-entry palette on a sprite painted in nine colours stops being a wall of hex. The
only way to work this out before was to read every pixel through `get_pixels` and
count them by hand.

Args:
    frame: Count only this frame. Default: every frame.
    layer: Count only this layer. Default: every pixel layer, groups walked through.
        Tilemap layers are skipped, because the numbers in their cels are tile
        references rather than palette offsets.

Returns `used` (index, colour and pixel count, most pixels first), `unused`, `runs`
(the contiguous spans of used indices, longest first, which is what a cycle rotates),
the transparent index and how many pixels sit on it, and `out_of_range`: pixels
carrying an index past the end of the palette, which is what a palette resized
smaller than its art leaves behind and which no colour can be read for at all.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | no | _none_ |
| `layer` | string | no | _none_ |


### `load_palette`

Load a palette from a file (.gpl, .pal, .aseprite, .png, ...) and apply it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `palette_file` | string | yes |  |


### `quantize_palette`

Derive a palette from the art, reduced to at most `max_colors` entries.

The step between a picture and pixel art. `extract_palette` lists the colours a
sprite already uses but cannot reduce them to a budget, and `set_color_mode` maps art
onto a palette but cannot decide what the palette should be. This asks the editor's
own quantizer for the best `max_colors` colours for this art and installs them, which
is what to do before `set_color_mode("indexed", palette_source="keep")`.

One entry is spent on transparency, at index 0, which is what an indexed sprite needs
there: an opaque colour at the transparent index is in the palette and can never be
drawn.

**`max_colors` is a ceiling and nothing more, and it has a cliff in it.** The
reduction merges whole levels of colour space at a time, so it can stop well short of
what was asked for: measured, four distinct colours with `max_colors=4` came back as
one mid-grey that was the average of all four, while `max_colors=5` on the same art
returned all four exactly. The result therefore reports how many colours the art has,
how many of them the new palette holds exactly, and how many entries can draw at all,
and says in `warnings` when the palette cannot hold the art. Raising `max_colors` by
a little is usually what fixes it.

Refuses an indexed sprite. There a pixel is an offset into the palette rather than a
colour, so replacing the palette changes what every pixel means without touching a
pixel; the error says how to do it in that case.

Past a million pixels the art is not scanned, the palette is still derived, and the
result says the comparison was skipped rather than implying the art is blank.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `max_colors` | integer | no | 256 |


### `ramp_between`

Build a ramp from its two ends, which is how a ramp is usually decided.

`generate_ramp` grows a ramp outward from one base colour, so reaching a particular
shadow and a particular highlight means guessing at `hue_shift` until the ends land
near what was wanted. This takes the ends directly: pick the cool shadow and the warm
highlight, and the middle is interpolated between them.

Both ends come back **exactly** as given. They were chosen, and a ramp whose endpoints
are approximations of the caller's own colours is not the ramp that was asked for.

Args:
    easing: "perceptual" (the default) walks the straight line between the ends in
        Oklab, so the middle steps are evenly spaced to the eye and the ramp keeps its
        hue. "linear" is the naive sRGB blend, which darkens and greys the middle.
    filename, apply: As `generate_ramp`. "append" or "replace" writes the ramp into
        that sprite's palette.

Neither mode rotates hue. Interpolating hue between distant colours is what turns a
blue-to-cream ramp magenta in the middle: at that distance both ways round the wheel
are equally short, and neither is the blend anybody wanted.

Comes back with `hue_span`, `sat_floor` and `grey_steps` alongside the colours. These
are worth reading, because interpolation can only carry the chroma its ends supply: two
endpoints that are themselves near-neutral produce a ramp of greys however it is eased,
and `grey_steps` is how many of its interior steps fall below the saturation at which
hue is visible at all. The ramp this reporting was added for came back with six of
eight, and the figure painted from it read as grey stone for three drafts before anyone
measured it. To hold a chroma that the ends do not supply, use `generate_ramp` with
`chroma`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `shadow_color` | string | yes |  |
| `light_color` | string | yes |  |
| `steps` | integer | no | 5 |
| `easing` | string | no | perceptual |
| `filename` | string | no | _none_ |
| `apply` | string | no | none |


### `ramp_from_art`

Recover the ramp an existing sprite is painted with.

`extract_palette` reports the colours a sprite uses as a set. A set is not a ramp: the
shading tools need them ordered dark to light, and an agent asked to add to somebody
else's sprite has no way to get that order today.

The colours are grouped by luminance into `steps` bands, and each band is represented
by the colour most of its pixels use, so every entry is a colour that is actually in
the art and can be matched against it. `coverage` says what share of the drawn pixels
each step covers, which is how to tell a real ramp from one step plus four stragglers.

Says so when the colours are not a ramp: art spanning many hues is several materials
sharing a sprite, and comes back with a warning rather than with a plausible-looking
five colours. Scope the read with `layer` when that happens.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `steps` | integer | no | 5 |
| `layer` | string | no | _none_ |
| `frame` | integer | no | 1 |


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

The index is bounded by the palette ceiling: the Lua below resizes the palette to
`index + 1`, so the index *is* a palette size.

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
    data: Optional user data. A string is stored as it arrives; a dict or list is
        JSON-encoded, so {"type": "hitbox", "id": "body"} round-trips through
        export_slice_metadata, which derives the slice's type and id from it.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `x` | integer | yes |  |
| `y` | integer | yes |  |
| `width` | integer | yes |  |
| `height` | integer | yes |  |
| `center_x` | integer | no | _none_ |
| `center_y` | integer | no | _none_ |
| `center_width` | integer | no | _none_ |
| `center_height` | integer | no | _none_ |
| `pivot_x` | integer | no | _none_ |
| `pivot_y` | integer | no | _none_ |
| `color` | string | no | _none_ |
| `data` | string | no | _none_ |


### `list_slices`

List every slice with its bounds, center, pivot, colour and user-data.

User-data comes back two ways, because it is one string that is sometimes a document.
`data` is the string exactly as Aseprite stores it, so it round-trips through
`set_slice` unchanged. `data_parsed` is added only when that string is valid JSON,
which is the shape worth sending: `{"type": "hitbox", "id": "body"}` is what
`export_slice_metadata` reads a slice's type and id from, and what
`build_asset_from_spec` writes. A slice with no user-data has neither field, so "set
and forgot" and "never set" are now distinguishable, which they were not while this
tool reported the same thing for both.

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

data: a string is stored as it arrives; a dict or list is JSON-encoded, so structured
user-data round-trips through export_slice_metadata.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `name` | string | yes |  |
| `x` | integer | no | _none_ |
| `y` | integer | no | _none_ |
| `width` | integer | no | _none_ |
| `height` | integer | no | _none_ |
| `new_name` | string | no | _none_ |
| `color` | string | no | _none_ |
| `data` | string | no | _none_ |


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

overwrite: Replace files the pattern would expand onto (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


### `export_gif`

Export the full animation as an animated GIF (honours frame durations).

Tag *ranges* are honoured, but a tag's playback direction is not: a GIF is a flat
frame sequence. A ping-pong tag exports forward, and the result says so in
`warnings` rather than letting the caller find out in-engine.

Args:
    overwrite: Replace `output` if it already exists (default False = no-clobber).
    loop: True (the default) repeats forever, which is what Aseprite writes and what
        a cycle wants. False plays the animation once and stops.

`loop=False` is the one a one-shot needs, and there was no way to ask for it. An attack
or a death is not a cycle: built from tags at `repeats=1`, with `validate_loop`
confirming it does not close, it still exported as an endless loop that snapped from
the recovery pose back to the wind-up. Set this and the result reports `loops`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |
| `loop` | boolean | no | True |


### `export_layer`

Export a single layer of one frame as a PNG (others excluded).

overwrite: Replace `output` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | yes |  |
| `output` | string | yes |  |
| `frame` | integer | no | 1 |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


### `export_layers`

Export each layer to its own image file.

output_pattern must contain "{layer}" (e.g. "layers/{layer}.png"); add
"{frame}" too for animations. include_hidden also exports hidden layers.

overwrite: Replace files the pattern would expand onto (default False =
no-clobber). Aseprite expands the placeholders, so the check refuses when any
file matching the pattern already exists.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |
| `include_hidden` | boolean | no | False |
| `overwrite` | boolean | no | False |


### `export_onion_skin`

Export a frame with neighbouring frames ghosted behind it (onion skin).

Args:
    frame: The in-focus frame (drawn fully opaque), 1-based.
    previous, next: How many earlier/later frames to ghost.
    ghost_opacity: Max opacity (0-255) of the nearest ghost; further frames fade.
    scale: Integer upscaling factor for the output PNG.
    overwrite: Replace `output` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frame` | integer | yes |  |
| `output` | string | yes |  |
| `previous` | integer | no | 2 |
| `next` | integer | no | 0 |
| `ghost_opacity` | integer | no | 80 |
| `scale` | integer | no | 4 |
| `overwrite` | boolean | no | False |


### `export_png`

Export one frame as a flattened PNG.

Args:
    output: Destination .png path.
    frame: Frame to export, 1-based (default 1).
    scale: Integer upscaling factor (default 1).
    overwrite: Replace `output` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `frame` | integer | no | 1 |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


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
    overwrite: Replace existing output(s) (default False = no-clobber). When
        data_output is given, both files are checked before anything is written.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `sheet_type` | string | no | packed |
| `scale` | integer | no | 1 |
| `data_output` | string | no | _none_ |
| `padding` | integer | no | 0 |
| `layer` | string | no | _none_ |
| `ignore_layer` | string | no | _none_ |
| `split_layers` | boolean | no | False |
| `split_tags` | boolean | no | False |
| `overwrite` | boolean | no | False |


### `export_spritesheet_packed`

Export a sprite sheet with the controls a game engine needs: extrude, dedupe, trim.

The sibling of `export_spritesheet`, which goes through the Aseprite CLI. This one
drives the editor's own export command, which the CLI flags do not fully reach, and
adds three things that matter when the sheet is going into an engine rather than into
a preview:

Args:
    output: Destination sheet image (.png).
    sheet_type: one of horizontal, vertical, rows, columns, packed (the default).
    trim: Trim each frame to its drawn pixels before packing, so empty margins cost
        no sheet space. The frame rectangles in the data file say where each frame
        went and how much was trimmed, so an engine can still place it correctly.
    extrude: Duplicate each frame's edge pixels one pixel outwards around its cell.
        This is the fix for the thin seam or transparent line that appears between
        tiles in Unity, Godot or a shader at non-integer zoom: the sampler reads
        half a texel past the frame's edge, and without extrude that is whatever the
        neighbouring frame or empty space holds. The frame rectangle in the data file
        still names the frame itself, not the border.
    merge_duplicates: Give identical frames one rectangle in the sheet instead of a
        copy each, which is what shrinks a sheet full of held poses. Identical by
        pixels, so it catches both a duplicated frame and a linked cel. A packed
        sheet does this anyway and the result says so.
    padding: Pixels of padding around and between frames, as `export_spritesheet`.
        Padding separates frames; extrude fills the gap at the frame's own edge.
        They solve different halves of the same bleeding problem and compose.
    data_output: Optional .json path for the sheet metadata, which also carries the
        layer, tag and slice lists.
    data_format: "json-array" (the default when `data_output` is given) or
        "json-hash". The array form lists frames in order, which an engine indexing
        by frame number wants; the hash form keys them by name, which a loader
        looking frames up by name wants. The tag section is called `frameTags` in
        both.
    overwrite: Replace existing output(s) (default False = no-clobber). When
        `data_output` is given, both files are checked before anything is written.

The source sprite is not modified: verified, the file's bytes and frame count are the
same afterwards, including with trim and extrude set.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `sheet_type` | string | no | packed |
| `trim` | boolean | no | False |
| `extrude` | boolean | no | False |
| `merge_duplicates` | boolean | no | False |
| `padding` | integer | no | 0 |
| `data_output` | string | no | _none_ |
| `data_format` | string | no | _none_ |
| `overwrite` | boolean | no | False |


### `export_tag_gif`

Export only the frames of a named animation tag as an animated GIF.

overwrite: Replace `output` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `tag` | string | yes |  |
| `output` | string | yes |  |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


### `export_tags`

Export each animation tag's frames to their own files.

output_pattern must contain "{tag}" (and usually "{frame}"),
e.g. "anim/{tag}_{frame}.png".

overwrite: Replace files the pattern would expand onto (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output_pattern` | string | yes |  |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


### `import_image`

Create an editable .aseprite sprite from a flat image (.png/.bmp/.jpg/...).

Args:
    input_image: Source raster image.
    output: Destination .aseprite path.
    overwrite: Replace `output` if it already exists (default False = no-clobber).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `input_image` | string | yes |  |
| `output` | string | yes |  |
| `overwrite` | boolean | no | False |


## Engine export presets

### `export_godot_spriteframes`

Export a sprite as a Godot 4 ``SpriteFrames`` resource (.tres) + a packed sheet.

Produces three files: a packed PNG sprite sheet, its JSON frame/tag metadata, and a
``SpriteFrames`` .tres that references the sheet via ``AtlasTexture`` regions, one
Godot animation per Aseprite tag (or a single ``default`` animation if untagged), with
per-frame timing taken from Aseprite frame durations.

v1 emits ``SpriteFrames`` only (no pivot/origin/hitbox/9-slice). Aseprite tag direction
isn't represented (Godot animations only loop or not); ``default_loop`` is applied to all.

Args:
    output: Destination .tres path (workspace-relative).
    sheet_output: Sheet PNG path. Defaults to ``<output stem>.png`` beside the .tres.
    scale: Integer upscaling factor for the sheet.
    texture_res_path: The ``res://`` path of the sheet inside your Godot project (the
        AtlasTexture atlas). Defaults to ``res://<sheet filename>`` (same-folder import).
    default_loop: ``loop`` flag for every generated animation (default True).
    overwrite: Replace existing outputs (default False = no-clobber). All three targets
        are validated up front, so nothing is written if any already exists.

Returns a ``workflow_manifest.v1`` manifest (kind ``engine_preset``).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | yes |  |
| `sheet_output` | string | no | _none_ |
| `scale` | integer | no | 1 |
| `texture_res_path` | string | no | _none_ |
| `default_loop` | boolean | no | True |
| `overwrite` | boolean | no | False |


### `export_slice_metadata`

Export every slice as engine-agnostic JSON (``aseprite_mcp.slice_metadata.v1``).

Each slice becomes ``{name, type, id, bounds, pivot, nine_slice, color, data,
raw_data}``. **Type detection:** a slice's user-data JSON ``type`` wins; otherwise the
name convention ``<type>:<id>`` (recognized types: hitbox, hurtbox, collision, interact,
pivot, origin, attach, spawn, nine_slice; anything else becomes ``"custom"``, never an
error). ``id`` comes from the data ``id`` or the name's ``:<id>`` suffix. ``nine_slice``
(Aseprite's 9-patch center) and ``pivot`` are emitted whenever the slice has them. Slice
user-data that is valid JSON is parsed into ``data``; the raw string is kept in ``raw_data``.

Args:
    output: Destination .json path. Defaults to ``<sprite>_slices.json`` beside the sprite.
    overwrite: Replace an existing file (default False = no-clobber).

Returns a ``workflow_manifest.v1`` manifest (kind ``engine_metadata``).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `output` | string | no | _none_ |
| `overwrite` | boolean | no | False |


## Minecraft resource packs

### `export_minecraft_texture`

Export a sprite into a resource pack at its correct texture path.

A single-frame sprite exports as a plain PNG. A multi-frame sprite exports as a
**vertical strip** (frame 1 on top, no padding) and gets a ``.png.mcmeta`` sidecar -
that pairing is what the game reads as an animation, and either half alone is broken.

Args:
    pack_root: The resource-pack directory (its ``assets/`` tree is written under this).
    namespace: Your mod/pack id. Defaults to "minecraft", which overrides vanilla.
    category: Texture subdirectory - block, item, entity, gui, particle, ...
    texture_name: In-pack texture name, ``/`` allowed for subdirectories. Defaults to
        the sprite's filename stem.
    frametime: Ticks per frame for the animation sidecar (1 tick = 50 ms).
    interpolate: Blend between animation frames.
    frame_order: Optional playback order (see ``write_texture_mcmeta``).
    overwrite: Replace existing files (default False = no-clobber).

Returns a ``workflow_manifest.v1`` manifest (kind ``minecraft_texture``).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `pack_root` | string | yes |  |
| `namespace` | string | no | minecraft |
| `category` | string | no | block |
| `texture_name` | string | no | _none_ |
| `frametime` | integer | no | 1 |
| `interpolate` | boolean | no | False |
| `frame_order` | array<any> | no | _none_ |
| `overwrite` | boolean | no | False |


### `validate_minecraft_texture`

Check a sprite against Minecraft's texture rules before it ships.

Always checks that frames are square and power-of-two. Optionally checks the declared
size, frame count and palette budget; if `tiling` is set, measures the wrap-around
seams of every frame; if `pack_root` is given, confirms an animated texture has its
``.png.mcmeta`` sidecar.

**The seam check** does not require the first and last columns to match - that is only
true of a texture with no variation, and would reject most real block art. It compares
the wrap transition against the texture's own interior column-to-column transitions and
reports the ratio, so a borderline verdict can be judged rather than taken on faith.
`warn_ratio` / `error_ratio` set where "suspect" and "seam" begin.

Returns a ``workflow_manifest.v1`` manifest (kind ``validation``) whose `validation`
block is ``{passed, checks, errors, warnings}``, plus per-frame seam measurements
under `tiling` when the seam check ran.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `category` | string | no | _none_ |
| `texture_size` | integer | no | _none_ |
| `tiling` | boolean | no | False |
| `expected_frames` | integer | no | _none_ |
| `max_palette_size` | integer | no | _none_ |
| `pack_root` | string | no | _none_ |
| `namespace` | string | no | minecraft |
| `texture_name` | string | no | _none_ |
| `warn_ratio` | number | no | 2.0 |
| `error_ratio` | number | no | 4.0 |


### `write_pack_mcmeta`

Write ``<pack_root>/pack.mcmeta`` - the file that makes a directory a resource pack.

Args:
    pack_root: Directory to become the pack root (created if needed).
    mc_version: A known Minecraft version (e.g. "1.21.1") to look the format up from.
        Defaults to 1.21.1.
    pack_format: The format number, overriding `mc_version`. Required for versions
        outside the known table - an unverified guess produces a pack the game
        rejects as incompatible, so it is refused rather than guessed.
    supported_min, supported_max: Optional inclusive `supported_formats` range,
        letting one pack load across several game versions.

Returns a ``workflow_manifest.v1`` manifest (kind ``minecraft_pack``).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `pack_root` | string | yes |  |
| `mc_version` | string | no | _none_ |
| `pack_format` | integer | no | _none_ |
| `description` | string | no | Generated by aseprite-mcp |
| `supported_min` | integer | no | _none_ |
| `supported_max` | integer | no | _none_ |
| `overwrite` | boolean | no | False |


### `write_texture_mcmeta`

Write the ``<texture>.png.mcmeta`` sidecar for an animated texture.

``export_minecraft_texture`` writes this automatically for a multi-frame sprite; use
this to add or repair one beside a PNG that already exists.

Args:
    texture_path: Path to the ``.png`` (the sidecar goes beside it, same name + .mcmeta).
    frametime: Ticks each frame is shown for (1 tick = 50 ms).
    interpolate: Blend between frames - smooth for gradients, blurry for pixel art.
    frame_order: Optional playback order: frame indices (0-based) or
        ``{"index": i, "time": t}`` objects to hold individual frames longer.
    frame_width, frame_height: Only for non-square frames, which the game otherwise
        infers from the strip's width.

Returns a ``workflow_manifest.v1`` manifest (kind ``minecraft_texture``).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `texture_path` | string | yes |  |
| `frametime` | integer | no | 1 |
| `interpolate` | boolean | no | False |
| `frame_order` | array<any> | no | _none_ |
| `frame_width` | integer | no | _none_ |
| `frame_height` | integer | no | _none_ |
| `overwrite` | boolean | no | False |


## Reference / rotoscope

### `add_reference_layer`

Add a dimmed, locked layer holding a reference image to trace over.

Args:
    image_file: The reference image/sprite.
    layer_name: Name for the new layer (default "reference").
    opacity: Layer opacity (0-255); dim it so your art stands out.
    scale_to_fit: Resize the reference to the canvas size (smooth).
    x, y: Placement when not scaling to fit.
    frame: Which existing frame to place the reference on (1-based). An
        out-of-range frame is rejected with the sprite's valid range.

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
(frames are created as needed, so `start_frame` may sit past the end). Draw your
animation on a layer above, then exclude this layer at export with
ignore_layer="<layer_name>".

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `images` | array<string> | yes |  |
| `layer_name` | string | no | rotoscope |
| `opacity` | integer | no | 128 |
| `scale_to_fit` | boolean | no | False |
| `start_frame` | integer | no | 1 |


## Workflows (high-level scaffolding)

### `create_character_sprite`

Scaffold a character sprite project: a transparent canvas with a tidy layer
stack (body + details), an auto-generated shading palette ramp from `base_color`,
and (optionally) an outlined placeholder body to draw over.

Returns a ``workflow_manifest.v1`` manifest (sprite summary, created files,
palette, and suggested next actions), plus `pixels_written` for the placeholder it
drew. With `with_placeholder=False` nothing is drawn and the field is absent.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `name` | string | yes |  |
| `width` | integer | no | 32 |
| `height` | integer | no | 32 |
| `base_color` | string | no | #3878c8 |
| `with_placeholder` | boolean | no | True |


### `create_icon_set`

Scaffold an icon set: a grid sheet with `count` icon cells, each a placeholder
inside a named slice (`icon_0`, `icon_1`, …) for easy atlas export.

Returns a ``workflow_manifest.v1`` manifest (kind "icon_set"); the per-icon regions
appear as slices under `sprite.slices`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `name` | string | yes |  |
| `icon_size` | integer | no | 16 |
| `count` | integer | no | 4 |
| `columns` | integer | no | _none_ |


### `create_rpg_item_sheet`

Scaffold an RPG item sheet: a grid sheet with one named slice per item
(default sword/shield/potion/coin/key/gem), each with a placeholder.

Returns a ``workflow_manifest.v1`` manifest (kind "rpg_item_sheet"); item regions
appear as slices (named after each item) under `sprite.slices`.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `name` | string | yes |  |
| `item_size` | integer | no | 16 |
| `items` | array<string> | no | _none_ |
| `columns` | integer | no | _none_ |


### `create_tileset_project`

Scaffold a tilemap project: a canvas sized columns×rows tiles, a tilemap layer,
and a starter tileset (grass/dirt/water/stone by default, or your own
[{"name","color"}] list). The grid is filled with the first tile to start.

Returns a ``workflow_manifest.v1`` manifest with a tilemap block mapping tile
names to their tileset indices.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `name` | string | yes |  |
| `tile_size` | integer | no | 16 |
| `columns` | integer | no | 4 |
| `rows` | integer | no | 4 |
| `tiles` | array<object> | no | _none_ |
| `overwrite` | boolean | no | False |


### `export_game_asset_bundle`

Export a sprite into a game-ready bundle directory: a flattened PNG, an animated
GIF, a packed sprite sheet (+ JSON data), a GIF per animation tag, and a
`manifest.json` describing everything.

Args:
    overwrite: Replace existing bundle files (default False = no-clobber). Every
        planned output is checked up front, so the bundle fails before writing any
        file if a target already exists.

Returns a ``workflow_manifest.v1`` manifest (the same object is also written to
disk as manifest.json inside the bundle).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `bundle_name` | string | no | _none_ |
| `scale` | integer | no | 1 |
| `overwrite` | boolean | no | False |


### `make_4_frame_idle_animation`

Turn a single-frame sprite into a 4-frame idle "bob" loop.

Duplicates frame 1 to 4 frames, nudges `layer` down by `bob_pixels` on frames 2
and 4 for a subtle bob, sets uniform durations, and adds a looping tag.

Returns a ``workflow_manifest.v1`` manifest (sprite summary + animation block).

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `layer` | string | no | body |
| `frame_duration_ms` | integer | no | 150 |
| `bob_pixels` | integer | no | 1 |
| `tag_name` | string | no | idle |


### `make_8_direction_walk_template`

Scaffold an 8-direction walk-cycle template on an existing sprite: enough frames
for `frames_per_direction` per direction, with one animation tag per direction
(N, NE, E, SE, S, SW, W, NW by default).

Args:
    frames_per_direction: 8 is the convention for a walk, and it is what this
        defaults to: contact, down, pass, up for each leg. 6 is the budget option and
        4 only reads as a walk mirrored on a side view, which an 8-direction sheet by
        definition is not. The default was 4 until this was fixed (#91), so a sprite
        scaffolded before then has half the frames a walk needs.
    frame_duration_ms: Set on every frame. Shape the timing afterwards with
        `apply_timing_curve`: a walk holds its contacts.
    directions: Override the eight compass tags.

Frames are placeholders to draw over. Returns a ``workflow_manifest.v1`` manifest
(kind "walk_template") with an animation block listing the directions/tags.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `frames_per_direction` | integer | no | 8 |
| `frame_duration_ms` | integer | no | 120 |
| `directions` | array<string> | no | _none_ |


### `scaffold_cycle`

Scaffold one animation cycle: its frames, a tag per phase, and a shaped timing curve.

`kind` is `walk`, `run`, `idle`, `attack`, `hurt` or `death`, and it settles the four
things a scaffolded animation otherwise gets wrong:

* **The frame count.** walk 8 (6 is the budget option, and 4 only reads as a walk
  mirrored on a side view), run 6, idle 4, attack 5, hurt 2, death 6. A count outside
  the kind's conventional range is accepted with a warning rather than refused.
* **A tag per phase, named for the pose rather than numbered.** An 8-frame walk gets
  `walk_contactL`, `walk_downL`, `walk_passL`, `walk_upL` and the same four for the
  right step, plus a `walk` tag over the whole cycle, so the frame you are drawing on
  says what it is meant to be.
* **Non-uniform durations from the start**, via `apply_timing_curve`: a cycle holds
  its extremes, an attack snaps through the strike, a hurt flashes and then holds the
  recovery, a death slows to a stop on a held last pose. Uniform timing is the
  placeholder every animation starts with and almost none should keep.
* **Loop versus one-shot.** An attack, a hurt and a death do not wrap, so every tag
  they get is written with `repeats=1` instead of being left at 0 ("play forever").
  That field is what `validate_loop` reads, so a one-shot tagged as a loop makes the
  checker report a duplicated seam frame on an animation that has no seam.

Frames are copies of frame 1, there to draw over. Nothing already in the sprite is
deleted, but Aseprite inserts a copied frame rather than appending it, so on a sprite
that already has several frames the new ones land at the front and the existing ones
end up at the end of the cycle; the manifest warns when that happens. Frames past the
cycle are left untagged and untimed, with a warning saying which.

Args:
    kind: walk | run | idle | attack | hurt | death.
    frames: Override the kind's default frame count.
    base_ms: The duration of a passing frame; every other duration is a multiple of
        it. Defaults per kind, because a run passes through its poses faster than an
        idle breathes.

Returns a ``workflow_manifest.v1`` manifest (kind ``animation_cycle``) whose
`animation` section lists every phase with the frame, tag, duration, timing role and
repeat count it ended up with, read back off the saved sprite rather than restated
from what was asked for.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `kind` | string | yes |  |
| `frames` | integer | no | _none_ |
| `base_ms` | integer | no | _none_ |


### `validate_sprite_for_game_export`

Check whether a sprite is game-ready against the criteria you specify.

Runs a series of checks: does the file open, do dimensions match (exactly or as
a tile multiple), is the colour mode allowed, are frame counts / required animation
tags present, is the background transparent, is the palette within budget, do
expected export files exist, and is sprite-sheet metadata readable, plus soft
warnings for oversized canvases, missing tags, and default/blank layer names.

All criteria are optional; only the ones you pass are enforced. Returns a
``workflow_manifest.v1`` manifest (kind "validation") with a `validation` section
`{passed, checks[], errors[], warnings[]}`. `validation.passed` is the verdict;
`ok` just means the check ran.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `expected_width` | integer | no | _none_ |
| `expected_height` | integer | no | _none_ |
| `tile_multiple` | integer | no | _none_ |
| `allowed_color_modes` | array<string> | no | _none_ |
| `min_frames` | integer | no | _none_ |
| `max_frames` | integer | no | _none_ |
| `required_tags` | array<string> | no | _none_ |
| `require_transparent_background` | boolean | no | False |
| `max_palette_size` | integer | no | _none_ |
| `expected_exports` | array<string> | no | _none_ |
| `spritesheet_data` | string | no | _none_ |


## Asset spec (declarative build)

### `build_asset_from_spec`

Build the asset described by an ``aseprite_mcp.asset_spec.v1`` document.

Executes the (validated) plan by dispatching each step to an existing tool: scaffolds
the sprite for its `kind`, applies palette / extra layers / animation frames+tags /
slices, and runs the requested exports. **Structure only - no pixels are drawn;** the
returned manifest's `suggested_next_actions` hand the actual art back to you.

Args:
    overwrite: Passed to the export steps (replace existing export files). The sprite
        itself is created no-clobber, so building over an existing ``<name>.aseprite``
        raises - build to a new name or remove the old file.

Returns a ``workflow_manifest.v1`` (kind ``asset_spec``) with the created files, the
executed `plan`, and next actions. Raises ``ValidationFailed`` if the spec is invalid.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `spec` | object | yes |  |
| `overwrite` | boolean | no | False |


### `plan_asset_spec`

Return the ordered build steps for an asset spec **without launching Aseprite**.

The pure dry-run: each step is ``{tool, args, purpose}`` naming the existing tool that
`build_asset_from_spec` would call. Returns a ``workflow_manifest.v1`` (kind
``asset_spec``) with the steps under `plan` and `dry_run=true`. If the spec is invalid,
returns the validation report instead.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `spec` | object | yes |  |


### `validate_asset_against_spec`

Does a built sprite actually match the spec it was built from.

The loop closer. `validate_asset_spec` asks whether a document is well formed and
`plan_asset_spec` asks what it would do; this asks the question that bites, which is
whether the artifact and the declaration agree.

That gap is where this project's worst bugs have lived. A figure shipped with no
keyline at all because the outline was drawn onto an empty layer, and every count in
the result reported success. Three ramps clipped to pure black and beat their own
outline while passing every check that existed. Nothing was comparing what was asked
for against what arrived.

**Structure only, like `build_asset_from_spec`:** canvas size, layer names, frame
count, tag names, slice names and palette capacity. The spec layer declares no pixels,
so this verifies no pixels; `assess_sprite` is where the drawing itself is judged.

Args:
    filename: The sprite to check. Defaults to the spec's own ``<name>.aseprite``,
        which is what `build_asset_from_spec` would have written.

Returns `ok`, the list of fields `checked`, and a `mismatches` list naming the
declared value, the observed one and what the difference means. `verifiable` is false
when the spec declares nothing this can check, so an empty result is never mistaken
for a passing one.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `spec` | object | yes |  |
| `filename` | string | no | _none_ |


### `validate_asset_spec`

Validate an ``aseprite_mcp.asset_spec.v1`` document (does the *spec* make sense?).

Checks the schema, kind, canvas, per-kind fields, palette, layers, animations
(`frame_count`, not `frames`), slices, export formats, and that the work the plan
would produce fits one build. `name` may already carry a `.aseprite`/`.ase`
extension: it is normalised, not doubled, so `hero` and `hero.aseprite` name the same
file. Returns a ``workflow_manifest.v1`` (kind ``asset_spec``) with a `validation` block
`{passed, checks, errors, warnings}`. This does **not** check a finished sprite against
the spec - that's a separate future tool.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `spec` | object | yes |  |


## Batch operations

### `apply_operations`

Apply a list of edit operations to a sprite in one atomic, single-process batch.

Each operation is `{"op": "<name>", "args": {...}}`. Ops run **in order against the
same open sprite**, so later ops see earlier ones (e.g. add a layer then draw on it).
Arguments not listed for an op are rejected rather than ignored.

Atomic: if any op fails the whole batch is rolled back and nothing is saved; the
error names the failing op index. `dry_run=True` validates the op list and returns
the plan **without launching Aseprite** (shape checks only; runtime issues like a
missing layer surface on a real run).

Frames are 1-based, and an `arg=frame` argument must name a frame that already
exists: an out-of-range frame is rejected with the sprite's valid range rather than
clamped, so a per-op `summary` always describes the frames actually touched.

Returns a `workflow_manifest.v1` (kind "batch") with a per-op `operations` list, and,
when the ops touched pixels, the same `pixels_written` / `pixels_outside_selection` /
`selection_applied` fields every other tool reports: a batch run under an active
selection is clipped to it, and these say how much the mask refused.

Operations and their arguments ('?' marks an optional argument):
  add_frame(duration_ms=int?, copy_from=frame?)
  add_layer(name=str, group=str?, opacity=int?, blend_mode=str?, visible=bool?)
  add_slice(name=str, x=int, y=int, width=int, height=int, color=color?)
  add_tag(name=str, from=frame, to=frame, direction=str?, color=color?, repeats=int?)  [also accepts from_frame for from, to_frame for to]
  clear_layer(layer=str?, frame=frame?)
  copy_cel(layer=str, from=frame, to=frame, to_layer=str?)  [also accepts from_frame for from, to_frame for to]
  delete_cel(layer=str, frame=frame)
  draw_ellipse(layer=str?, frame=frame?, cx=int, cy=int, rx=int, ry=int, color=color)
  draw_line(layer=str?, frame=frame?, x1=int, y1=int, x2=int, y2=int, color=color)
  draw_pixels(layer=str?, frame=frame?, pixels=list, color=color?)
  draw_rectangle(layer=str?, frame=frame?, x=int, y=int, width=int, height=int, color=color)
  duplicate_frame(frame=frame)
  fill_ellipse(layer=str?, frame=frame?, cx=int, cy=int, rx=int, ry=int, color=color)
  fill_layer(layer=str?, frame=frame?, color=color)
  fill_rectangle(layer=str?, frame=frame?, x=int, y=int, width=int, height=int, color=color)
  remove_frame(frame=frame)
  remove_layer(layer=str)
  remove_slice(name=str)
  remove_tag(name=str)
  rename_layer(layer=str, new_name=str)
  replace_color(layer=str?, frame=frame?, from=color, to=color, tolerance=int?)  [also accepts from_color for from, to_color for to]
  set_all_frame_durations(duration_ms=int)
  set_cel_opacity(layer=str, frame=frame, opacity=int)
  set_cel_position(layer=str, frame=frame, x=int, y=int)
  set_frame_duration(frame=frame, duration_ms=int)
  set_layer_opacity(layer=str, opacity=int)
  set_layer_visible(layer=str, visible=bool)
  set_pixel(layer=str?, frame=frame?, x=int, y=int, color=color)

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |
| `operations` | array<object> | yes |  |
| `dry_run` | boolean | no | False |


## GUI companion mode

### `gui_available`

Check whether the Aseprite GUI can be launched (executable resolvable).

_No parameters._


### `open_in_editor`

Open a sprite in the Aseprite GUI window (non-blocking) for live viewing.

The window stays open and runs independently of this server. Keep editing the
file with the other tools; Aseprite detects the on-disk change and prompts to
reload (or reloads automatically, depending on your Aseprite preferences), so
you can watch edits land without re-opening.

Returns the launched process id. To stop watching, just close the Aseprite
window yourself.

| Parameter | Type | Required | Default |
| --- | --- | --- | --- |
| `filename` | string | yes |  |


## Health & self-test

### `health_check`

Run a self-test of the server and its Aseprite integration.

Returns whether Aseprite was found, its version, the workspace, the number of
registered tools, and whether a real create-sprite plus export-PNG round-trip
succeeds. `ok` is True only if the round-trip works and the workspace is usable.

`workspace` is the **resolved** path, which is where files land and what every other
tool reports, because paths are canonicalised before the containment check that keeps
them inside the workspace. When the configured value spells the same directory
differently, which is what a junction or a symlink does, it is reported alongside as
`workspace_configured` with a note; the two are one place, not two.

_No parameters._

