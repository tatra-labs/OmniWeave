"""The middleware order, which is the artifact -- and the only caller of `DriverHost.invoke()`.

`08-runtime.md` section 2.4 is titled *"The middleware order is the artifact"* and it means the
sentence literally: the eight layers are nothing on their own, and every one of them is a
`(fn) -> fn` that could sit anywhere. What this file ships is **where each one sits**, which is what
the section's own two property tests are about and what `02-architecture.md:74` marks in the module
map -- *"run/pipeline.py -- THE MIDDLEWARE ORDER; the ONLY caller of DriverHost.invoke() (G8)"*.

```text
with_events                  span open/close, W3C ids, ALWAYS ON
 |- with_request_count
    |- with_cache            <- A HIT RETURNS HERE. Zero budget, zero tokens, zero rate-limit
       |                        slots. Spend replayed from cache_index.spend_json,
       |                        was_cache_hit=True, micros RE-PRICED from the current PriceBook.
       |- with_budget        <- reserve/commit. A denial short-circuits to DEFERRED_BUDGET.
          |- with_retries    <- OUTSIDE rate limiting: a retry gets back in line.
             |                  Semaphore(1) per (unit_uri, unit_part)
             |- with_rate_limiting   no busy-wait, no time.sleep under a held lock
                |- with_metrics     <- measures the PROVIDER, not the queue
                   |- with_fault_injection
                      |- DriverHost.invoke(batch)
```

## The chain is synchronous, and that is derived rather than chosen

`Worker.invoke()` is a blocking frame loop over a pipe, and `02-architecture.md:659` pushes the CPU
render through `asyncio.to_thread`; so the whole chain runs inside a worker thread and every layer
here is an ordinary function. That is the same argument `BudgetLedger`'s own docstring makes for
being synchronous -- *"headroom is computed in SQL on a synchronous connection, never awaited"*
(`08:508`) -- and it is what lets `with_retries` hold a `threading.Lock` without blocking the loop,
and what lets every layer be tested without one. `asyncio` is permitted in this package; it is not
needed here, and a layer that awaited would be a layer that could not be tested without a loop.

## Two things the order buys, and both are property-tested

* **I25 -- a cache hit costs nothing.** `with_cache` sits OUTSIDE `with_budget`, so a hit returns
  before a reservation exists: zero budget, zero tokens, zero rate-limit slots, no driver
  constructed. `test_a_hit_returns_through_a_zero_headroom_ledger` runs a full-hit call through a
  ledger that denies every dimension and asserts `SKIPPED_CACHED`.
* **I8 -- no billable work without a reservation.** `with_budget` sits INSIDE `with_cache` and
  OUTSIDE `with_retries`, so every path that reaches the host has passed `admit()` first, and a
  retry re-enters below the reservation rather than around it.

The second placement has a third consequence `08:838` states and this module implements: a retry is
*"OUTSIDE rate limiting: a retry gets back in line"*. A retry that re-entered below the limiter
would be a client that answers a provider's congestion signal by spending its remaining quota
faster.

## `with_cache` splits the call rather than passing it through

`08:1795`: *"`outstanding` is what gets dispatched. `with_cache` returns `SKIPPED_CACHED` for every
hit **before** `with_budget` runs, so a 100%-hit Batch reserves nothing, consumes no rate-limit
slot, and constructs no driver."* A partly-hit batch is therefore **narrowed**: `Call.narrowed()`
builds the sub-call of the units that missed, the inner chain sees only those, and
`Reply.widened()` puts the answers back at their original indices. Every layer below `with_cache` is
written against a call whose every unit must be computed, which is why none of them carries a
"was this a hit" branch.

## What is deliberately NOT here

* **`probe()`.** `08:1770`'s `CacheProbe` carries decoded artefacts, a replayed `Spend` and
  re-priced micros; issuing it is one indexed query per Batch against `cache_index`. That is W4.4's
  half-built other end; this module declares `CacheDecision` -- the projection of that answer onto
  the two things a `(fn) -> fn` layer can act on -- and takes the query as a callable. The
  middleware never holds document bytes (I31), so `CacheProbe.hits`' decoded payloads reach the
  Operator through `Reply.produced` as `ArtifactRef`s and not as bytes.
* **`admit()`.** `16-roadmap.md:545` schedules *"`admit()` returning `admitted | deferred |
  degraded`"* with W4.5, beside the durable ledger. `with_budget` takes an `Admitter` and turns its
  three-valued answer into an `Outcome`; the arithmetic that produces it is `budget.py`'s.
* **The Operators.** `08:1905` puts them in `omniweave/run/operators/` and `ops/`, *"next to the
  middleware that is their only caller"*. `Operator.run()` calls `dispatch()`; `dispatch()` calls
  the host. An Operator that called the host directly *"would bypass the cache, the budget and the
  retry semaphore in one line"* (`08:1928`), which is the semgrep rule this file is the sole
  exclusion of.
* **The loop.** claim -> admit -> dispatch -> complete -> reap is `supervisor.py`'s. This module is
  called by the dispatch step and calls nothing above itself.

Specified in 08-runtime.md sections 2.4, 2.6, 5.5 and 7.4, 02-architecture.md section 1's module map
and section 4.1 row 11, 09-generation.md section 3, 12-performance.md section 5.8, and
15-observability.md section 2.1.
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypeAlias

from omniweave_core.cache import CacheLayer, CacheVerdict
from omniweave_core.errors import ConfigError, ResourceLimit, RouteError
from omniweave_core.events import EventKind
from omniweave_core.observe.degradation import Degradation
from omniweave_core.operator import Outcome
from omniweave_ports.types import ArtifactRef, FailureClass

from omniweave.route.spend import Spend
from omniweave.run.dispatch import Batch, call_attributes

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator

    from omniweave_core.clock import Clock
    from omniweave_core.host.subproc import InvokeReport
    from omniweave_ports.types import UnitRef

__all__ = [
    "CACHE_LAYER_BY_OPERATOR",
    "DEFAULT_MAX_ATTEMPTS",
    "HIT_VERDICTS",
    "LAYER_ORDER",
    "Admitter",
    "BudgetVerdict",
    "CacheDecision",
    "Call",
    "Chaos",
    "Handler",
    "Layer",
    "Prober",
    "Reply",
    "RequestCount",
    "RetryGuard",
    "TokenBucket",
    "build",
    "cache_layer_for",
    "chaos_fires",
    "with_budget",
    "with_cache",
    "with_events",
    "with_fault_injection",
    "with_metrics",
    "with_rate_limiting",
    "with_request_count",
    "with_retries",
]


# =============================================================================================
# 1. The order, as data
# =============================================================================================

LAYER_ORDER: Final[tuple[str, ...]] = (
    "with_events",
    "with_request_count",
    "with_cache",
    "with_budget",
    "with_retries",
    "with_rate_limiting",
    "with_metrics",
    "with_fault_injection",
)
"""The eight, outermost first. `08:832-845`'s diagram read top to bottom, and `02:481` read left to
right -- the two agree, and this tuple is asserted against both.

