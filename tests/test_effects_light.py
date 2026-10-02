"""Cast shadow and glow, tested against a real Aseprite.

Both exist because the same effect from an image editor takes the art off its palette, so
the assertion that matters in here is `palette_conformance`: a glow of interpolated
colours or a shadow made by multiplying alpha would look plausible in a preview and score
below 1.0 here. The geometry claims are checked for direction rather than for exact
sizes, since the sizes are the arithmetic that `test_lighting.py` already pins.

`remove_stray_pixels`'s opt-in erasing mode is pinned here too. It is the one mode of
that tool which changes the silhouette, so what it is held to is the opposite assertion
from conformance: how many pixels the sprite still has afterwards, and which ones.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import lighting, quality
from aseprite_mcp.core.errors import AsepriteError, ValidationFailed
from aseprite_mcp.tools import (
    cels,
    drawing,
    effects,
    frames,
    inspect,
    layers,
    sprite,
)

# A warm body ramp and a cool ground ramp, so a test can tell which of the two a pixel
# came from rather than only that it came from "the ramp".
BODY = ["#2d1b1b", "#5a3030", "#8f4d4d", "#c07878", "#e3b5b5"]
GROUND = ["#1b2028", "#333c48", "#55616f", "#7e8b99"]

SIZE = 40
BALL_CX, BALL_CY, BALL_R = 18, 18, 7


def _scene(request, suffix: str = "", floor_top: int = 28) -> str:
    """A ball on a floor, each on its own layer: the case a cast shadow is drawn for."""
    name = f"fx/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    layers.rename_layer(name, "Layer 1", "ball")
    layers.add_layer(name, "floor")
    layers.move_layer(name, "floor", 1)
    drawing.draw_rectangle(
        name, 0, floor_top, SIZE, SIZE - floor_top, GROUND[2], filled=True, layer="floor"
    )
    drawing.draw_ellipse(
        name, BALL_CX, BALL_CY, BALL_R, BALL_R, BODY[3], filled=True, layer="ball"
    )
    return name


def _bare_ball(request, suffix: str = "") -> str:
    """A ball with no floor at all, for the cases that must not need one."""
    name = f"fx/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    drawing.draw_ellipse(name, BALL_CX, BALL_CY, BALL_R, BALL_R, BODY[3], filled=True)
    return name


def _cells(name: str, layer: str | None = None) -> dict[tuple[int, int], str]:
    rows = inspect.get_pixels(name, 0, 0, SIZE, SIZE, layer=layer)["pixels"]
    return {
        (x, y): p.lower()
        for y, row in enumerate(rows)
        for x, p in enumerate(row)
        if not p.lower().endswith("00")
    }


def _centroid_x(cells: dict) -> float:
    return sum(x for x, _ in cells) / len(cells)


# --------------------------------------------------------------------- cast shadow
def test_a_cast_shadow_is_made_of_ramp_steps(request):
    """The premise. A shadow of blended alpha would score below 1.0 here."""
    name = _scene(request)
    result = effects.cast_shadow(name, "ball", GROUND, light_angle=135)

    assert result["shadow_pixels"] > 0
    shadow = inspect.get_pixels(name, 0, 0, SIZE, SIZE, layer=result["layer"])["pixels"]
    assert quality.palette_conformance(shadow, GROUND) == 1.0


@pytest.mark.parametrize(
    ("angle", "side"),
    [(135, "right"), (180, "right"), (45, "left"), (0, "left")],
)
def test_a_cast_shadow_falls_away_from_the_light_at_four_angles(request, angle, side):
    """The acceptance criterion, read off the drawn shadow rather than the parameters."""
    name = _bare_ball(request, f"_{angle}")
    result = effects.cast_shadow(name, "Layer 1", GROUND, light_angle=angle)

    shadow = _cells(name, result["layer"])
    assert shadow, "the shadow has to have been drawn"
    offset = _centroid_x(shadow) - BALL_CX
    if side == "right":
        assert offset > 0.5, f"a light at {angle} must cast right, got {offset:+.2f}"
    else:
        assert offset < -0.5, f"a light at {angle} must cast left, got {offset:+.2f}"


def test_an_overhead_light_casts_straight_down(request):
    name = _bare_ball(request)
    result = effects.cast_shadow(name, "Layer 1", GROUND, light_angle=135,
                                light_height=1.0)
    assert _centroid_x(_cells(name, result["layer"])) == pytest.approx(BALL_CX, abs=1.0)


def test_lowering_the_light_lengthens_the_shadow(request):
    """The direction of the change, not a size."""
    widths = []
    for height in (1.0, 0.7, 0.4, 0.15):
        name = _bare_ball(request, f"_{height}")
        result = effects.cast_shadow(
            name, "Layer 1", GROUND, light_angle=135, light_height=height
        )
        widths.append(result["shadow_ellipse"][2])

    assert widths == sorted(widths), f"rx must grow as the light drops: {widths}"
    assert widths[-1] > widths[0], widths


def test_the_drawn_ellipse_is_the_one_the_pure_geometry_specifies(request):
    """The formula lives in Python for testing and in Lua for drawing; they must agree.

    This is the only thing standing between the two copies and a silent divergence, so it
    is checked on a real sprite at several lights rather than assumed.
    """
    for angle, height in ((135, 0.6), (45, 0.3), (0, 0.9), (210, 0.5)):
        name = _bare_ball(request, f"_{angle}_{height}")
        result = effects.cast_shadow(
            name, "Layer 1", GROUND, light_angle=angle, light_height=height
        )
        expected = lighting.shadow_ellipse(
            tuple(result["subject_box"]), angle, height, result["ground_y"]
        )
        assert tuple(result["shadow_ellipse"]) == expected, (angle, height)


def test_the_contact_row_is_the_subjects_own_lowest_row(request):
    name = _bare_ball(request)
    result = effects.cast_shadow(name, "Layer 1", GROUND, light_angle=135)

    assert result["contact_row"] == BALL_CY + BALL_R
    assert result["ground_y"] == result["contact_row"], "the default is the contact row"


def test_the_subjects_own_cel_is_never_touched(request):
    """The acceptance criterion: the effect lives on its own layer and nowhere else."""
    name = _scene(request)
    before = _cells(name, "ball")

    result = effects.cast_shadow(name, "ball", GROUND, light_angle=135)

    assert _cells(name, "ball") == before
    assert result["layer"] == "shadow"
    assert result["subject_layer"] == "ball"


def test_deleting_the_layer_removes_the_shadow(request):
    name = _scene(request)
    before = _cells(name)
    effects.cast_shadow(name, "ball", GROUND, light_angle=135)
    assert _cells(name) != before

    layers.remove_layer(name, "shadow")
    assert _cells(name) == before


def test_the_shadow_sits_below_the_subject_in_the_stack(request):
    """So the subject stays crisp and the shadow reads behind it."""
    name = _scene(request)
    effects.cast_shadow(name, "ball", GROUND, light_angle=135)

    order = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    assert order.index("shadow") < order.index("ball"), order


def test_softness_adds_a_lighter_rim_of_further_ramp_steps(request):
    """A penumbra is ramp steps arranged in space, not a blur."""
    hard = _bare_ball(request, "_hard")
    soft = _bare_ball(request, "_soft")
    a = effects.cast_shadow(hard, "Layer 1", GROUND, light_angle=135, softness=0)
    b = effects.cast_shadow(soft, "Layer 1", GROUND, light_angle=135, softness=2)

    hard_colors = {p[:7] for p in _cells(hard, a["layer"]).values()}
    soft_colors = {p[:7] for p in _cells(soft, b["layer"]).values()}

    assert hard_colors == {GROUND[0]}, hard_colors
    assert len(soft_colors) == 3, soft_colors
    assert soft_colors <= {c.lower() for c in GROUND}
    assert b["shadow_pixels"] > a["shadow_pixels"]


def test_a_named_ground_layer_clips_the_shadow_to_the_floor(request):
    """A shadow hanging off the edge of a platform is the geometry bug this prevents."""
    name = _scene(request, floor_top=28)
    free = effects.cast_shadow(name, "ball", GROUND, light_angle=135,
                               new_layer="free")
    clipped = effects.cast_shadow(name, "ball", GROUND, light_angle=135,
                                  ground_layer="floor", new_layer="clipped")

    assert clipped["shadow_pixels"] < free["shadow_pixels"]
    assert clipped["clipped_pixels"] > 0

    floor = _cells(name, "floor")
    for xy in _cells(name, "clipped"):
        assert xy in floor, f"shadow pixel {xy} is not on the floor"


def test_no_surface_to_land_on_is_refused(request):
    """The issue's refusal: a shadow is a property of a surface."""
    name = _scene(request, floor_top=28)
    # A floor that exists but is nowhere near where the shadow falls.
    layers.add_layer(name, "ledge")
    drawing.draw_rectangle(name, 0, 0, 4, 2, GROUND[3], filled=True, layer="ledge")

    with pytest.raises(AsepriteError, match="no surface for this shadow to land on"):
        effects.cast_shadow(name, "ball", GROUND, light_angle=135, ground_layer="ledge")


