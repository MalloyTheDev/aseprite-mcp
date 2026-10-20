"""The asset-spec loop, built and then checked: requires Aseprite (--run-aseprite).

`compare_to_built` is pure and well covered in test_asset_spec.py, which is on the
pure-only allowlist and so cannot build a sprite. That left the tool wrapping it,
`validate_asset_against_spec`, without a behavioural test of its own: the suite named it
once, to assert it carries `readOnlyHint`, and never called it. It is the loop closer,
the one tool whose job is to catch a build that drifted from what was declared, so "it
was never actually run" is the wrong state for it to be in.

What is only reachable here, rather than through `compare_to_built`: resolving the
spec's own `<name>.aseprite` when no filename is given, refusing an invalid spec before
opening anything, and refusing a sprite that is not there.

Each build gets its own name because `build_asset_from_spec` creates the sprite
no-clobber by design, so a spec cannot be rebuilt over itself.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core.errors import AsepriteMCPError, ValidationFailed
from aseprite_mcp.tools import asset_spec, layers, sprite, tags


def _spec(name: str) -> dict:
    return {
        "schema": "aseprite_mcp.asset_spec.v1",
        "name": name,
        "kind": "character",
        "canvas": {"width": 32, "height": 32},
        "layers": ["body", "details"],
        "animations": [{"name": "idle", "frame_count": 4}],
    }


@pytest.fixture
def build(request):
    """Build a fresh asset per call, named for the test, and hand back its spec."""
    made = []

    def _build(suffix: str = "") -> tuple[dict, str]:
        spec = _spec(f"{request.node.name}{suffix}".replace("[", "_").replace("]", ""))
        asset_spec.build_asset_from_spec(spec)
        made.append(spec)
        return spec, spec["name"] + ".aseprite"

    return _build


def test_a_sprite_built_from_the_spec_matches_it(build):
    """And says which fields it checked: "nothing was reported" and "nothing was
    checked" look alike otherwise, which is the failure this tool exists to stop."""
    spec, filename = build()
    result = asset_spec.validate_asset_against_spec(spec)

    assert result["ok"] is True and result["mismatches"] == []
    assert result["verifiable"] is True
    assert set(result["checked"]) == {"canvas", "layers", "animations"}
    assert result["sprite"].endswith(filename), "it defaulted to the spec's own filename"


def test_a_canvas_that_drifted_is_caught(build):
    spec, filename = build()
    sprite.resize_canvas(filename, 48, 48)

    result = asset_spec.validate_asset_against_spec(spec)
    assert result["ok"] is False
    assert [m["field"] for m in result["mismatches"]] == ["canvas"]
    assert result["mismatches"][0]["declared"] == "32x32"
    assert result["mismatches"][0]["observed"] == "48x48"


def test_a_missing_layer_is_caught_and_named(build):
    """Separately from the canvas, so a check that stopped working cannot hide behind
    another one still firing."""
    spec, filename = build()
    layers.remove_layer(filename, "details")

    result = asset_spec.validate_asset_against_spec(spec)
    assert [m["field"] for m in result["mismatches"]] == ["layers"]
    assert "details" in result["mismatches"][0]["detail"]


def test_an_animation_whose_tag_went_missing_is_caught(build):
    spec, filename = build()
    tags.remove_tag(filename, "idle")

    result = asset_spec.validate_asset_against_spec(spec)
    assert [m["field"] for m in result["mismatches"]] == ["tags"]
    assert "idle" in result["mismatches"][0]["detail"]


def test_a_drifted_build_is_told_what_to_do(build):
    spec, filename = build()
    sprite.resize_canvas(filename, 48, 48)

    actions = asset_spec.validate_asset_against_spec(spec)["suggested_next_actions"]
    assert any("build_asset_from_spec" in line for line in actions), actions


@pytest.mark.pure
def test_an_invalid_spec_is_refused_before_a_sprite_is_opened(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a sprite was opened for a spec that is not valid")
    monkeypatch.setattr(asset_spec.inspect, "get_sprite_info", refuse)

    with pytest.raises(ValidationFailed, match="Invalid asset spec"):
        asset_spec.validate_asset_against_spec({"schema": "aseprite_mcp.asset_spec.v1"})


def test_a_sprite_that_is_not_there_is_refused_by_name():
    with pytest.raises(AsepriteMCPError, match="spec_loop_absent"):
        asset_spec.validate_asset_against_spec(_spec("spec_loop_absent"))
