"""The shared MCP application instance.

Defined in its own module so every tool module can `from ..app import mcp`
without creating an import cycle with `server.py`.

Two cross-cutting concerns are applied centrally here rather than tool by tool:
the wire form of every input schema (`portable_schema`) and the behaviour
annotations clients use to decide what to auto-approve (`annotations_for`).
Both are keyed on data the server already has at registration time, so a new tool
picks them up without touching its decorator, and the classification stays
auditable in one place instead of being spread over a hundred call sites.
"""

from __future__ import annotations

import copy
import inspect
import json
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .core.errors import UnknownArgumentError

INSTRUCTIONS = """\
This server drives Aseprite (a pixel-art / sprite editor) headlessly to create and
edit sprite files (.aseprite/.ase), draw pixel art, build animations, manage
palettes, and export to PNG/GIF/sprite sheets.

Workflow notes:
  * Filenames are relative to the server's workspace directory. Absolute paths and
    paths that escape the workspace (via "..") are rejected by default; the operator
    can opt out with ASEPRITE_MCP_ALLOW_ABSOLUTE=1. Most tools return the resolved path.
  * Tools that create a NEW output file (exports, saves, imports) are no-clobber: they
    refuse to replace an existing file unless you pass overwrite=True. Editing tools
    that take an existing `filename` save in place and need no such flag, so drawing
    into the same sprite repeatedly is expected and safe.
  * Sprites are real files on disk. Edits open the file, modify it, and save.
  * Frames are 1-based. Colours accept "#RRGGBB", "#RRGGBBAA", "r,g,b", "r,g,b,a",
    "index:N" (for indexed sprites), or a few names (black, white, red, green,
    blue, yellow, cyan, magenta, transparent, ...).
  * Call `render_preview` to get a PNG image of your work so you can see the result
    before continuing. Call `get_sprite_info` for the structured state of a sprite.
  * Recommended first step for a new asset: `create_sprite`, then draw, then preview.
"""

# ---------------------------------------------------------------------------
# Wire form of the input schemas
# ---------------------------------------------------------------------------
#
# The schemas are derived from the Python signatures by pydantic, and that derivation
# leaks into the wire: a `title` on every property and on the argument model itself, and
# `anyOf: [{...}, {"type": "null"}]` for every `x: int | None = None` hint. Neither
# carries information a client uses, both cost tokens on every tools/list, and strict
# function-calling modes plus several clients (Cline, Continue, LM Studio) mishandle the
# `anyOf` form: the parameter renders with no type, after which weaker models omit it or
# send the string "null".
#
# The signatures stay exactly as they are. This is a presentation pass over the derived
# schema, applied on the way out, so the pydantic model that actually validates a call
# keeps accepting null for an optional argument.

# Keywords whose values are themselves schemas. The walk follows only these, because
# `properties` keys are *parameter names*: a blind recursion would delete a parameter
# that happens to be called `title` or `default`.
_CHILD_SCHEMA = ("items", "additionalProperties", "not", "contains", "propertyNames")
_CHILD_SCHEMA_MAP = ("properties", "$defs", "definitions", "patternProperties")
_CHILD_SCHEMA_LIST = ("anyOf", "oneOf", "allOf", "prefixItems")


def _schema_nodes(node: Any) -> list[dict[str, Any]]:
    """Every JSON Schema object inside `node`, outermost first."""
    if not isinstance(node, dict):
        return []
    found = [node]
    for key in _CHILD_SCHEMA:
        found.extend(_schema_nodes(node.get(key)))
    for key in _CHILD_SCHEMA_MAP:
        child = node.get(key)
        if isinstance(child, dict):
            for value in child.values():
                found.extend(_schema_nodes(value))
    for key in _CHILD_SCHEMA_LIST:
        child = node.get(key)
        if isinstance(child, list):
            for value in child:
                found.extend(_schema_nodes(value))
    return found


_ABSENT = object()