def test_a_subject_with_nothing_drawn_on_it_is_refused(request):
    name = _scene(request)
    layers.add_layer(name, "empty")

    with pytest.raises(AsepriteError, match="has nothing drawn on frame"):
        effects.cast_shadow(name, "empty", GROUND)


def test_a_ground_row_off_the_canvas_is_refused(request):
    name = _bare_ball(request)
    with pytest.raises(AsepriteError, match="off the canvas"):
        effects.cast_shadow(name, "Layer 1", GROUND, ground_y=SIZE + 5)


def test_a_ground_row_above_the_subject_is_refused(request):
    """A floor running through the subject's legs is not a floor."""
    name = _bare_ball(request)
    with pytest.raises(AsepriteError, match="above the subject's contact row"):
        effects.cast_shadow(name, "Layer 1", GROUND, ground_y=BALL_CY - BALL_R)


def test_a_layer_name_that_is_already_taken_is_refused(request):
    """Two layers with one name make every later call that names it ambiguous."""
    name = _scene(request)
    with pytest.raises(AsepriteError, match="already exists"):
        effects.cast_shadow(name, "ball", GROUND, new_layer="floor")


def test_a_subject_cannot_be_its_own_floor(request):
    name = _scene(request)
    with pytest.raises(ValidationFailed, match="same layer as the subject"):
        effects.cast_shadow(name, "ball", GROUND, ground_layer="ball")


