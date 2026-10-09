"""Declarative asset-spec tools - describe an asset once, validate it, plan it, build it.

Three tools over the ``aseprite_mcp.asset_spec.v1`` schema (see ``core/asset_spec.py``):

  * ``validate_asset_spec`` - is the spec document valid? (pure; no Aseprite)
  * ``plan_asset_spec`` - the ordered steps a build would run (pure; no Aseprite)
  * ``build_asset_from_spec`` - execute the plan by dispatching to existing tools.

Build is **structure only**: it creates canvas/layers/frames/tags/slices/palette and runs
the requested exports, then hands drawing back to the agent. It never draws pixels and
never reimplements a scaffold - every step calls an existing workflow/batch/export tool.
"""

from __future__ import annotations

from pathlib import Path

from ..app import mcp
from ..core.asset_spec import (
    compare_to_built,
    plan_spec,
    sprite_filename,
    validate_spec,
)
from ..core.errors import ValidationFailed
from ..core.manifest import file_entry, sprite_summary, workflow_manifest
from . import (
    batch,
    export,
    export_presets,
    inspect,
    minecraft,
    palette,
    slices,
    sprite,
    workflow,
)

# Maps a plan step's tool name to the real callable it dispatches to.
_DISPATCH = {
    "create_sprite": sprite.create_sprite,
    "create_character_sprite": workflow.create_character_sprite,
    "make_8_direction_walk_template": workflow.make_8_direction_walk_template,
    "create_icon_set": workflow.create_icon_set,
    "create_rpg_item_sheet": workflow.create_rpg_item_sheet,
    "create_tileset_project": workflow.create_tileset_project,
    "set_palette": palette.set_palette,
    "apply_operations": batch.apply_operations,
    "add_slice": slices.add_slice,
    "export_godot_spriteframes": export_presets.export_godot_spriteframes,
    "export_slice_metadata": export_presets.export_slice_metadata,
    "export_gif": export.export_gif,
    "export_spritesheet": export.export_spritesheet,
    "export_png": export.export_png,
    "export_minecraft_texture": minecraft.export_minecraft_texture,
}


@mcp.tool()
def validate_asset_spec(spec: dict) -> dict:
    """Validate an ``aseprite_mcp.asset_spec.v1`` document (does the *spec* make sense?).

    Checks the schema, kind, canvas, per-kind fields, palette, layers, animations
    (`frame_count`, not `frames`), slices, export formats, and that the work the plan
    would produce fits one build. `name` may already carry a `.aseprite`/`.ase`
    extension: it is normalised, not doubled, so `hero` and `hero.aseprite` name the same
    file. Returns a ``workflow_manifest.v1`` (kind ``asset_spec``) with a `validation` block
    `{passed, checks, errors, warnings}`. This does **not** check a finished sprite against
    the spec - that's a separate future tool.
    """
    report = validate_spec(spec)
    actions = (
        ["Spec is valid - preview steps with plan_asset_spec(spec) or run build_asset_from_spec(spec)."]
        if report["passed"]
        else [f"Fix: {e}" for e in report["errors"]]
    )
    return workflow_manifest(
        "asset_spec",
        validation=report,
        warnings=report["warnings"],
        suggested_next_actions=actions,
    )


@mcp.tool()
def plan_asset_spec(spec: dict) -> dict:
    """Return the ordered build steps for an asset spec **without launching Aseprite**.

    The pure dry-run: each step is ``{tool, args, purpose}`` naming the existing tool that
    `build_asset_from_spec` would call. Returns a ``workflow_manifest.v1`` (kind
    ``asset_spec``) with the steps under `plan` and `dry_run=true`. If the spec is invalid,
    returns the validation report instead.
    """
    report = validate_spec(spec)
    if not report["passed"]:
        return workflow_manifest(
            "asset_spec", validation=report, warnings=report["warnings"],
            suggested_next_actions=[f"Fix: {e}" for e in report["errors"]],
        )
    steps = plan_spec(spec)
    return workflow_manifest(
        "asset_spec",
        plan=steps,
        dry_run=True,
        suggested_next_actions=[
            f"{len(steps)} step(s) planned. Run build_asset_from_spec(spec) to execute.",
            "No Aseprite was launched - this is a dry plan.",
        ],
    )


