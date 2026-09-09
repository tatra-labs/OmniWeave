"""`omniweave_core.store.doc.DocSink` -- the eleven L2 write methods, against a real store.

Every test here drives a `.owstore` built by the four shipped migrations in `tmp_path`, through a
real `StoreThread`, and asserts what is ON DISK afterwards. That is deliberate and it is what the
module needs: `DocSink` is the only writer of L2, so a fake connection would assert this file's
idea of the schema rather than the schema, and the two rules that matter most -- "rows are durable
and invisible while `g_t > doc.gen`" (03:594) and "a diagnostic about page 3,000 survives a crash
at page 3,001" (03:593) -- are only observable by reopening the file.

Every read goes through `store.sqlite.connect`, never through a second connection helper, so
INV-17's "one module connects" holds even in the test. `import sqlite3` below carries
`# noqa: TID251` for exactly one reason and it is named at its use site: the shard-ordinal test
asserts that the store's own interpolated `CHECK ((block_id >> 48) = 0)` refuses a foreign shard,
and the only way to assert a refusal SQLite makes is to name `sqlite3.IntegrityError`. The
per-file-ignore in `pyproject.toml` covers `store/*.py`, not `tests/`, so the directive is here.

Specified in 03-document-model.md section 2.10 (:538-620), section 1.1 (:54-86), section 2.9
(:440-478), section 6.2-6.5, section 8.2-8.4, section 9, section 10.1-10.2 and section 11.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import re
import sqlite3  # noqa: TID251 -- the store's own IntegrityError is the assertion.
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from conftest import PlanDocs
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import ModelError, ResourceLimit
from omniweave_core.model import enums
from omniweave_core.model.block import (
    BlockDraft,
    BlockId,
    Capabilities,
    CellPos,
    Mark,
)
from omniweave_core.model.enums import Kind, Layer, Method, PageKind, Quote, RelKind, Trust
from omniweave_core.model.grid import Grid, build_grid
from omniweave_core.model.records import AssetDraft, Diag, DocRecord, PageRecord
from omniweave_core.model.spans import OriginBytes, OriginNone, OriginPixels, Quad
from omniweave_core.store import DocSink as DocSinkProtocol
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import _MAX_QUOTE_BY_OS_KIND, DocSink

NOW_NS = 1_757_400_000_000_000_000
"""A fixed wall clock. `time.time` is banned in library code and injected everywhere in the
store, so a test reading the ambient clock would assert against a value production cannot make."""

SCORE_KINDS = frozenset({"layout_softmax", "ocr_char_conf"})
"""The `tools/scorekinds.toml` register, handed in. That file does not exist in the tree; the
module docstring of `store/doc.py` records it, and the sink takes the register from its caller for
the same reason it takes the clock and the ids from its caller."""

DECLARED = Capabilities(
    spatial="block_bbox",
    origin_span="exact",
    text_span=True,
    marks=True,
    reading_order="source",
    sections="typed_levels",
    tables="cells_with_spans",
    math=frozenset({"latex"}),
    assets="bytes",
    asset_origin=True,
    notes="linked",
    confidence="element",
    furniture="separated",
    round_trip="structure",
)
FLOOR = Capabilities(
    spatial="none",
    origin_span="none",
    text_span=False,
    marks=False,
    reading_order="raster",
    sections="none",
    tables="none",
    math=frozenset(),
    assets="none",
    asset_origin=False,
    notes="none",
    confidence="none",
    furniture="destroyed",
    round_trip="none",
)


# ---------------------------------------------------------------------------------------------
# The fixtures: a real store, a real CAS, a real producer row.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Harness:
    """One migrated `.owstore`, its CAS root and the `producer_id` every row is stamped with."""

    path: Path
    cas: Path
    producer_id: int


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    path = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cas.mkdir()
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.pdf', 1, 'abc123', X'00')"
        )
        producer_id = int(cursor.lastrowid or 0)
        connection.commit()
    finally:
        connection.close()
    return Harness(path=path, cas=cas, producer_id=producer_id)


def sink(harness: Harness, thread: ow.StoreThread, **kw: Any) -> DocSink:
    """A `DocSink` over an open `StoreThread`, with the harness's provenance already stamped."""
    defaults: dict[str, Any] = {
        "producer_id": harness.producer_id,
        "origin_operator": "parse.pdf",
        "origin_driver": "parse.pdf.pdfium",
        "driver_schema_v": 1,
        "blobs": BlobStore(harness.cas),
        "score_kinds": SCORE_KINDS,
        "restriction_bits": 0,
    }
    return DocSink(thread, **(defaults | kw))


def doc_record(key: int = 1, **kw: Any) -> DocRecord:
    record = DocRecord(
        doc_ord=0,
        doc_key=bytes([key]) * 16,
        gen=0,
        source_sha256=bytes([key]) * 32,
        normalizer="canonical/1",
        uri=f"file:///corpus/contract-{key}.pdf",
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({"magic": "%PDF-1.7"}),
        source_bytes=4096,
        status="ok",
        page_count=None,
        model_version="1.1",
        declared=DECLARED,
        achieved=FLOOR,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({"parse": 42}),
    )
    return replace(record, **kw)


def page_record(page: int, **kw: Any) -> PageRecord:
    record = PageRecord(
        page=page,
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=595_280,
        h_mpt=841_890,
        rotation=0,
        quad_origin="topleft",
        method=Method.NATIVE,
        status="ok",
    )
    return replace(record, **kw)


def root_draft() -> BlockDraft:
    return BlockDraft(
        kind=Kind.DOCUMENT,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.SYNTHETIC,
    )


def text_draft(parent: BlockId, kind: Kind, text: str, **kw: Any) -> BlockDraft:
    draft = BlockDraft(
        kind=kind,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.NORMALIZED,
        parent=parent,
        text=text,
        origin=OriginBytes(part="file", start=0, length=len(text), codec="utf-8/strict"),
    )
    for name, value in kw.items():
        setattr(draft, name, value)
    return draft


def open_store(harness: Harness) -> ow.StoreThread:
    return ow.StoreThread(lambda: ow.connect(harness.path))


