"""assess_sprite over real sprites: requires Aseprite (--run-aseprite).

The metrics themselves are tested in test_quality.py without an editor. What is tested
here is the part that needs one: that the whole frame is read correctly in a single
launch, whatever its size, and that the readings land on sprites that really do have the
faults they describe.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.core.runner import AsepriteError
from aseprite_mcp.tools import drawing, effects, inspect, layers, palette, shading, sprite

RAMP = palette.generate_ramp("#5a7fd4", steps=5, hue_shift=-40.0)["colors"]


def _orb(request, size: int = 32, box: int = 28, suffix: str = "") -> str:
    name = f"as/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, size, size)
    inset = (size - box) // 2
    drawing.draw_ellipse_in_box(name, inset, inset, box, box, RAMP[2], filled=True)
    shading.shade_region_by_light(name, RAMP, light_angle=125, rim=0.2)
    return name


def _lines(result: dict) -> str:
    return " ".join(result["readings"])


# -------------------------------------------------------------------- clean art is quiet
def test_a_clean_shaded_orb_has_nothing_to_report(request):
    result = inspect.assess_sprite(_orb(request), ramp=RAMP)

    assert result["metrics"]["palette_conformance"] == 1.0
    assert result["metrics"]["drawn_pixels"] > 0
    assert result["readings"] == [], result["readings"]


# ------------------------------------------------------------------- the faults it names
def test_a_brightness_filter_is_reported_as_leaving_the_ramp(request):
    """The measurement the shading tools exist for, now reachable by the agent that has
    to decide whether its last call was the right one."""
    name = _orb(request)
    assert inspect.assess_sprite(name, ramp=RAMP)["metrics"]["palette_conformance"] == 1.0

    effects.adjust_brightness_contrast(name, brightness=-20)

    after = inspect.assess_sprite(name, ramp=RAMP)
    assert after["metrics"]["palette_conformance"] == 0.0
    assert "off the declared ramp" in _lines(after)
    assert "shift_along_ramp" in _lines(after), "a fault should name its fix"


def test_scattered_pixels_are_reported_as_noise(request):
    name = _orb(request)
    before = inspect.assess_sprite(name)["metrics"]["isolated_pixels"]

    drawing.draw_pixels(name, [{"x": 1 + (i * 3) % 30, "y": 1 + (i * 7) % 30}
                               for i in range(16)], "#ff00ff")

    after = inspect.assess_sprite(name)
    assert after["metrics"]["isolated_pixels"] > before
    assert "no neighbour of their own colour" in _lines(after)


def test_art_lost_in_a_large_canvas_is_reported_with_the_sizes(request):
    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, 64, 64)
    drawing.draw_ellipse_in_box(name, 2, 2, 10, 10, RAMP[2], filled=True)

    result = inspect.assess_sprite(name)
    assert result["metrics"]["canvas_usage"] < 0.3
    assert "of 64x64" in _lines(result)


def test_an_empty_frame_says_so_rather_than_reporting_zeros(request):
    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)

    result = inspect.assess_sprite(name)
    assert result["metrics"]["bbox"] is None
    assert result["readings"] == ["Nothing is drawn on this frame."]


# ------------------------------------------------------------------------------ scoping
def test_a_layer_can_be_measured_on_its_own(request):
    """A background fills the canvas, so the flattened frame is always 100% used and
    always on whatever the background's colour is."""
    name = _orb(request)
    layers.add_layer(name, "bg")
    layers.move_layer(name, "bg", 1)
    drawing.fill_layer(name, "#101018", layer="bg")

    flattened = inspect.assess_sprite(name, ramp=RAMP)
    scoped = inspect.assess_sprite(name, layer="Layer 1", ramp=RAMP)

    assert flattened["metrics"]["canvas_usage"] == 1.0
    assert scoped["metrics"]["canvas_usage"] < 1.0
    assert scoped["metrics"]["palette_conformance"] == 1.0
    assert flattened["metrics"]["palette_conformance"] < 1.0


def test_the_tiling_check_tells_the_axes_apart(request):
    """A tile that wraps on one axis and not the other is the common case, and which one
    is broken is most of the fix."""
    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, 32, 32)
    # A vertical gradient meets itself along the sides and not top to bottom.
    # respect_alpha defaults to True, and a new sprite is transparent, so the fill has to
    # be told to paint the empty canvas.
    effects.fill_gradient(name, ["#101820", "#e8f0ff"], angle=90.0, respect_alpha=False)

    result = inspect.assess_sprite(name, check_tiling=True)
    seam = result["metrics"]["tile_seam"]
    assert seam["vertical"] > seam["horizontal"], seam
    assert "vertical wrap" in _lines(result)


