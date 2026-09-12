"""`SqliteCacheIndex` against a real `.owstore`: the upsert, the touch, and both sweeps.

The sweeps are the half that cannot be tested any other way. 08:1507 says age alone bounds nothing
and 08:1536 says a concurrently-claimed unit's memo is never swept out from under it; both are
properties of two SQL statements running against rows, and a fake would only re-state them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from omniweave_core.cache import (
    GC_DEFAULT_DAYS,
    MAX_BYTES_UNBOUNDED,
    NEVER_SWEEP_DAYS,
    CacheEntry,
    CacheLayer,
)
from omniweave_core.errors import StoreError
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.cache import SqliteCacheIndex

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NOW_NS = 1_757_400_000_000_000_000
DAY_NS = 86_400_000_000_000
URI = "file:///corpus/a.pdf"


class FakeClock:
    """`Clock`, with a settable wall reading. The store's timestamps are all injected."""

    def __init__(self, wall: int = NOW_NS) -> None:
        self.wall = wall

    def monotonic_ns(self) -> int:  # pragma: no cover -- the cache reads wall time only.
        return 0

    def wall_ns(self) -> int:
        return self.wall


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 4
    finally:
        connection.close()
    return path


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def index(owstore: Path, clock: FakeClock) -> Iterator[SqliteCacheIndex]:
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield SqliteCacheIndex(thread, clock=clock)
    finally:
        thread.close()


def entry(
    key: str = "a" * 64,
    *,
    layer: CacheLayer = CacheLayer.CALL,
    cost_class: str = "billed_api",
    part: str = "p3",
    size: int = 10,
    **over: object,
) -> CacheEntry:
    fields: dict[str, object] = {
        "cache_key": key,
        "layer": layer,
        "cost_class": cost_class,
        "ref": f"cas://ab/cd/{key[:8]}",
        "bytes": size,
        "unit_uri": URI,
        "unit_part": part,
        "driver": "parse.page.olmocr",
        "driver_schema_v": 7,
        "config_digest": "cd",
        "origin_operator": "parse.pdf",
        "spend_json": '{"gpu_ms":2400}',
        "micros": 853,
    }
    fields.update(over)
    return CacheEntry(**fields)  # type: ignore[arg-type]


ALLOWED = frozenset({(URI, "p3")})


def rows(path: Path) -> dict[str, tuple[int, int, int]]:
    """`cache_key -> (created_ns, last_hit_ns, hits)`, read outside the index under test."""
    connection = ow.connect(path)
    try:
        return {
            str(k): (int(created), int(hit), int(count))
            for k, created, hit, count in connection.execute(
                "SELECT cache_key, created_ns, last_hit_ns, hits FROM cache_index"
            )
        }
    finally:
        connection.close()


def seed_work(path: Path, cache_key: str, status: str) -> None:
    """One `work` row holding `cache_key`, which is what both sweeps refuse to sweep past."""
    connection = ow.connect(path)
    try:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO unit(unit_uri, state, trust_class, last_seen_gen)"
                " VALUES(:uri, 'planned', 'internal', 1)",
                {"uri": URI},
            )
            connection.execute(
                "INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key,"
                " cost_class, status)"
                " VALUES(:uri, :part, 'op.identify', 1, :key, 'free', :status)",
                {"uri": URI, "part": cache_key[:4], "key": cache_key, "status": status},
            )
    finally:
        connection.close()


def age(path: Path, cache_key: str, days: int, *, now_ns: int = NOW_NS) -> None:
    """Backdate one row's `last_hit_ns`, which is what the age sweep compares."""
    connection = ow.connect(path)
    try:
        with connection:
            connection.execute(
                "UPDATE cache_index SET last_hit_ns = :t WHERE cache_key = :k",
                {"t": now_ns - days * DAY_NS, "k": cache_key},
            )
    finally:
        connection.close()


