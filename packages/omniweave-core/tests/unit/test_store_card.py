"""The corpus card: what a caller reads before a query, and the three columns nothing can fill.

16:664's estimation basis is *"one row per `card_gen`"*, and section 3 builds that row over a real
migrated store. The families that matter:

* **`NO_JOB_DOCS` is one predicate, and the card is the table that proves why.** 07:763 says a job
  document *"would drive `verbatim_fraction` toward zero by adding to a denominator it can never
  contribute to"*, so section 2 puts a job document in the store and asserts the ratio does not
  move.
* **The plan's own worked card is arithmetically consistent.** 10:1061-1063's two histograms each
  sum to 10:1052's `blocks`, and `verbatim / blocks` rounds to the printed `verbatim_fraction`.
  Section 4 asserts that of the plan and then asserts the same property of a card we built.
* **The floor moves one way.** Section 5 drives `capability_floor()` over disagreeing documents,
  including `forfeits`, the one field where the floor is a UNION.
* **Three columns cannot be filled and the tests say so.** Section 7 asserts that no migration
  carries a language or a date column (D287) and that none of the thirteen absence-blocking diag
  symbols has a `codes.toml` row (D289), so the day either lands, a test says the gap closed.

# WHY `import sqlite3` IS HERE AT ALL

INV-17 bans it outside `omniweave_core/store/`, and this module's subject is a row SQLite computes:
the card's twenty-six columns are the output of nine statements over five tables, and none of the
claims below -- that a job document leaves `verbatim_fraction` unmoved, that the outline is ordered
by `(doc_ord, page, ord)`, that a rebuild at one `card_gen` REPLACES -- is readable from source.
The semgrep half of the ban scopes every rule to `packages/*/src/**` and already exempts a test;
ruff's half has no `per-file-ignores` row for tests, so the `noqa` is the narrowest form of the
exemption, and `test_store_maintenance.py` is the house form it follows.
"""

from __future__ import annotations

import json
import re
import sqlite3  # noqa: TID251 -- see the note below
from typing import TYPE_CHECKING

