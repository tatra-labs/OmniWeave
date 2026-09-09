"""The one `sqlite3.connect` in the framework: the connection layer, the thread, the snapshot.

ST1 (07-store-and-retrieval.md:2721): *"`sqlite3.connect` appears in exactly one module"*, enforced
by gate G24 and by `tools/gate_semgrep.py`'s `omniweave-no-sqlite3-connect-outside-store`. This is
that module. INV-17 upgrades the rule from module to module-**and**-thread (07:2722-2723): the
**store thread** is the only holder of a `Connection` in a process and every write reaches it as a
transaction closure on a bounded queue, which "deletes the cross-thread-connection failure class
outright". `StoreThread` below is the mechanism, and `sqlite3`'s own `check_same_thread=True` is
what makes the claim checkable rather than reviewed.

What this module is, section by section:

1. **The four pragma tuples**, transcribed from the fence printed at 07:165-180. The ORDER IS
   LOAD-BEARING and section 2.1 is titled with that fact.
2. **The refusals at open** -- `MIN_SQLITE` (07:196-200) and FTS5 (11-repo-layout.md:580), both
   naming `pip install omniweave-core[sqlite]`, the one optional dependency core has.
3. **`connect_readonly`'s two-rung ladder** (07:2744-2758), and the pragma it must NOT issue.
4. **Heal-on-open** above `[store] wal_heal_mb` (07:2807, 15-observability.md:1806) and the
   open-bulk-window refusal (ST13, 07:2858-2862).
5. **The section 3.1 schema-compatibility ladder** (07:273-295), four rows and no `--force`.
6. **The cross-process scoped lock** `store.write` (07:2724-2728, 02-architecture.md:746).
7. **The store thread**, its bounded queue, the transaction primitive and ST14's durability hook.
8. **`snapshot()`** -- `BEGIN DEFERRED` plus the one `index_state` read that opens it
(07:2777-2782),
   bounded by `MAX_SNAPSHOT_MS` through `Connection.interrupt()`.

**Not here, and owned elsewhere in this wave and the next:** the `Store`, `Reader`, `DocSink` and
`GraphSink` implementations (`store/__init__.py`'s four Protocols are their contract); the WAL valve
of 07 section 10.5 (`walvalve.py`); the four maintenance operations of 07 section 2.2
(`maintenance.py`); the `omniweave.index.lock` receipt (`indexlock.py`); and the migration loader,
which is `store/migrate.py` -- the split is argued in that module's docstring and here.

**Why the migration loader is a sibling module and not a section here.** Two reasons, and each is a
dependency direction. `connect()` must be usable on a file that has no schema at all -- that is what
G27(b) does and what a first `ow add` does -- so the connection layer may not depend on the
migration set. And the loader takes a `Connection` and nothing else: it knows no thread, no lock and
no snapshot, so folding it in here would sit 07 section 3.8's `migration` table beside 07 section
10's concurrency model with no shared vocabulary between them.

**Durations are `time.monotonic_ns`; every wall clock is the caller's.** `time.time`,
`time.perf_counter`, `datetime.now`, `os.getcwd`, `random`, `uuid4`, `secrets`, `subprocess`,
`asyncio` and `sys.exit` are all banned in library code (02-architecture.md:392, implemented as
`ast` checks in `tools/gate_semgrep.py`), and `time.monotonic_ns` survives because a duration is not
an ambient fact. Wall-clock values are therefore parameters: `FileScopedLock` takes `now_ns`, and so
does `migrate.apply_pending`.

Stdlib only (INV-2 / G1). One of the nine LAZY names (11-repo-layout.md section 1.3), reached only
by importing `omniweave_core.store.sqlite` on purpose. Tier T-SCHEMA: 02-architecture.md section 2
row 26.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Protocol

from omniweave_core.config import KEYS
from omniweave_core.contract import SCHEMA, SCHEMA_MINOR, SCHEMA_STRING
from omniweave_core.errors import ConfigError, StoreBusy, StoreError
from omniweave_core.limits import MAX_SNAPSHOT_MS, MIN_SQLITE
from omniweave_core.store.types import Snapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover -- Windows has no fcntl.
    _fcntl = None
try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover -- POSIX has no msvcrt.
    _msvcrt = None

__all__ = [
    "BATCH_WAIT_MS",
    "CONN_PRAGMAS",
    "CREATE_PRAGMAS",
    "DURABLE_COST_CLASSES",
    "EVENT_PRAGMAS",
    "INIT_PRAGMAS",
    "INTERACTIVE_WAIT_MS",
    "INTERRUPTED",
    "READONLY_PRAGMAS",
    "STORE_QUEUE_BOUND",
    "STORE_WRITE_LOCK",
    "SYNCHRONOUS_FULL",
    "SYNCHRONOUS_NORMAL",
    "FileScopedLock",
    "LockHolder",
    "ReadonlyRung",
    "SchemaAction",
    "ScopedLock",
    "StoreThread",
    "Unit",
    "connect",
    "connect_readonly",
    "heal_wal",
    "process_create_time",
    "readonly_target",
    "refuse_missing_fts5",
    "refuse_old_sqlite",
    "refuse_open_bulk_window",
    "schema_action",
    "snapshot",
    "wal_bytes",
]


# --------------------------------------------------------------------------------------------
# 1. The four pragma tuples. 07-store-and-retrieval.md:165-180, and the order IS the content.
# --------------------------------------------------------------------------------------------

CONN_PRAGMAS: Final = (
    "busy_timeout = 5000",
    "foreign_keys = ON",
    "journal_mode = WAL",
    "synchronous = NORMAL",
    "cache_size = -64000",
    "temp_store = MEMORY",
    "mmap_size = 268435456",
)
"""Per connection, IN THIS ORDER (07:165-172).

**`busy_timeout` is FIRST and that is the whole reason section 2.1 has a title.** 07:178-180:
*"`journal_mode = WAL` itself touches the file and can raise `SQLITE_BUSY` before the timeout is in
effect -- codegraph #238, an unreproducible startup crash."* A reordering here is not a style
change;
it re-opens a crash that took a bug number to find, which is why
`test_store_sqlite.py::test_the_pragmas_are_issued_in_the_order_the_plan_fixes` records the real
statement sequence a connection receives instead of comparing this tuple to a copy of itself.

Two of the seven carry a second job beyond speed, and both are quoted because a later reader will
otherwise tune them (07:186-194):

* **`temp_store = MEMORY`** *"is what makes the section 6.1 narrowing probe legal on a `mode=ro`
  connection: an `INSERT` into a TEMP table is a write to the *temp* schema, and with an in-memory
  temp store there is no temp file to create, journal or leave behind on a read-only filesystem."*
  Dropping it does not slow the narrowing probe down; it makes it fail on a read-only mount.
* **`mmap_size = 268435456`** (256 MB) *"is chosen to cover a full `vseg` scan at the stdlib
  backend's ceiling -- 27.2 MB (section 3.9) -- plus the hot B-tree pages of a multi-GB store."*
  It is sized off a measurement, not rounded to a power of two by taste.
"""

INIT_PRAGMAS: Final = ("journal_size_limit = 67108864",)
"""64 MiB. Required, or the `-wal` never shrinks below its high-water mark (07:175, :181-184).

The measurement is codegraph #1431: *"checkpoints fold frames back but leave the file at full size
... 25.6 GB of leaked WAL observed across repeatedly-SIGKILLed sessions."*

**DEFECT -- 07:175 labels this tuple "persistent PER FILE", and it is not.** Measured on SQLite
3.43.1: set `journal_size_limit = 67108864`, close the connection, re-open the same file, and
`PRAGMA journal_size_limit` reads `-1`. `PRAGMA auto_vacuum` and `PRAGMA page_size` from
`CREATE_PRAGMAS` *do* persist (they read back `2` and `8192`), so the label is right for that tuple
and wrong for this one. The plan's own justification points the same way -- 07:181-183 says the
`-wal` never shrinks *"while a connection lives"*, which is a per-connection property. So
`connect()`
issues `INIT_PRAGMAS` at **every** open, not only at create, and
`test_the_journal_size_limit_is_re_issued_on_every_open` pins the measurement so nobody "restores"
the create-time-only reading later. Reported; the correct behaviour is unaffected either way,
because a value re-issued on a file that already carries it is a no-op.
"""

CREATE_PRAGMAS: Final = ("page_size = 8192", "auto_vacuum = INCREMENTAL")
"""CREATE time only (07:176), and the timing is a constraint rather than a preference.

