"""The free Segment-grained Passes: every segmented document is derived in the same drain. **D668.**

W8.2's third slice. D666 wrote `derive.anchor.defterm`, D667 the store's two ends of its wire. This
is the schedule: 08:2035's `derive` stage after `derive.segment`, one row per document per Pass,
run by the run's own worker pool.

**The row is enqueued by the segmentation it follows.** `SegmentOperator` writes a document's
Segments and, in the same store-thread `Unit`, this module's rows for it -- so a document is never
segmented without its derive rows, nor queued for derivation over Segments that did not commit. The
row is `pending` while the drain is still polling, so the drain that segmented the document derives
it. `ON CONFLICT DO NOTHING` on `work_identity`, as `derive.segment`'s.

**One row per document per Pass, one unit per row** (D668). 06:810 runs a document-granularity free
Pass *"once, INVOKEd with the document's Segments as units"*, and `pipeline.Call` pairs units with
work rows one-to-one, so the unit is the document and its view is every live Segment in Segment
form, one after another (`omniweave_graph.view.read_segment_views`). The answer is split back per
Segment on its `seg` frames, and each Segment gets its own `derive_run` -- the grain 06:810 promises
`derive_cover` -- in one write `Unit` with `derive_pass` upserted from the card that ran.

**The row's operator is the Pass** (`derive.anchor.defterm`), and so is `origin_operator` on every
row it writes; the `producer` row keeps the family (`derive.anchor`), 08:1341's memo grain. D668
spelled the row by family, as 08:2039 prints it, and recorded that two Passes of one family on one
document would then share `work_identity` -- the second enqueue a silent no-op -- and share
`origin_operator`, so 06 section 10.2's owner-scoped replacement could not tell their rows apart.
`derive.anchor.native` is the second `derive.anchor` Pass, so D670 rules it: the Pass is the unit of
work and of ownership, and the family stays the unit of the memo.

**It has a driver and no decision** (D665): the candidate is `resolve()`'s, pinned to the Pass, and
a Pass the policy disables, a lockfile omits or a probe refuses enqueues nothing, with the report
saying which.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.cache import cache_key
from omniweave_core.drivers.resolve import Isolation, Requirement, resolve
from omniweave_core.errors import GraphError, RouteError
from omniweave_core.model.enums import Method
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store import sqlite as ow
from omniweave_core.store.graph import PassIdentity
from omniweave_core.store.items import (
    ITEM_LANES,
    ItemView,
    decode_items,
    document_body,
    document_views,
    drive_items,
    register_pass,
)
from omniweave_ports.types import FailureClass, UnitRef

from omniweave.plan import operator_of
from omniweave.route.spend import Spend
from omniweave.run import pipeline
from omniweave.run.converge import replace_prior_runs
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.parse import DeriveCount

if TYPE_CHECKING:
    from omniweave_core.drivers.catalog import Catalog
    from omniweave_core.drivers.resolve import Candidate, Policy
    from omniweave_core.host import subproc
    from omniweave_core.operator import RunContext, SpendVector
    from omniweave_core.store.queue import WorkRow
    from omniweave_ports.types import ArtifactRef

    from omniweave.run.dispatch import Batch
    from omniweave.run.operators.parse import ParseOperator, ParseTally

__all__ = [
    "DERIVE_PRIORITY",
    "FREE_PASSES",
    "DeriveOperator",
    "DerivePlan",
    "is_derive",
]

FREE_PASSES: Final[dict[str, Method]] = {
    "derive.anchor.native": Method.NATIVE_XML,
    "derive.xref.native": Method.NATIVE_XML,
    "derive.entity.table": Method.NATIVE_XML,
    "derive.anchor.defterm": Method.HEURISTIC,
    "derive.xref.pattern": Method.HEURISTIC,
}
"""The shipped Segment-grained free Passes and each one's `Method`, in `(cost_rank, phase)` order.

06 section 3.1's roster grows into this map one Pass at a time. **The method is here and not on the
card** (D668): `derive_run.method` is *"ONE METHOD PER PASS"* (0002:179) and the clamp the sink
applies reads it, but `[capability.derive]` and `[derive]` declare none, so the roster's `method`
column is the one source. A third-party Pass needs a card key before it can be scheduled here."""
DERIVE_PRIORITY: Final = 100
"""08:2035's `priority` for every derive row; a Pass's row exists only after its document's
Segments do, so it never competes with the `derive.segment` row it follows."""

ENQUEUE_SQL: Final = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, status, priority,
                 driver, decision_id, dispatch_key)
VALUES(:unit_uri, '', :operator, :op_version, :cache_key, 'free', 'pending', :priority,
       :driver, NULL, :dispatch_key)
ON CONFLICT(unit_uri, unit_part, operator, op_version) DO NOTHING
"""

