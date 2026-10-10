"""The JobDir layout: `ILFile`, one row per file under `il/`. **D737.**

09-generation.md section 3.7 prints `ILFile` here beside `ILBundle`, which is not built yet. This
module holds the row and the streaming read that fills it, because `il_digest` (09 section 4.5) is
a function of those rows and of nothing else.

## Rulings (the ledger's D737)

8. **`il/` is read flat, and a dot-file is not IL.** `ILFile.name` is a basename and the digest
   sorts by basename, so a subdirectory contributes nothing. A name beginning with `.` is skipped:
   `il/.stamp.lock` (09 section 4.3) is `ow out stamp`'s transient lock, and a digest that moved
   while a stamper held it would make every concurrent check stale.
9. **An empty file is readable.** 09's `byte_len` is *"0 iff sha256 == unreadable"*, which an empty
   `il.toml` contradicts: it has a digest and no bytes. Only the unreadable direction holds.
10. **An unreadable file's error names the error and not the path**: the exception's class and its
    `strerror`. The digest is basename-sorted so moving the job directory does not change it, and a
    report quoting an absolute path would change with the directory all the same.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["UNREADABLE", "ILFile", "read_il_files"]

UNREADABLE: Final = "unreadable"
"""What an unreadable file contributes to `il_digest` in place of its hex (09 section 4.5)."""

_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_BUFFER: Final = 1 << 20
"""`il_digest` streams (09 section 14.2): a fixed buffer, so an 8 GiB bundle digests in constant
memory."""


@dataclass(frozen=True, slots=True)
class ILFile:
    """One file under `il/`, `il.toml` included (09 section 3.7)."""

    name: str
    """A basename, never a path."""
    sha256: str
    """64 lower-case hex, or `UNREADABLE`."""
    byte_len: int
    error: str | None = None
    """Non-`None` iff `sha256 == UNREADABLE`."""

    def __post_init__(self) -> None:
        if not self.name or self.name in {".", ".."} or "/" in self.name or "\\" in self.name:
            raise ValueError(f"{self.name!r} is not a basename under il/")
        unreadable = self.sha256 == UNREADABLE
        if not unreadable and _HEX64.fullmatch(self.sha256) is None:
            raise ValueError(
                f"{self.name}: {self.sha256!r} is neither 64 lower-case hex nor {UNREADABLE!r}"
            )
        if unreadable != (self.error is not None):
            raise ValueError(f"{self.name}: an error is recorded iff the file is unreadable")
        if self.byte_len < 0 or (unreadable and self.byte_len):
            raise ValueError(f"{self.name}: byte_len {self.byte_len} (ruling 9)")


def read_il_files(root: Path) -> tuple[ILFile, ...]:
    """Every file directly under `root`, sorted by basename (rulings 8-10)."""
    names = sorted(
        entry.name
        for entry in os.scandir(root)
        if not entry.name.startswith(".") and not entry.is_dir()
    )
    return tuple(_read(root / name) for name in names)


def _read(path: Path) -> ILFile:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_BUFFER):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        return ILFile(
            path.name, UNREADABLE, 0, f"{type(exc).__name__}: {exc.strerror or 'unreadable'}"
        )
    return ILFile(path.name, digest.hexdigest(), size)
