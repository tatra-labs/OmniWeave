"""`SqliteAssetLedger` -- the `AssetLedger` over L2's `asset` table, for one compile. **D753.**

09-generation.md section 7.1 ("Freezing") is the whole of OUT10, and this class is its one writer.
`omniweave_core.out.ledger` holds the interface, `slot()`, the digest and the JobDir index; this
file holds what needs a connection, which INV-17 puts in `omniweave_core.store` and nowhere else.
It runs its statements on a `StoreThread`, the way `store/artifact.py` and `store/cache.py` do.

## Rulings

1. **`freeze()` is 09's four steps in 09's order.**
   - A declared `content_length` past the CAS ceiling is refused before the source is opened.
   - The stream goes into CAS through `BlobStore.put()`, which hashes as it writes and aborts at
     the ceiling, deleting what it staged.
   - The digest the source claims is compared with the digest the stream produced:
     `OW_ASSET_DIGEST_MISMATCH` on any difference.
   - The `asset` row is written or matched.
   - The row is recorded in the ledger and in `assets/index.json`.

   The bytes reach CAS before the row exists, so the failure a crash leaves is an object with no
   row, which `ow store gc` reaps, never a row with no object.
2. **A match never patches.** If the source's document already holds an `asset` row for these
   bytes, that row is the asset, with its licence facts and its `restriction_bits`, which are the
   SoR. The source's facts are written only on a row this call creates, under `origin_part` NULL
   and the ledger's own `restriction_bits` (the runner's stamp, INV-16). Two rows for one
   document and one digest (two `origin_part`s) resolve to the lower `asset_id`, so the choice is
   stable.
3. **The document must already exist.** 09 section 7.1's consequence 1: "a logo the user supplies
   is ingested as its own `doc` before it can be slotted". A source naming a `doc_ord` the store
   does not hold is `NotFoundError`, whose fix is that ingestion.
4. **Preflight check 2 is `assert_frozen()`** (09 section 5.1): every `asset-slot:` the bundle
   holds has a ledger row, and the store still holds that row's `asset` and its CAS object. The
   refusal is `OW_TARGET_ASSET_UNFROZEN`, naming every slot that fails, never only the first.
5. **The seal's joins come from the ledger.** `joins()` groups the rows into one `AssetJoin` per
   `(asset_id, slot, role)` with the sorted units that use it, which is `artifact_asset`'s key.
6. **`open()` reads only what is frozen** (ledger ruling 5). A slot with no ledger row is
   `OW_TARGET_ASSET_UNFROZEN`. A compile never reaches past its ledger, and never past the CAS:
   there is no fetch anywhere in this class, which is 09's "a compile that must fetch REFUSES"
   made structural.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, BinaryIO, Final

from omniweave_core.errors import ModelError, NotFoundError, ResourceLimit, StoreError, TargetError
from omniweave_core.out.ledger import (
    ROLES,
    LedgerRow,
    ledger_digest,
    read_index,
    slot,
    write_index,
)
from omniweave_core.store.artifact import AssetJoin
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from omniweave_core.blobs import BlobStore
    from omniweave_core.out.ledger import AssetSource

__all__ = ["ASSET_DIGEST_MISMATCH", "SqliteAssetLedger"]

ASSET_DIGEST_MISMATCH: Final = "OW_ASSET_DIGEST_MISMATCH"
_FIX_FREEZE: Final = "ow out scaffold --asset <path>"

_MATCH_SQL: Final = (
    "SELECT asset_id FROM asset WHERE doc_ord = ? AND sha256 = ? ORDER BY asset_id LIMIT 1"
)
_INSERT_SQL: Final = (
    "INSERT INTO asset(doc_ord, media_type, origin_part, sha256, byte_len, width, height,"
    " store_ref, licence, licence_url, spdx, source_url, retrieved_at_ns, restriction_bits)"
    " VALUES (:doc_ord, :media_type, NULL, :sha256, :byte_len, NULL, NULL, :store_ref, :licence,"
    " :licence_url, :spdx, :source_url, :retrieved_at_ns, :restriction_bits)"
)


class SqliteAssetLedger:
    """`AssetLedger` over one `StoreThread`, one `BlobStore` and one JobDir. Structural."""

    __slots__ = ("_blobs", "_job_dir", "_restriction_bits", "_rows", "_thread", "_wait_ms")

    def __init__(
        self,
        thread: StoreThread,
        blobs: BlobStore,
        *,
        job_dir: Path,
        restriction_bits: int = 0,
        wait_ms: int = INTERACTIVE_WAIT_MS,
    ) -> None:
        self._thread = thread
        self._blobs = blobs
        self._job_dir = job_dir
        self._restriction_bits = restriction_bits
        self._wait_ms = wait_ms
        self._rows: set[LedgerRow] = set(read_index(job_dir))

    def slot(self, sha256: str) -> str:
        return slot(sha256)

    def rows(self) -> tuple[LedgerRow, ...]:
        """The frozen rows in `(slot, role, unit)` order."""
        return tuple(sorted(self._rows, key=lambda r: (r.slot, r.role, r.unit, r.asset_id)))

    def digest(self) -> str:
        return ledger_digest(self._rows)

    def freeze(self, src: AssetSource, *, role: str, unit: str) -> LedgerRow:
        """Rulings 1-3: CAS first, then the row, then the ledger."""
        if role not in ROLES:
            raise ValueError(f"asset role {role!r} is not one of {sorted(ROLES)}")
        declared = src.content_length
        if declared is not None and declared > self._blobs.max_bytes:
            raise ResourceLimit(
                f"the source declares {declared} bytes, past MAX_ASSET_BYTES "
                f"({self._blobs.max_bytes}); nothing was read",
                limit="MAX_ASSET_BYTES",
                fix="split the asset, or clamp [limits] below the ceiling; widening is a fork",
            )
        with src.open() as handle:
            digest = self._blobs.put(handle)
        hexdigest = digest.hex()
        claimed = src.claimed_sha256
        if claimed is not None and claimed != hexdigest:
            raise ModelError(
                f"the source claimed sha256 {claimed} and the stream hashed to {hexdigest}; "
                "the asset is rejected (09 section 7.1)",
                symbol=ASSET_DIGEST_MISMATCH,
                fix="re-export the asset and freeze it again",
            )
        byte_len = self._blobs.path(digest).stat().st_size
        licence = src.licence
        params = {
            "doc_ord": src.doc_ord,
            "media_type": src.media_type,
            "sha256": digest,
            "byte_len": byte_len,
            "store_ref": self._blobs.ref(digest),
            "licence": None if licence is None else licence.licence,
            "licence_url": None if licence is None else licence.licence_url,
            "spdx": None if licence is None else licence.spdx,
            "source_url": None if licence is None else licence.source_url,
            "retrieved_at_ns": None if licence is None else licence.retrieved_at_ns,
            "restriction_bits": self._restriction_bits,
        }

        def run(connection: sqlite3.Connection) -> object:
            if (
                connection.execute("SELECT 1 FROM doc WHERE doc_ord = ?", (src.doc_ord,)).fetchone()
                is None
            ):
                raise NotFoundError(
                    f"no document d{src.doc_ord} owns this asset; every ledger asset belongs to "
                    "a corpus document (09 section 7.1)",
                    fix=_FIX_FREEZE + "   # ingests the file as its own document first",
                )
            found = connection.execute(_MATCH_SQL, (src.doc_ord, digest)).fetchone()
            if found is not None:
                return int(found[0])
            cursor = connection.execute(_INSERT_SQL, params)
            if cursor.lastrowid is None:  # pragma: no cover -- an INSERT that wrote has an id.
                raise StoreError("the asset INSERT wrote no rowid", fix="report this as a bug")
            return cursor.lastrowid

        asset_id = self._thread.run(
            Unit(name="out.freeze", run=run, cost_class="local_compute", wait_ms=self._wait_ms)
        )
        if not isinstance(asset_id, int):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the out.freeze unit returned no asset id", fix="report this bug")
        row = LedgerRow(
            asset_id=asset_id, sha256=hexdigest, slot=slot(hexdigest), role=role, unit=unit
        )
        self._rows.add(row)
        write_index(self._job_dir, self._rows)
        return row

    def assert_frozen(self, slots: Iterable[str]) -> None:
        """Ruling 4, preflight check 2: every slot has a row, an `asset`, and its CAS object."""
        wanted = sorted(set(slots))
        by_slot = {r.slot: r for r in self._rows}
        missing = [s for s in wanted if s not in by_slot]
        ids = sorted({by_slot[s].asset_id for s in wanted if s in by_slot})

        def run(connection: sqlite3.Connection) -> object:
            return {
                asset_id: bytes(sha).hex()
                for asset_id, sha in connection.execute(
                    "SELECT asset_id, sha256 FROM asset WHERE store_ref IS NOT NULL"
                    " AND asset_id IN (SELECT value FROM json_each(?))",
                    (str(ids),),
                )
            }

        held = self._thread.run(Unit(name="out.assert_frozen", run=run, wait_ms=self._wait_ms))
        if not isinstance(held, dict):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the out.assert_frozen unit returned no rows", fix="report this bug")
        for s in wanted:
            row = by_slot.get(s)
            if row is None:
                continue
            if held.get(row.asset_id) != row.sha256 or not self._blobs.has(row.sha256):
                missing.append(s)
        if missing:
            raise TargetError(
                f"{len(missing)} asset slot(s) are not frozen: {', '.join(sorted(missing))}",
                symbol="OW_TARGET_ASSET_UNFROZEN",
                fix=_FIX_FREEZE,
            )

    def joins(self) -> tuple[AssetJoin, ...]:
        """Ruling 5: `artifact_asset`'s rows for the seal, one per `(asset_id, slot, role)`."""
        grouped: dict[tuple[int, str, str], set[str]] = {}
        for row in self._rows:
            grouped.setdefault((row.asset_id, row.slot, row.role), set()).add(row.unit)
        return tuple(
            AssetJoin(asset_id, slot_, role, tuple(sorted(units)))
            for (asset_id, slot_, role), units in sorted(grouped.items())
        )

    def open(self, slot: str) -> BinaryIO:
        """Ruling 6: the bytes of a frozen slot, out of CAS, and nothing else."""
        for row in self._rows:
            if row.slot == slot:
                return self._blobs.open(row.sha256)
        raise TargetError(
            f"{slot} is not in this compile's ledger",
            symbol="OW_TARGET_ASSET_UNFROZEN",
            fix=_FIX_FREEZE,
        )
