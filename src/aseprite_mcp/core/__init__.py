"""Reusable execution & domain logic for aseprite-mcp.

`core` holds everything that does NOT depend on MCP registration: locating/running
Aseprite (`config`, `runner`), Lua generation (`luagen`), typed errors (`errors`), and
domain value types (`models`, `manifest`, `validation`). It must never import the MCP
app/tool modules, so it can be reused from tests, a CLI, or another runtime.
"""
