"""Exports must refuse work they cannot do, and report what they actually did.

Aseprite exits 0 for arguments it ignored. `run_cli` only raises on a non-zero exit, so an
export of a frame that does not exist, a tag that does not exist, or a layer that does not
exist all returned ok and wrote a file -- of something else. Worse, the return dict echoed the
REQUESTED value after the code had already clamped it, so:

    export_png(frame=99)  on a one-frame sprite -> {"ok": true, "frame": 99}   (frame 1 written)
    export_png(scale=0)                          -> {"ok": true, "scale": 0}   (scale 1 used)

A confident, machine-readable lie is worse than an error, because nothing downstream can tell.

These need a real Aseprite, so they are integration tests: run with --run-aseprite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aseprite_mcp.core.errors import ExportError
from aseprite_mcp.tools import export, layers, sprite, tags


@pytest.fixture()
def one_frame():
    """A one-frame, one-layer sprite -- the smallest thing that exposes the bug.

    The session-scoped workspace fixture in conftest already points at a temp dir.
    """
    name = "verify_src.aseprite"
    sprite.create_sprite(filename=name, width=16, height=16, overwrite=True)
    return name


# ------------------------------------------------------------------------------- frames


def test_a_frame_that_does_not_exist_is_refused(one_frame):
    with pytest.raises(ExportError, match="frame 99 does not exist"):
        export.export_png(filename=one_frame, output="out99.png", frame=99, overwrite=True)


def test_the_refusal_says_how_many_frames_there_are(one_frame):
    with pytest.raises(ExportError, match="1 frame"):
        export.export_png(filename=one_frame, output="out99.png", frame=99, overwrite=True)


def test_frame_zero_is_refused(one_frame):
    """1-based throughout; 0 used to clamp to frame 1 and report 0 back."""
    with pytest.raises(ExportError):
        export.export_png(filename=one_frame, output="out0.png", frame=0, overwrite=True)


def test_a_valid_frame_still_exports(one_frame):
    got = export.export_png(filename=one_frame, output="ok.png", frame=1, overwrite=True)
    assert got["ok"] and got["frame"] == 1 and got["bytes"] > 0


# -------------------------------------------------------------------------------- scale


@pytest.mark.parametrize("scale", [0, -4])
def test_a_nonsensical_scale_is_refused(one_frame, scale):
    with pytest.raises(ExportError, match="scale must be at least 1"):
        export.export_png(filename=one_frame, output="s.png", scale=scale, overwrite=True)


def test_a_valid_scale_is_reported_as_applied(one_frame):
    got = export.export_png(filename=one_frame, output="s2.png", scale=2, overwrite=True)
    assert got["scale"] == 2


# --------------------------------------------------------------------------------- tags


def test_an_unknown_tag_is_refused(one_frame):
    """An unknown --tag made Aseprite export EVERY frame and still exit 0."""
    with pytest.raises(ExportError, match="no tag named"):
        export.export_tag_gif(filename=one_frame, tag="NO_SUCH_TAG", output="t.gif",
                              overwrite=True)


def test_a_real_tag_exports(one_frame):
    tags.add_tag(filename=one_frame, name="idle", from_frame=1, to_frame=1)
    got = export.export_tag_gif(filename=one_frame, tag="idle", output="t2.gif", overwrite=True)
    assert got["ok"] and got["tag"] == "idle" and got["bytes"] > 0


# ------------------------------------------------------------------------------- layers


def test_an_unknown_layer_is_refused(one_frame):
    """An unknown --layer exported the whole sprite instead, and still exited 0."""
    with pytest.raises(ExportError, match="no layer named"):
        export.export_layer(filename=one_frame, layer="NO_SUCH_LAYER", output="l.png")


def test_the_refusal_lists_the_layers_that_do_exist(one_frame):
    layers.add_layer(filename=one_frame, name="Detail")
    with pytest.raises(ExportError, match="Detail"):
        export.export_layer(filename=one_frame, layer="NO_SUCH_LAYER", output="l2.png")


def test_a_real_layer_exports(one_frame):
    layers.add_layer(filename=one_frame, name="Detail")
    got = export.export_layer(filename=one_frame, layer="Detail", output="l3.png")
    assert got["ok"] and got["layer"] == "Detail" and got["bytes"] > 0


# ------------------------------------------------------------------ output verification


def test_every_export_reports_the_size_of_the_file_it_actually_wrote(one_frame):
    """`bytes > 0` is too weak to be evidence -- a hardcoded 1 satisfies it. The number has
    to be the real size, measured independently, or it is just another confident lie."""
    png = export.export_png(filename=one_frame, output="v1.png", overwrite=True)
    gif = export.export_gif(filename=one_frame, output="v2.gif", overwrite=True)
    for got in (png, gif):
        assert got["bytes"] == Path(got["output"]).stat().st_size > 0


@pytest.mark.pure
def test_an_export_that_wrote_nothing_is_not_a_success(tmp_path):
    """Aseprite exits 0 for work it skipped, so a clean exit is not proof of an export."""
    with pytest.raises(ExportError, match="wrote nothing"):
        export._verify_written(tmp_path / "never_created.png", "export_png")


@pytest.mark.pure
def test_an_export_that_wrote_an_empty_file_is_not_a_success(tmp_path):
    empty = tmp_path / "empty.png"
    empty.touch()
    with pytest.raises(ExportError, match="empty file"):
        export._verify_written(empty, "export_png")
