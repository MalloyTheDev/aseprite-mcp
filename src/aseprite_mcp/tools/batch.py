"""Batch operation runner: apply many edits to one sprite in a single Aseprite
process, atomically.

`apply_operations` validates the op list (pure Python), then, unless `dry_run`,
opens the sprite once, runs every op inside one `app.transaction`, and saves only if
all succeed. Any failure aborts the whole batch (rollback) and saves nothing. This
collapses multi-launch agent workflows (add layer -> draw -> add frame -> tag) into a
single, all-or-nothing call.
"""

from __future__ import annotations

import inspect
import json

from ..app import mcp
from ..core import oplib
from ..core.errors import strip_script_location
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
            f"{strip_script_location(info.get('error'))}; the sprite was not modified "
            "(rolled back)."
        )
    return None


def apply_operations(filename: str, operations: list[dict], dry_run: bool = False) -> dict:
    """Apply a list of edit operations to a sprite in one atomic, single-process batch.

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
        # Not one of ours (a failure outside the transaction, e.g. the sprite would not
        # open). Still caller-facing, so it gets the same path hygiene.
        cleaned = strip_script_location(str(exc))
        if cleaned != str(exc):
            raise LuaToolError(cleaned) from exc
        raise

    return workflow_manifest(
        "batch",
        sprite=sprite_summary(result["sprite"]),
        operations=result.get("operations", []),
        suggested_next_actions=[
            f"Validate it's game-ready: validate_sprite_for_game_export('{filename}').",
        ],
    )


# The op/argument table is generated from `oplib.OP_SPECS` and appended to the docstring
# *before* registration, so what MCP serves as this tool's description (and what
# docs/TOOLS.md renders) cannot drift from the registry the validator actually uses. The
# hand-written version listed 21 op names and no argument names at all, which left
# reading core/oplib.py as the only way to find out what an op takes.
#
# The base docstring is cleandoc'd before anything is appended, because how much
# indentation it still carries at this point depends on the interpreter: Python 3.13
# dedents docstrings at compile time and 3.12 does not. Matching the appended block to
# "the docstring's own level" therefore produces a different result per version, and
# docs/TOOLS.md is generated from this text, so the committed file was in sync on 3.12
# and out of sync on 3.13. Normalising first makes the result identical everywhere.
apply_operations.__doc__ = (
    f"{inspect.cleandoc(apply_operations.__doc__ or '').rstrip()}\n\n"
    "Operations and their arguments ('?' marks an optional argument):\n"
    # operations_reference() already indents its entries by two, so nothing is added
    # here. Indenting again is what produced the four-space entries the previous
    # version only avoided because cleandoc happened to strip the difference back off.
    f"{oplib.operations_reference()}\n"
)
apply_operations = mcp.tool()(apply_operations)
