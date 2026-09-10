"""The four read-only `ow store` verbs: `diff`, `explain`, `residue` and `export --portable`.

Covers `omniweave_core.store.inspect` (the three report verbs) and
`omniweave_core.store.portable` (the transport artefact). One file, because the four are one
wave and three of the four share the same fixture: a real `.owstore` with documents written
through `DocSink`, which is the only way a diff over documents or an export of one can be
asserted at all.

WHAT EACH SECTION IS TRYING TO CATCH
-------------------------------------
* **`explain` is byte-stable, twice over.** Explaining one store twice is the weak half -- a
  function with no clock in it passes that by construction. The half that matters is that two
  stores holding the same documents INSERTED IN A DIFFERENT ORDER render identically, because
  that is what makes the output golden-able: a byte-diff gate over a value that moves with
  ingest order fires on every unrelated commit and gets deleted within a month.
* **`explain` must not silently pass an index that is gone.** `test_..._is_a_reported_failure`
  drops a registered index out of a live store and asserts three things move together: the row's
  status, `ok`, and the rendered bytes. A gate whose report changed but whose exit code did not
  is the failure mode 07:957 exists to prevent.
* **`diff` speaks documents.** The assertion is on the COUNT of documents in each arm, not on
  rows, and the removal arm is asserted separately because "omit the row" and "report it as
  removed" are indistinguishable to a test that only counts what is present.
* **`residue` reports a zero.** An empty structure and a structure full of zeros are the same
  to `len()` and completely different to an operator, and INV-25 is a claim about growth that
  cannot be read off an absence.
* **the archive is consumable by something that is not omniweave.** `test_an_exported_archive_
  is_a_plain_zip...` imports `zipfile` and `json` and reads every member without touching
  `omniweave_core` at all, which is the only form in which 07:3092's claim is falsifiable.

ON `sqlite3` IN A TEST FILE (INV-17 / TID251)
----------------------------------------------
This file imports `sqlite3` for two reasons that both need the real module: the type annotation
on the helpers that take a connection, and the raw `INSERT`s that seed INV-25's residue tables.
Those rows have no writer in the tree yet -- `route_signal` is the router's (P4),
`quarantine` is the graph runner's (P5), `block_history` is written by a re-parse's retirement
pass and `ref_attempt` by the reference retry -- so seeding them with SQL is the only way to
assert that `residue()` counts them, and asserting it later would mean shipping the report
untested. `# noqa: TID251` on the import, with this paragraph as the reason.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sqlite3  # noqa: TID251 -- see the module docstring: this file seeds residue tables in SQL.
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import StoreError
from omniweave_core.model import (
    Capabilities,
    Kind,
    Layer,
    Method,
    PageKind,
    Quote,
    RelKind,
    Trust,
)
from omniweave_core.model.block import BlockDraft, CellPos, Mark
from omniweave_core.model.grid import build_grid
from omniweave_core.model.records import Diag, DocRecord, PageRecord
from omniweave_core.model.spans import OriginBytes
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.indexlock import LockFile, LockHeader, LockRow, write_lock
from omniweave_core.store.inspect import (
    ADDED,
    BLOCK_INDEXES,
    CELLS,
    CHANGED,
    COMPOSITIONS,
    DECOMPOSITION,
    DEFAULT_GROUP_LIMIT,
    INDEX_REGISTER,
    MACHINE_CAVEAT,
    MEASURED,
    MISSING,
    MIXED,
    MS_PER_NS,
    OK,
    PARTIAL,
    PENDING,
    PROSE,
    REMOVED,
    REPARSED,
    RESIDUE_TABLES,
    SUBTOTAL_ESTIMATE,
    SUBTOTAL_LINE,
    TOTAL_ESTIMATE,
    TOTAL_LINE,
    UNCHECKED,
    UNLISTED,
    UNUSED,
    _table_bytes,
    diff_lock,
    diff_stores,
    explain_indexes,
    lock_rows,
    residue,
    store_sizing,
)
from omniweave_core.store.maintenance import backup, index_ddl
from omniweave_core.store.portable import _BLOCKS_SQL, ARCHIVE_SUFFIX, export_portable
from omniweave_core.store.verify import derive_lock

NOW_NS = 1_757_400_000_000_000_000
"""A fixed timestamp. The clock is banned in library code and injected everywhere in the store."""

DOC_ONE = bytes([7]) * 16
DOC_TWO = bytes([8]) * 16
DOC_THREE = bytes([9]) * 16
"""Three `doc_key`s, written down here so no assertion reads its expected value out of the
database it is checking. `doc_key` is 16 bytes (`0001_init.sql:150`)."""

BODY_TEXT = "termination for convenience"

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
"""The all-absent capability floor. `Capabilities` has no defaults; all fifteen are required."""


# ---------------------------------------------------------------------------------------------
# Fixtures: a real store, and documents written through DocSink
# ---------------------------------------------------------------------------------------------


def _migrated(path: Path) -> int:
    """A fresh `.owstore` with the four migrations and one `producer` row. Returns the id."""
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.pdf', 1, 'abc123', X'00')"
        )
        connection.commit()
        return int(cursor.lastrowid or 0)
    finally:
        connection.close()


def _doc_record(key: bytes, uri: str, *, status: str = "ok") -> Any:
    return DocRecord(
        doc_ord=0,
        doc_key=key,
        gen=0,
        source_sha256=key * 2,
        normalizer="canonical/1",
        uri=uri,
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({}),
        source_bytes=4096,
        status=status,
        page_count=None,
        model_version="1.1",
        declared=FLOOR,
        achieved=FLOOR,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page_record() -> Any:
    return PageRecord(
        page=1,
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=595_280,
        h_mpt=841_890,
        rotation=0,
        quad_origin="topleft",
        method=Method.NATIVE,
        status="ok",
    )


def _write_doc(
    thread: Any, cas: Path, producer_id: int, key: bytes, uri: str, *, text: str = BODY_TEXT
) -> None:
    """One document, two blocks: the `document` root and one paragraph under it."""
    sink = DocSink(
        thread,
        producer_id=producer_id,
        origin_operator="parse.pdf",
        origin_driver="parse.pdf.pdfium",
        driver_schema_v=1,
        blobs=BlobStore(cas),
    )
    sink.begin_doc(_doc_record(key, uri))
    sink.begin_page(_page_record())
    root = sink.add_block(
        BlockDraft(
            kind=Kind.DOCUMENT,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.SYNTHETIC,
        )
    )
    sink.add_block(
        BlockDraft(
            kind=Kind.PARAGRAPH,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.NORMALIZED,
            parent=root,
            text=text,
            origin=OriginBytes(part="file", start=0, length=len(text), codec="utf-8/strict"),
        )
    )
    sink.end_page({})
    sink.end_doc("ok")


@pytest.fixture
def empty_store(tmp_path: Path) -> Path:
    """A migrated store with no documents in it."""
    path = tmp_path / "index.owstore"
    _migrated(path)
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """Three documents, written through `DocSink`. The fixture `diff` and `export` share."""
    path = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cas.mkdir()
    producer_id = _migrated(path)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        for key, uri in (
            (DOC_ONE, "file:///corpus/one.pdf"),
            (DOC_TWO, "file:///corpus/two.pdf"),
            (DOC_THREE, "file:///corpus/three.pdf"),
        ):
            _write_doc(thread, cas, producer_id, key, uri)
    return path


@pytest.fixture
def rich_store(tmp_path: Path) -> Path:
    """One document that fills every archive member the shipped schema can fill.

    A mark, a `rel`, a `part` and a diagnostic that NAMES A BLOCK. It exists because the
    two-block fixture above makes `test_an_archive_carries_no_block_id...` vacuous for three of
    the four places a `block_id` could leak: `rels.ndjson`, `diags.json` and the asset roles are
    not written at all when the tables are empty, so a `_StoreDocument` that emitted the raw
    integer would pass. That is the second finding of this file's mutation pass.
    """
    path = tmp_path / "rich.owstore"
    cas = tmp_path / "rich-cas"
    cas.mkdir()
    producer_id = _migrated(path)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.pdf",
            origin_driver="parse.pdf.pdfium",
            driver_schema_v=1,
            blobs=BlobStore(cas),
        )
        sink.begin_doc(_doc_record(DOC_ONE, "file:///corpus/rich.pdf"))
        sink.begin_page(_page_record())
        sink.add_part("file", None, bytes([3]) * 32, 4096)
        root = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        body = sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root,
                text=BODY_TEXT,
                origin=OriginBytes(
                    part="file", start=0, length=len(BODY_TEXT), codec="utf-8/strict"
                ),
            )
        )
        caption = sink.add_block(
            BlockDraft(
                kind=Kind.CAPTION,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=root,
                text="Figure 1",
                origin=OriginBytes(part="file", start=0, length=8, codec="utf-8/strict"),
            )
        )
        sink.add_marks(body, (Mark(a=0, b=11, kind="bold"),))
        sink.add_rel(caption, body, RelKind.CAPTION_OF, trust=Trust.INFERRED)
        sink.diag(
            Diag(
                code="OW_MARK_KIND_UNKNOWN",
                severity="warning",
                component="parse.pdf",
                message="a run style with no field",
                page=1,
                block=body,
            )
        )
        sink.end_page({})
        sink.end_doc("ok")
    return path


# ---------------------------------------------------------------------------------------------
# 1. `lock_rows` -- the re-derivation `ow store verify --lock` and `ow store diff` both read
# ---------------------------------------------------------------------------------------------


def test_lock_rows_re_derives_a_receipt_row_per_document_in_doc_key_order(corpus: Path) -> None:
    """Every column is asserted against a value written down HERE, not read back out of the store.

    `n_blocks = 2` is the fixture's own arithmetic -- one `document` root and one paragraph --
    and `gen = 1` is `DocSink`'s first generation. Reading either out of the database would make
    this a test that the database equals itself.
    """
    connection = ow.connect_readonly(corpus)
    try:
        rows = lock_rows(connection)
    finally:
        connection.close()

    assert [row.doc_key for row in rows] == [DOC_ONE, DOC_TWO, DOC_THREE], (
        "the receipt is sorted by doc_key BYTES (01-principles.md:688)"
    )
    assert [row.uri for row in rows] == [
        "file:///corpus/one.pdf",
        "file:///corpus/two.pdf",
        "file:///corpus/three.pdf",
    ]
    for row in rows:
        assert row.gen == 1
        assert row.status == "ok"
        assert row.n_blocks == 2, "one `document` root plus one paragraph"
        assert row.n_segments == 0, "nothing segments a document at P2"
        assert len(row.content_digest) == 16, "the root ow128 is 16 bytes (03:665)"


def test_lock_rows_is_the_same_derivation_ow_store_verify_lock_performs(corpus: Path) -> None:
    """INV-21: one fact, one home. 07:3155 puts `verify --lock` and `diff` in one sentence.

    Asserted as an identity between the two entry points rather than by reading `inspect.py`'s
    source, because what must hold is that the two verbs cannot disagree -- a second reading of
    the seven columns that happened to agree today is exactly the state this assertion is meant
    to make impossible.
    """
    connection = ow.connect_readonly(corpus)
    try:
        assert lock_rows(connection) == derive_lock(connection, header=_HEADER).rows
    finally:
        connection.close()


def test_a_document_with_no_root_block_gets_a_zero_root_digest_not_a_refusal(
    empty_store: Path,
) -> None:
    """`verify.derive_lock`'s ruling on the plan's silence, inherited rather than re-decided.

    A `doc` row with no `document` block at its head generation is a parse `end_doc` never
    finished. `derive_lock` writes the 16 zero bytes, so the receipt still names the document
    and a reviewer reads "no root"; `diff` therefore reports it as a document rather than
    failing the whole comparison. `export_portable` is where the same state IS a refusal, and
    for a different reason -- there is no archive to write -- which its own test pins.
    """
    connection = ow.connect(empty_store)
    try:
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
            "VALUES(1, ?, ?, 'file:///x.pdf', 'application/pdf', 'pdf', '{}', 4, 1, 'ok', "
            "'1.1', '{}', '{}')",
            (DOC_ONE, DOC_ONE * 2),
        )
        connection.commit()
        rows = lock_rows(connection)
    finally:
        connection.close()

    assert len(rows) == 1
    assert rows[0].doc_key == DOC_ONE
    assert rows[0].content_digest == bytes(16)
    assert rows[0].n_blocks == 0


# ---------------------------------------------------------------------------------------------
# 2. `ow store diff` -- documents, not rows
# ---------------------------------------------------------------------------------------------

_HEADER = LockHeader(scorer=1, segmenter="derive.segment.spine@3:9c1e", space="bge-m3@a1/8/c/i8")


def _row(key: bytes, *, gen: int = 1, n_segments: int = 0, status: str = "ok") -> LockRow:
    return LockRow(
        doc_key=key,
        gen=gen,
        status=status,
        n_blocks=2,
        n_segments=n_segments,
        content_digest=bytes([1]) * 16,
        uri=f"file:///corpus/{key[0]}.pdf",
    )


def test_a_diff_reports_one_document_changed_when_one_of_three_is_re_parsed() -> None:
    """07:3157's *"these four documents were re-parsed"*, at three documents and one re-parse.

    The assertion is on a count of DOCUMENTS. A diff that reported the two moved columns as two
    changes would also be "1 change" for a one-column edit and "2 changes" for this one, and a
    reviewer reading "2 changes" over a three-document corpus learns nothing.
    """
    before = LockFile(_HEADER, (_row(DOC_ONE), _row(DOC_TWO), _row(DOC_THREE)))
    after = LockFile(_HEADER, (_row(DOC_ONE), _row(DOC_TWO, gen=2), _row(DOC_THREE)))

    diff = diff_lock(before, after)

    assert diff.counts() == {REPARSED: 1, CHANGED: 0, ADDED: 0, REMOVED: 0}
    assert [d.doc_key for d in diff.of(REPARSED)] == [DOC_TWO]
    assert diff.of(REPARSED)[0].fields == ("gen",)
    assert diff.sentence() == "1 document re-parsed"


def test_a_deleted_document_is_reported_as_removed_and_not_merely_omitted() -> None:
    """The arm a diff gets wrong by doing nothing. 07:3157: *"and this one was removed"*.

    A diff that walked only the AFTER side would report zero changes here and be silently wrong,
    which is graphify's shipped defect in miniature (07:3105-3107, the pure union that
    resurrects a deletion).
    """
    before = LockFile(_HEADER, (_row(DOC_ONE), _row(DOC_TWO), _row(DOC_THREE)))
    after = LockFile(_HEADER, (_row(DOC_ONE), _row(DOC_THREE)))

    diff = diff_lock(before, after)

    assert diff.counts()[REMOVED] == 1
    removed = diff.of(REMOVED)[0]
    assert removed.doc_key == DOC_TWO
    assert removed.after is None and removed.before is not None
    assert diff.sentence() == "1 document removed"


def test_a_reparse_and_a_removal_are_reported_in_one_sentence() -> None:
    """The plan's own sentence shape: *"these four documents were re-parsed and this one was
    removed"* (07:3157)."""
    before = LockFile(_HEADER, (_row(DOC_ONE), _row(DOC_TWO), _row(DOC_THREE)))
    after = LockFile(_HEADER, (_row(DOC_ONE, gen=2), _row(DOC_THREE)))

    assert diff_lock(before, after).sentence() == "1 document re-parsed, 1 document removed"


