"""`scaffold_cycle`: the conventions it encodes, and the one-shot flag it has to get right.

Split in two deliberately. The conventions (frame counts, phase names, which kinds loop,
whether the timing curve is uniform) are pure arithmetic over the table in `workflow.py`
and run on CI with no editor, because a table nobody checks is a table that drifts. The
rest builds each cycle for real and reads the tags back **off the saved sprite**, because
`repeats` is the only place a file says "this plays once" and the claim is worthless if it
only ever existed in the manifest.

Why `repeats` is the load-bearing field rather than a cosmetic one: `validate_loop` sets
`tag_loops` from `tag.repeats == 0`, and a cycle's seam check reports a last frame
identical to the first as an error. Tag a death as a loop and the checker reports a
duplicated wrap frame on an animation that never wraps, which is
`test_validate_loop_only_checks_the_wrap_on_a_cycle` below.
"""

from __future__ import annotations

import pytest

from aseprite_mcp.core import timing
from aseprite_mcp.core.errors import ValidationFailed
from aseprite_mcp.tools import animation, frames, inspect, sprite, workflow

# What issue #91 records, written out here rather than read from the table under test:
# "idle 4 or 6, run 6 or 8, attack 5 to 7 one-shot, hurt 2 to 3, death 6 to 10", and a
# walk of 8 ("6 is the budget option; 4 only works mirrored for a side view").
CONVENTIONS = {
    "walk": (8, (4, 8), True),
    "run": (6, (6, 8), True),
    "idle": (4, (4, 6), True),
    "attack": (5, (5, 7), False),
    "hurt": (2, (2, 3), False),
    "death": (6, (6, 10), False),
}
LOOPS = [k for k, (_, _, loops) in CONVENTIONS.items() if loops]
ONE_SHOTS = [k for k, (_, _, loops) in CONVENTIONS.items() if not loops]

# The phase names each kind gets at its own default count, written out rather than asked
# of `workflow._phases`. The first version of `test_the_phase_tags_land_one_per_frame...`
# built its expectation by calling that function, and a planted `_phases` returning
# `pose1..poseN` passed it: both sides of the comparison were wrong together. One frame
# per named pose at the default count is the claim, so the names belong here.
PHASES = {
    "walk": ["contactL", "downL", "passL", "upL",
             "contactR", "downR", "passR", "upR"],
    "run": ["contactL", "downL", "airL", "contactR", "downR", "airR"],
    "idle": ["rest", "rise", "peak", "fall"],
    "attack": ["anticipation", "swing", "impact", "recoil", "recover"],
    "hurt": ["impact", "recover"],
    "death": ["impact", "stagger", "fall", "land", "settle", "still"],
}


# ===== the conventions, with no editor in the room ====================================


@pytest.mark.pure
def test_every_kind_defaults_to_the_count_the_convention_names():
    assert set(workflow._CYCLES) == set(CONVENTIONS)
    for kind, (default, span, _) in CONVENTIONS.items():
        spec = workflow._CYCLES[kind]
        assert spec.default == default, kind
        assert spec.convention == span, kind
        low, high = span
        assert low <= spec.default <= high, f"{kind}'s own default is out of its range"


@pytest.mark.pure
def test_attack_hurt_and_death_are_one_shots_and_the_cycles_are_not():
    """The acceptance criterion, at the level of the table that decides it."""
    for kind in ONE_SHOTS:
        assert workflow._CYCLES[kind].loops is False, f"{kind} must not be a loop"
    for kind in LOOPS:
        assert workflow._CYCLES[kind].loops is True, f"{kind} is a cycle"


@pytest.mark.pure
@pytest.mark.parametrize("kind", list(CONVENTIONS))
def test_each_kind_is_named_for_its_phases_not_numbered(kind):
    """The issue's own example for a walk: `walk_contactL`, `walk_downL` and so on."""
    default = CONVENTIONS[kind][0]
    assert workflow._phases(workflow._CYCLES[kind], default) == PHASES[kind]


@pytest.mark.pure
def test_the_budget_counts_keep_both_legs_symmetric():
    """6 drops the `up` pose rather than giving one leg more poses than the other."""
    assert workflow._phases(workflow._CYCLES["walk"], 6) == [
        "contactL", "downL", "passL", "contactR", "downR", "passR",
    ]
    # And a run at 8 gains the push-off rather than losing its flight pose.
    assert workflow._phases(workflow._CYCLES["run"], 8) == [
        "contactL", "downL", "pushL", "airL", "contactR", "downR", "pushR", "airR",
    ]


