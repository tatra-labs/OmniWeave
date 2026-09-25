"""`acquire.add_sources`: `ow_add`'s roster step over real files and a real store. 10:1114's (a).

Every walk is over a real directory under `tmp_path`, and every store is migrated by the shipped
migrations. `now_ns` is ten seconds past the wall clock, so a unit's stored `indexed_at_ns` is
settled past its file's `mtime` by more than `MTIME_GRANULARITY_NS` and `stat_fresh()` can hold.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the assertions read the store the add wrote.
import time
from pathlib import Path

import pytest
from omniweave_core import acquire
from omniweave_core.errors import ResourceLimit
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow


def _now() -> int:
    """Ten seconds past the wall clock, taken per call: a module-level value goes stale under
    `-n auto`, where a test can run long after collection and its files' `mtime` then falls inside
    the settling window of a "now" that is already in the past."""
    return time.time_ns() + 10_000_000_000


def _tree(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"body of {name}", encoding="utf-8")
    return root


def _rows(store: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(store)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_a_directory_is_rostered_with_its_one_scope_row(tmp_path: Path) -> None:
    """10:1114: *"`unit` rows plus one `ingest_scope` row in a single transaction"*."""
    docs = _tree(tmp_path / "docs", "a.pdf", "b.pdf", "sub/c.pdf")
    store = tmp_path / ".omniweave" / "index.owstore"
    added = acquire.add_sources(store, [docs], now_ns=_now())
    assert (added.discovered, added.skipped, added.unchanged) == (3, 0, 0)
    assert len(added.queued) == 3
    assert added.written is True
    assert _rows(store, "SELECT count(*), min(state) FROM unit") == [(3, "discovered")]
    ((scope_id, discovered, indexed, complete),) = _rows(
        store, "SELECT scope_id, discovered, indexed, complete FROM ingest_scope"
    )
    assert (discovered, indexed, complete) == (3, 3, 1)
    assert added.scopes == (scope_id,)
    assert str(scope_id).endswith("/docs/")


def test_the_first_add_creates_and_migrates_the_store(tmp_path: Path) -> None:
    """10:541-542's *"before the first `ow add`"*: the add is what makes the store."""
    store = tmp_path / "deep" / "er" / "index.owstore"
    acquire.add_sources(store, [_tree(tmp_path / "docs", "a.pdf")], now_ns=_now())
    assert store.is_file()
    assert _rows(store, "SELECT count(*) FROM unit") == [(1,)]


def test_an_acquired_unit_whose_stat_still_holds_is_unchanged(tmp_path: Path) -> None:
    docs = _tree(tmp_path / "docs", "a.pdf", "b.pdf")
    store = tmp_path / "index.owstore"
    acquire.add_sources(store, [docs], now_ns=_now())
    conn = sqlite3.connect(store)
    conn.execute("UPDATE unit SET state = 'acquired' WHERE unit_uri LIKE '%a.pdf'")
    conn.commit()
    conn.close()
    again = acquire.add_sources(store, [docs], now_ns=_now())
    assert again.unchanged == 1
    assert [uri.rsplit("/", 1)[1] for uri in again.queued] == ["b.pdf"], "never acquired"


def test_a_changed_file_is_queued_even_when_it_was_acquired(tmp_path: Path) -> None:
    docs = _tree(tmp_path / "docs", "a.pdf")
    store = tmp_path / "index.owstore"
    acquire.add_sources(store, [docs], now_ns=_now())
    conn = sqlite3.connect(store)
    conn.execute("UPDATE unit SET state = 'acquired', size = size + 1")
    conn.commit()
    conn.close()
    assert len(acquire.add_sources(store, [docs], now_ns=_now()).queued) == 1


def test_a_file_source_writes_its_unit_and_no_scope_row(tmp_path: Path) -> None:
    """D556. The parent's complete scan must survive one file being added to it: a scope row for
    the file would REPLACE the parent's with `discovered = 1`."""
    docs = _tree(tmp_path / "docs", "a.pdf", "b.pdf", "c.pdf")
    store = tmp_path / "index.owstore"
    acquire.add_sources(store, [docs], now_ns=_now())
    before = _rows(store, "SELECT * FROM ingest_scope")
    _tree(docs, "d.pdf")
    added = acquire.add_sources(store, [docs / "d.pdf"], now_ns=_now())
    assert added.scopes == ()
    assert added.discovered == 1
    assert _rows(store, "SELECT * FROM ingest_scope") == before
    assert _rows(store, "SELECT count(*) FROM unit") == [(4,)]
    assert _rows(store, "SELECT scope_rule FROM unit WHERE unit_uri LIKE '%d.pdf'") == [
        ("explicit",)
    ]