def test_a_change_at_a_fixed_generation_is_not_called_a_re_parse() -> None:
    """`gen` is *"the parse generation, and nothing else"* (07:2919).

    A derived-layer rebuild moves `n_segments` at a fixed `gen`, and calling that a re-parse
    would tell a reviewer a document was read again when only its segmentation changed.
    """
    before = LockFile(_HEADER, (_row(DOC_ONE),))
    after = LockFile(_HEADER, (_row(DOC_ONE, n_segments=4),))

    diff = diff_lock(before, after)

    assert diff.counts() == {REPARSED: 0, CHANGED: 1, ADDED: 0, REMOVED: 0}
    assert diff.of(CHANGED)[0].fields == ("n_segments",)


def test_an_unchanged_corpus_says_so_in_words() -> None:
    """An empty diff returns a sentence, not an empty string.

    An empty string in a review comment cannot be told from a tool that failed to run, which is
    the same argument `residue()` makes for reporting a zero.
    """
    before = LockFile(_HEADER, (_row(DOC_ONE),))
    diff = diff_lock(before, before)
    assert diff.unchanged
    assert diff.sentence() == "no documents changed"


def test_a_header_difference_is_its_own_report_line() -> None:
    """07:3130: two receipts with different `scorer`s are not comparable document by document."""
    other = LockHeader(scorer=2, segmenter=_HEADER.segmenter, space=_HEADER.space)
    diff = diff_lock(LockFile(_HEADER, ()), LockFile(other, ()))
    assert diff.header_changed
    assert not diff.unchanged
    assert diff.sentence() == "the lock header changed"


def test_a_diff_accepts_the_receipt_text_on_either_side() -> None:
    """`ow store diff` holds `HEAD:omniweave.index.lock` as bytes, not as a parsed object."""
    before = write_lock(_HEADER, (_row(DOC_ONE), _row(DOC_TWO)))
    after = write_lock(_HEADER, (_row(DOC_ONE),))
    assert diff_lock(before, after).counts()[REMOVED] == 1


def test_diff_stores_over_a_real_re_parse_names_the_one_document(
    corpus: Path, tmp_path: Path
) -> None:
    """The end-to-end shape: back the store up, re-parse one document, diff the two files.

    `maintenance.backup` is `VACUUM INTO`, so the "before" side is a real second `.owstore` and
    not a copy of the report. Re-parsing goes through `DocSink`, so `doc.gen` moves the way an
    ingest moves it rather than the way an `UPDATE` in a test would.
    """
    before_path = tmp_path / "before.owstore"
    connection = ow.connect(corpus)
    try:
        backup(connection, before_path)
    finally:
        connection.close()

    cas = tmp_path / "cas"
    with ow.StoreThread(lambda: ow.connect(corpus)) as thread:
        producer_id = 1
        _write_doc(thread, cas, producer_id, DOC_TWO, "file:///corpus/two.pdf", text="rewritten")

    before = ow.connect_readonly(before_path)
    after = ow.connect_readonly(corpus)
    try:
        diff = diff_stores(before, after)
    finally:
        before.close()
        after.close()

    assert diff.counts()[REPARSED] == 1, diff.sentence()
    delta = diff.of(REPARSED)[0]
    assert delta.doc_key == DOC_TWO
    assert delta.before is not None and delta.after is not None
    assert delta.before.gen == 1 and delta.after.gen == 2
    assert "gen" in delta.fields


def test_a_first_ingest_of_a_document_is_reported_as_added(corpus: Path, tmp_path: Path) -> None:
    """The third arm, against two real stores: an empty one and the three-document fixture."""
    empty = tmp_path / "empty.owstore"
    _migrated(empty)
    left = ow.connect_readonly(empty)
    right = ow.connect_readonly(corpus)
    try:
        diff = diff_stores(left, right)
    finally:
        left.close()
        right.close()
    assert diff.counts() == {ADDED: 3, REPARSED: 0, CHANGED: 0, REMOVED: 0}
    assert diff.sentence() == "3 documents added"


# ---------------------------------------------------------------------------------------------
# 3. `ow store explain --golden` -- deterministic, sorted, and loud about a missing index
# ---------------------------------------------------------------------------------------------


def test_explaining_one_store_twice_produces_identical_bytes(corpus: Path) -> None:
    """The weak half of byte stability, asserted first because the strong half builds on it."""
    connection = ow.connect_readonly(corpus)
    try:
        first = explain_indexes(connection).render()
        second = explain_indexes(connection).render()
    finally:
        connection.close()
    assert first == second
    assert first.endswith("\n") and "\r" not in first, "LF only, one trailing newline"


def test_two_stores_built_in_different_insertion_orders_explain_identically(
    tmp_path: Path,
) -> None:
    """**This is what makes the output golden-able.**

    The two stores hold the same three documents; one ingested them in the order 7, 8, 9 and the
    other 9, 8, 7, so every `doc_ord` and every `block_id` differs between them. A golden output
    that moved with either would fire on every unrelated commit and be deleted within a month.
    """
    renders = []
    for name, keys in (
        ("forward", (DOC_ONE, DOC_TWO, DOC_THREE)),
        ("reverse", (DOC_THREE, DOC_TWO, DOC_ONE)),
    ):
        path = tmp_path / f"{name}.owstore"
        cas = tmp_path / f"cas-{name}"
        cas.mkdir()
        producer_id = _migrated(path)
        with ow.StoreThread(lambda p=path: ow.connect(p)) as thread:
            for key in keys:
                _write_doc(thread, cas, producer_id, key, f"file:///corpus/{key[0]}.pdf")
        connection = ow.connect_readonly(path)
        try:
            renders.append(explain_indexes(connection).render())
        finally:
            connection.close()

    assert renders[0] == renders[1], (
        "the golden explain output moved with ingest order; it cannot be byte-diff gated"
    )


def test_the_golden_output_carries_no_clock_no_path_and_no_row_count(corpus: Path) -> None:
    """The five things deliberately absent, checked as absences rather than trusted.

    A path would make the gate machine-specific; a row count would make it corpus-specific; a
    `sqlite_version()` would make it toolchain-specific. Each is a way a byte-diff gate becomes
    unusable while still looking like it works.
    """
    connection = ow.connect_readonly(corpus)
    try:
        text = explain_indexes(connection).render()
    finally:
        connection.close()
    assert str(corpus) not in text and corpus.name not in text
    assert not re.search(r"\b1[0-9]{9,}\b", text), "a wall-clock stamp reached the golden output"
    assert "sqlite" not in text.lower() or "sqlite_autoindex" in text


def test_every_register_row_whose_owner_migration_is_applied_resolves_to_a_live_index(
    corpus: Path,
) -> None:
    """ST17 forward: no register row names an index a fully migrated store does not have."""
    connection = ow.connect_readonly(corpus)
    try:
        report = explain_indexes(connection)
    finally:
        connection.close()
    assert report.ok, [f"{r.index.name}: {r.reason}" for r in report.failures]
    checked = [r for r in report.rows if r.status in (OK, UNUSED)]
    assert len(checked) == 26, "twenty-six of the twenty-nine register rows are in a P2 store"


def test_an_index_the_register_names_and_sqlite_master_lacks_is_a_reported_failure(
    corpus: Path,
) -> None:
    """07:957, and the reason it cannot be a skip.

    Three things must move together when a registered index disappears: the row's status, the
    report's `ok`, and the rendered bytes. A report that changed its text but kept `ok = True`
    would pass CI; one that kept its text but flipped `ok` would give a reviewer no diff to read.
    """
    connection = ow.connect(corpus)
    try:
        before = explain_indexes(connection)
        connection.execute("DROP INDEX block_cdig")
        connection.commit()
        after = explain_indexes(connection)
    finally:
        connection.close()

    assert before.ok and not after.ok
    dropped = next(r for r in after.rows if r.index.name == "block_cdig")
    assert dropped.status == MISSING
    assert dropped in after.failures
    assert "block_cdig" in dropped.reason and "957" in dropped.reason
    assert before.render() != after.render()
    assert "block_cdig\tblock\t0001\tmissing" in after.render()


def test_a_register_row_whose_owner_is_not_a_shipped_migration_is_pending_and_still_printed(
    corpus: Path,
) -> None:
    """`artifact_cite_block` is 09-generation's and `retrieval_event_*` live in `events.owstore`.

    Three rows in this state on every P2 store, and each is a LINE in the golden output rather
    than a row the report quietly drops -- an absent line is how a register row stops being
    checked without anybody noticing.
    """
    connection = ow.connect_readonly(corpus)
    try:
        report = explain_indexes(connection)
        text = report.render()
    finally:
        connection.close()
    pending = {r.index.name for r in report.rows if r.status == PENDING}
    assert pending == {"artifact_cite_block", "retrieval_event_ts", "retrieval_event_bad"}
    for name in sorted(pending):
        assert f"{name}\t" in text
    assert report.ok, "a pending owner is not a failure"


def test_a_partly_migrated_store_reports_the_absent_owners_rows_as_pending_not_missing(
    tmp_path: Path,
) -> None:
    """The other half of `pending`: an owner that IS a shipped migration but is not applied here.

    Without this clause the `pending` verdict could be produced by the owner-name lookup alone
    and would never exercise the applied-migration set, which is the part that turns into a
    `missing` the day someone forgets to migrate. `0004_runtime.sql` is the one left off, and it
    is the one that must be left off: the `migration` ledger itself is `0003_index.sql`'s, so a
    store below that has no applied set to read and every row would be pending for a second
    reason -- which would make this test pass without exercising anything.
    """
    path = tmp_path / "partial.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS, sources=_migrations_through(3))
        report = explain_indexes(connection)
    finally:
        connection.close()

    runtime = next(r for r in report.rows if r.index.name == "dep_reverse")
    assert runtime.status == PENDING
    assert "0004 is not applied" in runtime.reason
    assert report.ok, "an unapplied migration is not a missing index"
    assert next(r for r in report.rows if r.index.name == "block_addr").status == OK
    assert next(r for r in report.rows if r.index.name == "block_sec_path").status == OK


def _migrations_through(version: int) -> tuple[Any, ...]:
    """The shipped migrations up to and including `version`, for the partial store above."""
    return tuple(s for s in migrate.migrations() if s.version <= version)


def test_anchor_corpus_is_reported_unused_because_anchor_name_dominates_it(
    corpus: Path,
) -> None:
    """DEFECT 3, pinned. ST17's headline is *"every shipped index is used"* (07:3251).

    `anchor_name` is `(name_norm, akind, scope, doc_ord)` and `anchor_corpus` is
    `(name_norm, akind)` partial `scope = 'corpus'`, so the first is a superset of the second
    with the predicate's own column inside the key and the planner never reaches for the second.
    The day the register or the DDL changes on either side, this test says which.
    """
    connection = ow.connect_readonly(corpus)
    try:
        report = explain_indexes(connection)
    finally:
        connection.close()
    unused = {r.index.name for r in report.rows if r.status == UNUSED}
    assert unused == {"anchor_corpus"}, (
        "the set of registered-but-unchosen indexes moved; ST17 says every shipped index is used"
    )
    row = next(r for r in report.rows if r.index.name == "anchor_corpus")
    assert "anchor_name" in " ".join(row.plan)


def test_shipped_indexes_with_no_register_row_are_listed_and_do_not_fail(
    corpus: Path,
) -> None:
    """DEFECT 1: 07:957's reverse clause cannot hold against section 3.13's twenty-nine rows.

    The four shipped migrations create seventy-six indexes. Reporting the fifty with no register
    row keeps the fact visible without failing every build until `tools/indexes.toml` lands.
    """
    connection = ow.connect_readonly(corpus)
    try:
        report = explain_indexes(connection)
    finally:
        connection.close()
    assert report.ok
    assert "rel_src" in report.unregistered and "work_claimable" in report.unregistered
    assert not any(n.startswith("sqlite_autoindex_") for n in report.unregistered), (
        "an autoindex has no CREATE INDEX statement and cannot be registered"
    )
    assert list(report.unregistered) == sorted(report.unregistered)


def test_the_register_is_a_transcription_of_the_plans_own_table(plan: Any) -> None:
    """Every name, table and owner in `INDEX_REGISTER` comes from 07 section 3.13, in its order.

    A register that carries a row the plan did not order, or that has quietly dropped one, is
    the failure this project has already paid for twice. The probe column is excluded because
    it is this module's (DEFECT 2) and the plan prints no statements.
    """
    plan.require()
    rows = _plan_index_rows(plan.text("07-store-and-retrieval.md"))
    assert len(rows) == 29, f"section 3.13 prints twenty-nine index rows, found {len(rows)}"
    assert [(e.name, e.table, e.owner) for e in INDEX_REGISTER] == rows, (
        "INDEX_REGISTER and 07 section 3.13's table disagree"
    )


def _plan_index_rows(text: str) -> list[tuple[str, str, str]]:
    """The `| Index | Table | Owner | Serves | Shape |` table of 07 section 3.13.

    Scanned between its own header row and the "Twenty-nine index rows." sentence that closes
    it, so a later table elsewhere in the document cannot contribute a phantom row -- the same
    scope discipline `test_store_integration.py` learned from `_declared_tables`.
    """
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("| Index | Table | Owner |"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("Twenty-nine index rows."))
    out: list[tuple[str, str, str]] = []
    for line in lines[start + 2 : end]:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append((cells[0].strip("`"), cells[1].strip("`"), cells[2].strip("`")))
    return out


# ---------------------------------------------------------------------------------------------
# 4. `ow store residue` -- INV-25's four tables, `ref_unresolved`, and the container share
# ---------------------------------------------------------------------------------------------


def test_a_store_with_no_residue_reports_a_zero_for_every_table(empty_store: Path) -> None:
    """**A zero, not an empty structure.**

    An empty tuple and four rows of zero are the same to `len()`. They are not the same to an
    operator: one says "nothing has accumulated", the other says nothing at all, and INV-25 is a
    claim about growth that cannot be read off an absence. 07:553's *"the residue is data, not a
    log line"* is the same instruction -- data is there when nothing happened.
    """
    connection = ow.connect_readonly(empty_store)
    try:
        report = residue(connection, now_ns=NOW_NS)
    finally:
        connection.close()

    assert [t.table for t in report.tables] == [
        "route_signal",
        "quarantine",
        "ref_attempt",
        "block_history",
    ], "INV-25's four, in 01-principles.md:796's printed order"
    for table in report.tables:
        assert table.rows == 0
        assert table.empty
        assert table.oldest is None and table.newest is None and table.oldest_age_ns is None
    assert report.total_rows == 0
    assert report.groups == () and report.unresolved_sites == 0
    assert not report.truncated