def test_a_light_too_low_for_the_canvas_is_refused_not_reported_as_drawn(request):
    """A tool reporting success having drawn nothing is the failure mode here.

    A tall subject under a near-horizon light projects an ellipse hundreds of pixels
    across, which this canvas cannot show any of usefully. The message quotes the
    light_height and the size it produced, so the argument to change is named.
    """
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    drawing.draw_rectangle(name, SIZE - 3, 2, 3, 34, BODY[3], filled=True)

    with pytest.raises(AsepriteError, match="past anything the sprite can show") as exc:
        effects.cast_shadow(name, "Layer 1", GROUND, light_angle=180, light_height=0.06)
    assert "light_height 0.060" in str(exc.value)


def test_the_rasterisation_point_count_matches_the_pure_bound(request):
    """The allocation guard's arithmetic lives in Python and in Lua; they must agree.

    The guard runs before anything is rasterised, so if the Lua's count drifted below the
    pure one the bound would be checked against the wrong number.
    """
    name = _bare_ball(request)
    result = effects.cast_shadow(name, "Layer 1", GROUND, light_angle=135, softness=1)

    _, _, rx, ry = result["shadow_ellipse"]
    expected = lighting.filled_ellipse_points(rx + result["softness"],
                                              ry + result["softness"])
    assert result["ellipse_points"] == expected


def test_a_shadow_too_large_to_rasterise_is_refused_before_it_allocates(request):
    """Reachable from legal arguments, and an out-of-memory with nothing drawn if not.

    A wide subject under a low light asks for an ellipse whose point list is built in
    full before any pixel is written, so the cost is memory rather than patience. The
    canvas here is small; it is the subject's width and the light's height that drive the
    radii, which is exactly why a per-axis canvas check cannot catch this.
    """
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, 4000, 60)
    drawing.draw_rectangle(name, 0, 0, 4000, 55, BODY[3], filled=True)

    with pytest.raises(AsepriteError, match="would rasterise") as exc:
        effects.cast_shadow(name, "Layer 1", GROUND, light_angle=180, light_height=0.25)
    message = str(exc.value)
    assert "past the limit of" in message
    assert "memory rather than patience" in message