_UNIT_SQL: Final = "SELECT content_sha256 FROM unit WHERE unit_uri = ?"
_DOC_SQL: Final = "SELECT doc_ord, gen FROM doc WHERE doc_key = ?"
_PRODUCER_INSERT_SQL: Final = """
INSERT OR IGNORE INTO producer(operator, op_version, code_fingerprint, options_digest)
VALUES(:operator, :op_version, :code_fingerprint, :options_digest)
"""
_PRODUCER_ID_SQL: Final = """
SELECT producer_id FROM producer
 WHERE operator = :operator AND op_version = :op_version AND code_fingerprint = :code_fingerprint
   AND options_digest = :options_digest AND model_id IS NULL AND model_rev IS NULL
   AND runtime IS NULL AND runtime_version IS NULL AND prompt_fp IS NULL
"""


def is_derive(operator: str) -> bool:
    """A Segment-grained free Pass's row: a `derive.*` family other than the segmenter's."""
    return operator.startswith("derive.") and operator != "derive.segment"


@dataclass(frozen=True, slots=True)
class DerivePlan:
    """The run's resolved free Passes, and the rows each segmented document earns."""

    passes: tuple[Candidate, ...]
    ctx: RunContext

    @classmethod
    def of(cls, catalog: Catalog, policy: Policy, ctx: RunContext) -> tuple[DerivePlan | None, str]:
        """Each Pass's pinned candidate; `None` and why when none resolves."""
        passes: list[Candidate] = []
        why: list[str] = []
        for pass_id in FREE_PASSES:
            resolution = resolve(Requirement(port="derive/1", pinned=pass_id), catalog, policy)
            found = [c for c in resolution.candidates if c.card.identity.id == pass_id]
            if found:  # `pinned` filters nothing (resolve.py:506): the Pass is picked by id
                passes.append(found[0])
                continue
            refused = [
                f"{r.code}: {r.detail}" for r in resolution.rejected if r.driver_id == pass_id
            ]
            why.append(f"{pass_id}: {refused[0] if refused else 'not installed'}")
        return (cls(tuple(passes), ctx) if passes else None), "; ".join(why)

    def enqueue(self, connection: Any, unit: UnitRef) -> int:
        """Every Pass's row for a document whose Segments were just written. Returns how many."""
        added = 0
        for candidate in self.passes:
            card = candidate.card
            operator = operator_of(card.identity.id)
            added += connection.execute(
                ENQUEUE_SQL,
                {
                    "unit_uri": unit.uri,
                    "operator": card.identity.id,
                    "op_version": card.identity.schema_version,
                    "cache_key": cache_key(
                        unit,
                        _producer(operator, card, candidate.config_digest),
                        card,
                        self.ctx,
                        salt="",
                    ),
                    "priority": DERIVE_PRIORITY,
                    "driver": card.identity.id,
                    "dispatch_key": dispatch_key(
                        card.identity.id, candidate.config_digest, str(candidate.isolation_granted)
                    ),
                },
            ).rowcount
        return added


def _producer(operator: str, card: Any, config_digest: str) -> Producer:
    return Producer(
        operator=operator,
        op_version=card.identity.schema_version,
        code_fingerprint="",
        options_digest=bytes.fromhex(config_digest),
    )


