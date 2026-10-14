"""`omniweave_core.out.ledger`: the asset ledger's interface and the one asset syntax an IL holds.

09-generation.md section 7.1 and charter OUT9. The store-backed `AssetLedger` is W9.7's; this file
holds the part that needs no table, `slot()`, and the row a compile reads.
"""

from __future__ import annotations

import pytest
from omniweave_core.out.ledger import SLOT_PREFIX, LedgerRow, slot

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
