"""`SqliteDepIndex` -- the invalidation query, the TEMP delta it joins, and the cohort writer.

`omniweave_core.deps` holds the domain, the key shapes, the three population paths and the
statements; this file is what runs them. The split is `budget.py`/`store/budget.py`'s and
`work.py`/`store/queue.py`'s, one module over again: 02-architecture.md row 20 homes the vocabulary
in core and INV-17 gives `omniweave_core.store` *"the ONLY `sqlite3.connect`"*, so the object that
holds a connection lives here and satisfies the `DepIndex` Protocol structurally.

## Three statements, one `Unit`, and why that is not an optimisation

`dependents()` materialises the delta into a TEMP table and joins it, which is three statements:
clear, insert, select. They run inside **one** `Unit` -- one transaction on the store thread -- for
the reason `SqliteCacheIndex.get_many()` chunks inside one: a delta written in one transaction and
joined in another can be joined against a `dep` table that moved in between, and the answer would
be a set of work rows nobody can reproduce. Here it is worse than for a probe, because the answer
is *"re-derive these"*: a missed row is a document that stays wrong until a full rebuild, which is
exactly CG-33's 4.3%.

**The TEMP table is `IF NOT EXISTS` plus `DELETE FROM`, never `CREATE`/`DROP`** (07:1601-1603).
`StoreThread` reuses one connection for the life of the store, so a bare `CREATE TEMP TABLE` would
fail on the second call -- the same mechanism that made the rule necessary for `tmp_narrow` on a
pooled read connection, arriving here through a different door.

## The delta is bounded by the caller and the caller is `op.converge`

There is no chunking and no `IN` list: the delta goes into a table, so `SQLITE_MAX_VARIABLE_NUMBER`
is not reachable and a 100,000-key delta is one insert loop and one join rather than 111 statements.
That is the property that makes 12-performance.md:1400's budget -- *"ONE query on
`dep_reverse(kind, key)`"* -- true for a corpus-scale delta and not only a small one.

## What `dep_rows()` is for

`SqliteStore.complete()` takes a `dep_rows` `Contribution` and has had one since P2 with no
producer. `omniweave_core.deps.record_deps()` is the producer; this is the two-line adapter that
binds a computed `tuple[Dep, ...]` to the `(row_id, result_view)` signature `complete()` fixes. It
ignores its `StepResultView` for the reason `reservation_commit()` does: the deps are the runner's
observation of what it fed the driver, and reading them off a driver's result would put the subset
rule back in the driver's hands.

Specified in 02-architecture.md section 2 rows 20 and 26, 08-runtime.md section 5.6(a)
(:1812-1846), 07-store-and-retrieval.md sections 11.4 and 9.3, and `0004_runtime.sql:184-217`.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Final

from omniweave_core.deps import (
    CHANGED_CLEAR_SQL,
    CHANGED_DDL,
    CHANGED_INSERT_SQL,
    INVALIDATE_SQL,
)
from omniweave_core.errors import StoreError
from omniweave_core.store.queue import Contribution, Statement, dep_statements
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_core.deps import Change, Cohort, Dep
    from omniweave_core.store.queue import StepResultView

__all__ = [
    "COHORT_MEMBER_SQL",
    "COHORT_UPSERT_SQL",
    "SqliteDepIndex",
    "cohort_statements",
    "dep_rows",
]


COHORT_UPSERT_SQL: Final = """
INSERT INTO cohort(cohort_id, name, member_count, member_sha256, built_gen, built_ns)
     VALUES(:cohort_id, :name, :member_count, :member_sha256, :built_gen, :built_ns)
ON CONFLICT(cohort_id) DO NOTHING
"""
"""`DO NOTHING`: a cohort id IS its members, so a second build of the same set is the same row.

`cohort_id = 'coh_' || sha256_canonical(merkle)[:24]` (08:1830), so a conflict on the primary key
means the member set is byte-identical -- there is nothing an update could change except
`built_gen` and `built_ns`, and moving those would rewrite when the cohort was first known on every
run that re-observed it. `DO UPDATE` here would make the two timestamp columns mean "last seen",
which is a fact the `unit` roster already holds under a different name.
"""

COHORT_MEMBER_SQL: Final = """
INSERT OR IGNORE INTO cohort_member(cohort_id, unit_uri, unit_part, content_sha256)
     VALUES(:cohort_id, :unit_uri, :unit_part, :content_sha256)
"""
"""One row per member, conflicting on `PRIMARY KEY (cohort_id, unit_uri, unit_part)`.