def test_a_legitimately_large_shadow_on_a_large_canvas_still_draws(request):
    """The guard must refuse the allocation without refusing a big sprite."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, 512, 256)
    drawing.draw_rectangle(name, 100, 20, 300, 200, BODY[3], filled=True)

    result = effects.cast_shadow(name, "Layer 1", GROUND, light_angle=135,
                                 light_height=0.5)

    # Tens of thousands of points: far larger than the other shadows here, and accepted.
    assert result["ellipse_points"] > 20_000, result["ellipse_points"]
    assert result["ellipse_points"] < 2_097_152
    assert result["shadow_pixels"] > 0

    # A 64x64 window on the shadow itself: `get_pixels` caps a single read at 4096 px, so
    # the whole canvas cannot be asked for in one call at this size.
    cx, cy, _, _ = result["shadow_ellipse"]
    x0 = max(0, min(512 - 64, cx - 32))
    y0 = max(0, min(256 - 64, cy - 32))
    shadow = inspect.get_pixels(name, x0, y0, 64, 64, layer=result["layer"])["pixels"]
    drawn = [p for row in shadow for p in row if not p.lower().endswith("00")]
    assert drawn, "the window should land on the shadow"
    assert quality.palette_conformance(shadow, GROUND) == 1.0


def test_a_penumbra_longer_than_the_ramp_is_refused_not_flattened(request):
    """Each pixel of penumbra is one ramp step, so the ramp has to have them.

    Clamping the outer rings onto the last entry would draw a flat band of one colour and
    report it as a soft edge, which is invisible in the result.
    """
    name = _scene(request)
    with pytest.raises(ValidationFailed, match="needs 4 ramp steps") as exc:
        effects.cast_shadow(name, "ball", GROUND[:3], softness=3)
    assert "Lower softness to 2" in str(exc.value)

    # And the largest penumbra the ramp can express is accepted.
    result = effects.cast_shadow(name, "ball", GROUND[:3], softness=2)
    assert len({p[:7] for p in _cells(name, result["layer"]).values()}) == 3


def test_cast_shadow_rejects_arguments_that_cannot_mean_anything(request):
    name = _scene(request)
    with pytest.raises(ValidationFailed, match="at least 2 colours"):
        effects.cast_shadow(name, "ball", ["#000000"])
    with pytest.raises(ValidationFailed, match="light_height"):
        effects.cast_shadow(name, "ball", GROUND, light_height=0.0)
    with pytest.raises(ValidationFailed, match="light_height"):
        effects.cast_shadow(name, "ball", GROUND, light_height=1.5)
    with pytest.raises(ValidationFailed, match="softness"):
        effects.cast_shadow(name, "ball", GROUND, softness=99)
    with pytest.raises(ValidationFailed, match="opacity"):
        effects.cast_shadow(name, "ball", GROUND, opacity=999)
    with pytest.raises(ValidationFailed, match="new_layer"):
        effects.cast_shadow(name, "ball", GROUND, new_layer="   ")


# ---------------------------------------------------------------------------- glow
def test_a_glow_stays_on_the_palette(request):
    """The acceptance criterion: conformance stays at 1.0 when given a ramp."""
    name = _bare_ball(request)
    result = effects.glow(name, GROUND, radius=3)

    assert result["glow_pixels"] > 0
    halo = inspect.get_pixels(name, 0, 0, SIZE, SIZE, layer=result["layer"])["pixels"]
    assert quality.palette_conformance(halo, GROUND) == 1.0
    # And the composite, which is what actually gets exported.
    whole = inspect.get_pixels(name, 0, 0, SIZE, SIZE)["pixels"]
    assert quality.palette_conformance(whole, [*GROUND, *BODY]) == 1.0


def test_a_glow_steps_down_the_ramp_as_it_goes_out(request):
    """Several rings, each a step further down, rather than one flat ring."""
    name = _bare_ball(request)
    result = effects.glow(name, GROUND, radius=3, falloff="linear", dither_edge=False)

    assert result["rings"] == lighting.glow_rings(3, len(GROUND), "linear")
    assert all(count > 0 for count in result["per_ring"]), result["per_ring"]

    cells = _cells(name, result["layer"])
    used = {p[:7] for p in cells.values()}
    expected = {GROUND[step - 1].lower() for step in result["rings"]}
    assert used == expected, (used, expected)


def test_the_ring_touching_the_artwork_is_the_brightest(request):
    name = _bare_ball(request)
    result = effects.glow(name, GROUND, radius=3, dither_edge=False)
    cells = _cells(name, result["layer"])

    # The pixel immediately left of the ball's leftmost column is ring 1.
    inner = cells[(BALL_CX - BALL_R - 1, BALL_CY)]
    assert inner[:7] == GROUND[-1].lower(), inner


def test_dithering_the_outer_edge_thins_it_rather_than_fading_its_colour(request):
    """A fade in coverage, not in alpha, so every drawn pixel is still a ramp step."""
    solid = _bare_ball(request, "_solid")
    dithered = _bare_ball(request, "_dithered")
    a = effects.glow(solid, GROUND, radius=3, dither_edge=False)
    b = effects.glow(dithered, GROUND, radius=3, dither_edge=True)

    assert b["per_ring"][-1] < a["per_ring"][-1]
    assert b["per_ring"][:-1] == a["per_ring"][:-1], "only the outer ring is thinned"

    halo = inspect.get_pixels(dithered, 0, 0, SIZE, SIZE, layer=b["layer"])["pixels"]
    assert quality.palette_conformance(halo, GROUND) == 1.0
    alphas = {p[7:9] for row in halo for p in row if not p.lower().endswith("00")}
    assert alphas == {"ff"}, f"the fade must not be partial alpha: {alphas}"


def test_quadratic_falloff_keeps_a_hotter_core_than_linear(request):
    a = _bare_ball(request, "_lin")
    b = _bare_ball(request, "_quad")
    linear = effects.glow(a, GROUND, radius=4, falloff="linear")
    quadratic = effects.glow(b, GROUND, radius=4, falloff="quadratic")

    assert quadratic["rings"] != linear["rings"]
    assert all(
        q <= ln for q, ln in zip(quadratic["rings"], linear["rings"], strict=True)
    )


def test_a_glow_never_paints_over_the_subject(request):
    """So a body blocks the halo of a gem inside it, and the artwork stays crisp."""
    name = _bare_ball(request)
    subject = _cells(name, "Layer 1")
    result = effects.glow(name, GROUND, radius=3)

    halo = _cells(name, result["layer"])
    overlap = set(halo) & set(subject)
    assert not overlap, f"the glow covered {len(overlap)} pixels of the subject"
    assert _cells(name, "Layer 1") == subject, "the subject's cel must be untouched"


def test_base_color_scopes_the_glow_to_one_material(request):
    """A gem glows; the hand holding it does not."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    drawing.draw_rectangle(name, 4, 4, 10, 10, BODY[1], filled=True)
    drawing.draw_rectangle(name, 24, 24, 6, 6, "#39d7c0", filled=True)

    whole = effects.glow(name, GROUND, radius=2, new_layer="all")
    gem = effects.glow(name, GROUND, radius=2, base_color="#39d7c0",
                       tolerance=10, new_layer="gem")

    assert gem["seed_pixels"] < whole["seed_pixels"]
    assert gem["glow_pixels"] < whole["glow_pixels"]
    # Everything the scoped glow drew is near the gem, not near the block.
    for x, y in _cells(name, "gem"):
        assert x > 18 and y > 18, f"the scoped glow reached {(x, y)}"


