"""Pure-Python tests for the core/MCP split + backwards-compat shims (CI tier)."""

import importlib
import subprocess
import sys

import pytest

CORE_MODULES = [
    "aseprite_mcp.core.config",
    "aseprite_mcp.core.errors",
    "aseprite_mcp.core.limits",
    "aseprite_mcp.core.luagen",
    "aseprite_mcp.core.manifest",
    "aseprite_mcp.core.models",
    "aseprite_mcp.core.paths",
    "aseprite_mcp.core.runner",
    "aseprite_mcp.core.validation",
]

# The public names each backwards-compat shim must keep re-exporting.
SHIM_EXPORTS = {
    "aseprite_mcp.config": ["find_aseprite", "resolve"],
    "aseprite_mcp.errors": ["AsepriteMCPError", "WorkspaceError"],
    "aseprite_mcp.luagen": ["to_lua"],
    "aseprite_mcp.runner": ["AsepriteError", "run_cli", "run_lua"],
}


@pytest.mark.parametrize("name", CORE_MODULES)
def test_core_modules_import(name):
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize("module,names", sorted(SHIM_EXPORTS.items()))
def test_backwards_compatible_top_level_imports(module, names):
    """The pre-`core/` import paths must keep working for existing callers."""
    mod = importlib.import_module(module)
    missing = [n for n in names if not hasattr(mod, n)]
    assert not missing, f"{module} no longer re-exports {missing}"


def test_error_alias_survives():
    from aseprite_mcp.core.errors import AsepriteMCPError
    from aseprite_mcp.runner import AsepriteError

    assert AsepriteError is AsepriteMCPError


def test_core_does_not_import_mcp_app_or_tools():
    """Importing core must not pull in the MCP app or any tool module, proving
    core is reusable without MCP registration side effects. Checked in a clean
    interpreter so other tests' imports don't pollute the result."""
    imports = "".join(f"import {m}\n" for m in CORE_MODULES)
    code = (
        "import sys\n"
        + imports
        + "assert 'aseprite_mcp.app' not in sys.modules, 'core imported the MCP app'\n"
        # The server package, not a submodule: mcp 2.x removed mcp.server.fastmcp, so
        # asserting on that path would pass for the wrong reason (nothing can import it)
        # and stop testing the isolation this guards.
        "assert 'mcp.server' not in sys.modules, 'core imported the MCP server package'\n"
        "assert not any(m.startswith('aseprite_mcp.tools') for m in sys.modules), "
        "'core imported a tools module'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_geometry_tools_document_their_coordinate_conventions():
    """The conventions must reach the model, not just the module docstring.

    Only a function's own docstring becomes its tool description, so an explanation
    living in the module header is invisible to every caller. Of the 117 tools the server
    had when this was written, three mentioned the origin, and most geometry tools
    documented no argument at all, while two primitives centred half a pixel apart.
    """
    import asyncio

    from aseprite_mcp.server import mcp

    tools = {t.name: (t.description or "") for t in asyncio.run(mcp.list_tools())}
    geometry = (
        "draw_pixels", "draw_line", "draw_polyline", "draw_curve",
        "draw_rectangle", "draw_ellipse", "fill_area",
    )
    for name in geometry:
        description = tools[name]
        assert "top-left" in description, f"{name} does not state the origin"
        assert "grows DOWN" in description, f"{name} does not state the y direction"
        assert "pixels_clipped" in description, f"{name} does not mention clipping"


# --------------------------------------------- the read-only annotation is a promise
def _effective_source(name: str) -> str:
    """A tool's own source, plus any module-level Lua constant it names.

    The Lua a tool runs is sometimes a local string and sometimes a module constant like
    `_ASSESS_LUA`, so reading the function alone would miss half of them and reading the
    whole module would catch its neighbours' writes. Following the constants the function
    actually references is what makes the check specific to the tool.
    """
    import importlib
    import inspect as inspect_mod
    import pkgutil

    from aseprite_mcp import tools as tools_pkg

    for info in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"aseprite_mcp.tools.{info.name}")
        fn = getattr(module, name, None)
        if fn is None or not callable(fn):
            continue
        try:
            source = inspect_mod.getsource(fn)
        except (OSError, TypeError):  # pragma: no cover - defensive
            continue
        parts = [source]
        for attr, value in vars(module).items():
            if attr.endswith("_LUA") and isinstance(value, str) and attr in source:
                parts.append(value)
        return "\n".join(parts)
    raise AssertionError(f"{name} is in READ_ONLY_TOOLS but no tools module defines it")