A tuple and not a comment because the order **is** the artifact: `build()` composes from this
sequence, `Reply.stopped_at` names a member of it, and `test_the_order_is_the_plans_diagram` parses
the diagram out of `08-runtime.md` and compares. A reordering that a reviewer would have to spot by
reading eight `if`s becomes a one-line diff in a constant instead."""

DEFAULT_MAX_ATTEMPTS: Final = 5
"""`work.attempts_total < 5` is the claim predicate's clause (`08:105`), so five is the number of
times a row can be claimed at all. `with_retries` does not re-derive a ladder: the retry *decision*
is `classify()`'s and the cooldown is `Failure.cooldown_ms`; this ceiling only stops an in-call loop
from outliving the row's own budget."""

HIT_VERDICTS: Final[frozenset[CacheVerdict]] = frozenset(
    {CacheVerdict.HIT, CacheVerdict.HIT_LEGACY}
)
"""The two of the seven that answer a unit. `hit_legacy` served the request and is simultaneously
the mixed-vintage warning (`08:1772`'s `legacy` counter), so it short-circuits like a hit and is
counted like a warning -- the same split `CacheStats.from_verdicts()` makes in the manifest."""


# =============================================================================================
# 2. `with_cache` must be told which layer to probe, and the operator fixes it
# =============================================================================================

CACHE_LAYER_BY_OPERATOR: Final[Mapping[str, CacheLayer | None]] = {
    "acquire.fs": None,
    "acquire.*": CacheLayer.BLOB,
    "op.identify": None,
    "op.converge": None,
    "op.lexicon": None,
    "op.resolve": None,
    "op.cluster": None,
    "parse.*": CacheLayer.CALL,
    "derive.*": CacheLayer.CALL,
    "embed.*": CacheLayer.EMBED,
    "compile.*": None,
}
"""`08:856-869`'s table, transcribed -- **the mapping is fixed by the operator, not by the driver**.

Two of the plan's ten rows are not operators and are absent from this table on purpose. *"the raster
step inside a `render`-requiring decision"* -> `render` and *"`evaluate()`'s signal computation"* ->
`signal` are steps inside the router, not `work` rows with an `operator` column, so they probe their
layer at their own call site and never reach `with_cache`. That is why `CacheLayer` has five members
and this table has three: the two missing ones belong to P5.

`acquire.fs` is `None` and the row says why -- *"the file IS the blob; a copy would be a second
representation"* -- which is also the reason a 100%-cache-hit `ow ingest` issues **zero** cache
queries for it (`08:870`): an operator with no layer skips `with_cache` entirely rather than probing
a layer it can never hit."""


def cache_layer_for(operator: str) -> CacheLayer | None:
    """The `CacheLayer` one operator probes, or `None` when it probes nothing.

    Exact match first, then the `<port>.*` family. An operator outside the table is refused rather
    than defaulted: `08:854` fixes the mapping by the operator, so an unknown one has no answer, and
    guessing `None` would silently turn a billed driver's cache off.
    """
    if operator in CACHE_LAYER_BY_OPERATOR:
        return CACHE_LAYER_BY_OPERATOR[operator]
    port, _, family = operator.partition(".")
    if family and f"{port}.*" in CACHE_LAYER_BY_OPERATOR:
        return CACHE_LAYER_BY_OPERATOR[f"{port}.*"]
    raise ConfigError(
        f"{operator!r} has no row in 08 section 2.4's cache-layer table",
        fix="add the operator to CACHE_LAYER_BY_OPERATOR when its row lands in the plan",
    )