def read(harness: Harness, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Reopen the file and read it. Reopening is the point: it proves the rows are DURABLE."""
    connection = ow.connect(harness.path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def counts(harness: Harness, *tables: str) -> dict[str, int]:
    return {
        table: read(harness, f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608
        for table in tables
    }


# ---------------------------------------------------------------------------------------------
# 1. The full happy path: two pages, a page-crossing merged table, all eleven methods.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Written:
    """What `write_happy_path` minted, so an assertion can name a block rather than an integer."""

    record: DocRecord
    root: BlockId
    heading: BlockId
    paragraph: BlockId
    table: BlockId
    cells: tuple[BlockId, ...]
    asset_id: int


def write_happy_path(
    harness: Harness, *, key: int = 1, stop_after_page: int | None = None
) -> Written:
    """Drive all eleven methods over a two-page document whose table crosses the page break.

    The table is 03 section 12.3's own worked multi-page case -- "A table crossing a page break is
    ONE `table` block at the first page, whose cells carry their own `page`" -- so this fixture
    exercises the closure pass, `add_grid` "in the transaction of its LAST page", and a cell whose
    `addr` is built from a parent minted in an earlier transaction, all at once.

    `stop_after_page` returns WITHOUT calling `end_page` for the next page, which is how the crash
    tests get a page's worth of writes that never committed.
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        record = writer.begin_doc(doc_record(key))

        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        heading = writer.add_block(
            text_draft(root, Kind.HEADING, "Master Services Agreement", payload={"level": 1})
        )
        writer.add_marks(heading, [Mark(a=0, b=6, kind="bold"), Mark(a=0, b=0, kind="anchor")])
        table = writer.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
                label="Fees",
            )
        )
        cells = [
            writer.add_block(cell_draft(table, "Region", CellPos(0, 0))),
            writer.add_block(cell_draft(table, "FY2024", CellPos(0, 1))),
        ]
        writer.add_part("file", io.BytesIO(b"%PDF-1.7 ..."), _sha(b"%PDF-1.7 ..."), 12)
        writer.diag(
            Diag(
                code="OW_TEXT_SPLIT",
                severity="info",
                component="parse.pdf.pdfium",
                message="a run was split across two spans",
                page=0,
            )
        )
        writer.end_page({"blocks": 4})
        if stop_after_page == 0:
            return Written(record, root, heading, BlockId(0), table, tuple(cells), 0)

        writer.begin_page(page_record(1))
        paragraph = writer.add_block(
            text_draft(root, Kind.PARAGRAPH, "Fees are payable within 30 days.")
        )
        cells.append(writer.add_block(cell_draft(table, "Cloud", CellPos(1, 0, 1, 2))))
        writer.add_rel(heading, paragraph, RelKind.HEADING_OF, trust=Trust.INFERRED)
        payload = b"\x89PNG\r\n\x1a\n logo bytes"
        asset_id = writer.add_asset(
            AssetDraft(
                media_type="image/png",
                sha256=_sha(payload),
                byte_len=len(payload),
                origin_part="pdf:page=1/image=0",
                width=64,
                height=64,
            ),
            io.BytesIO(payload),
        )
        writer.add_grid(
            table,
            build_grid(
                (
                    CellDraft(int(block), position)
                    for block, position in zip(cells, POSITIONS, strict=True)
                ),
                header_rows=1,
                recon=("native_xml", 0.98),
                diag=lambda _d: None,
            ),
        )
        writer.end_page({"blocks": 2})
        if stop_after_page == 1:
            return Written(record, root, heading, paragraph, table, tuple(cells), asset_id)

        final = writer.end_doc("ok")
    return Written(final, root, heading, paragraph, table, tuple(cells), asset_id)


POSITIONS = (CellPos(0, 0), CellPos(0, 1), CellPos(1, 0, 1, 2))


@dataclass(frozen=True, slots=True)
class CellDraft:
    """03:337-338's `CellDraft`, read structurally by `build_grid`.

    Declared here and not imported because `model/block.py` has not declared it -- `grid.py`'s
    `_cell_position` says so in its own docstring and reports the required edit. This is the test's
    stand-in and it carries exactly the two attributes the plan prints.
    """

    id: int
    pos: CellPos


def cell_draft(table: BlockId, text: str, pos: CellPos) -> BlockDraft:
    return BlockDraft(
        kind=Kind.TABLE_CELL,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.NORMALIZED,
        parent=table,
        text=text,
        cell=pos,
        origin=OriginBytes(part="file", start=0, length=len(text), codec="utf-8/strict"),
    )


