"""What an Aseprite file says about itself in its first fourteen bytes.

The header gives the canvas and the frame count without launching Aseprite. That lets a
tool which hands a file to the command line refuse an impossible request before the
launch, and answer a question it used to launch Aseprite to ask: an export learned a
sprite's frame count by running a script, then ran the export.

Layout (Aseprite's file-format spec, and checked against files this server wrote): a
DWORD file size, the WORD magic number 0xA5E0, then the frame count, width and height as
WORDs, all little-endian.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import NamedTuple

_MAGIC = 0xA5E0
_HEAD = struct.Struct("<IHHHH")


class AseHeader(NamedTuple):
    width: int
    height: int
    frames: int


def read_header(path: str | Path) -> AseHeader | None:
    """The canvas and frame count of an .aseprite / .ase file.

    None when `path` cannot be read or is not one (a PNG, a truncated file), in which
    case no claim is made and the caller falls back to whatever it did before.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(_HEAD.size)
    except OSError:
        return None
    if len(head) < _HEAD.size:
        return None
    _size, magic, frames, width, height = _HEAD.unpack(head)
    if magic != _MAGIC:
        return None
    return AseHeader(width=width, height=height, frames=frames)
