"""The crash matrix: SIGKILL at every statement boundary in `Store.complete()`, then converge.

This module is `ow test crash-matrix`'s library half -- 16-roadmap.md:445 spells P2's exit line
`uv run ow test crash-matrix --statement-boundaries all`, `ow` is P7's (16 section 10) and
`crash_matrix()` below is the function that verb wires. Its CI half is `tools/gate_crash.py`,
which is G21's runner: `tools/gates.toml`'s G21 row asserts *"kill-9 at three points; `ow
resume`; store equals an uninterrupted run"* in the `crash` job at a 240 s budget, on PR and
nightly, `nightly_note = "full matrix"`.

## What the matrix verifies, in one sentence that is not this module's

07-store-and-retrieval.md:2730-2733: *"`Store.complete()` is the only mutation entry point on the
queue boundary, and one unit's derived rows, its `work` transition, its `dep` rows, its
reservation commit and its spend row commit **together or not at all**."* 17-risks.md:861 says
what that sentence is worth without this file: the matrix is *"the only evidence that INV-17's
'commit together' claim is real"*.

## Why the process control is NOT here

`subprocess` is banned in library code (02-architecture.md:392, enforced as an `ast` check by
`tools/gate_semgrep.py`'s `omniweave-no-subprocess-outside-toolchain-and-host-subproc`) and
`packages/*/src/**` is that ban's scope. A real SIGKILL therefore lives in `tools/gate_crash.py`
-- the parent that spawns and kills -- and in this module's test file; what lives here is
everything that is not process control:

* the boundary ENUMERATION, taken from `queue.complete_boundaries()` and never by parsing source;
* the KILL HOOK -- a `sqlite3` trace callback armed on the store thread, which fires immediately
  before each statement of `complete()`'s transaction and therefore names the boundary the
  process is standing on;
* the DERIVE and RESUME paths, which are what `ow resume` will call;
* the COMPARISON, which is byte-for-byte over the `.owdoc` export plus a fingerprint of the
  runtime rows the export cannot see.

`tools/` is not library code and may import `subprocess`; `tools/gate_semgrep.py:26-37` takes
exactly that reading for itself. The split is stated rather than assumed, because the alternative
-- one module that both drives the store and kills processes -- would put a banned import under
`src/` and make G8 and G24 red for a test harness's convenience.

## The kill hook, and why an in-process kill is a faithful model of SIGKILL

`sqlite3.Connection.set_trace_callback` fires **before** each statement runs, so parking or
aborting inside it leaves the transaction standing exactly at a statement boundary. Two shapes
use it:

* **`tools/gate_crash.py`'s child** parks in the callback and the parent sends the real signal.
  On POSIX that is `SIGKILL`; on Windows `Popen.kill()` is `TerminateProcess`, which -- like
  `SIGKILL` and unlike `SIGTERM` -- cannot be caught, handled or ignored, and runs no `atexit`
  hook, no `__del__` and no `Connection.close()`. What matters to a store is whether the dying
  process gets to flush or roll back, and neither call gives it the chance, so the Windows cell
  tests the same property. What Windows does not reproduce is a signal delivered by the kernel
  mid-`fsync`; that is a durability question about `synchronous = FULL` (ST14) rather than about
  atomicity, and it is not what this matrix measures.
* **`simulate_kill_at()`** calls `Connection.interrupt()` from inside the callback, which raises
  `SQLITE_INTERRUPT` out of the pending statement. `sqlite.py`'s `_transact` rolls back on any
  raise, so what a reopened store finds is identical to what it finds after a pre-COMMIT SIGKILL:
  the transaction's frames were never committed. It is a MODEL and is labelled one -- it leaks no
  `-wal` and leaves no stale `-shm` -- which is why `tools/gate_crash.py` does the real thing and
  this exists so the harness's own tests can run forty cycles inside a unit-test budget.

## The eight fixtures, and the forty boundaries

16-roadmap.md:422 prices W2.9 at *"~40 statement boundaries at a scripted kill-and-verify cycle
each; DataFlow's eight checkpoint failure modes are the fixture list"*, and 17-risks.md:861
repeats the eight. `CHECKPOINT_FAILURE_MODES` transcribes them and `SCENARIOS` is one scenario
per mode, each with a two-`dep` plan: one `work_transition` plus two `dep_insert` statements is
three statements, hence five boundaries (`len(plan) + 2`), hence **forty** across the eight. That
is 16:422's "~40", arrived at from its own two numbers rather than chosen.

## Stdlib only (INV-2 / G1); no clock, no ids, no `random`

`now_ns`, `now_ms`, the worker identity, the generation and the sampling salt are all parameters.
11-repo-layout.md:2185 fixes the rule the three-point selection obeys -- *"Sampling is blake2b.
Determinism is a gate, not a habit."* -- so `kill_points()` is a keyed `blake2b` over the boundary
names and reports which three it drew. `import sqlite3` is legal here because this file is under
`store/`, where pyproject.toml's per-file-ignore covers TID251 (INV-17); nothing here connects,
and every connection comes from `store.sqlite`.

Tier T5 (13-quality.md:252): the soak tier runs *"`ow test crash-matrix` at every statement
boundary in `Store.complete()`"*, which is `--all`; G21's PR cell runs three points.

Specified in 16-roadmap.md:422 and :436-445, 17-risks.md:861, 13-quality.md:252,
07-store-and-retrieval.md:2730-2733, :2807 and :2859-2866, 01-principles.md:1092 (AP-5) and
11-repo-layout.md section 6.4's G21 row.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from omniweave_ports.types import UnitRef

from omniweave_core.archive.owdoc import BlockExport, DocHeader, export
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import StoreError
from omniweave_core.model import (
    Capabilities,
    Kind,
    Layer,
    Method,
    OsKind,
    PageKind,
    Quote,
    Trust,
)
from omniweave_core.model.block import Addr, Block, BlockDraft, BlockId, Cite
from omniweave_core.model.records import DocRecord, PageRecord
from omniweave_core.model.spans import OriginNone
from omniweave_core.operator import (
    CACHE_KEY_HEX_LEN,
    OperatorIdentity,
    Outcome,
    StepMetrics,
    StepResult,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.queue import (
    SqliteStore,
    Statement,
    StepResultView,
    complete_boundaries,
    dep_statements,
)

__all__ = [
    "AFTER_BEGIN",
    "AFTER_COMMIT",
    "CHECKPOINT_FAILURE_MODES",
    "FIXTURE_CACHE_KEY",
    "FIXTURE_DOC_KEY",
    "FIXTURE_GEN",
    "FIXTURE_LEASE_MS",
    "FIXTURE_URI",
    "FIXTURE_WORKER",
    "MATRIX_SALT",
    "PR_POINTS",
    "SCENARIOS",
    "SHIPPED_MIGRATIONS",
    "WORK_FINGERPRINT_COLUMNS",
    "BoundaryResult",
    "CheckpointFailureMode",
    "Fingerprint",
    "MatrixReport",
    "ResumeReport",
    "RunReport",
    "Scenario",
    "baseline",
    "boundaries_of",
    "crash_matrix",
    "derive",
    "fingerprint",
    "kill_points",
    "matrix_boundaries",
    "owdoc_bytes",
    "plan_of",
    "reopen",
    "resume",
    "run_scenario",
    "seed",
    "simulate_kill_at",
    "verify_boundary",
]


# ---------------------------------------------------------------------------------------------
# 1. The eight fixtures: DataFlow's checkpoint failure inventory, and what refuses each.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckpointFailureMode:
    """One of DataFlow's eight documented checkpoint failure modes, and omniweave's refusal.

    `dataflow` is the observed defect, `refusal` is the mechanism that makes it impossible here,
    and `asserts` is what this mode's crash-matrix scenario actually checks after the kill. The
    third field is why this is a fixture list rather than a comment: a failure mode with no
    assertion is a paragraph, and 16-roadmap.md:422 asked for fixtures.
    """

    id: str
    dataflow: str
    refusal: str
    asserts: str


CHECKPOINT_FAILURE_MODES: Final[tuple[CheckpointFailureMode, ...]] = (
    CheckpointFailureMode(
        id="non_atomic_write",
        dataflow=(
            "`open(path, 'w')` truncates first, so a crash in the window leaves an empty "
            "checkpoint and the next resume dies in `map(int, ''.split(','))` -- unrecoverable "
            "without deleting the file by hand (mine-runtime.md:582-586)"
        ),
        refusal=(
            "there is no checkpoint file: the transaction IS the record, and the WAL commit is "
            "what makes it all-or-nothing (07:2730-2733)"
        ),
        asserts=(
            "after the kill the store still opens, `PRAGMA integrity_check` says ok and "
            "`PRAGMA foreign_key_check` is empty -- there is no torn record to recover from"
        ),
    ),
    CheckpointFailureMode(
        id="no_fsync",
        dataflow="on power loss the checkpoint content may be stale or torn (:587)",
        refusal=(
            "ST14: a `billed_api` completion sets `synchronous = FULL` BEFORE `BEGIN` (07:2736), "
            "so the one commit whose loss costs money is the one that is fsynced"
        ),
        asserts=(
            "a `billed_api` scenario converges to the same bytes as a `free` one, and a kill "
            "after COMMIT leaves the completion present rather than rolled back"
        ),
    ),
    CheckpointFailureMode(
        id="written_per_batch",
        dataflow="one open/truncate/write/close per batch, unbounded (:588)",
        refusal=(
            "one transaction per unit (07:2717), so a unit of any width is one commit and the "
            "write count is a property of the unit rather than of the batch size"
        ),
        asserts=(
            "the whole plan sits between exactly one `BEGIN IMMEDIATE` and one `COMMIT`: the "
            "enumeration is `len(plan) + 2` and the trace sees one commit, not one per statement"
        ),
    ),
    CheckpointFailureMode(
        id="lies_for_lazy_storage",
        dataflow=(
            "the checkpoint is written after `run()` returns but `LazyFileStorage.write()` only "
            "buffers in RAM, so the checkpoint claims step N batch K is durable when nothing was "
            "flushed and resume skips work that was never done (:589-592)"
        ),
        refusal=(
            "the `work` transition and the rows it certifies are in ONE transaction, so a `done` "
            "status cannot outlive the rows it claims -- there is no second protocol to disagree "
            "with the first (01-principles.md:1092, AP-5)"
        ),
        asserts=(
            "a kill at the boundary AFTER the `work_transition` statement and BEFORE the `dep` "
            "rows leaves the row NOT `done`: the transition rolls back with the rows it certifies"
        ),
    ),
    CheckpointFailureMode(
        id="arbitrary_checkpoint_location",
        dataflow=(
            "the checkpoint lives in `self.op_nodes_list[1].storage` -- the FIRST operator's "
            "cache directory -- so mixed-storage pipelines scatter it and share one counter "
            "(:593-594)"
        ),
        refusal=(
            "the store file is the only durable record: `.owstore` plus its `-wal` and `-shm`, "
            "and a content-addressed CAS beside it"
        ),
        asserts=(
            "after the kill the store directory holds no file the uninterrupted run did not also "
            "produce -- no sidecar checkpoint appears anywhere"
        ),
    ),
    CheckpointFailureMode(
        id="no_plan_identity",
        dataflow=(
            "the checkpoint stores an integer index, so editing `forward()` or reordering two "
            "operators makes step 4 a DIFFERENT operator on resume -- silent corruption, no "
            "detection (:595-598): *a resume token must include a hash of the plan it belongs to*"
        ),
        refusal=(
            "`work.cache_key` is RECORDED, so a config change is a MISMATCH and not a reuse "
            "(0004_runtime.sql:95); row identity is `(unit_uri, unit_part, operator, op_version)` "
            "and never a position"
        ),
        asserts=(
            "the converged row carries the completion's own `cache_key` and not the enqueued "
            "placeholder, so what was actually derived is what the row records"
        ),
    ),
    CheckpointFailureMode(
        id="no_input_identity",
        dataflow=(
            "change `first_entry_file_name` and resume: the batches are positional slices of a "
            "different file (:599-600)"
        ),
        refusal=(
            "resume re-derives the plan from current inputs and subtracts what is done; it never "
            "replays a recorded plan (01-principles.md:1092)"
        ),
        asserts=(
            "the derive step reads `doc(doc_key, gen)` and is skipped when the page is already "
            "present, so a resume writes no second generation of the same input"
        ),
    ),
    CheckpointFailureMode(
        id="inverted_default_ergonomics",
        dataflow=(
            "`resume_from_last=True` is the default and combining it with `resume_step` raises, "
            "so `forward(resume_step=3)` -- the obvious call -- fails (:601-603)"
        ),
        refusal=(
            "recovery is re-running the ordinary command: the `work` table's claimable set IS the "
            "checkpoint, so there is no resume flag to combine wrongly (01-principles.md:1092)"
        ),
        asserts=(
            "`resume()` takes no mode argument and is idempotent -- running it on a converged "
            "store reaps nothing, re-runs nothing and leaves the same bytes"
        ),
    ),
)
"""The fixture list, transcribed from `_plan/_notes/mine-runtime.md:580-620`.