# =============================================================================================
# 3. What travels through the chain
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Call:
    """One `DriverHost.invoke()`, as the middleware sees it before any layer has run.

    A `Batch` plus the four things the layers need that a batch does not carry: the units the rows
    resolve to, the operator (which fixes the cache layer), the deadline and the budget ceiling that
    go into `INVOKE{invoke_id, units, deadline_ms, budget_micros}`.

    **`units` is parallel to `batch.rows` and the pairing is load-bearing**, for the same reason
    `dispatch.invocation_units()` refuses a pairing that is not one-to-one and in order:
    `RESULT{unit_index}` is an index INTO THE BATCH. `narrowed()` is the only thing that may break
    that alignment, and `widened()` is the only thing that may repair it.
    """

    batch: Batch
    units: tuple[UnitRef, ...]
    operator: str
    deadline_ms: int = 0
    budget_micros: int = 0
    attempt: int = 1
    provider: str = ""
    batch_index: int = 0
    origin: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if len(self.units) != self.batch.size:
            raise RouteError(
                f"{len(self.units)} units against a batch of {self.batch.size}; RESULT.unit_index "
                f"is an index into the batch, so the two are one-to-one and in order",
                fix="build the units with dispatch.invocation_units()",
            )
        if not self.units:
            raise RouteError(
                "a call over no units",
                fix="form_batches() never produces an empty batch; do not narrow to nothing",
            )
        if self.attempt < 1:
            raise RouteError(
                f"attempt {self.attempt}; route_spend.attempt is 1-based",
                fix="the first attempt is 1",
            )
        if self.origin and len(self.origin) != len(self.units):
            raise RouteError(
                f"{len(self.origin)} origin indices against {len(self.units)} units",
                fix="narrowed() sets origin; do not set it by hand",
            )

    @property
    def size(self) -> int:
        return len(self.units)

    @property
    def cache_layer(self) -> CacheLayer | None:
        """`08:854`'s table, resolved once from the operator. Never asked of the driver."""
        return cache_layer_for(self.operator)

    def keys(self) -> tuple[tuple[str, str], ...]:
        """`(unit_uri, unit_part)` per unit -- `with_retries`' `Semaphore(1)` key (`08:925`)."""
        return tuple((unit.uri, unit.part) for unit in self.units)

    def narrowed(self, indices: Sequence[int]) -> Call:
        """The sub-call over `indices`, in order, carrying where each unit came from.

        The `Batch` is narrowed with it, because everything below `with_cache` reads `batch.size`
        as the number of units in flight -- a batch that still claimed 256 rows while eight went to
        the driver would put a wrong `batch_size` on the `call` span and a wrong ceiling on AIMD.
        """
        picked = tuple(indices)
        if not picked:
            raise RouteError(
                "narrowing a call to no units; the caller short-circuits instead",
                fix="check CacheDecision.outstanding before narrowing",
            )
        if sorted(picked) != list(picked) or len(set(picked)) != len(picked):
            raise RouteError(
                f"narrowing to {picked}, which is not a strictly increasing index list",
                fix="pass CacheDecision.outstanding, which is in unit order",
            )
        out_of_range = tuple(index for index in picked if not 0 <= index < self.size)
        if out_of_range:
            raise RouteError(
                f"{out_of_range} are outside a call of {self.size} units",
                fix="index into Call.units",
            )
        origin = self.origin or tuple(range(self.size))
        return replace(
            self,
            batch=Batch(
                invoke_id=self.batch.invoke_id,
                rows=tuple(self.batch.rows[index] for index in picked),
            ),
            units=tuple(self.units[index] for index in picked),
            origin=tuple(origin[index] for index in picked),
        )


@dataclass(frozen=True, slots=True)
class Reply:
    """One call's answer, at the call's own width. Always `len(outcomes) == call.size`.

    I24 in the middleware's terms: `dispatch.fan_out()` guarantees one outcome per unit out of the
    host, and every layer here preserves that width or is a bug. `stopped_at` names the layer that
    produced the answer -- `""` when the host did -- which is what makes *"A HIT RETURNS HERE"* an
    assertion rather than a comment.

    The per-unit tuples are parallel to `outcomes` and each is either empty or full width. Empty
    means "this layer had nothing to say about money", which is different from seven zeros: a
    `DEFERRED_BUDGET` reply carries no `Spend` because nothing ran, and a free driver's reply
    carries seven honest zeros because something did.
    """

    outcomes: tuple[Outcome, ...]
    report: InvokeReport | None = None
    produced: tuple[tuple[ArtifactRef, ...], ...] = ()
    spend: tuple[Spend, ...] = ()
    micros: tuple[int, ...] = ()
    stopped_at: str = ""
    deferred_dim: str | None = None
    would_have_been_micros: int = 0
    degradations: tuple[Degradation, ...] = ()
    provider_ms: int = 0

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise RouteError(
                "a reply over no units; every call answers for every unit it carried (I24)",
                fix="build replies with Reply.of() or from fan_out()",
            )
        width = len(self.outcomes)
        for name in ("produced", "spend", "micros"):
            side: tuple[object, ...] = getattr(self, name)
            if side and len(side) != width:
                raise RouteError(
                    f"reply.{name} has {len(side)} entries against {width} outcomes; a per-unit "
                    f"tuple is empty or full width",
                    fix="pad to the call's width, or leave it empty",
                )
        if self.stopped_at and self.stopped_at not in LAYER_ORDER:
            raise RouteError(
                f"{self.stopped_at!r} is not one of the eight layers {LAYER_ORDER}",
                fix="name the layer that returned, or leave it empty for the host",
            )
        if (self.deferred_dim is not None) != (Outcome.DEFERRED_BUDGET in self.outcomes):
            raise RouteError(
                "deferred_dim and DEFERRED_BUDGET travel together; StepResult requires the "
                "dimension on that outcome and it is meaningless on any other",
                fix="set both, or neither",
            )

    @property
    def size(self) -> int:
        return len(self.outcomes)

    @classmethod
    def of(cls, outcome: Outcome, size: int, **rest: object) -> Reply:
        """One outcome, repeated across a whole call. The short-circuit constructor."""
        return cls(outcomes=(outcome,) * size, **rest)  # type: ignore[arg-type]

    def widened(self, origin: Sequence[int], width: int, filler: Reply) -> Reply:
        """Put this narrowed reply's answers back at `origin`, over `filler`'s full-width answer.

        The merge `with_cache` performs after a partial hit, and the only place two replies become
        one. `filler` is the hit-side reply, already at full width; this one carries the units that
        went down the chain. Scalars are taken from whichever reply has a non-default value, with
        this one winning -- a `provider_ms` measured on the outstanding units is the call's provider
        time, and the hit side has none by construction.
        """
        if len(origin) != self.size:
            raise RouteError(
                f"{len(origin)} origin indices against {self.size} outcomes",
                fix="pass Call.origin from the narrowed call",
            )
        if filler.size != width:
            raise RouteError(
                f"the filler reply is {filler.size} wide against a call of {width}",
                fix="the hit-side reply is built at the original call's width",
            )
        outcomes = list(filler.outcomes)
        produced = list(filler.produced or (((),) * width))
        spend = list(filler.spend or ((Spend(),) * width))
        micros = list(filler.micros or ((0,) * width))
        mine_produced = self.produced or (((),) * self.size)
        mine_spend = self.spend or ((Spend(),) * self.size)
        mine_micros = self.micros or ((0,) * self.size)
        for slot, index in enumerate(origin):
            outcomes[index] = self.outcomes[slot]
            produced[index] = mine_produced[slot]
            spend[index] = mine_spend[slot]
            micros[index] = mine_micros[slot]
        return Reply(
            outcomes=tuple(outcomes),
            report=self.report,
            produced=tuple(produced),
            spend=tuple(spend),
            micros=tuple(micros),
            stopped_at=self.stopped_at,
            deferred_dim=self.deferred_dim,
            would_have_been_micros=filler.would_have_been_micros + self.would_have_been_micros,
            degradations=filler.degradations + self.degradations,
            provider_ms=self.provider_ms or filler.provider_ms,
        )


