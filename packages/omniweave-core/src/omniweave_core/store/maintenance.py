"""The four maintenance operations, `ow store` compact/backup/repair, and bulk windows.

Implements 07-store-and-retrieval.md section 2.2 (:201-229), which is the whole of this module's
law and prints, for each of four operations, its **statement**, its **bound** and why it is not
optional; plus section 10.6 (:2847-2866), which fixes what a bulk window may and may not drop.
07:3369 is the roadmap row that owes it: *"The charter sets `auto_vacuum = INCREMENTAL` with
nothing that vacuums, ships FTS5 with nothing that merges, and names `ow store repair` without
defining it."*

**Every function here takes the `sqlite3.Connection` and returns what it did.** Nothing in this
module connects, opens, schedules or threads. 07:203-205 draws that line in as many words -- "in
the runtime's maintenance window ([the runtime](08-runtime.md) owns the window; the operations,
their statements and their bounds are this document's)" -- so *when* is 08's and *what* is here.
The WAL fold, the fourth operation, is `walvalve.fold_now`: it is the one of the four that needs a
governor's state across calls, so it lives with the valve whose constants bound it (07:212 sends it
to section 10.5) and reaches this module only as the `fold` callable `maintenance_window` invokes.

## The three traps section 2.2 states, and how each is made structural

1. **`PRAGMA optimize` runs off-thread with a STRICTLY SMALLER inline fallback, never the same list
   run inline** (07:209, quoting codegraph `index.ts:677-712`: *"these pragmas are minutes of
   synchronous IO (a 95k-file kernel index)"*). `OPTIMIZE_OFFTHREAD` and `OPTIMIZE_INLINE` are both
   `OptimizePlan`s, and the inline one is not a second literal: it is **constructed by narrowing the
   off-thread one**, and `OptimizePlan.narrowed()` raises unless the result is a proper subset. So
   the relationship the plan requires cannot be broken by editing a number -- the constructor
   refuses. `test_store_maintenance.py` asserts the subset property itself rather than the two
   values.

   "List" is read as SQLite's own word for the argument of `PRAGMA optimize`: *a bitmask of
   optimizations*. `optimizations` is therefore a `frozenset` of mask bits, and "strictly smaller"
   is proper set inclusion -- an assertion that holds for every input, unlike a comparison of two
   integers. The inline plan additionally carries a smaller `analysis_limit`, which is the other
   reading of the same sentence ("`analysis_limit` is the bound"); both readings are satisfied at
   once and neither is guessed away. See DEFECT 1 below.

2. **FTS5 `'optimize'` is O(index) and runs ONLY inside `ow store compact`** (07:214-216) -- "never
   in the maintenance window and never on an interactive path". Two independent enforcers, because
   a convention is not an enforcer:

   * `_fts_command()` **refuses** `FTS_OPTIMIZE` outright. Every window-path FTS write goes through
     it, so reaching `'optimize'` from `fts_merge` raises rather than merges.
   * `_fts_optimize()` is the only function in this module that can emit it, `compact()` is its only
     caller, and `test_store_maintenance.py` walks this module's own AST call graph from
     `maintenance_window` and asserts `_fts_optimize` is unreachable. A later edit that calls it
     from the window fails the test, not a review.

3. **`incremental_vacuum` is conditional.** `auto_vacuum = INCREMENTAL` (07:173's `CREATE_PRAGMAS`)
   reclaims nothing on its own, and the trigger is `freelist_count / page_count > 0.25` (07:211),
   strictly greater, which is why `FREELIST_RATIO_TRIGGER` is compared with `>` and never `>=`.

## Both `VACUUM` and FTS `'optimize'` change physical row order

07:218-219: *"which is exactly why every Channel is totally ordered on `(-score, block_id)` (ST7)
and why the ST7 property test VACUUMs."* 13-quality.md:874 is that test, P-10: *"`FusedHit`
sequences are totally ordered on `(-score, block_id)` and stable across a `VACUUM` and an FTS5
`optimize` ... ties broken by storage order are nondeterministic and only appear after
maintenance."* `compact()` is the verb that makes the hazard real, so it is named here; the total
order itself is the retrieval module's and is deliberately not restated.

## `ow store repair` is exactly four steps, in order (07:220-228)

(1) re-create every index whose `sqlite_master` row is missing, reading its DDL from `schema/` **by
name** with a hard raise on a miss; (2) rebuild the FTS tables when `index_state.fts_state <> 'ok'`;
(3) `PRAGMA foreign_key_check` and `PRAGMA integrity_check`; (4) re-derive `stat`. **Only then** is
`index_state.bulk_window` cleared -- `repair()` clears it as its last act and `RepairReport` records
each step, so "in order" is observable and not merely intended.

`tools/indexes.toml` is the register 07:221 names as the source of index names. **It does not exist,
and this module does not create one**: a plan-ordered register that no wave has landed is owed by
its owner, and minting it here would be a register allocation. Instead the names and their DDL are
read out of the shipped migrations -- which is where the plan sends the *DDL* anyway ("reading its
DDL from `schema/` by name") -- so the two halves of 07:221 stay one fact rather than two.
`test_store_maintenance.py` proves the reader against a real applied database: every index,
trigger, view and virtual table the parser finds is checked against `sqlite_master` after the four
migrations are applied, in both directions. When `tools/indexes.toml` lands, `index_names()` must
read it and this parser becomes its cross-check, never its second home (INV-21).

## Bulk windows (07:2847-2866)

* **Only non-UNIQUE secondary indexes and the FTS triggers are dropped.** `secondary_index_names()`
  is exactly the `CREATE INDEX` set, and `unique_index_names()` is exactly the `CREATE UNIQUE INDEX`
  set; nothing computes membership from a name, so a rename cannot move an index between them.
  07:2854-2855: *"The UNIQUE identity index is never dropped. Dropping it makes duplicate insertion
  possible during exactly the window nobody is watching."*
* **The marker is written before the first DDL**, with `fts_state = 'building'` beside it, and
  committed before any DDL is issued -- `open_bulk_window()` commits between the two, so a SIGKILL
  anywhere after that point leaves the pessimistic value. 07:2858-2860 and ST13 (07:3247).
* **An open marker refuses to serve**, naming `ow store repair` -- `refuse_if_bulk_window_open()`,
  which `store/sqlite.py`'s open path calls (02-architecture.md:724 row 6, 08-runtime.md:478).
* The FTS triggers are identified **structurally**: a trigger is an FTS sync trigger when its DDL
  writes to a table the migrations declare with `USING fts5`. `work_no_live_delete` and
  `route_decision_monotone` are triggers too and are never dropped, and they are excluded by that
  rule rather than by a name list.
* 07:2861's *"the loop yields at the top of each body"* is the runtime's yield rule (08-runtime.md
  section 8.4, `[runtime] yield_interval`), not this module's: a pure function over a connection has
  no event loop to yield to. `open_bulk_window()` and `close_bulk_window()` therefore take an
  optional `on_step` callback, invoked **at the top of each body**, which is where the runtime hangs
  its yield and its watchdog heartbeat.

## Where a number lives

`ANALYSIS_LIMIT`, `MERGE_PAGES`, `MERGE_STEPS`, `FREE_PAGES_PER_STEP` and
`FREELIST_RATIO_TRIGGER` are transcribed from 07:209-211, which is their only definition site in
the plan. They are **not** in `omniweave_core.limits`: that module holds "every `MAX_*` ceiling in
the framework, the one `MIN_SQLITE` floor" -- ceilings clampable down by a tenant -- and these five
are neither ceilings nor settings but the fixed arguments of five statements. Charter section 6.10's
list of named maxima does not carry them. A copy in `limits.py` would be INV-21's second home for
one fact.

## DEFECTS

**DEFECT 1 -- 07:209 requires an inline fallback and never says what it is.** The row gives the
off-thread statements (`PRAGMA analysis_limit = 1000` then `PRAGMA optimize`), calls
`analysis_limit` "the bound", and requires the inline fallback to be "strictly smaller" than "the
same list". One definition site, two readable meanings of "smaller": a smaller `analysis_limit`, or
fewer optimizations. Neither has more definition sites than the other, so the reading that satisfies
BOTH is implemented -- `OPTIMIZE_INLINE` narrows the optimization set *and* divides the analysis
limit -- and the divisor `INLINE_ANALYSIS_DIVISOR = 10` is this module's, recorded here because the
plan fixes only `<`. Reported.

**DEFECT 2 -- 07:210's statement names `block_fts`, and the store ships three FTS5 tables.**
`block_fts` (0001), `head_fts` and `block_tri` (0003) all accumulate one segment per commit for
the identical reason, but the plan's statement, its `MERGE_PAGES` bound and F55's measurement
(07:3402, 12-performance.md:1478, 17-risks.md:637) name `block_fts` and `block_fts_data` only.
`FTS_MERGE_TABLES = ("block_fts",)` follows the one definition site; `fts_merge(tables=...)` lets a
caller add the other two, and `MERGE_STEPS` is enforced as a total across tables because 07:210
bounds it "per window" and not per table. Reported: the plan owes a ruling on whether `head_fts`
and `block_tri` join the window.

**DEFECT 3 -- `OW-S-031` is allocated as a numeral with no symbol.** 07:2859, 07:3195,
11-repo-layout.md:1334 and 15-observability.md:1517 all name the numeral for the open-bulk-window
refusal; no site prints a symbol, and `codes.toml` carries no row. `BULK_WINDOW_OPEN_SYMBOL` below
is this module's spelling, and it follows the house form already used twice in the shipped DDL
(`0004_runtime.sql:139`, `:364`: *"OW-S-014 is charter.md:4072's allocation and has no codes.toml
row yet -- reported to the owner"*). `codes.toml` is a transcription of plan allocations and is not
this wave's file, so no row is added here. Reported.

**DEFECT 4 -- `stat`'s `docs` key needs `NO_JOB_DOCS`, which has no code home yet.**
`0003_index.sql:426-428` fixes the predicate as `format <> 'owjob'` and says "whose one spelling
lives in `omniweave_core.store` and which every site appends verbatim". `omniweave_core.store`
does not export it. Repair step 4 therefore re-derives the keys it can spell without minting a
second home and records `docs` in `RepairReport.stat_deferred`, naming why. Reported as a required
edit to `store/__init__.py`.

Stdlib only (INV-2 / G1). `import sqlite3` is legal here and needs no `noqa`: ruff's TID251
per-file-ignore covers `store/*.py` (pyproject.toml), which is INV-17's five-file allowance.
Inside one of the nine LAZY subpackages, so `import omniweave_core` must not reach it -- G17.

Tier T-INTERNAL: not an SDK surface. 07 section 2.2 is the specification.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Final

from omniweave_core.errors import StoreError

__all__ = [
    "ANALYSIS_LIMIT",
    "BULK_WINDOW_KEY",
    "BULK_WINDOW_OPEN_SYMBOL",
    "DEFAULT_OPTIMIZATIONS",
    "FREELIST_RATIO_TRIGGER",
    "FREE_PAGES_PER_STEP",
    "FTS_MERGE",
    "FTS_MERGE_TABLES",
    "FTS_OPTIMIZE",
    "FTS_REBUILD",
    "FTS_STATE_BUILDING",
    "FTS_STATE_KEY",
    "FTS_STATE_OK",
    "FTS_STATE_STALE",
    "INLINE_ANALYSIS_DIVISOR",
    "MERGE_PAGES",
    "MERGE_STEPS",
    "OPTIMIZE_ANALYZE_MAYBE_BENEFIT",
    "OPTIMIZE_ANALYZE_REGARDLESS",
    "OPTIMIZE_DEBUG",
    "OPTIMIZE_INLINE",
    "OPTIMIZE_OFFTHREAD",
    "REPAIR_FIX",
    "BackupReport",
    "BulkWindow",
    "CompactReport",
    "MergeReport",
    "OptimizePlan",
    "PlannerStatistics",
    "ReclaimReport",
    "RepairReport",
    "SchemaObject",
    "WindowReport",
    "backup",
    "bulk_window_marker",
    "close_bulk_window",
    "compact",
    "fts_merge",
    "fts_table_names",
    "fts_trigger_names",
    "index_ddl",
    "index_names",
    "maintenance_window",
    "object_ddl",
    "open_bulk_window",
    "planner_statistics",
    "reclaim_free_pages",
    "refuse_if_bulk_window_open",
    "repair",
    "secondary_index_names",
    "shipped_schema",
    "unique_index_names",
]


# ---------------------------------------------------------------------------
# The transcribed constants. 07-store-and-retrieval.md:209-211, their only definition site.
# ---------------------------------------------------------------------------

ANALYSIS_LIMIT: Final = 1000
"""`PRAGMA analysis_limit = 1000`, from 07:209, where it is called "the bound".