Idempotency mechanism 2 of 08:428, and the warning that comes with it -- *"`INSERT OR IGNORE` with
no UNIQUE index to conflict on is a plain `INSERT`"* -- is satisfied: `cohort_member` is
`WITHOUT ROWID` on that triple, so the conflict target exists. Re-inserting a member cannot change
its `content_sha256` either, for the same reason the parent row cannot change: a different digest is
a different cohort id.
"""


def cohort_statements(
    cohort: Cohort,
    members: Sequence[tuple[str, str, str]],
    *,
    built_gen: int,
    built_ns: int,
) -> tuple[Statement, ...]:
    """The parent row and its members, in that order. The FK requires it.

    `cohort_member.cohort_id REFERENCES cohort(cohort_id)` and `foreign_keys = ON`, so the parent
    must be inserted first within the transaction; SQLite checks an immediate FK at the DML on the
    child row, not at commit.

    Members are **sorted and de-duplicated**, matching `cohort_digest()`'s own treatment of them, so
    that the rows written agree with the merkle that named them. `cohort.member_count` is asserted
    against that set rather than trusted: a parent claiming 40 members over 39 rows would make
    `ow index stats` report a cohort the store cannot reconstruct, and the cheap check is here.
    """
    rows = sorted({(uri, part, sha) for uri, part, sha in members})
    if len(rows) != cohort.member_count:
        raise StoreError(
            f"cohort {cohort.cohort_id} declares {cohort.member_count} members and "
            f"{len(rows)} distinct rows were supplied",
            fix="build the Cohort with cohort_of() over the same members you are writing",
        )
    out = [
        Statement(
            participant="derived_rows",
            name="cohort_upsert",
            sql=COHORT_UPSERT_SQL,
            params={
                "cohort_id": cohort.cohort_id,
                "name": cohort.name,
                "member_count": cohort.member_count,
                "member_sha256": cohort.member_sha256,
                "built_gen": built_gen,
                "built_ns": built_ns,
            },
        )
    ]
    out.extend(
        Statement(
            participant="derived_rows",
            name=f"cohort_member[{index}]",
            sql=COHORT_MEMBER_SQL,
            params={
                "cohort_id": cohort.cohort_id,
                "unit_uri": uri,
                "unit_part": part,
                "content_sha256": sha,
            },
        )
        for index, (uri, part, sha) in enumerate(rows)
    )
    return tuple(out)


def dep_rows(deps: Sequence[Dep], *, allowed_keys: frozenset[str] | None = None) -> Contribution:
    """A `dep_rows` `Contribution` bound to one derivation's recorded deps.

    The adapter `complete()`'s four participant slots have waited for since P2. `record_deps()`
    computed and refused; `dep_statements()` writes the SQL and refuses again at the store boundary;
    this only carries the rows across the `(row_id, result_view)` signature, because `complete()`
    still takes `(row_id, gen, result)` and nothing else (07:58, charter.md:3395).

    `allowed_keys` is forwarded rather than re-derived: 08:1839's subset rule is checked at both
    ends on purpose, and the set the runner assembled is the one thing neither end can reconstruct.
    """

    def contribute(row_id: int, _result: StepResultView) -> Sequence[Statement]:
        return dep_statements(row_id, [dep.row for dep in deps], allowed_keys=allowed_keys)

    return contribute


class SqliteDepIndex:
    """`DepIndex` over the `dep` table. One method, one transaction, one indexed join.

    Holds no delta and no answer between calls. The reverse index is the authority and it moves
    whenever a `complete()` lands, so a cached dependent set would be wrong by the time a converge
    pass read it -- the same argument `SqliteBudgetLedger` makes for headroom, and the same reason
    both recompute in SQL rather than in an attribute.
    """

    __slots__ = ("_thread", "_wait_ms")

    def __init__(self, thread: StoreThread, *, wait_ms: int = INTERACTIVE_WAIT_MS) -> None:
        self._thread = thread
        self._wait_ms = wait_ms

    def dependents(self, changes: Sequence[Change], /) -> frozenset[int]:
        """The `work.id`s whose recorded digest differs from this delta. 07:2954, 08:1817.

        Three statements in one `Unit`: clear the TEMP delta, fill it, join it. The clear runs even
        on the first call -- `CREATE TEMP TABLE IF NOT EXISTS` may have found an existing table
        holding the previous call's delta, and a stale row there would invalidate work rows nothing
        in this pass touched.

        `cost_class="free"` because ST14 derives `Unit.durable` from it and nothing here writes a
        durable row: the TEMP table is discarded with the connection, and the answer is a read.
        """
        if not changes:
            return frozenset()

        def run(connection: sqlite3.Connection) -> object:
            connection.execute(CHANGED_DDL)
            connection.execute(CHANGED_CLEAR_SQL)
            connection.executemany(
                CHANGED_INSERT_SQL,
                [(change.kind, change.key, change.new_digest) for change in changes],
            )
            return frozenset(int(row[0]) for row in connection.execute(INVALIDATE_SQL).fetchall())

        found = self._thread.run(
            Unit(name="deps.dependents", run=run, cost_class="free", wait_ms=self._wait_ms)
        )
        if not isinstance(found, frozenset):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the deps.dependents unit returned no set", fix="report this as a bug")
        return found
