"""The `parse/1` Operator: hops 10-17 of 02-architecture.md section 4.1, for one claimed batch.

```text
hop 10  run.dispatch        the Supervisor's claim, one dispatch_key, formed into a Batch
hop 11  run.pipeline        build(subproc_host(...) | inproc_host(...)) -- with_events always
hop 12  host.subproc  S4    launch(): listen, spawn, contain, accept, HELLO, HELLO_ACK
        host.inproc   S1    DriverGuard over a resolve() Candidate, the driver built once per key
hop 13  the driver          parse(unit, PartSelector(), io) -> owdoc-fragment/1, child or host
hop 14  host.wire           S4: RESULT, one frame per unit, produced rebuilt host-side (D583)
hop 15  this module         DriverResult -> StepResult: identity, cache_key, the empty check
hop 16  store.fragment      the fragment decoded into DocSink; end_page commits per page
hop 17  Store.complete      work 'done' + unit 'settled' in one transaction (ParseLedger)
```

`ow ingest` stopped at hop 9 until W7.3z: a planned `parse.office` row waited for an executor that
did not exist, and `NoExecutorError` (D578) named that. This is the executor, for both seams a
`parse/1` card can be granted:

* **S4**, a worker process -- what the first-party office driver is granted on a checkout, whose
  editable install has no pinned trust (D576);
* **S1**, in process -- the office card's own request, `[isolation] requires = "inproc"`, granted
  when DR9's six conjuncts hold: a pinned first-party trust among them, which is a wheel install.

Which one ran is the row's `dispatch_key`, recomputed for both modes (`_granted`), and nothing
after the driver call can tell the two apart: `pipeline.inproc_host` answers with `subproc_host`'s
`Reply` shape, so hops 15-17 are one code path.

## What S1 does not do that S4 does

* **Contain a crash.** 04:1826: *"an `inproc` segfault kills the run"*. That asymmetry is DR9's
  whole justification, and it is why the grant is `resolve()`'s and re-checked here only as an
  identity: the guard is built from the `Candidate` `resolve()` returns for this driver, and a
  candidate granted anything but `inproc` refuses to become a guard.
* **Arm an egress hook.** 14:875 covers an `inproc` driver by *"the host's hook"*, and `ow ingest`
  arms none: a PEP 578 hook cannot be removed, and arming one in the supervisor would bind the
  whole run to one driver's `needs_network`. DR9 bars `needs_network = true` from `inproc`, so the
  first net holds; the second is not here (D597).
* **Bound memory.** A job object caps a worker; nothing caps a thread. `[isolation] memory_mb` is
  S4's.

**Neither `[runtime]` S1 knob is read here (D598).** `max_inproc = 2` bounds S1 calls in flight
(02:828), and the per-key lock -- one driver object serves every batch of its key, and a driver is
not promised to be re-entrant -- already holds one key to one call. One driver is `inproc`-eligible,
so at most one S1 call is ever in flight and the bound holds with nothing reading it; the second
eligible driver is when it needs a reader. `inproc_bulk_threshold` -- the host switching to a worker
past 64 units -- is a planning decision about the `dispatch_key`, and is not made here.

## Where the source bytes come from

A `parse/1` driver consumes `raw_bytes` -- *"a CAS blob plus a `UnitRef`"* (04:566) -- and opens
them through `io.blobs.open(unit.content_sha256)`. 02:69 puts the CAS write in `run/discover.py`
(*"the `unit` roster + CAS blobs"*); the shipped acquisition hashes a file without keeping it, so
this Operator stages each unit's bytes into the CAS at dispatch, once, and names the blob in the
`INVOKE` unit's `blob_ref`. A file whose raw digest no longer matches the unit's recorded one
changed after it was identified, and is failed as `corrupt_input` rather than parsed under a key
that describes other bytes (D582).

## What `complete()` writes, and what it cannot

02:487 has hop 17 write *"in **one** transaction: the derived rows, `work.status='done'` +
`work.cache_key`, the `dep` rows, the reservation commit and the `route_spend` row (I20)"*. The
derived rows of a parse are `DocSink`'s, and `DocSink` commits its own transactions -- one per page
and one in `end_doc` that makes the generation visible (03:585, 03:586). So the document is visible
**before** `complete()` runs, and a crash between the two leaves a committed generation beside a
claimed row that the reaper returns; the re-parse writes the next generation and `rebind` carries
identity across. The `unit`'s move to `settled` does ride in `complete()`'s transaction, through
`ParseLedger`. The dep rows, the reservation commit and the spend row are not written: the office
driver is `free`, admits at DECODE with no reservation, and `route_spend` is P4's (D585).

## A document password (ADR-15 D15.4)

*"The host writes it to a file in the one invocation's `DriverIO.tmpdir`, which the host deletes
(14:1060), and the driver reads it there. `DriverIO` keeps its four fields (INV-6)."* For each unit
`[ingest] password_file` maps, the secret is written to `host.keystore.PASSWORD_FILENAME` in that
unit's scratch directory before the call: by `_Source.invocation` for S4, into the directory the
worker is about to hand the driver (`<tmp>/<invoke_id>/<index>`, `worker._invoke`'s own layout),
and by `_Guarded.work` for S1, into the one `inproc_host` just made. The worker removes each unit's
scratch after its call; this Operator removes the invocation's whole directory after the reply,
whatever the worker did, so a crashed worker leaves no password behind. The secret is in no
`INVOKE` header, no `HELLO`, no `effective_config` and no digest.

Specified in 02-architecture.md section 4.1 rows 10-17, 08-runtime.md sections 1.3 and 6.1, and
04-driver-system.md section 6.2.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, BinaryIO, Final, cast

from omniweave_core.errors import ModelError, RouteError
from omniweave_core.host import keystore, subproc
from omniweave_core.limits import MAX_ASSET_TOTAL_BYTES, MAX_ENTRY_BYTES
from omniweave_core.model.block import Capabilities
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_core.store.queue import Statement
from omniweave_core.work import rung_for
from omniweave_ports.types import (
    ArtifactRef,
    DriverIO,
    DriverResult,
    FailureClass,
    Isolation,
    UnitRef,
)

from omniweave.run import pipeline
from omniweave.run.dispatch import (
    AimdRegistry,
    Regroup,
    batch_event,
    dispatch_key,
    regroup,
    start_batch,
)
from omniweave.run.routing import PORT as PARSE_PORT

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.blobs import BlobStore
    from omniweave_core.config import Config
    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.drivers.catalog import Catalog
    from omniweave_core.drivers.resolve import Policy
    from omniweave_core.host.inproc import DriverGuard
    from omniweave_core.host.worker import WorkerBlobs
    from omniweave_core.operator import RunContext
    from omniweave_core.store.queue import StepResultView, WorkRow

    from omniweave.run.dispatch import Batch
    from omniweave.run.passwords import Passwords
    from omniweave.run.pipeline import Call, Reply

__all__ = [
    "DEFAULT_EGRESS_MODE",
    "MAX_OUTPUT_BYTES",
    "MODEL_VERSION",
    "PARSE_FAILED_SQL",
    "SETTLED_SQL",
    "Ordinals",
    "ParseLedger",
    "ParseOperator",
    "ParseTally",
    "is_parse",
    "worker_env",
]

MAX_OUTPUT_BYTES: Final[int] = MAX_ENTRY_BYTES + MAX_ASSET_TOTAL_BYTES
"""`DriverIO.max_output_bytes` for a parse: one document's largest input plus every asset it may
carry. 04:1795 makes this *"the host's number"* and no plan line gives it a value (charter
D3's `max_output_bytes: int` has none either), so it is derived from the two ceilings a parse's
output is already bounded by -- the fragment by the source it describes, the assets by
`MAX_ASSET_TOTAL_BYTES` -- rather than invented (D583)."""

MODEL_VERSION: Final[str] = "1.1"
"""`doc.model_version`: `tools/wirekeys.toml`'s `model_version`, which 03:687 fixes at 1.1."""

DEFAULT_EGRESS_MODE: Final[str] = "granted"
"""14:829's default `[egress] mode`, sent on `HELLO` (14:867). `config.py` declares no
`egress.mode` key yet, so the shipped default is the only value there is to send (D584)."""

SETTLED_SQL: Final[str] = """
UPDATE unit SET state = 'settled', settled_gen = :gen, stale_since = NULL
 WHERE unit_uri = :unit_uri AND state IN ('planned', 'running')
"""
"""05:404's `running -> settled`, *"every part terminal; doc.status in ok|partial"*. From
`planned` as well, because this build moves no unit to `running` (D585).

`stale_since` is cleared, and this is the one statement that clears it (D645). 08:1891 keeps it
*"across a reset, because it measures how long the answer has been untrustworthy"*: a retry, a
failure and a re-open all keep it, and only the new bytes settling ends that time."""

PARSE_FAILED_SQL: Final[str] = """
UPDATE unit SET state = 'failed', acq_failure_class = :failure_class
 WHERE unit_uri = :unit_uri AND state IN ('planned', 'running')
"""
"""05:405's `failed`, *"a permanent FailureClass, no doc row"*. `acq_failure_class` for
`expand.IDENTIFY_FAILED_SQL`'s reason: `unit` has one column for why a unit stopped."""

_UNIT_SQL: Final[str] = """
SELECT content_sha256, bytes, media_type, normalizer, derived FROM unit WHERE unit_uri = ?
"""
_PRODUCER_INSERT_SQL: Final[str] = """
INSERT OR IGNORE INTO producer(operator, op_version, code_fingerprint, options_digest)
VALUES(:operator, :op_version, :code_fingerprint, :options_digest)
"""
_PRODUCER_ID_SQL: Final[str] = """
SELECT producer_id FROM producer
 WHERE operator = :operator AND op_version = :op_version AND code_fingerprint = :code_fingerprint
   AND options_digest = :options_digest AND model_id IS NULL AND model_rev IS NULL
   AND runtime IS NULL AND runtime_version IS NULL AND prompt_fp IS NULL
"""
_HELLO_DEADLINES: Final = subproc.Deadlines(progress_ms=0, wall_ms_hard=60_000, deadline_ms=0)
"""`HELLO` runs under `wall_ms_hard` alone: a worker that imports its driver and answers nothing
in a minute is not a worker, and there is no `PROGRESS` to wait for before `HELLO_ACK`."""


def is_parse(operator: str) -> bool:
    """A routed `parse.*` row -- 02:479's operator, the driver's port family."""
    return operator.startswith("parse.")


# =============================================================================================
# doc_ord, reserved in path order
# =============================================================================================

_TO_PARSE_SQL: Final[str] = """
SELECT u.content_sha256 FROM work AS w JOIN unit AS u USING (unit_uri)
 WHERE w.operator LIKE 'parse.%' AND w.status IN ('pending', 'claimed', 'failed_transient')
   AND u.content_sha256 IS NOT NULL
 ORDER BY w.unit_uri, w.unit_part
"""
_NEXT_ORD_SQL: Final[str] = "SELECT IFNULL(MAX(doc_ord), 0) + 1 FROM doc"
_KNOWN_CHUNK: Final[int] = 900
"""Doc keys per `IN (...)` probe, under SQLite's default 999 host parameters."""


class Ordinals:
    """The `doc_ord` each first-sight document of the run takes, fixed before any parse settles.

    `doc_ord` is the row a document's first write inserts, and parses settle on as many threads as
    a class has workers, in whatever order they finish. So two ingests of one folder numbered the
    same documents differently, and every cite an Answer printed (`d77#2`) named a number the same
    inputs did not reproduce (D653, D654). Routing has finished before the parse drain starts, so
    every unit the run will parse is in `work` by then: `reserve` numbers the documents not yet in
    the store in `unit_uri` order, from the next free ordinal, and a parse takes its document's.

    A unit that fails keeps its number unused, so a store's ordinals can have gaps, as they already
    do after `ow corpus rm`. A document the reservation did not see -- one whose parse row was
    written after it -- takes the next number past the reserved ones. Before `reserve`, as in the
    drain that finishes an interrupted run before routing, nothing is reserved and `take` answers
    `None`, which is SQLite's own choice.
    """

    __slots__ = ("_guard", "_next", "_reserved")

    def __init__(self) -> None:
        self._reserved: dict[bytes, int] = {}
        self._next: int | None = None
        self._guard = threading.Lock()

    def reserve(self, thread: ow.StoreThread) -> int:
        """Number the run's unparsed documents in path order. Returns how many were numbered."""
        found = thread.run(
            ow.Unit(
                name="parse.reserve_ordinals",
                run=_to_number,
                cost_class="free",
                wait_ms=ow.BATCH_WAIT_MS,
            )
        )
        keys, start, known = cast("tuple[list[bytes], int, set[bytes]]", found)
        reserved: dict[bytes, int] = {}
        for key in keys:
            if key not in known and key not in reserved:
                reserved[key] = start + len(reserved)
        with self._guard:
            self._reserved = reserved
            self._next = start + len(reserved)
        return len(reserved)

    def take(self, doc_key: bytes) -> int | None:
        """This document's reserved ordinal, the next one past them, or `None` before `reserve`."""
        with self._guard:
            if self._next is None:
                return None
            found = self._reserved.get(doc_key)
            if found is None:
                found = self._reserved[doc_key] = self._next
                self._next += 1
            return found


def _to_number(connection: object) -> tuple[list[bytes], int, set[bytes]]:
    """The doc keys of the run's parse rows in path order, the next ordinal, and those stored."""
    rows = connection.execute(_TO_PARSE_SQL).fetchall()  # type: ignore[attr-defined]
    keys = [bytes.fromhex(str(row[0]))[:16] for row in rows]
    start = int(connection.execute(_NEXT_ORD_SQL).fetchone()[0])  # type: ignore[attr-defined]
    known: set[bytes] = set()
    distinct = list(dict.fromkeys(keys))
    for at in range(0, len(distinct), _KNOWN_CHUNK):
        chunk = distinct[at : at + _KNOWN_CHUNK]
        marks = ",".join("?" * len(chunk))
        found = connection.execute(  # type: ignore[attr-defined]
            f"SELECT doc_key FROM doc WHERE doc_key IN ({marks})",  # noqa: S608 -- marks only
            chunk,
        )
        known.update(bytes(row[0]) for row in found)
    return keys, start, known


# =============================================================================================
# The complete() contribution
# =============================================================================================


class ParseLedger:
    """The `derived_rows` contribution for `parse.*` rows: the unit's terminal move.

    `expand.IdentifyLedger`'s shape and argument, for a second operator: the contribution needs the
    unit and the generation, and `StepResultView` carries neither, so the Operator records them
    before `complete()` and the caller forgets them once the commit stuck.
    """

    __slots__ = ("_rows",)

    def __init__(self) -> None:
        self._rows: dict[int, tuple[str, int]] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def record(self, row_id: int, unit_uri: str, generation: int) -> None:
        self._rows[row_id] = (unit_uri, generation)

    def forget(self, row_id: int) -> None:
        self._rows.pop(row_id, None)

    def __call__(self, row_id: int, result: StepResultView) -> Sequence[Statement]:
        known = self._rows.get(row_id)
        if known is None:
            return ()
        unit_uri, generation = known
        if result.outcome in (Outcome.OK, Outcome.OK_PARTIAL):
            return (
                Statement(
                    participant="derived_rows",
                    name="unit_settled",
                    sql=SETTLED_SQL,
                    params={"unit_uri": unit_uri, "gen": generation},
                ),
            )
        if result.outcome == Outcome.FAILED_PERMANENT:
            return (
                Statement(
                    participant="derived_rows",
                    name="unit_parse_failed",
                    sql=PARSE_FAILED_SQL,
                    params={"unit_uri": unit_uri, "failure_class": result.failure_class},
                ),
            )
        return ()


# =============================================================================================
# The report
# =============================================================================================


@dataclass(slots=True)
class ParseTally:
    """What the parse hops did, for `IngestReport`. Counts only; the rows are the record."""

    parsed: Counter[str] = field(default_factory=Counter)
    failed: Counter[str] = field(default_factory=Counter)
    docs: int = 0
    blocks: int = 0
    asset_links_dropped: int = 0
    calls: int = 0
    workers: int = 0
    inproc: int = 0
    """Driver objects built in the host's interpreter, one per `(driver_id, config_digest)`."""
    regrouped: int = 0
    """Units sent to a worker again in a smaller call after a memory verdict or a crash (D657)."""

    def emit(self, *, kind: object, fields: Mapping[str, object]) -> None:
        """`with_events`' sink. No trace sink is wired into `ow ingest` yet, so the `call.begin`
        and `call.end` pair is counted here rather than dropped: one `calls` per `INVOKE`."""
        del fields
        if str(kind).endswith("end"):
            self.calls += 1

    def lines(self) -> list[str]:
        if not (self.parsed or self.failed):
            return []
        drivers = ", ".join(f"{name} {n}" for name, n in sorted(self.parsed.items()))
        out = [
            f"  parse     {sum(self.parsed.values())} parsed ({drivers or 'none'}), "
            f"{self.docs} documents, {self.blocks} blocks, {self.calls} INVOKE over "
            f"{self.workers} worker(s)" + (f" and {self.inproc} in process" if self.inproc else "")
        ]
        if self.failed:
            classes = ", ".join(f"{name} {n}" for name, n in sorted(self.failed.items()))
            out.append(f"  parse     {sum(self.failed.values())} failed ({classes})")
        if self.regrouped:
            out.append(
                f"  parse     {self.regrouped} unit(s) sent again in a smaller batch after a "
                f"memory limit or a crash in theirs"
            )
        if self.asset_links_dropped:
            out.append(
                f"  parse     {self.asset_links_dropped} block->asset links not written: DocSink "
                f"has no block_asset writer (D586)"
            )
        return out


# =============================================================================================
# The Operator
# =============================================================================================


@dataclass(frozen=True, slots=True)
class _Granted:
    """What routing decided for a card, recomputed from the same inputs and checked against the
    row's own `dispatch_key` -- so a config edited since planning is caught, not served."""

    card: DriverCard
    effective_config: Mapping[str, Any]
    config_digest: str
    isolation: Isolation


@dataclass(frozen=True, slots=True)
class _Staged:
    unit: UnitRef
    blob_ref: str
    normalizer: str | None
    format_evidence: Mapping[str, Any]
    raw_digest: bytes


class ParseOperator:
    """The `Dispatcher` for `parse.*` rows. One call per claimed batch; one `StepResult` per row.

    Holds the run's `WorkerPool`, which is run-scoped (02:677): `close()` stops every worker and
    `ow ingest` calls it when the drain ends.
    """

    __slots__ = (
        "_aimd",
        "_aimd_lock",
        "_cas",
        "_catalog",
        "_config",
        "_ctx",
        "_drivers",
        "_executable",
        "_launches",
        "_ledger",
        "_locks",
        "_locks_guard",
        "_ordinals",
        "_passwords",
        "_pool",
        "_producers",
        "_resolving",
        "_settings",
        "_sink_lock",
        "_spawn",
        "_tally",
        "_thread",
        "_tmp",
    )

    def __init__(
        self,
        thread: ow.StoreThread,
        *,
        ctx: RunContext,
        config: Config,
        catalog: Catalog,
        resolving: Policy,
        cas: BlobStore,
        ledger: ParseLedger,
        tally: ParseTally,
        executable: str = sys.executable,
        spawn: Callable[..., subproc.WorkerProcess] = subproc.spawn_worker,
        passwords: Passwords | None = None,
        ordinals: Ordinals | None = None,
    ) -> None:
        self._thread = thread
        self._ctx = ctx
        self._config = config
        self._catalog = catalog
        self._resolving = resolving
        self._cas = cas
        self._ledger = ledger
        self._tally = tally
        self._executable = executable
        self._spawn = spawn
        self._settings = subproc.HostSettings.from_config(config)
        self._pool = subproc.WorkerPool(spawn=spawn, settings=self._settings, now_ms=self._now_ms)
        self._producers: dict[tuple[str, int, str], int] = {}
        self._tmp = Path(ctx.roots.cache) / "tmp" / ctx.run_id
        self._launches = 0
        self._locks: dict[subproc.WorkerKey, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._sink_lock = threading.Lock()
        self._drivers: dict[subproc.WorkerKey, object] = {}
        self._passwords = passwords
        self._ordinals = ordinals
        self._aimd = AimdRegistry()
        self._aimd_lock = threading.Lock()

    def _now_ms(self) -> int:
        return self._ctx.clock.monotonic_ns() // 1_000_000

    def close(self) -> None:
        """Stop every worker. `SHUTDOWN`, then the uncatchable step (`Worker.stop`)."""
        self._pool.close()

    def secret_for(self, unit_uri: str) -> str | None:
        """The password `[ingest] password_file` maps this unit to, or `None` (D15.4)."""
        return None if self._passwords is None else self._passwords.secret_for(unit_uri)

    # -- the batch -----------------------------------------------------------------------------

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]:
        driver = batch.driver
        if driver is None:
            raise RouteError(
                f"invoke {batch.invoke_id} has no driver; a parse row is routed (02:452-461)",
                fix="ow ingest again: an unrouted row is a planner bug and the reaper returns it",
            )
        granted = self._granted(driver, batch.dispatch_key or "")
        operator = batch.rows[0].operator
        producer = Producer(
            operator=operator,
            op_version=granted.card.identity.schema_version,
            code_fingerprint="",
            options_digest=bytes.fromhex(granted.config_digest),
        )
        staged: list[_Staged | StepResult] = [self._stage(row, producer) for row in batch.rows]
        ready = [i for i, one in enumerate(staged) if isinstance(one, _Staged)]
        results: list[StepResult | None] = [
            one if isinstance(one, StepResult) else None for one in staged
        ]
        if ready:
            answers = self._answers(batch, ready, staged, granted=granted, operator=operator)
            for index in ready:
                reply, slot = answers[index]
                results[index] = self._settle(
                    batch.rows[index],
                    cast("_Staged", staged[index]),
                    reply,
                    slot,
                    granted=granted,
                    producer=producer,
                )
        out: list[StepResult] = []
        for row, result in zip(batch.rows, results, strict=True):
            assert result is not None  # noqa: S101 -- every index is staged or settled above.
            self._ledger.record(row.id, row.unit_uri, self._ctx.generation)
            out.append(result)
        return out

    def _answers(
        self,
        batch: Batch,
        ready: Sequence[int],
        staged: Sequence[_Staged | StepResult],
        *,
        granted: _Granted,
        operator: str,
    ) -> dict[int, tuple[Reply, int]]:
        """Each ready row's reply and its slot in it, over as many calls as that takes. **D657.**

        While nothing goes wrong a claimed batch is one call. Under `subproc` it is first cut to
        the size AIMD has learned for the worker key (08-runtime.md:760), and a call whose
        verdicts `dispatch.regroup` reads as being about the company a unit kept -- a memory
        verdict, a crash -- sends those units again in smaller calls, each under its own invoke id,
        until each has an answer about itself. Before D657 the mechanisms existed and nothing
        called them, so `ow add` over office-200 failed nine to eleven spreadsheets a run, small
        ones among them, for sitting in a batch beside a large one; it now settles 199 of 200.

        In process there is no shared worker memory to halve and a crash is the run's (04:1826),
        so S1 makes the one call it always made.
        """
        key = subproc.WorkerKey(granted.card.identity.id, granted.config_digest)
        localise = granted.isolation is Isolation.SUBPROC
        ceiling = self._ceiling(granted) if localise else len(ready)
        with self._aimd_lock:
            size = self._aimd.size(key, ceiling=ceiling) if localise else len(ready)
        todo = deque(Regroup(tuple(ready[i : i + size])) for i in range(0, len(ready), size))
        answers: dict[int, tuple[Reply, int]] = {}
        calls = 0
        while todo:
            group = todo.popleft()
            invoke_id = batch.invoke_id if calls == 0 else f"{batch.invoke_id}.{calls}"
            calls += 1
            reply = self._call(
                batch, invoke_id, group.slots, staged, granted=granted, operator=operator
            )
            failures = (
                reply.report.failures if reply.report is not None else (None,) * len(group.slots)
            )
            again = regroup(group, failures) if localise else ()
            if any(len(one.slots) >= len(group.slots) for one in again):
                #  Every regroup must shrink, or this loop is a worker billed forever for one
                #  batch. `adapt_batch` and `retry_batch_size` both shrink; this holds them to it.
                raise RouteError(
                    f"a call of {len(group.slots)} unit(s) was regrouped no smaller "
                    f"({[len(one.slots) for one in again]}), which would never end",
                    fix="dispatch.regroup must return calls smaller than the one they came from",
                )
            if localise:
                with self._aimd_lock:
                    self._aimd.observe(key, batch_event(failures), ceiling=ceiling)
            going = {slot for one in again for slot in one.slots}
            self._tally.regrouped += len(going)
            for position, index in enumerate(group.slots):
                if index not in going:
                    answers[index] = (reply, position)
            todo.extend(again)
        return answers

    def _call(
        self,
        batch: Batch,
        invoke_id: str,
        slots: Sequence[int],
        staged: Sequence[_Staged | StepResult],
        *,
        granted: _Granted,
        operator: str,
    ) -> Reply:
        """One `INVOKE` of the rows at `slots`, through the middleware chain."""
        chosen = [cast("_Staged", staged[i]) for i in slots]
        call = pipeline.Call(
            batch=type(batch)(invoke_id=invoke_id, rows=tuple(batch.rows[i] for i in slots)),
            units=tuple(one.unit for one in chosen),
            operator=operator,
            deadline_ms=granted.card.isolation.wall_ms_hard,
        )
        host = (
            pipeline.inproc_host(_Guarded(self, granted, chosen))
            if granted.isolation is Isolation.INPROC
            else pipeline.subproc_host(_Source(self, granted, chosen))
        )
        handler = pipeline.build(host, emit=self._tally.emit, isolation=str(granted.isolation))
        try:
            with self._lock(subproc.WorkerKey(granted.card.identity.id, granted.config_digest)):
                return handler(call)
        finally:
            #  D15.4: the host deletes the invocation's tmpdir, and a password file with it.
            shutil.rmtree(self._tmp / invoke_id, ignore_errors=True)

    def _ceiling(self, granted: _Granted) -> int:
        """`start_batch()`: `[runtime.claim] batch` for the card's class, clamped by the card."""
        from omniweave.run.supervisor import claim_batch_of  # noqa: PLC0415 -- no import cycle

        card = granted.card
        cost = card.cost_model.cost_class if card.cost_model is not None else "free"
        return start_batch(
            claim_batch_of(self._config), str(cost), card_max=card.isolation.batch_max_units
        )

    def _lock(self, key: subproc.WorkerKey) -> threading.Lock:
        """One lock per worker key, held across the pool's acquire and the whole `INVOKE`.

        The Supervisor dispatches claimed batches on worker threads, concurrently (08:648's
        `to_thread` executor), and two batches of one `dispatch_key` are two calls on ONE worker --
        02:482's *"one worker per `(driver_id, config_digest)`"*. A worker's channel carries one
        conversation, and `WorkerPool` is not a thread-safe structure: measured, the second of two
        concurrent first batches built a second worker under the first one's pipe name and died on
        `ERROR_PIPE_BUSY` (231), stranding its eight rows `claimed` until the lease reaper came
        (D588). Serialising per key keeps the plan's one-worker property and costs nothing the
        plan did not already price: one worker processes one `INVOKE` at a time either way.
        """
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _granted(self, driver: str, key: str) -> _Granted:
        card = self._catalog.cards.get(driver)
        if card is None:
            raise RouteError(
                f"{driver} was routed and is not in this run's catalog",
                fix="reinstall the driver, or ow ingest again to re-route the unit",
            )
        supplied = self._resolving.driver_config.get(driver, {})
        effective = card.config.effective(supplied)
        from omniweave_core.canonical import sha256_canonical  # noqa: PLC0415

        digest = sha256_canonical(effective)
        for isolation in (Isolation.SUBPROC, Isolation.INPROC):
            if dispatch_key(driver, digest, str(isolation)) == key:
                return _Granted(card, MappingProxyType(dict(effective)), digest, isolation)
        raise RouteError(
            f"{driver}'s dispatch_key {key} matches neither isolation under the current config; "
            f"the driver's [drivers] config changed after the row was planned",
            fix="ow ingest again after the lease expires; the unit is re-routed under the new "
            "config",
        )

    def _stage(self, row: WorkRow, producer: Producer) -> _Staged | StepResult:
        """The unit's bytes into the CAS, checked against the digest identify recorded."""
        found = self._read(_UNIT_SQL, (row.unit_uri,))
        if found is None or not found[0]:
            raise RouteError(
                f"work row {row.id} names {row.unit_uri!r}, which has no acquired digest",
                fix="ow ingest again: the lease reaper returns the row",
            )
        content_sha256, size, media_type, normalizer, derived = found
        unit = UnitRef(
            uri=row.unit_uri,
            part=row.unit_part,
            content_sha256=str(content_sha256),
            byte_len=int(size or 0),
            media_type=None if media_type is None else str(media_type),
        )
        try:
            with Path(row.unit_uri).open("rb") as handle:
                raw = self._cas.put(handle)
        except OSError as gone:
            return self._failed(
                row, unit, producer, FailureClass.CORRUPT_INPUT, f"unreadable at parse: {gone}"
            )
        if normalizer is None and raw.hex() != unit.content_sha256:
            return self._failed(
                row,
                unit,
                producer,
                FailureClass.CORRUPT_INPUT,
                "the source changed after it was identified; the next ow ingest re-acquires it "
                "(D582)",
            )
        evidence = _evidence_of(derived)
        from omniweave_core.blobs import format_ref  # noqa: PLC0415

        return _Staged(
            unit=unit,
            blob_ref=format_ref(raw),
            normalizer=None if normalizer is None else str(normalizer),
            format_evidence=evidence,
            raw_digest=raw,
        )

    # -- hop 15 and 16 -------------------------------------------------------------------------

    def _settle(
        self,
        row: WorkRow,
        staged: _Staged,
        reply: Reply,
        slot: int,
        *,
        granted: _Granted,
        producer: Producer,
    ) -> StepResult:
        outcome = reply.outcomes[slot]
        unit = staged.unit
        if outcome not in (Outcome.OK, Outcome.OK_PARTIAL):
            return self._unsettled(
                row, unit, reply=reply, slot=slot, outcome=outcome, producer=producer
            )
        produced = reply.produced[slot] if reply.produced else ()
        if sum(ref.byte_len for ref in produced) > MAX_OUTPUT_BYTES:
            return self._failed(
                row, unit, producer, FailureClass.TOO_LARGE, "produced over max_output_bytes"
            )
        fragments = [ref for ref in produced if ref.kind == "doc_fragment"]
        if len(fragments) != 1:
            return self._failed(
                row,
                unit,
                producer,
                FailureClass.EMPTY_RESULT if not fragments else FailureClass.DRIVER_BUG,
                f"a parse produced {len(fragments)} doc_fragment refs; exactly one is a result",
            )
        fragment = fragments[0]
        refused = self._first_pass(fragment)
        if refused is not None:
            return self._failed(row, unit, producer, *refused)
        doc_key = bytes.fromhex(unit.content_sha256)[:16]
        sink = DocSink(
            self._thread,
            producer_id=self._producer_id(producer),
            origin_operator=producer.operator,
            origin_driver=granted.card.identity.id,
            driver_schema_v=granted.card.identity.schema_version,
            blobs=self._cas,
            decision_id=row.decision_id,
            cost_class=row.cost_class,
            doc_ord=None if self._ordinals is None else self._ordinals.take(doc_key),
        )
        try:
            # ONE OPEN SINK AT A TIME (D589). `DocSink.begin_doc` reads the store's `block_id` and
            # `asset_id` high-water marks once and mints from them in memory until `end_doc`, so
            # two documents decoded on two dispatch threads mint the same ids and the second
            # `end_page` dies on `UNIQUE constraint failed: block.block_id` -- measured on the
            # first fifteen-file corpus. The worker call runs concurrently; the store write, which
            # is serial on the store thread anyway, is serialised here as a whole document.
            self._sink_lock.acquire()
            with self._stream(fragment) as lines:
                decoded = decode(
                    records_of(lines),
                    sink=sink,
                    doc=FragmentDoc(
                        doc_key=doc_key,
                        source_sha256=staged.raw_digest,
                        normalizer=staged.normalizer,
                        uri=unit.uri,
                        source_bytes=unit.byte_len,
                        declared=_declared(granted.card),
                        model_version=MODEL_VERSION,
                        format_evidence=staged.format_evidence,
                    ),
                    assets=[ref for ref in produced if ref.kind == "asset"],
                    open_ref=self._open,
                    open_part=self._retained,
                )
        except ModelError as refused:
            return self._failed(
                row,
                unit,
                producer,
                FailureClass.DRIVER_BUG,
                f"{refused.code()}: {refused}",
            )
        finally:
            self._sink_lock.release()
        self._tally.parsed[granted.card.identity.id] += 1
        self._tally.docs += 1
        self._tally.blocks += decoded.blocks
        self._tally.asset_links_dropped += decoded.asset_links_dropped
        partial = decoded.status == "partial" or outcome is Outcome.OK_PARTIAL
        return StepResult(
            outcome=Outcome.OK_PARTIAL if partial else Outcome.OK,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            produced=tuple(produced),
            partial_reason="the driver reported a partial document" if partial else None,
            metrics=StepMetrics(rows_written=decoded.blocks, peak_rss_bytes=_peak_of(reply, slot)),
        )

    def _unsettled(
        self,
        row: WorkRow,
        unit: UnitRef,
        *,
        reply: Reply,
        slot: int,
        outcome: Outcome,
        producer: Producer,
    ) -> StepResult:
        """A unit the worker did not answer `ok` for: its verdict, transient or permanent."""
        verdict = None if reply.report is None else reply.report.failures[slot]
        failure = FailureClass.DRIVER_CRASHED if verdict is None else verdict.failure_class
        message = "" if verdict is None else verdict.message
        if outcome is Outcome.FAILED_TRANSIENT:
            self._tally.failed[str(failure)] += 1
            rung = rung_for(str(failure), _source_of(verdict))
            cooldown = (
                verdict.retry_after_ms
                if verdict is not None and verdict.retry_after_ms is not None
                else (rung.first_cooldown_ms if rung and rung.first_cooldown_ms else 60_000)
            )
            return StepResult(
                outcome=Outcome.FAILED_TRANSIENT,
                unit=unit,
                identity=producer,
                cache_key=row.cache_key,
                failure_class=failure,
                failure_message=message,
                retry_after_ms=cooldown,
            )
        return self._failed(row, unit, producer, failure, message)

    def _failed(
        self,
        row: WorkRow,
        unit: UnitRef,
        producer: Producer,
        failure: FailureClass,
        message: str,
    ) -> StepResult:
        self._tally.failed[str(failure)] += 1
        return StepResult(
            outcome=Outcome.FAILED_PERMANENT,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            failure_class=failure,
            failure_message=message[:2_048],
        )

    # -- store reads ---------------------------------------------------------------------------

    def _read(self, sql: str, params: tuple[object, ...]) -> tuple[Any, ...] | None:
        row = self._thread.run(
            ow.Unit(
                name="parse.read",
                run=lambda c: c.execute(sql, params).fetchone(),  # type: ignore[attr-defined]
                cost_class="free",
                wait_ms=ow.BATCH_WAIT_MS,
            )
        )
        return cast("tuple[Any, ...] | None", row)

    def _producer_id(self, producer: Producer) -> int:
        key = (producer.operator, producer.op_version, producer.options_digest.hex())
        known = self._producers.get(key)
        if known is not None:
            return known
        params = {
            "operator": producer.operator,
            "op_version": producer.op_version,
            "code_fingerprint": producer.code_fingerprint,
            "options_digest": producer.options_digest,
        }

        def run(connection: object) -> object:
            connection.execute(_PRODUCER_INSERT_SQL, params)  # type: ignore[attr-defined]
            return connection.execute(_PRODUCER_ID_SQL, params).fetchone()  # type: ignore[attr-defined]

        found = self._thread.run(
            ow.Unit(name="parse.producer", run=run, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
        )
        producer_id = int(cast("tuple[int]", found)[0])
        self._producers[key] = producer_id
        return producer_id

    def _stream(self, ref: ArtifactRef) -> BinaryIO:
        """The fragment as lines off a stream: the CAS file, or its inline bytes. Never read whole.

        12-performance.md:229: the supervisor is *"capped at 600 MB by I31 and forbidden from
        holding document bytes"*. Reading the fragment whole and listing its records held both at
        once -- 108 MB of body and 210,000 decoded dicts for `gen_5000p_pdf` -- and the supervisor
        peaked at 1,021,456,384 B (D629). A binary file iterates by line, which is what
        `records_of` takes, so neither pass below holds more than one record (D630).
        """
        if ref.inline is not None:
            return io.BytesIO(ref.inline)
        return cast("BinaryIO", self._open(ref))

    def _first_pass(self, ref: ArtifactRef) -> tuple[FailureClass, str] | None:
        """Every line a JSON object, and at least one block -- or the refusal that says which not.

        Before `DocSink` sees anything, so a fragment with a malformed line or no block writes
        nothing: the property the whole-fragment list gave for free. It parses and discards, so it
        costs one more JSON pass and no memory (D630).
        """
        try:
            with self._stream(ref) as lines:
                blocks = sum(1 for record in records_of(lines) if record.get("t") == "block")
        except ModelError as bad:
            return (FailureClass.DRIVER_BUG, f"{bad.code()}: {bad}")
        if not blocks:
            return (
                FailureClass.EMPTY_RESULT,
                "the fragment has no block: 08:245-249, there is no empty success",
            )
        return None

    def _open(self, ref: ArtifactRef) -> Any:
        from omniweave_core.blobs import parse_ref  # noqa: PLC0415

        return self._cas.open(parse_ref(str(ref.blob)))

    def _retained(self, sha256: bytes) -> Any:
        """A part the driver asked to retain, by digest: the CAS's bytes, or `None` if it has none.

        `_stage()` put the unit's own bytes in the CAS before `INVOKE`, so a part whose digest is
        the source's -- the PDF driver's one `pdf/source.pdf` -- is always there. Any other part is
        retained only if its bytes already are; nothing here fetches (D628).
        """
        return self._cas.open(sha256) if self._cas.has(sha256) else None

    # -- S1: the guard and the driver -----------------------------------------------------------

    def _guard(self, granted: _Granted, call: Call) -> DriverGuard:
        """A `DriverGuard` over the `Candidate` `resolve()` gives this driver for this batch.

        `DriverGuard` takes clearance only as a `resolve()` `Candidate` -- *"clearance for inproc is
        `Candidate.isolation_granted` and cannot be asserted by the caller"* -- and a claimed row
        carries a `dispatch_key`, not a candidate (D596). So the Operator asks `resolve()` the
        question routing asked, over the run's frozen catalog and policy and the batch's media
        type: memoised on the three digests, so the answer is the one routing got. The config digest
        needs no second check -- `_granted` has already matched the row's key against this config's
        -- but the grant does: a policy that stopped granting `inproc` since planning is a refusal,
        not a guard.
        """
        from omniweave_core.drivers.resolve import Requirement, resolve  # noqa: PLC0415
        from omniweave_core.host.inproc import Deadlines, DriverGuard  # noqa: PLC0415

        driver = granted.card.identity.id
        media = call.units[0].media_type or ""
        found = resolve(Requirement(port=PARSE_PORT, format=media), self._catalog, self._resolving)
        candidate = next((one for one in found.candidates if one.driver_id == driver), None)
        if candidate is None or candidate.isolation_granted is not Isolation.INPROC:
            raise RouteError(
                f"{driver}'s row was planned inproc and resolve() no longer grants it for "
                f"{media!r}; the [drivers] policy changed after the row was planned",
                fix="ow ingest again after the lease expires; the unit is re-routed",
            )
        return DriverGuard(
            candidate,
            deadlines=Deadlines.of_card(granted.card.isolation, deadline_ms=call.deadline_ms),
            monotonic_ns=self._ctx.clock.monotonic_ns,
        )

    def _driver(self, granted: _Granted) -> object:
        """The driver object for one `(driver_id, config_digest)`, built on first use, kept for the
        run -- S1's counterpart of the worker pool, whose one worker per key it mirrors. Called
        under that key's lock, so two batches of one key never build two."""
        key = subproc.WorkerKey(granted.card.identity.id, granted.config_digest)
        built = self._drivers.get(key)
        if built is None:
            from omniweave_core.host.activate import construct  # noqa: PLC0415

            built = construct(granted.card, granted.effective_config)
            self._drivers[key] = built
            self._tally.inproc += 1
        return built

    # -- the worker ----------------------------------------------------------------------------

    def _worker(self, granted: _Granted) -> subproc.Worker:
        card = granted.card
        key = subproc.WorkerKey(card.identity.id, granted.config_digest)
        cost = card.cost_model.cost_class if card.cost_model is not None else "free"

        def build() -> subproc.Worker:
            self._tmp.mkdir(parents=True, exist_ok=True)
            self._launches += 1
            address = _address(self._ctx.run_id, self._launches)
            isolation, _shortfalls = subproc.grant_isolation(
                mode=Isolation.SUBPROC,
                batch_max_units=card.isolation.batch_max_units,
                platform=sys.platform,
                address_space_capped=sys.platform == "win32" and card.isolation.memory_mb > 0,
                net_blocked_requested=not card.hardware.needs_network,
                cpu_cap_requested=False,
                fd_cap_requested=False,
            )
            hello = {
                "port": f"{card.identity.port.value}/{card.identity.port_major}",
                "card_schema": card.card_schema,
                "card_sha256": card.card_sha256,
                "driver_id": card.identity.id,
                "effective_config": dict(granted.effective_config),
                "roots": {"source_ro": str(self._ctx.roots.source), "tmp": str(self._tmp)},
                "blob_base": str(self._cas.root),
                "isolation_granted": dict(isolation.as_header()),
                "traceparent": "",
                "max_output_bytes": MAX_OUTPUT_BYTES,
                "egress_mode": DEFAULT_EGRESS_MODE,
            }
            expect = {
                "driver_id": card.identity.id,
                "version": card.identity.version,
                "schema_version": card.identity.schema_version,
                "port": hello["port"],
            }
            worker, _ack = subproc.launch(
                key,
                subproc.SpawnRequest(
                    argv=subproc.worker_argv(self._executable, address),
                    cwd=str(self._tmp),
                    env=worker_env(),
                    address=address,
                ),
                hello=hello,
                expect=expect,
                deadlines=_HELLO_DEADLINES,
                settings=self._settings,
                now_ms=self._now_ms,
                memory_mb=card.isolation.memory_mb,
                spawn=self._spawn,
            )
            self._tally.workers += 1
            return worker

        if self._pool.get(key) is None and self._pool.full(str(cost)):
            self._make_room(str(cost), key)
        return self._pool.acquire(key, cost_class=str(cost), build=build)

    def _make_room(self, cost_class: str, key: subproc.WorkerKey) -> None:
        """Retire the least recently used worker of a full class that nobody is calling. **D653.**

        `[drivers] max_workers` bounds how many worker processes a class holds, and a worker
        outlives its batches by `worker_idle_ttl_s` (300 s). So under `max_workers.free = 1` the
        first driver's idle worker held the only place, the pool refused the second driver's, and
        every batch of it crashed: a folder of documents and PDFs ingested its documents, left its
        PDFs `claimed`, and ended `partial` with exit 0. Replacing an idle worker keeps the cap,
        which counts processes and not drivers.

        A worker is in use exactly while its key's lock is held (`_lock` covers the acquire and
        the whole `INVOKE`), so a lock taken without blocking proves nobody is calling it. When
        every worker of the class is busy, nothing is retired, and the pool's refusal stands.
        """
        for other in self._pool.idle_order(cost_class):
            if other == key:
                continue
            lock = self._lock(other)
            if not lock.acquire(blocking=False):
                continue
            try:
                if self._pool.retire(other):
                    return
            finally:
                lock.release()


class _Source:
    """`pipeline.WorkerSource` for one batch: the pool's worker, the `INVOKE`, the card's limits."""

    __slots__ = ("_granted", "_operator", "_staged")

    def __init__(self, operator: ParseOperator, granted: _Granted, staged: list[_Staged]) -> None:
        self._operator = operator
        self._granted = granted
        self._staged = staged

    def worker(self, call: Call) -> subproc.Worker:
        del call
        return self._operator._worker(self._granted)

    def invocation(self, call: Call) -> subproc.Invocation:
        """The `INVOKE`, after each mapped unit's password is in its scratch directory (D15.4).

        Called once per attempt, so a retry's worker finds the file again even after the first
        worker removed its scratch."""
        for index, unit in enumerate(call.units):
            secret = self._operator.secret_for(unit.uri)
            if secret is not None:
                directory = self._operator._tmp / call.batch.invoke_id / str(index)
                keystore.write_password(directory, secret)
        return subproc.Invocation(
            invoke_id=call.batch.invoke_id,
            units=call.units,
            deadline_ms=call.deadline_ms,
            budget_micros=call.budget_micros,
            blob_refs=tuple(one.blob_ref for one in self._staged),
        )

    def deadlines(self, call: Call) -> subproc.Deadlines:
        spec = self._granted.card.isolation
        return subproc.Deadlines(
            progress_ms=spec.progress_ms,
            wall_ms_hard=spec.wall_ms_hard,
            deadline_ms=call.deadline_ms,
        )

    def memory_mb(self, call: Call) -> int:
        del call
        return self._granted.card.isolation.memory_mb


class _Guarded:
    """`pipeline.GuardSource` for one batch: the guard, the driver's `parse`, the CAS aliased to the
    staged blobs, and the run's scratch root -- `_Source`'s four answers, for the seam with no
    process."""

    __slots__ = ("_granted", "_operator", "_staged")

    def __init__(self, operator: ParseOperator, granted: _Granted, staged: list[_Staged]) -> None:
        self._operator = operator
        self._granted = granted
        self._staged = staged

    def guard(self, call: Call) -> DriverGuard:
        return self._operator._guard(self._granted, call)

    def work(self, call: Call, index: int) -> Callable[[DriverIO], DriverResult]:
        from omniweave_core.host.worker import parse_one  # noqa: PLC0415

        parse = getattr(self._operator._driver(self._granted), "parse", None)
        unit = call.units[index]
        secret = self._operator.secret_for(unit.uri)

        def work(io_obj: DriverIO) -> DriverResult:
            if secret is not None:
                keystore.write_password(Path(io_obj.tmpdir), secret)
            return parse_one(parse, unit, io_obj)

        return work

    def blobs(self, call: Call) -> WorkerBlobs:
        """The CAS with each unit's `content_sha256` aliased to its staged blob -- `WorkerBlobs`,
        whose docstring is why: a driver opens its input by the NORMALISED digest."""
        del call
        from omniweave_core.host.worker import WorkerBlobs  # noqa: PLC0415

        return WorkerBlobs(
            self._operator._cas, {one.unit.content_sha256: one.blob_ref for one in self._staged}
        )

    def tmp(self, call: Call) -> Path:
        del call
        return self._operator._tmp

    def max_output_bytes(self, call: Call) -> int:
        del call
        return MAX_OUTPUT_BYTES


# =============================================================================================
# Small pieces
# =============================================================================================


def _address(run_id: str, ordinal: int) -> str:
    """One worker's base address: a named pipe on Windows, a socket path elsewhere."""
    name = f"ow-{os.getpid()}-{run_id[-10:].lower()}-{ordinal}"
    if sys.platform == "win32":
        return f"\\\\.\\pipe\\{name}"
    return str(Path("/tmp") / f"{name}.sock")  # noqa: S108 -- pragma: POSIX arm, untested here


_WORKER_ENV_KEYS: Final[tuple[str, ...]] = ("SYSTEMROOT", "PATH", "TEMP", "TMP")
"""The environment a worker inherits, BY NAME. `SpawnRequest.env` is complete and not an overlay:
*"an inherited environment carries the host's `PYTHONPATH`, its proxy variables and its tokens into
a third party's process"*. `SYSTEMROOT` is what CPython needs to start on Windows at all; `PATH` is
where a card's `needs_binaries` are found; `TEMP`/`TMP` keep a library's own tempfile use off the
Windows directory. Nothing else crosses."""


def worker_env() -> dict[str, str]:
    """`_WORKER_ENV_KEYS` from this process's environment: a child's complete environment."""
    return {key: os.environ[key] for key in _WORKER_ENV_KEYS if key in os.environ}


def _evidence_of(derived: object) -> Mapping[str, Any]:
    try:
        parsed = json.loads(str(derived or "{}"))
    except ValueError:
        return {}
    evidence = parsed.get("format_evidence") if isinstance(parsed, dict) else None
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except ValueError:
            return {}
    return evidence if isinstance(evidence, dict) else {}


def _declared(card: DriverCard) -> Capabilities:
    """The card's `[capability.parse]`, as the fifteen `Capabilities` fields (03 section 2.9)."""
    caps = card.parse
    names = Capabilities.__dataclass_fields__
    if caps is None:
        raise RouteError(
            f"{card.identity.id} has no [capability.parse]; a parse row needs one",
            fix=f"ow drivers verify {card.identity.id}",
        )
    return Capabilities(**{name: getattr(caps, name) for name in names if hasattr(caps, name)})


def _peak_of(reply: Reply, slot: int) -> int:
    """The worker's sampled peak for one unit, from its `DriverResult` (04:1765). 0 when absent.

    `subproc.Worker` writes the host's sample over the driver's own figure, so this is the number
    `work.peak_rss_bytes` keeps (`COMPLETE_SQL`'s `MAX`). An in-process driver's result carries the
    driver's own report, which for every first-party driver is 0 (D629).
    """
    results = reply.report.results if reply.report is not None else ()
    found = results[slot] if slot < len(results) else None
    return 0 if found is None else max(0, int(found.metrics.peak_rss_bytes))


def _source_of(verdict: object) -> Any:
    from omniweave_core.work import Source  # noqa: PLC0415

    return Source.HOST if getattr(verdict, "detected_by", "host") == "host" else Source.DRIVER
