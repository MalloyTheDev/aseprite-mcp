"""Indexed colour mode: the decisions a palette needs before Aseprite is launched.

An indexed sprite is the only colour mode here whose pixels are not colours. They are
offsets into a palette, and one of those offsets, `transparentColor`, does not mean a
colour at all; it means "no pixel here". Every way that fact can be got wrong has now
been got wrong at least once:

  * a new indexed sprite came out of Aseprite with 256 entries that were all opaque
    black, so every colour request was equidistant from every entry, the first one won,
    and the first one is the transparent index. Every draw landed, invisibly, and
    reported the pixels it had written (#138).
  * converting an RGB sprite to indexed mapped the art against whatever palette the
    sprite happened to carry, and a saved RGB sprite carries one transparent entry. The
    art did not survive the conversion and nothing said so (#137).

What lives here is the part that is arithmetic and naming rather than pixels: which mode
names and algorithm names are real, and what palette a new indexed sprite should start
with. The pixel work stays in Lua, where the editor is.
"""

from __future__ import annotations

import math

from .errors import ValidationFailed

# --------------------------------------------------------------------------- #
# Enumerations                                                                #
# --------------------------------------------------------------------------- #
# Spellings callers actually use, mapped to the three modes Aseprite has. Normalising
# in Python rather than in Lua is the difference between a typo that costs a rejected
# argument and a typo that costs an Aseprite launch.
_COLOR_MODE_ALIASES = {
    "rgb": "rgb",
    "indexed": "indexed",
    "gray": "gray",
    "grey": "gray",
    "grayscale": "gray",
    "greyscale": "gray",
}

COLOR_MODES = ("rgb", "indexed", "gray")

# How a colour that falls between two palette entries is resolved when converting to
# indexed. Validated here because Aseprite does not validate it: `ChangePixelFormat`
# accepts `dithering = "no-such-dither"` without complaint and quietly converts with
# its default, so a misspelled algorithm used to report success having done something
# other than what was asked.
DITHERING_ALGORITHMS = ("none", "ordered", "old")

# Where the palette an indexed conversion maps against comes from.
#
# "from_art" is what the editor's own RGB-to-indexed does: quantize the sprite first so
# the palette holds the colours the art is actually painted with, then map onto it.
# "keep" maps against the palette the sprite already has, which is what a caller wants
# after deliberately loading a .gpl or hand-building a ramp, and is also exactly how
# #137 destroyed the art of anyone who had not done so.
PALETTE_SOURCES = ("from_art", "keep")


def _normalise(field: str, value, aliases: dict[str, str], remedy: str = "") -> str:
    """Look `value` up in `aliases`, raising `ValidationFailed` that names the choices.

    The message lists the canonical names rather than every spelling that maps to them,
    so a caller is told what to say and not how many ways there are to say it.
    """
    found = aliases.get(str(value).strip().lower())
    if found is None:
        allowed = ", ".join(sorted(set(aliases.values())))
        message = f"{field} must be one of: {allowed}. Got {value!r}."
        raise ValidationFailed(f"{message} {remedy}".strip())
    return found


def normalise_color_mode(value) -> str:
    """Canonicalise a colour mode name to "rgb", "indexed" or "gray".

    Accepts the grey/gray and -scale spellings because both get typed and both mean the
    same mode. It does not accept "rgba": an RGB sprite here always has an alpha channel,
    so "rgba" is not a fourth mode but a guess about which of the three was meant, and
    this codebase refuses guesses.
    """
    return _normalise("color_mode", value, _COLOR_MODE_ALIASES)


def normalise_dithering(value) -> str:
    """Canonicalise a dithering algorithm name, or refuse it."""
    return _normalise(
        "dithering", value, {name: name for name in DITHERING_ALGORITHMS},
        remedy="Dithering only applies when converting to indexed.",
    )


def normalise_palette_source(value) -> str:
    """Canonicalise a `palette_source`, or refuse it."""
    return _normalise(
        "palette_source", value, {name: name for name in PALETTE_SOURCES},
        remedy='"from_art" builds a palette from the sprite; "keep" uses the one it has.',
    )