def test_residue_counts_each_inv25_table_separately(corpus: Path) -> None:
    """Four different counts, so a report that summed them or reused one could not pass.

    The four counts are deliberately distinct primes-in-spirit (1, 2, 3, 4): equal counts would
    let a bug that read one table four times produce the right answer.
    """
    connection = ow.connect(corpus)
    try:
        _seed_residue(connection)
        report = residue(connection, now_ns=NOW_NS)
    finally:
        connection.close()

    assert report.table("route_signal").rows == 1
    assert report.table("quarantine").rows == 2
    assert report.table("ref_attempt").rows == 3
    assert report.table("block_history").rows == 4
    assert report.total_rows == 10


def test_the_generation_stamped_tables_report_an_age_in_generations(corpus: Path) -> None:
    """Three of INV-25's four carry no clock, and the report says so instead of inventing one.

    `ref_attempt.ts_a` is a `TextSpan` start (`0003_index.sql:215-222`) and reading it as a
    timestamp would print a plausible age that is a character offset. `last_tried_gen` is the
    column, and its unit is `generation`.
    """
    connection = ow.connect(corpus)
    try:
        _seed_residue(connection)
        report = residue(connection, now_ns=NOW_NS)
    finally:
        connection.close()

    attempts = report.table("ref_attempt")
    assert attempts.age_column == "last_tried_gen"
    assert attempts.age_unit == "generation"
    assert (attempts.oldest, attempts.newest) == (1, 3)
    assert attempts.oldest_age_ns is None, "a generation number is not a nanosecond clock"

    history = report.table("block_history")
    assert (history.age_column, history.age_unit) == ("retired_gen", "generation")
    assert (history.oldest, history.newest) == (1, 4)


def test_route_signals_age_is_wall_milliseconds_against_the_callers_clock(corpus: Path) -> None:
    """The one INV-25 table with a wall-clock stamp. `0004_runtime.sql:358` fixes the unit.

    The expected age is computed here from two constants written down in this file, so the
    assertion cannot be satisfied by reading the store's own value back out of it.
    """
    computed_at_ms = 1_757_000_000_000
    now_ns = 1_757_400_000_000_000_000
    connection = ow.connect(corpus)
    try:
        connection.execute(
            "INSERT INTO route_signal(content_sha256, unit_part, signal_key, signal_version, "
            "compute_ms, computed_at) VALUES('a1', '', 'page_count', '1', 3, ?)",
            (computed_at_ms,),
        )
        connection.commit()
        report = residue(connection, now_ns=now_ns)
    finally:
        connection.close()

    signals = report.table("route_signal")
    assert signals.age_unit == "wall_ms"
    assert signals.oldest == computed_at_ms
    assert signals.oldest_age_ns == now_ns - computed_at_ms * MS_PER_NS
    assert signals.oldest_age_ns == 400_000_000_000_000, "400,000 seconds, computed by hand"


def test_residue_groups_unresolved_references_by_name_norm(corpus: Path) -> None:
    """07:553, exactly: *"prints `ref_unresolved` grouped by `name_norm`"*.

    Three sites over two names, ranked worst-first. The `ref_unresolved` VIEW is the source and
    not the `ref_site` table, which matters: the view's anti-join honours the head generation and
    the anchor's scope (`0003_index.sql:247-254`), and counting `ref_site` directly would report
    every reference in the corpus as residue.
    """
    connection = ow.connect(corpus)
    try:
        block_id, doc_ord = connection.execute(
            "SELECT block_id, doc_ord FROM block WHERE addr = 'doc' ORDER BY doc_ord LIMIT 1"
        ).fetchone()
        _ref_site(connection, doc_ord, block_id, "section 4.2", 0)
        _ref_site(connection, doc_ord, block_id, "section 4.2", 10)
        _ref_site(connection, doc_ord, block_id, "exhibit a", 20)
        connection.commit()
        report = residue(connection, now_ns=NOW_NS)
    finally:
        connection.close()

    assert report.unresolved_sites == 3
    assert [(g.name_norm, g.sites) for g in report.groups] == [("section 4.2", 2), ("exhibit a", 1)]
    assert report.groups[0].akinds == ("section",)
    assert report.groups[0].docs == 1
    assert report.groups[0].surface == "Section 4.2"


def test_a_resolved_reference_is_not_residue(corpus: Path) -> None:
    """The negative control the grouping test needs to mean anything.

    Without it, `residue()` could be counting `ref_site` rows and every assertion above would
    still pass. An `anchor` in the same document with the same `name_norm` takes the reference
    out of the view, and the group disappears.
    """
    connection = ow.connect(corpus)
    try:
        block_id, doc_ord = connection.execute(
            "SELECT block_id, doc_ord FROM block WHERE addr = 'doc' ORDER BY doc_ord LIMIT 1"
        ).fetchone()
        _ref_site(connection, doc_ord, block_id, "section 4.2", 0)
        connection.commit()
        assert residue(connection, now_ns=NOW_NS).unresolved_sites == 1

        run_id = _derive_run(connection)
        connection.execute(
            "INSERT INTO anchor(doc_ord, gen, name_norm, akind, surface, block_id, scope, run_id)"
            " VALUES(?, 1, 'section 4.2', 'section', 'Section 4.2', ?, 'document', ?)",
            (doc_ord, block_id, run_id),
        )
        connection.commit()
        assert residue(connection, now_ns=NOW_NS).unresolved_sites == 0
    finally:
        connection.close()


def test_the_group_ceiling_is_a_take_n_plus_one_and_reports_that_it_bound(corpus: Path) -> None:
    """INV-25's own defence list ends with *"every ceiling at `take(N+1)`"* (01-principles.md:796).

    `truncated` is derived from reading one group past the limit, so it is exact: deriving it
    from `len(groups) == limit` would report a false positive on a corpus with exactly `limit`
    groups.
    """
    connection = ow.connect(corpus)
    try:
        block_id, doc_ord = connection.execute(
            "SELECT block_id, doc_ord FROM block WHERE addr = 'doc' ORDER BY doc_ord LIMIT 1"
        ).fetchone()
        for n in range(3):
            _ref_site(connection, doc_ord, block_id, f"clause {n}", n * 10)
        connection.commit()

        assert residue(connection, now_ns=NOW_NS, limit=3).truncated is False
        bound = residue(connection, now_ns=NOW_NS, limit=2)
        assert bound.truncated is True
        assert len(bound.groups) == 2
        assert bound.unresolved_sites == 3, "the total is not clamped by the group ceiling"

        with pytest.raises(StoreError, match="at least 1"):
            residue(connection, now_ns=NOW_NS, limit=0)
    finally:
        connection.close()


def test_the_container_share_reads_unit_derived_container_bytes(empty_store: Path) -> None:
    """05-ingest-and-routing.md:818: what `ow store residue` reads *"to find a corpus that is
    90% zip members"*.

    Nine of ten units carry `container_bytes`, so `share` is exactly 0.9 -- the sentence's own
    number, computed from a roster this test wrote rather than from a value it read back.
    """
    connection = ow.connect(empty_store)
    try:
        for n in range(10):
            derived = '{"container_bytes": 100}' if n < 9 else "{}"
            connection.execute(
                "INSERT INTO unit(unit_uri, state, bytes, derived, trust_class, last_seen_gen) "
                "VALUES(?, 'settled', 200, ?, 'internal', 1)",
                (f"file:///c/{n}", derived),
            )
        connection.commit()
        report = residue(connection, now_ns=NOW_NS)
    finally:
        connection.close()

    share = report.containers
    assert (share.units, share.container_units) == (10, 9)
    assert share.share == pytest.approx(0.9)
    assert share.container_bytes == 900
    assert share.total_bytes == 2000
    assert share.byte_share == pytest.approx(0.45)


def test_an_empty_roster_reports_a_zero_share_rather_than_dividing_by_zero(
    empty_store: Path,
) -> None:
    """A store with no units is the common case at P2 and must not raise."""
    connection = ow.connect_readonly(empty_store)
    try:
        share = residue(connection, now_ns=NOW_NS).containers
    finally:
        connection.close()
    assert (share.units, share.share, share.byte_share) == (0, 0.0, 0.0)


def test_the_residue_tables_are_inv25s_own_four(plan: Any) -> None:
    """A register is a transcription: the four names come from 01-principles.md:796 and nowhere
    else, in the order that line prints them."""
    plan.require()
    hits = plan.grep(r"INV-25: residue grows without bound", documents=("01-principles.md",))
    assert len(hits) == 1, "INV-25's row moved; the transcription below needs re-reading"
    named = re.findall(r"`([a-z_]+)`", hits[0].text.split("without bound")[1])
    assert [spec.table for spec in RESIDUE_TABLES] == named[:4]


def test_the_default_group_ceiling_is_this_modules_and_says_so() -> None:
    """The plan fixes no number for the group ceiling; the constant exists and is a parameter."""
    assert DEFAULT_GROUP_LIMIT >= 1


# ---------------------------------------------------------------------------------------------
# 5. `ow store export --portable` -- a transport artefact something else can read
# ---------------------------------------------------------------------------------------------


def test_export_portable_writes_one_archive_per_document_named_by_its_doc_key(
    corpus: Path, tmp_path: Path
) -> None:
    """07:3092: *"writes **one `.owdoc` per document**"*.

    The names are `doc_key` hex, which is the same value in every store that ingested those
    bytes; `doc_ord` would name the same document differently in two corpora and is exactly what
    07:3078 says an archive must not carry.
    """
    out = tmp_path / "portable"
    out.mkdir()
    connection = ow.connect_readonly(corpus)
    try:
        result = export_portable(connection, out)
    finally:
        connection.close()

    assert result.documents == 3
    assert result.skipped == ()
    assert sorted(p.name for p in out.iterdir()) == [
        f"{key.hex()}{ARCHIVE_SUFFIX}" for key in (DOC_ONE, DOC_TWO, DOC_THREE)
    ]
    assert result.blocks == 6, "two blocks per document, three documents"


def test_an_exported_archive_is_a_plain_zip_the_standard_library_alone_can_read(
    corpus: Path, tmp_path: Path
) -> None:
    """**The claim 07:3092 makes, proved the only way it can be.**

    *"a plain ZIP that `unzip -l` and `jq` both read with no external tool"*, and 00-vision.md:429
    makes the consumer explicitly not omniweave: *"export with `ow store export --portable` and
    index it yourself"*. So the reading half of this test uses `zipfile` and `json` and nothing
    from `omniweave_core` at all -- every member is listed the way `unzip -l` lists them and
    parsed the way `jq` parses them, and the document's text comes back out.
    """
    out = tmp_path / "portable"
    out.mkdir()
    connection = ow.connect_readonly(corpus)
    try:
        export_portable(connection, out)
    finally:
        connection.close()

    archive = out / f"{DOC_ONE.hex()}{ARCHIVE_SUFFIX}"
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None, "the central directory does not describe the members"
        names = zf.namelist()
        assert "manifest.json" in names and "frames.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["doc_key"] == DOC_ONE.hex()
        assert manifest["gen"] == 1
        assert manifest["source"]["uri"] == "file:///corpus/one.pdf"
        assert manifest["counts"]["blocks"] == 2
        blocks = [
            json.loads(line)
            for name in names
            if name.startswith("blocks/")
            for line in zf.read(name).decode("utf-8").splitlines()
        ]

    assert [b["i"] for b in blocks] == ["doc", "p1/0"], "addresses, in (page, ord, addr) order"
    assert [b["t"] for b in blocks] == [None, BODY_TEXT]
    assert blocks[1]["pa"] == "doc", "the parent is an address, not an id"


def test_an_archive_carries_no_block_id_anywhere_in_any_member(
    rich_store: Path, tmp_path: Path
) -> None:
    """07:3094: *"An archive contains **no `block_id`**: every internal reference in it is an
    `addr`."*

    Asserted over the raw bytes of every member and over the parsed records, because the two
    catch different mistakes: a substring scan catches a key named `block_id` and a value scan
    catches a bare integer smuggled into a field that should hold an address.
    """
    out = tmp_path / "portable"
    out.mkdir()
    connection = ow.connect_readonly(rich_store)
    try:
        ids = {int(v) for (v,) in connection.execute("SELECT block_id FROM block")}
        members = _member_counts(connection)
        export_portable(connection, out)
    finally:
        connection.close()

    assert ids, "the fixture wrote no blocks; this test would pass vacuously"
    assert members == {"rel": 1, "mark": 1, "diag": 1, "part": 1}, (
        f"the rich fixture stopped filling every member a block_id could leak through: {members}"
    )
    for archive in sorted(out.iterdir()):
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                raw = zf.read(name)
                assert b"block_id" not in raw, f"{archive.name}:{name} names block_id"
                if not name.endswith((".json", ".ndjson")):
                    continue
                for record in _records(raw, name):
                    for key in ("i", "pa", "src", "dst"):
                        value = record.get(key)
                        assert value is None or isinstance(value, str), (
                            f"{archive.name}:{name} carries {key}={value!r}, not an address"
                        )


def _member_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """How many rows the fixture wrote into each table an archive member is built from.

    Asserted rather than assumed, because the whole value of the rich fixture is that the
    members it fills are actually written; a fixture that quietly stopped writing a `rel` would
    make the block-id assertion vacuous again without failing anything.
    """
    return {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # noqa: S608
        for table in ("rel", "mark", "diag", "part")
    }


def _records(raw: bytes, name: str) -> list[dict[str, Any]]:
    """Every JSON object in one member, whatever shape the member is."""
    if name.endswith(".ndjson"):
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    decoded = json.loads(raw.decode("utf-8"))
    if isinstance(decoded, list):
        return [d for d in decoded if isinstance(d, dict)]
    return [decoded] if isinstance(decoded, dict) else []


def test_exporting_the_same_corpus_twice_produces_byte_identical_archives(
    corpus: Path, tmp_path: Path
) -> None:
    """INV-10's half of the transport artefact: the bytes are a function of the document.

    `archive/owdoc.py` pins every clock- and platform-dependent ZIP field; what this asserts is
    that the STORE side adds nothing that moves -- no dict ordering accident, no `ORDER BY` tie
    resolved by storage order (see `portable.py` DEFECT 1).
    """
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    connection = ow.connect_readonly(corpus)
    try:
        export_portable(connection, first)
        export_portable(connection, second)
    finally:
        connection.close()

    for left in sorted(first.iterdir()):
        right = second / left.name
        assert left.read_bytes() == right.read_bytes(), f"{left.name} is not byte-stable"


