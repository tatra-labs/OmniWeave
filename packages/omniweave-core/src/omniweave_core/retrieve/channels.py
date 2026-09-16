"""The query sanitiser, and the `identity` ladder's grades. Phase 2, before the snapshot.

07:1308 states the shape of this file in one sentence: *"Query sanitisation is a **semantic
transform, not escaping**"*. Escaping asks what FTS5 will choke on; a semantic transform asks what
the user meant, and the two differ on every row of 07:1310's table -- a lifted `§4.2(b)` is not an
escaped `§4.2(b)`, it is a different Channel's input.

`plan()` is pure and memoised on query SHAPE, so nothing here may run inside it: the sanitiser reads
the query TEXT, which 07:1543 keeps out of the memo key on purpose. It runs in phase 2, beside the
query embedding, *"BEFORE the snapshot opened"* (07:1925) -- and its output is the `ChannelInput`
that `retrieve()` binds onto each `ChannelSpec` with `dataclasses.replace`.

## The seven transforms, and the one that is not a transform at all

07:1310's table, in the order it prints them:

| input | transform | why |
|---|---|---|
| `§ ¶ † ‡ · —` | to space | *"`unicode61` drops them anyway; keeping them creates empty tokens"* |
| soft hyphen, `-\\n` | folded | *"a line-broken word must match its unbroken form"* |
| `" * ( ) : ^ -`, bare `AND OR NOT NEAR` | stripped | *"a user cannot inject FTS5 syntax"* |
| `§4.2(b)`, `Fig. 3a`, `GL-4471`, `d7#412` | **lifted out** | *"they belong to `exact`"* |
| CJK runs | bigrammed | 07:1320, *"`unicode61` does not segment CJK"* |
| unknown `foo:bar` | plain text | 07:1321, *"so `TODO:` returns results"* |

The lift is the row that is not a transform: it MOVES material to another Channel, and which Channel
depends on the shape. D239 is that the plan's own four examples do not all go to the same place --
`d7#412` is a cite and the `exact` Channel it is sent to joins `anchor` and `ref_site` on
`(name_norm, akind)`, which a cite has neither of. `Sanitized` therefore carries `refs` and `idents`
separately and the lift decides between them.

## The ladder's grades are ordinals with gaps, and the gaps are the argument

07:1259's `IDENTITY_LADDER` is nine named grades, and 07:1263 makes one of them a freeze item:
*"The **40 tier** is the first thing a "simplification" deletes and it must not be."* Collapsing 40
into 50 *"lets a punctuation-different match tie a literal one and fall through to BM25 -- measured
in the source system as a test fixture outranking the symbol it tests by 0.355 of ~58."*

45 is casefold only; 40 is NFKC plus punctuation plus separators, which is `normalize_key`'s fold
exactly. So the two tiers are two normalisers over one comparison, and "Table 3.2 (revised)" ties
"Table 3.2" at 40 while losing to it at 45 -- which is the whole distinction.

**The reported grade is the one actually measured** (07:1255), never the tier that was asked for.
`ChannelResult.grades` carries it per block.

Specified in 07-store-and-retrieval.md section 5.2; scheduled by 16-roadmap.md:658.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import UsageError
from omniweave_core.ident import normalize_key
from omniweave_core.limits import MAX_QUERY_CHARS, MAX_QUERY_REFS, MAX_QUERY_TERMS

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DSL_FIELDS",
    "FTS_OPERATORS",
    "FTS_SYNTAX",
    "IDENTITY_LADDER",
    "SPINE_DECAY",
    "TO_SPACE",
    "W_BODY",
    "W_HEAD",
    "Sanitized",
    "bigrams",
    "sanitize",
]

IDENTITY_LADDER: Final[Mapping[str, int]] = MappingProxyType(
    {
        "cite_exact": 50,
        "addr_exact": 50,
        "doc_uri_exact": 50,
        "doc_key_prefix": 48,
        "title_exact": 45,
        "title_normalised": 40,
        "title_prefix": 30,
        "spine_segment": 20,
        "none": 0,
    }
)
"""07:1259, verbatim, including the two comments it carries: `title_exact` is *"casefold only"* and
`title_normalised` *"needed MORE than case: NFKC, punctuation, separators"*.