@pytest.mark.pure
@pytest.mark.parametrize("kind", list(CONVENTIONS))
def test_every_count_in_a_convention_names_its_phases(kind):
    """One phase per frame, all named, all distinct, at every count the issue allows.

    Distinctness is the one that matters beyond tidiness: each phase becomes a tag, and
    Aseprite will hold two tags with one name without complaining, after which neither can
    be addressed by it.
    """
    spec = workflow._CYCLES[kind]
    low, high = spec.convention
    for count in range(low, high + 1):
        phases = workflow._phases(spec, count)
        assert len(phases) == count, (kind, count)
        assert len(set(phases)) == count, f"{kind} at {count} repeats a phase: {phases}"
        assert not any(p.startswith("pose") for p in phases), (
            f"{kind} at {count} is inside its convention and still fell back to numbered "
            f"poses: {phases}"
        )


@pytest.mark.pure
def test_a_count_past_the_table_falls_back_to_numbered_poses():
    """Allowed, but visibly unnamed, which is what the out-of-convention warning says."""
    phases = workflow._phases(workflow._CYCLES["walk"], 12)
    assert len(phases) == 12 and len(set(phases)) == 12
    assert "pose5L" in phases and "pose6R" in phases


@pytest.mark.pure
def test_a_shorter_take_loses_its_tail_not_its_impact():
    """Below the convention the tail is dropped, because the tail is the recovery."""
    assert workflow._phases(workflow._CYCLES["death"], 4) == [
        "impact", "stagger", "fall", "land",
    ]
    assert workflow._phases(workflow._CYCLES["attack"], 3) == [
        "anticipation", "swing", "impact",
    ]


@pytest.mark.pure
def test_no_kind_starts_out_uniformly_timed():
    """"Non-uniform starting durations" asserted as arithmetic, not as a curve name.

    `flat` would satisfy "has a curve" and give every frame the same duration, which is
    the placeholder the issue is asking these scaffolds to stop shipping.
    """
    for kind, spec in workflow._CYCLES.items():
        plan = timing.plan(
            list(range(1, spec.default + 1)),
            curve=spec.curve,
            base_ms=spec.base_ms,
            hold_frames=[spec.default] if spec.hold_last else None,
            snap_frames=[1] if spec.snap_first else None,
        )
        assert len(set(plan["durations_ms"])) > 1, (
            f"{kind} starts out uniform at {plan['durations_ms']}"
        )


@pytest.mark.pure
def test_an_unknown_kind_names_the_six_that_exist():
    with pytest.raises(ValidationFailed, match="bad value for 'kind'") as exc:
        workflow.scaffold_cycle("nope.aseprite", "jump")
    for kind in CONVENTIONS:
        assert kind in str(exc.value)


@pytest.mark.pure
def test_a_frameless_cycle_is_refused_before_aseprite_is_launched():
    """Pre-flight: a bad count never reaches the editor, so this runs on CI."""
    with pytest.raises(ValidationFailed, match="frames"):
        workflow.scaffold_cycle("nope.aseprite", "walk", frames=0)
    with pytest.raises(ValidationFailed, match="frames"):
        workflow.scaffold_cycle("nope.aseprite", "walk", frames=10_000)


@pytest.mark.pure
def test_the_two_older_scaffolds_are_still_registered():
    """`scaffold_cycle` lands beside them rather than over them.

    #91 says it "replaces" the two, but removing a registered tool is a breaking change
    for every caller of it, so that is the owner's call and not this change's. Pinned so
    the replacement cannot happen by accident.
    """
    import aseprite_mcp.server  # noqa: F401  importing registers every tool
    from aseprite_mcp.app import mcp

    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {"scaffold_cycle", "make_4_frame_idle_animation",
            "make_8_direction_walk_template"} <= names


# ===== and now for real, with the tags read back off the file =========================


@pytest.fixture(scope="module")
def built():
    """Every kind scaffolded once: the manifest, and a fresh read of the saved sprite.

    Module-scoped because each scaffold is fourteen-odd Aseprite launches (about three
    seconds) and nothing below mutates what it is handed.
    """
    out = {}
    for kind in CONVENTIONS:
        name = f"cyc/{kind}.aseprite"
        sprite.create_sprite(name, 16, 16, "rgb", overwrite=True)
        manifest = workflow.scaffold_cycle(name, kind)
        out[kind] = (name, manifest, inspect.get_sprite_info(name))
    return out