Handler: TypeAlias = Callable[["Call"], "Reply"]
"""What every layer wraps and what every layer returns: one call in, one reply out."""

Layer: TypeAlias = Callable[[Handler], Handler]
"""`08:849`: *"Each layer is `(fn) -> fn`."* The alias exists so that sentence has a name a reader
can look up, and so `build()`'s eight assignments are visibly one kind of thing."""


# =============================================================================================
# 4. `with_events` -- ALWAYS ON, and the only layer with no `if`
# =============================================================================================


def with_events(
    inner: Callable[[Call], Reply],
    *,
    emit: Callable[..., object],
    driver_version: str = "",
    driver_schema_v: int = 0,
    isolation: str = "",
) -> Callable[[Call], Reply]:
    """`call.begin` before, `call.end` after, with `15:140`'s eighteen attributes across the pair.

    **The outermost layer and the one that is never skipped.** `08:832` writes ALWAYS ON beside it,
    and the reason is `15`'s: the event stream is diagnostic and droppable, so turning it off is the
    sink list's job (`[observe] sinks = []`) and never the chain's. A layer that could be composed
    out would make "every driver call has a span" a configuration rather than a fact.

    The attributes come from `dispatch.call_attributes()` -- this module does not spell the eighteen
    a second time. `call.begin` carries what is known before the call and `call.end` carries the
    same map with `spend` and `micros` filled in, which is the partition D150 recorded when it
    appended the two kinds: `invoke_id` is on both, so the pair joins.

    An `end` is emitted even when the inner chain raises, because a span that opens and never closes
    is I33's orphan and `RunRecorder` buffers the subtree until it closes.
    """

    def handler(call: Call) -> Reply:
        attributes = call_attributes(
            call.batch,
            batch_index=call.batch_index,
            driver_version=driver_version,
            driver_schema_v=driver_schema_v,
            isolation=isolation,
            provider=call.provider,
        )
        emit(kind=EventKind.CALL_BEGIN, fields=attributes)
        try:
            reply = inner(call)
        except BaseException:
            emit(kind=EventKind.CALL_END, fields={**attributes, "outcome": "driver_crashed"})
            raise
        emit(
            kind=EventKind.CALL_END,
            fields={
                **call_attributes(
                    call.batch,
                    batch_index=call.batch_index,
                    driver_version=driver_version,
                    driver_schema_v=driver_schema_v,
                    isolation=isolation,
                    provider=call.provider,
                    spend=_total(reply.spend),
                    micros=sum(reply.micros),
                ),
                "outcome": str(reply.outcomes[0]),
            },
        )
        return reply

    return handler


def _total(spend: Sequence[Spend]) -> Spend | None:
    """The call's `Spend`, summed. `None` when nothing reported one, which is not seven zeros.

    `Spend.__add__` refuses to add across providers, and that refusal is right here too: one call is
    one driver at one provider, so a sum that raised would mean the batch was mis-attributed.
    """
    if not spend:
        return None
    total = Spend()
    for one in spend:
        total = total + one
    return total


# =============================================================================================
# 5. `with_request_count` -- what the CALLER asked for, above the cache
# =============================================================================================


@dataclass(slots=True)
class RequestCount:
    """graphrag's three counters (`graphrag_llm/middleware/with_request_count.py`), verbatim.

    `attempted_request_count`, `successful_response_count` and `failed_response_count` are that
    module's own names for the same three numbers, set on every call and incremented here rather
    than there because one process makes many calls.

    **Its position is the whole of its meaning.** Above `with_cache`, it counts what the *caller*
    asked for; `with_metrics`, at the bottom, counts what the *provider* did. A cache hit
    increments `attempted` and `succeeded` here and nothing at all down there, so the difference
    between the two counts is exactly the cache's contribution -- and neither number has to know the
    cache exists. graphrag makes the same split, and its pipeline applies this layer last
    (outermost) for the same reason.
    """

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0

    def as_manifest_fields(self) -> Mapping[str, int]:
        return {
            "attempted_request_count": self.attempted,
            "successful_response_count": self.succeeded,
            "failed_response_count": self.failed,
        }


def with_request_count(
    inner: Callable[[Call], Reply], *, counter: RequestCount
) -> Callable[[Call], Reply]:
    """Count the call, then count how it ended. A raise counts as a failure and re-raises.

    A `DEFERRED_BUDGET` reply is a **success** by this counter's reckoning and that is deliberate:
    `08:2285` says *"a denial is never a failure"*, and a counter that called it one would make the
    first number an operator reads after a budget cap says no look like breakage.
    """

    def handler(call: Call) -> Reply:
        counter.attempted += 1
        try:
            reply = inner(call)
        except BaseException:
            counter.failed += 1
            raise
        counter.succeeded += 1
        return reply

    return handler


# =============================================================================================
# 6. `with_cache` -- A HIT RETURNS HERE
# =============================================================================================


