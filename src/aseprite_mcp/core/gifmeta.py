"""Reading and rewriting a GIF's loop metadata, without re-encoding a single frame.

Aseprite always writes the Netscape Application Extension with a repeat count of zero,
which means "loop forever", and its CLI has no flag for anything else. So every animation
this server exported looped, including the ones whose whole point was that they do not: a
one-shot attack built with tags at `repeats=1`, whose generator asserts that `validate_loop`
reports `loops is False`, shipped as a GIF that cut from the recovery pose back to the
wind-up every second and a half, forever. The tool could not express the thing the piece
was teaching.

The fix is to remove the extension rather than to write a count into it. Setting the count
to 1 is the obvious move and is wrong: the GIF specification calls it an iteration count,
decoders disagree over whether 1 means "play once" or "play once more after the first
pass", and the result is a one-shot in some viewers and a double in others. A GIF carrying
no Netscape extension at all plays exactly once everywhere, which is the unambiguous form
and the one hand-authored one-shots use.

This module is pure: bytes in, bytes out. Nothing here knows what Aseprite is.
"""
from __future__ import annotations

# 0x21 extension introducer, 0xFF application extension, 0x0B an 11-byte identifier.
_NETSCAPE = b"\x21\xff\x0bNETSCAPE2.0"
_GIF_MAGIC = (b"GIF87a", b"GIF89a")


def has_loop(data: bytes) -> bool:
    """Whether the GIF carries a Netscape loop extension at all."""
    return data.find(_NETSCAPE) >= 0


def loop_count(data: bytes) -> int | None:
    """The declared iteration count, 0 meaning forever, or None if there is no extension."""
    at = data.find(_NETSCAPE)
    if at < 0:
        return None
    body = at + len(_NETSCAPE)
    # sub-block: size byte, then `size` bytes of which the last two are the count.
    size = data[body]
    if size < 3:
        return None
    return int.from_bytes(data[body + 2:body + 4], "little")


def strip_loop(data: bytes) -> bytes:
    """The same GIF with its loop extension removed, so it plays once and stops.

    Every frame, colour table and delay is left exactly as it was: this edits nineteen
    bytes of metadata and copies the rest, so a one-shot export is pixel-identical to the
    looping one it came from. Already-stripped input comes back unchanged, which keeps the
    operation safe to apply twice.
    """
    if not data.startswith(_GIF_MAGIC):
        raise ValueError(
            f"not a GIF: the file begins {data[:6]!r}, not GIF87a or GIF89a. Loop "
            "metadata can only be rewritten on a GIF."
        )
    at = data.find(_NETSCAPE)
    if at < 0:
        return data
    body = at + len(_NETSCAPE)
    size = data[body]
    end = body + 1 + size
    if end >= len(data) or data[end] != 0x00:
        # Refused rather than guessed. A truncated or unusual extension is better reported
        # than silently cut at the wrong offset, which would corrupt the frame that follows.
        raise ValueError(
            f"the Netscape extension at byte {at} is not terminated where its length says "
            f"it should be, so this file is not safe to rewrite."
        )
    return data[:at] + data[end + 1:]