def test_the_glow_sits_below_the_subject_in_the_stack(request):
    name = _bare_ball(request)
    effects.glow(name, GROUND, radius=2)
    order = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    assert order.index("glow") < order.index("Layer 1"), order


def test_deleting_the_layer_removes_the_glow(request):
    name = _bare_ball(request)
    before = _cells(name)
    effects.glow(name, GROUND, radius=3)
    assert _cells(name) != before

    layers.remove_layer(name, "glow")
    assert _cells(name) == before


def test_nothing_matching_base_color_is_refused(request):
    name = _bare_ball(request)
    with pytest.raises(AsepriteError, match="No pixel matched base_color"):
        effects.glow(name, GROUND, base_color="#00ff00", tolerance=1)


def test_a_glow_with_nowhere_to_go_is_refused(request):
    """A subject filling the canvas leaves no room, which is not a success."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 8)
    drawing.draw_rectangle(name, 0, 0, 8, 8, BODY[3], filled=True)

    with pytest.raises(AsepriteError, match="nowhere to go"):
        effects.glow(name, GROUND, radius=2)


def test_an_empty_layer_cannot_glow(request):
    name = _bare_ball(request)
    layers.add_layer(name, "blank")
    with pytest.raises(AsepriteError, match="nothing to glow around"):
        effects.glow(name, GROUND, layer="blank")


def test_glowing_the_same_layer_and_frame_twice_is_refused(request):
    """Two halos composited into one cel are a picture neither call describes.

    This used to be stated about the layer and is stated about the cel now, which is the
    narrowing that lets one glow layer hold a cel per frame of an animation. The second
    call here is the same layer *and* the same frame, so it is still refused.
    """
    name = _bare_ball(request)
    effects.glow(name, GROUND, radius=2)
    with pytest.raises(AsepriteError, match="already has a cel on frame 1"):
        effects.glow(name, GROUND, radius=2)


def test_glow_rejects_arguments_that_cannot_mean_anything(request):
    name = _bare_ball(request)
    with pytest.raises(ValidationFailed, match="at least 2 colours"):
        effects.glow(name, ["#000000"])
    with pytest.raises(ValidationFailed, match="falloff"):
        effects.glow(name, GROUND, falloff="gaussian")
    with pytest.raises(ValidationFailed, match="radius"):
        effects.glow(name, GROUND, radius=0)
    with pytest.raises(ValidationFailed, match="radius"):
        effects.glow(name, GROUND, radius=9999)
    with pytest.raises(ValidationFailed, match="tolerance"):
        effects.glow(name, GROUND, tolerance=-1)
    with pytest.raises(ValidationFailed, match="new_layer"):
        effects.glow(name, GROUND, new_layer=" ")


# ------------------------------------------------- a background cannot cast a shadow
def _background_ball(request, suffix: str = "", height: int = SIZE) -> str:
    """A ball on the sprite's Background layer, which is opaque and fills the canvas."""
    name = f"fx/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, SIZE, height)
    drawing.draw_ellipse(name, BALL_CX, BALL_CY, BALL_R, BALL_R, BODY[3], filled=True)
    sprite.convert_layer_to_background(name, "Layer 1")
    return name


def test_a_background_subject_is_refused_for_having_no_silhouette(request):
    """A background fills the canvas, so the measured box is the canvas and the
    projection degenerates. What came out of this before was a confident success: an
    ellipse centred on the bottom row, cast from the whole canvas as a silhouette."""
    name = _background_ball(request)

    with pytest.raises(AsepriteError, match="cannot cast a shadow") as exc:
        effects.cast_shadow(name, "Background", GROUND)

    message = str(exc.value)
    assert "silhouette" in message
    assert "convert_background_to_layer" in message


def test_the_background_refusal_comes_before_the_light_height_message(request):
    """On a taller canvas the degenerate projection overflowed the canvas check instead,
    and the message named light_height: a parameter that was never the problem."""
    name = _background_ball(request, "_tall", height=90)

    with pytest.raises(AsepriteError) as exc:
        effects.cast_shadow(name, "Background", GROUND)

    assert "cannot cast a shadow" in str(exc.value)
    assert "light_height" not in str(exc.value), "the wrong parameter was being named"


def test_a_background_is_still_a_perfectly_good_ground(request):
    """The refusal is about the subject. An opaque background is exactly what a floor is,
    so clipping a shadow to one has to keep working."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    layers.rename_layer(name, "Layer 1", "floor")
    layers.add_layer(name, "ball")
    drawing.draw_ellipse(name, BALL_CX, BALL_CY, BALL_R, BALL_R, BODY[3], filled=True,
                         layer="ball")
    sprite.convert_layer_to_background(name, "floor")

    result = effects.cast_shadow(name, "ball", GROUND, ground_layer="Background")

    assert result["shadow_pixels"] > 0
    assert result["clipped_pixels"] == 0, "a background covers the canvas"


# ------------------------------------------- what the render actually shows of a floor
def _grouped_scene(request) -> str:
    """The same ball and floor, with the floor inside a group that can be hidden."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, SIZE, SIZE)
    layers.rename_layer(name, "Layer 1", "ball")
    layers.add_group_layer(name, "scenery")
    layers.add_layer(name, "floor", group="scenery")
    drawing.draw_rectangle(name, 0, 28, SIZE, SIZE - 28, GROUND[2], filled=True,
                           layer="floor")
    drawing.draw_ellipse(name, BALL_CX, BALL_CY, BALL_R, BALL_R, BODY[3], filled=True,
                         layer="ball")
    return name


