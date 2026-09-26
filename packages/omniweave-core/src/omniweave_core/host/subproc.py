"""Seam S4: one long-lived driver worker per `(driver_id, config_digest)`, and the reader that
does not oblige it.

**W3.2, second half** (16-roadmap.md:482). 02-architecture.md:428 and :831 compress the whole
lifecycle into two table cells and every clause in them is a mechanism here: the wire caps, one
worker per `(driver_id, config_digest)`, `max_workers` per cost class, `worker_idle_ttl_s`, AIMD
halving on OOM *and its recovery*, a worker that dies without a frame yielding `driver_crashed`
synthesised from the exit status plus the tail of a stderr ring, the single retry at `batch = 1`
to localise the poison unit, and the crash accounting that quarantines the DRIVER for the run.
04-driver-system.md section 6.2 owns the grammar, section 6.3 the five failure modes, section 6.4
the per-OS watchdog and section 6.5 the hostile driver.

## What this module is for, in one sentence that is not ours

14-security.md:538-540: *"What `subproc` actually buys is that the host's availability is
independent of the driver's behaviour: a segfault, a leak, a hang, a frame flood and a 4 GB
`header_len` are each one row instead of a lost run. That is a different and achievable property
from 'the driver cannot hurt you'."* 04-driver-system.md:1802 says the same from the other side:
*"None of that makes `subproc` a security boundary; it makes the host's availability independent
of the driver's behaviour."* Everything below is written to that standard and to no higher one --
04-driver-system.md section 6.6 is the security statement and this module cannot improve on it.

## Why `subprocess` is legal here, and the discipline that comes with it

`tools/semgrep/omniweave.yaml`'s `omniweave-no-subprocess-outside-toolchain-and-host-subproc`
excludes exactly two paths and this file is one of them (02-architecture.md:392, :432; the same
two-home rule is `pyproject.toml`'s `banned-api` message, which is the independent second
enforcer). The rule's own message says what the ban is *for*, and it is not "child processes are
scary": *"no toolchain digest is checked, no `cwd=` is passed -- graphify #2316 ran
`git rev-parse HEAD` without `cwd=` and stamped the invoking repo's commit into the target's
graph -- and the spawn appears in no ledger row."* So `SpawnRequest` makes `cwd` a REQUIRED field
with no default, `env` an explicit mapping rather than an inherited environment, and `argv` a
tuple that is never a string (`shell=False` is not negotiable: 04-driver-system.md:1098 requires
it for `[driver] exec`). A spawn this module cannot describe is a spawn it refuses to make.

## The seven mechanisms, each of which is a test

1. **The worker key is `(driver_id, config_digest)` and that is a CORRECTNESS property.**
   02-architecture.md:85, :482 and :677. Two configurations sharing a worker means one
   configuration's work is done under the other's settings, which is a wrong answer and not a
   slow one. `WorkerKey` is therefore the pool's only key and `config_digest` is
   `omniweave_core.identity.config_digest`'s (02-architecture.md section 8.3), never re-derived
   here.
2. **Three deadlines exist, they are separate, and they are separately named**
   (04-driver-system.md:1733-1735): `progress_ms` for a silent driver, `wall_ms_hard` for a
   chatty one, `deadline_ms` for the caller's. **`PROGRESS` is the only frame that resets
   `progress_ms`** -- a `LOG` frame does not, and 04:1735-1737 calls that "a deliberate
   correction of the obvious design". `Countdown` is that rule, and `Countdown.expired()` returns
   WHICH limit fired because 04:1728-1729's outcome column is `FAILED_PERMANENT{TIMEOUT}` with
   `limit` naming it.
3. **Every blocking read has a deadline.** A worker is a process we do not trust; it can send a
   length prefix that lies, a frame that never ends, a body shorter than the declared length, or
   nothing at all forever. The reader thread's reads are blocking, the SUPERVISOR's waits are not:
   it waits on a bounded queue for at most `HostSettings.tick_ms` at a time and re-checks the
   three deadlines at BOTH ENDS of every tick -- before the queue read, so a frame flood cannot
   hold the supervisor in a loop past `wall_ms_hard`, and after it, so a wait that consumed the
   remaining budget is noticed. That is the whole of 04-driver-system.md section 6.5 in one
   sentence -- the assertion is a bounded refusal, never a hang. `_await_frame`'s docstring
   argues the order at length, because the obvious one is the wrong one.
4. **The read queue is bounded and a full queue means the host stops reading.**
   `FRAME_QUEUE_MAX = 256` (04-driver-system.md:1793, :2849). The reader thread blocks in
   `Queue.put`, the pipe fills, the driver stalls, and `wall_ms_hard` fires. **No frame is
   buffered on the host's behalf** -- a frame flood becomes backpressure, never host memory.
5. **AIMD halves on OOM and RECOVERS**, because 02-architecture.md:831 and 12-performance.md:1027
   both say halve-and-never-recover "lets one foreign process permanently cap a driver". The
   recovery half is not a nicety; it is the half that makes the mechanism correct, so
   `adapt_batch` is a pure function over `AimdState` and the streak resets on a NON-CLEAN event
   rather than on any event.
6. **A worker that dies without a frame is `driver_crashed` SYNTHESISED, never guessed**
   (02-architecture.md:831, :1060): the exit status plus the last `STDERR_RING_BYTES` of the
   stderr ring, and nothing else -- no traceback, no module path (02:1060 is explicit: "Nothing
   else crosses").
7. **Quarantine is per driver, per run, and it has ONE home.** `crash_quarantine = {crashes = 3,
   window_s = 60}` (04-driver-system.md:1727, 08-runtime.md:2591) counts crashes here and
   `CrashLedger.quarantined()` projects the set; `omniweave_core.drivers.resolve`'s
   `Policy.quarantined` CONSUMES it and `RejectCode.QUARANTINED` is the rejection. There is no
   second channel and no second flag -- INV-21, and `resolve.py`'s `_gate_not_quarantined` is the
   reader.

## The host verdict is not a `DriverError`, and that is forced by the types

`omniweave_ports.types.DriverError.__post_init__` enforces charter D3's "`retry_after_ms` REQUIRED
iff transient", and `TRANSIENT_FAILURE_CLASSES` holds `TIMEOUT` and `RESOURCE_LIMIT`. Its own
docstring says why: *"Only a driver constructs a `DriverError`, so this set is the driver half of
that table"* -- driver-reported `timeout` is transient (the driver observed a slow remote peer),
**host-detected `timeout` is `failed_permanent`** (02-architecture.md:1014, 08-runtime.md:567).
A host that constructed `DriverError(TIMEOUT, ...)` would therefore have to invent a
`retry_after_ms` it has no basis for AND would mis-state the verdict. So host-detected failures
are `HostVerdict`, which carries `permanent` explicitly and converts to a `DriverError` only for
the classes a driver could itself have raised. 08-runtime.md section 1.3's `Outcome`/`StepResult`
is where a `HostVerdict` finally lands, and that type is P4's (16-roadmap.md:493 W4.1), so this
module produces the verdict and never the row.

## What is deliberately NOT here

* **`Batch` and `DriverHost.invoke(Batch)`.** 02-architecture.md:238's own "does not include"
  column reads *"batching policy, retries and quarantine decisions -- all
  `omniweave/run/dispatch.py`'s"*, and `Batch` is 08-runtime.md section 2.2's type, landing at P4
  (16-roadmap.md:493). `Invocation` below is the S4 WIRE payload -- `INVOKE{invoke_id, units,
  deadline_ms, budget_micros}`, 04-driver-system.md:1699's four keys and no others -- which
  section 6.2 owns. `adapt_batch` and `retry_batch_size` are the pure MECHANISMS the dispatcher
  will call; 08-runtime.md:760-775 prints `adapt_batch` under *its* section 2.2, so the eventual
  home is P4's dispatcher and the relocation is reported rather than pre-empted. They are here
  because W3.2 is where the OOM and the crash are OBSERVED and because 02:831 puts AIMD inside
  the S4 cell.
* **The worker-side `DriverIO`.** 04-driver-system.md section 6.7 and 14-security.md:867 give the
  worker bootstrap its own obligations (the audit hook installed BEFORE `activate()` imports the
  driver's module) and `DriverIO` needs a `BlobStore`. `connect()` and `read_frame()` below are
  the parts of the worker side that are pure protocol; the bootstrap is `inproc.py`'s company.
* **`Degradation`.** 15-observability.md:964-996 is that type's SOLE home and it lives in
  `omniweave_core/observe/degradation.py`, which does not exist yet. `IsolationShortfall` carries
  the FACTS 04-driver-system.md:1710-1711 requires -- "naming the control and the OS" -- and
  `IsolationShortfall.DEGRADATION_KIND` transcribes the one literal (15-observability.md:981)
  rather than redeclaring the twenty-seven-member vocabulary.

## Windows, and the six things this platform does not give us

02-architecture.md:428 calls the transport *"a 0600 unix socket or an owner-only named pipe"*. We
develop and test on Windows 11, so **the named-pipe arm is the arm that runs here and the AF_UNIX
arm is the one this machine cannot test**; `NamedPipeListener` and `UnixSocketListener` are both
written and only the first is exercised, which is stated rather than hidden.
`store/crashmatrix.py`'s docstring is the precedent for that idiom and this file follows it.
04-driver-system.md:1745 requires the shortfalls be *"recorded rather than claimed"* (DR10), so
`CONTROLS_BY_PLATFORM` transcribes section 6.4's per-OS table and `grant_isolation()` turns each
missing control into one `IsolationShortfall` naming the control and the OS:

* **No CPU cap.** 04-driver-system.md:1752's Windows cell is *"not available; `wall_ms_hard`
  only"*, and 08-runtime.md:2444 repeats it. `cpu_capped` is `False` here, always.
* **No file-descriptor cap.** :1753's Windows cell is "not applicable". `fd_capped` is `False`.
* **No network namespace.** :1755 -- `unshare(CLONE_NEWNET)` is Linux-only and Windows
  *"degrades to a process-level guard"*. `net_blocked` is `False`, and 14-security.md:111 puts
  that in the out-of-scope list in as many words.
* **No two-step kill.** 04-driver-system.md:1728 spells the hang path *"SIGTERM, SIGKILL at +5 s,
  the whole process group reaped"*. Windows has no SIGTERM: `Popen.terminate()` IS
  `TerminateProcess`, which -- as `store/crashmatrix.py` already states -- cannot be caught,
  handled or ignored. So the catchable half of the ladder is the `SHUTDOWN{grace_ms}` FRAME, which
  the driver may act on, and the uncatchable half is `TerminateProcess` at `+KILL_GRACE_MS`: the
  two-signal ladder collapses to one signal plus one frame. What Windows does not reproduce is a
  driver that installs a `SIGTERM` handler and flushes -- there is no such handler to install --
  and that matters to a driver's own tidiness, never to the host's availability, which is the
  property section 6.5 is about.
* **The process-group reap is a JOB OBJECT.** :1728's "whole process group" has no Windows
  counterpart. `JobObject` creates one with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, assigns the
  child, and `TerminateJobObject` takes the grandchildren with it. That IS observable here:
  `JobObject.pids()` reads `JobObjectBasicProcessIdList` back, so the test asserts the child's pid
  is in the job -- a job object nobody was assigned to is the silent failure this replaces.
* **The process we hold may not be the process doing the work.** A venv created by `uv` puts a
  LAUNCHER TRAMPOLINE at `sys.executable`, which execs the base interpreter as its own child, so
  `Popen.pid` is the trampoline and the driver runs in a grandchild. Two consequences, and only
  one of them is benign: the job object covers the whole tree, so the reap and the address-space
  cap are unaffected -- which is exactly the argument 04-driver-system.md:1728 makes for reaping
  a group rather than a process -- but `peak_rss_bytes(proc.pid)` then samples the trampoline
  and reads a few megabytes whatever the driver allocates. The watchdog's number is therefore
  only as good as the spawn's shape, and a caller that spawns through a trampoline is sampling
  the wrong process. Recorded, not papered over: the tree-wide answer is the job object's
  `PeakJobMemoryUsed`, which 04:1751's Windows cell does not name, so it is not claimed here.
* **RSS sampling is psapi, not `getrusage`.** There is no `resource` module on Windows, so no
  `RLIMIT_AS`, no `RLIMIT_DATA`, no `RLIMIT_CPU`, no `RLIMIT_NOFILE` and no `os.nice`.
  `tools/measure_store.py:410-436` already solved peak-RSS sampling here and `peak_rss_bytes()`
  takes the same reading, including the one detail that makes the bug silent: `OpenProcess`
  returns a HANDLE and ctypes defaults `restype` to `c_int`, which TRUNCATES it on 64-bit Windows
  so `GetProcessMemoryInfo` then fails with a perfectly plausible zero. Every `restype` and
  `argtypes` below is set explicitly for that reason.

## Stdlib only, no loop, no ambient anything

INV-2/G1: `contextlib`, `ctypes`, `io`, `msvcrt`, `os`, `queue`, `socket`, `subprocess` and
`threading` are all standard library, and 04-driver-system.md:1769 says the watchdog "adds no
dependency" for exactly this reason. G23: **no `asyncio` and no `selectors`** -- the single event
loop lives in `omniweave/run/` (INV-3), so the supervisor is one blocking wait on a bounded queue
tick, which is also what makes the frame flood become backpressure (mechanism 4). The clock, the
ids and the spawn are PARAMETERS: `now_ms` is a `Callable[[], int]`, `invoke_id` arrives on the
`Invocation`, and `Spawn` is injected, so every deadline test runs on a fake clock and every pool
test runs without a process. `tick_ms` is not a constant here either -- 04-driver-system.md:1769
says RSS sampling at 250 ms "is the same cadence as `loop_lag_max_ms = 250`, so the supervisor
loop already wakes at that rate", and `runtime.loop_lag_max_ms` is `config.py`'s key, so
`HostSettings.from_config()` reads it and this module declares no 250.

Tier T-CONTRACT (02-architecture.md:238). Specified in 04-driver-system.md sections 6.2-6.6,
02-architecture.md section 5.6 row 12, section 6.2's process map, and the S4 seam row at :428
and :831.
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import os
import queue
import socket
import subprocess  # S4. TID251 is per-file-ignored for this path in pyproject.toml.
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, NamedTuple, Protocol

from omniweave_ports.types import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    Isolation,
    UnitRef,
)

from omniweave_core.errors import DriverHostError
from omniweave_core.host import wire

try:  # Windows only. The POSIX arm of the transport is the 0600 unix socket.
    import msvcrt
except ImportError:  # pragma: no cover -- POSIX, which this machine is not
    msvcrt = None  # type: ignore[assignment]


# =============================================================================================
# 1. The framing is `omniweave_core.host.wire`'s, and nothing here re-declares it
#
# `wire.py` is "FRAMING ONLY (~80 lines, fuzzed)" (02-architecture.md:86, :238) and is
# AUTHORITATIVE: the eleven kinds and their numbers, the direction column, the three caps
# (`MAX_HEADER_BYTES`, `MAX_BODY_BYTES`, `MAX_HEADER_DEPTH`), the `kind` header key, `encode`,
# `decode`, `decode_prefix` and `read_frame` are all its. This module names none of them a second
# time -- no frame-kind number, no cap, no byte offset appears below (INV-21).
#
# What subproc.py adds on top of framing is the three things framing deliberately does not do:
# a DEADLINE on every blocking read, a BOUNDED queue between the read and the supervisor, and a
# PROCESS whose death is a verdict. `wire.Recv` is the seam -- "read AT MOST n bytes, returning
# fewer only at end of stream" -- and `_exact` below is the adapter from a `ByteChannel` to it.
# =============================================================================================


def _exact(channel: ByteChannel) -> wire.Recv:
    """A `wire.Recv` over a `ByteChannel`: read exactly `n` bytes, or fewer only at EOF.

    `socket.recv` and `FileIO.read` both return a SHORT read whenever the peer has not sent
    everything yet, and `wire.read_frame` treats a short read as a truncation fault -- correctly,
    because framing cannot tell "not yet" from "never" without a clock and framing has no clock.
    So the loop is here, where the clock is: this adapter blocks until the declared bytes arrive
    or the transport ends, and the DEADLINE that bounds that block is the supervisor's tick on
    the far side of `FrameReader`'s queue.

    It never allocates more than `size`, which is the property 04-driver-system.md:1791 states as
    *"the reader allocates exactly the declared length and never speculatively"* -- and `size` has
    already been through `wire.decode_prefix`'s caps by the time `read_frame` asks for it.
    """

    def recv(size: int) -> bytes:
        if size <= 0:
            return b""
        buffer = bytearray()
        while len(buffer) < size:
            chunk = channel.recv(size - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
        return bytes(buffer)

    return recv


RESULT_UNIT_INDEX_KEY: Final = "unit_index"
"""The `RESULT` header key whose value is validated against the batch.

A PAYLOAD key and not a framing one, which is why it is here: `wire.py`'s docstring says framing
"makes no claim about which payload keys a kind carries". 04-driver-system.md:1796 makes this one
load-bearing -- *"a `RESULT` for a unit that was not in the `INVOKE`"* is a protocol error and
*"the worker is killed, not trusted"*.
"""


# =============================================================================================
# 2. The host's own constants: not `wire.py`'s, and not `config.py`'s either.
#
# Rule: a number `config.py` already declares is read from the `Config`, never restated (INV-21).
# `worker_idle_ttl_s`, `crash_quarantine` and `max_workers` are all `[drivers]` keys with
# declared defaults in `config.py`, so they arrive on `HostSettings` and there is no default for
# them here. What is left below is the set of numbers the plan states and no config key owns.
# =============================================================================================

FRAME_QUEUE_MAX: Final = 256
"""The host's bounded read queue, PER WORKER.

04-driver-system.md:2849 is the definition site and states the consequence: *"A full queue means
the host stops reading, so a frame flood becomes pipe backpressure and then `wall_ms_hard`, never
host memory."* :1793 is the attack row it answers. Not a config key -- a knob here would let an
operator turn the backpressure off, which is the one thing it exists to guarantee.
"""

STDERR_RING_BYTES: Final = 4_096
"""4 KiB: the tail of the child's stderr attached to a synthesised crash.

04-driver-system.md:1723 and :1721, 02-architecture.md:581, :831 and :1060 all say "the last
4 KiB of the stderr ring". 15-observability.md:1333 adds the handling rule -- the tail is
*"never parsed for a code"* and passes through `redact()` before it is stored -- so
`StderrRing.tail()` returns bytes and this module does not interpret them.
"""

AIMD_RECOVERY_STREAK: Final = 20
"""Consecutive clean batches before the batch size increases by one.

02-architecture.md:831 (*"recovers after 20 consecutive clean batches"*), 08-runtime.md:770 and
12-performance.md:1027 all print 20. Additive increase, multiplicative decrease -- and the
recovery is the half that makes the mechanism correct.
"""

KILL_GRACE_MS: Final = 5_000
"""+5 s: the gap between the graceful step and the uncatchable one.

