"""Shared manifest schema for workflow tools: ``workflow_manifest.v1``.

Workflow tools (see ``workflow.py``) return a standardized manifest so the
asset-production layer can grow without every tool inventing its own result shape.
This module is pure-Python (no Aseprite, no MCP registration) and uses only stdlib
typing + small builder helpers, intentionally not a framework.

Shape (always-present keys: ok, schema_version, kind, created_files,
suggested_next_actions, warnings; the rest are included only when relevant):

    {
      "ok": True,
      "schema_version": "workflow_manifest.v1",
      "kind": "character_sprite" | "idle_animation" | "tileset_project" | "game_asset_bundle",
      "sprite": { "path", "width", "height", "color_mode", "frames", "layers", "tags" },
      "created_files": [ { "role", "path", "format" }, ... ],
      "exports":       [ { "role", "path", "format", "metadata_path"? }, ... ],
      "palette":   { "colors": [...], "count": N },
      "animation": { "tag": "idle", "frames": [1,2,3,4], "duration_ms": 120 },
      "tilemap":   { "layer", "tile_width", "tile_height", "tiles": [...], "grid": {...} },
      "assessment": { "frames_total", "frames_assessed": [...], "defects": [...],
                      "observations": [...], "waived"?, "skipped"? },
      "pixels_written": N, "pixels_outside_selection": N, "selection_applied": True,
      "suggested_next_actions": [ "...", ... ],
      "warnings": []
    }
"""

from __future__ import annotations

from typing import Any, TypedDict

SCHEMA_VERSION = "workflow_manifest.v1"

# Where a manifest reports what it wrote: **at the top level**, beside `ok`, not in a
# `pixels` section of its own (#201).
#
# A manifest built from `operations` and `sprite` alone could say `status: applied` for a
# batch whose mask had refused every pixel of an op. Measured on a 16x8 canvas with the
# right half selected, one batched `replace_color`: the Lua result carried
# `pixels_written: 64, pixels_outside_selection: 64, selection_applied: true`, and the
# manifest carried none of the three.
#
# Both shapes were available and `WorkflowManifest` is `total=False`, so either is
# additive and `v1` stays `v1`. Top level, because:
#
#   * the sections of this manifest (`sprite`, `exports`, `palette`, `animation`,
#     `tilemap`, `validation`, `operations`) each describe the *product*. These fields are
#     a verdict on the *call*, which is why `ok` and `dry_run` are top level too;
#   * every other result in this server reports these fields at its top level, and
#     `tools/common.py::carry_harness_keys` exists specifically to put them there on a
#     result the Python side rebuilt. A manifest is that same situation. Nesting them here
#     would mean a client reading `pixels_outside_selection` needs one rule for the
#     workflow tools and another for everything else.
#
# Absent rather than zero, matching the harness in `core/luagen.py`: a key that is there
# at all means there is something to read. A tool that writes no pixels grows no `0` that
# reads as a claim about pixels.
#
# The set is the one `tools/common.py` already calls the harness's report, plus
# `pixels_written`, which that module's two callers set by hand. Repeated here rather than
# imported because `core` must not import `tools`;
# `test_manifest.py::test_the_harness_report_is_the_same_set_tools_common_carries` pins
# the two against each other so they cannot drift apart.
HARNESS_REPORT_KEYS = (
    "pixels_written",
    "pixels_clipped",
    "pixels_skipped",
    "pixels_outside_selection",
    "selection_applied",
    "linked_frames_also_changed",
)
# The ones that are counts and therefore add up across several sub-calls; the rest merge
# by their own rule in `pixel_counters`.
_COUNT_KEYS = (
    "pixels_written",
    "pixels_clipped",
    "pixels_skipped",
    "pixels_outside_selection",
)

VALID_KINDS = (
    "character_sprite",
    "idle_animation",
    "tileset_project",
    "game_asset_bundle",
    "validation",
    "icon_set",
    "walk_template",
    "rpg_item_sheet",
    "batch",
    "engine_preset",
    "engine_metadata",
    "asset_spec",
    "minecraft_pack",
    "minecraft_texture",
    "animation_cycle",
)
FILE_ROLES = ("source_sprite", "preview_png", "image", "manifest", "engine_resource", "metadata")
EXPORT_ROLES = ("spritesheet", "gif", "png", "tag_gif", "frames")


class FileEntry(TypedDict, total=False):
    role: str
    path: str
    format: str
    metadata_path: str


class WorkflowManifest(TypedDict, total=False):
    ok: bool
    schema_version: str
    kind: str
    sprite: dict
    created_files: list
    exports: list
    palette: dict
    animation: dict
    tilemap: dict
    tiling: dict
    assessment: dict
    validation: dict
    operations: list
    plan: list
    dry_run: bool
    # The harness's report, at the top level: see HARNESS_REPORT_KEYS above.
    pixels_written: int
    pixels_clipped: int
    pixels_skipped: int
    pixels_outside_selection: int
    selection_applied: bool
    linked_frames_also_changed: list
    suggested_next_actions: list
    warnings: list


