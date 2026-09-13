"""`SqliteCacheIndex` -- the cache statements submitted on the store thread.

`omniweave_core.cache` holds the key recipe, the read policy, the namespaces and the statements;
this file runs them. The split is `work.py`/`store/queue.py`'s and `budget.py`/`store/budget.py`'s,
for the third time and the same reason: INV-17 gives `omniweave_core.store` *"the ONLY
`sqlite3.connect`"*, so the object that holds a connection lives here and satisfies the Protocol
structurally.

## The clock is injected, never read

`cache_index` carries three timestamps -- `created_ns`, `last_hit_ns` and the `:now_ns` both sweeps
compare against -- and not one of them comes from `time`. `Clock` is a constructor argument, which
is 08:295's third ban (*"no ambient clock"*) applied to the module that would otherwise be the
easiest place to break it: a GC that read the wall clock directly would be untestable without
waiting seven days.

## Who writes `last_hit_ns`, and why it is a method rather than a side effect (D146)

Both sweeps order on `last_hit_ns`, and the size sweep is an **LRU** over it. Nothing in the plan
says who advances it: `08:1307` says a hit *"replays the Spend and re-prices it"*,
`0004_runtime.sql` declares the column and the `hits` counter beside it, and no clause anywhere
writes either.

Left unwritten, `last_hit_ns == created_ns` forever and the LRU degrades to a FIFO -- which evicts
the oldest **entry** rather than the least recently **used** one, and on a corpus re-ingested
monthly that is precisely backwards: the memo that has served every run since January is the first
one deleted. `touch()` is therefore a fifth method on the boundary, called by the runner **after**
the read policy returns `HIT` or `HIT_LEGACY` and never on a miss -- because counting a
`miss_corrupt` as a hit would keep a broken entry alive by rewarding it for being read.

Specified in 02-architecture.md section 2 rows 18 and 26, 08-runtime.md Part 4 (:1439-1540) and
`0004_runtime.sql:155-183`.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Final

from omniweave_core.cache import (
    AGE_SWEEP_SQL,
    CACHE_INDEX_COLUMNS,
    MAX_BYTES_UNBOUNDED,
    NEVER_SWEEP_DAYS,
    SIZE_SWEEP_SQL,
    UPSERT_SQL,
    CacheEntry,
    CacheLayer,
    chunked,
    reject_unallowed,
)
from omniweave_core.errors import StoreError
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "GC_COST_CLASS_DAYS",
    "SELECT_SQL",
    "STAT_SQL",
    "TOUCH_SQL",
    "SqliteCacheIndex",
    "select_many_sql",
]

_COLUMNS: Final = ", ".join(CACHE_INDEX_COLUMNS)
SELECT_SQL: Final = (
    f"SELECT {_COLUMNS} FROM cache_index WHERE cache_key = :k"  # noqa: S608 -- a constant
    # column list from this module, and the key is bound. The same allowance
    # `test_store_queue.py` takes over `WORK_COLUMNS`, for the same reason: a projection built
    # from the column tuple cannot drift from the tuple the row is read back through.
)
"""The eighteen columns by name, in the DDL's order. Built from `CACHE_INDEX_COLUMNS` so the
projection and the row-to-`CacheEntry` mapping cannot disagree about position."""


def select_many_sql(count: int) -> str:
    """`SELECT ... WHERE cache_key IN (?, ?, ...)` for exactly `count` keys. **08:1791.**

    *"One indexed query per Batch, not one per unit: `WHERE cache_key IN (...)` against
    `cache_index`'s primary key. At `batch = 256` that is one statement instead of 256, and the
    `IN` list is chunked at 900 to stay under SQLite's `SQLITE_MAX_VARIABLE_NUMBER` floor."*

    **The placeholders are generated and the keys are still bound.** A key is a 64-character hex
    digest this process computed, so interpolating them would be safe and would also be the habit
    that is unsafe the next time; what is interpolated is the *count* of `?`s, which is an integer
    from `len()`. `cache_key` is the table's `PRIMARY KEY`, so the `IN` is an index scan over at
    most 900 rowids and never a table scan.

    Positional `?` rather than the named `:k` `SELECT_SQL` uses, because a named parameter per key
    would need a generated name per key and a dict to match -- more machinery for the same bound
    values, and `sqlite3` accepts a sequence directly.
    """
    if count < 1:
        raise ValueError("select_many_sql is asked for at least one key")
    holes = ", ".join("?" * count)
    return f"SELECT {_COLUMNS} FROM cache_index WHERE cache_key IN ({holes})"  # noqa: S608


TOUCH_SQL: Final = """
UPDATE cache_index SET last_hit_ns = :now_ns, hits = hits + 1 WHERE cache_key = :k
"""
"""**D146.** The LRU's only writer, called after the read policy returns a hit and never before."""