def test_a_hidden_ground_layer_is_reported_rather_than_refused(request):
    """Drawn pixels are drawn pixels, so the clip is still answerable and the shadow is
    still drawn; what was missing was any sign that the floor is not on screen."""
    name = _scene(request)
    layers.set_layer_properties(name, "floor", visible=False)

    result = effects.cast_shadow(name, "ball", GROUND, ground_layer="floor")

    assert result["shadow_pixels"] > 0
    assert result["ground_layer"] == "floor"
    assert result["ground_layer_visible"] is False
    notes = " ".join(result["warnings"])
    assert "floor" in notes and "hidden" in notes, notes


def test_a_ground_layer_inside_a_hidden_group_is_reported_too(request):
    """Aseprite reports isVisible per layer, so this floor's own flag is on while nothing
    of it reaches the render. The note has to name the group, which is what to unhide."""
    name = _grouped_scene(request)
    layers.set_layer_properties(name, "scenery", visible=False)

    result = effects.cast_shadow(name, "ball", GROUND, ground_layer="floor")

    assert result["shadow_pixels"] > 0
    assert result["ground_layer_visible"] is False
    assert result["ground_layer_hidden"] == ["scenery"]
    assert "scenery" in " ".join(result["warnings"])


def test_a_part_transparent_ground_layer_names_its_opacity(request):
    name = _scene(request)
    layers.set_layer_properties(name, "floor", opacity=64)

    result = effects.cast_shadow(name, "ball", GROUND, ground_layer="floor")

    assert result["ground_layer_visible"] is True
    assert result["ground_layer_opacity"] == 64
    assert "64" in " ".join(result["warnings"])


def test_a_visible_opaque_ground_layer_is_worth_saying_nothing_about(request):
    """The reporting has to be quiet in the ordinary case, or it is noise."""
    name = _scene(request)

    result = effects.cast_shadow(name, "ball", GROUND, ground_layer="floor")

    assert result["ground_layer_visible"] is True
    assert result["ground_layer_opacity"] == 255
    assert "ground_layer_hidden" not in result
    assert "warnings" not in result


def test_no_ground_layer_named_means_nothing_is_reported_about_one(request):
    """The keys are a measurement of the layer that was consulted, so with none named
    there is nothing to measure and nothing to say."""
    result = effects.cast_shadow(_bare_ball(request), "Layer 1", GROUND)

    assert "ground_layer" not in result
    assert "ground_layer_visible" not in result
    assert "warnings" not in result


@pytest.mark.pure
def test_a_floor_the_render_shows_in_full_earns_no_note():
    assert effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": True,
        "ground_layer_opacity": 255,
    }) == []


@pytest.mark.pure
def test_nothing_is_said_when_no_ground_layer_was_consulted():
    assert effects._ground_layer_notes({"ok": True, "shadow_pixels": 12}) == []


@pytest.mark.pure
def test_a_hidden_floor_note_names_the_layer_and_what_to_do():
    notes = effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": False,
        "ground_layer_opacity": 255, "ground_layer_hidden": ["floor"],
    })
    assert len(notes) == 1
    assert "'floor' is hidden" in notes[0]
    assert "set_layer_properties" in notes[0]


@pytest.mark.pure
def test_a_floor_hidden_by_its_group_blames_the_group():
    notes = effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": False,
        "ground_layer_opacity": 255, "ground_layer_hidden": ["scenery"],
    })
    assert len(notes) == 1
    assert "group 'scenery'" in notes[0]
    assert "own flag is on" in notes[0], "unhiding the layer itself would not help"


@pytest.mark.pure
def test_a_floor_hidden_twice_over_says_so_once():
    notes = effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": False,
        "ground_layer_opacity": 255, "ground_layer_hidden": ["floor", "scenery"],
    })
    assert len(notes) == 1
    assert "'floor'" in notes[0] and "'scenery'" in notes[0]


@pytest.mark.pure
def test_an_opacity_of_zero_reads_as_hidden_rather_than_as_faint():
    notes = effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": True,
        "ground_layer_opacity": 0,
    })
    assert len(notes) == 1
    assert "opacity 0" in notes[0]
    assert "nothing" in notes[0]


@pytest.mark.pure
def test_a_faint_floor_note_quotes_the_opacity_it_found():
    notes = effects._ground_layer_notes({
        "ground_layer": "floor", "ground_layer_visible": True,
        "ground_layer_opacity": 95,
    })
    assert len(notes) == 1
    assert "95" in notes[0]


# -------------------------------------------- remove_stray_pixels: the erasing mode
DIRT = "#ff00ff"
ART = "#6b4a2f"
BLOCK = 16 * 16