# --------------------------------------------------------------------------- #
# The palette a new indexed sprite starts with                                #
# --------------------------------------------------------------------------- #
# The 32 colours Aseprite ships as its factory default palette (DawnBringer 32), copied
# here rather than read from `app.defaultPalette` at run time.
#
# Reading the editor's own default would track whatever the operator has configured,
# which sounds like the friendly choice and is not: it makes the contents of a file this
# server creates depend on a preferences file nobody in the conversation can see. Two
# machines running the same `create_sprite` call would produce different sprites, and an
# operator whose default palette happens to be three colours would get a sprite that is
# nearly as undrawable as the 256 blacks this replaces. Pinning the values keeps
# `create_sprite` a function of its arguments.
_DEFAULT_COLORS = (
    "#000000ff", "#222034ff", "#45283cff", "#663931ff", "#8f563bff", "#df7126ff",
    "#d9a066ff", "#eec39aff", "#fbf236ff", "#99e550ff", "#6abe30ff", "#37946eff",
    "#4b692fff", "#524b24ff", "#323c39ff", "#3f3f74ff", "#306082ff", "#5b6ee1ff",
    "#639bffff", "#5fcde4ff", "#cbdbfcff", "#ffffffff", "#9badb7ff", "#847e87ff",
    "#696a6aff", "#595652ff", "#76428aff", "#ac3232ff", "#d95763ff", "#d77bbaff",
    "#8f974aff", "#8a6f30ff",
)

# Index 0 is a fully transparent entry, and the 32 colours follow it.
#
# A new sprite's `transparentColor` is 0, so index 0 is the one offset that means "no
# pixel here". Putting a colour there is how the editor's own default palette reads, and
# it is a trap: the entry is opaque black, black is the commonest colour in pixel art,
# and a request for black would resolve to the index that draws nothing. Spending entry
# 0 on transparency costs one palette slot and makes the palette say what is true.
DEFAULT_INDEXED_PALETTE = ("#00000000", *_DEFAULT_COLORS)


def _hex(color: dict) -> str:
    """An `{r, g, b, a}` colour spec as the "#rrggbbaa" string a palette tool takes.

    Channels arrive already in 0..255: `ColorSpec` clamps the numeric form and the hex
    forms cannot exceed a byte. Deliberately not masked to a byte here, because a mask
    would turn an out-of-range channel into a different colour silently; an over-wide
    value instead formats to an over-long string that `parse_color` rejects outright.
    """
    return "#{:02x}{:02x}{:02x}{:02x}".format(
        color["r"], color["g"], color["b"], color["a"]
    )


def palette_for_new_sprite(background: dict | None) -> list[str]:
    """The palette to install on a newly created indexed sprite.

    `background` is a parsed colour spec (`ColorSpec.as_dict()`) or None.

    An indexed sprite can only hold colours its palette names, so a background colour
    that is not in the palette can only be approximated, and a `create_sprite` that
    quietly substituted the nearest default colour for the one it was given would be
    doing less than it claimed. The requested colour is therefore appended when the
    default palette does not already contain it, which makes the background exact and
    leaves the rest of the palette to draw with.

    An `index:N` background names an offset rather than a colour, so there is nothing to
    add: the default palette is 33 entries deep and the index resolves against it.
    """
    colors = list(DEFAULT_INDEXED_PALETTE)
    if background is None or background.get("index") is not None:
        return colors
    wanted = _hex(background)
    if wanted not in colors:
        colors.append(wanted)
    return colors


