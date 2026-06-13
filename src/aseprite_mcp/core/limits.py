"""Hard size limits on user-supplied collections — a DoS guard at the validation boundary.

These are conservative ceilings, not tuning knobs: they bound the worst-case memory and
time of a single tool call while staying well above any legitimate pixel-art workload.
There is intentionally **no environment/config override** yet — raise the relevant constant
(and document it) only if real demand appears. Exceeding a limit raises ``ValidationFailed``
with the field name, the received count, the cap, and how to recover.
"""

from __future__ import annotations

from collections.abc import Sized

from .errors import ValidationFailed

# Maximum number of operations in a single apply_operations batch.
MAX_BATCH_OPERATIONS = 500
# Maximum length of an explicit pixel/point coordinate list in one call
# (65,536 == a full 256x256 sprite's worth of pixels).
MAX_PIXEL_LIST_LENGTH = 65_536
# Maximum number of tile placements in one set_tiles call.
MAX_TILE_LIST_LENGTH = 65_536
# Maximum number of palette colours in one set_palette call (indexed-palette ceiling).
MAX_COLOR_LIST_LENGTH = 256


def check_list_length(
    field: str,
    items: Sized,
    maximum: int,
    *,
    remedy: str = "Split the request into smaller calls.",
) -> None:
    """Raise ``ValidationFailed`` if ``items`` is longer than ``maximum``.

    The message names the field, the received count, the cap, and how to recover, e.g.
    ``operations has 731 items; maximum is 500. Split the edit into multiple batches.``
    """
    count = len(items)
    if count > maximum:
        raise ValidationFailed(
            f"{field} has {count} items; maximum is {maximum}. {remedy}"
        )
