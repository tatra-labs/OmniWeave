"""`lower.group`: a `<g>` as a DrawingML group, whose frame is its children's. D795.

A group's transform is folded into each child's matrix (`lower.transform`), so the group itself
maps its children one to one: its box is the box its children take, and its child frame is the
same box. An empty group is a group at the origin with no extent. A group's `opacity` is pushed
down to its children's alpha (`lower.paint.alpha`), because a DrawingML group has none. A group's
filter (D799) is its `p:grpSpPr`'s `a:effectLst`, turned by the matrix its children carry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniweave_target_pptx.lower import effects
from omniweave_target_pptx.lower._emit import xfrm
from omniweave_target_pptx.lower._geometry import Placed, angle
from omniweave_target_pptx.lower._style import element, inherited
from omniweave_target_pptx.lower.ids import shape_name
from omniweave_target_pptx.lower.transform import transform

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["group"]


def group(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<g>` as `p:grpSp`, its children lowered into it."""
    group_id = em.take_id()
    made = element("p:grpSp")
    properties = element("p:nvGrpSpPr", made)
    element("p:cNvPr", properties, id=str(group_id), name=shape_name(node, group_id))
    element("p:cNvGrpSpPr", properties)
    element("p:nvPr", properties)
    frame = element("p:grpSpPr", made)
    with em.group(made) as boxes:
        em.children(node, chain)
    box = _bounds(boxes)
    frame.append(xfrm(box, None, child=box))
    found = effects.apply(node, em.definitions)
    if found is not None:
        m = transform(chain)
        fill = inherited(chain, "fill")
        effects.effect(found, frame, scale=m.scale, turn=angle(m), fill=fill)
    em.add(made, box)


def _bounds(boxes: list[Placed]) -> Placed:
    if not boxes:
        return Placed(0, 0, 0, 0)
    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.x + b.cx for b in boxes)
    bottom = max(b.y + b.cy for b in boxes)
    return Placed(left, top, right - left, bottom - top)