@dataclass(frozen=True, slots=True)
class CacheDecision:
    """`08:1770`'s `CacheProbe`, projected onto what a `(fn) -> fn` layer can act on.

    The full `CacheProbe` carries `hits: tuple[CacheHit, ...]` -- *"decoded artefact + replayed
    Spend + micros re-priced"* -- and `verdicts: Mapping[UnitKey, CacheVerdict]`. The middleware
    needs three of those four: which units are answered, what they produced, and what the answer is
    worth. It does **not** need the decoded payloads, because I31 keeps document bytes out of the
    supervisor; `produced` is a tuple of `ArtifactRef`, which is a reference by construction.

    Every tuple is parallel to `Call.units`, so a verdict and its unit cannot drift apart -- which
    is what `CacheProbe`'s own `Mapping[UnitKey, ...]` buys at the cost of a dictionary this layer
    would immediately have to re-order.
    """

    verdicts: tuple[CacheVerdict, ...]
    produced: tuple[tuple[ArtifactRef, ...], ...] = ()
    spend: tuple[Spend, ...] = ()
    micros: tuple[int, ...] = ()
    would_have_been_micros: int = 0

    def __post_init__(self) -> None:
        if not self.verdicts:
            raise RouteError(
                "a cache decision over no units",
                fix="probe() answers for every unit of the batch",
            )
        for name in ("produced", "spend", "micros"):
            side: tuple[object, ...] = getattr(self, name)
            if side and len(side) != len(self.verdicts):
                raise RouteError(
                    f"decision.{name} has {len(side)} entries against {len(self.verdicts)} "
                    f"verdicts; every tuple is parallel to Call.units",
                    fix="pad to the batch's width, or leave it empty",
                )

    @property
    def outstanding(self) -> tuple[int, ...]:
        """The indices that must be computed -- `08:1795`'s *"what gets dispatched"*, in order."""
        return tuple(
            index for index, verdict in enumerate(self.verdicts) if verdict not in HIT_VERDICTS
        )

    @property
    def legacy(self) -> int:
        """`CacheProbe.legacy` -- the mixed-vintage warning count."""
        return sum(1 for verdict in self.verdicts if verdict is CacheVerdict.HIT_LEGACY)


class Prober(Protocol):
    """One indexed query per Batch. The narrow end of `08:1786`'s `probe()`.

    A Protocol rather than a function type so that the layer's dependency has a name a reader can
    look up, and so a test can supply a prober that records what it was asked. `probe()` itself --
    the chunked `WHERE cache_key IN (...)` against `cache_index`, the six-clause read policy and the
    re-pricing -- is `omniweave_core.cache`'s and W4.4's.
    """

    def __call__(self, call: Call, layer: CacheLayer) -> CacheDecision: ...


def with_cache(
    inner: Callable[[Call], Reply], *, probe: Prober, layer: CacheLayer
) -> Callable[[Call], Reply]:
    """Answer every hit here; narrow the call to the misses; merge on the way back.

    Three properties, and the order is what makes all three true:

    1. **A full-hit call never reaches `with_budget`.** It returns with `stopped_at="with_cache"`,
       so zero reservations exist, zero rate-limit slots are taken and no driver is constructed
       (I25).
    2. **A partial hit dispatches only the misses.** `Call.narrowed()` re-cuts the batch, so the
       `call` span below carries the real `batch_size` and AIMD adapts against the real width.
    3. **`micros` is re-priced, not replayed.** The layer copies what `probe()` returned;
       `08:835-836` requires the number to come from the *current* `PriceBook`, so a hit billed at
       last month's prices is a bill nobody can reproduce.

    `build()` applies this layer only when the operator declares a layer, so an `acquire.fs` or
    `op.*` call issues no query at all (`08:870`).
    """

    def handler(call: Call) -> Reply:
        decision = probe(call, layer)
        if len(decision.verdicts) != call.size:
            raise RouteError(
                f"probe() answered for {len(decision.verdicts)} of {call.size} units",
                fix="probe() returns one verdict per unit of the batch",
            )
        outstanding = decision.outstanding
        hit_side = _hit_reply(call, decision)
        if not outstanding:
            return hit_side
        narrowed = call.narrowed(outstanding)
        return inner(narrowed).widened(narrowed.origin, call.size, hit_side)

    return handler


def _hit_reply(call: Call, decision: CacheDecision) -> Reply:
    """The full-width reply the hits alone would make. A miss's slot is `OK` only as a placeholder.

    `widened()` overwrites every outstanding slot, so the placeholder is never observable; it
    exists because `Reply` refuses a ragged per-unit tuple, and a sentinel `Outcome` would be a
    ninth member of a closed eight-member enum.
    """
    outcomes = tuple(
        Outcome.SKIPPED_CACHED if verdict in HIT_VERDICTS else Outcome.OK
        for verdict in decision.verdicts
    )
    return Reply(
        outcomes=outcomes,
        produced=decision.produced or (((),) * call.size),
        spend=decision.spend or ((Spend(),) * call.size),
        micros=decision.micros or ((0,) * call.size),
        stopped_at="with_cache",
        would_have_been_micros=decision.would_have_been_micros,
    )


# =============================================================================================
# 7. `with_budget` -- reserve, commit, and a denial that is not a failure
# =============================================================================================


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    """`admit()`'s three-valued answer. `route_decision.admission`'s CHECK, verbatim.

    `degraded` is the third value and it is not a denial: `05:2527`'s ladder lets a rung be admitted
    at a cheaper driver rather than refused, and the work still runs. Only `deferred` short-circuits
    here, which is why `DEFERRED_BUDGET` has a `deferred_dim` and the other two do not.
    """

    admission: Literal["admitted", "deferred", "degraded"]
    deferred_dim: str | None = None
    reservations: tuple[str, ...] = ()
    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        if self.admission not in ("admitted", "deferred", "degraded"):
            raise RouteError(
                f"{self.admission!r} is not an admission; the three are admitted, deferred, "
                f"degraded",
                fix="return one of route_decision.admission's CHECK values",
            )
        if (self.admission == "deferred") != (self.deferred_dim is not None):
            raise RouteError(
                "a deferral names the dimension that bound and nothing else does; "
                "08:2270's table makes the dimension the whole of what the operator is told",
                fix="set deferred_dim on deferred, and only on deferred",
            )


class Admitter(Protocol):
    """`admit()` plus its two closers, as one dependency. W4.5's arithmetic, this layer's shape."""

    def admit(self, call: Call) -> BudgetVerdict: ...

    def commit(self, call: Call, verdict: BudgetVerdict, spend: Sequence[Spend]) -> None: ...

    def release(self, call: Call, verdict: BudgetVerdict) -> None: ...