**DEFECT, and this is the ruling.** Four plan files call these *"eight documented failure modes"*
(01-principles.md:1092, 08-runtime.md:2175, 16-roadmap.md:422, 17-risks.md:861) and not one of the
four enumerates them; between them the four name only the step-numbered index, the artefacts
living outside the checkpoint model, their not being content-addressed, and a row index unstable
under batching. `_plan/_notes/mine-runtime.md:580-620` prints all eight under the heading
*"Failure inventory -- all eight are real, and all eight are things omniweave must not repeat"*,
so the note is the only definition site and the eight are taken from it. One enumeration beats
four mentions: count definition sites, not mentions.
"""


# ---------------------------------------------------------------------------------------------
# 2. Fixture constants. Every one is fixed, so that two runs produce identical bytes.
# ---------------------------------------------------------------------------------------------

FIXTURE_URI: Final = "file:///corpus/crash-matrix.pdf"
"""The one `unit.unit_uri` the matrix enqueues against: one unit, one `work` row per scenario."""

FIXTURE_DOC_KEY: Final = bytes.fromhex("c9a5") * 8
"""`doc.doc_key`, 16 bytes.

A LITERAL and not a hash of anything. In production `doc_key` is `sha256(normalized source
bytes)[:16]`; the matrix has no source bytes, and what it needs is a value that is identical in
the interrupted and the uninterrupted store."""

FIXTURE_CACHE_KEY: Final = "c" * CACHE_KEY_HEX_LEN
"""`StepResult.cache_key`: 64 hex characters, `StepResult.__post_init__`'s only length rule."""

FIXTURE_GEN: Final = 1
"""The run generation -- `RunContext.generation`, *"a monotonic INTEGER, never a clock"* (08:270).

It is also `doc.gen` and `page.gen` for the fixture document, deliberately: `claim()` writes it
into `work.claimed_gen`, which is what `complete()`'s commit predicate compares (08:2841), so a
resume that re-claimed at a different generation would read as superseded rather than as a
resume."""

FIXTURE_WORKER: Final = "crash-matrix:0:0.0"
"""`'<host>:<pid>:<process_create_time>'` (0004_runtime.sql:110), with all three fixed.

A real pid would make two runs of the same scenario differ in `work.claimed_by` and therefore in
the store's bytes, which is the one thing the matrix compares. The store RECORDS this identity
and does not parse it (`SqliteStore.claim`'s docstring), so a constant is legal here and is what
makes the comparison a comparison."""

FIXTURE_LEASE_MS: Final = 60_000
"""Long enough that no lease expires inside a cycle by itself: `resume()` reaps deliberately."""

FIXTURE_IDENTITY: Final = OperatorIdentity(
    operator="parse.pdf", op_version=1, code_fingerprint="crash-matrix", options_digest=b"\x00"
)
"""The `StepResult.identity` every scenario reports, and the `producer` row it is written as.

**`OperatorIdentity` IS `Producer`** (08:1930), so there is one object here and not a value
type beside a row: `FIXTURE_PRODUCER` below is this object's four columns read off it rather
than a second literal, which is what stops the fixture's SQL from drifting from the fixture's
type. `op_version` is an integer, as it is at every site.
"""

FIXTURE_PRODUCER: Final = (
    FIXTURE_IDENTITY.operator,
    FIXTURE_IDENTITY.op_version,
    FIXTURE_IDENTITY.code_fingerprint,
    FIXTURE_IDENTITY.options_digest,
)
"""`(operator, op_version, code_fingerprint, options_digest)` -- `producer_identity`'s first
four columns (0001_init.sql:195-198), bound positionally by `_PRODUCER_SQL`."""

FIXTURE_CONTENT_SHA256: Final = "c0"
"""`UnitRef.content_sha256`, and `route_decision.content_sha256` is the same two characters.

A placeholder in both places and deliberately not a digest: the matrix has no source bytes,
and what it needs is a value identical in the interrupted and the uninterrupted store. Taken
from `_DECISION_SQL`, which wrote `'c0'` before there was a `UnitRef` to agree with.
"""

MATRIX_SALT: Final = b"ow-crash-1"
"""The sampling salt, in the plan's own `ow-<name>-1` shape (`ow-split-1`, `ow-tune-1` and
`ow-perm-1` at 13-quality.md:404-425). See `kill_points()`. `blake2b`'s `salt=` takes at most 16
bytes and this is ten."""

PR_POINTS: Final = 3
"""G21's assertion is *"kill-9 at three points"*; its nightly cell reads `full matrix`."""

SHIPPED_MIGRATIONS: Final = 4
"""`store/schema/migrations/` holds `0001..0004`. A fixture store that applied a different number
applied a different schema, and every column name below would be a guess."""

