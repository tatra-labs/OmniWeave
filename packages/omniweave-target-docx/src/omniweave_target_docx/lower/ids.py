"""`ow.el`: a `data-ow-el` address, kept in the artefact as a bookmark (`lower.ids:bookmark`)."""

from __future__ import annotations

from typing import Any, Final

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

__all__ = ["PREFIX", "bookmark"]

PREFIX: Final = "ow_"


def _name(el: str) -> str:
    """`u01/e2` as `ow_u01_e2`: a bookmark name is a letter, then letters, digits and `_`."""
    return PREFIX + el.replace("/", "_")


def bookmark(el: str, number: int) -> tuple[Any, Any]:
    """The `w:bookmarkStart` and `w:bookmarkEnd` pair that keeps `el` in the artefact."""
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(number))
    start.set(qn("w:name"), _name(el))
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(number))
    return start, end