It bounds how many rows `PRAGMA optimize`'s `ANALYZE` visits per index, which is what turns
"minutes of synchronous IO" into a bounded step. Set to 0 it means unlimited, so a zero here would
silently remove the only bound the row declares.
"""

INLINE_ANALYSIS_DIVISOR: Final = 10
"""How much smaller the inline fallback's `analysis_limit` is. **This module's, not the plan's.**

07:209 fixes only the relation ("strictly smaller"), never a value -- see DEFECT 1 in the module
docstring. Ten is chosen so the inline path is an order of magnitude cheaper rather than marginally
so: its whole reason for existing is that the off-thread submission did not happen, and a fallback
that costs almost as much as the thing it replaces is the mitigation-worse-than-nothing shape the
futility latch exists for (ST16).
"""

OPTIMIZE_DEBUG: Final = 0x00001
"""`PRAGMA optimize` mask bit: report what would be done and do nothing. Never in a shipped plan."""

OPTIMIZE_ANALYZE_MAYBE_BENEFIT: Final = 0x00002
"""`PRAGMA optimize` mask bit: `ANALYZE` tables that might benefit. The one bit inline keeps."""

OPTIMIZE_ANALYZE_REGARDLESS: Final = 0x00010
"""`PRAGMA optimize` mask bit: `ANALYZE` a used table even when its statistics look current.

Defined by SQLite 3.46 and ignored below it, which costs nothing at `MIN_SQLITE = (3, 42, 0)`: an
unknown bit in the mask is ignored rather than an error. It is in the off-thread set because that
set is "everything the default mask enables", and it is the bit the inline set drops.
"""

MERGE_PAGES: Final = 64
"""The `rank` argument of `INSERT INTO block_fts(block_fts, rank) VALUES('merge', 64)` (07:210).

