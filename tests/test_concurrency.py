"""The Aseprite invocation lock, tested without launching Aseprite.

An Aseprite run is a read-modify-write over a whole sprite file, so two overlapping
runs on one file do not merely interleave: measured over eight trials of two concurrent
layer additions, three kept only one edit and five produced a file that no longer
decoded, while all eight reported success. The lock in `core.runner` is what stops that,
and these tests pin it at the seam rather than by racing the real editor (that
regression lives in `test_regressions.py`, behind --run-aseprite).
"""

from __future__ import annotations

import io
import subprocess
import threading
import time

import pytest

from aseprite_mcp.core import runner
from aseprite_mcp.core.errors import LuaToolError


def _stub_proc(argv, stdout=""):
    return subprocess.CompletedProcess(argv, 0, stdout, "")


class _OverlapProbe:
    """Records the highest number of callers inside the guarded region at once."""

    def __init__(self, dwell: float = 0.05) -> None:
        self.dwell = dwell
        self.inside = 0
        self.peak = 0
        self._guard = threading.Lock()

    def __call__(self, argv, timeout, limit=None):
        with self._guard:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        # Dwell long enough that an unguarded implementation is certain to be caught.
        time.sleep(self.dwell)
        with self._guard:
            self.inside -= 1
        return _stub_proc(argv)


def test_run_bounded_serializes_overlapping_callers(monkeypatch):
    """Six threads through the real lock must never be inside the seam together."""
    probe = _OverlapProbe()
    monkeypatch.setattr(runner, "_drain_tail", lambda *a, **k: None)

    def guarded(argv):
        with runner._ASEPRITE_LOCK:
            probe(argv, 10)

    threads = [threading.Thread(target=guarded, args=(["aseprite"],)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert probe.peak == 1, f"expected serialization, saw {probe.peak} concurrent runs"


def test_the_lock_is_reentrant_on_one_thread():
    """A tool reaching the runner twice on one thread must not deadlock against itself."""
    with runner._ASEPRITE_LOCK:
        acquired = runner._ASEPRITE_LOCK.acquire(timeout=1)
        try:
            assert acquired, "lock is not reentrant; a nested call would deadlock"
        finally:
            if acquired:
                runner._ASEPRITE_LOCK.release()


class _FakePopen:
    """Enough of Popen for `_run_bounded`, with a hook that runs while the child 'runs'.

    Deliberately fakes the *process*, not `_run_bounded`: the lock lives inside
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


def test_run_lua_excludes_other_threads_while_aseprite_runs(monkeypatch):
    """While a run is in progress, a second thread must fail to take the lock.

    That is the property that actually prevents the corruption, and asserting it this
    way does not depend on RLock internals.
    """
    other_thread_got_in = threading.Event()
    reached_the_child = threading.Event()

    def probe_from_another_thread():
        reached_the_child.set()

        def contender():
            if runner._ASEPRITE_LOCK.acquire(timeout=0.2):
                runner._ASEPRITE_LOCK.release()
                other_thread_got_in.set()

        rival = threading.Thread(target=contender)
        rival.start()
        rival.join()

    monkeypatch.setattr(_FakePopen, "during_wait", staticmethod(probe_from_another_thread))
    monkeypatch.setattr(runner.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")

    # The fake child writes no sentinel, so parsing raises; we only care that the lock
    # was exclusive while the child was running.
    with pytest.raises(LuaToolError):
        runner.run_lua("RESULT = {}")

    assert reached_the_child.is_set(), "run_lua never launched the child"
    assert not other_thread_got_in.is_set(), (
        "another thread acquired the lock while an Aseprite run was in progress"
    )


def test_run_cli_is_also_serialized(monkeypatch):
    """run_cli shares the seam, so it must share the lock."""
    other_thread_got_in = threading.Event()

    def probe_from_another_thread():
        def contender():
            if runner._ASEPRITE_LOCK.acquire(timeout=0.2):
                runner._ASEPRITE_LOCK.release()
                other_thread_got_in.set()

        rival = threading.Thread(target=contender)
        rival.start()
        rival.join()

    monkeypatch.setattr(_FakePopen, "during_wait", staticmethod(probe_from_another_thread))
    monkeypatch.setattr(runner.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(runner.config, "find_aseprite", lambda: "aseprite")

    runner.run_cli(["--version"])
    assert not other_thread_got_in.is_set(), "run_cli did not hold the lock"