def test_the_block_stream_is_ordered_by_page_then_ord_then_addr(tmp_path: Path) -> None:
    """`portable.py` DEFECT 1, asserted on a document where `(page, ord)` genuinely ties.

    `block_sib` is UNIQUE `(doc_ord, gen, IFNULL(parent_id,-1), ord)`, so `ord` is unique among
    SIBLINGS only and blocks under different parents tie freely: here the `document` root, the
    first page root, and the first child of every page root all sit at `(page 1, ord 0)`.

    Eleven page roots is the smallest fixture that separates the addr order from the insertion
    order, and separating them is the whole point: `'p1/10/0'` sorts BEFORE `'p1/2/0'` in ASCII
    while it is inserted long after it. The expected sequence below is written out by hand, so
    the assertion compares the archive against a list in this file and not against whatever
    `ORDER BY` happened to return. Drop the `addr` key from `_BLOCKS_SQL` and this is the test
    that fails; the `VACUUM` test below does not catch it, because `VACUUM` rebuilds a two-row
    table in the order it already had.
    """
    path = tmp_path / "wide.owstore"
    cas = tmp_path / "cas"
    cas.mkdir()
    out = tmp_path / "portable"
    out.mkdir()
    producer_id = _migrated(path)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.pdf",
            origin_driver="parse.pdf.pdfium",
            driver_schema_v=1,
            blobs=BlobStore(cas),
        )
        sink.begin_doc(_doc_record(DOC_ONE, "file:///corpus/wide.pdf"))
        sink.begin_page(_page_record())
        root = sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        for n in range(11):
            section = sink.add_block(
                BlockDraft(
                    kind=Kind.SECTION,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.SYNTHETIC,
                    parent=root,
                )
            )
            sink.add_block(
                BlockDraft(
                    kind=Kind.PARAGRAPH,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.NORMALIZED,
                    parent=section,
                    text=f"clause {n}",
                    origin=OriginBytes(part="file", start=n, length=1, codec="utf-8/strict"),
                )
            )
        sink.end_page({})
        sink.end_doc("ok")

    connection = ow.connect_readonly(path)
    try:
        export_portable(connection, out)
    finally:
        connection.close()

    with zipfile.ZipFile(out / f"{DOC_ONE.hex()}{ARCHIVE_SUFFIX}") as zf:
        order = [
            json.loads(line)["i"]
            for name in sorted(n for n in zf.namelist() if n.startswith("blocks/"))
            for line in zf.read(name).decode("utf-8").splitlines()
        ]

    tied_at_ord_zero = ["doc", "p1/0", "p1/0/0", "p1/1/0", "p1/10/0"] + [
        f"p1/{n}/0" for n in range(2, 10)
    ]
    remaining_page_roots = [f"p1/{n}" for n in range(1, 11)]
    assert order == tied_at_ord_zero + remaining_page_roots, (
        "the block stream is not ordered by (page, ord, addr); `(page, ord)` alone leaves ties "
        "that storage order resolves, and storage order is not a fact about the document"
    )


def test_the_block_order_ends_in_a_key_the_schema_proves_unique() -> None:
    """The tie-break asserted STRUCTURALLY, because no data fixture can assert it.

    This is the finding the mutation pass produced and it is worth writing down. Removing
    `addr` from `_BLOCKS_SQL`'s `ORDER BY` leaves every data assertion green: the planner serves
    `WHERE doc_ord = ? AND gen = ?` from `block_addr`, a covering UNIQUE index on
    `(doc_ord, gen, addr)`, so rows reach the sorter in `addr` order already and SQLite's
    small-input merge sort preserves it. The order is therefore CORRECT TODAY BY ACCIDENT -- it
    depends on which index the planner chose, which is exactly the thing `ow store explain`
    exists to watch for flips.

    So the property is asserted where it lives: the last key of the `ORDER BY` must be a column
    the schema proves unique for one `(doc_ord, gen)`, and `block_addr`'s own DDL is what proves
    it. A future edit that drops the key, or that ends the order on a column with no uniqueness
    behind it, fails here.
    """
    order_by = _BLOCKS_SQL.split("ORDER BY", 1)[1]
    keys = [key.strip() for key in order_by.strip().split(",")]
    assert keys == ["page", "ord", "addr"], (
        "the block stream's order changed; `(page, ord)` alone is not total (block_sib makes "
        "`ord` unique among SIBLINGS only), so the last key must be a unique one"
    )
    ddl = " ".join(index_ddl("block_addr").split())
    assert "CREATE UNIQUE INDEX" in ddl.upper()
    assert re.search(r"block\s*\(\s*doc_ord\s*,\s*gen\s*,\s*addr\s*\)", ddl), (
        f"`addr` is the block stream's tie-break and {ddl!r} no longer proves it unique per "
        f"(doc_ord, gen)"
    )


def test_a_vacuum_does_not_move_an_archives_bytes(corpus: Path, tmp_path: Path) -> None:
    """The weaker, complementary property: re-exporting after a `VACUUM` reproduces the bytes.

    `VACUUM` changes physical row order (07:218-219), which is what makes an `ORDER BY` tie
    unsafe. It does not reliably change the order of a two-row table, which is why the test
    above and not this one is the one that pins the tie-break.
    """
    before_dir, after_dir = tmp_path / "before", tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()
    connection = ow.connect(corpus)
    try:
        export_portable(connection, before_dir)
        connection.execute("VACUUM")
        export_portable(connection, after_dir)
    finally:
        connection.close()

    for left in sorted(before_dir.iterdir()):
        assert left.read_bytes() == (after_dir / left.name).read_bytes()


def test_a_document_with_no_root_block_is_skipped_with_a_reason(
    corpus: Path, tmp_path: Path
) -> None:
    """One unfinished document may not cost a caller a whole corpus export.

    It is reported rather than raised, and the report names the `doc_key` and why -- a silent
    skip would make `result.documents` disagree with the corpus with nothing saying so.
    """
    out = tmp_path / "portable"
    out.mkdir()
    connection = ow.connect(corpus)
    try:
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
            "VALUES(99, ?, ?, 'file:///x.pdf', 'application/pdf', 'pdf', '{}', 4, 1, 'ok', "
            "'1.1', '{}', '{}')",
            (bytes([1]) * 16, bytes([1]) * 32),
        )
        connection.commit()
        result = export_portable(connection, out)
    finally:
        connection.close()

    assert result.documents == 3
    assert [key for key, _ in result.skipped] == [(bytes([1]) * 16).hex()]
    assert "no `document` block" in result.skipped[0][1]


def test_export_portable_refuses_a_directory_that_does_not_exist(
    corpus: Path, tmp_path: Path
) -> None:
    """A read-only verb does not create a tree; a typo is an error, not a new directory."""
    connection = ow.connect_readonly(corpus)
    try:
        with pytest.raises(StoreError, match="not an existing directory"):
            export_portable(connection, tmp_path / "nope")
    finally:
        connection.close()


def test_the_manifest_names_the_producer_by_index_and_never_by_producer_id(
    corpus: Path, tmp_path: Path
) -> None:
    """`producer_id` is the fourth store-local integer, and the format handles it (03:666).

    `pd` is an INDEX into `manifest.producers[]`, so a block's provenance travels without the
    store's surrogate key. The fixture's one producer therefore lands at index 0 regardless of
    what `producer.producer_id` happens to be.
    """
    out = tmp_path / "portable"
    out.mkdir()
    connection = ow.connect_readonly(corpus)
    try:
        export_portable(connection, out)
    finally:
        connection.close()

    with zipfile.ZipFile(out / f"{DOC_ONE.hex()}{ARCHIVE_SUFFIX}") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        blocks = [
            json.loads(line)
            for name in zf.namelist()
            if name.startswith("blocks/")
            for line in zf.read(name).decode("utf-8").splitlines()
        ]
    assert [p["operator"] for p in manifest["producers"]] == ["parse.pdf"]
    assert {b["pd"] for b in blocks} == {0}


# ---------------------------------------------------------------------------------------------
# Seeding helpers for the residue tables, which have no writer in the tree yet
# ---------------------------------------------------------------------------------------------


def _ref_site(
    connection: sqlite3.Connection, doc_ord: int, block_id: int, name_norm: str, ts_a: int
) -> None:
    """One unresolved reference occurrence. `surface` is title-cased so it cannot be the key."""
    connection.execute(
        "INSERT INTO ref_site(name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, scope, "
        "origin_operator) VALUES(?, 'section', ?, ?, ?, ?, ?, 'document', 'op.xref')",
        (name_norm, doc_ord, block_id, ts_a, ts_a + 5, name_norm.title()),
    )


def _derive_run(connection: sqlite3.Connection) -> int:
    """A `derive_run` row, plus the `derive_pass` its foreign key needs."""
    connection.execute(
        "INSERT OR IGNORE INTO derive_pass(pass_id, port, cost_class, cost_rank, lanes, "
        "granularity, card_sha256, schema_version) "
        "VALUES('op.xref', 'op', 'free', 0, '[\"xref\"]', 'document', 'ab', 1)"
    )
    producer_id = connection.execute("SELECT producer_id FROM producer LIMIT 1").fetchone()[0]
    cursor = connection.execute(
        "INSERT INTO derive_run(pass_id, at_gen, producer_id, method, origin_operator, "
        "origin_driver, driver_schema_v, cost_class, input_digest, cache_key, status) "
        "VALUES('op.xref', 1, ?, 0, 'op.xref', 'op.xref', 1, 'free', X'00', ?, 'ok')",
        (producer_id, "0" * 64),
    )
    return int(cursor.lastrowid or 0)


def _seed_residue(connection: sqlite3.Connection) -> None:
    """One `route_signal`, two `quarantine`, three `ref_attempt`, four `block_history`.

    Four different counts on purpose: equal counts would let a report that read one table four
    times produce the right answer.
    """
    connection.execute(
        "INSERT INTO route_signal(content_sha256, unit_part, signal_key, signal_version, "
        "compute_ms, computed_at) VALUES('a1', '', 'page_count', '1', 3, 1757000000000)"
    )
    run_id = _derive_run(connection)
    for n, gen in enumerate((1, 2)):
        connection.execute(
            "INSERT INTO quarantine(code, run_id, row_kind, payload, at_gen) "
            "VALUES(?, ?, 'entity', '{}', ?)",
            (f"OW_GRAPH_UNGROUNDED_{n}", run_id, gen),
        )
    blocks = [
        int(v)
        for (v,) in connection.execute("SELECT block_id FROM block ORDER BY block_id LIMIT 3")
    ]
    for gen, block_id in enumerate(blocks, start=1):
        connection.execute(
            "INSERT INTO ref_attempt(block_id, ts_a, attempts, last_tried_gen) VALUES(?, ?, 1, ?)",
            (block_id, gen * 10, gen),
        )
    for gen in (1, 2, 3, 4):
        connection.execute(
            "INSERT INTO block_history(block_id, doc_ord, retired_gen, reason) "
            "VALUES(?, 1, ?, 'reparse_resegmented')",
            (900 + gen, gen),
        )
    connection.commit()


