"""Shared helpers for tool modules: colour parsing and path handling.

Colour and path logic is defined in `models.py` (the typed validation boundary);
these thin wrappers keep the long-standing `parse_color`/`lua_path` API that the
tool modules import.
"""

from __future__ import annotations

from pathlib import Path

from ..core import config, indexed
from ..core.models import ColorSpec, SpritePath
from ..core.runner import record_path, run_lua


def parse_color(spec: str | None) -> dict:
    """Parse a flexible colour string into the dict the Lua side consumes
    ({r, g, b, a} or {index: N}). Delegates to `models.ColorSpec`.

    Accepts: "#RGB", "#RGBA", "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a",
    "index:N" (for indexed sprites), or a name such as black/white/red/transparent.
    """
    return ColorSpec.parse(spec).as_dict()


def resolve_path(filename: str) -> Path:
    """Resolve a user filename to an absolute path under the workspace if relative."""
    return config.resolve(filename)


def lua_path(p: Path | str) -> str:
    """Path string for embedding in Lua. Forward slashes work on every platform.

    Also records the path for the current call, which is how the runner knows which files
    an Aseprite invocation may touch and so which invocations are safe to run in
    parallel. This is the only seam where that can be learned reliably: every path headed
    for a Lua script is spelled here, whereas the argument names those paths travel under
    are not one name but ten, and a runner that guessed from the name would silently
    claim nothing for a tool whose name it did not know. A path recorded but not used
    costs nothing; a path used but not recorded would let two runs overwrite one sprite,
    so the recording is deliberately wider than it needs to be rather than narrower.
    """
    lua = SpritePath(str(p)).lua()
    record_path(lua)
    return lua


def run_ramp_lua(body: str, args: dict) -> dict:
    """`run_lua` for a tool that takes a declared `ramp`, with the palette reading added.

    On an indexed sprite a ramp colour the palette does not hold is not written: it is
    resolved to the nearest entry that can draw. The harness measures what the ramp
    became (`ramp_on_palette`); this turns that into the sentence a caller can act on and
    drops it in `warnings`.

    Every tool with a `ramp` parameter goes through here rather than through `run_lua`,
    and `test_imports.py` pins that, because a tool that forgets is a tool whose shading
    silently bands on indexed art. Absent rather than empty when there is nothing to say,
    so a `warnings` key always means there is something.
    """
    result = run_lua(body, args)
    if not isinstance(result, dict):
        return result
    notes = indexed.ramp_readings(result.get("ramp_on_palette") or {})
    if notes:
        # Appended rather than assigned: a tool may already have warnings of its own, and
        # dropping those to report this one would trade a finding for a finding.
        existing = result.get("warnings")
        result["warnings"] = [*existing, *notes] if isinstance(existing, list) else notes
    return result


# How many pixels a tool body has actually landed, for tools that report a count of their
# own alongside the harness's `pixels_written`.
#
# `img_set` refuses a write outside the active selection, silently and by design, so a
# tally kept beside the write loop counts pixels that were never painted. Measured: with
# a selection in a corner the glow never reaches, `glow` reported `glow_pixels: 56` beside
# `pixels_written: 0` and added a layer with nothing on it; `outline_smart` reported 36
# where 18 landed; `gradient_map`'s `per_step` summed to twice its own `pixels_written`.
#
# Reading the prelude's counter rather than restating the mask test is the point. The rule
# lives in `masked_out` and nowhere else, which is the guarantee issue #199 was about: a
# second copy of it here would be a second place for it to drift.
LANDED_LUA = """
local function landed() return _px_written end
"""


# What the harness attaches to a Lua result that the tool itself did not put there.
#
# `selection_applied` and the pixel counters are stamped onto RESULT after the body runs,
# so a tool whose Python side returns the Lua table gets them for free and a tool that
# assembles a fresh dict silently loses them. `tween_cels` and `smear_frame` both do the
# latter, and `tween_cels`'s own docstring promised `pixels_outside_selection` by name
# while the key could never arrive: a selection-scoped tween reported what it wrote and
# nothing about what the mask refused, which is the missing-count failure of #181 in a
# tool that looked like it had inherited the fix.
_HARNESS_KEYS = (
    "pixels_clipped", "pixels_skipped", "pixels_outside_selection",
    "selection_applied", "linked_frames_also_changed",
)


def carry_harness_keys(out: dict, raw: dict) -> dict:
    """Copy the harness's report fields from a raw Lua result onto a rebuilt one.

    Absent rather than zero, matching the harness: a key that is there at all means there
    is something to read.
    """
    for key in _HARNESS_KEYS:
        if key in raw:
            out[key] = raw[key]
    return out
