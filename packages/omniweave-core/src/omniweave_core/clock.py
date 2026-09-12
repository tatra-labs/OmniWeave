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

**No implementation ships in this file yet, and that is deliberate rather than unfinished.** A
`SystemClock` reading `time.monotonic_ns()` is one of W4.9's three seams and it arrives with the
stale-lock test that gives it meaning. What the framework needs *today* is the type an injection
site can name; a test writes two lines to satisfy it, which is the property the Protocol exists to
buy. `@runtime_checkable` so that a seam can assert what it was handed rather than trusting it.

Stdlib only, and in fact no imports beyond `typing` (INV-2, G1). Not one of the nine LAZY names:
this is a Protocol and importing it costs nothing.

Tier T-CONTRACT: 02-architecture.md section 2 row 23.

Specified in 02-architecture.md section 2 row 23 and 08-runtime.md sections 1.3 and 8 (:280, :295,
:359, :398, :406, :2816).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Clock"]


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