# --------------------------------------------------------------------------- #
# Entries a palette holds and cannot draw                                     #
# --------------------------------------------------------------------------- #
def palette_readings(state: dict, color_mode: str) -> list[str]:
    """What is worth saying about a palette that was just written to a sprite.

    `state` is the measurement the Lua side takes: `size`, `transparent_index`,
    `at_transparent_index` (the colour sitting there, or None when the index is out of
    range) and `drawable`, the number of entries that could actually produce a visible
    pixel.

    An indexed pixel is an offset, and one offset means "no pixel here". So an opaque
    colour sitting at the sprite's transparent index is in the palette, is reported by
    `get_palette`, and can never be drawn: `nearest_index` excludes that offset, because
    answering a colour question with it writes nothing. Nobody has done anything wrong
    when that happens, which is why this warns rather than refuses. `set_palette` with
    an opaque entry at index 0 is perfectly reasonable for a sprite that never draws
    that colour.

    It bites in a way that looks like a tool bug rather than a palette one. A ramp
    written darkest-first, which is the natural order, puts its darkest colour at index
    0, and that colour then silently resolves to its nearest *drawable* neighbour: the
    shading comes out banded and every tool reports success.

    `sort_palette` does not create this, which is worth saying because it looks as
    though it should: it remaps `spr.transparentColor` through the same table it remaps
    the pixels with, so the transparent index follows its entry and keeps pointing at a
    transparent colour however the palette is reordered.

    Nothing here applies to RGB or grayscale, where a pixel carries its own alpha and
    `transparentColor` means nothing, so those return no readings at all rather than a
    warning a caller cannot act on.
    """
    if color_mode != "indexed":
        return []

    out: list[str] = []
    index = state.get("transparent_index")
    shadowed = state.get("at_transparent_index")
    size = state.get("size") or 0
    drawable = state.get("drawable")

    if shadowed is not None and not str(shadowed).lower().endswith("00"):
        out.append(
            f"Palette entry {index} is {shadowed}, and {index} is this sprite's "
            "transparent index, so that colour cannot be drawn: a request for it "
            "resolves to the nearest entry that can be. The palette will still report "
            f"it. Point the transparent index somewhere else with set_transparent_color, "
            "or order the palette so the colour you mean to draw is not at index "
            f"{index}. A transparent entry at {index} is the usual arrangement."
        )

    if drawable == 0:
        out.append(
            f"None of this palette's {size} entries can draw a visible pixel: every one "
            f"is either transparent or sits at the transparent index ({index}). Drawing "
            "by colour will be refused until the palette has something to draw with "
            "(add_palette_color, or set_palette)."
        )
    elif drawable is not None and size and drawable < size - 1:
        out.append(
            f"{size - drawable} of {size} palette entries cannot draw a visible pixel "
            "(transparent, or at the transparent index). That is only a problem if you "
            "expected to draw with one of them."
        )
    return out

# --------------------------------------------------------------------------- #
# A declared ramp against the palette that has to hold it                     #
# --------------------------------------------------------------------------- #
# Below this share of a ramp surviving as distinct colours, the ramp is not really on
# this palette and the shading will band however well the tool does its job. Two steps
# merging out of eight is a palette with a gap in it; half of them merging is the wrong
# palette for this ramp. The number is a reporting threshold only: nothing is refused.
RAMP_MOSTLY_PRESENT = 0.75


