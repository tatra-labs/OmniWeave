"""The injected `Clock`: `monotonic_ns()` and `wall_ns()`, and never an ambient one.

02-architecture.md section 2 row 23 is this module's charter, and the exclusion is the whole point:

> | 23 | Locks, clock | `omniweave_core.locks`, `.clock` | the scoped cross-process lock
> (`O_CREAT|O_EXCL` + `flock`, holder identity `(host, pid, process_create_time)`); the injected
> `Clock` protocol | **ambient time** -- `time.time()` is banned in library code; a lease is stamped
> from **the store's** clock (`unixepoch('subsec')*1000 + :lease_ms`), never a worker's |

08-runtime.md:2816 gives the shape in one line -- *"`monotonic_ns()` plus `wall_ns()`, **injected**
on `RunContext`, never ambient. What makes the debounce and generation invariants testable without
an operating system"* -- and 08:295 names the third ban of the three `RunContext` carries: *"**No
ambient clock**: `Clock` is injected, which is what makes the debounce and generation invariants
testable without an operating system."*

**Why this module exists one cell early.** 16-roadmap.md:549 schedules `clock.py` as P4 W4.9,
beside `modelserver.py` and `locks.py`. The Protocol lands here with W4.1's successor instead,
because `CancelToken` cannot be *typed* without it: 08:359 gives the token a `_clock: "Clock"` slot
and 08:406 makes the reason normative -- a token *"that took a lock, read the store, or called
`time.monotonic()` through anything but the injected `Clock` would be the cheapest available way to
trip the very monitor that is supposed to be watching the work"*. A forward reference cannot be
called, so the alternative was a second declaration inside `operator.py`, which is the home this
row already names. W4.9 lands the rest -- the concrete clocks, `locks.py` and `modelserver.py` --
and finds the Protocol already here.

`SystemClock` below is the implementation W4.9 owed, and it is the one place in the framework where
the machine's clock is read. A test still writes two lines to satisfy the Protocol, which is the
property the Protocol exists to buy; `@runtime_checkable` so that a seam can assert what it was
handed rather than trusting it.

## The per-OS ladder, and the ban that cannot be followed literally (D154)

`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans `time.time`,
`time.time_ns`, `time.perf_counter`, `time.perf_counter_ns`, `time.process_time` and
`time.process_time_ns` in `packages/*/src/**`, and its message prescribes the replacement:
*"the clock is injected -- `ctx.clock.wall_ns()` for a wall reading, **`time.monotonic_ns()` for a
duration**"*.

**`time.monotonic()` on Windows is `GetTickCount64`, whose resolution is 15.6 ms.** Measured:
`time.get_clock_info("monotonic").resolution == 0.015625` against `perf_counter`'s `1e-07`. So the
duration `15-observability.md:434` asks the manifest for -- `observe.serialise_ns_total`, the
serialiser's own overhead, *"a number that cannot be subtracted contaminates every measurement
beside it"* -- rounds to **zero** on six of `11-repo-layout.md §6.2`'s nine test-matrix cells, and a
zero reads as *free* rather than as *unmeasured*.

`SystemClock` therefore chooses, **once at construction**, between `time.monotonic_ns()` and
`time.perf_counter_ns()`, and records which. Two rules keep the substitution honest:

1. **It only substitutes a clock the interpreter itself calls monotonic.** `time.get_clock_info`
   reports it; a `perf_counter` that is not monotonic on some platform is not taken, and the coarse
   reading is kept with the shortfall recorded. Resolution is never bought with monotonicity,
   because `Cancellation.at_mono_ns` is measured from this and 08:377 is explicit that a backward
   step *"must not turn a 5 s grace into an hour or a no-op"*.
2. **The shortfall is recorded rather than claimed.** `ClockFacts` carries the source, both
   resolutions and whether the reading is still coarser than a microsecond, so a manifest can say
   `serialise_ns_total` was unmeasurable instead of reporting `0`.

This file carries a **scoped** G8 exemption for exactly those two calls, in `tools/egress.toml`'s
style and for `toolchain.py`'s reason: one module is entitled to read the machine, and every other
module injects. `time.time()` stays banned here too -- `wall_ns()` is `time.time_ns()`.

Stdlib plus `time` (INV-2, G1). Not one of the nine LAZY names: this is a Protocol plus a small
class and importing it costs nothing.

Tier T-CONTRACT: 02-architecture.md section 2 row 23.

Specified in 02-architecture.md section 2 row 23 and 08-runtime.md sections 1.3 and 8 (:280, :295,
:359, :398, :406, :2816); the ladder is `_plan/_notes/build-defects.md` D154.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

__all__ = [
    "MICROSECOND_NS",
    "MONOTONIC_MAX_RESOLUTION_NS",
    "Clock",
    "ClockFacts",
    "SystemClock",
    "clock_facts",
]


@runtime_checkable
class Clock(Protocol):
    """Two readings, two jobs, and they are never interchangeable.

    `monotonic_ns()` is the only source for a **duration**: every elapsed measurement in the
    framework is a difference of two of its readings. 08:377 says why in the one place it costs
    most -- `Cancellation.at_mono_ns` is *"NEVER a wall clock: `[runtime] shutdown_grace_ms` is
    measured from here, and a backward NTP step must not turn a 5 s grace into an hour or a
    no-op"*. 15-observability.md's `Event` carries both for the same reason and states the rule:
    *"every duration is computed from `ts_mono_ns`"*.

    `wall_ns()` is for correlation with things outside this process -- an operator's log, an
    upstream request id, a `run_id`'s mint time -- and for nothing else. `new_run_id()` in
    `omniweave_core.operator` is its one caller in core.

    Neither is `time.time()`. The ban is on **ambient** time rather than on the standard library:
    a `Clock` implementation is where `time.monotonic_ns()` is called, exactly once, behind a name
    a test can replace.
    """

    def monotonic_ns(self) -> int:
        """A monotone nanosecond counter with an arbitrary origin. Durations only."""
        ...

    def wall_ns(self) -> int:
        """Nanoseconds since the Unix epoch. Correlation only -- never a duration."""
        ...


# --------------------------------------------------------------------------------------------
# 2. What this machine's clocks can actually measure. D154.
# --------------------------------------------------------------------------------------------

MICROSECOND_NS: Final = 1_000
"""One microsecond. The scale `observe.serialise_ns_total` is reported at (15-observability:434)."""

MONOTONIC_MAX_RESOLUTION_NS: Final = 1_000_000
"""One millisecond: past this, `monotonic_ns()` cannot time anything this framework measures.

