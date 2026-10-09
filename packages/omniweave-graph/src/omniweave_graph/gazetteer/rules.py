"""`derive.entity.gazetteer`'s rules: the corpus's own names, found again in its text. **D683.**

06-structure-extraction.md section 3.7 is the specification. `op.lexicon` reads the store's
corpus-scoped aliases into an artefact (`owgraph-lexicon/1`, below); this Pass builds an
Aho-Corasick automaton over it and reports each occurrence of a name as a mention of the entity
that carries it -- *"a surface match is evidence of an occurrence, not of a new thing"*.

## Rulings the plan leaves to the Pass (the ledger's D683)

1. **The automaton runs over word tokens, not characters.** A lexicon name is a `name_norm`, which
   is `normalize_key(surface)`: casefolded, NFKC'd, every run of non-word characters one `_`. A
   member's text is cut into word runs (`[^\\W_]+`), each run put through the same fold
   (`key_form`), and the automaton's alphabet is those folded runs. So `Acme Holdings, Ltd.` meets
   `acme_holdings_ltd`, a match can only start and end on a word boundary -- `acme` never fires
   inside `macme` -- and the goto table is a `dict` of `dict`s keyed by token, 06:1206's shape.
2. **A hit is reported as a span, not a quote.** 06:1215 has the Pass emit the matched surface as a
   `quote` because a character automaton's offsets are in normalised space. These offsets are not:
   every token keeps the `block.text` span it was cut from, so the span is exact, and a quote would
   be grounded at its FIRST occurrence -- two hits on one name in one block would both land on the
   first.
3. **Longest match wins, leftmost first.** Matches are taken in order of start, longest first, and
   a match overlapping one already taken is dropped: `Acme Holdings Ltd` is one hit, not three.
4. **One name, several entities: a mention each, and a diagnostic.** Two corpus entities may carry
   one alias (an `org` and a `product` both called `Atlas`). The hit is evidence for both, so both
   get a mention, and `OW_GRAPH_QUOTE_AMBIGUOUS` records that the surface did not decide.

Standard library only; `key_form` is `omniweave_core.ident.normalize_key` re-stated, as defterm's.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_graph.defterm.rules import key_form

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = [
    "LEXICON_FORMAT",
    "Automaton",
    "Hit",
    "Lexicon",
    "Target",
    "Token",
    "decode_lexicon",
    "find",
    "tokens",
]

LEXICON_FORMAT: Final = "owgraph-lexicon/1"
"""The artefact `op.lexicon` writes (`omniweave_core.store.lexicon`): a header, then one `name`
line per lexicon name in `name` order, each listing the entities that carry it."""

_WORD: Final = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class Target:
    """An entity a lexicon name points at: what the Pass proposes again to bind to it (06:628)."""

    etype: str
    key: str
    title: str


@dataclass(frozen=True, slots=True)
class Lexicon:
    names: Mapping[str, tuple[Target, ...]]
    """`name_norm` -> the corpus entities carrying it, in the artefact's order."""


@dataclass(frozen=True, slots=True)
class Token:
    """One folded word of a member's text, and the `block.text` span it was cut from."""

    key: str
    a: int
    b: int


@dataclass(frozen=True, slots=True)
class Hit:
    """One occurrence: the name, its span in `block.text`, and the surface there."""

    name: str
    a: int
    b: int
    surface: str


def decode_lexicon(raw: bytes) -> Lexicon:
    """`owgraph-lexicon/1`, decoded. A malformed artefact raises `ValueError` naming the line."""
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise ValueError("the lexicon is empty: not even a header")
    head = json.loads(lines[0])
    if not isinstance(head, dict) or head.get("t") != "lexicon":
        raise ValueError("line 1 is not a lexicon header")
    if head.get("format") != LEXICON_FORMAT:
        raise ValueError(f"line 1 names format {head.get('format')!r}, not {LEXICON_FORMAT}")
    names: dict[str, tuple[Target, ...]] = {}
    for number, line in enumerate(lines[1:], start=2):
        frame = json.loads(line)
        if not isinstance(frame, dict) or frame.get("t") != "name":
            raise ValueError(f"line {number} is not a name frame")
        name, found = frame.get("name"), frame.get("entities")
        if not isinstance(name, str) or not name:
            raise ValueError(f"line {number} is not a name frame")
        if not isinstance(found, list) or not found:
            raise ValueError(f"line {number}: {name!r} names no entity")
        names[name] = tuple(_target(number, one) for one in found)
    if head.get("names") != len(names):
        raise ValueError(f"the header counts {head.get('names')!r} names and {len(names)} follow")
    return Lexicon(names=names)