_TRANSACTION_BEGIN: Final = 2
"""Which `BEGIN IMMEDIATE` inside `complete()` opens the transaction under test.

`complete()` issues two units: `COST_CLASS_SQL` in its own transaction first, because ST14 needs
`work.cost_class` BEFORE the `BEGIN` it selects `synchronous` for (07:2736), and then the durable
one. So the second `BEGIN` the tracer sees is the transaction whose statement boundaries W2.9
enumerates, and the first is a read that writes nothing."""

AFTER_BEGIN: Final = "after:begin"
"""`complete_boundaries()`'s first name, spelled once so nothing retypes a string."""

AFTER_COMMIT: Final = "after:commit"
"""`complete_boundaries()`'s last name. The one boundary no trace callback can stand on: it is
past the `COMMIT` that the callback fires before, so `run_scenario()` signals it itself."""

WORK_FINGERPRINT_COLUMNS: Final = (
    "id",
    "unit_uri",
    "unit_part",
    "operator",
    "op_version",
    "cache_key",
    "decision_id",
    "driver",
    "cost_class",
    "dispatch_key",
    "status",
    "failure_class",
    "failure_message",
    "attempts_total",
    "attempts_today",
    "cost_micros",
    "queued_ms",
    "ran_ms",
    "peak_rss_bytes",
    "priority",
)
"""Which `work` columns two runs are compared on, and the five deliberately left out.

`last_attempt_at`, `lease_expires`, `retry_after`, `claimed_by` and `stale_since` are the store's
own clock or are derived from it -- `unixepoch('subsec')`, which charter.md:4090 marks *"THE
STORE'S CLOCK, never a worker's"*. Two runs happen at two wall times, so comparing those columns
would fail at every boundary and prove nothing; `COMPLETE_SQL` NULLs `claimed_by` and
`lease_expires` on the way out anyway.

`attempts_total` and `attempts_today` are IN, and they are the interesting pair: a crash costs a
claim and a reap gives it back -- *"a power cut is not an attempt"* (08:121-122) -- so an
interrupted run that converges must show the SAME attempt count as one that never crashed. A
`reap_expired_leases` that forgot to decrement is a one-line regression and this is what sees it.
"""

_RUNTIME_TABLES: Final = ("dep", "budget_reservation", "route_spend")
"""The other three of `complete()`'s five participants that own a table.

`derived_rows` is L2 and is compared through the `.owdoc` export; `work_transition` is `work` and
is compared column by column through `WORK_FINGERPRINT_COLUMNS`. These three are compared whole,
because the archive carries L2 alone and 07:2730-2733 names all five."""

_FLOOR: Final = Capabilities(
    spatial="none",
    origin_span="none",
    text_span=False,
    marks=False,
    reading_order="raster",
    sections="none",
    tables="none",
    math=frozenset(),
    assets="none",
    asset_origin=False,
    notes="none",
    confidence="none",
    furniture="destroyed",
    round_trip="none",
)
"""The all-absent capability floor. All fifteen fields are required (03 section 4.4): a driver
that forgets one cannot silently claim it."""


# ---------------------------------------------------------------------------------------------
# 3. A scenario, and the eight of them.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    """One fixture: one `work` row, one page of blocks, and the plan `complete()` will execute.

    `mode` is the `CheckpointFailureMode.id` this scenario is the fixture for. `part` is
    `work.unit_part`, which is what makes the eight rows distinct under `work_identity`'s
    `UNIQUE(unit_uri, unit_part, operator, op_version)`.

    `deps` are `(kind, key, digest)` triples handed to `queue.dep_statements()`, the shipped
    `dep_rows` participant, and they are what gives a P2 plan more than one statement. Of
    07:2730-2733's five participants exactly one has a P2 producer -- the `work` transition -- and
    `dep_rows` is the one whose SQL and refusals already ship, so it is the honest way to build a
    plan wide enough to have interior boundaries. Two per scenario, which is what makes the matrix
    forty boundaries.
    """

    mode: str
    part: str
    cost_class: str = "free"
    outcome: str = "ok"
    deps: tuple[tuple[str, str, str], ...] = ()
    texts: tuple[str, ...] = ("the first paragraph", "the second paragraph")


def _scenarios() -> tuple[Scenario, ...]:
    """One scenario per failure mode, in `CHECKPOINT_FAILURE_MODES` order.

    The `cost_class` split is `no_fsync`'s: it is the one mode whose refusal is ST14, so its
    scenario is the `billed_api` one and `sqlite.py`'s `_transact` sets `synchronous = FULL`
    before its `BEGIN`. Every other scenario is `free`, the general case 07:2734 gives
    `synchronous = NORMAL`.
    """
    return tuple(
        Scenario(
            mode=mode.id,
            part=f"p{index}",
            cost_class="billed_api" if mode.id == "no_fsync" else "free",
            deps=(
                ("unit", f"{FIXTURE_URI}#{index}a", f"d{index}a"),
                ("part", f"{FIXTURE_URI}#{index}b", f"d{index}b"),
            ),
        )
        for index, mode in enumerate(CHECKPOINT_FAILURE_MODES)
    )


SCENARIOS: Final[tuple[Scenario, ...]] = _scenarios()
"""The eight fixtures. `len(matrix_boundaries()) == 40`, which is 16-roadmap.md:422's "~40"."""


# ---------------------------------------------------------------------------------------------
# 4. The boundary enumeration. It CALLS `queue`; it never reads `queue`'s source.
# ---------------------------------------------------------------------------------------------


class _NoThread:
    """A `StoreThread` stand-in for `plan_of()`, which never reaches a connection.

    `SqliteStore.complete_plan()` is documented PURE -- *"No connection, no clock, no id minting
    -- so W2.9 can enumerate `complete()`'s crash boundaries by calling this"* -- and this object
    turns that claim into a runtime check rather than a trust: a call that did reach the store
    thread raises here instead of quietly opening a database.
    """

    def run(self, unit: object, **_kw: object) -> object:  # pragma: no cover -- see docstring.
        raise StoreError(
            f"complete_plan() reached the store thread through {unit!r}; it is documented pure",
            fix="report this as a bug in omniweave_core.store.queue",
        )


_UNUSED_THREAD: Final[Any] = _NoThread()


def _result(scenario: Scenario) -> StepResult:
    """The `StepResult` a scenario's driver would return. Fixed metrics: two runs, same bytes.

    `unit` and `identity` are required on the real type and were absent from the P2 carrier this
    module used to build, which had folded both away as unhomed. Neither reaches SQL through
    `complete()` -- `StepResultView` names six attributes and these are not among them -- so the
    fixture store is byte-identical across the change. What they buy is that the matrix now
    constructs the same class the runtime does, which is the whole point of a carrier having been
    a carrier.
    """
    return StepResult(
        outcome=Outcome(scenario.outcome),
        unit=UnitRef(
            uri=FIXTURE_URI,
            part=scenario.part,
            content_sha256=FIXTURE_CONTENT_SHA256,
            byte_len=sum(len(text) for text in scenario.texts),
        ),
        identity=FIXTURE_IDENTITY,
        cache_key=FIXTURE_CACHE_KEY,
        metrics=StepMetrics(queued_ms=11, ran_ms=22, micros=33, rows_written=len(scenario.texts)),
    )


def _contribution(scenario: Scenario) -> Callable[[int, StepResultView], Sequence[Statement]]:
    """The `dep_rows` `Contribution` for one scenario. `queue.dep_statements()` writes the SQL."""

    def contribute(row_id: int, _result_view: StepResultView) -> Sequence[Statement]:
        return dep_statements(row_id, scenario.deps)

    return contribute


def plan_of(scenario: Scenario, *, row_id: int = 1) -> tuple[Statement, ...]:
    """The statements `complete()` will run for `scenario`. PURE: no connection, no clock.

    Built by handing `queue.SqliteStore` the scenario's `dep_rows` contribution and asking for
    `complete_plan()`, which is the API `queue.py` points W2.9 at in as many words: *"a crash
    matrix that had to find those by parsing this module's source would break on any edit to it"*
    (`Statement`'s docstring). The `StoreThread` handed in is `_NoThread`, which proves the
    purity rather than assuming it.
    """
    store = SqliteStore(_UNUSED_THREAD, dep_rows=_contribution(scenario))
    return store.complete_plan(row_id, _result(scenario))


def boundaries_of(scenario: Scenario) -> tuple[str, ...]:
    """`scenario`'s crash boundaries, in order: `len(plan) + 2` of them, per `complete_boundaries`.

    One after `BEGIN IMMEDIATE`, one after each statement, one after `COMMIT`. Every boundary
    before the last must leave the store exactly as it was; the last must leave every
    participant's rows present.
    """
    return complete_boundaries(plan_of(scenario))


def matrix_boundaries(scenarios: Sequence[Scenario] = SCENARIOS) -> tuple[tuple[str, str], ...]:
    """Every `(scenario.mode, boundary)` pair in the matrix, in scenario then boundary order.

    Forty pairs for the shipped eight. This is the population `kill_points()` samples AND the
    population `crash_matrix()` walks under `--all`, so the two cannot disagree about what the
    matrix is.
    """
    return tuple(
        (scenario.mode, boundary) for scenario in scenarios for boundary in boundaries_of(scenario)
    )


