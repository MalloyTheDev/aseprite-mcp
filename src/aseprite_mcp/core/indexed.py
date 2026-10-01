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
