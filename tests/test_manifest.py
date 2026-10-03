"""Pure-Python tests for the workflow manifest schema: no Aseprite (always run)."""

import json

import pytest

from aseprite_mcp.core import manifest as M

_REQUIRED_KEYS = {"ok", "schema_version", "kind", "created_files", "suggested_next_actions", "warnings"}


def test_manifest_has_required_keys():
    m = M.workflow_manifest("character_sprite")
    assert set(m) >= _REQUIRED_KEYS
    assert m["ok"] is True
    assert m["schema_version"] == "workflow_manifest.v1"
    assert m["kind"] == "character_sprite"
    assert m["created_files"] == [] and m["warnings"] == []
    assert m["suggested_next_actions"] == []


def test_optional_sections_omitted_when_empty():
    m = M.workflow_manifest("idle_animation")
    for optional in ("sprite", "exports", "palette", "animation", "tilemap"):
        assert optional not in m  # omitted, not present-as-null


def test_optional_sections_included_when_present():
    m = M.workflow_manifest(
        "tileset_project",
        tilemap={"layer": "tiles", "tile_width": 16, "tile_height": 16, "tiles": []},
        palette={"colors": ["#000000"], "count": 1},
    )
    assert m["tilemap"]["layer"] == "tiles"
    assert m["palette"]["count"] == 1


def test_file_and_export_entries_normalize_paths():
    from pathlib import Path

    fe = M.file_entry("source_sprite", Path("a") / "b.aseprite", "aseprite")
    assert isinstance(fe["path"], str) and fe["role"] == "source_sprite"
    ee = M.export_entry("spritesheet", Path("x.png"), "png", metadata_path=Path("x.json"))
    assert isinstance(ee["path"], str) and isinstance(ee["metadata_path"], str)


def test_export_entry_omits_metadata_when_absent():
    ee = M.export_entry("gif", "a.gif", "gif")
    assert "metadata_path" not in ee


def test_invalid_kind_and_role_error_clearly():
    with pytest.raises(ValueError, match="Invalid manifest kind"):
        M.workflow_manifest("not_a_kind")
    with pytest.raises(ValueError, match="Invalid created-file role"):
        M.file_entry("bogus", "p", "png")
    with pytest.raises(ValueError, match="Invalid export role"):
        M.export_entry("bogus", "p", "png")


def test_normalize_actions():
    assert M.normalize_actions(None) == []
    assert M.normalize_actions(["a", "b"]) == ["a", "b"]
    assert M.normalize_actions([1, 2]) == ["1", "2"]


def test_manifest_is_json_serializable():
    m = M.workflow_manifest(
        "game_asset_bundle",
        created_files=[M.file_entry("manifest", "m.json", "json")],
        exports=[M.export_entry("png", "a.png", "png")],
        suggested_next_actions=["go"],
    )
    s = json.dumps(m)
    assert json.loads(s)["kind"] == "game_asset_bundle"


def test_sprite_summary_shape():
    info = {
        "path": "x.aseprite", "width": 32, "height": 16, "colorMode": "rgb",
        "frameCount": 4, "layers": [{"name": "body"}, {"name": "details"}],
        "tags": [{"name": "idle", "from": 1, "to": 4, "aniDir": "forward"}],
    }
    s = M.sprite_summary(info)
    assert s["width"] == 32 and s["height"] == 16 and s["color_mode"] == "rgb"
    assert s["frames"] == 4 and s["layers"] == ["body", "details"]
    assert s["tags"][0]["name"] == "idle"
    assert s["slices"] == []  # absent -> consistently empty


def test_sprite_summary_includes_slices():
    info = {
        "width": 16, "height": 16, "colorMode": "rgb", "frameCount": 1,
        "layers": [{"name": "Layer 1"}], "tags": [],
        "slices": [{"name": "icon_0", "bounds": {"x": 0, "y": 0, "width": 8, "height": 8}}],
    }
    s = M.sprite_summary(info)
    assert s["slices"][0]["name"] == "icon_0"


def test_new_workflow_kinds_are_valid():
    for kind in ("icon_set", "walk_template", "rpg_item_sheet", "validation", "batch"):
        assert M.workflow_manifest(kind)["kind"] == kind


def test_batch_operations_and_dry_run_fields():
    ops = [{"index": 0, "op": "add_layer", "status": "planned", "summary": "add_layer(name=x)"}]
    m = M.workflow_manifest("batch", operations=ops, dry_run=True)
    assert m["operations"] == ops and m["dry_run"] is True
    m2 = M.workflow_manifest("batch", operations=[])
    assert m2["operations"] == [] and "dry_run" not in m2  # dry_run omitted when False


def test_every_manifest_kind_serializes():
    """Every VALID_KIND, populated with all optional sections, round-trips through JSON.

    Guards against a latent kind/section combination that can't be serialized.
    """
    sprite = M.sprite_summary({
        "path": "x.aseprite", "width": 16, "height": 16, "colorMode": "rgb",
        "frameCount": 2, "layers": [{"name": "body"}],
        "tags": [{"name": "idle", "from": 1, "to": 2, "aniDir": "forward"}],
        "slices": [{"name": "s", "bounds": {"x": 0, "y": 0, "width": 8, "height": 8}}],
    })
    for kind in M.VALID_KINDS:
        m = M.workflow_manifest(
            kind,
            sprite=sprite,
            created_files=[M.file_entry("source_sprite", "x.aseprite", "aseprite")],
            exports=[M.export_entry("spritesheet", "x.png", "png", metadata_path="x.json")],
            palette={"colors": ["#000000"], "count": 1},
            animation={"tag": "idle", "frames": [1, 2], "duration_ms": 120},
            tilemap={"layer": "tiles", "tile_width": 16, "tile_height": 16, "tiles": []},
            validation={"passed": True, "checks": [], "errors": [], "warnings": []},
            operations=[{"index": 0, "op": "add_layer", "status": "applied"}],
            dry_run=True,
            counters={"pixels_written": 3, "pixels_outside_selection": 1,
                      "selection_applied": True, "linked_frames_also_changed": [2, 3]},
            suggested_next_actions=["next"],
            warnings=["w"],
        )
        assert json.loads(json.dumps(m))["kind"] == kind