def _sha(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def test_the_happy_path_writes_every_l2_table_and_leaves_the_store_referentially_sound(
    harness: Harness,
) -> None:
    """Two pages, a merged page-crossing table, and all eleven methods, against a real store."""
    written = write_happy_path(harness)

    assert counts(
        harness,
        "doc",
        "page",
        "block",
        "mark",
        "rel",
        "table_meta",
        "cell",
        "grid_slot",
        "asset",
        "part",
    ) == {
        "doc": 1,
        "page": 2,
        "block": 7,
        "mark": 2,
        "rel": 1,
        "table_meta": 1,
        "cell": 3,
        # has_merges = 1, so the cover map is TOTAL over sum(row_len) = 4 (03:1902-1907).
        "grid_slot": 4,
        "asset": 1,
        "part": 1,
    }
    assert read(harness, "PRAGMA foreign_key_check") == []
    assert read(harness, "PRAGMA integrity_check")[0][0] == "ok"
    assert written.record.gen == 1, "end_doc returns the record at the COMMITTED head (03:596)"
    assert written.record.doc_ord == 1, "begin_doc assigns doc_ord on first sight (03:576)"


def test_the_addresses_are_section_6_2s_three_rules_including_a_cell_across_a_page_break(
    harness: Harness,
) -> None:
    """`doc`, `p<page>/<page-root ordinal>`, `.../r<r>c<c>`, and the page ANCHOR (M-INV-2).

    The third cell is minted on page 1 under a table minted on page 0, so its address's page
    component is its ANCHOR's page and not its own -- which is 03:1100-1103's rule 2 and the
    property that makes `Doc.blocks(pages=...)` able to return page-1 cells without the page-0
    table block.
    """
    write_happy_path(harness)
    rows = dict(read(harness, "SELECT addr, page FROM block ORDER BY block_id"))
    assert rows == {
        "doc": 0,
        "p0/0": 0,
        "p0/1": 0,
        "p0/1/r0c0": 0,
        "p0/1/r0c1": 0,
        "p1/0": 1,
        "p0/1/r1c0": 1,
    }


def test_ord_is_dense_from_zero_among_siblings_while_the_addr_step_is_page_local(
    harness: Harness,
) -> None:
    """`block_sib` is UNIQUE over the whole generation; the addr's first step is per page (03:1113).

    The paragraph is the first page-root block of page 1, so its addr step is `0` while its `ord`
    among the root's children is `3`. Conflating the two is what would make re-parsing page 12 of
    a 5,000-page document renumber pages 13 through 4,999.
    """
    write_happy_path(harness)
    rows = read(harness, "SELECT addr, ord FROM block ORDER BY block_id")
    assert dict(rows) == {
        "doc": 0,
        "p0/0": 0,
        "p0/1": 1,
        "p0/1/r0c0": 0,
        "p0/1/r0c1": 1,
        "p1/0": 2,
        "p0/1/r1c0": 2,
    }
    paragraph = read(harness, "SELECT ord, addr FROM block WHERE addr = 'p1/0'")
    assert paragraph == [(2, "p1/0")], "the root's third child, and page 1's FIRST page root"


def test_the_closure_pass_finalises_only_the_containers_whose_subtree_crosses_a_page(
    harness: Harness,
) -> None:
    """03:1220-1234. A digest read from an uncommitted generation is not final until this runs.

    The table's provisional digest is written at `end_page(0)` over the cell it had then; the
    second cell lands on page 1, so `end_doc` must rewrite it. The heading's subtree closed on its
    own page and must NOT move -- which is what makes the pass `O(cross-page containers)` rather
    than `O(blocks)`, and what 03:1236-1238 means by "a `content_digest` read from an uncommitted
    generation is not final".
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        heading = writer.add_block(text_draft(root, Kind.HEADING, "H", payload={"level": 1}))
        table = writer.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
            )
        )
        first = writer.add_block(cell_draft(table, "a", CellPos(0, 0)))
        writer.end_page({})
        staged = dict(read(harness, "SELECT block_id, content_digest FROM block"))

        writer.begin_page(page_record(1))
        second = writer.add_block(cell_draft(table, "b", CellPos(1, 0)))
        writer.add_grid(
            table,
            build_grid(
                (CellDraft(int(first), CellPos(0, 0)), CellDraft(int(second), CellPos(1, 0))),
                diag=lambda _d: None,
            ),
        )
        writer.end_page({})
        writer.end_doc("ok")

    final = dict(read(harness, "SELECT block_id, content_digest FROM block"))
    assert final[int(heading)] == staged[int(heading)], "a same-page subtree was already final"
    assert final[int(first)] == staged[int(first)], "a leaf is never provisional"
    assert final[int(table)] != staged[int(table)], "the cross-page table was re-digested"
    assert final[int(root)] != staged[int(root)], "the root is always in the set (03:1232)"


# ---------------------------------------------------------------------------------------------
# 2. Staging invisibility -- 03 section 2.9's central claim.
# ---------------------------------------------------------------------------------------------


def test_the_staged_generation_is_durable_and_completely_invisible_before_end_doc(
    harness: Harness,
) -> None:
    """Both halves, because either alone is worthless.

    03:75-80: *"Nothing is visible before step 4. Every reader resolves through `ow_block_head`,
    which joins `block.gen = doc.gen`; a crash at page 3,000 of 5,000 leaves 3,000 durable but
    invisible pages."* A test that only asserted the rows exist would pass against a sink that
    committed them at `doc.gen`; a test that only asserted `ow_block_head` is empty would pass
    against a sink that wrote nothing at all. The pair is the evidence.
    """
    write_happy_path(harness, stop_after_page=1)

    assert read(harness, "SELECT gen FROM doc") == [(0,)], "gen 0 means NO committed generation"
    assert read(harness, "SELECT count(*) FROM ow_block_head") == [(0,)]
    assert read(harness, "SELECT count(*) FROM block WHERE gen = 1") == [(7,)]
    assert read(harness, "SELECT count(*) FROM page WHERE gen = 1") == [(2,)]
    # Durable: the file was closed and reopened by `read()` between the two assertions above.
    assert read(harness, "PRAGMA foreign_key_check") == []


def test_a_crash_between_two_end_page_calls_leaves_page_n_durable_and_page_n_plus_one_absent(
    harness: Harness,
) -> None:
    """03:594's "commits ONE transaction", seen from the failure side.

    Page 1's blocks are staged and its `end_page` is never called, so the whole page vanishes with
    the process while page 0's rows stay on disk -- and both remain invisible.
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        writer.add_block(text_draft(root, Kind.PARAGRAPH, "page zero"))
        writer.end_page({})
        writer.begin_page(page_record(1))
        writer.add_block(text_draft(root, Kind.PARAGRAPH, "page one"))
        # No end_page: the process "crashes" here.

    assert read(harness, "SELECT count(*) FROM page") == [(1,)]
    assert read(harness, "SELECT text FROM block WHERE text IS NOT NULL") == [("page zero",)]
    assert read(harness, "SELECT gen FROM doc") == [(0,)]


def test_a_diagnostic_about_page_three_survives_a_crash_during_page_four(harness: Harness) -> None:
    """03:593 in as many words, and the reason `diag()` has no transaction of its own.

    *"a `diag` row inside the CURRENT page's transaction, so a diagnostic about page 3,000 survives
    a crash at page 3,001"*. Page 4 is simulated by never calling its `end_page`.
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(3))
        root = writer.add_block(root_draft())
        writer.diag(
            Diag(
                code="OW_QUAD_NO_DPI",
                severity="warning",
                component="parse.pdf.pdfium",
                message="page 3 declared px with no dpi",
                page=3,
            )
        )
        writer.end_page({})
        writer.begin_page(page_record(4))
        writer.add_block(text_draft(root, Kind.PARAGRAPH, "page four"))
        writer.diag(
            Diag(
                code="OW_TEXT_SPLIT",
                severity="warning",
                component="parse.pdf.pdfium",
                message="page 4 diagnostic",
                page=4,
            )
        )
        # No end_page for page 4.

    assert read(harness, "SELECT code, page FROM diag ORDER BY rowid") == [("OW_QUAD_NO_DPI", 3)]


# ---------------------------------------------------------------------------------------------
# 3. `cite` -- minted from `doc.next_cite_n`, durable, and carried by `rebind`.
# ---------------------------------------------------------------------------------------------


def test_cite_is_minted_from_doc_next_cite_n_and_the_counter_is_persisted(
    harness: Harness,
) -> None:
    """03:1140-1152. `n` is per-`doc_key`, monotonic, never reset and never reused.

    The counter is written in the same transaction as the rows that consumed it, so a reopened
    store cannot re-issue a number a committed block already wears.
    """
    write_happy_path(harness)
    cites = [row[0] for row in read(harness, "SELECT cite FROM block ORDER BY block_id")]
    assert cites == ["d1#1", "d1#2", "d1#3", "d1#4", "d1#5", "d1#6", "d1#7"]
    assert read(harness, "SELECT next_cite_n FROM doc") == [(8,)]


def test_two_documents_cites_never_collide_because_the_doc_ord_is_inside_the_name(
    harness: Harness,
) -> None:
    """`cite := [corpus ":"] "d" doc_ord "#" n` (03:1140), and `block_cite` is `(doc_ord, cite)`."""
    write_happy_path(harness, key=1)
    write_happy_path(harness, key=2)
    by_doc = read(harness, "SELECT doc_ord, cite FROM block ORDER BY doc_ord, block_id")
    assert {doc for doc, _ in by_doc} == {1, 2}
    assert len({cite for _, cite in by_doc}) == len(by_doc), "one cite names at most one row"
    assert read(harness, "SELECT count(*) FROM block WHERE cite = 'd2#1'") == [(1,)]


def test_a_re_parse_carries_every_cite_and_block_id_and_advances_the_generation(
    harness: Harness,
) -> None:
    """P21: `carried == n_blocks`, `created == 0`, `retired == 0`, `doc.gen` + 1.

    This is `rebind()` wired through `end_doc` (03:70). An identical re-parse matches every block
    on rule 1 -- equal `content_digest` under the same parent -- so the durable `block_id`s and the
    shipped `cite`s survive, which is the whole reason the pass exists: "a cite is a shipped,
    durable name; re-minting it on re-parse would re-point every citation already in someone's
    document" (03:1284-1287).
    """
    write_happy_path(harness)
    before = read(harness, "SELECT block_id, cite, addr, revision FROM block ORDER BY block_id")
    assert read(harness, "SELECT gen FROM doc") == [(1,)]

    write_happy_path(harness)

    after = read(harness, "SELECT block_id, cite, addr, revision FROM block ORDER BY block_id")
    assert after == before, "every block_id, cite and addr carried, and no revision moved"
    assert read(harness, "SELECT gen FROM doc") == [(2,)]
    assert read(harness, "SELECT count(*) FROM block WHERE gen = 2") == [(7,)]
    assert read(harness, "SELECT count(*) FROM block_history") == [(0,)], "nothing retired"
    assert read(harness, "SELECT count(*) FROM ow_block_head") == [(7,)]
    assert read(harness, "PRAGMA foreign_key_check") == []
    # The staged twins' cites became permanent gaps, which is correct (03:1155-1159).
    assert read(harness, "SELECT next_cite_n FROM doc") == [(15,)]


def test_a_re_parse_that_matches_nothing_quarantines_and_does_not_move_the_head(
    harness: Harness,
) -> None:
    """Below `threshold` the generation is durable, invisible and inspectable (03:1298-1302).

    `doc.gen` does not move, `end_doc` returns the record at the OLD head, and the refusal is
    RECORDED as `OW_REBIND_UNEXPLAINED` rather than raised -- `model/rebind.py` is explicit that
    "the raise belongs to `end_doc()`'s caller".
    """
    write_happy_path(harness)
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        for n in range(6):
            writer.add_block(text_draft(root, Kind.PARAGRAPH, f"entirely different text {n}"))
        writer.end_page({})
        returned = writer.end_doc("ok")

    assert returned.gen == 1, "the post-commit record is the record at the COMMITTED head"
    assert read(harness, "SELECT gen FROM doc") == [(1,)]
    assert read(harness, "SELECT count(*) FROM block WHERE gen = 2") == [(7,)], "durable"
    assert read(harness, "SELECT count(*) FROM ow_block_head") == [(7,)], "still generation 1"
    quarantine = read(
        harness, "SELECT severity, fatal FROM diag WHERE code = 'OW_REBIND_UNEXPLAINED'"
    )
    assert quarantine == [("error", 1)]


# ---------------------------------------------------------------------------------------------
# 4. The clamps -- lowered, not rejected, and the original claim is recorded.
# ---------------------------------------------------------------------------------------------


def test_a_verbatim_claim_on_a_pixels_origin_is_stored_lowered_and_the_claim_is_recorded(
    harness: Harness,
) -> None:
    """`MAX_QUOTE_BY_OS_KIND[PIXELS] = RECONSTRUCTED` (03:1675-1681). A ceiling, never a floor.

    *"the polygon is the address; there is no character source"*. The block is STORED, not
    rejected, and `OW_QUOTE_CLAMPED` carries the driver's original claim so over-claiming is
    measurable rather than silently corrected (03:1697).
    """
    quad = Quad(0, 0, 1000, 0, 1000, 1000, 0, 1000)
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0, method=Method.OCR_PAGE))
        root = writer.add_block(root_draft())
        writer.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.OCR_PAGE,
                trust=Trust.EXTRACTED,
                quote=Quote.VERBATIM,
                parent=root,
                text="scanned line",
                quad=quad,
                origin=OriginPixels(page=0, quad=quad),
            )
        )
        writer.end_page({})
        writer.end_doc("ok")

    stored = read(harness, "SELECT quote, trust FROM block WHERE text = 'scanned line'")
    assert stored == [(int(Quote.RECONSTRUCTED), int(Trust.INFERRED))]
    clamps = dict(read(harness, "SELECT code, count(*) FROM diag GROUP BY code"))
    assert clamps["OW_QUOTE_CLAMPED"] == 1
    assert clamps["OW_GRAPH_TRUST_CLAMPED"] == 1, "ocr_page caps trust at inferred (03:1616)"
    detail = read(harness, "SELECT detail FROM diag WHERE code = 'OW_QUOTE_CLAMPED'")[0][0]
    assert '"claimed":"verbatim"' in detail and '"stored":"reconstructed"' in detail


def test_a_derived_operator_cannot_launder_the_none_ceiling_up_to_normalized(
    harness: Harness,
) -> None:
    """`clamp_quote`'s SECOND clamp (03:1683-1686), which `os_kind` alone cannot see.

    *"a table synopsis has `os_kind = none` and `origin_operator = 'derive.table'`, so it lands at
    `SYNTHETIC` rather than inheriting `NORMALIZED`"* -- "a derived block quotes nothing by
    inheritance".
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread, origin_operator="derive.table")
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        writer.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.HEURISTIC,
                trust=Trust.INFERRED,
                quote=Quote.NORMALIZED,
                parent=root,
                text="Three rows, two columns.",
                origin=OriginNone(),
            )
        )
        writer.end_page({})
        writer.end_doc("ok")

    assert read(harness, "SELECT quote FROM block WHERE text LIKE 'Three%'") == [
        (int(Quote.SYNTHETIC),)
    ]


