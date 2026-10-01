"""What a difference between two frames means: pure, no Aseprite, no MCP.

The counting happens in Lua, where both images are already in memory as integers. This
module decides what the counts say, which is the part worth testing against dicts rather
than against sprites.

Two things here are deliberately unlike the other reports in this server.

**Silence is not the good outcome.** `assess_sprite` says nothing when there is nothing
worth acting on, because a report that comments on every sprite is one nobody reads. A
diff is the opposite: "nothing changed" is the loudest thing it can say. An edit that did
not land looks exactly like an edit that was not needed, and the agent cannot see which.

**A change is never a fault.** Different is not wrong, so there is no verdict unless the
caller says what they expected. `expect` turns a measurement into a checkable claim, the
way `ramp` turns `assess_sprite` into a palette check, and it is omitted rather than
guessed at.
"""

from __future__ import annotations

# Above this share of the drawn art repainted, an edit stops being an edit: it is a
# filter over the whole frame, and the fix is a different tool rather than a smaller
# brush.
FULL_REPAINT = 0.95
# Changed pixels as a share of their own bounding box. A region edit fills its box; dirt
# from a shading pass is scattered across one. The ratio is what tells them apart.
SCATTER_DENSITY = 0.1
# A small box is dense whatever is in it, so scatter is only judged on a box worth
# judging.
SCATTER_MIN_BOX = 64
# Colours the change introduced, as a share of the ones it replaced. Pixel art palettes
# are small, so a handful of genuinely new entries is a change of material rather than a
# change of shade.
COLOR_GROWTH = 0.5

CLASSIFICATIONS = ("identical", "silhouette", "interior", "coverage", "mixed")


def _pixels(n: int) -> str:
    """Say it as 1 pixel or as 7 pixels.

    A report that says "1 pixels" reads as a bug in the report, which is not what you
    want sitting next to the numbers it is asking to be trusted.
    """
    return f"{n} pixel" if n == 1 else f"{n} pixels"


def classify(counts: dict) -> str:
    """One word for what kind of change this is.

    Ordered by what the caller has to do about it. A silhouette that moved is a different
    bug from a repaint, and a repaint is a different bug from an alpha change, so when
    several are true at once the silhouette is the one named: it is the one that breaks
    collision boxes and outlines downstream.
    """
    if counts["changed_pixels"] == 0:
        return "identical"
    silhouette = counts["silhouette_added"] + counts["silhouette_removed"]
    interior, coverage = counts["interior_changed"], counts["coverage_changed"]
    if silhouette:
        return "silhouette"
    if interior and coverage:
        return "mixed"
    return "interior" if interior else "coverage"


def shares(counts: dict) -> dict:
    """The two ratios that make the counts mean something.

    `changed_share` is against the pixels drawn in either frame, not against the canvas:
    a 4-pixel edit to a 4-pixel sprite is a total repaint and a 4-pixel edit to a full
    32x32 is a touch-up, and the canvas cannot tell them apart.

    `change_density` is against the bounding box of the changed pixels themselves, which
    is what separates an edited region from dirt scattered over one.
    """
    union = max(1, counts.get("drawn_union", 0))
    box = counts.get("change_box")
    area = (box["width"] * box["height"]) if box else 0
    return {
        "changed_share": round(counts["changed_pixels"] / union, 3),
        "change_density": round(counts["changed_pixels"] / area, 3) if area else 0.0,
    }


def introduced(counts: dict) -> list[dict]:
    """Colours the change put at the changed pixels that it did not take away.

    Both lists cover the changed pixels only, so this is a claim about the edit rather
    than about the sprite: a colour counted here was not among the ones the edit
    replaced, which is the sense in which it is new. It may well be in use elsewhere in
    the frame, and saying otherwise would need a full pass over both images for a line of
    prose.
    """
    before = {entry["color"] for entry in counts.get("colors_before") or ()}
    return [
        entry for entry in counts.get("colors_after") or ()
        if entry["color"] not in before
    ]