def _dirty_block(request, suffix: str = "", dirt: list[dict] | None = None) -> str:
    """A block of art with dirt floating outside it on empty canvas.

    The default dirt is the issue's own example: two lone pixels, each with nothing but
    transparency around it, which is what an effects pass leaves outside the shape.
    """
    name = f"fx/{request.node.name}{suffix}.aseprite"
    sprite.create_sprite(name, 32, 32)
    drawing.draw_rectangle(name, 8, 8, 16, 16, ART, filled=True)
    drawing.draw_pixels(name, dirt or [{"x": 2, "y": 2}, {"x": 29, "y": 3}], DIRT)
    return name


def _drawn(name: str) -> int:
    return inspect.assess_sprite(name)["metrics"]["drawn_pixels"]


def test_dirt_on_empty_canvas_is_left_alone_by_default(request):
    """The default cannot change: not changing the silhouette is the tool's promise."""
    name = _dirty_block(request)

    result = effects.remove_stray_pixels(name)

    assert result["replaced"] == 0
    assert "erased" not in result, "a count for work nobody asked for is misleading"
    assert _drawn(name) == BLOCK + 2


def test_erase_isolated_takes_the_dirt_and_counts_it_apart_from_replaced(request):
    """The two counts are different promises: one keeps the silhouette, one changes it."""
    name = _dirty_block(request)

    result = effects.remove_stray_pixels(name, erase_isolated=True)

    assert result["erased"] == 2
    assert result["erased_clusters"] == 2
    assert result["replaced"] == 0, "neither pixel had a colour to take"
    assert _drawn(name) == BLOCK
    assert inspect.assess_sprite(name)["metrics"]["isolated_pixels"] == 0


def test_erasing_leaves_the_art_to_the_replacement_rule(request):
    """Inside the shape the old answer is still the right one: a stray takes the colour
    around it, because the replacement comes from the ramp already next to it."""
    name = _dirty_block(request)
    drawing.draw_pixels(name, [{"x": 12, "y": 12}], BODY[4])

    result = effects.remove_stray_pixels(name, erase_isolated=True)

    assert result["replaced"] == 1
    assert result["erased"] == 2
    assert _drawn(name) == BLOCK, "the block kept every pixel it had"
    assert inspect.get_pixels(name, 12, 12, 1, 1)["pixels"][0][0].lower() \
        .startswith(ART), "the interior stray was repainted, not erased"


def test_a_protected_colour_is_not_erased_either(request):
    """A one-pixel spark floating clear of the art is isolated by this definition and is
    meant to be there, so naming its colour has to stop the erasing too."""
    name = _dirty_block(request)

    result = effects.remove_stray_pixels(name, erase_isolated=True, protect=[DIRT])

    assert result["erased"] == 0
    assert _drawn(name) == BLOCK + 2


def test_a_two_pixel_speck_needs_min_cluster(request):
    """Neither pixel of a pair is isolated by the single-pixel rule: each has the other
    for company, which is why dirt in twos survived both the old tool and the new flag."""
    name = _dirty_block(request, dirt=[{"x": 2, "y": 2}, {"x": 3, "y": 2}])

    assert effects.remove_stray_pixels(name, erase_isolated=True)["erased"] == 0
    assert _drawn(name) == BLOCK + 2

    result = effects.remove_stray_pixels(name, erase_isolated=True, min_cluster=2)

    assert result["erased"] == 2
    assert result["erased_clusters"] == 1, "one speck, not two pixels of dirt"
    assert _drawn(name) == BLOCK


def test_a_cluster_one_pixel_bigger_than_the_setting_survives(request):
    """The bound is exact, so a three-pixel mark is art at min_cluster=2 and dirt at 3."""
    mark = [{"x": 2, "y": 2}, {"x": 3, "y": 2}, {"x": 2, "y": 3}]
    small = _dirty_block(request, "_2", dirt=mark)
    large = _dirty_block(request, "_3", dirt=mark)

    assert effects.remove_stray_pixels(small, erase_isolated=True, min_cluster=2)["erased"] == 0
    assert effects.remove_stray_pixels(large, erase_isolated=True, min_cluster=3)["erased"] == 3


def test_the_artwork_is_never_a_cluster_however_high_min_cluster_goes(request):
    """What makes this safe: a cluster is what has nothing but transparency around it, and
    the art is connected to itself. Only the detached dirt can go."""
    name = _dirty_block(request)

    result = effects.remove_stray_pixels(name, erase_isolated=True, min_cluster=8)

    assert result["erased"] == 2
    assert _drawn(name) == BLOCK


def test_a_two_colour_speck_is_erased_rather_than_having_its_colours_traded(request):
    """Each pixel of a two-colour speck is a stray whose only opaque neighbour is the
    other one, so the replacement rule can only swap them: the same dirt in a different
    order, and not even the same twice, since a second pass swaps it back."""
    name = _dirty_block(request, dirt=[{"x": 2, "y": 2}])
    drawing.draw_pixels(name, [{"x": 3, "y": 2}], "#39d7c0")

    result = effects.remove_stray_pixels(name, erase_isolated=True, min_cluster=2)

    assert result["erased"] == 2
    assert result["replaced"] == 0, "the speck went instead of being recoloured"
    assert _drawn(name) == BLOCK


