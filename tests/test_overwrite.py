"""Integration tests for the no-clobber overwrite policy — require Aseprite.

Run only under `pytest --run-aseprite`. Verify that output-writing tools refuse to
replace an existing file by default, that `overwrite=True` restores the old
replace-in-place behaviour, and that the multi-file bundle export fails before
writing anything when a target already exists.
"""

import pytest

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import ExportError, WorkspaceError
from aseprite_mcp.tools import export, sprite, workflow


# ----------------------------------------------------------------- create_sprite
def test_create_sprite_no_clobber():
    sprite.create_sprite("w/ov_make.aseprite", 8, 8)
    with pytest.raises(WorkspaceError, match="already exists"):
        sprite.create_sprite("w/ov_make.aseprite", 8, 8)
    # explicit opt-in succeeds
    sprite.create_sprite("w/ov_make.aseprite", 16, 16, overwrite=True)


# --------------------------------------------------------------- save_sprite_as
def test_save_sprite_as_no_clobber():
    sprite.create_sprite("w/ov_src.aseprite", 8, 8)
    sprite.save_sprite_as("w/ov_src.aseprite", "w/ov_copy.aseprite")
    with pytest.raises(WorkspaceError, match="already exists"):
        sprite.save_sprite_as("w/ov_src.aseprite", "w/ov_copy.aseprite")
    sprite.save_sprite_as("w/ov_src.aseprite", "w/ov_copy.aseprite", overwrite=True)


# ----------------------------------------------------------------- export_png
def test_export_png_no_clobber():
    sprite.create_sprite("w/ov_png.aseprite", 8, 8, background="#ffffff")
    export.export_png("w/ov_png.aseprite", "w/ov.png")
    with pytest.raises(ExportError, match="already exists"):
        export.export_png("w/ov_png.aseprite", "w/ov.png")
    export.export_png("w/ov_png.aseprite", "w/ov.png", overwrite=True)


# ----------------------------------------------------------------- export_tag_gif
def test_export_tag_gif_no_clobber():
    workflow.create_character_sprite("w/ov_tag", 16, 16)
    workflow.make_4_frame_idle_animation("w/ov_tag.aseprite")  # adds the "idle" tag
    export.export_tag_gif("w/ov_tag.aseprite", "idle", "w/idle.gif")
    with pytest.raises(ExportError, match="already exists"):
        export.export_tag_gif("w/ov_tag.aseprite", "idle", "w/idle.gif")
    export.export_tag_gif("w/ov_tag.aseprite", "idle", "w/idle.gif", overwrite=True)


# ---------------------------------------------------------- export_spritesheet
def test_export_spritesheet_no_clobber_checks_data_output():
    sprite.create_sprite("w/ov_sheet.aseprite", 8, 8, background="#ffffff")
    export.export_spritesheet("w/ov_sheet.aseprite", "w/sheet.png", data_output="w/sheet.json")
    # the existing sheet image blocks a re-export
    with pytest.raises(ExportError, match="already exists"):
        export.export_spritesheet("w/ov_sheet.aseprite", "w/sheet.png", data_output="w/sheet2.json")
    # ...and so does an existing data file even when the image path is new
    with pytest.raises(ExportError, match="already exists"):
        export.export_spritesheet("w/ov_sheet.aseprite", "w/sheet2.png", data_output="w/sheet.json")
    export.export_spritesheet(
        "w/ov_sheet.aseprite", "w/sheet.png", data_output="w/sheet.json", overwrite=True
    )


# --------------------------------------------------------------------- bundle
def test_bundle_no_clobber_round_trip():
    workflow.create_character_sprite("w/ov_b1", 16, 16)
    workflow.export_game_asset_bundle("w/ov_b1.aseprite")
    with pytest.raises(ExportError, match="already exists"):
        workflow.export_game_asset_bundle("w/ov_b1.aseprite")
    # explicit replacement of the whole bundle succeeds
    workflow.export_game_asset_bundle("w/ov_b1.aseprite", overwrite=True)


def test_bundle_fails_before_writing_any_file():
    workflow.create_character_sprite("w/ov_b2", 16, 16)
    # Pre-create the LAST planned output (manifest.json); the up-front validation
    # pass should reject the bundle before any image export runs.
    manifest = config.resolve("ov_b2_bundle/manifest.json")
    manifest.write_text("{}", encoding="utf-8")
    png = config.resolve("ov_b2_bundle/ov_b2.png")  # resolve only; file not created

    with pytest.raises(ExportError, match="already exists"):
        workflow.export_game_asset_bundle("w/ov_b2.aseprite")
    assert not png.exists()  # nothing was written despite the manifest being later in the plan
