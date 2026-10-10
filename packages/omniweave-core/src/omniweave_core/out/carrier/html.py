"""The `html` carrier over stdlib `html.parser`: DOCTYPE, PIs and bogus comments refused. **D738.**

09-generation.md section 3.1 item 4, and its `visible_text` table's `html` row. `html.parser`
recovers from everything, so strictness is this module's: the strict parse refuses what the
recovering one records (ruling 4).

## Rulings (the ledger's D738)

11. **The strict parse is well-formed HTML, as a browser would build it.** An end tag that closes
    nothing, one that closes past an open element, an element left open, a second root element,
    text outside the root, a duplicated attribute, an end tag on a void element, and a non-void
    element written `<x/>` are each an error. That last one matters most: a browser does not close
    `<div/>`, so a tree that did would disagree with the `deck` Toolchain's own render. The
    recovering read records each and builds what a reader would expect.
12. **A bogus comment is any `handle_comment` whose source does not open `<!--`**, and a CDATA
    section is one too (`unknown_decl`). Both are refused in both modes, like a DOCTYPE and a
    processing instruction (09 section 3.1 item 4).
13. **The block and invisible sets are arguments until the ConstructTable exists.** 09 inserts
    `"\n"` *"at every block-level boundary in the declared construct set"* and drops elements whose
    row says `visible = false`. `constructs.py` is not built, so `html_carrier()` takes both sets,
    defaulting to HTML's block-level elements and to the elements a browser never renders (`head`,
    `script`, `style`, `template`).
"""

from __future__ import annotations

from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Final

from omniweave_core.out.carrier import CarrierNode, CarrierParseError, ParseError
from omniweave_core.out.carrier.tree import Budget, Cursor, Doc, Lines, Node, check_size

__all__ = ["BLOCKS", "INVISIBLE", "VOID", "HtmlDoc", "html_carrier"]