def ramp_readings(state: dict) -> list[str]:
    """What is worth saying about a ramp declared against an indexed sprite's palette.

    `state` is the measurement the Lua harness takes whenever a tool is given a `ramp`
    and the sprite is indexed: `declared` (how many steps were passed), `resolved` (how
    many distinct palette entries those steps landed on), `exact` (how many were in the
    palette exactly) and `steps`, one record per entry with the colour asked for, the
    index it resolved to and the colour that index holds.

    An indexed pixel is an offset into a palette, so a shading tool cannot write a colour
    the palette does not hold. `rgba_to_px` sends it through `nearest_index` and it lands
    on the nearest entry that can draw. That is not a bug and refusing it would make the
    shading tools unusable on exactly the sprites that most want a fixed palette, which
    is why every reading here is a reading and not a refusal.

    It needs saying because two of its consequences are invisible in the result:

    * **A shade between two steps that resolve to one entry does nothing.** The tool
      reports the pixels it wrote and the picture is unchanged. Measured: a sprite drawn
      in a ramp's step 1, shifted one step up against a palette holding three of the
      ramp's five colours, came back byte for byte identical with
      `pixels_written: 144`.
    * **`palette_conformance` does not catch it.** The colour the pixel snapped to is
      still a colour on the declared ramp, so conformance reads 1.0 for a no-op. The
      metric that exists to separate shading from filtering is blind to this case,
      which is why the finding has to come from the palette and not from the pixels.

    Nothing is said when every step is present and distinct, which is the normal case for
    a palette built from the ramp (`generate_ramp` then `set_palette`), and nothing is
    said about RGB or grayscale sprites because the harness only measures indexed ones.
    """
    steps = state.get("steps") or []
    declared = state.get("declared") or len(steps)
    resolved = state.get("resolved") or 0
    exact = state.get("exact") or 0

    if state.get("undrawable_palette"):
        # No step can be resolved, because no entry can draw. Said here rather than left
        # to the measurement's silence: a tool that wrote nothing on such a sprite
        # succeeds (there was nothing to write), and the reason it had no effect is a
        # fact about the palette that nothing else in its result mentions. A tool that
        # does try to draw gets the refusal from `nearest_index` instead.
        return [
            "This sprite's palette has no entry that can draw a visible pixel, so none "
            f"of the {declared} declared ramp steps could be resolved and shading it "
            "cannot do anything. add_palette_color or set_palette first."
        ]

    if not steps or not declared:
        return []

    out: list[str] = []

    if resolved < declared:
        # Grouped by the index they landed on, in ramp order, so the reader sees which
        # steps merged rather than a count they have to reconstruct.
        groups: dict[int, list[dict]] = {}
        for entry in steps:
            groups.setdefault(entry.get("index"), []).append(entry)
        merged = [group for group in groups.values() if len(group) > 1]
        named = "; ".join(
            "steps {} ({}) all resolve to palette entry {} ({})".format(
                " and ".join(str(e.get("step")) for e in group),
                ", ".join(str(e.get("want")) for e in group),
                group[0].get("index"),
                group[0].get("got"),
            )
            for group in merged
        )
        out.append(
            f"This sprite is indexed and its palette holds {resolved} of the "
            f"{declared} declared ramp steps as distinct colours: {named}. A shade "
            "between two steps that resolve to the same entry changes nothing, and "
            "still reports the pixels it wrote. palette_conformance will not show it "
            "either, because the colour landed on is still on the ramp. Add the missing "
            "colours with add_palette_color or set_palette, or declare the ramp the "
            "palette actually holds."
        )
    elif exact < declared:
        # Every step still distinct, so the shading will read as shading; the colours are
        # just not the ones that were asked for. Worth one line, not an alarm.
        shifted = [e for e in steps if not e.get("exact")]
        # Four examples and then a count, not the whole list: past a handful this is the
        # measurement again rather than a finding, and `ramp_on_palette` carries every
        # step for anyone who wants them all.
        shown = ", ".join(f"{e.get('want')} as {e.get('got')}" for e in shifted[:4])
        rest = f", and {len(shifted) - 4} more" if len(shifted) > 4 else ""
        out.append(
            f"{len(shifted)} of the {declared} declared ramp steps are not in this "
            f"indexed sprite's palette and were drawn as their nearest entry instead: "
            f"{shown}{rest}. Each step still landed on a different colour, so the "
            "shading holds its shape; the colours are not the ones declared."
        )

    if resolved == 1 and declared > 1:
        out.append(
            f"Every one of the {declared} ramp steps resolves to the same palette "
            f"entry ({steps[0].get('index')}, {steps[0].get('got')}), so there is no "
            "ramp on this sprite to shade along and nothing this tool writes can vary. "
            "The palette needs the ramp's colours before any shading will show."
        )
    elif declared and resolved / declared < RAMP_MOSTLY_PRESENT:
        out.append(
            f"Only {resolved / declared:.0%} of the ramp survives as distinct colours "
            "here, so the result will band wherever the merged steps meet. "
            "extract_palette on the art and generate_ramp against it is the usual way "
            "to get a ramp this palette can hold."
        )
    return out


