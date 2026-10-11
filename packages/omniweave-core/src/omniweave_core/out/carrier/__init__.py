"""The carrier seam: `CarrierDoc`, `CarrierNode`, `Splice`, `ParseError` and the selector. **D738.**

09-generation.md section 3.1. A carrier is an existing text format with an existing stdlib parser:
`carrier.xml` for `svg` and `carrier.html` for `html`. This module holds what both share: the
types every rule is written against, the one selector grammar three callers parse through, the
inline-style splitter `@style|<prop>` reads, and the transactional splice.

## Rulings (the ledger's D738)

1. **`select()` returns a tuple.** 09 prints `Iterator[CarrierNode]`, and the reference target's
   `rule_id_with_style` opens with `if not ctx.doc.select("html|style"): return`, which against an
   iterator never returns: an iterator is always true. A tuple makes that line mean what it says,
   and a unit's matches are bounded by `MAX_IL_NODES` either way.
2. **A carrier failure raises, and a splice failure is returned.** `CarrierDoc` is what
   `CompileV1.carrier()` returns, so a file that will not parse raises `CarrierParseError`, which
   carries the `ParseError` value `run_pack()`'s order 0 records. `splice()` returns its
   `ParseError` (09 section 3.1 decision 3), so the original is untouched when the caller branches.
3. **A limit is a `ResourceLimit` naming its knob**: `MAX_IL_FILE_BYTES`, `MAX_IL_DEPTH` and
   `MAX_IL_NODES`, each checked during the parse and not after (09 section 14.3).
4. **The recovering read records what it recovered from.** `CarrierDoc.problems` is every
   well-formedness error the READ parse stepped over. Order 0 can still fail the file, and
   `splice()` refuses to write a document that has any: *"never modify a file you could not fully
   parse"*. A DOCTYPE, an entity declaration, a processing instruction, an HTML bogus comment and a
   limit are refused in both modes.
5. **A selector's prefix is the carrier's own.** `parse_selector(s, ns)` refuses `html|p` against
   `svg`, and `@<name>|<sub>` for any `<name>` but `style`, with `OW_TARGET_SELECTOR_INVALID` and
   the offset (09 section 3.1 rules 2, 3 and 6).
6. **Overlapping splices are refused before any is applied, and so are two at one offset**: two
   edits to one place are two opinions (09 section 8.3 pt 3). An offset outside the source or
   inside a UTF-8 sequence is refused the same way, as the caller's error, not the file's.
7. **`place_marker()` and `Insertion` arrived with D746**, and `nsig` with D743's canonicaliser.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from typing import Final, Literal, Protocol

from omniweave_core.errors import TargetError

__all__ = [
    "CarrierDoc",
    "CarrierNode",
    "CarrierParseError",
    "Insertion",
    "ParseError",
    "Selector",
    "Splice",
    "apply_splices",
    "parse_selector",
    "style_declarations",
]

_SELECTOR_FIX: Final = "ow explain OW-T-007"
_LEAD_MASK: Final = 0xC0
_CONTINUATION: Final = 0x80
"""A UTF-8 continuation byte is `10xxxxxx`: no splice may start or end on one."""


class CarrierNode(Protocol):
    """One element (09 section 3.1). Every rule is written against this and nothing else."""

    @property
    def at(self) -> str:
        """`il/u03.svg:41:9`: job-relative path, 1-based line, 1-based column in characters."""
        ...

    @property
    def el(self) -> str | None:
        """The `data-ow-el` address, `None` until `ow out stamp` has minted one."""
        ...

    @property
    def nsig(self) -> str:
        """8 hex over this node's canonical subtree (09 section 8.2), memoized per node.

        The subtree half only: the shared-definition half is the resolver's, once a unit.
        """
        ...

    @property
    def tag(self) -> str:
        """`svg|text`, `html|p`: the selector's spelling."""
        ...

    def attr(self, name: str) -> str | None:
        """`None` when absent, `""` when present and empty."""
        ...

    def children(self) -> Iterator[CarrierNode]:
        """The element children, in document order."""
        ...

    def text_content(self) -> str:
        """The subtree's raw character data: no whitespace rule, no NFC. Not `visible_text()`."""
        ...


