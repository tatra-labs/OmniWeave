"""`derive.segment`: every document a run parses is segmented in the same drain. **D665.**

W8.1's fourth slice. D662 wrote the segmenter, D663 the store's two ends of its wire, D664 its card
and the worker that serves `derive/1`. This is the schedule: 08:2035's `derive` stage, one
`derive.segment` row per parsed document, run by the run's own worker pool.

**The row is enqueued by the parse it follows.** `ParseLedger`'s contribution for a row that settles
`ok` carries `SegmentPlan.statement()`, so the `derive.segment` row commits in the transaction that
settles the unit -- 02:452-461's "no window" rule for a routed row, kept for this one. It is
`pending` while the drain is still polling, so the drain that parsed the document segments it.
`ON CONFLICT DO NOTHING` on `work_identity` because a resumed run settles nothing twice, and a
document read again had its terminal rows cleared by `discover.REOPEN_WORK_SQL`, this one with them.

**It has a driver and no decision** (D665). 06 section 1.7's `PassIdentity.decision_id` is "NULL
for a free Pass", so `0004_runtime.sql` admits a free `derive.*` row with `driver` and
`dispatch_key` and a NULL `decision_id`. The candidate is still `resolve()`'s: a segmenter the
policy disables, a lockfile omits or a probe refuses enqueues nothing, and the report says which.

**The Operator borrows the parse Operator's pool.** 02:677 makes the pool run-scoped and 02:482 one
worker per `(driver_id, config_digest)`, so a second pool would be a second set of workers under the
same keys. `SegmentOperator` holds the run's `ParseOperator` and uses its `_granted`, `_worker` and
per-key lock; the call goes through `pipeline.subproc_host`, the one caller G8 allows.

**What a row does:** read the unit's head document, build the view (`store.segments.build_view`),
put it in the CAS, `INVOKE` with `lane = "segment"`, then decode and write in one store-thread
transaction. The view is in the CAS because the worker reads only blobs, and is content-addressed,
so an unchanged generation's view is stored once.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.cache import cache_key
from omniweave_core.drivers.resolve import Isolation, Requirement, resolve
from omniweave_core.errors import GraphError, RouteError
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store import sqlite as ow
from omniweave_core.store.queue import Statement
from omniweave_core.store.segments import (
    SegmenterIdentity,
    SegmentView,
    build_view,
    decode_segments,
    write_segments,
)
from omniweave_ports.types import FailureClass, UnitRef

from omniweave.run import pipeline
from omniweave.run.dispatch import dispatch_key

if TYPE_CHECKING:
    from omniweave_core.drivers.catalog import Catalog
    from omniweave_core.drivers.resolve import Candidate, Policy
    from omniweave_core.host import subproc
    from omniweave_core.operator import RunContext
    from omniweave_core.store.queue import WorkRow
    from omniweave_ports.types import ArtifactRef

    from omniweave.run.dispatch import Batch
    from omniweave.run.operators.parse import ParseOperator, ParseTally

__all__ = [
    "ENQUEUE_SQL",
    "SEGMENTER_ID",
    "SEGMENT_LANE",
    "SEGMENT_OPERATOR",
    "SEGMENT_PRIORITY",
    "SegmentOperator",
    "SegmentPlan",
    "is_segment",
]

SEGMENT_OPERATOR: Final = "derive.segment"
"""`work.operator`: the driver id without its implementation segment, as `plan.operator_of`."""
SEGMENTER_ID: Final = "derive.segment.spine"
SEGMENT_LANE: Final = "segment"
"""`DeriveScope.lane`. The segmenter is "not a lane" (06:825) and ignores it; the wire still says
which pass a call is for."""
SEGMENT_PRIORITY: Final = 100
"""08:2035's `priority`, below a parse row's 200: a drain parses what it can before it segments."""

ENQUEUE_SQL: Final = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, status, priority,
                 driver, decision_id, dispatch_key)
VALUES(:unit_uri, '', :operator, :op_version, :cache_key, 'free', 'pending', :priority,
       :driver, NULL, :dispatch_key)
ON CONFLICT(unit_uri, unit_part, operator, op_version) DO NOTHING
"""

_UNIT_SQL: Final = "SELECT content_sha256 FROM unit WHERE unit_uri = ?"
_DOC_SQL: Final = "SELECT doc_ord, gen FROM doc WHERE doc_key = ?"
"""The unit's document by `doc_key`, the parse Operator's own derivation of it: the first sixteen
bytes of the unit's `content_sha256`. A file that changed is a new `doc_key` and a new document,
and `discover.retire_replaced` retires the old one's Segments with it."""


