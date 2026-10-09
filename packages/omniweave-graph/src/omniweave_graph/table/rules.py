"""`derive.entity.table`'s rules: a table with a header row is already a relation. **D681.**

06-structure-extraction.md section 3.6 is the specification: *"A table with `header_rows >= 1` is a
schema, and every data row under it is a set of `(header, cell)` assertions about the row's
subject."* Per data row: one entity for the subject cell, one `attribute` claim per other non-empty
cell `observed` at that cell's own cite, and one `canonical` alias per subject.

## Rulings the plan leaves to the Pass (the ledger's D681)

1. **A cell is the members that sit in it.** A cell's text is its paragraphs' (the view gives each
   paragraph its cell's position, D681), so a cell with two paragraphs reads as both texts joined by
   a space, and is grounded at its first non-empty paragraph, over that paragraph's stripped text.
2. **The subject column** is the first column whose header normalises to a subject word -- 06:1149's
   `name`, `party`, `item`, `id`, `description` -- for the whole table; failing that, each row's
   first non-empty cell, as 06 prints it.
3. **`etype` is inferred from the subject column's header, conservatively.** A small closed map of
   header words to the corpus etypes `org`, `person`, `place` and `product`; anything else is
   `unknown`. A guess is `unknown`, as a guessed datatype is `string`.
4. **Scope follows the etype.** A subject under a header the map knows names a thing across the
   corpus -- a party, a person, a country -- and is `corpus`, its etype's `etype_vocab.scope`. An
   `unknown` subject is a row label (`Revenue`, `north`) whose meaning is this table's, and is
   `document`: two financial statements' `Revenue` rows are not one entity.
5. **The predicate is the header as written;** the sink normalises it (D681), as it does an entity's
   key and an anchor's name, so `normalize_key` has one home and this package restates none. A cell
   under an empty header asserts nothing and is not a claim.
6. **`object_datatype` is closed and conservative** (06:1154-1158): `xsd:date` for a valid ISO-8601
   date or an unambiguous day-month-year in English month names; `money:<ISO4217>` when the cell has
   a digit and the cell or its header names a currency by ISO code or by `EUR`'s or `GBP`'s own sign
   -- `$` and `¥` are not one currency's, so they decide nothing; `xsd:decimal` for a bare number
   under a header normalising to a numeric word; `string` otherwise. The literal is the cell's text,
   untouched: the datatype says what it is and never rewrites it.

Forms (`FORM`, `FORM_FIELD`, `KEY_VALUE`, `CHECKBOX`) are 06:1160-1171's other half and are not
here: no shipped parse driver emits those kinds yet. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_graph.view import Member

__all__ = [
    "CORPUS_ETYPES",
    "SUBJECT_WORDS",
    "CellText",
    "Fact",
    "Row",
    "datatype",
    "find",
]

SUBJECT_WORDS: Final = frozenset({"name", "party", "item", "id", "description"})
"""06:1149: a column whose header normalises to one of these is the subject column."""

_ETYPE_BY_HEADER: Final = {
    "party": "org",
    "parties": "org",
    "company": "org",
    "organisation": "org",
    "organization": "org",
    "counterparty": "org",
    "person": "person",
    "employee": "person",
    "signatory": "person",
    "country": "place",
    "jurisdiction": "place",
    "location": "place",
    "city": "place",
    "product": "product",
    "sku": "product",
}
"""Ruling 3's closed map. A header word not here infers `unknown`."""

CORPUS_ETYPES: Final = frozenset({"org", "person", "place", "product"})
"""Ruling 4: the etypes whose `etype_vocab.scope` is `corpus` and that a header can name."""

_NUMERIC_WORDS: Final = frozenset(
    {
        "amount", "total", "quantity", "qty", "count", "number", "price", "rate", "value",
        "percent", "percentage", "balance", "units", "sum", "fee", "fees", "cost",
    }
)  # fmt: skip
_CURRENCY_CODES: Final = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD", "INR",
        "SEK", "NOK", "DKK", "ZAR", "BRL", "MXN", "KRW",
    }
)  # fmt: skip
_CURRENCY_SIGNS: Final = {"€": "EUR", "£": "GBP"}
_MONTHS: Final = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DAY_MONTH_YEAR: Final = re.compile(rf"\d{{1,2}} (?:{_MONTHS}) \d{{4}}\Z", re.IGNORECASE)
_MONTH_DAY_YEAR: Final = re.compile(rf"(?:{_MONTHS}) \d{{1,2}}, \d{{4}}\Z", re.IGNORECASE)
_NUMBER: Final = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z")
_CODE_TOKEN: Final = re.compile(r"\b[A-Z]{3}\b")
_WORD: Final = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True, slots=True)
class CellText:
    """One cell's text, and where it is grounded: its first non-empty member, a span into that
    member's `block.text` over its stripped text (ruling 1)."""

    cite: str
    text: str
    span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Fact:
    """One `(header, cell)` assertion about a row's subject."""

    header: str
    cell: CellText
    datatype: str


