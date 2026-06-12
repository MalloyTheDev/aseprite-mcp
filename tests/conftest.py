"""Pytest configuration and the --run-aseprite gate.

Test tiers:
  * Pure-Python unit tests (test_unit.py) ALWAYS run — no Aseprite needed. This is
    what CI exercises for real on every push.
  * Aseprite integration & golden-output tests run ONLY when `--run-aseprite` is
    passed (and Aseprite is installed). They are the local/optional release gate:

        uv run pytest                 # fast: unit tests only
        uv run pytest --run-aseprite  # full: unit + integration + golden

The workspace points at a temp dir, and absolute paths are allowed so integration
tests can export into pytest's tmp_path.
"""

import os

import pytest

from aseprite_mcp import config as ase_config

# Test files that are pure-Python (no Aseprite) and must always run, including on CI.
PURE_PYTHON_TESTS = ("test_unit", "test_manifest", "test_validation", "test_errors", "test_models")


def pytest_addoption(parser):
    parser.addoption(
        "--run-aseprite",
        action="store_true",
        default=False,
        help="Run integration/golden tests that drive a real Aseprite install.",
    )


@pytest.fixture(scope="session", autouse=True)
def _workspace(tmp_path_factory):
    ws = tmp_path_factory.mktemp("aseprite_ws")
    os.environ["ASEPRITE_MCP_WORKSPACE"] = str(ws)
    # Integration tests write exports to pytest tmp_path (outside the workspace).
    os.environ["ASEPRITE_MCP_ALLOW_ABSOLUTE"] = "1"
    yield ws


def pytest_collection_modifyitems(config, items):
    run_aseprite = config.getoption("--run-aseprite")
    missing_reason = None
    if run_aseprite:
        try:
            ase_config.find_aseprite()
        except FileNotFoundError as exc:
            missing_reason = f"--run-aseprite was given but Aseprite was not found: {exc}"

    for item in items:
        # Pure-Python tests always run (no Aseprite needed).
        if any(name in item.nodeid for name in PURE_PYTHON_TESTS):
            continue
        if not run_aseprite:
            item.add_marker(pytest.mark.skip(reason="needs --run-aseprite (Aseprite integration test)"))
        elif missing_reason:
            item.add_marker(pytest.mark.skip(reason=missing_reason))
