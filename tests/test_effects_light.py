"""Cast shadow and glow, tested against a real Aseprite.

Both exist because the same effect from an image editor takes the art off its palette, so
the assertion that matters in here is `palette_conformance`: a glow of interpolated
colours or a shadow made by multiplying alpha would look plausible in a preview and score
below 1.0 here. The geometry claims are checked for direction rather than for exact
sizes, since the sizes are the arithmetic that `test_lighting.py` already pins.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import lighting, quality
from aseprite_mcp.core.errors import AsepriteError, ValidationFailed
from aseprite_mcp.tools import drawing, effects, inspect, layers, sprite

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


def test_a_glow_layer_name_that_is_taken_is_refused(request):
    name = _bare_ball(request)
    effects.glow(name, GROUND, radius=2)
    with pytest.raises(AsepriteError, match="already exists"):
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