VOID: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
BLOCKS: Final = frozenset(
    {
        "address", "article", "aside", "blockquote", "caption", "dd", "details", "dialog",
        "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "nav", "ol", "p", "pre",
        "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)  # fmt: skip
INVISIBLE: Final = frozenset({"head", "script", "style", "template"})


class HtmlDoc(Doc):
    """One `owdeck/1`, `owflow/1` or `owtext/1` file."""

    def __init__(
        self, *, blocks: frozenset[str], invisible: frozenset[str], **kwargs: object
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._blocks = blocks
        self._invisible = invisible

    def visible_text(self, n: CarrierNode) -> str:
        """09 section 3.1's `html` row, under ruling 13's sets."""
        if not isinstance(n, Node):
            raise TypeError(f"{n!r} is not a node of this carrier")
        lines = Lines()
        self._gather(n, lines)
        return lines.render()

    def _gather(self, node: Node, lines: Lines) -> None:
        local = node.tag.removeprefix("html|")
        if local in self._invisible:
            return
        if local == "br":
            lines.hard()
            return
        block = local in self._blocks
        if block:
            lines.soft()
        for item in node.content:
            if isinstance(item, str):
                lines.text(item)
            else:
                self._gather(item, lines)
        if block:
            lines.soft()


def html_carrier(
    path: str,
    text: str,
    *,
    strict: bool,
    blocks: Iterable[str] = BLOCKS,
    invisible: Iterable[str] = INVISIBLE,
) -> HtmlDoc:
    """Parse one IL file. Raises `CarrierParseError`, or `ResourceLimit` naming its knob."""
    check_size(path, text.encode("utf-8"))
    builder = _Build(path, text, strict=strict)
    builder.feed(text)
    builder.close()
    roots, problems = builder.finish()
    blocks, invisible = frozenset(blocks), frozenset(invisible)
    return HtmlDoc(
        path=path,
        text=text,
        ns="html",
        roots=roots,
        problems=problems,
        reparse=lambda t: html_carrier(path, t, strict=True, blocks=blocks, invisible=invisible),
        blocks=blocks,
        invisible=invisible,
    )


class _Build(HTMLParser):
    def __init__(self, path: str, text: str, *, strict: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.text = text
        self.strict = strict
        self.cursor = Cursor(text)
        self.budget = Budget(path)
        self.line_starts = _line_starts(text)
        self.stack: list[Node] = []
        self.roots: list[Node] = []
        self.problems: list[ParseError] = []

    # -- positions --------------------------------------------------------------------------

    def _here(self) -> tuple[int, str]:
        """The current construct's character offset and its `path:line:col`."""
        line, col = self.getpos()
        return self.line_starts[line - 1] + col, f"{self.path}:{line}:{col + 1}"

    def _problem(self, at: str, msg: str) -> None:
        error = ParseError(at, msg)
        if self.strict:
            raise CarrierParseError(error)
        self.problems.append(error)

    def _refuse(self, what: str) -> None:
        raise CarrierParseError(ParseError(self._here()[1], f"{what} is refused"))

    # -- elements ---------------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, closed=tag in VOID)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID:
            self._problem(self._here()[1], f"<{tag}/> does not close a non-void element in HTML")
        self._open(tag, attrs, closed=True)

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        self.budget.admit(len(self.stack))
        char, at = self._here()
        start = self.cursor.byte_of(char)
        raw = self.get_starttag_text() or ""
        values: dict[str, str] = {}
        for name, value in attrs:
            if name in values:
                self._problem(at, f"attribute {name!r} is repeated on <{tag}>")
                continue
            values[name] = value or ""
        parent = self.stack[-1] if self.stack else None
        node = Node(
            f"html|{tag}",
            values,
            at=at,
            start=start,
            start_end=start + len(raw.encode("utf-8")),
            parent=parent,
        )
        node.self_closing = closed
        if parent is not None:
            parent.content.append(node)
        else:
            if self.roots:
                self._problem(at, f"<{tag}> is a second root element")
            self.roots.append(node)
        if not closed:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        char, at = self._here()
        start = self.cursor.byte_of(char)
        end = start + len(self.text[char : self.text.find(">", char) + 1].encode("utf-8"))
        if tag in VOID:
            self._problem(at, f"</{tag}> closes a void element")
            return
        depth = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].tag == f"html|{tag}"),
            None,
        )
        if depth is None:
            self._problem(at, f"</{tag}> closes no open element")
            return
        if depth != len(self.stack) - 1:
            self._problem(at, f"</{tag}> closes <{self.stack[-1].tag.removeprefix('html|')}> early")
        for node in self.stack[depth + 1 :]:
            node.end = start
        self.stack[depth].end = end
        del self.stack[depth:]

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].append_text(data)
        elif data.strip():
            self._problem(self._here()[1], "text outside the root element")

    # -- refused in both modes (09 section 3.1 item 4, ruling 12) ---------------------------

    def handle_comment(self, data: str) -> None:  # noqa: ARG002 -- the source decides.
        char, _ = self._here()
        if not self.text.startswith("<!--", char):
            self._refuse("a bogus comment")

    def handle_decl(self, decl: str) -> None:
        self._refuse(f"<!{decl.split(maxsplit=1)[0] if decl.strip() else decl}")

    def unknown_decl(self, data: str) -> None:  # noqa: ARG002 -- refused, whatever it holds.
        self._refuse("a CDATA section or bogus comment")

    def handle_pi(self, data: str) -> None:
        target = data.split(maxsplit=1)[0] if data.strip() else ""
        self._refuse(f"the processing instruction <?{target}")

    # -- the end ----------------------------------------------------------------------------

    def finish(self) -> tuple[list[Node], list[ParseError]]:
        end = len(self.text.encode("utf-8"))
        for node in reversed(self.stack):
            self._problem(node.at, f"<{node.tag.removeprefix('html|')}> is never closed")
            node.end = end
        self.stack.clear()
        if not self.roots:
            raise CarrierParseError(
                self.problems[0]
                if self.problems
                else ParseError(f"{self.path}:1:1", "no element found")
            )
        return self.roots, self.problems


def _line_starts(text: str) -> list[int]:
    starts = [0]
    at = text.find("\n")
    while at >= 0:
        starts.append(at + 1)
        at = text.find("\n", at + 1)
    return starts
