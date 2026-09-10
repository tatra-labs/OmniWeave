"""Seam S1: the `DriverGuard` that wraps an in-process driver call, and nothing more.

04-driver-system.md:1822-1832 is section 6.7, "`inproc`, and the guard around it": the guard
"supplies the same `DriverIO`, the same three deadlines (enforced by a watchdog thread, since
RLIMIT is per-process) and the same `progress_ms` reset semantics. What it cannot supply is crash
containment: an `inproc` segfault kills the run."

## Which half is whose, and this file's half is the smaller one

`resolve()` decides WHETHER a driver may run in process. This module decides NOTHING about that
and re-checks none of it.

* **`omniweave_core.drivers.resolve`** owns DR9's six conjuncts (04-driver-system.md:1636-1643),
  the `isolation_shortfall` degradation that a card asking for `inproc` and failing one earns
  instead of a refusal (:1646), the `ISOLATION_NOT_PERMITTED` refusal for a card asking for
  `wasm` (:1650) and the `TRUST_INSUFFICIENT` refusal for an operator naming an id in
  `[drivers] inproc` whose computed trust bars it. `_grant_isolation()` is that function and
  `Candidate.isolation_granted` is its answer -- "**the host's decision, never the card's
  request**". Ledger D72 is the ruling that gave `TRUST_INSUFFICIENT` its one producer.
* **This module** reads that answer and refuses to run anything it did not grant. A guard that
  re-evaluated the conjuncts would be a second home for the policy (INV-21) and, worse, could
  disagree with the `Resolution` whose digest a run manifest already recorded. So the check here
  is one identity comparison -- `candidate.isolation_granted is Isolation.INPROC` -- and the
  clearance is checked at CONSTRUCTION, because a guard that exists is a guard that may run.
* **`omniweave/run/dispatch.py`** owns admission control and batching: `[runtime] max_inproc = 2`
  bounds "concurrent calls" (02-architecture.md:828) and `[runtime] inproc_bulk_threshold = 64`
  is where "the host switches" to a worker (04-driver-system.md:1828-1830). Both are counters over
  set of calls; this file sees one call and cannot count a set. 02-architecture.md:238 assigns
  "batching policy, retries and quarantine decisions" to `run/dispatch.py` by name, so neither
  knob is read here.

## The clearance check is a `Candidate` and not a duck

`DriverGuard.__init__` requires `type(candidate) is Candidate`. A structural check would let any
object with an `isolation_granted` attribute forge clearance, and clearance is exactly the thing
an attacker or a careless caller would want to forge: `Candidate` can only be built by
`resolve()`'s `_candidate_of()`, after nineteen gates. The refusal is a `DriverHostError` because
a caller handing S1 something `resolve()` did not clear is OUR bug, in the same family as
02-architecture.md:1577's "a card/code mismatch at `activate()`".

## `CARD_CODE_MISMATCH`, the half of it that exists in process

04-driver-system.md:1542-1550 checks step 4 twice on purpose, "because an `inproc` driver has no
`HELLO_ACK`". `check_code()` is the half that survives in process: the loaded class's `PORT` and
`SCHEMA_VERSION` against the card's, raising `OW_CARD_CODE_MISMATCH` -- the symbol
`codes.toml`'s `OW-D-073` already carries, reached through `RejectCode.CARD_CODE_MISMATCH.symbol`
rather than spelled again here. It takes an already-imported class and imports nothing: the
`activate()` that resolves `card.entrypoint` is a separate function the plan files under `host/`
(`tools/semgrep/omniweave.yaml`'s `omniweave-no-import-module-outside-host`) and it does not
exist in the tree yet.

## Attribution at the call boundary

02-architecture.md:1061 (seam S1's row in section 7.5): the guard "catches `BaseException` at the
call boundary and converts anything that is not a `DriverError` into `FailureClass.driver_bug`;
nothing propagates into the loop". Note the object it converts INTO: a `FailureClass`, not a
`DriverError`. That is not a nicety of wording, and `GuardFailure` exists because of it --

`DriverError.__post_init__` enforces charter D3's "`retry_after_ms` REQUIRED iff transient", and
`omniweave_ports.types:185-186` says why in as many words: "Only a driver constructs a
`DriverError`, so this set is the driver half of that table". `timeout` is transient there. But a
HOST-detected timeout is `FAILED_PERMANENT` (04-driver-system.md:1728 gives
`FAILED_PERMANENT{TIMEOUT}`, `limit = "progress_ms"`), and it has no `retry_after_ms` to give:
the host did not observe a slow remote peer, it observed a driver that stopped. A guard that
constructed `DriverError(cls=TIMEOUT)` would therefore have to invent a cooldown to satisfy a
constructor written for the other producer. `GuardFailure` carries exactly the five fields
02-architecture.md:1060 sends across S4 -- `failure_class`, message, `retry_after_ms`, `pages`,
`limit` -- and permits the combination the wire permits and `DriverError` does not. One shape
crosses both seams; only the constructor's obligations differ, and they differ because the
producer does.

## The three deadlines, and the shortfall a watchdog thread cannot cover

04-driver-system.md:1733-1735: "Three deadlines exist, they are separate and they are separately
named: `progress_ms` (a silent driver), `wall_ms_hard` (a chatty one) and `deadline_ms` on the
invocation (the caller's). **`PROGRESS` is the only frame that resets `progress_ms`.** A `LOG`
frame does not, and that is a deliberate correction of the obvious design." In process there are
no frames, so the same rule reads: `DriverIO.progress()` resets it and `DriverIO.log()` does not.

**What this cannot do is stop a driver that does not cooperate, and that is stated rather than
papered over.** In a worker, `progress_ms` ends in SIGTERM then SIGKILL of the whole process
group (04-driver-system.md:1728). In process there is no process to kill but the run's own, and
04-driver-system.md:1826 already names the asymmetry -- "what it cannot supply is crash
containment". So the watchdog thread does the two things a thread can do: it flips
`DriverIO.cancelled()`, which the driver is obliged to check "at every loop top" (:1738), and it
records which deadline fired. A driver that ignores `cancelled()` runs to completion and its
result is then DISCARDED in favour of `FAILED_PERMANENT{TIMEOUT}` -- so the deadline is honest
about the ledger even when it cannot be honest about the CPU. The breach is evaluated once more
after the call returns, which is what makes that true when the thread never got scheduled at all,
and is what makes the whole mechanism testable against a supplied clock rather than against a
sleep.

**On Windows this is the same code and the same shortfall.** Nothing here is per-OS: the
watchdog is a `threading.Event` wait, not a signal, an `RLIMIT` or a job object, and
04-driver-system.md:1748-1756's per-OS table applies to the SUBPROC watchdog. The one platform
fact worth writing down is that Windows offers no CPU cap at all (:1752, "not available;
`wall_ms_hard` only`"), so on Windows `wall_ms_hard` is the only backstop for a compute-bound
driver in either isolation mode -- and in process, as above, it is a backstop that reports rather
than one that stops. `os._exit` is deliberately NOT used here: 04-driver-system.md:1772 puts it
in the SUBPROC watchdog's timer fallback, where the process it ends is the worker's; ending the
supervisor from S1's guard would turn a slow driver into a lost run.

## `DriverIO` gains no field, and could not

`omniweave_ports.types.DriverIO` is INV-6's audited surface: "NOT EXTENSIBLE: adding a field here
amends the charter, whose audit question is literally 'count `DriverIO`'s fields'. It has four."
`GuardIO` therefore subclasses it with `__slots__ = ()` and keeps every piece of per-call state
in a module-level `WeakKeyDictionary` keyed on the io -- the idiom `omniweave_ports.types` itself
uses for `_OUTPUT_METER` and `_HEAD_CACHE`, and the reason `DriverIO` carries
`weakref_slot=True`. `dataclasses.fields(GuardIO)` still answers four.

Stdlib only (INV-2), no `asyncio` and no `selectors` (G23 -- a watchdog is a thread and an event,
not a loop), no `subprocess` (this is the seam that does not spawn), no wall clock and no RNG:
`monotonic_ns` is a parameter defaulting to `time.monotonic_ns`, the idiom
`omniweave_core.blobs:405` sets.

Specified in 04-driver-system.md section 6.7 (:1822-1832), section 6.1 (:1632-1655) and section
6.3 (:1723-1741), 02-architecture.md section 7.5's S1 row (:1061) and section 5.6's S1 row
(:828), 15-observability.md:193 and glossary.md:598.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple, TypeAlias

from omniweave_ports.types import (
    BlobStore,
    DriverError,
    DriverIO,
    DriverResult,
    FailureClass,
    Isolation,
    Scalar,
    ServiceHandle,
)

from omniweave_core.drivers.card import DriverCard, IsolationSpec
from omniweave_core.drivers.resolve import Candidate, RejectCode
from omniweave_core.errors import CapabilityMissing, DriverHostError

__all__ = [
    "NO_SERVICES",
    "DeadlineLimit",
    "Deadlines",
    "DriverGuard",
    "GuardFailure",
    "GuardIO",
    "GuardOutcome",
    "LogSink",
]

LogSink: TypeAlias = Callable[[str, Mapping[str, Scalar]], None]
"""What `DriverIO.log()` hands its record to. `(event, fields) -> None`.

