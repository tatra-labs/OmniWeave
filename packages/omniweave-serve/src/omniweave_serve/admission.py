"""The bounded admission queue. 10-interfaces.md:958, rule (a) of three.

> *"The server therefore admits at most `[serve] max_concurrent_queries` (default **2**)
> snapshots per process, queues up to `max_queued_queries` (default **8**), and refuses beyond
> that with `OW-A-022 / OW_SERVE_OVERLOADED` carrying a `retry_after_ms` computed from the
> observed p95. A queued call's wait is charged against its own deadline, and `queued_ms` is
> reported separately from `ran_ms` in `retrieval_event`."*

## WHAT IS BEING ADMITTED, AND WHY THE NUMBER IS SMALL

Snapshots, not requests. A `Snapshot` is one `BEGIN DEFERRED` held for the whole call and **a held
read transaction pins the WAL** (07-store-and-retrieval.md section 10.5), so the default of 2 is a
WAL bound before it is a latency one: unbounded concurrent retrieval against a store being written
is the exact condition that produced 22 GB of WAL and exit 137 in codegraph. A queue in front of
the cap is what turns that bound into a wait instead of a refusal, and a bound on the queue is what
stops the wait from becoming unbounded in its turn.

## WHY THIS HOLDS NO LOOP, AND WHY THAT IS THE DESIGN RATHER THAN A DODGE

Nothing here awaits, sleeps or reads a clock. `offer()`, `promote()` and `finish()` are ordinary
calls taking a monotonic reading as an argument, and the transport that owns the loop decides who
waits on what. Three reasons, in the order they bind:

1. **A policy that can be tested without an event loop is tested exhaustively.** Every state this
   object can reach is reachable from a test that passes integers, which is `clock.py`'s own
   argument for an injected `Clock` -- *"what makes the debounce and generation invariants testable
   without an operating system"* -- applied to admission.
2. **The waiting is not this object's to do.** Who is woken when a slot frees is the transport's
   question, and stdio and HTTP will answer it differently. `promote()` hands back the ticket that
   is now admitted and says nothing about how it is resumed.
3. **`asyncio` is banned in this distribution's source.** `pyproject.toml`'s `banned-api` block
   reads *"INV-3: omniweave/run/ only. Core must not import a loop"*, and `omniweave_serve`'s only
   `TID251` escape is `otlp.py`. D344 records that the ban's scope sentence and 02:264 row 40's
   grant of the transports to this distribution cannot both be read literally -- but it is not the
   reason for this shape, it is a consequence the shape happens to avoid.

## THE NAME, WHICH IS DELIBERATELY NOT `Admission`

08:669-700's `Admission` is a different object in a different distribution: four
`asyncio.BoundedSemaphore` families over cost classes, living in `omniweave/run/supervisor.py`,
narrowed to its two water marks by `omniweave_core.operator.AdmissionView`. That one gates INGEST
work under the Supervisor; this one gates RETRIEVAL snapshots under a server that 02:264 forbids
from running the Supervisor at all. Two objects named `Admission` in one repository would make
every later sentence about "admission" ambiguous, so this takes 10 section 3.11's own phrase for
itself -- *"a bounded admission queue"*.

## WHERE `retry_after_ms` COMES FROM

10:958 says *"computed from the observed p95"* and stops there, which leaves three numbers to
derive rather than invent. Each is bound to something already shipped:

* **the estimate** is the nearest-rank p95 of the last `WINDOW` observed holds. Nearest rank, and
  not an interpolation, because `omniweave/run/bench.py` already fixed that choice for this
  repository and *"two harnesses using two of them would report two p99s for one run"*; the
  binding test holds this function against that one.
* **the cold value**, for the refusal that happens before anything has completed, is
  `[retrieval.budget] query_ms`. That is not a spare number: 12-performance.md's B27 makes 250 ms
  *"G10's ceiling and `[retrieval.budget] query_ms`"* and the p95 of the very operation a refused
  caller is waiting on. The first refusal quotes the plan's own committed p95 for it.
* **the ceiling** is `[retrieval] snapshot_ms`, the clamp on how long one read transaction may
  live. What is admitted is a snapshot, so a hold cannot outlast it, and a `retry_after_ms` above
  it would advertise a wait the store's own timeout makes impossible.

`WINDOW` is this module's, and D343 records that the plan gives no window: the observation ring has
to have a length, a p95 over fewer than twenty samples is one sample's opinion, and a ring long
enough to outlive a corpus swap reports a latency the server no longer has.

## WHAT THIS MODULE DOES NOT DECIDE

The wire shape of the refusal. 10:940's table gives `OW-A-022` the row *"text refusal naming the
wait"* under a section whose closing sentence is *"the `isError` rows are all security refusals"*,
and 18:1443 says *"`OW_SERVE_OVERLOADED` (`OW-A-022`) is the one `isError: true` that carries a
`retry_after_ms`"*. Those are two answers, D345 is the entry, and the dispatcher is where the
disagreement has to be settled. `offer()` returns a `Decision` and `overloaded()` builds the
`ResourceLimit`; neither says `isError`.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from itertools import count
from typing import TYPE_CHECKING, Final

from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError, InternalError, ResourceLimit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_core.config import Config

__all__ = [
    "KEY_CEILING_MS",
    "KEY_COLD_MS",
    "KEY_CONCURRENT",
    "KEY_QUEUED",
    "OVERLOADED",
    "QUANTILE",
    "WINDOW",
    "AdmissionQueue",
    "Admitted",
    "Decision",
    "Held",
    "Verdict",
    "elapsed_ms",
    "overloaded",
    "percentile",
]

KEY_CONCURRENT: Final = "serve.max_concurrent_queries"
"""How many snapshots are held at once. 10:958's default 2."""

