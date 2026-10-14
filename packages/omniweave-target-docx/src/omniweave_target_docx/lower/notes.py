"""Notes: a reference in the text, and its body in the footnotes or endnotes part.

The gate paired every reference with one body in its unit (`docx.note.resolves@1`), so the walk
skips a body where it stands (its row says `visible = false`) and writes it when its reference is
met. Word numbers notes in the order their references appear, so a note's id is that order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from omniweave_target_docx.lower._stories import REFERENCE_STYLE, TEXT_STYLE, Story, mark

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["endnote", "footnote", "reference"]


def reference(em: Emitter, node: CarrierNode) -> None:
    """`a[data-ow-note]`: the body written first, then the numbered mark where the link stands."""
    note = node.attr("data-ow-note") or ""
    body = em.bodies[note]
    em.flush()
    with em.detached():
        em.handler(body)(em, body)
    kind, number = em.notes.placed[note]
    run = em.run()
    run.style = REFERENCE_STYLE[kind]
    marker = OxmlElement(f"w:{kind}Reference")
    marker.set(qn("w:id"), str(number))
    run._r.append(marker)
    em.at_start, em.pending = False, ""


def footnote(em: Emitter, node: CarrierNode) -> None:
    """`aside[data-ow-footnote]`: a note at the foot of the page its reference lands on."""
    _body(em, node, "footnote", node.attr("data-ow-footnote") or "")


def endnote(em: Emitter, node: CarrierNode) -> None:
    """`aside[data-ow-endnote]`: a note at the end of the document."""
    _body(em, node, "endnote", node.attr("data-ow-endnote") or "")


def _body(em: Emitter, node: CarrierNode, kind: str, note: str) -> None:
    number, element = em.notes.new(kind)
    story = Story(element, em.document.part, em.text_width)
    with em.scope(story, element=element, style=TEXT_STYLE[kind]):
        em.addressed(node, lambda: em.flow(node))
    mark(element, kind)
    em.notes.placed[note] = (kind, number)
