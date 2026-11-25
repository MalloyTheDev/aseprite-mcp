"""Pytest configuration: the two test tiers and the --run-aseprite gate.

Test tiers:
  * The pure tier needs no Aseprite and ALWAYS runs. It is what CI exercises on every
    push, on runners with no editor installed. A test is in it when its module is on
    PURE_PYTHON_TESTS below, or when the test carries `@pytest.mark.pure` (directly, or
    through a module-level `pytestmark = pytest.mark.pure`).
  * The editor tier (integration and golden-output tests) drives a real Aseprite and
    runs ONLY when `--run-aseprite` is passed:

        uv run --locked pytest                 # pure tier only
        uv run --locked pytest --run-aseprite  # pure tier + editor tier

Every tests/test_*.py has to declare which tier it belongs to, in exactly one way: on
PURE_PYTHON_TESTS, on EDITOR_ONLY_TESTS, or carrying at least one `pure` marker (a file
that mixes pure and editor tests marks its pure ones). An undeclared file fails at setup
with an instruction, rather than being skipped, because a skip looks like a pass.

Without `--run-aseprite`, ASEPRITE_PATH is pointed at a path that does not exist for the
whole session, so an installed editor is unreachable and a test that is labelled pure but
launches Aseprite fails here exactly as it would on CI. With `--run-aseprite`, a missing
editor is a usage error rather than 800-odd skips.

The workspace points at a temp dir, and absolute paths are allowed so integration tests
can export into pytest's tmp_path.
"""

from __future__ import annotations

import ast
import functools
import os
import pathlib
import tempfile

import pytest

from aseprite_mcp import config as ase_config

TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Test files that are pure-Python (no Aseprite) and must always run, including on CI.
PURE_PYTHON_TESTS = (
    "test_unit", "test_manifest", "test_validation", "test_errors", "test_models",
    "test_imports", "test_oplib", "test_output_paths", "test_limits", "test_properties",
    "test_engine_godot", "test_slice_metadata", "test_asset_spec", "test_hardening",
    "test_concurrency", "test_minecraft", "test_minecraft_tools", "test_strict_args",
    "test_path_sandbox", "test_error_hierarchy", "test_schema_portability",
    "test_refusals_reach_clients",
    "test_quality", "test_slice_data", "test_tool_docs", "test_loopcheck",
    "test_motion", "test_timing", "test_ramps",
    "test_frameops", "test_spritediff", "test_indexed", "test_lighting",
    "test_inbetween", "test_style", "test_metadata", "test_quantization",
    "test_test_tiers", "test_release_gate", "test_verify_showcase",
)

# Test files in which every test drives a real Aseprite. They run only under
# --run-aseprite. A file that also holds editor-free tests does not belong here: mark
# those tests `pure` instead, and the file leaves this list.
EDITOR_ONLY_TESTS = (
    "test_advanced", "test_background_fill", "test_background_reads",
    "test_background_writes", "test_expansion", "test_export_presets",
    "test_export_slice_metadata", "test_golden", "test_grayscale",
    "test_indexed_background", "test_indexed_sprites", "test_overwrite",
    "test_regressions", "test_selection", "test_selection_scoping", "test_shading",
    "test_stray_pixels", "test_tools", "test_walk_template_batch", "test_workflows",
)

# Entries on both lists are whole module names: `test_timing` means tests/test_timing.py
# and nothing else.

# Where ASEPRITE_PATH points for a session without --run-aseprite. It must not exist; its
# name is what a mislabelled pure test reports when it tries to launch the editor.
NO_EDITOR_SENTINEL = str(
    pathlib.Path(tempfile.gettempdir()) / "aseprite-mcp-tests"
    / "editor-disabled-without--run-aseprite" / "aseprite"
)

_UNREGISTERED = pytest.StashKey[str]()
_saved_aseprite_path = pytest.StashKey[tuple[bool, str]]()


def _is_pure_mark(node: ast.AST) -> bool:
    """`pytest.mark.pure` or `pytest.mark.pure(...)` (any `<x>.mark.pure`)."""
    if isinstance(node, ast.Call):
        node = node.func
    return (isinstance(node, ast.Attribute) and node.attr == "pure"
            and isinstance(node.value, ast.Attribute) and node.value.attr == "mark")


def _pure_marks_in(node: ast.AST) -> int:
    return sum(_is_pure_mark(n) for n in ast.walk(node))