# ------------------------------------------------------------------------------- the cap
def test_one_aseprite_launch_however_big_the_frame(request, monkeypatch):
    from aseprite_mcp.core import runner

    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, 256, 256)
    drawing.draw_ellipse_in_box(name, 8, 8, 240, 240, RAMP[2], filled=True)

    launches = []
    real = runner._run_bounded

    def counted(*args, **kwargs):
        launches.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_bounded", counted)
    result = inspect.assess_sprite(name)

    assert len(launches) == 1
    assert result["width"] == 256 and result["height"] == 256
    assert result["metrics"]["drawn_pixels"] > 40_000


def test_a_frame_past_the_cap_is_refused_with_its_size(request):
    from aseprite_mcp.core.limits import MAX_ASSESS_PIXELS

    side = 1 + int(MAX_ASSESS_PIXELS ** 0.5)
    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, side, side)

    with pytest.raises(AsepriteError, match=f"{side}x{side}"):
        inspect.assess_sprite(name)


def test_assessing_changes_nothing(request):
    """It is a measurement. The file it opened must come back byte-identical."""
    import hashlib

    from aseprite_mcp.tools.common import resolve_path

    name = _orb(request)
    path = resolve_path(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = path.stat().st_mtime_ns

    inspect.assess_sprite(name, ramp=RAMP, check_tiling=True)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.stat().st_mtime_ns == mtime


# ------------------------------------------- indexed transparency (issue #134)
# The pixel decode used to live twice in inspect.py, and both copies went straight to
# the palette without the transparentColor check the prelude does first. On a sprite
# whose transparent index points at an opaque palette entry, every transparent pixel
# read back as that colour, so the whole canvas counted as drawn.


def _indexed_trap(request) -> str:
    """An indexed sprite whose transparent index is an opaque palette entry."""
    from aseprite_mcp.tools import palette as palette_tools

    name = f"as/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 8, color_mode="indexed")
    palette_tools.set_palette(name, ["#ff00ff", "#204080", "#e0e0e0"])
    drawing.draw_rectangle(name, 2, 2, 3, 3, "index:1", filled=True)
    palette_tools.set_transparent_color(name, 0)
    return name


def test_transparent_pixels_are_not_counted_as_drawn_on_an_indexed_sprite(request):
    name = _indexed_trap(request)

    metrics = inspect.assess_sprite(name)["metrics"]

    assert metrics["drawn_pixels"] == 9, "only the 3x3 rectangle is drawn"
    assert metrics["bbox"] == [2, 2, 4, 4]
    assert metrics["canvas_usage"] < 1.0


def test_get_pixels_reads_those_pixels_as_transparent(request):
    name = _indexed_trap(request)

    rows = inspect.get_pixels(name, 0, 0, 8, 8)["pixels"]

    assert rows[0][0].lower().endswith("00"), "a transparent pixel must read transparent"
    assert not rows[3][3].lower().endswith("00"), "the drawn rectangle is still opaque"


def test_the_map_format_shows_the_shape_rather_than_a_full_canvas(request):
    """The map exists to be readable at a glance, which it was not: every pixel showed
    as the transparent index's palette colour."""
    name = _indexed_trap(request)

    mapped = inspect.get_pixels(name, 0, 0, 8, 8, format="map")

    assert mapped["rows"][0] == "........"
    assert mapped["rows"][3][2:5] == "aaa"


# ------------------------------------------------------- a ramp in any colour notation
@pytest.mark.pure
def test_a_ramp_in_any_notation_is_measured_as_hex():
    """The metrics parse hex only, so `ramp=["red"]` crashed after the launch and `#abc`
    was silently misread, though every drawing tool accepts both."""
    assert inspect.ramp_as_hex(["red", "#AABBCC", "#abc", "10,20,30", "#ff000080"]) == [
        "#ff0000", "#aabbcc", "#aabbcc", "#0a141e", "#ff000080"]


@pytest.mark.pure
def test_a_palette_index_in_a_ramp_is_refused_by_name():
    with pytest.raises(ValidationFailed, match="'index:3' is a palette index"):
        inspect.ramp_as_hex(["#000000", "index:3"])


def test_a_named_ramp_measures_exactly_as_its_hex_does(request):
    name = _orb(request)
    by_name = inspect.assess_sprite(name, ramp=["black", "white"])
    by_hex = inspect.assess_sprite(name, ramp=["#000000", "#ffffff"])
    assert by_name["metrics"]["palette_conformance"] == 0.0
    assert by_name["metrics"] == by_hex["metrics"]
    assert by_name["readings"] == by_hex["readings"]
