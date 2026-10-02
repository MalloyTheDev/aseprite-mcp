"""Deriving a palette from artwork: the judgement about whether the result can draw it.

`app.command.ColorQuantization` builds a palette out of the colours a sprite is painted
with, which is the missing step in an "import a picture, make it pixel art" pipeline:
`set_color_mode` can map art onto a palette but cannot decide what the palette should be,
and `extract_palette` lists the colours already used but cannot reduce them to a budget.

What lives here is the reading of the result, because the result can be a palette that
cannot draw the art while every call involved reports success. Measured on 1.3.18.6:

  * `max_colors` is a ceiling and nothing more. On a 256-colour gradient the derived
    palette came back at exactly the requested size for 2, 3, 4, 5, 12, 16 and 32.
  * On art with few colours the reduction can stop far short of that ceiling. Four
    distinct opaque colours (red, green, blue, yellow) with `max_colors=4` came back as
    two entries: one transparent, and one mid-grey `#7f7f40` that is the average of all
    four. Asking for 5 on the same art returned all four colours exactly. So the one
    number a caller controls has a cliff in it, one entry is spent on transparency, and
    nothing in the palette itself says the art has been reduced to a single tone.

The arithmetic is here, in Python, so it is unit-tested without an editor; the counting
happens in Lua, where the pixels are.
"""

from __future__ import annotations

from .limits import MAX_COLOR_LIST_LENGTH, check_count

# Two is the smallest request worth making. ColorQuantization reserves an entry for
# transparency, so a one-entry palette is the transparent entry alone and can draw
# nothing at all; `max_colors=0` was accepted by the command and produced a palette of
# three, which is not a reading of the argument anyone could predict.
MIN_QUANTIZE_COLORS = 2

# Distinct colours the art scan tracks before it stops counting. Four times a palette's
# own ceiling: past that the answer to "will this palette hold the art" is already "no",
# and the count is a photo histogram rather than a finding. The scan says when it stopped,
# so the number it reports is a floor and the readings below say "at least".
MAX_SCANNED_COLORS = 1_024


def check_max_colors(value) -> int:
    """Validate `max_colors` and return it as an int, or raise ``ValidationFailed``."""
    return check_count(
        "max_colors",
        value,
        MAX_COLOR_LIST_LENGTH,
        minimum=MIN_QUANTIZE_COLORS,
        remedy=f"A palette holds at most {MAX_COLOR_LIST_LENGTH} colours.",
    )


def quantization_readings(state: dict) -> list[str]:
    """What is worth saying about a palette that was just derived from the art.

    `state` is the measurement the Lua side takes: `requested` (the `max_colors` asked
    for), `size` and `drawable` (how many entries can produce a visible pixel),
    `art_colors` (distinct opaque colours found in the art), `art_colors_exact` (how
    many of those the derived palette holds exactly), `art_colors_capped` (the scan
    stopped counting distinct colours, so `art_colors` is a floor) and `art_scanned`
    (whether the art was measured at all).

    Nothing is said when the palette holds every colour the art uses, which is the
    normal outcome and the one a caller does not need a paragraph about.
    """
    size = state.get("size") or 0
    drawable = state.get("drawable")
    requested = state.get("requested") or 0
    art_colors = state.get("art_colors") or 0
    exact = state.get("art_colors_exact") or 0
    capped = bool(state.get("art_colors_capped"))

    if not state.get("art_scanned", True):
        # The art was too large to measure, so every reading below that compares the
        # palette against the art is unavailable. Saying so beats saying nothing, and
        # beats the readings a zero colour count would otherwise produce: without this
        # branch an unscanned sprite reads as a blank one.
        unmeasured = [
            "This sprite was too large to scan, so the derived palette has not been "
            "compared against the colours in the art: the readings that would say "
            "whether it can hold them are missing, not clear. extract_palette on one "
            "frame answers the same question by hand."
        ]
        if drawable is not None and drawable <= 1:
            unmeasured.append(
                f"The derived palette has {drawable} entry that can draw a visible "
                "pixel, which is almost certainly too few: raise max_colors."
            )
        return unmeasured

    if art_colors == 0:
        return [
            "Nothing is drawn in this sprite, so there were no colours to derive a "
            "palette from. The palette you have is whatever the file already carried."
        ]

    out: list[str] = []

    if drawable == 0:
        out.append(
            f"None of the {size} derived entries can draw a visible pixel, so this "
            "palette cannot hold the art at all. Raise max_colors."
        )
    elif drawable == 1 and art_colors > 1:
        out.append(
            f"The derived palette has one drawable entry for art painted in "
            f"{'at least ' if capped else ''}{art_colors} colours, so converting to "
            "indexed against it would flatten the whole sprite to a single tone. The "
            "reduction merges whole levels at a time, so a max_colors equal to the "
            f"number of colours in the art is exactly where it collapses: try "
            f"max_colors={min(art_colors + 1, MAX_COLOR_LIST_LENGTH)} or more."
        )
    elif size < requested and art_colors + 1 > size:
        # Short of the ceiling while the art still had colours left to cover: the
        # reduction stopped early rather than the art running out of colours. Worth one
        # line, because the obvious reading of a small palette is that the art was
        # simple, and here it is not.
        out.append(
            f"You asked for up to {requested} colours and the palette came back with "
            f"{size}, for art painted in {'at least ' if capped else ''}{art_colors} "
            "colours. The reduction merges whole levels at a time and can stop well "
            "short of the ceiling; a slightly larger max_colors often returns more, "
            "not fewer, of the original colours."
        )

    if exact < art_colors:
        shortfall = art_colors - exact
        out.append(
            f"{shortfall} of the {'at least ' if capped else ''}{art_colors} colours in "
            "the art are not in the derived palette and will be approximated by their "
            "nearest entry when the sprite is converted to indexed. That is what "
            "reducing a palette means; extract_palette lists the colours the art "
            "actually uses if you need to keep particular ones."
        )

    return out