KEY_QUEUED: Final = "serve.max_queued_queries"
"""How many calls wait behind them. 10:958's default 8."""

KEY_COLD_MS: Final = "retrieval.budget.query_ms"
"""The estimate before anything has been observed. B27's p95 and G10's ceiling."""

KEY_CEILING_MS: Final = "retrieval.snapshot_ms"
"""The clamp on one read transaction's life, and therefore on any honest `retry_after_ms`."""

OVERLOADED: Final = "OW_SERVE_OVERLOADED"
"""`OW-A-022`. The symbol is the wire form; the numeric is resolved from `codes.toml`."""

QUANTILE: Final = 0.95
"""p95, because 10:958 says p95."""

WINDOW: Final = 128
"""How many completed holds the estimate is computed over.

**Not from the plan.** Two bounds meet here and neither is written down anywhere, so the number is
argued rather than cited. Below about twenty samples a 95th percentile is whichever single sample
happens to sit at the top, so a short ring reports one slow call as the steady state. A long ring
outlives the thing it is measuring: a corpus swap, a `[retrieval]` change or an FTS5 merge moves
the real p95 and a ring of thousands keeps quoting the old one for hours. 128 puts the p95 at the
122nd of 128 observations -- six samples above it, enough that a single outlier cannot define it --
and turns over inside a few minutes of steady traffic at the shipped concurrency of 2. D343.
"""


class Verdict(StrEnum):
    """What `offer()` decided. Three, and the middle one is the reason the object exists."""

    ADMIT = "admit"
    """A slot was free. The caller holds a ticket and may open its snapshot now."""

    QUEUE = "queue"
    """No slot, but room to wait. The ticket is in the queue and `promote()` will name it."""

    REFUSE = "refuse"
    """Neither. `OW-A-022`, and `retry_after_ms` says how long to wait before asking again."""


@dataclass(frozen=True, slots=True)
class Decision:
    """`offer()`'s whole answer, including the two counts that explain it.

    The counts are reported on every verdict and not only on a refusal, because an operator reading
    `retrieval_event` needs to know that a call which was admitted was admitted into a busy server.
    """

    verdict: Verdict
    ticket: int
    running: int
    queued: int
    retry_after_ms: int
    """Zero on `ADMIT` and `QUEUE`: a call that was not refused was not asked to come back."""


