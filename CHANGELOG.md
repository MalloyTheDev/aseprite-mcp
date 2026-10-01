# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Indexed colour mode was unusable from either end.** An indexed pixel is an offset into
  a palette, and one offset, `transparentColor`, means "no pixel here" rather than a
  colour. Both the tool that created a palette and the tool that converted onto one were
  willing to answer a colour question with that offset, and neither said so.

  A sprite from `create_sprite(color_mode="indexed")` had a palette of 256 entries that
  were all opaque black. Every entry was therefore equidistant from every request, the
  first index won by being first, and index 0 is the transparent one: red, white and
  everything else resolved to "nothing is here", so every draw landed invisibly and
  reported the pixels it had written. A new indexed sprite now gets a 33-colour palette,
  a transparent entry at index 0 followed by the 32 colours Aseprite ships as its
  default, and a `background` colour the palette does not already hold is added to it so
  the background is the colour that was asked for rather than the nearest one available
  (#138).

  `set_color_mode(..., "indexed")` mapped the art against whatever palette the sprite was
  carrying, and a saved RGB sprite carries a single transparent entry. The art did not
  survive: every pixel pointed at that entry, the sprite read back empty, and the call
  returned ok. The conversion now quantizes the sprite's own colours into a palette first,
  across every frame, which is what the editor does; `palette_source="keep"` asks for the
  old behaviour, for a palette that was loaded or built on purpose (#137).

  `nearest_index` in the shared Lua prelude, which every drawing tool resolves colours
  through, no longer considers the transparent index or an entry whose own alpha is zero:
  neither can hold a visible pixel, so neither is an answer to "which colour is nearest",
  however near it is. It refuses outright, naming `add_palette_color` and `set_palette`,
  when the palette has nothing drawable at all. Tools that mean to write transparency are
  unaffected, since a request with zero alpha is answered with the transparent index
  before any nearest-match runs.

  `set_color_mode` now also **refuses** a conversion to indexed that would make drawn
  pixels disappear, names how many were at stake, and leaves the file on disk untouched.
  Losing colour accuracy is what indexed mode is for and still proceeds; losing pixels
  cannot be undone and was the whole of #137.

- **`set_color_mode` accepted any `dithering` string.** Aseprite takes
  `dithering = "no-such-dither"` without a word and converts with its default, so a
  misspelled algorithm reported success having done something other than what was asked.
  `dithering`, `palette_source` and `create_sprite`'s `color_mode` are now checked in
  Python, before a process is launched. `color_mode="rgba"` is refused rather than read as
  `"rgb"`: an RGB sprite here always has an alpha channel, so "rgba" is a guess about
  which of the three modes was meant, and `set_color_mode` already refused it.

- **Transparent pixels counted as drawn on indexed sprites.** The Lua prelude resolves an
  indexed pixel through `spr.transparentColor` before the palette, and `tools/inspect.py`
  had two local copies of that decode, neither of which did. On a sprite whose transparent
  index points at a palette entry that is itself opaque, every transparent pixel read back
  as that colour: `assess_sprite` reported an 8x8 sprite with nine drawn pixels as having
  all sixty-four, along with the canvas usage, bounding box, colour count and silhouette
  that follow from it, and `get_pixels` returned opaque colours for pixels that were not
  there, including in the `map` format whose whole purpose is to be readable at a glance.
  Both copies are gone; there is one decode now, the prelude's, which is what everything
  else already used. Found while designing `diff_sprites`, which has to pick one
  definition of transparent and would otherwise have disagreed with `assess_sprite`.

### Added
- **`diff_sprites`: compare two frames and say what changed.** An agent cannot look at
  its own sprite, and the gap that leaves is not "is this good" (`assess_sprite` answers
  that) but "did my last call do what I meant". Nothing here could answer it: the only way
  to tell an edit that landed from one that quietly went nowhere was to read both frames
  back as pixels and compare them by hand, 4096 at a time.

  The report is four counts that add up to the total, because "changed" on its own means
  several different things and they are different bugs. Pixels that *entered or left the
  silhouette* move the shape itself, and with it the collision box, the outline and the
  trimmed export box; pixels *repainted inside* it changed colour; pixels that changed
  *alpha alone* are an opacity or anti-aliasing change rather than a repaint. The issue
  asking for this proposed a single changed-pixel count, which would have reported a
  shading pass that ate the outline and a shading pass that worked as the same number.

  Nothing changed is the loudest result rather than the quietest, because an edit that
  went to the wrong layer, or was scoped by a selection nobody cleared, or was clipped off
  the canvas, looks exactly like an edit that was not needed. That case names the three
  usual causes in the order they are worth checking.

  A difference is never reported as a fault, since different is not wrong: pass `expect=`
  ("identical", "silhouette", "interior", "coverage", "mixed") and the measurement becomes
  a check with a pass or a fail, the way `ramp=` turns `assess_sprite` into a palette check.
  `layer=` compares one layer instead of the composite, which is the distinction that makes
  the tool useful at all, since every drawing tool writes to one layer and a composite can
  look unchanged while the layer under it was repainted. `other=` defaults to the sprite
  itself, so a frame-to-frame diff of one animation is the same call.

  It reads both frames in one Aseprite launch and never writes: the frames are rendered
  into scratch images, and a selection sidecar is deliberately not loaded, because a diff
  is a question about the whole frame. Different colour modes compare fine, so an indexed
  sprite can be checked against its RGB export. Finding the differences takes three
  narrowing passes rather than one scan, since almost no pixel in a frame changes: a native
  whole-frame comparison first, then one string comparison per row of the raw buffer, and
  only then per-pixel work on the rows that actually hold a difference. The per-pixel pass
  is the authority on what counts as changed, which matters because the cheaper tests
  disagree about pixels that are transparent in both frames, and a tool that trusted them
  would report "identical" and "47 pixels differ" in the same breath.

- **A tag can say how many times it plays, and frames can be reordered.** Three gaps in
  the frame and tag layer, each of which forced a workaround that damaged the sprite.
  `add_tag` and `set_tag` now take `repeats`, which Aseprite has always stored and nothing
  here could write: 0 means forever, which is how a cycle is marked in the file, and 1 is
  a one-shot such as an attack or a death. `get_sprite_info` reports it, and `validate_loop`
  already read it, so a sprite now answers for itself whether its frames wrap instead of
  having to be told. A negative count is refused rather than passed on, because Aseprite
  stores -1 as 0, which means the opposite of the one-shot that was asked for; and a range
  edit no longer turns a one-shot into a loop, which it did because changing a tag's range
  recreates it and a new tag starts at 0.
- **`reverse_frames` and `move_frame`.** Reversing a walk to get its mirror, or fixing an
  ordering mistake, previously meant re-authoring the frames. Aseprite has no command that
  moves a frame, so a move is expressed as two reversals of the block between the two
  positions: nothing is copied, which means cels on every layer, frame durations and cel
  links all travel with the frame. A gapped frame list is refused, because Aseprite
  reverses everything between the first and the last frame of a selection and would
  silently take in the frames nobody named. Both tools report which tags overlapped the
  frames they touched: tags mark positions rather than pictures, so a tag over reordered
  frames now covers different drawings, and naming them is more use than either quietly
  re-pointing them or refusing the edit. (141 tools.)
- **`ramp_between` and `ramp_from_art`.** Every shading tool takes a `ramp`, and the only
  way to get one was `generate_ramp`, which grows a ramp outward from a single base
  colour: reaching a particular shadow and a particular highlight meant guessing at
  `hue_shift` until the ends landed near what was wanted. `ramp_between` takes the ends
  directly and returns them exactly as given. The middle is interpolated in Oklab, because
  interpolating hue between distant colours is what turns a blue-to-cream ramp magenta in
  the middle: at that distance both ways round the wheel are equally short and neither is
  a blend. `ramp_from_art` recovers the ramp a sprite is already painted with, which
  `extract_palette` could not do because a set of colours is not a ramp: the colours are
  grouped by luminance, each band is represented by the colour most of its pixels use, and
  `coverage` says what share of the art each step carries. It says when the art is not a
  ramp at all, by looking for colours of the same brightness with very different hues,
  which is two materials sharing a sprite; spread *along* a ramp is not a signal, since a
  cool shadow to a warm highlight legitimately crosses half the wheel. (139 tools.)
- **`gradient_map`** - the tool that brings art onto a ramp at all. Every other shading
  tool starts from art that is already on one: `shift_along_ramp` moves pixels between
  steps they belong to, and `shade_region_by_light` shades a region painted in one of the
  ramp's colours. Nothing handled the common starting point, which is an imported image,
  a photo traced over, or a gradient fill with more colours than the palette wants. Each
  pixel's luminance now picks its step, darkest to lightest, so a 64-colour gradient comes
  out as exactly the five colours it was given and `assess_sprite` reports a palette
  conformance of 1.0. `contrast` stretches the mapping around mid-grey and `bias` shifts
  it, because the useful control is not which colours are used but how much of the art
  each step takes; `dither` resolves the fraction between two steps with an ordered
  pattern, which reads as a gradient without adding a colour. Alpha is carried through, so
  anti-aliased edges keep their coverage and the silhouette does not move.
- **`remove_stray_pixels`** - the noise `assess_sprite` counts, with something to do
  about it. A stray is a pixel with no neighbour of its own colour in any of the eight
  directions, which is what a shading pass leaves at a band boundary and what reads as
  dirt at sprite scale. Each one takes the most common colour among its opaque
  neighbours, so no colour that was not already there can appear, ramped art stays on its
  ramp, and the silhouette cannot move. A pixel whose only same-colour neighbour is
  diagonal is part of a dither and is left alone; `protect` names colours to keep, since
  a one-pixel specular is a stray by the definition and is meant to be there. This is not
  Aseprite's own Despeckle, a median filter which on a measured test added a colour, took
  the art off its ramp, and left *more* strays than it found. (136 tools.)
- **`assess_sprite`** - the quality metrics existed and nothing could reach them.
  `core/quality.py` has measured twelve things about a sprite since the hardening work,
  is unit-tested, and is how the shading tools prove they keep art on the palette; the
  only way to run it was a script. An agent could ask what a sprite *contains* and never
  whether it was any good. It now reports colours and ramps in use, painted pixels, noise
  (pixels with no neighbour of their own colour), jagged diagonals, the drawn box and how
  much of the canvas it fills, centring, silhouette asymmetry, palette conformance against
  a declared ramp, and optionally the tile seam per axis. Each measurement worth acting on
  comes back as a sentence naming the fault and the tool that fixes it, and clean art
  comes back with nothing to say, because a report that comments on every sprite is one
  nobody reads. The thresholds are relative to the art's own size: a raster circle is made
  of steps and is not told off for being round. (135 tools.)

### Changed
- **The showcase art is cleaned and the creature redrawn.** `assess_sprite` was pointed at
  every showcase image as its first real job and found stray pixels in all of them, so the
  generators now clear them: the item sheet went from 60 to 39, the creature from 13 to 6
  per frame, the skeleton from 27 to 8, and the tile scene from 2,912 to 978 by picking
  its colour variation per 2x2 block rather than per pixel, which is texture instead of
  static. The creature also grew its stalk in every facing rather than only when facing
  away, where it looked like something growing out of the back of its head, and lost the
  pale belly patch that sat under its eyes and read as a full mouth; it has a small mouth
  now instead.

## [0.8.1] - 2026-09-30

### Changed
- **The showcase art is redrawn and now reproducible.** The item sheet and the
  eight-direction sheet were from the earliest version of the server: the sword was a
  clipped diagonal, and the eight facings were green blobs with a red line for a nose.
  Both are redrawn with the current tools, along with the tilemap scene and the skeleton,
  each item carrying its own ramp so a potion's glass, liquid and cork shade independently.
  The generators live in `scripts/showcase/` and reproduce every committed image
  byte-for-byte, so the pictures that advertise a tool change when the tool does.

## [0.8.0] - 2026-09-30

The release that made the server usable by any MCP client and gave it an opinion about
pixel art. It moves to the mcp 2.x SDK, closes two defects that silently corrupted files,
adds four new domains (shading, selections, animation, Minecraft resource packs) and takes
the tool count from 96 to 134.

Two behaviour changes to know about: a filled ellipse is now the same shape as its own
outline, so every filled ellipse has different pixels, and concurrent calls to one sprite
are now serialized rather than racing.

### Added
- **`link_cels` / `unlink_cels`, and `get_cel` now reports links.** A linked cel is one
  image appearing on several frames: editing any of them edits all of them, and the file
  stores the image once instead of once per frame. It is in every Aseprite file and how a
  held pose is actually drawn, and none of it was reachable from here. `get_cel` answers
  with `linked` and `linked_with`, so a held pose is visible as what it is rather than as
  frames that happen to look alike; the frames are reported rather than Aseprite's image
  ids, which are assigned per open and would look like state a caller could keep.
  `link_cels` keeps the first listed frame's image and drops what the others were showing,
  which is what linking means, so it is marked destructive and says so in its own
  description. (134 tools.)
- **`draw_ellipse_in_box`** - there was no way to draw an even-diameter circle. Every
  ellipse came from a centre and radii, so it was always an odd 2*radius+1 across: a disc
  could not be centred on a 32x32 canvas, and a circle could not line up with an
  even-width rectangle. The new tool takes the same bounding box as `draw_rectangle` and
  fills it exactly. An even side is drawn the way it is by hand, as the odd ellipse one
  pixel smaller with its middle row or column repeated, and an odd box gives pixel for
  pixel what `draw_ellipse` gives, because the ellipse geometry is now one function that
  both forms place differently rather than two rasterisers that nearly agree. The shared
  geometry note every drawing tool carries used to document the gap; it now names the way
  round it. (132 tools.)
- **`apply_timing_curve`** - uniform frame durations are the placeholder every animation
  starts with, and `validate_loop` has been warning about them with nothing to point at.
  Now there is: `hold_extremes` holds the ends of a cycle two and a half times as long as
  the poses it passes through, `attack` lays out anticipation, a strike snapped through in
  20 to 40ms, a held impact and a recovery, `ease_in` and `ease_out` start or end slow, and
  `flat` puts everything back. Individual poses can be named in `hold_frames` and
  `snap_frames`. Every frame comes back with the role it was given, so the result explains
  itself. A hold is always a longer duration and never a duplicated frame, which would cost
  a frame, shift every tag index, and hide the repeat from the very check that looks for
  repeated frames; the returned `frames_added` is there to be asserted on. Because easing
  the durations on top of eased spacing is the same curve twice, the cels are measured on
  the way through and the call warns rather than quietly reading as slow motion.
  (131 tools.)
- **`offset_cels`** - move a drawn cel along a path across frames in one Aseprite launch,
  instead of one call and one launch per frame with every intermediate position worked out
  by the caller. Give it the frames and the whole movement; the cel on the first frame
  stays where it is and the last lands exactly on target. `ease` shapes the spacing
  (`linear`, `ease_in`, `ease_out`, `ease_in_out`, or `gravity`, which keeps horizontal
  speed even while the vertical accelerates), and `arc_height` bends the path into a jump.
  Because cel positions are whole pixels, it is the running position that is rounded and
  not each step, so the leftover carries forward: a 43px slide over nine steps comes out
  5, 5, 4, 5, 5, 5, 4, 5, 5 rather than the alternating 5, 4, 5, 5, 4 that reads as a limp,
  and no frame lands as much as a pixel from the ideal curve. The returned `deltas` are
  the spacing a viewer sees, which `validate_loop` can then measure in the file.
  (130 tools.)
- **`validate_loop`** - an animation can now be checked instead of eyeballed. It renders
  every frame once, in a single Aseprite launch, and reports per-frame hashes, content
  bounding boxes, centroids, the bottom row of the drawn content, the spacing series and
  the durations, then names the faults a still frame hides: a last frame identical to the
  first (the loop shows one image twice at the wrap), identical adjacent frames (a pose
  held by repeating a frame instead of lengthening one), uniform placeholder timing,
  spacing that wobbles rather than eases, a contact edge that moves, and frames with
  nothing drawn on them. Scope it to a tag or to one layer, so a character can be measured
  without the background it stands on. The verdict fails only on faults that are wrong
  whatever the animation is doing; a bouncing ball is meant to leave the ground, so that
  is reported and not failed. (129 tools.)
- **Minecraft resource-pack domain** (4 tools): `export_minecraft_texture`,
  `validate_minecraft_texture`, `write_pack_mcmeta`, `write_texture_mcmeta`, plus a
  matching asset-spec kind and seam validation in `core/minecraft.py`. (117 tools.)
- **Undeclared arguments are rejected**, at both the tool and the batch-op level. The
  schema layer validates the parameters a tool declares and silently drops the rest, so
  `create_sprite(colour_mode="indexed")`, when the parameter is `color_mode`, returned ok
  and an RGB sprite: a confidently wrong asset with no signal to correct against.
  Accepted names come from each function's own signature, so the check cannot drift.
- `ASEPRITE_MCP_TRANSPORT` selects `stdio` (default), `streamable-http`, or `sse`, so
  agents that cannot spawn a local process can reach the server. Read the warning in the
  README first: file access here is scoped by a workspace directory, not by an identity.
- `python -m aseprite_mcp` works, which several clients document in preference to the
  console script, and which avoids holding `Scripts/aseprite-mcp.exe` open (that lock
  blocks `uv sync` on Windows while the server is running).
- **Declarative asset spec** (`aseprite_mcp.asset_spec.v1`) — describe an asset in one
  document instead of orchestrating dozens of calls. Three tools: `validate_asset_spec`
  (is the spec valid?), `plan_asset_spec` (pure dry-run — the ordered steps a build would
  run, no Aseprite launched), and `build_asset_from_spec` (executes the plan via existing
  workflow/batch/export tools). Build is **structure only** — canvas, layers, frames, tags,
  slices, palette, and exports; it never draws pixels and hands the art back to the agent.
  Kinds: character, enemy, item_sheet, icon_set, tileset, walk_8dir. Pure schema/planner in
  `core/asset_spec.py`. (113 tools.)

### Fixed
- **A filled ellipse was a different shape from its own outline.** The same radii gave a
  disc that came to a one-pixel point at the pole and an outline with a five-pixel flat
  top, because the fill had its own per-row half-width formula while the outline was a
  midpoint ellipse. A filled circle therefore looked like a lemon, and `add_outline`
  around a filled disc did not reproduce `filled=False`. The fill is now the span between
  the edges the midpoint pass itself found, so the two are one shape rendered two ways,
  and `draw_ellipse_in_box` inherits it. **This changes the pixels of every filled
  ellipse**, including the placeholder in `create_character_sprite`: discs are rounder and
  slightly larger in area. Nothing in the suite depended on the old silhouette except one
  pixel count, which now counts the disc instead of remembering it.
- **One Aseprite integration test was running on CI, where there is no Aseprite.** The
  allowlist that decides which tests never need Aseprite was matched as a substring of the
  whole test id, so any test *function* whose name contained a listed module's name joined
  the always-run set: `test_animation.py::test_timing_never_touches_a_pixel` matched the
  entry for `tests/test_timing.py`. The match is on the module's own name now, which is
  what the list always meant.
- **The README's own tool catalogue was missing the same three domains the generated
  reference was.** Shading, selections and Minecraft resource packs had never been added
  to it by hand, so the front page listed 115 of 130 tools while claiming to be a
  catalogue. All four missing sections are there now (including the animation checks),
  and a test asserts every registered tool is named in `README.md`, the way one already
  asserts it for `docs/TOOLS.md`. The project layout in the README was two refactors
  behind and now describes `core/` and every tool module.
- **15 tools were missing from the tool reference.** `docs/TOOLS.md` is generated from
  the live registry and CI checks it is in sync, which looked like enough. It was not:
  only modules named in the generator's `GROUPS` list got a section and the rest were
  dropped in silence, so the header counted 128 tools while the file described 113, and
  `--check` compared that file against the same lossy output and passed. Shading,
  selections and the whole Minecraft domain were absent from the document an agent reads
  to find out what this server can do. All three are documented now; generation fails
  loudly when a tool module has no `GROUPS` entry; and tests assert the artifact itself
  covers every registered tool, so a missing entry cannot pass as up to date again. The
  README's tool count, which had drifted 11 behind, is now checked the same way.
- **Slice user-data could not carry structure.** `export_slice_metadata` derives a
  slice's `type` and `id` by parsing its `data`, so `{"type": "hitbox", "id": "body"}` is
  the shape worth sending, and it could not be sent: `add_slice` / `set_slice` declared
  `data: str`, while a client either sends structured user-data as an object or has a
  JSON-looking string parsed into one before the tool is reached. The value arrived as a
  dict and was refused by validation, or dropped before the call, leaving a slice with no
  data that exported as `type: "custom"` with a null `id`. A dict or list is now
  JSON-encoded before validation, so both forms work. The parameter still advertises a
  plain `string`, which keeps it usable by clients that require a concrete type.
- **Concurrent edits destroyed sprite files.** An Aseprite run is a read-modify-write
  over a whole sprite and nothing serialized those runs; all but one tool is sync, so
  FastMCP dispatches them through worker threads and a client that batches calls is
  enough to overlap them. Eight trials of two concurrent layer additions to one sprite:
  three kept only one edit, five left a file that no longer decoded, and all eight
  reported success. Invocations now hold a process-wide lock; the same trials keep both
  edits 8 of 8.
- **Caller text could forge the stdout result protocol.** Sentinels were a fixed prefix
  matched by line position, and the Lua escaper's `%c` class is byte-wise, so the UTF-8
  encodings of U+0085, U+2028 and U+2029 passed through raw while Python's `splitlines()`
  treats all three as line breaks. A layer name could therefore start a stdout line and
  claim to be a result or an error; the forged error was raised as the server's own, and
  since the name was saved first, the sprite stayed poisoned on every later call. The
  same trick forged a success. Sentinels are now per-run, framed with a nonce generated
  after the arguments are serialized, so a payload cannot name the token it would have to
  guess. Duplicate sentinels are refused rather than resolved by last-one-wins.
- **`run_cli` reported refused work as success.** Aseprite's CLI exits 0 for arguments it
  rejected, so a bogus flag or a missing input file raised nothing. Non-empty stderr now
  fails the call.
- **Exports no longer claim work they did not do.** The return dict echoed the requested
  value after the code had clamped it: `export_png(frame=99)` on a one-frame sprite
  returned `{"ok": true, "frame": 99}` having written frame 1, and `scale=0` returned
  scale 0 having used 1.
- A non-object Lua result is refused rather than handed to callers that index into it,
  and output truncation no longer keeps the partial first line, which could both hide a
  real sentinel and, at a computable offset, expose caller text as one.
- A non-executable `ASEPRITE_PATH` raises `AsepriteNotFoundError` instead of a bare
  `OSError`, and the Aseprite child gets `stdin=DEVNULL` so it cannot inherit the
  client's JSON-RPC stream.
- README no longer advertises a stale tool count.
- **No-clobber policy was not actually universal.** Six output-writing tools
  (`export_layer`, `export_layers`, `export_tags`, `export_frames`, `export_onion_skin`,
  `import_image`) resolved their destination with `resolve_path()` instead of
  `ensure_output_path()`, so they silently overwrote existing files while `SECURITY.md`
  and the README documented the opposite. All six now honour the policy and accept
  `overwrite=True`.
- **Server instructions described the pre-sandbox behaviour.** The `INSTRUCTIONS` string
  the agent reads still said absolute paths were "honoured as-is"; it now describes the
  sandbox and the no-clobber default.

### Security
- **Pattern exports are no-clobber too.** Aseprite expands `{frame}`/`{layer}`/`{tag}`
  patterns itself, so the concrete filenames aren't known up front. `ensure_output_pattern`
  refuses when anything the pattern could expand into already exists (literal text is
  glob-escaped, so a `[` in a filename can't cause a false conflict).
- **Canvas geometry is bounded.** `create_sprite` allowed 65535x65535 (~17 GB of pixels)
  and `resize_canvas` / `crop_sprite` / `scale_sprite` had no size validation at all.
  All four now go through `check_canvas_size`: 16384px per axis **and** 16,777,216 pixels
  of area, because two individually-legal axes can still be gigabytes. The `scale_sprite`
  `factor` path is checked inside Aseprite, where the source size is known, and rejects
  non-finite/non-positive factors up front.
- **Inline payloads are bounded.** `draw_image_base64` capped at 32 MB decoded (checked
  against the encoded length first, so an oversized payload is rejected without
  allocating the decode).
- **Text rasterization is budgeted while it renders.** `draw_text`'s 200,000-pixel cap
  previously fired *after* the coordinate list was fully materialized. With each source
  pixel becoming `scale**2` entries, the memory was already spent by the time the guard
  ran. The budget is now enforced during rasterization, and `scale`/`font_size` are
  capped at 64/512.
- **Timeouts can't be disabled.** `ASEPRITE_MCP_TIMEOUT` is clamped to 1-3600s; a
  negative, zero, NaN, or infinite value falls back to the default instead of making
  every call fail instantly or hang forever.
- **Executable resolution.** The `ASEPRITE_PATH` cache is keyed on the env var, so a
  change to it is no longer served a stale binary, and a path pointing at a *directory*
  is rejected with a message that says so.
- **Bounded process output, while it is read.** Aseprite's stdout/stderr are now drained
  into a bounded tail buffer (8M characters) by a reader thread per stream, replacing
  `subprocess.run(capture_output=True)`. Truncating after the fact could not prevent
  memory exhaustion, because `capture_output` accumulates the whole stream before it
  returns. The tail is what is kept, since the RESULT/ERROR sentinels are printed last.
- **Inline and source images are checked for declared dimensions.** A byte cap does not
  bound the raster: a solid-colour PNG compresses to a few hundred KB while declaring
  20000x20000, so it passes a 32 MB limit and then makes Aseprite allocate gigabytes.
  `stamp_file` and `draw_image_base64` now read the header with Pillow (no pixel decode)
  and enforce the canvas limits, converting Pillow's own bomb error into a typed one.
  Formats Pillow cannot identify, notably `.aseprite`, are passed through unchecked.
- **Sprite scaling accounts for every cel.** `SpriteSize` rescales each cel, so a legal
  target canvas still multiplies by the cel count: 100 full-frame cels of a 16x16 sprite
  scaled to 4096x4096 is ~1.7 Gpx, several GB of RGBA. The predicted aggregate is now
  bounded (`MAX_SPRITE_TOTAL_PIXELS`) before any of it is allocated.
- **The text budget counts plotted pixels, not the bounding box.** Folding `scale**2`
  into the glyph-box pre-check rejected a 7x7 box at scale 64 (200,704 > 200,000) even
  for a line of spaces that plots nothing. The bitmap allocation and the plotted-pixel
  budget are now separate limits.
- **Supply-chain hardening of CI** — GitHub Actions are now pinned to commit SHAs
  (`actions/checkout`, `astral-sh/setup-uv`) instead of mutable tags, and a
  `.github/dependabot.yml` keeps actions and Python deps (uv ecosystem) current via
  reviewed PRs (with version annotations). Future bumps are Dependabot PRs, not a manual
  floating-tag chore.
- **CodeQL** (`security-extended`) now scans `main`, every PR, and weekly on a schedule.

### Changed
- **Requires `mcp[cli]>=2.0.0`.** The 2.x SDK removed `mcp.server.fastmcp`: `FastMCP` is
  now `MCPServer`, `Image` moved to `mcp.server.mcpserver`, `Tool.inputSchema` became
  `input_schema`, and `call_tool` gained a `context` parameter and returns a
  `CallToolResult`. This is a breaking dependency change: an environment pinned to
  mcp 1.x will not import this version. Verified against mcp 2.2.0 with the full suite,
  including the real-Aseprite tier.
- **Ruff lint in CI.** The project had no linter; `ruff check` now runs on `src`, `tests`,
  and `scripts` across the whole Python matrix. The 89 findings from the first run are
  fixed, including three `raise ... from` chains that were swallowing the original
  exception and a `zip()` whose equal-length invariant is now explicit (`strict=True`).
  The formatter is deliberately **not** wired up: it would rewrite 49 files and bury
  behavioural changes in noise.
- **CI runs are cancelled when superseded** on pull requests (never on `main`), and the
  workflow can be dispatched manually.
- **`py.typed`** ships in the wheel, so the annotations are visible to consumers.

## [0.7.0] - 2026-06-13

First engine-ready export layer: take a sprite all the way to game-engine resources.

### Added
- **Godot 4 export preset** — `export_godot_spriteframes` exports a sprite as a Godot 4
  `SpriteFrames` resource (.tres) plus a packed sheet (+ JSON rects): one Godot animation
  per Aseprite tag (or a single `default` animation when untagged), each frame an
  `AtlasTexture` region, with per-frame timing derived from Aseprite frame durations. The
  pure builder lives in `core/engines/godot.py`. v1 is SpriteFrames only — no
  pivot/origin/hitbox/9-slice; tag direction isn't mapped (Godot animations only loop).
- **Slice metadata export** — `export_slice_metadata` writes engine-agnostic
  `<sprite>_slices.json` (schema `aseprite_mcp.slice_metadata.v1`): every slice as
  `{name, type, id, bounds, pivot, nine_slice, color, data, raw_data}`. Type comes from a
  slice's JSON `data` field (`{"type":...}`) or the `<type>:<id>` name convention (hitbox,
  hurtbox, collision, interact, pivot, origin, attach, spawn, nine_slice; unknown → `custom`,
  never an error). 9-slice center and pivot are emitted whenever present. Pure builder in
  `core/slice_metadata.py`. (Now 110 tools.)
- **Hypothesis property tests** for the security-critical pure boundaries: `to_lua`
  (no break-out of Lua string literals), colour parsing (valid normalize, arbitrary text
  never crashes, channels stay 0–255), and the path sandbox (relative paths never escape;
  absolutes rejected). `hypothesis` added as a dev-only dependency.
- `scripts/release_gate.py` — one command runs the whole local gate (lint → pure tests →
  integration → docs-sync → build), fail-fast, with `--skip-aseprite` to mirror CI.

### Security
- **Collection size limits (DoS guard).** Batch op-lists and explicit pixel/point/tile/
  colour lists are now capped; exceeding a cap raises `ValidationFailed` before any work
  begins, with a message saying how to split the request. Caps: 500 batch operations,
  65,536 pixels/points, 65,536 tiles, 256 palette colours (`core/limits.py`). No env
  override yet.
- Added `SECURITY.md` documenting the threat model, protections, and how to report issues.

### Changed
- **CI** now builds the wheel + sdist and tests on Python 3.10/3.11/3.12/3.13.
- Fixed post-core-split file paths in `README.md` / `CONTRIBUTING.md` (the `core/` layout).

## [0.6.1] - 2026-06-13

Safety hardening patch release. The default output behaviour is now no-clobber.

### Security
- **No-clobber output policy** — output-writing tools (`create_sprite`, `save_sprite_as`,
  `export_png`, `export_gif`, `export_spritesheet`, `export_game_asset_bundle`) now refuse
  to overwrite an existing file by default. Pass `overwrite=True` to replace one
  intentionally. Multi-file exports (sprite sheet + JSON, asset bundle) validate **every**
  planned output up front, so they fail before writing anything if any target already exists.
  Sprite saves raise `WorkspaceError` on conflict; exports raise `ExportError`.
- **CI least privilege** — the GitHub Actions workflow now runs with
  `permissions: contents: read`.

### Added
- Regression coverage for workspace **symlink-escape** (pure-Python `tests/test_output_paths.py`,
  always run; symlink cases skip where the OS can't create symlinks) and `--run-aseprite`
  overwrite tests (`tests/test_overwrite.py`).

## [0.6.0] - 2026-06-12

### Added
- **Atomic batch operations** — `apply_operations(filename, operations, dry_run)` applies a
  curated set of 21 mutating ops (layers, frames, tags, drawing, slices, `replace_color`) to
  one sprite in a **single Aseprite process**, inside one `app.transaction`: open once → run
  all ops → save only if every op succeeds. `dry_run=True` validates the op list with **zero**
  Aseprite launches. Any failure rolls back, saves nothing, and names the failing op index.
  Returns a `workflow_manifest.v1` (kind `batch`).

### Changed
- **Internal hardening (since v0.5.0):**
  - Typed error hierarchy — `AsepriteMCPError` base with `ConfigError`/`AsepriteNotFoundError`/
    `WorkspaceError`/`AsepriteTimeoutError`/`LuaToolError`/`AsepriteCLIError`/`ExportError`/
    `ValidationFailed`. `AsepriteError` kept as a backwards-compatible alias.
  - Typed value models (`Point`/`Size`/`Rect`/`Pixel`/`ColorSpec`/`LayerRef`/`FrameRef`/
    `FrameRange`/`SpritePath`) at the validation boundary; `parse_color` delegates to `ColorSpec`.
  - `core/` vs MCP-tool split — reusable logic now lives in `aseprite_mcp.core` (importable
    without the FastMCP app); backwards-compatible top-level import shims are preserved.

## [0.5.0] - 2026-06-12

### Added
- **Workflow pack 2** — three more high-level generators, each returning a
  `workflow_manifest.v1` that suggests a follow-up `validate_sprite_for_game_export` call:
  `create_icon_set` and `create_rpg_item_sheet` (grid sheets with a placeholder + a named
  slice per cell) and `make_8_direction_walk_template` (frames + one animation tag per
  direction). `sprite_summary` now reports `slices`.
- **Top-of-README showcase** — a three-tier gallery (Easy / Medium / Hard) demonstrating
  the create → animate → validate → export pipeline, with media generated entirely via the
  MCP tools (`docs/assets/showcase/`).

## [0.4.0] - 2026-06-12

### Added
- **`validate_sprite_for_game_export`** — a game-readiness validation workflow. Checks
  optional criteria (dimensions / tile multiples, colour mode, frame counts, required
  animation tags, transparent-background expectations, palette budget, expected export
  files, sprite-sheet metadata) and returns a `workflow_manifest.v1` (kind `validation`)
  with `{passed, checks, errors, warnings}`. The pipeline is now create → animate →
  validate → export. Pure decision logic lives in `tools/validation.py` (unit-tested in CI).

## [0.3.0] - 2026-06-12

### Added
- **High-level workflow tools** that scaffold whole assets in one call and return a
  structured manifest (files, paths, frames, tags, dimensions, suggested next actions):
  `create_character_sprite`, `make_4_frame_idle_animation`, `create_tileset_project`,
  and `export_game_asset_bundle`. They compose the existing low-level tools — deterministic
  scaffolding, no AI/model generation.
- A `--run-aseprite` pytest flag gating the integration & golden suites; pure-Python unit
  tests always run. Golden-output tests assert exact dimensions, pixel colours, frame/layer
  counts, tag metadata, and exported geometry. `scripts/gen_tool_docs.py --check` verifies
  the tool docs are in sync (now enforced in CI).

## [0.2.0] - 2026-06-12

### Added
- `health_check` self-test tool — reports whether Aseprite is found, its version, the
  workspace, the registered tool count, and a real create-sprite + export-PNG round-trip.
- Pure-Python unit tests (`parse_color`, `to_lua`, path sandbox) that run in CI **without**
  an Aseprite install, giving real coverage even where the integration suite skips.

### Changed
- **Security: file access is now sandboxed to the workspace by default.** Relative paths
  only; absolute paths and paths that escape the workspace via `..` are rejected unless
  `ASEPRITE_MCP_ALLOW_ABSOLUTE=1` is set. (Previously absolute paths were always honoured.)

### Docs
- Promoted the slime animation + sprite to the README hero; added a Security section.

## [0.1.0] - 2026-06-12

Initial release. **98 tools** driving Aseprite 1.3+ headlessly via batch Lua scripting
and the Aseprite CLI.

### Added

- **Core engine** — Python→Lua serialization, a shared Lua prelude (JSON encoder,
  colour/pixel helpers, deterministic drawing primitives, `sprite_info`), and a runner
  that parses sentinel JSON / errors from `aseprite -b`.
- **Sprite lifecycle** — create, save-as, colour-mode conversion, resize canvas, crop,
  scale, flatten, trim-to-content, background ↔ layer conversion.
- **Inspection** — structured `get_sprite_info`, `render_preview` (returns a PNG image),
  `get_pixels`, `list_sprites`.
- **Layers** — add, group, remove, rename, properties, reorder, duplicate, merge-down.
- **Frames & tags** — add/duplicate/remove frames, per-frame & uniform durations,
  animation tags (forward/reverse/pingpong).
- **Cels** — inspect, reposition, opacity, copy between frames, delete.
- **Drawing** — pixels, lines (with pixel-perfect & anti-aliased modes), polylines,
  Bézier curves, rectangles, ellipses (with anti-aliased fill), flood fill, fill/clear.
- **Brushes & symmetry** — custom ASCII-mask brushes, pattern tiling, layer mirroring,
  symmetric pixel plotting.
- **Effects** — linear/radial gradients (with dithering), checkerboard, outline,
  drop shadow, colour replace, invert, brightness/contrast, hue/saturation, desaturate.
- **Text** — render text with a built-in bitmap font or any TrueType font.
- **Tilemaps** — create tilemap layers, define/paint tiles, place/read the tile grid.
- **Palette** — get/set, edit/add/resize entries, load files, transparency, extract
  unique colours, sort (with indexed remap), generate hue-shifted ramps.
- **Slices** — named regions with optional 9-patch center, pivot, colour, and data.
- **Image stamping** — composite files or inline base64 images onto a layer.
- **Transforms** — flip and rotate the whole sprite.
- **Export** — PNG, animated GIF, per-tag GIF, sprite sheets (+ JSON metadata, layer/tag
  filters & splits), per-frame, per-layer, per-tag files, and onion-skin composites.
- **Reference / rotoscope** — dimmed locked reference layers and per-frame reference
  sequences.
- **GUI companion mode** — `open_in_editor` opens a sprite in the live Aseprite window
  (non-blocking) so headless edits can be watched via Aseprite's reload-on-change.

[0.8.1]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.8.1
[0.8.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.8.0
[0.7.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.7.0
[0.6.1]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.6.1
[0.6.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.5.0
[0.4.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.4.0
[0.3.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.1.0