class DeriveOperator:
    """The `Dispatcher` for a free Pass's rows: one call per claimed batch, one result a row."""

    __slots__ = ("_parse", "_tally", "_thread")

    def __init__(self, parse: ParseOperator, thread: ow.StoreThread, tally: ParseTally) -> None:
        self._parse = parse
        self._thread = thread
        self._tally = tally

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]:
        driver = batch.driver
        if driver is None or driver not in FREE_PASSES:
            raise RouteError(
                f"invoke {batch.invoke_id} names {driver!r}, which is no shipped free Pass",
                fix="ow ingest again: the row is re-enqueued when its document is segmented again",
            )
        granted = self._parse._granted(driver, batch.dispatch_key or "")
        if granted.isolation is not Isolation.SUBPROC:
            raise RouteError(
                f"{driver} was granted {granted.isolation}; its card requires subproc",
                fix="remove it from [drivers] inproc",
            )
        card = granted.card
        producer = _producer(operator_of(driver), card, granted.config_digest)
        results: list[StepResult | None] = [None] * batch.size
        staged: list[tuple[int, tuple[ItemView, ...], UnitRef, str]] = []
        for index, row in enumerate(batch.rows):
            views = self._views(row.unit_uri)
            if not views:
                results[index] = self._failed(
                    driver, row, _unit_of(row), producer, failure=FailureClass.EMPTY_RESULT,
                    message="the unit's document has no live Segment",
                )  # fmt: skip
                continue
            from omniweave_core.blobs import format_ref  # noqa: PLC0415

            body = document_body(views)
            digest = self._parse._cas.put(io.BytesIO(body))
            unit = UnitRef(
                uri=row.unit_uri, part="", content_sha256=digest.hex(), byte_len=len(body)
            )
            staged.append((index, views, unit, format_ref(digest)))
        if staged:
            reply = self._call(batch, staged, granted, driver)
            identity = PassIdentity(
                pass_id=driver,
                producer_id=self._producer_id(producer),
                method=FREE_PASSES[driver],
                origin_operator=driver,
                origin_driver=driver,
                driver_schema_v=card.identity.schema_version,
                cost_class="free",
            )
            for slot, (index, views, unit, _ref) in enumerate(staged):
                results[index] = self._settle(
                    batch.rows[index], unit, views, reply=reply, slot=slot, producer=producer,
                    identity=identity, card=card,
                )  # fmt: skip
        return [cast("StepResult", one) for one in results]

    def _views(self, unit_uri: str) -> tuple[ItemView, ...]:
        def read(connection: Any) -> tuple[ItemView, ...]:
            unit = connection.execute(_UNIT_SQL, (unit_uri,)).fetchone()
            if unit is None or not unit[0]:
                return ()
            found = connection.execute(_DOC_SQL, (bytes.fromhex(str(unit[0]))[:16],)).fetchone()
            if found is None:
                return ()
            return document_views(connection, int(found[0]), int(found[1]))

        return cast(
            "tuple[ItemView, ...]",
            self._thread.run(
                ow.Unit(name="derive.view", run=read, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
            ),
        )

    def _producer_id(self, producer: Producer) -> int:
        params = {
            "operator": producer.operator,
            "op_version": producer.op_version,
            "code_fingerprint": producer.code_fingerprint,
            "options_digest": producer.options_digest,
        }

        def run(connection: Any) -> Any:
            connection.execute(_PRODUCER_INSERT_SQL, params)
            return connection.execute(_PRODUCER_ID_SQL, params).fetchone()

        found = self._thread.run(
            ow.Unit(name="derive.producer", run=run, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
        )
        return int(cast("tuple[int]", found)[0])

    def _call(
        self,
        batch: Batch,
        staged: Sequence[tuple[int, tuple[ItemView, ...], UnitRef, str]],
        granted: Any,
        operator: str,
    ) -> pipeline.Reply:
        from omniweave_core.host import subproc  # noqa: PLC0415

        call = pipeline.Call(
            batch=type(batch)(
                invoke_id=batch.invoke_id, rows=tuple(batch.rows[i] for i, *_ in staged)
            ),
            units=tuple(unit for _i, _v, unit, _r in staged),
            operator=operator,
            deadline_ms=granted.card.isolation.wall_ms_hard,
        )
        lanes = sorted(granted.card.derive.items) if granted.card.derive is not None else []
        host = pipeline.subproc_host(
            _Source(self._parse, granted, tuple(ref for *_x, ref in staged), _lane(lanes))
        )
        handler = pipeline.build(host, emit=self._tally.emit, isolation=str(granted.isolation))
        key = subproc.WorkerKey(granted.card.identity.id, granted.config_digest)
        with self._parse._lock(key):
            return handler(call)

    def _settle(
        self,
        row: WorkRow,
        unit: UnitRef,
        views: tuple[ItemView, ...],
        *,
        reply: pipeline.Reply,
        slot: int,
        producer: Producer,
        identity: PassIdentity,
        card: Any,
    ) -> StepResult:
        driver = identity.pass_id
        outcome = reply.outcomes[slot]
        if outcome not in (Outcome.OK, Outcome.OK_PARTIAL):
            verdict = None if reply.report is None else reply.report.failures[slot]
            failure = FailureClass.DRIVER_CRASHED if verdict is None else verdict.failure_class
            return self._failed(
                driver, row, unit, producer, failure=failure,
                message="" if verdict is None else verdict.message,
            )  # fmt: skip
        produced = reply.produced[slot] if reply.produced else ()
        items = [ref for ref in produced if ref.kind == "graph_items"]
        if len(items) != 1:
            return self._failed(
                driver, row, unit, producer, failure=FailureClass.DRIVER_BUG,
                message=f"{driver} produced {len(items)} graph_items refs; one is an answer",
            )  # fmt: skip
        spend = cast("SpendVector", reply.spend[slot] if reply.spend else Spend())
        try:
            units = decode_items(self._body(items[0]), views)

            def write(connection: Any) -> list[Any]:
                register_pass(connection, card)
                written = [drive_items(connection, u, identity, spend) for u in units]
                #  D681: a whole answer replaces this Pass's earlier runs on each Segment.
                for report in written:
                    if report.status in {"ok", "empty"}:
                        replace_prior_runs(connection, report.run_id)
                return written

            reports = cast(
                "list[Any]",
                self._thread.run(
                    ow.Unit(
                        name="derive.write", run=write, cost_class="free", wait_ms=ow.BATCH_WAIT_MS
                    )
                ),
            )
        except GraphError as refused:
            return self._failed(
                driver, row, unit, producer, failure=FailureClass.DRIVER_BUG, message=str(refused)
            )
        count = self._tally.derived.setdefault(driver, DeriveCount())
        count.documents += 1
        count.runs += len(reports)
        count.items += sum(r.emitted for r in reports)
        count.quarantined += sum(r.quarantined for r in reports)
        return StepResult(
            outcome=Outcome.OK,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            produced=tuple(produced),
            metrics=StepMetrics(rows_written=sum(r.emitted for r in reports)),
        )

    def _body(self, ref: ArtifactRef) -> bytes:
        if ref.inline is not None:
            return ref.inline
        from omniweave_core.blobs import parse_ref  # noqa: PLC0415

        with self._parse._cas.open(parse_ref(str(ref.blob))) as handle:
            return handle.read()

    def _failed(
        self,
        driver: str,
        row: WorkRow,
        unit: UnitRef,
        producer: Producer,
        *,
        failure: FailureClass,
        message: str,
    ) -> StepResult:
        self._tally.derive_failed[f"{driver} {failure}"] += 1
        return StepResult(
            outcome=Outcome.FAILED_PERMANENT,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            failure_class=failure,
            failure_message=message[:2_048],
        )


def _lane(items: Sequence[str]) -> str:
    """`DeriveScope.lane`: the first lane the Pass's items serve, `anchor` before `entity`."""
    lanes = sorted({ITEM_LANES[i] for i in items if i in ITEM_LANES})
    return lanes[0] if lanes else ""


class _Source:
    """`pipeline.WorkerSource` for one derive batch: the run's worker, an `INVOKE` with a lane."""

    __slots__ = ("_blob_refs", "_granted", "_lane", "_parse")

    def __init__(
        self, parse: ParseOperator, granted: Any, blob_refs: tuple[str, ...], lane: str
    ) -> None:
        self._parse = parse
        self._granted = granted
        self._blob_refs = blob_refs
        self._lane = lane

    def worker(self, call: pipeline.Call) -> subproc.Worker:
        del call
        return self._parse._worker(self._granted)

    def invocation(self, call: pipeline.Call) -> subproc.Invocation:
        from omniweave_core.host import subproc  # noqa: PLC0415

        return subproc.Invocation(
            invoke_id=call.batch.invoke_id,
            units=call.units,
            deadline_ms=call.deadline_ms,
            budget_micros=call.budget_micros,
            blob_refs=self._blob_refs,
            lane=self._lane or None,
        )

    def deadlines(self, call: pipeline.Call) -> subproc.Deadlines:
        from omniweave_core.host import subproc  # noqa: PLC0415

        spec = self._granted.card.isolation
        return subproc.Deadlines(
            progress_ms=spec.progress_ms,
            wall_ms_hard=spec.wall_ms_hard,
            deadline_ms=call.deadline_ms,
        )

    def memory_mb(self, call: pipeline.Call) -> int:
        del call
        return int(self._granted.card.isolation.memory_mb)


def _unit_of(row: WorkRow) -> UnitRef:
    return UnitRef(uri=row.unit_uri, part=row.unit_part, content_sha256="", byte_len=0)