Pages of merging per step. FTS5 writes one new segment per commit until `automerge` (left at its
default, 4) folds them, and the lexical Channel's p50 climbs with the **segment count**, not the row
count -- so an incrementally written index degrades without this even though it is never wrong.
"""

MERGE_STEPS: Final = 16
"""At most sixteen `'merge'` steps per window (07:210). The bound, and it is per WINDOW.

Not per table: 07:210 says "per window", so `fts_merge` counts steps across every table it is
given. F55 (07:3402) is the open question of whether 16 holds over months of writes, and its
remedy raises `automerge` from 4 first and `MERGE_STEPS` from 16 second, in that order.
"""

FREE_PAGES_PER_STEP: Final = 2048
"""`PRAGMA incremental_vacuum(2048)` -- 16 MB at `page_size = 8192` (07:211, 07:173)."""

FREELIST_RATIO_TRIGGER: Final = 0.25
"""Reclaim only when `freelist_count / page_count > 0.25` (07:211). Strictly greater.

A full re-parse retires one generation of every block, so the file holds up to ~2x its logical size
until this runs; below a quarter the reclaim costs more IO than the space it returns.
"""

FTS_MERGE_TABLES: Final[tuple[str, ...]] = ("block_fts",)
"""The FTS5 tables the maintenance window merges. 07:210 names exactly one -- see DEFECT 2."""


# ---------------------------------------------------------------------------
# `index_state` keys and the strings that are not this module's to invent.
# ---------------------------------------------------------------------------

BULK_WINDOW_KEY: Final = "bulk_window"
"""`index_state.bulk_window` -- 07:697 and `0003_index.sql:407-408` list the eleven keys."""

FTS_STATE_KEY: Final = "fts_state"
"""`index_state.fts_state` -- the three-state machine at 07:424-430."""

FTS_STATE_OK: Final = "ok"
"""Written "after a successful `'rebuild'`, or at the end of a bulk window" (07:426)."""

FTS_STATE_BUILDING: Final = "building"
"""Written by `ow store repair` / a bulk window, BEFORE the first FTS DDL (07:428)."""

FTS_STATE_STALE: Final = "stale"
"""Written by a writer that inserted `block` rows with the triggers dropped (07:429)."""

FTS_OPTIMIZE: Final = "optimize"
"""The FTS5 command that is O(index). `_fts_command` refuses it; only `compact()` may emit it."""

FTS_MERGE: Final = "merge"
"""The FTS5 command of 07:210's statement."""

FTS_REBUILD: Final = "rebuild"
"""The FTS5 command of `ow store repair` step 2 (07:224)."""

REPAIR_FIX: Final = "ow store repair"
"""The command every refusal in this module names, because 07:220 makes it the recovery verb."""

BULK_WINDOW_OPEN_SYMBOL: Final = "OW_BULK_WINDOW_OPEN"
"""The symbol for `OW-S-031`. **Allocated here because the plan allocates only the numeral.**

07:2859, 07:3195, 11-repo-layout.md:1334 and 15-observability.md:1517 all print `OW-S-031`; none
prints a symbol and `codes.toml` has no row, so `OwError.numeric()` resolves to `""` for it until
one lands. The house form for this exact situation is already in the shipped DDL twice
(`0004_runtime.sql:139` and `:364`). See DEFECT 3.
"""


# ---------------------------------------------------------------------------
# Operation 1 -- planner statistics. The off-thread plan and its provably smaller inline fallback.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptimizePlan:
    """One `PRAGMA analysis_limit` / `PRAGMA optimize` pair, as a bound plus a SET of optimizations.

    `optimizations` is a `frozenset` of `PRAGMA optimize` mask bits because SQLite's own
    documentation calls that argument *a bitmask of optimizations*: making it a set is what turns
    07:209's "strictly smaller" into a checkable relation (proper inclusion) instead of a comparison
    between two hand-written integers.
    """

    analysis_limit: int
    optimizations: frozenset[int]

    def mask(self) -> int:
        """The bits ORed together, for `PRAGMA optimize(<mask>)`."""
        mask = 0
        for bit in self.optimizations:
            mask |= bit
        return mask

    def statements(self) -> tuple[str, ...]:
        """The SQL, in order. The full plan emits 07:209's two statements VERBATIM.

        A plan equal to `DEFAULT_OPTIMIZATIONS` emits the bare `PRAGMA optimize`, which is exactly
        what the plan row prints and exactly what SQLite's default mask (`0xfffe`) means. Any
        narrower plan has to spell its mask, because there is no other way to ask for less.
        """
        limit = f"PRAGMA analysis_limit = {self.analysis_limit:d}"
        if self.optimizations == DEFAULT_OPTIMIZATIONS:
            return (limit, "PRAGMA optimize")
        return (limit, f"PRAGMA optimize({self.mask():#x})")

    def covers(self, other: OptimizePlan) -> bool:
        """True when `other` is a **strictly smaller** plan than this one, on both axes.

        Proper subset of the optimizations, and an `analysis_limit` no larger. This is the predicate
        07:209 states; `narrowed()` enforces it at construction and the test asserts it here.
        """
        smaller_set = other.optimizations < self.optimizations
        return smaller_set and other.analysis_limit <= self.analysis_limit

    def narrowed(self, *, keep: frozenset[int], analysis_limit: int) -> OptimizePlan:
        """A strictly smaller plan, or a raise. **The only way `OPTIMIZE_INLINE` is built.**

        Raising rather than returning is the point: 07:209's "never the same list run inline" has to
        survive someone editing a constant, and a constructor that refuses cannot be edited into
        agreement with itself.
        """
        candidate = OptimizePlan(analysis_limit=analysis_limit, optimizations=keep)
        if not self.covers(candidate):
            raise StoreError(
                f"an inline `PRAGMA optimize` fallback must be strictly smaller than the "
                f"off-thread plan (07-store-and-retrieval.md:209): {sorted(keep)} is not a proper "
                f"subset of {sorted(self.optimizations)}, or analysis_limit {analysis_limit} "
                f"exceeds {self.analysis_limit}",
                fix="ow doctor",
            )
        return candidate


DEFAULT_OPTIMIZATIONS: Final[frozenset[int]] = frozenset(
    {OPTIMIZE_ANALYZE_MAYBE_BENEFIT, OPTIMIZE_ANALYZE_REGARDLESS}
)
"""Every non-debug optimization SQLite documents -- what a bare `PRAGMA optimize` asks for.

SQLite's default mask is `0xfffe`, i.e. every bit but the debug bit. Only these two are documented,
so this set is "the documented content of the default", and `OptimizePlan.statements()` emits the
bare pragma for it rather than spelling `0xfffe` -- the plan's own literal, kept literal.
"""

OPTIMIZE_OFFTHREAD: Final = OptimizePlan(
    analysis_limit=ANALYSIS_LIMIT, optimizations=DEFAULT_OPTIMIZATIONS
)
"""07:209's list, off the query path: `PRAGMA analysis_limit = 1000` then `PRAGMA optimize`."""

OPTIMIZE_INLINE: Final = OPTIMIZE_OFFTHREAD.narrowed(
    keep=frozenset({OPTIMIZE_ANALYZE_MAYBE_BENEFIT}),
    analysis_limit=ANALYSIS_LIMIT // INLINE_ANALYSIS_DIVISOR,
)
"""The inline fallback. **Derived from `OPTIMIZE_OFFTHREAD`, never written out a second time.**

`narrowed()` raises unless the result is a proper subset with no larger bound, so this line is the
proof of 07:209's requirement rather than a claim about it.
"""


