"""The WordprocessingML walk: a `.docx` this target built, read back as a tree of blocks.

`lower/` wrote a body of paragraphs and tables between section breaks, a numbering part, two
notes parts and a provenance part, and this module reads them in that order and nothing else.
What it reads is what `lower/` writes: a paragraph's style names its construct, a `w:numPr` its
list and level, a bookmark `ow_u01_e3` an address, a `w:footnoteReference` a note.

## Rulings

1. **A unit is a section.** Every paragraph whose `w:pPr` holds a `w:sectPr` closes one, and the
   body's own `w:sectPr` closes the last. The break paragraph is no block.
2. **Containers are rebuilt from their spelling.** Consecutive `Quote` paragraphs are one
   `blockquote`. A `List Paragraph` with a `w:numPr` is a `list_item` in the list its `w:numId`
   names, nested by `w:ilvl`, and one without is a further paragraph of the item before it. A
   `Caption` paragraph before a table is the table's caption, and one after a picture makes a
   `figure` of the two. A table closes any open list or quotation.
3. **A block's text is the artefact's.** A paragraph's is its runs' text, `w:br` a newline and
   `w:tab` a tab, with a note's reference contributing nothing. A container's is its children's,
   one line each, as the carrier's visible text joins block boundaries. A note body's first
   paragraph drops the number and the one space `lower/` put before its text.
4. **An address lands on the block of its construct's kind.** A bookmark's start sits in the
   first paragraph its element made, which may be the heading a section opens with. The
   provenance part names each address's construct, `kind_map.toml` its kind, and the address is
   given to the nearest block, the paragraph itself or an ancestor, of that kind. A construct
   with no kind (an inline mark) has no block of its own and is not placed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from docx.oxml.ns import qn

__all__ = ["Node", "Notes", "read_body", "read_notes"]

_EL: Final = re.compile(r"ow_(u\d{2,})_(e\d+)")
_HEADING: Final = re.compile(r"Heading([1-9])")
_P, _TBL, _R, _T = qn("w:p"), qn("w:tbl"), qn("w:r"), qn("w:t")
_PPR, _SECT, _STYLE, _VAL = qn("w:pPr"), qn("w:sectPr"), qn("w:pStyle"), qn("w:val")
_NUMPR, _ILVL, _NUMID = qn("w:numPr"), qn("w:ilvl"), qn("w:numId")
_START, _NAME, _ID = qn("w:bookmarkStart"), qn("w:name"), qn("w:id")
_BR, _TAB, _HYPERLINK = qn("w:br"), qn("w:tab"), qn("w:hyperlink")
_REFS: Final = {qn("w:footnoteReference"): "footnote", qn("w:endnoteReference"): "endnote"}
_SKIPPED_RUNS: Final = frozenset({qn("w:footnoteRef"), qn("w:endnoteRef")})
_DRAWING, _DOCPR, _PBDR = qn("w:drawing"), qn("wp:docPr"), qn("w:pBdr")
_TR, _TC, _TCPR, _TRPR = qn("w:tr"), qn("w:tc"), qn("w:tcPr"), qn("w:trPr")
_SPAN, _VMERGE, _HEADER = qn("w:gridSpan"), qn("w:vMerge"), qn("w:tblHeader")


@dataclass
class Node:
    """One block of the read-back, before it is a fragment record."""

    kind: str
    text: str = ""
    payload: dict[str, Any] | None = None
    layer: str = "body"
    cell: dict[str, int] | None = None
    children: list[Node] = field(default_factory=list)
    starts: list[str] = field(default_factory=list)
    """The addresses whose bookmarks start in this paragraph."""
    refs: list[tuple[int, str, str]] = field(default_factory=list)
    """`(offset, kind, w:id)` for each note reference in this paragraph's text."""
    parent: Node | None = None
    el: str | None = None
    cites: list[str] = field(default_factory=list)

    def add(self, child: Node) -> Node:
        child.parent = self
        self.children.append(child)
        return child

    def joined(self) -> str:
        """Ruling 3: a leaf's own text, or its own layer's children's, one line each."""
        if not self.children:
            return self.text
        return "\n".join(t for c in self.children if c.layer == self.layer and (t := c.joined()))

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class _Lists:
    """The open lists: one `(numId, ilvl, list, last item)` a level, outermost first."""

    open: list[tuple[str, int, Node, Node | None]] = field(default_factory=list)

    def close(self) -> None:
        self.open.clear()