def _collapse_nullable(node: dict[str, Any]) -> None:
    """Turn `anyOf: [T, null]` into T, dropping a `default` of null with it.

    Optionality is already carried by the property's absence from `required`, so the
    null member adds nothing; and once the type is concrete, `default: null` would
    contradict it, which a validating client is right to complain about.

    A union with two real members (`int | str`) is left alone: collapsing it would
    have to throw one of them away.
    """
    members = node.get("anyOf")
    if not isinstance(members, list) or len(members) != 2:
        return
    nulls = [m for m in members if isinstance(m, dict) and m.get("type") == "null"]
    rest = [m for m in members if isinstance(m, dict) and m.get("type") != "null"]
    if len(nulls) != 1 or len(rest) != 1 or "type" not in rest[0]:
        return
    del node["anyOf"]
    for key, value in rest[0].items():
        node.setdefault(key, value)
    if node.get("default", _ABSENT) is None:
        del node["default"]


def portable_schema(schema: Any) -> Any:
    """The wire form of a derived input schema: no titles, no nullable unions, and
    every remaining default also stated in prose.

    The default is restated in the description because OpenAI-style strict function
    calling drops the `default` keyword outright. `default` itself is kept, since
    clients that honour it prefill from it and the generated docs read it.
    """
    if not isinstance(schema, dict):
        return schema
    out = copy.deepcopy(schema)

    nodes = _schema_nodes(out)
    for node in nodes:
        node.pop("title", None)
    for node in nodes:
        _collapse_nullable(node)
    for node in _schema_nodes(out):
        if "default" not in node:
            continue
        stated = f"Default: {json.dumps(node['default'])}."
        existing = node.get("description")
        # Skipped when it is already there so the pass is idempotent: a tool whose own
        # description names the default, and a schema handed back through here twice,
        # both keep one clause rather than gaining one per call.
        if stated in (existing or ""):
            continue
        node["description"] = f"{existing.rstrip()} {stated}" if existing else stated
    return out


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------
#
# Cline, Continue and Goose auto-approve a tool marked read-only, which is the
# difference between an agent that can look at a sprite freely and one that prompts for
# every `get_sprite_info`. The flip side is that a wrong `readOnlyHint` auto-approves
# something that mutates the caller's files, so a tool goes in READ_ONLY_TOOLS only
# after its own code (and everything it calls, up to the Aseprite runner) was read and
# found to write nothing the caller owns.
#
# `openWorldHint` is false for every tool: this server talks to the local filesystem and
# a local Aseprite process, never to an open-ended external service.

# Verified read-only: opens a sprite (or nothing at all) and returns what it found.
#
# `render_preview` and `health_check` each write a file, which is why they look like they
# belong on the other list: both write only to a private `tempfile` path that they delete
# again, outside the workspace, and neither ever saves the sprite it opened. They are
# read-only with respect to everything the caller owns, and they are also the two tools
# an agent calls most often, so prompting on them is pure friction.
READ_ONLY_TOOLS = frozenset({
    "get_cel",
    "get_palette",
    "get_pixels",
    "get_sprite_info",
    "get_tilemap",
    "gui_available",
    "health_check",
    "list_slices",
    "list_sprites",
    "plan_asset_spec",
    "render_preview",
    "validate_asset_spec",
    "validate_minecraft_texture",
    "validate_sprite_for_game_export",
})

# Destroys content that was already there, so a confirmation is actually warranted.
# Every tool that takes an `overwrite` argument is added to this set at registration:
# `overwrite=True` is precisely the ability to replace an existing file.
DESTRUCTIVE_TOOLS = frozenset({
    # Removes an object outright.
    "clear_layer",
    "delete_cel",
    "remove_frame",
    "remove_layer",
    "remove_slice",
    "remove_tag",
    # Collapses several objects into one; the originals do not survive.
    "flatten_sprite",
    "merge_layer_down",
    # Discards pixels or resamples them: the original raster cannot be recovered.
    "crop_sprite",
    "resize_canvas",
    "scale_sprite",
    "set_color_mode",
    "trim_sprite",
    # Overwrites a whole layer or the whole palette with new content.
    "fill_layer",
    "load_palette",
    "replace_color",
    "resize_palette",
    "set_palette",
    # Its op vocabulary includes remove_layer, clear_layer, remove_tag and replace_color,
    # so any given batch may well be destructive.
    "apply_operations",
})