STAT_SQL: Final = """
SELECT layer, COUNT(*), COALESCE(SUM(bytes), 0) FROM cache_index GROUP BY layer
"""
"""What `ow cache stat` prints per layer, beside `cache.GROWTH_BOUND_WORDS` and the free-disk
figure -- 08:1523 wants the `call` layer's size next to the headroom *"so the operator sees it
coming"*, since that layer's bound is `0` and the disk refusal is its only limit."""

GC_COST_CLASS_DAYS: Final[Mapping[str, str]] = {
    "free": "free_after_days",
    "local_compute": "local_after_days",
    "billed_api": "billed_after_days",
}
"""Which `[cache] gc` key governs which `cost_class`. Three classes, three keys, one mapping.

`billed_after_days` is in the table and its shipped value is `0`, which means **never** -- so the
age sweep skips the class entirely rather than deleting everything. A mapping that omitted the
billed row would have made "never" an absence, and an absence is what a later edit fills in.
"""


class SqliteCacheIndex:
    """`CacheIndex`'s five methods over one `StoreThread`. Structural: no inheritance edge.

    Satisfies `omniweave_core.cache.CacheIndex`, which is a `Protocol` with `runtime_checkable`
    deliberately off, the same arrangement `Store`/`SqliteStore` and `BudgetLedger`/
    `SqliteBudgetLedger` have.

    **It is not the record of completion.** 02-architecture.md row 18's exclusion column says so
    and this class holds no method that could answer "has this unit been done": that is
    `work.status='done'` plus a matching `work.cache_key`, three facts the `work` table owns.
    """

    __slots__ = ("_clock", "_thread", "_wait_ms")

    def __init__(
        self, thread: StoreThread, *, clock: Clock, wait_ms: int = INTERACTIVE_WAIT_MS
    ) -> None:
        self._thread = thread
        self._clock = clock
        self._wait_ms = wait_ms

    # -- read ----------------------------------------------------------------------------------

    def get(self, key: str) -> CacheEntry | None:
        """The row, or `None`. **The lookup, never the policy.**

        08:1439 is the sentence this method is written against: *"'Cache hit' is a **policy**, not a
        lookup."* Returning the row and letting `cache.read_verdict()` judge it is what keeps the
        six clauses in one place and out of every caller -- and what lets clause 2 (the blob does
        not parse) and clause 4 (the artefact is empty) be decided by the layers that can actually
        answer them, which are the blob store and the Operator.
        """

        def run(connection: sqlite3.Connection) -> object:
            row = connection.execute(SELECT_SQL, {"k": key}).fetchone()
            return None if row is None else _entry(row)

        found = self._thread.run(
            Unit(name="cache.get", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if found is not None and not isinstance(found, CacheEntry):  # pragma: no cover
            raise StoreError("the cache.get unit returned no entry", fix="report this as a bug")
        return found

    def get_many(self, keys: Sequence[str]) -> Mapping[str, CacheEntry]:
        """Every row among `keys` that exists, by key. **The sixth call, and 08:1791 needs it.**

        `02-architecture.md` row 18's boundary cell reads `CacheIndex.get/put`, and a probe built
        over `get` alone issues one statement per unit -- which is exactly what `08:1789` says the
        caller never does: *"the caller never issues N lookups"*. So the boundary grows one read,
        and it is a read rather than a policy: what comes back is rows, and `read_verdict()` still
        judges them. Recorded as **D170**.

        Chunked at `cache.IN_CHUNK` inside one `Unit`, so a 5,000-key probe is six statements in
        **one** transaction rather than six transactions. That matters for more than lock traffic:
        two chunks read in two transactions could see two different states of the index, and a
        probe that reported a hit for one half of a batch and a miss for the other after a
        concurrent sweep would be a batch nobody can reproduce.

        A key that has no row is simply absent from the mapping, which is clause 1's `None` in
        batch form -- `probe()` reads `.get(key)` and `read_verdict(None, ...)` returns `MISS`.
        """
        wanted = tuple(dict.fromkeys(keys))
        if not wanted:
            return {}

        def run(connection: sqlite3.Connection) -> object:
            found: dict[str, CacheEntry] = {}
            for chunk in chunked(wanted):
                for row in connection.execute(select_many_sql(len(chunk)), chunk).fetchall():
                    entry = _entry(row)
                    found[entry.cache_key] = entry
            return found

        rows = self._thread.run(
            Unit(name="cache.get_many", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(rows, dict):  # pragma: no cover -- the closure returns a dict or raises.
            raise StoreError("the cache.get_many unit returned no mapping", fix="report this bug")
        return rows

    def touch(self, key: str) -> bool:
        """Advance `last_hit_ns` and increment `hits`. **D146**; the LRU has no other writer.

        Called by the runner after `read_verdict()` returns `HIT` or `HIT_LEGACY`, and never on a
        miss: counting a `miss_corrupt` as a hit would keep a broken entry alive by rewarding it for
        having been read, and clause 2's self-heal overwrites it on the next success anyway.
        """
        return self._update(
            TOUCH_SQL, {"k": key, "now_ns": self._clock.wall_ns()}, name="cache.touch"
        )

    # -- write ---------------------------------------------------------------------------------

    def put(
        self, entries: Sequence[CacheEntry], *, allowed_units: frozenset[tuple[str, str]]
    ) -> int:
        """Write the allowed entries; return how many were written. 08:1465.

        **The allowlist is checked before anything is written, and a reject does not stop the
        rest.** 08:1469 says an offending entry is *"rejected and recorded"*, so a single poisoned
        entry must not discard a Batch's worth of legitimate ones -- and the returned count is how
        the caller learns: `len(entries) - written` is the number refused. A caller that wants to
        *record* them, which 08:1469 also asks for, calls `cache.reject_unallowed()` first and gets
        the entries themselves; that is why the pure half returns the rejects rather than a
        boolean, and why it lives in `omniweave_core.cache` rather than here.

        One transaction for the batch, and an upsert per entry: clauses 2 and 4 of the read policy
        both require an overwrite -- a corrupt or empty entry is *"overwritten on the next
        success"*, self-healing with no flag -- and `INSERT OR IGNORE` would leave the corruption in
        place forever, which is graphify's behaviour before #2405.

        Ordering against CAS is the caller's and 08:1480 fixes it: the blob is written and fsynced
        **before** this row, so a crash leaves an unreferenced blob -- swept by mark-and-sweep --
        rather than an index row pointing at nothing.
        """
        rejected = frozenset(id(entry) for entry in reject_unallowed(entries, allowed_units))
        rows = tuple(entry for entry in entries if id(entry) not in rejected)
        now_ns = self._clock.wall_ns()

        def run(connection: sqlite3.Connection) -> object:
            for entry in rows:
                connection.execute(UPSERT_SQL, _params(entry, now_ns))
            return len(rows)

        # ST14: `Unit.durable` is derived from `cost_class`, and a batch holding one billed
        # response is written under `synchronous = FULL`. A cache entry for a call an operator
        # paid for is exactly the row that must survive a power cut; a free memo is not.
        durable = any(entry.cost_class == "billed_api" for entry in rows)
        written = self._thread.run(
            Unit(
                name="cache.put",
                run=run,
                cost_class="billed_api" if durable else "free",
                wait_ms=self._wait_ms,
            )
        )
        if not isinstance(written, int):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError("the cache.put unit returned no count", fix="report this as a bug")
        return written

    # -- sweep ---------------------------------------------------------------------------------

    def sweep(
        self, *, now_ns: int, gc_days: Mapping[str, int], max_bytes: Mapping[str, int]
    ) -> int:
        """The age sweep, then the size sweep. Returns the rows deleted by both.

        **Both, and in that order**, because 08:1505 says the draft-obvious mistake is to ship only
        the first: *"age alone does not bound anything -- at 10.7 MB per rendered page, one
        2,000-page ingest puts 21 GB in the `render` layer inside its `local_after_days = 90`
        window and blows straight past `render = 20 GiB`."* Age first so the size sweep has less to
        do, and so an entry that is both stale and over the bound is counted once.

        A `cost_class` whose `*_after_days` is `NEVER_SWEEP_DAYS` is skipped, and a layer whose
        `max_bytes` is `MAX_BYTES_UNBOUNDED` is skipped: `0` means never and unbounded
        respectively, and both are decisions rather than omissions.

        One transaction for all of it, on the store thread inside the `store.write` lock like every
        other write. Both statements exclude keys referenced by a live `work` row, so *"a
        concurrently-claimed unit's memo is never swept out from under it"*.
        """
        plans: list[tuple[str, dict[str, object]]] = []
        for cost_class, key in GC_COST_CLASS_DAYS.items():
            days = gc_days.get(key, NEVER_SWEEP_DAYS)
            if days == NEVER_SWEEP_DAYS:
                continue
            if days < 0:
                raise StoreError(
                    f"[cache] gc.{key} is {days}; 0 means never and there is no negative age",
                    fix=f"set [cache] gc.{key} to 0 (never) or a positive number of days",
                )
            plans.append(
                (AGE_SWEEP_SQL, {"cost_class": cost_class, "now_ns": now_ns, "after_days": days})
            )
        for layer in CacheLayer:
            bound = max_bytes.get(layer.value, MAX_BYTES_UNBOUNDED)
            if bound == MAX_BYTES_UNBOUNDED:
                continue
            if bound < 0:
                raise StoreError(
                    f"[cache.max_bytes] {layer.value} is {bound}; 0 means unbounded",
                    fix=f"set [cache.max_bytes] {layer.value} to 0 or a positive byte count",
                )
            plans.append((SIZE_SWEEP_SQL, {"layer": layer.value, "bound": bound}))

        def run(connection: sqlite3.Connection) -> object:
            # `Connection.total_changes` rather than `Cursor.rowcount`: SQLite reports `-1` for a
            # `DELETE` fed by a CTE, which the size sweep is, so summing `rowcount` would report
            # a negative sweep. `total_changes` is the connection's own counter and is exact for
            # both statements.
            before = connection.total_changes
            for sql, params in plans:
                connection.execute(sql, params)
            return connection.total_changes - before

        swept = self._thread.run(
            Unit(name="cache.sweep", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(swept, int):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError("the cache.sweep unit returned no count", fix="report this as a bug")
        return swept

    def stat(self) -> Mapping[str, tuple[int, int]]:
        """`layer -> (rows, bytes)`, for every layer including the empty ones.

        Every layer, so `ow cache stat`'s output has a fixed shape: an operator comparing two runs
        should not have to notice that a line is missing to learn that a layer is empty.
        """

        def run(connection: sqlite3.Connection) -> object:
            found = {
                str(layer): (int(rows), int(size))
                for layer, rows, size in connection.execute(STAT_SQL)
            }
            return {layer.value: found.get(layer.value, (0, 0)) for layer in CacheLayer}

        counted = self._thread.run(
            Unit(name="cache.stat", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(counted, dict):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError("the cache.stat unit returned no mapping", fix="report this as a bug")
        return counted

    # -- one shared update ---------------------------------------------------------------------

    def _update(self, sql: str, params: Mapping[str, object], *, name: str) -> bool:
        def run(connection: sqlite3.Connection) -> object:
            return connection.execute(sql, dict(params)).rowcount == 1

        moved = self._thread.run(Unit(name=name, run=run, cost_class="free", wait_ms=self._wait_ms))
        if not isinstance(moved, bool):  # pragma: no cover -- `Unit.run` is typed `-> object`.
            raise StoreError(f"the {name} unit returned no boolean", fix="report this as a bug")
        return moved


def _params(entry: CacheEntry, now_ns: int) -> dict[str, object]:
    """`UPSERT_SQL`'s named binds. `partial` is INTEGER and `bool` is an `int` subclass."""
    return {
        "cache_key": entry.cache_key,
        "recipe": entry.recipe,
        "layer": entry.layer.value,
        "cost_class": entry.cost_class,
        "ref": entry.ref,
        "bytes": entry.bytes,
        "unit_uri": entry.unit_uri,
        "unit_part": entry.unit_part,
        "driver": entry.driver,
        "driver_schema_v": entry.driver_schema_v,
        "config_digest": entry.config_digest,
        "origin_operator": entry.origin_operator,
        "spend_json": entry.spend_json,
        "micros": entry.micros,
        "partial": int(entry.partial),
        "now_ns": now_ns,
        "hits": entry.hits,
    }


def _entry(row: Sequence[object]) -> CacheEntry:
    """One `cache_index` row as a `CacheEntry`, by name rather than by position.

    `created_ns` and `last_hit_ns` are read and dropped: a `CacheEntry` is what a caller **writes**,
    and the two timestamps are the index's own -- `created_ns` is set once by the upsert and
    `last_hit_ns` only by `touch()`. Carrying them on the value type would invite a caller to set
    them, which is the ambient clock reaching the store through a dataclass.
    """
    if len(row) != len(CACHE_INDEX_COLUMNS):
        raise StoreError(
            f"cache_index returned {len(row)} columns and this projection names "
            f"{len(CACHE_INDEX_COLUMNS)}",
            fix="report this as a bug in omniweave_core.store.cache",
        )
    values = dict(zip(CACHE_INDEX_COLUMNS, row, strict=True))
    return CacheEntry(
        cache_key=str(values["cache_key"]),
        recipe=int(values["recipe"]),  # type: ignore[arg-type]
        layer=CacheLayer(str(values["layer"])),
        cost_class=str(values["cost_class"]),
        ref=str(values["ref"]),
        bytes=int(values["bytes"]),  # type: ignore[arg-type]
        unit_uri=str(values["unit_uri"]),
        unit_part=str(values["unit_part"]),
        driver=str(values["driver"]),
        driver_schema_v=int(values["driver_schema_v"]),  # type: ignore[arg-type]
        config_digest=str(values["config_digest"]),
        origin_operator=str(values["origin_operator"]),
        spend_json=str(values["spend_json"]),
        micros=int(values["micros"]),  # type: ignore[arg-type]
        partial=bool(values["partial"]),
        hits=int(values["hits"]),  # type: ignore[arg-type]
    )
