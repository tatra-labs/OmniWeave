"""The lowering walk: owflow/1 nodes to python-docx blocks and runs, dispatched by the table.

09 section 5.2: *"`maps_to` is the whole mapping table ... There is no dispatch dictionary
maintained by hand and no `getattr` on a construct id."* An element is lowered by the function its
native row's `maps_to` names (`lower.blocks:heading`), resolved from the table, so a construct the
table gains without a function is preflight check 1's refusal and never a silent skip. The module
half of a `maps_to` is looked up among the family modules `_pack` imports, never imported by
name: `importlib.import_module` is the host's alone (INV-4).

The `Emitter` holds what the handlers share: the scope blocks go into (the body, a table cell,
with its paragraph defaults), the paragraph runs go into, the inline marks in force, the HTML
whitespace rule's state, the numbering and the bookmark counter.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from types import ModuleType
from typing import TYPE_CHECKING, Any, Final

from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run
from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import CarrierNode, Selector, parse_selector, style_declarations
from omniweave_core.out.constructs import Construct, ConstructTable, Disposition

from omniweave_target_docx.lower.blocks import alignment, bidi
from omniweave_target_docx.lower.ids import bookmark
from omniweave_target_docx.lower.inline import language
from omniweave_target_docx.rules import BLOCKS

if TYPE_CHECKING:
    from docx.document import Document
    from docx.text.paragraph import Paragraph

__all__ = [
    "CODE_FONT",
    "Emitter",
    "Marks",
    "Row",
    "refuse_unmapped",
    "resolve",
    "rows_of",
    "unmapped",
    "walk",
]

Handler = Callable[["Emitter", CarrierNode], None]
_SPACE: Final = re.compile(r"([ \t\n\r\f]+)")
_BLOCK_TAGS: Final = frozenset(f"html|{b}" for b in BLOCKS)
_P: Final = qn("w:p")
_PPR: Final = qn("w:pPr")
_SECT: Final = qn("w:sectPr")
CODE_FONT: Final = "Courier New"
"""`code` and `pre`: a monospace face every Word install has."""


@dataclass(frozen=True, slots=True)
class Marks:
    """The run properties the inline ancestors of a piece of text put in force."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    code: bool = False
    subscript: bool = False
    superscript: bool = False
    highlight: bool = False
    lang: str | None = None
    rtl: bool = False


@dataclass(frozen=True, slots=True)
class Row:
    """One native row with its selector parsed: what a node matches for the row's function."""

    construct: Construct
    selector: Selector


def rows_of(table: ConstructTable) -> tuple[Row, ...]:
    """The table's native rows, in table order."""
    return tuple(
        Row(row, parse_selector(row.selector, table.carrier))
        for row in table.rows
        if row.disposition is Disposition.NATIVE
    )


def resolve(maps_to: str, families: Mapping[str, ModuleType]) -> Callable[..., Any] | None:
    """`lower.blocks:heading` to its function, or `None` when it is not built (preflight 1)."""
    module, _, symbol = maps_to.partition(":")
    family = families.get(module)
    if family is None or symbol.startswith("_") or symbol not in getattr(family, "__all__", ()):
        return None
    found = getattr(family, symbol)  # a name the table holds and the module exports
    return found if callable(found) else None


def walk(root: CarrierNode) -> Iterator[CarrierNode]:
    """`root` and every element below it, in document order."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(list(node.children())))


def unmapped(
    roots: Sequence[CarrierNode], rows: Sequence[Row], families: Mapping[str, ModuleType]
) -> list[Construct]:
    """Preflight 1: each row the units use whose `maps_to` this `lower/` does not define."""
    used: dict[str, Construct] = {}
    for root in roots:
        for node in walk(root):
            for row in rows:
                if row.selector.matches(node):
                    used.setdefault(row.construct.id, row.construct)
    return [c for c in used.values() if resolve(c.maps_to or "", families) is None]


def refuse_unmapped(missing: Sequence[Construct]) -> None:
    if missing:
        named = ", ".join(f"{c.id} ({c.maps_to})" for c in missing)
        raise TargetError(
            f"the units use constructs this compiler cannot lower: {named}",
            symbol="OW_TARGET_CONSTRUCT_UNMAPPED",
            fix=f"ow out constructs docx --construct {missing[0].id}",
        )


@dataclass
class _Scope:
    """Where blocks go, and the defaults a paragraph made there takes."""

    container: Any
    element: Any
    style: str | None = None
    indent: int | None = None
    align: str | None = None
    number: tuple[int, int] | None = None
    """`(numId, ilvl)` for the next paragraph made here: a list item's first paragraph."""