def test_the_quote_ceiling_table_matches_the_plans_printed_fence(plan: PlanDocs) -> None:
    """`_MAX_QUOTE_BY_OS_KIND` against 03 section 8.3's own fence, member for member.

    The register has no public home yet -- `model/__init__.py:80` still lists
    `MAX_QUOTE_BY_OS_KIND` as owed by P2 -- so this asserts the private transcription against the
    document rather than against a second copy of itself.
    """
    plan.require()
    body = plan.text("03-document-model.md")
    fence = re.search(
        r"MAX_QUOTE_BY_OS_KIND: Mapping\[OsKind, Quote\] = \{(.*?)\}", body, re.DOTALL
    )
    assert fence is not None, "03 section 8.3 prints the mapping exactly once"
    printed = {
        f"OsKind.{name}": f"Quote.{value}"
        for name, value in re.findall(r"OsKind\.(\w+):\s*(\w+)", fence.group(1))
    }
    assert printed == {
        f"OsKind.{kind.name}": f"Quote.{quote.name}"
        for kind, quote in _MAX_QUOTE_BY_OS_KIND.items()
    }


def test_the_private_quote_ceiling_agrees_with_model_enums_the_moment_that_name_lands() -> None:
    """A parity guard against the day `MAX_QUOTE_BY_OS_KIND` gets its public home.

    `store/doc.py`'s docstring reports the required edit: the register belongs beside
    `MAX_TRUST_BY_METHOD` in `model/enums.py`. Until it arrives this skips; the moment it does,
    a disagreement between the two copies fails here instead of shipping.
    """
    public = getattr(enums, "MAX_QUOTE_BY_OS_KIND", None)
    if public is None:
        pytest.skip("model.enums does not declare MAX_QUOTE_BY_OS_KIND yet (a required edit)")
    assert dict(public) == dict(_MAX_QUOTE_BY_OS_KIND)