# ---------------------------------------------------------------------------------------------
# 5. `store_sizing` -- `store.bytes_per_block` and 07:1021-1037's decomposition
# ---------------------------------------------------------------------------------------------
#
# WHAT THESE TESTS ARE TRYING TO CATCH, AND THE ONE RULE THEY ARE WRITTEN AGAINST
# --------------------------------------------------------------------------------
# A sizing report divides one number the store produced by another number the store produced, so
# almost every assertion one could write about it is satisfied by a function that is internally
# consistent and externally wrong. **When both sides of an equality come from the same store, the
# test pins agreement and not value.** So:
#
# * the block COUNT is asserted against a literal written down here (`SIZING_BLOCKS = 16`), which
#   is the fixture's own arithmetic -- one document root, one page root, one heading, three
#   paragraphs, one table and nine cells -- and never against `SELECT count(*) FROM block`;
# * the file SIZE is asserted against `Path.stat()`, an independent read of the same external
#   object through a different code path than the one under test;
# * the record ENCODING is asserted against a byte count hand-derived from SQLite's published
#   record format in `test_a_record_is_sized_by_the_file_format_and_not_by_a_second_guess`, which
#   is the only assertion in this section whose expected value does not come out of a database at
#   all -- and it is therefore the one that would catch a `_payload_sql` that was wrong in the
#   same direction everywhere;
# * the DECOMPOSITION's estimates and plan lines are asserted against `_plan/`, because
#   `DECOMPOSITION` is a transcription and a transcription is only worth what its cross-check is.
#
# THE DEGRADED `dbstat` PATH IS TESTED ON EVERY BUILD, not only on the one that happens to lack
# the virtual table. `_NoDbstat` wraps a real connection and raises the exact
# `sqlite3.OperationalError` a build without `SQLITE_ENABLE_DBSTAT_VTAB` raises, so the branch is
# exercised on a machine where `dbstat` works -- which is the machine on which it would otherwise
# silently rot.


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`.

    The same helper `test_gate_crash.py` uses, for the same reason: a test file that counted
    directory levels would break the day it moved, and `_plan/` is read here by absolute path.
    """
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


PLAN_07 = _repo_root(Path(__file__).resolve()) / "_plan" / "07-store-and-retrieval.md"
"""The plan file `DECOMPOSITION` transcribes. Read, never written (`_plan/` is frozen)."""

SIZING_BLOCKS = 16
"""The `sized_store` fixture's block count, written down HERE and not counted from the store.

1 document root + 1 page root + 1 heading + 3 paragraphs + 1 table + 9 cells = 16. Every
aggregate in this section divides by this literal, so a report that lost a block fails rather
than divide by its own smaller denominator and produce a plausible quotient.
"""

SIZING_PARAGRAPH = ("lorem ipsum dolor sit amet " * 12)[:300]
"""One paragraph, 300 characters. 07:1023's own prose figure: *"A prose paragraph is ~300 B"*."""

SIZING_CELL = "r0c0 val"
"""One cell, 8 characters, near 07:1023's *"a table cell is ~10 B"*. Every cell in the fixture is
this length -- `f"r{r}c{c} val"` is 8 characters for every single-digit r and c -- which is what
makes `text_bytes_per_block` for the `cells` composition an exact literal below."""

SIZING_HEADING = "Section 1"
"""Nine characters."""


@dataclass(frozen=True, slots=True)
class _CellDraft:
    """03:337-338's `CellDraft`, read structurally by `build_grid`.

    Declared here for the same reason `test_store_doc.py` declares it: `model/block.py` has not
    shipped the type, `grid.py`'s `_cell_position` reads it structurally, and this carries exactly
    the two attributes the plan prints.
    """

    id: int
    pos: CellPos


class _NoDbstat:
    """A connection that has no `dbstat`, whatever the SQLite underneath actually has.

    `store_sizing` reaches its connection through `execute` alone, so a wrapper is enough. The
    raised type and message are the ones SQLite itself raises for an eponymous virtual table the
    build omits -- `sqlite3.OperationalError("no such table: dbstat")` -- because a test that
    raised something else would prove `store_sizing` catches the wrong exception.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        if "dbstat" in sql:
            raise sqlite3.OperationalError("no such table: dbstat")
        return self._connection.execute(sql, parameters)


def _write_sized_doc(thread: Any, cas: Path, producer_id: int, part: Path) -> None:
    """The `sized_store` fixture's one document. See `SIZING_BLOCKS` for the census.

    The `part` carries REAL BYTES. `add_part(path, None, ...)` leaves `store_ref` NULL, and any
    block claiming `Quote.VERBATIM` against an unretained part makes `owcheck` emit a diagnostic
    -- which `DocSink.end_doc` then fails to insert (see the DEFECT reported in this wave's
    findings: `owcheck.OwcheckReport.diag_rows` hands `_end_doc` a `dict` in the `detail` column
    and `sqlite3` refuses to bind it). Retaining the bytes is also what the P2 demo does
    (16-roadmap.md:437, `ow store verify` re-deriving `content_sha256` from stored bytes), so the
    fixture is the shape the measurement is actually taken over rather than a smaller one.
    """
    sink = DocSink(
        thread,
        producer_id=producer_id,
        origin_operator="parse.pdf",
        origin_driver="parse.pdf.stub",
        driver_schema_v=1,
        blobs=BlobStore(cas),
    )
    sink.begin_doc(_doc_record(DOC_ONE, "file:///corpus/sized.pdf"))
    sink.begin_page(_page_record())
    with part.open("rb") as handle:
        sink.add_part("file", handle, hashlib.sha256(part.read_bytes()).digest(), 4096)
    root = sink.add_block(
        BlockDraft(
            kind=Kind.DOCUMENT,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.SYNTHETIC,
        )
    )
    page_root = sink.add_block(
        BlockDraft(
            kind=Kind.CONTAINER,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.SYNTHETIC,
            parent=root,
        )
    )
    sink.add_block(
        BlockDraft(
            kind=Kind.HEADING,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.VERBATIM,
            parent=page_root,
            text=SIZING_HEADING,
            origin=OriginBytes(part="file", start=0, length=9, codec="utf-8/strict"),
        )
    )
    offset = 9
    for _ in range(3):
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.NORMALIZED,
                parent=page_root,
                text=SIZING_PARAGRAPH,
                origin=OriginBytes(
                    part="file", start=offset, length=len(SIZING_PARAGRAPH), codec="utf-8/strict"
                ),
            )
        )
        offset += len(SIZING_PARAGRAPH)
    table = sink.add_block(
        BlockDraft(
            kind=Kind.TABLE,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.SYNTHETIC,
            parent=page_root,
        )
    )
    positions = [CellPos(r, c) for r in range(3) for c in range(3)]
    minted = []
    for position in positions:
        minted.append(
            sink.add_block(
                BlockDraft(
                    kind=Kind.TABLE_CELL,
                    layer=Layer.BODY,
                    method=Method.NATIVE,
                    trust=Trust.EXTRACTED,
                    quote=Quote.VERBATIM,
                    parent=table,
                    cell=position,
                    text=f"r{position.r}c{position.c} val",
                    origin=OriginBytes(part="file", start=offset, length=8, codec="utf-8/strict"),
                )
            )
        )
        offset += 8
    sink.add_grid(
        table,
        build_grid(
            (_CellDraft(int(b), p) for b, p in zip(minted, positions, strict=True)),
            header_rows=1,
            diag=lambda _d: None,
        ),
    )
    sink.end_page({})
    sink.end_doc("ok")


@pytest.fixture
def sized_store(tmp_path: Path) -> Path:
    """One document of sixteen blocks: prose, a table and its cells. See `SIZING_BLOCKS`.

    Tens of blocks and not four hundred thousand. Nothing this section asserts scales with the
    corpus -- the arithmetic pins, the by-kind sum and the degraded `dbstat` branch are the same
    at sixteen blocks as at 400k -- and `tools/measure_store.py` is where the number that DOES
    need a real corpus gets taken.
    """
    path = tmp_path / "sized.owstore"
    cas = tmp_path / "sized-cas"
    cas.mkdir()
    part = tmp_path / "sized.pdf"
    part.write_bytes(b"%PDF-1.4" + b"x" * 4088)
    producer_id = _migrated(path)
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        _write_sized_doc(thread, cas, producer_id, part)
    return path


def _sizing(path: Path) -> Any:
    """Size a closed store through a fresh read-write connection, and close it again."""
    connection = ow.connect(path)
    try:
        return store_sizing(connection, path=path)
    finally:
        connection.close()


# --- the arithmetic pins --------------------------------------------------------------------


def test_bytes_per_block_is_the_database_file_over_a_block_count_this_test_wrote_down(
    sized_store: Path,
) -> None:
    """Both sides of the quotient are pinned independently, which is the whole point.

    The denominator is `SIZING_BLOCKS`, a literal derived from the fixture's `add_block` calls.
    The numerator is `Path.stat().st_size`, read here through `os.stat` rather than out of the
    report -- so a `_store_files` that sized the wrong file, or an extra block nobody meant to
    write, fails. Asserting `report.bytes_per_block == report.files.db_bytes / report.blocks`
    would have asserted that division works.
    """
    report = _sizing(sized_store)
    assert report.blocks == SIZING_BLOCKS
    assert report.live_blocks == SIZING_BLOCKS
    assert report.files.db_bytes == sized_store.stat().st_size
    assert report.bytes_per_block == pytest.approx(sized_store.stat().st_size / SIZING_BLOCKS)


def test_the_by_kind_counts_sum_to_the_block_count_and_each_kind_is_the_census_written_here(
    sized_store: Path,
) -> None:
    """Six kinds, and every count is the fixture's own arithmetic rather than a query's answer.

    The sum is asserted as well as the parts, because a report that dropped one kind entirely
    would still have parts that were individually right.
    """
    report = _sizing(sized_store)
    census = {row.name: row.blocks for row in report.kinds}
    assert census == {
        "document": 1,
        "container": 1,
        "heading": 1,
        "paragraph": 3,
        "table": 1,
        "table_cell": 9,
    }
    assert sum(census.values()) == SIZING_BLOCKS
    assert sum(row.blocks for row in report.kinds) == report.blocks


def test_the_three_compositions_carry_the_prose_and_cell_split_07_1023_turns_on(
    sized_store: Path,
) -> None:
    """F4's split, with every expected value written down here.

    `prose` is the heading plus three paragraphs and its text is 9 + 3x300 = 909 bytes; `cells`
    is nine cells of eight bytes each; `mixed` is every block in the store. The `text B/block`
    figures are the quantity 07:1023 states in prose (*"a prose paragraph is ~300 B; a table cell
    is ~10 B"*), so this assertion is the one that says the fixture is measuring the thing the
    plan sentence is about.
    """
    report = _sizing(sized_store)
    prose = report.composition(PROSE)
    cells = report.composition(CELLS)
    mixed = report.composition(MIXED)

    assert prose.blocks == 4
    assert prose.kinds == ("heading", "paragraph")
    assert prose.text_bytes == len(SIZING_HEADING) + 3 * len(SIZING_PARAGRAPH)
    assert prose.text_bytes_per_block == pytest.approx(909 / 4)

    assert cells.blocks == 9
    assert cells.kinds == ("table_cell",)
    assert cells.text_bytes == 9 * len(SIZING_CELL)
    assert cells.text_bytes_per_block == pytest.approx(8.0)

    assert mixed.blocks == SIZING_BLOCKS
    assert mixed.share == pytest.approx(1.0)
    assert prose.share == pytest.approx(4 / SIZING_BLOCKS)
    assert cells.share == pytest.approx(9 / SIZING_BLOCKS)
    assert cells.bytes_per_block < prose.bytes_per_block


def test_every_byte_of_a_block_record_is_charged_to_exactly_one_component(
    sized_store: Path,
) -> None:
    """The seven `block`-row rows plus `UNLISTED` add up to the measured subtotal, exactly.

    That is the charging rule `_scan_blocks` documents -- each column pays its body and its own
    serial byte to the group that names it, and the row's remaining varints go to the row that
    says *"+ row header"* (07:1024). If the rule leaked, the subtotal and the parts would drift
    and neither would be wrong on its own. `pytest.approx` is float division by a block count,
    not slack in the rule.

    **This test pins AGREEMENT between the parts and the subtotal, and it pins no VALUE.** Both
    sides are sums of the same SQL expression, so an encoding that was wrong in the same
    direction everywhere satisfies it -- and section 6's mutation pass proved exactly that. It
    used to carry a third assertion,
    `report.record_bytes_per_block == report.component("subtotal").measured`, which could not
    fail at all: the property looks that row up and returns its `measured`. The VALUE is pinned
    instead by
    `test_the_measured_block_record_total_is_pinned_to_a_second_implementation_of_the_format`.
    """
    report = _sizing(sized_store)
    parts = [
        "text",
        "scalars",
        "addr_cite",
        "digests",
        "quad",
        "provenance",
        "x_payload_raw",
        UNLISTED,
    ]
    total = sum(report.component(key).measured or 0.0 for key in parts)
    assert total == pytest.approx(report.component("subtotal").measured)


def test_the_unlisted_columns_row_is_not_zero_which_is_why_defect_5_is_reported(
    sized_store: Path,
) -> None:
    """`os_codec` is `'utf-8/strict'` on every text block, and 07:1023-1029 charges it to nothing.

    A store whose text blocks all carry a byte origin pays thirteen bytes plus a serial byte for
    `os_codec` on each of them, so the row is measurably above zero -- the fixture has thirteen
    such blocks out of sixteen. If a future edit folded these columns into one of the plan's
    seven rows, this assertion would go to zero and say so.
    """
    report = _sizing(sized_store)
    unlisted = report.component(UNLISTED)
    assert unlisted.estimated is None
    assert unlisted.measured is not None
    assert unlisted.measured > 10.0


def test_a_record_is_sized_by_the_file_format_and_not_by_a_second_guess(tmp_path: Path) -> None:
    """The one expected value in this section that no database produced.

    A table `(a INTEGER PRIMARY KEY, b TEXT, c INTEGER, d BLOB)` holding `(1, 'abc', 0, x'00')`
    occupies, by SQLite's record format:

    * header -- one serial-type varint per column. `a` is the rowid alias, stored as NULL, serial
      type 0, one byte. `b` is text of three bytes, serial type `2*3+13 = 19`, one byte. `c` is
      the integer 0, serial type 8, which carries the value and one byte. `d` is a one-byte blob,
      serial type `2*1+12 = 14`, one byte. Four bytes, plus the header's own length as a varint:
      `4 + 1 = 5`, and 5 fits one byte, so the header is **5**.
    * body -- 0 for the rowid alias, 3 for `'abc'`, **0** for the integer 0 (serial type 8 IS the
      value), 1 for the blob. **4**.
    * the cell -- payload `5 + 4 = 9`, its size as a varint (**1**), and the rowid `1` as a varint
      (**1**). **11 bytes.**

    Eleven. Written out at length because the zero-width cases are exactly what a plausible-but-
    wrong implementation gets wrong: charging the rowid alias its integer width and the literal 0
    a byte each would give 16, which no assertion drawn from the same store would ever catch.
    """
    path = tmp_path / "encoding.owstore"
    _migrated(path)
    connection = ow.connect(path)
    try:
        connection.execute("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, c INTEGER, d BLOB)")
        connection.execute("INSERT INTO t VALUES (1, 'abc', 0, X'00')")
        connection.commit()
        rows, record_bytes = _table_bytes(connection, "t")
    finally:
        connection.close()
    assert rows == 1
    assert record_bytes == 11


# --- the WAL --------------------------------------------------------------------------------


def test_the_wal_is_sized_separately_and_is_never_folded_into_bytes_per_block(
    sized_store: Path,
) -> None:
    """A measurement taken with a fat WAL is a different measurement, and both are reported.

    `wal.bulk_index_peak_bytes` exists as its own `[[budget]]` row (12-performance.md:250)
    precisely because WAL growth is its own failure -- *"codegraph measured 5.9 GB of WAL against
    a 340 MB DB"* -- so a `bytes_per_block` that quietly included it would move for a reason the
    ratchet is not measuring. The WAL is made non-empty here by holding an uncheckpointed write
    open, which is the only way a `-wal` has bytes in it while anything can read the report.
    """
    connection = ow.connect(sized_store)
    try:
        connection.execute(
            "INSERT INTO diag(doc_ord, gen, page, part, code, severity, component, message, "
            "detail, fatal) VALUES(1, 1, 1, NULL, 'OW_TEST', 'warning', 't', 'm', '{}', 0)"
        )
        connection.commit()
        wal = sized_store.with_name(sized_store.name + "-wal")
        assert wal.stat().st_size > 0, "the fixture failed to leave an uncheckpointed WAL"
        report = store_sizing(connection, path=sized_store)
        assert report.files.wal_present is True
        assert report.files.wal_bytes == wal.stat().st_size
        assert report.files.db_bytes == sized_store.stat().st_size
        assert report.files.total_bytes == (
            report.files.db_bytes + report.files.wal_bytes + report.files.shm_bytes
        )
        assert report.bytes_per_block == pytest.approx(report.files.db_bytes / SIZING_BLOCKS)
        assert report.bytes_per_block_on_disk > report.bytes_per_block
    finally:
        connection.close()


# --- the degraded `dbstat` path ---------------------------------------------------------------


def test_a_store_without_dbstat_says_it_is_degraded_and_names_what_it_could_not_weigh(
    sized_store: Path,
) -> None:
    """`verify.py`'s `_unchecked()` register: a third state with a reason, not a silent pass.

    Asserted on every build through `_NoDbstat`, so the branch is live on a machine whose SQLite
    does have the virtual table. Three things move together: the report's `dbstat` flag, the
    three components that can only be weighed by pages, and the total's own state -- a report
    that degraded one of them and passed the others would understate the total by 202 estimated
    bytes a block with nothing saying so.
    """
    connection = ow.connect(sized_store)
    try:
        report = store_sizing(_NoDbstat(connection), path=sized_store)
    finally:
        connection.close()

    assert report.dbstat is False
    assert "SQLITE_ENABLE_DBSTAT_VTAB" in report.dbstat_reason
    for key in ("block_indexes", "block_fts", "head_fts"):
        row = report.component(key)
        assert row.state == UNCHECKED
        assert row.measured is None
        assert "dbstat" in row.reason
    assert report.component("block_indexes").reason.count("block_") >= len(BLOCK_INDEXES)
    assert report.component("block_sec").state == PARTIAL
    assert report.component("total").state == PARTIAL
    assert "block_indexes" in report.component("total").reason


def test_the_column_only_components_are_measured_even_when_dbstat_is_absent(
    sized_store: Path,
) -> None:
    """Degrading is not failing: the seven `block`-row rows need no `dbstat` and must not degrade.

    This is the assertion that stops the degraded path from becoming an excuse. Everything that
    can be measured from the record format is measured whatever the SQLite build is, and only the
    page-level rows go `UNCHECKED`.
    """
    connection = ow.connect(sized_store)
    try:
        report = store_sizing(_NoDbstat(connection), path=sized_store)
    finally:
        connection.close()
    for key in ("text", "scalars", "addr_cite", "digests", "quad", "provenance", "x_payload_raw"):
        row = report.component(key)
        assert row.state == MEASURED, key
        assert row.measured is not None


def test_the_real_dbstat_answer_is_consistent_with_whatever_this_build_supports(
    sized_store: Path,
) -> None:
    """Whichever branch this interpreter's SQLite takes, the report must be coherent about it.

    Written as a two-armed assertion rather than an `xfail` on a build, because both arms ship:
    CPython's bundled SQLite omits `SQLITE_ENABLE_DBSTAT_VTAB` on at least Windows/msvc, and a
    system SQLite on Linux frequently has it. A test that assumed either would be a test about
    the runner.
    """
    report = _sizing(sized_store)
    row = report.component("block_indexes")
    if report.dbstat:
        assert report.dbstat_reason == ""
        assert row.state == MEASURED
        assert row.measured is not None and row.measured > 0.0
    else:
        assert report.dbstat_reason != ""
        assert row.state == UNCHECKED
        assert row.measured is None


# --- the transcription ------------------------------------------------------------------------


def _plan_table_rows() -> dict[int, tuple[str, str]]:
    """`{1-based line: (component cell, bytes cell)}` for 07 section 4.1's table.

    A markdown pipe table, parsed by splitting on `|`. Only rows whose second cell looks like a
    byte figure are kept, which drops the header and the `|---|---:|---|` separator without
    hard-coding their line numbers.
    """
    text = PLAN_07.read_text(encoding="utf-8")
    rows: dict[int, tuple[str, str]] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or "~" not in cells[1]:
            continue
        rows[number] = (cells[0], cells[1])
    return rows


def test_every_decomposition_row_is_transcribed_from_the_line_it_names() -> None:
    """`DECOMPOSITION` is a transcription, and this is its cross-check against `_plan/`.

    Both halves of every row are asserted: the COMPONENT cell verbatim and the BYTES cell as the
    number. A row invented here -- however well motivated -- fails, and so does a row whose
    estimate drifted from the plan's. No store is opened: the transcription is a property of the
    source and of `_plan/`, and reading a store here would only slow it down.
    """
    plan = _plan_table_rows()
    for spec in DECOMPOSITION:
        assert spec.plan_line in plan, f"{spec.key}: 07:{spec.plan_line} is not a table row"
        component, byte_cell = plan[spec.plan_line]
        assert component == spec.component, f"{spec.key}: component cell drifted"
        assert byte_cell == f"~{int(spec.estimated)}", f"{spec.key}: byte cell drifted"


def test_the_subtotal_and_total_lines_are_the_plans_and_their_estimates_add_up() -> None:
    """07:1030 and 07:1037, and the arithmetic that ties them to the rows above them.

    The plan prints ~324 and ~636; the seven `block`-row estimates sum to 324 and all thirteen
    sum to 636. That is an assertion about the PLAN, not about this module: were the plan's own
    table to stop adding up, this test is where it would surface, and the numbers here are the
    plan's rather than a total this file computed and then agreed with.
    """
    plan = _plan_table_rows()
    assert plan[SUBTOTAL_LINE] == ("**`block` row subtotal**", "**~324**")
    assert plan[TOTAL_LINE] == ("**Total**", "**~636**")
    assert SUBTOTAL_ESTIMATE == 324.0
    assert TOTAL_ESTIMATE == 636.0
    row_estimates = [spec.estimated for spec in DECOMPOSITION if spec.columns]
    assert sum(row_estimates) == SUBTOTAL_ESTIMATE
    assert sum(spec.estimated for spec in DECOMPOSITION) == TOTAL_ESTIMATE


def test_the_nine_block_indexes_are_derived_from_the_register_and_are_07_1031s_nine() -> None:
    """`BLOCK_INDEXES` is `INDEX_REGISTER` filtered, and 07:1031 names the same nine.

    Pinned in both directions: the derived tuple against a list written down here from 07:1031's
    own prose, and its length against the word "nine" in the component cell. A tenth `block`
    index added to the register without a plan edit fails here, which is the failure this
    derivation exists to make visible rather than to absorb.
    """
    assert BLOCK_INDEXES == (
        "block_addr",
        "block_cite",
        "block_sib",
        "block_read",
        "block_parent",
        "block_kind",
        "block_cdig",
        "block_review",
        "block_restricted",
    )
    assert len(BLOCK_INDEXES) == 9
    assert _plan_table_rows()[1031][0] == "nine `block` indexes"


# --- what gets printed --------------------------------------------------------------------------


def test_the_blocks_per_page_figure_carries_its_caveat_on_its_own_line(sized_store: Path) -> None:
    """D27: blocks-per-page is a property of the corpus and 03:3086 says what closes F1.

    The caveat is asserted to be on the SAME rendered line as the number, not merely present in
    the report. A footnote is what gets quoted without, and a blocks-per-page figure quoted
    without its caveat is a claim that F1 closed at P2.
    """
    report = _sizing(sized_store)
    assert report.blocks_per_page == pytest.approx(SIZING_BLOCKS / 1)
    lines = [line for line in report.render().split("\n") if line.startswith("blocks/page")]
    assert len(lines) == 1
    assert "03-document-model.md:3086" in lines[0]
    assert "not F1's answer" in lines[0]


def test_a_rendered_report_is_byte_stable_across_two_reads_of_one_store(
    sized_store: Path,
) -> None:
    """No clock, no absolute path, no row order that depends on anything but the data.

    The weak half of `ExplainReport.render()`'s claim and it is asserted for the same reason: a
    report a reviewer diffs between two runs must not move for reasons unrelated to the store.
    """
    assert _sizing(sized_store).render() == _sizing(sized_store).render()
    assert sized_store.parent.name not in _sizing(sized_store).render()


def test_a_store_with_no_blocks_reports_zero_rather_than_dividing_by_it(
    empty_store: Path,
) -> None:
    """A ratio with no denominator is "this corpus does not answer the question", not infinity.

    The same ruling `ContainerShare.share` makes for an empty roster. Every aggregate is 0.0 and
    the report is still a whole report -- three compositions, the full decomposition -- because
    an empty structure and a structure full of zeros are different answers.
    """
    report = _sizing(empty_store)
    assert report.blocks == 0
    assert report.kinds == ()
    assert report.bytes_per_block == 0.0
    assert report.blocks_per_page == 0.0
    assert report.files.db_bytes > 0
    assert tuple(row.composition for row in report.compositions) == COMPOSITIONS
    assert all(row.blocks == 0 for row in report.compositions)
    assert report.component("total").measured == 0.0


def test_an_unknown_composition_or_component_raises_rather_than_returning_none(
    sized_store: Path,
) -> None:
    """`ResidueReport.table`'s ruling, applied to the two lookups this report adds."""
    report = _sizing(sized_store)
    with pytest.raises(KeyError):
        report.composition("figures")
    with pytest.raises(KeyError):
        report.component("indexes")
    with pytest.raises(KeyError):
        report.kind("formula")


def test_an_identifier_that_is_not_a_bare_sql_name_is_refused_before_it_reaches_a_statement(
    empty_store: Path,
) -> None:
    """The interpolation guard, asserted directly. `_require_ident` is a private and this is why.

    `_table_bytes` interpolates a table name; every caller in the module passes a literal, so the
    only way to show the guard is live is to call it with something that is not one.
    """
    connection = ow.connect(empty_store)
    try:
        with pytest.raises(StoreError, match="bare SQL identifier"):
            _table_bytes(connection, "block; DROP TABLE block")
    finally:
        connection.close()


def _load_tool(name: str) -> ModuleType:
    """Import a `tools/` script by path. `tools/` is not a package, so there is no dotted name.

    `test_gate_crash.py` loads `tools/gate_crash.py` the same way and for the same reason. The
    module name is prefixed so a script and a test module can never collide in `sys.modules`.
    """
    path = _repo_root(Path(__file__).resolve()) / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ow_test_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


measure_store = _load_tool("measure_store")
"""`tools/measure_store.py`, the runner this section's last four tests are about."""

load_budget = measure_store.load_budget


def _numeric_literals(path: Path) -> set[float]:
    """Every numeric constant in `path`'s CODE, with comments and docstrings excluded.

    Rule 3, made mechanical: a phantom match inside a comment has already cost this project a
    wrong number. `ast.parse` throws comments away and gives every docstring back as a `str`
    constant, so filtering `Constant` nodes to `int` and `float` -- and excluding `bool`, which
    is an `int` subclass -- leaves exactly the literals a comparison could be written against.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        float(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }


# --- `tools/measure_store.py`, the runner around all of the above -----------------------------


def test_the_measurement_script_reads_660_from_the_register_and_not_from_a_literal() -> None:
    """`eval/perf.toml` owns `store.bytes_per_block`; `tools/measure_store.py` reads it.

    The value is asserted against 660 -- charter.md:7617-7622 and 12-performance.md:244 -- from
    the register file, and separately the script's own source is asserted to contain no NUMERIC
    LITERAL 660, because the failure this guards against is a fallback constant that silently
    takes over the day the register moves.

    **Comments are stripped before the count, and so are docstrings.** The word 660 appears four
    times in `tools/measure_store.py`'s prose, saying where the number lives and why it is not
    here; a grep would have counted those and either failed for the wrong reason or been
    loosened until it stopped catching anything. `ast` sees code and nothing else, which is what
    makes this an assertion about definition sites rather than about mentions.

    Skipped, with the reason stated, when `eval/perf.toml` has not landed: it is W10.4 and
    another agent owns it.
    """
    root = _repo_root(Path(__file__).resolve())
    perf = root / "eval" / "perf.toml"
    if not perf.exists():
        pytest.skip(
            "eval/perf.toml has not landed yet; it is W10.4 and 12-performance.md:207 "
            "owns it, and an integration pass turns this green"
        )
    budget = load_budget(perf, "store.bytes_per_block")
    assert budget.value == 660.0
    assert budget.tol_pct == 10
    assert budget.tolerance == pytest.approx(66.0)
    assert budget.within(660.0) and budget.within(726.0) and not budget.within(727.0)
    assert 660 not in _numeric_literals(root / "tools" / "measure_store.py")


def test_the_measurement_script_reports_did_not_run_rather_than_a_number_it_cannot_have(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 2 and a named absence when contract F1's or F2's file is not on disk.

    An integration pass runs after this wave, so the absent case must be a clear report and not a
    traceback -- and it must not be exit 1, which CI would read as a breached budget.
    """
    monkeypatch.setattr(measure_store, "GENERATOR", tmp_path / "gen_5000p_pdf.py")
    out = StringIO()
    assert measure_store.main([], out=out) == measure_store.EXIT_NOT_RUN
    printed = out.getvalue()
    assert "DID NOT RUN" in printed
    assert "the generator" in printed


def test_the_measurement_script_never_prints_that_a_budget_was_met() -> None:
    """12-performance.md:1966, asserted against the source rather than against a run.

    A run needs the fixture and the stub driver; the promise does not. The two words this script
    must never put next to each other are asserted absent, and `MACHINE_CAVEAT` -- which lives in
    `store/inspect.py` so the library and the runner cannot drift into two disclaimers -- is
    asserted present.
    """
    root = _repo_root(Path(__file__).resolve())
    source = (root / "tools" / "measure_store.py").read_text(encoding="utf-8")
    assert "MACHINE_CAVEAT" in source
    assert "ow-bench-1" in source
    assert "budget is met" not in source
    assert "BUDGET OK" not in source
    assert "ow-bench-1" in MACHINE_CAVEAT
    assert "INDICATION" in source


def test_the_measurement_script_does_not_compare_peak_rss_to_the_deferred_row() -> None:
    """Ruling D26. `rss.gen5000p_peak_bytes` is the anydoc fork tripwire and there is no anydoc.

    The figure is printed and labelled; the comparison is not made. `_numeric_literals` is the
    assertion that matters -- the budgeted value is not a number anywhere in the script's CODE,
    so nothing can be compared to it -- and the two prose assertions below say the reader is
    told the figure exists and is deferred rather than simply not being shown it.
    """
    root = _repo_root(Path(__file__).resolve())
    script = root / "tools" / "measure_store.py"
    source = script.read_text(encoding="utf-8")
    assert 1_610_612_736 not in _numeric_literals(script)
    assert "INFORMATIONAL" in source
    assert "1,610,612,736" in source


# ---------------------------------------------------------------------------------------------
# 6. Adversarial pins -- the sizing claims a mutation would otherwise have walked through
# ---------------------------------------------------------------------------------------------
#
# Every test below exists because a specific mutation was applied to `store/inspect.py` or to
# `tools/measure_store.py`, section 5 was run, and it stayed GREEN. Each test names the mutation
# it kills, because a test whose failure mode is not written down is a test the next person
# weakens the first time it goes red for a reason they do not recognise.
#
# TWO SHAPES PRODUCED EVERY SURVIVOR, and both are worth recognising by name.
#
# **Both sides of the equality came out of the same store.** `SizingReport.record_bytes_per_block`
# IS `component("subtotal").measured` -- the property looks that row up and returns it -- so
# `assert report.record_bytes_per_block == report.component("subtotal").measured` was `x == x`
# and could not fail. `_expected_record_bytes` below is the fix for the general case: a SECOND
# IMPLEMENTATION of SQLite's record format, written in Python against the published encoding and
# reading the same rows back through `SELECT rowid, *`. It reproduces the eleven hand-derived
# bytes of `test_a_record_is_sized_by_the_file_format_and_not_by_a_second_guess`, and it is what
# the `block` table's forty columns are now measured against. With only the module's own SQL on
# both sides, `_scan_blocks` could drop the rowid varint from every cell -- a systematic
# undercount of up to nine bytes a row on a real corpus -- and every assertion in section 5 still
# passed, because the parts and the subtotal moved together.
#
# **The fixture could not tell two quantities apart.** `sized_store` had no tombstoned block, so
# `blocks` and `live_blocks` were both 16 and the denominator of `store.bytes_per_block` could be
# swapped for either. 07:1046 is why that is not a quibble: *"A full re-parse retires one
# generation of every block, so between the re-parse and the next `PRAGMA incremental_vacuum` the
# file holds up to 2x its logical size."* The fixture also had no `mark`, `rel`, `ref_site`,
# `block_sec` or `segment_block` row, so the three components 07:1034-1036 charge ~110 B/block
# for measured zero whatever the code did; and `doc` and `page` each held exactly one row, so
# `documents` could be counted out of the wrong table. A fixture that collapses two quantities
# onto one value tests neither of them.
#
# THE REPORT IS ALSO AN ARTEFACT. Section 5 asserted the degraded `dbstat` path on the value
# object and never on `render()`, so the whole `dbstat ABSENT <reason>` line could be deleted and
# the suite stayed green -- the operator would then read a report that looks complete and is not.
# Two of the plan's thirteen rows (`segment_block`, `sparse`) were reachable by no assertion at
# all, so `_components` could omit them from the tuple it returns and nothing noticed.
#
# `tools/measure_store.py` HAD NO BEHAVIOURAL TEST. Its three tests read the script's SOURCE TEXT
# and grep it for `MACHINE_CAVEAT`, `ow-bench-1` and `INDICATION` -- every one of which also
# occurs in a docstring or in the import line. So the script could be made to print
# `VERDICT  budget PASS` and to stop printing the ow-bench-1 caveat altogether, and all three
# passed. That is rule 3 in its exact form: a comment is not a definition site, and neither is a
# docstring. The tests below run `_report` and `main` and assert on what came out.


_RECORD_VARINT_BOUNDS: tuple[int, ...] = (
    127,
    16_383,
    2_097_151,
    268_435_455,
    34_359_738_367,
    4_398_046_511_103,
    562_949_953_421_311,
    72_057_594_037_927_935,
)
"""Inclusive upper bound of a 1- to 8-byte SQLite varint; anything larger takes nine.

Written out here rather than imported from `store/inspect.py`, because a second implementation
that shares the constants of the module under test is not a second implementation.
"""


def _varint_bytes(value: int) -> int:
    """How many bytes SQLite's varint encoding gives a non-negative `value`."""
    for width, bound in enumerate(_RECORD_VARINT_BOUNDS, start=1):
        if value <= bound:
            return width
    return 9


_INTEGER_SERIALS: tuple[tuple[int, int], ...] = (
    (127, 1),
    (32_767, 2),
    (8_388_607, 3),
    (2_147_483_647, 4),
    (140_737_488_355_327, 6),
)
"""Serial types 1-6 of the record format: an integer's magnitude bound and its BODY width.

Five entries and six types: type 5 is a SIX-byte integer and there is no five-byte form, which
is the detail an implementation written as `(bits + 7) // 8` gets wrong. Anything past the last
bound is type 6 and eight bytes.
"""


def _integer_serial(value: int) -> tuple[int, int]:
    """`(serial type, body bytes)` for an INTEGER value.

    Types 8 and 9 ARE the integers 0 and 1 -- they carry the value in the type and cost no body
    bytes -- which is the case a plausible-but-wrong encoder charges a byte for. Split out of
    `_serial_of` only so each function stays under ruff's return ceiling.
    """
    if value == 0:
        return (8, 0)
    if value == 1:
        return (9, 0)
    for serial, (bound, width) in enumerate(_INTEGER_SERIALS, start=1):
        if -bound - 1 <= value <= bound:
            return (serial, width)
    return (6, 8)


def _serial_of(value: object) -> tuple[int, int]:
    """`(serial type, body bytes)` for one column value, from SQLite's record-format table.

    Serial type 0 is NULL and costs no body bytes; type 7 is an f64; text is `2n + 13` and blob
    is `2n + 12`, both over the BYTE length rather than the character count. `_integer_serial`
    has the rest.
    """
    if value is None:
        return (0, 0)
    if isinstance(value, float):
        return (7, 8)
    if isinstance(value, int):
        return _integer_serial(value)
    if isinstance(value, str):
        body = len(value.encode("utf-8"))
        return (2 * body + 13, body)
    blob = bytes(value)  # type: ignore[call-overload]
    return (2 * len(blob) + 12, len(blob))


def _expected_record_bytes(connection: sqlite3.Connection, table: str, *, alias: str) -> int:
    """Every b-tree cell of a ROWID table, sized by a second implementation of the format.

    `alias` names the `INTEGER PRIMARY KEY` column, which IS the rowid: the record stores a NULL
    in its place, so it costs one header byte and no body, and the rowid itself is carried once
    as the cell's own varint. It is passed in rather than derived, because deriving it would
    mean re-using `_columns_of`, which is one of the things this helper exists to be independent
    of.

    The header's first field is the header's OWN length as a varint, so `H = W + varint(H)` is
    implicit; it is solved here by iterating to a fixed point, which is the same equation
    `_header_sql` solves in SQL and is arrived at from the specification rather than from that
    code.
    """
    names = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
    total = 0
    for row in connection.execute(f"SELECT rowid, * FROM {table}"):  # noqa: S608
        rowid = int(row[0])
        header = 0
        body = 0
        for name, value in zip(names, row[1:], strict=True):
            if name == alias:
                header += 1
                continue
            serial, width = _serial_of(value)
            header += _varint_bytes(serial)
            body += width
        size = header
        while size != header + _varint_bytes(size):
            size = header + _varint_bytes(size)
        payload = size + body
        total += payload + _varint_bytes(payload) + _varint_bytes(rowid)
    return total


SIZING_COMPONENT_KEYS: tuple[str, ...] = (
    "text",
    "scalars",
    "addr_cite",
    "digests",
    "quad",
    "provenance",
    "x_payload_raw",
    UNLISTED,
    "subtotal",
    "block_indexes",
    "block_fts",
    "head_fts",
    "block_sec",
    "segment_block",
    "sparse",
    "total",
)
"""Every row `store_sizing` reports, in the order it reports them.

