"""`lower.patterns`: a `url(#id)` paint naming a `<pattern>`, as DrawingML's `a:pattFill`. D798.

owsvg/1's pattern is a DrawingML preset by name (`pptx.defs@1`): `data-ow-preset` names it, and
`data-ow-fg` and `data-ow-bg` give its two colours, black and white when unstated, as
PowerPoint's own pattern fill starts. The pattern's tile, if the IL draws one, is SVG's fallback
for other readers and is not lowered. Both colours take the shape's own alpha (`lower.paint`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_target_pptx.lower._style import colour, element

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["background", "foreground", "pattern", "preset"]

_FOREGROUND: Final = "#000000"
_BACKGROUND: Final = "#FFFFFF"


def pattern(node: CarrierNode, alpha: float, parent: Any) -> None:
    """A `<pattern>` as `a:pattFill` of its preset and its two colours."""
    made = element("a:pattFill", parent, prst=preset(node))
    colour(foreground(node), alpha, element("a:fgClr", made))
    colour(background(node), alpha, element("a:bgClr", made))


def preset(node: CarrierNode) -> str:
    """`data-ow-preset`: the DrawingML preset `pptx.defs@1` holds it to."""
    return node.attr("data-ow-preset") or ""


def foreground(node: CarrierNode) -> str:
    return node.attr("data-ow-fg") or _FOREGROUND


def background(node: CarrierNode) -> str:
    return node.attr("data-ow-bg") or _BACKGROUND
