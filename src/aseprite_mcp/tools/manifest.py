"""Shared manifest schema for workflow tools — ``workflow_manifest.v1``.

Workflow tools (see ``workflow.py``) return a standardized manifest so the
asset-production layer can grow without every tool inventing its own result shape.
This module is pure-Python (no Aseprite, no MCP registration) and uses only stdlib
typing + small builder helpers — intentionally not a framework.

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
      "suggested_next_actions": [ "...", ... ],
      "warnings": []
    }
"""

from __future__ import annotations

from typing import Any, TypedDict

SCHEMA_VERSION = "workflow_manifest.v1"

VALID_KINDS = (
    "character_sprite",
    "idle_animation",
    "tileset_project",
    "game_asset_bundle",
    "validation",
)
FILE_ROLES = ("source_sprite", "preview_png", "image", "manifest")
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
    validation: dict
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
            {"name": t["name"], "from": t["from"], "to": t["to"], "aniDir": t.get("aniDir")}
            for t in info["tags"]
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
    suggested_next_actions: Any = None,
    warnings: list | None = None,
) -> WorkflowManifest:
    """Assemble a ``workflow_manifest.v1`` dict.

    Always includes ok/schema_version/kind/created_files/suggested_next_actions/warnings.
    Optional sections (sprite/exports/palette/animation/tilemap) are included only when
    non-empty, so empty sections are consistently omitted rather than left as null.
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
    return manifest