Sixteen: 07:1023-1036's thirteen, the `UNLISTED` row DEFECT 5 adds, and the two the module
computes rather than transcribes (07:1030's subtotal and 07:1037's total).
"""


# --- the record encoding, pinned against something that is not this module --------------------


def test_the_measured_block_record_total_is_pinned_to_a_second_implementation_of_the_format(
    sized_store: Path,
) -> None:
    """MUTATION KILLED: `_scan_blocks` computing its cell with `without_rowid=True`.

    That mutation drops the rowid varint from every `block` cell -- one byte a row on this
    fixture and up to nine on a store whose block ids approach the `(block_id >> 48) = 0` bound
    -- and section 5 stayed entirely green under it. The seven column groups, the row-overhead
    group and the subtotal are all sums of the same SQL expression, so they moved together and
    the parts still added up to the whole. Nothing pinned the `block` table's record bytes to a
    figure that had not come out of `_cell_bytes_sql`.

    `_expected_record_bytes` is that figure. Three claims are pinned by it at once: `_table_bytes`
    over the real forty-column table, the subtotal row, and `record_bytes_per_block` -- which
    used to be asserted against `component("subtotal").measured`, the value it literally returns.
    """
    connection = ow.connect(sized_store)
    try:
        expected = _expected_record_bytes(connection, "block", alias="block_id")
        report = store_sizing(connection, path=sized_store)
        assert _table_bytes(connection, "block") == (SIZING_BLOCKS, expected)
    finally:
        connection.close()

    assert expected > 3 * len(SIZING_PARAGRAPH), "the fixture's paragraphs are not in the total"
    subtotal = report.component("subtotal").measured
    assert subtotal is not None
    assert subtotal * SIZING_BLOCKS == pytest.approx(expected)
    assert report.record_bytes_per_block * SIZING_BLOCKS == pytest.approx(expected)


# --- the denominator ---------------------------------------------------------------------------


def test_a_tombstoned_block_stays_in_the_denominator_and_is_reported_as_not_live(
    sized_store: Path,
) -> None:
    """MUTATION KILLED: dividing by `live_blocks` instead of by the `block` row count.

    `sized_store` had no tombstone, so `blocks` and `live_blocks` were both 16 and the two were
    interchangeable everywhere in the report. 07:1046 is why that matters: *"A full re-parse
    retires one generation of every block, so between the re-parse and the next `PRAGMA
    incremental_vacuum` the file holds up to 2x its logical size."* On a store inside that
    window the two denominators differ by a factor of two, and `store.bytes_per_block` is a
    RATCHET with a 10% tolerance (12-performance.md:244).

    One block is tombstoned the way a retirement does it -- `state` 0 -> 1, `0001_init.sql:266`,
    *"0=live 1=tombstone. There is no DELETE."* -- and the report is asserted to keep the row in
    the denominator while reporting the live count beside it. **Which of the two 12:244 means is
    not settled by this test**; what is settled is that changing it silently now fails.
    """
    connection = ow.connect(sized_store)
    try:
        connection.execute(
            "UPDATE block SET state = 1 WHERE block_id = ("
            "  SELECT block_id FROM block WHERE kind = ("
            "    SELECT ord FROM enum_val WHERE domain = 'kind' AND name = 'paragraph'"
            "  ) ORDER BY block_id LIMIT 1)"
        )
        connection.commit()
    finally:
        connection.close()

    report = _sizing(sized_store)
    assert report.blocks == SIZING_BLOCKS
    assert report.live_blocks == SIZING_BLOCKS - 1
    assert report.kind("paragraph").blocks == 3
    assert report.kind("paragraph").live == 2
    assert report.composition(MIXED).blocks == SIZING_BLOCKS
    assert report.files.db_bytes == sized_store.stat().st_size
    assert report.bytes_per_block == pytest.approx(report.files.db_bytes / SIZING_BLOCKS)
    assert report.bytes_per_block != pytest.approx(report.files.db_bytes / (SIZING_BLOCKS - 1))
    assert f"{SIZING_BLOCKS - 1:,} live" in report.render()


def test_the_document_and_page_counts_are_read_from_their_own_tables(sized_store: Path) -> None:
    """MUTATION KILLED: counting `documents` out of `page`.

    The fixture had one `doc` row and one `page` row, so the two tables were indistinguishable
    and `documents` was asserted nowhere at all. A second `page` row is added here -- a copy of
    the first at `page + 1`, which is what a two-page document is in this schema -- so the two
    counts differ and `blocks_per_page` gets a denominator that is neither the block count nor
    the document count.
    """
    connection = ow.connect(sized_store)
    try:
        connection.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, rotation, quad_origin, method, "
            "producer_id) SELECT doc_ord, gen, page + 1, page_kind, rotation, quad_origin, "
            "method, producer_id FROM page"
        )
        connection.commit()
    finally:
        connection.close()

    report = _sizing(sized_store)
    assert report.documents == 1
    assert report.pages == 2
    assert report.blocks == SIZING_BLOCKS
    assert report.blocks_per_page == pytest.approx(SIZING_BLOCKS / 2)


# --- the rows that measured zero because their tables were empty --------------------------------


def test_a_whole_table_component_charges_the_rows_it_actually_finds(sized_store: Path) -> None:
    """MUTATION KILLED: `_one_component` adding nothing at all for `spec.tables`.

    07:1034, :1035 and :1036 charge `block_sec`, `segment_block` and `mark`/`rel`/`ref_site` a
    combined ~110 of the plan's ~636 B/block, and all five of those tables are empty in
    `sized_store`. So the code that measures them contributed 0.0 to every assertion in section
    5, and could have been deleted outright without a test noticing.

    Four `mark` rows are written -- the sparse inline formatting of 07:1036's own row, and the
    one of the five tables that can be filled with an `INSERT` and a block id -- and the
    `sparse` component is asserted against `_expected_record_bytes` rather than against the
    module's own arithmetic. `covers` is asserted too: a row that measured the bytes and then
    described them as something else is a report a reviewer cannot attack line by line (07:1017).
    """
    before = _sizing(sized_store)
    assert before.component("sparse").measured == 0.0

    connection = ow.connect(sized_store)
    try:
        targets = [
            int(row[0])
            for row in connection.execute("SELECT block_id FROM block ORDER BY block_id LIMIT 4")
        ]
        connection.executemany(
            "INSERT INTO mark(block_id, a, b, kind, value) VALUES(?, 0, 4, 'emph', NULL)",
            [(block_id,) for block_id in targets],
        )
        connection.commit()
        expected = _expected_record_bytes(connection, "mark", alias="mark_id")
        report = store_sizing(connection, path=sized_store)
    finally:
        connection.close()

    assert len(targets) == 4
    assert expected > 0
    sparse = report.component("sparse")
    assert sparse.state == MEASURED
    assert sparse.measured == pytest.approx(expected / SIZING_BLOCKS)
    assert sparse.measured is not None and sparse.measured > 0.0
    assert "`mark` (4 row(s))" in sparse.covers
    assert "`rel` (0 row(s))" in sparse.covers


# --- the report as an artefact somebody reads ---------------------------------------------------


def test_the_report_carries_every_row_of_the_plans_table_in_one_fixed_order(
    sized_store: Path,
) -> None:
    """MUTATION KILLED: `_components` returning `*rows[7:12]` where it returns `*rows[7:]`.

    That drops `sparse` (07:1036) out of the reported tuple while leaving it in `DECOMPOSITION`,
    so the estimate arithmetic still summed to 636 and the total still counted the row. The only
    thing that changed was that the reviewer's table lost a line -- and nothing in section 5
    ever looked up `segment_block` or `sparse`, so those two rows were reachable by no assertion.

    Order is pinned as well as membership, because `render()` prints the rows in tuple order and
    07:1030's subtotal has to sit under the seven rows it subtotals.
    """
    report = _sizing(sized_store)
    assert tuple(row.key for row in report.components) == SIZING_COMPONENT_KEYS
    assert len(SIZING_COMPONENT_KEYS) == len(DECOMPOSITION) + 3
    assert {spec.key for spec in DECOMPOSITION} < set(SIZING_COMPONENT_KEYS)
    rendered = report.render()
    for spec in DECOMPOSITION:
        assert spec.component in rendered, spec.key
        assert f"{spec.plan_line:>6}" in rendered, spec.key


def test_the_plans_table_has_no_component_row_the_transcription_left_out() -> None:
    """The transcription cross-check, run in the direction section 5 does not run it.

    `test_every_decomposition_row_is_transcribed_from_the_line_it_names` walks `DECOMPOSITION`
    and looks each row up in `_plan/`, so a row the PLAN has and the module lacks is invisible to
    it. A dropped row was caught only by the estimate arithmetic, and only because 07:1030 and
    07:1037 happen to be transcribed independently -- which is a coincidence of this particular
    table and not a property of transcriptions. This walks 07's own table instead and asserts
    the module accounts for every line of it, which is rule 4 in the direction that catches an
    omission rather than an invention.
    """
    plan = _plan_table_rows()
    first = min(spec.plan_line for spec in DECOMPOSITION)
    section = {line for line in plan if first <= line <= TOTAL_LINE}
    transcribed = {spec.plan_line for spec in DECOMPOSITION} | {SUBTOTAL_LINE, TOTAL_LINE}
    assert section == transcribed
    assert len(section) == 15
    assert len(DECOMPOSITION) == 13


def test_the_rendered_report_says_dbstat_was_absent_on_a_line_of_its_own(
    sized_store: Path,
) -> None:
    """MUTATION KILLED: deleting the `dbstat` line from `_render_lines`.

    Section 5 asserted the degraded path three ways on the VALUE OBJECT and never once on
    `render()`, which is the only artefact an operator actually reads. So the line naming the
    degradation could be removed and the suite stayed green: the printed report would carry
    three components with no measurement and no visible reason, which is exactly the *"'I could
    not read them' must not read like 'they were fine'"* failure 07:3184-3185 names.

    Both arms are asserted, because P2 is being built on a Windows CPython whose bundled SQLite
    omits `SQLITE_ENABLE_DBSTAT_VTAB` and CI's Linux runner frequently has it.
    """
    connection = ow.connect(sized_store)
    try:
        degraded = store_sizing(_NoDbstat(connection), path=sized_store)
        healthy = store_sizing(connection, path=sized_store)
    finally:
        connection.close()

    printed = degraded.render()
    lines = [line for line in printed.split("\n") if line.startswith("dbstat")]
    assert len(lines) == 1
    assert lines[0].split()[1] == "ABSENT"
    assert "SQLITE_ENABLE_DBSTAT_VTAB" in lines[0]
    assert UNCHECKED in printed
    assert degraded.component("block_indexes").reason in printed

    healthy_lines = [line for line in healthy.render().split("\n") if line.startswith("dbstat")]
    assert len(healthy_lines) == 1
    # The STATUS TOKEN and not a substring: `_NO_DBSTAT` itself ends "...is available for
    # indexes or FTS shadow tables", so `"available" in line` is true on the ABSENT arm too.
    assert healthy_lines[0].split()[1] == ("available" if healthy.dbstat else "ABSENT")


# --- `tools/measure_store.py`, run rather than grepped ------------------------------------------


def _fake_budget(value: float, *, ratchet: bool = False) -> Any:
    """One `[[budget]]` row, built here so a test can choose which side of tolerance it is on.

    `ratchet` defaults False so the two-sided tests below keep asserting the two-sided rule. The
    SHIPPED `store.bytes_per_block` row carries `ratchet = true`; that asymmetry is the subject of
    `test_a_ratchet_is_not_breached_by_a_figure_below_its_band` and it is not a default.
    """
    row: dict[str, Any] = {"id": measure_store.BUDGET_ID, "value": value, "tol_pct": 10}
    if ratchet:
        row["ratchet"] = True
    return measure_store.Budget(
        id=measure_store.BUDGET_ID,
        value=value,
        tol_pct=10,
        tol_abs=None,
        row=MappingProxyType(row),
    )


def test_a_ratchet_is_not_breached_by_a_figure_below_its_band() -> None:
    """A RATCHET'S TOLERANCE IS ONE-SIDED, and this is the defect this test was written for.

    12-performance.md:244 spells `store.bytes_per_block` as *"a ratchet: it may fall and never
    rise"* and :1655 as *"cannot be raised at all"*. The first cut of `measure_store.py` compared
    with `abs(measured - value) <= tolerance` and printed 394 B/block -- the real measured figure
    at 5,000 pages -- as OUTSIDE tolerance, one line above a caveat saying a breach of this row
    cannot be raised away. A reader had no way to tell an over-budget store from a store that had
    just got smaller, which is the only thing a ratchet is for.

    The literals are pinned, not derived from the row, because a test that recomputed
    `value +/- tolerance` from the same object it is interrogating would pin agreement and not
    value: it would pass just as happily against a two-sided comparison.
    """
    ratchet = _fake_budget(660.0, ratchet=True)
    assert ratchet.ratchet is True
    # BELOW the band: the direction the ratchet exists to produce. Not a breach.
    assert not ratchet.breaches(394.0), "a ratchet that fell was reported as breached"
    assert not ratchet.breaches(0.0), "a ratchet cannot be breached downwards at any magnitude"
    # INSIDE, and at the exact ceiling: not a breach.
    assert not ratchet.breaches(660.0)
    assert not ratchet.breaches(726.0)
    # ABOVE the ceiling by one: the only breach a ratchet has.
    assert ratchet.breaches(727.0), "a ratchet that rose past its ceiling was not reported"

    # And the two-sided question is still asked, and still answered two-sidedly, by `within` --
    # so the fix widened the vocabulary rather than redefining the old word.
    assert not ratchet.within(394.0)

    # A NON-ratchet row breaches on BOTH sides. Without this the assertions above would hold for
    # an implementation that simply never breaches downwards, ratchet or not.
    plain = _fake_budget(660.0)
    assert plain.ratchet is False
    assert plain.breaches(394.0), "a non-ratchet row must breach below its band too"
    assert plain.breaches(727.0)
    assert not plain.breaches(660.0)


def test_the_shipped_bytes_per_block_row_is_the_ratchet_the_plan_says_it_is() -> None:
    """The asymmetry above only matters because the SHIPPED row carries it.

    `_fake_budget` can declare anything; this reads `eval/perf.toml`. 12-performance.md:244 is the
    definition site and charter.md:7618-7623 the transcription source, and both mark this row a
    ratchet -- it is the only one of the twelve that does.
    """
    root = _repo_root(Path(__file__).resolve())
    perf = root / "eval" / "perf.toml"
    if not perf.exists():
        pytest.skip("eval/perf.toml has not landed yet")
    budget = load_budget(perf, "store.bytes_per_block")
    assert budget.ratchet is True, (
        "the shipped store.bytes_per_block row lost `ratchet = true`. 12-performance.md:244 and "
        "charter.md:7618-7623 both carry it, and without it a store that got smaller reads as a "
        "breach."
    )
    assert not budget.breaches(394.0), "the measured 5,000-page figure reads as a breach"
    assert budget.breaches(727.0)

    rows = tomllib.loads(perf.read_text(encoding="utf-8"))["budget"]
    ratchets = sorted(r["id"] for r in rows if r.get("ratchet"))
    assert ratchets == ["store.bytes_per_block"], (
        "12-performance.md:233-247 marks exactly one of the twelve rows a ratchet; the register "
        f"now marks {ratchets}"
    )


def _fake_measurement(store: Path) -> Any:
    """A `Measurement` over a REAL `SizingReport`, without running the generator or an ingest.

    Contract F1's generator and F2's stub driver are exercised end to end by an integration
    pass; what these tests are about is what the runner PRINTS given a measurement, which needs
    a real report and nothing else. Every other field is a literal, so the printed text is
    determined entirely by this file.
    """
    report = _sizing(store)
    return measure_store.Measurement(
        pages=1,
        pdf=Path("fixtures/generated/gen_1p.pdf"),
        pdf_bytes=4096,
        pdf_sha256="0" * 64,
        ingest_seconds=0.25,
        floor_bytes=report.files.db_bytes // 2,
        report=report,
        peak_rss=512_000_000,
        peak_rss_source="a literal, so this test does not depend on the runner's memory",
    )


def test_the_runner_prints_an_indication_and_never_a_verdict_on_either_side_of_tolerance(
    sized_store: Path,
) -> None:
    """MUTATION KILLED: printing `VERDICT  budget PASS` and dropping the ow-bench-1 caveat.

    That mutation left all three of section 5's `measure_store` tests green, because they read
    the script's SOURCE and grep it for `MACHINE_CAVEAT` (which survives in the import line),
    `ow-bench-1` and `INDICATION` (which survive in the module docstring). Rule 3: a comment is
    not a definition site, and neither is a docstring. This test runs `_report` and reads what
    came out of it.

    Both sides of tolerance are exercised, and the INSIDE arm is the one that matters:
    12-performance.md:1966 makes `ow-bench-1` the only machine a Budget may live on, so a
    measurement that happens to land inside 660 +/- 10% on a developer's laptop must still not
    be reported as a pass. A sixteen-block store is thousands of bytes a block, so the outside
    arm is reached with the register's real 660 and the inside arm with a row built to contain
    the measurement.
    """
    measurement = _fake_measurement(sized_store)
    measured = measurement.report.bytes_per_block
    assert measured > 726.0, "a 16-block store is nowhere near 660 B/block; the fixture changed"

    outside: list[str] = []
    assert measure_store._report(measurement, _fake_budget(660.0), "", outside.append) is False
    inside: list[str] = []
    assert measure_store._report(measurement, _fake_budget(measured), "", inside.append) is True

    for lines, word in ((outside, "OUTSIDE"), (inside, "inside")):
        printed = "\n".join(lines)
        assert f"INDICATION         {word} tolerance" in printed
        assert MACHINE_CAVEAT in printed
        assert "ow-bench-1" in printed
        assert "no baseline was written" in printed
        assert "not F1's answer" in printed
        for forbidden in ("VERDICT", "BUDGET OK", "budget is met", "budget met", "PASS", "FAIL"):
            assert forbidden not in printed, forbidden


def test_the_runner_prints_peak_rss_as_informational_and_compares_it_to_nothing(
    sized_store: Path,
) -> None:
    """Ruling D26, asserted on the OUTPUT rather than on the source's numeric literals.

    Section 5 proved 1,610,612,736 is not a literal in the script's code, which is necessary and
    not sufficient: a runner that omitted the figure entirely, or printed it bare with no label,
    passes that assertion. The reader has to be told the number exists, that it is deferred, and
    which phase owns it -- because a peak-RSS figure printed next to a store measurement with no
    label reads like a budget that was checked.
    """
    lines: list[str] = []
    measure_store._report(_fake_measurement(sized_store), _fake_budget(660.0), "", lines.append)
    printed = "\n".join(lines)
    assert "rss.gen5000p_peak_bytes" in printed
    assert "512,000,000 B" in printed
    assert "INFORMATIONAL" in printed
    assert "anydoc is W3.4 = P3" in printed
    assert "Not compared to 1,610,612,736 here" in printed


def test_the_runner_says_no_comparison_was_made_when_the_register_is_unreadable(
    sized_store: Path,
) -> None:
    """An absent `eval/perf.toml` must produce a measurement and a named absence, not a silence.

    `load_budget` raising is the design -- a second copy of 660 in the script is the thing the
    register exists to prevent -- and the branch that handles the raise returns True so `--gate`
    cannot fail on a file another wave has not written yet. Both halves are asserted: the reason
    is printed, and the measurement above it is printed anyway.
    """
    lines: list[str] = []
    reason = "eval/perf.toml does not exist; it is W10.4 and 12-performance.md:207 owns it"
    assert measure_store._report(_fake_measurement(sized_store), None, reason, lines.append) is (
        True
    )
    printed = "\n".join(lines)
    assert "register           UNREADABLE" in printed
    assert reason in printed
    assert "no comparison was made. The measurement above still stands." in printed
    assert "INDICATION" not in printed
    assert measure_store.BUDGET_ID in printed


def _measure_stub(store: Path, seen: list[Path]) -> Any:
    """A stand-in for `measure()` that records its workspace and leaves one byte behind in it."""

    def measure(workspace: Path, *, pages: int, out: Path | None) -> Any:  # noqa: ARG001
        seen.append(workspace)
        (workspace / "left-behind.txt").write_text("state no second run recreates\n", "utf-8")
        return _fake_measurement(store)

    return measure


def test_the_runner_removes_the_workspace_it_owns_and_keeps_the_one_it_was_handed(
    sized_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION KILLED: deleting `shutil.rmtree(workspace)` from `main`'s `finally`.

    No test ran `main` to completion, so the whole workspace lifecycle -- mint a tempdir, build
    two `.owstore` files inside it, remove it unless `--keep` -- was unexercised. The corollary
    this is written against: **a cleanup step is only tested by state the next run will not
    recreate.** `mkdtemp` is stubbed to hand out a NEW directory on every call, and the
    assertion is that the FIRST one is gone after the first run; a stub that reused one path
    would have made the assertion meaningless the moment a later run recreated it.

    Three lifecycles, because they are three different contracts: an owned tempdir is removed,
    `--keep` suppresses the removal, and a `--workspace` the caller named is never the runner's
    to delete and mints no tempdir at all.
    """
    seen: list[Path] = []
    made: list[Path] = []

    def fake_mkdtemp(prefix: str = "") -> str:
        path = tmp_path / f"owned-{len(made)}-{prefix}"
        path.mkdir()
        made.append(path)
        return str(path)

    perf = tmp_path / "perf.toml"
    perf.write_text(
        '[[budget]]\nid = "store.bytes_per_block"\nvalue = 660\ntol_pct = 10\n', encoding="utf-8"
    )
    monkeypatch.setattr(measure_store, "PERF_TOML", perf)
    monkeypatch.setattr(measure_store, "GENERATOR", Path(__file__))
    monkeypatch.setattr(measure_store, "STUB_DRIVER", Path(__file__))
    monkeypatch.setattr(measure_store, "measure", _measure_stub(sized_store, seen))
    monkeypatch.setattr(measure_store.tempfile, "mkdtemp", fake_mkdtemp)

    assert measure_store.main([], out=StringIO()) == measure_store.EXIT_CLEAN
    assert seen == made
    assert not made[0].exists(), "main() left on disk the tempdir it minted"

    assert measure_store.main(["--keep"], out=StringIO()) == measure_store.EXIT_CLEAN
    assert made[1].exists()
    assert (made[1] / "left-behind.txt").is_file()

    given = tmp_path / "given"
    assert measure_store.main(["--workspace", str(given)], out=StringIO()) == (
        measure_store.EXIT_CLEAN
    )
    assert (given / "left-behind.txt").is_file()
    assert len(made) == 2, "a --workspace run must not mint a tempdir"
    assert seen == [*made, given]