@dataclass(frozen=True, slots=True)
class PlannerStatistics:
    """What operation 1 did: which plan, and the statements it actually issued."""

    inline: bool
    plan: OptimizePlan
    statements: tuple[str, ...]


def planner_statistics(conn: sqlite3.Connection, *, inline: bool = False) -> PlannerStatistics:
    """Operation 1 of four: refresh the query planner's statistics (07:209).

    **Why it is not optional.** Without `sqlite_stat1` rows the planner guesses at join order and
    index choice, and the guess degrades as the corpus grows -- so a store that is only written and
    read gets slower at a rate nothing reports.

    **Why `inline` is a fallback and not a mode.** codegraph measured these pragmas at minutes of
    synchronous IO on a 95k-file index (`index.ts:677-712`), so the caller runs this off-thread;
    `inline=True` is for the path where that submission could not happen, and it runs
    `OPTIMIZE_INLINE`, which `OptimizePlan.narrowed()` guarantees is strictly smaller.
    """
    plan = OPTIMIZE_INLINE if inline else OPTIMIZE_OFFTHREAD
    statements = plan.statements()
    for sql in statements:
        conn.execute(sql).fetchall()
    return PlannerStatistics(inline=inline, plan=plan, statements=statements)


# ---------------------------------------------------------------------------
# Operation 2 -- the FTS5 segment merge.
# ---------------------------------------------------------------------------

_MERGE_COMMAND_ROW_CHANGES: Final = 1
"""The `total_changes` a no-op `'merge'` costs: the command row itself, and nothing else."""


def _fts_command(
    conn: sqlite3.Connection, table: str, command: str, rank: int | None = None
) -> None:
    """Issue one FTS5 command row, refusing `'optimize'` whatever the caller passes.

    This is the guard half of trap 2 (module docstring). 07:214-216 puts FTS `'optimize'` inside
    `ow store compact` and nowhere else -- "never in the maintenance window and never on an
    interactive path" -- and a guard that reads the command it was handed catches the case a call
    graph cannot: a command computed at runtime.

    The table name is interpolated because an FTS5 command row names its own table twice and SQLite
    binds values, never identifiers. `table` is checked against the shipped schema first, so the
    interpolated text is one of a closed set the migrations declare.
    """
    if command == FTS_OPTIMIZE:
        raise StoreError(
            f"FTS5 'optimize' is O(index) and belongs to `ow store compact` alone "
            f"(07-store-and-retrieval.md:214-216); it was asked for on {table!r} through the "
            f"maintenance path",
            fix="ow store compact",
        )
    known = fts_table_names()
    if table not in known:
        raise StoreError(
            f"{table!r} is not an FTS5 table in the shipped schema (have {', '.join(known)})",
            fix=REPAIR_FIX,
        )
    if rank is None:
        conn.execute(f"INSERT INTO {table}({table}) VALUES(?)", (command,))
    else:
        conn.execute(
            f"INSERT INTO {table}({table}, rank) VALUES(?, ?)",
            (command, rank),
        )


@dataclass(frozen=True, slots=True)
class MergeReport:
    """What operation 2 did: which table each `'merge'` step touched, and whether it ran out."""

    steps: tuple[str, ...]
    pages: int
    exhausted: bool

    @property
    def step_count(self) -> int:
        """Steps actually issued. Never above `MERGE_STEPS`."""
        return len(self.steps)


def fts_merge(
    conn: sqlite3.Connection,
    *,
    tables: Sequence[str] = FTS_MERGE_TABLES,
    pages: int = MERGE_PAGES,
    steps: int = MERGE_STEPS,
) -> MergeReport:
    """Operation 2 of four: fold FTS5 segments, at most `MERGE_STEPS` steps per window (07:210).

    **Why it is not optional.** FTS5 writes one new segment per commit until `automerge` (default 4)
    folds them, and the lexical Channel's p50 climbs with the **segment count**, not the row count.
    An incrementally written index therefore gets slower while remaining perfectly correct, which is
    the degradation an operator cannot see.

    **The early exit is measured, not assumed.** A `'merge'` command row always counts as one
    change even when there was nothing to merge, so `total_changes` moving by exactly one is the
    signal that this table is fully merged; anything more means real work happened. Verified on
    SQLite 3.43.1 against a 600-commit `automerge = 0` index: 54 changes on the working step, 1 on
    the next. Stopping early keeps the window's cost proportional to the work available rather than
    to `MERGE_STEPS`.

    `steps` is a TOTAL across `tables`, because 07:210 bounds it "per window".

    `exhausted` is False when the step budget ran out with work still available -- the caller learns
    that the next window has more to do, which is the input F55 measures.
    """
    issued: list[str] = []
    exhausted = True
    for table in tables:
        while len(issued) < steps:
            before = conn.total_changes
            _fts_command(conn, table, FTS_MERGE, pages)
            issued.append(table)
            if conn.total_changes - before <= _MERGE_COMMAND_ROW_CHANGES:
                break
        else:
            exhausted = False
            break
    return MergeReport(steps=tuple(issued), pages=pages, exhausted=exhausted)


# ---------------------------------------------------------------------------
# Operation 3 -- free-page reclaim.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReclaimReport:
    """What operation 3 did, and the two numbers `ow store stats` prints side by side (07:211)."""

    page_count: int
    freelist_count: int
    ratio: float
    triggered: bool
    pages_requested: int
    freelist_after: int


def reclaim_free_pages(
    conn: sqlite3.Connection, *, pages: int = FREE_PAGES_PER_STEP
) -> ReclaimReport:
    """Operation 3 of four: `PRAGMA incremental_vacuum(2048)`, above a quarter free (07:211).

    **Why it is not optional.** `auto_vacuum = INCREMENTAL` (`CREATE_PRAGMAS`, 07:173) reclaims
    nothing on its own -- it only maintains the pointer map that makes reclaim cheap. A full
    re-parse retires one generation of every block, so without this the file holds up to ~2x its
    logical size indefinitely.

    **The trigger is strictly greater than `FREELIST_RATIO_TRIGGER`.** 07:211 writes
    `freelist_count / page_count > 0.25`, and an empty file (`page_count = 0`) is not a trigger: the
    ratio is undefined there, so it is reported as 0.0 and nothing runs.
    """
    page_count = _pragma_int(conn, "page_count")
    freelist = _pragma_int(conn, "freelist_count")
    ratio = 0.0 if page_count <= 0 else freelist / page_count
    triggered = ratio > FREELIST_RATIO_TRIGGER
    if triggered:
        conn.execute(f"PRAGMA incremental_vacuum({pages:d})").fetchall()
    return ReclaimReport(
        page_count=page_count,
        freelist_count=freelist,
        ratio=ratio,
        triggered=triggered,
        pages_requested=pages if triggered else 0,
        freelist_after=_pragma_int(conn, "freelist_count"),
    )


def _pragma_int(conn: sqlite3.Connection, name: str) -> int:
    """One integer-valued `PRAGMA`, or 0 when the pragma returns no row.

    `name` is never caller data: every call site passes a literal from this module.
    """
    row = conn.execute(f"PRAGMA {name}").fetchone()
    return 0 if row is None or row[0] is None else int(row[0])