class CarrierDoc(Protocol):
    """One parsed IL file (09 section 3.1), less `place_marker()` (ruling 7)."""

    comment_open: str
    comment_close: str

    @property
    def problems(self) -> tuple[ParseError, ...]:
        """Ruling 4: what the recovering read stepped over. Empty after a strict parse."""
        ...

    def root(self) -> CarrierNode: ...

    def select(self, selector: str) -> tuple[CarrierNode, ...]:
        """Every node the selector yields, in document order (ruling 1)."""
        ...

    def source(self) -> str: ...

    def splice(self, edits: Sequence[Splice]) -> str | ParseError:
        """Apply `edits` back to front and reparse strictly; all or nothing (OUT17)."""
        ...

    def visible_text(self, n: CarrierNode) -> str:
        """The carrier's definition of the visible text (09 section 3.1's table)."""
        ...

    def place_marker(self, n: CarrierNode) -> Insertion:
        """Where a marker for `n` would go: its container's first child, on its own line."""
        ...


@dataclass(frozen=True, slots=True)
class Splice:
    """One edit over a byte range of `source().encode("utf-8")`."""

    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"splice [{self.start}, {self.end}) is not a byte range")


@dataclass(frozen=True, slots=True)
class Insertion:
    """Where a marker line lands (09 section 3.1). Offsets are `Splice`'s byte space."""

    at_byte: int
    """Where the marker's text is spliced in."""
    line: int
    """The 1-based line the marker then occupies."""
    el: str
    """The address the marker is written against."""
    container_el: str | None
    """The ancestor that carries it, set iff hoisted."""
    hoisted: bool
    """The anchor was self-closing, so the note may refer to a child of the container."""
    prefix: str
    """What precedes the marker so that it sits on its own line: a newline when the container's
    start tag does not end its line, else the next line's indentation (D746 ruling 8)."""
    suffix: str = "\n"


@dataclass(frozen=True, slots=True)
class ParseError:
    """A parse failure as a value: `path:line:col` and the parser's own message."""

    at: str
    msg: str


class CarrierParseError(ValueError):
    """Ruling 2: a file the carrier will not parse, carrying the `ParseError` order 0 records."""

    def __init__(self, error: ParseError) -> None:
        super().__init__(f"{error.at}: {error.msg}")
        self.error = error


# ---------------------------------------------------------------------------
# The selector grammar (09 section 3.1)
# ---------------------------------------------------------------------------

_ELEMENT: Final = re.compile(
    r"(?P<ns>[A-Za-z]+)\|(?P<local>[A-Za-z0-9-]+)(?:\[(?P<qualifier>[A-Za-z_][A-Za-z0-9_:-]*)\])?"
)
_ATTRIBUTE: Final = re.compile(r"@(?P<name>[A-Za-z_][A-Za-z0-9_:-]*)")
_SUBPROPERTY: Final = re.compile(
    r"@(?P<name>[A-Za-z_][A-Za-z0-9_:-]*)\|(?P<prop>[A-Za-z][A-Za-z0-9-]*)"
)


@dataclass(frozen=True, slots=True)
class Selector:
    """One parsed selector: exactly one of the three productions."""

    kind: Literal["element", "attribute", "subproperty"]
    tag: str = ""
    """`svg|text` for the element form."""
    name: str = ""
    """The qualifier for the element form, the attribute for the other two."""
    prop: str = ""
    """The CSS property for the subproperty form, lower-cased."""

    def matches(self, node: CarrierNode) -> bool:
        """09 section 3.1's table: every form yields the element."""
        if self.kind == "element":
            return node.tag == self.tag and (not self.name or node.attr(self.name) is not None)
        value = node.attr(self.name)
        if value is None:
            return False
        if self.kind == "attribute":
            return True
        return any(prop == self.prop for prop, _ in style_declarations(value))


