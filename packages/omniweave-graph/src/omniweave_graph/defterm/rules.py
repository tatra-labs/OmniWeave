"""`derive.anchor.defterm`'s algorithm: a Segment's members in, its definition sites out. **D666.**

Pure: no I/O, no clock, no store. `driver.py` decodes the view and encodes the answer as
`owgraph-items/1`; the rules are here so they can be tested without a wire.

06-structure-extraction.md section 3.5 is the specification: four patterns over one block's `text`
with the term as a capture group, plus one structural rule, at most `DEFTERM_MAX_PER_BLOCK = 16`
matches per block and 512 characters of trailing context per match.

| rule          | shape                                                   | aliases           |
|---------------|---------------------------------------------------------|-------------------|
| copular       | `"Indemnified Party" means any Person entitled to ...`  | canonical         |
| parenthetical | `International Business Machines Corporation ("IBM")`   | expansion, abbrev |
| hereinafter   | `Acme Holdings Ltd. (hereinafter, the "Company")`       | variant, abbrev   |
| glossary      | a list item or two-column table row under `Definitions` | canonical         |

## The readings this module takes where the plan is silent

1. **A quoted term is in double quotes, straight or curly, or in curly single quotes**, and is 1 to
   `DEFTERM_MAX_TERM_CHARS = 80` characters on one line. Straight single quotes are not quotes
   here: they are apostrophes far more often than they open a defined term.
2. **"Within three tokens" counts whitespace-separated words** between the closing quote and the
   verb; punctuation attached to the quote (`"IBM") means`) is not a word, and a `.`, `;` or `:`
   between them ends the sentence and the match (`"Agreement". It means`). The verbs are 06's four
   -- `means`, `shall mean`, `refers to`, `is defined as` -- plus `has`/`have`/`shall have the
   meaning(s)`, the by-reference form (`"Closing" shall have the meaning set forth in Section 2.1`)
   that contracts use for most terms defined elsewhere. Matched case-insensitively.
3. **The trailing context is the definition.** The up to 512 characters after the verb, stripped,
   become the entity's `description`; the copular and glossary rules have one, the two
   parenthetical rules do not.
4. **A capitalised run** is read backwards from the parenthesis: tokens whose first character is
   upper case (or a digit, in a token holding an upper-case letter: `3M`), joined by the
   connectors `of`, `and`, `&`, `for`, `the`, `de`, `du`, `la`, `van`, `von`, `der`, never starting
   or ending with one, at most `DEFTERM_MAX_RUN_TOKENS = 8` tokens. A token ending `;`, `:`, `!` or
   `?`, or a period after more than four letters, is the end of a sentence and stops the run --
   `Ltd.`, `Inc.` and `U.S.` do not. The parenthetical rule needs two capitalised tokens, as 06
   says; `(the "Company")` is the same rule, because a contract writes it that way far more often
   than without the article. The hereinafter rule needs none: `hereinafter` is the definition
   signal on its own, and the variant alias is minted only when a run is there.
5. **A glossary heading is the Segment's nearest heading** (`heading_path[-1]`), with a leading
   enumerator dropped (`1.`, `Article 1`, `Section 1.1`, `I.`, `(a)`), whose first word is
   `definitions`, `definition` or `glossary`, or whose first two are `defined terms`. Only the
   nearest: a list under `1.2 Interpretation` inside `Article 1 Definitions` is not a glossary.
   A row is a `list_item` whose text opens with the term and a separator (`:`, a spaced dash, a
   tab, or the copular verb), or a `table_cell` in column 0 below the header rows of a table the
   host says is two columns wide; the definition is the text after the separator, or the row's
   column-1 cell when it is a member.
6. **One definition per term per block.** When two rules find one term in one block (`"IBM")
   means` is both copular and parenthetical) they are one definition, with their aliases unioned.
   Two blocks defining one term are two definitions: the sink quarantines the second anchor with
   both surfaces, because the document is ambiguous (06:115-118) and it is not this Pass's to pick.
7. **A term whose `normalize_key` form is shorter than three characters is not minted** (06:1136).
   `key_form` is `omniweave_core.ident.normalize_key` re-stated, because this package may not import
   core; `tests/unit/test_defterm_rules.py` holds the two equal.
8. **The per-block bound counts definitions, not regex hits.** At most 16 per block, in reading
   order; past that the rest are refused with `Diag(OW_RESOURCE_LIMIT,
   {limit: "DEFTERM_MAX_PER_BLOCK"})` naming how many there were.
9. **Blocks of a kind that carries no prose are not read**: `code`, `formula`, `toc`,
   `toc_entry`, `page_header`, `page_footer`. A `heading` is read: `1.1 "Affiliate" means ...`
   is a heading in some parses.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_graph.view import Member

__all__ = [
    "DEFTERM_CONTEXT_CHARS",
    "DEFTERM_MAX_PER_BLOCK",
    "DEFTERM_MAX_RUN_TOKENS",
    "DEFTERM_MAX_TERM_CHARS",
    "DEFTERM_MIN_KEY_CHARS",
    "Alias",
    "Definition",
    "Found",
    "Notice",
    "find",
    "is_glossary_heading",
    "key_form",
]

DEFTERM_MAX_PER_BLOCK: Final = 16
"""06:1114: at most 16 definitions per block, so a block of quoted fragments costs O(length)."""
DEFTERM_CONTEXT_CHARS: Final = 512
"""06:1115: at most 512 characters of trailing context per match (reading 3)."""
DEFTERM_MIN_KEY_CHARS: Final = 3
"""06:1136: a candidate whose `normalize_key` form is shorter is rejected at mint time."""
DEFTERM_MAX_TERM_CHARS: Final = 80
"""Reading 1: a quoted span longer than this is a quotation, not a term."""
DEFTERM_MAX_RUN_TOKENS: Final = 8
"""06:1121: "a capitalised run of 2-8 tokens"."""

_COMPONENT: Final = "derive.anchor.defterm"
_RESOURCE_LIMIT: Final = "OW_RESOURCE_LIMIT"
_SKIP_KINDS: Final = frozenset(
    {"code", "formula", "toc", "toc_entry", "page_header", "page_footer"}
)
_CONNECTORS: Final = frozenset(
    {"of", "and", "&", "for", "the", "de", "du", "la", "van", "von", "der"}
)
_RUN_WINDOW: Final = 400
_ABBREVIATION_LETTERS: Final = 4
"""Reading 4: `Ltd.` and `U.S.` end in a period without ending a sentence; `Agreement.` does."""
_GLOSSARY_COLS: Final = 2
_KEY_FIXPOINT_STEPS: Final = 6

_QUOTED: Final = (
    r'(?:"(?P<q1>[^"\n]{1,80})"|\u201c(?P<q2>[^\u201d\n]{1,80})\u201d'
    r"|\u2018(?P<q3>[^\u2019\n]{1,80})\u2019)"
)
_WORD: Final = r'[^\s"\u201c\u201d\u2018\u2019.;:]+'
_VERB: Final = (
    r"(?P<verb>(?i:shall\s+mean|means|refers\s+to|is\s+defined\s+as"
    r"|(?:shall\s+)?ha(?:s|ve)\s+the\s+meanings?)\b)"
)
_COPULAR: Final = re.compile(_QUOTED + rf"(?:{_WORD})?(?:\s+{_WORD}){{0,3}}?\s+" + _VERB)
_PARENTHETICAL: Final = re.compile(r"\(\s*(?i:the\s+)?" + _QUOTED + r"\s*\)")
_HEREINAFTER: Final = re.compile(
    r"\(\s*(?i:hereinafter(?:\s+(?:referred\s+to\s+as|called))?)\s*,?\s*(?i:the\s+)?"
    + _QUOTED
    + r"\s*\)"
)
_GLOSSARY_ROW: Final = re.compile(
    r"\s*(?P<term>[^\s:\t][^:\t\n]{0,79}?)"
    r"(?:\s*:|\s+[-\u2013\u2014]\s|\t|\s+(?=(?i:shall\s+mean|means)\b))"
)
_ENUMERATOR: Final = re.compile(
    r"\s*(?:(?:article|section|part|chapter|schedule|clause)\s+"
    r"(?:[0-9]+(?:\.[0-9]+)*|[ivxlcdm]+|[a-z])[.):]?"
    r"|\(?(?:[0-9]+(?:\.[0-9]+)*[.)]?|(?:[ivxlcdm]+|[a-z])[.)]))\s+",
    re.IGNORECASE,
)
_ITEM_MARK: Final = re.compile(r"\s*(?:[-*•]|\(?[0-9a-z]{1,3}[.)])\s+")
_QUOTE_CHARS: Final = '"\u201c\u201d\u2018\u2019*'
_KEY_NON_WORD: Final = re.compile(r"[^\w]+", re.UNICODE)
_KEY_UNDERSCORE_RUN: Final = re.compile(r"_+")


@dataclass(frozen=True, slots=True)
class Alias:
    surface: str
    alias_kind: str
    """`canonical`, `variant`, `abbrev` or `expansion` -- the four 06:1119-1124 mints."""


@dataclass(frozen=True, slots=True)
class Definition:
    """One definition site: a `defined_term` anchor, its entity and its aliases."""

    cite: str
    span: tuple[int, int]
    """The term in `block.text`, half-open, in characters: a `TextSpan`."""
    term: str
    rule: str
    aliases: tuple[Alias, ...]
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Notice:
    """A Diag this Pass owes the operator: a disclosed refusal, never a silent one."""

    code: str
    message: str
    cite: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Found:
    definitions: tuple[Definition, ...]
    notices: tuple[Notice, ...]


def key_form(s: str) -> str:
    """`omniweave_core.ident.normalize_key`, re-stated (reading 7)."""
    cur = s
    for _ in range(_KEY_FIXPOINT_STEPS):
        nxt = unicodedata.normalize("NFKC", cur.casefold())
        if nxt == cur:
            break
        cur = nxt
    cur = _KEY_NON_WORD.sub("_", cur)
    return _KEY_UNDERSCORE_RUN.sub("_", cur).strip("_")


def is_glossary_heading(heading: str) -> bool:
    """Reading 5: `Definitions`, `1. Definitions and Interpretation`, `Glossary of Terms`."""
    rest = heading
    lead = _ENUMERATOR.match(heading)
    if lead is not None:
        rest = heading[lead.end() :]
    words = re.findall(r"\w+", rest.casefold())
    return bool(words) and (
        words[0] in {"definitions", "definition", "glossary"} or words[:2] == ["defined", "terms"]
    )


def find(members: Sequence[Member], heading_path: Sequence[str]) -> Found:
    """Every definition site in one Segment, in reading order, and the Diags owed."""
    glossary = bool(heading_path) and is_glossary_heading(heading_path[-1])
    definitions: list[Definition] = []
    notices: list[Notice] = []
    for member in members:
        if member.text is None or member.kind in _SKIP_KINDS:
            continue
        found = _merged(_candidates(member, members, glossary=glossary))
        if len(found) > DEFTERM_MAX_PER_BLOCK:
            notices.append(
                Notice(
                    code=_RESOURCE_LIMIT,
                    message=(
                        f"{len(found)} definitions in one block; the first "
                        f"{DEFTERM_MAX_PER_BLOCK} are kept"
                    ),
                    cite=member.cite,
                    detail={
                        "limit": "DEFTERM_MAX_PER_BLOCK",
                        "value": DEFTERM_MAX_PER_BLOCK,
                        "found": len(found),
                    },
                )
            )
        definitions += found[:DEFTERM_MAX_PER_BLOCK]
    return Found(definitions=tuple(definitions), notices=tuple(notices))


def _candidates(
    member: Member, members: Sequence[Member], *, glossary: bool
) -> Iterator[Definition]:
    text = member.text or ""
    yield from _copular(member.cite, text)
    yield from _parenthetical(member.cite, text)
    yield from _hereinafter(member.cite, text)
    if glossary:
        yield from _glossary(member, members)


def _merged(candidates: Iterator[Definition]) -> list[Definition]:
    """Reading 6 and 7: one definition per key per block, and none under three key characters."""
    by_key: dict[str, Definition] = {}
    for found in candidates:
        key = key_form(found.term)
        if len(key) < DEFTERM_MIN_KEY_CHARS:
            continue
        first = by_key.get(key)
        if first is None:
            by_key[key] = found
            continue
        extra = tuple(a for a in found.aliases if a not in first.aliases)
        by_key[key] = Definition(
            cite=first.cite,
            span=first.span,
            term=first.term,
            rule=first.rule,
            aliases=first.aliases + extra,
            description=first.description or found.description,
        )
    return sorted(by_key.values(), key=lambda d: d.span)


def _term(match: re.Match[str]) -> tuple[str, tuple[int, int]]:
    for group in ("q1", "q2", "q3"):
        if match.group(group) is not None:
            return match.group(group), match.span(group)
    raise AssertionError("a quoted match with no quoted group")  # pragma: no cover


def _trailing(text: str, start: int) -> str | None:
    while start < len(text) and text[start].isspace():
        start += 1
    tail = text[start : start + DEFTERM_CONTEXT_CHARS].rstrip()
    return tail or None


def _copular(cite: str, text: str) -> Iterator[Definition]:
    for match in _COPULAR.finditer(text):
        term, span = _term(match)
        yield Definition(
            cite=cite,
            span=span,
            term=term,
            rule="copular",
            aliases=(Alias(term, "canonical"),),
            description=_trailing(text, match.end("verb")),
        )


def _parenthetical(cite: str, text: str) -> Iterator[Definition]:
    for match in _PARENTHETICAL.finditer(text):
        term, span = _term(match)
        run = _run_before(text, match.start(), need=2)
        if run is None:
            continue
        yield Definition(
            cite=cite,
            span=span,
            term=term,
            rule="parenthetical",
            aliases=(Alias(run, "expansion"), Alias(term, "abbrev")),
        )


def _hereinafter(cite: str, text: str) -> Iterator[Definition]:
    for match in _HEREINAFTER.finditer(text):
        term, span = _term(match)
        run = _run_before(text, match.start(), need=1)
        aliases = (
            (Alias(term, "abbrev"),)
            if run is None
            else (
                Alias(run, "variant"),
                Alias(term, "abbrev"),
            )
        )
        yield Definition(cite=cite, span=span, term=term, rule="hereinafter", aliases=aliases)


def _run_before(text: str, end: int, *, need: int) -> str | None:
    """Reading 4: the capitalised run ending just before `end`, or `None` if it is too short."""
    low = max(0, end - _RUN_WINDOW)
    tokens = [(m.start() + low, m.end() + low) for m in re.finditer(r"\S+", text[low:end])]
    if low > 0 and tokens and tokens[0][0] == low:
        tokens = tokens[1:]
    run: list[tuple[int, int]] = []
    for position, (a, b) in enumerate(reversed(tokens)):
        word = text[a:b]
        if position > 0 and _ends_sentence(word):
            break
        if not (_capitalised(word) or (word.casefold() in _CONNECTORS and run)):
            break
        run.append((a, b))
        if len(run) == DEFTERM_MAX_RUN_TOKENS:
            break
    while run and not _capitalised(text[run[-1][0] : run[-1][1]]):
        run.pop()
    if sum(1 for a, b in run if _capitalised(text[a:b])) < need:
        return None
    surface = text[run[-1][0] : run[0][1]].rstrip(",")
    return surface or None


def _capitalised(word: str) -> bool:
    first = word[0]
    return first.isupper() or (first.isdigit() and any(ch.isupper() for ch in word))


def _ends_sentence(word: str) -> bool:
    if word[-1] in ";:!?":
        return True
    if word[-1] != ".":
        return False
    return sum(1 for ch in word if ch.isalpha()) > _ABBREVIATION_LETTERS


def _glossary(member: Member, members: Sequence[Member]) -> Iterator[Definition]:
    text = member.text or ""
    if member.kind == "list_item":
        mark = _ITEM_MARK.match(text)
        match = _GLOSSARY_ROW.match(text, 0 if mark is None else mark.end())
        if match is None:
            return
        found = _glossary_term(text, *match.span("term"))
        if found is not None:
            yield _glossary_definition(member.cite, text, found, _trailing(text, match.end()))
        return
    cell = member.table
    if cell is None:  # a paragraph IN a cell carries the cell's position (06:1316, D681)
        return
    if cell.n_cols != _GLOSSARY_COLS or cell.c != 0 or cell.r < cell.header_rows:
        return
    found = _glossary_term(text, 0, len(text))
    if found is None:
        return
    definition = next(
        (
            m.text.strip()[:DEFTERM_CONTEXT_CHARS] or None
            for m in members
            if m.table is not None
            and m.text is not None
            and m.table.table_cite == cell.table_cite
            and m.table.r == cell.r
            and m.table.c == 1
        ),
        None,
    )
    yield _glossary_definition(member.cite, text, found, definition)


def _glossary_term(text: str, a: int, b: int) -> tuple[int, int] | None:
    """Trim whitespace and quote or bold markers; refuse a head that is not a term."""
    while a < b and (text[a].isspace() or text[a] in _QUOTE_CHARS):
        a += 1
    while b > a and (text[b - 1].isspace() or text[b - 1] in _QUOTE_CHARS):
        b -= 1
    head = text[a:b]
    if not head or len(head) > DEFTERM_MAX_TERM_CHARS or len(head.split()) > DEFTERM_MAX_RUN_TOKENS:
        return None
    if any(ch in head for ch in ";!?\n"):
        return None
    return a, b


def _glossary_definition(
    cite: str, text: str, span: tuple[int, int], description: str | None
) -> Definition:
    term = text[span[0] : span[1]]
    return Definition(
        cite=cite,
        span=span,
        term=term,
        rule="glossary",
        aliases=(Alias(term, "canonical"),),
        description=description,
    )