def kill_points(
    population: Sequence[tuple[str, str]] = (),
    *,
    salt: bytes = MATRIX_SALT,
    count: int = PR_POINTS,
) -> tuple[tuple[str, str], ...]:
    """Draw `count` points from the matrix, deterministically. 11-repo-layout.md:2185.

    *"Sampling is blake2b. Determinism is a gate, not a habit."* -- so the draw is a keyed
    `blake2b` over each point's own name and never an RNG. `random` is banned in library code, and
    a seeded `random.Random` would still make the draw depend on iteration order; a per-point
    digest does not. That is the property 05-ingest-and-routing.md:2801's sampler has and the
    reason its `audit_selected` is *"DERIVED, never random"*.

    The three come back in MATRIX order rather than digest order, so a report reads left to right;
    the digest decides membership only. `salt` is what a caller varies to get a different three --
    `tools/gate_crash.py` accepts one and 11-repo-layout.md:2615 suggests the commit sha for a
    PR-path sample.

    Refuses to draw more points than the population holds rather than returning fewer: a gate that
    says "three points" and silently ran two is 11-repo-layout.md section 6.8's check that cannot
    fail.
    """
    points = tuple(population) or matrix_boundaries()
    if count < 1:
        raise StoreError(
            f"asked for {count} kill points; a matrix run of no points is not a run",
            fix="pass count >= 1",
        )
    if count > len(points):
        raise StoreError(
            f"asked for {count} kill points and the matrix holds {len(points)}",
            fix="pass count <= len(matrix_boundaries())",
        )
    keyed = sorted(
        (hashlib.blake2b(f"{mode}\x00{boundary}".encode(), digest_size=8, salt=salt).digest(), i)
        for i, (mode, boundary) in enumerate(points)
    )
    return tuple(points[index] for index in sorted(index for _digest, index in keyed[:count]))


# ---------------------------------------------------------------------------------------------
# 5. Building the fixture store.
# ---------------------------------------------------------------------------------------------

_UNIT_SQL: Final = (
    "INSERT OR IGNORE INTO unit(unit_uri, state, trust_class, last_seen_gen) "
    "VALUES(:uri, 'planned', 'internal', :gen)"
)

_EVIDENCE_SQL: Final = (
    "INSERT OR IGNORE INTO route_evidence(evidence_digest, payload, first_seen_at) "
    "VALUES('ev', X'00', 1)"
)

_DECISION_SQL: Final = """
INSERT OR IGNORE INTO route_decision(
  decision_id, content_sha256, unit_part, lane, rung,
  policy_digest, pricebook_digest, hints_digest, read_set_digest,
  driver, cost_class, rule_id, rule_origin, slice_key,
  evidence_digest, est_spend, est_micros, reserved_micros,
  admission, generation, decided_at)
VALUES(:decision_id, 'c0', :unit_part, 'parse', 1,
  'pd', 'pb', 'hd', 'rd',
  'drv', :cost_class, 'r1', 'crash-matrix:1', 'sk',
  'ev', '{}', 0, 0, 'admitted', :gen, 1)
"""

_WORK_SQL: Final = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key,
                 decision_id, driver, cost_class, dispatch_key, status)
VALUES(:uri, :part, 'parse.pdf', 1, 'planned',
       :decision_id, 'drv', :cost_class, :dispatch_key, 'pending')