# ---------------------------------------------------------------------------------------------
# 5. `score` / `score_kind` -- nullable together, and the register is not optional.
# ---------------------------------------------------------------------------------------------


def _one_scored(harness: Harness, **kw: Any) -> None:
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        writer.add_block(text_draft(root, Kind.PARAGRAPH, "scored", **kw))
        writer.end_page({})
        writer.end_doc("ok")


def test_an_unregistered_score_kind_raises_at_add_block(harness: Harness) -> None:
    """03:295 and 03:1715-1717; INV-19's architectural `A` enforcer (01:531).

    *"an unregistered `score_kind` raises at `DocSink.add_block` rather than being stored and
    puzzled over later. A layout softmax and a token probability are not comparable and must not
    share a column without a discriminator."*
    """
    with pytest.raises(ModelError) as caught:
        _one_scored(harness, score=0.7, score_kind="vibes")
    assert caught.value.code() == "OW_SCORE_KIND_UNREGISTERED"
    assert "vibes" in str(caught.value)
    assert read(harness, "SELECT count(*) FROM block") == [(0,)], "nothing was written"


def test_score_and_score_kind_are_refused_individually_and_accepted_together(
    harness: Harness,
) -> None:
    """Nullable TOGETHER (03:1713), which is also a DDL CHECK -- two enforcers, one rule."""
    with pytest.raises(ModelError, match="TOGETHER"):
        _one_scored(harness, score=0.7)
    with pytest.raises(ModelError, match="TOGETHER"):
        _one_scored(harness, score_kind="layout_softmax")

    _one_scored(harness, score=0.7, score_kind="layout_softmax")
    assert read(harness, "SELECT score, score_kind FROM block WHERE text = 'scored'") == [
        (0.7, "layout_softmax")
    ]


def test_an_element_score_raises_the_achieved_confidence_grain_to_element(
    harness: Harness,
) -> None:
    """03:519's derivation: "the finest grain at which a score is non-NULL"."""
    _one_scored(harness, score=0.7, score_kind="layout_softmax")
    achieved = read(harness, "SELECT achieved FROM doc")[0][0]
    assert '"confidence":"element"' in achieved


# ---------------------------------------------------------------------------------------------
# 6. Tables -- `grid_slot` only when merged, and row-major arrival.
# ---------------------------------------------------------------------------------------------


def _table_document(harness: Harness, positions: tuple[CellPos, ...]) -> None:
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        table = writer.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
            )
        )
        cells = [writer.add_block(cell_draft(table, f"c{n}", p)) for n, p in enumerate(positions)]
        writer.add_grid(
            table,
            build_grid(
                (CellDraft(int(b), p) for b, p in zip(cells, positions, strict=True)),
                diag=lambda _d: None,
            ),
        )
        writer.end_page({})
        writer.end_doc("ok")