Three names share the grade 50 and that is not a redundancy: a cite, an addr and a document URI are
three different lookups and `grades` reports which one measured, so an operator reading a Verdict
can tell a durable `cite` hit from a positional `addr` hit. 16:669 freezes the tiers
*"including the 40 tier, which is the first thing a well-meaning simplification deletes"*."""

W_BODY: Final[float] = 1.0
W_HEAD: Final[float] = 6.0
SPINE_DECAY: Final[float] = 0.6
"""07:1294's three, and 07:1293 says what they discharge: *"the one place 'D5 owns the BM25
weights' is discharged."* They are homed here rather than in the lexical Channel's SQL because
`lex(b)` is a scorer over two FTS tables and a spine walk, and the three numbers are the whole of
what a reviewer has to argue with. The scorer itself is W6.2b."""

TO_SPACE: Final[str] = "§¶†‡·—"
"""`§ ¶ † ‡ · —`. 07:1316: *"`unicode61` drops them anyway; keeping them creates empty tokens"*."""

FTS_SYNTAX: Final[str] = '"*():^-'
"""07:1318's set, stripped so *"a user cannot inject FTS5 syntax"*. The hyphen is in it and the
soft-hyphen fold above runs first, so a line-broken word is rejoined before the strip sees it."""

FTS_OPERATORS: Final[frozenset[str]] = frozenset({"AND", "OR", "NOT", "NEAR"})
"""Bare, and therefore case-sensitive: FTS5 reads only the upper-case forms as operators, so `and`
in a sentence is a term and `AND` is syntax. Stripping both would delete a word the user typed."""

DSL_FIELDS: Final[tuple[str, ...]] = (
    "kind",
    "page",
    "doc",
    "layer",
    "trust",
    "quote",
    "sec",
    "lang",
)
"""07:1319's eight, in its order. *"each validated against its enum; an invalid value is a usage
error naming the legal set, never a silent drop."*

Validation is the CALLER's: this module reports which field carried which value and
`retrieve()` maps them onto `Filters`, whose fields are typed against the enums. Splitting it that
way keeps one home for "what is a legal `Kind`" -- `omniweave_core.model.enums` -- rather than a
second copy of eight vocabularies here.

`lang:` is in the list and cannot be satisfied: `store/reader.py`'s DEFECT 1 records that
`Filters.lang` names no shipped column and that `narrow()` refuses a non-`None` value rather than
widening the query silently. So the field parses here and refuses there, which is the same answer
arriving one layer later."""

_CITE: Final[re.Pattern[str]] = re.compile(r"^d(?P<doc>\d+)#(?P<n>\d+)$")
"""`block.cite`, 0001_init.sql:241 -- `'d7#412'`, for prompts only (INV-8). The `doc_ord` is inside
the string, which matters: `CREATE UNIQUE INDEX block_cite ON block(doc_ord, cite)` is two columns,
so a lookup that cannot supply `doc_ord` is a scan of the whole corpus. D240."""

_ADDR: Final[re.Pattern[str]] = re.compile(r"^p\d+(?:/[\dA-Za-z]+)*$")
"""`block.addr`, 0001_init.sql:240 -- `'doc' | 'p14/3' | 'p14/3/r2c5'`.

The bare `'doc'` form is deliberately NOT matched. It is the document root block's addr and it is
also an ordinary English word, so lifting it would take `doc` out of every query that used it as a
noun; a caller who means the root block spells it `addr:doc` through a field the DSL does not
have. Reported with D241 rather than worked around, because the ladder's tier 50 is the place a
document-level identity is supposed to resolve."""

_URI: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9+.-]*://|^[a-z]:[\\/]|^/")
"""A document URI, loosely: a scheme, a Windows drive, or an absolute path. Loose on purpose -- the
tier-50 lookup is an equality against `doc.uri` and a false candidate costs one index probe."""

_REF_SHAPES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"§+\s*\d[\d.]*(?:\([a-z0-9]+\))*"), "clause"),
    (re.compile(r"\b(?:fig|figure)\.?\s*\d[\dA-Za-z.-]*", re.IGNORECASE), "figure"),
    (re.compile(r"\b(?:tab|table)\.?\s*\d[\dA-Za-z.-]*", re.IGNORECASE), "table"),
    (re.compile(r"\b(?:eq|equation)\.?\s*\d[\dA-Za-z.-]*", re.IGNORECASE), "equation"),
    (re.compile(r"\b[A-Z]{2,}-\d+\b"), "identifier"),
    (re.compile(r"\[[^\]\s]+\]"), "citekey"),
)
r"""07:1316's four examples plus the two the same shapes imply, each with the `AnchorKind` member it
resolves against (`model/enums.py:349-362`, the fourteen).

**Each tail must start with a digit**, and that one character is what keeps the patterns from
eating prose: without it `(?:tab|table)\.?\s*[\dA-Za-z]+` lifts *"table shows"* out of a query as a
reference to a table named `shows`, and the `lexical` Channel never sees either word. A reference
without a number is not a reference.

