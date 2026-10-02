"""Both documents that list every tool must still list every tool (pure Python).

`docs/TOOLS.md` is generated, and CI checks it is in sync, so it looked safe. It was not:
only modules named in the generator's GROUPS list got a section, and a module missing from
that list was dropped without a word. The header still counted the tools, and `--check`
compared the file against the same lossy output, so the check passed while shading,
selections and the Minecraft domain (15 tools) were absent from the reference an agent
reads to find out what this server can do.

The README's tool catalogue has the same job and no generator: it is one hand-written row
per tool, and until these tests it had nothing checking it. It drifted the same way and
for the same reason, and the pass that fixed it had to write a throwaway script to
establish that every row names a real tool and every tool has exactly one row. A check
that must be re-invented each time it is needed is not a check, so it lives here now.

These tests check the artifacts rather than the generator that writes one of them, so they
fail whether the cause is a missing GROUPS entry, a renamed module, or a hand edit.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path

import pytest

import aseprite_mcp.server  # noqa: F401  -- importing registers every tool
from aseprite_mcp.app import mcp

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs" / "TOOLS.md"
README = REPO / "README.md"

# The two README sections that carry one row per tool. The rest of the file has tables
# too (the contents map, the environment variables) and they are not catalogues.
ROW_SECTIONS = ("## High-level workflows", "## Tool catalogue")

# A backticked bare snake_case identifier, which is how the catalogue names a tool.
TOOL_IN_BACKTICKS = re.compile(r"`([a-z][a-z0-9_]*)`")


def _catalogue_rows() -> list[tuple[int, str]]:
    """Every catalogue and workflow table row, as (line number, the Tool cell).

    Only the first cell is read, because a description names other tools in passing: the
    `tween_cels` row mentions `validate_loop`, the `draw_ellipse_in_box` row mentions
    `draw_rectangle`. Reading whole rows would report both of those as listed twice and
    send the reader to delete a row that is correct.
    """
    rows: list[tuple[int, str]] = []
    in_section = False
    in_fence = False
    for lineno, line in enumerate(README.read_text(encoding="utf-8").split("\n"), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):  # not "### ", so subsections stay inside a section
            in_section = line.strip() in ROW_SECTIONS
            continue
        if not in_section or not line.startswith("|"):
            continue
        cell = line.strip().strip("|").split("|")[0].strip()
        if cell in ("Tool", "---", ":---", "---:", ":---:"):  # header and separator
            continue
        rows.append((lineno, cell))
    return rows


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_tool_docs", REPO / "scripts" / "gen_tool_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def registered() -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


@pytest.fixture(scope="module")
def documented() -> set[str]:
    return set(re.findall(r"^### `([a-z0-9_]+)`", DOCS.read_text(encoding="utf-8"), re.M))


@pytest.fixture(scope="module")
def catalogued() -> dict[str, list[int]]:
    """Tool name -> the README line numbers of the catalogue rows that name it."""
    found: dict[str, list[int]] = {}
    for lineno, cell in _catalogue_rows():
        for name in TOOL_IN_BACKTICKS.findall(cell):
            found.setdefault(name, []).append(lineno)
    return found


def test_every_registered_tool_has_a_section(registered, documented):
    missing = sorted(registered - documented)
    assert missing == [], f"registered but undocumented: {missing}"


def test_the_reference_describes_no_tool_that_does_not_exist(registered, documented):
    stale = sorted(documented - registered)
    assert stale == [], f"documented but not registered: {stale}"


def test_the_advertised_count_matches_the_registry(registered):
    header = DOCS.read_text(encoding="utf-8").split("\n## Contents", 1)[0]
    counted = re.search(r"\*\*(\d+) tools\.\*\*", header)
    assert counted, "the reference no longer states a tool count"
    assert int(counted.group(1)) == len(registered)


def test_the_sections_the_catalogue_checks_read_are_still_there():
    """A parser pointed at a renamed heading reads an empty catalogue.

    Most of the checks below would then pass for the wrong reason, so the headings they
    depend on are asserted by name first. The one that would fail, every tool has a row,
    would name every tool in the registry rather than the real cause.
    """
    text = README.read_text(encoding="utf-8")
    absent = [s for s in ROW_SECTIONS if f"\n{s}\n" not in text]
    assert absent == [], (
        f"README headings the catalogue checks parse are gone or renamed: {absent}. "
        "Update ROW_SECTIONS in this file to match the README."
    )
    assert _catalogue_rows(), "the README catalogue parsed to zero rows"


def test_every_name_in_a_catalogue_row_is_a_registered_tool(registered, catalogued):
    """A row can outlive the tool it describes, and reads as a feature that exists."""
    stale = sorted(
        (name, lines) for name, lines in catalogued.items() if name not in registered
    )
    assert stale == [], (
        "README catalogue rows name tools that are not registered, as (name, README "
        f"lines): {stale}. Delete the row, or correct the name."
    )


def test_every_registered_tool_has_a_catalogue_row(registered, catalogued):
    """The front page is where a tool is found before anyone opens the reference.

    It drifted the same way the generated reference did, and for the same reason: the
    catalogue is written by hand, and three domains (shading, selections, Minecraft) were
    added without it. Naming each tool in backticks in the Tool cell of a row is the
    whole requirement; the description beside it is prose, and prose is not something a
    test should have opinions about.
    """
    missing = sorted(registered - set(catalogued))
    assert missing == [], (
        f"{len(missing)} registered tool(s) have no README catalogue row: {missing}. "
        "Add one row each under the matching '### ' heading of the Tool catalogue, or "
        "to the High-level workflows table if the tool scaffolds a whole asset. If a row "
        "does exist, it is outside the sections this reads: add its '## ' heading to "
        "ROW_SECTIONS in this file."
    )


def test_no_tool_is_named_in_two_catalogue_rows(catalogued):
    """Two rows for one tool is how a renamed or re-homed tool leaves a stale twin
    behind, and it was the property that caught real defects."""
    doubled = sorted(
        (name, lines) for name, lines in catalogued.items() if len(lines) > 1
    )
    assert doubled == [], (
        "README catalogue rows name the same tool more than once, as (name, README "
        f"lines): {doubled}. Keep one row per tool."
    )


def test_every_catalogue_row_names_at_least_one_tool():
    """A row whose Tool cell lost its backticks stops being found by every check above,
    so the tool it describes silently becomes undocumented."""
    bare = [
        (lineno, cell)
        for lineno, cell in _catalogue_rows()
        if not TOOL_IN_BACKTICKS.findall(cell)
    ]
    assert bare == [], (
        "README catalogue rows name no tool at all, as (README line, Tool cell): "
        f"{bare}. Put the tool name in the first cell, in backticks."
    )


def test_every_tool_count_in_the_readme_is_the_live_count(registered):
    """The front page said 117 while the server had 128, which is the first number a
    reader sees and the easiest one to leave behind. There are two such numbers now, the
    headline bullet and the contents map, so every "<n> tools" in the file is checked
    rather than only the first. A count of part of the tool set must therefore be written
    so it does not read as the total ("13 workflow tools" is not matched here; a bare
    "13 tools" would be, and would fail).
    """
    text = README.read_text(encoding="utf-8")
    assert re.search(r"\*\*(\d+) tools\*\*", text), (
        "the README headline bullet no longer states the tool count"
    )
    claims = [
        (text[: m.start()].count("\n") + 1, int(m.group(1)))
        for m in re.finditer(r"(\d+)\s+tools\b", text)
    ]
    wrong = [c for c in claims if c[1] != len(registered)]
    assert wrong == [], (
        f"README tool counts disagree with the registry's {len(registered)}, as "
        f"(README line, claimed): {wrong}."
    )


def test_every_tool_module_is_grouped(registered):
    """A new tool module with no GROUPS entry is the failure that happened; catching it
    here names the module instead of leaving the tools missing."""
    gen = _generator()
    grouped = {mod for mod, _ in gen.GROUPS}
    owners = {}
    for path in sorted((REPO / "src" / "aseprite_mcp" / "tools").glob("*.py")):
        if path.stem == "__init__":
            continue
        text = path.read_text(encoding="utf-8")
        if "@mcp.tool()" in text:
            owners[path.stem] = path.name
    ungrouped = sorted(set(owners) - grouped)
    assert ungrouped == [], f"tool modules absent from GROUPS: {ungrouped}"


def test_generation_refuses_to_drop_a_tool(monkeypatch):
    """The guard itself: with a module removed from GROUPS, generating must fail loudly
    rather than write a reference that silently omits those tools."""
    gen = _generator()
    monkeypatch.setattr(gen, "GROUPS", [g for g in gen.GROUPS if g[0] != "shading"])
    with pytest.raises(SystemExit, match="shift_along_ramp"):
        asyncio.run(gen.main(check=True))
