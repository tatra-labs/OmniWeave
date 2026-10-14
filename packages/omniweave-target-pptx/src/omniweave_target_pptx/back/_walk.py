"""The PresentationML walk: a `.pptx` this target built, read back as a tree of blocks. D804.

`lower/` wrote one slide a unit, each a shape tree of groups, shapes, text boxes and pictures,
and a provenance part that names each address's construct (`els`) and where it landed (`at`,
D803). This module reads a slide's tree and nothing else.

## Rulings

1. **A slide is a `section`**, a group a `container`, a text box a `paragraph`, a picture a
   `picture`, and any other shape a `diagram`: `kind_map.toml`'s kinds. An addressed shape takes
   its own construct's kind, so a manual region's group is the `paragraph` its row says.
2. **A block's text is the artefact's.** A text box's is its paragraphs, a line each, its ends
   trimmed of empty lines unless it is preserved, as `Lines.render` joins a text's lines. A
   container's, a section's included, is each text box under it, a line each, as the carrier's
   `visible_text` joins a node's top-most texts.
3. **A `<use>` group holds a clone**, whose text the IL holds once, where it is defined. The
   group is a block with no text, and its clone is not walked, so no text is read twice. A group
   is a `<use>`'s by its address's construct, or, unaddressed, by the kind its name gives.
4. **An addressed `<tspan>` is a block of its own under its text box**: the runs its `at` names in
   its line, joined, and collapsed as the carrier collapses unless the text is preserved, which
   is its `visible_text`.
5. **A manual region's outline is a `comment` on `Layer.ANNOTATION`**, its text the outline's
   description, `ow:manual <reason>`, as docx's comment is; the region's own text stays its
   group's. It is a page root after its slide's section, as docx's comment is one after the
   body: M-INV-5 (03:1022) lets only a page root name its own layer.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from omniweave_core.out.carrier.tree import collapse
from pptx.oxml.ns import qn

__all__ = ["MANUAL", "Lookup", "Node", "Place", "read_slide"]

_SP, _GRP, _PIC = qn("p:sp"), qn("p:grpSp"), qn("p:pic")
_TX_BODY, _P, _R, _T = qn("p:txBody"), qn("a:p"), qn("a:r"), qn("a:t")
_NAMED: Final = {
    _SP: f"{qn('p:nvSpPr')}/{qn('p:cNvPr')}",
    _GRP: f"{qn('p:nvGrpSpPr')}/{qn('p:cNvPr')}",
    _PIC: f"{qn('p:nvPicPr')}/{qn('p:cNvPr')}",
}
MANUAL: Final = "ow:manual "
"""The name `lower.manual` gives a region's outline."""
_USE: Final = "def.use"
_UNADDRESSED_USE: Final = "use "
"""`lower.ids.shape_name` of a `<use>` with no address: its kind, then its id."""


@dataclass
class Node:
    """One block of the read-back, before it is a fragment record."""

    kind: str
    page: int
    text: str = ""
    layer: str = "body"
    parent: Node | None = None
    children: list[Node] = field(default_factory=list)
    el: str | None = None
    cites: list[str] = field(default_factory=list)

    def add(self, child: Node) -> Node:
        child.parent = self
        self.children.append(child)
        return child

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True, slots=True)
class Place:
    """Where one address landed in a slide (`at`): a shape's own, or a `<tspan>`'s line and
    runs."""

    el: str
    line: int | None = None
    runs: tuple[int, int] = (0, 0)
    preserve: bool = False


@dataclass(frozen=True, slots=True)
class Lookup:
    """Each address's construct (the part's `els`) and each construct's kind (`kind_map.toml`)."""

    els: Mapping[str, str]
    kinds: Mapping[str, str]

    def kind(self, el: str) -> str | None:
        return self.kinds.get(self.els.get(el, ""))

    def cloned(self, el: str) -> bool:
        return self.els.get(el) == _USE


def read_slide(
    tree: Any, page: int, located: Mapping[int, Sequence[Place]], lookup: Lookup
) -> list[Node]:
    """A slide's shape tree as a `section` and its blocks, then its manual outlines' comments
    (rulings 1 to 5)."""
    section = Node(kind="section", page=page)
    notes: list[Node] = []
    section.text = "\n".join(_walk(tree, section, located, lookup, notes))
    return [section, *notes]


def _walk(
    element: Any,
    parent: Node,
    located: Mapping[int, Sequence[Place]],
    lookup: Lookup,
    notes: list[Node],
) -> list[str]:
    """Each shape under `element` as a block under `parent`; the texts it holds, in order."""
    texts: list[str] = []
    for child in element:
        path = _NAMED.get(child.tag)
        if path is None:
            continue
        named = child.find(path)
        places = located.get(int(named.get("id")), ())
        own = next((p for p in places if p.line is None), None)
        if child.tag == _GRP:
            block = _block(parent, "container", own, lookup)
            if not _cloned(named, own, lookup):
                inner = _walk(child, block, located, lookup, notes)
                block.text = "\n".join(inner)
                texts.extend(inner)
        elif child.tag == _PIC:
            _block(parent, "picture", own, lookup)
        elif child.find(_TX_BODY) is not None:
            texts.append(_text_box(child, parent, own, places, lookup))
        elif (named.get("name") or "").startswith(MANUAL):
            text = named.get("descr") or ""
            notes.append(Node(kind="comment", page=parent.page, text=text, layer="annotation"))
        else:
            _block(parent, "diagram", own, lookup)
    return texts


def _text_box(
    shape: Any, parent: Node, own: Place | None, places: Sequence[Place], lookup: Lookup
) -> str:
    """Rulings 2 and 4: a text box's block, and a block for each `<tspan>` it located."""
    paragraphs = shape.find(_TX_BODY).findall(_P)
    joined = "\n".join("".join(t.text or "" for t in p.iter(_T)) for p in paragraphs)
    block = _block(parent, "paragraph", own, lookup)
    block.text = joined if own is not None and own.preserve else joined.strip("\n")
    for place in places:
        if place.line is None or place.line >= len(paragraphs):
            continue
        runs = paragraphs[place.line].findall(_R)[slice(*place.runs)]
        text = "".join(t.text or "" for r in runs for t in r.iter(_T))
        run = _block(block, "paragraph", place, lookup)
        run.text = text if place.preserve else collapse(text)
    return block.text


def _block(parent: Node, kind: str, place: Place | None, lookup: Lookup) -> Node:
    """Ruling 1: a block of `kind` under `parent`, or its address's construct's kind."""
    block = parent.add(Node(kind=kind, page=parent.page))
    if place is not None:
        block.el = place.el
        block.kind = lookup.kind(place.el) or kind
    return block


def _cloned(named: Any, own: Place | None, lookup: Lookup) -> bool:
    """Ruling 3: a `<use>`'s group, by its construct or, unaddressed, by its name."""
    if own is not None:
        return lookup.cloned(own.el)
    return (named.get("name") or "").startswith(_UNADDRESSED_USE)