# --------------------------------------------------------------------------- #
# A resolved shift table against the palette that has to hold its targets     #
# --------------------------------------------------------------------------- #
def shift_table_readings(state: dict, collisions: list[dict]) -> list[str]:
    """What is worth saying about a smear's trail colours on an indexed palette.

    A sibling of `ramp_readings` rather than a reuse of it, because the thing that merges
    is not the same thing. `smear_frame` resolves its ramp in Python into a
    colour-to-colour table before Aseprite is launched, so by the time the palette is
    involved there are no ramp steps left to report: there are trail copies, each one
    shift deeper, and the question is which of *those* come out the same colour (#173).
    Every sentence `ramp_readings` writes names "declared ramp steps", and reusing it
    here would answer a question `smear_frame` does not ask: a ramp step the palette
    cannot hold costs nothing if no plot shifts that far.

    `state` is the prelude's `ramp_palette_state`, called with the table's distinct
    target colours instead of with a declared ramp, so `declared` is how many colours the
    trail asked the palette for and `resolved` is how many entries they landed on.
    `collisions` is `inbetween.shift_table_collisions`: the shift levels that share an
    entry, grouped by the subject colour they came from.

    Measured on a 64x40 indexed sprite whose palette held ramp steps 0, 2 and 4 of a
    five-colour ramp, a disc drawn in step 4, `mode="echo"` with `steps=3`: the plots came
    back at shifts 4, 3 and 1, shift 3 asked for #6b2d4a and shift 4 for #2c1b2e, and both
    resolved to entry 1. Frame 3 came out with 88 pixels of #2c1b2e, 44 of #b04a5a and
    none at all of #6b2d4a, while `warnings` was empty and `ramp_headroom` was correctly
    silent (the subject had four steps below it and the deepest shift was four).
    """
    if state.get("undrawable_palette"):
        # Cannot be reached from `smear_frame` today: it refuses an indexed sprite with no
        # ramp, and `nearest_index` would have raised during the write long before this
        # ran. Answered rather than asked anyway, because the measurement can report it
        # and a reading costs less than finding out which of those two guards moved.
        return [
            "This sprite's palette has no entry that can draw a visible pixel, so none of "
            "the trail's colours could be resolved. add_palette_color or set_palette "
            "first."
        ]

    declared = state.get("declared") or 0
    resolved = state.get("resolved") or 0
    if not declared or not collisions:
        return []

    named = "; ".join(
        "shifts {} ({}) all draw as palette entry {}".format(
            " and ".join(str(shift) for shift in group["shifts"]),
            ", ".join(group["wants"]),
            group["index"],
        )
        for group in collisions[:4]
    )
    rest = f", and {len(collisions) - 4} more" if len(collisions) > 4 else ""
    merged = [str(shift) for shift in
              sorted({shift for group in collisions for shift in group["shifts"]})]
    # "3 and 4", not "3, 4": the sentence names copies an animator has to go and look at,
    # and a two-item comma list reads as a truncated one.
    listed = " and ".join(merged) if len(merged) < 3 else (
        ", ".join(merged[:-1]) + " and " + merged[-1]
    )
    return [
        f"This sprite is indexed and its palette holds {resolved} of the {declared} "
        f"colours this trail asks for as distinct entries: {named}{rest}. The copies at "
        f"shifts {listed} therefore come out the "
        "same colour wherever that subject colour appears, so the trail bands there "
        "rather than stepping. This is not the headroom warning: the ramp does reach far "
        "enough, the palette does not hold what it reaches. Add the missing colours with "
        "add_palette_color or set_palette, pass a ramp the palette already holds, or ask "
        "for fewer steps."
    ]


# --------------------------------------------------------------------------- #
# Palette cycling, and the indices worth cycling                              #
# --------------------------------------------------------------------------- #
# Aseprite's file format carries a palette per frame, but its Lua API does not expose
# one, which is the question issue #128 opened with. Measured against the installed
# editor, `app.version == "1.3.18.6"`:
#
#   * `#spr.palettes` is 1 on a fresh indexed sprite.
#   * `Palette(4).frame` is nil, and assigning it raises
#     "attempt to index a nil value (field '__setters')".
#   * `spr.palettes[2] = Palette(4)`, `table.insert(spr.palettes, ...)` and
#     `spr.palettes.length = 2` all raise that same `__setters` error, so the collection
#     is read-only.
#   * `Sprite:newPalette` and `Sprite:deletePalette` do not exist ("Field newPalette does
#     not exist").
#   * `Palette{ frame = 2 }` is not an error and not a Palette either: it returns a plain
#     Lua table, which `setPalette` then rejects with "PaletteObj expected, got table".
#   * `spr:setPalette(alt)` with `app.frame` set to frame 2 succeeds, replaces palette
#     *1*, leaves `#spr.palettes` at 1, and the reopened file has one palette.
#   * `app.command.LoadPalette{ filename = ... }` on frame 3 behaves the same way.
#
# So the real thing is not reachable and `cycle_palette` ships the fallback the issue
# names: the frames are generated, and what rotates is the pixels' own indices rather
# than the palette. On an indexed sprite those are the same picture. Rotating the palette
# by +step moves the colour at a slot forward; with the palette held still, a pixel shows
# that same colour by moving its index back by step. The remap is exact, with no
# `nearest_index` anywhere in it, and the palette comes out of the call byte for byte as
# the artist wrote it, which rotating it would not.