# ---------------------------------------------------------------------------------------------
# 1. Put and get
# ---------------------------------------------------------------------------------------------


def test_an_entry_round_trips_through_the_index(index: SqliteCacheIndex) -> None:
    """Eighteen columns out and back, by name rather than by position."""
    written = index.put([entry()], allowed_units=ALLOWED)
    assert written == 1

    found = index.get("a" * 64)
    assert found == entry()
    assert index.get("b" * 64) is None


def test_a_write_naming_a_unit_outside_the_batch_is_refused_and_the_rest_proceed(
    index: SqliteCacheIndex,
) -> None:
    """I13, structural. 08:1469: an offending entry is *"rejected and recorded"*, not fatal.

    The threat graphify names (#1757): *"a model must not be able to replace that file's complete
    cache entry unless the file was part of the current extraction batch."* The second half of the
    mechanism is that `DriverIO` carries no cache handle at all, so a driver cannot write here
    even incorrectly.
    """
    mine = entry()
    theirs = entry("b" * 64, part="p9")

    assert index.put([mine, theirs], allowed_units=ALLOWED) == 1
    assert index.get("a" * 64) is not None
    assert index.get("b" * 64) is None, "a poisoned entry reaches no row"


def test_a_corrupt_entry_is_overwritten_on_the_next_success(
    index: SqliteCacheIndex, owstore: Path, clock: FakeClock
) -> None:
    """Read-policy clauses 2 and 4: *"overwritten on the next success"*, with no flag.

    graphify re-billed a corrupt entry every run until #2405 counted it. An `INSERT OR IGNORE`
    would have reproduced that exactly.
    """
    index.put([entry(size=10, micros=853)], allowed_units=ALLOWED)
    before = rows(owstore)["a" * 64]

    clock.wall = NOW_NS + DAY_NS
    index.put([entry(size=4_096, micros=999)], allowed_units=ALLOWED)

    healed = index.get("a" * 64)
    assert healed is not None
    assert (healed.bytes, healed.micros) == (4_096, 999)

    after = rows(owstore)["a" * 64]
    assert after[0] == before[0], "created_ns survives an overwrite; the GC sweeps on age"
    assert after[1] == NOW_NS + DAY_NS
    assert after[2] == before[2], "a self-heal does not reset a popular entry's history"


def test_the_clock_is_injected_and_nothing_reads_the_wall(
    index: SqliteCacheIndex, owstore: Path, clock: FakeClock
) -> None:
    """08:295's third ban, at the module that would otherwise be the easiest place to break it."""
    clock.wall = 42
    index.put([entry()], allowed_units=ALLOWED)
    assert rows(owstore)["a" * 64][:2] == (42, 42)


# ---------------------------------------------------------------------------------------------
# 2. Touch -- D146
# ---------------------------------------------------------------------------------------------


def test_touch_advances_the_lru_and_counts_the_hit(
    index: SqliteCacheIndex, owstore: Path, clock: FakeClock
) -> None:
    """**D146**: the LRU has no other writer, and unwritten it degrades to a FIFO."""
    index.put([entry()], allowed_units=ALLOWED)
    clock.wall = NOW_NS + 5 * DAY_NS

    assert index.touch("a" * 64) is True
    created, last_hit, hits = rows(owstore)["a" * 64]
    assert created == NOW_NS
    assert last_hit == NOW_NS + 5 * DAY_NS
    assert hits == 1

    assert index.touch("z" * 64) is False, "nothing to advance is not an error"


def test_an_untouched_entry_keeps_its_creation_time_as_its_last_hit(
    index: SqliteCacheIndex, owstore: Path
) -> None:
    """Which is what makes the missing writer a silent bug rather than a crash: the size sweep's
    LRU still runs, and evicts the oldest **entry** rather than the least recently **used** one."""
    index.put([entry()], allowed_units=ALLOWED)
    created, last_hit, hits = rows(owstore)["a" * 64]
    assert created == last_hit
    assert hits == 0


