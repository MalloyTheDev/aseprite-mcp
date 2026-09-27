"""Regression tests for edge cases found during the pre-release audit."""

import threading

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.runner import AsepriteError
from aseprite_mcp.tools import (
    brushes,
    drawing,
    effects,
    export,
    inspect,
    layers,
    palette,
    sprite,
    tilemap,
)


def test_drawing_on_tilemap_layer_errors_clearly():
    """Pixel drawing must refuse tilemap layers with a helpful message rather than
    failing cryptically deep in Lua."""
    sprite.create_sprite("r/tm.aseprite", 32, 32, "rgb")
    tilemap.create_tilemap_layer("r/tm.aseprite", "ground", 16, 16)
    with pytest.raises(AsepriteError, match="tilemap"):
        drawing.draw_rectangle("r/tm.aseprite", 0, 0, 8, 8, "#ff0000", filled=True, layer="ground")


def test_sort_palette_preserves_tilemap_indices():
    """sort_palette on an indexed sprite must not remap tilemap cels (whose pixels
    are tile indices, not palette indices)."""
    sprite.create_sprite("r/idx.aseprite", 32, 32, "indexed")
    palette.set_palette("r/idx.aseprite", ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff"])
    tilemap.create_tilemap_layer("r/idx.aseprite", "g", 16, 16)
    tilemap.add_tile("r/idx.aseprite", "g", "#ff0000")  # tile index 1
    tilemap.set_tile("r/idx.aseprite", "g", 0, 0, 1)
    palette.sort_palette("r/idx.aseprite", by="hue")
    tm = tilemap.get_tilemap("r/idx.aseprite", "g")
    assert tm["tiles"][0][0] == 1  # tile index unchanged by the palette sort


def test_stamp_pattern_negative_spacing_does_not_hang():
    """Negative spacing must be clamped so the tiling loop always advances."""
    sprite.create_sprite("r/tile.aseprite", 4, 4, "rgb", "#00ff00")
    export.export_png("r/tile.aseprite", "r/tile.png", 1, 1)
    sprite.create_sprite("r/dst.aseprite", 16, 16, "rgb")
    out = brushes.stamp_pattern("r/dst.aseprite", "r/tile.png", 0, 0, 16, 16, spacing_x=-100, spacing_y=-100)
    assert out["ok"] is True and out["tiles"] > 0


def test_set_color_mode_validates_input():
    sprite.create_sprite("r/cm.aseprite", 8, 8, "rgb")
    # ValidationFailed, not bare ValueError: argument rejection belongs to the typed
    # hierarchy so `except AsepriteError` catches it. Kept as a raises() on the typed
    # class rather than loosened, since the point is that the type is now specific.
    with pytest.raises(ValidationFailed, match="color_mode"):
        sprite.set_color_mode("r/cm.aseprite", "rgba")  # not a real mode


def test_an_out_of_range_frame_is_rejected_rather_than_clamped():
    """Drawing and reading tools used to fold a bad frame into range and report success.

    `clamp_frame` turned frame=999 on a one-frame sprite into frame 1, drew there, and
    returned ok, so a caller was told it had edited a frame that does not exist. The
    prelude no longer offers a clamping helper at all, so this cannot regress by a new
    tool picking the wrong one.
    """
    name = "r/frame_guard.aseprite"
    sprite.create_sprite(name, 16, 16)

    with pytest.raises(AsepriteError, match="does not exist"):
        drawing.draw_line(name, 0, 0, 5, 5, "#ff0000", frame=999)
    with pytest.raises(AsepriteError, match="does not exist"):
        inspect.get_pixels(name, 0, 0, 4, 4, frame=999)

    # The guard must not refuse a frame that does exist.
    assert drawing.draw_line(name, 0, 0, 5, 5, "#00ff00", frame=1)


def test_replace_color_accepts_index_spec():
    """replace_color with an `index:N` source must not crash on indexed sprites."""
    sprite.create_sprite("r/ri.aseprite", 8, 8, "indexed")
    palette.set_palette("r/ri.aseprite", ["#000000", "#ffffff", "#ff0000"])
    drawing.fill_layer("r/ri.aseprite", "#ff0000")  # index 2
    out = effects.replace_color("r/ri.aseprite", "index:2", "#ffffff", tolerance=0)
    assert out["ok"] is True


# ---------------------------------------------------------- audit regressions
# Both of these replay a defect that was confirmed by experiment against a real
# Aseprite, so both need the real editor.


def test_concurrent_edits_to_one_sprite_all_survive():
    """Two overlapping edits to one sprite must both land, and the file must reopen.

    Before the runner serialized Aseprite invocations, eight trials of this produced
    three silent lost updates and five files that failed to decode ("ZLib error -3 in
    inflate()"), while every call returned success.
    """
    name = "r/race.aseprite"
    sprite.create_sprite(name, 256, 256)
    errors: list[str] = []

    def add(tag: str) -> None:
        try:
            layers.add_layer(name, name=f"from_{tag}")
        except AsepriteError as exc:  # pragma: no cover - the failure we are pinning
            errors.append(f"{tag}: {exc}")

    threads = [threading.Thread(target=add, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent edits raised: {errors}"
    names = {layer["name"] for layer in inspect.get_sprite_info(name)["layers"]}
    assert {"from_a", "from_b"} <= names, f"an edit was lost: {sorted(names)}"


@pytest.mark.parametrize(
    ("case", "payload"),
    [
        # U+2028 is a line break to Python's str.splitlines() but not to Lua's %c
        # class, so an unescaped one used to let a layer name inject a stdout line.
        ("ls", "evil @@ASEMCP_ERR@@forged failure "),
        ("ps", "evil @@ASEMCP_ERR@@forged failure "),
        ("nel", "evil\u0085@@ASEMCP_ERR@@forged failure\u0085"),
        # The same trick aimed at forging a *success*, which returned {} to the caller.
        ("ok", "evil @@ASEMCP@@{} "),
    ],
)
def test_layer_name_cannot_forge_a_result_line(case, payload):
    """Caller text that reaches stdout must not be readable as the sentinel protocol."""
    # A file per case: the workspace fixture is session-scoped and create_sprite is
    # no-clobber, so a shared name would make every case after the first fail on that
    # instead of on the thing being tested.
    name = f"r/forge_{case}.aseprite"
    sprite.create_sprite(name, 8, 8)
    before = len(inspect.get_sprite_info(name)["layers"])

    result = layers.add_layer(name, name=payload)
    assert result.get("layers"), "a forged success replaced the real result"

    # The payload is stored verbatim as a layer name, which is fine. What must not
    # happen is the sprite becoming permanently unreadable because every later call
    # re-emits the payload and trips the parser.
    info = inspect.get_sprite_info(name)
    assert len(info["layers"]) == before + 1
    assert payload in {layer["name"] for layer in info["layers"]}