@pytest.mark.parametrize("kind", list(CONVENTIONS))
def test_each_kind_scaffolds_its_conventional_frame_count(built, kind):
    _name, manifest, info = built[kind]
    expected = CONVENTIONS[kind][0]
    assert info["frameCount"] == expected, f"{kind} should be {expected} frames"
    assert manifest["kind"] == "animation_cycle"
    assert manifest["animation"]["frames"] == list(range(1, expected + 1))
    assert manifest["warnings"] == [], f"{kind} at its own default warned: {manifest}"


@pytest.mark.parametrize("kind", ONE_SHOTS)
def test_an_attack_a_hurt_and_a_death_are_tagged_as_one_shots(built, kind):
    """The acceptance criterion, read off the saved file rather than off the manifest.

    Every tag, not only the whole-cycle one: `repeats=0` on a per-phase tag says "hold
    this pose forever", which on a death is exactly the wrong claim.
    """
    _name, manifest, info = built[kind]
    assert info["tags"], f"{kind} produced no tags at all"
    for tag in info["tags"]:
        assert tag["repeats"] == 1, (
            f"{kind}'s tag {tag['name']!r} has repeats={tag['repeats']}, and 0 means "
            f"'play forever'"
        )
    assert manifest["animation"]["loops"] is False
    assert manifest["animation"]["repeats"] == 1


@pytest.mark.parametrize("kind", LOOPS)
def test_a_walk_a_run_and_an_idle_are_tagged_as_loops(built, kind):
    _name, manifest, info = built[kind]
    assert info["tags"]
    for tag in info["tags"]:
        assert tag["repeats"] == 0, (
            f"{kind}'s tag {tag['name']!r} has repeats={tag['repeats']}, so it stops "
            f"instead of cycling"
        )
    assert manifest["animation"]["loops"] is True


@pytest.mark.parametrize("kind", list(CONVENTIONS))
def test_the_phase_tags_land_one_per_frame_on_the_saved_sprite(built, kind):
    """A tag for the whole cycle plus one per phase, each on the frame it names."""
    _name, manifest, info = built[kind]
    count = CONVENTIONS[kind][0]
    by_name = {t["name"]: t for t in info["tags"]}

    assert by_name[kind]["from"] == 1 and by_name[kind]["to"] == count
    expected = [f"{kind}_{phase}" for phase in PHASES[kind]]
    assert sorted(by_name) == sorted([kind, *expected]), f"{kind} tags: {sorted(by_name)}"
    for number, tag_name in enumerate(expected, start=1):
        tag = by_name[tag_name]
        assert tag["from"] == number and tag["to"] == number, (kind, tag_name, tag)
    # And the manifest's own phase list agrees with the file, frame for frame.
    assert [p["tag"] for p in manifest["animation"]["phases"]] == expected


@pytest.mark.parametrize("kind", list(CONVENTIONS))
def test_the_durations_in_the_file_are_not_uniform(built, kind):
    """Read off the frames, because `apply_timing_curve` is the thing being trusted here."""
    _name, manifest, info = built[kind]
    written = [round(f["duration"] * 1000) for f in info["frames"]]
    assert len(set(written)) > 1, f"{kind} was saved with uniform timing: {written}"
    assert written == manifest["animation"]["durations_ms"], (
        f"{kind}'s manifest claims {manifest['animation']['durations_ms']} and the file "
        f"says {written}"
    )
    assert sum(written) == manifest["animation"]["total_duration_ms"]


def test_validate_loop_only_checks_the_wrap_on_a_cycle(built):
    """What the one-shot flag is *for*, demonstrated rather than asserted about a number.

    Every frame of a fresh scaffold is a copy of frame 1, so the first and last frames are
    identical in both cases. For a cycle that is a real fault, a wrap showing one image
    twice, and `validate_loop` says so; for a one-shot there is no wrap, and it must not.
    Tagging a death as a loop would make the checker invent that error.
    """
    def wrap_errors(kind):
        name = built[kind][0]
        report = animation.validate_loop(name, tag=kind)["validation"]
        return [e for e in report["errors"] if "wrap" in e]

    assert wrap_errors("walk"), "a cycle's duplicated seam frame is an error"
    assert wrap_errors("death") == [], (
        "a one-shot has no wrap, so its last frame matching its first is not a seam fault"
    )


