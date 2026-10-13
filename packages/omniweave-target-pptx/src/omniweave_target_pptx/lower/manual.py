"""`lower.manual`: a region a person completes, kept where it stands as a marked placeholder.
D802.

09 section 9: a unit holding an `ow:manual` region is `manual_required` whatever the compile
writes, and a draft carries "placeholders carrying their `ManualReason`". On a slide the region
is a group of its own content as drawn, named by its address, whose `descr` (the alt text
PowerPoint's selection pane shows) is `ow:manual <reason>`. One more shape marks it: a dashed
outline over the region's box, `MARK`, named and described the same way, so a person finds the
work in the slide and in the pane alike. Neither carries text, so R2's visible text is the
region's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pptx.oxml.ns import qn

from omniweave_target_pptx.lower._emit import xfrm
from omniweave_target_pptx.lower._geometry import emu
from omniweave_target_pptx.lower._style import element, solid
from omniweave_target_pptx.lower.group import bounds, framed
from omniweave_target_pptx.lower.shapes import preset

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["placeholder"]

MARK: Final = "#C00000"
"""The outline's colour: PowerPoint's own dark red."""
MARK_WIDTH: Final = 2.0
"""The outline's width, in user units."""


def placeholder(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A manual region as its content, its reason and an outline over it (module docstring)."""
    said = f"ow:manual {node.attr('data-ow-manual') or ''}"

    def draw() -> None:
        em.children(node, chain)
        box = bounds(em.boxes[-1])
        mark_id = em.take_id()
        made = element("p:sp")
        properties = element("p:nvSpPr", made)
        element("p:cNvPr", properties, id=str(mark_id), name=f"ow:manual {mark_id}", descr=said)
        element("p:cNvSpPr", properties)
        element("p:nvPr", properties)
        body = element("p:spPr", made)
        xfrm(box, body)
        preset("rect", 0)(body)
        element("a:noFill", body)
        line = element("a:ln", body, w=str(emu(MARK_WIDTH)))
        solid(MARK, 1.0, line)
        element("a:prstDash", line, val="dash")
        em.add(made, box)

    group = framed(em, node, chain, draw)
    group.find(f"{qn('p:nvGrpSpPr')}/{qn('p:cNvPr')}").set("descr", said)
