"""Pytest configuration.

- Points the workspace at a temp dir and allows absolute paths so integration
  tests can export to pytest's tmp_path.
- Skips the Aseprite-dependent suites when Aseprite isn't installed, but always
  runs the pure-Python unit tests (test_unit.py) so CI has real coverage without
  an Aseprite license.
"""

import os

import pytest

from aseprite_mcp import config as ase_config


@pytest.fixture(scope="session", autouse=True)
def _workspace(tmp_path_factory):
    ws = tmp_path_factory.mktemp("aseprite_ws")
    os.environ["ASEPRITE_MCP_WORKSPACE"] = str(ws)
    # Integration tests write exports to pytest tmp_path (outside the workspace).
    os.environ["ASEPRITE_MCP_ALLOW_ABSOLUTE"] = "1"
    yield ws


def pytest_collection_modifyitems(config, items):
    try:
        ase_config.find_aseprite()
        return  # Aseprite present: run everything.
    except FileNotFoundError:
        pass
    skip = pytest.mark.skip(reason="Aseprite executable not found (set ASEPRITE_PATH).")
    for item in items:
        # Pure-Python unit tests don't need Aseprite — always run them.
        if "test_unit" in item.nodeid:
            continue
        item.add_marker(skip)
