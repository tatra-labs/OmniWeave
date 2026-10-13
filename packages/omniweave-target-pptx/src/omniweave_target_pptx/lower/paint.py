"""`lower.paint`: a shape's fill and line paint, and the alpha down its chain. D795.

SVG's initial `fill` is black and its initial `stroke` is none. `fill-opacity` and
`stroke-opacity` inherit, and `opacity` multiplies down the chain (`_style`). Each opacity is
clamped to 0 to 1 before it composes, as SVG clamps every opacity property, so a product is
always a level `a:alpha` can hold. A `url(#id)` paint
names a gradient or a pattern, which are later families: a unit using one is refused by preflight
check 1 before this runs.
"""

from __future__ import annotations

import math
from typing import Any, Final

from omniweave_core.errors import TargetError

from omniweave_target_pptx.lower._style import Chain, declared, element, inherited, number, solid

__all__ = ["alpha", "fill", "fill_alpha", "line", "line_alpha"]

_BLACK: Final = "#000000"
_NONE: Final = "none"


def alpha(chain: Chain) -> float:
    """`opacity`: each node's own, multiplied down the chain."""
    return math.prod(_level(declared(node, "opacity")) for node in chain)


def fill_alpha(chain: Chain) -> float:
    """`fill-opacity`, inherited, times the chain's `opacity`."""
    return _level(inherited(chain, "fill-opacity")) * alpha(chain)


def line_alpha(chain: Chain) -> float:
    """`stroke-opacity`, inherited, times the chain's `opacity`."""
    return _level(inherited(chain, "stroke-opacity")) * alpha(chain)


def fill(chain: Chain, parent: Any) -> None:
    """The shape's fill: `a:noFill`, or `a:solidFill` of its colour at its alpha."""
    _paint(inherited(chain, "fill") or _BLACK, fill_alpha(chain), parent)


def line(chain: Chain, parent: Any) -> bool:
    """The line's paint under `parent`, an `a:ln`; `False` when the stroke is none."""
    stated = inherited(chain, "stroke") or _NONE
    _paint(stated, line_alpha(chain), parent)
    return stated != _NONE


def _level(text: str | None) -> float:
    """One opacity, 1 when unstated, clamped to 0 to 1."""
    return max(0.0, min(1.0, number(text, 1.0)))


def _paint(stated: str, level: float, parent: Any) -> None:
    if stated == _NONE:
        element("a:noFill", parent)
    elif stated.startswith("url("):
        raise TargetError(
            f"paint {stated} names a gradient or a pattern, which this lowering does not draw",
            symbol="OW_TARGET_CONSTRUCT_UNMAPPED",
            fix="ow out constructs pptx --group def",
        )
    else:
        solid(stated, level, parent)
