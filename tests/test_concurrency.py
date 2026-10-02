"""The Aseprite invocation lock, tested without launching Aseprite.

An Aseprite run is a read-modify-write over a whole sprite file, so two overlapping
runs on one file do not merely interleave: measured over eight trials of two concurrent
layer additions, three kept only one edit and five produced a file that no longer
decoded, while all eight reported success. The claims in `core.runner` are what stop
that, and these tests pin them at the seam rather than by racing the real editor (that
regression lives in `test_regressions.py`, behind --run-aseprite).

Two properties are pinned here and they pull in opposite directions, which is the point.
Runs that name one sprite must never overlap, and runs that name different sprites must
overlap. A file that asserted only the first would pass unchanged against a single
process-wide lock, and so could not tell a working optimisation from one that had stopped
working; a file that asserted only the second would not notice the corruption coming
back. Every test below therefore says which direction it is guarding.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import threading
import time
from functools import partial

import pytest

from aseprite_mcp.core import runner
from aseprite_mcp.core.errors import LuaToolError
from aseprite_mcp.tools import common

# Long enough that an implementation which fails to serialize is certain to be caught,
# and that four threads started together are all inside the guarded region at once.
DWELL = 0.2


@pytest.fixture(autouse=True)
def _fresh_recording():
    """One test's recorded paths must not be another's.

    The recording is a ContextVar, and the main thread's context outlives a test. Under a
    real server each call arrives with its own copy of the context (anyio copies it into
    the worker thread), so resetting here reproduces the per-call isolation the runner
    relies on rather than papering over its absence.
    """
    token = runner._RECORDED_PATHS.set(None)
    try:
        yield
    finally:
        runner._RECORDED_PATHS.reset(token)
        assert not runner._CLAIMS, "a claim outlived the run that took it"


class _FakePopen:
    """Enough of Popen for `_run_bounded`, with a hook that runs while the child 'runs'.

    Deliberately fakes the *process*, not `_run_bounded`: the claim is taken inside
    `_run_bounded`, so stubbing that function would stub out the thing under test.
    """

    during_wait = staticmethod(lambda: None)

    def __init__(self, argv, **kwargs):
        self.args = argv
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.returncode = 0

    def wait(self, timeout=None):
        type(self).during_wait()
        return 0

    def kill(self):  # pragma: no cover - only the timeout path needs it
        pass


class _Overlap:
    """Records the peak number of fake Aseprite children alive at the same time."""

    def __init__(self, dwell: float = DWELL) -> None:
        self.dwell = dwell
        self.peak = 0
        self._inside = 0
        self._guard = threading.Lock()

    def during_wait(self) -> None:
        with self._guard:
            self._inside += 1
            self.peak = max(self.peak, self._inside)
        time.sleep(self.dwell)
        with self._guard:
            self._inside -= 1


@pytest.fixture
def overlap(monkeypatch):
    probe = _Overlap()
    monkeypatch.setattr(_FakePopen, "during_wait", staticmethod(probe.during_wait))
    monkeypatch.setattr(runner.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    return probe


def _lua_naming(*paths: str, unrecorded: str | None = None) -> None:
    """One `run_lua` naming `paths`, recorded the way a real tool records them.

    `unrecorded` is spelled straight into the arguments without going through
    `lua_path`, which is how a tool that found a path somewhere other than the one seam
    would look to the runner.
    """
    args: dict = {}
    for i, path in enumerate(paths):
        args[f"path_{i}"] = common.lua_path(path)
    if unrecorded is not None:
        args["sneaky"] = unrecorded
    with contextlib.suppress(LuaToolError):
        runner.run_lua("RESULT = {}", args or None)


def _in_parallel(*targets) -> None:
    # daemon, so a thread stuck on a claim fails the test with a message instead of
    # hanging the interpreter at exit while it waits to be joined.
    threads = [threading.Thread(target=t, daemon=True) for t in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        # Generously bounded: a hang here is a deadlock, and a deadlocked test should
        # fail with a message rather than wedge the suite.
        thread.join(timeout=30)
    for thread in threads:
        assert not thread.is_alive(), "a run never finished; the claim deadlocked"


# ----------------------------------------------------- the direction that prevents harm
def test_runs_on_one_sprite_never_overlap(overlap):
    """Six calls naming the same sprite must be serialized. This is the corruption."""
    one = "F:/ws/hero.aseprite"
    _in_parallel(*[partial(_lua_naming, one) for _ in range(6)])

    assert overlap.peak == 1, f"expected serialization, saw {overlap.peak} concurrent runs"


def test_a_run_whose_path_was_not_recorded_is_still_serialized(overlap):
    """A tool that got its path from somewhere other than `lua_path` must not go parallel.

    This is the failure mode the issue was written around: a narrowing that learns paths
    from a source it can miss would hand such a tool no claim at all, which looks exactly
    like a working optimisation while the corruption is back.
    """

    def unrecorded() -> None:
        with contextlib.suppress(LuaToolError):
            runner.run_lua("RESULT = {}", {"src": "F:/ws/stranger.aseprite"})

    _in_parallel(partial(_lua_naming, "F:/ws/hero.aseprite"), unrecorded)

    assert overlap.peak == 1, (
        "a run with no recorded path overlapped another run; an unrecognised path must "
        "claim the whole editor"
    )


def test_an_unaccounted_path_in_the_arguments_widens_the_claim(overlap):
    """Recording some of a run's paths is not enough: one it cannot account for is global.

    A claim narrowed to the paths it happened to recognise, while a path it did not
    recognise travels in the same arguments, is under-locking. The whole-editor fallback
    has to trigger on the *presence* of the unknown, not on the absence of knowns.
    """
    _in_parallel(
        partial(_lua_naming, "F:/ws/a.aseprite", unrecorded="F:/ws/b.aseprite"),
        partial(_lua_naming, "F:/ws/b.aseprite"),
    )

    assert overlap.peak == 1, (
        "a run carrying an unrecorded path still narrowed its claim"
    )


def test_two_runs_sharing_one_of_their_paths_do_not_overlap(overlap):
    """A claim is a set and conflict is intersection, not equality.

    `save_sprite_as` names two files, and a pipeline hands one call's output to the next
    as its input. So a run copying a to b and a run editing b into c have to be
    serialized on b, even though neither names the same pair of files as the other.
    """
    _in_parallel(
        partial(_lua_naming, "F:/ws/a.aseprite", "F:/ws/b.aseprite"),
        partial(_lua_naming, "F:/ws/b.aseprite", "F:/ws/c.aseprite"),
    )

    assert overlap.peak == 1, "two runs that both name b.aseprite overlapped on it"


def test_run_cli_claims_the_whole_editor_against_a_narrowed_run(overlap):
    """An export must exclude every Lua run, not merely other exports.

    `run_cli` never reaches Lua, so none of its paths pass the recording seam. If a
    narrowed Lua claim could slip past a CLI claim, an export would read a sprite while
    an edit rewrote it, which is the same race in a new place.
    """

    def export() -> None:
        with contextlib.suppress(Exception):
            runner.run_cli(["F:/ws/hero.aseprite", "--save-as", "F:/ws/hero.png"])

    _in_parallel(export, partial(_lua_naming, "F:/ws/unrelated.aseprite"))

    assert overlap.peak == 1, "a narrowed run overlapped a CLI run's whole-editor claim"


# --------------------------------------------------- the direction that proves the gain
def test_runs_on_different_sprites_do_overlap(overlap):
    """Four calls naming four sprites must all be in flight together.

    Without this the optimisation is assumed rather than demonstrated: the file above
    passes just as well with every call serialized.
    """
    names = [f"F:/ws/s{i}.aseprite" for i in range(4)]
    _in_parallel(*[partial(_lua_naming, n) for n in names])

    assert overlap.peak == 4, (
        f"four unrelated sprites should run in parallel, saw {overlap.peak} at once"
    )


def test_two_runs_with_no_path_in_common_overlap(overlap):
    """The other half of intersection: two files each, none shared, so both proceed."""
    _in_parallel(
        partial(_lua_naming, "F:/ws/a.aseprite", "F:/ws/b.aseprite"),
        partial(_lua_naming, "F:/ws/c.aseprite", "F:/ws/d.aseprite"),
    )

    assert overlap.peak == 2, (
        f"two runs with no file in common should overlap, saw {overlap.peak}"
    )


# ------------------------------------------------------------- the claim, as a function
def test_a_recorded_path_becomes_the_claim():
    one = common.lua_path("F:/ws/hero.aseprite")
    assert runner._claim_keys({"src": one}) == frozenset({os.path.normcase(one)})


def test_a_path_nested_in_a_list_is_claimed():
    """`import_reference_sequence` passes a list of paths, not a path."""
    paths = [common.lua_path(f"F:/ws/ref{i}.png") for i in range(3)]
    keys = runner._claim_keys({"src": common.lua_path("F:/ws/a.aseprite"), "images": paths})
    assert keys is not None
    assert len(keys) == 4, f"a path inside a list was missed: {keys}"


def test_nothing_recorded_means_the_whole_editor():
    assert runner._claim_keys({"src": "F:/ws/hero.aseprite"}) is None


def test_a_run_that_names_no_path_takes_the_whole_editor():
    """An empty claim would conflict with nothing and so overlap everything."""
    common.lua_path("F:/ws/hero.aseprite")
    assert runner._claim_keys({"frame": 1, "color": "#ff0000"}) is None
    assert runner._claim_keys(None) is None


def test_a_leftover_recording_cannot_narrow_a_run_that_names_another_file():
    """Staleness is why nothing clears the recording, so it is pinned rather than argued.

    A path left over from an earlier call is only ever claimed when the run in front of
    the runner also names it. One that names a different file gets the whole editor.
    """
    stale = common.lua_path("F:/ws/from_an_earlier_call.aseprite")

    assert runner._claim_keys({"src": stale}) == frozenset({os.path.normcase(stale)})
    assert runner._claim_keys({"src": "F:/ws/this_call.aseprite"}) is None


def test_two_spellings_of_one_file_claim_the_same_key():
    """Whether case matters is the filesystem's answer, not this module's.

    On Windows `hero.aseprite` and `Hero.aseprite` are one file, so two claims that
    failed to intersect would be exactly the overlap this prevents. Elsewhere they are
    two files and must stay parallel. `os.path.normcase` is the line that decides, and
    this asserts the outcome on both kinds of host rather than skipping on one.
    """
    lower = runner._claim_keys({"src": common.lua_path("F:/ws/hero.aseprite")})
    upper = runner._claim_keys({"src": common.lua_path("F:/ws/Hero.aseprite")})
    assert lower and upper
    same_file = os.path.normcase("F:/ws/hero.aseprite") == os.path.normcase("F:/ws/Hero.aseprite")
    assert bool(lower & upper) is same_file


def test_a_recording_that_outgrows_its_cap_falls_back_to_the_whole_editor():
    """The cap bounds the set; dropping it may only widen a claim, never narrow one."""
    first = common.lua_path("F:/ws/first.aseprite")
    for i in range(runner._MAX_RECORDED_PATHS + 1):
        common.lua_path(f"F:/ws/filler{i}.aseprite")

    assert len(runner._RECORDED_PATHS.get()) <= runner._MAX_RECORDED_PATHS
    assert runner._claim_keys({"src": first}) is None, (
        "a path the cap dropped was still treated as accounted for"
    )


def test_an_argument_structure_that_will_not_end_takes_the_whole_editor(monkeypatch):
    """A cyclic or absurdly deep argument structure must fall back, not hang."""
    monkeypatch.setattr(runner, "_MAX_ARG_NODES", 64)
    common.lua_path("F:/ws/hero.aseprite")
    cyclic: dict = {"src": common.lua_path("F:/ws/hero.aseprite")}
    cyclic["self"] = cyclic

    assert runner._claim_keys(cyclic) is None


# ------------------------------------------------------------------------- reentrancy
@pytest.mark.parametrize(
    ("outer", "inner"),
    [
        (frozenset({"a"}), frozenset({"a"})),
        (frozenset({"a"}), None),
        (None, frozenset({"a"})),
        (None, None),
    ],
)
def test_a_thread_does_not_wait_for_a_claim_it_already_holds(outer, inner):
    """A tool that reaches the runner twice on one thread must not block on itself.

    The old lock was an RLock for exactly this reason, and replacing it with a claim
    table has to keep the property or a nested call hangs instead of failing.
    """
    done = threading.Event()

    def nest() -> None:
        with runner._claim(outer), runner._claim(inner):
            pass
        done.set()

    thread = threading.Thread(target=nest, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert done.is_set(), f"a nested claim deadlocked against itself ({outer} then {inner})"


def test_a_mixed_batch_is_parallel_across_sprites_and_serial_within_each(overlap):
    """Two calls on each of two sprites: exactly two runs at a time, never three.

    Both halves of the contract in one assertion, which is the one that would actually
    catch a half-done job. A claim that never narrows caps this at one; a claim that
    narrows too far lets all four in at once. Only exactly two is the behaviour asked
    for.
    """
    pairs = ["F:/ws/one.aseprite", "F:/ws/one.aseprite",
             "F:/ws/two.aseprite", "F:/ws/two.aseprite"]
    _in_parallel(*[partial(_lua_naming, p) for p in pairs])

    assert overlap.peak == 2, (
        f"two sprites should give two concurrent runs, saw {overlap.peak}"
    )


def test_the_runner_still_reports_a_failed_run(monkeypatch):
    """The claim must not swallow the error path: a child with no sentinel still raises."""
    monkeypatch.setattr(runner.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    with pytest.raises(LuaToolError):
        runner.run_lua("RESULT = {}", {"src": common.lua_path("F:/ws/hero.aseprite")})


def test_a_completed_process_is_what_comes_back(monkeypatch):
    """A guard that changed the return shape would break every caller; it does not."""
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")
    monkeypatch.setattr(runner.subprocess, "Popen", _FakePopen)
    proc = runner._run_bounded(["aseprite", "--version"], 10, keys=frozenset({"x"}))
    assert isinstance(proc, subprocess.CompletedProcess)
    assert proc.returncode == 0