04-driver-system.md:1728 (*"SIGTERM, SIGKILL at +5 s"*), :126 (*"`SHUTDOWN`, then SIGTERM, then
SIGKILL at +5 s"*) and 05-ingest-and-routing.md:3054 all print the same 5 s. On Windows the
graceful step is the `SHUTDOWN{grace_ms}` frame rather than a signal; see the module docstring's
"No two-step kill".

**Two things about this number are reported rather than resolved here.**

1. The plan's ladder has TWO five-second gaps, not one: 08-runtime.md:2406 sends `SHUTDOWN`
   only after `[runtime] shutdown_grace_ms = 5000` has passed with no return, and *then* SIGTERM,
   and *then* SIGKILL at +5 s. Windows has no catchable signal, so the middle rung does not
   exist here (module docstring) and the ladder collapses to `SHUTDOWN` plus `TerminateProcess`
   at +5 s -- ONE gap, with the second five seconds unreachable on this platform rather than
   dropped. On POSIX the same collapse would lose a rung, which is why `stop(grace_ms=...)`
   takes the gap as an argument and this constant is only its default.
2. `[runtime] shutdown_grace_ms` is a config key in the plan (08-runtime.md:2406, :2603) and
   `config.py` does not declare it, so section 2's rule -- "a number `config.py` already declares
   is read from the `Config`, never restated" -- cannot be followed for it. The constant is the
   only home the number has today; the owed `config.py` row is reported.
"""

# =============================================================================================
# 3. Settings, and the three deadlines
# =============================================================================================


@dataclass(frozen=True, slots=True)
class HostSettings:
    """The `[drivers]` and `[runtime]` numbers the host runs on. **No defaults, on purpose.**

    Every field here is a key `config.py` already declares, so a default in this dataclass would
    be a second home for a number the config module owns (INV-21) and the two could drift
    silently -- which is the exact failure mode 08-runtime.md:735 describes for `max_workers`:
    *"a silent clamp would have made an operator's `max_workers = 4` a lie recorded nowhere"*.
    `from_config()` is the only intended constructor; a test constructs one directly with
    literals, which is what makes the test pin values rather than agreement.

    `tick_ms` is `runtime.loop_lag_max_ms` and not a fourth deadline: 04-driver-system.md:1769
    says RSS sampling at 250 ms *"is the same cadence as `loop_lag_max_ms = 250`, so the
    supervisor loop already wakes at that rate and the watchdog is free"*. One tick therefore does
    three things -- re-check the three deadlines, sample RSS, and take one frame off the queue --
    and there is exactly one wake rate in the process.
    """

    worker_idle_ttl_s: int
    crash_threshold: int
    crash_window_s: int
    tick_ms: int
    max_workers: Mapping[str, int]

    @classmethod
    def from_config(cls, cfg: object) -> HostSettings:
        """Read the five numbers off a resolved `Config`.

        Typed `object` and reached through `getattr` so that this module does not import
        `omniweave_core.config` merely to name a type: `host` is one of G17's nine lazy names and
        `config` is on core's eager surface, so the edge is legal in that direction but pointless
        -- what the host needs is five integers, not the config machinery. The keys are
        `drivers.worker_idle_ttl_s` (300), `drivers.crash_quarantine` (`{crashes = 3, window_s =
        60}`), `runtime.loop_lag_max_ms` (250) and `drivers.max_workers`
        (`{free = 4, local_compute = 4, billed_api = 8}`), all declared in `config.py` and
        specified in 08-runtime.md:2589-2591 and :2444.
        """
        get = getattr(cfg, "get", None)
        if not callable(get):
            raise DriverHostError(
                f"{type(cfg).__name__} is not a resolved Config: no get()",
                fix="pass omniweave_core.config.load(...)'s Config to HostSettings.from_config",
            )
        quarantine = get("drivers.crash_quarantine")
        if not isinstance(quarantine, Mapping):
            raise DriverHostError(
                "drivers.crash_quarantine did not resolve to a table",
                fix="set [drivers] crash_quarantine = { crashes = 3, window_s = 60 }",
            )
        workers = get("drivers.max_workers")
        return cls(
            worker_idle_ttl_s=int(get("drivers.worker_idle_ttl_s")),  # type: ignore[arg-type]
            crash_threshold=int(quarantine["crashes"]),  # type: ignore[arg-type]
            crash_window_s=int(quarantine["window_s"]),  # type: ignore[arg-type]
            tick_ms=int(get("runtime.loop_lag_max_ms")),  # type: ignore[arg-type]
            max_workers=MappingProxyType(
                {str(k): int(v) for k, v in dict(workers).items()}  # type: ignore[arg-type]
            ),
        )


class Deadlines(NamedTuple):
    """The three deadlines of 04-driver-system.md:1733-1735, as three separate numbers.

    `progress_ms` and `wall_ms_hard` are the card's (`[isolation]`, 04-driver-system.md:769:
    *"none"* by way of a default -- they are per-card and the reference card at :923-924 prints
    15000 and 60000). `deadline_ms` is the CALLER's and rides on the `INVOKE` frame
    (04-driver-system.md:1699). A zero means "not bounded by this one", which is how a `PROBE`
    exchange runs under `wall_ms_hard` alone.
    """

    progress_ms: int
    wall_ms_hard: int
    deadline_ms: int


LIMIT_NAMES: Final = ("progress_ms", "wall_ms_hard", "deadline_ms")
"""The three `limit` spellings a host-detected `TIMEOUT` may name, in the plan's own order.

04-driver-system.md:1728-1729's outcome column prints `limit = "progress_ms"` and
`limit = "wall_ms_hard"` verbatim. `deadline_ms` completes the three of :1734 and the plan prints
NO outcome row for it -- it is the caller's deadline, and 02-architecture.md:1014 lists all three
as "three separate deadlines" without assigning the third a `limit` spelling. Reported: the
spelling is ours, derived from the field name the plan does print.
"""


class Countdown:
    """The three deadlines against one injected clock, and WHICH one fired.

    Not frozen and not a value type: it holds `last_progress_ms`, which is mutable state by
    construction -- **`PROGRESS` is the only frame that resets it** (04-driver-system.md:1735,
    12-performance.md:311, 08-runtime.md:2377). `note_log()` exists and deliberately does
    nothing, because "a `LOG` frame does not reset it" is a claim worth having a named site for:
    a reviewer can see that the LOG path was considered and rejected rather than forgotten.

    `expired()` returns the first limit to have elapsed in TIME, and ties break in `LIMIT_NAMES`
    order, which is the plan's printed order. Two deadlines firing on the same millisecond is
    otherwise decided by dict ordering, which is not a contract.
    """

    __slots__ = ("_deadlines", "_last_progress_ms", "_started_ms")

    def __init__(self, deadlines: Deadlines, *, started_ms: int) -> None:
        self._deadlines = deadlines
        self._started_ms = started_ms
        self._last_progress_ms = started_ms

    @property
    def started_ms(self) -> int:
        return self._started_ms

    @property
    def last_progress_ms(self) -> int:
        return self._last_progress_ms

    def note_progress(self, now_ms: int) -> None:
        """A `PROGRESS` frame arrived. The ONE frame that moves `progress_ms`'s origin."""
        self._last_progress_ms = now_ms

    def note_log(self, now_ms: int) -> None:  # noqa: ARG002 -- the no-op IS the specification
        """A `LOG` frame arrived. Resets NOTHING.

        04-driver-system.md:1735-1737: *"a driver logging in a tight loop while making no progress
        would otherwise look alive forever, which is the failure `progress_ms` exists to catch."*
        """
        return

    def elapsed_ms(self, now_ms: int) -> int:
        return now_ms - self._started_ms

    def expired(self, now_ms: int) -> str | None:
        """The `limit` spelling of the first deadline to have elapsed, or `None`."""
        overshoot: dict[str, int] = {}
        silent = now_ms - self._last_progress_ms
        if self._deadlines.progress_ms > 0 and silent >= self._deadlines.progress_ms:
            overshoot["progress_ms"] = silent - self._deadlines.progress_ms
        elapsed = now_ms - self._started_ms
        if self._deadlines.wall_ms_hard > 0 and elapsed >= self._deadlines.wall_ms_hard:
            overshoot["wall_ms_hard"] = elapsed - self._deadlines.wall_ms_hard
        if self._deadlines.deadline_ms > 0 and elapsed >= self._deadlines.deadline_ms:
            overshoot["deadline_ms"] = elapsed - self._deadlines.deadline_ms
        if not overshoot:
            return None
        widest = max(overshoot.values())
        for name in LIMIT_NAMES:
            if overshoot.get(name) == widest:
                return name
        raise AssertionError("unreachable: overshoot keys are a subset of LIMIT_NAMES")

    def wait_ms(self, now_ms: int, *, tick_ms: int) -> int:
        """How long the supervisor may block on the queue before it must look at the clock again.

        Never longer than one tick, so the wall clock is re-read at `loop_lag_max_ms` even when
        the next deadline is an hour away, and never longer than the nearest deadline, so a
        250 ms tick does not overshoot a 10 ms remainder. Never negative: a caller that gets 0
        must treat the deadline as fired.
        """
        remaining = [tick_ms]
        if self._deadlines.progress_ms > 0:
            remaining.append(self._last_progress_ms + self._deadlines.progress_ms - now_ms)
        if self._deadlines.wall_ms_hard > 0:
            remaining.append(self._started_ms + self._deadlines.wall_ms_hard - now_ms)
        if self._deadlines.deadline_ms > 0:
            remaining.append(self._started_ms + self._deadlines.deadline_ms - now_ms)
        return max(0, min(remaining))


# =============================================================================================
# 4. The host's verdict, and the five failure modes it is the range of
# =============================================================================================


@dataclass(frozen=True, slots=True)
class HostVerdict:
    """One failure, as the HOST saw it. Not a `DriverError` -- see the module docstring.

    `permanent` is carried rather than computed because the same `FailureClass` has two verdicts
    depending on who observed it (08-runtime.md:567): driver-reported `timeout` is transient,
    host-detected `timeout` is `failed_permanent`. A `permanent` field that a reader could derive
    from `failure_class` alone would therefore be wrong for exactly the two classes that matter.

    `stderr_tail` is bytes and stays bytes: 15-observability.md:1333 says the tail is *"never
    parsed for a code"* and passes `redact()` before storage, and decoding it here would be the
    first step towards parsing it.
    """

    failure_class: FailureClass
    message: str
    permanent: bool
    limit: str | None = None
    retry_after_ms: int | None = None
    pages: tuple[int, ...] = ()
    exit_status: int | None = None
    stderr_tail: bytes = b""
    detected_by: str = "host"

    @classmethod
    def crashed(cls, *, exit_status: int | None, stderr_tail: bytes) -> HostVerdict:
        """A worker that died WITHOUT a frame. 02-architecture.md:831 and :1060.

        *"synthesised from the exit status plus the last 4 KiB of the stderr ring"* -- and nothing
        else. The message names the exit status because a reader's first question is whether the
        child was signalled or exited, and on POSIX a negative `returncode` from
        `subprocess.Popen` IS the signal number.
        """
        return cls(
            failure_class=FailureClass.DRIVER_CRASHED,
            message=(
                f"worker died without a frame, exit status {exit_status}"
                if exit_status is not None
                else "worker closed the transport without a frame and did not exit: no status"
            ),
            permanent=True,
            exit_status=exit_status,
            stderr_tail=stderr_tail[-STDERR_RING_BYTES:],
        )

    @classmethod
    def timed_out(cls, limit: str, *, elapsed_ms: int) -> HostVerdict:
        """A host-detected deadline. `FAILED_PERMANENT{TIMEOUT}`, `limit` naming which fired."""
        if limit not in LIMIT_NAMES:
            raise DriverHostError(
                f"{limit!r} is not one of the three deadlines {LIMIT_NAMES}",
                fix="name progress_ms, wall_ms_hard or deadline_ms",
            )
        return cls(
            failure_class=FailureClass.TIMEOUT,
            message=f"{limit} elapsed after {elapsed_ms} ms",
            permanent=True,
            limit=limit,
        )

    @classmethod
    def over_memory(cls, *, observed_bytes: int, cap_mb: int) -> HostVerdict:
        """The watchdog's verdict. `FAILED_PERMANENT{RESOURCE_LIMIT}`, `limit = "memory_mb"`.

        04-driver-system.md:1730. `limit` names the knob that would need raising, which is
        `[isolation] memory_mb` on the card, and the arithmetic is in the message because
        `ow doctor --runtime` prints the same product against physical RAM (:1777).
        """
        return cls(
            failure_class=FailureClass.RESOURCE_LIMIT,
            message=(
                f"worker peak RSS {observed_bytes} bytes over [isolation] memory_mb {cap_mb} "
                f"({cap_mb * 1_048_576} bytes)"
            ),
            permanent=True,
            limit="memory_mb",
        )

    @classmethod
    def from_driver(cls, error: DriverError) -> HostVerdict:
        """A driver-REPORTED failure, carried through without re-classifying it.

        02-architecture.md:1060: the worker serialises *"the five `DriverError` fields --
        `failure_class`, message, `retry_after_ms`, `pages`, `limit`"* into the `RESULT` header or
        sends `FATAL` as its last words, and the host reconstructs the error. `permanent` is
        `False` for a class in `TRANSIENT_FAILURE_CLASSES` and the retry ladder is
        `run/pipeline.py`'s `with_retries` calling `classify()`, never this module's.
        """
        return cls(
            failure_class=error.cls,
            message=error.message,
            permanent=error.retry_after_ms is None,
            limit=error.limit,
            retry_after_ms=error.retry_after_ms,
            pages=error.pages,
            detected_by="driver",
        )

    def as_driver_error(self) -> DriverError:
        """The `DriverError` this verdict is, when one exists.

        02-architecture.md:1060 says `host/subproc.py` *"reconstructs a `DriverError`"*, and for a
        driver-reported failure and for a synthesised `driver_crashed` it can: neither needs a
        `retry_after_ms` it does not have. It CANNOT for a host-detected `timeout` or
        `resource_limit`, because `DriverError.__post_init__` requires `retry_after_ms` for a
        transient class and both are transient IN THE DRIVER'S HALF of 08-runtime.md:567's table
        while being permanent here. Raising is the honest answer; inventing a cooldown is not.
        """
        if self.detected_by == "host" and self.retry_after_ms is None:
            transient = self.failure_class in {
                FailureClass.RATE_LIMITED,
                FailureClass.UPSTREAM_UNAVAILABLE,
                FailureClass.TIMEOUT,
                FailureClass.RESOURCE_LIMIT,
            }
            if transient:
                raise DriverHostError(
                    f"a host-detected {self.failure_class.value} is failed_permanent and has no "
                    "retry_after_ms, so it is not expressible as a DriverError "
                    "(08-runtime.md:567)",
                    fix="carry the HostVerdict to run/pipeline.py and let it build the Outcome",
                )
        return DriverError(
            cls=self.failure_class,
            message=self.message,
            retry_after_ms=self.retry_after_ms,
            pages=self.pages,
            limit=self.limit,
        )


class FailureMode(NamedTuple):
    """One row of 04-driver-system.md:1727-1731. A transcription, not a design."""

    failure: str
    detector: str
    mechanism: str
    outcome: str
    limit: str | None


FAILURE_MODES: Final = (
    FailureMode(
        failure="segfault / abnormal exit",
        detector="waitpid returns a signal or a non-zero exit before RESULT",
        mechanism="retry once at batch = 1; attach the last 4 KiB of stderr",
        outcome="FAILED_PERMANENT{DRIVER_CRASHED}",
        limit=None,
    ),
    FailureMode(
        failure="hang, silent",
        detector="progress_ms since the last PROGRESS frame",
        mechanism="SIGTERM, SIGKILL at +5 s, the whole process group reaped",
        outcome="FAILED_PERMANENT{TIMEOUT}",
        limit="progress_ms",
    ),
    FailureMode(
        failure="hang, chatty",
        detector="wall_ms_hard since INVOKE",
        mechanism="SIGTERM, SIGKILL at +5 s, the whole process group reaped",
        outcome="FAILED_PERMANENT{TIMEOUT}",
        limit="wall_ms_hard",
    ),
    FailureMode(
        failure="memory leak / runaway",
        detector="section 6.4's per-OS controls",
        mechanism="RLIMIT or a job object where available; RSS sampling everywhere",
        outcome="FAILED_PERMANENT{RESOURCE_LIMIT}",
        limit="memory_mb",
    ),
    FailureMode(
        failure="malicious",
        detector="not detected",
        mechanism="containment only; section 6.6",
        outcome="the residual risk, written down",
        limit=None,
    ),
)
"""The FIVE failure modes, transcribed from 04-driver-system.md:1727-1731.

FIVE because :1723's heading says "The five failure modes, and the mechanism for each" and the
table under it has five rows, which agree. The fifth row's detector is *"not detected"* and its
outcome is *"the residual risk, written down"*: it is in the table so that the count of modes
this module handles cannot be quietly read as five when it is four.
"""


# =============================================================================================
# 5. AIMD, and the single retry that localises the poison unit
# =============================================================================================


class BatchEvent(StrEnum):
    """What one batch did, as AIMD sees it. FOUR members, from 08-runtime.md:764-773's `match`.

    08-runtime.md:762 states the constraint the enum has to satisfy: *"`BatchEvent` is a
    projection of `FailureClass`, not a second taxonomy."* So there is no `TIMEOUT` member --
    a timeout does not change the batch size, because a smaller batch does not make a hanging
    driver finish -- and no `OK_PARTIAL`: a partial success is clean as far as the batch size is
    concerned. `RESOURCE_LIMIT` is the OOM arm, `WORKER_DIED` shares it, `DRIVER_CRASHED` goes
    straight to 1, and `CLEAN` is the recovery arm.
    """

    CLEAN = "clean"
    RESOURCE_LIMIT = "resource_limit"
    WORKER_DIED = "worker_died"
    DRIVER_CRASHED = "driver_crashed"


class AimdState(NamedTuple):
    """The AIMD state per `(driver_id, config_digest)` -- 08-runtime.md:760's own key.

    `card_max` is `card.isolation.batch_max_units` (the reference card prints 32 at
    04-driver-system.md:925) and is the ceiling the increase may never pass; `batch` is the
    current size; `clean_streak` counts CONSECUTIVE clean batches.
    """

    batch: int
    clean_streak: int
    card_max: int


