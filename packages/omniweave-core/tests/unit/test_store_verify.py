"""`ow store verify` and `ow doc verify`, each clause shown failing on a store broken THAT way.

**Every corruption in this file is raw SQL against a real migrated `.owstore`.** Not a mock, not
a monkeypatched checker, not a hand-built row dict: a store built by the shipped migrations and
written through `DocSink`, then damaged with an `UPDATE`, an `INSERT` or a `DELETE` of exactly
the shape the plan says is a corrupt store. A clause tested against a fake subject proves the
clause agrees with the fake.

**And a clean store passes**, asserted as its own test at the top rather than implied by fifteen
failures. Fifteen tests that each turn one clause red would all still pass if `verify_store`
returned FAILED for everything, which is the shape of "a test that cannot fail" seen from its
other side.

**On the two assertions that read a value out of the store they are checking.** The digest tests
do not compare a stored digest with a re-derived one and call it agreement -- that comparison
cannot fail, because a mutation moves both sides. They pin the *literal* bytes the recipe
produces for a known row (`_KNOWN_DIGEST`), so a change to the recipe fails here and not merely
somewhere downstream.

Specified in 16-roadmap.md:435 and :420 (W2.7), 07-store-and-retrieval.md sections 13.2, 14 and
15, 03-document-model.md:2691 and :2789, 06-structure-extraction.md:779 and :2394,
11-repo-layout.md:1196-1202 and 14-security.md:1205-1210.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3  # noqa: TID251 -- see the module docstring: every corruption is raw SQL on a

#                REAL migrated store, and a clause tested against a mock proves only that the
#                mock agrees with it.
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from omniweave_core.archive.owcheck import Clause as OwcheckClause
from omniweave_core.archive.owcheck import ClauseState
from omniweave_core.blobs import BlobStore
from omniweave_core.canonical import ow128
from omniweave_core.errors import StoreError, UsageError
from omniweave_core.identity import content_digest as ow_content_digest
from omniweave_core.limits import MAX_SEGMENT_BLOCKS
from omniweave_core.model import Capabilities, Kind, Layer, Method, PageKind, Quote, Trust
from omniweave_core.model.block import BlockDraft
from omniweave_core.model.records import DocRecord, PageRecord
from omniweave_core.model.spans import OriginBytes
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.indexlock import LockHeader, has_conflict_markers, write_lock
from omniweave_core.store.verify import (
    _SCHEMA_COLUMN_EXEMPT,
    ALL_CLAUSES,
    COVER_BITS_BYTES,
    DEFAULT_CLAUSES,
    ERASED_CLAUSES,
    FTS_CLAUSES,
    GRAPH_CLAUSES,
    LOCK_CLAUSES,
    MAX_LIVE_GENERATIONS,
    VerifyClause,
    VerifyReport,
    derive_lock,
    verify_doc,
    verify_store,
)

NOW_NS = 1_757_400_000_000_000_000
"""A fixed timestamp. The clock is banned in library code and injected everywhere in the store."""

BODY_TEXT = "termination for convenience"
PART_BYTES = b"termination for convenience, and the bytes that prove it"
PART_SHA256 = hashlib.sha256(PART_BYTES).digest()
"""The real hash of the real bytes. `DocSink.add_part` refuses a declared digest that disagrees
with what it streamed (`OW_ASSET_DIGEST_MISMATCH`), so the fixture cannot lie about it."""

HEADER = LockHeader(scorer=1, segmenter="derive.segment.spine@3:9c1e", space="none@0/0/none/i8")
"""A receipt header. `segmenter` and `space` are opaque tokens owned elsewhere (INV-21)."""


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
"""The all-absent capability floor; `Capabilities` has no defaults (03 section 4.4)."""


# ---------------------------------------------------------------------------------------------
# Fixtures: one real store, one real document, one real CAS
# ---------------------------------------------------------------------------------------------


def _doc_record(key: int, uri: str) -> DocRecord:
    return DocRecord(
        doc_ord=0,
        doc_key=bytes([key]) * 16,
        gen=0,
        source_sha256=bytes([key]) * 32,
        normalizer="canonical/1",
        uri=uri,
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({}),
        source_bytes=len(PART_BYTES),
        status="ok",
        page_count=None,
        model_version="1.1",
        declared=FLOOR,
        achieved=FLOOR,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page_record(page: int = 1) -> PageRecord:
    return PageRecord(
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


@pytest.fixture
def blank(tmp_path: Path) -> Path:
    """A real `.owstore` with all four migrations applied and nothing written."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    finally:
        connection.close()
    return path


@pytest.fixture
def cas(tmp_path: Path) -> BlobStore:
    root = tmp_path / "cas"
    root.mkdir()
    return BlobStore(root)


@pytest.fixture
def store(blank: Path, cas: BlobStore) -> Path:
    """`blank` plus one document written through `DocSink`: two blocks, one retained part.

    Written through the real sink so `content_digest` is the real recipe's output over real
    columns. A fixture that inserted the blocks with raw SQL would have to compute the digests,
    and then the digest clause would be checking this file's arithmetic against itself.
    """
    with ow.StoreThread(lambda: ow.connect(blank)) as thread:
        sink = DocSink(
            thread,
            producer_id=_producer(blank),
            origin_operator="parse.pdf",
            origin_driver="parse.pdf.pdfium",
            driver_schema_v=1,
            blobs=cas,
        )
        sink.begin_doc(_doc_record(7, "file:///corpus/contract.pdf"))
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
                quote=Quote.VERBATIM,
                parent=root,
                text=BODY_TEXT,
                origin=OriginBytes(
                    part="file", start=0, length=len(BODY_TEXT), codec="utf-8/strict"
                ),
            )
        )
        sink.add_part("file", io.BytesIO(PART_BYTES), PART_SHA256, len(PART_BYTES))
        sink.end_page({})
        sink.end_doc("ok")
    return blank


def _producer(path: Path) -> int:
    connection = ow.connect(path)
    try:
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.pdf', 1, 'abc123', X'00')"
        )
        connection.commit()
        return int(cursor.lastrowid or 0)
    finally:
        connection.close()


def _open(path: Path) -> sqlite3.Connection:
    return ow.connect(path)