def readings(counts: dict, *, names: dict) -> list[str]:
    """What the numbers say, in sentences, each naming the tool that answers for it."""
    out: list[str] = []
    ratio = shares(counts)
    before = names.get("before", "the first frame")
    after = names.get("after", "the second frame")

    if counts["changed_pixels"] == 0:
        out.append(
            f"Nothing changed: {after} is pixel for pixel {before}. If an edit was "
            "meant to land here, it did not. The usual causes, in the order they are "
            "worth checking: the edit went to a different layer (every drawing tool "
            "writes to one layer, and both this and get_pixels take layer= so you can "
            "look at the same one); a selection was still scoping it, so the pixels "
            "outside it were masked out (get_selection, then deselect); or the "
            "coordinates were off the canvas, which clips silently."
        )
        return out

    added, removed = counts["silhouette_added"], counts["silhouette_removed"]
    if added or removed:
        out.append(
            f"The silhouette changed: {_pixels(added)} entered it and {removed} left "
            "it. "
            "That is the shape itself, so everything measured against it moves too, "
            "including collision boxes, outlines and the trimmed export box. The "
            "shading tools are built to leave a silhouette alone, so if this came from "
            "one of them it is the bug rather than the result."
        )

    interior = counts["interior_changed"]
    if interior:
        share = interior / max(1, counts.get("drawn_union", 0))
        if share >= FULL_REPAINT:
            out.append(
                f"Every drawn pixel was repainted ({interior} of them), which reads as a "
                "filter over the whole frame rather than an edit. assess_sprite with a "
                "ramp= says how much of the art is still on the palette; "
                "shift_along_ramp and gradient_map are the passes that keep it there."
            )
        else:
            out.append(
                f"{_pixels(interior)} {'was' if interior == 1 else 'were'} repainted "
                f"inside the silhouette, {share:.0%} of the drawn art."
            )

    coverage = counts["coverage_changed"]
    if coverage and not interior:
        out.append(
            f"{_pixels(coverage)} changed alpha only, keeping the same colour, which "
            "is coverage rather than a repaint: a cel or layer opacity change, or an "
            "anti-aliasing pass. In indexed colour it can also mean pixels moved on or "
            "off the transparent index while the palette entry stayed put."
        )

    box = counts.get("change_box")
    if box and box["width"] * box["height"] >= SCATTER_MIN_BOX \
            and ratio["change_density"] < SCATTER_DENSITY:
        out.append(
            f"The changed pixels are scattered across a {box['width']}x{box['height']} "
            f"box that is only {ratio['change_density']:.0%} changed, which reads as "
            "stray pixels left by a pass rather than as an edited region. "
            "remove_stray_pixels is what answers for noise, and assess_sprite counts it."
        )

    new = introduced(counts)
    replaced = len(counts.get("colors_before") or ())
    if new and len(new) > max(2, COLOR_GROWTH * replaced):
        listed = ", ".join(entry["color"] for entry in new[:3])
        out.append(
            f"The change introduced {len(new)} colours that were not among the "
            f"{replaced} it replaced ({listed} and so on), which is more than a change "
            "of shade. assess_sprite with a ramp= says how much of the result is off it."
        )
    return out


def verdict(counts: dict, expect: str) -> dict:
    """A pass or fail, but only against an expectation the caller stated.

    Same shape as every other check in this server, so `passed` is false only when an
    error-level check failed, and the detail describes the failure rather than the pass.
    """
    if expect not in CLASSIFICATIONS:
        raise ValueError(
            f"expect must be one of {', '.join(CLASSIFICATIONS)}; got {expect!r}"
        )
    found = classify(counts)
    ok = found == expect
    detail = "" if ok else (
        f"expected a {expect} change and measured a {found} one: "
        f"{counts['silhouette_added']} pixels entered the silhouette, "
        f"{counts['silhouette_removed']} left it, {counts['interior_changed']} were "
        f"repainted inside it, and {counts['coverage_changed']} changed only their alpha"
    )
    return {
        "passed": ok,
        "checks": [{"name": "expected_change", "ok": ok, "level": "error",
                    "detail": detail}],
        "errors": [] if ok else [detail],
        "warnings": [],
    }