@dataclass
class _Body:
    """The walk's state between body children."""

    ordered: Mapping[str, bool]
    sections: list[Node] = field(default_factory=list)
    section: Node = field(default_factory=lambda: Node("section"))
    lists: _Lists = field(default_factory=_Lists)
    quote: Node | None = None
    caption: Node | None = None
    pending: list[str] = field(default_factory=list)
    """Addresses whose bookmarks start between blocks, given to the next paragraph read."""


def read_body(document: Any, numbering: Any | None) -> list[Node]:
    """Ruling 1: the body's sections, each with its blocks."""
    body = _Body(_ordered(numbering))
    root = document.find(qn("w:body"))
    for child in root if root is not None else ():
        if child.tag == _P:
            if child.find(f"{_PPR}/{_SECT}") is not None:
                _close(body)
                continue
            _paragraph(body, child)
        elif child.tag == _TBL:
            body.lists.close()
            body.quote = None
            table = body.section.add(_table(child, body))
            if body.caption is not None:
                caption, body.caption = body.caption, None
                table.children.insert(0, caption)
                caption.parent = table
        elif child.tag == _START:
            body.pending.extend(_addresses([child]))
    _close(body)
    return body.sections


@dataclass
class Notes:
    """Each note body, by kind and `w:id`."""

    by_id: dict[tuple[str, str], Node] = field(default_factory=dict)


def read_notes(root: Any | None, kind: str, notes: Notes) -> None:
    """Every note of one part but Word's two separators, each a `Layer.NOTE` block."""
    if root is None:
        return
    for note in root.findall(qn(f"w:{kind}")):
        if note.get(qn("w:type")) is not None:
            continue
        node = Node(kind, layer="note")
        for p in note.findall(_P):
            node.add(_leaf(p, "paragraph", [])).layer = "note"
        if node.children:
            first = node.children[0]
            first.text = first.text.removeprefix(" ")
        notes.by_id[kind, note.get(_ID, "")] = node


def _close(body: _Body) -> None:
    """Ruling 1: the open section, finished. One with no block is still a unit."""
    body.lists.close()
    body.quote = None
    if body.caption is not None:
        body.section.add(body.caption)
        body.caption = None
    body.sections.append(body.section)
    body.section = Node("section")


def _paragraph(body: _Body, p: Any) -> None:
    style = _style(p)
    if style != "Caption" and body.caption is not None:
        body.section.add(body.caption)
        body.caption = None
    if style == "ListParagraph":
        _listed(body, p)
        return
    body.lists.close()
    if style == "Quote":
        if body.quote is None:
            body.quote = body.section.add(Node("blockquote"))
        body.quote.add(_leaf(p, "paragraph", body.pending))
        return
    body.quote = None
    heading = _HEADING.fullmatch(style or "")
    if heading is not None:
        body.section.add(_leaf(p, "heading", body.pending, {"level": int(heading[1])}))
    elif style == "CodeBlock":
        body.section.add(_leaf(p, "code", body.pending))
    elif style == "Caption":
        _caption(body, _leaf(p, "caption", body.pending))
    elif p.find(f".//{_DRAWING}") is not None and not _text(p)[0]:
        docpr = p.find(f".//{_DOCPR}")
        alt = docpr.get("descr") if docpr is not None else None
        body.section.add(_leaf(p, "picture", body.pending, {"alt": alt} if alt else None))
    elif p.find(f"{_PPR}/{_PBDR}") is not None and not _text(p)[0]:
        body.section.add(_leaf(p, "rule", body.pending))
    else:
        body.section.add(_leaf(p, "paragraph", body.pending))


def _listed(body: _Body, p: Any) -> None:
    """Ruling 2: an item where a `w:numPr` names one, else a further paragraph of the last."""
    body.quote = None
    numpr = p.find(f"{_PPR}/{_NUMPR}")
    if numpr is not None:
        _item(body, p, numpr)
        return
    item = body.lists.open[-1][3] if body.lists.open else None
    (item or body.section).add(_leaf(p, "paragraph", body.pending))


def _caption(body: _Body, caption: Node) -> None:
    """Ruling 2: after a picture, a figure of the two; otherwise held for the next table."""
    last = body.section.children[-1] if body.section.children else None
    if last is not None and last.kind == "picture":
        body.section.children.pop()
        figure = body.section.add(Node("figure"))
        figure.add(last)
        figure.add(caption)
        return
    if body.caption is not None:
        body.section.add(body.caption)
    body.caption = caption


