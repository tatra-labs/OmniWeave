"""Inline marks: emphasis, code, scripts, highlight, links, line breaks and language."""

from __future__ import annotations

from typing import TYPE_CHECKING

from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from omniweave_target_docx.lower.ids import PREFIX

if TYPE_CHECKING:
    from docx.text.run import Run
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = [
    "bold",
    "code",
    "highlight",
    "hyperlink",
    "italic",
    "language",
    "language_run",
    "line_break",
    "strike",
    "subscript",
    "superscript",
    "underline",
]


def bold(em: Emitter, node: CarrierNode) -> None:
    with em.marked(bold=True):
        em.inline_children(node)


def italic(em: Emitter, node: CarrierNode) -> None:
    with em.marked(italic=True):
        em.inline_children(node)


def underline(em: Emitter, node: CarrierNode) -> None:
    with em.marked(underline=True):
        em.inline_children(node)


def strike(em: Emitter, node: CarrierNode) -> None:
    with em.marked(strike=True):
        em.inline_children(node)


def code(em: Emitter, node: CarrierNode) -> None:
    with em.marked(code=True):
        em.inline_children(node)


def subscript(em: Emitter, node: CarrierNode) -> None:
    with em.marked(subscript=True, superscript=False):
        em.inline_children(node)


def superscript(em: Emitter, node: CarrierNode) -> None:
    with em.marked(superscript=True, subscript=False):
        em.inline_children(node)


def highlight(em: Emitter, node: CarrierNode) -> None:
    with em.marked(highlight=True):
        em.inline_children(node)


def line_break(em: Emitter, node: CarrierNode) -> None:
    del node
    em.line_break()


def language_run(em: Emitter, node: CarrierNode) -> None:
    """`span[lang]`: the language is the walk's to pass down (`Emitter.inherited`)."""
    em.inline_children(node)


def hyperlink(em: Emitter, node: CarrierNode) -> None:
    """`a[href]`: an external relationship, or an anchor naming a `data-ow-el` bookmark.

    A link inside a link has nowhere to go in WordprocessingML, so its text joins the outer one.
    """
    if em.run_parent is not None:
        em.inline_children(node)
        return
    href = node.attr("href") or ""
    if em.pending:  # the space before a link is the sentence's, not the link's underlined text
        em.buffered(em.pending)
        em.pending = ""
    em.flush()
    link = OxmlElement("w:hyperlink")
    if href.startswith("#"):
        link.set(qn("w:anchor"), PREFIX + href[1:].replace("/", "_"))
    else:
        part = em.document.part
        link.set(qn("r:id"), part.relate_to(href, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
    em.parent().append(link)
    em.run_parent = link
    try:
        em.inline_children(node)
        em.flush()
    finally:
        em.run_parent = None


def language(run: Run, tag: str) -> None:
    """`lang`: `w:lang` on each run inside, the last of the properties `Marks` writes."""
    element = OxmlElement("w:lang")
    element.set(qn("w:val"), tag)
    run._r.get_or_add_rPr().append(element)