@dataclass(frozen=True, slots=True)
class Admitted:
    """A queued ticket that just reached the front. `queued_ms` is what the wait cost it.

    10:961 charges that wait *"against its own deadline"*, which is the caller's arithmetic and not
    this object's: the deadline belongs to the request, and an admission queue that held deadlines
    would be deciding retrieval policy from the wrong side of the seam.
    """

    ticket: int
    queued_ms: int


@dataclass(frozen=True, slots=True)
class Held:
    """What one completed call cost, with the two durations kept apart.

    **`queued_ms` is ALWAYS separate from `ran_ms`** -- 02:1126, 08:52 and 15:1234 all say it, and
    `omniweave_core.operator.StepMetrics` writes it in capitals on the field. A contended admission
    and a slow query are indistinguishable from outside, and they send an operator to opposite
    knobs: one to `max_concurrent_queries`, the other to the index.
    """

    ticket: int
    queued_ms: int
    ran_ms: int


def percentile(ordered: Sequence[int], quantile: float) -> float:
    """The `quantile` of an ALREADY-SORTED sample, by NEAREST RANK. Empty is `nan`.

    The same definition, clause for clause, as `omniweave.run.bench.percentile`, and
    `test_serve_admission.py` holds the two against each other over a battery of samples. It is
    duplicated rather than imported because 02:264 forbids this distribution from importing
    `omniweave` at all -- the same seam `catalog.py` crosses by test and not by import, one
    function smaller. D346 records it as the fourth instance of that class.

    Nearest rank has the property that matters here: every value it returns is a value that was
    actually observed, so a `retry_after_ms` names a wait some call really took.
    """
    total = len(ordered)
    if total == 0:
        return math.nan
    if not 0.0 < quantile <= 1.0:
        raise ValueError(f"quantile is in (0, 1]; got {quantile}")
    rank = math.ceil(quantile * total)
    return ordered[min(total, max(1, rank)) - 1]


def _shipped_int(key: str) -> int:
    """The declared default for `key`, read from the registry rather than transcribed."""
    default = KEYS[key].default
    if not isinstance(default, int) or isinstance(default, bool):
        raise InternalError(  # pragma: no cover - a registry edit would have to break the kind
            f"{key} is declared {default!r}, which is not an int",
            fix="ow doctor --deep --render json   # attach the report: this is an omniweave bug",
        )
    return default


def overloaded(decision: Decision) -> ResourceLimit:
    """`OW-A-022 / OW_SERVE_OVERLOADED` for a refused `Decision`, naming the knob and the wait.

    `ResourceLimit` and not `SurfaceError`, although `OW-A-022` is an `A` code: the area letter
    names which register table a numeric lives in, and `codes.toml`'s own header says
    *"ResourceLimit is cross-area and allocates no letter of its own"* for exactly this case. The
    class exists because it is *"the ONE error required to name a knob"*, and an overload whose
    message did not name `max_queued_queries` would leave an operator tuning the wrong number.
    """
    if decision.verdict is not Verdict.REFUSE:
        raise InternalError(
            f"{decision.verdict} is not a refusal and has no OW-A-022 to report",
            fix="ow doctor --deep --render json   # attach the report: this is an omniweave bug",
        )
    return ResourceLimit(
        f"the server is at its admission ceiling: {decision.running} snapshot(s) held and "
        f"{decision.queued} call(s) already waiting. Retry after {decision.retry_after_ms} ms",
        limit=KEY_QUEUED,
        symbol=OVERLOADED,
        fix=f"ow config set {KEY_QUEUED} <n>   # or retry after retry_after_ms",
    )


