"""The corpus card -- what a caller reads BEFORE running a query, computed and never written.

10:1010 fixes the card's job in six words: *"is the answer likely to be in here?"*, at ~1,200
characters, from *"the full `corpus_card` row at `max(card_gen)`"*. Every column is derived from
`doc`, `page`, `block`, `diag` and `ingest_scope` by the statements below. Nothing here calls a
model: 10:1089 is the rule -- *"`abstract` is `NULL` unless a human ran `ow corpora --summarize`"*
-- and this module never writes that column at all.

## The honesty number, and why it is computed here rather than at serve

`verbatim_fraction` is cited by eight documents as the thing that discloses, before a query runs,
that `quote = verbatim` is unreachable on a path. 03:1561 states the case it exists for: on the
office path *"the block is text with a `cite`, at `quote = NORMALIZED` at best; `verbatim` is
unreachable on this path and `corpus_card.verbatim_fraction` discloses it **before any query
runs**"*. A number computed at serve would be a number an agent learns one refused quote at a time,
which is the failure the field exists to prevent -- so it is a stored column on a row built by the
runner, and this module is the builder.

## The capability floor, and the one field that is a union

10:1076: *"**`achieved` is the MIN over drivers**, not a card's claim -- the corpus's *real*
capability floor."* `capability_floor()` is that MIN over `doc.achieved`, and it is a MIN in four
different senses because `Capabilities` has four kinds of field:

* the ten ORDERED ladders (`drivers.card.PARSE_LADDERS`) take the lowest rung any document
  achieved, by ladder index and never alphabetically -- 04's `reading_order` order is marker's
  measured `char_stream` > `learned` result and not how the words sound;
* the three booleans take `AND`;
* `math` is a SET and takes INTERSECTION -- a corpus offers a notation only where every document
  does;
* `forfeits` is a set and takes **UNION**, because it is the only field whose members are
  NEGATIVE. 03:296's `forfeits` names what a driver gives up, so the floor of two drivers forfeits
  whatever either forfeits. Intersecting it would make a corpus look MORE capable as it grows,
  which is the exact direction a floor may not move.

An empty corpus has no floor to take a MIN over, and `capability_floor(())` returns `None` rather
than the bottom of every ladder: a corpus with no documents has an UNKNOWN capability, not a
terrible one, and 05:2122's discipline (*"Uncomputable is None; NEVER a default value"*) is the
same rule one layer up.

## The gap join runs against codes the caller supplies

10:1085: *"**`gaps` is derived from the `diag` table**, and `CREATE INDEX diag_code` exists
specifically so that join is cheap. ... It is the input to absence gate `parse_gap_in_scope`, which
is what makes `absent` mean something."* The codes that block an absence claim are
`ABSENCE_BLOCKING_DIAGS`, which W6.5 homed in `omniweave_core.retrieve.verdict` -- and this module
may not import it. `omniweave_core.retrieve.verdict` imports `omniweave_core.store.types`, so the
edge back is a package cycle, and it is the same cycle `Coverage.gaps` already documents
(`store/types.py`). So the codes arrive as a parameter, the way `DocSink` takes its `score_kinds`
register: an ambient input the caller owns, defaulting to nothing rather than to a guess.

## `langs` and `date_range` have no column to read

charter.md:6717 declares `langs_json` and `date_range_json` NOT NULL, 10:1054-1055 prints
`{"en": 16, "de": 1}` and `{"lo": "2019-03-01", "hi": "2025-06-14"}`, and **no table in the
migration set carries a document language or a document date.** `doc` has seventeen columns and
none of them is either. D287 is the entry. Shipped: `{}` and `{"lo": null, "hi": null}`, which is
exactly the shape 18:685 already types for the second (`Mapping[str, str | None]`) and a legal
`Mapping[str, int]` for the first -- an empty answer the wire form can carry, rather than a
language detector this cell would have had to invent.

## Two caps the plan states and two it does not

`OUTLINE_MAX = 40` is charter.md:6718's own *"<= 40 top-level titles, sampled DETERMINISTICALLY"*.
`TOP_TERMS_MAX` and `GAPS_MAX` are this module's, because ~1,200 characters is a budget and an
uncapped list is not a budget. The arithmetic that sets them is in their docstrings, and D288
records that the stated cap and the stated size cannot both hold.

Specified in charter.md:6705-6727, 10-interfaces.md section 4.2 and 18-api-sketch.md:676-703;
scheduled by 16-roadmap.md:664. Tier T-INTERNAL: one of the nine LAZY names, so nothing eager may
reach it (G17).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import PARSE_BOOLS, PARSE_LADDERS, PARSE_SETS
from omniweave_core.errors import StoreError
from omniweave_core.model.enums import Quote, Trust
from omniweave_core.store import NO_JOB_DOCS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from omniweave_core.errors import Register

__all__ = [
    "CARD_COLUMNS",
    "GAPS_MAX",
    "OUTLINE_MAX",
    "TOP_TERMS_MAX",
    "CardRead",
    "CorpusCardRow",
    "Gap",
    "build_card",
    "capability_floor",
    "card_stale",
    "inspect",
    "read_card",
    "write_card",
]


# =============================================================================================
# 1. The caps
# =============================================================================================

OUTLINE_MAX: Final[int] = 40
"""charter.md:6718 and 18:686 -- *"<= 40 top-level titles, sampled DETERMINISTICALLY"*.