# ---------------------------------------------------------------------------------------------
# 3. The age sweep
# ---------------------------------------------------------------------------------------------


def test_the_age_sweep_deletes_past_the_window_and_keeps_what_is_inside_it(
    index: SqliteCacheIndex, owstore: Path
) -> None:
    """`free_after_days = 7`. One query per cost class, and the window is `last_hit_ns`'s."""
    index.put(
        [entry("a" * 64, cost_class="free"), entry("b" * 64, cost_class="free")],
        allowed_units=ALLOWED,
    )
    age(owstore, "a" * 64, days=8)
    age(owstore, "b" * 64, days=6)

    assert index.sweep(now_ns=NOW_NS, gc_days=GC_DEFAULT_DAYS, max_bytes={}) == 1
    assert index.get("a" * 64) is None
    assert index.get("b" * 64) is not None


def test_a_billed_entry_is_never_swept_on_a_timer(index: SqliteCacheIndex, owstore: Path) -> None:
    """`billed_after_days = 0` means **never**. 08:1502, and `0` is the whole statement of it.

    Read as "immediately", the shipped default would delete every billed response on the first
    sweep -- the single most expensive misreading available in this file.
    """
    assert GC_DEFAULT_DAYS["billed_after_days"] == NEVER_SWEEP_DAYS
    index.put([entry(cost_class="billed_api")], allowed_units=ALLOWED)
    age(owstore, "a" * 64, days=4_000)

    assert index.sweep(now_ns=NOW_NS, gc_days=GC_DEFAULT_DAYS, max_bytes={}) == 0
    assert index.get("a" * 64) is not None


def test_a_live_work_rows_memo_is_never_swept(index: SqliteCacheIndex, owstore: Path) -> None:
    """08:1536's concurrency answer, carried by the statement rather than by a lock.

    A `pending` or `claimed` row's key is excluded, so a unit claimed while the sweep runs keeps
    the memo it is about to read. A `done` row's is not, which is what makes the sweep able to
    collect anything at all.
    """
    index.put(
        [entry("a" * 64, cost_class="free"), entry("b" * 64, cost_class="free")],
        allowed_units=ALLOWED,
    )
    age(owstore, "a" * 64, days=30)
    age(owstore, "b" * 64, days=30)
    seed_work(owstore, "a" * 64, status="claimed")
    seed_work(owstore, "b" * 64, status="done")

    assert index.sweep(now_ns=NOW_NS, gc_days=GC_DEFAULT_DAYS, max_bytes={}) == 1
    assert index.get("a" * 64) is not None
    assert index.get("b" * 64) is None


def test_a_negative_age_is_refused_rather_than_silently_sweeping_the_future(
    index: SqliteCacheIndex,
) -> None:
    """`0` already means never, so a negative number is a typo with nothing to fall back on."""
    with pytest.raises(StoreError, match="no negative age"):
        index.sweep(now_ns=NOW_NS, gc_days={"free_after_days": -1}, max_bytes={})


# ---------------------------------------------------------------------------------------------
# 4. The size sweep -- what actually enforces the bound
# ---------------------------------------------------------------------------------------------


def test_the_size_sweep_keeps_the_most_recently_used_and_drops_the_rest(
    index: SqliteCacheIndex, owstore: Path
) -> None:
    """08:1505: *"age alone does not bound anything"*. LRU by `last_hit_ns`, newest kept.

    Three 10-byte render entries under a 25-byte bound: the two most recently touched survive and
    the oldest goes, which is the behaviour `touch()` exists to make meaningful.
    """
    index.put(
        [
            entry("a" * 64, layer=CacheLayer.RENDER, cost_class="local_compute"),
            entry("b" * 64, layer=CacheLayer.RENDER, cost_class="local_compute"),
            entry("c" * 64, layer=CacheLayer.RENDER, cost_class="local_compute"),
        ],
        allowed_units=ALLOWED,
    )
    age(owstore, "a" * 64, days=3)
    age(owstore, "b" * 64, days=2)
    age(owstore, "c" * 64, days=1)

    swept = index.sweep(now_ns=NOW_NS, gc_days={}, max_bytes={"render": 25})
    assert swept == 1
    assert index.get("a" * 64) is None
    assert index.get("b" * 64) is not None
    assert index.get("c" * 64) is not None