def test_a_merge_free_table_writes_zero_grid_slot_rows(harness: Harness) -> None:
    """03:1902-1907: *"a merge-free 4M-cell sheet is 4,000,000 ordinary Blocks and ZERO grid_slot
    rows"*, and `slot(r, c)` is arithmetic against `cell`."""
    _table_document(harness, (CellPos(0, 0), CellPos(0, 1), CellPos(1, 0), CellPos(1, 1)))
    assert read(harness, "SELECT count(*) FROM grid_slot") == [(0,)]
    assert read(harness, "SELECT has_merges FROM table_meta") == [(0,)]
    assert read(harness, "SELECT count(*) FROM cell") == [(4,)]


def test_a_merged_table_materialises_a_total_cover_map(harness: Harness) -> None:
    """When `has_merges = 1` the map holds ALL `sum(row_len)` positions, an origin mapping to
    itself (03:1902-1905) -- because the charter's own neighbour query returns nothing for an
    unmerged position otherwise."""
    _table_document(harness, (CellPos(0, 0, 2, 1), CellPos(0, 1), CellPos(1, 1)))
    assert read(harness, "SELECT has_merges FROM table_meta") == [(1,)]
    slots = read(harness, "SELECT r, c FROM grid_slot ORDER BY r, c")
    assert slots == [(0, 0), (0, 1), (1, 0), (1, 1)], "total, including the origin's own position"


def test_cells_that_reach_add_block_out_of_row_major_order_are_refused(harness: Harness) -> None:
    """03:1937: *"Cells arrive in row-major origin order ... `add_grid` asserts it."*

    The `ord` a cell wears among the table's children is its ARRIVAL index, and 03:1993-1994 makes
    those ordinals "row-major over origins, dense from 0" -- a store fact. So an out-of-order
    arrival is refused here even though `build_grid` itself would buffer and sort it.
    """
    with pytest.raises(ModelError, match="row-major"):
        _table_document(harness, (CellPos(1, 0), CellPos(0, 0)))


def test_add_grid_refuses_a_grid_whose_origins_are_not_the_cells_that_were_minted(
    harness: Harness,
) -> None:
    """A `Grid` naming a cell no `add_block` minted would write a `cell` row with a foreign id."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        table = writer.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
            )
        )
        minted = writer.add_block(cell_draft(table, "a", CellPos(0, 0)))
        grid = build_grid(
            (CellDraft(int(minted), CellPos(0, 0)), CellDraft(999_999, CellPos(0, 1))),
            diag=lambda _d: None,
        )
        with pytest.raises(ModelError, match="the same set"):
            writer.add_grid(table, grid)


def test_a_table_extent_above_max_expansion_is_a_resource_limit_naming_the_knob(
    harness: Harness,
) -> None:
    """03:1946: `MAX_EXPANSION` is charged, "so a tiny document carrying rowspan=99999 cannot
    force unbounded work", and it equals `MAX_GRID_SLOTS` so one charge covers storage too."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        table = writer.add_block(
            BlockDraft(
                kind=Kind.TABLE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
            )
        )
        oversized = Grid(
            n_rows=1,
            n_cols=1,
            row_len=(4_000_001,),
            header_rows=0,
            header_cols=0,
            kind="data",
            recon=None,
            has_merges=False,
            native=None,
            origins=MappingProxyType({}),
            cover=MappingProxyType({}),
            clamps=0,
        )
        with pytest.raises(ResourceLimit) as caught:
            writer.add_grid(table, oversized)
        assert caught.value.limit == "MAX_EXPANSION"


# ---------------------------------------------------------------------------------------------
# 7. Layer inheritance, the cell pair, and the payload schema.
# ---------------------------------------------------------------------------------------------


def test_a_non_page_root_naming_a_layer_other_than_its_parents_is_refused(
    harness: Harness,
) -> None:
    """M-INV-5 (03:1027-1031). Without inheritance the layer filter becomes a subtree walk."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        note = writer.add_block(
            BlockDraft(
                kind=Kind.FOOTNOTE,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
                parent=root,
            )
        )
        assert read(harness, "SELECT 1") is not None
        child = BlockDraft(
            kind=Kind.PARAGRAPH,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.NORMALIZED,
            parent=note,
            text="the note body",
        )
        with pytest.raises(ModelError) as caught:
            writer.add_block(child)
        assert caught.value.code() == "OW_LAYER_NOT_INHERITED"


def test_a_page_root_takes_its_layer_default_from_its_kind(harness: Harness) -> None:
    """03:1027-1029's mapping: `footnote` to `note`, `page_header` to `furniture`, else `body`."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        for kind in (Kind.FOOTNOTE, Kind.PAGE_HEADER, Kind.COMMENT, Kind.PARAGRAPH):
            writer.add_block(
                BlockDraft(
                    kind=kind,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.SYNTHETIC,
                    parent=root,
                )
            )
        writer.end_page({})
        writer.end_doc("ok")

    rows = read(
        harness,
        "SELECT e.name FROM block b JOIN enum_val e ON e.ord = b.layer "
        "AND e.domain = 'layer' WHERE b.parent_id IS NOT NULL ORDER BY b.block_id",
    )
    assert [row[0] for row in rows] == ["note", "furniture", "annotation", "body"]


def test_a_cell_pos_on_a_non_cell_kind_and_a_cell_kind_without_one_are_both_refused(
    harness: Harness,
) -> None:
    """03:334: *"`cell is not None` implies `kind == Kind.TABLE_CELL` and a `parent` of kind
    `table`, both asserted at `add_block`"* -- and the converse, because a `table_cell` with no
    position could not be given its `r<r>c<c>` addr step (03:1105)."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        with pytest.raises(ModelError, match="implies table_cell"):
            writer.add_block(text_draft(root, Kind.PARAGRAPH, "x", cell=CellPos(0, 0)))
        with pytest.raises(ModelError, match="CellPos"):
            writer.add_block(text_draft(root, Kind.TABLE_CELL, "x"))


def test_a_heading_payload_outside_the_printed_schema_is_refused_at_write(
    harness: Harness,
) -> None:
    """03:977: `heading.level` is `{"type":"integer","minimum":1,"maximum":9}`, checked at write.

    *"A payload that fails its kind's schema is `OW_SCHEMA_PAYLOAD_INVALID` at write, not a puzzle
    later"* (03:979).
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        with pytest.raises(ModelError) as caught:
            writer.add_block(text_draft(root, Kind.HEADING, "H", payload={"level": 12}))
        assert caught.value.code() == "OW_SCHEMA_PAYLOAD_INVALID"
        # An unknown key for a known kind is PRESERVED, not refused (03:1001).
        writer.add_block(
            text_draft(root, Kind.HEADING, "H", payload={"level": 2, "vendor_hint": "x"})
        )
        writer.end_page({})
        writer.end_doc("ok")
    stored = read(harness, "SELECT payload FROM block WHERE payload IS NOT NULL")
    assert stored == [('{"level":2,"vendor_hint":"x"}',)]


