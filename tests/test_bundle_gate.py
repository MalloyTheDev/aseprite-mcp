"""The game asset bundle judges the art before it writes anything.

`export_game_asset_bundle` is the finishing step two workflows point at, and it used to
export whatever it was given. It now assesses every frame first, in one launch, and
refuses on a defect: a reading that scored as a fault against known-good and known-bad
sprites. Everything else is an observation, listed in the manifest and never blocking.

Most of this needs a real Aseprite (--run-aseprite). The frame sampling and the skip
past the pixel cap are `pure`, decided in Python before anything is launched.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import drawing, frames, inspect, sprite, workflow
from aseprite_mcp.tools.common import resolve_path

RAMP = ["#202020", "#606060", "#a0a0a0"]


def _square(name: str, *, count: int = 1, stray: str | None = None) -> str:
    """A 16x16 outlined square drawn only from RAMP, on `count` frames."""
    sprite.create_sprite(name, 16, 16, overwrite=True)
    drawing.draw_rectangle(name, 4, 4, 8, 8, RAMP[1], filled=True)
    drawing.draw_rectangle(name, 4, 4, 8, 8, RAMP[0])
    drawing.draw_pixels(name, [{"x": 6, "y": 6}], RAMP[2])
    if stray:
        drawing.draw_pixels(name, [{"x": 8, "y": 8}], stray)
    for _ in range(count - 1):
        frames.add_frame(name)
    return name


# --- decided before launch ---------------------------------------------------------


@pytest.mark.pure
def test_the_sample_is_bounded_and_keeps_both_ends():
    for count in range(1, 40):
        for budget in range(1, 45):
            chosen = inspect._spread(count, budget)
            case = (count, budget, chosen)
            assert chosen == sorted(set(chosen)), case
            assert 1 <= len(chosen) <= budget, case
            assert all(1 <= n <= count for n in chosen), case
            assert chosen[0] == 1, case
            if budget >= count:
                assert chosen == list(range(1, count + 1)), case
            elif budget >= 2:
                assert chosen[-1] == count, case


@pytest.mark.pure
def test_a_frame_past_the_cap_is_skipped_not_passed(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("Aseprite was launched for a frame too large to assess")
    monkeypatch.setattr(inspect, "run_lua", refuse)
    result = inspect.assess_frames("gate/huge.aseprite", frame_count=3, width=2048,
                                   height=2048)
    assert result["frames_assessed"] == [] and result["defects"] == []
    assert "no frame was judged" in result["skipped"]


# --- against Aseprite --------------------------------------------------------------


def test_an_off_ramp_pixel_refuses_the_bundle_and_writes_nothing():
    name = _square("gate/stray.aseprite", stray="#ff0080")
    with pytest.raises(ValidationFailed) as excinfo:
        workflow.export_game_asset_bundle(name, ramp=RAMP)
    message = str(excinfo.value)
    assert "frame 1: 1 of" in message and "off the declared ramp" in message
    assert "allow_defects=True" in message
    assert not resolve_path("stray_bundle/stray.png").exists()
    assert not resolve_path("stray_bundle/manifest.json").exists()


def test_allow_defects_bundles_and_records_them():
    name = _square("gate/waived.aseprite", stray="#ff0080")
    manifest = workflow.export_game_asset_bundle(name, ramp=RAMP, allow_defects=True)
    assert manifest["assessment"]["waived"] is True
    assert len(manifest["warnings"]) == 1
    assert manifest["warnings"][0].startswith("frame 1: 1 of")
    assert resolve_path("waived_bundle/waived.png").exists()


def test_a_clean_sprite_bundles_with_its_assessment():
    name = _square("gate/clean.aseprite", count=3)
    manifest = workflow.export_game_asset_bundle(name, ramp=RAMP)
    assessment = manifest["assessment"]
    assert assessment["frames_total"] == 3
    assert assessment["frames_assessed"] == [1, 2, 3]
    assert assessment["defects"] == [] and "waived" not in assessment
    assert manifest["warnings"] == []


def test_each_frame_is_judged_as_assess_sprite_judges_it():
    """The one-launch reader shares its encoder with assess_sprite and must agree with it."""
    name = "gate/moving.aseprite"
    sprite.create_sprite(name, 24, 24, overwrite=True)
    for number, x in enumerate((3, 8, 13), start=1):
        if number > 1:
            frames.add_frame(name)
            drawing.clear_layer(name, frame=number)
        drawing.draw_rectangle(name, x, 6, 8, 12, "#4060c0", filled=True, frame=number)
        drawing.draw_pixels(name, [{"x": x + 2, "y": 8}], "#ff0000", frame=number)

    found = inspect.assess_frames(name, frame_count=3, width=24, height=24)
    assert found["frames_assessed"] == [1, 2, 3]
    for number in (1, 2, 3):
        on_frame = {f["reading"] for f in found["defects"] + found["observations"]
                    if number in f["frames"]}
        assert on_frame == set(inspect.assess_sprite(name, frame=number)["readings"])


def test_past_the_pixel_budget_an_even_sample_is_judged(monkeypatch):
    monkeypatch.setattr(inspect, "MAX_ASSESS_PIXELS", 2 * 16 * 16)
    name = _square("gate/long.aseprite", count=5)
    found = inspect.assess_frames(name, frame_count=5, width=16, height=16)
    assert found["frames_total"] == 5
    assert found["frames_assessed"] == [1, 5]


def test_a_bundle_too_large_to_assess_says_so(monkeypatch):
    monkeypatch.setattr(inspect, "MAX_ASSESS_PIXELS", 1)
    name = _square("gate/unjudged.aseprite")
    manifest = workflow.export_game_asset_bundle(name)
    assert "no frame was judged" in manifest["assessment"]["skipped"]
    assert any(w.startswith("The art was not assessed") for w in manifest["warnings"])
