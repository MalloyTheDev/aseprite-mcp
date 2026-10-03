"""One registry, one result shape: every sprite description carries a verdict.

A write tool here returned one of two shapes. Forty-one set `ok = true` in a `RESULT`
table of their own; thirty returned `sprite_info(spr)` unwrapped, and that table had no
`ok` key, so nothing in the result could ever say the call did nothing. Censused on the
live registry at v0.10.0, 152 tools:

    RESULT = sprite_info AND no ok anywhere : 30
    RESULT = sprite_info AND sets ok itself : 1   (merge_layer_down, from #219)
    own RESULT table with ok = true         : 41

The cost was not a missing `ok: false`. It was that a caller could not write one check:
`add_layer` and `fill_layer` sit in the same module and disagreed about whether the key
exists, and `merge_layer_down` returned a sprite description that looked identical
whether the merge happened or not. The fix is one line in `core/luagen.py::sprite_info`,
and these tests are registry-wide so a new tool cannot reintroduce the split.

The static tests are marked `pure` individually rather than by adding this module to
conftest's `PURE_PYTHON_TESTS`: that list is an allowlist, and a marker on the test is
the form that fails visibly on a machine with no Aseprite if it is wrong. The editor-tier
test at the bottom is the only proof that the key actually arrives in a result, which no
reading of the source can give.
"""

from __future__ import annotations

import inspect as pyinspect
import pathlib
import re

import pytest

from aseprite_mcp import server  # noqa: F401  importing registers every tool
from aseprite_mcp.app import mcp
from aseprite_mcp.core import luagen
from aseprite_mcp.tools import batch, drawing, inspect, layers, sprite

REGISTERED = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

# Where a sprite description is handed back whole, and so inherits the verdict.
RETURNS_SPRITE_INFO = re.compile(r"RESULT\s*=\s*sprite_info\(")
# Either shape of the verdict: a field in a table, or set on the result after. Anchored
# to a whole line on purpose. A substring search for `ok = true` was the first version of
# this and it passed with the key deleted, because the comment above the key says the
# words: a test that prose can satisfy measures the prose.
SETS_OK = re.compile(r"^\s*(RESULT\.ok\s*=\s*true|ok\s*=\s*true,?)\s*$", re.M)


def _code_only(text: str, markers: tuple[str, ...] = ("--",)) -> str:
    """The same text with its comments removed, trailing ones as well as whole lines.

    `--` only, by default, because `#` is Lua's length operator and not a comment:
    `frameCount = #spr.frames` would lose its value. A Python source gets both markers,
    where `--` still means the Lua comments inside its embedded bodies.

    A `--` inside a Lua string is cut too, which is a false negative this file can
    afford: everything it looks for is a field or an assignment, never a message.
    """
    out = []
    for line in text.splitlines():
        for marker in markers:
            at = line.find(marker)
            if at != -1:
                line = line[:at]
        out.append(line)
    return "\n".join(out)


def _sprite_info_table() -> str:
    """Just the table `sprite_info` returns, comments stripped.

    Read off the assembled prelude, so it is the Lua Aseprite is actually handed rather
    than the Python that writes it.
    """
    code = _code_only(luagen.PRELUDE)
    start = code.index("local function sprite_info(spr)")
    table = code.index("return {", start)
    return code[table:code.index("\nend", table)]


def _tool_sources():
    """Every registered tool's source, which is where its Lua body lives."""
    for name, tool in sorted(REGISTERED.items()):
        try:
            yield name, pyinspect.getsource(tool.fn)
        except (OSError, TypeError):  # pragma: no cover - a C or synthesized callable
            continue


def _source_files():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aseprite_mcp"
    return sorted(root.rglob("*.py")), root


@pytest.mark.pure
def test_sprite_info_returns_a_verdict():
    """The one line the whole family inherits, pinned at its source.

    Asserted against the assembled prelude rather than the function that writes it, so
    this is the Lua Aseprite is actually handed, and against the table with its comments
    stripped, so the comment that explains the key cannot stand in for the key.
    """
    assert SETS_OK.search(_sprite_info_table()), (
        "sprite_info's returned table has no ok key, so the thirty tools that return it "
        "unwrapped have no field that could say the call did nothing"
    )


@pytest.mark.pure
def test_every_tool_returning_a_sprite_description_carries_ok():
    """Registry-wide, so a new tool cannot be the next one without a verdict.

    The census is the shape of the test: a tool that hands back `sprite_info(...)` must
    end up with `ok`, whether it inherits the key or sets it itself. Both are honest;
    what is not allowed is a third shape with neither.
    """
    returns_description, missing = [], []
    inherits = bool(SETS_OK.search(_sprite_info_table()))
    for name, src in _tool_sources():
        if not RETURNS_SPRITE_INFO.search(src):
            continue
        returns_description.append(name)
        if not (inherits or SETS_OK.search(_code_only(src, ("--", "#")))):
            missing.append(name)

    # Measured at the time of the fix. A floor rather than an equality, so adding a tool
    # to the family is not an edit to this test, while a drop to a handful (which is how
    # a regex-based census silently stops looking) fails here.
    assert len(returns_description) >= 31, (
        f"only {len(returns_description)} tools look like they return a sprite "
        "description, so this test is not looking at the family it was written for"
    )
    assert not missing, (
        "these tools return a sprite description with no verdict in it, so a caller "
        f"cannot tell 'done' from 'nothing to do': {sorted(missing)}"
    )


