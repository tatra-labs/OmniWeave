"""`SqliteArtifactStore` against a real `.owstore`: the seal, the lookup, the aggregate, the loop.

09-generation.md section 2 (the seal), section 5.4 (the lookup-before-build and the three race
rules), section 7.3 (the restriction aggregate) and section 10 (the citation ledger and its
query). Every behaviour is a property of statements running against rows, so every test runs them
against a store with all five migrations applied and a seeded document, block set and asset set.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3  # noqa: TID251 -- the assertions read the rows the writer wrote.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.errors import NotFoundError, TargetError, explain
from omniweave_core.model.enums import Quote, enum_val_rows
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.store import artifact as artifact_module
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.artifact import (
    ARTIFACT_COLUMNS,
    LOOKUP_SQL,
    QUOTING_SQL,
    ArtifactDraft,
    AssetJoin,
    CiteRow,
    ElRow,
    PureKey,
    Restricted,
    SqliteArtifactStore,
    UnitRow,
    artifact_rows,
    ensure_producer,
    latest_generation,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW_NS = 1_700_000_000_000_000_000
SEALED_NS = 1_757_400_000_000_000_000
ORD = {(domain, name): ordinal for domain, ordinal, name in enum_val_rows()}
SHA_A = "a" * 64
SHA_B = "b" * 64
BARRED = 1 << 3
"""A bit the tests' policy bars. Asset 202 and block 103 carry it."""


def d(n: int) -> str:
    return f"sha256:{n:064x}"


class FakeClock:
    def monotonic_ns(self) -> int:  # pragma: no cover -- the seal reads wall time only.
        return 0

    def wall_ns(self) -> int:
        return SEALED_NS


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES (1, 'compile.text.owtext', 1, 'f', x'00')"
    )
    connection.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
        " format_evidence, source_bytes, status, model_version, declared, achieved)"
        " VALUES (7, ?, ?, 'file:///c/contract.pdf', 'application/pdf', 'pdf', '{}', 10, 'ok',"
        " '1.1', '{}', '{}')",
        (b"\x07" * 16, b"\x00" * 32),
    )
    for page in (14, 15):
        connection.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id)"
            " VALUES (7, 1, ?, ?, ?, 1)",
            (page, ORD["page_kind", "page"], ORD["method", "native_xml"]),
        )
    blocks = [
        (101, 14, "d7#1", Quote.VERBATIM, 0, "Revenue rose 12% in Q3."),
        (102, 14, "d7#2", Quote.NORMALIZED, 0, "Margins held."),
        (103, 14, "d7#3", Quote.VERBATIM, BARRED | 1, "Restricted figure."),
        (104, 15, "d7#4", Quote.VERBATIM, 0, "Another page."),
    ]
    for block_id, page, cite, quote, bits, text in blocks:
        connection.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text,"
            " content_digest, os_kind, producer_id, method, trust, quote, origin_operator,"
            " origin_driver, driver_schema_v, restriction_bits)"
            " VALUES (?, 7, 1, ?, ?, ?, ?, ?, ?, ?, x'00', ?, 1, ?, 2, ?, 'parse.pdf',"
            " 'parse.pdf.text', 1, ?)",
            (
                block_id,
                page,
                f"p{page}/{block_id}",
                cite,
                block_id,
                ORD["kind", "paragraph"],
                ORD["layer", "body"],
                text,
                ORD["origin_span_kind", "none"],
                ORD["method", "native_xml"],
                int(quote),
                bits,
            ),
        )
    for asset_id, sha, bits in ((201, SHA_A, 0), (202, SHA_B, BARRED | 2)):
        connection.execute(
            "INSERT INTO asset(asset_id, doc_ord, media_type, sha256, byte_len, store_ref,"
            " restriction_bits) VALUES (?, 7, 'image/png', ?, 5, ?, ?)",
            (asset_id, bytes.fromhex(sha), f"cas://{sha[:2]}/{sha[2:4]}/{sha}", bits),
        )


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 5
        connection.execute("BEGIN IMMEDIATE")
        _seed(connection)
        connection.execute("COMMIT")
    finally:
        connection.close()
    return path


@pytest.fixture
def thread(owstore: Path) -> Iterator[ow.StoreThread]:
    started = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield started
    finally:
        started.close()


@pytest.fixture
def store(thread: ow.StoreThread) -> SqliteArtifactStore:
    return SqliteArtifactStore(thread, clock=FakeClock())


