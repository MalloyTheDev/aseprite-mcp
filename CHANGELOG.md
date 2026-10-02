# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`shade_region_by_light` and `specular_highlight` say where the region landed**
  (#183). `base_color` scopes a pass by colour *distance*, which is not the same as
  scoping it by material: art whose fills came from `generate_ramp` puts two materials
  closer together than the default `tolerance` of 24, because every step of a gold ramp
  is within 24 of a step of a brass one. Measured on two separated 12x12 squares,
  `#f2b632` and `#e0a33c` are 18 apart, so a pass scoped to the brass reshaded the gold
  as well and `region_pixels` could not say so: a count cannot tell one region from four.

  Both tools now return `region_components` and `region_bounds`. That same call comes
  back with 2 components and a box 44 pixels wide on a 48-pixel canvas; at
  `tolerance=1.0` it comes back with 1 component and the 12x12 square it was aimed at. It
  costs one flood fill over a mask that had already been built, written with an explicit
  stack rather than recursively because a region can be the whole canvas and Lua's C
  stack is not that deep. Worth reading on the specular in particular: its normals come
  from the *whole* region, so a glint scoped to a compound object lands wherever that
  object's mass bulges, which is how the showcase longsword got its only highlight on its
  leather grip and none on its blade.

- **`generate_ramp` always returns `distinct`, and warns when it clipped** (#184).
  Lightness is clamped at both ends, so a base near white or near black spends its
  outermost steps on one colour: `generate_ramp("#c2cde0", steps=9, hue_shift=-22,
  saturation_shift=-28, light_range=0.68)` returns nine entries whose top two are both
  `#ffffff`, and the old result carried `steps` and `colors` and no way to find that out.
  The ramp is still returned, because clamping is the honest result of those inputs and a
  caller may not care, but `warnings` now names which end collapsed and the nearest
  `light_range` that would not. A test takes the suggested value and checks it really
  does return nine distinct colours, because the suggestion is the actionable half and
  has to be true rather than plausible.

  Silence was expensive because the cost landed two tools later. `specular_highlight`
  needs the ramp's top step brighter than what `shade_region_by_light` spread over the
  lit side, so a ramp whose top two entries are both white makes the glint refuse with a
  message about the shading pass, several calls from the cause. `core/ramps.py` gains
  `clipped_ends`, `nearest_unclipped` and `clip_warning`, and the warning mentions
  speculars only when the *top* collapsed, since a ramp that lost steps to black or to
  rounding in the middle has a different problem. `nearest_unclipped` scans a grid rather
  than bisecting: distinctness is not monotonic in `light_range`, because too wide clamps
  the ends onto each other and too narrow rounds neighbours onto the same hex, so the
  answer can lie either side of what was asked for. Asking the question at all meant
  wrapping the ramp loop in a function of `light_range`, which had to leave the
  arithmetic byte for byte identical since the committed showcase art is generated from
  it; 18,150 input combinations were compared against the pre-patch code and every one
  matched.

- **`dither_band` reports `from_color` and `to_color`** (#186). `from_step` and `to_step`
  are 1-based, while the `ramp` passed beside them is a list indexed from 0, so the pair
  that dithers `ramp[3]` against `ramp[4]` is `from_step=4, to_step=5` and the two
  conventions sit one line apart in a script. All the tool validates is that the pair is
  adjacent, and an off-by-one still names an adjacent pair, so the call succeeded and
  dithered the wrong boundary with nothing in the result to catch it. The two colours are
  resolved in Python rather than in Lua, which is handed two colours already and cannot
  tell a deliberate pair from a mistake, and the docstring spells the collision out where
  it happens.

### Changed
- **`glow` and `cast_shadow` reuse their own effect layer across frames** (#185). The
  guarantee worth keeping is about a *cel*: two effects composited into one cel are a
  picture neither call describes. It was enforced on the *layer*, and a layer spans every
  frame, so the showcase's four-frame torch flicker needed `glow 1` through `glow 4`,
  each holding a single cel and empty on the other three, and a ten-frame effect would
  have needed ten. The layer stack then said nothing about the animation it belonged to.

  Both tools now write into a layer of the given name when they created it themselves and
  the target frame has no cel on it yet, which is how one layer carries a per-frame
  effect across a whole animation. The same layer *and* frame is still refused, as is a
  layer of that name holding artwork somebody else drew, and one that has since been
  moved out from under its subject, since `new_layer` is documented as sitting directly
  below `layer`. The mark identifying a layer as the tool's own goes in namespaced plugin
  data under `aseprite-mcp` rather than in `layer.data`: `data` is the User Data field
  the editor shows, and `set_properties` already treats the unnamed group as the
  caller's. The dungeon scene is 8 layers rather than 11 as a result, with one `halo`
  layer holding four cels, and its composite is byte for byte what it was, because the
  empty cels the old shape left on three layers per frame contributed nothing.

- **The showcase is a five-piece equipment sheet, a torch-lit room, and two pictures for
  capabilities that had none** (#180). The item sheet was four versions of one exercise,
  a heart, a coin, a potion and a sword, and nothing in the gallery showed the tools
  working together. `items.py` now draws a longsword, a kite shield, a great helm, a
  bronze key and a spell scroll: a long thin blade, a big flat painted face, a round
  shell, a part made of nothing but thin parts, and a matte non-metal. A showcase of one
  material shaded one way proves much less than it looks like it does. The silhouettes
  are typed out row by row, because the draft that derived them from curves produced a
  lumpy heart and an emboss that read as noise.

  `dungeon.py` is new, and is about what the tools do together rather than about one
  tool: 112 by 72 pixels, five ramps, four frames. Thirty-five wall blocks take their
  form from a single `shade_region_by_light` call, because the mortar joints make the
  mask thirty-five components and a distance field describes each one on its own. The
  light falls off in zones stepped down the surface's own ramp with `shift_along_ramp`, a
  rectangle per course so that every cut lands on a joint. The chest casts onto the floor
  layer and is clipped to it. The torch flickers over four frames with four durations,
  four leans and four silhouettes.

  `zorder.py` and `quantize.py` give `set_cel_z_index` and `quantize_palette` a picture
  each. The first swings a blade past a round shield, behind it on the approach and in
  front on the follow-through, with two layers that are never reordered, and it asserts
  the composited pixel at (45,20) is the shield's oak on one frame and the blade's steel
  on the next, because a z-index that round-trips through the file while changing nothing
  about the render would look identical. The second renders a dusk scene in 117 colours
  and then in 13 and in 5; its first draft produced three identical panels, because
  `quantize_palette` derives a palette and touches no pixel, exactly as its own warning
  says, and the `set_color_mode` that follows is what reduces the art.

  Nine generators now reproduce all twelve committed images byte for byte.
  `item_sheet.png` was recommitted along the way: three source pixels, two in the heart
  and one in the potion, moved from a shared cool grey to their own item's ramp colour
  because of the #177 stray-pixel fix, which is exactly the drift these scripts exist to
  catch.

- **Ten defects in that new art, found by reviewing it at 12x rather than at thumbnail
  size** (#187 to #196, all fixed). Nine of the ten were invisible at the size the README
  shows these images at and obvious at native scale on a checkerboard, and every one of
  them had passed the checks the generators already carried: the cell-colour census
  proved no colour crossed a cell and said nothing about whether the glint inside it was
  on the right object, and the falloff probe went on passing while the far wall was one
  tile repeated. An assertion covers the failure it was written for and no other.

  Three of them turned on the same realisation, that the answer was to stop handing a
  shape to a tool which describes a different kind of shape. The sword's blade is a prism
  and is painted as seven columns (a lit edge, a lit bevel, a dark groove, a shadowed
  bevel and a rim light), because `shade_region_by_light` gave it a soft gradient with no
  edge anywhere in it (#190). The scroll's sheet is flat paper in four column bands,
  because the pinched silhouette split the distance field into two lobes and put a blotch
  across the lower right that read as a water stain (#191). The torchlight is the masonry
  lifted up its own ramp, one `get_pixels` over the pool and one `draw_pixels` back,
  which the recorded run reports as 1,503 wall pixels lifted and none off-ramp; three
  drafts with `glow` all read as a sticker, because `glow` grows its rings from the
  subject's silhouette and paints at full opacity, so a tall flame gives a hard-edged egg
  and inside it the mortar joints disappear (#195). `glow` stays at `radius=3` for the
  heat right at the flame, which is the job it is good at.

  The rest, each with the measurement that caught it. Two of the four glints were on the
  wrong part, the sword's on its leather grip and the key's on the shadow side of its
  bow, both from scoping the highlight to a whole 40px cell; each is scoped to a
  rectangle holding one part now, and the key's hole is punched after the glint rather
  than before, because it had been taking the bow's own edge out of the eligible interior
  (#187). The generator's `hand_lit` helper takes a part's global top and bottom row,
  which is right for a slab and useless for anything that wraps: on the shield's rim it
  lit two pixels and left ninety at the flat fill colour, so the rim and the pommel gem
  use a new `edge_lit` that lights by the direction each pixel's edge faces, taken as the
  vector from the part's centre (#188). One set of finishing parameters was applied to
  five different surfaces, so `dither_band` on steel put a four-pixel checkerboard across
  the helm's 23px face and read as damage; it runs on the shield's paint alone now
  (#189). The five items shared no palette family and no optical weight, so the one-off
  mint pommel gem is gone, the ribbon's pink is a deep red used twice, and their centre
  lines agree within one row where the helm used to sit two rows high (#192). Uniform
  17px blocks gave identical distance fields, and three steps of falloff down a nine-step
  ramp clamped the darks together, leaving 8 of 24 sampled blocks pixel for pixel
  identical at 6 tones; widths cycle through (17, 11, 23, 14, 20) with a per-course phase
  and the ramps are thirteen steps, for 31 distinct patterns from 35 blocks with none
  under 4 tones (#193). The chest's lid seam survived on 10 of its 27 pixels because the
  straps and the lock were drawn over it, and `contact_shadow` had been handed an
  occluder colour that a later pass repainted, so it matched 3 pixels on the whole chest;
  the seam is 18 of 27 and the contact shadow darkens 102 wood pixels, both asserted
  (#194). The floor's courses grow taller and its stones wider down the frame, because
  four flat full-width rows read as a second wall lying down (#196).

  Both READMEs now point at the issues, and the paragraph claiming thirty-five domed
  blocks from one shading call is rewritten around what that claim cost.

### Fixed
- **A write whose selection masked out every pixel reported no counts at all** (#181).
  The result harness attaches the pixel counters under one gate, and `_px_masked` was
  read inside that gate without being part of it. A write that drew nothing left the
  other three counters at zero, so the whole block was skipped and
  `pixels_outside_selection` went with it: the call came back `ok: true` with
  `selection_applied: true` and no number anywhere, in the one case where the number is
  the entire answer. A mask that ate ten pixels is not an absence of pixels. One term
  added to the gate. The other half is pinned as well, that a write made with no
  selection still grows neither field, because not reporting a zero is the reason the
  gate is there at all.

- **The `.msk` selection sidecar outlived the sprite it belonged to** (#182). A selection
  is not stored in the .aseprite file, so it lives in a sidecar beside the sprite and is
  reloaded whenever that sprite is opened. `create_sprite(overwrite=True)` wrote a brand
  new sprite over an old one and left the old one's sidecar sitting beside it, so the new
  sprite opened carrying a selection from a sprite that no longer existed and every edit
  outside that rectangle was dropped. What eventually surfaced was "Nothing to shade: no
  pixel matched" from a later call, several steps from the cause and clean on a fresh
  workspace, which reads as nondeterminism rather than as a leftover file.
  `save_sprite_as` and `import_image` had the same hole.

  The suffix and the two helpers now live in `core/paths.py` with the rest of the path
  policy, because the selection tools that write the sidecar and the sprite tools that
  have to discard it need the same answer, and two modules guessing at the same suffix is
  how that stops being true. `create_sprite` reports `discarded_selection` when there was
  one to discard and says nothing when there was not. Deliberately not done by the
  exports: `with_suffix` maps `hero.png` and `hero.aseprite` onto one `hero.msk`, so an
  export doing this would throw away the selection of the sprite it was exporting. A
  sidecar that exists and cannot be removed raises rather than being swallowed, because
  handing back a new sprite still carrying an old one's selection is the failure, not the
  error about it. The test that matters is not the missing file but the next edit, which
  now writes all 256 pixels of a 16x16 fill.

### Added
- **Per-object metadata and a packed sheet exporter**, four capabilities the editor has
  had since 1.3 (#95, #94).

  `set_cel_z_index` reorders one cel against its layer's neighbours, which is the answer
  to a limb that is in front of the body on one frame and behind it on the next without
  restructuring the layer stack. `z` is an offset on the layer's own stack position and
  ties go to the larger value; the result reports the frame's competing cels back to
  front, because a number alone does not tell a caller that the arm moved. It is refused
  outside -32768 to 32767: the editor accepts a larger number in memory and then stores
  it in a 16-bit field, so saving and reopening turned 32768 into -32768 and 100000 into
  -31072. `get_cel` now reports `z_index` too.

  `set_properties` and `get_properties` reach the custom-property store that a sprite,
  layer, cel, tag, slice or tile carries inside the .aseprite file, with namespaces. Game
  metadata (a hitbox on a slice, an anchor on a layer, the damage frames of a tag) now
  travels with the art instead of in a sidecar the next edit desynchronises. Values keep
  their type. A selector the chosen target does not use is refused rather than ignored,
  since the write would otherwise land on a different object than the one named.
  Measured, and pinned both ways: a property lives on the record linked cels share, so a
  write to a held pose reaches every frame of it, while a z-index does not.

  `quantize_palette` derives a palette from the art and reduces it to a budget, the step
  between a picture and pixel art that `extract_palette` and `set_color_mode` leave open.
  `max_colors` is a ceiling with a cliff in it: four colours at `max_colors=4` come back
  as one averaged grey while `max_colors=5` returns all four, so the result reports what
  the art holds against what the palette can draw and warns when they disagree. It
  refuses an indexed sprite, where replacing the palette changes what every pixel means
  without touching one; measured, that corrupted the art and could leave pixels pointing
  past the end of the palette.

  `export_spritesheet_packed` exports through the editor's own command, a sibling of the
  proven CLI-based `export_spritesheet` rather than a replacement. It adds extrude (the
  one-pixel border duplication that fixes texture bleeding in a game engine),
  merge-duplicates, trim, padding, and a data file carrying the layer, tag and slice
  sections. A packed sheet merges duplicates whether or not the flag is set, and the
  result says so. An output extension the editor cannot encode writes nothing, raises
  nothing and returns success, so the written file is verified afterwards.

- **`docs/HEADLESS.md`**, a reference for designing a tool against `aseprite -b --script`,
  organised so an idea can be ruled out in one pass (#96). It covers the two `app.useTool`
  calls that take the process down, the calls that return success and do nothing, what is
  absent under `-b`, `app.preferences` and why nothing may write to it, and the region
  transforms reachable only as manual pixel work. Each constraint points at the code it
  forced, so the file explains why ramp shading is palette index arithmetic, why gradients
  are projected per pixel, and why `app.useTool` is never called anywhere in this server.

  Claims re-checked against Aseprite 1.3.18.6 are marked as such, and two were wrong:
  `Dialog` is not absent but a constructor that evaluates to `nil`, which a truthiness
  guard will not catch, and `app.site` is present and populated with only `app.site.editor`
  missing. The crashes and anything needing an `app.preferences` write were deliberately
  not reproduced, and the file says which claims those are and why.

- **`remove_stray_pixels` takes `erase_isolated`**, which erases a stray with no opaque
  neighbour instead of skipping it (#139). That stray is the dirt an effects pass leaves
  outside the art, which had no colour to take and so was the one kind of mess the tool
  could not clean, while `diff_sprites` was already reading it as scattered noise and
  naming this tool. Reported as `erased` and `erased_clusters`, apart from `replaced`,
  because erasing changes the silhouette, which is the one thing the tool otherwise never
  does; opt-in for the same reason, since a spark or a floating highlight is an isolated
  pixel that is meant to be there. `min_cluster` extends it to the two-pixel speck, where
  neither pixel is isolated because each has the other for company. Erasure is defined
  over clusters joined to each other and to nothing else, so it cannot reach the artwork
  at any setting.

### Changed
- **The Aseprite invocation lock is per sprite path rather than process-wide** (#66).
  Calls on different sprites run in parallel; calls on one sprite stay serialized, as do
  all CLI exports. Six parallel edits to six sprites measured 1.44s before and 0.44s
  after, with six parallel edits to one sprite still serialized.

  Paths are learned at `tools/common.lua_path`, the one seam every path headed for Lua
  passes through, rather than by reading argument names: ten different names are in use
  for paths, and a runner that sniffed them would claim nothing for a tool whose name it
  did not know, which looks exactly like a run that is correctly parallel. Anything the
  runner cannot account for still claims the whole editor, so the narrowing can only ever
  over-lock.

  Both spellings of a path separator count as unaccountable, not just the forward slash.
  Testing for "/" alone made the argument circular, since a path reaching Lua is
  forward-slashed only because it came through `lua_path`: a tool passing a raw
  `str(resolved_path)` would hand over a backslash string that was neither recorded nor
  path-shaped, and the claim would narrow around a file it was about to write. Nothing
  does that today, and an audit over a full integration run logged no narrowed claim that
  omitted a path-shaped value of either spelling, so the check costs nothing measurable
  and the property is enforced rather than conventional.

- **`trim_sprite` shares one measurement with `diff_sprites`** instead of scanning every
  pixel with `getPixel` (#172). Its answer is identical, pinned on the sprite from the
  issue before the change, and the scan is 5.2x cheaper over a 1024x1024 frame.

- **The tween's anchor and sample cap live where CI can test them** (#149). Both are
  arithmetic over the source cel's drawn bounds and both existed only in Lua, so a
  regression in either kept CI green and would have surfaced only in a `--run-aseprite`
  run, the tier CI does not run. The bounds are the editor's to measure and `tween_cels`
  is one Aseprite launch by design, so the authority now lives in `core/inbetween.py`
  with pure tests, the Lua carries a transcription, and a test holds the two together: a
  one-pixel error planted in the Lua anchor fails both of them.

- **The README tool catalogue is tested** (#155). Every name in a catalogue or workflow
  row is a registered tool, every registered tool has exactly one row, no row names
  nothing, and every tool count in the prose matches the registry; failures name the
  offending tool and the README line. The catalogue was already in sync, so this is a
  regression guard for the structural drift that a previous pass had to fix with a
  throwaway script. It replaces two weaker checks, one of which accepted a tool name
  anywhere in the document including prose, the other of which verified only the headline
  count and not the contents map that carries the same number.

- **The em dash check looks at files nobody has staged yet.** It listed tracked files
  only, so a new document carrying the character passed locally and would have failed
  only on CI, which is the one situation the check exists for.

### Fixed
- **A tween pivoted on a box measured by a different definition of empty than the count
  beside it** (#176). `Image:shrinkBounds` honours the sprite's transparent index only, so
  a pixel held in a palette entry that is itself transparent counted as content to it.
  Measured on an indexed sprite with art on rows 2 to 5 and one such pixel on row 13,
  `tween_cels` reported `source_bounds` of height 12 and put a bottom anchor at y=13,
  while `source_pixels` correctly said 16: a squash meant to keep a character's feet on
  the floor pivoted eight rows beneath them. `tween_cels` and both passes of
  `smear_frame` now measure with `visible_extent`, which is the definition the counts use.
  The two remaining `shrinkBounds` calls in that module are left alone on purpose, with
  the reasoning written where they are: one trims a cel being written, where a pixel in a
  transparent entry is real data that cropping would discard, and the other reports a
  single generous number rather than two that conflict.

- **`remove_stray_pixels` traded a two-colour speck instead of cleaning it** (#177). Each
  pixel of the speck is a stray whose only opaque neighbour is the other one, so the rule
  had each take the other's colour: `#ff00ff #00ff00` became `#00ff00 #ff00ff`, the pass
  reported two replacements having cleaned nothing, and a second pass traded them back, so
  the tool was not idempotent on its own output. A stray may now only take a colour from a
  pixel that is staying, so a speck with no staying neighbour is left exactly as it was and
  the count says zero. `erase_isolated` with `min_cluster=2` is the route that cleans it.
  A stray touching the artwork is unaffected, which a control test pins.

- **`diff_sprites` measured `drawn_pixels` and `content` by two different definitions of
  indexed transparency** (#172). The count treated both the sprite's transparent index and
  any palette entry whose own alpha is 0 as empty; the content box came from
  `Image:shrinkBounds`, which honours the transparent index only. On an 8x8 indexed sprite
  holding one pixel in a transparent palette entry that read `drawn_pixels: 4` beside a
  5x5 box whose corner nothing in the sprite could draw. Both now come from one prelude
  measurement, so they cannot disagree rather than merely agreeing today. RGB and
  grayscale results are unchanged.

- **`cast_shadow` on a background subject drew a confident wrong shadow.** A background is
  opaque and fills the canvas, so the measured subject box was the canvas itself. The issue
  reported this as a confusing `light_height` error, and that is the better case: measured
  on a 40x40 sprite with defaults the tool *succeeded*, casting an ellipse from the
  canvas's own outline and reporting `ok: true`. It is now refused with the reason a
  background cannot cast a shadow, naming `convert_background_to_layer` (#146).

- **`cast_shadow` says what the floor it clipped to actually is** (#146). A `ground_layer`
  is still consulted for its drawn pixels alone, which is the right question for a clip, so
  a hidden floor or one at a tenth opacity still catches a shadow; what is new is that the
  result carries `ground_layer`, `ground_layer_visible`, `ground_layer_opacity` and
  `ground_layer_hidden`, and `warnings` names whatever is switched off. Aseprite's
  visibility is per layer, so a floor inside a hidden group reported itself visible while
  nothing of it reached the picture; the check walks the enclosing groups for that reason.

- **A smear tapered against its subject's bounding box rather than its own width** (#150).
  The rule measured distance from the box's centre line, so a part of the shape far from
  the middle of the box lost its trail however wide it was. Measured on an L of a 4px bar
  and a 16px foot, moved down, the trail depth per column went from `0 1 2 2 | 3 4 5 6 6 5
  4 3 2 2 1 0` to `2 6 6 2 | 3 4 5 6 6 5 4 3 2 2 1 0`: one lens centred on the box before,
  two lenses after, each centred on its own part. The foot is identical in both, which is
  the sign the change is targeted rather than sweeping. A line's span is its lowest and
  highest opaque pixel, so a ring's trail still draws through its own hole, which is
  measured as unchanged rather than claimed.


### Changed
- **Removed every em dash from tracked content, and added the test that keeps it that
  way.** The project does not use U+2014, new work had respected that for a long time,
  and the tree still carried 121 of them across 43 files. That is not a cosmetic
  inconsistency: it is what made the rule unenforceable. A `git grep` over a dirty
  baseline reports the same hits on every run, so there was no way to tell a new
  violation from an old one, and the convention could only ever be upheld by whoever
  happened to remember it.

  Each occurrence was replaced with the punctuation that fits rather than with one
  substitute, because the character was doing three different jobs: separating a label
  from its description (now a colon, which is most of the CHANGELOG's feature rows),
  joining two independent clauses (a semicolon), and marking an appositive or an aside
  (a comma). Six sites needed rewording instead, where no single mark read properly.
  Released CHANGELOG sections are included: the punctuation changes, the record does not.

  `tests/test_style.py` now fails on any tracked file containing the character, naming
  every offender as `file:line` with its text, and it builds the character from its code
  point so the test is not itself the thing it forbids. `docs/TOOLS.md` is generated from
  docstrings, so the fix there was upstream in the docstrings; the test asserts that file
  is still tracked, because if it stopped being tracked a regression could land through
  the generator with nothing failing.

### Added
- **The shading tools now say when an indexed palette cannot hold the ramp they were
  given.** An indexed pixel is an offset into a palette, so a shading tool cannot write a
  colour the palette does not hold: `rgba_to_px` sends it through `nearest_index` and it
  lands on the nearest entry that can draw. That is what indexed mode means, and refusing
  it would make these tools unusable on exactly the sprites that most want a fixed
  palette, so this is a measurement and not a refusal.

  It needed saying because two of its consequences were invisible. A shade between two
  ramp steps that resolve to the same palette entry does nothing at all: measured on a
  sprite drawn in step 1 of a five step ramp against a palette holding three of those
  colours, `shift_along_ramp(steps=1)` reported 144 pixels written and left the picture
  byte for byte identical. And `palette_conformance` does not catch it, because the
  colour the pixel snapped to is still a colour on the declared ramp, so the one metric
  that separates shading from filtering read 1.0 for a no-op.

  Every tool that takes a `ramp` now returns `ramp_on_palette` on an indexed sprite: how
  many steps were declared, how many distinct palette entries they resolved to, how many
  were in the palette exactly, and the resolution of each step. Where steps merged, the
  `warnings` name which ones and which colour they merged into. `assess_sprite(ramp=...)`
  says it too, in its readings beside the conformance number it qualifies. Costs one
  `nearest_index` call per ramp entry rather than per pixel, so it is free at any sprite
  size, and it is measured through the sprite's own resolver so it cannot drift from
  where the pixels actually go.

  Attached by the Lua harness rather than by each of the nine tools, the way the pixel
  counts and the linked-cel report already are, with the judgement itself pure in
  `core.indexed.ramp_readings`. A meta-test pins every ramp-taking tool to the wrapper,
  because a tool that quietly used plain `run_lua` would be a tool whose shading bands on
  indexed art with nothing said. `smear_frame` is deliberately not covered: it resolves
  its ramp in Python into a colour-to-colour lookup table and passes no ramp to Lua, so
  the question for it is what that table's *targets* resolve to, which is a different
  measurement.

  Nothing is reported on RGB or grayscale sprites, where a pixel carries its own colour
  and there is no palette to snap to, and nothing is reported when the palette holds the
  ramp exactly, which is the normal case for a palette built with `generate_ramp` and
  `set_palette`.

  The indexed path through the shading layer was also completely untested: every test in
  `test_shading.py`, `test_lighting.py` and `test_effects_light.py` built an RGB sprite.
  It now has coverage, including the no-op above pinned as a test that would fail if the
  reading were ever dropped on the theory that conformance would catch it.

### Changed
- **`set_color_mode` no longer risks turning a large conversion into a timeout.** The
  tool counts every drawn pixel before and after a conversion to indexed, so it can
  refuse one that would make art disappear, and nothing bounded that scan but the
  invocation timeout. On the sprites this server is used on it is free; on a 4096x4096
  sheet of several frames it is tens of millions of pixels counted twice, and the only
  backstop was `ASEPRITE_MCP_TIMEOUT` turning a working conversion into a timeout with
  nothing useful in it.

  Past `MAX_VERIFY_PIXELS` (33,554,432, the canvas area times the frame count) the
  conversion now runs and reports `verified: false` with a reason naming the measurement
  and pointing at `diff_sprites`, instead of being refused. Refusing would have traded a
  rare slow call for a permanent gap in a capability, which is worse than the problem.
  Indexed targets now always carry `verified`, so the caller branches on a field rather
  than on whether `drawn_pixels` happens to be present.

  The count itself moved into the Lua prelude, where `diff_sprites` and `set_color_mode`
  share one implementation instead of carrying a loop each. The shared version reads
  alpha at a fixed byte stride out of `Image.bytes` rather than calling `getPixel` per
  pixel, measured at 0.088us per pixel against 0.58us, so the scan is about 6.6 times
  cheaper as well as bounded. Two implementations of one number were two chances to be
  wrong about indexed transparency, which has already shipped here once.

- **The pixel-loss refusal no longer guesses which palette was at fault.** It used to
  pick one of two remedies based on `palette_source`, and the `from_art` branch said
  "Unexpected with palette_source='from_art'" because no case reaching it was ever
  found: quantizing from the art is what stops pixels being lost. A message that has
  never run cannot be relied on to be right when it finally does, so both remedies are
  now offered and neither route is blamed.

### Fixed
- **Sorting a palette corrupted an indexed sprite that had linked cels.** `sort_palette`
  remaps every pixel through the same table it reorders the palette with, so the image
  looks identical afterwards. It did that by looping over `spr.cels` and assigning
  `cel.image`, and linked cels share one `CelData`: the shared image was therefore
  remapped once per linked frame. A four frame hold came back remapped four times, so
  index 1 became 2, then 0, then 3, then 1 again, and art drawn in the darkest colour of
  a four colour palette read back mid grey while the tool reported success and promised
  the picture was unchanged. The corruption scaled with the size of the link group, which
  is why a two frame hold looked almost right. Each distinct image is now collected
  before anything is written and remapped exactly once; the links are preserved, because
  every frame in a group shows the same drawing and all of them want the same remap.
  Found while looking into the linked-cel reporting below.
- **An edit to a linked cel said nothing about the frames it also changed.** Linked cels
  share one image, so `draw_pixels(..., frame=2)` on four linked frames changes all four.
  That is correct and is the point of linking: `link_cels` says "editing any of them
  edits all of them", and Aseprite itself paints every frame sharing a cel. What was
  wrong is that the result said `frame: 2, pixels_written: 1` and stopped there, so the
  only way to know four frames had moved was to have called `get_cel` first and thought
  about it. The frames an edit also reached are now reported as
  `linked_frames_also_changed`, attached by the same harness that reports the pixel
  counts, so all thirteen tools that commit an image say it without each one having to
  remember to.

  The first attempt at this broke the frame out of the group instead, on the reasoning
  that a call naming a frame means that frame. Two existing tests caught it, and they
  were right: one of them exists precisely to notice if linking ever quietly becomes
  copying. Propagation is the feature, silence was the defect, and only the silence is
  fixed.
- **A palette could hold a colour that can never be drawn, and said nothing.** An
  indexed pixel is an offset, and one offset means "no pixel here", so an opaque colour
  sitting at the sprite's transparent index is in the palette, is returned by
  `get_palette`, and resolves to its nearest *drawable* neighbour when anything asks for
  it. A ramp written darkest-first, which is the natural order, puts its darkest colour
  at index 0 and loses it: the shading comes out banded and every tool reports success.
  The six tools that write a palette (`set_palette`, `set_palette_color`,
  `add_palette_color`, `resize_palette`, `load_palette`, `sort_palette`) now report it,
  naming the entry, the index and `set_transparent_color`.

  A warning rather than a refusal, because an opaque entry at index 0 is perfectly
  reasonable for a sprite that never draws that colour. Nothing is said about RGB or
  grayscale sprites, where a pixel carries its own alpha and the transparent index means
  nothing, so the reading cannot be noise on the common case. And the transparent index
  is deliberately **not** moved to a transparent entry: that would reinterpret every
  existing index-0 pixel in the sprite as opaque, which is a worse and quieter kind of
  damage than the one being reported.


## [0.9.0] - 2026-10-01

The release that gave the server a way to check its own work. `diff_sprites` answers the
question the measuring tools could not, which is not "is this any good" but "did my last
call do what I meant": it compares two frames and splits the difference into pixels that
entered or left the silhouette, pixels repainted inside it, and pixels that changed only
their alpha, because those are three different bugs. Indexed colour mode became usable at
all, having previously accepted every draw and silently discarded it. The shading layer
reached the top of the ramp with `specular_highlight`, `cast_shadow` and `glow`, all built
from ramp steps rather than from alpha. And the animation layer learned to make the frames
between two poses, with `tween_cels` and `smear_frame`.

Tool count goes from 134 to 147.

**Three behaviour changes to know about**, which is why this is 0.9.0 and not 0.8.2.
`set_color_mode(..., "indexed")` now builds the palette from the art by default rather
than mapping onto whatever palette the file was carrying, and **refuses** a conversion
that would make drawn pixels disappear; the old mapping is still available as
`palette_source="keep"`. `create_sprite(color_mode="indexed")` now produces a usable
33-colour palette instead of 256 identical blacks. And `color_mode="rgba"`, an
undocumented alias that used to be accepted as RGB, is now refused, which matches what
`set_color_mode` already did.

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

- **A slice's user-data could be written but not read back.** `add_slice` and `set_slice`
  store `Slice.data`, and the whole point of sending it as `{"type": "hitbox", "id":
  "body"}` is that an engine reads a slice's type and id from it. Nothing reported it:
  `sprite_info` built each slice as `{name, bounds, center?, pivot?}` and dropped both
  `data` and `color`, and `list_slices` returns those entries, so it showed the same thing
  for a slice carrying structured data and a slice carrying nothing. The only way to see
  what a slice held was to write an export file and parse it, which is also why confirming
  the earlier slice-data fix was inconclusive the first time.

  `sprite_info` now reports `color` and, when it is not empty, `data` exactly as Aseprite
  stores it, so the string round-trips through `set_slice` unedited. `list_slices` adds
  `data_parsed` when that string is valid JSON, which is the shape worth sending; a slice
  with no user-data has neither field, so "set and forgot" and "never set" are
  distinguishable at last. Whether a string is a document is guessed in exactly one place,
  `core.slice_metadata.parse_user_data`, because an export and a readback describing the
  same slice differently is the failure worth preventing.

  That also removes a second slice reader. `export_slice_metadata` had a private Lua copy
  which was the only thing reporting a slice's colour and user-data, and it launched
  Aseprite a second time to use it, on top of the launch it already made for the sprite
  summary. Both now come from the shared serializer in one launch. Two copies of one
  reader drifting apart is exactly the bug fixed in the indexed-transparency decode a
  release ago.

- **`health_check` reported a workspace no other tool would ever return.** Paths are
  canonicalised before the containment check, which is what stops a junction from reaching
  outside the workspace, and it means every tool hands back a resolved path. `health_check`
  reported the configured value instead. On a machine where `Documents` is relocated behind
  a junction, which is a common way to move it off the system drive, the two differed by
  drive letter: `health_check` said `C:\Users\x\Documents\aseprite-mcp` while
  `create_sprite` said `F:\Users\x\Documents\aseprite-mcp`. They are one directory reached
  two ways, but two paths on different drives is also exactly what a sandbox escape looks
  like, and it cost real investigation time to rule that out, including checking whether a
  file had been written outside the workspace.

  `workspace` is now the resolved path, because that is where files land and what the other
  tools report, and the configured value appears beside it as `workspace_configured` with a
  note saying the two are the same place, only when they differ. The canonicalisation is
  stated in the tool's own description too, since that is where a caller looks first.
  `config.resolved_workspace` is now the single definition of where the workspace is, so
  the report and the containment check cannot drift apart about it.

  Fixed in passing: `health_check` read the workspace while building its result, so a
  workspace that could not be created raised out of the tool instead of being reported. The
  one tool whose job is to say what is wrong said nothing at all, and took every other check
  down with it. An unusable workspace is now a `workspace_error` field with `ok` false, and
  the rest of the self-test is still reported.

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
- **Python 3.14 is supported and tested.** `requires-python = ">=3.10"` has no upper
  bound, so it already admitted 3.14 while CI stopped at 3.13: the package told pip it
  worked on an interpreter the suite had never run on. 3.14 is now in the CI matrix,
  having been run against locally first, and the per-minor classifiers PyPI's sidebar and
  search filters read are present for the first time (they were absent entirely, leaving
  only `Programming Language :: Python :: 3`). A test ties the classifiers, the
  `requires-python` floor and the CI matrix together, because the defect was the two
  drifting apart rather than either value being wrong.
- **`tween_cels`: the three things an inbetween does that nothing here could do.**
  `offset_cels` moves a cel along a path, and that is one of four. The other three, a
  scale, a turn and a fade, had no tool: a ten-frame fade was ten `set_cel_opacity` calls,
  and a spinning coin was one `rotate_sprite` per frame on a scratch file, four Aseprite
  launches a frame. This writes every listed frame in one launch.

  It interpolates a **transform, not pixels**. Blending two drawings gives a double
  exposure, two silhouettes at half strength, which reads as a mistake rather than as
  motion, so there is one source drawing and every frame is that drawing resampled by its
  share of the change. Each frame samples the pristine original rather than the frame
  before it, so the rounding never compounds: reaching 40 degrees in eight frames and in
  two gives the same final cel, which is a test.

  Three decisions worth stating. The **anchor** is the point the transform holds still and
  it is read from the cel's own drawn bounds, so `anchor="bottom"` squashes onto the
  ground instead of near it, and `validate_loop`'s contact-edge check confirms the contact
  row did not move (it measures 0 drift). The vertical scale can be given separately, so a
  squash is wider as it is shorter, which is what makes a bouncing ball read as weight
  rather than as a zoom. And the fade sets the cel's own **opacity** rather than baking
  alpha, because a baked fade invents colours that are not on the palette, so a pure
  opacity tween leaves every frame's pixels byte-identical.

  Sampling is nearest-neighbour and copies the source pixel whole, so no colour appears
  that the drawing did not already contain and `palette_conformance` is unchanged across a
  quarter turn. The quarter turns are exact on purpose: `cos(radians(90))` is 6.1e-17, and
  sampling through that loses a row for no reason the caller could see. Rotation lands on
  whole degrees, and a frame sitting within 15 degrees of a quarter turn is reported in
  `warnings`, because nearest-neighbour sampling that shallow shuffles the edge pixels
  rather than turning the shape.

  What it refuses, rather than approximating: a from and to identical on every channel
  (each frame would be rewritten with the drawing the source already holds), a scale of
  zero, a group or tilemap layer, a source frame with no cel or nothing drawn on it, a
  frame whose transform lands entirely off the canvas, and **any frame that shares its
  image with another frame**. That last one is the sharp edge and it was measured rather
  than assumed: linked cels share one `CelData`, so the image, the position *and* the
  opacity are shared, and assigning to one of four linked cels changed all four. The
  refusal names the frames and points at `unlink_cels`. The generated cels are written
  through `newCel` and trimmed to their own content, so a cel's position stays a fact that
  `offset_cels` and `smear_frame` can read.

- **`smear_frame`: the piece of animation craft this server could not do at all.** Between
  two frames of a fast movement the eye expects a smear: one frame where the subject is
  drawn along its path, so the motion reads as speed rather than as teleportation.
  `stretch` elongates the subject back along the movement and thins it to a single pixel
  at the tip; `echo` draws it several times, each copy a step further down the ramp.

  **A smear made with alpha is a smear made of colours that are not in the palette.** Pass
  `ramp=` and every trail pixel is the nearest ramp entry to the subject's own colour
  there, stepped toward the dark end and clamped rather than wrapped, so
  `palette_conformance` stays at 1.0, which is the property every shading tool here holds
  to. Opacity remains the fallback when no ramp is given, and the result says in
  `warnings` that the fallback leaves the palette rather than letting that be discovered.

  The movement vector is **taken from the sprite** rather than restated by the caller: it
  is the shift between the centres of the drawn content on the two frames. The content
  box, not `cel.position`, because every tool here that writes a whole canvas back leaves
  the position at (0, 0) on every frame, and a position diff would read zero while the
  drawing plainly moved.

  A frame with no movement to smear is refused with both content boxes, rather than
  producing a blur of nothing, and so is a movement too short to smear at the given
  strength (it names the pixels and the length that would result). The subject is drawn
  last and comes back untouched, so the change is pixels entering the silhouette and
  nothing repainted inside it; only the named frame is written, which is why a linked cel
  is refused here too. `steps` is refused with `mode="stretch"` rather than silently
  ignored.

  The ramp matching lives in pure Python: the read pass returns the subject's distinct
  colours, Python matches them and builds a lookup table, and the generated Lua looks
  colours up without making a colour judgement. So there is one matcher with tests rather
  than a second one in Lua that nearly agrees with `shading.py`'s. (147 tools.)

- **The top end of the ramp: `specular_highlight`, and a second light for
  `shade_region_by_light`.** `shade_region_by_light` describes a form under one light and
  spreads the ramp's top step over the whole lit side, which is what a matte surface does
  and is why its output reads as plastic. Two things were missing above it.

  `specular_highlight` places the glint: a two or three pixel blob on the part of the form
  whose normal faces the *half-vector* between the light and the viewer, not the light
  itself. That offset toward the viewer is the whole difference between a specular and a
  brighter patch of diffuse, and it is why this is a tool rather than a larger `bias`.
  `size` is a pixel count rather than a radius, because a specular is two or three pixels
  and the point of the tool is that it stays that small; the pixels are grown outward from
  the brightest one so the result is one glint rather than dots scattered over every part
  of the form that happens to face the light. `tightness` is a threshold on that
  alignment, not an exponent: raising something to a power does not change the ranking, so
  an exponent would have been a parameter that did nothing.

  It will not touch an edge pixel. A glint on the silhouette's border reads as a hole
  punched in the form, so only pixels with all eight neighbours inside the region are
  candidates, and a region with no such pixel is refused with the same message
  `shade_region_by_light` already gives for a form too thin to shade. The two share their
  region mask, distance field and normals rather than computing them twice, because a
  specular derived from a slightly different normal field lands beside the highlight it is
  meant to sit inside.

  Two refusals are worth naming. A light that reflects nowhere on the form is refused with
  the best alignment the form actually offers, so the number to lower `tightness` to is in
  the error rather than a guess. And a glint painted in the colour that is already there
  is refused outright: shading with the full ramp leaves nothing above its top step, so
  the default workflow is to shade with the ramp minus its last entry and reserve that
  step, which the error says. Writing three pixels the colour they already were and
  reporting success would have been the no-op-that-looks-fine this project keeps finding.

  Its colour is the ramp's top step, so `palette_conformance` stays at 1.0. Metal is the
  one material whose specular is genuinely brighter than its own ramp, and
  `highlight_color` is the flag for it; the result reports `highlight_on_ramp` so a colour
  off the ramp is a stated trade rather than a silent conformance drop.

  `shade_region_by_light` also takes `fill_angle` and `fill_strength` now: a second,
  weaker light, which is how a shadow side stays readable instead of going flat at
  `ambient`. The two are summed and clamped rather than averaged, because averaging scales
  the key down as the fill comes up, so adding a fill light would have darkened the sprite
  overall and quietly cost it the ramp's top step. `fill_strength` is capped below 1: a
  fill matching the key puts the two terminators on opposite sides of one shape and adds
  up to the flat fill the shading was meant to replace. `per_step` in the result counts
  pixels per ramp entry, so "the fill lightened the shadow side" is a number rather than
  an impression. Omitting `fill_angle` leaves the output bit-identical to before.

- **`cast_shadow` and `glow`, both made of ramp steps rather than of alpha.**
  `add_drop_shadow` offsets a copy of the art and tints it, which is a sticker of the
  subject floating beside it, and `add_outline` gives one flat ring, which reads as a
  sticker too. Neither of the two effects every sprite eventually needs could be assembled
  from what was here.

  `cast_shadow` puts a shadow on a *surface*: away from the light, foreshortened by the
  light's height, an ellipse under the subject rather than a second silhouette. The
  direction is the opposite of `light_angle` and the length is the real cotangent of the
  light's elevation, so an overhead light casts straight down and a low one throws the
  shadow far to one side; the light's height moves the length and not the depth, since the
  depth is the floor's foreshortening and has nothing to do with the light. `ground_y`
  defaults to the subject's own contact row, the same measurement `validate_loop` reports
  as `contact_rows`, and `ground_layer` answers the other half of the geometry question:
  the shadow is clipped to that layer's pixels, so it cannot run off the edge of a
  platform and hang in the air, and a surface with nothing where the shadow falls is
  refused rather than drawn onto nothing. The core is the ramp's darkest step and each
  pixel of `softness` around it is one step lighter, so the penumbra is ramp entries
  arranged in space; `opacity` is the layer's, and the docstring says plainly that
  lowering it blends the shadow with the ground and takes the composite off the ramp.

  `glow` is several rings, each a step further down a ramp, hottest against the artwork.
  `falloff` chooses whether the steps are evenly spaced or drop away faster, which is the
  difference between a coloured border and something that reads as a light source, and
  `dither_edge` thins the outermost ring with an ordered pattern so the halo ends softly.
  That fade is in the coverage rather than in an alpha value, so every pixel it draws is
  still exactly a ramp entry and `palette_conformance` stays at 1.0. `base_color` scopes
  it, so a gem glows and the hand holding it does not; distance is measured out from those
  pixels but the glow is never painted over any part of the subject, so a body blocks its
  own gem's halo. The ring distances come from one chamfer pass over the inverted
  silhouette, which costs the same whatever the radius, where a neighbourhood scan per
  pixel would have been quadratic in it.

  Both write to their own layer below the subject, so the subject's cel is untouched and
  deleting one layer removes the effect, and both refuse a layer name that is already
  taken: `find_layer` resolves by name, so two layers called "glow" make every later call
  that names one ambiguous.

  `cast_shadow` also refuses a shadow it cannot rasterise. `ellipse_offsets` emits one
  Lua table per pixel of a filled ellipse's *area* and builds the whole list before
  anything is drawn, so that count is an allocation rather than a running time, and it is
  quadratic in radii that grow with both the subject's size and how low the light sits.
  On the widest canvas the geometry cap allows, a near-full-width subject under a low
  light asks for about 94 million points: an out-of-memory with nothing drawn, from
  arguments that are each individually valid, and invisible to any per-axis check for the
  same reason a dimension limit cannot see a 17 GB canvas. The count is now checked
  against `MAX_SHADOW_ELLIPSE_POINTS` before the rasteriser is called, the refusal names
  both radii and the remedy, and an accepted shadow reports `ellipse_points` so a caller
  can see how close it came. A penumbra longer than the ramp can express is refused the
  same way rather than stacking its outer rings onto the last entry and calling a flat
  band a soft edge.

  The shadow's geometry lives in `core/lighting.py` as pure arithmetic, where it is tested
  at four light angles with no editor, and is transcribed into Lua for drawing because
  only the editor knows the subject's drawn box. An integration test asserts the two
  agree on a real sprite, which is the only thing that keeps a formula in two places
  honest; the rounding in both is floor(v + 0.5) rather than Python's banker's rounding,
  which would otherwise have disagreed at a half pixel on even-width subjects. (145 tools.)

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
  would report "identical" and "47 pixels differ" in the same breath. (142 tools.)

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
  anti-aliased edges keep their coverage and the silhouette does not move. (137 tools.)
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
- **`assess_sprite`, `diff_sprites` and `get_selection` now advertise `readOnlyHint`.**
  All three write nothing, and none of them said so, which cost an approval prompt on
  exactly the tools an agent calls after every pass; approval fatigue is how a user ends
  up approving everything. `get_selection` was the sharper case: it matches the `get_*`
  prefix a client keyed on names rather than on annotations would auto-approve, so the
  gap is what made prefix matching look reasonable. A test now pins the direction that
  would actually hurt, a tool on that list which saves the caller's sprite, and it found
  `health_check` on its first run: that one does call `saveAs`, to a private temporary
  file it deletes again, so the exemption is written down with its reason and the test
  holds it to that reason.
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
- **Declarative asset spec** (`aseprite_mcp.asset_spec.v1`): describe an asset in one
  document instead of orchestrating dozens of calls. Three tools: `validate_asset_spec`
  (is the spec valid?), `plan_asset_spec` (pure dry-run: the ordered steps a build would
  run, no Aseprite launched), and `build_asset_from_spec` (executes the plan via existing
  workflow/batch/export tools). Build is **structure only**: canvas, layers, frames, tags,
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
- **Supply-chain hardening of CI**: GitHub Actions are now pinned to commit SHAs
  (`actions/checkout`, `astral-sh/setup-uv`) instead of mutable tags, and a
  `.github/dependabot.yml` keeps actions and Python deps (uv ecosystem) current via
  reviewed PRs (with version annotations). Future bumps are Dependabot PRs, not a manual
  floating-tag chore.
- **CodeQL** (`security-extended`) now scans `main`, every PR, and weekly on a schedule.

*The seven entries below were backfilled on 2026-10-01. They shipped in this release, in
PR #67, and were missing from the changelog entirely, which left `SECURITY.md` as their
only record: four of them sat labelled "(unreleased)" there through two releases and
others were dated to a `v0.7.1` that was never published. The changelog is where a
version claim is supposed to be settled, so the omission is the root cause rather than a
cosmetic gap.*

- **A junction could disclose names from outside the workspace.** `list_sprites` walked
  the workspace with `rglob`, and an NTFS junction is not a symlink as far as Python is
  concerned: `is_symlink()` is False for one, so the walk went straight through it and
  reported filenames and byte sizes from wherever it pointed. Every directory is now
  re-checked with `realpath` before the walk descends into it, which also stops a
  junction aimed at `C:\` from enumerating the whole drive, and every file is re-checked
  too, because `is_file()` and `stat()` follow a file symlink pointing outside.
- **A failing read built directory trees.** `resolve()` created the parent directory of
  whatever it was handed, so reading `a/b/c/d/e/absent.png` left five directories behind
  whether or not the call then succeeded. A caller could build an arbitrary tree inside
  the workspace out of nothing but calls that failed. Creating the parent is now opt-in
  (`create_parent=True`), which the output helpers in `core.paths` pass and a read does
  not.
- **Windows path components that are not files.** Three spellings pass a containment
  check and then do not behave like the file the caller named, so each is now refused
  with a message saying why. A component ending in a space or a dot has it stripped by
  Windows, so the path reported back would not be the path on disk. A component
  containing `:` names an NTFS alternate data stream, which is invisible to every
  listing and export tool here. A reserved device name (`CON`, `PRN`, `AUX`, `NUL`,
  `CONIN$`, `CONOUT$`, `COM0`-`COM9`, `LPT0`-`LPT9`) talks to the device instead of
  creating a file: a write to `NUL` is discarded and reported as a success, which is
  silent data loss with a positive result. The check is on the component's *stem*,
  because whether `NUL.png` is device-mapped varies by Windows build. All three are
  gated on Windows, since each is a legal POSIX filename and refusing it there would
  decline work for no reason.
- **The default workspace could land inside the Python installation.** The default was
  `<repo>/workspace`, derived from `parents[3]` of `core/config.py`, which is the repo
  root only in a `src/` checkout. `pyproject.toml` ships an `aseprite-mcp` console
  script, so `uvx aseprite-mcp` is the normal setup for anyone who has not cloned the
  repository, and there the same arithmetic pointed at `<venv>/Lib/workspace` on Windows
  or `/usr/lib/python3.12/workspace` on POSIX. Sprites written there are invisible to
  the user at best and a bare `PermissionError` at worst. The sibling default is now used
  only when the layout is genuinely a checkout, and otherwise a per-user data directory
  is used (`%LOCALAPPDATA%`, `~/Library/Application Support`, or `$XDG_DATA_HOME`).
- **A null byte in a filename was rejected only by accident.** Through Python 3.12 an
  embedded NUL made `Path.resolve()` raise `ValueError`, so the sandbox failed closed as
  a side effect of the standard library. Python 3.13 resolves such a path without
  complaint, and the sandbox then returned it as accepted. A guard that holds only
  because of an implementation detail is not a guard, and this one had already stopped
  holding on the newest interpreter the project supports, so the byte is now rejected
  explicitly.
- **`ASEPRITE_MCP_ALLOW_ABSOLUTE` skipped canonicalisation.** The permissive branch
  returned the path without `.resolve()`, so a path still containing `..` segments was
  handed back and landed verbatim in manifests and in the directory creation below it.
  Opting out of the containment check is not the same as opting out of knowing where the
  file is; both branches canonicalise now.
- **An unusable workspace is a typed error.** A workspace directory that cannot be
  created raised a bare `PermissionError` with no remedy in it, which is how sprites
  ended up aimed at `site-packages` in the first place. It is a `WorkspaceError` naming
  the directory and `ASEPRITE_MCP_WORKSPACE`.

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
- **Godot 4 export preset**: `export_godot_spriteframes` exports a sprite as a Godot 4
  `SpriteFrames` resource (.tres) plus a packed sheet (+ JSON rects): one Godot animation
  per Aseprite tag (or a single `default` animation when untagged), each frame an
  `AtlasTexture` region, with per-frame timing derived from Aseprite frame durations. The
  pure builder lives in `core/engines/godot.py`. v1 is SpriteFrames only: no
  pivot/origin/hitbox/9-slice; tag direction isn't mapped (Godot animations only loop).
- **Slice metadata export**: `export_slice_metadata` writes engine-agnostic
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
- `scripts/release_gate.py`: one command runs the whole local gate (lint → pure tests →
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
- **No-clobber output policy**: output-writing tools (`create_sprite`, `save_sprite_as`,
  `export_png`, `export_gif`, `export_spritesheet`, `export_game_asset_bundle`) now refuse
  to overwrite an existing file by default. Pass `overwrite=True` to replace one
  intentionally. Multi-file exports (sprite sheet + JSON, asset bundle) validate **every**
  planned output up front, so they fail before writing anything if any target already exists.
  Sprite saves raise `WorkspaceError` on conflict; exports raise `ExportError`.
- **CI least privilege**: the GitHub Actions workflow now runs with
  `permissions: contents: read`.

### Added
- Regression coverage for workspace **symlink-escape** (pure-Python `tests/test_output_paths.py`,
  always run; symlink cases skip where the OS can't create symlinks) and `--run-aseprite`
  overwrite tests (`tests/test_overwrite.py`).

## [0.6.0] - 2026-06-12

### Added
- **Atomic batch operations**: `apply_operations(filename, operations, dry_run)` applies a
  curated set of 21 mutating ops (layers, frames, tags, drawing, slices, `replace_color`) to
  one sprite in a **single Aseprite process**, inside one `app.transaction`: open once → run
  all ops → save only if every op succeeds. `dry_run=True` validates the op list with **zero**
  Aseprite launches. Any failure rolls back, saves nothing, and names the failing op index.
  Returns a `workflow_manifest.v1` (kind `batch`).

### Changed
- **Internal hardening (since v0.5.0):**
  - Typed error hierarchy: `AsepriteMCPError` base with `ConfigError`/`AsepriteNotFoundError`/
    `WorkspaceError`/`AsepriteTimeoutError`/`LuaToolError`/`AsepriteCLIError`/`ExportError`/
    `ValidationFailed`. `AsepriteError` kept as a backwards-compatible alias.
  - Typed value models (`Point`/`Size`/`Rect`/`Pixel`/`ColorSpec`/`LayerRef`/`FrameRef`/
    `FrameRange`/`SpritePath`) at the validation boundary; `parse_color` delegates to `ColorSpec`.
  - `core/` vs MCP-tool split: reusable logic now lives in `aseprite_mcp.core` (importable
    without the FastMCP app); backwards-compatible top-level import shims are preserved.

## [0.5.0] - 2026-06-12

### Added
- **Workflow pack 2**: three more high-level generators, each returning a
  `workflow_manifest.v1` that suggests a follow-up `validate_sprite_for_game_export` call:
  `create_icon_set` and `create_rpg_item_sheet` (grid sheets with a placeholder + a named
  slice per cell) and `make_8_direction_walk_template` (frames + one animation tag per
  direction). `sprite_summary` now reports `slices`.
- **Top-of-README showcase**: a three-tier gallery (Easy / Medium / Hard) demonstrating
  the create → animate → validate → export pipeline, with media generated entirely via the
  MCP tools (`docs/assets/showcase/`).

## [0.4.0] - 2026-06-12

### Added
- **`validate_sprite_for_game_export`**: a game-readiness validation workflow. Checks
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
  and `export_game_asset_bundle`. They compose the existing low-level tools: deterministic
  scaffolding, no AI/model generation.
- A `--run-aseprite` pytest flag gating the integration & golden suites; pure-Python unit
  tests always run. Golden-output tests assert exact dimensions, pixel colours, frame/layer
  counts, tag metadata, and exported geometry. `scripts/gen_tool_docs.py --check` verifies
  the tool docs are in sync (now enforced in CI).

## [0.2.0] - 2026-06-12

### Added
- `health_check` self-test tool: reports whether Aseprite is found, its version, the
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

- **Core engine**: Python→Lua serialization, a shared Lua prelude (JSON encoder,
  colour/pixel helpers, deterministic drawing primitives, `sprite_info`), and a runner
  that parses sentinel JSON / errors from `aseprite -b`.
- **Sprite lifecycle**: create, save-as, colour-mode conversion, resize canvas, crop,
  scale, flatten, trim-to-content, background ↔ layer conversion.
- **Inspection**: structured `get_sprite_info`, `render_preview` (returns a PNG image),
  `get_pixels`, `list_sprites`.
- **Layers**: add, group, remove, rename, properties, reorder, duplicate, merge-down.
- **Frames & tags**: add/duplicate/remove frames, per-frame & uniform durations,
  animation tags (forward/reverse/pingpong).
- **Cels**: inspect, reposition, opacity, copy between frames, delete.
- **Drawing**: pixels, lines (with pixel-perfect & anti-aliased modes), polylines,
  Bézier curves, rectangles, ellipses (with anti-aliased fill), flood fill, fill/clear.
- **Brushes & symmetry**: custom ASCII-mask brushes, pattern tiling, layer mirroring,
  symmetric pixel plotting.
- **Effects**: linear/radial gradients (with dithering), checkerboard, outline,
  drop shadow, colour replace, invert, brightness/contrast, hue/saturation, desaturate.
- **Text**: render text with a built-in bitmap font or any TrueType font.
- **Tilemaps**: create tilemap layers, define/paint tiles, place/read the tile grid.
- **Palette**: get/set, edit/add/resize entries, load files, transparency, extract
  unique colours, sort (with indexed remap), generate hue-shifted ramps.
- **Slices**: named regions with optional 9-patch center, pivot, colour, and data.
- **Image stamping**: composite files or inline base64 images onto a layer.
- **Transforms**: flip and rotate the whole sprite.
- **Export**: PNG, animated GIF, per-tag GIF, sprite sheets (+ JSON metadata, layer/tag
  filters & splits), per-frame, per-layer, per-tag files, and onion-skin composites.
- **Reference / rotoscope**: dimmed locked reference layers and per-frame reference
  sequences.
- **GUI companion mode**: `open_in_editor` opens a sprite in the live Aseprite window
  (non-blocking) so headless edits can be watched via Aseprite's reload-on-change.

[0.9.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.9.0
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
