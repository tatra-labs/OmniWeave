"""The asset ledger's interface: `AssetLedger`, `AssetSource` and `LedgerRow`. **D749, D753.**

09-generation.md section 7.1 prints `AssetLedger` with three methods. Its implementation writes L2's
`asset` row and the `artifact_asset` join, which are W9.7's tables, so this cell lands the interface
`CompileV1.lower()` is typed against and the slot syntax every IL uses, and W9.7 lands the class.
D753 lands it: `omniweave_core.store.ledger.SqliteAssetLedger`, over the store thread, with the
JobDir half here because it needs no table.

## Rulings (the ledger's D749)

1. **The ledger is a Protocol until its tables exist.** `lower()` takes an `AssetLedger` and reads
   it; a target never writes one, so the interface is all a target is compiled against.
2. **`slot()` is framework code now**, because it is the only asset syntax an IL holds (OUT9) and
   needs no table: `asset-slot:` and 64 lower-case hex, refused otherwise.
3. **An `AssetSource` offers a stream, and may offer a length and a claimed digest.** `freeze()`
   hashes the stream itself and compares, because a content-addressed store with an unverified
   writer is a substitution oracle (09 section 7.1); the length is the pre-check, never the bound.

## Rulings (the ledger's D753)

4. **An `AssetSource` names its corpus document and may carry licence facts.** 09 section 7.1:
   "every ledger asset belongs to a corpus document", and `asset.doc_ord` is NOT NULL, so a
   source that cannot name one cannot be frozen. The five licence columns travel as one
   `AssetLicence`, the shape `AssetDraft` already gives them.
5. **The ledger is also the reader `lower()` needs.** 09's glossary calls `AssetLedger` "the
   writer and reader over L2's `asset` table for one compile", and its three printed methods
   cannot read. `open(slot)` returns the bytes a frozen slot names, and refuses one that is not
   frozen.
6. **`ledger_digest` is over `(slot, role, unit)`, never over `asset_id`.** 09 section 7.3 orders
   the rows by `(slot, role)`, and `unit` breaks the remaining tie. `asset_id` is a surrogate
   local to one store, so a digest over it would make one compile's purity input differ between
   two machines that froze the same bytes. The slot already names the bytes.
7. **The frozen rows live in `assets/index.json` until the seal.** 11-repo-layout.md's JobDir puts
   `assets/` (with `index.json`) in the data plane, and no store row can hold them earlier,
   because `artifact_asset` needs an `artifact_id` and only the seal mints one. The file is written
   to a sibling and renamed over the old one, so a reader never sees half of it.

## Rulings (the ledger's D771)

8. **A compile worker reads the ledger and never writes it.** `FrozenLedger` is the rows of
   `assets/index.json` over the CAS a worker is handed: `digest()` and `open()` as
   `SqliteAssetLedger` answers them, and `freeze()` refused, because the worker has no store
   handle (INV-6) and every asset is frozen before the gate it compiles behind.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, Final, Never, Protocol

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import TargetError
from omniweave_core.limits import MAX_IL_FILE_BYTES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "ASSET_INDEX",
    "INDEX_SCHEMA",
    "ROLES",
    "SLOT_PREFIX",
    "AssetLedger",
    "AssetLicence",
    "AssetSource",
    "BlobReader",
    "FrozenLedger",
    "LedgerRow",
    "ledger_digest",
    "read_index",
    "slot",
    "write_index",
]

SLOT_PREFIX: Final = "asset-slot:"
ROLES: Final = frozenset({"image", "bake", "font", "video", "audio", "ole", "thumbnail"})
"""`artifact_asset.role`, as 09 section 7 prints its comment."""
ASSET_INDEX: Final = "assets/index.json"
INDEX_SCHEMA: Final = "omniweave.out-assets/1"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_UNIT_ID: Final = re.compile(r"u\d{2,}")
_ROW_KEYS: Final = frozenset({"asset_id", "sha256", "slot", "role", "unit"})
_FIX_FREEZE: Final = "ow out scaffold --asset <path>"


def slot(sha256: str) -> str:
    """Ruling 2: `asset-slot:<sha256>`, the only asset syntax an IL holds (OUT9)."""
    if _HEX64.fullmatch(sha256) is None:
        raise ValueError(f"{sha256!r} is not 64 lower-case hex")
    return SLOT_PREFIX + sha256


@dataclass(frozen=True, slots=True)
class AssetLicence:
    """Ruling 4: the five licence columns of `asset`, carried per asset (03 section 2.8)."""

    licence: str | None = None
    licence_url: str | None = None
    spdx: str | None = None
    source_url: str | None = None
    retrieved_at_ns: int | None = None


class AssetSource(Protocol):
    """Rulings 3 and 4: what `freeze()` reads."""

    @property
    def media_type(self) -> str: ...

    @property
    def content_length(self) -> int | None: ...

    @property
    def claimed_sha256(self) -> str | None: ...

    @property
    def doc_ord(self) -> int:
        """The corpus document the asset belongs to (`asset.doc_ord`, NOT NULL)."""
        ...

    @property
    def licence(self) -> AssetLicence | None: ...

    def open(self) -> BinaryIO: ...


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One frozen asset as a compile sees it: the `asset` row and its slot in this artefact."""

    asset_id: int
    sha256: str
    slot: str
    role: str
    """`image`, `bake`, `font`, `video`, `audio`, `ole` or `thumbnail` (09 section 7)."""
    unit: str

    def __post_init__(self) -> None:
        if isinstance(self.asset_id, bool) or not isinstance(self.asset_id, int):
            raise TypeError(f"asset_id {self.asset_id!r} is not an integer")
        if self.asset_id < 1:
            raise ValueError(f"asset_id {self.asset_id} is below 1")
        if self.slot != slot(self.sha256):
            raise ValueError(f"slot {self.slot!r} is not asset-slot:{self.sha256}")
        if self.role not in ROLES:
            raise ValueError(f"asset role {self.role!r} is not one of {sorted(ROLES)}")
        if _UNIT_ID.fullmatch(self.unit) is None:
            raise ValueError(f"unit id {self.unit!r} does not match ^u\\d{{2,}}$")


