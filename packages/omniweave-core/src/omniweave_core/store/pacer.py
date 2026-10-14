"""The Pacer's SQLite third: N inserts and their select, through the one connect. **D822.**

12-performance.md section 1.2: every time budget on `ow-bench-1` is a ratio to the Pacer, and the
Pacer is *"`blake2b` over 64 MiB, a 2M-iteration integer loop, and 200k SQLite insert+select"*.
The first two are pure Python and live with the rest of the Pacer in `omniweave.run.bench`. This
one is here because INV-17 puts `sqlite3.connect` in `store/sqlite.py` and G24 keeps `BEGIN` and
`COMMIT` inside `omniweave_core/store/`; the bench measures the round and does not hold the file.

## Rulings

1. **The file is the caller's**, a path in a scratch directory the bench already has. It opens
   through `sqlite.connect()`, so the Pacer pays the pragmas a store pays, which is the point of
   having SQLite in it at all.
2. **The inserts are one transaction**, as a store's derived rows are (INV-17), so the round
   measures the B-tree and the WAL and not one fsync per row.
3. **The select reads every row back and sums its keys**, returned as the round's proof. A read
   that returned nothing could not tell a select from a skipped one, and `n(n-1)/2` is checkable
   without a second query.
4. **A file that already holds the table is refused**, rather than appended to: a second round
   over the same file would measure a larger B-tree and report the same number of rows.

Specified in 12-performance.md section 1.2 and `eval/perf.toml`'s `[pacer]`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.errors import StoreError
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["PACER_TABLE", "sqlite_round"]

PACER_TABLE: Final = "ow_pacer"
_PAYLOAD: Final = b"\x5a" * 32
"""A fixed 32-byte value per row: each row is a key and a blob, and none costs more than another."""


def sqlite_round(path: Path, rows: int) -> int:
    """Insert `rows` rows in one transaction, select them all, and return the sum of their keys."""
    if rows < 0:
        raise StoreError(f"a Pacer round of {rows} rows", fix="pass a row count of 0 or more")
    connection = connect(path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (PACER_TABLE,)
        ).fetchone()
        if exists is not None:
            raise StoreError(
                f"{path} already holds a Pacer table; a second round would time a larger B-tree",
                fix="give each Pacer round a fresh scratch file",
            )
        connection.execute(f"CREATE TABLE {PACER_TABLE} (k INTEGER PRIMARY KEY, v BLOB NOT NULL)")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.executemany(
                f"INSERT INTO {PACER_TABLE} (k, v) VALUES (?, ?)",  # noqa: S608 -- a constant
                ((k, _PAYLOAD) for k in range(rows)),
            )
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
        total = 0
        for (key,) in connection.execute(f"SELECT k FROM {PACER_TABLE}"):  # noqa: S608
            total += int(key)
        return total
    finally:
        connection.close()
