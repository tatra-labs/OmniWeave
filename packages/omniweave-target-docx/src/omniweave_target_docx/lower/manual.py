"""`ow:manual`: a region a person completes, kept visible as a highlighted placeholder."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["placeholder"]


def placeholder(em: Emitter, node: CarrierNode) -> None:
    """One paragraph: the reason, bold and highlighted, then the region's own text.

    The unit is `manual_required` whatever this writes (09 section 9), so the placeholder's job is
    to be found: a reader skimming the document sees it, and Word's find locates `[manual:`.
    """
    em.new_paragraph()
    with em.marked(bold=True, highlight=True):
        em.text(f"[manual: {node.attr('data-ow-manual') or ''}]")
    with em.marked(highlight=True):
        em.text(" " + node.text_content())