def test_no_read_only_tool_writes():
    """`readOnlyHint` is a promise to the client, so it has to be true.

    This is the direction that would actually hurt. A tool missing from the set costs an
    approval prompt it did not need; a tool wrongly *in* the set is one a client may run
    without asking, and if it saves the sprite the caller never got the choice. Three
    tools were missing from the set for a release before anyone measured it, so the
    membership is pinned here rather than left to review.

    The opposite direction is deliberately not asserted. "Writes no pixels" is not the
    same as "read-only": every export tool writes a file through `ensure_output_path`
    without ever calling `save_sprite`, so a test demanding that all of them be annotated
    read-only would be wrong about most of the tools it caught.
    """
    import re

    from aseprite_mcp.app import READ_ONLY_TOOLS

    # Two tools do write, to a private `tempfile` path outside the workspace which they
    # delete again, and neither saves the sprite it opened. `app.py` says so where the set
    # is defined. They are exempt by name rather than by pattern, so that adding a third
    # exemption is a decision somebody makes on purpose.
    writes_only_its_own_tempfile = {"render_preview", "health_check"}

    writes = re.compile(r"\b(save_sprite|commit_image)\s*\(|:saveAs\s*\(")
    saves_a_sprite = re.compile(r"\b(save_sprite|commit_image)\s*\(")

    for name in sorted(READ_ONLY_TOOLS - writes_only_its_own_tempfile):
        found = [m.group(0) for m in writes.finditer(_effective_source(name))]
        assert not found, (
            f"{name} is annotated read-only but its source calls {found}, which saves "
            "the caller's sprite"
        )

    # The exemptions are still held to the narrower promise, and to the reason they were
    # exempted in the first place.
    for name in sorted(writes_only_its_own_tempfile):
        source = _effective_source(name)
        found = [m.group(0) for m in saves_a_sprite.finditer(source)]
        assert not found, f"{name} calls {found}, so its exemption no longer holds"
        assert "tempfile" in source, (
            f"{name} is exempt because it writes only to a private tempfile, and its "
            "source no longer mentions tempfile, so the reason for the exemption is gone"
        )


def test_the_tools_an_agent_calls_after_every_pass_are_read_only():
    """Named rather than inferred, because these three are the regression.

    They are the measuring tools, the ones a self-correcting agent calls most, and they
    were the ones left out.
    """
    from aseprite_mcp.app import READ_ONLY_TOOLS

    for name in ("assess_sprite", "diff_sprites", "get_selection"):
        assert name in READ_ONLY_TOOLS, f"{name} writes nothing and should say so"


def test_every_read_only_tool_actually_exists():
    """A renamed tool would leave a stale name here, silently annotating nothing."""
    import asyncio

    from aseprite_mcp.app import READ_ONLY_TOOLS
    from aseprite_mcp.server import mcp

    live = {t.name for t in asyncio.run(mcp.list_tools())}
    missing = sorted(READ_ONLY_TOOLS - live)
    assert not missing, f"READ_ONLY_TOOLS names tools that do not exist: {missing}"


def test_the_annotation_reaches_the_wire():
    """The set is only useful if it arrives at the client as `readOnlyHint`."""
    import asyncio

    from aseprite_mcp.app import READ_ONLY_TOOLS
    from aseprite_mcp.server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in sorted(READ_ONLY_TOOLS):
        hint = getattr(tools[name].annotations, "read_only_hint", None)
        assert hint is True, f"{name} is in READ_ONLY_TOOLS but advertises {hint!r}"


# ------------------------------------- the Python support claim has to be a real one
def test_declared_python_support_matches_what_ci_tests():
    """`requires-python` is a promise to pip; the CI matrix is the evidence for it.

    These drifted: `requires-python = ">=3.10"` has no upper bound, so it admitted 3.14
    while the matrix stopped at 3.13, and the package told pip it worked on an
    interpreter the suite had never run on. The project has already been bitten by a
    minor-version behaviour change once, in `core/config.py`: an embedded null byte used
    to make `Path.resolve()` raise, which made the sandbox fail closed as a side effect,
    and 3.13 resolves such a path without complaint, so the guard had to be written out
    explicitly. An untested minor is exactly where that kind of thing hides.

    Parsed with regular expressions rather than `tomllib` and `yaml` on purpose: this
    test has to run on every interpreter in the matrix, `tomllib` arrived in 3.11, and
    PyYAML is not a declared dependency of this package.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    classifiers = set(re.findall(
        r'"Programming Language :: Python :: (\d+\.\d+)"', pyproject))
    matrix_line = re.search(r"python-version:\s*\[([^\]]*)\]", workflow)
    assert matrix_line, "could not find the CI python-version matrix"
    matrix = set(re.findall(r'"(\d+\.\d+)"', matrix_line.group(1)))

    assert matrix, "the CI matrix parsed as empty, so this test proves nothing"
    assert classifiers == matrix, (
        "the per-minor classifiers and the CI matrix disagree: "
        f"classifiers only {sorted(classifiers - matrix)}, "
        f"matrix only {sorted(matrix - classifiers)}. PyPI filters on the classifiers, "
        "so a minor in one and not the other is a claim with no evidence or evidence "
        "for a claim nobody made."
    )

    floor = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)', pyproject)
    assert floor, "requires-python is not a simple >=X.Y bound; update this test with it"
    lowest = min(matrix, key=lambda v: tuple(int(n) for n in v.split(".")))
    assert floor.group(1) == lowest, (
        f"requires-python floor is {floor.group(1)} but the lowest tested minor is "
        f"{lowest}; one of them is wrong"
    )

    highest = max(matrix, key=lambda v: tuple(int(n) for n in v.split(".")))
    upper = re.search(r'requires-python\s*=\s*">=[\d.]+,\s*<(\d+\.\d+)', pyproject)
    if upper:
        assert upper.group(1) > highest, (
            f"requires-python excludes {upper.group(1)} and above, but the matrix tests "
            f"up to {highest}: the cap would refuse an interpreter that is known to work"
        )
