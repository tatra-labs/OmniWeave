"""`lower.group`: a `<g>` as a DrawingML group, whose frame is its children's. D795.

A group's transform is folded into each child's matrix (`lower.transform`), so the group itself
maps its children one to one: its box is the box its children take, and its child frame is the
same box. An empty group is a group at the origin with no extent. A group's `opacity` is pushed
down to its children's alpha (`lower.paint.alpha`), because a DrawingML group has none. A group's
filter (D799) is its `p:grpSpPr`'s `a:effectLst`, turned by the matrix its children carry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from omniweave_target_pptx.lower import effects
from omniweave_target_pptx.lower._emit import xfrm
from omniweave_target_pptx.lower._geometry import Placed, angle
from omniweave_target_pptx.lower._style import element, inherited
from omniweave_target_pptx.lower.transform import transform

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["group"]


def group(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<g>` as `p:grpSp`, its children lowered into it."""
    framed(em, node, chain, lambda: em.children(node, chain))


def framed(em: Emitter, node: CarrierNode, chain: Chain, draw: Callable[[], None]) -> Any:
    """A `p:grpSp` named by `node`, holding what `draw` lowers: a `<g>`'s children, or the
    clone a `<use>` draws (D801). The group is returned, for a manual region to describe."""
    group_id = em.take_id()
    made = element("p:grpSp")
    properties = element("p:nvGrpSpPr", made)
    em.click(element("p:cNvPr", properties, id=str(group_id), name=em.name(node, group_id)))
    element("p:cNvGrpSpPr", properties)
    element("p:nvPr", properties)
    frame = element("p:grpSpPr", made)
    with em.group(made) as boxes:
        draw()
    box = bounds(boxes)
    frame.append(xfrm(box, None, child=box))
    found = effects.apply(node, em.definitions)
    if found is not None:
        m = transform(chain)
        fill = inherited(chain, "fill")
        effects.effect(found, frame, scale=m.scale, turn=angle(m), fill=fill)
    em.add(made, box)
    return made


def bounds(boxes: list[Placed]) -> Placed:
    """The box `boxes` take together; an empty list is a box at the origin with no extent."""
    if not boxes:
        return Placed(0, 0, 0, 0)
    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.x + b.cx for b in boxes)
    bottom = max(b.y + b.cy for b in boxes)
    return Placed(left, top, right - left, bottom - top)