@mcp.tool()
def build_asset_from_spec(spec: dict, overwrite: bool = False) -> dict:
    """Build the asset described by an ``aseprite_mcp.asset_spec.v1`` document.

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
    """
    report = validate_spec(spec)
    if not report["passed"]:
        raise ValidationFailed("Invalid asset spec: " + "; ".join(report["errors"]))

    steps = plan_spec(spec)
    fname = sprite_filename(spec["name"])

    created: list[dict] = []
    for st in steps:
        func = _DISPATCH[st["tool"]]
        args = dict(st["args"])
        if st["tool"].startswith("export_"):
            args["overwrite"] = overwrite
            created.extend(_export_files(st["tool"], func(**args)))
        else:
            func(**args)

    info = inspect.get_sprite_info(fname)
    created.insert(0, file_entry("source_sprite", info["path"], "aseprite"))
    return workflow_manifest(
        "asset_spec",
        sprite=sprite_summary(info),
        created_files=created,
        plan=steps,
        suggested_next_actions=_build_next_actions(spec["kind"], fname),
    )


def _export_files(tool: str, result: dict) -> list[dict]:
    """Turn an export tool's result into created-file entries for the build manifest."""
    if tool == "export_godot_spriteframes":
        return [file_entry("engine_resource", result["created_files"][0]["path"], "tres")]
    if tool == "export_slice_metadata":
        return [file_entry("metadata", result["created_files"][0]["path"], "json")]
    if tool == "export_minecraft_texture":
        # Returns a manifest rather than a bare {output}: one call can produce both the
        # PNG and its .png.mcmeta sidecar, and dropping the sidecar from the build's
        # created-files list would hide half of what an animated texture needs.
        return list(result["created_files"])
    out = result["output"]
    return [file_entry("image", out, Path(out).suffix.lstrip(".") or "png")]


def _build_next_actions(kind: str, fname: str) -> list[str]:
    actions = ["Build created STRUCTURE only (no pixels) - draw the art next."]
    if kind in ("character", "enemy"):
        actions.append(f"Draw on the 'body'/'details' layers of {fname}, then render_preview('{fname}').")
    elif kind == "walk_8dir":
        actions.append(f"Draw each direction's walk frames under its tag in {fname}.")
    elif kind in ("icon_set", "item_sheet"):
        actions.append("Draw each cell inside its named slice (the placeholders are there to draw over).")
    elif kind == "tileset":
        actions.append("Paint tiles with paint_tile_pixels and lay them out with set_tiles.")
    elif kind == "minecraft":
        actions.append(
            f"Draw each frame of {fname} at texture resolution - every Aseprite frame "
            "becomes one row of the vertical strip the game animates."
        )
        actions.append(
            f"Before shipping, run validate_minecraft_texture('{fname}', tiling=True) for a "
            "block texture: wrap-around seams are invisible in the editor and obvious on a wall."
        )
    actions.append("Re-run the export_* tools (overwrite=True) to regenerate engine files after editing.")
    return actions


@mcp.tool()
def validate_asset_against_spec(spec: dict, filename: str | None = None) -> dict:
    """Does a built sprite actually match the spec it was built from.

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
    """
    report = validate_spec(spec)
    if not report["passed"]:
        raise ValidationFailed("Invalid asset spec: " + "; ".join(report["errors"]))
    target = filename or sprite_filename(spec["name"])
    observed = inspect.get_sprite_info(target)
    result = compare_to_built(spec, observed)
    result["sprite"] = target
    if not result["verifiable"]:
        result["suggested_next_actions"] = [
            "This spec declares nothing structural to check: add canvas, layers, "
            "animations, slices or palette to make it verifiable.",
        ]
    elif not result["ok"]:
        result["suggested_next_actions"] = [
            f"{len(result['mismatches'])} mismatch(es) between the spec and the sprite.",
            "Rebuild with build_asset_from_spec, or correct the spec to match intent.",
        ]
    return result