# ---------------------------------------------------------------------------
# The window: the three connection-local operations, plus the injected fold.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowReport:
    """One maintenance window: the three operations this module owns, plus whether the fold ran."""

    statistics: PlannerStatistics
    merge: MergeReport
    reclaim: ReclaimReport
    folded: bool


def maintenance_window(
    conn: sqlite3.Connection,
    *,
    inline_optimize: bool = False,
    fold: Callable[[], object] | None = None,
    tables: Sequence[str] = FTS_MERGE_TABLES,
) -> WindowReport:
    """The four operations of 07:201-212, in the order the table prints them.

    `fold` is the fourth -- `walvalve.fold_now`, which is injected rather than constructed because
    a fold needs a WAL, a governor and a thread, none of which a pure function over a connection
    has. 07:212's bound is "phase boundaries only", so a window with no phase boundary passes
    `None` and the report says `folded=False`.

    **FTS `'optimize'` is unreachable from here.** Every FTS write below goes through
    `_fts_command`, which refuses it, and `test_store_maintenance.py` walks this module's AST call
    graph from this function to prove `_fts_optimize` is not reachable. 07:214-216.
    """
    statistics = planner_statistics(conn, inline=inline_optimize)
    merge = fts_merge(conn, tables=tables)
    reclaim = reclaim_free_pages(conn)
    if fold is not None:
        fold()
    return WindowReport(
        statistics=statistics, merge=merge, reclaim=reclaim, folded=fold is not None
    )


# ---------------------------------------------------------------------------
# The shipped schema, read by name. 07:221 and 07:2850-2851.
# ---------------------------------------------------------------------------

_MIGRATIONS_PACKAGE: Final = "omniweave_core.store"
_MIGRATIONS_SUBPATH: Final[tuple[str, ...]] = ("schema", "migrations")
"""Where the DDL lives, as package data. `_plan/_notes/build-defects.md` D12 is why it is here.

11-repo-layout.md:1186 has it "packaged with `omniweave-core` as package data, read through
`importlib.resources` at use time", and `tools/gate_migrations.py:146` names the same directory.
Read at USE time and never at import time, and never through `__file__` or `__path__`
(11-repo-layout.md section 2.6 rule 1): a zipapp gives a package with no usable filesystem path.
"""