"""

_PRODUCER_SQL: Final = (
    "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
    "VALUES(?, ?, ?, ?)"
)

# THE FIVE STATEMENTS ABOVE ARE A FIXTURE, NOT A PLANNER.
#
# Writing a `work` row is the planner's job and the planner is P4's `omniweave_core.work`
# (16-roadmap.md:541). `Store.complete()` is "the only mutation entry point on the queue boundary"
# (07:2730) and enqueue is the other end, which P2 does not ship. They exist because a crash
# matrix over `complete()` needs something to complete; they are confined to this module and to
# `seed()`, and they are deleted the day the planner lands. They are the same five
# `tests/unit/test_store_queue.py` already seeds with, for the same reason and the same shape.


def seed(path: Path, cas: Path, *, now_ns: int, scenarios: Sequence[Scenario] = SCENARIOS) -> Path:
    """Create the store, apply the four migrations, and enqueue one `work` row per scenario.

    `now_ns` is INJECTED: `migrate.apply_pending(conn, *, now_ns)` stamps the migration ledger with
    it, and `time.time` is banned in library code (02:392). Two runs at the same `now_ns` therefore
    write the same ledger, which is one of the things a byte comparison would otherwise trip on.

    Returns `path`, so a caller can chain. `cas` is created when absent: `BlobStore` is `DocSink`'s
    and the fixture writes no blobs, but the directory has to exist to construct one.
    """
    cas.mkdir(parents=True, exist_ok=True)
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=now_ns)
        if len(applied) != SHIPPED_MIGRATIONS:
            raise StoreError(
                f"the crash-matrix fixture applied {len(applied)} migrations and the shipped set "
                f"is four",
                fix="ow store migrate",
            )
        connection.execute(_PRODUCER_SQL, FIXTURE_PRODUCER)
        connection.execute(_UNIT_SQL, {"uri": FIXTURE_URI, "gen": FIXTURE_GEN})
        connection.execute(_EVIDENCE_SQL)
        for scenario in scenarios:
            connection.execute(
                _DECISION_SQL,
                {
                    "decision_id": f"dec_{scenario.part}",
                    "unit_part": scenario.part,
                    "cost_class": scenario.cost_class,
                    "gen": FIXTURE_GEN,
                },
            )
            connection.execute(
                _WORK_SQL,
                {
                    "uri": FIXTURE_URI,
                    "part": scenario.part,
                    "decision_id": f"dec_{scenario.part}",
                    "cost_class": scenario.cost_class,
                    "dispatch_key": f"dk_{scenario.part}",
                },
            )
        connection.commit()
    finally:
        connection.close()
    return path


def _producer_id(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT producer_id FROM producer WHERE operator = ? AND op_version = ?",
        FIXTURE_PRODUCER[:2],
    ).fetchone()
    if row is None:
        raise StoreError(
            "the crash-matrix fixture store has no producer row",
            fix="call seed() before run_scenario()",
        )
    return int(row[0])


# ---------------------------------------------------------------------------------------------
# 6. The unit of work: derive (idempotent), then complete.
# ---------------------------------------------------------------------------------------------


def _doc_record() -> DocRecord:
    """The fixture document. Every field a constant, for the same reason `FIXTURE_WORKER` is."""
    return DocRecord(
        doc_ord=0,
        doc_key=FIXTURE_DOC_KEY,
        gen=FIXTURE_GEN,
        source_sha256=bytes.fromhex("5e") * 32,
        normalizer="canonical/1",
        uri=FIXTURE_URI,
        media_type="application/pdf",
        format="pdf",
        format_evidence=MappingProxyType({}),
        source_bytes=4096,
        status="ok",
        page_count=1,
        model_version="1.1",
        declared=_FLOOR,
        achieved=_FLOOR,
        confidence=MappingProxyType({}),
        timings_ms=MappingProxyType({}),
    )


def _page_record() -> PageRecord:
    """One page, 0-based -- *"ORIGINAL source index, 0-based. NEVER a batch index"* (0001:207)."""
    return PageRecord(
        page=0,
        page_kind=PageKind.PAGE,
        label=None,
        w_mpt=595_280,
        h_mpt=841_890,
        rotation=0,
        quad_origin="topleft",
        method=Method.NATIVE,
        status="ok",
    )


def _page_present(connection: sqlite3.Connection) -> bool:
    """Whether the fixture document's page already exists at `FIXTURE_GEN`.

    This is `derive()`'s subtraction, and it reads exactly the predicate 07 section 3.12 clause 1
    names: *"`doc(doc_key, gen)` present"*. 01-principles.md:1092 fixes the shape it serves --
    *"resume re-derives the plan from current inputs and subtracts what is done, and never replays
    a recorded plan."* A resume after a crash inside `complete()` finds the page present, because
    `DocSink.end_page()` commits its own transaction (03:594) BEFORE `complete()` is ever called.
    """
    row = connection.execute(
        "SELECT 1 FROM page JOIN doc USING (doc_ord) WHERE doc.doc_key = ? AND page.gen = ?",
        (FIXTURE_DOC_KEY, FIXTURE_GEN),
    ).fetchone()
    return row is not None


def derive(thread: ow.StoreThread, cas: Path, scenario: Scenario, *, producer_id: int) -> bool:
    """Write the scenario's page of blocks through `DocSink`, unless it is already there.

    Returns whether it wrote. `DocSink` is the only writer of L2 and this does not become a second
    one: it constructs one and drives the ordinary `begin_doc` / `begin_page` / `add_block` /
    `end_page` / `end_doc` sequence.

    **The idempotence is the point, and it is fixture mode `no_input_identity`'s assertion.**
    DataFlow resumes into positional slices of whatever file is configured now; omniweave's resume
    asks the store what is present and writes only the difference. A `derive()` that re-ran
    unconditionally would mint a second generation of the same page, and the `.owdoc` export of a
    resumed store would then differ from the uninterrupted one -- which is exactly the failure the
    matrix would report.

    Every scenario writes into the SAME document, so the first scenario derives and the other
    seven skip. That is deliberate: it makes the derive/skip branch exercised on every run rather
    than only after a crash.
    """
    existing = thread.run(ow.Unit(name="crash.derived?", run=_page_present, cost_class="free"))
    if existing:
        return False
    sink = DocSink(
        thread,
        producer_id=producer_id,
        origin_operator="parse.pdf",
        origin_driver="parse.pdf.pdfium",
        driver_schema_v=1,
        blobs=BlobStore(cas),
    )
    sink.begin_doc(_doc_record())
    sink.begin_page(_page_record())
    root = sink.add_block(
        BlockDraft(
            kind=Kind.DOCUMENT,
            layer=Layer.BODY,
            method=Method.NATIVE,
            trust=Trust.EXTRACTED,
            quote=Quote.SYNTHETIC,
        )
    )
    for text in scenario.texts:
        sink.add_block(
            BlockDraft(
                kind=Kind.PARAGRAPH,
                layer=Layer.BODY,
                method=Method.NATIVE,
                trust=Trust.EXTRACTED,
                quote=Quote.VERBATIM,
                parent=root,
                text=text,
            )
        )
    sink.end_page({"blocks": len(scenario.texts) + 1})
    sink.end_doc("ok")
    return True


class _Tracer:
    """A `sqlite3` trace callback that names the crash boundary the connection is standing on.

    The callback fires immediately BEFORE each statement, so the k-th statement traced after
    `complete()`'s own `BEGIN IMMEDIATE` stands at boundary k-1 of `complete_boundaries()`:
    nothing of the plan has run at the first, `plan[0]` has run at the second, and the trace of
    `COMMIT` stands at the boundary after the last statement. `after:commit` is unreachable from
    here by construction and is signalled by the caller once `complete()` has returned.

    `complete()` issues TWO units -- `COST_CLASS_SQL` in its own transaction first, then the
    durable one (ST14; see `queue.SqliteStore.complete`) -- so this counts `BEGIN`s and only
    indexes inside the second. Counting the leading keyword rather than matching the statement
    text is deliberate: CPython's trace callback may hand back the EXPANDED SQL, so the parameter
    values are not something to match on, and the keyword is.

    `seen` is the run's evidence that every boundary was actually reached. 11-repo-layout.md
    section 6.8 asks that of every check that discovers its own inputs, and a matrix whose
    boundaries were silently skipped would report forty cycles having run fewer.
    """

    __slots__ = ("_begins", "_boundaries", "_index", "on_boundary", "seen")

    def __init__(self, boundaries: Sequence[str], on_boundary: Callable[[str], None]) -> None:
        self._boundaries = tuple(boundaries)
        self.on_boundary = on_boundary
        self._begins = 0
        self._index = 0
        self.seen: list[str] = []

    def __call__(self, statement: str) -> None:
        head = statement.lstrip()[:8].upper()
        if head.startswith("BEGIN"):
            self._begins += 1
            self._index = 0
            return
        if head.startswith("ROLLBACK"):
            # A rollback is the crash's aftermath, not a statement of the plan. `_transact` issues
            # one on any raise, so counting it would make `seen` claim a boundary the transaction
            # never stood on -- and `seen` is what proves every boundary was reached.
            return
        if self._begins != _TRANSACTION_BEGIN or self._index >= len(self._boundaries) - 1:
            return
        name = self._boundaries[self._index]
        self._index += 1
        self.seen.append(name)
        self.on_boundary(name)


@dataclass(frozen=True, slots=True)
class RunReport:
    """What one drive of a scenario did, and which boundaries the transaction stood on."""

    scenario: str
    derived: bool
    completed: bool
    superseded: bool
    reached: tuple[str, ...]
    killed_at: str | None


def _ignore(_name: str) -> None:
    """The no-op boundary hook. A run with no kill still walks every boundary."""


def _drive(
    thread: ow.StoreThread,
    cas: Path,
    scenario: Scenario,
    *,
    hook: Callable[[str], None],
    abandon: bool = False,
) -> tuple[bool, bool, _Tracer, bool]:
    """Claim, derive, arm the tracer, complete. Returns `(derived, completed, tracer, claimed)`.

    The one body `run_scenario()` and `simulate_kill_at()` share, so the killed path and the clean
    path cannot drift apart in what they do to the store -- which would make every comparison
    between them meaningless.

    **`abandon` is the killed path, and it is the difference a dying process actually makes.** A
    clean run disarms the tracer and hands the connection back; a killed one touches the
    connection no further and lets `StoreThread.close()` drop it, which is what a process that
    took a SIGKILL does. It also has to be that way mechanically: `Connection.interrupt()` from
    inside a trace callback can leave the interrupt pending across `_transact`'s own `ROLLBACK`,
    so the next statement on that connection -- the disarm unit's `PRAGMA synchronous` -- fails
    with *"Safety level may not be changed inside a transaction"*. Tidying up after a simulated
    crash is exactly the thing a crash does not do.
    """
    producer_id = thread.run(ow.Unit(name="crash.producer", run=_producer_id, cost_class="free"))
    derived = derive(thread, cas, scenario, producer_id=int(producer_id))  # type: ignore[arg-type]
    store = SqliteStore(thread, dep_rows=_contribution(scenario))
    rows = store.claim(batch=1, gen=FIXTURE_GEN, worker=FIXTURE_WORKER, lease_ms=FIXTURE_LEASE_MS)
    wanted = [row for row in rows if row.unit_part == scenario.part]
    tracer = _Tracer(boundaries_of(scenario), hook)
    if not wanted:
        return derived, False, tracer, False
    thread.run(
        ow.Unit(
            name="crash.arm",
            run=lambda connection: connection.set_trace_callback(tracer),
            cost_class="free",
        )
    )
    try:
        completed = store.complete(wanted[0].id, FIXTURE_GEN, _result(scenario))
    except sqlite3.Error:
        completed = False
    if not abandon:
        thread.run(
            ow.Unit(
                name="crash.disarm",
                run=lambda connection: connection.set_trace_callback(None),
                cost_class="free",
            )
        )
    return derived, completed, tracer, True


def run_scenario(
    path: Path,
    cas: Path,
    scenario: Scenario,
    *,
    on_boundary: Callable[[str], None] | None = None,
    wal_heal_mb: int | None = None,
) -> RunReport:
    """Claim, derive and complete one scenario against the store at `path`. No kill.

    This is the unit the matrix kills in the middle of, run to completion. `on_boundary`, when
    given, is called ON THE STORE THREAD immediately before each statement of `complete()`'s
    transaction with the name of the boundary the process is standing on, and once more with
    `after:commit` after `complete()` has returned. A caller that wants to die there parks in it:
    `tools/gate_crash.py`'s child does exactly that and its parent sends the signal.

    Every open goes through `reopen()`, so a run that follows a kill heals the WAL that kill leaked
    (07:2807, and 07:181-183's **25.6 GB** of leaked WAL from repeatedly-SIGKILLed sessions with no
    heal-on-open).

    The `ow` verb: this is one unit of `ow run`; `ow test crash-matrix` drives it.
    """
    with reopen(path, wal_heal_mb=wal_heal_mb) as thread:
        derived, completed, tracer, claimed = _drive(
            thread, cas, scenario, hook=on_boundary or _ignore
        )
    if on_boundary is not None and claimed:
        on_boundary(AFTER_COMMIT)
    return RunReport(
        scenario=scenario.mode,
        derived=derived,
        completed=completed,
        superseded=claimed and not completed,
        reached=(*tracer.seen, AFTER_COMMIT) if claimed else (),
        killed_at=None,
    )


def simulate_kill_at(
    path: Path,
    cas: Path,
    scenario: Scenario,
    boundary: str,
    *,
    wal_heal_mb: int | None = None,
) -> RunReport:
    """Drive `scenario` and abort the transaction AT `boundary`, in this process. A MODEL.

    See the module docstring for why this models a SIGKILL faithfully and where it does not. The
    abort is `Connection.interrupt()` from inside the trace callback, which raises
    `SQLITE_INTERRUPT` out of the pending statement; `sqlite.py`'s `_transact` rolls back on any
    raise, and `INTERRUPTED` is that module's own name for the condition. What a reopened store
    finds is therefore identical to what it finds after a pre-COMMIT SIGKILL -- the frames were
    never committed. What it does not reproduce is the leaked `-wal` and the stale `-shm` a killed
    process leaves behind, which is why `tools/gate_crash.py` spawns and kills a real process, and
    why this exists so forty cycles fit inside a unit-test budget.

    `after:commit` is the one boundary with nothing to abort: the transaction has committed and
    the process is about to die holding nothing. The run is allowed to finish, which is the
    correct model rather than a gap -- a SIGKILL there loses no committed work.
    """
    known = boundaries_of(scenario)
    if boundary not in known:
        raise StoreError(
            f"{boundary!r} is not a boundary of scenario {scenario.mode!r}: {known}",
            fix="pass a name from boundaries_of(scenario)",
        )
    if boundary == AFTER_COMMIT:
        clean = run_scenario(path, cas, scenario, wal_heal_mb=wal_heal_mb)
        return RunReport(
            scenario=clean.scenario,
            derived=clean.derived,
            completed=clean.completed,
            superseded=clean.superseded,
            reached=clean.reached,
            killed_at=AFTER_COMMIT,
        )
    handle: dict[str, sqlite3.Connection | None] = {"connection": None}

    def hook(name: str) -> None:
        connection = handle["connection"]
        if name == boundary and connection is not None:
            connection.interrupt()

    with reopen(path, wal_heal_mb=wal_heal_mb) as thread:
        thread.run(
            ow.Unit(
                name="crash.handle",
                run=lambda connection: handle.__setitem__("connection", connection),
                cost_class="free",
            )
        )
        derived, completed, tracer, claimed = _drive(thread, cas, scenario, hook=hook, abandon=True)
    return RunReport(
        scenario=scenario.mode,
        derived=derived,
        completed=completed,
        superseded=False,
        reached=tuple(tracer.seen) if claimed else (),
        killed_at=boundary,
    )


# ---------------------------------------------------------------------------------------------
# 7. Reopen, and resume.
# ---------------------------------------------------------------------------------------------


class _Opened:
    """A `StoreThread` context manager that heals the WAL on the way in. `reopen()`'s return.

    The heal is 07:2807's *"`[store] wal_heal_mb = 64` => heal an oversized WAL at every open"*.
    `wal_before` and `reclaimed` are recorded so a caller can assert the heal happened rather than
    assume it.

    **THE HEAL RUNS BEFORE THE STORE THREAD STARTS, ON A CONNECTION THAT HOLDS NOTHING, AND IT HAS
    TO.** `heal_wal`'s own docstring makes the condition explicit: a `wal_checkpoint(TRUNCATE)` is
    legal here only because it *"runs at open, on a connection that has issued no `BEGIN` and
    holds nothing, which is the **parked barrier** [07:2836-2839] the same paragraph requires."*
    Every `StoreThread.run(Unit)` wraps its closure in `BEGIN IMMEDIATE` ... `COMMIT` (`_transact`),
    and a truncate checkpoint inside a transaction returns `SQLITE_BUSY` -- which `heal_wal`
    swallows, so a heal submitted as a unit reports 0 reclaimed on a 3 MB WAL and looks like a
    healthy store. That is the failure this shape avoids, and it was found by the assertion in
    `test_gate_crash.py::test_a_reopen_after_a_real_kill_heals_an_oversized_wal` rather than by
    reading.

    The heal connection is closed immediately: it exists for one pragma. The store thread then
    opens its own, which is the one every unit runs on (INV-17's *"the only holder of a
    `Connection` in a process"* -- the two never overlap).
    """

    __slots__ = ("_thread", "path", "reclaimed", "wal_before", "wal_heal_mb")

    def __init__(self, path: Path, *, wal_heal_mb: int | None) -> None:
        self.path = path
        self.wal_heal_mb = wal_heal_mb
        self.wal_before = ow.wal_bytes(path)
        self.reclaimed = 0
        self._thread = ow.StoreThread(lambda: ow.connect(path))

    def __enter__(self) -> ow.StoreThread:
        barrier = ow.connect(self.path)
        try:
            self.reclaimed = ow.heal_wal(barrier, self.path, wal_heal_mb=self.wal_heal_mb)
        finally:
            barrier.close()
        self._thread.start()
        return self._thread

    def __exit__(self, *_exc: object) -> None:
        self._thread.close()


def reopen(path: Path, *, wal_heal_mb: int | None = None) -> _Opened:
    """Open the store at `path` on a fresh `StoreThread`, healing an oversized WAL first.

    Every open in this module goes through here, which is what makes *"a reopen after SIGKILL
    heals the WAL"* a property of the harness rather than of one call site. 07:181-183 is the
    measurement that earns it a function: **25.6 GB** of leaked WAL across repeatedly-SIGKILLed
    sessions with no heal-on-open.

    `wal_heal_mb = None` takes `[store] wal_heal_mb`'s default of 64 MB; a test that wants to
    watch the heal fire passes a smaller threshold rather than writing 64 MB of WAL.

    The `ow` verb: every one of them opens this way, `ow store verify` nearest of all.
    """
    return _Opened(path, wal_heal_mb=wal_heal_mb)


@dataclass(frozen=True, slots=True)
class ResumeReport:
    """What `resume()` did: how many leases it reaped, and which units it re-ran."""

    reaped: int
    reran: tuple[str, ...]
    reclaimed_wal_bytes: int


def resume(
    path: Path,
    cas: Path,
    *,
    now_ms: int,
    scenarios: Sequence[Scenario] = SCENARIOS,
    wal_heal_mb: int | None = None,
) -> ResumeReport:
    """The `ow resume` path: heal, reap, re-derive what is missing, complete what is unfinished.

    16-roadmap.md:436-438's P2 demo is this function: *"SIGKILL the writer mid-commit, reopen, and
    `ow resume` converges to the uninterrupted result byte for byte in the `.owdoc` export."*

    Three steps and no fourth, because 01-principles.md:1092 rules the fourth out:

    1. **Reopen and heal.** `reopen()`, which is where 07:2807's heal-on-open happens.
    2. **Reap.** `Store.reap_expired_leases(now_ms)` returns every expired claim to `pending` with
       its attempt counts decremented -- *"a power cut is not an attempt"* (08:121-122). `now_ms`
       is INJECTED, exactly as the store's own signature injects it (07:59): a resume that read
       the ambient clock could not be replayed.
    3. **Re-run what is claimable.** For each scenario whose `work` row is not `done`, drive the
       ordinary unit again. There is no checkpoint to read and no recorded plan to replay: *"the
       `work` table's claimable set **is** the checkpoint; resume re-derives the plan from current
       inputs and subtracts what is done."* `derive()` performs the subtraction.

    `now_ms` must be past the lease this harness mints (`FIXTURE_LEASE_MS` after the claim), which
    is why callers pass a far-future millisecond: a reap that swept nothing would leave step 3
    finding the row still `claimed`, and a resume that cannot reclaim its own crashed unit is not
    a resume.

    Idempotent by construction, which is fixture mode `inverted_default_ergonomics`'s assertion:
    on a converged store the reap sweeps nothing, the unfinished set is empty and nothing re-runs.

    The `ow` verb: `ow resume`.
    """
    opened = reopen(path, wal_heal_mb=wal_heal_mb)
    with opened as thread:
        store = SqliteStore(thread)
        reaped = store.reap_expired_leases(now_ms)
        unfinished = thread.run(
            ow.Unit(name="crash.unfinished", run=_unfinished_parts, cost_class="free")
        )
    parts = set(unfinished)  # type: ignore[arg-type]
    reran = tuple(
        scenario.mode
        for scenario in scenarios
        if scenario.part in parts and run_scenario(path, cas, scenario, wal_heal_mb=wal_heal_mb)
    )
    return ResumeReport(reaped=int(reaped), reran=reran, reclaimed_wal_bytes=opened.reclaimed)


def _unfinished_parts(connection: sqlite3.Connection) -> tuple[str, ...]:
    """`work.unit_part` for every row that is not `done`. Step 3's "subtract what is done"."""
    return tuple(
        str(part)
        for (part,) in connection.execute(
            "SELECT unit_part FROM work WHERE unit_uri = ? AND status <> 'done' ORDER BY unit_part",
            (FIXTURE_URI,),
        )
    )


# ---------------------------------------------------------------------------------------------
# 8. The comparison. Byte-for-byte on the `.owdoc` export, plus the rows it cannot see.
# ---------------------------------------------------------------------------------------------


def _enum_names(connection: sqlite3.Connection, domain: str) -> Mapping[int, str]:
    """`{ord: member name}` for one `enum_val` domain, read off the store and not off Python.

    The same rule `reader.py:388-399` states for the forward direction: reading ordinals off this
    build's enums would make a store built by an older seed answer with this build's numbering,
    which is exactly the drift `enum_val` exists to make impossible.
    """
    return {
        int(ord_): str(name)
        for name, ord_ in connection.execute(
            "SELECT name, ord FROM enum_val WHERE domain = ?", (domain,)
        )
    }


_EXPORT_SQL: Final = """
SELECT block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind, raw_kind, layer, label,
       text, content_digest, layout_digest, revision, quad, os_kind, ts_a, ts_b, producer_id,
       method, trust, quote, score, score_kind, origin_operator, origin_driver, driver_schema_v,
       restriction_bits, state, x, payload, decision_id
  FROM block
 WHERE doc_ord = :doc_ord AND gen = :gen
 ORDER BY page, ord, block_id
"""


class _StoreExport:
    """An `ExportSource` over one generation of one document in a real store. NARROW BY DESIGN.

    `archive.owdoc.ExportSource`'s own docstring says who the general implementation is: *"The
    type that DOES have this shape is `Doc`, the lazy read handle of 03-document-model.md:
    2584-2606 ... when `Doc` lands it satisfies this protocol structurally."* `Doc` is P4's, and
    this is not it. This is the crash matrix's projection: it reads the columns the matrix's own
    fixture writes and REFUSES anything outside them rather than guessing, so the day a fixture
    grows a quad, a mark or a grid the refusal fires instead of a silently thinner archive.

    Six of the nine methods return nothing, and each is empty because the fixture writes nothing
    into it -- `_refuse_unsupported()` is what turns that from an assumption into a check.

    Why an export at all: 16-roadmap.md:437 makes *"byte for byte in the `.owdoc` export"* the
    comparison the P2 demo converges on, and `archive/` already writes a byte-stable archive with
    a byte-identical re-export among its own tests. That is what makes "equals an uninterrupted
    run" checkable rather than approximate.
    """

    __slots__ = ("_connection", "_kinds", "_layers", "_methods", "_os_kinds", "_producers", "_row")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._kinds = _enum_names(connection, "kind")
        self._layers = _enum_names(connection, "layer")
        self._methods = _enum_names(connection, "method")
        self._os_kinds = _enum_names(connection, "origin_span_kind")
        self._row = connection.execute(
            "SELECT doc_ord, doc_key, gen, status, uri, media_type, format, declared, achieved, "
            "       confidence, timings_ms, x "
            "  FROM doc WHERE doc_key = ?",
            (FIXTURE_DOC_KEY,),
        ).fetchone()
        if self._row is None:
            raise StoreError(
                "the crash-matrix store holds no fixture document to export",
                fix="run the scenario before exporting",
            )
        self._producers = tuple(
            (int(pid), str(operator), int(version))
            for pid, operator, version in connection.execute(
                "SELECT DISTINCT p.producer_id, p.operator, p.op_version "
                "  FROM producer p JOIN block b USING (producer_id) "
                " WHERE b.doc_ord = ? AND b.gen = ? ORDER BY p.producer_id",
                (int(self._row[0]), int(self._row[2])),
            )
        )

    def header(self) -> DocHeader:
        row = self._row
        return DocHeader(
            doc_key=bytes(row[1]).hex(),
            gen=int(row[2]),
            status=str(row[3]),
            source={"uri": str(row[4]), "media_type": str(row[5]), "format": str(row[6])},
            declared=json.loads(str(row[7])),
            achieved=json.loads(str(row[8])),
            producers=[
                {"operator": operator, "op_version": version}
                for _pid, operator, version in self._producers
            ],
            confidence=json.loads(str(row[9])),
            timings_ms=json.loads(str(row[10])),
            x=json.loads(str(row[11])),
        )

    def blocks(self) -> Iterator[BlockExport]:
        index = {pid: i for i, (pid, _op, _v) in enumerate(self._producers)}
        rows = self._connection.execute(
            _EXPORT_SQL, {"doc_ord": int(self._row[0]), "gen": int(self._row[2])}
        )
        for row in rows:
            yield BlockExport(
                block=self._block(row),
                producer=index[int(row[20])],
                payload=None if row[32] is None else json.loads(str(row[32])),
                decision_id=None if row[33] is None else str(row[33]),
            )

    def _block(self, row: Sequence[Any]) -> Block:
        """One `block` row as a `Block`, refusing every column shape the fixture does not write."""
        os_kind = self._os_kinds[int(row[17])]
        self._refuse_unsupported(row, os_kind)
        return Block(
            id=BlockId(int(row[0])),
            addr=Addr(str(row[4])),
            cite=Cite(str(row[5])),
            doc_ord=int(row[1]),
            gen=int(row[2]),
            page=int(row[3]),
            parent=None if row[6] is None else BlockId(int(row[6])),
            ord=int(row[7]),
            kind=Kind(self._kinds[int(row[8])]),
            raw_kind=None if row[9] is None else str(row[9]),
            layer=Layer(self._layers[int(row[10])]),
            label=None if row[11] is None else str(row[11]),
            text=None if row[12] is None else str(row[12]),
            content_digest=bytes(row[13]),
            layout_digest=None,
            revision=int(row[15]),
            quad=None,
            origin=OriginNone(),
            span=None,
            producer_id=int(row[20]),
            method=Method(self._methods[int(row[21])]),
            trust=Trust(int(row[22])),
            quote=Quote(int(row[23])),
            score=None if row[24] is None else float(row[24]),
            score_kind=None if row[25] is None else str(row[25]),
            origin_operator=str(row[26]),
            origin_driver=str(row[27]),
            driver_schema_v=int(row[28]),
            restriction_bits=int(row[29]),
            marks=(),
            tombstoned=bool(row[30]),
            x=json.loads(str(row[31])),
        )

    @staticmethod
    def _refuse_unsupported(row: Sequence[Any], os_kind: str) -> None:
        """The projection's honesty check: anything it would silently drop is a raise.

        A narrow hydrator that quietly emitted `quad=None` for a block that HAS a quad would make
        two stores compare equal on a column neither one exported. That is the failure rule 7 of
        this project's house rules calls a test that cannot fail, so the columns outside the
        projection are asserted absent rather than ignored.
        """
        dropped = [
            name
            for name, value in (
                ("layout_digest", row[14]),
                ("quad", row[16]),
                ("ts_a", row[18]),
                ("ts_b", row[19]),
            )
            if value is not None
        ]
        if os_kind != OsKind.NONE.value:
            dropped.append(f"os_kind={os_kind}")
        if dropped:
            raise StoreError(
                f"block {row[0]} carries {dropped}, which the crash matrix's narrow "
                f"ExportSource does not project",
                fix="hydrate through omniweave_core.model.doc.Doc when P4 lands (03:2584-2606)",
            )

    def rels(self) -> Iterable[Any]:
        return self._empty("rel")

    def grids(self) -> Iterable[Any]:
        return self._empty("table_meta")

    def parts(self) -> Iterable[Any]:
        return self._empty("part")

    def assets(self) -> Iterable[Any]:
        return self._empty("asset")

    def views(self) -> Iterable[Any]:
        return ()

    def diags(self) -> Iterable[Mapping[str, Any]]:
        """Every `diag` row of this generation, projected whole.

        The one satellite the fixture actually writes: `DocSink` records a diagnostic when it
        clamps a `quote` or a `trust`, and those rows are part of what a crash must not lose, so
        they are exported rather than asserted absent. `detail` is stored JSON and is parsed, so
        the archive carries an object where the column carries text.
        """
        columns = (
            "page",
            "block_id",
            "part",
            "code",
            "severity",
            "component",
            "message",
            "detail",
            "fatal",
        )
        rows = self._connection.execute(
            f"SELECT {', '.join(columns)} FROM diag WHERE doc_ord = ? AND gen = ? "  # noqa: S608
            f"ORDER BY page, block_id, code, message",
            (int(self._row[0]), int(self._row[2])),
        )
        return [
            {
                name: json.loads(str(value)) if name == "detail" else value
                for name, value in zip(columns, row, strict=True)
            }
            for row in rows
        ]

    def toc(self) -> Sequence[Mapping[str, Any]]:
        return ()

    def _empty(self, table: str) -> tuple[Any, ...]:
        """Assert the table this projection does not read is in fact empty, then return nothing."""
        (count,) = self._connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        if int(count):
            raise StoreError(
                f"the crash-matrix store holds {count} {table} row(s) and the narrow "
                f"ExportSource does not project them",
                fix="hydrate through omniweave_core.model.doc.Doc when P4 lands (03:2584-2606)",
            )
        return ()


def owdoc_bytes(path: Path, out: Path) -> bytes:
    """Export the fixture document from the store at `path` to `out`, and return its bytes.

    The comparison 16-roadmap.md:437 asks for is over these bytes: *"`ow resume` converges to the
    uninterrupted result **byte for byte in the `.owdoc` export**."* The archive is byte-stable by
    construction -- `archive/owdoc.py` pins every `ZipInfo` and has a byte-identical re-export
    among its own tests -- so a difference in these bytes is a difference in the store and never
    in the writer.

    Read-only: `connect_readonly` perturbs nothing, which matters because the mtime it would
    otherwise move is the one the freshness check reads (07 section 10.3).

    The `ow` verb: `ow doc export`.
    """
    connection = ow.connect_readonly(path)
    try:
        export(_StoreExport(connection), out)
    finally:
        connection.close()
    return out.read_bytes()


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Everything two runs are compared on. Two equal `Fingerprint`s are two equal stores.

    `owdoc` is the `.owdoc` export's sha256 -- 16-roadmap.md:437's byte-for-byte comparison, held
    as a digest so a report can print it. `work` and `tables` are the runtime rows the archive
    cannot see: 07:2730-2733 names five participants and the archive carries only the first, so
    an export-only comparison would be blind to four fifths of the sentence under test.

    `sidecars` is fixture mode `arbitrary_checkpoint_location`'s assertion: the file names beside
    the store, so a stray checkpoint appearing anywhere is a difference rather than a shrug.
    """

    owdoc: str
    work: str
    tables: Mapping[str, str]
    sidecars: tuple[str, ...]

    def differences(self, other: Fingerprint) -> tuple[str, ...]:
        """Which fields differ, named. Empty means the two stores are the same store."""
        out: list[str] = []
        if self.owdoc != other.owdoc:
            out.append(f"owdoc {self.owdoc[:16]} != {other.owdoc[:16]}")
        if self.work != other.work:
            out.append(f"work {self.work[:16]} != {other.work[:16]}")
        for table in sorted({*self.tables, *other.tables}):
            mine, theirs = self.tables.get(table), other.tables.get(table)
            if mine != theirs:
                out.append(f"{table} {mine} != {theirs}")
        if self.sidecars != other.sidecars:
            out.append(f"sidecars {self.sidecars} != {other.sidecars}")
        return tuple(out)


def _digest(rows: Iterable[Sequence[Any]]) -> str:
    """A stable digest of a row set. `blake2b`, because `01` says every sampled thing is."""
    hasher = hashlib.blake2b(digest_size=16)
    for row in rows:
        hasher.update(
            json.dumps(
                [value.hex() if isinstance(value, bytes) else value for value in row],
                sort_keys=True,
                allow_nan=False,
            ).encode()
        )
        hasher.update(b"\x1e")
    return hasher.hexdigest()


def fingerprint(path: Path, out: Path) -> Fingerprint:
    """The whole comparable state of the store at `path`. `out` receives the `.owdoc` export.

    `out` is a parameter and not a temporary this function invents, because `Path(".")` and an
    ambient temp directory are both banned in library code (02:392) and because a caller that
    wants to keep the two archives for a diff should be able to.

    The `ow` verb: `ow store verify` reads the same rows for a different question.
    """
    archive = owdoc_bytes(path, out)
    connection = ow.connect_readonly(path)
    try:
        work = _digest(
            connection.execute(
                f"SELECT {', '.join(WORK_FINGERPRINT_COLUMNS)} FROM work ORDER BY id"  # noqa: S608
            )
        )
        tables = {
            table: _digest(connection.execute(f"SELECT * FROM {table}"))  # noqa: S608
            for table in _RUNTIME_TABLES
        }
    finally:
        connection.close()
    return Fingerprint(
        owdoc=hashlib.sha256(archive).hexdigest(),
        work=work,
        tables=MappingProxyType(tables),
        sidecars=tuple(sorted(p.name for p in path.parent.iterdir() if p.name != out.name)),
    )


# ---------------------------------------------------------------------------------------------
# 9. One boundary, and the whole matrix.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    """One kill-and-verify cycle: what was killed, what converged, and what did not."""

    mode: str
    boundary: str
    ok: bool
    reached: tuple[str, ...]
    differences: tuple[str, ...]
    integrity: str
    reclaimed_wal_bytes: int

    @property
    def label(self) -> str:
        return f"{self.mode}/{self.boundary}"


@dataclass(frozen=True, slots=True)
class MatrixReport:
    """Every cycle the matrix ran, and whether all of them converged."""

    results: tuple[BoundaryResult, ...]
    baseline: Fingerprint

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    @property
    def failures(self) -> tuple[BoundaryResult, ...]:
        return tuple(result for result in self.results if not result.ok)


def baseline(root: Path, *, now_ns: int, scenarios: Sequence[Scenario] = SCENARIOS) -> Fingerprint:
    """The uninterrupted run: seed, run every scenario to completion, fingerprint.

    The `ow` verb: `ow run` over the whole fixture corpus, then `ow doc export`.

    This is the right-hand side of G21's *"store equals an uninterrupted run"*. It is built in its
    own directory and rebuilt for each cycle's comparison target rather than shared, because a
    fingerprint that came out of the same file the crashed run wrote would pin agreement and not
    value -- and a round trip that reads its expected value out of the database it is checking
    cannot fail.
    """
    path = root / "index.owstore"
    seed(path, root / "cas", now_ns=now_ns, scenarios=scenarios)
    for scenario in scenarios:
        run_scenario(path, root / "cas", scenario)
    return fingerprint(path, root / "baseline.owdoc")


def _integrity(path: Path) -> str:
    """`PRAGMA integrity_check` plus `PRAGMA foreign_key_check`, as one word or a complaint.

    Fixture mode `non_atomic_write`'s assertion: DataFlow's crash leaves a checkpoint that cannot
    be parsed and can only be deleted; a crash here has to leave a store SQLite itself calls
    sound.
    """
    connection = ow.connect_readonly(path)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != "ok":
        return integrity
    return "ok" if not violations else f"foreign_key_check: {violations!r}"


def verify_boundary(
    root: Path,
    mode: str,
    boundary: str,
    *,
    now_ns: int,
    now_ms: int,
    baseline: Fingerprint,
    scenarios: Sequence[Scenario] = SCENARIOS,
    wal_heal_mb: int | None = None,
    kill: Callable[[Path, Path, Scenario, str], RunReport] = simulate_kill_at,
) -> BoundaryResult:
    """One kill-and-verify cycle: seed, run, kill at `boundary`, resume, compare to `baseline`.

    `kill` is the seam that makes this the same function for both halves of G21. Its default is
    `simulate_kill_at`, the in-process model; `tools/gate_crash.py` passes a callable that spawns
    a child, waits for it to park at the boundary and sends the real signal. Everything else --
    the seeding, the resume, the comparison -- is identical between the two, which is what stops
    the cheap harness and the real gate from testing different things.

    `root` must be an empty directory: this creates the store, the CAS and two archives in it.
    """
    path = root / "index.owstore"
    cas = root / "cas"
    seed(path, cas, now_ns=now_ns, scenarios=scenarios)
    by_mode = {scenario.mode: scenario for scenario in scenarios}
    target = by_mode[mode]
    for scenario in scenarios:
        if scenario.mode == mode:
            break
        run_scenario(path, cas, scenario)
    report = kill(path, cas, target, boundary)
    opened = reopen(path, wal_heal_mb=wal_heal_mb)
    with opened:
        pass
    resume(path, cas, now_ms=now_ms, scenarios=scenarios, wal_heal_mb=wal_heal_mb)
    for scenario in scenarios:
        run_scenario(path, cas, scenario, wal_heal_mb=wal_heal_mb)
    integrity = _integrity(path)
    got = fingerprint(path, root / "resumed.owdoc")
    differences = got.differences(baseline)
    return BoundaryResult(
        mode=mode,
        boundary=boundary,
        ok=not differences and integrity == "ok",
        reached=report.reached,
        differences=differences,
        integrity=integrity,
        reclaimed_wal_bytes=opened.reclaimed,
    )


def crash_matrix(
    workspace: Path,
    *,
    now_ns: int,
    now_ms: int,
    points: Sequence[tuple[str, str]] | None = None,
    scenarios: Sequence[Scenario] = SCENARIOS,
    wal_heal_mb: int | None = None,
    kill: Callable[[Path, Path, Scenario, str], RunReport] = simulate_kill_at,
) -> MatrixReport:
    """`ow test crash-matrix`. Run one kill-and-verify cycle per point and report every one.

    `points is None` is `--statement-boundaries all` (16-roadmap.md:445), the T5 soak form
    (13-quality.md:252) and G21's nightly `full matrix`: forty cycles. A caller that passes
    `kill_points()` gets G21's PR form, three deterministically-drawn points.

    `workspace` must be an existing, empty directory; each cycle gets a subdirectory of it, and so
    does the baseline. Nothing is deleted here: a failing cycle's two archives are left on disk
    beside each other, which is the whole reason a byte comparison is worth more than a boolean.

    The `ow` verb: `ow test crash-matrix`.
    """
    chosen = matrix_boundaries(scenarios) if points is None else tuple(points)
    base_dir = workspace / "baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    base = baseline(base_dir, now_ns=now_ns, scenarios=scenarios)
    results: list[BoundaryResult] = []
    for index, (mode, boundary) in enumerate(chosen):
        cycle = workspace / f"cycle{index:03d}"
        cycle.mkdir(parents=True, exist_ok=True)
        results.append(
            verify_boundary(
                cycle,
                mode,
                boundary,
                now_ns=now_ns,
                now_ms=now_ms,
                baseline=base,
                scenarios=scenarios,
                wal_heal_mb=wal_heal_mb,
                kill=kill,
            )
        )
    return MatrixReport(results=tuple(results), baseline=base)