def usage_runs(used: list[int]) -> list[dict]:
    """The contiguous spans of palette indices the art uses, longest first.

    The one thing a caller needs before they can cycle anything and the one thing there
    was no way to find: a cycle wants a run of entries that read as a ramp, and reading
    every pixel through `get_pixels` to look for one is not a way to find it.

    Runs of a single index are included. A one-entry run cannot be cycled, but leaving it
    out would make the list disagree with `used` for no reason, and `length` says so.
    """
    spans: list[dict] = []
    for index in sorted(set(used)):
        if spans and index == spans[-1]["last"] + 1:
            spans[-1]["last"] = index
            spans[-1]["length"] += 1
        else:
            spans.append({"first": index, "last": index, "length": 1})
    return sorted(spans, key=lambda span: (-span["length"], span["first"]))


# A run shorter than this cannot carry a cycle: two entries swap back and forth, which
# reads as a flicker rather than as flow. Three is the shortest run that travels.
MIN_CYCLE_RUN = 3


def palette_usage_readings(state: dict) -> list[str]:
    """What is worth saying about which palette indices the art actually uses.

    `state` carries `size`, `drawn` (index to pixel count, for the indices that can draw
    a visible pixel) and `out_of_range` (pixels carrying an index at or past the end of
    the palette).
    """
    out: list[str] = []
    size = state.get("size") or 0
    drawn = {int(k): v for k, v in (state.get("drawn") or {}).items() if v}

    if state.get("out_of_range"):
        # Possible because a palette can be resized smaller than the art drawn against
        # it: the pixels keep their old offsets and there is no entry left to read them
        # through. Worth naming because every colour question about those pixels has no
        # answer at all, rather than a near one.
        out.append(
            f"{state['out_of_range']} pixel(s) carry an index at or past the end of this "
            f"{size}-entry palette, so there is no colour to read them through: the "
            "palette was resized smaller than the art drawn against it. resize_palette "
            "back up, or set_palette with enough entries."
        )

    if not drawn:
        out.append(
            "No pixel in scope carries a drawable palette index, so there is nothing here "
            "to cycle or recolour. Draw first, or check the layer and frame this was "
            "scoped to."
        )
        return out

    runs = usage_runs(sorted(drawn))
    longest = runs[0]["length"]
    if longest < MIN_CYCLE_RUN:
        out.append(
            f"The art uses {len(drawn)} palette entries but never {MIN_CYCLE_RUN} in a "
            f"row (the longest run is {longest}), so there is no ramp here for "
            "cycle_palette to rotate: two entries swapping back and forth read as a "
            "flicker rather than as flow. sort_palette will put a ramp's entries next to "
            "each other, and generate_ramp then set_palette builds one that already is."
        )
    return out


def cycle_indices(
    indices: list[int], colors: list[str], transparent_index: int, drawn: dict[int, int]
) -> list[int]:
    """The indices a cycle may rotate, or a refusal naming what is wrong with them.

    Checked against the palette the sprite actually has rather than against a ceiling,
    which is why this runs on a measurement and not on the argument alone: an index of 40
    is fine on a 64-entry palette and means nothing on a 33-entry one, and the difference
    is only knowable with the file open. Nothing has been written when this runs.

    `colors` is the palette as "#rrggbbaa" strings, so the two indices that are in a
    palette and cannot draw are refused from the same place: the sprite's transparent
    index, which means "no pixel here" rather than a colour, and an entry whose own alpha
    is 0. Either one in the cycle makes drawn pixels vanish on one frame and empty space
    fill on the next, which is the #138 failure arriving by a new route.

    `drawn` maps index to pixel count for the pixels in scope. A cycle over indices the
    art never uses writes identical frames, so the sprite grows by `frame_count` frames,
    the GIF does not animate, and every tool reports success; refused here, with the
    indices the art does use, which is the answer the caller needed anyway.
    """
    size = len(colors)
    if len(indices) < 2:
        raise ValidationFailed(
            f"indices has {len(indices)} entry(s); a cycle needs at least 2 to rotate "
            "between. One entry rotated onto itself is the frame you already have."
        )
    out: list[int] = []
    for position, raw in enumerate(indices):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValidationFailed(
                f"indices[{position}] is {raw!r}; a palette index is a whole number."
            ) from None
        if value < 0 or value >= size:
            raise ValidationFailed(
                f"indices[{position}] is {value}, and this sprite's palette has {size} "
                f"entries, numbered 0-{size - 1}. Nothing was written. get_palette lists "
                "them, and list_palette_usage says which ones the art is drawn with."
            )
        if value == transparent_index:
            raise ValidationFailed(
                f"indices[{position}] is {value}, which is this sprite's transparent "
                'index, so it is not a colour: it means "no pixel here". Rotating it '
                "through the cycle would make drawn pixels vanish on one frame and empty "
                "space fill with colour on the next. Leave it out, or point the "
                "transparent index elsewhere with set_transparent_color."
            )
        if str(colors[value]).lower().endswith("00"):
            raise ValidationFailed(
                f"indices[{position}] is {value}, and palette entry {value} is "
                f"{colors[value]}, which is fully transparent and so draws nothing. "
                "Rotating it through the cycle would make drawn pixels vanish on one "
                "frame. Leave it out, or give that entry a colour with "
                "set_palette_color."
            )
        if value in out:
            raise ValidationFailed(
                f"indices[{position}] is {value}, which is already in the cycle. A "
                "repeated index would be rotated to two places at once, so the order the "
                "colours travel in would depend on which came last."
            )
        out.append(value)

    if not any(drawn.get(value) for value in out):
        used = ", ".join(str(index) for index in sorted(drawn)[:12])
        more = f" (and {len(drawn) - 12} more)" if len(drawn) > 12 else ""
        raise ValidationFailed(
            f"none of the indices {out} appear in the art in scope, so every frame of the "
            "cycle would be identical to the one drawn and the animation would not move. "
            f"The indices the art is actually drawn with are: {used}{more}. "
            "list_palette_usage reports the pixel count for each and the contiguous runs "
            "worth cycling."
        )
    return out