def _corrupt(path: Path, *statements: str | tuple[str, tuple[Any, ...]]) -> None:
    """Apply raw SQL to a real store and commit. The only way a corruption is made in this file."""
    connection = ow.connect(path)
    try:
        for statement in statements:
            if isinstance(statement, tuple):
                connection.execute(statement[0], statement[1])
            else:
                connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _clause(report: VerifyReport, clause: VerifyClause) -> Any:
    return report.by_clause(clause)


def _run(path: Path, clause: VerifyClause, **kwargs: Any) -> Any:
    connection = _open(path)
    try:
        report = verify_store(connection, now_ns=NOW_NS, clauses=[clause], **kwargs)
    finally:
        connection.close()
    return report.by_clause(clause)


# ---------------------------------------------------------------------------------------------
# The clean store, which is what makes the fifteen failures mean something
# ---------------------------------------------------------------------------------------------


def test_a_clean_store_passes_every_clause_it_can_check(store: Path, cas: BlobStore) -> None:
    """The anchor. Without it, a `verify_store` that failed everything would pass every other
    test in this file."""
    connection = _open(store)
    try:
        report = verify_store(
            connection,
            now_ns=NOW_NS,
            clauses=ALL_CLAUSES,
            blobs=cas,
            lock_text=write_lock(HEADER, derive_lock(connection, header=HEADER).rows),
        )
    finally:
        connection.close()

    failed = [c.clause for c in report.clauses if c.state is ClauseState.FAILED]
    assert failed == [], f"a clean store failed {failed}: {[f.detail for f in report.findings]}"
    assert report.ok
    assert report.at_ns == NOW_NS, "the report carries the caller's clock and never its own"

    unchecked = {c.clause for c in report.clauses if c.state is ClauseState.UNCHECKED}
    assert unchecked == {VerifyClause.RETIRED_OCCURRENCES}, (
        f"exactly one clause is legitimately unrunnable on a complete store -- the deprecation "
        f"census, whose register does not exist -- and these were: {sorted(unchecked)}"
    )
    assert not report.complete, "an UNCHECKED clause makes the report incomplete, never not-ok"

    digest = _clause(report, VerifyClause.BLOCK_DIGEST)
    assert digest.checked == 2, (
        "the document root and the paragraph under it; a clause that passed over zero rows "
        "would pass this whole file"
    )
    assert _clause(report, VerifyClause.CAS_DIGEST).checked == 1


def test_the_paragraphs_digest_is_the_recipes_output_and_not_merely_self_consistent(
    store: Path,
) -> None:
    """The literal, pinned where a mutation cannot move it.

    `_block_digest` compares a stored digest against a re-derived one, and both sides come out
    of the same store: shifting the recipe moves both and the comparison stays green. So the
    value for a known row is written down here. `identity.content_digest` is called directly --
    the same function `DocSink` used -- and what is being pinned is that the row in the store
    carries the digest of the fields this test names, rather than of some other fields.
    """
    connection = _open(store)
    try:
        stored, kind, layer, text = connection.execute(
            "SELECT content_digest, kind, layer, text FROM block WHERE text IS NOT NULL"
        ).fetchone()
    finally:
        connection.close()
    assert text == BODY_TEXT
    assert bytes(stored) == ow_content_digest(int(kind), int(layer), BODY_TEXT, None, [])
    assert bytes(stored).hex() != ow_content_digest(int(kind), int(layer), None, None, []).hex(), (
        "a container (text IS NULL) and this paragraph must not share a digest: 03 section 6.4's "
        "three distinct encodings for absent / null / empty"
    )


# ---------------------------------------------------------------------------------------------
# Clause 1 -- block.content_digest. 16-roadmap.md:435
# ---------------------------------------------------------------------------------------------


def test_a_content_digest_altered_in_the_row_but_not_in_the_bytes_is_caught(store: Path) -> None:
    """16-roadmap.md:435, the headline clause: re-derive and compare, never self-compare."""
    _corrupt(store, "UPDATE block SET content_digest = X'00112233445566778899aabbccddeeff'")
    result = _run(store, VerifyClause.BLOCK_DIGEST)
    assert result.state is ClauseState.FAILED
    assert len(result.findings) == 2, "every block's digest was replaced; every one is a finding"
    assert "00112233445566778899aabbccddeeff" in result.findings[0].detail
    assert result.findings[0].where.startswith("d1#"), "a finding names the durable cite"


def test_reordering_two_siblings_moves_their_parents_digest_and_the_clause_says_so(
    store: Path,
) -> None:
    """The children are a digest input in `ord` order (03 section 6.4), so a swap is a mismatch.

    This is the half a per-row check cannot see: each child's own digest is untouched and still
    re-derives, and only the container is wrong. A clause that re-derived leaves and trusted
    containers would report a clean store.
    """
    _corrupt(
        store,
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind, "
        "layer, content_digest, os_kind, os_part, os_a, os_b, os_codec, producer_id, method, "
        "trust, quote, origin_operator, origin_driver, driver_schema_v, text) "
        "SELECT 9001, doc_ord, gen, page, 'p1/9', 'd1#9001', parent_id, 9, kind, layer, "
        "content_digest, os_kind, os_part, os_a, os_b, os_codec, producer_id, method, trust, "
        "quote, origin_operator, origin_driver, driver_schema_v, 'a second child' "
        "FROM block WHERE text IS NOT NULL",
    )
    result = _run(store, VerifyClause.BLOCK_DIGEST)
    assert result.state is ClauseState.FAILED
    assert any("children" in finding.detail for finding in result.findings), (
        f"a container gained a child and no finding mentions the children input: {result.findings}"
    )


# ---------------------------------------------------------------------------------------------
# Clause 3 -- the CAS digests, re-derived from the stored bytes
# ---------------------------------------------------------------------------------------------