def is_segment(operator: str) -> bool:
    return operator == SEGMENT_OPERATOR


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    """The run's resolved segmenter, and the `derive.segment` row each parsed unit earns."""

    candidate: Candidate
    ctx: RunContext

    @classmethod
    def of(
        cls, catalog: Catalog, policy: Policy, ctx: RunContext
    ) -> tuple[SegmentPlan | None, str]:
        """`resolve()`'s candidate for the pinned segmenter, or `None` and why it has none."""
        resolution = resolve(Requirement(port="derive/1", pinned=SEGMENTER_ID), catalog, policy)
        if resolution.candidates:  # pinned: the segmenter, or nothing
            return cls(resolution.candidates[0], ctx), ""
        why = [f"{r.code}: {r.detail}" for r in resolution.rejected if r.driver_id == SEGMENTER_ID]
        return None, (why[0] if why else f"{SEGMENTER_ID} is not installed")

    @property
    def producer(self) -> Producer:
        return Producer(
            operator=SEGMENT_OPERATOR,
            op_version=self.candidate.card.identity.schema_version,
            code_fingerprint="",
            options_digest=bytes.fromhex(self.candidate.config_digest),
        )

    def statement(self, unit: UnitRef) -> Statement:
        """The `derive.segment` row for a unit whose parse settled `ok`."""
        card = self.candidate.card
        return Statement(
            participant="derived_rows",
            name="segment_enqueued",
            sql=ENQUEUE_SQL,
            params={
                "unit_uri": unit.uri,
                "operator": SEGMENT_OPERATOR,
                "op_version": card.identity.schema_version,
                "cache_key": cache_key(unit, self.producer, card, self.ctx, salt=""),
                "priority": SEGMENT_PRIORITY,
                "driver": card.identity.id,
                "dispatch_key": dispatch_key(
                    card.identity.id,
                    self.candidate.config_digest,
                    str(self.candidate.isolation_granted),
                ),
            },
        )