Not a tuned number and not a ceiling in `limits.py`'s sense (INV-22 -- *"a ceiling is never a target
and never a setting"*). It is the boundary between the two readings' competences: every duration in
the manifest below a millisecond -- a serialise, a cache probe, a single `Statement` -- is
unmeasurable by a clock whose tick is longer than it, and every duration above one is measurable by
either. Windows' 15.6 ms `GetTickCount64` is on the wrong side of it by a factor of sixteen; Linux's
and macOS' `clock_gettime(CLOCK_MONOTONIC)` at 1 ns are on the right side by six orders of
magnitude. No platform in the support matrix sits near the line, which is what makes a single
threshold honest rather than arbitrary.
"""

_SOURCES: Final = ("monotonic_ns", "perf_counter_ns")
"""The two calls `SystemClock` chooses between, in preference order."""


@dataclass(frozen=True, slots=True)
class ClockFacts:
    """Which duration call this platform got, what it can resolve, and what it cannot.

    **The shortfall is recorded, never claimed.** That is D154's requirement and it is the reason
    this type exists at all rather than the choice being a private branch: `15-observability.md:434`
    asks the manifest for the serialiser's own overhead so a reader can subtract it, and a `0` from
    an unmeasurable clock is worse than an absence, because it reads as *free*. A manifest that
    carries `coarse = True` can print `unmeasured` instead.

    `monotonic_resolution_ns` is kept beside `resolution_ns` even when they are equal, so an
    operator reading a report can see what was rejected as well as what was chosen.
    """

    source: Literal["monotonic_ns", "perf_counter_ns"]
    resolution_ns: int
    monotonic_resolution_ns: int
    perf_counter_monotonic: bool

    @property
    def coarse(self) -> bool:
        """Whether the chosen reading still cannot resolve a microsecond."""
        return self.resolution_ns > MICROSECOND_NS

    @property
    def substituted(self) -> bool:
        """Whether the ban's prescribed `time.monotonic_ns()` was passed over."""
        return self.source != "monotonic_ns"


