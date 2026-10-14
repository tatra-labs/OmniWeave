"""`lower.geometry`: a box's offset and extent in user units, attribute or `style`. D795.

`x`, `y`, `width` and `height` are presentation attributes and, for the shapes that carry them,
`style` properties too (`pptx.length@1`), so each is read as `_style.declared` reads a property:
the `style` declaration first. A missing offset is 0 and a missing extent is 0, SVG's initial
values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniweave_target_pptx.lower._style import declared, number

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["extent", "offset"]


def offset(node: CarrierNode, name: str) -> float:
    """`x` or `y`: the box's corner on its axis."""
    return number(declared(node, name), 0.0)


def extent(node: CarrierNode, name: str) -> float:
    """`width` or `height`: the box's size on its axis."""
    return number(declared(node, name), 0.0)