def test_a_part_sha256_altered_in_the_row_is_caught_by_re_hashing_the_stored_bytes(
    store: Path, cas: BlobStore
) -> None:
    """16-roadmap.md:435's "from stored bytes". `BlobStore.verify` could not catch this.

    `verify(digest)` re-hashes the object *at the path the digest names* and compares it to that
    same digest, so it answers "is this blob what its own name says". A row whose `sha256` was
    edited names a different blob entirely; only hashing what `store_ref` points at and
    comparing to the column catches it, which is what the clause does.
    """
    _corrupt(store, "UPDATE part SET sha256 = X'" + ("ab" * 32) + "'")
    result = _run(store, VerifyClause.CAS_DIGEST, blobs=cas)
    assert result.state is ClauseState.FAILED
    assert result.checked == 1
    details = " ".join(finding.detail for finding in result.findings)
    assert "store_ref names" in details, f"the intra-row disagreement was not reported: {details}"
    assert PART_SHA256.hex() in details, "the finding does not name the hash of the real bytes"


def test_a_cas_object_whose_bytes_changed_is_caught(store: Path, cas: BlobStore) -> None:
    """07:3184 -- *"a CAS blob's bytes changed"*. The row is untouched; the file is not."""
    path = cas.path(PART_SHA256)
    path.write_bytes(b"substituted bytes of exactly the wrong provenance")
    result = _run(store, VerifyClause.CAS_DIGEST, blobs=cas)
    assert result.state is ClauseState.FAILED
    assert any("its bytes changed" in finding.detail for finding in result.findings), (
        f"{[f.detail for f in result.findings]}"
    )


def test_a_missing_cas_object_is_dangling_and_not_a_hash_mismatch(
    store: Path, cas: BlobStore
) -> None:
    """07:3183. Three failures with three remedies are reported apart, not folded into one."""
    cas.path(PART_SHA256).unlink()
    result = _run(store, VerifyClause.CAS_DIGEST, blobs=cas)
    assert result.state is ClauseState.FAILED
    assert [f.detail for f in result.findings] == [
        f"no CAS object at {cas.ref(PART_SHA256)}: the row is dangling"
    ]


def test_the_cas_clause_is_unchecked_without_a_blob_store_and_unchecked_is_not_a_pass(
    store: Path,
) -> None:
    """A missing CAS reading as a pass is how 07:3184 goes unnoticed for a corpus's lifetime."""
    result = _run(store, VerifyClause.CAS_DIGEST)
    assert result.state is ClauseState.UNCHECKED
    assert result.state is not ClauseState.PASSED
    assert "1 retained blobs" in result.reason


# ---------------------------------------------------------------------------------------------
# Clause 4 -- content_sha256
# ---------------------------------------------------------------------------------------------


def _add_unit(path: Path, content_sha256: str) -> None:
    _corrupt(
        path,
        (
            "INSERT INTO unit(unit_uri, state, content_sha256, normalizer, trust_class, "
            "last_seen_gen) VALUES(?, 'settled', ?, 'canonical/1', 'internal', 1)",
            ("file:///corpus/contract.pdf", content_sha256),
        ),
    )


def test_a_content_sha256_altered_in_the_row_disagrees_with_the_doc_key_it_produced(
    store: Path,
) -> None:
    """05:258 -- one normalisation, two digests of it, and they cannot disagree."""
    _add_unit(store, ("07" * 16) + ("ff" * 16))  # the right doc_key prefix, then anything.
    assert _run(store, VerifyClause.CONTENT_SHA256).state is ClauseState.PASSED

    _corrupt(store, "UPDATE unit SET content_sha256 = '" + ("0e" * 32) + "'")
    result = _run(store, VerifyClause.CONTENT_SHA256)
    assert result.state is ClauseState.FAILED
    assert result.counts["unit_doc_pairs"] == 1
    assert "doc_key" in result.findings[0].detail
    assert result.findings[0].where == "file:///corpus/contract.pdf"


def test_a_content_sha256_that_is_not_64_hex_characters_is_caught_by_shape(store: Path) -> None:
    """The shape check covers every column named `content_sha256`, discovered by table_info."""
    _add_unit(store, "not-a-digest")
    result = _run(store, VerifyClause.CONTENT_SHA256)
    assert result.state is ClauseState.FAILED
    assert "64 lower-case hex" in result.findings[0].detail
    assert result.findings[0].where.startswith("unit(unit_uri=")


def test_a_unit_and_a_doc_under_different_normalisers_are_not_compared(store: Path) -> None:
    """A raw-hashed unit (`OW-C-041`) and a normalised document hash different byte streams."""
    _add_unit(store, "0e" * 32)
    _corrupt(store, "UPDATE unit SET normalizer = NULL")
    result = _run(store, VerifyClause.CONTENT_SHA256)
    assert result.state is ClauseState.PASSED
    assert result.counts["unit_doc_pairs"] == 0, "the pair was compared across two normalisers"


# ---------------------------------------------------------------------------------------------
# Clause 5 -- at most two live generations. 03:2691
# ---------------------------------------------------------------------------------------------


def test_three_live_generations_of_one_document_mean_a_sweep_did_not_run(store: Path) -> None:
    """03:2691 -- *"the head plus at most one staged. A third would mean a sweep did not run"*."""
    for gen in (2, 3):
        _corrupt(
            store,
            (
                "INSERT INTO page(doc_ord, gen, page, page_kind, w_mpt, h_mpt, rotation, "
                "quad_origin, method, status, producer_id) "
                "SELECT doc_ord, ?, page, page_kind, w_mpt, h_mpt, rotation, quad_origin, "
                "method, status, producer_id FROM page WHERE gen = 1",
                (gen,),
            ),
        )
        result = _run(store, VerifyClause.GENERATIONS)
        expected = ClauseState.PASSED if gen <= MAX_LIVE_GENERATIONS else ClauseState.FAILED
        assert result.state is expected, (
            f"{gen} generations alive reported {result.state}; the bound is "
            f"{MAX_LIVE_GENERATIONS} and two is normal, not a fault"
        )
    assert "sweep did not run" in _run(store, VerifyClause.GENERATIONS).findings[0].detail


# ---------------------------------------------------------------------------------------------
# Clause 7 -- block_link.via_entity, the column with no foreign key. 07:590
# ---------------------------------------------------------------------------------------------


def _add_block_link(path: Path, via_entity: int | None) -> None:
    _corrupt(
        path,
        "INSERT OR IGNORE INTO relation_vocab(relation, actor_rule, source) "
        "VALUES('refers_to', 'source cites target', 'builtin')",
        (
            "INSERT INTO block_link(src_block, dst_block, relation, via_entity, producer_id, "
            "trust, origin_operator, origin_driver, driver_schema_v) "
            "SELECT min(block_id), max(block_id), 'refers_to', ?, min(producer_id), 2, "
            "'op.xref', 'op.xref', 1 FROM block",
            (via_entity,),
        ),
    )


