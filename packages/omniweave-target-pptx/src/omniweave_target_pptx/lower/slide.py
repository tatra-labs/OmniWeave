"""`lower.slide`: one `<svg>` is one slide, and its `viewBox` is the deck's size. D795.

PowerPoint has one slide size a presentation, so every unit's `viewBox` must be the same
(`_pack`'s preflight), and the size is that box at 9525 EMU a user unit.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["size", "slide"]

_VIEWBOX: Final = re.compile(r"0 0 ([1-9][0-9]*) ([1-9][0-9]*)")


def slide(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """The slide root: its children, in document order."""
    em.children(node, chain)


def size(node: CarrierNode) -> tuple[int, int] | None:
    """The `viewBox`'s width and height in user units, or `None` for one the canvas rule
    refuses."""
    m = _VIEWBOX.fullmatch(node.attr("viewBox") or "")
    return None if m is None else (int(m[1]), int(m[2]))
