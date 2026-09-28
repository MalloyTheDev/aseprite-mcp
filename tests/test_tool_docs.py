"""docs/TOOLS.md must describe every registered tool (pure Python, always runs).

The reference is generated, and CI checks it is in sync, so it looked safe. It was not:
only modules named in the generator's GROUPS list got a section, and a module missing from
that list was dropped without a word. The header still counted the tools, and `--check`
compared the file against the same lossy output, so the check passed while shading,
selections and the Minecraft domain (15 tools) were absent from the reference an agent
reads to find out what this server can do.

These tests check the artifact rather than the generator that writes it, so they fail
whether the cause is a missing GROUPS entry, a renamed module, or a hand edit.
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


def test_readme_advertises_the_real_tool_count(registered):
    """The front page said 117 while the server had 128, which is the first number a
    reader sees and the easiest one to leave behind."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    claimed = re.search(r"\*\*(\d+) tools\*\*", readme)
    assert claimed, "README no longer states a tool count"
    assert int(claimed.group(1)) == len(registered)


def test_every_tool_is_named_in_the_readme(registered):
    """The front page is where a tool is found before anyone opens the reference.

    It drifted the same way the reference did, and for the same reason: the catalogue is
    written by hand, and three domains (shading, selections, Minecraft) were added without
    it. Naming each tool in backticks is the whole requirement; the table around it is
    prose, and prose is not something a test should have opinions about.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    missing = sorted(name for name in registered if f"`{name}`" not in readme)
    assert missing == [], f"registered but absent from the README: {missing}"


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