def _item(body: _Body, p: Any, numpr: Any) -> None:
    """Ruling 2: a list item, in the list its `w:numId` names, at its `w:ilvl`."""
    level = numpr.find(_ILVL)
    ilvl = int(level.get(_VAL, "0")) if level is not None else 0
    num_el = numpr.find(_NUMID)
    num = num_el.get(_VAL, "") if num_el is not None else ""
    stack = body.lists.open
    while stack and stack[-1][1] > ilvl:
        stack.pop()
    if stack and stack[-1][1] == ilvl and stack[-1][0] != num:
        stack.pop()
    if not stack or stack[-1][1] < ilvl:
        owner = stack[-1][3] if stack and stack[-1][3] is not None else body.section
        listed = owner.add(Node("list", payload={"ordered": body.ordered.get(num, False)}))
        stack.append((num, ilvl, listed, None))
    num_id, level_no, listed, _ = stack[-1]
    item = listed.add(Node("list_item"))
    item.add(_leaf(p, "paragraph", body.pending))
    stack[-1] = (num_id, level_no, listed, item)


def _table(tbl: Any, body: _Body) -> Node:
    """A grid laid out from `w:gridSpan` and `w:vMerge`, one `table_cell` per origin slot."""
    rows = tbl.findall(_TR)
    header = sum(1 for tr in rows if tr.find(f"{_TRPR}/{_HEADER}") is not None)
    table = Node("table", payload={"header_rows": header, "header_cols": 0, "kind": "data"})
    origins: dict[int, Node] = {}
    """Grid column -> the cell whose vertical merge is open in it."""
    for r, tr in enumerate(rows):
        c = 0
        for tc in tr.findall(_TC):
            tcpr = tc.find(_TCPR)
            span_el = tcpr.find(_SPAN) if tcpr is not None else None
            span = int(span_el.get(_VAL, "1")) if span_el is not None else 1
            merge = tcpr.find(_VMERGE) if tcpr is not None else None
            above = origins.get(c)
            if merge is not None and merge.get(_VAL) != "restart" and above is not None:
                if above.cell is not None:
                    above.cell["row_span"] += 1
                c += span
                continue
            cell_node = table.add(
                Node("table_cell", cell={"r": r, "c": c, "row_span": 1, "col_span": span})
            )
            for item in tc:
                if item.tag == _P and (_text(item)[0] or item.find(f".//{_START}") is not None):
                    cell_node.add(_leaf(item, "paragraph", body.pending))
                elif item.tag == _TBL:
                    cell_node.add(_table(item, body))
            if merge is not None:
                origins[c] = cell_node
            else:
                origins.pop(c, None)
            c += span
    return table


def _leaf(p: Any, kind: str, pending: list[str], payload: dict[str, Any] | None = None) -> Node:
    text, refs = _text(p)
    node = Node(kind, text=text, payload=payload, refs=refs)
    node.starts = [*pending, *_addresses(p.iter(_START))]
    pending.clear()
    return node


def _text(p: Any) -> tuple[str, list[tuple[int, str, str]]]:
    """Ruling 3: the paragraph's runs, in order, with where each note reference stands."""
    out: list[str] = []
    refs: list[tuple[int, str, str]] = []
    for run in p.iter(_R):
        for item in run:
            if item.tag == _T:
                out.append(item.text or "")
            elif item.tag == _BR:
                out.append("\n")
            elif item.tag == _TAB:
                out.append("\t")
            elif item.tag in _REFS:
                refs.append((len("".join(out)), _REFS[item.tag], item.get(_ID, "")))
    return "".join(out), refs


def _addresses(starts: Any) -> list[str]:
    found = []
    for start in starts:
        m = _EL.fullmatch(start.get(_NAME, ""))
        if m is not None:
            found.append(f"{m[1]}/{m[2]}")
    return found


def _style(p: Any) -> str | None:
    style = p.find(f"{_PPR}/{_STYLE}")
    return None if style is None else style.get(_VAL)


def _ordered(numbering: Any | None) -> dict[str, bool]:
    """`w:numId` -> whether its list counts: its abstract list's first level is not a bullet."""
    if numbering is None:
        return {}
    formats: dict[str, bool] = {}
    for abstract in numbering.findall(qn("w:abstractNum")):
        fmt = abstract.find(f"{qn('w:lvl')}/{qn('w:numFmt')}")
        formats[abstract.get(qn("w:abstractNumId"), "")] = (
            fmt is not None and fmt.get(_VAL) != "bullet"
        )
    out: dict[str, bool] = {}
    for num in numbering.findall(qn("w:num")):
        abstract = num.find(qn("w:abstractNumId"))
        if abstract is not None:
            out[num.get(qn("w:numId"), "")] = formats.get(abstract.get(_VAL, ""), False)
    return out