**They are searched inside the text, not matched against a whitespace token.** Three of the six
shapes carry a space -- `Fig. 3a`, `Table 3.2`, `§ 4.2` -- so a token-at-a-time lift finds `Fig.`
and leaves `3a` behind as an FTS term, which is 07:1316's *"noise to FTS"* arriving anyway.

`§4.2(b)` is `clause` and not `section`: 06:1015 gives DOCX heading numbering `section` and a
`w:sdt` clause tag `clause`, and a `§`-prefixed sub-paragraph is the second. `GL-4471` is
`identifier`, which 06:1024 names in as many words -- *"an identifier of the form `GL-4471` ... is
`scope='corpus'`"*. `d7#412` is in the plan's row and is NOT here: it is a cite and goes to
`idents`. D239."""

_CJK: Final[re.Pattern[str]] = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]+")
"""Hiragana, katakana, the two CJK ideograph blocks, compatibility ideographs and half-width kana.
07:1320: *"`unicode61` does not segment CJK"*."""

_SOFT_HYPHEN: Final[str] = "­"
_LINE_BREAK_HYPHEN: Final[re.Pattern[str]] = re.compile(r"-\s*\n\s*")
_FIELD: Final[re.Pattern[str]] = re.compile(r"^(?P<name>[a-z_]+):(?P<value>.*)$")
_BIGRAM: Final[int] = 2
_FIX: Final[str] = "ow query --help"


@dataclass(frozen=True, slots=True)
class Sanitized:
    """What phase 2 made of the query text. Four outputs and one disclosure.

    `terms` reach FTS5; `refs` reach the `exact` Channel as `(name_norm, akind)`; `idents` reach the
    `identity` ladder; `fields` reach `Filters`. `dropped` is what a bound refused to carry, and it
    is a field rather than a log line because 07:1319's ceilings are query bounds a caller can hit
    with an ordinary paste -- *"`MAX_QUERY_TERMS = 64`, `MAX_QUERY_REFS = 16`, `MAX_QUERY_CHARS =
    4_000`"* -- and a query silently cut to 64 terms is a recall loss that presents as absence.
    """

    terms: tuple[str, ...] = ()
    refs: tuple[tuple[str, str], ...] = ()
    idents: tuple[str, ...] = ()
    fields: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    dropped: tuple[str, ...] = ()

    @property
    def truncated(self) -> bool:
        return bool(self.dropped)


def sanitize(text: str) -> Sanitized:
    """One query string in; the four Channel inputs out. Never raises on content, only on size.

    The order of operations is the table's own and it is load-bearing twice. The soft-hyphen fold
    runs BEFORE the syntax strip, or `FTS_SYNTAX`'s hyphen would delete the join it is meant to
    make. The lift runs BEFORE the fold, or `§4.2(b)` would have lost its `§` to `TO_SPACE` and its
    parentheses to the strip, and the `exact` Channel would never see it.
    """
    if len(text) > MAX_QUERY_CHARS:
        raise UsageError(
            f"the query is {len(text)} characters and MAX_QUERY_CHARS is {MAX_QUERY_CHARS}",
            fix=_FIX,
        )
    joined = _LINE_BREAK_HYPHEN.sub("", text.replace(_SOFT_HYPHEN, ""))
    fields: dict[str, str] = {}
    idents: list[str] = []
    dropped: list[str] = []
    kept: list[str] = []
    for token in joined.split():
        if _take_field(token, fields):
            continue
        if _is_ident(token):
            idents.append(token)
            continue
        kept.append(token)
    refs, residue = _lift_refs(" ".join(kept), dropped)
    terms = _terms(residue)
    if len(terms) > MAX_QUERY_TERMS:
        dropped.extend(terms[MAX_QUERY_TERMS:])
        terms = terms[:MAX_QUERY_TERMS]
    return Sanitized(
        terms=terms,
        refs=tuple(refs),
        idents=tuple(idents),
        fields=MappingProxyType(dict(fields)),
        dropped=tuple(dropped),
    )


def _take_field(token: str, fields: dict[str, str]) -> bool:
    """`kind:table` into `fields`; `TODO:` and `foo:bar` back into the text. 07:1318.

    07:1321's row: an unknown `foo:bar` prefix passes through as plain text, *"so `TODO:`
    returns results"*. The rule is the field NAME and not the colon -- a colon is ordinary
    punctuation in prose, and a query that lost every word before one would be a different query.
    """
    found = _FIELD.match(token)
    if found is None or found["name"] not in DSL_FIELDS or not found["value"]:
        return False
    fields[found["name"]] = found["value"]
    return True


def _lift_refs(text: str, dropped: list[str]) -> tuple[tuple[tuple[str, str], ...], str]:
    """Every reference-shaped run, and the text with those runs removed.

    One pass per shape, in `_REF_SHAPES` order, each replacing its matches with a space so a later
    shape cannot re-lift the same characters. `MAX_QUERY_REFS = 16` bounds the result and what it
    refuses lands in `dropped` -- the `exact` Channel's own statement is one query over a
    `tmp_refs` TEMP table (07:1283), so the ceiling is about the query plan rather than about
    memory, and a caller who exceeded it is told which refs did not travel.
    """
    refs: list[tuple[str, str]] = []
    residue = text
    for pattern, akind in _REF_SHAPES:
        found = list(pattern.finditer(residue))
        if not found:
            continue
        for match in found:
            if len(refs) < MAX_QUERY_REFS:
                refs.append((normalize_key(match.group()), akind))
            else:
                dropped.append(match.group())
        residue = pattern.sub(" ", residue)
    return tuple(refs), residue


def _is_ident(token: str) -> bool:
    """A cite, an addr or a document URI -- the identity ladder's three tier-50 lookups."""
    return bool(_CITE.match(token) or _ADDR.match(token) or _URI.match(token))


def _terms(text: str) -> tuple[str, ...]:
    """The residue, folded and split into FTS terms. CJK runs become bigrams.

    `TO_SPACE` before the syntax strip, so a `§` that survived the lift becomes a separator rather
    than an empty token; the strip second; the CJK split last, because a bigram of two ideographs
    must not then be broken by a separator rule that never applied to it.
    """
    folded = text
    for char in TO_SPACE:
        folded = folded.replace(char, " ")
    for char in FTS_SYNTAX:
        folded = folded.replace(char, " ")
    out: list[str] = []
    for token in folded.split():
        if token in FTS_OPERATORS:
            continue
        out.extend(_split_cjk(token))
    return tuple(out)


def _split_cjk(token: str) -> list[str]:
    """A token with CJK in it becomes its bigrams plus whatever else it carried, in order."""
    if not _CJK.search(token):
        return [token]
    pieces: list[str] = []
    index = 0
    for run in _CJK.finditer(token):
        head = token[index : run.start()]
        if head:
            pieces.append(head)
        pieces.extend(bigrams(run.group()))
        index = run.end()
    tail = token[index:]
    if tail:
        pieces.append(tail)
    return pieces


def bigrams(run: str) -> list[str]:
    """`"合同条款"` into `["合同", "同条", "条款"]`. A single character is its own bigram.

    Overlapping, not disjoint: disjoint bigrams make a query for `同条` miss a document containing
    it at an odd offset, which is a recall loss with no symptom. One character is kept whole
    because a query that is one ideograph has no pair to make and dropping it would return the
    corpus.
    """
    if len(run) < _BIGRAM:
        return [run]
    return [run[index : index + _BIGRAM] for index in range(len(run) - 1)]


def grade_title(ident: str, label: str) -> str:
    """The tier a label ACTUALLY measures against an ident. 07:1255, and the 40 tier is the point.

    Four answers in descending strength: `title_exact` is casefold equality (45); `title_normalised`
    is `normalize_key` equality (40), which folds NFKC, punctuation and separators -- so
    `"Table 3-2"` reaches 40 against `"Table 3.2"` and never 45; `title_prefix` is a casefolded
    prefix (30); `none` is 0.

    07:1265's own worked failure is the one this ordering prevents: *"The document analogue is
    'Table 3.2 (revised)' tying with 'Table 3.2'."* Under this ladder it does not tie -- it grades
    `title_prefix` at 30 against the literal match's 45 -- and that gap is the whole of the 40
    tier's argument.

    `normalize_key` and not a local fold: 02:229 puts the blocking-key normaliser in
    `omniweave_core.ident` and a second one here would be the drift 13:1072 names.
    """
    if not label:
        return "none"
    if ident.casefold() == label.casefold():
        return "title_exact"
    if normalize_key(ident) == normalize_key(label):
        return "title_normalised"
    if label.casefold().startswith(ident.casefold()) or ident.casefold().startswith(
        label.casefold()
    ):
        return "title_prefix"
    return "none"


def cite_doc_ord(cite: str) -> int | None:
    """`'d7#412'` to `7`, or `None` when the token is not a cite.

    D240: `block_cite` is `UNIQUE(doc_ord, cite)`, so the `doc_ord` the string already carries is
    what turns 07:1269's *"index lookup"* into one. Without it the equality on `cite` alone is a
    full scan of `block`, which on a 41,822-block corpus is the difference between the ladder's
    sub-millisecond claim and its 15 ms budget.
    """
    found = _CITE.match(cite)
    return int(found["doc"]) if found else None


def normalise_query_text(text: str) -> str:
    """NFC, for an ident compared against a stored `label`. Not a fold -- `grade_title()` folds."""
    return unicodedata.normalize("NFC", text)