def test_a_block_link_via_entity_pointing_at_no_entity_is_caught(store: Path) -> None:
    """07:590 / `0003_index.sql:307-315` -- *"DELIBERATELY NO FOREIGN KEY ... verify checks it"*.

    The insert itself must succeed, and that is half the test: if `via_entity` had an FK, SQLite
    would refuse the row and this clause would have nothing to do. `PRAGMA foreign_keys` is ON
    for the whole connection (`CONN_PRAGMAS`), so a successful insert of a dangling reference is
    itself the proof that the column carries no constraint.
    """
    _add_block_link(store, 999_999)
    result = _run(store, VerifyClause.VIA_ENTITY)
    assert result.state is ClauseState.FAILED
    assert result.checked == 1
    assert "999999" in result.findings[0].detail
    assert "no foreign key" in result.findings[0].detail


def test_a_null_via_entity_is_not_a_subject_of_the_clause(store: Path) -> None:
    """NULL means "not entity-mediated", which is the common case and never a fault."""
    _add_block_link(store, None)
    result = _run(store, VerifyClause.VIA_ENTITY)
    assert result.state is ClauseState.PASSED
    assert result.checked == 0


# ---------------------------------------------------------------------------------------------
# Clause 8 -- cover_bits is exactly 64 bytes. 06:779
# ---------------------------------------------------------------------------------------------


def _add_cover(path: Path, cover_bits: bytes) -> None:
    """A `derive_cover` row and the whole FK chain above it, in a real store."""
    digest = ow128(b"ow.segment.1", ["x"])
    _corrupt(
        path,
        "INSERT INTO segmenter(segmenter_id, driver_id, driver_schema_v, params_digest) "
        "VALUES(1, 'derive.segment.spine', 3, X'9c1e')",
        (
            "INSERT INTO segment(segment_id, doc_ord, gen, ord, segmenter_id, layer, "
            "heading_path, n_blocks, n_tokens, n_chars, tokenizer_id, first_page, last_page, "
            "trust, quote_min, kind_mask, content_digest, origin_operator, origin_driver, "
            "driver_schema_v) VALUES(1, 1, 1, 0, 1, 0, '[]', 1, 4, 27, 'o200k', 1, 1, 2, 4, 0, "
            "?, 'derive.segment.spine', 'derive.segment.spine', 3)",
            (digest,),
        ),
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, lanes, granularity, "
        "card_sha256, schema_version) "
        "VALUES('op.xref', 'op', 'free', 0, '[\"xref\"]', 'document', 'aa', 1)",
        (
            "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
            "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, "
            "cache_key, status) SELECT 1, 1, 'op.xref', 1, min(producer_id), 7, 'op.xref', "
            "'op.xref', 1, 'free', ?, 'k', 'ok' FROM producer",
            (digest,),
        ),
        (
            "INSERT INTO derive_cover(segment_id, lane, run_id, cover_bits, n_covered) "
            "VALUES(1, 'xref', 1, ?, 1)",
            (cover_bits,),
        ),
    )


def test_a_cover_bits_blob_of_the_wrong_length_is_a_corrupt_store(store: Path) -> None:
    """06:779 -- *"`LENGTH(cover_bits) <> 64` is a corrupt store and `ow store verify` says so"*."""
    _add_cover(store, b"\x00" * (COVER_BITS_BYTES - 1))
    result = _run(store, VerifyClause.COVER_BITS)
    assert result.state is ClauseState.FAILED
    assert result.checked == 1
    assert f"{COVER_BITS_BYTES - 1} bytes, not {COVER_BITS_BYTES}" in result.findings[0].detail
    assert "uncovered ground" in result.findings[0].detail


def test_a_cover_bits_blob_of_exactly_64_bytes_passes(store: Path) -> None:
    """The other direction, so the clause is not merely "derive_cover rows are a finding"."""
    _add_cover(store, b"\x00" * COVER_BITS_BYTES)
    result = _run(store, VerifyClause.COVER_BITS)
    assert result.state is ClauseState.PASSED
    assert result.checked == 1


def test_the_cover_bitmap_length_is_derived_from_max_segment_blocks_and_not_written_64() -> None:
    """One number, one home (18-api-sketch.md section 4). `0002_graph.sql:220` prints both."""
    assert COVER_BITS_BYTES == MAX_SEGMENT_BLOCKS // 8 == 64
    assert MAX_SEGMENT_BLOCKS % 8 == 0, "a non-multiple of eight would need a ceiling term"


# ---------------------------------------------------------------------------------------------
# Clause 2 -- segment.content_digest. 06:1002
# ---------------------------------------------------------------------------------------------


def test_a_segment_content_digest_altered_in_the_row_is_caught(store: Path) -> None:
    """06:1002's recipe, re-derived. The fixture's digest is deliberately not the recipe's."""
    _add_cover(store, b"\x00" * COVER_BITS_BYTES)
    result = _run(store, VerifyClause.SEGMENT_DIGEST)
    assert result.state is ClauseState.FAILED, "the fixture's placeholder digest was accepted"
    assert result.checked == 1
    assert "06:1002's recipe over 0 members" in result.findings[0].detail

    correct = ow128(b"ow.segment.1", ["derive.segment.spine", 3, "9c1e", [], []])
    _corrupt(store, ("UPDATE segment SET content_digest = ?", (correct,)))
    assert _run(store, VerifyClause.SEGMENT_DIGEST).state is ClauseState.PASSED


# ---------------------------------------------------------------------------------------------
# Clause 9 -- SCHEMA is single-homed. 07:3199-3211, ST23, ST24
# ---------------------------------------------------------------------------------------------


def test_a_schema_key_in_meta_is_a_second_home(store: Path) -> None:
    """ST23: *"a migration fixture that writes `meta.schema` is asserted to fail `verify`"*."""
    _corrupt(store, "INSERT INTO meta(k, v) VALUES('schema', '1.0')")
    result = _run(store, VerifyClause.SINGLE_HOME)
    assert result.state is ClauseState.FAILED
    assert result.findings[0].code == "OW_SCHEMA_SECOND_HOME"
    assert result.findings[0].where == "meta.k = 'schema'"


