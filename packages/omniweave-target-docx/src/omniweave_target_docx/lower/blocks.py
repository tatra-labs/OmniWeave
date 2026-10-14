"""Blocks: headings, paragraphs, quotations, code, the thematic break, alignment and direction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

if TYPE_CHECKING:
    from docx.text.paragraph import Paragraph
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["alignment", "bidi", "code_block", "heading", "paragraph", "quote", "rule"]

_ALIGN: Final = {
    "start": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "end": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
"""`text-align` to `w:jc`. Transitional WordprocessingML reads `left` as a bidi paragraph's
leading edge, so `start` is `left` and `end` is `right` in either direction."""
_AFTER_BIDI: Final = (
    "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
    "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
    "w:pPrChange",
)  # fmt: skip
"""CT_PPr's sequence after `w:bidi`."""
_AFTER_PBDR: Final = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
                      "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
                      "w:bidi", *_AFTER_BIDI)  # fmt: skip
"""CT_PPr's sequence after `w:pBdr`."""


def heading(em: Emitter, node: CarrierNode) -> None:
    """`h1`..`h6` as Word's `Heading 1`..`Heading 6`, which its navigation pane reads."""
    em.new_paragraph(f"Heading {node.tag.removeprefix('html|h')}")
    em.inline_children(node)


def paragraph(em: Emitter, node: CarrierNode) -> None:
    em.new_paragraph()
    em.inline_children(node)


def quote(em: Emitter, node: CarrierNode) -> None:
    """Every paragraph inside takes Word's `Quote` style, unless it names its own."""
    with em.scope(style="Quote"):
        em.flow(node)


def code_block(em: Emitter, node: CarrierNode) -> None:
    """`pre`: one `Code Block` paragraph, every space kept and each newline a line break."""
    em.new_paragraph("Code Block")
    em.preserve = True
    try:
        em.inline_children(node)
    finally:
        em.end_paragraph()
        em.preserve = False


def rule(em: Emitter, node: CarrierNode) -> None:
    """`hr`: an empty paragraph with a bottom border, Word's own spelling of a thematic break."""
    del node
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for name, value in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "auto")):
        bottom.set(qn(f"w:{name}"), value)
    border.append(bottom)
    ppr = em.new_paragraph()._p.get_or_add_pPr()
    ppr.insert_element_before(border, *_AFTER_PBDR)


def alignment(paragraph: Paragraph, value: str) -> None:
    """`style="text-align: ..."`, inherited by the paragraphs an element makes."""
    paragraph.alignment = _ALIGN[value]


def bidi(paragraph: Paragraph) -> None:
    """`dir="rtl"`: a right-to-left paragraph. Its runs carry `w:rtl` (`Marks.rtl`)."""
    ppr = paragraph._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.insert_element_before(OxmlElement("w:bidi"), *_AFTER_BIDI)
