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

import json
import re
import sqlite3  # noqa: TID251 -- see the module docstring: this file seeds residue tables in SQL.
import zipfile
from pathlib import Path
from types import MappingProxyType
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
from omniweave_core.model.block import BlockDraft, Mark
from omniweave_core.model.records import Diag, DocRecord, PageRecord
from omniweave_core.model.spans import OriginBytes
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.indexlock import LockFile, LockHeader, LockRow, write_lock
from omniweave_core.store.inspect import (
    ADDED,
    CHANGED,
    DEFAULT_GROUP_LIMIT,
    INDEX_REGISTER,
    MISSING,
    MS_PER_NS,
    OK,
    PENDING,
    REMOVED,
    REPARSED,
    RESIDUE_TABLES,
    UNUSED,
    diff_lock,
    diff_stores,
    explain_indexes,
    lock_rows,
    residue,
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