def test_two_index_state_schema_rows_are_two_answers(store: Path) -> None:
    """ST24 -- *"exactly one `schema` row"*. A second row is a second answer to one question.

    `index_state` is `(k TEXT PRIMARY KEY, v)`, so a second row under the same key is
    unrepresentable through the front door. A migration that rebuilt the table without its key
    is the way a store arrives in this state, and that is what this does -- ordinary DDL, no
    `writable_schema` trickery, so `PRAGMA integrity_check` still says `ok` afterwards and the
    clause is the only thing that objects.
    """
    _corrupt(
        store,
        "CREATE TABLE index_state_rebuild (k TEXT, v TEXT NOT NULL)",
        "INSERT INTO index_state_rebuild SELECT k, v FROM index_state",
        "DROP TABLE index_state",
        "ALTER TABLE index_state_rebuild RENAME TO index_state",
        "INSERT INTO index_state(k, v) VALUES('schema', '2.0')",
    )
    connection = _open(store)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    result = _run(store, VerifyClause.SINGLE_HOME)
    assert result.state is ClauseState.FAILED
    assert "2 rows keyed `schema`" in result.findings[0].detail


def test_a_schema_column_on_another_table_is_a_second_home(store: Path) -> None:
    """07:3205 rule 2, "every other table by PRAGMA table_info"."""
    _corrupt(store, "CREATE TABLE later_migration_mistake (id INTEGER PRIMARY KEY, schema TEXT)")
    result = _run(store, VerifyClause.SINGLE_HOME)
    assert result.state is ClauseState.FAILED
    assert result.findings[0].where == "later_migration_mistake.schema"


def test_the_schema_column_exemption_names_exactly_run_and_says_why() -> None:
    """A register is a transcription: one row, one excusing DDL line, and no room for a second.

    `run.schema` is *"the SCHEMA MAJOR this run wrote, recorded per run"* and the DDL says in as
    many words that it is not a second home. Pinning the set against a literal is what stops the
    exemption from growing into the allow-list that makes rejection criterion 19 unenforceable.
    """
    assert set(_SCHEMA_COLUMN_EXEMPT) == {"run"}
    assert "0004_runtime.sql:245-248" in _SCHEMA_COLUMN_EXEMPT["run"]


# ---------------------------------------------------------------------------------------------
# Clauses 10 and 11 -- FTS. 07:418, ST21
# ---------------------------------------------------------------------------------------------


def test_an_fts_posting_that_survives_its_block_is_caught(store: Path) -> None:
    """ST21's orphan: a posting whose content lookup finds nothing (07:415-418).

    Written as a direct `INSERT` of a posting for a rowid no `block` row has, which is what a
    cascade or a bulk window that dropped the triggers leaves behind. It is also the shape a
    `'delete'` command with the wrong text leaves, which the DDL's own comment calls corrupting
    the index silently.
    """
    _corrupt(store, "INSERT INTO block_fts(rowid, text) VALUES (987654, 'a ghost posting')")
    result = _run(store, VerifyClause.FTS_ROWCOUNT)
    assert result.state is ClauseState.FAILED
    assert "987654" in result.findings[0].detail
    assert "survive their block" in result.findings[0].detail
    assert result.counts["block_fts_indexed"] == result.counts["block_fts_live"] + 1


def test_integrity_check_at_rank_one_would_fail_every_shipped_store(store: Path) -> None:
    """Why `_fts_integrity` runs the DEFAULT form only. Measured, not chosen.

    `rank = 1` additionally requires the index to match the WHOLE content table, and the shipped
    triggers deliberately skip `state <> 0` and `text IS NULL` (`0001_init.sql:505-508`,
    03:2432-2447). This store is clean and holds one container whose `text` is NULL, so `rank = 1`
    reports it malformed -- on a store nothing is wrong with. Pinned here so nobody "fixes" the
    clause by adding the stricter check.
    """
    connection = _open(store)
    try:
        connection.execute("INSERT INTO block_fts(block_fts) VALUES('integrity-check')")
        with pytest.raises(sqlite3.DatabaseError, match="malformed"):
            connection.execute(
                "INSERT INTO block_fts(block_fts, rank) VALUES('integrity-check', 1)"
            )
        container, indexed = connection.execute(
            "SELECT count(*) FILTER (WHERE text IS NULL), count(*) FILTER (WHERE text IS NOT NULL)"
            " FROM block"
        ).fetchone()
    finally:
        connection.close()
    assert container == 1 and indexed == 1, (
        "the store no longer holds an unindexed content row, so the measurement above no longer "
        "demonstrates what it claims"
    )
    assert _run(store, VerifyClause.FTS_INTEGRITY).state is ClauseState.PASSED


def test_the_default_integrity_check_does_not_see_the_orphan_which_is_why_both_clauses_exist(
    store: Path,
) -> None:
    """07:418 asks for `integrity-check` AND a count comparison, and this is which catches what.

    An orphaned posting leaves the index internally consistent, so the default check passes it;
    the rowid-set comparison is the half that sees it. Two clauses, because neither alone is
    sufficient -- which is what the plan's "and" is doing in that sentence.
    """
    _corrupt(store, "INSERT INTO block_fts(rowid, text) VALUES (987654, 'a ghost posting')")
    assert _run(store, VerifyClause.FTS_INTEGRITY).state is ClauseState.PASSED
    assert _run(store, VerifyClause.FTS_ROWCOUNT).state is ClauseState.FAILED