def with_budget(inner: Callable[[Call], Reply], *, admitter: Admitter) -> Callable[[Call], Reply]:
    """Reserve before, commit or release after. A denial short-circuits to `DEFERRED_BUDGET`.

    **This is where I8 is discharged.** Every path from here down reaches the host, and every path
    from here down has passed `admit()`, because `with_retries` is *inside* this layer -- so a retry
    re-enters below a reservation that is still held rather than around it, and a `REGEN` cannot
    double-reserve one page.

    The release on the failure path is not an optimisation. `08:2251`'s reservation is a **p95
    ceiling**, so an attempt that stops early has over-reserved by up to `3.2x` its eventual spend;
    `05:2537` releases the gap at commit and `store/budget.py`'s `RELEASE_REMAINING_SQL` sweeps what
    is left. A layer that returned without doing either would subtract from headroom until the store
    was deleted -- which is D141, recorded.
    """

    def handler(call: Call) -> Reply:
        verdict = admitter.admit(call)
        if verdict.admission == "deferred":
            return Reply.of(
                Outcome.DEFERRED_BUDGET,
                call.size,
                stopped_at="with_budget",
                deferred_dim=verdict.deferred_dim,
                degradations=verdict.degradations,
            )
        try:
            reply = inner(call)
        except BaseException:
            admitter.release(call, verdict)
            raise
        if reply.spend:
            admitter.commit(call, verdict, reply.spend)
        else:
            admitter.release(call, verdict)
        if verdict.degradations:
            reply = replace(reply, degradations=verdict.degradations + reply.degradations)
        return reply

    return handler


# =============================================================================================
# 8. `with_retries` -- Semaphore(1) per (unit_uri, unit_part), OUTSIDE rate limiting
# =============================================================================================


class RetryGuard:
    """One lock per `(unit_uri, unit_part)`, created on demand and dropped when nobody holds it.

    `08:925` lists this among the five things that are deliberately not parallel and gives the cost
    of getting it wrong in one line: *"Two attempts in flight on one page can double-bill it and
    produce two spend rows for one decision."*

    **A `threading.Lock` and not an `asyncio.Semaphore`**, because the chain runs inside
    `asyncio.to_thread` -- see the module docstring. **Reference-counted and not a growing dict**,
    because a run over `08:499`'s 331,455 rows would otherwise leave one lock object per part
    claimed, and the bound that matters is concurrency rather than corpus size: at most one entry
    per caller in flight.
    """

    __slots__ = ("_locks", "_mutex")

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._locks: dict[tuple[str, str], tuple[threading.Lock, list[int]]] = {}

    def __len__(self) -> int:
        """How many keys are held or waited on right now. Zero between calls, and tested for."""
        with self._mutex:
            return len(self._locks)

    @contextlib.contextmanager
    def hold(self, keys: Sequence[tuple[str, str]]) -> Iterator[None]:
        """Hold every key of a call, in sorted order, for the duration of the block.

        **Sorted**, which is the one thing that keeps a batch from deadlocking against another batch
        that shares two of its parts: two callers acquiring `{a, b}` in opposite orders is the
        textbook cycle, and `dispatch.form_batches()` preserves first-appearance order rather than
        sorting (`08:790`), so the orders really can differ. Deduplicated too, because a
        non-reentrant `Lock` taken twice for one repeated key is a deadlock against oneself.
        """
        wanted = sorted(set(keys))
        taken: list[tuple[str, str]] = []
        try:
            for key in wanted:
                self._acquire(key)
                taken.append(key)
            yield
        finally:
            for key in reversed(taken):
                self._release(key)

    def _acquire(self, key: tuple[str, str]) -> None:
        with self._mutex:
            entry = self._locks.get(key)
            if entry is None:
                entry = (threading.Lock(), [0])
                self._locks[key] = entry
            entry[1][0] += 1
        entry[0].acquire()

    def _release(self, key: tuple[str, str]) -> None:
        with self._mutex:
            entry = self._locks[key]
            entry[1][0] -= 1
            if entry[1][0] == 0:
                del self._locks[key]
        entry[0].release()