def rows(owstore: Path, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(owstore)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def key(**over: Any) -> PureKey:
    fields: dict[str, Any] = {
        "target": "pptx",
        "slug": "q3-board",
        "delivery": "release",
        "il_digest": d(1),
        "constructs_digest": d(2),
        "ledger_digest": d(3),
        "card_sha256": d(4),
        "brief_digest": d(5),
        "toolchain_digest": None,
    }
    fields.update(over)
    return PureKey(**fields)


def unit(n: int, **over: Any) -> UnitRow:
    fields: dict[str, Any] = {
        "unit": f"u{n:02d}",
        "ord": n,
        "outcome": UnitOutcome.NATIVE,
        "il_path": f"il/u{n:02d}.svg",
        "il_sha256": d(100 + n),
        "nsig": f"{n:08x}",
    }
    fields.update(over)
    return UnitRow(**fields)


def draft(**over: Any) -> ArtifactDraft:
    fields: dict[str, Any] = {
        "key": key(),
        "artifact_gen": 1,
        "origin": "authored",
        "compile_driver": "compile.pptx.native",
        "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "path": "q3-board@1/q3-board.pptx",
        "sha256": d(10),
        "byte_len": 4096,
        "part_digest": d(11),
        "il_store_ref": "cas://00/00/" + "0" * 64,
        "determinism": ("part", "byte"),
        "gate_status": GateStatus.PASSED,
        "report_sha256": d(12),
        "receipt_sha256": d(13),
        "producer_id": 1,
        "units": (unit(1), unit(2)),
        "assets": (AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u01",)),),
        "cites": (
            CiteRow("u01", "u01/e2", "d7#1", 101, 1, "quote", 0, 17, verbatim=True),
            CiteRow("u02", "u02/e1", "d7#2", 102, 1, "paraphrase"),
        ),
    }
    fields.update(over)
    return ArtifactDraft(**fields)


# ---------------------------------------------------------------------------
# The seal
# ---------------------------------------------------------------------------


def test_the_column_tuple_is_the_table(owstore: Path) -> None:
    assert tuple(r[1] for r in rows(owstore, "PRAGMA table_info(artifact)")) == ARTIFACT_COLUMNS


def test_a_seal_writes_the_artefact_and_its_rows_in_one_transaction(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    sealed = store.seal(draft())
    assert not sealed.hit
    row = sealed.row
    assert (row.slug, row.artifact_gen, row.sealed_at_ns) == ("q3-board", 1, SEALED_NS)
    assert row.key == key()
    assert (row.sha256, row.part_digest, row.receipt_sha256) == (d(10), d(11), d(13))
    assert row.determinism == ("byte", "part")
    assert row.gate_status is GateStatus.PASSED
    assert row.read_back_doc_ord is None
    assert store.units(row.artifact_id) == (unit(1), unit(2))
    assert rows(owstore, "SELECT asset_id, slot, role, units FROM artifact_asset") == [
        (201, "asset-slot:" + SHA_A, "image", '["u01"]')
    ]
    assert rows(
        owstore, "SELECT unit, el, cite, block_id, doc_gen, kind, verbatim FROM artifact_cite"
    ) == [
        ("u01", "u01/e2", "d7#1", 101, 1, "quote", 1),
        ("u02", "u02/e1", "d7#2", 102, 1, "paraphrase", 0),
    ]
    assert store.get("q3-board", 1) == row


def test_a_seal_that_fails_part_way_leaves_no_row(
    store: SqliteArtifactStore, thread: ow.StoreThread, owstore: Path
) -> None:
    """Ruling 1: a child row that cannot be written takes the artefact row with it."""
    thread.run(
        ow.Unit(
            name="test.trap",
            run=lambda c: c.execute(
                "CREATE TEMP TRIGGER trap BEFORE INSERT ON artifact_cite"
                " BEGIN SELECT RAISE(ABORT, 'trapped'); END"
            ),
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="trapped"):
        store.seal(draft())
    assert rows(owstore, "SELECT count(*) FROM artifact") == [(0,)]
    assert rows(owstore, "SELECT count(*) FROM artifact_unit") == [(0,)]


def test_restriction_bits_carry_every_source(store: SqliteArtifactStore) -> None:
    """Ruling 8: the card's stamp, OR every asset's and every cited block's bits."""
    sealed = store.seal(
        draft(
            restriction_bits=1 << 9,
            assets=(AssetJoin(202, "asset-slot:" + SHA_B, "image", ("u02",)),),
            cites=(CiteRow("u01", "u01/e1", "d7#3", 103, 1, "derived"),),
        )
    )
    assert sealed.row.restriction_bits == (1 << 9) | BARRED | 2 | 1


# ---------------------------------------------------------------------------
# Section 5.4: the lookup, and two compiles racing on one slug
# ---------------------------------------------------------------------------


def test_the_lookup_finds_the_identical_compile_and_uses_the_index(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    assert store.lookup(key()) is None
    sealed = store.seal(draft())
    assert store.lookup(key()) == sealed.row
    plan = " ".join(
        str(r[-1]) for r in rows(owstore, f"EXPLAIN QUERY PLAN {LOOKUP_SQL}", key().params())
    )
    assert "artifact_pure" in plan, plan


@pytest.mark.parametrize(
    "change",
    [
        {"target": "docx"},
        {"slug": "q3-board-copy"},
        {"delivery": "draft"},
        {"il_digest": d(91)},
        {"constructs_digest": d(92)},
        {"ledger_digest": d(93)},
        {"card_sha256": d(94)},
        {"brief_digest": d(95)},
        {"brief_digest": None},
        {"toolchain_digest": d(96)},
    ],
)
def test_any_one_key_column_is_a_miss(store: SqliteArtifactStore, change: dict[str, Any]) -> None:
    store.seal(draft())
    assert store.lookup(key(**change)) is None


def test_an_identical_compile_at_the_same_generation_is_the_winners_row(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    """Rule 3 through ruling 2's guard: the winner took the planned generation."""
    first = store.seal(draft())
    second = store.seal(draft())
    assert second.hit
    assert second.row == first.row
    assert rows(owstore, "SELECT count(*) FROM artifact_unit") == [(2,)]


def test_an_identical_compile_at_the_next_generation_is_the_winners_row(
    store: SqliteArtifactStore,
) -> None:
    """Rule 3 through `artifact_pure` itself: a gen 2 plan of gen 1's inputs."""
    first = store.seal(draft())
    second = store.seal(draft(artifact_gen=2, path="q3-board@2/q3-board.pptx"))
    assert second.hit
    assert second.row == first.row


def test_a_different_compile_planned_at_a_taken_generation_is_contended(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    """Ruling 2: the receipt names gen 1 and gen 1 is taken, so nothing is written."""
    store.seal(draft())
    with pytest.raises(TargetError, match=r"planned as generation 1, and generation 1") as caught:
        store.seal(draft(key=key(il_digest=d(77))))
    assert caught.value.code() == "OW_TARGET_GEN_CONTENDED"
    assert "--slug q3-board" in caught.value.fix
    assert rows(owstore, "SELECT count(*) FROM artifact") == [(1,)]


def test_a_plan_past_the_next_generation_is_contended(store: SqliteArtifactStore) -> None:
    with pytest.raises(TargetError, match=r"planned as generation 3, .* the next is 1"):
        store.seal(draft(artifact_gen=3))


def test_a_new_brief_is_a_new_generation(store: SqliteArtifactStore) -> None:
    """Ruling 5: the sixth digest is in the key, so a brief change is never the old bytes."""
    store.seal(draft())
    second = store.seal(draft(artifact_gen=2, key=key(brief_digest=d(55))))
    assert not second.hit
    assert second.row.artifact_gen == 2


def test_latest_is_the_newest_sealed_generation_of_a_slug(store: SqliteArtifactStore) -> None:
    """D764: `ow out scaffold` proposes one past it, and a slug never sealed has 0."""
    assert store.latest("q3-board") == 0
    store.seal(draft())
    assert store.latest("q3-board") == 1
    store.seal(draft(artifact_gen=2, key=key(brief_digest=d(55))))
    assert store.latest("q3-board") == 2
    assert store.latest("q4-board") == 0


def test_latest_generation_reads_a_read_only_store_and_one_from_before_0005(
    store: SqliteArtifactStore, owstore: Path, tmp_path: Path
) -> None:
    """D765: `ow out scaffold` opens the store read-only, and an unmigrated one sealed nothing."""
    old = ow.connect(tmp_path / "old.owstore")
    try:
        assert latest_generation(old, "q3-board") == 0
    finally:
        old.close()
    store.seal(draft())
    readonly = ow.connect_readonly(owstore)
    try:
        assert latest_generation(readonly, "q3-board") == 1
    finally:
        readonly.close()


def test_artifact_rows_are_every_seal_by_slug_then_generation(
    store: SqliteArtifactStore, owstore: Path, tmp_path: Path
) -> None:
    """D769: `ow out list` reads them read-only; a store from before 0005 has none."""
    old = ow.connect(tmp_path / "old.owstore")
    try:
        assert artifact_rows(old) == ()
    finally:
        old.close()
    first = store.seal(draft()).row
    second = store.seal(draft(artifact_gen=2, key=key(brief_digest=d(55)))).row
    #  Sealed last, listed first: the order is slug then generation, never insertion.
    memo = store.seal(draft(key=key(slug="a-memo"), path="a-memo@1/a-memo.pptx")).row
    readonly = ow.connect_readonly(owstore)
    try:
        assert artifact_rows(readonly) == (memo, first, second)
        assert artifact_rows(readonly, "q3-board") == (first, second)
        assert artifact_rows(readonly, "q4-board") == ()
    finally:
        readonly.close()


def test_ensure_producer_is_one_row_per_identity(owstore: Path) -> None:
    """D770: the compile path's producer, inserted once and found again."""
    from omniweave_core.model.records import Producer  # noqa: PLC0415

    owtext = Producer(
        operator="compile.text.owtext", op_version=1, code_fingerprint="", options_digest=b"\x01"
    )
    connection = ow.connect(owstore)
    try:
        sql = "SELECT count(*) FROM producer WHERE operator = 'compile.text.owtext'"
        (seeded,) = connection.execute(sql).fetchone()
        first = ensure_producer(connection, owtext)
        assert ensure_producer(connection, owtext) == first
        other = ensure_producer(connection, dataclasses.replace(owtext, op_version=2))
        assert other != first
        (count,) = connection.execute(sql).fetchone()
        #  The seed already holds one with another identity: two new rows, not one per call.
        assert count == seeded + 2
    finally:
        connection.close()


def test_a_draft_and_a_release_of_one_input_are_two_rows(store: SqliteArtifactStore) -> None:
    store.seal(draft())
    second = store.seal(
        draft(artifact_gen=2, key=key(delivery="draft"), gate_status=GateStatus.MANUAL_REQUIRED)
    )
    assert not second.hit
    assert second.row.delivery == "draft"


# ---------------------------------------------------------------------------
# Rulings 9-11: what the seal checks against the store
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block_id", [None, 999])
def test_a_compiles_citation_names_a_block(
    store: SqliteArtifactStore, block_id: int | None
) -> None:
    cite = CiteRow("u01", "u01/e9", "d7#9", block_id, 1, "paraphrase")
    with pytest.raises(TargetError, match="names no block") as caught:
        store.seal(draft(cites=(cite,)))
    assert caught.value.code() == "OW_TARGET_CITE_UNRESOLVED"


def test_a_read_back_artefact_may_hold_an_unresolved_citation(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    cite = CiteRow("u01", "u01/e9", "x3#9", None, 1, "paraphrase")
    store.seal(draft(origin="read_back", cites=(cite,)))
    assert rows(owstore, "SELECT block_id FROM artifact_cite") == [(None,)]
    with pytest.raises(TargetError, match="names no block"):
        store.seal(
            draft(
                origin="read_back",
                artifact_gen=2,
                key=key(il_digest=d(78)),
                cites=(CiteRow("u01", "u01/e9", "x3#9", 999, 1, "paraphrase"),),
            )
        )


@pytest.mark.parametrize(
    ("cite", "said"),
    [
        (CiteRow("u01", "u01/e2", "d7#2", 102, 1, "quote", 0, 5, verbatim=True), "normalized"),
        (CiteRow("u01", "u01/e2", "d7#1", 101, 1, "quote", verbatim=True), "names no span"),
    ],
)
def test_verbatim_is_refused_where_the_store_disproves_it(
    store: SqliteArtifactStore, cite: CiteRow, said: str
) -> None:
    with pytest.raises(TargetError, match=said) as caught:
        store.seal(draft(cites=(cite,)))
    assert caught.value.code() == "OW_TARGET_CITE_NOT_VERBATIM"
    assert caught.value.fix == f"ow open {cite.cite} --raw"


@pytest.mark.parametrize(
    "join",
    [
        AssetJoin(299, "asset-slot:" + SHA_A, "image", ("u01",)),
        AssetJoin(201, "asset-slot:" + SHA_B, "image", ("u01",)),
    ],
)
def test_a_ledger_join_names_a_frozen_asset_under_its_own_slot(
    store: SqliteArtifactStore, join: AssetJoin
) -> None:
    with pytest.raises(TargetError, match="is not frozen under") as caught:
        store.seal(draft(assets=(join,)))
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"


# ---------------------------------------------------------------------------
# Section 7.3: the restriction aggregate
# ---------------------------------------------------------------------------


def test_the_aggregate_names_the_barred_assets_and_cites(store: SqliteArtifactStore) -> None:
    found = store.restricted(
        asset_ids=[201, 202, 202, 299], block_ids=[101, 103, 103], barred_mask=BARRED
    )
    assert found == (
        Restricted("asset", 202, BARRED | 2, None),
        Restricted("cite", 103, BARRED | 1, "d7#3"),
    )
    assert store.restricted(asset_ids=[202], block_ids=[103], barred_mask=1 << 20) == ()
    assert store.restricted(asset_ids=[], block_ids=[], barred_mask=BARRED) == ()


def test_the_aggregate_reads_the_store_at_each_evaluation(
    store: SqliteArtifactStore, thread: ow.StoreThread
) -> None:
    """Section 7.3: the second evaluation is the one that governs bytes."""
    assert store.restricted(asset_ids=[201], block_ids=[101], barred_mask=BARRED) == ()
    thread.run(
        ow.Unit(
            name="test.restrict",
            run=lambda c: c.execute(
                "UPDATE asset SET restriction_bits = ? WHERE asset_id = 201", (BARRED,)
            ),
        )
    )
    assert store.restricted(asset_ids=[201], block_ids=[101], barred_mask=BARRED) == (
        Restricted("asset", 201, BARRED, None),
    )


@pytest.mark.parametrize("mask", [-1, 1 << 32])
def test_the_mask_is_thirty_two_bits(store: SqliteArtifactStore, mask: int) -> None:
    with pytest.raises(ValueError, match="32 bits"):
        store.restricted(asset_ids=[], block_ids=[], barred_mask=mask)


# ---------------------------------------------------------------------------
# Ruling 6: the loop, closed once
# ---------------------------------------------------------------------------


def test_the_loop_closes_once(store: SqliteArtifactStore, owstore: Path) -> None:
    sealed = store.seal(draft())
    assert store.els(sealed.row.artifact_id) == ()
    closed = store.close_loop(sealed.row.artifact_id, 7, [ElRow("u01", "u01/e2", 101)])
    assert closed.read_back_doc_ord == 7
    assert store.els(sealed.row.artifact_id) == (ElRow("u01", "u01/e2", 101),)
    other = store.seal(draft(key=key(il_digest=d(9)), artifact_gen=2))
    assert store.els(other.row.artifact_id) == (), "the map is one artefact's"
    assert dataclasses.replace(closed, read_back_doc_ord=None) == sealed.row
    assert rows(owstore, "SELECT unit, el, block_id FROM artifact_el") == [("u01", "u01/e2", 101)]
    with pytest.raises(TargetError, match="already read back") as caught:
        store.close_loop(sealed.row.artifact_id, 7, [])
    assert caught.value.code() == "OW_TARGET_ARTIFACT_SEALED"


def test_the_loop_needs_a_real_artefact_and_its_own_units(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    with pytest.raises(NotFoundError, match="no artifact 99"):
        store.close_loop(99, 7, [])
    sealed = store.seal(draft())
    with pytest.raises(ValueError, match=r"has no unit \['u09'\]"):
        store.close_loop(sealed.row.artifact_id, 7, [ElRow("u09", "u09/e1", 101)])
    assert rows(owstore, "SELECT read_back_doc_ord FROM artifact") == [(None,)]


# ---------------------------------------------------------------------------
# Section 10: which decks quote this page?
# ---------------------------------------------------------------------------


def test_which_released_decks_quote_page_14(store: SqliteArtifactStore, owstore: Path) -> None:
    store.seal(draft())
    store.seal(
        draft(
            key=key(slug="ops-review"),
            path="ops-review@1/ops-review.pptx",
            cites=(CiteRow("u02", "u02/e7", "d7#4", 104, 1, "quote"),),
        )
    )
    store.seal(
        draft(
            artifact_gen=2,
            key=key(delivery="draft", il_digest=d(70)),
            gate_status=GateStatus.MANUAL_REQUIRED,
        )
    )
    found = store.quoting(7, 14)
    assert [(q.slug, q.artifact_gen, q.unit, q.el, q.kind, q.verbatim) for q in found] == [
        ("q3-board", 1, "u01", "u01/e2", "quote", True),
        ("q3-board", 1, "u02", "u02/e1", "paraphrase", False),
    ]
    assert [q.slug for q in store.quoting(7, 15)] == ["ops-review"]
    plan = " ".join(
        str(r[-1])
        for r in rows(owstore, f"EXPLAIN QUERY PLAN {QUOTING_SQL}", {"doc": 7, "page": 14})
    )
    assert "artifact_cite_block" in plan, plan


def test_get_names_what_it_did_not_find(store: SqliteArtifactStore) -> None:
    with pytest.raises(NotFoundError, match="no artefact q3-board@4") as caught:
        store.get("q3-board", 4)
    assert caught.value.fix == "ow out list --slug q3-board"


# ---------------------------------------------------------------------------
# The draft refuses what the table would, and what the table cannot see
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "said"),
    [
        ({"gate_status": GateStatus.UNVERIFIED}, "a release needs a passed gate"),
        ({"origin": "imported"}, "origin 'imported'"),
        ({"artifact_gen": 0}, "below 1"),
        ({"parent_artifact_gen": 1}, "not an earlier generation"),
        ({"determinism": ("byte",)}, "must include part"),
        ({"sha256": "a" * 64}, "sha256 'a"),
        ({"il_store_ref": "file:///il"}, "not a cas://"),
        ({"restriction_bits": 1 << 32}, "not 32 bits"),
        ({"units": ()}, "at least one unit"),
        ({"units": (unit(1), unit(1))}, "unit ids repeat"),
        ({"units": (unit(2, ord=2),)}, r"not 1\.\.1"),
        (
            {"assets": (AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u07",)),)},
            "outside the roster",
        ),
        (
            {
                "assets": (
                    AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u01",)),
                    AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u02",)),
                )
            },
            "join repeats",
        ),
        (
            {
                "cites": (
                    CiteRow("u01", "u01/e2", "d7#2", 102, 1, "quote"),
                    CiteRow("u01", "u01/e2", "d7#2", 102, 1, "paraphrase"),
                )
            },
            "citation repeats",
        ),
        ({"cites": (CiteRow("u05", "u05/e2", "d7#2", 102, 1, "quote"),)}, "names unit 'u05'"),
    ],
)
def test_a_draft_refuses_a_malformed_artefact(over: dict[str, Any], said: str) -> None:
    with pytest.raises(ValueError, match=said):
        draft(**over)


@pytest.mark.parametrize(
    ("build", "said"),
    [
        (lambda: unit(1, unit="slide1"), "does not match"),
        (lambda: unit(1, ord=0), "below 1"),
        (lambda: unit(1, il_sha256="sha256:XY"), "il_sha256"),
        (lambda: unit(1, nsig=""), "nsig"),
        (lambda: unit(1, outcome=UnitOutcome.BAKED), "needs a reason"),
        (lambda: AssetJoin(1, "asset-slot:" + SHA_A, "logo", ("u01",)), "role 'logo'"),
        (lambda: AssetJoin(1, "sha256:" + SHA_A, "image", ("u01",)), "is not asset-slot"),
        (lambda: AssetJoin(1, "asset-slot:" + SHA_A, "image", ()), "used by no unit"),
        (lambda: CiteRow("u01", "e", "d7#1", 1, 1, "rumour"), "kind 'rumour'"),  # type: ignore[arg-type]
        (lambda: CiteRow("u01", "e", "d7#1", 1, 1, "quote", 3), "both ends"),
        (lambda: CiteRow("u01", "e", "d7#1", 1, 1, "quote", 5, 5), "empty or negative"),
        (lambda: key(delivery="final"), "release or draft"),
        (lambda: key(slug=""), "names its target and its slug"),
        (lambda: key(toolchain_digest="sha256:00"), "toolchain_digest"),
    ],
)
def test_the_rows_refuse_what_the_table_would(build: Any, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        build()


def test_every_refusal_is_a_registered_code() -> None:
    """The five OW-T codes this module raises are in `codes.toml`, so `ow explain` resolves them."""
    source = Path(artifact_module.__file__).read_text(encoding="utf-8")
    symbols = set(re.findall(r'symbol="(OW_TARGET_[A-Z_]+)"', source))
    assert symbols == {
        "OW_TARGET_ARTIFACT_SEALED",
        "OW_TARGET_ASSET_UNFROZEN",
        "OW_TARGET_CITE_NOT_VERBATIM",
        "OW_TARGET_CITE_UNRESOLVED",
        "OW_TARGET_GEN_CONTENDED",
    }
    for symbol in symbols:
        assert explain(symbol).symbol == symbol


def test_the_ledger_is_one_row_per_unit_of_each_frozen_asset(store: SqliteArtifactStore) -> None:
    """D776: `ow out back` writes these as the restored `assets/index.json`."""
    from omniweave_core.out.ledger import LedgerRow, slot  # noqa: PLC0415

    sealed = store.seal(
        draft(
            assets=(
                AssetJoin(202, slot(SHA_B), "bake", ("u02",)),
                AssetJoin(201, slot(SHA_A), "image", ("u01", "u02")),
            )
        )
    )
    assert store.ledger(sealed.row.artifact_id) == (
        LedgerRow(201, SHA_A, slot(SHA_A), "image", "u01"),
        LedgerRow(201, SHA_A, slot(SHA_A), "image", "u02"),
        LedgerRow(202, SHA_B, slot(SHA_B), "bake", "u02"),
    )
    assert store.ledger(sealed.row.artifact_id + 1) == ()


def test_the_assets_are_each_slot_with_its_asset_rows_facts(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    """D778: what `ow out assets --slug` prints, in slot order."""
    from omniweave_core.store.artifact import ArtifactAsset  # noqa: PLC0415

    connection = sqlite3.connect(owstore)
    try:
        connection.execute(
            "UPDATE asset SET spdx = 'CC-BY-4.0', licence = 'cc' WHERE asset_id = 201"
        )
        connection.commit()
    finally:
        connection.close()
    sealed = store.seal(
        draft(
            assets=(
                AssetJoin(202, "asset-slot:" + SHA_B, "bake", ("u02",)),
                AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u01", "u02")),
            )
        )
    )
    first, second = store.assets(sealed.row.artifact_id)
    assert first == ArtifactAsset(
        asset_id=201, sha256=SHA_A, slot="asset-slot:" + SHA_A, role="image",
        units=("u01", "u02"), media_type="image/png", byte_len=5, doc_ord=7, licence="cc",
        spdx="CC-BY-4.0", restriction_bits=0,
    )  # fmt: skip
    assert (second.asset_id, second.role, second.restriction_bits) == (202, "bake", BARRED | 2)
    assert store.assets(sealed.row.artifact_id + 1) == ()


def test_the_slot_use_is_every_artefact_and_every_owning_document(
    store: SqliteArtifactStore, owstore: Path
) -> None:
    """D778: 09 section 7.2's reuse query, over one store."""
    from omniweave_core.store.artifact import SlotArtifact, SlotDocument  # noqa: PLC0415

    connection = sqlite3.connect(owstore)
    try:
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
            " format_evidence, source_bytes, status, model_version, declared, achieved)"
            " VALUES (8, ?, ?, 'file:///c/logo.png', 'image/png', 'png', '{}', 5, 'ok',"
            " '1.1', '{}', '{}')",
            (b"\x08" * 16, b"\x00" * 32),
        )
        connection.execute(
            "INSERT INTO asset(asset_id, doc_ord, media_type, sha256, byte_len, store_ref)"
            " VALUES (203, 8, 'image/png', ?, 5, 'cas://x')",
            (bytes.fromhex(SHA_A),),
        )
        connection.commit()
    finally:
        connection.close()
    store.seal(draft())
    store.seal(
        draft(
            key=key(slug="q4-board"),
            path="q4-board@1/q4-board.pptx",
            assets=(AssetJoin(203, "asset-slot:" + SHA_A, "thumbnail", ("u02",)),),
        )
    )
    users, owners = store.slot_use(SHA_A)
    assert users == (
        SlotArtifact("q3-board", 1, "image", ("u01",)),
        SlotArtifact("q4-board", 1, "thumbnail", ("u02",)),
    )
    assert owners == (
        SlotDocument(7, "file:///c/contract.pdf", 201),
        SlotDocument(8, "file:///c/logo.png", 203),
    )
    assert store.slot_use("c" * 64) == ((), ())