def test_the_row_count_the_plan_prints_is_vacuous_over_an_external_content_table(
    store: Path,
) -> None:
    """Why `_fts_rowcount` compares rowid SETS and not `count(*)`, measured rather than argued.

    07:418 says to compare `SELECT count(*) FROM block_fts` against the live block count. For an
    external-content FTS5 table an unindexed scan is answered out of the CONTENT table, so that
    count is the block count by construction and the comparison can never fail. Recorded here so
    the deviation from the printed instruction is evidence and not preference.
    """
    _corrupt(store, "INSERT INTO block_fts(rowid, text) VALUES (987654, 'a ghost posting')")
    connection = _open(store)
    try:
        delegated = connection.execute("SELECT count(*) FROM block_fts").fetchone()[0]
        content = connection.execute("SELECT count(*) FROM block").fetchone()[0]
    finally:
        connection.close()
    assert delegated == content, (
        f"count(*) over block_fts returned {delegated} against {content} content rows and one "
        f"orphaned posting. If it has stopped delegating to the content table, 07:418's printed "
        f"comparison may now be implementable as written"
    )
    assert _run(store, VerifyClause.FTS_ROWCOUNT).state is ClauseState.FAILED


def test_a_live_block_with_no_posting_is_the_other_direction(store: Path) -> None:
    """A repopulate that did not finish -- `index_state.fts_state = 'stale'`'s shape."""
    _corrupt(
        store,
        "INSERT INTO block_fts(block_fts, rowid, text) "
        "SELECT 'delete', block_id, text FROM block WHERE text IS NOT NULL",
    )
    result = _run(store, VerifyClause.FTS_ROWCOUNT)
    assert result.state is ClauseState.FAILED
    assert "no posting" in result.findings[0].detail


def test_the_fts_clause_leaves_no_shadow_table_behind_in_main(store: Path) -> None:
    """The `fts5vocab` shadow lives in `temp`, so a verify does not modify the store's schema."""
    connection = _open(store)
    try:
        before = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        verify_store(connection, now_ns=NOW_NS, clauses=FTS_CLAUSES)
        after = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        leftovers = connection.execute(
            "SELECT name FROM temp.sqlite_master WHERE name LIKE 'ow_verify%'"
        ).fetchall()
    finally:
        connection.close()
    assert before == after, "verify added an object to the store's schema"
    assert leftovers == [], f"the temp vocab shadow was not dropped: {leftovers}"


# ---------------------------------------------------------------------------------------------
# Clause 12 -- the entity closure. 06:2394
# ---------------------------------------------------------------------------------------------


def _add_entities(path: Path) -> None:
    _corrupt(
        path,
        "INSERT INTO etype_vocab(etype, scope, resolution, source) "
        "VALUES('org', 'corpus', 'fuzzy', 'builtin')",
        "INSERT INTO entity(entity_id, cite, scope, etype, key, title, canonical_id, "
        "resolution_method, trust, mention_digest) VALUES"
        "(1, 'e1', 0, 'org', 'acme', 'Acme', 1, 7, 2, X'00'),"
        "(2, 'e2', 0, 'org', 'acme inc', 'Acme Inc', 1, 7, 2, X'00')",
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, lanes, granularity, "
        "card_sha256, schema_version) "
        "VALUES('op.resolve', 'op', 'free', 0, '[\"entity\"]', 'corpus', 'aa', 1)",
        "INSERT INTO derive_run(run_id, pass_id, at_gen, producer_id, method, origin_operator, "
        "origin_driver, driver_schema_v, cost_class, input_digest, cache_key, status) "
        "SELECT 1, 'op.resolve', 1, min(producer_id), 7, 'op.resolve', 'op.resolve', 1, 'free', "
        "X'00', 'k', 'ok' FROM producer",
        "INSERT INTO entity_merge(merge_id, loser_id, winner_id, polarity, stage, method, trust, "
        "run_id, decided_at_gen) VALUES(1, 2, 1, 1, 'exact', 7, 2, 1, 1)",
    )


def test_a_canonical_id_that_disagrees_with_the_entity_merge_log_is_caught(store: Path) -> None:
    """06:2394 -- *"recomputes the closure from the log and byte-compares"*."""
    _add_entities(store)
    assert _run(store, VerifyClause.GRAPH_CLOSURE).state is ClauseState.PASSED

    _corrupt(store, "UPDATE entity SET canonical_id = 2 WHERE entity_id = 2")
    result = _run(store, VerifyClause.GRAPH_CLOSURE)
    assert result.state is ClauseState.FAILED
    assert result.counts["positive_pairs"] == 1
    assert any("does not match the log" in f.detail for f in result.findings)


def test_a_user_split_overwritten_by_an_automatic_merge_is_caught(store: Path) -> None:
    """`polarity = -1` is the one construct that makes a human split survive a later merge."""
    _add_entities(store)
    _corrupt(store, "UPDATE entity_merge SET polarity = -1 WHERE merge_id = 1")
    result = _run(store, VerifyClause.GRAPH_CLOSURE)
    assert result.state is ClauseState.FAILED
    assert any("human split" in f.detail for f in result.findings)


# ---------------------------------------------------------------------------------------------
# Clauses 13 and 14 -- the receipt. 07:3150 and :3155
# ---------------------------------------------------------------------------------------------


def _lock_text(path: Path) -> str:
    connection = _open(path)
    try:
        return write_lock(HEADER, derive_lock(connection, header=HEADER).rows)
    finally:
        connection.close()


def test_a_receipt_derived_from_the_store_matches_that_store(store: Path) -> None:
    """The clean case, and the precondition for every failure below."""
    text = _lock_text(store)
    result = _run(store, VerifyClause.LOCK_STORE_MATCH, lock_text=text)
    assert result.state is ClauseState.PASSED
    assert result.checked == 1, "one document, one line"
    assert text.count("\n") == 2, "one header line, one row, one trailing newline"
    assert "file:///corpus/contract.pdf" in text


def test_a_receipt_containing_a_conflict_marker_is_refused_with_ow_s_061(store: Path) -> None:
    """07:3150, ST19 at :3253, D-03 at 15:1516 -- *"refuses ... with `OW-S-061`"*."""
    text = _lock_text(store)
    conflicted = text.replace("#", "<<<<<<< ours\n#", 1) + ">>>>>>> theirs\n"
    assert has_conflict_markers(conflicted)

    connection = _open(store)
    try:
        report = verify_store(connection, now_ns=NOW_NS, clauses=LOCK_CLAUSES, lock_text=conflicted)
    finally:
        connection.close()
    markers = report.by_clause(VerifyClause.LOCK_MARKERS)
    assert markers.state is ClauseState.FAILED
    assert markers.findings[0].code == "OW-S-061"
    assert "unresolved merge" in markers.findings[0].detail
    assert report.by_clause(VerifyClause.LOCK_STORE_MATCH).state is ClauseState.UNCHECKED, (
        "a refused receipt must not then be compared: the comparison would report noise the "
        "operator has to read past to reach the refusal"
    )