def parse_selector(selector: str, ns: str) -> Selector:
    """The one parser for `select()`, a row's `selector` and its `forbidden_when` (ruling 5)."""
    return _parse(selector, ns)


@lru_cache(maxsize=512)
def _parse(selector: str, ns: str) -> Selector:
    if (m := _SUBPROPERTY.fullmatch(selector)) is not None:
        if m["name"] != "style":
            _invalid(selector, len(m["name"]) + 1, "only @style has sub-properties")
        return Selector("subproperty", name="style", prop=m["prop"].lower())
    if (m := _ATTRIBUTE.fullmatch(selector)) is not None:
        return Selector("attribute", name=m["name"])
    if (m := _ELEMENT.fullmatch(selector)) is not None:
        if m["ns"] != ns:
            _invalid(selector, 0, f"the prefix is the carrier's own, {ns}|")
        return Selector("element", tag=f"{ns}|{m['local']}", name=m["qualifier"] or "")
    _invalid(selector, _stop(selector), "not one of ns|local[attr], @attr, @style|prop")
    raise AssertionError  # unreachable: _invalid raises


def _stop(selector: str) -> int:
    """The offset at which the longest grammatical prefix stops: where the reader should look."""
    for pattern in (_SUBPROPERTY, _ELEMENT, _ATTRIBUTE):
        m = pattern.match(selector)
        if m is not None:
            return m.end()
    return 0


def _invalid(selector: str, offset: int, why: str) -> None:
    raise TargetError(
        f"selector {selector!r} is invalid at offset {offset}: {why}",
        symbol="OW_TARGET_SELECTOR_INVALID",
        fix=_SELECTOR_FIX,
    )


def style_declarations(value: str) -> tuple[tuple[str, str], ...]:
    """An inline `style` as `(property, value)` pairs, in order. Property names lower-cased.

    `;` separates declarations except inside quotes or parentheses (`url(a;b)`), and a
    declaration without a `:` declares nothing.
    """
    out: list[tuple[str, str]] = []
    for part in _split(value):
        prop, colon, rest = part.partition(":")
        if colon and prop.strip():
            out.append((prop.strip().lower(), rest.strip()))
    return tuple(out)


def _split(value: str) -> Iterator[str]:
    depth = 0
    quote = ""
    start = 0
    for i, c in enumerate(value):
        if quote:
            quote = "" if c == quote else quote
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth = max(depth - 1, 0)
        elif c == ";" and depth == 0:
            yield value[start:i]
            start = i + 1
    yield value[start:]


# ---------------------------------------------------------------------------
# The transactional splice (OUT17)
# ---------------------------------------------------------------------------


def apply_splices(
    source: str, edits: Sequence[Splice], reparse: Callable[[str], object]
) -> str | ParseError:
    """Ruling 6, then back to front, then `reparse` strictly. The carriers' one `splice()`."""
    data = source.encode("utf-8")
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for a, b in pairwise(ordered):
        if b.start < a.end or b.start == a.start:
            raise ValueError(f"splices [{a.start}, {a.end}) and [{b.start}, {b.end}) overlap")
    for edit in ordered:
        if edit.end > len(data) or not (_boundary(data, edit.start) and _boundary(data, edit.end)):
            raise ValueError(f"splice [{edit.start}, {edit.end}) is not on a character boundary")
    for edit in reversed(ordered):
        data = data[: edit.start] + edit.text.encode("utf-8") + data[edit.end :]
    text = data.decode("utf-8")
    try:
        reparse(text)
    except CarrierParseError as exc:
        return exc.error
    return text


def _boundary(data: bytes, offset: int) -> bool:
    """`offset` starts a UTF-8 sequence, or is the end: never a continuation byte."""
    return offset == len(data) or (
        0 <= offset < len(data) and data[offset] & _LEAD_MASK != _CONTINUATION
    )
