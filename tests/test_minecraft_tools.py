"""Tool-layer tests for the Minecraft domain, with the Aseprite calls stubbed.

The pure decision logic lives in ``core/minecraft.py`` and is covered by
``test_minecraft.py``. What is checked here is the *wiring* around it — which export tool
a frame count selects, where the file lands inside the pack, whether the sidecar is
written alongside the PNG, and whether a wide texture is read back in correctly stitched
bands. Those are the parts that silently produce a pack the game will not load, and none
of them need a real Aseprite to exercise.
"""

import json
from pathlib import Path

import pytest

from aseprite_mcp.core import config
from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import minecraft as mct


def _info(width=16, height=16, frames=1, path="copper_grate.aseprite"):
    return {"path": path, "width": width, "height": height, "colorMode": "rgb",
            "frameCount": frames, "layers": [{"name": "base"}], "tags": [], "slices": []}


@pytest.fixture
def stub(monkeypatch):
    """Stub the Aseprite-backed calls and record what the tool asked them to do."""
    calls = {"spritesheet": [], "png": [], "pixels": []}

    def fake_info(filename):
        return calls.get("info", _info())

    def fake_spritesheet(**kw):
        calls["spritesheet"].append(kw)
        out = config.resolve(kw["output"])
        out.write_bytes(b"\x89PNG stub")
        return {"ok": True, "output": str(out)}

    def fake_png(**kw):
        calls["png"].append(kw)
        out = config.resolve(kw["output"])
        out.write_bytes(b"\x89PNG stub")
        return {"ok": True, "output": str(out)}

    def fake_pixels(filename, x=0, y=0, width=None, height=None, frame=1):
        calls["pixels"].append({"x": x, "y": y, "width": width, "height": height,
                                "frame": frame})
        # A distinct colour per row makes stitching errors visible rather than plausible.
        return {"pixels": [[f"#{(y + r) % 256:02x}0000ff"] * width for r in range(height)]}

    monkeypatch.setattr(mct.inspect, "get_sprite_info", fake_info)
    monkeypatch.setattr(mct.export, "export_spritesheet", fake_spritesheet)
    monkeypatch.setattr(mct.export, "export_png", fake_png)
    monkeypatch.setattr(mct.inspect, "get_pixels", fake_pixels)
    return calls


# ============================================================= pack.mcmeta
def test_write_pack_mcmeta_uses_known_version():
    r = mct.write_pack_mcmeta("packs/p1", mc_version="1.21.1", overwrite=True)
    doc = json.loads(Path(r["created_files"][0]["path"]).read_text(encoding="utf-8"))
    assert doc["pack"]["pack_format"] == 34


def test_write_pack_mcmeta_refuses_unknown_version():
    with pytest.raises(ValueError, match="Unknown Minecraft version"):
        mct.write_pack_mcmeta("packs/p2", mc_version="1.99")


def test_write_pack_mcmeta_supported_range_needs_both_ends():
    with pytest.raises(ExportError, match="together"):
        mct.write_pack_mcmeta("packs/p3", supported_min=32)


def test_write_pack_mcmeta_rejects_inverted_range():
    with pytest.raises(ExportError, match="greater than"):
        mct.write_pack_mcmeta("packs/p4", supported_min=42, supported_max=32)


def test_write_pack_mcmeta_is_no_clobber():
    mct.write_pack_mcmeta("packs/p5", overwrite=True)
    with pytest.raises(ExportError, match="already exists"):
        mct.write_pack_mcmeta("packs/p5")


# ============================================================= sidecar
def test_sidecar_must_target_the_png_itself():
    # <name>.png.mcmeta -- passing the stem would silently produce a file the game ignores.
    with pytest.raises(ExportError, match="sidecar is"):
        mct.write_texture_mcmeta("packs/p/assets/x/textures/block/lava")


def test_sidecar_document_written_beside_png():
    r = mct.write_texture_mcmeta("packs/p6/lava.png", frametime=2, interpolate=True,
                                 overwrite=True)
    path = Path(r["created_files"][0]["path"])
    assert path.name == "lava.png.mcmeta"
    assert json.loads(path.read_text(encoding="utf-8"))["animation"] == {
        "frametime": 2, "interpolate": True}


# ============================================================= export wiring
def test_static_texture_exports_png_and_no_sidecar(stub):
    r = mct.export_minecraft_texture("copper_grate.aseprite", pack_root="packs/e1",
                                     namespace="mcsc", category="block", overwrite=True)
    assert len(stub["png"]) == 1 and not stub["spritesheet"]
    assert stub["png"][0]["output"].endswith(
        "packs/e1/assets/mcsc/textures/block/copper_grate.png")
    assert [f["format"] for f in r["created_files"]] == ["png"]


def test_animated_texture_exports_vertical_strip_with_sidecar(stub):
    stub["info"] = _info(frames=4)
    r = mct.export_minecraft_texture("lava_flow.aseprite", pack_root="packs/e2",
                                     namespace="mcsc", category="block",
                                     texture_name="lava_flow", frametime=3, overwrite=True)
    call = stub["spritesheet"][0]
    # A packed or padded sheet is not a Minecraft animation; only an unpadded vertical
    # strip is, and the game gives no diagnostic when it is anything else.
    assert call["sheet_type"] == "vertical" and call["padding"] == 0
    assert [f["format"] for f in r["created_files"]] == ["png", "mcmeta"]
    sidecar = Path(r["created_files"][1]["path"])
    assert sidecar.name == "lava_flow.png.mcmeta"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["animation"]["frametime"] == 3


