"""Game-engine export adapters.

Pure-Python builders that turn Aseprite sprite-sheet metadata into engine-native
resource files (Godot, …). No Aseprite, no MCP, no file IO — just data → text, so the
mapping logic is unit-testable. The MCP tools in ``aseprite_mcp.tools.export_presets``
orchestrate the actual export (run Aseprite → read the sheet JSON → call these builders).
"""
