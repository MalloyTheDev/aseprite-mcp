"""Cross-cutting guard for the typed error hierarchy (issue #60) - no Aseprite.

Two complementary checks, because one alone does not close the hole:

1. `test_no_bare_value_error_in_tool_module` walks the AST of every module in
   `aseprite_mcp/tools/` and fails on a `raise ValueError`. That is what makes a *newly
   introduced* bare `ValueError` fail CI, including in a tool this file never calls.
2. `test_argument_rejection_is_typed` actually calls tools with a bad argument and
   asserts the failure is an `AsepriteMCPError`, with Aseprite stubbed out so a rejection
   that only happens after a launch does not count.

`ValueError` is not a subclass of `AsepriteMCPError`, so `except AsepriteError` misses
every bare site; the point of these tests is that the property holds for the whole tool
surface rather than for the modules someone remembered to fix.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from aseprite_mcp.core.errors import AsepriteMCPError
from aseprite_mcp.tools import (
    batch,
    brushes,
    cels,
    drawing,
    effects,
    frames,
    palette,
    reference,
    sprite,
    tags,
    tilemap,
    transform,
    workflow,
)

TOOLS_DIR = pathlib.Path(batch.__file__).parent

# A `raise ValueError` is allowed only where a comment says why. Put the marker on the
# raise itself or on the line above it, e.g.
#   # bare ValueError: parsed by ColorSpec, whose callers catch ValueError.
JUSTIFICATION_MARKER = "bare ValueError:"

# Modules still carrying unconverted sites, with the count at the time of writing.
# `strict=True` on purpose: once a module is converted its entry here starts *failing*,
# which is the signal to delete the line rather than let the exemption rot.
#
# Empty, and it should stay that way. These four modules were outside both halves of
# #60's file split (its component list names brushes, drawing, effects, palette,
# reference, tilemap, transform and workflow) and were converted in a separate pass.
# An entry here marks a module as knowingly unconverted, which is strictly worse than
# fixing it: the xfail is strict, so re-adding one and then converting the module makes
# this test fail rather than silently pass.
PENDING: dict[str, str] = {}


def _bare_value_error_lines(path: pathlib.Path) -> list[int]:
    """Line numbers of `raise ValueError(...)` statements lacking a justification."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found: list[int] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if not (isinstance(exc, ast.Name) and exc.id == "ValueError"):
            continue
        window = lines[max(0, node.lineno - 2):node.end_lineno or node.lineno]
        if any(JUSTIFICATION_MARKER in line for line in window):
            continue
        found.append(node.lineno)
    return found


def _tool_modules() -> list:
    params = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        marks = []
        if path.name in PENDING:
            marks.append(pytest.mark.xfail(strict=True, reason=PENDING[path.name]))
        params.append(pytest.param(path, id=path.name, marks=marks))
    return params


@pytest.mark.parametrize("path", _tool_modules())
def test_no_bare_value_error_in_tool_module(path: pathlib.Path):
    """Argument rejection must raise inside the hierarchy, not a bare ValueError."""
    offenders = _bare_value_error_lines(path)
    assert not offenders, (
        f"{path.name} raises a bare ValueError at line(s) "
        f"{', '.join(str(n) for n in offenders)}. Raise ValidationFailed (or another "
        f"AsepriteMCPError subclass) instead, or justify it with a "
        f"'# {JUSTIFICATION_MARKER} ...' comment."
    )


def test_pending_list_names_real_modules():
    """A stale exemption is as bad as a missing one: every PENDING file must exist."""
    missing = sorted(name for name in PENDING if not (TOOLS_DIR / name).is_file())
    assert not missing, f"PENDING names modules that no longer exist: {missing}"


# --------------------------------------------------------------------------- #
# Runtime half: a rejected argument raises inside the hierarchy, before launch #
# --------------------------------------------------------------------------- #
def _boom(*_args, **_kwargs):
    raise AssertionError("Aseprite was launched; the argument should have been rejected first.")


def _case(fn, *args, **kwargs):
    return pytest.param(fn, args, kwargs, id=f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__name__}")


def _pending_case(fn, *args, reason: str, **kwargs):
    param = _case(fn, *args, **kwargs)
    return pytest.param(*param.values, id=param.id, marks=pytest.mark.xfail(strict=True, reason=reason))


REJECTIONS = [
    # Frames/tags/cels: an out-of-range frame number (issue #61).
    _case(frames.set_frame_duration, "h/x.aseprite", 0, 100),
    _case(frames.duplicate_frame, "h/x.aseprite", -1),
    _case(frames.add_frame, "h/x.aseprite", copy_from=0),
    _case(tags.add_tag, "h/x.aseprite", "t", 0, 1),
    _case(tags.set_tag, "h/x.aseprite", "t", from_frame=0),
    _case(cels.get_cel, "h/x.aseprite", "Layer 1", 0),
    _case(cels.copy_cel, "h/x.aseprite", "Layer 1", 0, 1),
    # Enumerated string arguments.
    _case(transform.flip_sprite, "h/x.aseprite", "sideways"),
    _case(transform.rotate_sprite, "h/x.aseprite", 45),
    _case(palette.sort_palette, "h/x.aseprite", by="brightness"),
    _case(effects.add_outline, "h/x.aseprite", "#000000", where="everywhere"),
    _case(brushes.mirror_layer, "h/x.aseprite", "Layer 1", direction="diagonal"),
    # Empty / malformed collections.
    _case(reference.import_reference_sequence, "h/x.aseprite", []),
    _case(tilemap.set_tiles, "h/x.aseprite", "tiles", []),
    _case(tilemap.paint_tile_pixels, "h/x.aseprite", "tiles", 0, []),
    _case(tilemap.paint_tile_pixels, "h/x.aseprite", "tiles", 0, [{"x": 0, "y": 0}]),
    _case(drawing.draw_pixels, "h/x.aseprite", []),
    _case(palette.set_palette, "h/x.aseprite", []),
    _case(workflow.create_tileset_project, "h/x.aseprite", tiles=[]),
    # Batch: the op registry rejects shape and frame errors before any launch.
    _case(batch.apply_operations, "h/x.aseprite", [{"op": "no_such_op", "args": {}}]),
    _case(
        batch.apply_operations,
        "h/x.aseprite",
        [{"op": "set_frame_duration", "args": {"frame": 0, "duration_ms": 50}}],
    ),
    # Converted in the pass that emptied PENDING: both now raise ValidationFailed.
    _case(sprite.set_color_mode, "h/x.aseprite", "rgba"),
    _case(sprite.scale_sprite, "h/x.aseprite"),
]


@pytest.mark.parametrize(("fn", "args", "kwargs"), REJECTIONS)
def test_argument_rejection_is_typed(fn, args, kwargs, monkeypatch):
    module = __import__(fn.__module__, fromlist=["_"])
    for attr in ("run_lua", "run_cli"):
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, _boom)
    with pytest.raises(AsepriteMCPError):
        fn(*args, **kwargs)