def test_a_measurement_outside_tolerance_is_exit_zero_unless_gate_was_asked_for(
    sized_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MUTATION KILLED: making `--gate` the default.

    This is 12-performance.md:1966 expressed as an exit code, and it was asserted nowhere. The
    fixture's measurement is thousands of bytes a block against a 660 +/- 10% row, so the
    indication is OUTSIDE on both runs below; the default run must still exit 0, because on any
    machine that is not `ow-bench-1` an exit code derived from a Budget is a claim the machine
    is not entitled to make. `--gate` opts into it, and the output says in as many words that
    the exit code is the flag's contract rather than a statement about the budget.

    The register is written here rather than read out of `eval/perf.toml`, so what this pins is
    the exit-code contract and not another wave's file.
    """
    perf = tmp_path / "perf.toml"
    perf.write_text(
        '[[budget]]\nid = "store.bytes_per_block"\nvalue = 660\ntol_pct = 10\n', encoding="utf-8"
    )
    monkeypatch.setattr(measure_store, "PERF_TOML", perf)
    monkeypatch.setattr(measure_store, "GENERATOR", Path(__file__))
    monkeypatch.setattr(measure_store, "STUB_DRIVER", Path(__file__))
    monkeypatch.setattr(measure_store, "measure", _measure_stub(sized_store, []))

    plain = StringIO()
    assert measure_store.main(["--workspace", str(tmp_path / "w1")], out=plain) == (
        measure_store.EXIT_CLEAN
    )
    assert "OUTSIDE tolerance" in plain.getvalue()

    gated = StringIO()
    assert measure_store.main(["--gate", "--workspace", str(tmp_path / "w2")], out=gated) == (
        measure_store.EXIT_FAIL
    )
    assert "EXIT 1  --gate was passed" in gated.getvalue()
    assert "not a statement about the budget" in gated.getvalue()