# A sub-table is the one place the inherited key would lie: nested under another result,
# `ok` describes the sprite that was read and not the operation that was asked for. Both
# existing sites were checked by reading before the key was added, and neither leaks.
NESTED_SPRITE_INFO_SITES = {
    # `RESULT = { sprite = sprite_info(spr), operations = applied }`. Never reaches a
    # caller: `tools/batch.py` passes `result["sprite"]` through
    # `core/manifest.py::sprite_summary`, which copies eight named fields and not this
    # one, and the manifest supplies the outer verdict itself in Python.
    "core/oplib.py",
    # `local info = sprite_info(spr)`, then only `info.slices` and its count are copied
    # into RESULT, so the key never reaches the result at all.
    "tools/slices.py",
}


@pytest.mark.pure
def test_no_nested_sprite_info_can_read_as_the_outer_verdict():
    """The check the fix depended on, kept so the next sub-table use has to repeat it.

    `sprite_info` is called 33 times in `src/`. Thirty-one are `RESULT = sprite_info(..)`,
    which is the whole result and is the point. The other two are listed above with the
    reading that shows the key does not surface; a third one fails here until someone has
    done the same reading for it.
    """
    files, root = _source_files()
    nested = set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if "sprite_info(" not in line or "get_sprite_info(" in line:
                continue
            if re.match(r"\s*(RESULT\s*=\s*sprite_info\(|local function sprite_info)", line):
                continue
            nested.add(rel)
    assert nested == NESTED_SPRITE_INFO_SITES, (
        "a sprite_info result is embedded somewhere new, where the inherited `ok` would "
        f"describe the sprite read rather than the call: {sorted(nested)}. Check whether "
        "the key surfaces in the tool's result, then list the file with the reason."
    )


@pytest.mark.pure
def test_no_body_claims_failure_instead_of_refusing():
    """`ok` says the call did the thing; it is never a false flag on a call that did not.

    The tools fixed in #203, #204 and #219 refuse, with a sentence saying what to change.
    An `ok = false` would be the cheaper and worse answer, so its absence is pinned: once
    the key exists on every sprite description, writing one is a one-word edit away.
    """
    files, root = _source_files()
    offenders = []
    for path in files:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"\bok\s*=\s*false\b", line)
            if match is None:
                continue
            # Prose about the contract is not a breach of it, and this file's own
            # comments discuss the shape they forbid. Compared by position rather than
            # by cutting the line, so a `--` inside a string cannot blind the check.
            comment = min(
                (at for at in (line.find("--"), line.find("#")) if at != -1),
                default=None,
            )
            if comment is not None and comment < match.start():
                continue
            offenders.append(f"{path.relative_to(root).as_posix()}:{i}")
    assert not offenders, (
        "a body reports failure in a field instead of raising, which loses the remedy a "
        f"refusal carries: {offenders}"
    )


@pytest.mark.pure
def test_the_key_is_additive():
    """No existing key moved or changed type: the eleven that were there still are.

    `get_sprite_info` gains a key it does not need, which is the price of one shape. What
    would not be acceptable is paying for it with a rename.
    """
    returned = _sprite_info_table()
    for key in ("filename", "width", "height", "colorMode", "frameCount", "layerCount",
                "paletteSize", "layers", "frames", "tags", "slices"):
        assert re.search(rf"^\s*{key} = \S", returned, re.M), (
            f"sprite_info no longer returns {key}"
        )


# ======================= the key actually arrives (needs Aseprite) =======================
# Unmarked, so it belongs to the --run-aseprite tier. Everything above reads source; this
# reads a result, which is the only way to know the Lua edit survived json_encode.


def test_a_real_sprite_description_comes_back_with_ok(request):
    """Both halves of the old split, side by side, answering the same check."""
    name = f"shape/{request.node.name}.aseprite"
    created = sprite.create_sprite(name, 16, 16)
    assert created["ok"] is True, "create_sprite returns a sprite description"

    added = layers.add_layer(name, "art")
    assert added["ok"] is True, "add_layer inherits the verdict"

    filled = drawing.draw_rectangle(name, 0, 0, 4, 4, "#ff0000", filled=True, layer="art")
    assert filled["ok"] is True, "the other shape already said so"

    info = inspect.get_sprite_info(name)
    assert info["ok"] is True
    # Additive: the description is still the description.
    assert info["width"] == 16 and info["layerCount"] >= 2


def test_a_batch_keeps_its_verdict_at_the_top_and_not_inside(request):
    """The nesting case, measured rather than read.

    `apply_operations` embeds a sprite description under `sprite`. Its own verdict is the
    manifest's, at the top level, and the inherited key must not show up in the nested
    block where it would describe the sprite read instead of the batch.
    """
    name = f"shape/{request.node.name}.aseprite"
    sprite.create_sprite(name, 8, 8)
    result = batch.apply_operations(name, [{"op": "add_layer", "args": {"name": "b"}}])
    assert result["ok"] is True
    assert "ok" not in result["sprite"], (
        "the batch's nested sprite block carries a verdict of its own, which a caller "
        "would read as the batch's"
    )