A sink and not an accumulator: the `Event` vocabulary and the `TraceSink` that consumes it are
15-observability.md's property (02-architecture.md section 2 row 21), and a guard that invented
its own log buffer would be a second home for a run's events. 15-observability.md:193 gives S1's
traceparent propagation as "the `DriverGuard` sets it on the call frame", which is the same
division: the guard is where the record is made, not where it is kept.
"""

NO_SERVICES: Final[Mapping[str, ServiceHandle]] = MappingProxyType({})
"""The default `services` map: empty, so `DriverIO.service()` refuses by naming what is missing.

A module singleton rather than a call in a dataclass default, the precedent
`omniweave_core.drivers.resolve`'s `_NO_ACKS` sets. `omniweave_core.modelserver` -- the
attach-or-spawn ladder of 08-runtime.md section 3.2 -- lands at P4 W4.9 (16-roadmap.md:549) and
does not exist, so at P3 every S1 invocation passes this and a driver naming a Service gets
`CapabilityMissing` with the Service named, rather than an `AttributeError` from a half-built
host.
"""


class DeadlineLimit(StrEnum):
    """The three deadlines, "separate and separately named" (04-driver-system.md:1733).

    The VALUES are the strings the failure carries: 04-driver-system.md:1728-1729 prints
    `FAILED_PERMANENT{TIMEOUT}`, `limit = "progress_ms"` and `limit = "wall_ms_hard"`, and
    `DriverError.limit` / `GuardFailure.limit` is "the knob that would need raising"
    (`omniweave_ports.types`'s `DriverError`). `deadline_ms` is the third, "on the invocation
    (the caller's)".
    """

    PROGRESS_MS = "progress_ms"
    WALL_MS_HARD = "wall_ms_hard"
    DEADLINE_MS = "deadline_ms"


class Deadlines(NamedTuple):
    """The three, in milliseconds. **Zero means UNSET, not zero.**

    `omniweave_core.drivers.card.IsolationSpec` defaults `progress_ms` and `wall_ms_hard` to `0`
    for an absent key, so a card that declares neither would, read naively, breach both deadlines
    before the driver's first statement. An absent deadline is not an expired one; `of_card()`
    carries the card's values through unchanged and `enabled()` is what reads a `0` as "no
    bound". A test asserts a card declaring nothing runs to completion, because this is the one
    error in this file that would look like a working timeout.
    """

    progress_ms: int = 0
    wall_ms_hard: int = 0
    deadline_ms: int = 0

    @classmethod
    def of_card(cls, isolation: IsolationSpec, *, deadline_ms: int = 0) -> Deadlines:
        """Two from `[isolation]`, one from the invocation.

        `deadline_ms` is not on the card at all -- it is "on the invocation (the caller's)"
        (04-driver-system.md:1734) and is what `DriverIO.deadline_ms` carries to the driver.
        """
        return cls(
            progress_ms=isolation.progress_ms,
            wall_ms_hard=isolation.wall_ms_hard,
            deadline_ms=deadline_ms,
        )

    def enabled(self) -> tuple[DeadlineLimit, ...]:
        """The limits with a positive bound, in the precedence order `_breach()` applies."""
        pairs = (
            (DeadlineLimit.PROGRESS_MS, self.progress_ms),
            (DeadlineLimit.WALL_MS_HARD, self.wall_ms_hard),
            (DeadlineLimit.DEADLINE_MS, self.deadline_ms),
        )
        return tuple(limit for limit, value in pairs if value > 0)


@dataclass(frozen=True, slots=True)
class GuardFailure:
    """A host-side failure, carrying the five fields that cross S4 (02-architecture.md:1060).

    NOT a `DriverError`: see the module docstring's attribution section. `of_driver_error()` is
    the pass-through for a failure the driver did report, so a driver-raised `TIMEOUT` keeps its
    `retry_after_ms` and a host-detected one has none.
    """

    failure_class: FailureClass
    message: str
    retry_after_ms: int | None = None
    pages: tuple[int, ...] = ()
    limit: str | None = None

    @classmethod
    def of_driver_error(cls, exc: DriverError) -> GuardFailure:
        """The driver's own five fields, unchanged. The guard never rewrites an attribution."""
        return cls(
            failure_class=exc.cls,
            message=exc.message,
            retry_after_ms=exc.retry_after_ms,
            pages=exc.pages,
            limit=exc.limit,
        )


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    """Exactly one of `result` and `failure`, plus what the guard observed while it ran.

    `cancelled` records that the invocation was superseded, and it is NOT a failure: a driver
    that noticed `io.cancelled()` and returned early returned a real result, and whether that
    result commits is the runtime's `WHERE id=:id AND claimed_gen=:gen AND status='claimed'`
    predicate to decide -- "a superseded result **writes nothing**" (04-driver-system.md:1740).
    `DriverResult` cannot claim `cancelled` (INV-7), which is exactly why the flag rides here and
    not there.
    """

    result: DriverResult | None = None
    failure: GuardFailure | None = None
    cancelled: bool = False
    logs: int = 0
    progress_calls: int = 0
    last_progress: tuple[int, int | None] | None = None
    """`(done, total)` from the last `DriverIO.progress()` call, which is the `PROGRESS` frame's
    own payload minus the two identities a driver never mints (04-driver-system.md:1702). It is
    carried because in process there is no frame to carry it: without this the host can see THAT
    the driver reported progress and not WHERE it had got to."""

    def __post_init__(self) -> None:
        """One of the two, never both and never neither -- the discipline `DriverError`'s and
        `DriverResult`'s own `__post_init__`s apply to their invariants."""
        if (self.result is None) == (self.failure is None):
            raise ValueError("a GuardOutcome carries exactly one of result and failure")


@dataclass(slots=True)
class _CallState:
    """Per-invocation mutable state, held OFF the `DriverIO` so INV-6's field count stays four.

    `lock` guards the three fields the watchdog thread writes and the driver's thread reads.
    """

    monotonic_ns: Callable[[], int]
    deadlines: Deadlines
    log_sink: LogSink | None
    services: Mapping[str, ServiceHandle]
    started_ns: int
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_progress_ns: int = 0
    last_progress: tuple[int, int | None] | None = None
    cancelled: bool = False
    limit: DeadlineLimit | None = None
    closed: bool = False
    logs: int = 0
    progress_calls: int = 0


_STATE: weakref.WeakKeyDictionary[DriverIO, _CallState] = weakref.WeakKeyDictionary()
"""io -> its invocation's state. Weak, so a finished invocation's state dies with its `DriverIO`.

The same idiom, and for the same reason, as `omniweave_ports.types`'s `_OUTPUT_METER`: `DriverIO`
is a frozen slotted dataclass whose field count is audited, so state that belongs to a call and
not to the value has to live beside it rather than in it.
"""

_MS: Final[int] = 1_000_000
"""Nanoseconds per millisecond. Every deadline on the wire and on a card is in milliseconds and
every clock reading here is `monotonic_ns`, so the conversion happens once, named."""

_MIN_WAIT_S: Final[float] = 0.001
"""The watchdog's floor between wakes. A deadline already past yields a non-positive wait, and
`Event.wait(0)` in a loop is a busy spin; 1 ms is the resolution the deadlines are stated in."""

_RUNTIME_FIX: Final[str] = "ow doctor --runtime --render json   # attach the report to the issue"
"""The `fix` on every `DriverHostError` raised here. `ow doctor --runtime` is the verb
04-driver-system.md:1777 gives for the runtime's own health, and an `OwError` with no fix is
refused by its own constructor."""


def _state_of(io: DriverIO, method: str) -> _CallState:
    """The state behind an io, refusing an io whose invocation is over.

    A driver that stashes its `DriverIO` and calls it later is 04-driver-system.md section 6.5's
    family of hostile shapes -- not listed there, because in a worker the process is gone. In
    process it is not, so the refusal is explicit: writing into a finished invocation's ledger
    would attribute one unit's bytes and logs to another.
    """
    state = _STATE.get(io)
    if state is None or state.closed:
        raise DriverHostError(
            f"{method}(): this DriverIO's invocation is over; a DriverIO is valid for exactly "
            f"the call it was supplied to (INV-6)",
            fix=_RUNTIME_FIX,
        )
    return state


class GuardIO(DriverIO):
    """The concrete `DriverIO` an `inproc` driver is handed. FOUR FIELDS, all inherited.

    `omniweave_ports.types.DriverIO` prints the four methods' bodies as
    `raise NotImplementedError(... omniweave_core.host provides DriverIO)`; this is that
    provision for S1. `__slots__ = ()` adds no storage, so `dataclasses.fields()` still answers
    INV-6's audit question with four.
    """

    __slots__ = ()

    def service(self, name: str) -> ServiceHandle:
        """A HOST-managed Service by name, or `CapabilityMissing` naming it.

        The attach-or-spawn ladder is 08-runtime.md section 3.2's and `omniweave_core.modelserver`
        lands at P4 W4.9, so the guard hands out handles a caller supplied and never builds one.
        `CapabilityMissing` is the `DriverHostError` leaf whose `.missing` is machine-actionable
        (`omniweave_core.errors`; exit 64).
        """
        state = _state_of(self, "service")
        handle = state.services.get(name)
        if handle is None:
            raise CapabilityMissing(
                f"service({name!r}): no such Service is attached to this invocation",
                missing=(f"service:{name}",),
                fix=f"ow config set services.{name}.model_id <id>   # then ow doctor --runtime",
            )
        return handle

    def cancelled(self) -> bool:
        """True once a deadline fired or the runtime cancelled. Checked at every loop top.

        A closed invocation answers `True` rather than raising, and that asymmetry with the other
        three methods is deliberate: this is the one method a driver is obliged to call in its
        own hot loop (04-driver-system.md:1738), and telling a stale loop to stop is strictly
        safer than raising into it.
        """
        state = _STATE.get(self)
        if state is None:
            return True
        with state.lock:
            return state.cancelled or state.closed

    def log(self, event: str, **fields: Scalar) -> None:
        """One structured record. **Does NOT reset `progress_ms`** (04-driver-system.md:1735).

        "A driver logging in a tight loop while making no progress would otherwise look alive
        forever, which is the failure `progress_ms` exists to catch." Sole in-process equivalent
        of the `LOG` frame, and the only frame-shaped thing here that is not a frame.
        """
        state = _state_of(self, "log")
        with state.lock:
            state.logs += 1
        if state.log_sink is not None:
            state.log_sink(event, MappingProxyType(dict(fields)))

    def progress(self, done: int, total: int | None) -> None:
        """Reset `progress_ms`. The ONLY thing that does (04-driver-system.md:1735).

        `wall_ms_hard` is untouched and is the backstop, so "a driver cannot extend its own wall
        clock" (04-driver-system.md:1794) in process either.
        """
        state = _state_of(self, "progress")
        now = state.monotonic_ns()
        with state.lock:
            state.last_progress_ns = now
            state.last_progress = (done, total)
            state.progress_calls += 1


class DriverGuard:
    """The S1 call boundary: clearance in, one `GuardOutcome` out, nothing raised into the loop.

    Construction is where clearance is checked, so a `DriverGuard` that exists is one
    `resolve()` cleared for `inproc`. See the module docstring for what this class deliberately
    does not decide.
    """

    __slots__ = ("_candidate", "_deadlines", "_monotonic_ns")

    def __init__(
        self,
        candidate: Candidate,
        *,
        deadlines: Deadlines,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        """Refuse anything `resolve()` did not clear for `inproc`, before any driver can run.

        `type(...) is Candidate` and not `isinstance`: a subclass or a look-alike would be a way
        to forge clearance, and clearance is the one thing worth forging here.
        """
        if type(candidate) is not Candidate:
            raise DriverHostError(
                f"DriverGuard takes a resolve() Candidate; got "
                f"{type(candidate).__name__}. Clearance for inproc is "
                f"Candidate.isolation_granted and cannot be asserted by the caller "
                f"(04-driver-system.md:1381-1387, DR10)",
                fix=_RUNTIME_FIX,
            )
        if candidate.isolation_granted is not Isolation.INPROC:
            raise DriverHostError(
                f"{candidate.driver_id} was granted "
                f"{candidate.isolation_granted.value!r} and not 'inproc'; S1 runs only what "
                f"resolve() granted, and DR9's conjuncts are not re-decided here "
                f"(04-driver-system.md:1636-1648)",
                fix=_RUNTIME_FIX,
            )
        self._candidate = candidate
        self._deadlines = deadlines
        self._monotonic_ns = monotonic_ns

    @property
    def card(self) -> DriverCard:
        return self._candidate.card

    @property
    def driver_id(self) -> str:
        return self._candidate.driver_id

    @property
    def deadlines(self) -> Deadlines:
        return self._deadlines

    def check_code(self, loaded: type[object]) -> None:
        """The in-process half of `activate()`'s step 4 (04-driver-system.md:1543-1546).

        `PORT` and `SCHEMA_VERSION` on the loaded class against the card's `port` and
        `schema_version`; a mismatch is `OW_CARD_CODE_MISMATCH`, "refused BEFORE any work"
        (`codes.toml` `OW-D-073`). The other half is the worker's `HELLO_ACK` and an `inproc`
        driver has none, which is why the plan checks step 4 twice.

        Imports nothing: the class is the caller's. Resolving `card.entrypoint` is `activate()`'s
        and `activate()` does not exist in the tree yet.
        """
        identity = self._candidate.card.identity
        wanted = (f"{identity.port.value}/{identity.port_major}", identity.schema_version)
        got = (getattr(loaded, "PORT", None), getattr(loaded, "SCHEMA_VERSION", None))
        if got != wanted:
            raise DriverHostError(
                f"{self.driver_id}: the loaded class declares PORT={got[0]!r} "
                f"SCHEMA_VERSION={got[1]!r} and the card says {wanted[0]!r} / {wanted[1]!r}",
                symbol=RejectCode.CARD_CODE_MISMATCH.symbol,
                fix=f"ow drivers verify {self.driver_id}",
            )

    def invoke(
        self,
        work: Callable[[DriverIO], DriverResult],
        *,
        blobs: BlobStore,
        tmpdir: str,
        max_output_bytes: int,
        services: Mapping[str, ServiceHandle] = NO_SERVICES,
        log_sink: LogSink | None = None,
    ) -> GuardOutcome:
        """Run `work` under the guard. Never raises out of the driver's failure.

        The guard builds the `DriverIO` itself rather than accepting one, because a caller-built
        io would be an io the guard does not control and INV-6's four fields include the output
        ceiling `ArtifactRef.of` meters against.

        `BaseException` is caught, per 02-architecture.md:1061, and that includes
        `KeyboardInterrupt` and `SystemExit` raised inside the driver's own frame. Both are the
        driver's doing there: `sys.exit` is banned in library code framework-wide, and
        cancellation "propagates **by generation, not by signal**" (04-driver-system.md:1739), so
        neither is a signal the supervisor sent. Letting either escape would be the one thing
        S1's row forbids -- "nothing propagates into the loop".
        """
        io = GuardIO(
            blobs=blobs,
            tmpdir=tmpdir,
            deadline_ms=self._deadlines.deadline_ms,
            max_output_bytes=max_output_bytes,
        )
        started = self._monotonic_ns()
        state = _CallState(
            monotonic_ns=self._monotonic_ns,
            deadlines=self._deadlines,
            log_sink=log_sink,
            services=services,
            started_ns=started,
            last_progress_ns=started,
        )
        _STATE[io] = state
        stop = threading.Event()
        watchdog = self._start_watchdog(state, stop)
        try:
            outcome = self._run(work, io, state)
        finally:
            stop.set()
            if watchdog is not None:
                watchdog.join()
            with state.lock:
                state.closed = True
        return outcome

    def cancel(self, io: DriverIO) -> None:
        """Supersede a running invocation. The runtime's half of cancellation, by generation.

        No `limit` is set: this is not a deadline breach, so a driver that notices and returns
        early still returns a result and `GuardOutcome.cancelled` is what tells the runtime the
        generation moved (04-driver-system.md:1740).
        """
        state = _STATE.get(io)
        if state is None:
            return
        with state.lock:
            state.cancelled = True

    def _run(
        self,
        work: Callable[[DriverIO], DriverResult],
        io: GuardIO,
        state: _CallState,
    ) -> GuardOutcome:
        """The catch, the conversion, and the post-call deadline evaluation."""
        failure: GuardFailure | None = None
        result: DriverResult | None = None
        try:
            result = work(io)
        except DriverError as exc:
            failure = GuardFailure.of_driver_error(exc)
        except BaseException as exc:
            failure = GuardFailure(
                failure_class=FailureClass.DRIVER_BUG,
                message=f"{type(exc).__name__}: {exc}",
            )
        breach = self._breach(state)
        with state.lock:
            cancelled = state.cancelled
            logs = state.logs
            progress_calls = state.progress_calls
            last_progress = state.last_progress
        if breach is not None:
            failure = GuardFailure(
                failure_class=FailureClass.TIMEOUT,
                message=f"{self.driver_id}: {breach.value} elapsed with the call still running",
                limit=breach.value,
            )
            result = None
        return GuardOutcome(
            result=None if failure is not None else result,
            failure=failure,
            cancelled=cancelled,
            logs=logs,
            progress_calls=progress_calls,
            last_progress=last_progress,
        )

    def _start_watchdog(self, state: _CallState, stop: threading.Event) -> threading.Thread | None:
        """A thread per invocation, and none at all when no deadline is declared.

        `daemon=True` so a wedged driver cannot keep the interpreter alive at exit, and `join()`
        in `invoke()`'s `finally` so a finished invocation has no thread still holding its state.
        """
        if not self._deadlines.enabled():
            return None
        thread = threading.Thread(
            target=self._watch,
            args=(state, stop),
            name=f"ow-inproc-watchdog-{self.driver_id}",
            daemon=True,
        )
        thread.start()
        return thread

    def _watch(self, state: _CallState, stop: threading.Event) -> None:
        """Wake at the next deadline, flip `cancelled()` on a breach, and stop.

        It cannot preempt the driver; see the module docstring. What it can do is make
        `io.cancelled()` true as early as the deadline, which is the whole of what a cooperative
        driver needs.
        """
        while not stop.wait(self._next_wait_s(state)):
            breach = self._breach(state)
            if breach is None:
                continue
            with state.lock:
                state.limit = breach
                state.cancelled = True
            return

    def _next_wait_s(self, state: _CallState) -> float:
        """Seconds until the earliest enabled deadline, floored at `_MIN_WAIT_S`."""
        now = state.monotonic_ns()
        with state.lock:
            last_progress = state.last_progress_ns
        remaining_ns = [
            deadline * _MS - (now - origin)
            for deadline, origin in (
                (self._deadlines.progress_ms, last_progress),
                (self._deadlines.wall_ms_hard, state.started_ns),
                (self._deadlines.deadline_ms, state.started_ns),
            )
            if deadline > 0
        ]
        return max(min(remaining_ns) / 1e9, _MIN_WAIT_S)

    def _breach(self, state: _CallState) -> DeadlineLimit | None:
        """Which deadline has elapsed, or `None`. Pure over the clock, so it is testable.

        **The precedence order is ours and is pinned by a test, not by the plan.**
        04-driver-system.md:1728-1729 lists the silent hang before the chatty one and gives each
        its own `limit` string, but says nothing about a wake at which two have already elapsed.
        `progress_ms` wins because it is the more specific diagnosis -- a driver that has made no
        progress has told us what is wrong with it, where `wall_ms_hard` only says the call was
        long -- and `deadline_ms` is last because the caller's deadline is a fact about the
        request rather than about the driver.
        """
        now = state.monotonic_ns()
        with state.lock:
            if state.limit is not None:
                return state.limit
            last_progress = state.last_progress_ns
        elapsed = now - state.started_ns
        checks = (
            (DeadlineLimit.PROGRESS_MS, self._deadlines.progress_ms, now - last_progress),
            (DeadlineLimit.WALL_MS_HARD, self._deadlines.wall_ms_hard, elapsed),
            (DeadlineLimit.DEADLINE_MS, self._deadlines.deadline_ms, elapsed),
        )
        for limit, bound, spent in checks:
            if bound > 0 and spent >= bound * _MS:
                return limit
        return None
