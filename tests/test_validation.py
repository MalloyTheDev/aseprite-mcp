"""Pure-Python tests for the export-validation logic — no Aseprite (always run)."""

from aseprite_mcp.tools import validation


def _info(**over):
    base = {
        "width": 32, "height": 32, "colorMode": "rgb", "frameCount": 1,
        "layers": [{"name": "body"}], "tags": [], "paletteSize": 8,
    }
    base.update(over)
    return base


def test_clean_sprite_passes():
    r = validation.evaluate(_info(), expected_width=32, expected_height=32,
                            allowed_color_modes=["rgb"], min_frames=1)
    assert r["passed"] is True and r["errors"] == []


def test_dimension_and_tile_multiple_errors():
    r = validation.evaluate(_info(width=30), expected_width=32)
    assert r["passed"] is False and any("width" in e for e in r["errors"])
    r2 = validation.evaluate(_info(width=30, height=32), tile_multiple=16)
    assert r2["passed"] is False and any("multiple" in e for e in r2["errors"])


def test_color_mode_and_palette_errors():
    r = validation.evaluate(_info(colorMode="rgb"), allowed_color_modes=["indexed"])
    assert r["passed"] is False
    r2 = validation.evaluate(_info(paletteSize=64), max_palette_size=16)
    assert r2["passed"] is False and any("palette" in e for e in r2["errors"])


def test_frames_and_required_tags():
    r = validation.evaluate(_info(frameCount=1), min_frames=4)
    assert r["passed"] is False
    info = _info(frameCount=4, tags=[{"name": "idle", "from": 1, "to": 4}])
    r2 = validation.evaluate(info, required_tags=["idle", "walk"])
    assert r2["passed"] is False and any("walk" in e for e in r2["errors"])
    r3 = validation.evaluate(info, required_tags=["idle"])
    assert r3["passed"] is True


def test_transparent_background():
    opaque = validation.evaluate(_info(), require_transparent_background=True,
                                 transparent_corners=[True, True, False, True])
    assert opaque["passed"] is False
    clear = validation.evaluate(_info(), require_transparent_background=True,
                                transparent_corners=[True, True, True, True])
    assert clear["passed"] is True
    unknown = validation.evaluate(_info(), require_transparent_background=True,
                                  transparent_corners=None)
    assert unknown["passed"] is True  # only a warning when corners can't be read
    assert unknown["warnings"]


def test_exports_and_metadata_errors():
    r = validation.evaluate(_info(), missing_exports=["a.png", "b.gif"])
    assert r["passed"] is False and any("missing export" in e for e in r["errors"])
    ok = validation.evaluate(_info(), missing_exports=[])
    assert ok["passed"] is True
    bad = validation.evaluate(_info(), unreadable_metadata="sheet.json")
    assert bad["passed"] is False


def test_soft_warnings_do_not_fail():
    info = _info(width=2048, height=64, frameCount=3, layers=[{"name": "Layer 1"}])
    r = validation.evaluate(info)
    assert r["passed"] is True  # warnings only
    joined = " ".join(r["warnings"])
    assert "large canvas" in joined
    assert "no animation tags" in joined
    assert "Layer 1" in joined
