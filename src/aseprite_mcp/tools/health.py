"""Health check — verify the server can actually drive Aseprite end to end.

Lets a user ask the agent "is the Aseprite MCP working?" and get a useful answer:
is Aseprite found, can it run Lua, can it create a sprite, can it export a PNG.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from .. import __version__, config
from ..app import mcp
from ..runner import run_cli, run_lua
from .common import lua_path


@mcp.tool()
async def health_check() -> dict:
    """Run a self-test of the server and its Aseprite integration.

    Returns whether Aseprite was found, its version, the resolved workspace, the
    number of registered tools, and whether a real create-sprite + export-PNG
    round-trip succeeds. `ok` is True only if the full round-trip works.
    """
    result: dict = {
        "ok": False,
        "version": __version__,
        "workspace": str(config.workspace()),
        "allow_absolute_paths": config.allow_absolute(),
        "timeout_seconds": config.timeout(),
        "aseprite_found": False,
    }

    try:
        from .. import server  # noqa: F401  ensure every tool module is registered
        result["tools_registered"] = len(await mcp.list_tools())
    except Exception:  # pragma: no cover - defensive
        pass

    try:
        result["aseprite_path"] = config.find_aseprite()
        result["aseprite_found"] = True
    except FileNotFoundError as exc:
        result["reason"] = str(exc)
        return result

    tmp = tempfile.mkdtemp(prefix="asemcp_health_")
    try:
        spr = os.path.join(tmp, "health.aseprite")
        png = os.path.join(tmp, "health.png")
        info = run_lua(
            "local s = Sprite(4, 4, ColorMode.RGB); s.filename = ARG.p; s:saveAs(ARG.p); "
            "RESULT = { version = tostring(app.version) }",
            {"p": lua_path(spr)},
        )
        result["aseprite_version"] = info.get("version")
        result["can_run_lua"] = True
        result["can_create_sprite"] = os.path.exists(spr)
        run_cli([spr, "--save-as", png])
        result["can_export_png"] = os.path.exists(png)
    except Exception as exc:
        result["error"] = str(exc)
        result.setdefault("can_run_lua", False)
        result.setdefault("can_create_sprite", False)
        result.setdefault("can_export_png", False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    result["ok"] = bool(
        result.get("aseprite_found")
        and result.get("can_create_sprite")
        and result.get("can_export_png")
    )
    return result
