"""Frame reordering arithmetic: pure, because this is where the off-by-one lives.

Aseprite has no command that moves a frame. It has one that reverses a range, and a move
is a rotation, and a rotation is two reversals: reverse the whole block, then reverse all
but the frame that has arrived. Written down here so the index arithmetic can be tested
against a list rather than against a sprite.

The other thing worth stating once is what happens to tags. Aseprite's tags mark frame
*positions*, not pictures, so reordering frames under a tag leaves the tag where it is and
changes what it covers. Nothing here quietly re-points them: a caller that moves a frame
through a tag is told which tags were affected and decides what it meant.
"""

from __future__ import annotations

from itertools import pairwise


def rotation_reversals(frame: int, to: int) -> list[tuple[int, int]]:
    """The two reversals that move `frame` to position `to`, in order.

    Moving later rotates the block [frame..to] left by one; moving earlier rotates
    [to..frame] right by one. Each is the whole block reversed, then all but the one
    element that has landed where it belongs.
    """
    if frame == to:
        raise ValueError("a frame is already where it is; nothing to move")
    if frame < to:
        return [(frame, to), (frame, to - 1)]
    return [(to, frame), (to + 1, frame)]


def apply_reversals(order: list, reversals: list[tuple[int, int]]) -> list:
    """Run reversals over a 1-based sequence. Here so a test can check the arithmetic
    against a list, which is the same thing Aseprite does to the frames."""
    out = list(order)
    for first, last in reversals:
        if last > first:
            out[first - 1:last] = reversed(out[first - 1:last])
    return out


def check_contiguous(frames: list[int]) -> tuple[int, int]:
    """Return (first, last) for a run of consecutive frames, or say where the gap is.

    Aseprite reverses the *span* of a selection, so a gapped list of 1, 3, 5 reverses
    frames 1 through 5 and touches two frames nobody named. Refusing is the only way to
    keep the tool honest about what it did.
    """
    if not frames:
        raise ValueError("no frames given")
    ordered = sorted(frames)
    for earlier, later in pairwise(ordered):
        if later != earlier + 1:
            raise ValueError(
                f"frames must be one unbroken run; {earlier} is followed by {later}. "
                "Aseprite reverses everything between the first and the last, so a gap "
                "would silently take in the frames in between."
            )
    return ordered[0], ordered[-1]


def tags_touching(tags: list[dict], first: int, last: int) -> list[str]:
    """Names of the tags whose range overlaps [first, last], in file order.

    A tag that merely sits alongside the affected frames is unaffected; one that overlaps
    them now covers different drawings, whether or not its own numbers changed.
    """
    return [
        tag["name"]
        for tag in tags
        if tag["from"] <= last and tag["to"] >= first
    ]