`page_size` is refused once a page has been written and, separately, once the journal mode is `wal`;
`auto_vacuum` is refused once a table exists. So both must be issued after `busy_timeout` (so a
contended create still has its timeout) and **before** `journal_mode = WAL`. `connect()` interleaves
them there, and `tools/gate_migrations.py:418-424` reached the same interleaving independently --
*"a create-time pragma applied after `journal_mode = WAL` is silently a no-op and the scratch file
would then not be the file a store receives."*

`auto_vacuum = INCREMENTAL` reclaims nothing on its own; 07 section 2.2's
`PRAGMA incremental_vacuum(FREE_PAGES_PER_STEP)` is what does the reclaiming, and it is
`maintenance.py`'s.
"""

EVENT_PRAGMAS: Final = ("busy_timeout = 200", "journal_mode = WAL", "synchronous = OFF")
"""`events.owstore` ONLY (07:177-178), and deliberately weaker than the index's (07:196-198).

*"`synchronous = OFF` and a 200 ms `busy_timeout`, because a lost telemetry row is free and a
blocked query is not. A `SQLITE_BUSY` on the events file drops the batch and increments
`store.events_dropped`."* Transcribed here because 07 section 2.1 prints all four tuples together
and a fourth home would be a second home; the events ledger itself is not this wave's, so nothing
below reads this tuple. The `MIN_SQLITE` and FTS5 refusals do not apply to it either: the events
file
holds `retrieval_event` and no STRICT table, and it is `[DER]` and deletable.
"""

READONLY_PRAGMAS: Final = tuple(p for p in CONN_PRAGMAS if not p.startswith("journal_mode"))
"""`CONN_PRAGMAS` minus `journal_mode`, DERIVED so the two cannot drift.

**07 section 10.3 gives the ladder and does not say which pragmas a read-only connection may
issue.** Six of the seven are connection-scoped and touch no file: `busy_timeout`, `foreign_keys`,
`synchronous`, `cache_size`, `temp_store` and `mmap_size` all applied cleanly on both rungs against
both journal modes. `journal_mode` is the exception, and it is dropped for one measured reason and
one structural one.

**Measured on 3.43.1:** `PRAGMA journal_mode = WAL` on a `file:...?mode=ro` connection to a
database that is not ALREADY in WAL mode raises `sqlite3.OperationalError("attempt to write a
readonly database")`, because setting a journal mode writes the file header. Such a database is not
exotic here -- `ow store backup` is `VACUUM INTO <path>` (07 section 2.2) and a `VACUUM INTO`
output is a fresh file in SQLite's default `delete` journal mode.

**And the honest scope of that: through the shipped ladder the combination is not reached today**,
which is recorded rather than glossed. A `delete`-mode file has no `-wal` sidecar, so
`readonly_target` gives it rung 2, and under `immutable=1` the same pragma is a harmless no-op --
also measured. So this tuple is a GUARD, not a fix for a live failure: it costs nothing, it removes
the one statement in the set that can write, and it is what keeps rung 1 correct if a later caller
ever hands `mode=ro` a file the ladder did not choose it for. `journal_mode` is also the one pragma
a reader has no use for -- the mode is a property of the file, and a reader that had to set it
would be a writer.

**A third measurement, recorded so nobody attributes the sidecars to a pragma.** A `mode=ro` open
of a WAL-mode database creates `-shm` and `-wal` whether or not any pragma is issued and whether or
not anything is read; `mode=ro&immutable=1` creates neither. So 07:2749-2752's "a read perturbs
nothing" guarantee is carried by the RUNG and not by this tuple: rung 2 creates nothing, and rung 1
is only chosen when the sidecars already exist. Neither rung moves the main file's mtime, which is
the half the freshness check actually reads.
"""

SYNCHRONOUS_NORMAL: Final = 1
SYNCHRONOUS_FULL: Final = 2
"""`PRAGMA synchronous`'s integer readings, named because ST14's test asserts one of them.

SQLite spells the domain `0 = OFF, 1 = NORMAL, 2 = FULL, 3 = EXTRA`, and `PRAGMA synchronous`
returns the integer while `CONN_PRAGMAS` sets the word. Both spellings are the plan's -- 07:168
writes `synchronous = NORMAL` and 07:2737 writes *"a test asserts the pragma value at commit time"*
-- so the two constants exist to keep the assertion from carrying a bare `2`.
"""


# --------------------------------------------------------------------------------------------
# 2. The wait budgets and the queue bound. 07 section 10.1.
# --------------------------------------------------------------------------------------------

INTERACTIVE_WAIT_MS: Final = 2_000
BATCH_WAIT_MS: Final = 60_000
"""The two `store.write` wait budgets, PASSED PER CALL and never configured globally (07:2726-2729).

*"A lock timeout is a UX decision: codegraph's 120 s wait presented as a frozen, hung agent and was
cut to 5 s."* 08-runtime.md:2583 names the same pair from the runtime's side as
`[runtime] interactive_wait_ms` / `batch_wait_lock_ms` = 2000 / 60000, *"the two named `store.write`
wait budgets, passed per call"*.

**They live here and not in `omniweave_core.limits`, and the reason is limits.py's own rule.** That
module holds *"every `MAX_*` ceiling, the one `MIN_SQLITE` floor, and `effective()`"*
(02-architecture.md:231) under INV-22, *"a ceiling is never a target and never a setting"*. These
two
are neither ceilings nor floors: they are the default arguments of one call, and the plan says so in
the same sentence that names them. `MAX_SNAPSHOT_MS` is the contrast -- it IS a ceiling, so it is
imported from `limits` above rather than retyped.
"""

STORE_WRITE_LOCK: Final = "store.write"
"""The scoped lock's name (07:2724, 02-architecture.md:746). One string, one site."""

STORE_QUEUE_BOUND: Final = 1024
"""The bound on the store thread's transaction queue (07:2723, "a bounded queue").

**A shape, not a tuned number, and the shape is what makes 1024 safe.** The queue is a hand-off
between threads of ONE process; the durable queue is the `work` table, which is what 07:2729 means
by *"the queue row is durable, so losing the race costs latency, not work"*. So this queue never has
to hold a run's worth of work -- `queue_high_water = 50_000` (07:2882) bounds THAT, and it bounds
`work` rows, not in-flight transactions. What this bound has to be is "larger than any plausible
burst of concurrently-submitting threads, and small enough that a runaway producer is stopped rather
than swallowed".

**What happens when it is full: the submitter BLOCKS, and past its timeout it RAISES.** Never a
drop. A dropped transaction is lost work with no witness, and the two places the plan does permit a
drop both say why it is free -- a telemetry batch (07:2874) and a watcher event. Neither reading
reaches a transaction closure. Back-pressure is the correct answer because the submitter is a thread
that can wait; see `StoreThread.submit`.
"""

DURABLE_COST_CLASSES: Final = frozenset({"billed_api"})
"""Which `cost_class` values commit at `synchronous = FULL`. ST14, 07:2735-2740.

*"A `BILLED_API` commit is durable -- `synchronous = FULL` is set BEFORE `BEGIN` for that
transaction, and a test asserts the pragma value at commit time for a billed operator and `NORMAL`
for a free one. One fsync against a VLM call is free; re-billing 116,400 pages because a laptop lid
closed is not."*

A `frozenset` rather than a comparison against one literal because the domain is closed and printed
-- `work.cost_class` and `route_decision.cost_class` both
`CHECK (cost_class IN ('free','local_compute','billed_api'))` (0004_runtime.sql:102, :327) -- and a
set makes "which of the three" answerable at one site. `CostClass` itself is P4's type
(08-runtime.md), which is why `Unit` carries the `str`: the hook has to exist before the enum does,
and 07:2740's test is a synthetic billed operator for exactly that reason.
"""

INTERRUPTED: Final = "SQLITE_INTERRUPT"
"""`sqlite3.Error.sqlite_errorname` for a statement stopped by `Connection.interrupt()`.

Measured on 3.43.1: the interrupt surfaces as `sqlite3.OperationalError("interrupted")` with this
`sqlite_errorname`. Matched on the errorname rather than on the message, because the message is
SQLite's and is part of no contract.
"""

_FIX_SQLITE_EXTRA: Final = "pip install omniweave-core[sqlite]"
_FIX_UPGRADE: Final = "pip install -U omniweave-core"
_FIX_MIGRATE: Final = "ow store migrate"
_FIX_REPAIR: Final = "ow store repair"

_MIB: Final = 1 << 20


# --------------------------------------------------------------------------------------------
# 3. The two refusals at open.
# --------------------------------------------------------------------------------------------


