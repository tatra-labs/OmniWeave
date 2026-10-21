"""`SqliteAssetLedger` against a real store and a real CAS: freeze, match, preflight 2, the seal.

09-generation.md section 7.1 (freezing, OUT10), section 7.3 (`ledger_digest`) and section 5.1's
preflight check 2. The rows the ledger writes are L2's `asset` rows, the bytes are `BlobStore`'s,
and the frozen set persists in the JobDir's `assets/index.json` between authoring and the seal.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the ledger wrote.
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import ModelError, NotFoundError, ResourceLimit, TargetError, explain
from omniweave_core.out import ledger as out_ledger
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.ledger import (
    ASSET_INDEX,
    AssetLedger,
    AssetLicence,
    LedgerRow,
    ledger_digest,
    read_index,
    slot,
    write_index,
)
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.artifact import (
    ArtifactDraft,
    AssetJoin,
    PureKey,
    SqliteArtifactStore,
    UnitRow,
)
from omniweave_core.store.ledger import SqliteAssetLedger

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW_NS = 1_700_000_000_000_000_000
LOGO = b"\x89PNG logo bytes"
CHART = b"\x89PNG chart bytes, longer"
CC_BY = AssetLicence(licence="CC BY 4.0", spdx="CC-BY-4.0", source_url="urn:example:logo")
STAMP = 1 << 5


def hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Source:
    """An `AssetSource` over bytes in memory, counting how often it was opened."""

    data: bytes
    doc_ord: int = 8
    media_type: str = "image/png"
    content_length: int | None = None
    claimed_sha256: str | None = None
    licence: AssetLicence | None = CC_BY
    opened: int = 0

    def open(self) -> BinaryIO:
        self.opened += 1
        return io.BytesIO(self.data)


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES (1, 'compile.text.owtext', 1, 'f', x'00')"
    )
    for doc_ord in (7, 8):
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
            " format_evidence, source_bytes, status, model_version, declared, achieved)"
            " VALUES (?, ?, ?, ?, 'image/png', 'png', '{}', 10, 'ok', '1.1', '{}', '{}')",
            (doc_ord, bytes([doc_ord]) * 16, b"\x00" * 32, f"file:///c/{doc_ord}.png"),
        )
    sha = hexdigest(LOGO)
    connection.execute(
        "INSERT INTO asset(asset_id, doc_ord, media_type, origin_part, sha256, byte_len,"
        " store_ref, licence, restriction_bits) VALUES (41, 7, 'image/png', 'logo.png', ?, ?,"
        " ?, 'proprietary', 2)",
        (bytes.fromhex(sha), len(LOGO), f"cas://{sha[:2]}/{sha[2:4]}/{sha}"),
    )


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 6
        connection.execute("BEGIN IMMEDIATE")
        _seed(connection)
        connection.execute("COMMIT")
    finally:
        connection.close()
    return path


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    (tmp_path / "cas").mkdir()
    store = BlobStore(tmp_path / "cas")
    store.put(io.BytesIO(LOGO))
    return store


@pytest.fixture
def thread(owstore: Path) -> Iterator[ow.StoreThread]:
    started = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield started
    finally:
        started.close()


@pytest.fixture
def job(tmp_path: Path) -> Path:
    return tmp_path / "job"


@pytest.fixture
def ledger(thread: ow.StoreThread, blobs: BlobStore, job: Path) -> SqliteAssetLedger:
    return SqliteAssetLedger(thread, blobs, job_dir=job, restriction_bits=STAMP)


def rows(owstore: Path, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(owstore)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# freeze()
# ---------------------------------------------------------------------------


def test_freeze_writes_the_asset_row_and_the_index(
    ledger: SqliteAssetLedger, owstore: Path, blobs: BlobStore, job: Path
) -> None:
    sha = hexdigest(CHART)
    row = ledger.freeze(Source(CHART, claimed_sha256=sha), role="image", unit="u02")
    assert (row.sha256, row.slot, row.role, row.unit) == (sha, slot(sha), "image", "u02")
    assert rows(
        owstore,
        "SELECT doc_ord, origin_part, byte_len, store_ref, licence, spdx, source_url,"
        " restriction_bits FROM asset WHERE asset_id = ?",
        (row.asset_id,),
    ) == [(8, None, len(CHART), blobs.ref(sha), "CC BY 4.0", "CC-BY-4.0", CC_BY.source_url, STAMP)]
    assert blobs.has(sha)
    assert read_index(job) == (row,)
    assert not (job / (ASSET_INDEX + ".tmp")).exists()


def test_freeze_matches_the_documents_row_and_never_patches_it(
    ledger: SqliteAssetLedger, owstore: Path
) -> None:
    """Ruling 2: doc 7 already holds the logo; its licence and bits are the SoR."""
    row = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    assert row.asset_id == 41
    assert rows(owstore, "SELECT asset_id, licence, restriction_bits FROM asset") == [
        (41, "proprietary", 2)
    ]


def test_the_same_bytes_under_another_document_are_another_row(
    ledger: SqliteAssetLedger, owstore: Path
) -> None:
    """09 section 7.2: the ledger deduplicates bytes and does not deduplicate permission."""
    row = ledger.freeze(Source(LOGO, doc_ord=8), role="image", unit="u01")
    assert row.asset_id != 41
    assert rows(
        owstore, "SELECT count(*) FROM asset WHERE sha256 = ?", (bytes.fromhex(row.sha256),)
    ) == [(2,)]


def test_one_asset_used_twice_is_one_row_and_one_join(
    ledger: SqliteAssetLedger, owstore: Path
) -> None:
    first = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u03")
    ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    ledger.freeze(Source(LOGO, doc_ord=7), role="thumbnail", unit="u01")
    assert rows(owstore, "SELECT count(*) FROM asset") == [(1,)]
    assert ledger.joins() == (
        AssetJoin(41, first.slot, "image", ("u01", "u03")),
        AssetJoin(41, first.slot, "thumbnail", ("u01",)),
    )
    assert [(r.role, r.unit) for r in ledger.rows()] == [
        ("image", "u01"),
        ("image", "u03"),
        ("thumbnail", "u01"),
    ]


def test_a_claimed_digest_the_stream_disproves_is_rejected(
    ledger: SqliteAssetLedger, owstore: Path, job: Path
) -> None:
    with pytest.raises(ModelError, match="hashed to") as caught:
        ledger.freeze(Source(CHART, claimed_sha256=hexdigest(LOGO)), role="image", unit="u01")
    assert caught.value.code() == "OW_ASSET_DIGEST_MISMATCH"
    assert explain("OW_ASSET_DIGEST_MISMATCH").numeric == "OW-M-035"
    assert rows(owstore, "SELECT count(*) FROM asset") == [(1,)]
    assert read_index(job) == ()


def test_a_declared_length_past_the_ceiling_is_refused_unread(
    thread: ow.StoreThread, tmp_path: Path, job: Path
) -> None:
    (tmp_path / "small").mkdir()
    small = BlobStore(tmp_path / "small", max_bytes=16)
    ledger = SqliteAssetLedger(thread, small, job_dir=job)
    source = Source(CHART, content_length=len(CHART))
    with pytest.raises(ResourceLimit, match="nothing was read") as caught:
        ledger.freeze(source, role="image", unit="u01")
    assert caught.value.limit == "MAX_ASSET_BYTES"
    assert source.opened == 0


def test_an_undeclared_stream_past_the_ceiling_aborts_and_leaves_nothing(
    thread: ow.StoreThread, tmp_path: Path, job: Path, owstore: Path
) -> None:
    (tmp_path / "small").mkdir()
    small = BlobStore(tmp_path / "small", max_bytes=16)
    ledger = SqliteAssetLedger(thread, small, job_dir=job)
    with pytest.raises(ResourceLimit, match="MAX_ASSET_BYTES"):
        ledger.freeze(Source(CHART), role="image", unit="u01")
    assert not small.has(hexdigest(CHART))
    assert rows(owstore, "SELECT count(*) FROM asset") == [(1,)]


def test_an_asset_with_no_document_is_refused(ledger: SqliteAssetLedger, owstore: Path) -> None:
    with pytest.raises(NotFoundError, match="no document d99") as caught:
        ledger.freeze(Source(CHART, doc_ord=99), role="image", unit="u01")
    assert "ingests the file as its own document first" in caught.value.fix
    assert rows(owstore, "SELECT count(*) FROM asset") == [(1,)]


def test_a_role_outside_the_vocabulary_is_refused(ledger: SqliteAssetLedger) -> None:
    with pytest.raises(ValueError, match="role 'logo'"):
        ledger.freeze(Source(CHART), role="logo", unit="u01")


# ---------------------------------------------------------------------------
# The digest, and the index between authoring and the seal
# ---------------------------------------------------------------------------


def test_the_digest_is_over_content_never_over_asset_id() -> None:
    """Ledger ruling 6: two stores that froze the same bytes compute one digest."""
    sha = hexdigest(LOGO)
    here = [
        LedgerRow(41, sha, slot(sha), "image", "u01"),
        LedgerRow(41, sha, slot(sha), "font", "u02"),
    ]
    there = [
        LedgerRow(9, sha, slot(sha), "font", "u02"),
        LedgerRow(9, sha, slot(sha), "image", "u01"),
    ]
    assert ledger_digest(here) == ledger_digest(there)
    assert ledger_digest(here).startswith("sha256:")
    moved = [LedgerRow(41, sha, slot(sha), "image", "u03"), here[1]]
    assert ledger_digest(moved) != ledger_digest(here)
    assert ledger_digest([here[0]]) != ledger_digest(here)


def test_the_frozen_set_survives_into_the_next_ledger(
    ledger: SqliteAssetLedger, thread: ow.StoreThread, blobs: BlobStore, job: Path
) -> None:
    ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    ledger.freeze(Source(CHART), role="image", unit="u02")
    again = SqliteAssetLedger(thread, blobs, job_dir=job)
    assert again.rows() == ledger.rows()
    assert again.digest() == ledger.digest()


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (b"{", "not JSON"),
        (b'{"schema": "x", "rows": []}', "schema is not"),
        (b'{"schema": "omniweave.out-assets/1", "rows": [], "extra": 1}', "exactly a schema"),
        (b'{"schema": "omniweave.out-assets/1", "rows": {}}', "exactly a schema"),
        (b'{"schema": "omniweave.out-assets/1", "rows": [{"asset_id": 1}]}', "is not"),
        (
            b'{"schema": "omniweave.out-assets/1", "rows": [{"asset_id": "1", "sha256": "'
            + b"a" * 64
            + b'", "slot": "asset-slot:'
            + b"a" * 64
            + b'", "role": "image", "unit": "u01"}]}',
            "not an integer",
        ),
        (
            b'{"schema": "omniweave.out-assets/1", "rows": [{"asset_id": 1, "sha256": "'
            + b"a" * 64
            + b'", "slot": "asset-slot:'
            + b"b" * 64
            + b'", "role": "image", "unit": "u01"}]}',
            "is not asset-slot",
        ),
    ],
)
def test_a_malformed_index_freezes_nothing(job: Path, body: bytes, said: str) -> None:
    (job / "assets").mkdir(parents=True)
    (job / ASSET_INDEX).write_bytes(body)
    with pytest.raises(TargetError, match=said) as caught:
        read_index(job)
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"


def test_the_index_read_is_bounded(job: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sha = hexdigest(LOGO)
    write_index(job, [LedgerRow(41, sha, slot(sha), "image", "u01")])
    monkeypatch.setattr(out_ledger, "MAX_IL_FILE_BYTES", 20)
    with pytest.raises(TargetError, match="runs past 20 bytes"):
        read_index(job)


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        ({"asset_id": 0}, "below 1"),
        ({"asset_id": True}, "not an integer"),
        ({"role": "logo"}, "role 'logo'"),
        ({"unit": "slide1"}, "does not match"),
    ],
)
def test_a_ledger_row_refuses_what_artifact_asset_would(fields: dict[str, Any], said: str) -> None:
    sha = hexdigest(LOGO)
    base: dict[str, Any] = {
        "asset_id": 41,
        "sha256": sha,
        "slot": slot(sha),
        "role": "image",
        "unit": "u01",
    }
    with pytest.raises((TypeError, ValueError), match=said):
        LedgerRow(**{**base, **fields})


# ---------------------------------------------------------------------------
# Preflight check 2, and the reader
# ---------------------------------------------------------------------------


def test_preflight_two_passes_when_every_slot_is_frozen(ledger: SqliteAssetLedger) -> None:
    logo = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    chart = ledger.freeze(Source(CHART), role="image", unit="u02")
    ledger.assert_frozen([logo.slot, chart.slot, logo.slot])


def test_preflight_two_names_every_slot_that_fails(
    ledger: SqliteAssetLedger, thread: ow.StoreThread, blobs: BlobStore
) -> None:
    logo = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    chart = ledger.freeze(Source(CHART), role="image", unit="u02")
    stray = slot("c" * 64)
    thread.run(
        ow.Unit(name="test.drop", run=lambda c: c.execute("DELETE FROM asset WHERE asset_id = 41"))
    )
    blobs.path(chart.sha256).unlink()
    with pytest.raises(TargetError, match=r"3 asset slot\(s\) are not frozen") as caught:
        ledger.assert_frozen([logo.slot, chart.slot, stray])
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"
    assert str(caught.value).endswith(", ".join(sorted([logo.slot, chart.slot, stray])))


def test_open_reads_a_frozen_slot_and_nothing_else(ledger: SqliteAssetLedger) -> None:
    logo = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    with ledger.open(logo.slot) as handle:
        assert handle.read() == LOGO
    with pytest.raises(TargetError, match="not in this compile's ledger") as caught:
        ledger.open(slot(hexdigest(CHART)))
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"


def test_the_store_ledger_is_an_asset_ledger(ledger: SqliteAssetLedger) -> None:
    typed: AssetLedger = ledger
    assert typed.slot(hexdigest(LOGO)) == slot(hexdigest(LOGO))
    assert typed.digest() == ledger_digest(())


class _Clock:
    def monotonic_ns(self) -> int:  # pragma: no cover -- the seal reads wall time only.
        return 0

    def wall_ns(self) -> int:
        return NOW_NS


def test_the_ledgers_joins_and_digest_are_what_the_seal_writes(
    ledger: SqliteAssetLedger, thread: ow.StoreThread, owstore: Path
) -> None:
    """Ruling 5: `joins()` is `artifact_asset`, and the asset's bits reach the artefact."""
    logo = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u02")
    ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")

    def d(n: int) -> str:
        return f"sha256:{n:064x}"

    sealed = SqliteArtifactStore(thread, clock=_Clock()).seal(
        ArtifactDraft(
            key=PureKey("pptx", "deck", "release", d(1), d(2), ledger.digest(), d(4)),
            artifact_gen=1,
            origin="authored",
            compile_driver="compile.pptx.native",
            media_type="application/zip",
            path="deck@1/deck.pptx",
            sha256=d(5),
            byte_len=1,
            part_digest=d(6),
            il_store_ref="cas://00/00/" + "0" * 64,
            determinism=("part",),
            gate_status=GateStatus.PASSED,
            report_sha256=d(7),
            receipt_sha256=d(8),
            producer_id=1,
            units=tuple(
                UnitRow(f"u0{n}", n, UnitOutcome.NATIVE, f"il/u0{n}.svg", d(10 + n), "0000abcd")
                for n in (1, 2)
            ),
            assets=ledger.joins(),
        )
    )
    assert rows(owstore, "SELECT asset_id, slot, role, units FROM artifact_asset") == [
        (41, logo.slot, "image", '["u01","u02"]')
    ]
    assert sealed.row.ledger_digest == ledger.digest()
    assert sealed.row.restriction_bits == 2


def test_the_index_is_json_a_reader_can_diff(ledger: SqliteAssetLedger, job: Path) -> None:
    row = ledger.freeze(Source(LOGO, doc_ord=7), role="image", unit="u01")
    body = json.loads((job / ASSET_INDEX).read_bytes())
    assert body == {
        "schema": "omniweave.out-assets/1",
        "rows": [
            {"asset_id": 41, "sha256": row.sha256, "slot": row.slot, "role": "image", "unit": "u01"}
        ],
    }