def test_an_extension_key_outside_the_x_vendor_key_grammar_is_refused(harness: Harness) -> None:
    """03:308: keys MUST match `x.<vendor>.<key>` and the vendor segment `ow` is reserved."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        with pytest.raises(ModelError, match=re.escape("x.<vendor>.<key>")):
            writer.add_block(text_draft(root, Kind.PARAGRAPH, "a", x={"note": 1}))
        with pytest.raises(ModelError, match="reserved"):
            writer.add_block(text_draft(root, Kind.PARAGRAPH, "a", x={"x.ow.note": 1}))
        writer.add_block(text_draft(root, Kind.PARAGRAPH, "a", x={"x.acme.note": 1}))
        writer.end_page({})
        writer.end_doc("ok")
    assert read(harness, "SELECT x FROM block WHERE text = 'a'") == [('{"x.acme.note":1}',)]


# ---------------------------------------------------------------------------------------------
# 8. Marks, assets and parts.
# ---------------------------------------------------------------------------------------------


def test_marks_are_stored_in_a_b_kind_order_and_a_range_past_the_text_is_refused(
    harness: Harness,
) -> None:
    """03:579 and 03:379-381. A zero-width mark is legal; a range past `len(text)` is not."""
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        root = writer.add_block(root_draft())
        block = writer.add_block(text_draft(root, Kind.PARAGRAPH, "abcdef"))
        with pytest.raises(ModelError, match="0 <= a <= b <= len"):
            writer.add_marks(block, [Mark(a=0, b=7, kind="bold")])
        other = writer.add_block(text_draft(root, Kind.PARAGRAPH, "abcdef"))
        writer.add_marks(
            other,
            [
                Mark(a=2, b=4, kind="italic"),
                Mark(a=0, b=0, kind="anchor"),
                Mark(a=0, b=6, kind="bold"),
            ],
        )
        with pytest.raises(ModelError, match="at most once"):
            writer.add_marks(other, [Mark(a=1, b=2, kind="code")])
        writer.end_page({})
        writer.end_doc("ok")

    assert read(harness, "SELECT a, b, kind FROM mark ORDER BY mark_id") == [
        (0, 0, "anchor"),
        (0, 6, "bold"),
        (2, 4, "italic"),
    ]


def test_add_asset_hashes_the_stream_itself_and_rejects_a_disagreeing_claim(
    harness: Harness,
) -> None:
    """03:2137-2140. *"a content-addressed store with an unverified writer is a substitution
    oracle"*, so the digest we store is the one we computed."""
    payload = b"real bytes"
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        writer.add_block(root_draft())
        with pytest.raises(ModelError) as caught:
            writer.add_asset(
                AssetDraft(media_type="image/png", sha256=_sha(b"lie"), byte_len=len(payload)),
                io.BytesIO(payload),
            )
        assert caught.value.code() == "OW_ASSET_DIGEST_MISMATCH"


def test_two_blocks_referencing_identical_bytes_produce_exactly_one_asset_row(
    harness: Harness,
) -> None:
    """Dedup on `(doc_ord, sha256, IFNULL(origin_part,''))` -- the `asset_identity` index (03:2088).

    The `IFNULL('')` sentinel is mandatory: SQL NULLs are each distinct, so a nullable natural key
    makes `INSERT OR IGNORE` degenerate into a plain INSERT (codegraph #1034).
    """
    payload = b"one logo"
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        writer.add_block(root_draft())
        draft = AssetDraft(media_type="image/png", sha256=_sha(payload), byte_len=len(payload))
        first = writer.add_asset(draft, io.BytesIO(payload))
        second = writer.add_asset(draft, io.BytesIO(payload))
        writer.end_page({})
        writer.end_doc("ok")

    assert first == second
    assert read(harness, "SELECT count(*) FROM asset") == [(1,)]
    ref = read(harness, "SELECT store_ref FROM asset")[0][0]
    assert (
        ref == f"cas://{_sha(payload).hex()[:2]}/{_sha(payload).hex()[2:4]}/{_sha(payload).hex()}"
    )


def test_add_parts_nullable_blob_is_the_retention_policy_in_the_signature(
    harness: Harness,
) -> None:
    """03:611-619: `blob = None` records `path`, `sha256` and `byte_len` with `store_ref` NULL.

    *"The digest and length are required either way, so the `glyphs` branch of INV-10 and
    `VERBATIM`'s re-verification can name WHICH part they could not read."*
    """
    kept, dropped = b"retained", b"discarded"
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        writer.add_block(root_draft())
        writer.add_part("word/document.xml", io.BytesIO(kept), _sha(kept), len(kept))
        writer.add_part("word/media/image1.png", None, _sha(dropped), len(dropped))
        writer.end_page({})
        writer.end_doc("ok")

    rows = read(harness, "SELECT path, byte_len, store_ref IS NULL FROM part ORDER BY path")
    assert rows == [
        ("word/document.xml", len(kept), 0),
        ("word/media/image1.png", len(dropped), 1),
    ]


# ---------------------------------------------------------------------------------------------
# 9. `achieved`, `doc.confidence`, and the frozen surface.
# ---------------------------------------------------------------------------------------------


def test_achieved_is_computed_from_the_committed_rows_and_never_exceeds_declared(
    harness: Harness,
) -> None:
    """INV-7 at the capability grain (03:534-536). `achieved` may be lower, never higher.

    The document below declares `cells_with_spans` and delivers a merged table, declares `linked`
    notes and delivers none, and declares `block_bbox` spatial and delivers no quad at all.
    """
    write_happy_path(harness)
    achieved = read(harness, "SELECT achieved FROM doc")[0][0]
    assert '"tables":"cells_with_spans"' in achieved
    assert '"spatial":"none"' in achieved, "no block carried a quad"
    assert '"notes":"none"' in achieved, "no note-layer block exists"
    assert '"marks":true' in achieved
    assert '"assets":"bytes"' in achieved
    assert '"asset_origin":true' in achieved
    assert '"reading_order":"source"' in achieved, "not observable from rows; the declaration"