import pytest
from conftest import migration_files
from omniweave_core.errors import StoreError, load_register
from omniweave_core.model.enums import Quote, Trust
from omniweave_core.retrieve.verdict import ABSENCE_BLOCKING_DIAGS
from omniweave_core.store import NO_JOB_DOCS
from omniweave_core.store.card import (
    CARD_COLUMNS,
    GAPS_MAX,
    OUTLINE_MAX,
    TOP_TERMS_MAX,
    CorpusCardRow,
    build_card,
    capability_floor,
    card_stale,
    read_card,
    write_card,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from conftest import PlanDocs

STORE_DOC = "07-store-and-retrieval.md"
INTERFACES = "10-interfaces.md"
CHARTER = "_notes/charter.md"

WRITER = "0.1.0"

COMMENT_SQL = re.compile("--[^" + chr(10) + "]{0,400}")
COMMENT_JSONC = re.compile("//[^" + chr(10) + "]{0,400}")
"""A line comment in the two languages this file strips before parsing.

Built from `chr(10)` and a bounded repeat rather than with a star-terminated character class,
because a star
immediately before a quote character reads as an italic-quote opener to the scratchpad's citation
checker and swallows the next real citation. The bound is generous: the longest comment in the
shipped DDL is under 200 characters."""


def _open(path: Path) -> sqlite3.Connection:
    """A migrated `.owstore`, the same way `test_store_maintenance.py` opens one."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    for migration in migration_files():
        conn.executescript(migration.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _kind(conn: sqlite3.Connection, name: str) -> int:
    """A `Kind` member's stored ordinal, read out of `enum_val` the way the DDL's CHECKs do."""
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = 'kind' AND name = ?", (name,)
    ).fetchone()
    return int(row[0])


ACHIEVED_PDF = {
    "spatial": "line_bbox",
    "origin_span": "exact",
    "text_span": True,
    "marks": True,
    "reading_order": "char_stream",
    "sections": "typed_levels",
    "tables": "cells",
    "math": ["latex"],
    "assets": "bytes",
    "asset_origin": True,
    "notes": "linked",
    "confidence": "page",
    "furniture": "separated",
    "round_trip": "structure",
    "forfeits": [],
}

ACHIEVED_DOCX = {
    **ACHIEVED_PDF,
    "origin_span": "none",
    "spatial": "none",
    "marks": False,
    "math": [],
    "confidence": "none",
    "forfeits": ["spatial"],
}


def _seed(conn: sqlite3.Connection) -> None:
    """Two real documents, one job document, and the rows a card reads.

    The job document is the point of the fixture and not decoration: it is the row 07:763 says a
    forgotten `NO_JOB_DOCS` would count.
    """
    conn.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES(1, 'parse.pdf.pdfium', 2, 'fp', x'00')"
    )
    docs = [
        (1, b"k1", "pdf", "policy.pdf", "ok", 2, 1000, json.dumps(ACHIEVED_PDF)),
        (2, b"k2", "docx", "benefits.docx", "partial", 1, 500, json.dumps(ACHIEVED_DOCX)),
        (3, b"k3", "owjob", "ow-job://c/a/d", "ok", 0, 9_000_000, json.dumps(ACHIEVED_PDF)),
    ]
    for doc_ord, key, fmt, uri, status, pages, source_bytes, achieved in docs:
        conn.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
            " format_evidence, source_bytes, gen, status, page_count, model_version,"
            " declared, achieved) VALUES(?,?,?,?,?,?,'{}',?,1,?,?, '1.1', '{}', ?)",
            (doc_ord, key, key, uri, "application/x", fmt, source_bytes, status, pages, achieved),
        )
    heading = _kind(conn, "heading")
    paragraph = _kind(conn, "paragraph")
    block_id = 0
    for doc_ord, pages in ((1, 2), (2, 1)):
        sibling = 0
        for page in range(pages):
            conn.execute(
                "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id)"
                " VALUES(?,1,?,0,0,1)",
                (doc_ord, page),
            )
            for ordinal in range(2):
                block_id += 1
                sibling += 1
                is_head = ordinal == 0
                trust = Trust.EXTRACTED if doc_ord == 1 else Trust.INFERRED
                quote = Quote.VERBATIM if doc_ord == 1 else Quote.NORMALIZED
                conn.execute(
                    "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer,"
                    " text, content_digest, os_kind, producer_id, method, trust, quote,"
                    " origin_operator, origin_driver, driver_schema_v, os_codec)"
                    " VALUES(?,?,1,?,?,?,?,?,0,?,x'00',4,1,0,?,?,'op','drv',1,NULL)",
                    (
                        block_id,
                        doc_ord,
                        page,
                        f"p{page}/{ordinal}",
                        f"d{doc_ord}#{block_id}",
                        sibling,
                        heading if is_head else paragraph,
                        f"Heading {doc_ord}.{page}" if is_head else "leave accrual entitlement",
                        int(trust),
                        int(quote),
                    ),
                )
    conn.execute(
        "INSERT INTO diag(doc_ord, gen, page, code, severity, component, message, fatal)"
        " VALUES(1,1,1,'OW_NEEDS_OCR','warning','parse','page render produced no text',0)"
    )
    conn.execute(
        "INSERT INTO diag(doc_ord, gen, page, code, severity, component, message, fatal)"
        " VALUES(2,1,0,'OW_NEEDS_OCR','error','parse','page render produced no text',0)"
    )
    conn.execute(
        "INSERT INTO diag(doc_ord, gen, page, code, severity, component, message, fatal)"
        " VALUES(1,1,0,'OW_SOMETHING_ELSE','info','parse','not a blocking code',0)"
    )
    conn.execute(
        "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, complete)"
        " VALUES('file:///corpus/', 4, 2, 0, 1, 1)"
    )
    conn.commit()


@pytest.fixture
def store(tmp_path: Path) -> sqlite3.Connection:
    """A migrated store with the fixture corpus in it."""
    conn = _open(tmp_path / "index.owstore")
    _seed(conn)
    return conn


def _card(conn: sqlite3.Connection, **kwargs: object) -> CorpusCardRow:
    """`build_card` with the fixture's identity filled in."""
    defaults: dict[str, object] = {
        "name": "handbook",
        "root": "file:///corpus/",
        "card_gen": 41,
        "built_at_ns": 1_756_713_123_000_000_000,
        "writer_version": WRITER,
    }
    return build_card(conn, **{**defaults, **kwargs})  # type: ignore[arg-type]


# =============================================================================================
# 1. The DDL and the column list are one list
# =============================================================================================


def test_the_column_list_is_the_ddls_in_the_ddls_order() -> None:
    """A second spelling of a column list is how an INSERT drifts from its VALUES.

    Parsed out of the migration rather than transcribed, so a column added to the table without a
    field on the row fails here instead of at the first write.
    """
    sql = next(p for p in migration_files() if p.name.startswith("0003")).read_text("utf-8")
    body = sql.split("CREATE TABLE corpus_card (", 1)[1].split("\n);", 1)[0]
    stripped = re.sub(COMMENT_SQL, "", body)
    declared = re.findall(r"(?:^|,)\s*([a-z_]+)\s+(?:INTEGER|TEXT|REAL|BLOB)", stripped)
    assert tuple(declared) == CARD_COLUMNS


def test_the_row_carries_one_field_per_column() -> None:
    """`CorpusCardRow.values()` is what the INSERT binds, so the two counts are one count."""
    assert tuple(CorpusCardRow.__dataclass_fields__) == CARD_COLUMNS


def test_no_job_docs_is_the_plans_own_literal(plan: PlanDocs) -> None:
    """07:751, verbatim, and it lives in `omniweave_core.store` because 07:750 says so."""
    plan.require()
    assert f'NO_JOB_DOCS: Final[str] = "{NO_JOB_DOCS}"' in plan.text(STORE_DOC)


# =============================================================================================
# 2. The job document, and the denominator it must not enter
# =============================================================================================


def test_the_job_document_is_not_counted(store: sqlite3.Connection) -> None:
    """Three `doc` rows, two documents. 07:763's sentence, as an assertion."""
    assert store.execute("SELECT count(*) FROM doc").fetchone()[0] == 3
    card = _card(store)
    assert card.docs_indexed == 2
    assert card.bytes == 1500  # the job row's 9 MB is not corpus bytes
    assert json.loads(card.formats_json) == {"pdf": 1, "docx": 1}


def test_the_job_document_does_not_move_the_honesty_number(store: sqlite3.Connection) -> None:
    """The denominator is BLOCKS, and a job document carries none -- so the ratio is unmoved.

    Asserted by deleting the job row and comparing, which is the only way to show that a predicate
    that happens to be vacuous today is still doing its job.
    """
    with_job = _card(store).verbatim_fraction
    store.execute("DELETE FROM doc WHERE format = 'owjob'")
    assert _card(store).verbatim_fraction == with_job


# =============================================================================================
# 3. The counts
# =============================================================================================


def test_the_counts_are_the_stores(store: sqlite3.Connection) -> None:
    """Every count on the row, against the fixture's own arithmetic."""
    card = _card(store)
    assert (card.docs_indexed, card.docs_partial, card.docs_failed) == (2, 1, 0)
    assert card.pages == 3  # 2 + 1, and the job document's zero
    assert card.blocks == 6  # three pages, two blocks each
    assert card.restriction_bits == 0
    assert card.card_gen == 41
    assert card.writer_version == WRITER


def test_docs_discovered_is_the_scope_roll_up(store: sqlite3.Connection) -> None:
    """`ingest_scope.discovered` summed, never less than what is indexed.

    The floor matters. 07:693 makes an absent scope row *"COVERAGE UNKNOWN"* and never
    "NOTHING WAS EXCLUDED", so a card reporting fewer discovered than indexed would be a third
    reading nobody asked for.
    """
    assert _card(store).docs_discovered == 4
    store.execute("DELETE FROM ingest_scope")
    assert _card(store).docs_discovered == 2


def test_the_abstract_is_never_written_here(store: sqlite3.Connection) -> None:
    """10:1089 -- *"An LLM never writes a corpus description silently"*."""
    card = _card(store)
    assert card.abstract is None
    assert card.abstract_producer_id is None


# =============================================================================================
# 4. The histograms, the honesty number, and the plan's own arithmetic
# =============================================================================================


def _worked(plan: PlanDocs) -> dict[str, object]:
    """10:1046-1071's worked `corpora-out-v1.json` entry, parsed out of the document."""
    text = plan.text(INTERFACES)
    block = text.split("### 4.2 `corpora-out-v1.json`, in full", 1)[1]
    fence = block.split("```jsonc", 1)[1].split("```", 1)[0]
    stripped = re.sub(COMMENT_JSONC, "", fence)
    return json.loads(stripped.replace('"…"', '"x"'))["corpora"][0]


def test_the_plans_worked_card_is_internally_consistent(plan: PlanDocs) -> None:
    """Both histograms sum to `blocks`, and `verbatim / blocks` is the printed fraction.

    This is what makes 10:1046-1071 a fixture rather than an illustration: the numbers were not
    typed independently, so a card that reproduces the property reproduces the plan's own model.
    """
    plan.require()
    row = _worked(plan)
    blocks = row["counts"]["blocks"]
    assert sum(row["trust_hist"].values()) == blocks
    assert sum(row["quote_hist"].values()) == blocks
    assert round(row["quote_hist"]["verbatim"] / blocks, 3) == row["verbatim_fraction"]


def test_our_histograms_have_the_same_property(store: sqlite3.Connection) -> None:
    """The property the plan's row has, asserted of a card this module built."""
    card = _card(store)
    trust_hist = json.loads(card.trust_hist_json)
    quote_hist = json.loads(card.quote_hist_json)
    assert sum(trust_hist.values()) == card.blocks
    assert sum(quote_hist.values()) == card.blocks
    assert card.verbatim_fraction == quote_hist["verbatim"] / card.blocks


def test_the_histograms_name_rungs_and_omit_the_empty_ones(store: sqlite3.Connection) -> None:
    """Keyed by member name, and a rung with no blocks is ABSENT rather than zero.

    10:1062's own `quote_hist` names three of `Quote`'s five rungs, which is only legal if an
    empty rung is omitted.
    """
    card = _card(store)
    assert json.loads(card.trust_hist_json) == {"extracted": 4, "inferred": 2}
    assert json.loads(card.quote_hist_json) == {"verbatim": 4, "normalized": 2}


def test_an_empty_corpus_has_a_zero_fraction_and_not_a_division(tmp_path: Path) -> None:
    """Zero blocks is zero verbatim blocks, and 0/0 is the one arithmetic a card may not do."""
    conn = _open(tmp_path / "empty.owstore")
    card = _card(conn)
    assert card.blocks == 0
    assert card.verbatim_fraction == 0.0


# =============================================================================================
# 5. The capability floor
# =============================================================================================


def test_the_floor_is_the_min_over_documents(store: sqlite3.Connection) -> None:
    """10:1076 -- *"**`achieved` is the MIN over drivers**, not a card's claim"*."""
    floor = json.loads(_card(store).achieved_json)
    assert floor["origin_span"] == "none"  # the docx document's rung, not the pdf's
    assert floor["spatial"] == "none"
    assert floor["confidence"] == "none"
    assert floor["marks"] is False  # AND over the two booleans
    assert floor["text_span"] is True


def test_math_intersects_and_forfeits_unions() -> None:
    """The one asymmetry: `forfeits` names what is GIVEN UP, so the floor takes the union.

    Intersecting it would make a corpus look more capable as it grows, which is the direction a
    floor may not move.
    """
    floor = capability_floor(
        [
            {**ACHIEVED_PDF, "math": ["latex", "mathml"], "forfeits": ["spatial"]},
            {**ACHIEVED_PDF, "math": ["latex"], "forfeits": ["round_trip"]},
        ]
    )
    assert floor is not None
    assert floor["math"] == ["latex"]
    assert floor["forfeits"] == ["round_trip", "spatial"]


def test_an_empty_corpus_has_no_floor() -> None:
    """`None`, not the bottom of every ladder: nobody asked, which is not the same as terrible."""
    assert capability_floor(()) is None


def test_a_rung_this_build_does_not_know_raises() -> None:
    """Sorting an unknown rung to the bottom would hide a schema mismatch inside a statistic."""
    with pytest.raises(StoreError) as caught:
        capability_floor([{**ACHIEVED_PDF, "origin_span": "approximate"}])
    assert "origin_span" in str(caught.value)
    assert caught.value.fix


def test_a_missing_ladder_key_reads_as_the_lowest_rung() -> None:
    """`PARSE_LADDERS` fixes element 0 as the only default that cannot over-claim."""
    floor = capability_floor([{k: v for k, v in ACHIEVED_PDF.items() if k != "tables"}])
    assert floor is not None
    assert floor["tables"] == "none"


# =============================================================================================
# 6. Outline, terms, and the gap join
# =============================================================================================


def test_the_outline_is_deterministic_and_capped(store: sqlite3.Connection) -> None:
    """charter.md:6718's *"<= 40 top-level titles, sampled DETERMINISTICALLY"*.

    Two builds over one store produce one outline, because the order is `(doc_ord, page, ord)` and
    not a score.
    """
    first = json.loads(_card(store).outline_json)
    assert first == ["Heading 1.0", "Heading 1.1", "Heading 2.0"]
    assert first == json.loads(_card(store).outline_json)
    assert len(first) <= OUTLINE_MAX


def test_the_top_terms_come_off_the_fts_index(store: sqlite3.Connection) -> None:
    """charter.md:6719 -- *"from an fts5vocab('block_fts','row') table. NOT 'free'"*.

    The fixture writes no FTS rows, so this asserts the other half of the contract: a corpus whose
    lexical index is not built yields no terms and never an exception.
    """
    terms = json.loads(_card(store).top_terms_json)
    assert isinstance(terms, list)
    assert len(terms) <= TOP_TERMS_MAX


def test_no_codes_means_no_gaps(store: sqlite3.Connection) -> None:
    """The fail-closed default: a card that invented a blocking set would arm gate 9 on its own."""
    assert json.loads(_card(store).gaps_json) == []


def test_the_gap_join_groups_by_code_and_counts_docs_and_pages(
    store: sqlite3.Connection,
) -> None:
    """10:1085's join, and the severity is the WORST seen for that code, not the first."""
    card = _card(store, blocking_codes=ABSENCE_BLOCKING_DIAGS)
    (gap,) = card.gaps
    assert gap.symbol == "OW_NEEDS_OCR"
    assert (gap.docs, gap.pages) == (2, 2)
    assert gap.severity == "error"
    assert len(card.gaps) <= GAPS_MAX


def test_an_unblocked_diag_code_is_not_a_gap(store: sqlite3.Connection) -> None:
    """`OW_SOMETHING_ELSE` is in `diag` and is not in the blocking set, so it is not a gap.

    `ABSENCE_BLOCKING_DIAGS`'s own docstring says a code outside the set is a diagnostic
    that does not block an absence claim -- a different and equally deliberate fact -- and
    that is this repository's prose rather than a plan line, so the card must not widen the
    join on its own.
    """
    codes = {gap.symbol for gap in _card(store, blocking_codes=ABSENCE_BLOCKING_DIAGS).gaps}
    assert "OW_SOMETHING_ELSE" not in codes


# =============================================================================================
# 7. The three columns nothing can fill
# =============================================================================================


def test_no_migration_carries_a_language_or_a_date_column() -> None:
    """D287. `langs_json` and `date_range_json` are NOT NULL and have no source.

    A grep over the DDL rather than over the reader, because the claim is about the schema: the
    day a `lang` column lands, this test fails and the two columns can be filled.
    """
    ddl = "\n".join(p.read_text("utf-8") for p in migration_files())
    body = re.sub(COMMENT_SQL, "", ddl)
    assert not re.search(r"^\s*lang\s+TEXT", body, re.MULTILINE)
    assert not re.search(r"^\s*doc_(date|created|modified)\w*\s+(TEXT|INTEGER)", body, re.MULTILINE)
    assert "date_range" not in body.replace("date_range_json", "")


def test_langs_and_date_range_are_the_empty_shapes(store: sqlite3.Connection) -> None:
    """The empty answer the wire form can carry. 18:685 types the second one exactly this way."""
    card = _card(store)
    assert json.loads(card.langs_json) == {}
    assert json.loads(card.date_range_json) == {"lo": None, "hi": None}


def test_not_one_blocking_diag_symbol_has_a_register_row() -> None:
    """D289. `Gap.code`, `.meaning` and `.fix` all come from `codes.toml`, which has none of them.

    Thirteen symbols, zero rows -- so 18:703's *"never empty"* cannot hold for `fix` today. The
    assertion is written as a count so that the day W1.3 adds the rows, this test names the change
    rather than silently passing.
    """
    register = load_register()
    registered = [s for s in ABSENCE_BLOCKING_DIAGS if s in register.by_symbol]
    assert registered == []
    assert len(ABSENCE_BLOCKING_DIAGS) == 13


def test_a_gap_reports_whether_its_code_resolved(store: sqlite3.Connection) -> None:
    """The three register-sourced fields are empty together, and `registered` is their predicate."""
    (gap,) = _card(store, blocking_codes=ABSENCE_BLOCKING_DIAGS, register=load_register()).gaps
    assert not gap.registered
    assert (gap.code, gap.meaning, gap.fix) == ("", "", "")
    assert gap.symbol and gap.severity  # what the store really knows is still there


# =============================================================================================
# 8. Write, read, and staleness
# =============================================================================================


def test_write_then_read_round_trips(store: sqlite3.Connection) -> None:
    """The row goes to SQLite and comes back equal, JSON columns included."""
    card = _card(store)
    write_card(store, card)
    assert read_card(store) == card
    assert read_card(store, 41) == card
    assert read_card(store, 40) is None


def test_the_reader_takes_the_newest_generation(store: sqlite3.Connection) -> None:
    """10:1010 -- *"the full `corpus_card` row at `max(card_gen)`"*."""
    write_card(store, _card(store, card_gen=40))
    write_card(store, _card(store, card_gen=41))
    newest = read_card(store)
    assert newest is not None
    assert newest.card_gen == 41


def test_a_rebuild_at_one_generation_replaces(store: sqlite3.Connection) -> None:
    """The card is [DER]: rebuilding it must be an idempotent write, not a constraint failure."""
    write_card(store, _card(store))
    write_card(store, _card(store, root="file:///moved/"))
    row = read_card(store)
    assert row is not None
    assert row.root == "file:///moved/"
    assert store.execute("SELECT count(*) FROM corpus_card").fetchone()[0] == 1


def test_staleness_is_reported_and_never_repaired(store: sqlite3.Connection) -> None:
    """10:1036-1039: missing or older than the newest `doc.gen`, and never silently recomputed."""
    assert card_stale(store, None) is True
    card = _card(store, card_gen=1)
    write_card(store, card)
    assert card_stale(store, card) is False
    store.execute("UPDATE doc SET gen = 2 WHERE doc_ord = 1")
    assert card_stale(store, card) is True
    assert store.execute("SELECT count(*) FROM corpus_card").fetchone()[0] == 1


def test_the_json_columns_are_canonical(store: sqlite3.Connection) -> None:
    """Sorted keys and no spaces, so two cards over one store diff to nothing."""
    card = _card(store)
    assert card.formats_json == '{"docx":1,"pdf":1}'
    assert " " not in card.trust_hist_json
