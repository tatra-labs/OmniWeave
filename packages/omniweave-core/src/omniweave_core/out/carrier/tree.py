"""The node and document both carriers build: one tree shape, two parsers. **D738.**

`carrier.xml` and `carrier.html` differ in how they parse and in what text is visible, and in
nothing else a rule can see. The node, the walk, `select()` and `splice()` are this module's, so
the two cannot disagree on what a selector yields or on how an edit lands.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from typing import Final

from omniweave_core.errors import ResourceLimit
from omniweave_core.limits import MAX_IL_DEPTH, MAX_IL_FILE_BYTES, MAX_IL_NODES
from omniweave_core.out.carrier import (
    CarrierNode,
    ParseError,
    Splice,
    apply_splices,
    parse_selector,
)

__all__ = ["Budget", "Cursor", "Doc", "Lines", "Node", "check_size", "collapse", "walk"]

EL_ATTRIBUTE: Final = "data-ow-el"
_SPACE: Final = re.compile(r"[ \t\n\r\f]+")


class Node:
    """One element. Positions are byte offsets into the UTF-8 source (09 section 3.1 decision 1)."""

    __slots__ = (
        "_at",
        "_attrs",
        "content",
        "end",
        "parent",
        "self_closing",
        "start",
        "start_end",
        "tag",
    )

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        *,
        at: str,
        start: int,
        start_end: int,
        parent: Node | None,
    ) -> None:
        self.tag = tag
        self._attrs = attrs
        self._at = at
        self.start = start
        """The `<` of the start tag."""
        self.start_end = start_end
        """One past the start tag's `>`."""
        self.end = start_end
        """One past the end tag's `>`; the start tag's end for a self-closed element."""
        self.self_closing = False
        self.parent = parent
        self.content: list[Node | str] = []
        """Character data and child elements, in document order."""

    @property
    def at(self) -> str:
        return self._at

    @property
    def el(self) -> str | None:
        return self._attrs.get(EL_ATTRIBUTE)

    def attr(self, name: str) -> str | None:
        return self._attrs.get(name)

    def attrs(self) -> dict[str, str]:
        """Every attribute, in source order."""
        return dict(self._attrs)

    def children(self) -> Iterator[Node]:
        return (c for c in self.content if isinstance(c, Node))

    def text_content(self) -> str:
        return "".join(_texts(self))

    def append_text(self, text: str) -> None:
        if self.content and isinstance(self.content[-1], str):
            self.content[-1] += text
        else:
            self.content.append(text)

    def __repr__(self) -> str:
        return f"<{self.tag} at {self._at}>"


def _texts(node: Node) -> Iterator[str]:
    stack: list[Node | str] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        else:
            stack.extend(reversed(item.content))


def walk(roots: Sequence[Node]) -> Iterator[Node]:
    """Every element, in document order. Iterative: depth is bounded, but not by the stack."""
    stack: list[Node] = list(reversed(roots))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed([c for c in node.content if isinstance(c, Node)]))


def collapse(text: str) -> str:
    """Runs of whitespace to one space, ends stripped: the carriers' shared whitespace rule."""
    return _SPACE.sub(" ", text).strip()


class Lines:
    """Visible-text assembly: soft breaks end a non-empty line, hard breaks always end one."""

    def __init__(self) -> None:
        self._lines: list[list[str]] = [[]]

    def text(self, piece: str) -> None:
        self._lines[-1].append(piece)

    def soft(self) -> None:
        if collapse("".join(self._lines[-1])):
            self._lines.append([])

    def hard(self) -> None:
        self._lines.append([])

    def render(self, *, preserve: bool = False) -> str:
        if preserve:
            return "\n".join("".join(line) for line in self._lines)
        return "\n".join(collapse("".join(line)) for line in self._lines).strip("\n")


class Cursor:
    """Byte offsets and positions for events that arrive in source order: O(source) in total.

    A minified IL is one 4 MiB line, and converting each event's position from the line start
    would be quadratic in it.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._char = 0
        self._byte = 0
        self._line = 1
        self._col = 1

    def byte_of(self, char: int) -> int:
        """The byte offset of character `char`, which never moves backwards."""
        if char < self._char:
            return len(self._text[:char].encode("utf-8"))
        piece = self._text[self._char : char]
        self._advance(piece)
        self._char = char
        return self._byte

    def char_of(self, byte: int, data: bytes) -> int:
        """The character offset of byte `byte`, which never moves backwards."""
        if byte < self._byte:
            return len(data[:byte].decode("utf-8", "replace"))
        piece = data[self._byte : byte].decode("utf-8", "replace")
        self._advance(piece)
        self._char += len(piece)
        return self._char

    def position(self) -> tuple[int, int]:
        """The 1-based line and column (in characters) of the last offset converted."""
        return self._line, self._col

    def _advance(self, piece: str) -> None:
        self._byte += len(piece.encode("utf-8"))
        newlines = piece.count("\n")
        if newlines:
            self._line += newlines
            self._col = len(piece) - piece.rfind("\n")
        else:
            self._col += len(piece)


class Budget:
    """`MAX_IL_DEPTH` and `MAX_IL_NODES`, checked as the parse goes (ruling 3)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._nodes = 0

    def admit(self, depth: int) -> None:
        self._nodes += 1
        if depth >= MAX_IL_DEPTH:
            raise ResourceLimit(
                f"{self._path} nests deeper than MAX_IL_DEPTH ({MAX_IL_DEPTH})",
                limit="MAX_IL_DEPTH",
                fix="flatten the unit's nesting; widening the ceiling is a fork",
            )
        if self._nodes > MAX_IL_NODES:
            raise ResourceLimit(
                f"{self._path} holds more than MAX_IL_NODES ({MAX_IL_NODES}) elements",
                limit="MAX_IL_NODES",
                fix="split the unit; widening the ceiling is a fork",
            )


def check_size(path: str, data: bytes) -> None:
    """`MAX_IL_FILE_BYTES`, before a byte is parsed (ruling 3)."""
    if len(data) > MAX_IL_FILE_BYTES:
        raise ResourceLimit(
            f"{path} is {len(data)} bytes, above MAX_IL_FILE_BYTES ({MAX_IL_FILE_BYTES})",
            limit="MAX_IL_FILE_BYTES",
            fix="split the unit; widening the ceiling is a fork",
        )


class Doc:
    """What both carriers share: the roots, the walk, `select()` and the strict `splice()`."""

    comment_open = "<!--"
    comment_close = "-->"

    def __init__(
        self,
        *,
        path: str,
        text: str,
        ns: str,
        roots: Sequence[Node],
        problems: Sequence[ParseError],
        reparse: Callable[[str], object],
    ) -> None:
        self._path = path
        self._text = text
        self._ns = ns
        self._roots = tuple(roots)
        self._problems = tuple(problems)
        self._reparse = reparse

    @property
    def path(self) -> str:
        return self._path

    @property
    def problems(self) -> tuple[ParseError, ...]:
        return self._problems

    def root(self) -> Node:
        return self._roots[0]

    def nodes(self) -> Iterator[Node]:
        return walk(self._roots)

    def select(self, selector: str) -> tuple[CarrierNode, ...]:
        parsed = parse_selector(selector, self._ns)
        return tuple(n for n in walk(self._roots) if parsed.matches(n))

    def source(self) -> str:
        return self._text

    def splice(self, edits: Sequence[Splice]) -> str | ParseError:
        """Ruling 4: a document the read had to recover is never written."""
        if self._problems:
            return self._problems[0]
        return apply_splices(self._text, edits, self._reparse)