@dataclass
class Emitter:
    """The state the handlers share. One a compile: every unit lowers into one document."""

    document: Document
    rows: tuple[Row, ...]
    families: Mapping[str, ModuleType]
    assets: Mapping[str, bytes]
    numbering: Any
    text_width: int
    scopes: list[_Scope] = field(default_factory=list)
    paragraph: Paragraph | None = None
    run_parent: Any = None
    marks: Marks = field(default_factory=Marks)
    preserve: bool = False
    """Inside `pre`: every space and line break is kept."""
    lists: list[int] = field(default_factory=list)
    """The `numId` of each list the walk is inside, outermost first."""
    bookmarks: int = 0
    buffer: list[str] = field(default_factory=list)
    buffer_marks: Marks = field(default_factory=Marks)
    at_start: bool = True
    pending: str = ""
    """What a following piece of text is prefixed with: a collapsed space, or `pre`'s newline."""
    handlers: dict[str, Handler] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scopes.append(_Scope(self.document, self.document.element.body))

    # -- dispatch -------------------------------------------------------------------------------

    def handler(self, node: CarrierNode) -> Handler:
        """The function the first native element row matching `node` names."""
        for row in self.rows:
            if row.selector.kind == "element" and row.selector.matches(node):
                maps_to = row.construct.maps_to or ""
                if maps_to not in self.handlers:
                    found = resolve(maps_to, self.families)
                    if found is None:
                        refuse_unmapped([row.construct])
                    self.handlers[maps_to] = found  # type: ignore[assignment]
                return self.handlers[maps_to]
        raise TargetError(
            f"<{node.tag.partition('|')[2]}> at {node.at} matches no native row of owflow/1",
            symbol="OW_TARGET_CONSTRUCT_UNMAPPED",
            fix="ow out check --stage final   # the gate refuses what no row declares",
        )

    def block(self, node: CarrierNode) -> None:
        """One block construct, with what it passes down, inside its bookmark."""
        self.end_paragraph()
        self.addressed(node, lambda: self.handler(node)(self, node))

    def addressed(self, node: CarrierNode, body: Callable[[], None]) -> None:
        """`body` under `node`'s inherited properties, inside a bookmark when it has a `data-ow-el`.

        The bookmark's ends are placed where the next block goes before and after `body` runs,
        then moved inside the first and last paragraphs it made, or dropped if it made none.
        """
        with self.inherited(node):
            if not node.el:
                body()
                self.end_paragraph()
                return
            element = self.scopes[-1].element
            start, end = self.bookmark_pair(node.el)
            _insert(element, start)
            body()
            self.end_paragraph()
            _insert(element, end)
            _tuck(start, end)

    def inline(self, node: CarrierNode) -> None:
        """One inline construct, inside a bookmark when it carries a `data-ow-el`."""
        with self.inherited(node):
            if not node.el:
                self.handler(node)(self, node)
                return
            self.flush()
            start, end = self.bookmark_pair(node.el)
            self.parent().append(start)
            self.handler(node)(self, node)
            self.flush()
            self.parent().append(end)

    def flow(self, node: CarrierNode) -> None:
        """A container's contents: blocks in place, inline content in implicit paragraphs."""
        for item in node.contents():
            if isinstance(item, str):
                if self.paragraph is not None or _SPACE.sub("", item):
                    self.text(item)
            elif item.tag in _BLOCK_TAGS:
                self.block(item)
            else:
                self.inline(item)
        self.end_paragraph()

    def inline_children(self, node: CarrierNode) -> None:
        for item in node.contents():
            if isinstance(item, str):
                self.text(item)
            else:
                self.inline(item)

    @contextmanager
    def inherited(self, node: CarrierNode) -> Iterator[None]:
        """What an element passes to everything inside it: `lang`, `dir` and `text-align`."""
        changes: dict[str, Any] = {}
        lang = node.attr("lang")
        if lang:
            changes["lang"] = lang
        direction = node.attr("dir")
        if direction in {"ltr", "rtl"}:
            changes["rtl"] = direction == "rtl"
        align = [v.strip().lower() for p, v in style_declarations(node.attr("style") or "")
                 if p == "text-align"]  # fmt: skip
        if not changes and not align:
            yield
            return
        outer, scope = self.marks, self.scopes[-1]
        before = scope.align
        self.marks = replace(outer, **changes)
        if align:
            scope.align = align[-1]
        try:
            yield
        finally:
            self.marks = outer
            scope.align = before

    # -- scopes and paragraphs ------------------------------------------------------------------

    @contextmanager
    def scope(
        self,
        container: Any = None,
        *,
        element: Any = None,
        style: str | None = None,
        indent: int | None = None,
        number: tuple[int, int] | None = None,
    ) -> Iterator[_Scope]:
        """Paragraphs made inside go into `container`, else the current one, with these defaults."""
        self.end_paragraph()
        outer = self.scopes[-1]
        inner = _Scope(
            container if container is not None else outer.container,
            element if element is not None else outer.element,
            style if style is not None else outer.style,
            indent if indent is not None else outer.indent,
            outer.align,
            number,
        )
        self.scopes.append(inner)
        try:
            yield inner
        finally:
            self.end_paragraph()
            self.scopes.pop()

    def new_paragraph(self, style: str | None = None) -> Paragraph:
        self.end_paragraph()
        scope = self.scopes[-1]
        paragraph = scope.container.add_paragraph(style=style or scope.style)
        if scope.number is not None:
            _number(paragraph, *scope.number)
            scope.number = None
        elif scope.indent is not None:
            paragraph.paragraph_format.left_indent = scope.indent
        if scope.align is not None:
            alignment(paragraph, scope.align)
        if self.marks.rtl:
            bidi(paragraph)
        self.paragraph = paragraph
        self.run_parent = None
        self.at_start, self.pending = True, ""
        return paragraph

    def ensure_paragraph(self) -> Paragraph:
        return self.paragraph if self.paragraph is not None else self.new_paragraph()

    def end_paragraph(self) -> None:
        self.flush()
        self.paragraph = None
        self.run_parent = None

    # -- text and runs --------------------------------------------------------------------------

    def text(self, data: str) -> None:
        """HTML's whitespace rule across runs, or `pre`'s, which keeps every character but one
        newline after the start tag and one before the end tag."""
        self.ensure_paragraph()
        if self.preserve:
            data = data.replace("\r\n", "\n")
            if self.at_start:
                data = data.removeprefix("\n")
            if not data:
                return
            self.buffered(self.pending + data.removesuffix("\n"))
            self.pending = "\n" if data.endswith("\n") else ""
            self.at_start = False
            return
        for piece in _SPACE.split(data):
            if not piece:
                continue
            if _SPACE.fullmatch(piece):
                self.pending = "" if self.at_start else " "
                continue
            self.buffered(self.pending + piece)
            self.at_start, self.pending = False, ""

    def buffered(self, data: str) -> None:
        """Text for the current run, which one `flush()` writes once the marks change."""
        self.ensure_paragraph()
        if self.buffer and self.buffer_marks != self.marks:
            self.flush()
        if not self.buffer:
            self.buffer_marks = self.marks
        self.buffer.append(data)

    def line_break(self) -> None:
        self.run().add_break()
        self.at_start, self.pending = True, ""

    @contextmanager
    def marked(self, **changes: Any) -> Iterator[None]:
        """Marks in force for the runs made inside."""
        outer = self.marks
        self.marks = replace(outer, **changes)
        try:
            yield
        finally:
            self.marks = outer

    def run(self) -> Run:
        """An empty run with the current marks, after any buffered text."""
        self.flush()
        return self._make_run("", self.marks)

    def flush(self) -> None:
        if not self.buffer:
            return
        text = "".join(self.buffer)
        self.buffer.clear()
        if text:
            self._make_run(text, self.buffer_marks)

    def parent(self) -> Any:
        """The element runs are appended to: a hyperlink when one is open, else the paragraph."""
        paragraph = self.ensure_paragraph()
        return self.run_parent if self.run_parent is not None else paragraph._p

    def _make_run(self, text: str, marks: Marks) -> Run:
        paragraph = self.ensure_paragraph()
        r = OxmlElement("w:r")
        self.parent().append(r)
        run = Run(r, paragraph)
        if text:
            run.text = text
        _apply(run, marks, link=self.run_parent is not None)
        return run

    def bookmark_pair(self, el: str) -> tuple[Any, Any]:
        pair = bookmark(el, self.bookmarks)
        self.bookmarks += 1
        return pair