@dataclass(frozen=True, slots=True)
class Row:
    """One data row: its subject, the subject's etype and scope, and its facts in column order."""

    table_cite: str
    subject: CellText
    etype: str
    scope: str
    facts: tuple[Fact, ...]


def find(members: Sequence[Member]) -> tuple[Row, ...]:
    """Every data row of every table with a header row among `members`, in reading order."""
    tables: dict[str, dict[tuple[int, int], list[Member]]] = {}
    header_rows: dict[str, int] = {}
    for member in members:
        cell = member.table
        if cell is None:
            continue
        tables.setdefault(cell.table_cite, {}).setdefault((cell.r, cell.c), []).append(member)
        header_rows[cell.table_cite] = cell.header_rows
    rows: list[Row] = []
    for table_cite, cells in tables.items():
        if header_rows[table_cite] >= 1:
            rows.extend(_rows(table_cite, cells, header_rows[table_cite]))
    return tuple(rows)


def datatype(cell: str, header: str) -> str:
    """Ruling 6. Closed and conservative: a guess is `string`."""
    if _is_date(cell):
        return "xsd:date"
    if any(ch.isdigit() for ch in cell):
        code = _currency(cell) or _currency(header)
        if code is not None:
            return f"money:{code}"
    if _NUMBER.match(cell) and _NUMERIC_WORDS & set(_words(header)):
        return "xsd:decimal"
    return "string"


def _rows(
    table_cite: str, cells: dict[tuple[int, int], list[Member]], headers_end: int
) -> list[Row]:
    texts = {pos: _cell_text(found) for pos, found in cells.items()}
    columns = sorted({c for _r, c in texts})
    headers = {
        c: " ".join(
            t.text for r in range(headers_end) if (t := texts.get((r, c))) is not None and t.text
        )
        for c in columns
    }
    named = next((c for c in columns if " ".join(_words(headers[c])) in SUBJECT_WORDS), None)
    out: list[Row] = []
    for r in sorted({r for r, _c in texts if r >= headers_end}):
        subject_c = named
        if subject_c is None:
            subject_c = next((c for c in columns if (t := texts.get((r, c))) and t.text), None)
        subject = None if subject_c is None else texts.get((r, subject_c))
        if subject_c is None or subject is None or not subject.text:
            continue
        etype = _etype(headers.get(subject_c, ""))
        facts = tuple(
            Fact(headers[c], cell, datatype(cell.text, headers[c]))
            for c in columns
            if c != subject_c
            and headers[c]
            and (cell := texts.get((r, c))) is not None
            and cell.text
        )
        scope = "corpus" if etype in CORPUS_ETYPES else "document"
        out.append(Row(table_cite, subject, etype, scope, facts))
    return out


def _cell_text(members: list[Member]) -> CellText:
    texts = [m for m in members if m.text and m.text.strip()]
    if not texts:
        return CellText(members[0].cite, "", (0, 0))
    first = texts[0]
    raw = first.text or ""
    a = len(raw) - len(raw.lstrip())
    b = len(raw.rstrip())
    joined = " ".join((m.text or "").strip() for m in texts)
    return CellText(first.cite, joined, (a, b))


def _etype(header: str) -> str:
    words = _words(header)
    return _ETYPE_BY_HEADER.get(words[0], "unknown") if len(words) == 1 else "unknown"


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _is_date(cell: str) -> bool:
    if _ISO_DATE.match(cell):
        try:
            dt.date.fromisoformat(cell)
        except ValueError:
            return False
        return True
    return bool(_DAY_MONTH_YEAR.match(cell) or _MONTH_DAY_YEAR.match(cell))


def _currency(text: str) -> str | None:
    for code in _CODE_TOKEN.findall(text):
        if code in _CURRENCY_CODES:
            return code
    return next((code for sign, code in _CURRENCY_SIGNS.items() if sign in text), None)
