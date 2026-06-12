"""Pure-Python tests for the core/MCP split + backwards-compat shims (CI tier)."""

import subprocess
import sys


def test_core_modules_import():
    import aseprite_mcp.core.config       # noqa: F401
    import aseprite_mcp.core.errors       # noqa: F401
    import aseprite_mcp.core.luagen       # noqa: F401
    import aseprite_mcp.core.manifest     # noqa: F401
    import aseprite_mcp.core.models       # noqa: F401
    import aseprite_mcp.core.runner       # noqa: F401
    import aseprite_mcp.core.validation   # noqa: F401


def test_backwards_compatible_top_level_imports():
    from aseprite_mcp.config import find_aseprite, resolve            # noqa: F401
    from aseprite_mcp.errors import AsepriteMCPError, WorkspaceError  # noqa: F401
    from aseprite_mcp.luagen import to_lua                            # noqa: F401
    from aseprite_mcp.runner import AsepriteError, run_cli, run_lua   # noqa: F401


def test_error_alias_survives():
    from aseprite_mcp.core.errors import AsepriteMCPError
    from aseprite_mcp.runner import AsepriteError

    assert AsepriteError is AsepriteMCPError


def test_core_does_not_import_mcp_app_or_tools():
    """Importing core must not pull in the FastMCP app or any tool module — proving
    core is reusable without MCP registration side effects. Checked in a clean
    interpreter so other tests' imports don't pollute the result."""
    code = (
        "import sys\n"
        "import aseprite_mcp.core.config, aseprite_mcp.core.runner, aseprite_mcp.core.luagen\n"
        "import aseprite_mcp.core.errors, aseprite_mcp.core.models\n"
        "import aseprite_mcp.core.manifest, aseprite_mcp.core.validation\n"
        "assert 'aseprite_mcp.app' not in sys.modules, 'core imported the MCP app'\n"
        "assert 'mcp.server.fastmcp' not in sys.modules, 'core imported FastMCP'\n"
        "assert not any(m.startswith('aseprite_mcp.tools') for m in sys.modules), "
        "'core imported a tools module'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