def adapt_batch(state: AimdState, event: BatchEvent) -> AimdState:
    """AIMD: multiplicative decrease, ADDITIVE increase. Pure.

    08-runtime.md:764-775 prints the decision as a `match` returning an int; this returns the
    whole state because the streak bookkeeping is the half that decides whether the recovery
    works, and the plan's snippet -- which reads `case BatchEvent.CLEAN if state.clean_streak >=
    20` -- does not print who increments or resets the streak. Three rules, and the second and
    third are ours:

    1. `RESOURCE_LIMIT | WORKER_DIED -> max(1, batch // 2)`; `DRIVER_CRASHED -> 1`, to localise
       the poison unit. Both are the plan's, verbatim.
    2. **A non-clean event resets the streak to zero**, which is what "20 CONSECUTIVE clean
       batches" (02-architecture.md:831) means. Without it, nineteen clean batches, one OOM and
       one clean batch would raise the ceiling, and the counter would be measuring twenty clean
       batches *ever* rather than twenty in a row.
    3. **The streak resets on the increase**, so the recovery is one `+1` per twenty clean
       batches rather than a `+1` on every batch after the twentieth. The plan does not print
       this rule; it is reported as a gap and decided here, on the grounds that additive increase
       is a rate and a rate needs a denominator. At `card_max = 32` from `batch = 1` that is 620
       clean batches to full recovery, which is the conservative direction: it cannot oscillate.

    The plan's own justification for the recovery arm existing at all, in its words
    (02-architecture.md:831, 12-performance.md:1027): *"halve-and-never-recover lets one foreign
    process permanently cap a driver"*.
    """
    if event is BatchEvent.DRIVER_CRASHED:
        return state._replace(batch=1, clean_streak=0)
    if event in (BatchEvent.RESOURCE_LIMIT, BatchEvent.WORKER_DIED):
        return state._replace(batch=max(1, state.batch // 2), clean_streak=0)
    streak = state.clean_streak + 1
    if streak >= AIMD_RECOVERY_STREAK:
        return state._replace(batch=min(state.batch + 1, state.card_max), clean_streak=0)
    return state._replace(clean_streak=streak)


def retry_batch_size(event: BatchEvent, *, attempt: int) -> int | None:
    """The size of the retry, or `None` when there is not one. ONCE, at `batch = 1`.

    04-driver-system.md:1720-1722 and 02-architecture.md:831: *"the batch retries **once** at
    `batch = 1`** to localise the poison unit"*, and 08-runtime.md:569 repeats it in the failure
    ladder. `attempt` is zero-based, so `attempt=1` is already the retry and returns `None`:
    "once" is the load-bearing word, and a retry ladder that read this as "until it stops
    crashing" would multiply a segfaulting driver by the batch size. Only a crash earns the
    retry -- an OOM halves and re-dispatches through the ordinary path, and a timeout is
    permanent (08-runtime.md:567).
    """
    if event is not BatchEvent.DRIVER_CRASHED:
        return None
    if attempt >= 1:
        return None
    return 1


# =============================================================================================
# 6. Crash accounting: the DRIVER is quarantined, for the RUN, and `resolve()` reads it
# =============================================================================================


class CrashLedger:
    """`crash_quarantine = { crashes = 3, window_s = 60 }`, counted per driver.

    04-driver-system.md:1727 and 08-runtime.md:2591 fix the shape; `config.py` declares the
    default and `HostSettings` carries it, so this class takes the two numbers as arguments and
    declares neither.

    **Three properties, and the third is the one a reviewer should check.**

    1. **Per driver.** Driver A's crashes never quarantine driver B; the ledger is a mapping
       keyed on `driver_id` and NOT on `WorkerKey`, because 04:1727 says the quarantine takes
       *"the **driver** -- not the unit -- for the run"*, and a driver that segfaults under one
       configuration is not thereby trustworthy under another. That is a deliberate asymmetry
       with the worker key and it is the direction that fails closed.
    2. **Windowed.** Three crashes spread over more than `window_s` do not quarantine, so a
       long-running ingest of a corpus with three bad documents in it is not a dead driver.
       Timestamps outside the window are dropped as they are passed, so the ledger's memory is
       bounded by `threshold` entries per driver rather than by the run's length.
    3. **Sticky for the run.** A later clean batch does NOT clear a quarantine. 04:1727 is
       "for the run", and `resolve()` re-planning around the driver is the recovery path
       (02-architecture.md:831: *"`resolve()` then returns `RejectCode.QUARANTINED` and the
       router re-plans"*). A ledger that forgot on success would re-offer a driver that crashes
       every fourth document forever, which is the shape the counter exists to stop.

    There is no persistence and no file: the quarantine is run-scoped, so a new run gets a new
    `CrashLedger` and no cleanup step exists to forget. `quarantined()` returns a `frozenset[str]`
    because that is the exact type `omniweave_core.drivers.resolve.Policy.quarantined` holds --
    the host is the producer, `Policy` the carrier and `_gate_not_quarantined` the reader, and
    INV-21 allows no second channel between them.
    """

    __slots__ = ("_crashes", "_quarantined", "_threshold", "_window_ms")

    def __init__(self, *, threshold: int, window_s: int) -> None:
        if threshold < 1:
            raise DriverHostError(
                f"crash_quarantine.crashes = {threshold} would quarantine on no crash at all",
                fix="set [drivers] crash_quarantine = { crashes = 3, window_s = 60 }",
            )
        self._threshold = threshold
        self._window_ms = window_s * 1000
        self._crashes: dict[str, list[int]] = {}
        self._quarantined: set[str] = set()

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def window_ms(self) -> int:
        return self._window_ms

    def record(self, driver_id: str, *, now_ms: int) -> bool:
        """Record one crash. Returns whether the driver is quarantined AS OF THIS CRASH."""
        recent = [at for at in self._crashes.get(driver_id, ()) if now_ms - at < self._window_ms]
        recent.append(now_ms)
        self._crashes[driver_id] = recent
        if len(recent) >= self._threshold:
            self._quarantined.add(driver_id)
        return driver_id in self._quarantined

    def crashes_in_window(self, driver_id: str, *, now_ms: int) -> int:
        """How many crashes are inside the window right now. Read-only; drops nothing."""
        return sum(1 for at in self._crashes.get(driver_id, ()) if now_ms - at < self._window_ms)

    def quarantined(self) -> frozenset[str]:
        """The set `Policy(quarantined=...)` takes. Sticky: nothing here ever removes an id."""
        return frozenset(self._quarantined)


class StderrRing:
    """The child's stderr, bounded to the last `STDERR_RING_BYTES`.

    A ring and not a log: the driver's stdout and stderr are *"captured, logged at debug and
    never parsed"* (04-driver-system.md:1683), so an unbounded buffer would be host memory spent
    on bytes nobody reads, and the one consumer is the crash synthesis, which wants the TAIL.
    Fed by a reader thread, so `feed` takes the lock; `tail` takes it too, because a synthesis
    racing the child's dying words would otherwise read a torn buffer.

    15-observability.md:1333 bounds it as *"8 samples + a 4-line tail (~4 KiB)"* in the
    observability path and this is the 4 KiB half; the sampling is the event pipeline's, not the
    host's, and the two are not the same mechanism.
    """

    __slots__ = ("_buf", "_lock", "_max")

    def __init__(self, *, max_bytes: int = STDERR_RING_BYTES) -> None:
        self._max = max_bytes
        self._buf = bytearray()
        self._lock = threading.Lock()

    def feed(self, chunk: bytes) -> None:
        with self._lock:
            self._buf.extend(chunk)
            if len(self._buf) > self._max:
                del self._buf[: len(self._buf) - self._max]

    def tail(self) -> bytes:
        with self._lock:
            return bytes(self._buf)


# =============================================================================================
# 7. Isolation: what was granted, and what the OS did not give us
# =============================================================================================


@dataclass(frozen=True, slots=True)
class IsolationGranted:
    """`isolation_granted` -- the closed, EIGHT-key record of 04-driver-system.md:1709-1710.

    EIGHT because :1707 says *"a closed, eight-key record"* and the braced list under it names
    `mode`, `address_space_capped`, `rss_sampled`, `cpu_capped`, `fd_capped`, `net_blocked`,
    `tmp_only_writable` and `batch_max_units` -- eight, which agree. It rides on `HELLO` and the
    worker echoes it in `HELLO_ACK`'s acknowledgement path *"so a shortfall is visible from both
    sides"* (DR10).

    Every boolean is what the host OBTAINED, never what the card asked for: 04:1745 requires that
    *"what was not obtained is recorded rather than claimed"*, and a record that carried the
    request would be a claim.
    """

    mode: Isolation
    address_space_capped: bool
    rss_sampled: bool
    cpu_capped: bool
    fd_capped: bool
    net_blocked: bool
    tmp_only_writable: bool
    batch_max_units: int

    def as_header(self) -> Mapping[str, object]:
        """The JSON form the `HELLO` frame carries."""
        return {
            "mode": self.mode.value,
            "address_space_capped": self.address_space_capped,
            "rss_sampled": self.rss_sampled,
            "cpu_capped": self.cpu_capped,
            "fd_capped": self.fd_capped,
            "net_blocked": self.net_blocked,
            "tmp_only_writable": self.tmp_only_writable,
            "batch_max_units": self.batch_max_units,
        }


@dataclass(frozen=True, slots=True)
class IsolationShortfall:
    """One control the card asked for and the OS did not provide, naming the control and the OS.

    04-driver-system.md:1710-1711: *"Any boolean that is `false` where the card asked for the
    property becomes one `Degradation(kind="isolation_shortfall")` on the result, naming the
    control and the OS."* `Degradation` itself is 15-observability.md:964-996's sole property and
    lives in `omniweave_core/observe/degradation.py`, which does not exist yet, so this type
    carries the two facts the sentence requires and `DEGRADATION_KIND` transcribes the one
    literal from 15-observability.md:981's twenty-seven-member list.
    """

    DEGRADATION_KIND: ClassVar[str] = "isolation_shortfall"

    control: str
    os_name: str
    reason: str

    def message(self) -> str:
        """One sentence, for a human -- 15-observability.md:998 requires it name the cause."""
        return f"{self.control} was not obtained on {self.os_name}: {self.reason}"


@dataclass(frozen=True, slots=True)
class PlatformControls:
    """One column of 04-driver-system.md:1748-1756's per-OS table. A transcription.

    SEVEN rows, because :1747's table has seven: address-space cap, RSS sampling, CPU cap,
    file-descriptor cap, priority, no-egress, writable surface. `has_*` is what the platform CAN
    do; whether it was actually done for a given worker is `grant_isolation()`'s answer, since a
    job object can fail to be created on a platform that has them.
    """

    os_name: str
    address_space_cap: str
    rss_sampling: str
    cpu_cap: str | None
    fd_cap: str | None
    priority: str
    no_egress: str | None
    writable_surface: str


CONTROLS_BY_PLATFORM: Final = MappingProxyType(
    {
        "linux": PlatformControls(
            os_name="linux",
            address_space_cap="resource.setrlimit(RLIMIT_AS, ...) in the child before exec",
            rss_sampling="/proc/<pid>/statm",
            cpu_cap="RLIMIT_CPU",
            fd_cap="RLIMIT_NOFILE",
            priority="os.nice(10)",
            no_egress="unshare(CLONE_NEWUSER | CLONE_NEWNET)",
            writable_surface="one per-invocation tmpdir",
        ),
        "darwin": PlatformControls(
            os_name="darwin",
            address_space_cap="resource.setrlimit(RLIMIT_DATA, ...), NOT RLIMIT_AS",
            rss_sampling="ps -o rss= -p <pid>",
            cpu_cap="RLIMIT_CPU",
            fd_cap="RLIMIT_NOFILE",
            priority="os.nice(10)",
            no_egress=None,
            writable_surface="one per-invocation tmpdir",
        ),
        "win32": PlatformControls(
            os_name="win32",
            address_space_cap="Job Object JOB_OBJECT_LIMIT_PROCESS_MEMORY via ctypes",
            rss_sampling="GetProcessMemoryInfo via ctypes",
            cpu_cap=None,
            fd_cap=None,
            priority="SetPriorityClass(BELOW_NORMAL)",
            no_egress=None,
            writable_surface="one per-invocation tmpdir",
        ),
    }
)
"""04-driver-system.md:1748-1756's three columns, as data. THREE platforms.

The `None`s are the shortfalls the plan states in words and they are worth reading as a list,
because two of the three platforms are missing two controls each: Windows has no CPU cap
(*"not available; `wall_ms_hard` only"*) and no fd cap (*"not applicable"*), and neither Windows
nor macOS can block egress (*"not available; degrades to a process-level guard"*). The macOS
address-space row is the one 04:1758-1762 says *"a reviewer should check, because getting it
wrong is silent"* -- `RLIMIT_DATA` and not `RLIMIT_AS`, taken verbatim from
`graphify/watch.py:221` with its own comment that *"RLIMIT_AS is unreliable under Apple's
libmalloc"*.
"""


def grant_isolation(
    *,
    mode: Isolation,
    batch_max_units: int,
    platform: str,
    address_space_capped: bool,
    net_blocked_requested: bool,
    cpu_cap_requested: bool,
    fd_cap_requested: bool,
) -> tuple[IsolationGranted, tuple[IsolationShortfall, ...]]:
    """What the host obtained, plus one shortfall per control the card asked for and did not get.

    `address_space_capped` is passed in rather than inferred because on Windows it is a fact
    about ONE worker -- whether `JobObject` was actually created and the limit actually set --
    and a table lookup would claim it for every worker on the platform, which is precisely the
    claim DR10 forbids. `rss_sampled` and `tmp_only_writable` are true on all three platforms
    (every column of :1751 and :1756 is populated), so they are read off the table.

    A control the card did NOT ask for produces no shortfall even when the platform lacks it:
    04:1710 conditions the degradation on *"`false` where the card asked for the property"*, and
    a `Degradation` for a control nobody wanted is noise that trains a reader to ignore the
    channel.
    """
    controls = CONTROLS_BY_PLATFORM.get(platform)
    if controls is None:
        controls = PlatformControls(
            os_name=platform,
            address_space_cap="unknown platform: nothing claimed",
            rss_sampling="unknown platform: nothing claimed",
            cpu_cap=None,
            fd_cap=None,
            priority="unknown platform: nothing claimed",
            no_egress=None,
            writable_surface="one per-invocation tmpdir",
        )
    known = platform in CONTROLS_BY_PLATFORM
    granted = IsolationGranted(
        mode=mode,
        address_space_capped=address_space_capped,
        rss_sampled=known,
        cpu_capped=cpu_cap_requested and controls.cpu_cap is not None,
        fd_capped=fd_cap_requested and controls.fd_cap is not None,
        net_blocked=net_blocked_requested and controls.no_egress is not None,
        tmp_only_writable=True,
        batch_max_units=batch_max_units,
    )
    shortfalls: list[IsolationShortfall] = []
    if not granted.address_space_capped:
        shortfalls.append(
            IsolationShortfall(
                control="address_space_capped",
                os_name=platform,
                reason=f"{controls.address_space_cap} was not obtained for this worker",
            )
        )
    if cpu_cap_requested and not granted.cpu_capped:
        shortfalls.append(
            IsolationShortfall(
                control="cpu_capped",
                os_name=platform,
                reason="no CPU cap on this OS; wall_ms_hard is the only bound",
            )
        )
    if fd_cap_requested and not granted.fd_capped:
        shortfalls.append(
            IsolationShortfall(
                control="fd_capped",
                os_name=platform,
                reason="no file-descriptor cap on this OS",
            )
        )
    if net_blocked_requested and not granted.net_blocked:
        shortfalls.append(
            IsolationShortfall(
                control="net_blocked",
                os_name=platform,
                reason=(
                    "no network namespace on this OS; needs_network = false degrades to a "
                    "process-level guard a determined malicious driver can bypass "
                    "(14-security.md:111)"
                ),
            )
        )
    if not granted.rss_sampled:
        shortfalls.append(
            IsolationShortfall(
                control="rss_sampled",
                os_name=platform,
                reason="no RSS sampling recipe is recorded for this platform",
            )
        )
    return granted, tuple(shortfalls)


# =============================================================================================
# 8. The watchdog's two Windows instruments: psapi and the job object
# =============================================================================================


class _WinCounters(ctypes.Structure):
    """`PROCESS_MEMORY_COUNTERS` (psapi.h). `SIZE_T` is `c_size_t`, which is pointer-width.

    The same declaration `tools/measure_store.py:388-408` carries, for the same reason it gives:
    `psutil` is not a dependency of this repo and INV-2/G1 is why it will not become one. The
    duplication is between a `tools/` script and library code, which is the direction the layer
    graph permits -- `tools/` may import core, core may not import `tools/`.
    """

    _fields_ = (
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


_PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
"""The least privilege that reads another process's memory counters. `PROCESS_QUERY_INFORMATION`
(0x0400) also works and asks for more; a watchdog that needs no more should ask for no more."""

_PROCESS_VM_READ: Final = 0x0010
"""Required alongside the query right by `GetProcessMemoryInfo` on older Windows. Requested
together, because a handle opened without it returns a plausible zero rather than failing."""


_STATM_RSS_FIELD: Final = 1
"""`/proc/<pid>/statm` field 1 (zero-based) is resident set size IN PAGES, not bytes.

Field 0 is total program size. Reading the wrong one overstates RSS by the address space, which
is the same class of silent unit error `tools/measure_store.py:411` records for `ru_maxrss`.
"""


def _peak_rss_win32(pid: int) -> tuple[int | None, str]:
    """The psapi arm. `tools/measure_store.py:410-436`'s reading, aimed at another process."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # `restype` is set explicitly on every call because ctypes defaults it to `c_int`, and on
    # 64-bit Windows that TRUNCATES a HANDLE -- after which `GetProcessMemoryInfo` fails with
    # a perfectly plausible zero rather than raising (tools/measure_store.py:424-426).
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, 0, pid)
    if not handle:
        return (None, f"OpenProcess({pid}) failed, GetLastError {kernel32.GetLastError()}")
    try:
        counters = _WinCounters()
        counters.cb = ctypes.sizeof(counters)
        get_info = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if get_info is None:  # pragma: no cover -- pre-Windows-7 puts it in psapi.dll only
            get_info = ctypes.windll.psapi.GetProcessMemoryInfo  # type: ignore[attr-defined]
        get_info.restype = ctypes.c_int
        get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinCounters), ctypes.c_uint32]
        if not get_info(handle, ctypes.byref(counters), counters.cb):
            return (None, f"GetProcessMemoryInfo failed, {kernel32.GetLastError()}")
        return (int(counters.PeakWorkingSetSize), "K32GetProcessMemoryInfo PeakWorkingSet")
    finally:
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(handle)


def _peak_rss_linux(pid: int) -> tuple[int | None, str]:  # pragma: no cover -- not this machine
    """The procfs arm. 04-driver-system.md:1751's Linux cell: `/proc/<pid>/statm`."""
    try:
        with open(f"/proc/{pid}/statm", "rb") as statm:  # noqa: PTH123 -- procfs, not a path
            parts = statm.read().split()
    except OSError as exc:
        return (None, f"/proc/{pid}/statm unreadable: {exc}")
    if len(parts) <= _STATM_RSS_FIELD:
        return (None, f"/proc/{pid}/statm had {len(parts)} fields")
    pages = int(parts[_STATM_RSS_FIELD])
    return (pages * os.sysconf("SC_PAGE_SIZE"), "/proc/<pid>/statm rss pages")


def peak_rss_bytes(pid: int) -> tuple[int | None, str]:
    """`(peak working set in bytes, how it was obtained)`, or `(None, why not)`. Never raises.

    Per-OS, and the units are the part that is easy to get wrong -- `tools/measure_store.py:411`
    states it for the self case: Linux's `ru_maxrss` is KILOBYTES, macOS's is BYTES, and Windows
    has no `getrusage` at all. This function reads ANOTHER process, so `getrusage` is not
    available on any platform: the POSIX arms read `/proc/<pid>/statm` (Linux, 04:1751) and
    return a stated shortfall on darwin, where the plan's recipe is `ps -o rss= -p <pid>` -- *"a
    G8-permitted `subprocess` site inside `host/subproc.py`"*, which this file is. The darwin
    arm is written as a stated shortfall and not as a `ps` call, because a shell-out this machine
    cannot exercise is worse than a recorded gap.

    Never raising is deliberate. A watchdog that raised while sampling would turn a memory
    question into a host crash, and 04:1769's whole argument for the watchdog is that it is free.

    The two figures are also not the same quantity, which is why the second element of the tuple
    exists: Windows reports a PEAK (`PeakWorkingSetSize`) and procfs reports the CURRENT resident
    set, so a Linux sampler needs the 250 ms cadence to approximate what Windows gives for free.
    That asymmetry is recorded rather than papered over.
    """
    if sys.platform == "win32":
        return _peak_rss_win32(pid)
    if sys.platform == "linux":  # pragma: no cover -- not the machine this was built on
        return _peak_rss_linux(pid)
    return (  # pragma: no cover -- darwin, which this machine is not
        None,
        "darwin samples with `ps -o rss= -p <pid>` (04-driver-system.md:1751); not run here",
    )


class _JobObjectBasicProcessIdList(ctypes.Structure):
    """`JOBOBJECT_BASIC_PROCESS_ID_LIST` with room for a small fixed number of pids.

    The Win32 struct ends in a variable-length array, which ctypes cannot express directly; the
    idiomatic answer is a struct with a fixed tail and `QueryInformationJobObject` reporting how
    many entries it filled. Sixteen is plenty for the assertion this exists to support -- "is the
    child in the job" -- and `NumberOfAssignedProcesses` still reports the true total, so a job
    with more processes than the tail can hold is visible rather than misreported.
    """

    _fields_ = (
        ("NumberOfAssignedProcesses", ctypes.c_uint32),
        ("NumberOfProcessIdsInList", ctypes.c_uint32),
        ("ProcessIdList", ctypes.c_void_p * 16),
    )


class _JobObjectExtendedLimit(ctypes.Structure):
    """`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, flattened.

    `JOBOBJECT_BASIC_LIMIT_INFORMATION` is inlined rather than nested because the only two fields
    that matter here -- `LimitFlags` and `ProcessMemoryLimit` -- sit on opposite sides of the
    boundary, and one flat struct with explicit padding types is easier to check against
    winnt.h than two nested ones.
    """

    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


_JOB_OBJECT_LIMIT_PROCESS_MEMORY: Final = 0x00000100
"""04-driver-system.md:1750's Windows address-space cap: `JOB_OBJECT_LIMIT_PROCESS_MEMORY`."""

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x00002000
"""What makes a job object the Windows counterpart of :1728's "whole process group reaped": the
tree dies when the last handle closes, so a host that itself dies does not leak grandchildren."""

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9
"""`JobObjectExtendedLimitInformation`, the `JOBOBJECTINFOCLASS` value."""

_JOB_OBJECT_BASIC_PROCESS_ID_LIST: Final = 3
"""`JobObjectBasicProcessIdList`. This is the one that makes the assignment OBSERVABLE."""

_BELOW_NORMAL_PRIORITY_CLASS: Final = 0x00004000
"""04-driver-system.md:1754's Windows priority row: `SetPriorityClass(BELOW_NORMAL)`, which is
`os.nice(10)`'s counterpart and carries graphify's reason -- *"a background rebuild must lose to
the user's editor"* (:1763) -- with the higher stake :1764 names: a VLM parse can allocate
gigabytes and an OOM-killer visit takes the user's editor with it."""


class JobObject:
    """A Windows job object: the address-space cap and the process-tree reap, in one handle.

    Two of 04-driver-system.md:1748-1756's Windows cells are this object and no other mechanism
    is available for either: the address-space cap is `JOB_OBJECT_LIMIT_PROCESS_MEMORY` (there is
    no `setrlimit`), and the *"whole process group"* of :1728 is `KILL_ON_JOB_CLOSE` plus
    `TerminateJobObject` (there are no process groups). `pids()` reads the assignment back, so
    "the child is in the job" is an assertion and not an assumption -- a job object nobody was
    assigned to is the silent failure this class exists to make loud.

    Not available on POSIX, where the same two facts come from `setrlimit` and `os.killpg`; the
    constructor refuses rather than pretending.
    """

    __slots__ = ("_closed", "_handle", "_kernel32")

    def __init__(self, *, memory_limit_bytes: int | None = None) -> None:
        if sys.platform != "win32":  # pragma: no cover -- POSIX
            raise DriverHostError(
                "a job object is the Windows arm; POSIX uses setrlimit and a process group",
                fix="call JobObject only under sys.platform == 'win32'",
            )
        self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise DriverHostError(
                f"CreateJobObjectW failed, GetLastError {self._kernel32.GetLastError()}",
                fix="run without a job object; the shortfall is recorded, not claimed (DR10)",
            )
        self._handle = handle
        self._closed = False
        limits = _JobObjectExtendedLimit()
        limits.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit_bytes is not None:
            limits.LimitFlags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            limits.ProcessMemoryLimit = memory_limit_bytes
        self._kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not ok:
            err = self._kernel32.GetLastError()
            self.close()
            raise DriverHostError(
                f"SetInformationJobObject failed, GetLastError {err}",
                fix="run without a job object; the shortfall is recorded, not claimed (DR10)",
            )

    @property
    def closed(self) -> bool:
        return self._closed

    def assign(self, pid: int) -> None:
        """Put one process into the job. Raises rather than silently not capping it."""
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE: exactly what AssignProcessToJobObject needs.
        proc = self._kernel32.OpenProcess(0x0100 | 0x0001, 0, pid)
        if not proc:
            raise DriverHostError(
                f"OpenProcess({pid}) failed, GetLastError {self._kernel32.GetLastError()}",
                fix="the worker had already exited; treat it as a crash and synthesise",
            )
        try:
            self._kernel32.AssignProcessToJobObject.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            if not self._kernel32.AssignProcessToJobObject(self._handle, proc):
                raise DriverHostError(
                    "AssignProcessToJobObject failed, GetLastError "
                    f"{self._kernel32.GetLastError()}",
                    fix="record address_space_capped = false; DR10 forbids claiming it",
                )
        finally:
            self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle(proc)

    def pids(self) -> tuple[int, ...]:
        """The pids currently assigned. This is what makes `assign()` checkable."""
        info = _JobObjectBasicProcessIdList()
        self._kernel32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        returned = ctypes.c_uint32(0)
        self._kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
            ctypes.byref(info),
            ctypes.sizeof(info),
            ctypes.byref(returned),
        )
        count = min(int(info.NumberOfProcessIdsInList), len(info.ProcessIdList))
        return tuple(int(info.ProcessIdList[i] or 0) for i in range(count))

    def terminate(self, exit_code: int = 1) -> None:
        """`TerminateJobObject` -- the whole tree, uncatchably. :1728's reap, Windows arm."""
        self._kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        """Close the handle. With `KILL_ON_JOB_CLOSE` set, this is itself a reap."""
        if self._closed:
            return
        self._closed = True
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle(self._handle)


def lower_priority(pid: int) -> tuple[bool, str]:
    """`SetPriorityClass(BELOW_NORMAL)` on Windows, `os.nice(10)` nowhere else. Never raises.

    04-driver-system.md:1754 and :1763. Returns `(obtained, how)` so the caller can record the
    shortfall rather than assume the priority; a background parse that did not lose to the
    user's editor is a fact worth having in the row.
    """
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        proc = kernel32.OpenProcess(0x0200, 0, pid)  # PROCESS_SET_INFORMATION
        if not proc:
            return (False, f"OpenProcess({pid}) failed, GetLastError {kernel32.GetLastError()}")
        try:
            kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            ok = bool(kernel32.SetPriorityClass(proc, _BELOW_NORMAL_PRIORITY_CLASS))
            return (ok, "SetPriorityClass(BELOW_NORMAL_PRIORITY_CLASS)")
        finally:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(proc)
    return (  # pragma: no cover -- POSIX, where the child nices itself before exec
        False,
        "os.nice(10) belongs in the child's preexec, not in the parent (04:1754)",
    )


# =============================================================================================
# 9. The transport: an owner-only named pipe here, a 0600 unix socket there
# =============================================================================================

# The `kind` is a HEADER key and `wire.KIND_KEY` is the one spelling of it: this module names it
# nowhere, because 02-architecture.md:238 makes `wire.py` framing's sole home and a second
# constant is a second home for one fact (INV-21). The gap the plan leaves here is worth stating
# once, since a reader of :1670-1676 will look for the kind and not find it: that fence prints the
# frame as `u32 header_len_le | u32 body_len_le | JSON header (UTF-8) | raw body bytes` -- FOUR
# fields, none of which is the kind -- while :1690-1703 numbers eleven kinds and
# 02-architecture.md:831 makes "an unknown frame `kind`" a protocol error. A kind that is a
# protocol error when unknown has to be ON the wire, and the only field it can be in is the JSON
# header, whose printed payload column shows no such key for any of the eleven rows. `wire.py`
# resolves it by carrying the kind's NAME at `wire.KIND_KEY`; the discrepancy is reported rather
# than smoothed, and it is reported by the agent that wrote the framing too.


_PIPE_BUFFER_BYTES: Final = 65_536
"""The kernel's per-direction pipe buffer. An OS hint, NOT a protocol cap.

The protocol caps are `HEADER_LEN_MAX` and `BODY_LEN_MAX` and they are the reader's; this number
only decides how much the kernel will hold before a writer blocks, which is what turns a frame
flood into backpressure at the OS layer as well as at `FRAME_QUEUE_MAX`. Our engineering call,
with no plan claim behind it: 64 KiB is a quarter of `INLINE_MAX`, so a maximal body needs four
kernel round trips and a flood of small frames stalls promptly.
"""

_PIPE_ACCESS_INBOUND: Final = 0x00000001
"""`PIPE_ACCESS_INBOUND`: the host READS this pipe and the driver writes it (`drv->host`)."""

_PIPE_ACCESS_OUTBOUND: Final = 0x00000002
"""`PIPE_ACCESS_OUTBOUND`: the host WRITES this pipe and the driver reads it (`host->drv`).

There is no `PIPE_ACCESS_DUPLEX` here and the reason is a measured Windows fact rather than a
preference -- see `NamedPipeListener`'s docstring. A duplex pipe was the first implementation and
it deadlocks.
"""

_PIPE_REJECT_REMOTE_CLIENTS: Final = 0x00000008
"""Refuse a client from another machine. 02-architecture.md:155 -- *"Never a daemon, never
loopback TCP"* -- is about the transport not being reachable off-box, and a named pipe IS
reachable over SMB unless this flag says otherwise."""

_FILE_FLAG_FIRST_PIPE_INSTANCE: Final = 0x00080000
"""Fail if the pipe name already exists. Without it a squatter that created the name first would
receive our `HELLO`, including `effective_config` and the roots -- so this flag is the half of
"owner-only" that a DACL cannot express."""

_ERROR_PIPE_CONNECTED: Final = 535
"""`ConnectNamedPipe` returning FALSE with this code means the client connected BEFORE the call,
which is success. Treating it as failure is the classic named-pipe race."""

_DUPLICATE_SAME_ACCESS: Final = 0x00000002
"""`DuplicateHandle`'s flag for "same access as the source". The source is the calling thread's
pseudo-handle, whose access is full, so the duplicate can be passed to `CancelSynchronousIo`."""

_TOKEN_QUERY: Final = 0x0008
_TOKEN_USER: Final = 1
_SDDL_REVISION_1: Final = 1


class _SecurityAttributes(ctypes.Structure):
    """`SECURITY_ATTRIBUTES`. `bInheritHandle` is 0: the child gets the pipe by NAME, never by an
    inherited handle, so a grandchild cannot inherit the protocol channel."""

    _fields_ = (
        ("nLength", ctypes.c_uint32),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    )


class _TokenUser(ctypes.Structure):
    """`TOKEN_USER` -- a `SID_AND_ATTRIBUTES`, flattened to its two fields."""

    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32))