def test_an_automatic_sweep_never_re_bills(index: SqliteCacheIndex) -> None:
    """I27, in the statement as well as in the partial index: `cost_class <> 'billed_api'`.

    Deleting a billed entry needs `ow cache prune --allow-rebill`, which prints the row count and
    the `would_have_been_micros` it is about to discard. `--ignore-cache` is **struck**.
    """
    index.put(
        [
            entry("a" * 64, layer=CacheLayer.CALL, cost_class="billed_api", size=1_000),
            entry("b" * 64, layer=CacheLayer.CALL, cost_class="local_compute", size=1_000),
        ],
        allowed_units=ALLOWED,
    )
    assert index.sweep(now_ns=NOW_NS, gc_days={}, max_bytes={"call": 1}) == 1
    assert index.get("a" * 64) is not None, "a billed entry is invisible to an automatic sweep"
    assert index.get("b" * 64) is None


def test_an_unbounded_layer_is_skipped_entirely(index: SqliteCacheIndex) -> None:
    """`[cache.max_bytes] call = 0` is unbounded, *"the decision, not an oversight"* (08:1521).

    Those are the two layers where a miss costs money, so their only bound is the disk-headroom
    refusal that `blobs.py` already carries.
    """
    index.put([entry(cost_class="local_compute", size=1 << 30)], allowed_units=ALLOWED)
    assert index.sweep(now_ns=NOW_NS, gc_days={}, max_bytes={"call": MAX_BYTES_UNBOUNDED}) == 0
    assert index.get("a" * 64) is not None


def test_a_negative_bound_is_refused(index: SqliteCacheIndex) -> None:
    """`0` already means unbounded, so a negative bound has no reading left."""
    with pytest.raises(StoreError, match="0 means unbounded"):
        index.sweep(now_ns=NOW_NS, gc_days={}, max_bytes={"render": -1})


def test_both_sweeps_run_and_age_goes_first(index: SqliteCacheIndex, owstore: Path) -> None:
    """Age first so the size sweep has less to do, and so a doubly-eligible row is counted once."""
    index.put(
        [
            entry("a" * 64, layer=CacheLayer.SIGNAL, cost_class="free", size=100),
            entry("b" * 64, layer=CacheLayer.SIGNAL, cost_class="free", size=100),
        ],
        allowed_units=ALLOWED,
    )
    age(owstore, "a" * 64, days=30)

    swept = index.sweep(now_ns=NOW_NS, gc_days=GC_DEFAULT_DAYS, max_bytes={"signal": 150})
    assert swept == 1, "the aged row is deleted once, not once per sweep"
    assert index.get("a" * 64) is None
    assert index.get("b" * 64) is not None


# ---------------------------------------------------------------------------------------------
# 5. Stat
# ---------------------------------------------------------------------------------------------


def test_stat_reports_every_layer_including_the_empty_ones(index: SqliteCacheIndex) -> None:
    """A fixed shape, so an operator comparing two runs need not notice a missing line."""
    index.put(
        [
            entry("a" * 64, layer=CacheLayer.CALL, size=10),
            entry("b" * 64, layer=CacheLayer.CALL, size=32),
            entry("c" * 64, layer=CacheLayer.RENDER, size=1_000),
        ],
        allowed_units=ALLOWED,
    )
    stat = index.stat()

    assert set(stat) == {member.value for member in CacheLayer}
    assert stat["call"] == (2, 42)
    assert stat["render"] == (1, 1_000)
    assert stat["embed"] == (0, 0)