# ===== the harness's report, at the top level (#201) ==================================
#
# `apply_operations` ran its ops through the shared prelude, so a batch under a selection
# was clipped correctly, and then built its manifest from `operations` and `sprite` alone.
# Measured on a 16x8 canvas with the right half selected, one batched `replace_color`: the
# Lua result carried `pixels_written: 64, pixels_outside_selection: 64,
# selection_applied: true` and the manifest carried none of the three, so it said
# `status: applied` for an op whose every pixel the mask had refused.


def test_counters_land_at_the_top_level_not_in_a_section():
    """The decision #201 asked for, asserted rather than only written down."""
    m = M.workflow_manifest("batch", counters={"pixels_written": 64,
                                               "pixels_outside_selection": 64,
                                               "selection_applied": True})
    assert m["pixels_written"] == 64
    assert m["pixels_outside_selection"] == 64
    assert m["selection_applied"] is True
    assert "pixels" not in m, "the counters are top-level keys, not a `pixels` section"
    assert "counters" not in m, "`counters` is the argument name, never a manifest key"


def test_counters_are_absent_rather_than_zero():
    """The harness's own rule: a key that is there at all means there is something."""
    m = M.workflow_manifest("batch")
    for key in M.HARNESS_REPORT_KEYS:
        assert key not in m
    # And the same for a tool that passed a result which simply had nothing to report.
    m2 = M.workflow_manifest("batch", counters={"sprite": {}, "operations": []})
    for key in M.HARNESS_REPORT_KEYS:
        assert key not in m2


def test_counters_are_lifted_out_of_a_raw_result_and_nothing_else_is():
    """`counters=result` is how batch.py passes its raw Lua result straight in."""
    raw = {"sprite": {"width": 8}, "operations": [{"index": 0}],
           "pixels_written": 7, "selection_applied": True, "ok": "not mine"}
    m = M.workflow_manifest("batch", counters=raw)
    assert m["pixels_written"] == 7 and m["selection_applied"] is True
    assert "sprite" not in m and "operations" not in m  # only the harness keys are read
    assert m["ok"] is True  # and the manifest's own `ok` is not overwritten by one


def test_pixel_counters_merges_several_sub_calls():
    """A workflow tool is several launches, so what the call did is the total."""
    merged = M.pixel_counters(
        {"pixels_written": 221},
        {"pixels_written": 72, "pixels_outside_selection": 4, "selection_applied": True},
        None,
        {"linked_frames_also_changed": [3, 2]},
        {"linked_frames_also_changed": [2, 5]},
    )
    assert merged["pixels_written"] == 293
    assert merged["pixels_outside_selection"] == 4
    assert merged["selection_applied"] is True
    assert merged["linked_frames_also_changed"] == [2, 3, 5]  # union, sorted
    assert "pixels_clipped" not in merged and "pixels_skipped" not in merged


def test_pixel_counters_of_nothing_at_all_is_empty():
    assert M.pixel_counters() == {}
    assert M.pixel_counters(None, {}, {"ok": True}) == {}
    assert M.pixel_counters({"selection_applied": False}) == {}  # a false flag is nothing


def test_the_harness_report_is_the_same_set_tools_common_carries():
    """One definition in two places, pinned, because `core` must not import `tools`.

    `tools/common.py::_HARNESS_KEYS` is the same set for the same reason, minus
    `pixels_written`, which its two callers set by hand beside it. If either side grows a
    field the other does not, a manifest and a bare tool result stop agreeing about what
    "what this call did" means, which is the drift #201 was about.
    """
    from aseprite_mcp.tools.common import _HARNESS_KEYS

    assert set(M.HARNESS_REPORT_KEYS) == set(_HARNESS_KEYS) | {"pixels_written"}


def test_sprite_summary_carries_a_tags_repeat_count():
    """0 means forever and 1 is a one-shot; nothing else in a sprite says which."""
    info = {
        "width": 8, "height": 8, "colorMode": "rgb", "frameCount": 2,
        "layers": [{"name": "body"}],
        "tags": [{"name": "death", "from": 1, "to": 2, "aniDir": "forward", "repeats": 1},
                 {"name": "walk", "from": 1, "to": 2, "aniDir": "forward", "repeats": 0}],
    }
    by_name = {t["name"]: t for t in M.sprite_summary(info)["tags"]}
    assert by_name["death"]["repeats"] == 1
    assert by_name["walk"]["repeats"] == 0
    # An older info dict with no `repeats` reads as the file's default, "forever".
    legacy = M.sprite_summary({**info, "tags": [{"name": "t", "from": 1, "to": 1}]})
    assert legacy["tags"][0]["repeats"] == 0
