"""`lower.ids`: a shape's name is its IL address, so a reader can find the element again. D795.

09 section 11.1's R2 holds every addressed element to the one read-back block carrying its
address. DrawingML's `p:cNvPr` has an `id` the slide counts from 2 (02-architecture.md's compile
walkthrough) and a free `name`, so the address is the name. An element with no address is named
by its kind and its id, PowerPoint's own `Rectangle 3` form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["shape_name"]


def shape_name(node: CarrierNode, shape_id: int) -> str:
    """The `p:cNvPr` name: the `data-ow-el` address, else `<kind> <id>`."""
    return node.attr("data-ow-el") or f"{node.tag.partition('|')[2]} {shape_id}"