def with_retries(
    inner: Callable[[Call], Reply],
    *,
    guard: RetryGuard,
    should_retry: Callable[[Reply, int], bool],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Callable[[Call], Reply]:
    """Serialise a part against itself, then retry what `should_retry` says to retry.

    **Outside rate limiting, which is the placement `08:838` writes out**: *"a retry gets back in
    line."* A retry that re-entered below `with_rate_limiting` would answer a provider's congestion
    signal by spending the remaining quota faster, which is the amplifier olmocr's harness was
    rejected for (`16:1139`: *"a retry amplifier and a 1600-concurrency default"*).

    `should_retry` is supplied rather than derived, because the decision is `work.classify()`'s: a
    `Failure` carries `verdict`, `scope` and `cooldown_ms`, and re-deriving any of that here would
    be a second retry ladder. This layer owns the loop, the lock and the ceiling and nothing else.
    """
    if max_attempts < 1:
        raise ConfigError(
            f"max_attempts={max_attempts}; a call is attempted at least once",
            fix=f"the claim predicate's own ceiling is {DEFAULT_MAX_ATTEMPTS}",
        )

    def handler(call: Call) -> Reply:
        with guard.hold(call.keys()):
            attempt = call.attempt
            reply = inner(call)
            while attempt < max_attempts and should_retry(reply, attempt):
                attempt += 1
                reply = inner(replace(call, attempt=attempt))
            return reply

    return handler


# =============================================================================================
# 9. `with_rate_limiting` -- no busy-wait, no `time.sleep` under a held lock
# =============================================================================================


class TokenBucket:
    """`rate_limit_rps` requests per second, with the wait computed under the lock and slept
    outside it.

    `08:841`'s two bans are one sentence and they are two different bugs. **No busy-wait**: a loop
    that re-checks a counter burns the CPU the render semaphore was sized against
    (`02:659`'s `max(1, cpus - 2)`). **No `time.sleep` under a held lock**: a sleeper holding the
    mutex serialises every other caller behind its own delay, turning a 4-per-second limiter into a
    1-per-second one under concurrency. So `take()` computes the delay, releases, and returns it;
    the caller sleeps.

    The clock is injected (`08:277`, *"INJECTED: monotonic_ns() + wall_ns(). Never ambient"*), which
    is also what makes the limiter testable without waiting.
    """

    __slots__ = ("_clock", "_mutex", "_next_ns", "_period_ns", "_rps")

    def __init__(self, rps: int, *, clock: Clock) -> None:
        if rps < 0:
            raise ConfigError(
                f"rate_limit_rps={rps}; the card declares a non-negative rate and 0 is unlimited",
                fix="04-driver-system.md:615",
            )
        self._rps = rps
        self._period_ns = 0 if rps == 0 else 1_000_000_000 // rps
        self._clock = clock
        self._mutex = threading.Lock()
        self._next_ns = 0

    @property
    def rps(self) -> int:
        return self._rps

    def take(self) -> int:
        """Claim the next slot and return the nanoseconds to wait for it. Never sleeps."""
        if self._period_ns == 0:
            return 0
        with self._mutex:
            now = self._clock.monotonic_ns()
            start = max(now, self._next_ns)
            self._next_ns = start + self._period_ns
            return start - now


def with_rate_limiting(
    inner: Callable[[Call], Reply],
    *,
    bucket: TokenBucket,
    sleep: Callable[[float], object] = time.sleep,
) -> Callable[[Call], Reply]:
    """Wait for the bucket, then call. One slot per call, not per unit.

    Per call, because the slot models a *request* and a Batch is one `INVOKE` frame -- which is also
    why a cache hit consumes none (`02:481`: *"zero budget, zero tokens, zero rate-limit slots"*)
    and why a batch of 256 does not exhaust a 4-rps limiter in a quarter of a second.

    `sleep` is an argument so a test spends no wall time; the default is the real one. This is the
    one place in the chain that blocks, and it blocks in a worker thread by construction.
    """

    def handler(call: Call) -> Reply:
        wait_ns = bucket.take()
        if wait_ns > 0:
            sleep(wait_ns / 1_000_000_000)
        return inner(call)

    return handler


# =============================================================================================
# 10. `with_metrics` -- measures the PROVIDER, not the queue
# =============================================================================================


def with_metrics(
    inner: Callable[[Call], Reply], *, clock: Clock, record: Callable[[Call, Reply, int], object]
) -> Callable[[Call], Reply]:
    """Time the inner call and hand `(call, reply, provider_ms)` to `record`.

    **Its position is its specification.** `08:842` writes *"measures the PROVIDER, not the queue"*
    beside it, and the only thing that makes that true is that it sits BELOW `with_rate_limiting`:
    the timer starts after the limiter's sleep has already happened, so a driver that waited four
    seconds for a slot and answered in 200 ms records 200 ms. Moving this layer one line up would
    turn every latency number in the fleet into a measurement of our own queue, which is the defect
    `12-performance.md` section 5.8 spends its `queued_ms`/`ran_ms` split avoiding at the work-row
    grain.

    `clock.monotonic_ns()` and never a wall reading: `15:57` requires every duration to be a
    difference of two monotonic readings, and the shortfall on a coarse monotonic clock is D154's,
    recorded against `Clock` rather than worked around here.
    """

    def handler(call: Call) -> Reply:
        started = clock.monotonic_ns()
        try:
            reply = inner(call)
        except BaseException:
            record(call, Reply.of(Outcome.FAILED_TRANSIENT, call.size), _ms(clock, started))
            raise
        elapsed = _ms(clock, started)
        measured = replace(reply, provider_ms=elapsed)
        record(call, measured, elapsed)
        return measured

    return handler


def _ms(clock: Clock, started_ns: int) -> int:
    """Elapsed milliseconds, floored at zero. A monotonic clock does not go backwards, and a
    negative duration reaching the ledger would be a number no reader could interpret."""
    return max(0, (clock.monotonic_ns() - started_ns) // 1_000_000)


# =============================================================================================
# 11. `with_fault_injection` -- shipped in production builds, off by default
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Chaos:
    """`_chaos:{failure_rate, exception_type, latency_ms, oom_at_unit}`. `08:843-844`, the whole of
    what the plan prints.

    **Not a config key**, and that is forced rather than chosen: G18 asserts that
    `tools/config_axes.toml`'s two axis lists cover `omniweave.toml.example` *exactly*, so a
    declared key absent from the example fails the gate from one side and a documented chaos knob in
    the shipped example fails the intent from the other. graphrag hits the same wall and takes the
    same way out -- `failure_rate_for_testing` rides in `model_extra` and its own comment says it is
    *"not an exposed configuration option and is only intended for internal testing"*. This is that,
    typed. `_notes/build-defects.md` D162 asks the plan for the carrier.

    **`failure_rate` is derived, never sampled.** `random` is semgrep-banned in library code
    (`02:392`), and the ban is doing real work here: a chaos run whose failures cannot be reproduced
    cannot be the counterfactual `13-quality.md`'s Injectors need, where `degradation_detection` is
    a hard gate at 1.000. `chaos_fires()` is `blake2b(unit_key || salt) % 10000 < rate * 10000`,
    which is RT2's own recipe for `audit_selected` applied to a second derived decision.

    **`exception_type` is a `FailureClass`**, not a Python class name. graphrag names a
    `litellm.exceptions` member because its chain raises; ours classifies, and a chaos run that
    injected an exception outside the thirteen-member vocabulary would exercise a path the failure
    ladder has no row for -- which is testing the harness rather than the system.
    """

    failure_rate: float = 0.0
    exception_type: FailureClass = FailureClass.UPSTREAM_UNAVAILABLE
    latency_ms: int = 0
    oom_at_unit: str = ""
    salt: str = "ow-chaos-1"

    def __post_init__(self) -> None:
        if not 0.0 <= self.failure_rate <= 1.0:
            raise ConfigError(
                f"failure_rate={self.failure_rate}; it is a probability",
                fix="0.0 is off and 1.0 fails every call",
            )
        if self.exception_type not in set(FailureClass):
            raise ConfigError(
                f"{self.exception_type!r} is not a FailureClass",
                fix="inject one of the thirteen the failure ladder has a row for",
            )
        if self.latency_ms < 0:
            raise ConfigError(
                f"latency_ms={self.latency_ms}; injected latency is added, never subtracted",
                fix="pass a non-negative delay",
            )

    @property
    def active(self) -> bool:
        """Whether this record does anything at all. `build()` skips the layer when it does not."""
        return self.failure_rate > 0.0 or self.latency_ms > 0 or bool(self.oom_at_unit)


_CHAOS_SCALE: Final = 10_000
"""RT2's denominator: `blake2b(...) % 10000 < rate x 10000`. Ten thousand and not `2**32` because a
rate is written in the config as a decimal with at most four places, and a modulus finer than the
input's precision buys nothing but a longer number in a failure message."""


def chaos_fires(unit: UnitRef, *, rate: float, salt: str) -> bool:
    """Whether chaos fires for one unit. Derived, stable, and the same on every machine.

    Keyed on `(uri, part)` rather than on the batch, so the same page fails on every run and a
    bisect over a chaos corpus converges. `blake2b` with a domain-separating `person=` is the same
    primitive `events.sample_key()` uses for tail sampling, for the same reason: a decision a test
    has to reproduce may not come from an RNG.
    """
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    digest = hashlib.blake2b(
        f"{unit.uri}\x00{unit.part}\x00{salt}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") % _CHAOS_SCALE < int(rate * _CHAOS_SCALE)


def with_fault_injection(
    inner: Callable[[Call], Reply],
    *,
    chaos: Chaos,
    sleep: Callable[[float], object] = time.sleep,
) -> Callable[[Call], Reply]:
    """The innermost layer, directly above the host. Three knobs, applied in the plan's own order.

    `latency_ms` first, because a slow call that then fails is the shape a timeout test needs;
    `oom_at_unit` second, because a `ResourceLimit` is our own refusal and never the driver's; and
    `failure_rate` last, because it stands in for the driver's answer and must not pre-empt the two
    faults the host would have detected first.

    A fired `failure_rate` returns a `FAILED_TRANSIENT` reply rather than raising. graphrag raises,
    because its chain is exception-driven; ours is `Outcome`-driven all the way down
    (`08:1.3`'s eight members), and an injected exception would take a path no real driver failure
    takes -- `host/subproc.py` turns a dead worker into a `HostVerdict`, never into a Python
    exception crossing S4.
    """

    def handler(call: Call) -> Reply:
        if chaos.latency_ms > 0:
            sleep(chaos.latency_ms / 1000.0)
        if chaos.oom_at_unit:
            for unit in call.units:
                if unit.uri == chaos.oom_at_unit:
                    # `limit` is required, and 02:7.2 gives the reason it is: a `ResourceLimit`
                    # is *"the ONE error required to name a knob"*. The injected fault names the
                    # knob that clears it, exactly as a real one would.
                    raise ResourceLimit(
                        f"chaos: oom_at_unit fired on {unit.uri}",
                        limit="_chaos.oom_at_unit",
                        fix="clear _chaos.oom_at_unit; this is an injected fault, not a real cap",
                    )
        if chaos.failure_rate > 0.0 and any(
            chaos_fires(unit, rate=chaos.failure_rate, salt=chaos.salt) for unit in call.units
        ):
            return Reply.of(
                Outcome.FAILED_TRANSIENT,
                call.size,
                stopped_at="with_fault_injection",
            )
        return inner(call)

    return handler


# =============================================================================================
# 12. `build()` -- a plain sequence of `if`s, no framework
# =============================================================================================


def build(
    host: Callable[[Call], Reply],
    *,
    emit: Callable[..., object],
    counter: RequestCount | None = None,
    probe: Prober | None = None,
    cache_layer: CacheLayer | None = None,
    admitter: Admitter | None = None,
    guard: RetryGuard | None = None,
    should_retry: Callable[[Reply, int], bool] | None = None,
    bucket: TokenBucket | None = None,
    clock: Clock | None = None,
    record: Callable[[Call, Reply, int], object] | None = None,
    chaos: Chaos | None = None,
    sleep: Callable[[float], object] = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    driver_version: str = "",
    driver_schema_v: int = 0,
    isolation: str = "",
) -> Callable[[Call], Reply]:
    """Compose the eight around `host`, innermost first. `08:849`, literally.

    *"Each layer is `(fn) -> fn` and is skipped when its dependency is `None` -- a plain sequence of
    `if`s, no framework."* graphrag's `with_middleware_pipeline` is that sequence and this is the
    same shape: wrap from the bottom up, one `if` per optional dependency, and the resulting order
    is `LAYER_ORDER` read outermost-first.

    Two layers are not optional in the same way as the rest. **`with_events` is ALWAYS ON** and
    takes no `None`: turning the stream off is `[observe] sinks`' job, not the chain's.
    **`with_cache` is skipped when the operator declares no layer**, which is a different kind of
    absence from a missing dependency -- `08:870` makes it the reason a 100%-hit `acquire.fs` run
    issues zero cache queries -- so it needs both a prober and a layer and refuses one without the
    other.

    `with_metrics` needs a clock and a recorder together for the same reason: a timer with nowhere
    to report is a measurement nobody reads, and `08:842`'s whole point is that somebody does.
    """
    handler = host
    if chaos is not None and chaos.active:
        handler = with_fault_injection(handler, chaos=chaos, sleep=sleep)
    if clock is not None and record is not None:
        handler = with_metrics(handler, clock=clock, record=record)
    if bucket is not None and bucket.rps > 0:
        handler = with_rate_limiting(handler, bucket=bucket, sleep=sleep)
    if guard is not None and should_retry is not None:
        handler = with_retries(
            handler, guard=guard, should_retry=should_retry, max_attempts=max_attempts
        )
    if admitter is not None:
        handler = with_budget(handler, admitter=admitter)
    if probe is not None and cache_layer is not None:
        handler = with_cache(handler, probe=probe, layer=cache_layer)
    elif (probe is None) != (cache_layer is None):
        raise ConfigError(
            "with_cache needs a prober and a layer together: 08:854 fixes the layer by the "
            "operator, so a prober with no layer has nothing to probe and a layer with no prober "
            "is a query that never runs",
            fix="pass both, or neither and let the operator's None skip the layer",
        )
    if counter is not None:
        handler = with_request_count(handler, counter=counter)
    return with_events(
        handler,
        emit=emit,
        driver_version=driver_version,
        driver_schema_v=driver_schema_v,
        isolation=isolation,
    )