class AdmissionQueue:
    """The state machine 10 section 3.11 rule (a) describes, and nothing else.

    Four transitions, each taking the caller's monotonic reading in nanoseconds:

    * `offer(at_ns)` -- `ADMIT`, `QUEUE` or `REFUSE`, and a ticket for the first two;
    * `promote(at_ns)` -- the queued ticket that a freed slot now belongs to, or `None`;
    * `finish(ticket, at_ns)` -- the hold ends, and `Held` reports what it cost;
    * `abandon(ticket)` -- a waiting caller left, which `notifications/cancelled` is.

    **`finish()` does not promote.** Freeing a slot and choosing who takes it are two facts, and an
    event loop needs the second one by name so it can wake exactly one waiter. A `finish()` that
    promoted would return two tickets and leave the caller to guess which of them to resume.

    **The queue is FIFO and says so.** Nothing in 10 section 3.11 asks for a priority, and a
    retrieval queue that reordered would make `queued_ms` unattributable -- the number an operator
    reads to tell a contended admission from a slow query.
    """

    __slots__ = (
        "_ceiling_ms",
        "_cold_ms",
        "_max_concurrent",
        "_max_queued",
        "_observed",
        "_queue",
        "_running",
        "_tickets",
    )

    def __init__(
        self,
        *,
        max_concurrent: int,
        max_queued: int,
        cold_ms: int,
        ceiling_ms: int,
    ) -> None:
        _positive(max_concurrent, KEY_CONCURRENT)
        _nonnegative(max_queued, KEY_QUEUED)
        _positive(cold_ms, KEY_COLD_MS)
        _positive(ceiling_ms, KEY_CEILING_MS)
        self._max_concurrent = max_concurrent
        self._max_queued = max_queued
        self._cold_ms = cold_ms
        self._ceiling_ms = ceiling_ms
        self._tickets = count(1)
        self._queue: deque[tuple[int, int]] = deque()
        self._running: dict[int, tuple[int, int]] = {}
        self._observed: deque[int] = deque(maxlen=WINDOW)

    @classmethod
    def shipped(cls) -> AdmissionQueue:
        """The queue an unconfigured server runs, built from the four declared defaults.

        Nothing is transcribed: every number comes out of `omniweave_core.config.KEYS`, so a
        default that moves moves here with it and there is no second copy to drift.
        """
        return cls(
            max_concurrent=_shipped_int(KEY_CONCURRENT),
            max_queued=_shipped_int(KEY_QUEUED),
            cold_ms=_shipped_int(KEY_COLD_MS),
            ceiling_ms=_shipped_int(KEY_CEILING_MS),
        )

    @classmethod
    def from_config(cls, config: Config) -> AdmissionQueue:
        """The queue a configured server runs. The same four keys, resolved through the layers."""
        return cls(
            max_concurrent=_as_int(config, KEY_CONCURRENT),
            max_queued=_as_int(config, KEY_QUEUED),
            cold_ms=_as_int(config, KEY_COLD_MS),
            ceiling_ms=_as_int(config, KEY_CEILING_MS),
        )

    @property
    def running(self) -> int:
        """Snapshots held right now."""
        return len(self._running)

    @property
    def queued(self) -> int:
        """Calls waiting for one."""
        return len(self._queue)

    @property
    def observations(self) -> int:
        """Completed holds the estimate is currently computed over, at most `WINDOW`."""
        return len(self._observed)

    def retry_after_ms(self) -> int:
        """The advertised wait: the observed p95, floored at 1 ms, clamped to the snapshot ceiling.

        Floored at 1 because a `retry_after_ms` of 0 tells an agent to retry immediately, which is
        the one instruction a server at its ceiling must not give. Clamped because a hold cannot
        outlive `[retrieval] snapshot_ms` -- the transaction is aborted at it -- so a larger
        estimate would be advertising a wait that cannot happen.
        """
        if not self._observed:
            estimate = self._cold_ms
        else:
            estimate = int(percentile(sorted(self._observed), QUANTILE))
        return max(1, min(estimate, self._ceiling_ms))

    def offer(self, *, at_ns: int) -> Decision:
        """Admit, queue or refuse one call. The ticket is 0 on a refusal and never reused."""
        if len(self._running) < self._max_concurrent:
            ticket = next(self._tickets)
            self._running[ticket] = (0, at_ns)
            return self._decision(Verdict.ADMIT, ticket)
        if len(self._queue) < self._max_queued:
            ticket = next(self._tickets)
            self._queue.append((ticket, at_ns))
            return self._decision(Verdict.QUEUE, ticket)
        return Decision(
            verdict=Verdict.REFUSE,
            ticket=0,
            running=len(self._running),
            queued=len(self._queue),
            retry_after_ms=self.retry_after_ms(),
        )

    def promote(self, *, at_ns: int) -> Admitted | None:
        """Give a freed slot to the longest-waiting call, or `None` if there is no taker.

        `None` covers both of the ways there can be none -- an empty queue, and a queue whose head
        cannot be admitted because the cap is still full -- and the caller treats them alike: it
        has nobody to wake.
        """
        if not self._queue or len(self._running) >= self._max_concurrent:
            return None
        ticket, offered_ns = self._queue.popleft()
        queued_ms = elapsed_ms(offered_ns, at_ns)
        self._running[ticket] = (queued_ms, at_ns)
        return Admitted(ticket=ticket, queued_ms=queued_ms)

    def finish(self, ticket: int, *, at_ns: int) -> Held:
        """End a hold and record it. The `ran_ms` recorded here is what later p95s are made of."""
        held = self._running.pop(ticket, None)
        if held is None:
            raise InternalError(
                f"ticket {ticket} is not holding a snapshot: it was finished twice, or never "
                f"admitted",
                fix="ow doctor --deep --render json   # attach the report: this is an "
                "omniweave bug",
            )
        queued_ms, started_ns = held
        ran_ms = elapsed_ms(started_ns, at_ns)
        self._observed.append(ran_ms)
        return Held(ticket=ticket, queued_ms=queued_ms, ran_ms=ran_ms)

    def abandon(self, ticket: int) -> bool:
        """Drop a ticket that is still waiting. `True` if it was there.

        This is where an MCP `notifications/cancelled` for a call that never started lands. It
        records no observation, because a wait that was abandoned measures the queue and not the
        work, and feeding it to the p95 would make cancellations look like slow queries.
        """
        for index, (queued_ticket, _) in enumerate(self._queue):
            if queued_ticket == ticket:
                del self._queue[index]
                return True
        return False

    def _decision(self, verdict: Verdict, ticket: int) -> Decision:
        """A non-refusal, whose `retry_after_ms` is 0 by construction rather than by omission."""
        return Decision(
            verdict=verdict,
            ticket=ticket,
            running=len(self._running),
            queued=len(self._queue),
            retry_after_ms=0,
        )