def refuse_old_sqlite(version_info: Sequence[int] | None = None) -> None:
    """Refuse below `MIN_SQLITE`, naming the features and `pip install omniweave-core[sqlite]`.

    07:196-200: *"`MIN_SQLITE = (3, 42, 0)` is the one declared floor in `omniweave_core.limits`,
    and it is three features deep: STRICT tables need 3.37.0, `unixepoch()` needs 3.38.0,
    `unixepoch('subsec')` needs 3.42.0. `store/sqlite.py` refuses at open below it, naming
    `pip install omniweave-core[sqlite]`."* The floor is imported from `limits`; retyping the tuple
    here would be the second home INV-21 forbids.

    `version_info` defaults to the running interpreter's `sqlite3.sqlite_version_info`. It is a
    parameter so the refusal is testable on a modern interpreter -- faking the version is the only
    way to test a floor you are above, and monkeypatching a C module's attribute is the alternative.

    **DEFECT -- the error class differs between two sites.** 02-architecture.md:724 puts every
    store-open refusal under *"`StoreError` (`OW-S-*`). The `MIN_SQLITE` refusal names
    `pip install omniweave-core[sqlite]`"*. 18-api-sketch.md:168-171 prints the raise itself as
    `ConfigError OW_SQLITE_TOO_OLD (OW-C-043)`, and `codes.toml` carries exactly that row with
    `raised_by = "ConfigError"`, seeded from 18:168 and 18:3210. Two definition sites (18-api-sketch
    and the register it seeded) against one line of prose, and the register is the only one of the
    three a `.code()` call can resolve, so `ConfigError` / `OW_SQLITE_TOO_OLD` is what ships.
    02:724's sentence is right about the *fix string* and wrong about the class; reported.
    """
    found = tuple(sqlite3.sqlite_version_info if version_info is None else version_info)
    if found >= MIN_SQLITE:
        return
    want = ".".join(str(part) for part in MIN_SQLITE)
    have = ".".join(str(part) for part in found)
    raise ConfigError(
        f"SQLite {have} is below the declared floor {want}: STRICT tables need 3.37, "
        f"unixepoch() needs 3.38 and unixepoch('subsec') needs 3.42, and the shipped DDL "
        f"uses all three",
        symbol="OW_SQLITE_TOO_OLD",
        fix=_FIX_SQLITE_EXTRA,
    )


def refuse_missing_fts5(connection: sqlite3.Connection) -> None:
    """Refuse an interpreter whose SQLite has no FTS5, naming the same extra.

    11-repo-layout.md:577-580 makes the two refusals one remedy: *"`omniweave-core` declares exactly
    one optional dependency, and it is a capability remedy rather than a feature:
    `[sqlite] = ["pysqlite3-binary>=0.5"]`, named by `store/sqlite.py`'s refusal when the
    interpreter's SQLite lacks FTS5 **or** is below `MIN_SQLITE`."*

    **PROBED, not assumed, and not read off `PRAGMA compile_options` either.** A `CREATE VIRTUAL
    TABLE ... USING fts5` against the TEMP schema is the only check that answers the question the
    store actually asks, because `block_fts` is an FTS5 external-content table with three sync
    triggers (0001_init.sql) and a build that lists `ENABLE_FTS5` but cannot create the module is a
    build that fails at the first `end_page()` instead of at open. The probe runs in `temp`, so it
    leaves nothing behind and works on a `mode=ro` connection -- which is the second job
    `temp_store = MEMORY` does (07:186-190).

    **DEFECT -- no `codes.toml` row exists for this condition.** 11:580 names the remedy and no
    document names a symbol or a numeric for "FTS5 absent"; the register's nearest rows are
    `OW-C-043` / `OW_SQLITE_TOO_OLD` (a version breach, a different fact) and the `OW-S-032`
    `fts_state = 'building'` code that 0003_index.sql:414 describes and the register does not carry
    either. So this raises `ConfigError` with the area default symbol `OW_CONFIG` and the specified
    fix, and the missing allocation is reported rather than invented -- `codes.toml` is a
    transcription and a row nobody ordered is not a fix.
    """
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.ow_fts5_probe USING fts5(probe)")
    except sqlite3.Error as error:
        raise ConfigError(
            f"this interpreter's SQLite cannot create an FTS5 table ({error}); block_fts is an "
            f"FTS5 external-content table and the lexical Channel has no fallback",
            fix=_FIX_SQLITE_EXTRA,
        ) from error
    connection.execute("DROP TABLE temp.ow_fts5_probe")


# --------------------------------------------------------------------------------------------
# 4. `connect` -- the one `sqlite3.connect` -- and the read-only ladder.
# --------------------------------------------------------------------------------------------


def _apply(connection: sqlite3.Connection, pragmas: Sequence[str]) -> None:
    """Issue `PRAGMA <p>` for each, in the given order, discarding the readings."""
    for pragma in pragmas:
        connection.execute(f"PRAGMA {pragma}")