class AssetLedger(Protocol):
    """09 section 7.1. `freeze()` is the only writer of a compile-time asset (OUT10)."""

    def slot(self, sha256: str) -> str: ...

    def freeze(self, src: AssetSource, *, role: str, unit: str) -> LedgerRow: ...

    def digest(self) -> str:
        """`ledger_digest`: `sha256_canonical` over the frozen rows in `(slot, role)` order."""
        ...

    def open(self, slot: str) -> BinaryIO:
        """Ruling 5: the bytes a frozen slot names."""
        ...


def ledger_digest(rows: Iterable[LedgerRow]) -> str:
    """Ruling 6: `sha256:` over `(slot, role, unit)` in that order, never over `asset_id`."""
    keyed = sorted({(r.slot, r.role, r.unit) for r in rows})
    return "sha256:" + sha256_canonical([list(k) for k in keyed])


def write_index(job_dir: Path, rows: Iterable[LedgerRow]) -> None:
    """Ruling 7: `assets/index.json`, sorted, written to a sibling and renamed over."""
    path = job_dir / ASSET_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": INDEX_SCHEMA,
        "rows": [
            {
                "asset_id": r.asset_id,
                "sha256": r.sha256,
                "slot": r.slot,
                "role": r.role,
                "unit": r.unit,
            }
            for r in sorted(set(rows), key=lambda r: (r.slot, r.role, r.unit, r.asset_id))
        ],
    }
    staged = path.with_name(path.name + ".tmp")
    staged.write_bytes(json.dumps(body, indent=1, sort_keys=True).encode("utf-8") + b"\n")
    staged.replace(path)


def read_index(job_dir: Path) -> tuple[LedgerRow, ...]:
    """Ruling 7: the frozen rows, or `()` before the first freeze. A malformed file is refused."""
    path = job_dir / ASSET_INDEX
    if not path.exists():
        return ()
    with path.open("rb") as handle:
        raw = handle.read(MAX_IL_FILE_BYTES + 1)
    if len(raw) > MAX_IL_FILE_BYTES:
        _bad_index(f"it runs past {MAX_IL_FILE_BYTES} bytes")
    try:
        body: Any = json.loads(raw)
    except ValueError as exc:
        _bad_index(f"it is not JSON: {exc}")
    if not isinstance(body, dict) or body.get("schema") != INDEX_SCHEMA:
        _bad_index(f"its schema is not {INDEX_SCHEMA!r}")
    rows = body.get("rows")
    if set(body) != {"schema", "rows"} or not isinstance(rows, list):
        _bad_index("it is not exactly a schema and a list of rows")
    out: list[LedgerRow] = []
    for row in rows:
        if not isinstance(row, dict) or frozenset(row) != _ROW_KEYS:
            _bad_index(f"row {row!r} is not {sorted(_ROW_KEYS)}")
        try:
            out.append(LedgerRow(**row))
        except (TypeError, ValueError) as exc:
            _bad_index(f"row {row!r}: {exc}")
    return tuple(out)


def _bad_index(why: str) -> Never:
    raise TargetError(
        f"{ASSET_INDEX} cannot be read, so no asset is frozen: {why}",
        symbol="OW_TARGET_ASSET_UNFROZEN",
        fix=_FIX_FREEZE,
    )


class BlobReader(Protocol):
    """The CAS read by digest: the one method a frozen ledger and an artefact read need, which
    the store's `BlobStore` and a driver's `io.blobs` both have."""

    def open(self, digest: str) -> BinaryIO: ...


class FrozenLedger:
    """Ruling 8: the frozen rows over a CAS, read-only. The ledger a compile worker hands
    `lower()`."""

    __slots__ = ("_blobs", "_rows")

    def __init__(self, rows: Iterable[LedgerRow], blobs: BlobReader) -> None:
        self._rows = tuple(rows)
        self._blobs = blobs

    @classmethod
    def of(cls, job_dir: Path, blobs: BlobReader) -> FrozenLedger:
        """The JobDir's `assets/index.json`, whose rows the gate was decided against."""
        return cls(read_index(job_dir), blobs)

    def slot(self, sha256: str) -> str:
        return slot(sha256)

    def freeze(self, src: AssetSource, *, role: str, unit: str) -> LedgerRow:
        del src
        raise TargetError(
            f"lower() asked to freeze a {role} asset for {unit}; a compile reads the ledger "
            "frozen before its gate, and writes none",
            symbol="OW_TARGET_ASSET_UNFROZEN",
            fix=_FIX_FREEZE,
        )

    def digest(self) -> str:
        return ledger_digest(self._rows)

    def open(self, slot: str) -> BinaryIO:
        for row in self._rows:
            if row.slot == slot:
                return self._blobs.open(row.sha256)
        raise TargetError(
            f"{slot} is not in this compile's ledger",
            symbol="OW_TARGET_ASSET_UNFROZEN",
            fix=_FIX_FREEZE,
        )