def elapsed_ms(start_ns: int, end_ns: int) -> int:
    """Whole elapsed milliseconds, floored, and never negative.

    Floored rather than rounded because a hold that has not lasted a millisecond has not lasted
    one. Clamped at zero because 08:377 is explicit that a clock stepping backwards must not turn a
    duration into nonsense -- here it would be a negative `ran_ms` poisoning every later p95.
    """
    return max(0, (end_ns - start_ns) // 1_000_000)


def _positive(value: int, key: str) -> None:
    """A cap that must admit something. `max_concurrent_queries = 0` refuses every call forever."""
    if value < 1:
        raise ConfigError(
            f"{key} is {value}; it must be at least 1",
            symbol="OW_CONFIG_VALUE",
            fix=f"set {key} to 1 or more in omniweave.toml, or remove it to take the default",
        )


def _nonnegative(value: int, key: str) -> None:
    """A queue of zero is a legitimate choice: refuse rather than wait. A negative one is not."""
    if value < 0:
        raise ConfigError(
            f"{key} is {value}; it must not be negative",
            symbol="OW_CONFIG_VALUE",
            fix=f"set {key} to 0 or more in omniweave.toml, or remove it to take the default",
        )


def _as_int(config: Config, key: str) -> int:
    """One resolved key as an int, refusing anything the loader let through as another kind."""
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(
            f"{key} resolved to {value!r}, which is not an integer",
            symbol="OW_CONFIG_VALUE",
            fix=f"set {key} to an integer in omniweave.toml, or remove it to take the default",
        )
    return value
