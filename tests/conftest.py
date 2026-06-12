"""Pytest configuration: point the workspace at a temp dir and skip the whole
suite cleanly when Aseprite is not installed (so CI without Aseprite is green)."""

import os

import pytest

from aseprite_mcp import config as ase_config


@pytest.fixture(scope="session", autouse=True)
def _workspace(tmp_path_factory):
    ws = tmp_path_factory.mktemp("aseprite_ws")
    os.environ["ASEPRITE_MCP_WORKSPACE"] = str(ws)
    yield ws


def pytest_collection_modifyitems(config, items):
    try:
        ase_config.find_aseprite()
    except FileNotFoundError:
        skip = pytest.mark.skip(reason="Aseprite executable not found (set ASEPRITE_PATH).")
        for item in items:
            item.add_marker(skip)