def _target(number: int, raw: object) -> Target:
    if not isinstance(raw, dict) or not all(
        isinstance(raw.get(k), str) and raw.get(k) for k in ("etype", "key", "title")
    ):
        raise ValueError(f"line {number}: an entity needs etype, key and title")
    return Target(etype=raw["etype"], key=raw["key"], title=raw["title"])


def tokens(text: str) -> tuple[Token, ...]:
    """Ruling 1: the folded word runs of `text`, each with the span it came from.

    A run whose fold has an inner `_` (NFKC can introduce punctuation: `½` folds to `1_2`) yields
    one token per piece, every piece carrying the whole run's span -- a name cannot match half a
    run.
    """
    out: list[Token] = []
    for match in _WORD.finditer(text):
        for piece in key_form(match.group()).split("_"):
            if piece:
                out.append(Token(key=piece, a=match.start(), b=match.end()))
    return tuple(out)


class Automaton:
    """Aho-Corasick over token sequences: a goto table of `dict`s, failure links, output links."""

    __slots__ = ("_dictionary", "_fail", "_goto", "_out")

    def __init__(self, names: Sequence[str]) -> None:
        self._goto: list[dict[str, int]] = [{}]
        self._out: list[tuple[str, int] | None] = [None]
        for name in names:
            pieces = [p for p in name.split("_") if p]
            if not pieces:
                continue
            node = 0
            for piece in pieces:
                nxt = self._goto[node].get(piece)
                if nxt is None:
                    nxt = len(self._goto)
                    self._goto[node][piece] = nxt
                    self._goto.append({})
                    self._out.append(None)
                node = nxt
            self._out[node] = (name, len(pieces))
        self._fail = [0] * len(self._goto)
        self._dictionary = [-1] * len(self._goto)
        self._link()

    def _link(self) -> None:
        dictionary = self._dictionary
        queue: deque[int] = deque(self._goto[0].values())
        while queue:
            node = queue.popleft()
            for piece, child in self._goto[node].items():
                queue.append(child)
                back = self._fail[node]
                while back and piece not in self._goto[back]:
                    back = self._fail[back]
                target = self._goto[back].get(piece, 0)
                self._fail[child] = target if target != child else 0
                fail = self._fail[child]
                dictionary[child] = fail if self._out[fail] is not None else dictionary[fail]

    def matches(self, keys: Sequence[str]) -> Iterator[tuple[int, int, str]]:
        """Every `(first, last, name)` -- token indices, inclusive -- in end order."""
        node = 0
        for index, key in enumerate(keys):
            while node and key not in self._goto[node]:
                node = self._fail[node]
            node = self._goto[node].get(key, 0)
            hit = node if self._out[node] is not None else self._dictionary[node]
            while hit > 0:
                found = self._out[hit]
                if found is not None:
                    name, length = found
                    yield (index - length + 1, index, name)
                hit = self._dictionary[hit]

    @property
    def nodes(self) -> int:
        return len(self._goto)


def find(text: str, automaton: Automaton) -> tuple[Hit, ...]:
    """Ruling 3: the leftmost-longest, non-overlapping hits of the automaton's names in `text`."""
    found = tokens(text)
    if not found:
        return ()
    ranked = sorted(automaton.matches([t.key for t in found]), key=lambda m: (m[0], m[0] - m[1]))
    out: list[Hit] = []
    after = -1
    for first, last, name in ranked:
        a, b = found[first].a, found[last].b
        if first <= after or (out and a < out[-1].b):
            continue
        if (first and found[first - 1].a == a) or (
            last + 1 < len(found) and found[last + 1].b == b
        ):
            continue  # half a run (ruling 1)
        out.append(Hit(name=name, a=a, b=b, surface=text[a:b]))
        after = last
    return tuple(out)
