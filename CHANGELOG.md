# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Godot export preset** — `export_godot_spriteframes` exports a sprite as a Godot 4
  `SpriteFrames` resource (.tres) plus a packed sheet (+ JSON rects): one Godot animation
  per Aseprite tag (or a single `default` animation when untagged), each frame an
  `AtlasTexture` region, with per-frame timing derived from Aseprite frame durations. The
  pure builder lives in `core/engines/godot.py`. v1 is SpriteFrames only — no
  pivot/origin/hitbox/9-slice; tag direction isn't mapped (Godot animations only loop).
  (109 tools.)

### Security
- **Collection size limits (DoS guard).** Batch op-lists and explicit pixel/point/tile/
  colour lists are now capped; exceeding a cap raises `ValidationFailed` before any work
  begins, with a message saying how to split the request. Caps: 500 batch operations,
  65,536 pixels/points, 65,536 tiles, 256 palette colours (`core/limits.py`). No env
  override yet.
- Added `SECURITY.md` documenting the threat model, protections, and how to report issues.

### Added
- **Hypothesis property tests** for the security-critical pure boundaries: `to_lua`
  (no break-out of Lua string literals), colour parsing (valid normalize, arbitrary text
  never crashes, channels stay 0–255), and the path sandbox (relative paths never escape;
  absolutes rejected). `hypothesis` added as a dev-only dependency.
- `scripts/release_gate.py` — one command runs the whole local gate (lint → pure tests →
  integration → docs-sync → build), fail-fast, with `--skip-aseprite` to mirror CI.

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

[0.6.1]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.6.1
[0.6.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.5.0
[0.4.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.4.0
[0.3.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/MalloyTheDev/aseprite-mcp/releases/tag/v0.1.0
