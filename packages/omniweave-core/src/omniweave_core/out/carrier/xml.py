"""The `svg` carrier over stdlib expat, refusing DOCTYPE, entities and PIs. **D738.**

09-generation.md section 3.1 items 2 and 4, and its `visible_text` table's `svg` row. An element
in the SVG namespace, or in none, is `svg|<local>`; an element in any other namespace keeps its
Clark spelling `{uri}local`, which no selector can name, so `unknown_construct = "forbidden"`
catches it (rule 2). `xlink:` and `xml:` attributes keep their prefixes.

## Rulings (the ledger's D738)

8. **The parse refuses before it expands.** Expat runs with parameter entities never parsed, and
   any DOCTYPE, entity declaration, external entity reference or processing instruction raises at
   its declaration, in both modes. The XML declaration is not a processing instruction to expat and
   passes.
9. **The recovering read keeps the tree as far as the first error**, closes what was open there,
   and records the error. Expat cannot step past a well-formedness error, so that is the whole of
   what an XML read can recover; a file with no root element at all is refused in both modes.
10. **`visible_text` of a `<text>` or `<tspan>` is its own; of any other node, each `<text>` under
    it, top-most only, one line each.** 09 defines the text of a `<text>`. A group holding three
    is three positioned texts, and a line each is what `read_back`'s blocks will hold.
"""

from __future__ import annotations

from typing import Final
from xml.parsers import expat

from omniweave_core.out.carrier import CarrierNode, CarrierParseError, ParseError
from omniweave_core.out.carrier.tree import Budget, Cursor, Doc, Lines, Node, check_size

__all__ = ["SVG_NS", "SvgDoc", "svg_carrier"]

SVG_NS: Final = "http://www.w3.org/2000/svg"
_PREFIXES: Final = {
    "http://www.w3.org/1999/xlink": "xlink",
    "http://www.w3.org/XML/1998/namespace": "xml",
}
_LINE_BREAK: Final = ("x", "dy")
_QUOTES: Final = (ord('"'), ord("'"))
_CLOSE: Final = ord(">")


class SvgDoc(Doc):
    """One `owsvg/1` file."""

    def visible_text(self, n: CarrierNode) -> str:
        """09 section 3.1's `svg` row, and ruling 10."""
        if not isinstance(n, Node):
            raise TypeError(f"{n!r} is not a node of this carrier")
        if n.tag in {"svg|text", "svg|tspan"}:
            return _text_of(n)
        texts: list[str] = []
        stack = [n]
        while stack:
            node = stack.pop()
            if node.tag == "svg|text":
                texts.append(_text_of(node))
                continue
            stack.extend(reversed(list(node.children())))
        return "\n".join(texts)


def _text_of(text: Node) -> str:
    lines = Lines()
    _gather(text, lines, first=True)
    return lines.render(preserve=_preserved(text))


def _gather(node: Node, lines: Lines, *, first: bool) -> None:
    if not first and any(node.attr(a) is not None for a in _LINE_BREAK):
        lines.hard()
    for item in node.content:
        if isinstance(item, str):
            lines.text(item)
        elif item.tag == "svg|tspan":
            _gather(item, lines, first=False)


def _preserved(node: Node) -> bool:
    current: Node | None = node
    while current is not None:
        space = current.attr("xml:space")
        if space is not None:
            return space == "preserve"
        current = current.parent
    return False


def svg_carrier(path: str, text: str, *, strict: bool) -> SvgDoc:
    """Parse one IL file. Raises `CarrierParseError`, or `ResourceLimit` naming its knob."""
    data = text.encode("utf-8")
    check_size(path, data)
    return _Build(path, text, data, strict=strict).run()


class _Refused(Exception):  # noqa: N818 -- a control-flow signal out of an expat handler.
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


