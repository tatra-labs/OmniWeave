"""`ow:manual`: a region a person completes, kept visible as a highlighted placeholder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["placeholder"]


def placeholder(em: Emitter, node: CarrierNode) -> None:
    """One highlighted paragraph of the region's own text, and its reason in a comment on it.

    The unit is `manual_required` whatever this writes (09 section 9), so the placeholder's job is
    to be found: highlighted in the text, and named in Word's comments pane as
    `ow:manual <reason>`. D787: the reason left the paragraph's text for the comment, because R2
    holds a block's text to its element's visible text, and the reason is not visible in the IL.
    """
    paragraph = em.new_paragraph()
    number = em.notes.comment(f"ow:manual {node.attr('data-ow-manual') or ''}")
    paragraph._p.append(_ided("w:commentRangeStart", number))
    with em.marked(highlight=True):
        em.text(node.text_content())
    em.flush()
    paragraph._p.append(_ided("w:commentRangeEnd", number))
    reference = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "CommentReference")
    rpr.append(style)
    reference.append(rpr)
    reference.append(_ided("w:commentReference", number))
    paragraph._p.append(reference)


def _ided(tag: str, number: int) -> Any:
    element = OxmlElement(tag)
    element.set(qn("w:id"), str(number))
    return element