def connect(
    path: Path,
    *,
    version_info: Sequence[int] | None = None,
    wal_heal_mb: int | None = None,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open `path` read-write with 07 section 2.1's pragmas in 07 section 2.1's order.

    The sequence, and every step is a line of the plan:

    1. `refuse_old_sqlite()` BEFORE the file is touched (07:196-200). A refusal that opened the file
       first would have created it.
    2. `sqlite3.connect(..., isolation_level=None)`. `isolation_level=None` hands every `BEGIN` to
       this module, which is what "one transaction per unit" (07:2717) and "one transaction each"
       for migrations (11-repo-layout.md:1187) both require; the DBAPI's implicit-transaction mode
       would open a transaction of its own choosing around the first `INSERT` and commit it at a
       moment nothing here chose.
    3. `busy_timeout` FIRST, then `CREATE_PRAGMAS` when the file did not exist, then the remaining
       six `CONN_PRAGMAS`, then `INIT_PRAGMAS`. The interleaving is `CREATE_PRAGMAS`' docstring.
    4. `refuse_missing_fts5()`.
    5. Heal an oversized WAL (`heal_wal`).

    **Whether this is a create is OBSERVED, never asked.** `path.exists()` is read once before the
    connect, because that is the only moment the answer is knowable: after `sqlite3.connect` the
    file
    exists whatever it did before. A caller that wanted "refuse to create" gets it from the
    read-only
    ladder or from `mode=rw`, and neither is this function's job.

    `factory` is passed to `sqlite3.connect` untouched. It is the seam
    `test_the_pragmas_are_issued_in_the_order_the_plan_fixes` uses: a `sqlite3.Connection` subclass
    overriding `execute` records the REAL statement sequence a connection receives, which is the
    only
    test of a pragma order that can fail. `sqlite3.Connection` is a C type, so neither the class nor
    an instance accepts a monkeypatched method; `factory` is the DBAPI's own answer.

    `wal_heal_mb` defaults to `[store] wal_heal_mb`'s declared default, read from `config.KEYS` so
    the number has one home (07:2807, 15-observability.md:1806).

    A failure anywhere after the connect closes the connection before re-raising: an open that
    refused must leave no `Connection` behind, or INV-17's "the store thread is the only holder"
    becomes a claim about the happy path only.
    """
    refuse_old_sqlite(version_info)
    creating = not path.exists()
    connection = (
        sqlite3.connect(path, isolation_level=None)
        if factory is None
        else sqlite3.connect(path, isolation_level=None, factory=factory)
    )
    try:
        _apply(connection, CONN_PRAGMAS[:1])
        if creating:
            _apply(connection, CREATE_PRAGMAS)
        _apply(connection, CONN_PRAGMAS[1:])
        _apply(connection, INIT_PRAGMAS)
        refuse_missing_fts5(connection)
        heal_wal(connection, path, wal_heal_mb=wal_heal_mb)
    except BaseException:
        connection.close()
        raise
    return connection


class ReadonlyRung:
    """The two rungs of the `connect_readonly` ladder, as the query strings they are.

    07:2744-2748 prints the ladder itself:

    ```text
    a `-wal` sidecar exists      -> mode=ro
    no `-wal` sidecar            -> mode=ro&immutable=1
    ```

    A class of two constants rather than a `StrEnum` because `omniweave_core.model.enums` owns every
    closed domain that reaches disk and this one never does: it is a diagnostic label on a decision
    taken in memory, and a sixteenth `enum_val` domain for it would be a row nobody reads.
    """

    RO: Final = "mode=ro"
    RO_IMMUTABLE: Final = "mode=ro&immutable=1"


def readonly_target(path: Path) -> tuple[str, str]:
    """`(uri, rung)` for a read of `path`, choosing the rung by whether a `-wal` sidecar exists.

    Returns the URI `connect_readonly` will open and the `ReadonlyRung` label it chose, so a caller
    -- `ow doctor`, a freshness report, a test -- can see the decision without taking a connection.

    **Why the ladder exists, and why each rung is wrong in the other case** (07:2749-2757):

    * *"A plain read-write open **creates** the WAL sidecars and moves the very mtime the freshness
      check reads. A read that perturbs freshness is a read that makes gate 6
      (`source_edited_unindexed`) fire on its own observation."* So neither rung is a plain open.
    * *"`immutable=1` is correct only when there is no WAL, because it tells SQLite the file cannot
      change and therefore that no WAL need be consulted -- using it while a `-wal` exists returns
      pre-WAL data, which is a **silent stale read** rather than an error."* Measured on 3.43.1 that
      failure is total rather than partial: against a store whose only `CREATE TABLE` is still in
      the WAL, `mode=ro&immutable=1` reports `no such table`. Silent is the general case; the
      measurement is the extreme of it.

    The URI is built with `Path.as_posix()`, because a SQLite URI filename is URI-shaped on every
    platform and a Windows `\\` is not a URI separator.
    """
    rung = ReadonlyRung.RO if _wal_path(path).exists() else ReadonlyRung.RO_IMMUTABLE
    return f"file:{path.as_posix()}?{rung}", rung


def connect_readonly(
    path: Path,
    *,
    version_info: Sequence[int] | None = None,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open `path` for reading only, on the rung `readonly_target` chose, perturbing nothing.

    `READONLY_PRAGMAS` -- `CONN_PRAGMAS` minus `journal_mode` -- is issued rather than
    `CONN_PRAGMAS`, and that tuple's docstring carries the measurement and the reported defect.
    No `CREATE_PRAGMAS` (there is nothing to create), no `INIT_PRAGMAS` (`journal_size_limit`
    governs a WAL this connection will never write) and no heal (healing is a write).

    A missing file is a refusal rather than an empty store: `mode=ro` on a path that does not exist
    raises `sqlite3.OperationalError("unable to open database file")`, which names no path and no
    remedy, so it is translated. `OW_CORPUS_NOT_FOUND` (`OW-A-002`) is 18-api-sketch.md:166's code
    for the same condition at the `omniweave.corpus()` layer; that is a `SurfaceError` and this
    module is below that surface, so the raise here is the store's own `StoreError` and the surface
    layer re-frames it.
    """
    refuse_old_sqlite(version_info)
    if not path.exists():
        raise StoreError(
            f"no store at {path}: a read-only open never creates one, because a created file "
            f"would answer every freshness question with 'empty'",
            fix="ow index build",
        )
    uri, _rung = readonly_target(path)
    connection = (
        sqlite3.connect(uri, uri=True, isolation_level=None)
        if factory is None
        else sqlite3.connect(uri, uri=True, isolation_level=None, factory=factory)
    )
    try:
        _apply(connection, READONLY_PRAGMAS)
    except BaseException:
        connection.close()
        raise
    return connection


# --------------------------------------------------------------------------------------------
# 5. Heal-on-open, and the bulk-window marker.
# --------------------------------------------------------------------------------------------


def _wal_path(path: Path) -> Path:
    """`<path>-wal`, SQLite's own sidecar spelling (07:135)."""
    return path.with_name(path.name + "-wal")


def wal_bytes(path: Path) -> int:
    """The `-wal` sidecar's size, or 0 when there is none."""
    try:
        return _wal_path(path).stat().st_size
    except OSError:
        return 0


def heal_wal(connection: sqlite3.Connection, path: Path, *, wal_heal_mb: int | None = None) -> int:
    """TRUNCATE-checkpoint an oversized WAL at open. Returns the bytes reclaimed.

    07:2807: *"`[store] wal_heal_mb = 64` => heal an oversized WAL at every open"*, and
    15-observability.md:1806 names the condition it clears -- a WAL *"truncated by heal-on-open
    above
    `[store] wal_heal_mb = 64`"* left behind by a killed process. The measured leak with no heal is
    07's own table row: **25.6 GB across repeatedly-SIGKILLed sessions**.

    `wal_heal_mb = 0` disables it, matching every other `_mb` knob in `[store]`. The threshold is
    `>`, not `>=`: a WAL exactly at the limit is at the limit and not past it.

    **A `TRUNCATE` checkpoint here is not the section 10.5 rule against truncating.** 07:2836-2839
    forbids a truncate against an *active* writer -- *"a truncate checkpoint against an active
    writer
    wins the lock race and then blocks that writer for its whole backfill"*. This runs at open, on a
    connection that has issued no `BEGIN` and holds nothing, which is the *"parked barrier"* the
    same
    paragraph requires. A `SQLITE_BUSY` here means another process is mid-write, and the honest
    reaction is to leave its WAL alone: the exception is swallowed and 0 is returned, because a
    failed heal is a missed optimisation and a raised one would fail an open on a healthy store.
    """
    limit_mb = KEYS["store.wal_heal_mb"].default if wal_heal_mb is None else wal_heal_mb
    if not isinstance(limit_mb, int) or limit_mb <= 0:
        return 0
    before = wal_bytes(path)
    if before <= limit_mb * _MIB:
        return 0
    with suppress(sqlite3.Error):
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return max(0, before - wal_bytes(path))


def refuse_open_bulk_window(connection: sqlite3.Connection) -> None:
    """ST13: an open `index_state.bulk_window` marker REFUSES TO SERVE, naming `ow store repair`.

    07:2858-2861: *"`index_state.bulk_window` is written **before the first DDL**, and
    `fts_state = 'building'` with it. An open marker at store open **refuses to serve** (ST13,
    `OW-S-031`) and names `ow store repair`; a SIGKILL test asserts it."* 11-repo-layout.md:1334
    gives the consequence a query would otherwise suffer: *"secondary indexes and FTS triggers may
    be
    dropped, so a query would silently under-return"*. 15-observability.md:1517 is the same check as
    doctor row `D-04`.

    This is the store's analogue of `blobs.py`'s `cas/tmp/` startup sweep, and the difference is the
    point: a stray `cas/tmp/` entry is garbage that can be deleted, while a bulk window is a
    *missing
    index* that no sweep can reconstruct without the DDL. 07 section 2.2 fixes `ow store repair` as
    exactly four steps and *"only then is `index_state.bulk_window` cleared"*, so this function
    refuses and never repairs.

    A store with no `index_state` table has no marker and cannot be mid-bulk-window: `index_state`
    ships in `0003_index.sql`, so a file below that migration is a file no bulk window has ever
    opened. That case returns cleanly rather than raising, which is what lets this run on a
    partially-migrated file at all.

    **DEFECT -- `OW-S-031` has no symbol.** Four plan sites name the numeric (07:2859, 07:3195,
    11:1334, 15:1517) and none names an `OW_SCREAMING_SNAKE` symbol, so `codes.toml` -- which is
    seeded from the sites that bind a numeric to a symbol adjacently -- carries no row for it. The
    raise below therefore uses `StoreError`'s area default symbol `OW_STORE` and prints `OW-S-031`
    in the message, where it is at least greppable. The owed edit is a `codes.toml` row; inventing
    the symbol here and then adding it to the register would be claiming the plan ordered a name it
    never wrote.
    """
    marker = _index_state(connection, "bulk_window")
    if marker in (None, "", "0"):
        return
    raise StoreError(
        f"OW-S-031: this store has an open bulk window ({marker!r}). Non-UNIQUE secondary indexes "
        f"and the FTS triggers may be dropped, so every query would silently under-return; "
        f"refusing to serve",
        fix=_FIX_REPAIR,
    )


def _index_state(connection: sqlite3.Connection, key: str) -> str | None:
    """`index_state.v` for `key`; `None` when the key, or the whole table, is absent.

    `index_state` is created by `0003_index.sql`, two migrations after the first, so every reader of
    it has to survive its absence -- which is also why G27(b) anchors its single-home assertion at
    the END of the migration run and not after `0001_init.sql` (11-repo-layout.md:1196-1200).
    """
    try:
        row = connection.execute("SELECT v FROM index_state WHERE k = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else str(row[0])


# --------------------------------------------------------------------------------------------
# 6. The section 3.1 schema-compatibility ladder.
# --------------------------------------------------------------------------------------------


class SchemaAction:
    """What a reader does with a file it did not write. Four values, one per row of 07:283-291.

    `SERVE` -- read normally. `SERVE_READS_ONLY` -- serve reads and refuse writes. `MIGRATE` --
    migrate forward on an exclusive write open. `REFUSE` -- refuse at open. There is one table and
    no `--force` (07:281-282).
    """

    SERVE: Final = "serve"
    SERVE_READS_ONLY: Final = "serve_reads_only"
    MIGRATE: Final = "migrate"
    REFUSE: Final = "refuse"


def schema_action(
    file_major: int, file_minor: int, *, writable: bool, raise_on_refuse: bool = True
) -> str:
    """The 07 section 3.1 ladder, evaluated. Raises on the two refusing rows unless asked not to.

    Transcribed from the four-row table at 07:283-291, against this build's `SCHEMA` from
    `omniweave_core.contract` -- the only code home for the pair (ADR-9), which is why nothing here
    retypes `1`. The messages print `contract.SCHEMA_STRING` rather than interpolating the two
    constants into a `<major>.<minor>` f-string of their own, because ADR-9 decision 2 makes
    `contract` *the one site in the framework that formats the pair* and `test_contract.py` greps
    every `omniweave_core` source for a second one. The FILE's pair IS formatted inline: those are
    two integers read off disk, so they are data rather than this build's stamp.

    * file major **>** reader major -- refuse: `OW-S-030` / `OW_SCHEMA_AHEAD`, naming both versions
      and `pip install -U omniweave-core`. *"Silent misreading is the failure an operator cannot
      detect."*
    * file major **<** reader major -- migrate forward on an exclusive write open; a `mode=ro` open
      refuses and names `ow store migrate`, because *"a read must never mutate the file whose mtime
      the freshness check reads (section 10.3)"*. `writable` is what separates the two halves.
    * equal major, file minor **>** reader minor -- serve reads; unknown `[DER]` objects are ignored
      and unknown `[SOR]` columns are not selected. *"Writes refuse, because a writer that does not
      know a column cannot maintain its invariant."*
    * equal major, file minor **<** reader minor -- migrate forward, additive DDL only by definition
      of a minor bump.

    `raise_on_refuse=False` returns `SchemaAction.REFUSE` instead of raising, which is what
    `ow doctor` needs: a doctor reports every check and exits once.
    """
    if file_major > SCHEMA:
        if raise_on_refuse:
            raise StoreError(
                f"this store is at SCHEMA {file_major}.{file_minor} and this build reads "
                f"{SCHEMA_STRING}: refusing to open, because a reader that guessed at an "
                f"unknown major would misread it silently",
                symbol="OW_SCHEMA_AHEAD",
                fix=_FIX_UPGRADE,
            )
        return SchemaAction.REFUSE
    if file_major < SCHEMA:
        if writable:
            return SchemaAction.MIGRATE
        if raise_on_refuse:
            raise StoreError(
                f"this store is at SCHEMA {file_major}.{file_minor} and this build reads "
                f"{SCHEMA_STRING}: a read-only open never migrates, because a read must "
                f"not move the mtime the freshness check reads",
                fix=_FIX_MIGRATE,
            )
        return SchemaAction.REFUSE
    if file_minor > SCHEMA_MINOR:
        return SchemaAction.SERVE_READS_ONLY
    if file_minor < SCHEMA_MINOR:
        return SchemaAction.MIGRATE
    return SchemaAction.SERVE


# --------------------------------------------------------------------------------------------
# 7. The cross-process scoped lock `store.write`.
# --------------------------------------------------------------------------------------------


def process_create_time(pid: int) -> tuple[float, str]:
    """`(process_create_time, source)` for `pid`, from the standard library only.

    The third component of the `store.write` holder identity, and 07:2724-2726 says exactly what it
    is for: *"holder identity is `(host, pid, process_create_time)` -- the third component is what
    stops a recycled pid from looking like a live holder."*

    **There is no portable standard-library API for another process's start time, so this degrades
    explicitly.** What each platform gives:

    * **Linux** -- `/proc/<pid>`'s own inode carries the process's start time. `st_ctime` on that
      directory is the moment the kernel created it, which is the moment the process started.
      Source `"/proc"`.
    * **macOS, the BSDs, Windows** -- nothing. The answer lives behind `sysctl(KERN_PROC)` and
      `GetProcessTimes`, and reaching either needs `ctypes` against a platform ABI or a third-party
      dependency, which INV-2 forbids core outright. Source `"unavailable"`, value `0.0`.

    **The degradation costs the operator-facing message and not the correctness property**, and that
    is why it is acceptable rather than merely admitted. The recycled-pid question is answered by
    `FileScopedLock` with an OS-held advisory lock, which the kernel releases when the holder dies
    whatever its pid becomes afterwards -- strictly stronger than comparing a start time, because it
    cannot be fooled by a clock change either. `process_create_time` remains in the identity because
    `15-observability.md:1537`'s doctor row `D-24` prints it: *"a live `store.write` lock: prints
    holder host, pid, `process_create_time`, age"*. Where it reads `0.0` the source string says
    `unavailable` and the doctor line says so rather than printing a plausible zero.
    """
    try:
        return (Path(f"/proc/{pid}").stat().st_ctime, "/proc")
    except OSError:
        return (0.0, "unavailable")


@dataclass(frozen=True, slots=True)
class LockHolder:
    """Who holds a scoped lock: `(host, pid, process_create_time)` plus what a report needs.

    The triple is 07:2724-2726's and 02-architecture.md:746's. `process_create_time_source` is this
    module's addition and is not a second copy of anything: it records WHICH mechanism answered, so
    a `0.0` reads as "this platform cannot tell" rather than as "the epoch". `acquired_ns` is a wall
    clock supplied by the lock's caller, and `age_s` against another supplied wall clock is what
    `StoreBusy.holder`'s third component is (`errors.py:247`, 18-api-sketch.md:450).
    """

    host: str
    pid: int
    process_create_time: float
    process_create_time_source: str
    acquired_ns: int

    def age_s(self, now_ns: int) -> float:
        """Seconds since `acquired_ns`, against a wall clock the caller reads.

        Negative would mean the holder's clock is ahead of ours, which on a shared mount is
        possible; it is clamped to 0.0 rather than reported, because a negative age in an error
        message reads as a bug in the message and the fact it would carry is "the clocks disagree",
        which is not what this error is about.
        """
        return max(0.0, (now_ns - self.acquired_ns) / 1e9)

    def as_json(self) -> str:
        """The lock file's payload: sorted keys, no spaces, one line.

        Sorted and separator-pinned because the file is read by another process and by a human, and
        a byte-stable rendering is what makes "the lock file changed" a meaningful observation.
        """
        return json.dumps(
            {
                "host": self.host,
                "pid": self.pid,
                "process_create_time": self.process_create_time,
                "process_create_time_source": self.process_create_time_source,
                "acquired_ns": self.acquired_ns,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class ScopedLock(Protocol):
    """The lock the store thread takes before a write transaction. Three methods.

    A local Protocol, not an import, and **02-architecture.md:746 is why this is a Protocol here at
    all**: that line homes the lock in `omniweave_core.locks` -- *"the cross-process scoped lock
    `store.write` in `omniweave_core.locks`: `O_CREAT|O_EXCL` plus `flock`, holder identity
    `(host, pid, process_create_time)`"* -- and `locks.py` does not exist yet
    (11-repo-layout.md:198 lists it beside `blobs.py`, `clock.py` and `work.py`). So this module
    declares the shape it needs and ships `FileScopedLock` as the default implementation, exactly as
    `model/rebind.py` declares two local Protocols over the store rather than importing one.

    **When `omniweave_core.locks` lands, `FileScopedLock` MOVES there and this Protocol stays.**
    That
    is the whole point of the split: the store thread depends on the shape, the shape is three
    methods, and INV-21's one-home rule is then satisfied by deleting one class from this file. The
    move is recorded in this wave's return value as an owed edit rather than left to be
    rediscovered.
    """

    @property
    def name(self) -> str:
        """The lock's scope name -- `store.write` for the only one this wave has."""
        ...

    def acquire(self, *, wait_ms: int) -> None:
        """Take the lock, waiting up to `wait_ms`; raise `StoreBusy` (exit 7) past it."""
        ...

    def release(self) -> None:
        """Give it up. Idempotent: releasing a lock this object does not hold is not an error."""
        ...

    def holder(self) -> LockHolder | None:
        """Who holds it right now, or `None` when nobody does."""
        ...


_LOCK_BYTE: Final = 1 << 20
"""The byte offset Windows byte-range locking uses, and it is NOT 0.

Measured on Windows 11: `msvcrt.locking` at offset 0 makes the locked byte unreadable to every
handle, this process's included, so a contender trying to READ the holder's identity out of the lock
file gets `PermissionError` and reports "no holder" for a lock that is very much held -- turning the
`StoreBusy` message that names host, pid and age (07:2872) into `?` and `0`. Locking one byte a
megabyte past any plausible payload keeps the identity readable while the lock itself stays
exclusive; Windows permits a range beyond end-of-file, which is what makes the offset free.

`fcntl.flock` needs no offset: it locks the open file description as a whole and blocks no read.
"""


def _take_advisory(fd: int) -> bool | None:
    """Try to take an OS advisory lock on `fd`. `True`/`False` taken or refused, `None` unknowable.

    The liveness half of 02-architecture.md:746's `O_CREAT|O_EXCL` plus `flock`. An advisory lock is
    the one liveness signal that cannot be wrong: the kernel drops it when the holding process dies,
    however it died and whatever pid is issued next. `None` means neither `fcntl` nor `msvcrt` is
    importable, which is not a platform this framework has met; the caller degrades to "assume the
    holder is live", which errs towards refusing a write rather than towards two writers.
    """
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    if _msvcrt is not None:
        os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
        try:
            _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    return None  # pragma: no cover -- no platform in the support matrix reaches this.


def _drop_advisory(fd: int) -> None:
    """Release an advisory lock taken by `_take_advisory`, tolerating a platform that has none."""
    if _fcntl is not None:
        with suppress(OSError):
            _fcntl.flock(fd, _fcntl.LOCK_UN)
    elif _msvcrt is not None:
        os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
        with suppress(OSError):
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)


@dataclass(eq=False)
class FileScopedLock:
    """`store.write` as a lock FILE plus an advisory lock on it. The shipped `ScopedLock`.

    02-architecture.md:746 fixes both mechanisms and this class is exactly those two:

    1. **`O_CREAT|O_EXCL`** is the mutual exclusion. Creating the file is the atomic act; the winner
       writes its `LockHolder` payload into it.
    2. **The advisory lock** (`fcntl.flock`, or `msvcrt.locking` on Windows) is the STALENESS test.
       A holder that was SIGKILLed leaves the file behind, and the file alone cannot distinguish a
       live holder from a dead one -- which is the same question `process_create_time` exists to
       answer and which the kernel answers better: if a contender can take the advisory lock on an
       existing file, the writer of that file is gone, and the file is broken and retried.

    **The wait is passed per call and never configured** (07:2726-2729). `acquire(wait_ms=...)`
    polls
    at `_POLL_MS` until the budget is spent and then raises `StoreBusy`, whose `EXIT = 7` and whose
    `.holder` is `(host, pid, age_s)` -- errors.py:246-261 and 18-api-sketch.md:450, *"the only code
    for which a bare retry is correct"*. **Never a silent retry loop** (07:2872).

    `now_ns` is a wall clock the caller supplies, because `time.time` is banned in library code
    (02-architecture.md:392). It is read twice: once to stamp `acquired_ns` into the payload, and
    once per refusal to compute the holder's age. A test supplies a counter and gets a deterministic
    age.

    `path` is the lock file. It is NOT `omniweave.index.lock` -- that is the committed corpus
    receipt
    (02-architecture.md:1168) and has nothing to do with this. A caller names
    `<cache_root>/store.write.lock` or equivalent; this class takes the path and no policy.
    """

    path: Path
    now_ns: Callable[[], int]
    name: str = STORE_WRITE_LOCK
    host: str = field(default_factory=socket.gethostname)
    pid: int = field(default_factory=os.getpid)
    _fd: int | None = field(default=None, init=False, repr=False)

    _POLL_MS: ClassVar[int] = 25
    """The poll interval while waiting. `ClassVar`, not `Final`: `dataclasses` excludes only
    `ClassVar`, so a bare `Final = 25` in a dataclass body becomes a seventh FIELD with a default
    -- measured, and the reason this annotation is spelled the long way."""

    def identity(self) -> LockHolder:
        """This process's `LockHolder`, stamped with the caller's clock."""
        created, source = process_create_time(self.pid)
        return LockHolder(
            host=self.host,
            pid=self.pid,
            process_create_time=created,
            process_create_time_source=source,
            acquired_ns=self.now_ns(),
        )

    def holder(self) -> LockHolder | None:
        """Read the lock file's payload, or `None` when there is no live holder.

        A file whose payload does not parse is reported as a holder with `pid = 0` rather than as no
        holder, because "there is a lock file I cannot read" must not resolve to "the lock is free".
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return LockHolder(
            host=str(data.get("host", "?")),
            pid=int(data.get("pid", 0)),
            process_create_time=float(data.get("process_create_time", 0.0)),
            process_create_time_source=str(data.get("process_create_time_source", "unavailable")),
            acquired_ns=int(data.get("acquired_ns", 0)),
        )

    def acquire(self, *, wait_ms: int = INTERACTIVE_WAIT_MS) -> None:
        """Take the lock within `wait_ms`, or raise `StoreBusy` naming host, pid and age.

        The loop is: try `O_CREAT|O_EXCL`; on `FileExistsError` try to break a dead holder's file;
        sleep `_POLL_MS`; repeat until the budget is spent. `wait_ms = 0` is one attempt and no
        sleep, which is what a caller that has already enqueued its work wants when it is only
        probing.

        Re-entering on a lock this object already holds is a usage error, not a no-op: two
        `acquire()` calls and one `release()` would leave the file behind with nobody watching it.
        """
        if self._fd is not None:
            raise StoreError(
                f"{self.name} is already held by this object; a scoped lock is not reentrant, "
                f"because the second release would be the one that mattered",
                fix="release the lock before acquiring it again",
            )
        deadline = time.monotonic_ns() + wait_ms * 1_000_000
        while True:
            if self._try_create():
                return
            if self._break_if_dead() and self._try_create():
                return
            if time.monotonic_ns() >= deadline:
                break
            time.sleep(self._POLL_MS / 1000)
        self._refuse(wait_ms)

    def _try_create(self) -> bool:
        """One `O_CREAT|O_EXCL` attempt; on success write the payload and hold the descriptor."""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        except FileExistsError:
            return False
        except OSError as error:
            raise StoreError(
                f"cannot create the {self.name} lock at {self.path}: {error}",
                fix="check that the cache root is writable",
            ) from error
        os.write(fd, self.identity().as_json().encode("utf-8") + b"\n")
        _take_advisory(fd)
        self._fd = fd
        return True

    def _break_if_dead(self) -> bool:
        """Unlink a lock file whose writer is gone, proved by taking the advisory lock on it.

        Returns whether it broke one, so `acquire` retries the `O_CREAT|O_EXCL` immediately rather
        than sleeping a poll interval -- which is what makes `acquire(wait_ms=0)` against a stale
        file succeed instead of refusing.

        `taken is None` means the platform offers no advisory lock at all, in which case the file is
        left alone: refusing a write is recoverable and two writers are not.
        """
        try:
            fd = os.open(self.path, os.O_RDWR)
        except OSError:
            return False
        try:
            if _take_advisory(fd) is not True:
                return False
            _drop_advisory(fd)
        finally:
            os.close(fd)
        try:
            self.path.unlink()
        except OSError:
            return False
        return True

    def _refuse(self, wait_ms: int) -> None:
        """Raise `StoreBusy` (exit 7) naming host, pid and age. Never a silent retry."""
        held = self.holder()
        host = held.host if held else "?"
        pid = held.pid if held else 0
        age = held.age_s(self.now_ns()) if held else 0.0
        raise StoreBusy(
            f"another writer holds {self.name}: host {host}, pid {pid}, age {age:.1f}s; "
            f"waited {wait_ms} ms",
            holder=(host, pid, age),
            symbol="OW_STORE_BUSY",
            fix=f"wait for {host}:{pid} to finish, or `ow store repair` if it is gone",
        )

    def release(self) -> None:
        """Drop the advisory lock, close the descriptor and unlink the file. Idempotent."""
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        _drop_advisory(fd)
        os.close(fd)
        with suppress(OSError):
            self.path.unlink()

    def __enter__(self) -> FileScopedLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


# --------------------------------------------------------------------------------------------
# 8. The store thread, its bounded queue and the transaction primitive.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unit:
    """One transaction, as the closure that runs inside it. 07:2717's "one transaction per unit".

    `run` receives the store thread's `Connection` and returns whatever the submitter wants back. It
    executes between a `BEGIN IMMEDIATE` and a `COMMIT`, and **if it raises, the transaction rolls
    back and the exception reaches the submitter** -- not a `False`, not a log line. 08-runtime.md's
    rule for the one boolean the store boundary does return says why: *"a boolean that means both
    'someone else won' and 'your driver is wrong' turns a bug into a no-op"* (08:2489-2494).

    `cost_class` is one of `work.cost_class`'s three (`free` / `local_compute` / `billed_api`), and
    a
    member of `DURABLE_COST_CLASSES` selects ST14's `synchronous = FULL` before the `BEGIN`. It is a
    `str` because `CostClass` is P4's type and the hook ships before the enum (07:2735-2740).

    `wait_ms` is the `store.write` budget THIS unit pays -- `INTERACTIVE_WAIT_MS` by default,
    `BATCH_WAIT_MS` for a watcher batch. Per call, never global (07:2726-2729).

    `on_commit` fires on the store thread with the connection still inside the transaction,
    immediately before `COMMIT`. It is the hook ST14's test uses -- *"a test asserts the pragma
    value
    **at commit time**"* (07:2737) -- and the hook the reservation-commit and spend-row writes of
    07:2731-2733 will use when P4 lands, since those must land in the same transaction as the
    derived rows. A hook that raised would abort the unit, which is the desired coupling.

    `name` is what an error message and a log line call this unit. Free-form: the plan names units
    by operation (`op.identify`, `op.converge`), and the store has no register of them.
    """

    name: str
    run: Callable[[sqlite3.Connection], object]
    cost_class: str = "free"
    wait_ms: int = INTERACTIVE_WAIT_MS
    on_commit: Callable[[sqlite3.Connection], None] | None = None

    @property
    def durable(self) -> bool:
        """Whether this unit commits at `synchronous = FULL` (ST14)."""
        return self.cost_class in DURABLE_COST_CLASSES


class _Ticket:
    """One submitted `Unit` and the slot its outcome lands in. Internal to `StoreThread`.

    A `threading.Event` plus two fields rather than a `concurrent.futures.Future`, because a Future
    carries an executor's cancellation and callback machinery that this queue deliberately does not
    have: a transaction closure that has reached the store thread cannot be cancelled, and
    pretending
    otherwise would be an API that lies.
    """

    __slots__ = ("done", "error", "unit", "value")

    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.done = threading.Event()
        self.value: object = None
        self.error: BaseException | None = None

    def result(self, timeout_s: float | None = None) -> object:
        """Block until the store thread has finished this unit, then return or re-raise.

        The exception is re-raised on the SUBMITTER's thread, which is the property the task's
        "a closure that raises leaves no partial rows and the exception reaches the submitter"
        names.
        """
        if not self.done.wait(timeout_s):
            raise StoreError(
                f"the store thread did not finish unit {self.unit.name!r} within {timeout_s}s",
                fix="check whether the store thread is blocked on the store.write lock",
            )
        if self.error is not None:
            raise self.error
        return self.value


class StoreThread:
    """The ONE holder of a `Connection` in this process. Every write is a `Unit` on its queue.

    INV-17, 07:2722-2723: *"The store thread is the only holder of a `Connection` in a process.
    Every
    write reaches it as a transaction closure on a bounded queue. This upgrades the module rule into
    a module-**and**-thread rule and deletes the cross-thread-connection failure class outright."*

    **The thread opens the connection itself, and that is what makes the claim structural.** The
    constructor takes an `opener`, not a `Connection`, and calls it as the thread's first act. With
    `sqlite3`'s default `check_same_thread=True`, the connection is then bound BY THE DRIVER to the
    only thread that is allowed to touch it: a smuggled reference used elsewhere raises
    `sqlite3.ProgrammingError` naming both thread ids, before any statement is prepared. Handing a
    ready-made `Connection` in would have forfeited that, since the object would already be bound to
    whoever built it. `StoreThread.connection` adds the store's own refusal on top, so the common
    mistake -- reading the attribute from the main thread -- fails with a `StoreError` that names
    the
    rule rather than with a driver message about thread ids.

    **Enqueue before attempting the lock** (07:2730-2733). `submit()` puts the `Unit` on the queue
    and returns; the store thread takes `store.write` when it DEQUEUES, at that unit's own
    `wait_ms`.
    So *"an interactive `ow add` writes its `work` row in a short transaction and returns; it does
    not sit for 60 s behind a batch writer"*. The lock is taken and released per unit, which is the
    granularity 07:2886 fixes: *"the batch takes `store.write` **once** per batch, not once per
    file"* -- one batch being one unit.

    **The queue is bounded** at `STORE_QUEUE_BOUND` and a full queue blocks the submitter, then
    raises; see that constant's docstring for why never a drop.

    Use it as a context manager. `__exit__` drains what is already queued, stops the thread and
    closes the connection, in that order, so a submitter that has already been told "accepted"
    always gets its transaction.
    """

    def __init__(
        self,
        opener: Callable[[], sqlite3.Connection],
        *,
        lock: ScopedLock | None = None,
        bound: int = STORE_QUEUE_BOUND,
        name: str = "ow-store",
    ) -> None:
        if bound < 1:
            raise StoreError(
                f"the store queue bound is {bound}; a queue that can hold nothing is a deadlock",
                fix="pass bound >= 1",
            )
        self._opener = opener
        self._lock = lock
        self._name = name
        self._queue: queue.Queue[_Ticket | None] = queue.Queue(maxsize=bound)
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._ready = threading.Event()
        self._connection: sqlite3.Connection | None = None
        self._open_error: BaseException | None = None
        self._closing = False

    # -- lifecycle ---------------------------------------------------------------------------

    def start(self) -> StoreThread:
        """Start the thread and block until it has opened the connection, or re-raise its failure.

        Blocking here is what makes `connect()`'s refusals -- `MIN_SQLITE`, FTS5, a schema ahead --
        reach the caller of `start()` rather than dying on a background thread with nobody watching.
        """
        self._thread.start()
        self._ready.wait()
        if self._open_error is not None:
            raise self._open_error
        return self

    def close(self, *, timeout_s: float = 30.0) -> None:
        """Drain the queue, stop the thread, close the connection. Idempotent."""
        if self._closing:
            return
        self._closing = True
        if self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout_s)

    def __enter__(self) -> StoreThread:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- ownership ---------------------------------------------------------------------------

    @property
    def owns_current_thread(self) -> bool:
        """Whether the caller IS the store thread, and may therefore touch the connection."""
        return threading.current_thread() is self._thread

    @property
    def connection(self) -> sqlite3.Connection:
        """The connection -- readable ONLY from the store thread.

        Any other thread gets a `StoreError` naming both threads and INV-17. This is the store's own
        refusal, one layer above `sqlite3`'s `check_same_thread` guard, and the two are not
        redundant: this one fires on the ATTRIBUTE READ, before a reference can escape to be used
        later or stored somewhere, and it names the rule instead of a pair of thread ids.
        """
        if not self.owns_current_thread:
            raise StoreError(
                f"the store connection belongs to thread {self._name!r} and this is "
                f"{threading.current_thread().name!r}: INV-17 makes the store thread the only "
                f"holder of a Connection in a process, so submit a Unit instead",
                fix="StoreThread.run(Unit(...))",
            )
        if self._connection is None:  # pragma: no cover -- unreachable once `start()` returned.
            raise StoreError("the store connection is not open", fix="StoreThread.start()")
        return self._connection

    # -- submission --------------------------------------------------------------------------

    def submit(self, unit: Unit, *, enqueue_timeout_s: float | None = None) -> _Ticket:
        """Put `unit` on the queue and return its ticket, WITHOUT waiting for the lock.

        This is 07:2730's *"enqueue before attempting the lock"* in one line: the return happens as
        soon as the unit is queued, and the `store.write` acquisition is the store thread's problem.

        A full queue blocks up to `enqueue_timeout_s` (forever when `None`) and then raises rather
        than dropping. `STORE_QUEUE_BOUND` argues the choice.
        """
        if self._closing:
            raise StoreError(
                f"the store thread is closing; unit {unit.name!r} was not accepted",
                fix="submit before close()",
            )
        ticket = _Ticket(unit)
        try:
            self._queue.put(ticket, timeout=enqueue_timeout_s)
        except queue.Full as error:
            raise StoreError(
                f"the store queue is full ({self._queue.maxsize} units) and unit {unit.name!r} "
                f"waited {enqueue_timeout_s}s; refusing rather than dropping a transaction",
                fix="reduce write concurrency, or raise the StoreThread bound",
            ) from error
        return ticket

    def run(self, unit: Unit, *, timeout_s: float | None = None) -> object:
        """`submit()` then wait. The ordinary way to write, and the shape `Store.complete()`
        needs."""
        return self.submit(unit).result(timeout_s)

    # -- the thread body ---------------------------------------------------------------------

    def _serve(self) -> None:
        """Open the connection, then apply units until a `None` sentinel arrives."""
        try:
            self._connection = self._opener()
        except BaseException as error:  # delivered to `start()`, never swallowed.
            self._open_error = error
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                self._apply(item)
        finally:
            self._connection.close()

    def _apply(self, ticket: _Ticket) -> None:
        """One unit: take the lock, run the transaction, deliver the outcome, release the lock."""
        try:
            if self._lock is not None:
                self._lock.acquire(wait_ms=ticket.unit.wait_ms)
            try:
                ticket.value = self._transact(ticket.unit)
            finally:
                if self._lock is not None:
                    self._lock.release()
        except BaseException as error:  # re-raised on the submitter's thread.
            ticket.error = error
        finally:
            ticket.done.set()

    def _transact(self, unit: Unit) -> object:
        """`synchronous`, `BEGIN IMMEDIATE`, the closure, `on_commit`, `COMMIT`. Rollback on raise.

        `BEGIN IMMEDIATE` and not `BEGIN`: a deferred write transaction takes its write lock at the
        first write statement, so two writers that both read first would discover the conflict
        mid-transaction and one would get `SQLITE_BUSY` after doing work. `IMMEDIATE` takes the
        RESERVED lock up front, which is the same "fail early or not at all" shape `store.write`
        gives across processes. `BEGIN DEFERRED` belongs to the reader and is `snapshot()`'s.

        **`synchronous` is set BEFORE the `BEGIN`** (ST14, 07:2736) and not inside it, because
        `PRAGMA synchronous` inside a transaction is a documented no-op -- the very shape 0001's
        header records for `foreign_keys`.
        """
        connection = self.connection
        target = "FULL" if unit.durable else "NORMAL"
        connection.execute(f"PRAGMA synchronous = {target}")
        connection.execute("BEGIN IMMEDIATE")
        try:
            value = unit.run(connection)
            if unit.on_commit is not None:
                unit.on_commit(connection)
        except BaseException:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
        return value


# --------------------------------------------------------------------------------------------
# 9. `snapshot()` -- one `BEGIN DEFERRED` for the whole query.
# --------------------------------------------------------------------------------------------


def _snapshot_ms(requested: int | None) -> int:
    """The effective deadline: the request (or `[retrieval] snapshot_ms`) clamped BELOW the ceiling.

    07:2789-2793: *"`MAX_SNAPSHOT_MS = 5_000` is the ceiling in `limits.py`; `[retrieval]
    snapshot_ms` clamps below it, default 2,000."* The default is read from `config.KEYS` and the
    ceiling from `limits`, so neither number is retyped here.
    """
    default = KEYS["retrieval.snapshot_ms"].default
    want = default if requested is None else requested
    if not isinstance(want, int) or want < 1:
        raise StoreError(
            f"snapshot_ms is {want!r}; a snapshot deadline is a positive number of milliseconds",
            fix="[retrieval] snapshot_ms = 2000",
        )
    return min(want, MAX_SNAPSHOT_MS)


@contextmanager
def snapshot(
    connection: sqlite3.Connection,
    *,
    snapshot_ms: int | None = None,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> Iterator[Snapshot]:
    """One `BEGIN DEFERRED` for the whole query, opened by its own first read. ST2, 07:2758-2799.

    **The two statements are one mechanism and their order is the mechanism** (07:2777-2782):
    *"A `BEGIN DEFERRED` does not actually acquire the read snapshot until the first statement, so
    `snapshot()` issues `BEGIN DEFERRED` followed immediately by
    `SELECT v FROM index_state WHERE k='generation'` -- one row, which both opens the snapshot and
    populates `Snapshot.generation` from inside it. Without that first read, two Channels could
    still
    straddle a commit."* So the generation read is not a convenience: it is what makes the
    transaction real, and it must be the FIRST statement after the `BEGIN`. `corpus_id` and `schema`
    are read after it, inside the now-open snapshot, where they are as stable as the generation is.

    **The deadline is a WAL-valve safety parameter, not a UX parameter** (07:2789-2793). A held read
    transaction pins the WAL, which is the condition that produced 22 GB of WAL and exit 137 in
    codegraph, so exceeding `min(snapshot_ms, MAX_SNAPSHOT_MS)` aborts with `OW-S-010` /
    `OW_SNAPSHOT_EXPIRED` and `verdict = degraded`. Two mechanisms enforce it and both are needed:

    * a `threading.Timer` calls `Connection.interrupt()`, which stops a statement that is running.
      Measured on 3.43.1, the interrupt surfaces as `sqlite3.OperationalError` with
      `sqlite_errorname == "SQLITE_INTERRUPT"`, and it is NOT sticky -- an interrupt that fires
      while
      no statement is running is discarded by the next one.
    * so the elapsed time is checked again on exit. That is the half that catches a body which spent
      its budget in Python between two cheap statements, which the interrupt cannot see at all.

    `monotonic_ns` is a parameter so a test can spend the budget without spending the wall time; the
    default is the one clock library code may read, because a duration is not an ambient fact.

    `vec_attached` is `True` when a schema named `vec` is attached to this connection. 07:2801-2803
    adds a second condition -- *"whether the sidecar was present **and** its `corpus_id` matched"*
    --
    which belongs to whoever ATTACHes the sidecar, since a mismatch means *"the sidecar is ignored,
    not read"* and an ignored sidecar is a sidecar that was never attached. Nothing in this wave
    attaches one, so the field reports the attach state and the matcher's contract is recorded here
    for the wave that adds it.

    The transaction ends in `ROLLBACK`, always. A read transaction has nothing to commit, and
    `COMMIT` on one differs from `ROLLBACK` only in implying that it might have.
    """
    budget_ms = _snapshot_ms(snapshot_ms)
    opened_ns = monotonic_ns()
    connection.execute("BEGIN DEFERRED")
    expired = threading.Event()

    def _interrupt() -> None:
        expired.set()
        connection.interrupt()

    timer = threading.Timer(budget_ms / 1000, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        generation = _require_index_state(connection, "generation")
        state = Snapshot(
            token=connection,
            generation=int(generation),
            corpus_id=_index_state(connection, "corpus_id") or "",
            schema=_schema_major(connection),
            vec_attached=_vec_attached(connection),
            opened_ns=opened_ns,
        )
        yield state
        _refuse_expired(expired, opened_ns, monotonic_ns(), budget_ms)
    except sqlite3.Error as error:
        if getattr(error, "sqlite_errorname", "") == INTERRUPTED or expired.is_set():
            raise _expired(budget_ms) from error
        raise
    finally:
        timer.cancel()
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")


def _refuse_expired(expired: threading.Event, opened_ns: int, now_ns: int, budget_ms: int) -> None:
    """Raise `OW-S-010` when the snapshot outlived its budget, whether or not a statement
    noticed."""
    if expired.is_set() or (now_ns - opened_ns) > budget_ms * 1_000_000:
        raise _expired(budget_ms)


def _expired(budget_ms: int) -> StoreError:
    """`OW-S-010` / `OW_SNAPSHOT_EXPIRED`, with the reason the deadline is not negotiable."""
    return StoreError(
        f"the read snapshot outlived its {budget_ms} ms budget and was interrupted: a held read "
        f"transaction pins the WAL, so the deadline is a WAL-valve safety parameter and the "
        f"query is degraded rather than served late",
        symbol="OW_SNAPSHOT_EXPIRED",
        fix="[retrieval] snapshot_ms, or narrow the query",
    )


def _require_index_state(connection: sqlite3.Connection, key: str) -> str:
    """`index_state.v` for `key`, raising rather than returning `None`.

    `snapshot()` uses this and `refuse_open_bulk_window` uses the forgiving `_index_state`, and the
    difference is which question is being asked. A missing `bulk_window` key means no bulk window; a
    missing `generation` key means the store has no `index_state` row the whole isolation guarantee
    is built on, and serving a query against it would report `generation = 0` for a store that has
    one.
    """
    value = _index_state(connection, key)
    if value is None:
        raise StoreError(
            f"index_state has no {key!r} row: this store has not finished its migrations, so a "
            f"snapshot has no generation to be consistent with",
            fix=_FIX_MIGRATE,
        )
    return value


def _schema_major(connection: sqlite3.Connection) -> int:
    """`index_state.schema`'s MAJOR, as `Snapshot.schema`'s `int`.

    `index_state.schema` holds `<major>.<minor>` and is the only place on disk that holds it
    (07:275-281, ADR-9). `Snapshot.schema` is an `int` while `IndexCaps.schema` is the string
    (07:3273) -- *"two fields, two shapes, both transcribed as printed"* (types.py) -- so the split
    happens here, at the read, and neither field is derived from the other.
    """
    raw = _index_state(connection, "schema")
    if raw is None:
        return 0
    head = raw.split(".", 1)[0]
    return int(head) if head.isdigit() else 0


def _vec_attached(connection: sqlite3.Connection) -> bool:
    """Whether a schema named `vec` is attached (07:135, ST3's `index.vec.owstore`)."""
    return any(str(row[1]) == "vec" for row in connection.execute("PRAGMA database_list"))