@functools.cache
def pure_marker_count(path: pathlib.Path) -> int:
    """How many `pure` markers a test file applies: one per decorated test or class, plus
    one per `pytestmark` assignment (module or class level) that includes the marker.

    Parsed rather than grepped, so a marker quoted in a docstring does not count and
    `pytestmark = [pytest.mark.pure, ...]` spread over several lines does.
    """
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += sum(_is_pure_mark(d) for d in node.decorator_list)
        if isinstance(node, (ast.Module, ast.ClassDef)):
            for stmt in node.body:
                targets = (stmt.targets if isinstance(stmt, ast.Assign)
                           else [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
                if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
                    count += _pure_marks_in(stmt.value) > 0
    return count


def registration_problem(path: pathlib.Path) -> str | None:
    """Why `path` does not declare exactly one tier, or None when it does."""
    path = pathlib.Path(path)
    name = path.stem
    states = []
    if name in PURE_PYTHON_TESTS:
        states.append("listed on PURE_PYTHON_TESTS")
    if name in EDITOR_ONLY_TESTS:
        states.append("listed on EDITOR_ONLY_TESTS")
    if pure_marker_count(path):
        states.append("carries `pure` markers")
    if len(states) == 1:
        return None
    if not states:
        return (
            f"tests/{path.name} does not say whether it needs Aseprite, so it would be "
            f"skipped in silence. In tests/conftest.py, add '{name}' to PURE_PYTHON_TESTS "
            f"if none of its tests launch the editor, or to EDITOR_ONLY_TESTS if all of "
            f"them do. If it mixes the two, mark the editor-free tests "
            f"@pytest.mark.pure instead (or the whole module, with "
            f"`pytestmark = pytest.mark.pure`)."
        )
    return (
        f"tests/{path.name} declares its tier more than once ({'; '.join(states)}). "
        f"Keep exactly one: a module on PURE_PYTHON_TESTS already runs in full, and a "
        f"module with `pure` tests in it is not editor-only."
    )


def pytest_addoption(parser):
    parser.addoption(
        "--run-aseprite",
        action="store_true",
        default=False,
        help="Run integration/golden tests that drive a real Aseprite install.",
    )


def pytest_configure(config):
    config.stash[_saved_aseprite_path] = (
        "ASEPRITE_PATH" in os.environ, os.environ.get("ASEPRITE_PATH", ""))
    if config.getoption("--run-aseprite"):
        # Asked for the editor tier and there is no editor: stop. Skipping every editor
        # test instead printed "1731 passed, 837 skipped" and exited 0, which reads as a
        # pass, and the reason only showed under -rs.
        try:
            ase_config.find_aseprite()
        except FileNotFoundError as exc:
            raise pytest.UsageError(
                f"--run-aseprite was given but Aseprite was not found: {exc}\n"
                "The editor tier needs a real Aseprite. Set ASEPRITE_PATH to the Aseprite "
                "executable (or put `aseprite` on PATH), or leave out --run-aseprite to "
                "run the pure tier only."
            ) from None
        return
    # No editor tier, so no editor: a test labelled pure that launches Aseprite has to
    # fail here as it does on CI, not pass because Steam happens to be installed.
    os.environ["ASEPRITE_PATH"] = NO_EDITOR_SENTINEL


def pytest_unconfigure(config):
    if _saved_aseprite_path not in config.stash:
        return
    was_set, value = config.stash[_saved_aseprite_path]
    if was_set:
        os.environ["ASEPRITE_PATH"] = value
    else:
        os.environ.pop("ASEPRITE_PATH", None)


@pytest.fixture(scope="session", autouse=True)
def _workspace(tmp_path_factory):
    ws = tmp_path_factory.mktemp("aseprite_ws")
    os.environ["ASEPRITE_MCP_WORKSPACE"] = str(ws)
    # Integration tests write exports to pytest tmp_path (outside the workspace).
    os.environ["ASEPRITE_MCP_ALLOW_ABSOLUTE"] = "1"
    yield ws


def pytest_collection_modifyitems(config, items):
    run_aseprite = config.getoption("--run-aseprite")

    for item in items:
        path = pathlib.Path(str(item.fspath))
        # An undeclared module is failed at setup rather than skipped, and before any
        # skip marker is added, so the instruction is what the run reports.
        if path.parent == TESTS_DIR and path.name.startswith("test_"):
            problem = registration_problem(path)
            if problem:
                item.stash[_UNREGISTERED] = problem
                continue
        # Pure-Python tests always run (no Aseprite needed). The match is on the module's
        # own name, never on the nodeid: a substring test let any test *function* whose
        # name contained a listed module's name into the always-run set, and
        # `test_animation.py::test_timing_never_touches_a_pixel` duly ran on CI, where
        # there is no Aseprite to launch.
        if path.stem in PURE_PYTHON_TESTS:
            continue
        # ...and so does an individual test marked `pure` inside a module that is not.
        #
        # The allowlist can only speak about whole files, and most of the integration
        # files hold a handful of tests that need no editor: the pre-flight refusals,
        # which assert that a bad argument is rejected in Python *before* Aseprite is
        # launched. Fifty-five of those were being skipped on CI, where a skip is
        # indistinguishable from a pass in a summary line. Listing their files instead
        # would be worse than the gap it closed: the Aseprite-backed tests in the same
        # file would then run with no editor and pass vacuously, which looks like
        # coverage.
        #
        # A test marked `pure` that actually needs Aseprite fails without --run-aseprite,
        # locally as on CI, because pytest_configure makes the editor unreachable.
        if item.get_closest_marker("pure"):
            continue
        if not run_aseprite:
            item.add_marker(pytest.mark.skip(reason="needs --run-aseprite (Aseprite integration test)"))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    problem = item.stash.get(_UNREGISTERED, None)
    if problem:
        pytest.fail(problem, pytrace=False)
