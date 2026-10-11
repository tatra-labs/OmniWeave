"""The asset ledger's interface: `AssetLedger`, `AssetSource` and `LedgerRow`. **D749.**

09-generation.md section 7.1 prints `AssetLedger` with three methods. Its implementation writes L2's
`asset` row and the `artifact_asset` join, which are W9.7's tables, so this cell lands the interface
`CompileV1.lower()` is typed against and the slot syntax every IL uses, and W9.7 lands the class.

## Rulings (the ledger's D749)

1. **The ledger is a Protocol until its tables exist.** `lower()` takes an `AssetLedger` and reads
   it; a target never writes one, so the interface is all a target is compiled against.
2. **`slot()` is framework code now**, because it is the only asset syntax an IL holds (OUT9) and
   needs no table: `asset-slot:` and 64 lower-case hex, refused otherwise.
3. **An `AssetSource` offers a stream, and may offer a length and a claimed digest.** `freeze()`
   hashes the stream itself and compares, because a content-addressed store with an unverified
   writer is a substitution oracle (09 section 7.1); the length is the pre-check, never the bound.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO, Final, Protocol

__all__ = ["SLOT_PREFIX", "AssetLedger", "AssetSource", "LedgerRow", "slot"]

SLOT_PREFIX: Final = "asset-slot:"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


def slot(sha256: str) -> str:
    """Ruling 2: `asset-slot:<sha256>`, the only asset syntax an IL holds (OUT9)."""
    if _HEX64.fullmatch(sha256) is None:
        raise ValueError(f"{sha256!r} is not 64 lower-case hex")
    return SLOT_PREFIX + sha256


class AssetSource(Protocol):
    """Ruling 3: what `freeze()` reads."""

    @property
    def media_type(self) -> str: ...

    @property
    def content_length(self) -> int | None: ...

    @property
    def claimed_sha256(self) -> str | None: ...

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
        if self.slot != slot(self.sha256):
            raise ValueError(f"slot {self.slot!r} is not asset-slot:{self.sha256}")


class AssetLedger(Protocol):
    """09 section 7.1. `freeze()` is the only writer of a compile-time asset (OUT10)."""

    def slot(self, sha256: str) -> str: ...

    def freeze(self, src: AssetSource, *, role: str, unit: str) -> LedgerRow: ...

    def digest(self) -> str:
        """`ledger_digest`: `sha256_canonical` over the frozen rows in `(slot, role)` order."""
        ...