class SegmentOperator:
    """The `Dispatcher` for `derive.segment` rows: one call per claimed batch, one result a row."""

    __slots__ = ("_parse", "_tally", "_thread")

    def __init__(self, parse: ParseOperator, thread: ow.StoreThread, tally: ParseTally) -> None:
        self._parse = parse
        self._thread = thread
        self._tally = tally

    def __call__(self, batch: Batch, /) -> Sequence[StepResult]:
        driver = batch.driver
        if driver is None:
            raise RouteError(
                f"invoke {batch.invoke_id} has no driver; a derive.segment row names its segmenter",
                fix="ow ingest again: the row is re-enqueued when its unit is parsed again",
            )
        granted = self._parse._granted(driver, batch.dispatch_key or "")
        if granted.isolation is not Isolation.SUBPROC:
            raise RouteError(
                f"{driver} was granted {granted.isolation}; the segmenter's card requires subproc",
                fix="remove it from [drivers] inproc",
            )
        card = granted.card
        producer = Producer(
            operator=SEGMENT_OPERATOR,
            op_version=card.identity.schema_version,
            code_fingerprint="",
            options_digest=bytes.fromhex(granted.config_digest),
        )
        identity = SegmenterIdentity(
            card.identity.id,
            card.identity.schema_version,
            cast("dict[str, int | float | str | bool]", dict(granted.effective_config)),
        )
        results: list[StepResult | None] = [None] * batch.size
        staged: list[tuple[int, SegmentView, UnitRef, str]] = []
        for index, row in enumerate(batch.rows):
            view = self._view(row.unit_uri)
            if view is None:
                results[index] = self._failed(
                    row, _unit_of(row), producer, FailureClass.EMPTY_RESULT,
                    "the unit has no stored document to segment",
                )  # fmt: skip
                continue
            from omniweave_core.blobs import format_ref  # noqa: PLC0415

            digest = self._parse._cas.put(io.BytesIO(view.body))
            unit = UnitRef(
                uri=row.unit_uri, part="", content_sha256=digest.hex(), byte_len=len(view.body)
            )
            staged.append((index, view, unit, format_ref(digest)))
        if staged:
            reply = self._call(batch, staged, granted)
            for slot, (index, view, unit, _ref) in enumerate(staged):
                results[index] = self._settle(
                    batch.rows[index],
                    unit,
                    view,
                    reply=reply,
                    slot=slot,
                    producer=producer,
                    identity=identity,
                )
        return [cast("StepResult", one) for one in results]

    def _view(self, unit_uri: str) -> SegmentView | None:
        def read(connection: Any) -> SegmentView | None:
            unit = connection.execute(_UNIT_SQL, (unit_uri,)).fetchone()
            if unit is None or not unit[0]:
                return None
            found = connection.execute(_DOC_SQL, (bytes.fromhex(str(unit[0]))[:16],)).fetchone()
            if found is None:
                return None
            return build_view(connection, int(found[0]), int(found[1]))

        return cast(
            "SegmentView | None",
            self._thread.run(
                ow.Unit(name="segment.view", run=read, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
            ),
        )

    def _call(
        self,
        batch: Batch,
        staged: Sequence[tuple[int, SegmentView, UnitRef, str]],
        granted: Any,
    ) -> pipeline.Reply:
        from omniweave_core.host import subproc  # noqa: PLC0415

        call = pipeline.Call(
            batch=type(batch)(
                invoke_id=batch.invoke_id, rows=tuple(batch.rows[i] for i, *_ in staged)
            ),
            units=tuple(unit for _i, _v, unit, _r in staged),
            operator=SEGMENT_OPERATOR,
            deadline_ms=granted.card.isolation.wall_ms_hard,
        )
        host = pipeline.subproc_host(
            _Source(self._parse, granted, tuple(ref for *_x, ref in staged))
        )
        handler = pipeline.build(host, emit=self._tally.emit, isolation=str(granted.isolation))
        key = subproc.WorkerKey(granted.card.identity.id, granted.config_digest)
        with self._parse._lock(key):
            return handler(call)

    def _settle(
        self,
        row: WorkRow,
        unit: UnitRef,
        view: SegmentView,
        *,
        reply: pipeline.Reply,
        slot: int,
        producer: Producer,
        identity: SegmenterIdentity,
    ) -> StepResult:
        outcome = reply.outcomes[slot]
        if outcome not in (Outcome.OK, Outcome.OK_PARTIAL):
            verdict = None if reply.report is None else reply.report.failures[slot]
            failure = FailureClass.DRIVER_CRASHED if verdict is None else verdict.failure_class
            return self._failed(
                row, unit, producer, failure, "" if verdict is None else verdict.message
            )
        produced = reply.produced[slot] if reply.produced else ()
        items = [ref for ref in produced if ref.kind == "graph_items"]
        if len(items) != 1:
            return self._failed(
                row, unit, producer, FailureClass.DRIVER_BUG,
                f"the segmenter produced {len(items)} graph_items refs; exactly one is an answer",
            )  # fmt: skip
        try:
            decoded = decode_segments(self._body(items[0]), view)
            report = self._thread.run(
                ow.Unit(
                    name="segment.write",
                    run=lambda c: write_segments(
                        c, view, identity, decoded, origin_operator=SEGMENT_OPERATOR
                    ),
                    cost_class="free",
                    wait_ms=ow.BATCH_WAIT_MS,
                )
            )
        except GraphError as refused:
            return self._failed(row, unit, producer, FailureClass.DRIVER_BUG, str(refused))
        self._tally.segmented += 1
        self._tally.segments_created += report.created  # type: ignore[attr-defined]
        self._tally.segments_kept += report.kept  # type: ignore[attr-defined]
        self._tally.segments_retired += report.retired  # type: ignore[attr-defined]
        return StepResult(
            outcome=Outcome.OK,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            produced=tuple(produced),
            metrics=StepMetrics(rows_written=len(decoded.segments)),
        )

    def _body(self, ref: ArtifactRef) -> bytes:
        if ref.inline is not None:
            return ref.inline
        from omniweave_core.blobs import parse_ref  # noqa: PLC0415

        with self._parse._cas.open(parse_ref(str(ref.blob))) as handle:
            return handle.read()

    def _failed(
        self, row: WorkRow, unit: UnitRef, producer: Producer, failure: FailureClass, message: str
    ) -> StepResult:
        self._tally.segment_failed[str(failure)] += 1
        return StepResult(
            outcome=Outcome.FAILED_PERMANENT,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            failure_class=failure,
            failure_message=message[:2_048],
        )


class _Source:
    """`pipeline.WorkerSource` for one segment batch: the run's worker, an `INVOKE` with a lane."""

    __slots__ = ("_blob_refs", "_granted", "_parse")

    def __init__(self, parse: ParseOperator, granted: Any, blob_refs: tuple[str, ...]) -> None:
        self._parse = parse
        self._granted = granted
        self._blob_refs = blob_refs

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
            lane=SEGMENT_LANE,
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