def current_user_sid() -> str:
    """The calling user's SID in string form (`S-1-5-21-...`). Windows only.

    Needed because "owner-only" has to be spelled with a real principal. The SDDL aliases that
    look right are not: `CO` (CREATOR OWNER) is substituted only in an INHERITABLE ACE, and `OW`
    (OWNER RIGHTS) is a separate well-known SID rather than "whoever owns this object", so a DACL
    written with either grants nobody access on a non-inheritable object. The token's own user
    SID is the only spelling that means what 02-architecture.md:428's "owner-only" says.
    """
    if sys.platform != "win32":  # pragma: no cover -- POSIX
        raise DriverHostError(
            "a SID is the Windows arm; POSIX names the owner with st_uid and mode 0600",
            fix="call current_user_sid only under sys.platform == 'win32'",
        )
    advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.argtypes = []
    token = ctypes.c_void_p()
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise DriverHostError(
            f"OpenProcessToken failed, GetLastError {kernel32.GetLastError()}",
            fix="run the host as a user whose token can be queried",
        )
    try:
        size = ctypes.c_uint32(0)
        advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, _TOKEN_USER, buffer, size.value, ctypes.byref(size)
        ):
            raise DriverHostError(
                f"GetTokenInformation(TokenUser) failed, {kernel32.GetLastError()}",
                fix="run the host as a user whose token carries a user SID",
            )
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        text = ctypes.c_wchar_p()
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        if not advapi32.ConvertSidToStringSidW(user.Sid, ctypes.byref(text)):
            raise DriverHostError(
                f"ConvertSidToStringSidW failed, {kernel32.GetLastError()}",
                fix="report the SID conversion failure; the pipe cannot be made owner-only",
            )
        try:
            return str(text.value)
        finally:
            kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(token)


def owner_only_sddl(sid: str) -> str:
    """`D:P(A;;GA;;;<sid>)` -- a protected DACL granting GENERIC_ALL to one principal.

    `P` is the load-bearing letter: it sets `SE_DACL_PROTECTED`, so no inherited ACE from
    anywhere can widen the pipe. One ACE, one SID, nothing for Administrators and nothing for
    SYSTEM -- 02-architecture.md:428 says *"owner-only"* and an ACE for a second principal is not
    that, however conventional it looks in a Windows service.
    """
    return f"D:P(A;;GA;;;{sid})"


class ByteChannel(Protocol):
    """A blocking, bidirectional byte stream. The framing is the reader's; this is the pipe.

    `recv` returns fewer bytes than asked for whenever the peer has sent fewer, and `b""` at EOF
    -- the same contract as `socket.recv`, so the unix-socket arm and the named-pipe arm are one
    interface and `read_frame()` is written once.
    """

    def recv(self, size: int) -> bytes: ...

    def sendall(self, data: bytes) -> None: ...

    def close(self) -> None: ...


class FileChannel:
    """ONE DIRECTION of the Windows named-pipe arm, over an `io.FileIO`. Both ends use it.

    The server end arrives as a HANDLE from `CreateNamedPipeW` and becomes an fd through
    `msvcrt.open_osfhandle`, after which the fd OWNS the handle -- which is why
    `NamedPipeListener.accept()` forgets its handles rather than closing them, and why closing
    this channel twice is safe but closing the handle behind it is not.

    A channel is one direction because the pipes are (see `NamedPipeListener`): `recv` on the
    write end and `sendall` on the read end are OS errors rather than protocol errors, and
    `DuplexChannel` is what puts the two halves back together into the `ByteChannel` framing
    expects.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: io.FileIO) -> None:
        self._raw = raw

    @classmethod
    def from_fd(cls, fd: int, *, write: bool) -> FileChannel:
        """Adopt an fd from `msvcrt.open_osfhandle`. The fd owns the handle from here."""
        return cls(io.FileIO(fd, "w" if write else "r", closefd=True))

    @classmethod
    def open(cls, path: str, *, write: bool) -> FileChannel:
        """Open one pipe by NAME -- the child's end.

        `os.open` and not `io.FileIO(path, ...)`, because `FileIO`'s `"w"` adds `O_CREAT` and
        `O_TRUNC`, and `CREATE_ALWAYS` against an existing named pipe is not "open it for
        writing". The flags here are exactly one access bit plus `O_BINARY`, which is what the
        CRT needs on Windows so that a `0x1A` byte in a frame body is not an end of file.
        """
        flags = (os.O_WRONLY if write else os.O_RDONLY) | getattr(os, "O_BINARY", 0)
        return cls(io.FileIO(os.open(path, flags), "w" if write else "r", closefd=True))

    def recv(self, size: int) -> bytes:
        data = self._raw.read(size)
        return b"" if data is None else bytes(data)

    def sendall(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = self._raw.write(view)
            if not written:
                raise DriverHostError(
                    "the transport accepted zero bytes; the worker end is gone",
                    fix="treat the worker as crashed and synthesise driver_crashed",
                )
            view = view[written:]

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._raw.close()


class DuplexChannel:
    """Two one-way `ByteChannel`s presented as one. The Windows arm of the transport.

    Framing wants a bidirectional stream (`wire.Recv` plus a `sendall`) and Windows will not give
    the host one it can use from two threads, so the pair is joined here instead of in the reader.
    `recv` is the `drv->host` pipe and `sendall` is the `host->drv` pipe; neither ever carries the
    other's traffic, and `close()` releases both because a half-closed transport is a worker that
    can still talk and cannot listen.

    The POSIX arm needs none of this: one `AF_UNIX SOCK_STREAM` socket is full duplex and a
    concurrent `recv` and `send` on it do not serialise. That asymmetry is the whole reason this
    class exists and it is recorded rather than hidden.
    """

    __slots__ = ("_read", "_write")

    def __init__(self, *, read: ByteChannel, write: ByteChannel) -> None:
        self._read = read
        self._write = write

    @property
    def read_half(self) -> ByteChannel:
        return self._read

    @property
    def write_half(self) -> ByteChannel:
        return self._write

    def recv(self, size: int) -> bytes:
        return self._read.recv(size)

    def sendall(self, data: bytes) -> None:
        self._write.sendall(data)

    def close(self) -> None:
        try:
            self._read.close()
        finally:
            self._write.close()


class SocketChannel:
    """A `ByteChannel` over a `socket`: the AF_UNIX arm.

    **Written and not exercised.** 02-architecture.md:428 offers *"a 0600 unix socket or an
    owner-only named pipe"* and this machine is Windows 11, where `AF_UNIX` exists in the kernel
    from build 17063 but `socket.AF_UNIX` is absent from CPython on Windows, so the arm cannot
    even be constructed here. `store/crashmatrix.py`'s docstring is the precedent for saying so
    rather than pretending the cell was covered.
    """

    __slots__ = ("_sock",)

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def recv(self, size: int) -> bytes:
        return self._sock.recv(size)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def close(self) -> None:
        with contextlib.suppress(OSError):  # pragma: no cover -- close after close
            self._sock.close()


class Listener(Protocol):
    """The host's end before the worker connects."""

    @property
    def address(self) -> str: ...

    def accept(self, *, timeout_ms: int) -> ByteChannel: ...

    def close(self) -> None: ...


