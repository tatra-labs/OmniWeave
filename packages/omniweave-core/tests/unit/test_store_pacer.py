"""`omniweave_core.store.pacer`: the Pacer's SQLite third. D822."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import StoreError
from omniweave_core.store.pacer import PACER_TABLE, sqlite_round
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from pathlib import Path


def test_a_round_reads_back_every_key(tmp_path: Path) -> None:
    """Ruling 3: the key sum is `n(n-1)/2`, checkable with no second query."""
    assert sqlite_round(tmp_path / "a.owstore", 1000) == 1000 * 999 // 2
    assert sqlite_round(tmp_path / "b.owstore", 0) == 0


def test_the_rows_are_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "p.owstore"
    sqlite_round(path, 250)
    connection = connect(path)
    try:
        sql = f"SELECT count(*), min(k), max(k), min(length(v)) FROM {PACER_TABLE}"  # noqa: S608
        assert connection.execute(sql).fetchone() == (250, 0, 249, 32)
    finally:
        connection.close()


def test_a_second_round_over_one_file_is_refused(tmp_path: Path) -> None:
    """Ruling 4: a larger B-tree is a different measurement."""
    path = tmp_path / "p.owstore"
    sqlite_round(path, 10)
    with pytest.raises(StoreError, match="already holds a Pacer table"):
        sqlite_round(path, 10)


def test_a_negative_round_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="-1 rows"):
        sqlite_round(tmp_path / "p.owstore", -1)
