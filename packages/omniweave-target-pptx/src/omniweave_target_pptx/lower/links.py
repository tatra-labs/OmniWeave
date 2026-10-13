"""`lower.links`: an `<a>` as a click on every shape it holds. D801.

`pptx.reference@1` holds a link to `#u<NN>`, a unit of the deck, or an `https:` page. An `<a>` is
a container, as SVG's is: its children are lowered where it stands, and each shape, text box,
picture and group made inside it carries an `a:hlinkClick` on its `p:cNvPr` (`Emitter.click`). A
page is an external hyperlink relationship of the slide. A unit is a relationship to that unit's
slide with PowerPoint's slide-jump action, `JUMP`, so `lower._pack` makes every slide before it
lowers any, and a unit the deck does not hold is refused (`OW_TARGET_REFERENCE_UNRESOLVED`). A
link inside a link is the inner one's, as the innermost anchor is SVG's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_target_pptx.lower.defs import reference

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["hyperlink"]

JUMP: Final = "ppaction://hlinksldjump"
"""PowerPoint's action for a click that jumps to the slide its relationship names."""


def hyperlink(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """An `<a>`'s children, each with a click to its `href`."""
    outer = em.linked
    em.linked = reference(node)
    try:
        em.children(node, chain)
    finally:
        em.linked = outer
