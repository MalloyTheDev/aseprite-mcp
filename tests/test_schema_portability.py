"""Registry-wide guards on the wire form of the tool schemas and their annotations.

These assert properties of *every* registered tool rather than of an example, because
both problems they guard against are reintroduced by adding a tool, not by editing one:

  * a new `x: int | None = None` parameter brings back the nullable `anyOf` and the
    pydantic `title` noise that strict function-calling clients mishandle;
  * a new `get_*` tool that quietly saves the sprite it opened, added to
    `READ_ONLY_TOOLS` by pattern-matching on its name, would be auto-approved by every
    client that honours `readOnlyHint` -- which is strictly worse than no annotation.

Pure Python: nothing here launches Aseprite.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
import textwrap
import types

import pytest

from aseprite_mcp import server  # noqa: F401  importing registers every tool
from aseprite_mcp.app import (
    DESTRUCTIVE_TOOLS,
    NON_DESTRUCTIVE_TOOLS,
    READ_ONLY_TOOLS,
    annotations_for,
    mcp,
    portable_schema,
)

# `_tool_manager` is the only place the underlying function object is reachable, and the
# source scan below needs it. `list_tools()` deliberately returns the wire view.
REGISTERED = {tool.name: tool for tool in mcp._tool_manager.list_tools()}


@pytest.fixture(scope="module")
def wire_tools():
    """Every tool exactly as `tools/list` presents it."""
    import asyncio

    return asyncio.run(mcp.list_tools())


def schema_nodes(node):
    """Every JSON Schema object inside `node`.

    Independent of the walk in `app.py` on purpose: if that one stopped descending into
    some branch, a shared implementation would stop checking it too.
    """
    if isinstance(node, dict):
        yield node
        for key in ("items", "additionalProperties", "not", "contains", "propertyNames"):
            yield from schema_nodes(node.get(key))
        for key in ("properties", "$defs", "definitions", "patternProperties"):
            child = node.get(key)
            if isinstance(child, dict):
                for value in child.values():
                    yield from schema_nodes(value)
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            child = node.get(key)
            if isinstance(child, list):
                for value in child:
                    yield from schema_nodes(value)


def properties_of(schema):
    yield from (schema.get("properties") or {}).items()


# ---------------------------------------------------------------------------
# Wire schema
# ---------------------------------------------------------------------------


def test_registry_is_not_empty(wire_tools):
    # Every other test here passes trivially on an empty registry, so an import that
    # silently registered nothing must fail loudly instead.
    assert len(wire_tools) > 100


def test_no_title_anywhere(wire_tools):
    offenders = [
        t.name
        for t in wire_tools
        if any("title" in node for node in schema_nodes(t.input_schema))
    ]
    assert offenders == [], (
        "these tools' input schemas still carry a pydantic `title`, which costs tokens "
        f"on every tools/list and tells a client nothing: {offenders}"
    )


def test_no_nullable_anyof_anywhere(wire_tools):
    offenders = []
    for t in wire_tools:
        for node in schema_nodes(t.input_schema):
            members = node.get("anyOf")
            if not isinstance(members, list) or len(members) != 2:
                continue
            if any(isinstance(m, dict) and m.get("type") == "null" for m in members):
                offenders.append(t.name)
    assert offenders == [], (
        "these tools expose a nullable two-member anyOf. Cline, Continue and LM Studio "
        "render it with no type, after which weaker models omit the argument or send the "
        f"string \"null\": {sorted(set(offenders))}"
    )


def test_every_property_has_a_concrete_type(wire_tools):
    offenders = [
        f"{t.name}.{name}"
        for t in wire_tools
        for name, prop in properties_of(t.input_schema)
        if "type" not in prop
    ]
    assert offenders == [], (
        "these parameters reach the wire with no `type`, so a strict client cannot build "
        "a function definition for them. A genuine union (int | str) needs a deliberate "
        f"decision about which type the wire advertises: {offenders}"
    )


def test_defaults_are_stated_in_the_description(wire_tools):
    offenders = []
    for t in wire_tools:
        for name, prop in properties_of(t.input_schema):
            if "default" not in prop:
                continue
            stated = f"Default: {json.dumps(prop['default'])}."
            if stated not in (prop.get("description") or ""):
                offenders.append(f"{t.name}.{name}")
    assert offenders == [], (
        "OpenAI strict mode drops the `default` keyword, so a default that lives only "
        f"there is invisible to the model: {offenders}"
    )


def test_no_default_of_null_survives(wire_tools):
    # `default: null` on a property whose type was collapsed to `integer` contradicts the
    # declared type; absence from `required` already says the argument is optional.
    offenders = []
    for t in wire_tools:
        for name, prop in properties_of(t.input_schema):
            if "default" in prop and prop["default"] is None:
                declared = prop.get("type")
                allows_null = declared == "null" or (
                    isinstance(declared, list) and "null" in declared
                )
                if not allows_null:
                    offenders.append(f"{t.name}.{name}")
    assert offenders == []


def test_required_names_all_exist(wire_tools):
    # A `required` entry naming a property that is not there would make a strict client
    # send an argument the server then rejects.
    for t in wire_tools:
        props = set(dict(properties_of(t.input_schema)))
        missing = sorted(set(t.input_schema.get("required") or []) - props)
        assert missing == [], f"{t.name} requires undeclared properties: {missing}"


def test_the_pass_is_idempotent(wire_tools):
    # list_tools applies it on every call; a pass that kept rewriting its own output
    # would grow the description by one "Default:" clause per request.
    for t in wire_tools:
        assert portable_schema(t.input_schema) == t.input_schema, t.name


def test_validation_still_accepts_an_explicit_null():
    # The wire schema is a presentation. The pydantic model that actually validates a
    # call must keep accepting null for an optional argument, or collapsing the union
    # would have narrowed the server's real contract.
    model = REGISTERED["get_pixels"].fn_metadata.arg_model
    assert model.model_validate({"filename": "a.aseprite", "width": None}).width is None


def test_a_parameter_named_title_or_default_is_not_deleted():
    # The walk has to know which keys are schema keywords: `properties` keys are
    # parameter names, and a blind recursion would delete parameters called `title`
    # or `default` along with the noise.
    schema = {
        "type": "object",
        "title": "fakeArguments",
        "properties": {
            "title": {"title": "Title", "type": "string"},
            "default": {"title": "Default", "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "default": None},
        },
        "required": ["title"],
    }
    out = portable_schema(schema)
    assert "title" not in out
    assert set(out["properties"]) == {"title", "default"}
    assert out["properties"]["title"] == {"type": "string"}
    assert out["properties"]["default"] == {"type": "integer"}


def test_a_real_union_is_left_alone():
    # Collapsing `int | str` would have to throw one member away, so it is out of scope.
    schema = {"type": "object", "properties": {
        "x": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    }}
    assert portable_schema(schema)["properties"]["x"]["anyOf"] == [
        {"type": "integer"}, {"type": "string"},
    ]


def test_array_item_types_survive_the_collapse():
    schema = {"type": "object", "properties": {
        "names": {"title": "Names", "default": None,
                  "anyOf": [{"items": {"type": "string"}, "type": "array"},
                            {"type": "null"}]},
    }}
    assert portable_schema(schema)["properties"]["names"] == {
        "type": "array", "items": {"type": "string"},
    }


def test_the_source_schema_is_not_mutated():
    # gen_tool_docs and the argument validator both read the derived schema; the pass
    # must hand back a copy rather than edit theirs.
    schema = {"type": "object", "title": "x", "properties": {"a": {"title": "A", "type": "string"}}}
    portable_schema(schema)
    assert schema["title"] == "x"
    assert schema["properties"]["a"]["title"] == "A"


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

# Markers for "this writes to disk". `save_sprite`/`saveAs` save the open sprite,
# `--save-as`/`--sheet`/`--split-layers` are Aseprite CLI flags that write a file, and
# the rest are Python writes. `mkdir` is deliberately absent: resolving any path creates
# the workspace directory, so it matches every tool and says nothing.
WRITE_MARKERS = (
    "save_sprite(",
    "saveAs",
    ":save()",
    "--save-as",
    "--sheet",
    "--split-layers",
    "write_text",
    "write_bytes",
    "json.dump(",
    "shutil.copy",
    "shutil.move",
    "os.replace",
)

# Modules the scan does not follow into. The runner ships a shared Lua preamble that
# *defines* save_sprite and saveAs for every tool, so following it would mark all 117 as
# writers; what matters is whether a tool's own Lua calls them.
RUNNER_MODULES = frozenset({
    "aseprite_mcp.core.runner",
    "aseprite_mcp.core.luagen",
    "aseprite_mcp.runner",
    "aseprite_mcp.luagen",
})

# Tools the scan flags that are nonetheless read-only with respect to the caller. Each
# writes only to a private `tempfile` path outside the workspace and deletes it again,
# and neither saves the sprite it opened. Reviewed by reading both functions in full.
# A new name may not be added here without the same review.
TEMP_FILE_ONLY = frozenset({"render_preview", "health_check"})


def _referenced(source: str, module: types.ModuleType):
    """Objects `source` names: module globals, and attributes of modules it imported."""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:  # pragma: no cover - defensive
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield getattr(module, node.id, None)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                base = getattr(module, node.value.id, None)
                if isinstance(base, types.ModuleType):
                    yield getattr(base, node.attr, None)
                    continue
            yield getattr(module, node.attr, None)


def write_markers_reachable_from(fn, depth: int = 6) -> list[str]:
    """Write markers in a tool's own source, or in the helpers and Lua string constants
    it reaches inside the package. The Lua a tool runs is assembled from module-level
    strings, so the scan has to follow those as well as the calls."""
    found: set[str] = set()
    seen: set[int] = set()

    def visit(obj, budget: int) -> None:
        if budget < 0 or id(obj) in seen:
            return
        seen.add(id(obj))
        try:
            source = inspect.getsource(obj)
        except (TypeError, OSError):  # pragma: no cover - defensive
            return
        found.update(m for m in WRITE_MARKERS if m in source)
        module = sys.modules.get(getattr(obj, "__module__", "") or "")
        if module is None:  # pragma: no cover - defensive
            return
        for target in _referenced(source, module):
            if isinstance(target, str):
                found.update(m for m in WRITE_MARKERS if m in target)
            elif isinstance(target, types.FunctionType):
                origin = getattr(target, "__module__", "")
                if origin.startswith("aseprite_mcp") and origin not in RUNNER_MODULES:
                    visit(target, budget - 1)

    visit(fn, depth)
    return sorted(found)


def derived_writers() -> dict[str, list[str]]:
    """Tools that write to disk, derived from the code two independent ways: an
    `overwrite` parameter (which *is* the ability to replace an existing file) and the
    source scan above."""
    writers: dict[str, list[str]] = {}
    for name, tool in REGISTERED.items():
        reasons = []
        if "overwrite" in inspect.signature(tool.fn).parameters:
            reasons.append("takes overwrite=")
        markers = write_markers_reachable_from(tool.fn)
        if markers:
            reasons.append(f"writes via {', '.join(markers)}")
        if reasons:
            writers[name] = reasons
    return writers


def test_the_write_scan_finds_the_obvious_writers():
    # Guards the guard: if the scan silently stopped resolving the Lua constants, it
    # would report no writers and every readOnlyHint assertion below would pass.
    writers = derived_writers()
    for name in ("draw_line", "export_png", "remove_layer", "apply_operations",
                 "create_character_sprite", "build_asset_from_spec", "set_tile"):
        assert name in writers, f"{name} writes to disk but the scan missed it"
    for name in ("get_sprite_info", "get_pixels", "list_sprites", "get_palette",
                 "gui_available", "validate_asset_spec"):
        assert name not in writers, f"{name} was flagged as a writer: {writers.get(name)}"


def test_no_writer_is_marked_read_only():
    offenders = {
        name: reasons
        for name, reasons in derived_writers().items()
        if name in READ_ONLY_TOOLS and name not in TEMP_FILE_ONLY
    }
    assert offenders == {}, (
        "a client that auto-approves on readOnlyHint would let these mutate the "
        f"caller's files without asking: {offenders}"
    )


def test_temp_file_exemptions_have_not_grown():
    # The exemption is a reviewed judgement about two specific functions, not a
    # category. A third tool joining it must be a deliberate edit with a fresh review.
    assert {"render_preview", "health_check"} == TEMP_FILE_ONLY
    assert TEMP_FILE_ONLY <= READ_ONLY_TOOLS


def test_no_read_only_tool_takes_overwrite():
    # Also enforced at registration, where it raises; asserted here so the reason is
    # recorded next to the rest of the classification.
    offenders = [
        name for name in READ_ONLY_TOOLS
        if "overwrite" in inspect.signature(REGISTERED[name].fn).parameters
    ]
    assert offenders == []


def test_a_read_only_tool_that_gains_overwrite_fails_at_registration():
    # The guard that matters most fires before the server serves anything: adding an
    # `overwrite` argument to a tool on the read-only list must stop the import, not
    # quietly ship a readOnlyHint that clients auto-approve.
    with pytest.raises(ValueError, match="READ_ONLY_TOOLS"):
        annotations_for("get_sprite_info", accepts_overwrite=True)


def test_every_tool_is_annotated(wire_tools):
    unannotated = [t.name for t in wire_tools if t.annotations is None]
    assert unannotated == []


def test_open_world_hint_is_false_everywhere(wire_tools):
    # This server reaches the local filesystem and a local Aseprite process, nothing else.
    offenders = [t.name for t in wire_tools if t.annotations.open_world_hint is not False]
    assert offenders == []


def test_read_only_hint_matches_the_classification(wire_tools):
    marked = {t.name for t in wire_tools if t.annotations.read_only_hint}
    assert marked == set(READ_ONLY_TOOLS)


def test_destructive_hint_is_set_for_clobbering_and_removing_tools(wire_tools):
    by_name = {t.name: t for t in wire_tools}
    for name in DESTRUCTIVE_TOOLS:
        assert by_name[name].annotations.destructive_hint is True, name
    for name, tool in REGISTERED.items():
        if "overwrite" in inspect.signature(tool.fn).parameters:
            assert by_name[name].annotations.destructive_hint is True, (
                f"{name} can replace an existing file but is not marked destructive"
            )


def test_non_destructive_claim_is_only_made_for_tools_that_cannot_clobber(wire_tools):
    by_name = {t.name: t for t in wire_tools}
    for name in NON_DESTRUCTIVE_TOOLS:
        assert "overwrite" not in inspect.signature(REGISTERED[name].fn).parameters, name
        assert by_name[name].annotations.destructive_hint is False, name


def test_classification_sets_are_disjoint_and_name_real_tools():
    sets = {
        "READ_ONLY_TOOLS": READ_ONLY_TOOLS,
        "DESTRUCTIVE_TOOLS": DESTRUCTIVE_TOOLS,
        "NON_DESTRUCTIVE_TOOLS": NON_DESTRUCTIVE_TOOLS,
    }
    for label, names in sets.items():
        # A renamed or deleted tool must not leave a stale entry behind: the next tool
        # to take that name would silently inherit the old classification.
        unknown = sorted(names - set(REGISTERED))
        assert unknown == [], f"{label} names tools that are not registered: {unknown}"
    assert not READ_ONLY_TOOLS & DESTRUCTIVE_TOOLS
    assert not READ_ONLY_TOOLS & NON_DESTRUCTIVE_TOOLS
    assert not DESTRUCTIVE_TOOLS & NON_DESTRUCTIVE_TOOLS