def test_export_warns_when_pack_has_no_mcmeta(stub):
    r = mct.export_minecraft_texture("copper_grate.aseprite", pack_root="packs/e3",
                                     namespace="mcsc", category="block", overwrite=True)
    assert any("pack.mcmeta" in w for w in r["warnings"])


def test_export_does_not_warn_when_pack_is_initialised(stub):
    mct.write_pack_mcmeta("packs/e4", overwrite=True)
    r = mct.export_minecraft_texture("copper_grate.aseprite",
                                     pack_root=str(config.resolve("packs/e4")),
                                     namespace="mcsc", category="block", overwrite=True)
    assert not any("pack.mcmeta" in w for w in r["warnings"])


def test_animation_settings_on_static_sprite_warn(stub):
    r = mct.export_minecraft_texture("copper_grate.aseprite", pack_root="packs/e5",
                                     namespace="mcsc", category="block",
                                     frametime=4, overwrite=True)
    assert any("one frame" in w for w in r["warnings"])


def test_subdirectory_texture_name_nests_in_pack(stub):
    mct.export_minecraft_texture("press.aseprite", pack_root="packs/e6", namespace="mcsc",
                                 category="block", texture_name="machines/press_top",
                                 overwrite=True)
    assert stub["png"][0]["output"].endswith(
        "packs/e6/assets/mcsc/textures/block/machines/press_top.png")


@pytest.mark.parametrize("kwargs,match", [
    ({"namespace": "MyPack"}, "lowercase"),
    ({"category": "blocks"}, "not a texture directory"),
    ({"texture_name": "CopperGrate"}, "resource path"),
])
def test_export_rejects_invalid_resource_locations(stub, kwargs, match):
    args = {"pack_root": "packs/e7", "namespace": "mcsc", "category": "block"}
    args.update(kwargs)
    with pytest.raises(ExportError, match=match):
        mct.export_minecraft_texture("copper_grate.aseprite", **args)


# ============================================================= banded pixel reads
def test_wide_texture_is_read_in_bands_and_stitched(stub):
    # get_pixels caps a call at 4096 px, so a 128-wide frame needs 4 reads of 32 rows.
    rows = mct._read_frame_pixels("big.aseprite", width=128, height=128, frame=1)
    assert len(rows) == 128 and all(len(r) == 128 for r in rows)
    assert [c["y"] for c in stub["pixels"]] == [0, 32, 64, 96]
    assert all(c["height"] == 32 for c in stub["pixels"])


def test_small_texture_is_a_single_read(stub):
    mct._read_frame_pixels("small.aseprite", width=16, height=16, frame=1)
    assert len(stub["pixels"]) == 1


def test_band_reads_cover_a_height_that_is_not_a_multiple(stub):
    # 4096//64 = 64 rows per band; a 100-row frame must not read past the end.
    mct._read_frame_pixels("odd.aseprite", width=64, height=100, frame=1)
    assert [(c["y"], c["height"]) for c in stub["pixels"]] == [(0, 64), (64, 36)]


# ============================================================= validation wiring
def test_validate_reads_every_frame(stub):
    stub["info"] = _info(frames=3)
    mct.validate_minecraft_texture("lava.aseprite", category="block", tiling=True)
    assert sorted({c["frame"] for c in stub["pixels"]}) == [1, 2, 3]


def test_validate_skips_seam_check_on_a_tiny_sprite(stub):
    stub["info"] = _info(width=2, height=2)
    r = mct.validate_minecraft_texture("tiny.aseprite", tiling=True)
    assert any("at least 3x3" in w for w in r["warnings"])
    assert not stub["pixels"]  # no point reading pixels it cannot judge


def test_validate_requires_category_with_pack_root(stub):
    with pytest.raises(ExportError, match="without category"):
        mct.validate_minecraft_texture("x.aseprite", pack_root="packs/v1")


def test_validate_flags_missing_sidecar_for_animated_texture(stub):
    stub["info"] = _info(frames=4)
    r = mct.validate_minecraft_texture("lava.aseprite", category="block",
                                       pack_root="packs/v2", namespace="mcsc",
                                       texture_name="lava")
    assert not r["validation"]["passed"]
    assert any("mcmeta" in e for e in r["validation"]["errors"])


def test_validate_passes_when_sidecar_present(stub):
    stub["info"] = _info(frames=4)
    root = config.resolve("packs/v3")
    png = root / "assets/mcsc/textures/block/lava.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"stub")
    png.with_suffix(".png.mcmeta").write_text('{"animation":{}}', encoding="utf-8")
    r = mct.validate_minecraft_texture("lava.aseprite", category="block",
                                       pack_root=str(root), namespace="mcsc",
                                       texture_name="lava")
    assert r["validation"]["passed"]