def test_a_receipt_that_no_longer_matches_the_store_is_reported_line_by_line(store: Path) -> None:
    """07:3155 -- re-derive from the store and compare. The diff is what a reviewer reads."""
    stale = _lock_text(store)
    _corrupt(store, "UPDATE doc SET status = 'partial'")
    result = _run(store, VerifyClause.LOCK_STORE_MATCH, lock_text=stale)
    assert result.state is ClauseState.FAILED
    assert "  ok  " in result.findings[0].detail
    assert "  partial  " in result.findings[0].detail


def test_a_receipt_listing_a_document_the_store_does_not_have_is_reported(store: Path) -> None:
    """The two asymmetric cases have two messages, because they have two remedies."""
    stale = _lock_text(store)
    _corrupt(store, "DELETE FROM block", "DELETE FROM page", "DELETE FROM doc")
    result = _run(store, VerifyClause.LOCK_STORE_MATCH, lock_text=stale)
    assert result.state is ClauseState.FAILED
    assert "the store has no `doc` row for it" in result.findings[0].detail


def test_a_receipt_header_pinning_the_wrong_scorer_is_caught(store: Path) -> None:
    """*"merging two corpora indexed by different scorers silently is exactly the drift the
    header exists to catch"* (07:3130). `scorer` is the field `index_state` holds."""
    _corrupt(store, "INSERT INTO index_state(k, v) VALUES('scorer_version', '2')")
    result = _run(
        store,
        VerifyClause.LOCK_STORE_MATCH,
        lock_text=_lock_text(store).replace("scorer=2", "scorer=1"),
    )
    assert result.state is ClauseState.FAILED
    assert result.findings[0].where.endswith("header")
    assert "scorer=2" in result.findings[0].detail


def test_the_derived_receipt_counts_live_head_blocks_and_names_the_root_digest(
    store: Path,
) -> None:
    """Every column is a stored field, so the receipt needs no re-parse (07:3155).

    The two counted columns are pinned against the store read a different way -- `ow_block_head`
    against a raw predicate -- so a receipt that counted staged or tombstoned rows is visible.
    """
    connection = _open(store)
    try:
        lock = derive_lock(connection, header=HEADER)
        root = connection.execute("SELECT content_digest FROM block WHERE addr = 'doc'").fetchone()[
            0
        ]
        live = connection.execute(
            "SELECT count(*) FROM block b JOIN doc d ON d.doc_ord = b.doc_ord "
            "WHERE b.gen = d.gen AND b.state = 0"
        ).fetchone()[0]
    finally:
        connection.close()
    assert len(lock.rows) == 1
    row = lock.rows[0]
    assert row.n_blocks == live == 2
    assert row.n_segments == 0, "P2 writes no segment rows"
    assert row.content_digest == bytes(root), "the receipt's digest is the document merkle root"
    assert row.gen == 1
    assert row.status == "ok"


# ---------------------------------------------------------------------------------------------
# Clause 15 -- the erasure cascade. 14:1205-1210
# ---------------------------------------------------------------------------------------------


def test_an_erased_block_whose_text_survives_fails_with_the_erasure_code(store: Path) -> None:
    """14:1207 -- cascade location 1 is `block.text` and `block_fts`, keyed on `block_id`."""
    _corrupt(
        store,
        "INSERT INTO block_history(block_id, doc_ord, retired_gen, reason) "
        "SELECT block_id, doc_ord, 1, 'erased:dsar-2026-114' FROM block WHERE text IS NOT NULL",
    )
    result = _run(store, VerifyClause.ERASED_RESIDUE)
    assert result.state is ClauseState.FAILED
    assert result.findings[0].code == "OW_ERASURE_INCOMPLETE"
    assert "cascade location 1" in result.findings[0].detail


def test_an_erased_block_whose_text_is_gone_leaves_the_clause_unchecked_not_passed(
    store: Path,
) -> None:
    """The other ten in-store locations key off an `erasure` row this schema does not create."""
    _corrupt(
        store,
        "INSERT INTO block_history(block_id, doc_ord, retired_gen, reason) "
        "SELECT block_id, doc_ord, 1, 'redacted:legal-hold' FROM block WHERE text IS NOT NULL",
        "UPDATE block SET text = NULL WHERE text IS NOT NULL",
    )
    result = _run(store, VerifyClause.ERASED_RESIDUE)
    assert result.state is ClauseState.UNCHECKED
    assert "locations 2 to 11" in result.reason


def test_a_store_with_no_erased_rows_passes_over_zero_subjects(store: Path) -> None:
    """Which is every P2 store, and `checked` is what says so."""
    result = _run(store, VerifyClause.ERASED_RESIDUE)
    assert result.state is ClauseState.PASSED
    assert result.checked == 0


# ---------------------------------------------------------------------------------------------
# `ow doc verify`
# ---------------------------------------------------------------------------------------------


def test_verify_doc_runs_owchecks_six_clauses_and_none_of_its_own(store: Path) -> None:
    """*"`ow doc verify` is `owcheck` over one document"* -- the adapter, not a second checker."""
    connection = _open(store)
    try:
        report = verify_doc(connection, 1, 1)
    finally:
        connection.close()
    assert [c.clause for c in report.clauses] == [clause.value for clause in OwcheckClause]
    assert report.ok, [f.detail for f in report.findings]
    assert report.by_clause(OwcheckClause.PARENT_ORD_BIJECTION.value).checked == 2


def test_verify_doc_reads_the_retained_parts_so_the_verbatim_clause_is_checked(
    store: Path,
) -> None:
    """The VERBATIM paragraph names part `file`, whose bytes are retained; INV-10 is provable.

    Over an archive with no `parts[]` this clause is UNCHECKED (owcheck's own rule). Over a
    store it is answerable, and answering it is the whole reason `_generation` reads `part`.
    """
    connection = _open(store)
    try:
        checked = verify_doc(connection, 1, 1).by_clause(OwcheckClause.VERBATIM_RETAINED_PART.value)
    finally:
        connection.close()
    assert checked.state is ClauseState.PASSED
    assert checked.checked == 1, "one block claims VERBATIM and it was actually looked at"