def test_a_file_name_that_looks_like_a_glob_is_matched_literally(tmp_path: Path) -> None:
    docs = _tree(tmp_path / "docs", "a[1].pdf", "a1.pdf")
    added = acquire.add_sources(tmp_path / "s.owstore", [docs / "a[1].pdf"], now_ns=_now())
    assert added.discovered == 1
    assert added.queued[0].endswith("a[1].pdf")


def test_a_dry_run_writes_nothing_not_even_the_store(tmp_path: Path) -> None:
    store = tmp_path / "index.owstore"
    added = acquire.add_sources(
        store, [_tree(tmp_path / "docs", "a.pdf")], now_ns=_now(), dry_run=True
    )
    assert added.written is False
    assert len(added.queued) == 1
    assert not store.exists()


def test_more_than_the_bound_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    """10:1127-1130: *"A breach is `RESOURCE_LIMIT` naming the knob ...; nothing is written."*"""
    store = tmp_path / "index.owstore"
    docs = _tree(tmp_path / "docs", "a.pdf", "b.pdf", "c.pdf")
    with pytest.raises(ResourceLimit) as raised:
        acquire.add_sources(store, [docs], now_ns=_now(), max_discovered=2)
    assert raised.value.limit == "ADD_MAX_DISCOVERED"
    assert not store.exists()
    assert acquire.ADD_MAX_DISCOVERED == 20_000


def test_the_bound_counts_across_every_source(tmp_path: Path) -> None:
    one = _tree(tmp_path / "one", "a.pdf", "b.pdf")
    two = _tree(tmp_path / "two", "c.pdf", "d.pdf")
    with pytest.raises(ResourceLimit):
        acquire.add_sources(tmp_path / "s.owstore", [one, two], now_ns=_now(), max_discovered=3)


def test_an_existing_store_is_written_through_its_migrations_not_recreated(
    tmp_path: Path,
) -> None:
    store = tmp_path / "index.owstore"
    conn = ow.connect(store)
    migrate.apply_pending(conn, now_ns=_now())
    conn.execute("INSERT INTO index_state(k, v) VALUES('probe', '1') ON CONFLICT DO NOTHING")
    conn.commit()
    conn.close()
    acquire.add_sources(store, [_tree(tmp_path / "docs", "a.pdf")], now_ns=_now())
    assert _rows(store, "SELECT v FROM index_state WHERE k = 'probe'") == [("1",)]


def test_every_row_ow_add_rosters_carries_the_walked_path_the_cache_salt_needs(
    tmp_path: Path,
) -> None:
    """D559. The key is written at first sight and never refreshed, so a roster writer that omits it
    leaves a unit no `op.identify` row can ever be keyed for."""
    import json  # noqa: PLC0415

    docs = _tree(tmp_path / "docs", "a.pdf", "sub/b.pdf")
    store = tmp_path / "index.owstore"
    acquire.add_sources(store, [docs, _tree(tmp_path / "loose", "c.pdf") / "c.pdf"], now_ns=_now())
    for (derived,) in _rows(store, "SELECT derived FROM unit"):
        walked = json.loads(str(derived))[acquire.WALKED_PATH_KEY]
        assert walked.startswith(str(tmp_path).replace("\\", "/"))


def test_an_add_waits_for_the_store_write_lock_and_names_its_holder(tmp_path: Path) -> None:
    """02:757-758: *"`ow_add` takes `store.write` at `interactive_wait_ms = 2000`"*. It took
    none."""
    from omniweave_core.errors import StoreBusy  # noqa: PLC0415
    from omniweave_core.locks import store_write_lock  # noqa: PLC0415

    store = tmp_path / "index.owstore"
    acquire.add_sources(store, [_tree(tmp_path / "docs", "a.pdf")], now_ns=_now())
    held = store_write_lock(store, now_ns=time.time_ns)
    held.acquire(wait_ms=0)
    try:
        with pytest.raises(StoreBusy) as busy:
            acquire.add_sources(store, [_tree(tmp_path / "more", "b.pdf")], now_ns=_now())
    finally:
        held.release()
    assert busy.value.EXIT == 7
    assert _rows(store, "SELECT count(*) FROM unit") == [(1,)]