# Adds a new object and leaves existing content alone; none of these can clobber a file.
NON_DESTRUCTIVE_TOOLS = frozenset({
    "add_frame",
    "add_group_layer",
    "add_layer",
    "add_palette_color",
    "add_reference_layer",
    "add_slice",
    "add_tag",
    "add_tile",
    "create_tilemap_layer",
    "duplicate_frame",
    "duplicate_layer",
    # Launches a viewer window and performs no update of its own.
    "open_in_editor",
})


def annotations_for(name: str, *, accepts_overwrite: bool) -> ToolAnnotations:
    """The annotations for one tool, from its name and whether it can clobber a file.

    Anything not on a list above gets `readOnlyHint: false` and no `destructiveHint`.
    That is deliberate rather than lazy: whether painting over a region destroyed
    something depends on what was underneath, and the spec's default for a missing
    `destructiveHint` is `true`, which is the cautious reading we want.
    """
    if name in READ_ONLY_TOOLS:
        if accepts_overwrite:
            raise ValueError(
                f"{name} is listed in READ_ONLY_TOOLS but takes an `overwrite` argument, "
                "so it can replace a file the caller owns. A client that auto-approves on "
                "readOnlyHint would let it. Remove it from READ_ONLY_TOOLS."
            )
        # destructiveHint and idempotentHint are defined only when readOnlyHint is
        # false, so stating them here would be noise.
        return ToolAnnotations(read_only_hint=True, open_world_hint=False)
    if accepts_overwrite or name in DESTRUCTIVE_TOOLS:
        return ToolAnnotations(
            read_only_hint=False, destructive_hint=True, open_world_hint=False
        )
    if name in NON_DESTRUCTIVE_TOOLS:
        return ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=False
        )
    return ToolAnnotations(read_only_hint=False, open_world_hint=False)


class StrictMCPServer(MCPServer):
    """An MCPServer that rejects arguments its tools do not declare.

    The schema layer validates the arguments a tool *does* declare and silently drops the
    rest, so `create_sprite(colour_mode="indexed")` -- when the parameter is `color_mode` --
    returns ok and an RGB sprite. The caller gets a confidently wrong asset and no signal to
    correct on.

    Accepted names are recorded at registration from each function's own signature, so the
    check cannot drift out of step with the tools. Ported verbatim from pixelprep-mcp, where
    this bug was first found.

    The same registration hook attaches each tool's annotations, and `list_tools` puts the
    input schemas into their portable wire form.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._accepted: dict[str, set[str]] = {}

    def tool(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        register_upstream = super().tool

        def register(fn):
            parameters = inspect.signature(fn).parameters.values()
            name = kwargs.get("name") or (args[0] if args and isinstance(args[0], str) else None)
            name = name or fn.__name__
            # **kwargs means the tool genuinely takes open-ended names; do not police it.
            if not any(p.kind is p.VAR_KEYWORD for p in parameters):
                self._accepted[name] = {
                    p.name for p in parameters
                    if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
                }
            options = dict(kwargs)
            if options.get("annotations") is None:
                options["annotations"] = annotations_for(
                    name,
                    accepts_overwrite=any(p.name == "overwrite" for p in parameters),
                )
            return register_upstream(*args, **options)(fn)

        return register

    async def list_tools(self):  # type: ignore[override]
        tools = await super().list_tools()
        return [
            tool.model_copy(update={"input_schema": portable_schema(tool.input_schema)})
            for tool in tools
        ]

    async def call_tool(  # type: ignore[override]
        self, name: str, arguments: dict[str, Any], *args: Any, **kwargs: Any
    ):
        accepted = self._accepted.get(name)
        if accepted is not None:
            unknown = sorted(set(arguments) - accepted)
            if unknown:
                raise UnknownArgumentError(
                    f"{name} does not accept {', '.join(repr(u) for u in unknown)}. "
                    f"Accepted arguments: {', '.join(sorted(accepted))}."
                )
        # Forwarded positionally/by keyword rather than enumerated: call_tool gained a
        # `context` parameter in the 2.x SDK, and an override that pins the older
        # two-argument shape silently stops receiving anything added after it.
        return await super().call_tool(name, arguments, *args, **kwargs)


mcp = StrictMCPServer("aseprite", instructions=INSTRUCTIONS)
