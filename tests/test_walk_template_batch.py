"""Aseprite-backed proof that batching the walk template preserved its behaviour.

`make_8_direction_walk_template` used to add one frame per Aseprite launch and re-read
the sprite after each one. It now builds the frames and tags as a single ordered
`apply_operations` batch. This file pins the refactor two ways:

* the sprite it produces is byte-identical to the one the per-frame loop produced
  (`_legacy_walk_template` below is a faithful replica of the old body); and
* the number of Aseprite launches tracks the number of batches, not the frame count.

These need a real Aseprite, so this file must stay OUT of conftest's
PURE_PYTHON_TESTS allowlist. The caps themselves are pre-flight and are tested
without Aseprite in test_limits.py.
"""

from aseprite_mcp.core import runner
from aseprite_mcp.tools import frames, inspect, sprite, tags, workflow

DIRS = ["N", "S"]
FPD = 2
DURATION = 120


def _legacy_walk_template(filename, frames_per_direction, frame_duration_ms, directions):
    """The pre-#59 body, verbatim in structure: two launches per frame."""
    dirs = directions
    total = frames_per_direction * len(dirs)
    info = inspect.get_sprite_info(filename)
    while info["frameCount"] < total:
        frames.add_frame(filename, frame_duration_ms, copy_from=1)
        info = inspect.get_sprite_info(filename)
    frames.set_all_frame_durations(filename, frame_duration_ms)
    for i, direction in enumerate(dirs):
        start = i * frames_per_direction + 1
        tags.add_tag(filename, direction, start, start + frames_per_direction - 1, "forward")


def _seed(name):
    """A small sprite with something on it, so the copied frames carry real pixels."""
    sprite.create_sprite(name, 8, 8, "rgb")
    from aseprite_mcp.tools import drawing

    drawing.draw_rectangle(name, 1, 1, 5, 5, "#3878c8", filled=True)
    return name


def test_batched_walk_template_is_byte_identical_to_the_per_frame_loop(tmp_path):
    old = _seed("wt/old.aseprite")
    new = _seed("wt/new.aseprite")

    _legacy_walk_template(old, FPD, DURATION, DIRS)
    workflow.make_8_direction_walk_template(
        new, frames_per_direction=FPD, frame_duration_ms=DURATION, directions=list(DIRS)
    )

    from aseprite_mcp.tools.common import resolve_path

    old_bytes = resolve_path(old).read_bytes()
    new_bytes = resolve_path(new).read_bytes()
    assert new_bytes == old_bytes, "the batched template changed the saved sprite"


def test_batched_walk_template_reports_the_same_state():
    """Belt and braces on the byte comparison: the visible state matches too."""
    name = _seed("wt/state.aseprite")
    m = workflow.make_8_direction_walk_template(
        name, frames_per_direction=FPD, frame_duration_ms=DURATION, directions=list(DIRS)
    )
    info = inspect.get_sprite_info(name)
    assert info["frameCount"] == FPD * len(DIRS)
    assert [t["name"] for t in info["tags"]] == DIRS
    assert [(t["from"], t["to"]) for t in info["tags"]] == [(1, 2), (3, 4)]
    assert all(round(f["duration"] * 1000) == DURATION for f in info["frames"])
    assert m["animation"]["tags"] == DIRS


def test_launches_scale_with_batches_not_frames(monkeypatch):
    """The old loop cost two launches per frame; this counts the real launches."""
    name = _seed("wt/count.aseprite")
    seen = []
    real = runner.run_lua

    def counting_run_lua(body, args=None, timeout=None):
        seen.append(1)
        return real(body, args, timeout)

    for mod in (workflow.inspect, workflow.frames, workflow.batch):
        monkeypatch.setattr(mod, "run_lua", counting_run_lua)

    workflow.make_8_direction_walk_template(
        name, frames_per_direction=8, frame_duration_ms=DURATION,
        directions=["N", "E", "S", "W"]
    )
    # 32 frames. The old body would have launched 2 per frame (~65); the batched one
    # launches once for the opening frame count, once for the single batch, once for
    # the uniform durations, and once for the final manifest read.
    assert len(seen) == 4
    assert inspect.get_sprite_info(name)["frameCount"] == 32