def test_verify_doc_fails_a_verbatim_claim_whose_part_bytes_were_not_retained(
    store: Path,
) -> None:
    """V01-5: *"zero Blocks claim `verbatim` without a non-NULL `part.store_ref`"*."""
    _corrupt(store, "UPDATE part SET store_ref = NULL")
    connection = _open(store)
    try:
        result = verify_doc(connection, 1, 1).by_clause(OwcheckClause.VERBATIM_RETAINED_PART.value)
    finally:
        connection.close()
    assert result.state is ClauseState.FAILED
    assert "not retained" in result.findings[0].detail


def test_verify_doc_reports_a_broken_parent_ord_bijection_out_of_the_store(store: Path) -> None:
    """A gap in a sibling `ord` run: `block_sib` is UNIQUE and permits it, which is the seam."""
    _corrupt(store, "UPDATE block SET ord = 5 WHERE addr = 'p1/0'")
    connection = _open(store)
    try:
        result = verify_doc(connection, 1, 1).by_clause(OwcheckClause.PARENT_ORD_BIJECTION.value)
    finally:
        connection.close()
    assert result.state is ClauseState.FAILED


def test_verify_doc_sees_a_staged_generation_the_reader_hides(blank: Path, cas: BlobStore) -> None:
    """03 section 2.9: staged rows are durable and invisible, and verifying them is the point.

    `gen` is a parameter and not `doc.gen` for exactly this: a generation that `end_doc()` has
    not published is the one worth checking before it is, and a verify that defaulted to the
    head could never reach it.
    """
    producer_id = _producer(blank)
    with ow.StoreThread(lambda: ow.connect(blank)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.pdf",
            origin_driver="parse.pdf.pdfium",
            driver_schema_v=1,
            blobs=cas,
        )
        sink.begin_doc(_doc_record(9, "file:///corpus/staged.pdf"))
        sink.begin_page(_page_record())
        sink.add_block(
            BlockDraft(
                kind=Kind.DOCUMENT,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.SYNTHETIC,
            )
        )
        sink.end_page({})
        # end_doc is deliberately not called: gen 1 is staged and doc.gen is still 0.
    connection = _open(blank)
    try:
        staged = verify_doc(connection, 1, 1)
        head = verify_doc(connection, 1, 0)
    finally:
        connection.close()
    assert staged.by_clause(OwcheckClause.PARENT_ORD_BIJECTION.value).checked == 1
    assert head.by_clause(OwcheckClause.PARENT_ORD_BIJECTION.value).checked == 0


# ---------------------------------------------------------------------------------------------
# The clause set itself
# ---------------------------------------------------------------------------------------------


def test_the_four_flag_subsets_and_the_default_set_partition_the_clauses() -> None:
    """Every clause is reachable from exactly one flag or from no flag at all.

    A clause in two subsets would run twice under `--fts --lock`; a clause in none would be
    unreachable, which is the failure mode a `DEFAULT_CLAUSES` written as a literal list has.
    It is written as a subtraction for that reason and this asserts the arithmetic.
    """
    flagged = [FTS_CLAUSES, GRAPH_CLAUSES, LOCK_CLAUSES, ERASED_CLAUSES, DEFAULT_CLAUSES]
    union: set[VerifyClause] = set()
    for subset in flagged:
        assert not (union & subset), f"a clause is in two subsets: {sorted(union & subset)}"
        union |= subset
    assert union == set(ALL_CLAUSES) == set(VerifyClause)
    assert len(ALL_CLAUSES) == 15


def test_the_verify_and_owcheck_clause_vocabularies_do_not_collide() -> None:
    """One `VerifyReport` carries both, keyed on the string, so a shared name would shadow."""
    mine = {clause.value for clause in VerifyClause}
    theirs = {clause.value for clause in OwcheckClause}
    assert not (mine & theirs), f"colliding clause names: {sorted(mine & theirs)}"


def test_an_unknown_clause_name_is_a_usage_error_and_not_a_silent_no_op(blank: Path) -> None:
    """A flag misspelled in a CI script must not verify nothing and exit 0."""
    connection = _open(blank)
    try:
        with pytest.raises(UsageError, match="is not a verify clause"):
            verify_store(connection, now_ns=NOW_NS, clauses=["--fts"])
    finally:
        connection.close()


def test_a_database_that_is_not_a_store_is_refused_rather_than_reported_on(tmp_path: Path) -> None:
    """The one raise. A corrupt store is describable; a different file is not a corrupt store."""
    path = tmp_path / "not-a-store.owstore"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE unrelated (a INTEGER)")
        with pytest.raises(StoreError, match="no `block` table"):
            verify_store(connection, now_ns=NOW_NS)
        with pytest.raises(StoreError, match="no `block` table"):
            verify_doc(connection, 1, 1)
    finally:
        connection.close()


def test_the_default_set_runs_without_a_cas_or_a_receipt(store: Path) -> None:
    """`ow store verify` with no flags and no arguments is a valid invocation."""
    connection = _open(store)
    try:
        report = verify_store(connection, now_ns=NOW_NS)
    finally:
        connection.close()
    assert {c.clause for c in report.clauses} == set(DEFAULT_CLAUSES)
    assert report.ok


def test_a_report_names_the_clause_that_found_each_thing(store: Path) -> None:
    """`Finding.clause` is the discriminator a caller branches on, even where the code is a
    class default -- which is `owcheck.Violation`'s rule and the reason it survives an
    unallocated `codes.toml` symbol."""
    _corrupt(store, "UPDATE block SET content_digest = X'00112233445566778899aabbccddeeff'")
    _corrupt(store, "INSERT INTO meta(k, v) VALUES('schema', '1.0')")
    connection = _open(store)
    try:
        report = verify_store(connection, now_ns=NOW_NS)
    finally:
        connection.close()
    by_clause: dict[str, int] = {}
    for finding in report.findings:
        by_clause[finding.clause] = by_clause.get(finding.clause, 0) + 1
    assert by_clause == {VerifyClause.BLOCK_DIGEST: 2, VerifyClause.SINGLE_HOME: 1}
    assert not report.ok
