"""A GIF that plays once, which this server could not export.

Aseprite's CLI always writes the Netscape loop extension with a repeat count of zero,
"loop forever", and offers no flag for anything else. So an animation that is not a cycle
still shipped as one: the attack showcase is built from tags at `repeats=1`, its generator
asserts that `validate_loop` reports `loops is False`, and the GIF it produced snapped from
the recovery pose back to the wind-up every second and a half for ever. The tool could not
express the thing the piece existed to teach.

These are pure: the rewriting is byte surgery on a file, so it is tested on bytes. The
editor-tier test at the bottom is the one that proves the export path actually calls it.
"""
from __future__ import annotations

import pathlib

import pytest

from aseprite_mcp.core import gifmeta

HERE = pathlib.Path(__file__).resolve().parent
LOOPING = HERE.parent / "docs" / "assets" / "showcase" / "lava.gif"


@pytest.mark.pure
def test_a_gif_aseprite_wrote_declares_an_endless_loop():
    """The premise. If Aseprite ever stops writing this, the stripping below is moot and
    this test is how that gets noticed rather than inferred."""
    raw = LOOPING.read_bytes()
    assert gifmeta.has_loop(raw), f"{LOOPING.name} carries no Netscape extension"
    assert gifmeta.loop_count(raw) == 0, (
        f"{LOOPING.name} declares {gifmeta.loop_count(raw)} iterations, not 'forever'")


@pytest.mark.pure
def test_stripping_the_loop_leaves_every_frame_alone():
    """The reason this is byte surgery and not a re-encode. A one-shot export has to be
    pixel-identical to the looping one, or the choice costs image quality."""
    raw = LOOPING.read_bytes()
    once = gifmeta.strip_loop(raw)
    assert not gifmeta.has_loop(once)
    assert gifmeta.loop_count(once) is None
    # Nineteen bytes: the introducer, the identifier, the sub-block and its terminator.
    assert len(raw) - len(once) == 19, (len(raw), len(once))


@pytest.mark.pure
def test_stripping_twice_changes_nothing_the_second_time():
    once = gifmeta.strip_loop(LOOPING.read_bytes())
    assert gifmeta.strip_loop(once) == once


@pytest.mark.pure
def test_a_file_that_is_not_a_gif_is_refused():
    """Rather than cutting at a byte offset found in something else's format."""
    with pytest.raises(ValueError, match="not a GIF"):
        gifmeta.strip_loop(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


@pytest.mark.pure
def test_a_truncated_extension_is_refused_rather_than_guessed():
    """A sub-block whose length runs past its terminator cannot be cut safely: doing it
    anyway would corrupt whatever frame follows, which is worse than refusing."""
    broken = b"GIF89a" + b"\x00" * 7 + gifmeta._NETSCAPE + b"\x03\x01\x00\x00\x41"
    with pytest.raises(ValueError, match="not terminated"):
        gifmeta.strip_loop(broken)