def test_a_cycle_scaffold_reports_no_pixels_because_it_writes_none(built):
    """#201's other half: the harness's report is absent, never a zero.

    Frames, tags and durations never reach `img_set`, so there is nothing to count, and a
    `pixels_written: 0` here would be a claim about pixels that were never in play.
    """
    for kind, (_name, manifest, _info) in built.items():
        for key in ("pixels_written", "pixels_outside_selection", "selection_applied"):
            assert key not in manifest, f"{kind} reported {key} without writing a pixel"


def test_a_tag_that_already_exists_is_refused_rather_than_duplicated():
    """Aseprite allows two tags with one name, and then neither can be addressed by it."""
    name = "cyc/clash.aseprite"
    sprite.create_sprite(name, 8, 8, "rgb", overwrite=True)
    workflow.scaffold_cycle(name, "hurt")
    before = sorted(t["name"] for t in inspect.get_sprite_info(name)["tags"])

    with pytest.raises(ValidationFailed, match="already has tag"):
        workflow.scaffold_cycle(name, "hurt")

    assert sorted(t["name"] for t in inspect.get_sprite_info(name)["tags"]) == before


def durations(name: str) -> list[int]:
    return [round(f["duration"] * 1000)
            for f in inspect.get_sprite_info(name)["frames"]]


def test_frames_past_the_cycle_are_left_alone_and_the_manifest_says_so():
    """A 2-frame hurt on a 5-frame sprite tags two frames and admits to the other three."""
    name = "cyc/extra.aseprite"
    sprite.create_sprite(name, 8, 8, "rgb", overwrite=True)
    for _ in range(4):
        frames.add_frame(name, 500, copy_from=1)
    before = durations(name)
    manifest = workflow.scaffold_cycle(name, "hurt")

    info = inspect.get_sprite_info(name)
    assert info["frameCount"] == 5, "existing frames must survive"
    assert any("frames 3-5" in w for w in manifest["warnings"]), manifest["warnings"]
    for tag in info["tags"]:
        assert tag["to"] <= 2, f"{tag['name']} reaches frame {tag['to']}"
    # The frames it did not tag kept whatever duration they already had: asserted against
    # what was measured before the call, not against a literal, because
    # `add_frame(copy_from=1)` inserts rather than appends and the set-up's own durations
    # therefore end up in an order a literal would have to encode.
    assert durations(name)[2:] == before[2:]
    assert durations(name)[:2] == manifest["animation"]["durations_ms"]


def test_inserting_frames_into_a_drawn_sprite_says_the_existing_ones_moved():
    """Measured: Aseprite's newFrame(n) inserts at n, so a copy does not append.

    One `add_frame(copy_from=1)` on a sprite holding a red frame 1 and a blue frame 2
    produces red, red, blue: the blue frame is still there and is no longer frame 2. That
    is `tools/frames.py` and `core/oplib.py` behaviour rather than this scaffold's, and a
    scaffold that quietly reordered a caller's drawn frames would be the worse of the two
    failures, so it is reported.
    """
    name = "cyc/drawn.aseprite"
    sprite.create_sprite(name, 4, 4, "rgb", overwrite=True)
    frames.add_frame(name, 100, copy_from=1)
    assert inspect.get_sprite_info(name)["frameCount"] == 2

    manifest = workflow.scaffold_cycle(name, "death")

    assert inspect.get_sprite_info(name)["frameCount"] == 6
    assert any("inserted at frame 1" in w for w in manifest["warnings"]), (
        manifest["warnings"]
    )


def test_an_odd_frame_count_says_which_frames_the_holds_landed_on():
    """Measured: `hold_extremes` holds frames 1 and count//2+1, which on a stepped kind
    is the second contact only when the count is even. A 5-frame walk holds frame 3
    (`passL`) while the contacts are 1 and 4, so the scaffold says so instead of leaving
    it to be discovered."""
    name = "cyc/odd.aseprite"
    sprite.create_sprite(name, 8, 8, "rgb", overwrite=True)
    manifest = workflow.scaffold_cycle(name, "walk", frames=5)

    assert any("odd count" in w for w in manifest["warnings"]), manifest["warnings"]
    roles = {p["phase"]: p["role"] for p in manifest["animation"]["phases"]}
    assert roles["contactL"] == "extreme"
    assert roles["passL"] == "extreme"  # the misalignment the warning is about
    assert roles["contactR"] == "passing"
