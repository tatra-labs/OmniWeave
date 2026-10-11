"""The numbering part: two nine-level list definitions, and one `w:num` a list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from omniweave_target_docx.lower.lists import STEP, start_at

if TYPE_CHECKING:
    from docx.document import Document

__all__ = ["LEVELS", "Numbering"]

LEVELS: Final = 9
"""`w:ilvl` 0-8: WordprocessingML's levels, and the list rule's limit."""
_BULLETS: Final = ("•", "◦", "▪")
_HANGING: Final = 360
_NSID: Final = {False: "0F0B0001", True: "0F0B0002"}
"""Fixed, so the part's bytes depend on the IL alone."""


class Numbering:
    """Adds owflow/1's two abstract lists to the document's numbering part on first use."""

    def __init__(self, document: Document) -> None:
        self._part = document.part.numbering_part.element
        self._abstract: dict[bool, int] = {}

    def new(self, *, ordered: bool, ilvl: int, start: int) -> int:
        """A new list's `numId`, restarting a numbered list's level at `start`."""
        abstract = self._abstract.get(ordered)
        if abstract is None:
            abstract = self._abstract[ordered] = self._define(ordered=ordered)
        num = self._part.add_num(abstract)
        if ordered:
            start_at(num, ilvl, start)
        return int(num.numId)

    def _define(self, *, ordered: bool) -> int:
        ids = [
            int(a.get(qn("w:abstractNumId"))) for a in self._part.iterchildren(qn("w:abstractNum"))
        ]
        number = max(ids, default=-1) + 1
        element = OxmlElement("w:abstractNum")
        element.set(qn("w:abstractNumId"), str(number))
        _child(element, "w:nsid", _NSID[ordered])
        _child(element, "w:multiLevelType", "multilevel")
        for ilvl in range(LEVELS):
            element.append(_level(ilvl, ordered=ordered))
        first_num = self._part.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(element)
        else:
            self._part.append(element)
        return number


def _level(ilvl: int, *, ordered: bool) -> Any:
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), str(ilvl))
    _child(level, "w:start", "1")
    _child(level, "w:numFmt", "decimal" if ordered else "bullet")
    _child(level, "w:lvlText", f"%{ilvl + 1}." if ordered else _BULLETS[ilvl % len(_BULLETS)])
    _child(level, "w:lvlJc", "left")
    ppr = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    indent.set(qn("w:left"), str(STEP * (ilvl + 1)))
    indent.set(qn("w:hanging"), str(_HANGING))
    ppr.append(indent)
    level.append(ppr)
    return level


def _child(parent: Any, tag: str, value: str) -> None:
    element = OxmlElement(tag)
    element.set(qn("w:val"), value)
    parent.append(element)