def cycle_step(step: int, count: int) -> int:
    """How far the colours travel per frame, checked against the cycle's length.

    A step that is a multiple of the cycle's length lands every colour back where it
    started, so every generated frame would be a copy of the drawn one.
    """
    try:
        value = int(step)
    except (TypeError, ValueError):
        raise ValidationFailed(f"step must be a whole number; got {step!r}.") from None
    if value % count == 0:
        raise ValidationFailed(
            f"step is {value} and the cycle has {count} indices, so every colour would "
            "travel a whole number of laps per frame and land where it started: every "
            f"frame would be identical. Pass a step that is not a multiple of {count}."
        )
    return value


def cycle_remaps(indices: list[int], frame_count: int, step: int) -> list[dict]:
    """The old-index to new-index table for each frame of the cycle, frame 1 first.

    Frame 1 is the drawn frame and its table is empty, so the art it was given comes back
    untouched. Frame `k` rotates by `(k - 1) * step`.

    The direction is the one that makes `step` read as the colours travelling forward
    along `indices`: rotating the palette so slot `j` takes the colour from slot
    `j - step` is the same picture as leaving the palette alone and sending a pixel at
    `indices[j]` to `indices[j - step]`. Written as the index move, because that is what
    is actually done to the file.
    """
    count = len(indices)
    out: list[dict] = []
    for frame in range(frame_count):
        rotation = (frame * step) % count
        out.append({} if not rotation else {
            indices[position]: indices[(position - rotation) % count]
            for position in range(count)
        })
    return out


def cycle_readings(
    indices: list[int], frame_count: int, step: int, drawn: dict[int, int]
) -> list[str]:
    """What is worth saying about a cycle that is about to be written.

    Both of these are about the animation rather than about the file, so neither refuses:
    a cycle that does not close is a perfectly good one to hold under a tag that stops,
    and a cycled index the art does not use is normal in a palette shared between sprites.
    """
    out: list[str] = []
    count = len(indices)
    if (frame_count * step) % count != 0:
        closes = count // math.gcd(abs(step), count)
        out.append(
            f"{frame_count} frames at step {step} over {count} indices does not return "
            "the colours to where they started, so the loop jumps at the wrap. A multiple "
            f"of {closes} frame(s) closes it."
        )
    idle = [index for index in indices if not drawn.get(index)]
    if idle:
        out.append(
            f"palette entr{'y' if len(idle) == 1 else 'ies'} "
            f"{', '.join(str(index) for index in idle)} "
            f"{'is' if len(idle) == 1 else 'are'} in the cycle but not in the art in "
            "scope, so there are no pixels for those colours to travel through and the "
            "motion will read as shorter than the ramp it was given. list_palette_usage "
            "says which entries the art is drawn with."
        )
    return out