class _Build:
    def __init__(self, path: str, text: str, data: bytes, *, strict: bool) -> None:
        self.path = path
        self.text = text
        self.data = data
        self.strict = strict
        self.cursor = Cursor(text)
        self.budget = Budget(path)
        self.stack: list[Node] = []
        self.roots: list[Node] = []
        self.parser = expat.ParserCreate(encoding="UTF-8", namespace_separator=" ")
        self.parser.ordered_attributes = True
        self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        self.parser.StartDoctypeDeclHandler = self._doctype
        self.parser.EntityDeclHandler = self._entity
        self.parser.ExternalEntityRefHandler = self._external
        self.parser.ProcessingInstructionHandler = self._pi
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.CharacterDataHandler = self._chars

    def run(self) -> SvgDoc:
        problems: list[ParseError] = []
        try:
            self.parser.Parse(self.data, True)
        except _Refused as refused:
            raise CarrierParseError(
                self._error(self.parser.CurrentByteIndex, f"{refused.what} is refused")
            ) from None
        except expat.ExpatError as exc:
            error = self._error(self.parser.ErrorByteIndex, expat.ErrorString(exc.code) or str(exc))
            if self.strict:
                raise CarrierParseError(error) from None
            problems.append(error)
            for node in self.stack:
                node.end = max(self.parser.ErrorByteIndex, node.start_end)
        if not self.roots:
            raise CarrierParseError(
                problems[0] if problems else ParseError(f"{self.path}:1:1", "no element found")
            )
        return SvgDoc(
            path=self.path,
            text=self.text,
            ns="svg",
            roots=self.roots[:1],
            problems=problems,
            reparse=lambda t: svg_carrier(self.path, t, strict=True),
        )

    def _error(self, byte: int, msg: str) -> ParseError:
        at = max(byte, 0)
        position = Cursor(self.text)
        position.char_of(at, self.data)
        line, col = position.position()
        return ParseError(f"{self.path}:{line}:{col}", msg)

    def _doctype(self, *_: object) -> None:
        raise _Refused("a DOCTYPE")

    def _entity(self, *_: object) -> None:
        raise _Refused("an entity declaration")

    def _external(self, *_: object) -> int:
        raise _Refused("an external entity reference")

    def _pi(self, target: str, _data: str) -> None:
        raise _Refused(f"the processing instruction <?{target}")

    def _start(self, name: str, attributes: list[str]) -> None:
        self.budget.admit(len(self.stack))
        start = self.parser.CurrentByteIndex
        self.cursor.char_of(start, self.data)
        line, col = self.cursor.position()
        start_end = _tag_end(self.data, start)
        attrs = {_attr(attributes[i]): attributes[i + 1] for i in range(0, len(attributes), 2)}
        parent = self.stack[-1] if self.stack else None
        node = Node(
            _tag(name),
            attrs,
            at=f"{self.path}:{line}:{col}",
            start=start,
            start_end=start_end,
            parent=parent,
        )
        node.self_closing = self.data[start_end - 2 : start_end] == b"/>"
        if parent is None:
            self.roots.append(node)
        else:
            parent.content.append(node)
        self.stack.append(node)

    def _end(self, _name: str) -> None:
        node = self.stack.pop()
        node.end = (
            node.start_end
            if node.self_closing
            else _tag_end(self.data, self.parser.CurrentByteIndex)
        )

    def _chars(self, data: str) -> None:
        if self.stack:
            self.stack[-1].append_text(data)


def _tag(name: str) -> str:
    uri, _, local = name.rpartition(" ")
    if not uri or uri == SVG_NS:
        return f"svg|{local}"
    return f"{{{uri}}}{local}"


def _attr(name: str) -> str:
    uri, _, local = name.rpartition(" ")
    if not uri:
        return local
    prefix = _PREFIXES.get(uri)
    return f"{prefix}:{local}" if prefix else f"{{{uri}}}{local}"


def _tag_end(data: bytes, start: int) -> int:
    """One past the `>` closing the tag that opens at `start`, quotes respected."""
    quote = 0
    for i in range(start + 1, len(data)):
        c = data[i]
        if quote:
            if c == quote:
                quote = 0
        elif c in _QUOTES:
            quote = c
        elif c == _CLOSE:
            return i + 1
    return len(data)