def test_erasing_the_same_dirt_twice_finds_none_the_second_time(request):
    """A cluster has no opaque neighbour by definition, so taking one away cannot isolate
    anything that was not isolated before."""
    name = _dirty_block(request)

    first = effects.remove_stray_pixels(name, erase_isolated=True, min_cluster=2)
    second = effects.remove_stray_pixels(name, erase_isolated=True, min_cluster=2)

    assert first["erased"] == 2
    assert second["erased"] == 0
    assert _drawn(name) == BLOCK


def test_a_sparse_dither_is_eaten_by_this_which_is_why_it_is_opt_in(request):
    """The case that keeps this off by default. A dither sparser than a checkerboard is
    disconnected, so every pixel of it is isolated and the whole pattern is dirt by this
    rule. The default leaves it, and `protect` names its colour when the flag is on."""
    name = f"fx/{request.node.name}.aseprite"
    sprite.create_sprite(name, 16, 16)
    spots = [{"x": x, "y": y} for y in range(2, 14, 2) for x in range(2, 14, 2)]
    drawing.draw_pixels(name, spots, DIRT)

    assert effects.remove_stray_pixels(name)["replaced"] == 0
    assert _drawn(name) == len(spots)

    assert effects.remove_stray_pixels(name, erase_isolated=True)["erased"] == len(spots)
    assert _drawn(name) == 0


@pytest.mark.pure
def test_min_cluster_without_erase_isolated_is_refused():
    """It has nothing to act on: the replacement rule is per pixel, not per cluster."""
    with pytest.raises(ValidationFailed, match="erase_isolated"):
        effects.remove_stray_pixels("unused.aseprite", min_cluster=2)


@pytest.mark.pure
def test_a_min_cluster_that_cannot_mean_anything_is_refused():
    with pytest.raises(ValidationFailed, match="min_cluster"):
        effects.remove_stray_pixels("unused.aseprite", erase_isolated=True, min_cluster=0)
    with pytest.raises(ValidationFailed, match="min_cluster"):
        effects.remove_stray_pixels("unused.aseprite", erase_isolated=True, min_cluster=99)


# ===== one effect layer, many frames ==================================================
# The refusal these tools owe a caller is about a *cel*: two effects composited into one
# cel are a picture neither call describes. It used to be enforced on the layer, and a
# layer spans every frame, so a four-frame flicker needed four glow layers holding one cel
# each and empty on the other three. A ten-frame effect needed ten.


def _animated_ball(request, frames_wanted: int = 3) -> str:
    name = _scene(request)
    for _ in range(frames_wanted - 1):
        frames.duplicate_frame(name, 1)
    return name


def test_one_glow_layer_carries_a_cel_on_every_frame(request):
    """The flickering-torch case, which is the reason this exists."""
    name = _animated_ball(request)

    for frame in (1, 2, 3):
        halo = effects.glow(name, BODY, radius=2, layer="ball", frame=frame,
                            new_layer="halo")
        assert halo["layer"] == "halo"
        assert halo["frame"] == frame

    stack = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    assert stack.count("halo") == 1, f"one layer, not one per frame: {stack}"

    for frame in (1, 2, 3):
        assert cels.get_cel(name, "halo", frame)["exists"] is True


def test_a_cast_shadow_layer_carries_a_cel_on_every_frame(request):
    name = _animated_ball(request)

    for frame in (1, 2, 3):
        effects.cast_shadow(name, "ball", GROUND, ground_layer="floor", frame=frame,
                            new_layer="under")

    stack = [lyr["name"] for lyr in inspect.get_sprite_info(name)["layers"]]
    assert stack.count("under") == 1, f"one layer, not one per frame: {stack}"


def test_the_same_layer_and_frame_twice_is_still_refused(request):
    """The guarantee that was always worth keeping, now stated about the cel."""
    name = _animated_ball(request)
    effects.glow(name, BODY, radius=2, layer="ball", frame=2, new_layer="halo")

    with pytest.raises(AsepriteError, match="already has a cel on frame 2"):
        effects.glow(name, BODY, radius=2, layer="ball", frame=2, new_layer="halo")


def test_an_effect_will_not_write_into_a_layer_holding_artwork(request):
    """Reuse is only for a layer this tool made, which it records on the layer itself."""
    name = _animated_ball(request)

    with pytest.raises(AsepriteError, match="was not created by this tool"):
        effects.glow(name, BODY, radius=2, layer="ball", frame=1, new_layer="floor")


def test_an_effect_layer_that_has_been_moved_is_not_reused(request):
    """`new_layer` is documented as sitting directly below `layer`, so it has to be."""
    name = _animated_ball(request)
    effects.glow(name, BODY, radius=2, layer="ball", frame=1, new_layer="halo")
    layers.move_layer(name, "halo", 1)

    with pytest.raises(AsepriteError, match="no longer directly below"):
        effects.glow(name, BODY, radius=2, layer="ball", frame=2, new_layer="halo")
