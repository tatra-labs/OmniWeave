"""`omniweave_core.out.ledger`: the asset ledger's interface and the one asset syntax an IL holds.

09-generation.md section 7.1 and charter OUT9. The store-backed `AssetLedger` is W9.7's; this file
holds the part that needs no table, `slot()`, and the row a compile reads.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import TargetError
from omniweave_core.out.ledger import (
    SLOT_PREFIX,
    FrozenLedger,
    LedgerRow,
    ledger_digest,
    slot,
    write_index,
)

HEX = "9f" * 32


def test_slot_is_asset_slot_and_64_lower_case_hex() -> None:
    assert slot(HEX) == f"{SLOT_PREFIX}{HEX}" == f"asset-slot:{HEX}"


@pytest.mark.parametrize("value", ["9F" * 32, HEX[:-1], HEX + "0", "", "sha256:" + HEX])
def test_slot_refuses_anything_else(value: str) -> None:
    with pytest.raises(ValueError, match="64 lower-case hex"):
        slot(value)


def test_a_ledger_row_carries_its_own_slot() -> None:
    row = LedgerRow(asset_id=7, sha256=HEX, slot=slot(HEX), role="image", unit="u03")
    assert row.slot.endswith(HEX)
    with pytest.raises(ValueError, match="is not asset-slot"):
        LedgerRow(asset_id=7, sha256=HEX, slot=slot("a" * 64), role="image", unit="u03")


# ---------------------------------------------------------------------------------------------
# Ruling 8 (D771): the ledger a compile worker reads
# ---------------------------------------------------------------------------------------------


def _frozen(tmp_path: Path) -> tuple[FrozenLedger, BlobStore, list[LedgerRow]]:
    (tmp_path / "cas").mkdir()
    blobs = BlobStore(tmp_path / "cas")
    rows = []
    for n, body in enumerate((b"logo", b"chart"), start=1):
        sha = blobs.put(io.BytesIO(body)).hex()
        rows.append(LedgerRow(asset_id=n, sha256=sha, slot=slot(sha), role="image", unit="u01"))
    write_index(tmp_path, rows)
    return FrozenLedger.of(tmp_path, blobs), blobs, rows


def test_the_frozen_ledger_is_the_indexs_rows_and_digest(tmp_path: Path) -> None:
    ledger, _, rows = _frozen(tmp_path)
    assert ledger.digest() == ledger_digest(rows)
    assert ledger.slot(HEX) == slot(HEX)


def test_a_frozen_slot_opens_its_bytes_out_of_the_cas(tmp_path: Path) -> None:
    ledger, _, rows = _frozen(tmp_path)
    for row, body in zip(rows, (b"logo", b"chart"), strict=True):
        with ledger.open(row.slot) as handle:
            assert handle.read() == body
        assert hashlib.sha256(body).hexdigest() == row.sha256


def test_a_slot_the_index_does_not_hold_is_refused(tmp_path: Path) -> None:
    ledger, _, _ = _frozen(tmp_path)
    with pytest.raises(TargetError) as caught:
        ledger.open(slot(HEX))
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"


def test_a_worker_never_freezes(tmp_path: Path) -> None:
    ledger, _, _ = _frozen(tmp_path)
    with pytest.raises(TargetError, match="writes none") as caught:
        ledger.freeze(object(), role="image", unit="u02")  # type: ignore[arg-type]
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"


def test_a_job_dir_with_no_index_is_the_empty_ledger(tmp_path: Path) -> None:
    (tmp_path / "cas").mkdir()
    ledger = FrozenLedger.of(tmp_path, BlobStore(tmp_path / "cas"))
    assert ledger.digest() == ledger_digest(())
