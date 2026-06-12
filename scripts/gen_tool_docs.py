"""Generate docs/TOOLS.md — a complete reference of every MCP tool.

Introspects the live FastMCP registry so the docs always match the code.

Usage:  uv run python scripts/gen_tool_docs.py
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path

from aseprite_mcp.app import mcp
from aseprite_mcp import server  # noqa: F401  (importing registers every tool)

# Ordered (module, heading) pairs for grouping the reference.
GROUPS = [
    ("sprite", "Sprite lifecycle"),
    ("inspect", "Inspection & preview"),
    ("layers", "Layers"),
    ("frames", "Frames (animation)"),
    ("tags", "Animation tags"),
    ("cels", "Cels"),
    ("drawing", "Drawing"),
    ("brushes", "Brushes & symmetry"),
    ("effects", "Effects & colour adjustments"),
    ("text", "Text"),
    ("tilemap", "Tilemaps"),
    ("image", "Image stamping"),
    ("palette", "Palette"),
    ("slices", "Slices"),
    ("transform", "Transforms"),
    ("export", "Export & import"),
    ("reference", "Reference / rotoscope"),
    ("gui", "GUI companion mode"),
]


def _build_name_to_module() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for mod_name, _ in GROUPS:
        mod = importlib.import_module(f"aseprite_mcp.tools.{mod_name}")
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if inspect.isfunction(obj) and getattr(obj, "__module__", "") == mod.__name__:
                mapping[attr] = mod_name
    return mapping


def _type_str(info: dict) -> str:
    if "type" in info:
        t = info["type"]
        if t == "array":
            items = info.get("items", {})
            return f"array<{items.get('type', 'any')}>"
        return t
    if "anyOf" in info:
        parts = [s.get("type", "any") for s in info["anyOf"]]
        return " | ".join(parts)
    return "any"


def _params_table(schema: dict) -> str:
    props = schema.get("properties", {})
    if not props:
        return "_No parameters._\n"
    required = set(schema.get("required", []))
    lines = ["| Parameter | Type | Required | Default |", "| --- | --- | --- | --- |"]
    for name, info in props.items():
        is_req = "yes" if name in required else "no"
        default = info.get("default", "")
        if default == "":
            default = "" if name in required else "_none_"
        lines.append(f"| `{name}` | {_type_str(info)} | {is_req} | {default} |")
    return "\n".join(lines) + "\n"


async def main() -> None:
    name_to_mod = _build_name_to_module()
    tools = await mcp.list_tools()
    by_mod: dict[str, list] = {}
    for t in tools:
        by_mod.setdefault(name_to_mod.get(t.name, "other"), []).append(t)
    for v in by_mod.values():
        v.sort(key=lambda t: t.name)

    out = [
        "# Aseprite MCP — Tool Reference",
        "",
        f"Auto-generated from the live tool registry by `scripts/gen_tool_docs.py`. "
        f"**{len(tools)} tools.**",
        "",
        "Colours accept `#RRGGBB`, `#RRGGBBAA`, `r,g,b`, `r,g,b,a`, `index:N`, or a name "
        "(black, white, red, green, blue, yellow, cyan, magenta, transparent, …). "
        "Frames are 1-based; palette indices are 0-based. Relative paths resolve inside the "
        "workspace.",
        "",
        "## Contents",
        "",
    ]
    for mod_name, heading in GROUPS:
        if by_mod.get(mod_name):
            anchor = heading.lower().replace(" ", "-").replace("&", "").replace("/", "").replace("(", "").replace(")", "").replace("--", "-")
            out.append(f"- [{heading}](#{anchor}) ({len(by_mod[mod_name])})")
    out.append("")

    for mod_name, heading in GROUPS:
        group = by_mod.get(mod_name)
        if not group:
            continue
        out.append(f"## {heading}")
        out.append("")
        for t in group:
            out.append(f"### `{t.name}`")
            out.append("")
            if t.description:
                out.append(t.description.strip())
                out.append("")
            out.append(_params_table(t.inputSchema or {}))
            out.append("")

    path = Path(__file__).resolve().parents[1] / "docs" / "TOOLS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path} ({len(tools)} tools)")


if __name__ == "__main__":
    asyncio.run(main())