H2D_SUFFIX: Final = "-h2d"
D2H_SUFFIX: Final = "-d2h"
"""The two halves of the Windows transport, by name. See `NamedPipeListener` for WHY there are
two, and `pipe_names()` for the one function both ends derive them with."""


def pipe_names(base: str) -> tuple[str, str]:
    """`(host->driver, driver->host)` for one worker's base address. ONE derivation site.

    Both ends of the protocol need the same two names, and the host is the only one that knows
    the base: it passes the base on the worker's argv and the child derives the pair with this
    function, so a suffix typo is a shared error rather than a silent half-connection.
    """
    return (base + H2D_SUFFIX, base + D2H_SUFFIX)


class _PendingConnect:
    """One `ConnectNamedPipe` on a daemon thread, owning the handle while it is pending.

    Split out of `accept()` because there are now TWO pipes to wait for and the ownership dance
    is the delicate part: the thread that is blocked in `ConnectNamedPipe` is the only party
    allowed to close the handle, since `CloseHandle` on a handle with a pending synchronous
    operation does not return until that operation completes. `give_up()` cancels the wait with
    `CancelSynchronousIo` so the thread ends and the pipe NAME is released; `wait()` reports
    whether the client actually arrived.
    """

    __slots__ = ("_handle", "_listener", "_lock", "_state", "_thread")

    def __init__(self, listener: NamedPipeListener, handle: int, *, name: str) -> None:
        self._listener = listener
        self._handle = handle
        self._lock = threading.Lock()
        self._state: dict[str, object] = {"ok": None, "gave_up": False, "thread": None}
        self._thread = threading.Thread(target=self._run, name=f"ow-s4-accept{name}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        kernel32 = self._listener.kernel32
        with self._lock:
            self._state["thread"] = self._listener.duplicate_current_thread()
        kernel32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        ok = bool(kernel32.ConnectNamedPipe(self._handle, None))
        ok = ok or kernel32.GetLastError() == _ERROR_PIPE_CONNECTED
        with self._lock:
            self._state["ok"] = ok
            orphaned = bool(self._state["gave_up"]) or not ok
            thread_handle = self._state["thread"]
            self._state["thread"] = None
        if orphaned:
            self._listener.close_handle(self._handle)
        if isinstance(thread_handle, int):
            self._listener.close_handle(thread_handle)

    @property
    def handle(self) -> int:
        """The pipe handle. Valid to adopt only after `wait()` returned `True`."""
        return self._handle

    def wait(self, timeout_ms: int) -> bool:
        """Did the client connect within `timeout_ms`?"""
        self._thread.join(max(0.0, timeout_ms / 1000))
        with self._lock:
            return self._state["ok"] is True

    def give_up(self) -> None:
        """Abandon a wait that did not complete. Never blocks; never closes a live connection."""
        with self._lock:
            if self._state["ok"] is True:
                return  # connected after all: the handle belongs to the caller now
            self._state["gave_up"] = True
            thread_handle = self._state["thread"]
            self._state["thread"] = None
        if isinstance(thread_handle, int):
            kernel32 = self._listener.kernel32
            kernel32.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
            kernel32.CancelSynchronousIo(thread_handle)
            self._listener.close_handle(thread_handle)


class NamedPipeListener:
    """TWO owner-only named pipes, one per direction, one instance each. The Windows arm of S4.

    ## Why two, when 02-architecture.md:428 says "an owner-only named pipe"

    Because one does not work, and the failure is a deadlock rather than an error. A named pipe
    created without `FILE_FLAG_OVERLAPPED` is a SYNCHRONOUS handle, and Windows serialises
    operations on a synchronous handle: while one thread has a `ReadFile` pending, another
    thread's `WriteFile` on the same handle waits for it. `FrameReader` exists precisely to keep
    a blocking read parked on a thread (mechanism 4 in the module docstring, and G23 forbids the
    selector that would replace it), so with one duplex pipe every `Worker.send` blocked behind
    the reader's parked read and the handshake never completed. Measured on Windows 11: a host
    with a `recv(8)` pending never completed an 8-byte `sendall` on the same handle.

    So the transport is `<base>-h2d` (`PIPE_ACCESS_OUTBOUND`, the host writes) and `<base>-d2h`
    (`PIPE_ACCESS_INBOUND`, the host reads). Each handle is used in exactly one direction by
    exactly one thread, so nothing serialises against anything. `DuplexChannel` joins them and
    every layer above it -- `wire`, `FrameReader`, `Worker` -- is unchanged.

    **This is a Windows-only shape and the POSIX arm keeps the plan's literal one.** An
    `AF_UNIX SOCK_STREAM` socket is full duplex and a concurrent `recv`/`send` on it does not
    serialise, so `UnixSocketListener` is one socket, as :428 says. The alternative that would
    have kept one pipe here is `FILE_FLAG_OVERLAPPED` plus an event object per operation, which
    is a genuinely different I/O model for the whole reader; two pipes is the smaller change and
    is reported as an amendment owed to :428's cell rather than treated as what it says.

    ## The four security properties, which both pipes carry

    * `nMaxInstances = 1` -- one client per pipe, so a second process cannot join the
      conversation after the worker has;
    * `FILE_FLAG_FIRST_PIPE_INSTANCE` -- creation FAILS if the name is taken, so a process that
      guessed the name and created it first does not receive our `HELLO` (which carries
      `effective_config`, `roots` and `blob_base`). A DACL cannot express this: the squatter's
      pipe would carry the squatter's DACL;
    * `PIPE_REJECT_REMOTE_CLIENTS` -- a named pipe is reachable over SMB by default, and
      02-architecture.md:155's *"never a daemon, never loopback TCP"* is a statement about
      reachability rather than about protocol choice;
    * a protected DACL with exactly one ACE, for the calling user's own SID -- see
      `owner_only_sddl`.

    ## The deadline, and the cleanup that was a hang

    `accept()` bounds each `ConnectNamedPipe` with a deadline by running it on a daemon thread
    and joining with a timeout, because a blocking `ConnectNamedPipe` cannot be interrupted
    without overlapped I/O and an unbounded wait for a child that never starts is exactly the
    hang section 6.5 forbids. The two waits are sequential and each gets the full `timeout_ms`,
    so a worker that connects to neither pipe costs at most `2 x timeout_ms` -- the waiters run
    concurrently, so the typical cost is one. That bound is stated rather than assumed.

    The first version of this class then hung in `close()`, and it is worth recording why: a
    timed-out `accept()` leaves the waiter parked INSIDE `ConnectNamedPipe`, which is a pending
    synchronous I/O on the handle, and `CloseHandle` on such a handle does not return until the
    operation completes. A bounded refusal whose cleanup is unbounded is not a bounded refusal.
    `_PendingConnect` owns the handle for exactly that reason, and `CancelSynchronousIo` is what
    ends the parked wait -- best effort by contract, since it returns `ERROR_NOT_FOUND` when the
    I/O has already completed, which is the benign race with a worker connecting one millisecond
    after the deadline. That worker finds a closed pipe, and the host reads the death as a crash
    it can synthesise: a row, not a hang.
    """

    __slots__ = ("_handles", "_kernel32", "_name", "_sd")

    def __init__(self, name: str, *, sddl: str | None = None) -> None:
        if sys.platform != "win32":  # pragma: no cover -- POSIX
            raise DriverHostError(
                "a named pipe is the Windows arm of S4; POSIX uses a 0600 unix socket",
                fix="call listener_for(), which picks the arm for the platform",
            )
        if not name.startswith("\\\\.\\pipe\\"):
            raise DriverHostError(
                rf"{name!r} is not a local pipe name; it must start with \\.\pipe\ ",
                fix=r"pass a name under \\.\pipe\, which is local-only by construction",
            )
        self._name = name
        self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._sd = self._descriptor(sddl)
        self._handles: dict[str, int] = {}
        h2d, d2h = pipe_names(name)
        try:
            self._handles[H2D_SUFFIX] = self._create(h2d, _PIPE_ACCESS_OUTBOUND)
            self._handles[D2H_SUFFIX] = self._create(d2h, _PIPE_ACCESS_INBOUND)
        except DriverHostError:
            self.close()
            raise

    def _descriptor(self, sddl: str | None) -> ctypes.c_void_p:
        """The SECURITY_DESCRIPTOR both pipes carry, from one SDDL string."""
        advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
        descriptor = ctypes.c_void_p()
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        text = sddl if sddl is not None else owner_only_sddl(current_user_sid())
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text, _SDDL_REVISION_1, ctypes.byref(descriptor), None
        ):
            raise DriverHostError(
                f"SDDL {text!r} did not convert, GetLastError {self._kernel32.GetLastError()}",
                fix="report the SDDL; the pipe cannot be created owner-only",
            )
        return descriptor

    def _create(self, name: str, access: int) -> int:
        """One pipe, one direction, one instance, owner-only, local-only."""
        attributes = _SecurityAttributes()
        attributes.nLength = ctypes.sizeof(attributes)
        attributes.lpSecurityDescriptor = self._sd
        attributes.bInheritHandle = 0
        self._kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        self._kernel32.CreateNamedPipeW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        handle = self._kernel32.CreateNamedPipeW(
            name,
            access | _FILE_FLAG_FIRST_PIPE_INSTANCE,
            _PIPE_REJECT_REMOTE_CLIENTS,  # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT = 0
            1,
            _PIPE_BUFFER_BYTES,
            _PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(attributes),
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise DriverHostError(
                f"CreateNamedPipeW({name!r}) failed, GetLastError {self._kernel32.GetLastError()}",
                fix="choose a pipe name nothing else holds; FIRST_PIPE_INSTANCE refuses a taken",
            )
        return int(handle)

    @property
    def address(self) -> str:
        """The BASE name. `pipe_names()` derives the two the worker actually opens."""
        return self._name

    @property
    def kernel32(self) -> ctypes.WinDLL:  # type: ignore[name-defined]
        """The `kernel32` binding, for `_PendingConnect`. Not a public surface."""
        return self._kernel32

    def _free_descriptor(self) -> None:
        if self._sd:
            self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            self._kernel32.LocalFree(self._sd)
            self._sd = ctypes.c_void_p()

    def close_handle(self, handle: int) -> None:
        """`CloseHandle`, once. Only ever called with no I/O pending on `handle`."""
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle(handle)

    def duplicate_current_thread(self) -> int | None:
        """A real handle for the calling thread, for `CancelSynchronousIo`.

        `GetCurrentThread()` returns the pseudo-handle `-2`, which names "the calling thread"
        and is therefore useless to another thread; `DuplicateHandle` turns it into a real one.
        Returns `None` rather than raising: failing to obtain a cancel handle costs the
        cancellation, and the ownership transfer in `accept()` already bounds `close()`.
        """
        kernel32 = self._kernel32
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.DuplicateHandle.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        duplicate = ctypes.c_void_p()
        process = kernel32.GetCurrentProcess()
        ok = kernel32.DuplicateHandle(
            process,
            kernel32.GetCurrentThread(),
            process,
            ctypes.byref(duplicate),
            0,
            0,
            _DUPLICATE_SAME_ACCESS,
        )
        if not ok or not duplicate.value:  # pragma: no cover -- a same-process duplicate
            return None
        return int(duplicate.value)

    def accept(self, *, timeout_ms: int) -> ByteChannel:
        """Wait for the one client on BOTH pipes, at most `timeout_ms` each. Never a hang.

        Ownership of each handle moves to its `_PendingConnect` before any wait begins, so every
        exit -- both connects, one connect, neither, an exception -- leaves exactly one closer.
        See the class docstring for why that is not tidiness.
        """
        if not self._handles:
            raise DriverHostError(
                "this listener has already accepted or been closed",
                fix="create one listener per worker; nMaxInstances is 1",
            )
        if msvcrt is None:  # pragma: no cover -- win32 implies msvcrt
            raise DriverHostError(
                "msvcrt is absent on a win32 interpreter",
                fix="report the interpreter build; the named-pipe arm needs open_osfhandle",
            )
        handles = self._handles
        self._handles = {}  # the pendings own them from here; close() has nothing to close
        pending = {
            suffix: _PendingConnect(self, handle, name=suffix) for suffix, handle in handles.items()
        }
        connected = {suffix: item.wait(timeout_ms) for suffix, item in pending.items()}
        if not all(connected.values()):
            for item in pending.values():
                item.give_up()
            self._free_descriptor()
            missing = sorted(suffix for suffix, ok in connected.items() if not ok)
            raise DriverHostError(
                f"no worker connected to {self._name}{missing} within {timeout_ms} ms",
                fix="check the worker argv; the spawn is in the ledger row for this invoke",
            )
        write_fd = msvcrt.open_osfhandle(pending[H2D_SUFFIX].handle, 0)
        read_fd = msvcrt.open_osfhandle(pending[D2H_SUFFIX].handle, 0)
        self._free_descriptor()
        return DuplexChannel(
            read=FileChannel.from_fd(read_fd, write=False),
            write=FileChannel.from_fd(write_fd, write=True),
        )

    def close(self) -> None:
        """Free the descriptor and any handle this listener still owns. Never blocks.

        After `accept()` every handle belongs to a `_PendingConnect` or to the returned
        channel's fds, so the loop below is the "created and never accepted" case only.
        """
        self._free_descriptor()
        for suffix in tuple(self._handles):
            self.close_handle(self._handles.pop(suffix))


class UnixSocketListener:
    """A `SOCK_STREAM` `AF_UNIX` socket at mode 0600. The POSIX arm of S4.

    **Written and not exercised here.** `socket.AF_UNIX` does not exist on CPython for Windows,
    so this class cannot be constructed on the machine W3.2 was built on, and the test that would
    cover it skips with that reason rather than being written to pass vacuously.

    The 0600 is applied with `os.chmod` after `bind` and BEFORE `listen`, and the order is the
    whole point: a socket that is listening at mode 0777 for even one scheduler quantum is a
    socket any local process may connect to, and 02-architecture.md:428's "0600" is a claim about
    the whole life of the socket. The stronger form -- a 0700 parent directory -- is the caller's,
    because the path is a parameter here (no `os.getcwd()`, no `tempfile` default: both are
    ambient inputs banned in library code).
    """

    __slots__ = ("_path", "_sock")

    def __init__(self, path: str) -> None:
        family = getattr(socket, "AF_UNIX", None)
        if family is None:  # pragma: no cover -- exercised on this machine, which IS win32
            raise DriverHostError(
                "socket.AF_UNIX is absent on this platform; the named-pipe arm is the one here",
                fix="call listener_for(), which picks the arm for the platform",
            )
        self._path = path
        self._sock = socket.socket(family, socket.SOCK_STREAM)
        self._sock.bind(path)
        os.chmod(path, 0o600)  # noqa: PTH101 -- before listen(); see the class docstring
        self._sock.listen(1)

    @property
    def address(self) -> str:
        return self._path

    def accept(self, *, timeout_ms: int) -> ByteChannel:  # pragma: no cover -- POSIX
        self._sock.settimeout(timeout_ms / 1000)
        try:
            conn, _ = self._sock.accept()
        except (TimeoutError, OSError) as exc:
            raise DriverHostError(
                f"no worker connected to {self._path} within {timeout_ms} ms: {exc}",
                fix="check the worker argv; the spawn is in the ledger row for this invoke",
            ) from exc
        conn.settimeout(None)
        return SocketChannel(conn)

    def close(self) -> None:  # pragma: no cover -- POSIX
        try:
            self._sock.close()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(self._path)  # noqa: PTH108 -- a socket path, not a document path


def listener_for(address: str) -> Listener:
    """The arm for this platform: a named pipe on Windows, a unix socket everywhere else.

    One function so that no caller writes the platform test twice, and so the two arms of
    02-architecture.md:428 have exactly one selection site.
    """
    if sys.platform == "win32":
        return NamedPipeListener(address)
    return UnixSocketListener(address)  # pragma: no cover -- POSIX


def _open_pipe(name: str, *, write: bool, timeout_ms: int) -> FileChannel:
    """Open one pipe by name, retrying until `timeout_ms`. A bounded refusal, never a spin.

    The retry exists because the child races the host: `CreateNamedPipeW` and
    `ConnectNamedPipe` are two calls on the host's side, and a child that got scheduled between
    them sees `ERROR_FILE_NOT_FOUND`. Polling every 50 ms for a bounded number of attempts is
    the shape `subprocess`-free code can take here -- `threading.Event().wait` and not
    `time.sleep`, so that the wait is a synchronisation primitive rather than a busy loop, and no
    clock is read at all.
    """
    for _ in range(max(1, timeout_ms // 50)):
        try:
            return FileChannel.open(name, write=write)
        except OSError:
            threading.Event().wait(0.05)
    raise DriverHostError(
        f"the worker could not open {name} within {timeout_ms} ms",
        fix="the host closed the listener; nothing to connect to",
    )


def connect(address: str, *, timeout_ms: int = KILL_GRACE_MS) -> ByteChannel:
    """The WORKER's end. Called in the child, which is why it is here and not in a `tools/` file.

    14-security.md:867 gives the worker bootstrap obligations this function does not discharge --
    the audit hook goes on before `activate()` imports the driver's module -- but the connect
    itself is pure protocol and belongs beside the framing that both ends share. A worker with
    its own copy of the frame layout is how two ends of one protocol drift.
    """
    if sys.platform == "win32":
        h2d, d2h = pipe_names(address)
        # The read half first, because the host writes `HELLO` as soon as both halves are up and
        # a child holding only the write half would have nowhere to read it from.
        read = _open_pipe(h2d, write=False, timeout_ms=timeout_ms)
        try:
            write = _open_pipe(d2h, write=True, timeout_ms=timeout_ms)
        except DriverHostError:
            read.close()
            raise
        return DuplexChannel(read=read, write=write)
    family = getattr(socket, "AF_UNIX", None)  # pragma: no cover -- POSIX
    if family is None:  # pragma: no cover -- unreachable off win32
        raise DriverHostError(
            "no AF_UNIX and not win32: there is no S4 transport on this platform",
            fix="report the platform; S4 needs a unix socket or a named pipe",
        )
    sock = socket.socket(family, socket.SOCK_STREAM)  # pragma: no cover -- POSIX
    sock.settimeout(timeout_ms / 1000)  # pragma: no cover -- POSIX
    sock.connect(address)  # pragma: no cover -- POSIX
    sock.settimeout(None)  # pragma: no cover -- POSIX
    return SocketChannel(sock)  # pragma: no cover -- POSIX


# =============================================================================================
# 10. The reader that does not oblige a hostile driver
# =============================================================================================


def next_frame(
    channel: ByteChannel, *, expect: wire.Direction = wire.Direction.DRIVER_TO_HOST
) -> wire.Frame | None:
    """One frame from a worker, or `None` at a CLEAN end of stream.

    The whole of this function is the distinction `wire.read_frame` cannot make and must not:
    a zero-byte read at a frame boundary is a worker that exited, and a zero-byte read PART WAY
    through a frame is a truncation. Framing sees both as a short read and refuses -- correctly,
    since a clean exit is a lifecycle fact and framing has no lifecycle. So the prefix is read
    here first: nothing at all means `None`, which becomes `synthesise_crash`; anything at all is
    handed to `wire.read_frame` through a shim that serves the bytes already in hand, so there is
    exactly ONE implementation of the frame grammar in the process.

    `expect` is the direction check, and it is not decoration: a worker that sends `INVOKE` is
    confused or hostile, and a host that read one would be taking dispatch orders from a third
    party's process (04-driver-system.md:1693's direction column, `wire.Direction`). It defaults
    to the HOST's half of the conversation and the WORKER passes the other -- one function, two
    ends, because a worker with its own copy of the frame grammar is how two ends of one protocol
    drift (14-security.md:867 gives the worker bootstrap a home in this module for that reason).
    """
    recv = _exact(channel)
    prefix = recv(wire.PREFIX_BYTES)
    if not prefix:
        return None
    pending = prefix

    def shim(size: int) -> bytes:
        nonlocal pending
        if pending:
            taken, pending = pending[:size], pending[size:]
            return taken
        return recv(size)

    return wire.read_frame(shim, expect=expect)


class _Terminal(NamedTuple):
    """The reader thread's last word: a clean EOF, or the protocol error that stopped it."""

    error: DriverHostError | None


class FrameReader:
    """A reader thread and a BOUNDED queue. The half of section 6.5 that is about memory.

    04-driver-system.md:1793 is one row and this class is all of it: *"the host reads into a
    bounded queue, `frame_queue_max = 256`. A full queue means the host **stops reading**; pipe
    backpressure stalls the driver, and `wall_ms_hard` fires. No frame is buffered on the host's
    behalf."* The mechanism is `Queue(maxsize=FRAME_QUEUE_MAX)` and a thread that blocks in
    `put()`: once the queue is full the thread is not reading, the kernel pipe buffer fills, the
    driver's own `write` blocks, and the only clock still running is the host's.

    **Why a thread and not a selector.** G23: core imports neither `asyncio` nor `selectors`, and
    the single event loop lives in `omniweave/run/` (INV-3). A blocking read on a daemon thread
    plus a bounded queue gives the supervisor a `get(timeout=...)` it can put a deadline on,
    which is what section 6.5 actually requires -- and it works identically over a named pipe,
    where a deadline on the read itself would need overlapped I/O.

    The thread is a daemon and is never joined on the deadline path: a `recv` blocked on a silent
    child cannot be interrupted, so the supervisor kills the child and the read returns EOF on
    its own. `depth()` exists for the flood test -- a queue that never exceeds its bound is the
    assertion, and it needs an observer.
    """

    __slots__ = ("_channel", "_queue", "_thread")

    def __init__(self, channel: ByteChannel, *, maxsize: int = FRAME_QUEUE_MAX) -> None:
        self._channel = channel
        self._queue: queue.Queue[wire.Frame | _Terminal] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._pump, name="ow-s4-reader", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            while True:
                frame = next_frame(self._channel)
                if frame is None:
                    self._queue.put(_Terminal(error=None))
                    return
                self._queue.put(frame)
        except DriverHostError as exc:
            self._queue.put(_Terminal(error=exc))
        except (OSError, ValueError) as exc:
            # A closed or reset transport is an EOF with a reason, never a host traceback: the
            # crash synthesis is what turns it into a row (02-architecture.md:1060). `ValueError`
            # is in the tuple because that is what `io.FileIO` raises when the channel is closed
            # UNDER a blocked reader ("I/O operation on closed file"), which is the ordinary end
            # of the kill path -- `Worker.kill()` closes the transport while this thread is
            # parked in `recv`. Letting it escape printed a traceback from a daemon thread into
            # the middle of the host's own report, which is the shape of an unhandled bug and not
            # of a worker that was killed on purpose.
            self._queue.put(_Terminal(error=None))
            del exc

    def depth(self) -> int:
        """How many frames are queued. The flood test's observer; never a control input."""
        return self._queue.qsize()

    def get(self, *, timeout_ms: int) -> wire.Frame | _Terminal | None:
        """One queued frame, the terminal, or `None` if `timeout_ms` passed with neither.

        `None` is not an error and not an EOF -- it is "nothing yet", and the supervisor's answer
        to it is to look at the three deadlines. That separation is why a silent driver produces
        a `TIMEOUT` naming `progress_ms` rather than a generic read failure.
        """
        try:
            return self._queue.get(timeout=max(0.0, timeout_ms / 1000))
        except queue.Empty:
            return None

    def alive(self) -> bool:
        return self._thread.is_alive()


# =============================================================================================
# 11. The spawn, and the discipline the semgrep exemption comes with
# =============================================================================================


class WorkerKey(NamedTuple):
    """`(driver_id, config_digest)` -- the pool's ONLY key, and a correctness property.

    02-architecture.md:85, :482, :677 and :831 all state it as one worker per this pair.
    `config_digest` is `omniweave_core.identity.config_digest`'s 64-char hex over the resolved
    config and is never recomputed here: two spellings of one digest is how a cache serves one
    configuration's work under another's settings (INV-21, I26).

    Note what is NOT in the key: the cost class, the isolation mode and the `dispatch_key`.
    `dispatch_key = sha256(driver ‖ config_digest ‖ isolation)[:16]` (02-architecture.md:479) is
    the QUEUE's batching key and has a third component; the worker key has two, because a
    worker's identity is what it loaded and how it was configured. Conflating them would give one
    driver two workers for one configuration whenever the isolation grant differed by a shortfall.
    """

    driver_id: str
    config_digest: str


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    """Everything a spawn needs, with nothing ambient. `cwd` has NO DEFAULT.

    The semgrep rule that exempts this file says what the ban is for and `cwd` is its first item:
    *"no `cwd=` is passed -- graphify #2316 ran `git rev-parse HEAD` without `cwd=` and stamped
    the invoking repo's commit into the target's graph"*. A `cwd` with a default would be the
    process's own working directory, which is the ambient input `os.getcwd()` is separately
    banned for, so the field is required and a caller that does not know where the worker should
    run cannot spawn one.

    `env` is a complete mapping and not an overlay: an inherited environment carries the host's
    `PYTHONPATH`, its proxy variables and its tokens into a third party's process. `argv` is a
    tuple because `shell=False` is not negotiable (04-driver-system.md:1098) and a string argv is
    how a shell gets involved by accident.
    """

    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    address: str

    def __post_init__(self) -> None:
        if not self.argv:
            raise DriverHostError(
                "a spawn with no argv",
                fix="pass the driver's [driver] exec argv, or the interpreter plus the bootstrap",
            )
        if not self.cwd:
            raise DriverHostError(
                "SpawnRequest.cwd is empty: a child with no declared cwd inherits ours",
                fix="pass the worker's working directory explicitly; never os.getcwd()",
            )


class WorkerProcess(Protocol):
    """The three things the host does to a child, and the one thing it asks.

    A Protocol, so the pool is testable without a process: every lifecycle test below runs
    against a fake that counts spawns and reports exit statuses on command. `subprocess.Popen`
    satisfies it as written, which is the point -- there is no adapter.
    """

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[[SpawnRequest], WorkerProcess]
"""How a worker comes into being. INJECTED, always.

The spawn is a parameter for the same reason the clock is: a test that cannot vary it can only be
written against the real thing, and 5,600 tests that each fork a Python interpreter is not a
suite anybody runs. `spawn_worker` below is the one real implementation.
"""


def spawn_worker(request: SpawnRequest, *, stderr: StderrRing, stdout: StderrRing) -> WorkerProcess:
    """`subprocess.Popen`, with every argument the semgrep message asks for.

    `stdout` and `stderr` are captured into rings and never parsed (04-driver-system.md:1683:
    *"stdout and stderr are captured, logged at debug and never parsed"*, because *"'stdout is
    protocol only' is a discipline rather than a mechanism and an MCP server's stderr banner
    renders at error level"*). They are DRAINED by two daemon threads rather than left in the
    kernel buffer, because a child that fills its stderr pipe blocks in `write` and then looks
    exactly like a hang -- a 64 KiB buffer is roughly one Python traceback away from that.

    `stdin` is `DEVNULL`: the protocol is the pipe, and a driver that reads stdin expecting input
    should see EOF rather than the host's terminal.
    """
    proc = subprocess.Popen(  # noqa: S603 -- argv is a tuple, shell=False, cwd is explicit
        list(request.argv),
        cwd=request.cwd,
        env=dict(request.env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
    )
    for stream, ring in ((proc.stdout, stdout), (proc.stderr, stderr)):
        if stream is None:  # pragma: no cover -- PIPE was requested for both
            continue
        threading.Thread(
            target=_drain, args=(stream, ring), name="ow-s4-drain", daemon=True
        ).start()
    return proc


def _drain(stream: object, ring: StderrRing) -> None:
    """Pump one captured stream into its bounded ring until EOF, then CLOSE it. Never raises.

    The close is not tidiness. `subprocess.PIPE` gives the parent one file object per captured
    stream, and a run that spawns a worker per `(driver_id, config_digest)` and reaps them at
    `worker_idle_ttl_s` would leak two of them per worker for the length of the run -- which on
    Windows is two handles the trampoline's grandchild also holds, and under
    `filterwarnings = ["error"]` is a `ResourceWarning` that fails a test suite. The ring already
    holds every byte anybody will read (04-driver-system.md:1683: *"captured, logged at debug and
    never parsed"*), so the file object has no reader left once EOF has arrived.
    """
    try:
        while True:
            chunk = stream.read(4096)  # type: ignore[attr-defined]
            if not chunk:
                return
            ring.feed(chunk)
    except (OSError, ValueError):  # pragma: no cover -- the pipe closed under us
        return
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()  # type: ignore[attr-defined]


class Captured(NamedTuple):
    """One finished child: exit status, both streams in full, and why it failed to run if it did.

    `returncode` is `None` when there is no status to report -- the spawn itself failed, or the
    child outlived `timeout_s` and was killed. `failed` then names the exception class and never
    its message, for the reason `envelope.Outcome.failed` gives: a message carries paths.
    """

    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    failed: str = ""


def run_captured(
    argv: Sequence[str],
    *,
    stdin: bytes,
    cwd: str,
    env: Mapping[str, str],
    timeout_s: float,
) -> Captured:
    """Run `argv` to completion with `stdin` piped in and both streams captured. Never raises.

    The one synchronous run-and-capture in the framework, and it is here because this file and
    `toolchain.py` are the only two `TID251` allows to import `subprocess`. Its first caller is
    `ow hooks check` (10 section 8.7), which must *"execute the installed command string"* as a host
    would -- a real child, piped stdio, the host's argv -- and read back what it printed.

    `shell=False` and an argv, never a string: the caller has already split the command the way the
    host's shell would, and resolving the executable is the caller's job because *that* is the
    thing being checked. `(OSError, ValueError)` is 10:2072's pair -- `ValueError` covers a NUL byte
    in an argument, which a command string read from a settings file can carry.
    """
    try:
        done = subprocess.run(  # noqa: S603 -- argv is a sequence, shell=False, cwd is explicit
            list(argv),
            input=stdin,
            capture_output=True,
            cwd=cwd,
            env=dict(env),
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return Captured(None, bytes(exc.stdout or b""), bytes(exc.stderr or b""), "TimeoutExpired")
    except (OSError, ValueError) as exc:
        return Captured(None, failed=type(exc).__name__)
    return Captured(done.returncode, done.stdout, done.stderr)


def synthesise_crash(proc: WorkerProcess, ring: StderrRing, *, wait_ms: int = 0) -> HostVerdict:
    """The exit status plus the tail of the stderr ring, and nothing else.

    02-architecture.md:831 and :1060, 04-driver-system.md:1723 and 08-runtime.md:569 all say the
    same sentence: *"A worker that dies **without** a frame yields `driver_crashed` synthesised
    from the exit status plus the last 4 KiB of the stderr ring."* This function is that
    sentence, and it exists as a named site so the sentence is greppable.

    **`wait_ms` is why this is not one line, and the reason is a measured race.** What the host
    OBSERVES is an EOF on the transport, and 04:1727's detector is *"`waitpid` returns a signal
    or a non-zero exit"* -- a different event, which happens slightly later: the child's pipe
    ends are closed by the kernel when it dies, and the parent learns the status when it reaps.
    A single `poll()` at EOF therefore returns `None` often enough to matter -- it did on every
    run of `tools/ow_host.py`'s `crash` scenario under a launcher trampoline, where the process
    the host holds is a shim that outlives its own child by a few milliseconds -- and a verdict
    *"synthesised from the exit status"* whose status is `None` has synthesised nothing. So the
    host waits, bounded by `wait_ms`, which callers pass as ONE supervisor tick
    (`HostSettings.tick_ms`, 04-driver-system.md:1769's 250 ms wake) rather than as a new number.

    A `None` that survives the wait is kept as `None` and said out loud in the message: an EOF
    from a child that is still running is a worker that closed its own transport, which is a
    protocol fault rather than a crash, and the kill path is what then supplies a status.

    On POSIX `Popen.returncode` is NEGATIVE for a signalled child (`-11` is `SIGSEGV`), which is
    what makes 04:1727's detector one number rather than two. On Windows there are no signals and
    `TerminateProcess`'s exit code is whatever the killer passed, so the same field means "how it
    died" on both platforms while meaning something different in detail: that asymmetry is
    recorded here and not smoothed, and it is why the message prints the raw status rather than
    interpreting it.
    """
    status = proc.poll()
    if status is None and wait_ms > 0:
        try:
            status = proc.wait(timeout=wait_ms / 1000)
        except subprocess.TimeoutExpired:
            status = None
    return HostVerdict.crashed(exit_status=status, stderr_tail=ring.tail())


# =============================================================================================
# 12. The invocation, and what came back
# =============================================================================================


class HelloAck(NamedTuple):
    """`HELLO_ACK{driver_id, version, schema_version, port, code_fingerprint}` --
    04-driver-system.md:1696's five keys, and `isolation_granted` echoed back per DR10."""

    driver_id: str
    version: str
    schema_version: int
    port: str
    code_fingerprint: str
    isolation_granted: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Invocation:
    """`INVOKE{invoke_id, units, deadline_ms, budget_micros}` -- 04-driver-system.md:1699's four
    keys and no others. NOT 08-runtime.md's `Batch`; see the module docstring.

    **`body` is singular, and that is a gap in the printed grammar.** :1699 says the units are a
    LIST and that *"a unit's bytes ride in the body"*, while :1674's frame is one header and ONE
    body with no offset table. Two units with inline bytes therefore cannot both ride in one
    `INVOKE`: concatenating them is unrecoverable without offsets, and an offset key would be
    grammar this module is not entitled to invent. So `__post_init__` refuses a batch with more
    than one inline body and names the gap, which is the fail-closed direction: above
    `INLINE_MAX` the plan already sends a `blob_ref` per unit (:1679), and a batch of blob refs
    has no ambiguity at all.
    """

    invoke_id: str
    units: tuple[UnitRef, ...]
    deadline_ms: int
    budget_micros: int
    body: bytes = b""
    inline_unit_index: int | None = None
    blob_refs: tuple[str | None, ...] = ()

    def __post_init__(self) -> None:
        if self.blob_refs and len(self.blob_refs) != len(self.units):
            raise DriverHostError(
                f"{len(self.blob_refs)} blob_refs for {len(self.units)} units",
                fix="one blob_ref per unit, None where the unit's bytes ride in the body",
            )
        if not self.units:
            raise DriverHostError(
                "an INVOKE with no units",
                fix="claim at least one work row before dispatching a batch",
            )
        if self.body and self.inline_unit_index is None:
            raise DriverHostError(
                "an INVOKE body with no inline_unit_index: one body cannot be attributed to a "
                "list of units (04-driver-system.md:1674 vs :1699)",
                fix="name the unit whose bytes ride in the body, or send blob refs for all",
            )
        if self.inline_unit_index is not None and not 0 <= self.inline_unit_index < len(self.units):
            raise DriverHostError(
                f"inline_unit_index {self.inline_unit_index} is outside the batch of "
                f"{len(self.units)}",
                fix="index the unit whose bytes ride in the body, zero-based",
            )
        if len(self.body) > wire.MAX_BODY_BYTES:
            raise DriverHostError(
                f"an INVOKE body of {len(self.body)} bytes is over INLINE_MAX "
                f"{wire.MAX_BODY_BYTES}",
                fix="put the unit in the CAS and send a blob_ref instead of the bytes",
            )

    def as_header(self) -> Mapping[str, object]:
        """:1699's four keys, plus the two additions this module owns and names.

        The four are `invoke_id`, `units`, `deadline_ms` and `budget_micros`, and the `kind` is
        `wire.encode`'s to insert (`wire.KIND_KEY` is reserved). Two things here are NOT on
        :1699 and both are stated rather than slipped in:

        * **`inline_unit_index`** exists because :1674's frame has ONE body and :1699's `units`
          is a LIST -- the gap the class docstring argues. Without it a batch with inline bytes
          cannot say whose bytes those are, and inventing an offset table would be more grammar
          than naming the one unit that may carry a body.
        * **`byte_len` on each unit.** :1699 prints `{uri, part, content_sha256, blob_ref?}`;
          `byte_len` is `omniweave_ports.types.UnitRef`'s fourth field (04-driver-system.md:195-196)
          and is sent because a worker that must bound its own read of a blob needs the length
          before it opens it.
        * **`blob_ref`**, :1699's own optional key, sent when the caller staged the unit's bytes
          in the CAS -- which the parse Operator always does (D582). At W3.2 it was absent because
          nothing could populate it; `blob_refs` is how a caller that can says so.
        * **`media_type`**, `UnitRef`'s fifth field. A CSV has no signature (the office driver's
          own `sniff` says so), so the unit's detected media type is the only evidence a driver has
          for it, and a worker that dropped it would decode every CSV as unrecognised (D583).

        All four are reported as amendments owed to :1699 rather than treated as settled.
        """
        return {
            "invoke_id": self.invoke_id,
            "units": [
                {
                    "uri": unit.uri,
                    "part": unit.part,
                    "content_sha256": unit.content_sha256,
                    "byte_len": unit.byte_len,
                    "media_type": unit.media_type,
                    **(
                        {"blob_ref": self.blob_refs[index]}
                        if self.blob_refs and self.blob_refs[index] is not None
                        else {}
                    ),
                }
                for index, unit in enumerate(self.units)
            ],
            "deadline_ms": self.deadline_ms,
            "budget_micros": self.budget_micros,
            "inline_unit_index": self.inline_unit_index,
        }


@dataclass(frozen=True, slots=True)
class InvokeReport:
    """One `INVOKE`'s outcome, per unit, plus the AIMD event the batch earned.

    `results` and `failures` are parallel to `Invocation.units` and exactly one of each pair is
    populated: 04-driver-system.md:1715 requires **one `RESULT` per unit**, so a unit with
    neither is a unit the worker never answered for and gets the synthesised crash. `event` is
    the `BatchEvent` the dispatcher feeds `adapt_batch`; `logs` and `progress_count` are what
    the observability path takes, and `progress_count` is here because "PROGRESS is the only
    frame that resets `progress_ms`" is only checkable if somebody counted them.
    """

    results: tuple[DriverResult | None, ...]
    failures: tuple[HostVerdict | None, ...]
    event: BatchEvent
    logs: tuple[Mapping[str, object], ...] = ()
    progress_count: int = 0

    def unanswered(self) -> tuple[int, ...]:
        """The unit indices with neither a result nor a failure. Empty on a complete batch."""
        return tuple(
            i
            for i, (ok, bad) in enumerate(zip(self.results, self.failures, strict=True))
            if ok is None and bad is None
        )


class _Awaited(NamedTuple):
    """What one supervisor tick produced: a frame, a verdict, or neither (keep waiting)."""

    frame: wire.Frame | None
    verdict: HostVerdict | None


# =============================================================================================
# 13. The worker
# =============================================================================================


class Worker:
    """One long-lived child, its channel, its reader thread and its three deadlines.

    Long-lived is the point: 12-performance.md:723 prices the fork/exec plus the driver import
    plus the model load as *"the single largest fixed cost in the pipeline, at 21x the in-process
    call it wraps"*, which is why `worker_idle_ttl_s = 300` exists and why the key is the
    configuration rather than the invocation.

    The supervisor loop is one method, `_await_frame`, and everything else is a caller of it. It
    does three things per tick and there is exactly one tick rate in the process
    (04-driver-system.md:1769): take at most one frame off the bounded queue, re-check the three
    deadlines, and -- when a memory cap is in force -- sample RSS. A tick that finds nothing is
    not an error; it is the only place a silent driver can be noticed.
    """

    __slots__ = (
        "_channel",
        "_job",
        "_key",
        "_last_used_ms",
        "_now_ms",
        "_proc",
        "_reader",
        "_settings",
        "_stderr",
        "_stopped",
    )

    def __init__(
        self,
        key: WorkerKey,
        proc: WorkerProcess,
        channel: ByteChannel,
        *,
        settings: HostSettings,
        now_ms: Callable[[], int],
        stderr: StderrRing,
        job: JobObject | None = None,
    ) -> None:
        self._key = key
        self._proc = proc
        self._channel = channel
        self._settings = settings
        self._now_ms = now_ms
        self._stderr = stderr
        self._job = job
        self._reader = FrameReader(channel)
        self._last_used_ms = now_ms()
        self._stopped = False

    @property
    def key(self) -> WorkerKey:
        return self._key

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def last_used_ms(self) -> int:
        return self._last_used_ms

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def reader(self) -> FrameReader:
        return self._reader

    def touch(self) -> None:
        """Mark the worker used now. What `worker_idle_ttl_s` is measured from."""
        self._last_used_ms = self._now_ms()

    def send(self, kind: wire.FrameKind, header: Mapping[str, object], body: bytes = b"") -> None:
        """Write one host->drv frame. Refuses a drv->host kind: the direction is grammar.

        `wire.encode` applies the caps on the way out and inserts `wire.KIND_KEY` itself, so the
        header passed in here is the PAYLOAD only -- and `wire.encode` refuses a header that
        already holds the key, which is what keeps the kind in exactly one place per frame.
        """
        if kind not in wire.HOST_TO_DRIVER:
            raise DriverHostError(
                f"{kind.name} is a drv->host frame and the host may not send it",
                fix="send HELLO, PROBE, INVOKE, CANCEL or SHUTDOWN",
            )
        self._channel.sendall(wire.encode(kind, dict(header), body))  # type: ignore[arg-type]

    def _await_frame(self, countdown: Countdown, *, memory_mb: int = 0) -> _Awaited:
        """One tick: at most one frame, or the verdict of a deadline or the watchdog.

        **The deadline is checked BEFORE the queue is read, and that order is the whole of
        04-driver-system.md:1794.** The obvious order is the other one -- take a frame that is
        already queued, then look at the clock, so a driver that finished a millisecond before
        its deadline is not killed for the scheduler's latency -- and this module shipped it
        that way first. It is wrong, and a `LOG` flood is the proof: while frames keep arriving
        the queue is never empty, the frame branch returns on every call, and the clock is never
        consulted. `wall_ms_hard` then never fires, which is exactly the attack :1794 answers --
        *"a `PROGRESS` flood to hold the worker alive | `progress_ms` resets, but `wall_ms_hard`
        does not, and it is the backstop. A driver cannot extend its own wall clock."* A driver
        that can hold the supervisor in a loop HAS extended its own wall clock.

        So the tick is: the clock, then one frame, then the clock again (because the wait may
        have consumed most of the remaining budget), then the watchdog. The cost of the leading
        check is three integer comparisons -- `Countdown.expired` reads no clock of its own -- so
        the spin a flood produces stays cheap while staying bounded. What it gives up is the
        millisecond of courtesy: a `RESULT` that was queued while the deadline elapsed is not
        read, and the invocation is `FAILED_PERMANENT{TIMEOUT}`. That is the right trade twice
        over -- the host cannot distinguish a frame that arrived just before its deadline from
        one that arrived just after, and a superseded result *"writes nothing"* anyway
        (04-driver-system.md:1741, the generation predicate).

        RSS is sampled only on a tick that found nothing, which keeps the flood spin free of a
        per-frame `OpenProcess`; 04-driver-system.md:1769 puts the sampler on the supervisor's
        250 ms wake and that wake is this branch.
        """
        now = self._now_ms()
        fired = countdown.expired(now)
        if fired is not None:
            return _Awaited(
                frame=None,
                verdict=HostVerdict.timed_out(fired, elapsed_ms=countdown.elapsed_ms(now)),
            )
        item = self._reader.get(timeout_ms=countdown.wait_ms(now, tick_ms=self._settings.tick_ms))
        if isinstance(item, wire.Frame):
            return _Awaited(frame=item, verdict=None)
        if isinstance(item, _Terminal):
            if item.error is not None:
                raise item.error
            return _Awaited(
                frame=None,
                # One tick to reap: see synthesise_crash's docstring for the race this closes.
                verdict=synthesise_crash(self._proc, self._stderr, wait_ms=self._settings.tick_ms),
            )
        now = self._now_ms()
        fired = countdown.expired(now)
        if fired is not None:
            return _Awaited(
                frame=None,
                verdict=HostVerdict.timed_out(fired, elapsed_ms=countdown.elapsed_ms(now)),
            )
        if memory_mb > 0:
            observed, _how = peak_rss_bytes(self._proc.pid)
            if observed is not None and observed > memory_mb * 1_048_576:
                return _Awaited(
                    frame=None,
                    verdict=HostVerdict.over_memory(observed_bytes=observed, cap_mb=memory_mb),
                )
        return _Awaited(frame=None, verdict=None)

    def hello(
        self,
        header: Mapping[str, object],
        *,
        expect: Mapping[str, object],
        deadlines: Deadlines,
    ) -> HelloAck:
        """`HELLO`, then `HELLO_ACK` checked against the card BEFORE any work.

        02-architecture.md:482 and 04-driver-system.md:1696: *"any mismatch against the card is
        `CARD_CODE_MISMATCH` before work"*, and codes.toml's `OW-D-073 OW_CARD_CODE_MISMATCH`
        says why it is checked twice -- *"an `inproc` driver has no `HELLO_ACK`, an `exec` driver
        has no importable class, and a `subproc` worker may be a different build than the card
        the host read from disk"*. This is the third of those cases and the only one that can
        see a wheel that does not match its own `driver.toml`.
        """
        self.send(wire.FrameKind.HELLO, header)
        countdown = Countdown(deadlines, started_ms=self._now_ms())
        while True:
            awaited = self._await_frame(countdown)
            if awaited.verdict is not None:
                raise DriverHostError(
                    f"the worker did not answer HELLO: {awaited.verdict.message}",
                    fix="check the worker bootstrap; nothing has been dispatched to it",
                )
            frame = awaited.frame
            if frame is None:
                continue
            if frame.kind is wire.FrameKind.LOG:
                countdown.note_log(self._now_ms())
                continue
            if frame.kind is not wire.FrameKind.HELLO_ACK:
                raise DriverHostError(
                    f"the worker answered HELLO with {frame.kind.name}",
                    fix="kill the worker; the handshake is not negotiable",
                )
            ack = HelloAck(
                driver_id=str(frame.header.get("driver_id", "")),
                version=str(frame.header.get("version", "")),
                schema_version=int(frame.header.get("schema_version", -1)),  # type: ignore[arg-type]
                port=str(frame.header.get("port", "")),
                code_fingerprint=str(frame.header.get("code_fingerprint", "")),
                isolation_granted=MappingProxyType(
                    dict(frame.header.get("isolation_granted", {}) or {})  # type: ignore[arg-type]
                ),
            )
            mismatched = tuple(
                name for name, wanted in expect.items() if getattr(ack, name, None) != wanted
            )
            if mismatched:
                detail = ", ".join(
                    f"{name}: card {expect[name]!r} != worker {getattr(ack, name, None)!r}"
                    for name in mismatched
                )
                raise DriverHostError(
                    f"HELLO_ACK disagrees with the card on {detail}",
                    symbol="OW_CARD_CODE_MISMATCH",
                    fix="reinstall the driver so the wheel and its driver.toml are one build",
                )
            self.touch()
            return ack

    def invoke(
        self, invocation: Invocation, *, deadlines: Deadlines, memory_mb: int = 0
    ) -> InvokeReport:
        """One `INVOKE`, one `RESULT` per unit, and a verdict for every unit that gets none.

        The loop is the whole of section 6.3 and section 6.5's `RESULT` row:

        * `RESULT` -- `unit_index` is validated against the batch and out of range KILLS the
          worker (04-driver-system.md:1796: *"a protocol error and the worker is killed, not
          trusted"*). A `RESULT` carrying `failure_class` is a driver-reported failure and is
          carried through `HostVerdict.from_driver` without re-classification (02:1060);
        * `PROGRESS` -- the ONE frame that resets `progress_ms`;
        * `LOG` -- structured only, and resets nothing;
        * `FATAL` -- the driver's last words. Every unit still unanswered takes it, because a
          worker that has said `FATAL` will not answer them;
        * EOF or a dead child -- `synthesise_crash`, attributed to the FIRST unanswered unit.
          04:1721 puts the death on **one** unit and the retry at `batch = 1` is what localises
          which; the host does not guess, it names the earliest candidate and lets
          `retry_batch_size` do the localisation.
        """
        self.touch()
        count = len(invocation.units)
        results: list[DriverResult | None] = [None] * count
        failures: list[HostVerdict | None] = [None] * count
        logs: list[Mapping[str, object]] = []
        progress = 0
        event = BatchEvent.CLEAN
        self.send(wire.FrameKind.INVOKE, invocation.as_header(), invocation.body)
        countdown = Countdown(deadlines, started_ms=self._now_ms())
        while any(r is None and f is None for r, f in zip(results, failures, strict=True)):
            awaited = self._await_frame(countdown, memory_mb=memory_mb)
            if awaited.verdict is not None:
                event = _assign_verdict(results, failures, awaited.verdict)
                break
            frame = awaited.frame
            if frame is None:
                continue
            if frame.kind is wire.FrameKind.PROGRESS:
                countdown.note_progress(self._now_ms())
                progress += 1
                continue
            if frame.kind is wire.FrameKind.LOG:
                countdown.note_log(self._now_ms())
                logs.append(frame.header)
                continue
            if frame.kind is wire.FrameKind.FATAL:
                event = _assign_verdict(results, failures, _fatal_verdict(frame))
                break
            if frame.kind is not wire.FrameKind.RESULT:
                raise DriverHostError(
                    f"{frame.kind.name} is not a frame a worker may send during an INVOKE",
                    fix="kill the worker; the direction and the phase are both grammar",
                )
            index = _unit_index(frame, count=count, worker=self)
            outcome, verdict = _result_of(frame)
            results[index] = outcome
            failures[index] = verdict
            if verdict is not None:
                event = _event_for(verdict)
        self.touch()
        return InvokeReport(
            results=tuple(results),
            failures=tuple(failures),
            event=event,
            logs=tuple(logs),
            progress_count=progress,
        )

    def cancel(self, invoke_id: str, *, generation: int) -> None:
        """`CANCEL{invoke_id, generation}` -- cancellation propagates BY GENERATION, not by signal.

        04-driver-system.md:1738-1741 and :2658. The commit predicate is
        `WHERE id=:id AND claimed_gen=:gen AND status='claimed'`, so a superseded result **writes
        nothing** and a driver that ignores `cancelled()` still meets `wall_ms_hard`. That is why
        this method neither waits for an acknowledgement nor kills anything: the correctness of
        cancellation does not depend on the driver's cooperation, only its promptness.
        """
        self.send(wire.FrameKind.CANCEL, {"invoke_id": invoke_id, "generation": generation})

    def stop(self, *, grace_ms: int = KILL_GRACE_MS) -> int | None:
        """`SHUTDOWN{grace_ms}`, then the uncatchable step. Returns the exit status.

        04-driver-system.md:1728's ladder is *"SIGTERM, SIGKILL at +5 s, the whole process group
        reaped"*. On Windows the catchable half is the FRAME and not a signal, because
        `Popen.terminate()` is already `TerminateProcess` and cannot be caught -- see the module
        docstring. So: send `SHUTDOWN`, wait up to `grace_ms` for the child to exit on its own,
        then `TerminateJobObject` (which takes the grandchildren) or `Popen.kill()`.
        """
        if self._stopped:
            return self._proc.poll()
        self._stopped = True
        # A dead channel needs no goodbye; the uncatchable step below is the mechanism.
        with contextlib.suppress(DriverHostError, OSError):
            self.send(wire.FrameKind.SHUTDOWN, {"grace_ms": grace_ms})
        try:
            status = self._proc.wait(timeout=grace_ms / 1000)
        except subprocess.TimeoutExpired:
            return self.kill()
        # The child is gone, so the reader thread has already seen EOF and no read is pending on
        # the channel -- which is the precondition for closing it without blocking (see
        # `NamedPipeListener.accept`'s docstring for the version of this that was a hang).
        # `reap_idle()` drops the worker straight after `stop()`, so this is the only site that
        # can release the transport on the graceful path.
        self.close()
        return status

    def kill(self) -> int | None:
        """The uncatchable step, and the whole tree with it."""
        self._stopped = True
        if self._job is not None:
            self._job.terminate()
        else:
            with contextlib.suppress(OSError):  # pragma: no cover -- already reaped
                self._proc.kill()
        try:
            status = self._proc.wait(timeout=KILL_GRACE_MS / 1000)
        except subprocess.TimeoutExpired:  # pragma: no cover -- TerminateProcess does not fail
            status = None
        self.close()
        return status

    def close(self) -> None:
        """Release the channel and the job handle. Idempotent."""
        self._channel.close()
        if self._job is not None and not self._job.closed:
            self._job.close()


def _assign_verdict(
    results: list[DriverResult | None],
    failures: list[HostVerdict | None],
    verdict: HostVerdict,
) -> BatchEvent:
    """Attribute one host verdict to the units that never got a `RESULT`. Returns the AIMD event.

    Two shapes, and the difference is 04-driver-system.md:1721's word "one": a synthesised
    `driver_crashed` lands on **one** unit -- *"The death is `FAILED_PERMANENT{DRIVER_CRASHED}`
    on one unit"* -- and the earliest unanswered index is the one named, because the retry at
    `batch = 1` is what actually localises the poison unit. Every other verdict (a timeout, an
    OOM, a `FATAL`) lands on ALL the unanswered units, because none of them will now be answered
    and a unit with neither result nor failure would be a work row nothing ever transitions.
    """
    single = verdict.failure_class is FailureClass.DRIVER_CRASHED
    for index in range(len(results)):
        if results[index] is None and failures[index] is None:
            failures[index] = verdict
            if single:
                break
    return _event_for(verdict)


def _event_for(verdict: HostVerdict) -> BatchEvent:
    """The `BatchEvent` a verdict projects onto. 08-runtime.md:762's "projection, not a taxonomy".

    Only three of the thirteen `FailureClass` members move the batch size, and the mapping is
    stated rather than inferred: `driver_crashed` goes to 1, `resource_limit` halves, and
    everything else -- a timeout included -- leaves the batch alone, because a smaller batch does
    not make a hanging driver finish.
    """
    if verdict.failure_class is FailureClass.DRIVER_CRASHED:
        return BatchEvent.DRIVER_CRASHED
    if verdict.failure_class is FailureClass.RESOURCE_LIMIT:
        return BatchEvent.RESOURCE_LIMIT
    return BatchEvent.CLEAN


def _unit_index(frame: wire.Frame, *, count: int, worker: Worker) -> int:
    """`unit_index`, validated against the batch. Out of range kills the worker.

    04-driver-system.md:1796, in its own words: *"`unit_index` is validated against the batch;
    out of range is a protocol error and the worker is killed, not trusted."* The kill happens
    HERE, before the raise propagates, because a worker that has just claimed a unit outside its
    own batch is a worker whose next frame is not worth reading.
    """
    raw = frame.header.get(RESULT_UNIT_INDEX_KEY)
    if not isinstance(raw, int) or isinstance(raw, bool) or not 0 <= raw < count:
        worker.kill()
        raise DriverHostError(
            f"RESULT carried unit_index {raw!r} for a batch of {count}",
            fix="kill the worker; a RESULT for a unit outside the INVOKE is not trusted",
        )
    return raw


def _result_of(frame: wire.Frame) -> tuple[DriverResult | None, HostVerdict | None]:
    """A `RESULT` frame's payload: a `DriverResult`, or the driver's own reported failure.

    02-architecture.md:1060: the worker serialises *"the five `DriverError` fields --
    `failure_class`, message, `retry_after_ms`, `pages`, `limit` -- into the `RESULT` header"*.

    **`produced` IS reconstructed here, from the header's `produced` list and the frame's one
    body (D583).** At W3.2 it was not, on the argument that `ArtifactRef.of()` is the single site
    that meters `io.max_output_bytes` (04-driver-system.md:1795) and a ref built from a header key
    would evade the meter. The meter still runs where 04:1795 puts it -- inside the worker, on
    the host's number, which `HELLO` now carries -- and what this function adds is the host-side
    re-check a hostile worker cannot skip: every ref is built through `ArtifactRef`'s own
    constructor (the closed kind vocabulary, `cas://` spelling, `INLINE_MAX`), at most one is
    inline and its `byte_len` must equal the body exactly, and `produced_total` is summed for the
    caller to hold against the ceiling. `worker.produced_header()` is the other end.

    **Every construction here is wrapped, because the types raise `ValueError` and a hostile
    worker is entitled to try it.** `DriverError.__post_init__` enforces charter D3's
    "`retry_after_ms` REQUIRED iff transient" and `DriverResult.__post_init__` enforces
    "`ok_partial` requires `partial_reason`", so a `RESULT` header carrying
    `failure_class = "timeout"` with no cooldown, or `outcome = "ok_partial"` with no reason, is
    a `ValueError` out of a ports constructor -- an UNNAMED error crossing the seam, which is
    exactly what section 6.5 forbids ("the assertion is a bounded refusal"). It is a
    `DriverHostError` here for the same reason `wire.py` raises one: 02-architecture.md:1060
    attributes a protocol fault at this seam to US, and a `TypeError` from `int()` over a header
    value the driver chose would say nothing about which frame was wrong.
    """
    failure = frame.header.get("failure_class")
    if failure is not None:
        try:
            cls = FailureClass(failure)
        except ValueError as exc:
            raise DriverHostError(
                f"{failure!r} is not one of the thirteen FailureClass members",
                fix="kill the worker; a failure class outside the closed set is a protocol error",
            ) from exc
        retry = frame.header.get("retry_after_ms")
        pages = frame.header.get("pages") or ()
        limit = frame.header.get("limit")
        try:
            error = DriverError(
                cls=cls,
                message=str(frame.header.get("message", "")),
                retry_after_ms=None if retry is None else int(retry),  # type: ignore[arg-type]
                pages=tuple(int(page) for page in pages),  # type: ignore[union-attr]
                limit=None if limit is None else str(limit),
            )
        except (TypeError, ValueError) as exc:
            raise DriverHostError(
                f"a RESULT reporting {cls.value} does not satisfy DriverError: {exc}",
                fix="kill the worker; charter D3 requires retry_after_ms iff the class is "
                "transient, and the worker's own top-level handler owes that field",
            ) from exc
        return (None, HostVerdict.from_driver(error))
    outcome = str(frame.header.get("outcome", "ok"))
    if outcome not in ("ok", "ok_partial"):
        raise DriverHostError(
            f"RESULT outcome {outcome!r} is not one of 'ok', 'ok_partial'",
            fix="kill the worker; INV-7 gives a driver exactly those two outcomes",
        )
    reason = frame.header.get("partial_reason")
    produced = _produced_of(frame)
    try:
        result = DriverResult(
            outcome="ok_partial" if outcome == "ok_partial" else "ok",
            produced=produced,
            partial_reason=None if reason is None else str(reason),
            metrics=_metrics_of(frame.header.get("metrics")),
        )
    except ValueError as exc:
        raise DriverHostError(
            f"a RESULT claiming {outcome!r} does not satisfy DriverResult: {exc}",
            fix="kill the worker; ok_partial without partial_reason is not a result",
        ) from exc
    return (result, None)


def _produced_of(frame: wire.Frame) -> tuple[ArtifactRef, ...]:
    """`RESULT.produced` as `ArtifactRef`s, the one inline body attributed by position. D583.

    Every refusal is a `DriverHostError`, never a `ValueError` out of the ports constructor, for
    `_result_of`'s reason: a protocol fault at this seam is attributed to us (02:1060).
    """
    raw = frame.header.get("produced") or []
    if not isinstance(raw, list):
        raise DriverHostError(
            "RESULT.produced is not a list",
            fix="kill the worker; produced is [{kind, byte_len, blob | inline}]",
        )
    refs: list[ArtifactRef] = []
    inline_seen = False
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise DriverHostError(
                "a RESULT.produced entry is not a table",
                fix="kill the worker; produced is [{kind, byte_len, blob | inline}]",
            )
        byte_len = entry.get("byte_len")
        if not isinstance(byte_len, int) or isinstance(byte_len, bool):
            raise DriverHostError(
                f"a RESULT.produced byte_len is {byte_len!r}",
                fix="kill the worker; byte_len is the ref's length in bytes",
            )
        inline = entry.get("inline") is True
        if inline and inline_seen:
            raise DriverHostError(
                "two RESULT.produced entries claim the one frame body",
                fix="kill the worker; at most one produced ref rides inline (D583)",
            )
        if inline and byte_len != len(frame.body):
            raise DriverHostError(
                f"the inline ref declares {byte_len} bytes and the body is {len(frame.body)}",
                fix="kill the worker; an inline ref's byte_len is the body's length",
            )
        inline_seen = inline_seen or inline
        try:
            refs.append(
                ArtifactRef(
                    kind=str(entry.get("kind", "")),
                    byte_len=byte_len,
                    inline=frame.body if inline else None,
                    blob=None if inline else str(entry.get("blob", "")),
                )
            )
        except ValueError as exc:
            raise DriverHostError(
                f"a RESULT.produced entry is not an ArtifactRef: {exc}",
                fix="kill the worker; the kind vocabulary and the cas:// spelling are closed",
            ) from exc
    if frame.body and not inline_seen:
        raise DriverHostError(
            f"a RESULT body of {len(frame.body)} bytes that no produced entry claims",
            fix="kill the worker; a body belongs to the one inline ref",
        )
    return tuple(refs)


def produced_total(result: DriverResult) -> int:
    """The bytes one result's refs declare, summed: the host's re-check of 04:1795's ceiling."""
    return sum(ref.byte_len for ref in result.produced)


_METRIC_FIELDS: Final = (
    "wall_ms",
    "cpu_ms",
    "gpu_ms",
    "tokens_in",
    "tokens_out",
    "calls",
    "bytes_egress",
    "bytes_read",
    "peak_rss_bytes",
)
"""`DriverMetrics`' nine physical units, in its own order. PHYSICAL UNITS ONLY: no micros."""


def _metrics_of(raw: object) -> DriverMetrics:
    """`RESULT.metrics` as `DriverMetrics`, a non-integer or negative field read as zero.

    Zero rather than a refusal because a metric is a report and never a control input: a worker
    that mis-states its own `wall_ms` has lied about itself, and the host's own clocks are what
    `with_metrics` records (08:842). Keys outside the nine are ignored -- there is no `cost_micros`
    to read even if a worker sends one (INV-15).
    """
    if not isinstance(raw, Mapping):
        return DriverMetrics()
    values: dict[str, int] = {}
    for name in _METRIC_FIELDS:
        value = raw.get(name, 0)
        ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        values[name] = value if ok else 0  # type: ignore[assignment]
    return DriverMetrics(**values)


def _fatal_verdict(frame: wire.Frame) -> HostVerdict:
    """`FATAL{failure_class, detail}` -- the driver's last words, 04-driver-system.md:1705.

    A `FATAL` with an unknown class is `driver_bug` rather than a protocol error: the frame is
    well formed and the driver is telling us it is broken, which is exactly what `driver_bug`
    means. That is the one place this module downgrades a vocabulary violation instead of
    killing, and the reason is that the alternative attributes a dying driver's last words to
    our own protocol layer.
    """
    raw = frame.header.get("failure_class")
    try:
        cls = FailureClass(raw)
    except ValueError:
        cls = FailureClass.DRIVER_BUG
    detail = str(frame.header.get("detail", ""))
    return HostVerdict(
        failure_class=cls,
        message=f"FATAL: {detail}" if detail else "FATAL with no detail",
        permanent=True,
        detected_by="driver",
    )


# =============================================================================================
# 14. The pool: one worker per key, `max_workers` per cost class, `worker_idle_ttl_s`
# =============================================================================================


class WorkerPool:
    """The run's workers, keyed on `(driver_id, config_digest)`, reaped at `worker_idle_ttl_s`.

    Run-scoped and never a daemon (02-architecture.md:155, :677, 08-runtime.md:2590). The pool
    holds the crash ledger because the crash is observed here, and it does NOT hold a gate:

    * **`acquire()` does not refuse a quarantined driver.** That refusal is
      `omniweave_core.drivers.resolve`'s nineteenth gate and `RejectCode.QUARANTINED` is its
      code; a second refusal here would be a second home for one decision (INV-21) and the two
      could disagree about a driver mid-run. The pool PRODUCES `quarantined()`; the router
      consumes it and re-plans (02-architecture.md:831).
    * **`acquire()` does not implement an admission semaphore.** `Admission.worker_sem` is
      08-runtime.md:670-685's and P4's. What the pool does is REFUSE a spawn that would exceed
      `max_workers` for the cost class, naming the knob -- because 08-runtime.md:704 says the
      analogous RAM check is *"a **refusal** naming `[drivers] max_workers`"* and that *"a
      silent clamp would hide the fact that ..."* an operator's number had become a lie. A pool
      that quietly spawned a fifth `free` worker under `max_workers.free = 4` would be exactly
      that lie.

    `reap_idle()` is called by the same supervisor tick as everything else. The TTL is measured
    from `last_used_ms` -- the end of the last `INVOKE`, not the spawn -- because the cost the
    TTL is trading against is the model load (12-performance.md:723), which a busy worker has
    already paid.
    """

    __slots__ = ("_ledger", "_now_ms", "_settings", "_spawn", "_workers")

    def __init__(
        self,
        *,
        spawn: Spawn,
        settings: HostSettings,
        now_ms: Callable[[], int],
        ledger: CrashLedger | None = None,
    ) -> None:
        self._spawn = spawn
        self._settings = settings
        self._now_ms = now_ms
        self._workers: dict[WorkerKey, tuple[Worker, str]] = {}
        self._ledger = ledger or CrashLedger(
            threshold=settings.crash_threshold, window_s=settings.crash_window_s
        )

    @property
    def ledger(self) -> CrashLedger:
        return self._ledger

    def live_keys(self) -> tuple[WorkerKey, ...]:
        """The keys with a worker right now, in insertion order. The pool's whole state."""
        return tuple(self._workers)

    def live_count(self, cost_class: str) -> int:
        return sum(1 for _, klass in self._workers.values() if klass == cost_class)

    def get(self, key: WorkerKey) -> Worker | None:
        """The existing worker for this key, or `None`. No spawn, no side effect."""
        entry = self._workers.get(key)
        return None if entry is None else entry[0]

    def acquire(
        self,
        key: WorkerKey,
        *,
        cost_class: str,
        build: Callable[[], Worker],
    ) -> Worker:
        """The worker for this key: the existing one, or a new one from `build`.

        `build` rather than a `SpawnRequest` because a worker is a spawn AND a listener AND an
        accept AND a `HELLO` exchange, and only the caller knows the card. What the pool owns is
        the KEY -- that a second configuration never shares the first's worker -- and the
        capacity refusal.
        """
        existing = self._workers.get(key)
        if existing is not None and not existing[0].stopped:
            existing[0].touch()
            return existing[0]
        cap = self._settings.max_workers.get(cost_class)
        if cap is None:
            raise DriverHostError(
                f"{cost_class!r} is not a cost class in [drivers] max_workers "
                f"{sorted(self._settings.max_workers)}",
                fix="name free, local_compute or billed_api",
            )
        if self.live_count(cost_class) >= cap:
            raise DriverHostError(
                f"{cost_class} already has {cap} worker processes and [drivers] max_workers "
                f"caps it there; refusing rather than clamping silently",
                fix=f"raise [drivers] max_workers.{cost_class}, or wait for a worker to idle out",
            )
        worker = build()
        if worker.key != key:
            raise DriverHostError(
                f"build() returned a worker keyed {worker.key} for {key}",
                fix="build the worker for the key you asked for; the key is a correctness bound",
            )
        self._workers[key] = (worker, cost_class)
        return worker

    def note_crash(self, driver_id: str) -> bool:
        """Record one crash against the DRIVER. Returns whether it is now quarantined.

        Keyed on `driver_id` and not on `WorkerKey`: 04-driver-system.md:1727 quarantines *"the
        **driver** -- not the unit -- for the run"*, and a driver that segfaults under one
        configuration has not thereby earned trust under another.
        """
        return self._ledger.record(driver_id, now_ms=self._now_ms())

    def quarantined(self) -> frozenset[str]:
        """The set to hand `omniweave_core.drivers.resolve.Policy(quarantined=...)`."""
        return self._ledger.quarantined()

    def reap_idle(self) -> tuple[WorkerKey, ...]:
        """Stop every worker idle for longer than `worker_idle_ttl_s`. Returns what was reaped.

        Strictly greater than the TTL, so a worker used exactly `worker_idle_ttl_s` ago survives
        one more tick. The boundary is arbitrary in itself and is pinned by a test so that it
        cannot drift silently: 300 s is 08-runtime.md:2590's number and the comparison is ours.
        """
        now = self._now_ms()
        cutoff = self._settings.worker_idle_ttl_s * 1000
        reaped: list[WorkerKey] = []
        for key, (worker, _klass) in list(self._workers.items()):
            if now - worker.last_used_ms > cutoff:
                worker.stop()
                del self._workers[key]
                reaped.append(key)
        return tuple(reaped)

    def discard(self, key: WorkerKey) -> None:
        """Forget a worker the caller has already killed. The crash path's bookkeeping."""
        entry = self._workers.pop(key, None)
        if entry is not None:
            entry[0].close()

    def close(self) -> None:
        """End of run. Every worker gets the frame, then the uncatchable step."""
        for key in list(self._workers):
            worker, _klass = self._workers.pop(key)
            worker.stop()


# =============================================================================================
# 15. One live worker: listen, spawn, contain, accept, HELLO
# =============================================================================================

WORKER_MODULE: Final = "omniweave_core.host.worker"
"""The bootstrap `python -m` runs. `host/worker.py` is the child's half of S4 (D581)."""

ACCEPT_MS: Final = 30_000
"""How long the host waits for a spawned worker to open both pipes. An interpreter start plus
`omniweave_core`'s import is well under a second here; thirty is for a cold disk, and a worker
that never connects is refused by `NamedPipeListener.accept`, naming the pipe, rather than
waited on."""


def worker_argv(executable: str, address: str) -> tuple[str, ...]:
    """`(python, -m, omniweave_core.host.worker, <base address>)`. The address is the argv's last
    element because `pipe_names` derives both pipe names from it on the child's side."""
    return (executable, "-m", WORKER_MODULE, address)


def launch(
    key: WorkerKey,
    request: SpawnRequest,
    *,
    hello: Mapping[str, object],
    expect: Mapping[str, object],
    deadlines: Deadlines,
    settings: HostSettings,
    now_ms: Callable[[], int],
    memory_mb: int = 0,
    spawn: Callable[..., WorkerProcess] = spawn_worker,
    accept_ms: int = ACCEPT_MS,
) -> tuple[Worker, HelloAck]:
    """A `Worker` that has answered `HELLO`, or a raise with the child already reaped.

    `WorkerPool.acquire()` takes this as its `build`: its docstring says *"a worker is a spawn AND
    a listener AND an accept AND a `HELLO` exchange, and only the caller knows the card"*, and this
    is those four in the one order that works. The listener exists before the spawn, because the
    child connects on its first line and a pipe that does not exist yet is `could not open`. The
    job object is created and the child assigned before the accept, so the address-space cap is in
    force before the child has read a frame. Every failure path kills the child: a half-started
    worker nobody holds is an orphan process with the driver's code loaded.

    On POSIX there is no job object and the cap is `setrlimit` in the child, which the bootstrap
    does not yet apply; `address_space_capped` is reported false there, as DR10 requires.
    """
    listener = listener_for(request.address)
    stderr = StderrRing()
    try:
        proc = spawn(request, stderr=stderr, stdout=StderrRing())
    except BaseException:
        listener.close()
        raise
    job: JobObject | None = None
    try:
        if sys.platform == "win32":
            job = JobObject(memory_limit_bytes=memory_mb * 1_048_576 if memory_mb > 0 else None)
            job.assign(proc.pid)
        channel = listener.accept(timeout_ms=accept_ms)
    except BaseException:
        listener.close()
        with contextlib.suppress(OSError):
            proc.kill()
        if job is not None:
            job.close()
        raise
    listener.close()
    worker = Worker(key, proc, channel, settings=settings, now_ms=now_ms, stderr=stderr, job=job)
    try:
        ack = worker.hello(hello, expect=expect, deadlines=deadlines)
    except BaseException:
        worker.kill()
        raise
    return worker, ack


__all__ = [
    "ACCEPT_MS",
    "AIMD_RECOVERY_STREAK",
    "CONTROLS_BY_PLATFORM",
    "FAILURE_MODES",
    "FRAME_QUEUE_MAX",
    "KILL_GRACE_MS",
    "LIMIT_NAMES",
    "RESULT_UNIT_INDEX_KEY",
    "STDERR_RING_BYTES",
    "WORKER_MODULE",
    "AimdState",
    "BatchEvent",
    "ByteChannel",
    "Captured",
    "Countdown",
    "CrashLedger",
    "Deadlines",
    "DuplexChannel",
    "FailureMode",
    "FileChannel",
    "FrameReader",
    "HelloAck",
    "HostSettings",
    "HostVerdict",
    "Invocation",
    "InvokeReport",
    "IsolationGranted",
    "IsolationShortfall",
    "JobObject",
    "Listener",
    "NamedPipeListener",
    "PlatformControls",
    "SocketChannel",
    "Spawn",
    "SpawnRequest",
    "StderrRing",
    "UnixSocketListener",
    "Worker",
    "WorkerKey",
    "WorkerPool",
    "WorkerProcess",
    "adapt_batch",
    "connect",
    "current_user_sid",
    "grant_isolation",
    "launch",
    "listener_for",
    "lower_priority",
    "next_frame",
    "owner_only_sddl",
    "peak_rss_bytes",
    "pipe_names",
    "produced_total",
    "retry_batch_size",
    "run_captured",
    "spawn_worker",
    "synthesise_crash",
    "worker_argv",
]
