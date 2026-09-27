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