Deterministic here means ordered by `(doc_ord, page, ord)` and truncated, never sampled at random
and never ordered by a score: two runs over one store must produce one card, because the card is a
row a reviewer diffs across generations."""

TOP_TERMS_MAX: Final[int] = 24
"""Unstated by the plan, and a cap is required for 10:1010's ~1,200 characters to mean anything.

charter.md:6719 says only *"from an fts5vocab('block_fts','row') table. NOT 'free'"* -- which fixes
the SOURCE (a real term frequency, not a model's idea of a topic) and not the length. 24 terms at
the ~9 characters a JSON string element costs is ~216 characters, which sits beside `OUTLINE_MAX`'s
40 titles without either of them owning the budget alone. D288 records that the plan's own stated
cap and its stated size disagree by more than this choice can fix."""

GAPS_MAX: Final[int] = 8
"""Unstated. charter.md:6723 says *"top diag codes"* and `top` implies a cut nobody sized.

Eight is `ABSENCE_BLOCKING_DIAGS`'s thirteen minus the five 13:1279 adds *"so the set is total"* --
the charter's own eight -- so a card can carry every code the charter itself contemplated and a
corpus failing in more ways than that is a corpus whose card is not the right report."""


# =============================================================================================
# 2. The row, and the gap
# =============================================================================================

CARD_COLUMNS: Final[tuple[str, ...]] = (
    "card_gen",
    "name",
    "root",
    "built_at_ns",
    "writer_version",
    "docs_indexed",
    "docs_discovered",
    "docs_partial",
    "docs_failed",
    "pages",
    "blocks",
    "bytes",
    "formats_json",
    "langs_json",
    "date_range_json",
    "outline_json",
    "top_terms_json",
    "achieved_json",
    "trust_hist_json",
    "quote_hist_json",
    "verbatim_fraction",
    "gaps_json",
    "restriction_bits",
    "embedding_json",
    "abstract",
    "abstract_producer_id",
)
"""The twenty-six columns of charter.md:6709-6727, in the DDL's order.

Written once here and rendered into both statements, because an INSERT whose column list has
drifted from its VALUES list is the defect a second spelling exists to produce."""


@dataclass(frozen=True, slots=True)
class Gap:
    """18:699's seven fields. One row of `gaps_json`, and absence gate 9's input.

    **Three of the seven cannot be filled today and the module does not pretend otherwise.**
    10:1086 requires *"both spellings of every code"* plus a meaning and a fix, and all three come
    from `codes.toml` -- whose own header calls `fix` deliberately absent from every seeded row
    until W1.3 fills it, and which carries no row at all for any of the thirteen
    `ABSENCE_BLOCKING_DIAGS` symbols. So `code`, `meaning` and `fix` are `""` for an unregistered
    symbol, 18:703's *"never empty"* does not yet hold, and D289 is the entry. `symbol`, `docs`,
    `pages` and `severity` come from the store and are always real.
    """

    code: str
    symbol: str
    meaning: str
    docs: int
    pages: int
    severity: str
    fix: str

    @property
    def registered(self) -> bool:
        """Whether `codes.toml` carried a row for this symbol. The three empty fields' predicate."""
        return bool(self.code)


@dataclass(frozen=True, slots=True)
class CorpusCardRow:
    """One `corpus_card` row, as the table stores it: JSON columns still JSON.

    Not 18:677's `CorpusCard`, which is the SDK's and lands with W7.1 (`corpora-out-v1.json` is
    reflected from `omniweave.sdk:CorpusCard`, not from this). The difference is the three
    read-time degradations -- `readable`, `reason`, `card_stale` -- which 10:1092 puts *"on the row
    rather than in a side channel"* and which are properties of a READ, not of a card: a card
    cannot record that it was unreadable. `card_stale()` below is the one of the three this module
    can answer, and it takes the connection rather than living on the row for that reason.
    """

    card_gen: int
    name: str
    root: str
    built_at_ns: int
    writer_version: str
    docs_indexed: int
    docs_discovered: int
    docs_partial: int
    docs_failed: int
    pages: int
    blocks: int
    bytes: int
    formats_json: str
    langs_json: str
    date_range_json: str
    outline_json: str
    top_terms_json: str
    achieved_json: str
    trust_hist_json: str
    quote_hist_json: str
    verbatim_fraction: float
    gaps_json: str
    restriction_bits: int
    embedding_json: str | None
    abstract: str | None
    abstract_producer_id: int | None

    @property
    def gaps(self) -> tuple[Gap, ...]:
        """`gaps_json` as the rows it holds."""
        return tuple(Gap(**row) for row in json.loads(self.gaps_json))

    def values(self) -> tuple[object, ...]:
        """The row in `CARD_COLUMNS` order, for the INSERT."""
        return tuple(getattr(self, column) for column in CARD_COLUMNS)


# =============================================================================================
# 3. The capability floor
# =============================================================================================


def capability_floor(achieved: Iterable[Mapping[str, object]]) -> dict[str, object] | None:
    """The MIN over documents of `doc.achieved`. 10:1076's *"corpus's *real* capability floor"*.

    `None` for an empty corpus: there is no floor over no documents, and the bottom of every
    ladder would be a claim that the corpus is maximally incapable rather than that nobody asked.

    A missing key reads as the ladder's element 0, which `PARSE_LADDERS`'s docstring already fixes
    as the only default that cannot over-claim. An unknown rung raises rather than sorting
    itself to the bottom, because a rung this build does not know is a schema mismatch and pricing
    it as the worst case would hide it.
    """
    rows = [dict(row) for row in achieved]
    if not rows:
        return None
    floor: dict[str, object] = {}
    for field, ladder in PARSE_LADDERS.items():
        floor[field] = ladder[min(_rung(row.get(field, ladder[0]), ladder, field) for row in rows)]
    for field in PARSE_BOOLS:
        floor[field] = all(bool(row.get(field, False)) for row in rows)
    floor["math"] = sorted(set.intersection(*(_set(row, "math") for row in rows)))
    floor["forfeits"] = sorted(set.union(*(_set(row, "forfeits") for row in rows)))
    return floor


def _rung(value: object, ladder: Sequence[str], field: str) -> int:
    """A ladder member's index, or a refusal naming the field and the members it does have."""
    if value in ladder:
        return ladder.index(str(value))
    raise StoreError(
        f"doc.achieved.{field} = {value!r} is not a rung of that ladder",
        symbol="OW_CARD_ACHIEVED_UNKNOWN",
        fix=(
            f"the shipped ladder is {', '.join(ladder)}; re-parse the document with a driver this "
            f"build knows, or upgrade omniweave-core"
        ),
    )


def _set(row: Mapping[str, object], field: str) -> set[str]:
    """One of `PARSE_SETS`'s two set-valued keys, as a set, with an absent key reading empty."""
    value = row.get(field, ())
    if isinstance(value, str):
        raise StoreError(
            f"doc.achieved.{field} is a string, not a set of {'|'.join(sorted(PARSE_SETS[field]))}",
            symbol="OW_CARD_ACHIEVED_UNKNOWN",
            fix=f"write {field} as a JSON array, which is what Capabilities serialises it as",
        )
    return set(value) if isinstance(value, (list, tuple, set, frozenset)) else set()


# =============================================================================================
# 4. The build
# =============================================================================================

_COUNTS = (
    "SELECT count(*), sum(status = 'partial'), sum(status = 'failed'), "  # noqa: S608 -- a constant
    "coalesce(sum(source_bytes), 0), coalesce(sum(page_count), 0) "
    f"FROM doc WHERE {NO_JOB_DOCS}"
)

_FORMATS = (
    f"SELECT format, count(*) FROM doc WHERE {NO_JOB_DOCS} "  # noqa: S608 -- a constant
    "GROUP BY format ORDER BY format"
)

_ACHIEVED = f"SELECT achieved FROM doc WHERE {NO_JOB_DOCS} ORDER BY doc_ord"  # noqa: S608

_BLOCK_STATS = """
SELECT count(*), coalesce(sum(restriction_bits), 0) FROM block WHERE state = 0
"""

_TRUST_HIST = "SELECT trust, count(*) FROM block WHERE state = 0 GROUP BY trust"
_QUOTE_HIST = "SELECT quote, count(*) FROM block WHERE state = 0 GROUP BY quote"

_DISCOVERED = "SELECT coalesce(sum(discovered), 0) FROM ingest_scope"

_OUTLINE = """
SELECT b.text FROM block b
 WHERE b.state = 0 AND b.text IS NOT NULL
   AND b.kind IN (SELECT ord FROM enum_val WHERE domain = 'kind' AND name IN ('title','heading'))
 ORDER BY b.doc_ord, b.page, b.ord
 LIMIT ?
"""

_GAPS = """
SELECT code, count(DISTINCT doc_ord), count(DISTINCT page),
       max(CASE severity WHEN 'error' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END)
  FROM diag
 WHERE code IN ({placeholders})
 GROUP BY code
 ORDER BY count(DISTINCT doc_ord) DESC, code
 LIMIT ?
"""

_SEVERITY: Final[Mapping[int, str]] = {1: "info", 2: "warning", 3: "error"}


def build_card(
    connection: sqlite3.Connection,
    *,
    name: str,
    root: str,
    card_gen: int,
    built_at_ns: int,
    writer_version: str,
    blocking_codes: Sequence[str] = (),
    register: Register | None = None,
    embedding: Mapping[str, object] | None = None,
) -> CorpusCardRow:
    """Compute one card from the store. Reads only; the caller writes it.

    `built_at_ns` and `writer_version` are parameters and not reads, for the reason
    `store/inspect.py` already states for `residue`: `time.time` is banned in library code and a
    version a module read of itself would be a second home for a fact `omniweave_core.contract`
    owns.

    `blocking_codes` defaults to EMPTY, which yields no gaps. That is the fail-closed direction for
    a list whose only consumer is an absence gate: a card that invented a gap set would let gate 9
    fire on a code nobody declared blocking, and a card with none says only that nobody asked.
    """
    docs, partial, failed, source_bytes, pages = _counts(connection, _COUNTS, 5)
    blocks, restriction_bits = _counts(connection, _BLOCK_STATS, 2)
    (discovered,) = _counts(connection, _DISCOVERED, 1)
    quote_hist = _histogram(connection, _QUOTE_HIST, Quote)
    floor = capability_floor(json.loads(text) for (text,) in connection.execute(_ACHIEVED))
    verbatim = quote_hist.get(Quote.VERBATIM.name.lower(), 0)
    return CorpusCardRow(
        card_gen=card_gen,
        name=name,
        root=root,
        built_at_ns=built_at_ns,
        writer_version=writer_version,
        docs_indexed=docs,
        docs_discovered=max(discovered, docs),
        docs_partial=partial,
        docs_failed=failed,
        pages=pages,
        blocks=blocks,
        bytes=source_bytes,
        formats_json=_dumps(dict(connection.execute(_FORMATS))),
        langs_json=_dumps({}),
        date_range_json=_dumps({"lo": None, "hi": None}),
        outline_json=_dumps([text for (text,) in connection.execute(_OUTLINE, (OUTLINE_MAX,))]),
        top_terms_json=_dumps(_top_terms(connection)),
        achieved_json=_dumps(floor),
        trust_hist_json=_dumps(_histogram(connection, _TRUST_HIST, Trust)),
        quote_hist_json=_dumps(quote_hist),
        verbatim_fraction=(verbatim / blocks) if blocks else 0.0,
        gaps_json=_dumps([asdict(gap) for gap in _gaps(connection, blocking_codes, register)]),
        restriction_bits=restriction_bits,
        embedding_json=None if embedding is None else _dumps(embedding),
        abstract=None,
        abstract_producer_id=None,
    )


def _counts(connection: sqlite3.Connection, statement: str, width: int) -> tuple[int, ...]:
    """One row of `width` integers, with a NULL cell reading zero.

    Typed `int` rather than `object` because every caller below does arithmetic with the result,
    and a `tuple[object, ...]` would put an `int()` call and a cast at each of the twelve uses.
    An aggregate over no rows is SQL NULL -- `sum()` of an empty set, not zero -- and zero is the
    honest count for a corpus with no documents, so the coalescing is here and not in nine
    statements.
    """
    row = connection.execute(statement).fetchone()
    cells = tuple(row) if row is not None else ()
    if len(cells) != width:
        raise StoreError(
            f"the card statement returned {len(cells)} cells, not {width}",
            symbol="OW_CARD_STATEMENT_SHAPE",
            fix="this is a build defect; the statement and its reader are in store/card.py",
        )
    return tuple(0 if cell is None else int(cell) for cell in cells)  # type: ignore[arg-type]


def _dumps(value: object) -> str:
    """Canonical JSON for a stored column: sorted keys, no spaces, so a card diffs cleanly."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _histogram(
    connection: sqlite3.Connection,
    statement: str,
    vocabulary: type[Trust] | type[Quote],
) -> dict[str, int]:
    """An ordinal column's counts, keyed by MEMBER NAME and omitting the rungs with no blocks.

    `Trust` and `Quote` store their own integers (`enum_val_rows()`'s first branch), so the stored
    value IS the member and no `enum_val` lookup is needed. A rung with no blocks is absent rather
    than zero, which is what 10:1061-1062's two printed histograms do -- `quote_hist` names three
    of five rungs and `trust_hist` all three of three.
    """
    rows = connection.execute(statement).fetchall()
    return {vocabulary(value).name.lower(): int(count) for value, count in rows}


def _top_terms(connection: sqlite3.Connection) -> list[str]:
    """The corpus's most frequent indexed terms, from `fts5vocab` over `block_fts`.

    charter.md:6719 fixes the source and rejects the alternative in two words -- *"NOT 'free'"*. A
    TEMP shadow table so a read-only store works and `main` is untouched, which is the idiom
    `p2-stage-b2c` already settled for reading an FTS index's own postings.

    An absent or unbuilt `block_fts` yields no terms rather than raising: the card is a report, and
    a corpus whose lexical index is still building has fewer facts, not a broken card.
    """
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.card_vocab USING fts5vocab(main, 'block_fts', 'row')"
        )
    except Exception:
        return []
    try:
        rows = connection.execute(
            "SELECT term FROM temp.card_vocab ORDER BY cnt DESC, term LIMIT ?", (TOP_TERMS_MAX,)
        ).fetchall()
        return [str(term) for (term,) in rows]
    finally:
        connection.execute("DROP TABLE temp.card_vocab")


def _gaps(
    connection: sqlite3.Connection, codes: Sequence[str], register: Register | None
) -> list[Gap]:
    """The `diag` join, resolved against the register where the register has a row."""
    if not codes:
        return []
    statement = _GAPS.format(placeholders=",".join("?" for _ in codes))
    rows = connection.execute(statement, (*codes, GAPS_MAX)).fetchall()
    gaps = []
    for symbol, docs, pages, severity in rows:
        entry = None if register is None else register.by_symbol.get(str(symbol))
        gaps.append(
            Gap(
                code="" if entry is None else entry.numeric,
                symbol=str(symbol),
                meaning="" if entry is None else entry.meaning,
                docs=int(docs),
                pages=int(pages),
                severity=_SEVERITY[int(severity)],
                fix="" if entry is None else entry.fix,
            )
        )
    return gaps


# =============================================================================================
# 5. Write, read, and the one degradation a card can answer about itself
# =============================================================================================


def write_card(connection: sqlite3.Connection, row: CorpusCardRow) -> None:
    """Insert one card. `card_gen` is the primary key, so a re-run at one generation REPLACES.

    `INSERT OR REPLACE` and not `INSERT`: the card is `[DER]`, rebuildable from the five tables it
    reads, and a runner that re-converges a generation must be able to write the answer twice. A
    unique-constraint failure here would make a rebuild an error instead of an idempotent write.
    """
    columns = ",".join(CARD_COLUMNS)
    marks = ",".join("?" for _ in CARD_COLUMNS)
    connection.execute(
        f"INSERT OR REPLACE INTO corpus_card ({columns}) VALUES ({marks})",  # noqa: S608
        row.values(),
    )


def read_card(connection: sqlite3.Connection, card_gen: int | None = None) -> CorpusCardRow | None:
    """The card at `card_gen`, or 10:1010's *"the full `corpus_card` row at `max(card_gen)`"*.

    `None` when there is no such row, which 10:1037 makes a reportable state and not an error --
    *"if `corpus_card` is missing or older than the newest `doc.gen`, the entry carries
    `card_stale: true`"*.
    """
    columns = ",".join(CARD_COLUMNS)
    if card_gen is None:
        statement = f"SELECT {columns} FROM corpus_card ORDER BY card_gen DESC LIMIT 1"  # noqa: S608
        row = connection.execute(statement).fetchone()
    else:
        statement = f"SELECT {columns} FROM corpus_card WHERE card_gen = ?"  # noqa: S608
        row = connection.execute(statement, (card_gen,)).fetchone()
    return None if row is None else CorpusCardRow(*row)


def card_stale(connection: sqlite3.Connection, row: CorpusCardRow | None) -> bool:
    """10:1036-1039's predicate: no card, or a card older than the newest `doc.gen`.

    Never recomputed here. The same paragraph is explicit that a stale card is *"never silently
    recomputed inside a read call -- `omniweave-serve` never runs the Supervisor"*, so this returns
    the fact and the caller prints `ow index update --corpus <name>`.
    """
    if row is None:
        return True
    statement = f"SELECT max(gen) FROM doc WHERE {NO_JOB_DOCS}"  # noqa: S608 -- a constant
    newest = connection.execute(statement).fetchone()[0]
    return newest is not None and int(newest) > row.card_gen


# =============================================================================================
# 6. One corpus, read for `ow_corpora`: the card and the three read-time degradations
# =============================================================================================

_PRODUCER_COLUMNS: Final[tuple[str, ...]] = (
    "operator",
    "op_version",
    "code_fingerprint",
    "model_id",
    "model_rev",
    "runtime",
    "runtime_version",
    "prompt_fp",
    "options_digest",
)
"""`producer`'s nine identity columns, in 18's `Producer` order (`corpora-out-v1.json`)."""


@dataclass(frozen=True, slots=True)
class CardRead:
    """What one store says about itself when `ow_corpora` asks. 10:1029-1040's three degradations.

    `readable` and `reason` are 10:1031's: *"listed with `readable: false` and a `reason`, and never
    omitted and never fatal"*. `stale` is `card_stale()`. `row` is `None` both when the store could
    not be read and when it holds no card, and `stale` is what tells the two apart. `producer` is
    the abstract's producer row, which is `None` whenever `abstract` is (10:1089).
    """

    readable: bool
    reason: str | None = None
    row: CorpusCardRow | None = None
    stale: bool = True
    producer: dict[str, object] | None = None


def inspect(path: Path) -> CardRead:
    """Open `path` read-only, read its newest card, and close it. Never raises for a bad store.

    10:1032: *"Omitting it would make a configuration error look like a corpus that does not exist;
    failing the whole call would let one bad store hide fifteen good ones."* So every way a store
    can fail to be read -- missing, unmigrated, locked, corrupt -- comes back as `readable=False`
    with the store's own message, and the card is never rebuilt here (10:1039).
    """
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415 -- the one open

    try:
        connection = store_sqlite.connect_readonly(path)
    except StoreError as error:
        return CardRead(readable=False, reason=str(error))
    try:
        row = read_card(connection)
        stale = card_stale(connection, row)
        producer = _producer(connection, row)
    except (sqlite3.Error, StoreError) as error:
        return CardRead(readable=False, reason=f"{path}: {error}")
    finally:
        connection.close()
    return CardRead(readable=True, row=row, stale=stale, producer=producer)


def _producer(
    connection: sqlite3.Connection, row: CorpusCardRow | None
) -> dict[str, object] | None:
    """The abstract's `producer` row, `options_digest` as 32 hex characters, or `None`."""
    if row is None or row.abstract_producer_id is None:
        return None
    found = connection.execute(
        f"SELECT {', '.join(_PRODUCER_COLUMNS)} FROM producer WHERE producer_id = ?",  # noqa: S608
        (row.abstract_producer_id,),
    ).fetchone()
    if found is None:
        return None
    out: dict[str, object] = dict(zip(_PRODUCER_COLUMNS, found, strict=True))
    digest = out["options_digest"]
    out["options_digest"] = bytes(digest).hex() if isinstance(digest, bytes | bytearray) else digest
    return out
