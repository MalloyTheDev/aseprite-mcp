# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[0.5.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.5.0
[0.4.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.4.0
[0.3.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.1.0
