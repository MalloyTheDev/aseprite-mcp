"""Pure-Python tests for the core/MCP split + backwards-compat shims (CI tier)."""

import importlib
import pathlib
import subprocess
import sys

import pytest


def _discovered_core_modules():
    """Every module under `core/`, found rather than listed.

    This was a hand-written list of nine, and `core/` holds twenty-eight. The nineteen it
    missed were, with one exception, the ones added *after* the list was written, which is
    the failure mode of listing: a module is outside the guard by default from the moment
    it is created, and the guard below is the one thing that keeps `core/` reusable without
    MCP. Discovery makes a new module covered because it exists rather than because
    somebody remembered.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aseprite_mcp" / "core"
    names = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.parent if path.name == "__init__.py" else path.with_suffix("")
        parts = rel.relative_to(root).parts
        names.add(".".join(("aseprite_mcp", "core", *parts)))
    return sorted(names)


CORE_MODULES = _discovered_core_modules()

# The nine that were listed by hand before discovery replaced them, kept as a floor. A
# glob that silently returned nothing would make every assertion below pass without
# checking anything, which is the one way this file could stop working without failing.
CORE_MODULES_FLOOR = frozenset({
    "aseprite_mcp.core.config",
    "aseprite_mcp.core.errors",
    "aseprite_mcp.core.limits",
    "aseprite_mcp.core.luagen",
    "aseprite_mcp.core.manifest",
    "aseprite_mcp.core.models",
    "aseprite_mcp.core.paths",
    "aseprite_mcp.core.runner",
    "aseprite_mcp.core.validation",
})

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


def test_the_core_module_list_is_discovered_and_complete():
    """The floor under the guard below, which is only as wide as the list it walks."""
    assert set(CORE_MODULES) >= CORE_MODULES_FLOOR, (
        f"discovery lost modules it used to cover: "
        f"{sorted(CORE_MODULES_FLOOR - set(CORE_MODULES))}")
    assert len(CORE_MODULES) >= 25, (
        f"only {len(CORE_MODULES)} core modules found, which is fewer than exist: the "
        "glob is broken and every import guard in this file is now passing vacuously")


def test_core_does_not_import_mcp_app_or_tools():
    """Importing core must not pull in the MCP app or any tool module, proving
    core is reusable without MCP registration side effects. Checked in a clean
    interpreter so other tests' imports don't pollute the result.

    This is the one test that keeps `core/` a library rather than the inside of a server.
    `tools/` may depend on `core/`; `core/` may depend on neither `tools/` nor the MCP SDK,
    and must not know MCP exists. A clean interpreter is what makes it mean that: an
    indirect import, by way of some module that itself imports the SDK, fails here too,
    which a scan of the source text would miss."""
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
        "draw_pixels", "draw_pixel_map", "draw_line", "draw_polyline", "draw_curve",
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


# ------------------------------------- the two-tier test mechanism has to keep working
def test_the_pure_marker_is_registered():
    """An unregistered marker is a warning, not an error, so a typo would be silent.

    `@pytest.mark.puer` on a test would stop exempting it, the test would go back to
    being skipped on CI, and the only trace would be an `PytestUnknownMarkWarning` in
    output nobody reads. Registering the marker in `pyproject.toml` turns that into a
    visible problem.
    """
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8")
    assert '"pure:' in pyproject, (
        "the `pure` marker is not declared in [tool.pytest.ini_options] markers, so a "
        "misspelled marker would silently stop exempting its test"
    )


def test_no_allowlisted_module_marks_a_test_pure():
    """The two mechanisms answer the same question and should not overlap.

    A module on `PURE_PYTHON_TESTS` already runs in full, so a `pure` marker inside it
    does nothing. It is worth failing on, because somebody writing one has misunderstood
    which mechanism applies, and the next person may copy it into a file where the
    distinction matters.
    """
    import re
    from pathlib import Path

    from conftest import PURE_PYTHON_TESTS

    offenders = []
    for name in PURE_PYTHON_TESTS:
        path = Path(__file__).resolve().parent / f"{name}.py"
        if not path.is_file():
            continue
        if re.search(r"^\s*@pytest\.mark\.pure\b", path.read_text(encoding="utf-8"),
                     re.M):
            offenders.append(name)
    assert not offenders, (
        f"these modules are already on the always-run allowlist, so the `pure` marker "
        f"in them has no effect: {sorted(offenders)}"
    )


def test_pure_marked_tests_exist_and_are_outside_the_allowlist():
    """Pins the mechanism's reason for existing.

    If this reaches zero, either the markers were lost in a refactor or every marked
    test's module joined the allowlist, and in the second case the vacuous-pass problem
    the marker exists to avoid has been reintroduced. Either way it is worth noticing.
    """
    import re
    from pathlib import Path

    from conftest import PURE_PYTHON_TESTS

    marked = {}
    for path in sorted((Path(__file__).resolve().parent).glob("test_*.py")):
        hits = len(re.findall(r"^\s*@pytest\.mark\.pure\b",
                              path.read_text(encoding="utf-8"), re.M))
        if hits:
            marked[path.stem] = hits

    assert marked, "no test carries the `pure` marker; the mechanism is unused"
    overlap = set(marked) & set(PURE_PYTHON_TESTS)
    assert not overlap, f"marked inside an allowlisted module: {sorted(overlap)}"


def test_the_visible_pixel_count_is_defined_once():
    """One number, one implementation.

    `set_color_mode` compares drawn pixels across a conversion to refuse one that would
    make art disappear, and `diff_sprites` reports the same count per side. Each used to
    carry its own loop for it, and the two loops disagreed about what indexed
    transparency is: the sprite's transparent index is one kind, a palette entry that is
    itself transparent is another, and a count that tests only the first reports a blank
    canvas as drawn. That mistake has already shipped here once (#138), which is why the
    helper is shared and why a second copy is worth failing a test over.

    Source text rather than behaviour, because a duplicate would agree with the original
    on every sprite a runtime test is likely to build. Agreement is exactly what makes a
    duplicate hard to notice.
    """
    import pathlib

    import aseprite_mcp
    from aseprite_mcp.core import luagen

    assert "local function visible_count(spr, img)" in luagen.PRELUDE, (
        "the shared helper is no longer in the prelude; the two callers have nowhere to "
        "share it from"
    )

    root = pathlib.Path(aseprite_mcp.__file__).resolve().parent
    offenders = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "tools").glob("*.py"))
        if "local function visible_count" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"{offenders} define their own visible_count; call the prelude's instead so "
        "both callers of this number cannot drift apart"
    )


def test_every_tool_that_takes_a_ramp_reports_it_against_an_indexed_palette():
    """A `ramp` argument on an indexed sprite is a request the palette may not be able to
    honour, and the tool has to say so.

    On an indexed sprite a pixel is an offset, so `rgba_to_px` sends a ramp colour the
    palette does not hold through `nearest_index` and it lands on the nearest entry that
    can draw. Two ramp steps can therefore resolve to one entry, which makes a shade
    between them a no-op that reports the pixels it wrote, and `palette_conformance`
    cannot see it because the colour landed on is still on the declared ramp (#145).

    The measurement is attached by the Lua harness to any tool whose ARG carries a
    `ramp`, and `run_ramp_lua` turns it into a warning. This test is why that convention
    is safe to rely on: a new shading tool that reaches for `run_lua` instead fails here
    rather than shipping shading that silently bands on indexed art.

    Every registered tool with a `ramp` parameter is now held to one of three promises,
    and none of them is "nothing". Most go through `run_ramp_lua`; `assess_sprite`
    surfaces the same reading itself, beside the conformance number it qualifies; and
    `smear_frame`, which resolves its ramp into a lookup table before the launch and has
    no `ARG.ramp` for the harness to see, measures that table's targets instead (#173).
    """
    import asyncio
    import importlib
    import inspect as inspect_mod
    import pkgutil

    from aseprite_mcp import tools as tools_pkg
    from aseprite_mcp.server import mcp

    # The registered tools, not every callable with a `ramp` parameter: `_smear_ramp` is
    # a private helper that parses one and `run_ramp_lua` is the wrapper itself, and
    # neither is something a caller can reach.
    registered = {t.name for t in asyncio.run(mcp.list_tools())}

    # smear_frame takes a ramp and does not go through `run_ramp_lua`, on purpose, and
    # that is now the whole of the exemption rather than a gap. It resolves the ramp in
    # Python into a colour-to-colour lookup table (`inbetween.shift_table`) and never
    # passes a ramp to Lua at all, so the harness has nothing to measure and routing it
    # through `run_ramp_lua` would measure the wrong thing: the question for it is what
    # the *table's* target colours resolve to, and a declared ramp step nothing shifts
    # that far is not a finding. It calls the prelude's `ramp_palette_state` from its own
    # write body with those targets and judges the answer with
    # `indexed.shift_table_readings`, so it is held to that instead (#173).
    resolves_its_ramp_in_python = {"smear_frame"}
    # assess_sprite measures instead of writing, so its reading belongs in `readings`
    # beside the conformance number it qualifies, not in `warnings`. It passes the ramp
    # to Lua for the measurement and consumes it itself.
    reports_it_as_a_reading = {"assess_sprite"}

    checked = []
    for info in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"aseprite_mcp.tools.{info.name}")
        for name, obj in vars(module).items():
            fn = getattr(obj, "fn", None) if hasattr(obj, "fn") else None
            target = fn or obj
            if not callable(target) or getattr(target, "__module__", "") != module.__name__:
                continue
            try:
                signature = inspect_mod.signature(target)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                continue
            if name not in registered or "ramp" not in signature.parameters:
                continue
            source = inspect_mod.getsource(target)
            if name in resolves_its_ramp_in_python:
                assert "shift_table_readings" in source, (
                    f"{name} resolves its ramp in Python, so the harness cannot measure "
                    "it, and it no longer calls indexed.shift_table_readings either: on "
                    "an indexed sprite its trail will band onto one palette entry and "
                    "report nothing. Measure the table's targets with the prelude's "
                    "ramp_palette_state and judge them there."
                )
                checked.append(name)
                continue
            if name in reports_it_as_a_reading:
                assert "ramp_readings" in source, (
                    f"{name} takes a ramp and surfaces the reading itself, but no longer "
                    "calls indexed.ramp_readings"
                )
                checked.append(name)
                continue
            assert "run_ramp_lua(" in source, (
                f"{name} takes a ramp but runs through plain run_lua, so on an indexed "
                "sprite it will resolve the ramp against the palette and report nothing. "
                "Use run_ramp_lua, or add it to an exemption here with the reason."
            )
            checked.append(name)

    # The list is asserted rather than just iterated: a lookup that quietly found nothing
    # would pass every assertion above and prove nothing at all.
    assert sorted(checked) == [
        "assess_sprite", "cast_shadow", "contact_shadow", "dither_band", "glow",
        "gradient_map", "outline_smart", "shade_region_by_light", "shift_along_ramp",
        "smear_frame", "specular_highlight",
    ], f"the set of ramp tools changed: {sorted(checked)}"


def test_the_ramp_measurement_is_keyed_on_the_name_every_tool_uses():
    """The harness finds the ramp by looking for `ARG.ramp`, so a tool that passes its
    parsed ramp under any other key gets no measurement and no warning, silently.

    Pinned here because the failure is invisible: the tool works, the shading lands, and
    the one thing that would have told the caller their palette cannot hold the ramp is
    missing. Checking the arg key is the only way to catch it without an indexed sprite
    per tool.
    """
    import asyncio
    import importlib
    import inspect as inspect_mod
    import pkgutil

    from aseprite_mcp import tools as tools_pkg
    from aseprite_mcp.server import mcp

    registered = {t.name for t in asyncio.run(mcp.list_tools())}

    for info in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"aseprite_mcp.tools.{info.name}")
        for name, obj in vars(module).items():
            target = getattr(obj, "fn", obj)
            if name not in registered or not callable(target):
                continue
            try:
                body = inspect_mod.getsource(target)
            except (OSError, TypeError):  # pragma: no cover - defensive
                continue
            if "run_ramp_lua(" not in body:
                continue
            assert '"ramp":' in body, (
                f"{name} calls run_ramp_lua but passes no \"ramp\" key to Lua, so the "
                "harness has nothing to measure and the wrapper will always be silent"
            )