def clock_facts() -> ClockFacts:
    """Ask the interpreter what its two duration clocks can do, and pick one. D154's ladder.

    `time.get_clock_info` is the standard library reporting on itself, which is the only source that
    is right on every platform without a table this module would have to maintain. It is read once
    per `SystemClock` and never per reading.

    **`perf_counter_ns` is taken only when the interpreter calls it monotonic.** `info.monotonic` is
    the flag, and the alternative -- substituting on resolution alone -- would trade the property
    `Cancellation.at_mono_ns` depends on for digits it does not need. 08:377: *"a backward NTP step
    must not turn a 5 s grace into an hour or a no-op."* Where `perf_counter` is not monotonic the
    coarse reading is kept and `ClockFacts.coarse` says so.
    """
    monotonic = time.get_clock_info("monotonic")
    perf = time.get_clock_info("perf_counter")
    monotonic_ns = round(monotonic.resolution * 1e9)
    perf_ns = round(perf.resolution * 1e9)
    substitute = (
        monotonic_ns > MONOTONIC_MAX_RESOLUTION_NS and perf.monotonic and perf_ns < monotonic_ns
    )
    return ClockFacts(
        source="perf_counter_ns" if substitute else "monotonic_ns",
        resolution_ns=perf_ns if substitute else monotonic_ns,
        monotonic_resolution_ns=monotonic_ns,
        perf_counter_monotonic=perf.monotonic,
    )


# --------------------------------------------------------------------------------------------
# 3. The one place the machine's clock is read.
# --------------------------------------------------------------------------------------------


class SystemClock:
    """The shipped `Clock`. Two calls, chosen once, and nothing else in this framework reads time.

    **The name is this cell's.** No plan document prints one: 02 row 23 names the module and the
    Protocol, 08:280 names the field on `RunContext`, and neither names a class. `SystemClock` says
    what distinguishes it from every other `Clock` an injection site will see -- it reads the system
    -- which is the only distinction that matters at a call site choosing between them.

    **The source is resolved at construction, not per reading.** `time.get_clock_info` is not free
    and a clock is read in the hot path of every span; more importantly, a clock that re-decided per
    call could return two readings from two different origins in one duration, and the difference of
    those is meaningless. One decision, recorded in `facts`, for the life of the object.

    `__slots__` and no state beyond the bound callable: a `Clock` is passed to every operator, and
    an attribute someone could set would be ambient time wearing an injection's clothes.
    """

    __slots__ = ("_facts", "_monotonic")

    def __init__(self, facts: ClockFacts | None = None) -> None:
        self._facts = clock_facts() if facts is None else facts
        self._monotonic = (
            time.perf_counter_ns if self._facts.source == "perf_counter_ns" else time.monotonic_ns
        )

    @property
    def facts(self) -> ClockFacts:
        """What this clock can resolve, for a manifest to report rather than to hide."""
        return self._facts

    def monotonic_ns(self) -> int:
        """A monotone nanosecond counter with an arbitrary origin. Durations only."""
        return self._monotonic()

    def wall_ns(self) -> int:
        """Nanoseconds since the Unix epoch. Correlation only -- never a duration.

        `time.time_ns()`, which the G8 ban names and this module is exempted from for the reason the
        ban itself gives: *"the clock is injected"*. This is the injection. Everything downstream
        takes a `Clock`, so there is exactly one call site to audit and it is this line.
        """
        return time.time_ns()