def _number(paragraph: Paragraph, num_id: int, ilvl: int) -> None:
    """A list item's first paragraph: `w:numPr` naming its list and level."""
    numpr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    numpr.get_or_add_ilvl().val = ilvl
    numpr.get_or_add_numId().val = num_id


def _insert(parent: Any, element: Any) -> None:
    """Where the next block goes: before a body's closing `sectPr`, else at the end."""
    last = parent[-1] if len(parent) else None
    if last is not None and last.tag == _SECT:
        last.addprevious(element)
    else:
        parent.append(element)


def _tuck(start: Any, end: Any) -> None:
    """A block bookmark moved inside its first and last paragraphs, or dropped if it is empty."""
    first = start.getnext()
    if first is end:
        start.getparent().remove(start)
        end.getparent().remove(end)
        return
    if first is not None and first.tag == _P:
        start.getparent().remove(start)
        ppr = first.find(_PPR)
        if ppr is not None:
            ppr.addnext(start)
        else:
            first.insert(0, start)
    last = end.getprevious()
    if last is not None and last.tag == _P:
        end.getparent().remove(end)
        last.append(end)


def _apply(run: Run, marks: Marks, *, link: bool) -> None:
    """The marks as run properties, in CT_RPr's order: python-docx's own, then `rtl`, `lang`."""
    if link:
        run.style = "Hyperlink"
    if marks.code:
        run.font.name = CODE_FONT
    if marks.bold:
        run.bold = True
    if marks.italic:
        run.italic = True
    if marks.strike:
        run.font.strike = True
    if marks.highlight:
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    if marks.underline:
        run.underline = True
    if marks.subscript:
        run.font.subscript = True
    if marks.superscript:
        run.font.superscript = True
    if marks.rtl:
        run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
    if marks.lang:
        language(run, marks.lang)