def test_doc_confidence_publishes_the_count_and_a_component_with_no_pages_is_null(
    harness: Harness,
) -> None:
    """03:1777-1790's corrected form of docling's `nanmean` over an all-NaN list.

    *"A component with `n_scored == 0` is `null`, not `0.0`, and is excluded from any aggregate
    grade."* `page.table_score` is separately COMPUTED from that page's `table_meta.recon_score`
    values rather than taken from the driver (03:474-478).
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0, parse_score=0.9))
        writer.add_block(root_draft())
        writer.end_page({})
        writer.begin_page(page_record(1, parse_score=0.7))
        writer.end_page({})
        writer.end_doc("ok")

    confidence = read(harness, "SELECT confidence FROM doc")[0][0]
    assert '"parse":0.7999999999999999' in confidence or '"parse":0.8' in confidence
    assert '"ocr":null' in confidence
    assert '"n_scored":{"layout":0,"ocr":0,"parse":2,"table":0}' in confidence


def test_page_table_score_is_computed_from_that_pages_table_meta_recon_scores(
    harness: Harness,
) -> None:
    """03:474-478 and 03:1791-1794. The driver declares the field and never assigns it; the host
    computes it, or leaves it NULL and excludes it."""
    write_happy_path(harness)
    assert read(harness, "SELECT page, table_score FROM page ORDER BY page") == [
        (0, 0.98),
        (1, None),
    ]


def test_the_sink_satisfies_the_frozen_protocol_and_adds_no_twelfth_public_method() -> None:
    """03:568-572. *"Eleven, and the count is fixed ... adding one is an ADR, not a patch."*

    Both halves are asserted: the eleven names are exactly the Protocol's eleven, and the concrete
    class exposes nothing else. A helper that drifted onto the public surface would be a twelfth
    method in everything but the plan's arithmetic.
    """
    eleven = {
        name
        for name in vars(DocSinkProtocol)
        if not name.startswith("_") and callable(vars(DocSinkProtocol)[name])
    }
    assert eleven == {
        "add_asset",
        "add_block",
        "add_grid",
        "add_marks",
        "add_part",
        "add_rel",
        "begin_doc",
        "begin_page",
        "diag",
        "end_doc",
        "end_page",
    }
    public = {name for name in dir(DocSink) if not name.startswith("_")}
    assert public == eleven, (
        f"the concrete sink exposes {sorted(public - eleven)} beyond the eleven"
    )


def test_the_methods_carry_the_protocols_signatures_parameter_for_parameter() -> None:
    """A structural Protocol checks attribute EXISTENCE at runtime, never signatures, so the
    conformance a `DocSink` implementation actually has to get right is asserted here."""
    for name in (
        "begin_doc",
        "begin_page",
        "add_block",
        "add_marks",
        "add_grid",
        "add_rel",
        "add_asset",
        "add_part",
        "diag",
        "end_page",
        "end_doc",
    ):
        declared = inspect.signature(getattr(DocSinkProtocol, name))
        concrete = inspect.signature(getattr(DocSink, name))
        assert [p.name for p in declared.parameters.values()] == [
            p.name for p in concrete.parameters.values()
        ], name


def test_the_block_id_layout_is_the_shard_prefix_over_a_forty_eight_bit_sequence(
    harness: Harness,
) -> None:
    """03:1058-1066. Sixteen bits of shard over forty-eight of sequence, top bit zero.

    Three properties, and the third is the one that makes the reservation free rather than
    theoretical. At a single store `shard_ord = 0`, so ids are literally 1, 2, 3 -- "zero bytes of
    overhead and human-readable in a log". A shard ordinal outside `0..32767` is refused at
    construction, because `block_id` is a SIGNED 64-bit value. And a sink that mints at a shard the
    STORE was not created for is refused by the store: `CHECK ((block_id >> 48) = 0)` carries the
    ordinal "interpolated as a literal by the migration at CREATE time" and is "re-asserted at
    every open against `index_state.shard_ord`" -- two enforcers, one number.
    """
    write_happy_path(harness)
    assert [row[0] for row in read(harness, "SELECT block_id FROM block ORDER BY block_id")] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]

    with open_store(harness) as thread:
        with pytest.raises(ValueError, match="shard_ord"):
            sink(harness, thread, shard_ord=40_000)
        writer = sink(harness, thread, shard_ord=3)
        writer.begin_doc(doc_record(key=2))
        writer.begin_page(page_record(0))
        minted = writer.add_block(root_draft())
        assert int(minted) >> 48 == 3, "the prefix is in the id the moment it is minted"
        with pytest.raises(sqlite3.IntegrityError, match=r"block_id >> 48"):
            writer.end_page({})


def test_a_diagnostic_raised_between_two_pages_joins_the_next_transaction_to_commit(
    harness: Harness,
) -> None:
    """The other half of 03:593, and the branch the one-buffer design collapses.

    A diagnostic raised after one `end_page` and before the next `begin_page` has no page
    transaction of its own; the sink holds it for the next one to commit. Dropping it would lose
    the only record of a failure that happened between pages, and giving it a transaction of its
    own would make it survive a crash that abandoned the generation it belongs to.
    """
    with open_store(harness) as thread:
        writer = sink(harness, thread)
        writer.begin_doc(doc_record())
        writer.begin_page(page_record(0))
        writer.add_block(root_draft())
        writer.end_page({})
        writer.diag(
            Diag(
                code="OW_DEPTH_FLATTENED",
                severity="warning",
                component="parse.pdf.pdfium",
                message="raised between page 0 and page 1",
            )
        )
        assert read(harness, "SELECT count(*) FROM diag") == [(0,)], "not yet committed"
        writer.begin_page(page_record(1))
        writer.end_page({})

    assert read(harness, "SELECT code FROM diag") == [("OW_DEPTH_FLATTENED",)]
