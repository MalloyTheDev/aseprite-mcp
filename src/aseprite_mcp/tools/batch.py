"""Batch operation runner — apply many edits to one sprite in a single Aseprite
process, atomically.

`apply_operations` validates the op list (pure Python), then — unless `dry_run` —
opens the sprite once, runs every op inside one `app.transaction`, and saves only if
all succeed. Any failure aborts the whole batch (rollback) and saves nothing. This
collapses multi-launch agent workflows (add layer -> draw -> add frame -> tag) into a
single, all-or-nothing call.
"""

from __future__ import annotations

import json

from ..app import mcp
from ..core import oplib
from ..core.manifest import sprite_summary, workflow_manifest
from ..core.runner import LuaToolError, run_lua
from .common import lua_path, resolve_path


def _structured_batch_error(message: str) -> LuaToolError | None:
    """If a Lua failure carries our structured batch JSON, turn it into a clear error."""
    try:
        info = json.loads(message)
    except (ValueError, TypeError):
        return None
    if isinstance(info, dict) and "failed_op_index" in info:
        return LuaToolError(
            f"Batch aborted at op {info['failed_op_index']} ({info.get('failed_op')}): "
            f"{info.get('error')} — the sprite was not modified (rolled back)."
        )
    return None


@mcp.tool()
def apply_operations(filename: str, operations: list[dict], dry_run: bool = False) -> dict:
    """Apply a list of edit operations to a sprite in one atomic, single-process batch.

    Each operation is `{"op": "<name>", "args": {...}}`. Supported ops (v1):
    add_layer, rename_layer, set_layer_visible, set_layer_opacity, remove_layer,
    add_frame, duplicate_frame, set_frame_duration, add_tag, remove_tag, set_pixel,
    draw_line, draw_rectangle, fill_rectangle, draw_ellipse, fill_ellipse, fill_layer,
    clear_layer, add_slice, remove_slice, replace_color. Ops run **in order against the
    same open sprite**, so later ops see earlier ones (e.g. add a layer then draw on it).

    Atomic: if any op fails the whole batch is rolled back and nothing is saved; the
    error names the failing op index. `dry_run=True` validates the op list and returns
    the plan **without launching Aseprite** (shape checks only — runtime issues like a
    missing layer surface on a real run).

    Returns a `workflow_manifest.v1` (kind "batch") with a per-op `operations` list.
    """
    normalized = oplib.validate_operations(operations)  # raises ValidationFailed on bad shape

    if dry_run:
        return workflow_manifest(
            "batch",
            operations=[
                {"index": i, "op": op["op"], "status": "planned", "summary": oplib.summarize(op)}
                for i, op in enumerate(normalized)
            ],
            dry_run=True,
            suggested_next_actions=["Re-run with dry_run=false to apply these atomically."],
        )

    path = resolve_path(filename)
    try:
        result = run_lua(oplib.BATCH_LUA_BODY, {"src": lua_path(path), "operations": normalized})
    except LuaToolError as exc:
        structured = _structured_batch_error(str(exc))
        if structured is not None:
            raise structured from exc
        raise

    return workflow_manifest(
        "batch",
        sprite=sprite_summary(result["sprite"]),
        operations=result.get("operations", []),
        suggested_next_actions=[
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}').",
        ],
    )
