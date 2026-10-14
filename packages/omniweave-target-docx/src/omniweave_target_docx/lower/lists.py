"""Lists: bulleted and numbered lists of items, nine levels deep, and definition lists.

Each `<ul>` or `<ol>` is its own `w:num`, so a numbered list restarts where it begins and nests
at the level its depth names (`w:ilvl` 0-8, the rule's limit). An item's first paragraph carries
the number and the paragraphs after it in the item are indented to its text. A definition list has
no WordprocessingML construct (its rows are `lossy`): a term is a bold paragraph kept with the
description, and a description an indented paragraph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Twips

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["bulleted", "definitions", "description", "item", "numbered", "start_at", "term"]

STEP: Final = 720
"""Twips a level indents: half an inch, Word's own list step."""
_ITEM_STYLE: Final = "List Paragraph"


def bulleted(em: Emitter, node: CarrierNode) -> None:
    _list(em, node, ordered=False)


def numbered(em: Emitter, node: CarrierNode) -> None:
    _list(em, node, ordered=True)


def _list(em: Emitter, node: CarrierNode, *, ordered: bool) -> None:
    raw = node.attr("start") or ""
    first = int(raw) if ordered and raw.isdecimal() else 1
    em.lists.append(em.numbering.new(ordered=ordered, ilvl=len(em.lists), start=first))
    try:
        for child in node.children():
            em.block(child)
    finally:
        em.lists.pop()


def item(em: Emitter, node: CarrierNode) -> None:
    """The first paragraph made inside is numbered; an empty item is one numbered paragraph."""
    ilvl = len(em.lists) - 1
    with em.scope(
        style=_ITEM_STYLE, indent=Twips(STEP * (ilvl + 1)), number=(em.lists[-1], ilvl)
    ) as scope:
        em.flow(node)
        if scope.number is not None:
            em.new_paragraph()


def start_at(num: Any, ilvl: int, start: int) -> None:
    """`<ol start>`: a `w:lvlOverride` restarting the list's own level at `start`."""
    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), str(ilvl))
    value = OxmlElement("w:startOverride")
    value.set(qn("w:val"), str(start))
    override.append(value)
    num.append(override)


def definitions(em: Emitter, node: CarrierNode) -> None:
    em.flow(node)


def term(em: Emitter, node: CarrierNode) -> None:
    em.new_paragraph().paragraph_format.keep_with_next = True
    with em.marked(bold=True):
        em.inline_children(node)


def description(em: Emitter, node: CarrierNode) -> None:
    with em.scope(indent=Twips(STEP)):
        em.flow(node)