def file_entry(role: str, path: Any, fmt: str) -> FileEntry:
    """A created-file entry (role must be one of FILE_ROLES). Path is stringified."""
    if role not in FILE_ROLES:
        raise ValueError(f"Invalid created-file role {role!r}; expected one of {FILE_ROLES}.")
    return {"role": role, "path": str(path), "format": fmt}


def export_entry(role: str, path: Any, fmt: str, metadata_path: Any = None) -> FileEntry:
    """An export entry (role must be one of EXPORT_ROLES). Paths are stringified."""
    if role not in EXPORT_ROLES:
        raise ValueError(f"Invalid export role {role!r}; expected one of {EXPORT_ROLES}.")
    entry: FileEntry = {"role": role, "path": str(path), "format": fmt}
    if metadata_path is not None:
        entry["metadata_path"] = str(metadata_path)
    return entry


def pixel_counters(*results: dict | None) -> dict:
    """The harness's report, lifted off one or more raw tool/Lua results and merged.

    A workflow tool is usually several sub-calls, each coming back with its own report, so
    what the *call* did is the total: counts add up, `selection_applied` is true if any
    pass was scoped, and the linked frames an edit also reached are the union.

    A key no result carried stays out of the answer entirely, which is the harness's own
    rule: absent means nothing to report, where `0` would be a claim.
    """
    merged: dict = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        for key in _COUNT_KEYS:
            if key in result:
                merged[key] = merged.get(key, 0) + int(result[key])
        if result.get("selection_applied"):
            merged["selection_applied"] = True
        also = result.get("linked_frames_also_changed")
        if also:
            merged["linked_frames_also_changed"] = sorted(
                {*merged.get("linked_frames_also_changed", ()), *also}
            )
    return merged


def sprite_summary(info: dict) -> dict:
    """Build the `sprite` block from a get_sprite_info / sprite_info result dict."""
    return {
        "path": info.get("path") or info.get("filename"),
        "width": info["width"],
        "height": info["height"],
        "color_mode": info["colorMode"],
        "frames": info["frameCount"],
        "layers": [layer["name"] for layer in info["layers"]],
        "tags": [
            # `repeats` is the file's own answer to whether these frames loop (0 means
            # forever, 1 is a one-shot such as an attack or a death) and nothing else in
            # the sprite says so, which is why `sprite_info` reports it and why a manifest
            # that dropped it could not tell a scaffolded cycle from a scaffolded one-shot.
            {"name": t["name"], "from": t["from"], "to": t["to"], "aniDir": t.get("aniDir"),
             "repeats": t.get("repeats", 0)}
            for t in info["tags"]
        ],
        "slices": [
            {"name": s["name"], "bounds": s["bounds"]} for s in info.get("slices", [])
        ],
    }


def normalize_actions(actions: Any) -> list[str]:
    """Coerce suggested-next-actions into a list of strings (None -> [])."""
    if not actions:
        return []
    return [str(a) for a in actions]


def workflow_manifest(
    kind: str,
    *,
    sprite: dict | None = None,
    created_files: list | None = None,
    exports: list | None = None,
    palette: dict | None = None,
    animation: dict | None = None,
    tilemap: dict | None = None,
    validation: dict | None = None,
    assessment: dict | None = None,
    operations: list | None = None,
    plan: list | None = None,
    dry_run: bool = False,
    counters: dict | None = None,
    suggested_next_actions: Any = None,
    warnings: list | None = None,
) -> WorkflowManifest:
    """Assemble a ``workflow_manifest.v1`` dict.

    Always includes ok/schema_version/kind/created_files/suggested_next_actions/warnings.
    Optional sections (sprite/exports/palette/animation/tilemap/validation/assessment)
    are included only when non-empty, so empty sections are consistently omitted rather
    than left as null.

    `counters` is the harness's report, and only the keys in HARNESS_REPORT_KEYS are read
    out of it: pass a raw Lua result, a sub-tool's result, or `pixel_counters(...)` over
    several of them. The fields land at the top level; see HARNESS_REPORT_KEYS for why.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"Invalid manifest kind {kind!r}; expected one of {VALID_KINDS}.")
    manifest: WorkflowManifest = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "created_files": list(created_files or []),
        "suggested_next_actions": normalize_actions(suggested_next_actions),
        "warnings": list(warnings or []),
    }
    # Before the sections, so what the call did sits next to `ok` rather than after the
    # description of what it produced.
    for key in HARNESS_REPORT_KEYS:
        if counters is not None and key in counters:
            manifest[key] = counters[key]  # type: ignore[literal-required]
    if sprite:
        manifest["sprite"] = sprite
    if exports:
        manifest["exports"] = exports
    if palette:
        manifest["palette"] = palette
    if animation:
        manifest["animation"] = animation
    if tilemap:
        manifest["tilemap"] = tilemap
    if validation:
        manifest["validation"] = validation
    if assessment:
        manifest["assessment"] = assessment
    if operations is not None:
        manifest["operations"] = operations
    if plan is not None:
        manifest["plan"] = plan
    if dry_run:
        manifest["dry_run"] = True
    return manifest
