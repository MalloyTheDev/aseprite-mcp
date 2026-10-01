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