_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+ON\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_TRIGGER_RE = re.compile(
    r"^\s*CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_TRIGGER_ON_RE = re.compile(r"\bON\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_VIRTUAL_RE = re.compile(
    r"^\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+USING\s+(?P<module>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_VIEW_RE = re.compile(
    r"^\s*CREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_TRIGGER_END_RE = re.compile(r"\bEND\s*$", re.IGNORECASE)
_FTS5_MODULE: Final = "fts5"


@dataclass(frozen=True, slots=True)
class SchemaObject:
    """One `CREATE` statement out of the shipped migrations, with what a caller needs to ask of it.

    `kind` is `index`, `trigger`, `table`, `virtual_table` or `view`. `unique` is only meaningful
    for an index and is what keeps 07:2854's rule structural: a bulk window drops
    `kind == "index" and not unique`, so the UNIQUE identity indexes are excluded by the parse of
    their own DDL rather than by anybody's list of names.

    `sql` is the statement TEXT, comments stripped and with no trailing semicolon, ready to hand to
    `execute()`. It is the shipped DDL and not a reconstruction: 07:2850-2851 is explicit --
    "Reconstructing a dropped index from memory is how an index comes back subtly different."
    """

    name: str
    kind: str
    table: str | None
    unique: bool
    module: str | None
    sql: str
    source: str


def _strip_sql_comments(text: str) -> str:
    """Remove `--` line comments, leaving single-quoted string literals alone.

    Written rather than regexed because a `--` inside a string literal is legal SQL and the shipped
    triggers carry `RAISE(ABORT,'OW-S-014 ...')`-shaped literals. A statement splitter that dropped
    the rest of such a line would silently truncate a trigger body.
    """
    out: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "'":
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "-" and text[index : index + 2] == "--":
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _statements(text: str) -> Iterator[str]:
    """Split a migration into statements, keeping a `CREATE TRIGGER ... BEGIN ... END;` whole.

    A trigger body holds its own semicolons, so a naive split on `;` cuts one into pieces. The rule
    is: while the accumulated text is a `CREATE TRIGGER`, a `;` terminates only when the text before
    it ends with `END`. Every shipped trigger is written in that form, and
    `test_store_maintenance.py` proves the whole parse against `sqlite_master` on a real applied
    database rather than trusting this function's own reading.
    """
    buffer: list[str] = []
    for char in _strip_sql_comments(text):
        if char != ";":
            buffer.append(char)
            continue
        candidate = "".join(buffer).strip()
        if _TRIGGER_RE.match(candidate) and not _TRIGGER_END_RE.search(candidate):
            buffer.append(char)
            continue
        if candidate:
            yield candidate
        buffer = []
    tail = "".join(buffer).strip()
    if tail:
        yield tail


def _migration_sources() -> tuple[tuple[str, str], ...]:
    """`(filename, text)` for every shipped migration, in numeric order.

    The numeric prefix IS the apply order (11-repo-layout.md:1188), and the names are
    `NNNN_<slug>.sql` with a fixed width, so a plain lexical sort on the name is the numeric sort.
    """
    anchor = resources.files(_MIGRATIONS_PACKAGE)
    for part in _MIGRATIONS_SUBPATH:
        anchor = anchor.joinpath(part)
    named = sorted((item.name, item) for item in anchor.iterdir() if item.name.endswith(".sql"))
    return tuple((name, item.read_text(encoding="utf-8")) for name, item in named)


@lru_cache(maxsize=1)
def shipped_schema() -> Mapping[str, SchemaObject]:
    """Every named object the shipped migrations create, keyed by name. Memoised, read at use time.

    One namespace, because `sqlite_master` has one: a trigger name and an index name cannot collide
    in SQLite, and `0001_init.sql:499-503` says so ("A TRIGGER NAME IS GLOBAL IN sqlite_master").
    A duplicate name here is therefore a defect in the migration set, and this function raises on
    one rather than letting the later definition win -- G27(b) would fail the apply for the same
    reason, and disagreeing with it silently is worse than either answer.
    """
    found: dict[str, SchemaObject] = {}
    for source, text in _migration_sources():
        for statement in _statements(text):
            obj = _classify(statement, source)
            if obj is None:
                continue
            if obj.name in found:
                raise StoreError(
                    f"the shipped migrations declare {obj.name!r} twice "
                    f"({found[obj.name].source} and {source}); sqlite_master has one namespace "
                    f"for indexes, triggers, tables and views",
                    fix="ow doctor",
                )
            found[obj.name] = obj
    return MappingProxyType(found)


def _classify(statement: str, source: str) -> SchemaObject | None:
    """One `CREATE` statement as a `SchemaObject`, or `None` when it creates nothing named."""
    match = _INDEX_RE.match(statement)
    if match is not None:
        return SchemaObject(
            name=match["name"],
            kind="index",
            table=match["table"],
            unique=match["unique"] is not None,
            module=None,
            sql=statement,
            source=source,
        )
    match = _TRIGGER_RE.match(statement)
    if match is not None:
        on_table = _TRIGGER_ON_RE.search(statement[match.end() :])
        return SchemaObject(
            name=match["name"],
            kind="trigger",
            table=None if on_table is None else on_table["table"],
            unique=False,
            module=None,
            sql=statement,
            source=source,
        )
    match = _VIRTUAL_RE.match(statement)
    if match is not None:
        return SchemaObject(
            name=match["name"],
            kind="virtual_table",
            table=None,
            unique=False,
            module=match["module"].lower(),
            sql=statement,
            source=source,
        )
    match = _VIEW_RE.match(statement)
    if match is not None:
        return SchemaObject(
            name=match["name"],
            kind="view",
            table=None,
            unique=False,
            module=None,
            sql=statement,
            source=source,
        )
    match = _TABLE_RE.match(statement)
    if match is not None:
        return SchemaObject(
            name=match["name"],
            kind="table",
            table=None,
            unique=False,
            module=None,
            sql=statement,
            source=source,
        )
    return None


def object_ddl(name: str) -> str:
    """The shipped `CREATE` statement for `name`. **A hard raise on a miss** (07:221, 07:2850).

    The raise is the specified behaviour and not defensive coding: 07:2850-2851 says the DDL is read
    "by name, with a hard raise on a miss" because "reconstructing a dropped index from memory is
    how an index comes back subtly different" -- an index that exists with the wrong column order
    or a missing partial-index `WHERE` under-returns silently, which is the one failure class the
    store's whole design refuses to make undetectable.
    """
    schema = shipped_schema()
    obj = schema.get(name)
    if obj is None:
        raise StoreError(
            f"no DDL for {name!r} in the shipped schema: it names an object the migrations under "
            f"{'/'.join(_MIGRATIONS_SUBPATH)} do not create, and reconstructing one from memory is "
            f"how an index comes back subtly different (07-store-and-retrieval.md:2850)",
            fix=REPAIR_FIX,
        )
    return obj.sql


def index_ddl(name: str) -> str:
    """`object_ddl` narrowed to indexes, so a trigger name cannot be re-created as an index."""
    schema = shipped_schema()
    obj = schema.get(name)
    if obj is not None and obj.kind != "index":
        raise StoreError(
            f"{name!r} is a {obj.kind} in the shipped schema, not an index",
            fix=REPAIR_FIX,
        )
    return object_ddl(name)


def index_names() -> tuple[str, ...]:
    """Every index the shipped migrations create, sorted.

    **`tools/indexes.toml` is the plan's home for this list and is owed** (07:221). It does not
    exist; this function derives the same list from the DDL the plan already sends the reader to,
    which keeps one fact in one place until the register lands. When it does, this becomes the
    register's cross-check -- `repair(names=...)` is the seam that lets the register supply the
    names without this module changing.
    """
    return tuple(sorted(n for n, o in shipped_schema().items() if o.kind == "index"))


def unique_index_names() -> tuple[str, ...]:
    """The UNIQUE indexes. **Never dropped by a bulk window** (07:2854)."""
    return tuple(sorted(n for n, o in shipped_schema().items() if o.kind == "index" and o.unique))


def secondary_index_names() -> tuple[str, ...]:
    """The non-UNIQUE indexes: exactly what a bulk window may drop (07:2848, 07:2854)."""
    return tuple(
        sorted(n for n, o in shipped_schema().items() if o.kind == "index" and not o.unique)
    )


def fts_table_names() -> tuple[str, ...]:
    """The FTS5 virtual tables the migrations declare: `block_fts`, `head_fts`, `block_tri`."""
    return tuple(
        sorted(
            n
            for n, o in shipped_schema().items()
            if o.kind == "virtual_table" and o.module == _FTS5_MODULE
        )
    )


def fts_trigger_names() -> tuple[str, ...]:
    """The FTS sync triggers, identified STRUCTURALLY and not by a name list.

    A trigger is an FTS sync trigger when its body writes to a table the migrations declare with
    `USING fts5`. That rule keeps `work_no_live_delete` and `route_decision_monotone` -- which are
    triggers on ordinary tables and enforce ABORT invariants -- out of every bulk window, and it
    keeps them out because of what they DO rather than because of what they are called.
    """
    fts = fts_table_names()
    out: list[str] = []
    for name, obj in shipped_schema().items():
        if obj.kind != "trigger":
            continue
        body = obj.sql.lower()
        if any(re.search(rf"\b{re.escape(table)}\b", body) for table in fts):
            out.append(name)
    return tuple(sorted(out))


# ---------------------------------------------------------------------------
# `index_state`, and the refusal an open bulk window is.
# ---------------------------------------------------------------------------


def _set_index_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert one `index_state` row. `k` is the primary key, so this is the only correct form."""
    conn.execute(
        "INSERT INTO index_state(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, value),
    )


def _get_index_state(conn: sqlite3.Connection, key: str) -> str | None:
    """One `index_state` value, or `None` when the row is absent."""
    row = conn.execute("SELECT v FROM index_state WHERE k = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def bulk_window_marker(conn: sqlite3.Connection) -> str | None:
    """`index_state.bulk_window`, or `None` when no window is open.

    **Absence means closed, and an empty string is not used for it.** `index_state.v` is
    `TEXT NOT NULL`, so a cleared marker could only be `''`, and a falsy value that also means
    "present" is exactly the ambiguity that makes a crashed window look closed. `close_bulk_window`
    and `repair` DELETE the row.
    """
    return _get_index_state(conn, BULK_WINDOW_KEY)


def refuse_if_bulk_window_open(conn: sqlite3.Connection) -> None:
    """`OW-S-031`: an open bulk-window marker **refuses to serve**, naming `ow store repair`.

    ST13 (07:3247) and 11-repo-layout.md:1334 give the reason: "secondary indexes and FTS triggers
    may be dropped, so a query would silently under-return". The refusal is what makes a crash
    inside a bulk window visible instead of served, and it is `store/sqlite.py`'s open path that
    calls it (02-architecture.md:724 row 6, 08-runtime.md:478).
    """
    marker = bulk_window_marker(conn)
    if marker is None:
        return
    raise StoreError(
        f"OW-S-031: this store has an open bulk window ({marker}), so secondary indexes and FTS "
        f"triggers may be dropped and a query would silently under-return; it refuses to serve "
        f"until `{REPAIR_FIX}` completes its four steps",
        symbol=BULK_WINDOW_OPEN_SYMBOL,
        fix=REPAIR_FIX,
    )


def _refuse_open_transaction(conn: sqlite3.Connection, verb: str) -> None:
    """A maintenance verb never commits somebody else's transaction, and `VACUUM` cannot run in one.

    Both halves are real. `VACUUM` and `VACUUM INTO` raise "cannot VACUUM from within a
    transaction", and every verb below has to `commit()` its own writes -- so entering with a
    caller's transaction open would either fail obscurely or silently commit work the caller had not
    finished. Refusing early names the actual problem.
    """
    if conn.in_transaction:
        raise StoreError(
            f"`{verb}` needs the connection to have no open transaction: it commits its own work "
            f"and VACUUM cannot run inside a transaction",
            fix="commit or roll back before running store maintenance",
        )


# ---------------------------------------------------------------------------
# Bulk windows. 07 section 10.6.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BulkWindow:
    """An open bulk window: exactly what was dropped, so exactly that can be re-created.

    The lists are what `close_bulk_window` re-creates and are recorded rather than recomputed,
    because a window opened against `tables=(...)` drops a subset and recomputing the full set at
    close would try to create indexes that were never dropped.
    """

    marker: str
    dropped_indexes: tuple[str, ...]
    dropped_triggers: tuple[str, ...]
    fts_tables: tuple[str, ...]


def open_bulk_window(
    conn: sqlite3.Connection,
    *,
    now_ns: int,
    owner: str,
    tables: Sequence[str] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> BulkWindow:
    """Drop the non-UNIQUE secondary indexes and the FTS triggers, marker first (07:2847-2861).

    The measured payoff is codegraph's: dropping four non-unique edge indexes took a 224k-edge
    `INSERT OR IGNORE` stream from 2.8 s to 1.1 s with ~0.3 s to re-create -- one B-tree paid
    instead of five (07:2849-2850).

    **`index_state.bulk_window` is written and COMMITTED before the first DDL**, with
    `fts_state = 'building'` beside it (07:2858-2860). The commit is the load-bearing part: a marker
    written in the same uncommitted transaction as the first `DROP INDEX` vanishes with it on a
    SIGKILL, which is precisely the crash ST13 exists to make visible.

    **The UNIQUE identity indexes are never dropped** (07:2854-2855). `secondary_index_names()` is
    the `CREATE INDEX` set and nothing else, so a duplicate insert still fails during the window --
    which `test_store_maintenance.py` asserts by inserting one.

    `now_ns` and `owner` are the caller's: library code reads no ambient clock and no ambient pid
    (02-architecture.md:392). `on_step` is invoked **at the top of each body** (07:2861), which is
    where the runtime hangs its cooperative yield and its watchdog heartbeat -- this module has no
    event loop of its own.
    """
    _refuse_open_transaction(conn, "open_bulk_window")
    wanted = None if tables is None else frozenset(tables)
    schema = shipped_schema()
    indexes = tuple(
        n for n in secondary_index_names() if wanted is None or schema[n].table in wanted
    )
    fts_tables = (
        fts_table_names() if wanted is None else tuple(t for t in fts_table_names() if t in wanted)
    )
    triggers = tuple(
        n
        for n in fts_trigger_names()
        if wanted is None
        or any(re.search(rf"\b{re.escape(t)}\b", schema[n].sql.lower()) for t in fts_tables)
    )
    marker = _marker_text(now_ns=now_ns, owner=owner, indexes=indexes, triggers=triggers)

    # STEP 0, and it is before every DDL statement below: the marker and the pessimistic fts_state,
    # committed. 07:2858-2860.
    _set_index_state(conn, BULK_WINDOW_KEY, marker)
    if fts_tables:
        _set_index_state(conn, FTS_STATE_KEY, FTS_STATE_BUILDING)
    conn.commit()

    for name in indexes:
        if on_step is not None:
            on_step(name)
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    for name in triggers:
        if on_step is not None:
            on_step(name)
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    conn.commit()
    return BulkWindow(
        marker=marker,
        dropped_indexes=indexes,
        dropped_triggers=triggers,
        fts_tables=fts_tables,
    )


def _marker_text(
    *, now_ns: int, owner: str, indexes: Sequence[str], triggers: Sequence[str]
) -> str:
    """The marker's TEXT: who opened the window, when, and how much it dropped.

    The plan fixes that the marker exists and WHEN it is written, never its payload (07:2858). Two
    decisions:

    * **Counts, not names.** The marker's reader is an operator looking at `ow doctor`'s `D-04`
      line (15-observability.md:1517) or at the `OW-S-031` refusal, and the recovery path does not
      need the names: `repair()` step 1 re-creates every index in `index_names()` whose
      `sqlite_master` row is missing, so it re-derives the dropped set from the database itself.
      A marker that listed 60 names would put 2 KB inside an error message to duplicate something
      already recoverable.
    * `owner` and `now_ns` are the caller's, and they are here because the first question about a
      window a killed process left open is which process left it.
    """
    return f"owner={owner} at_ns={now_ns:d} indexes={len(indexes):d} triggers={len(triggers):d}"


def close_bulk_window(
    conn: sqlite3.Connection,
    window: BulkWindow,
    *,
    on_step: Callable[[str], None] | None = None,
) -> None:
    """Re-create exactly what the window dropped, repopulate FTS, then clear the marker (07:2850).

    The DDL comes from `object_ddl` -- the shipped text, by name, with a hard raise on a miss -- and
    never from anything this process remembered. The order is re-create, then `'rebuild'`, then
    `fts_state = 'ok'`, then clear: 07:426 makes `ok` mean "a bulk window that re-created the
    triggers **and** re-populated", so writing it before the rebuild would claim a completeness the
    index does not have.
    """
    _refuse_open_transaction(conn, "close_bulk_window")
    for name in [*window.dropped_indexes, *window.dropped_triggers]:
        if on_step is not None:
            on_step(name)
        conn.execute(object_ddl(name))
    for table in window.fts_tables:
        if on_step is not None:
            on_step(table)
        _fts_command(conn, table, FTS_REBUILD)
    if window.fts_tables:
        _set_index_state(conn, FTS_STATE_KEY, FTS_STATE_OK)
    conn.execute("DELETE FROM index_state WHERE k = ?", (BULK_WINDOW_KEY,))
    conn.commit()


# ---------------------------------------------------------------------------
# `ow store backup` and `ow store compact`. 07:216-219.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BackupReport:
    """Where the backup went and how big it is."""

    path: str
    byte_len: int


def backup(conn: sqlite3.Connection, dest: Path) -> BackupReport:
    """`ow store backup` -- `VACUUM INTO <path>`: atomic, no torn WAL (07:216-217).

    **Why `VACUUM INTO` and not a file copy.** A copy of a `.owstore` in WAL mode without its `-wal`
    sidecar is a database missing every committed frame that has not been checkpointed, and a copy
    of both taken separately is a torn pair. `VACUUM INTO` writes a complete, freshly packed
    database from one read transaction, so the destination is consistent by construction.

    **It changes physical row order** (07:218-219), like `compact()`. That is why every Channel is
    totally ordered on `(-score, block_id)` (ST7) and why the ST7 property test VACUUMs
    (13-quality.md:874, P-10): a tie broken by storage order is nondeterministic and shows up only
    after maintenance.
    """
    _refuse_open_transaction(conn, "backup")
    conn.execute("VACUUM INTO ?", (str(dest),))
    return BackupReport(path=str(dest), byte_len=dest.stat().st_size)


def _fts_optimize(conn: sqlite3.Connection, table: str) -> None:
    """`INSERT INTO <t>(<t>) VALUES('optimize')` -- **the only emitter of it in this module**.

    O(index): it merges the whole index into one segment. 07:214-216 confines it to
    `ow store compact`, "never in the maintenance window and never on an interactive path", and
    `compact()` is this function's only caller. `test_store_maintenance.py` walks this module's call
    graph from `maintenance_window` and asserts it cannot reach here, which is the enforcement a
    convention cannot give.
    """
    conn.execute(f"INSERT INTO {table}({table}) VALUES('optimize')")


@dataclass(frozen=True, slots=True)
class CompactReport:
    """What `ow store compact` did: pages before and after, the FTS tables, the check result."""

    page_count_before: int
    page_count_after: int
    fts_optimized: tuple[str, ...]
    integrity: tuple[str, ...]

    @property
    def intact(self) -> bool:
        """True when `PRAGMA integrity_check` returned exactly the single row `ok`."""
        return self.integrity == ("ok",)


def compact(conn: sqlite3.Connection, *, tables: Sequence[str] | None = None) -> CompactReport:
    """`ow store compact` -- full `VACUUM`, FTS `'optimize'`, `PRAGMA integrity_check` (07:216-217).

    This is the one verb allowed to run FTS `'optimize'`, and the reason it is a verb rather than a
    window step is that both halves are O(size): `VACUUM` rewrites the file and `'optimize'` merges
    the whole lexical index into one segment. F55's fallback (07:3402) is that if the bounded
    `'merge'` step cannot hold the lexical Channel's latency over months of writes, this becomes "a
    documented weekly operation rather than an on-demand verb" -- a scheduling change in the
    runtime, not a change here.

    **It changes physical row order.** See `backup`; ST7 and 13-quality.md:874's P-10 are the
    property that survives it.
    """
    _refuse_open_transaction(conn, "compact")
    before = _pragma_int(conn, "page_count")
    conn.execute("VACUUM")
    chosen = fts_table_names() if tables is None else tuple(tables)
    for table in chosen:
        if table not in fts_table_names():
            raise StoreError(
                f"{table!r} is not an FTS5 table in the shipped schema", fix=REPAIR_FIX
            )
        _fts_optimize(conn, table)
    conn.commit()
    integrity = tuple(str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall())
    return CompactReport(
        page_count_before=before,
        page_count_after=_pragma_int(conn, "page_count"),
        fts_optimized=chosen,
        integrity=integrity,
    )


# ---------------------------------------------------------------------------
# `ow store repair` -- four steps, in order. 07:220-228.
# ---------------------------------------------------------------------------

_STAT_DEFERRED: Final[Mapping[str, str]] = MappingProxyType(
    {
        "docs": (
            "needs the NO_JOB_DOCS predicate (`format <> 'owjob'`), whose one code home is "
            "`omniweave_core.store` per 0003_index.sql:426-428; that module does not export it "
            "yet and spelling it here would be INV-21's second home"
        ),
        "per_kind": (
            "07:696-698 and 0003_index.sql:421-423 name 'per-kind counts' without fixing a key "
            "spelling; inventing one would allocate register rows the plan did not order"
        ),
    }
)
"""`stat` keys repair step 4 does NOT write, and why. See DEFECT 4 in the module docstring."""

_STAT_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "live_blocks": "SELECT count(*) FROM ow_block_head",
        "live_segments": "SELECT count(*) FROM ow_segment_head",
    }
)
"""The two `stat` keys whose spelling the shipped DDL fixes (`0003_index.sql:421-422`).

Both read a head view rather than the base table, because "live" is exactly what `ow_block_head`
and `ow_segment_head` define -- `gen = doc.gen AND state = 0` (`0001_init.sql:328-330`,
`0003_index.sql:87-89`). Re-deriving the definition here would be a second home for it.
"""


@dataclass(frozen=True, slots=True)
class RepairReport:
    """The four steps of 07:220-228, each recorded, in `steps` in the order they ran."""

    steps: tuple[str, ...]
    recreated_indexes: tuple[str, ...]
    fts_rebuilt: tuple[str, ...]
    foreign_key_violations: int
    integrity: tuple[str, ...]
    stat_written: Mapping[str, int]
    stat_deferred: Mapping[str, str]
    bulk_window_cleared: bool


def repair(
    conn: sqlite3.Connection,
    *,
    now_ns: int,
    names: Sequence[str] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> RepairReport:
    """`ow store repair`, ST13's recovery verb: **exactly four steps, in order** (07:220-228).

    1. Re-create every index in `names` whose `sqlite_master` row is missing, reading its DDL from
       `schema/` **by name with a hard raise on a miss**. `names` defaults to `index_names()`
       because `tools/indexes.toml` -- the register 07:221 names -- has not landed; the parameter is
       the seam it will arrive through.
    2. Rebuild the FTS tables when `index_state.fts_state <> 'ok'`, then write `ok`. A store whose
       `fts_state` is already `ok` is not rebuilt: `'rebuild'` is O(index), and 07:424-431 makes
       `fts_state` the authority on whether the index is of unknown completeness.
    3. `PRAGMA foreign_key_check` and `PRAGMA integrity_check`.
    4. Re-derive `stat`.

    **Only then is `index_state.bulk_window` cleared** (07:228), and clearing it is this function's
    last statement.

    **A corrupt file stops the verb at step 3 and leaves the marker open.** 07:226 orders the two
    checks and does not say what a failure does; the reading implemented is that a repair which
    found corruption must not present itself as a repair, and that the next open must still refuse
    (`OW-S-031`) rather than serve a file `integrity_check` rejected. Reported.

    `now_ns` is the caller's clock -- `stat.computed_ns` is a stored timestamp and library code
    reads no ambient one.
    """
    _refuse_open_transaction(conn, "repair")
    steps: list[str] = []

    # ---- step 1: the missing indexes, by name, from schema/.
    steps.append("recreate_indexes")
    present = {
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    recreated: list[str] = []
    for name in index_names() if names is None else names:
        if on_step is not None:
            on_step(name)
        if name in present:
            continue
        conn.execute(index_ddl(name))
        recreated.append(name)
    conn.commit()

    # ---- step 2: the FTS tables, only when fts_state says they are of unknown completeness.
    steps.append("rebuild_fts")
    rebuilt: list[str] = []
    if _get_index_state(conn, FTS_STATE_KEY) != FTS_STATE_OK:
        for table in fts_table_names():
            if on_step is not None:
                on_step(table)
            _fts_command(conn, table, FTS_REBUILD)
            rebuilt.append(table)
        _set_index_state(conn, FTS_STATE_KEY, FTS_STATE_OK)
        conn.commit()

    # ---- step 3: the two checks.
    steps.append("checks")
    violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    integrity = tuple(str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall())
    if violations or integrity != ("ok",):
        raise StoreError(
            f"`{REPAIR_FIX}` stopped at step 3: PRAGMA foreign_key_check reported {violations} "
            f"violation(s) and PRAGMA integrity_check reported {integrity}; step 4 did not run and "
            f"index_state.bulk_window was not cleared, so this store still refuses to serve",
            fix="ow store backup <path> && ow index rebuild",
        )

    # ---- step 4: re-derive stat.
    steps.append("rederive_stat")
    written: dict[str, int] = {}
    for key, sql in _STAT_SQL.items():
        if on_step is not None:
            on_step(key)
        row = conn.execute(sql).fetchone()
        value = 0 if row is None else int(row[0])
        conn.execute(
            "INSERT INTO stat(k, v, computed_ns) VALUES(?, ?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v, computed_ns = excluded.computed_ns",
            (key, value, now_ns),
        )
        written[key] = value

    # ---- and only then the marker.
    steps.append("clear_bulk_window")
    had_marker = bulk_window_marker(conn) is not None
    conn.execute("DELETE FROM index_state WHERE k = ?", (BULK_WINDOW_KEY,))
    conn.commit()
    return RepairReport(
        steps=tuple(steps),
        recreated_indexes=tuple(recreated),
        fts_rebuilt=tuple(rebuilt),
        foreign_key_violations=violations,
        integrity=integrity,
        stat_written=MappingProxyType(written),
        stat_deferred=_STAT_DEFERRED,
        bulk_window_cleared=had_marker,
    )
