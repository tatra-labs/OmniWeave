"""Seam S4 -- the worker lifecycle, the reader that does not oblige, and the Windows cells.

`host/subproc.py` is 02-architecture.md:428's seam and 04-driver-system.md sections 6.2-6.6 are
its specification. Every clause of the S4 row at 02-architecture.md:831 is a test here, and the
families below say which clause and what would break if the test were weaker.

**Why some of this file spawns real processes.** `import subprocess` is banned by ruff's TID251
outside `omniweave_core.toolchain` and `host/subproc.py`, and this file takes that escape the way
`tests/unit/test_gate_crash.py` takes it: the ban's scope is `packages/*/src/**`, and three of the
properties here cannot be observed without a real child --

1. **the transport.** An owner-only named pipe with `FILE_FLAG_FIRST_PIPE_INSTANCE`,
   `PIPE_REJECT_REMOTE_CLIENTS` and a one-ACE DACL is a Win32 object, and a fake channel proves
   nothing about it. The round trip here connects a real client to a real listener;
2. **`cwd=`.** The semgrep rule that exempts `host/subproc.py` says what the ban is FOR, and its
   first item is that graphify #2316 ran `git rev-parse HEAD` without `cwd=` and stamped the
   invoking repo's commit into the target's graph. The only way to show that our spawn passes
   `cwd` is to spawn a child that reports its own working directory;
3. **the reap.** 04-driver-system.md:1728 says *"the whole process group"* reaped, and Windows has
   no process groups. `JobObject.pids()` reading the assignment back, and a killed grandchild, are
   both facts about live processes.

Everything else runs against fakes -- `FakeProcess`, `FakeChannel`, `Clock` -- because a suite
that forked an interpreter per deadline would not be run.

## The families

* **the grammar has one home.** `wire.py` owns the eleven kinds, the three caps and the `kind`
  header key, and this file asserts that no module-level constant in `subproc.py` re-spells any of
  them. That test is here because a duplicate `KIND_KEY` shipped in the first draft of the module
  and was found by reading rather than by a test.
* **the three deadlines.** `progress_ms`, `wall_ms_hard`, `deadline_ms`
  (04-driver-system.md:1733-1735), the `PROGRESS`-only reset (:1735), and the ORDER of the tick:
  the deadline is checked before the queue, because a driver whose frames never stop arriving
  otherwise keeps the supervisor in a loop and the wall clock is never read -- which is exactly
  the attack :1794 answers. That order is pinned by
  `test_a_progress_flood_cannot_extend_the_wall_clock_when_the_queue_is_never_empty`, over a
  reader that is never empty, and NOT by the two flood tests over a real reader thread: a reader
  thread cannot keep a real `Queue` occupied against the supervisor, so the queue runs dry, the
  post-read check covers for the pre-read one, and deleting the pre-read check leaves those two
  tests green. That was measured, not reasoned.
* **every blocking wait is bounded, and the test's bound is the JOIN.** `run_bounded` runs the
  call on a daemon thread and asserts the thread finished. An `assert elapsed < 5.0` written
  after the call cannot fail on the module it exists to reject -- a queue read with no deadline
  never returns, and the session hangs with no output rather than going red. Every test here
  that could hang goes through `run_bounded`, the runner test included.
* **AIMD, both halves.** The plan says halve-and-never-recover *"lets one foreign process
  permanently cap a driver"* (02-architecture.md:831), so the recovery is tested as hard as the
  halving: that nineteen cleans do not raise the batch, that the twentieth does, that a non-clean
  event resets the streak, and that a halved batch actually climbs back to `card_max`.
* **quarantine, per driver, per run, with one home.** Three crashes in sixty seconds
  (04-driver-system.md:1720), and the ROUND TRIP into `omniweave_core.drivers.resolve`: the pool
  produces the set, `Policy.quarantined` carries it and `resolve()` stops offering the driver.
  The same call with an empty set returns the driver, so the gate is what changed the outcome and
  not the fixture.
* **the worker key is a correctness property.** `(driver_id, config_digest)`
  (02-architecture.md:85, :482): a changed config gets a NEW worker and an unchanged one reuses
  it. The digest is pinned as a LITERAL rather than recomputed here, because a test that derives
  the expected digest from the same function that produced it pins agreement and not identity.
* **the reader that does not oblige a hostile driver.** 04-driver-system.md section 6.5, one test
  per row: a length prefix that lies, a body shorter than declared, a frame that never ends,
  nothing at all forever, a frame flood, a `RESULT` for a unit outside the batch. Every assertion
  is a bounded refusal, and the bound is asserted in wall-clock milliseconds.
* **the Windows cells, and the ones this platform cannot show.** 04-driver-system.md:1745 requires
  that what was not obtained be *"recorded rather than claimed"*, so `grant_isolation`'s
  shortfalls are asserted member by member. `socket.AF_UNIX` does not exist on CPython for
  Windows, so the unix-socket arm is asserted to REFUSE here and its 0600 ordering skips with that
  reason rather than being written to pass vacuously.

Specified in 04-driver-system.md sections 6.2-6.6, 02-architecture.md section 3.4 (S4), section
5.6's S4 row (:831) and section 7.5's (:1060), 08-runtime.md sections 1.6 and 2.2, and
16-roadmap.md:482.
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib.util
import os
import re
import socket
import subprocess  # noqa: TID251 -- see the module docstring: real children ARE the subject.
import sys
import threading
import time
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import TypeVar

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.drivers.catalog import Catalog
from omniweave_core.drivers.resolve import (
    Policy,
    RejectCode,
    Requirement,
    clear_memo,
    resolve,
)
from omniweave_core.errors import DriverHostError
from omniweave_core.host import subproc as sp
from omniweave_core.host import wire
from omniweave_core.identity import config_digest
from omniweave_ports.types import (
    DriverError,
    DriverResult,
    FailureClass,
    Isolation,
    ProbeEnv,
    TrustTier,
    UnitRef,
)


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
SUBPROC_SOURCE = (
    REPO_ROOT / "packages" / "omniweave-core" / "src" / "omniweave_core" / "host" / "subproc.py"
)
TOOL_PATH = REPO_ROOT / "tools" / "ow_host.py"

# The runner is a script in `tools/`, not a distribution, so there is no package to import it
# from. `spec_from_file_location` loads it by path -- the mechanism `test_gate_crash.py` and
# `test_drivers_resolve.py` both use, and for the same two reasons: not `importlib.import_module`,
# which is banned outside `host/`, and not a `sys.path` mutation, which would leak into every
# later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_ow_host", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repo
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


WINDOWS = sys.platform == "win32"
WINDOWS_ONLY = pytest.mark.skipif(
    not WINDOWS, reason="the named-pipe arm, job objects and psapi are the Windows cells of S4"
)

# ---------------------------------------------------------------------------------------------
# The literals. Every one is the plan's, cited, and written out rather than imported from the
# subject -- rule: when both sides of an equality come from one source the test pins agreement.
# ---------------------------------------------------------------------------------------------

FRAME_QUEUE_MAX = 256
"""04-driver-system.md:1793 and :2849, glossary.md:662. The host's bounded read queue."""

STDERR_RING_BYTES = 4_096
"""4 KiB. 04-driver-system.md:1719, :1727; 02-architecture.md:581, :831, :1060."""

AIMD_RECOVERY_STREAK = 20
"""02-architecture.md:831, 08-runtime.md:770, 12-performance.md:1027 -- twenty CONSECUTIVE."""

CRASH_THRESHOLD = 3
CRASH_WINDOW_S = 60
"""`crash_quarantine = { crashes = 3, window_s = 60 }` -- 04-driver-system.md:1720,
08-runtime.md:2591, 18-api-sketch.md:1645."""

WORKER_IDLE_TTL_S = 300
"""02-architecture.md:238, :677; 04-driver-system.md:1670; 08-runtime.md:2590;
12-performance.md:723."""

LOOP_LAG_MAX_MS = 250
"""`runtime.loop_lag_max_ms`, which 04-driver-system.md:1769 makes the supervisor's wake AND the
RSS sampling cadence -- "so the supervisor loop already wakes at that rate"."""

MAX_WORKERS = {"free": 4, "local_compute": 4, "billed_api": 8}
"""04-driver-system.md:1782's shipped default for `[drivers] max_workers`, which counts WORKER
PROCESSES per cost class -- `[budget] max_inflight` counts units and is a different table."""

KILL_GRACE_MS = 5_000
"""04-driver-system.md:126, :1728 and 05-ingest-and-routing.md:3054's "+5 s"."""

LIMIT_NAMES = ("progress_ms", "wall_ms_hard", "deadline_ms")
"""The three deadlines in 04-driver-system.md:1733-1735's printed order. `progress_ms` and
`wall_ms_hard` are printed as `limit` values at :1728-1729; `deadline_ms`'s spelling is ours,
derived from the field name the plan prints, and this literal is where that choice is pinned."""

ISOLATION_GRANTED_KEYS = (
    "mode",
    "address_space_capped",
    "rss_sampled",
    "cpu_capped",
    "fd_capped",
    "net_blocked",
    "tmp_only_writable",
    "batch_max_units",
)
"""04-driver-system.md:1709-1710's *"closed, eight-key record"*, counted: eight names, and the
prose's number agrees with its own braced list."""

BATCH_EVENTS = ("clean", "resource_limit", "worker_died", "driver_crashed")
"""08-runtime.md:764-773's `match` arms, as a closed set of four wire values."""

WORKER_KEY_FIELDS = ("driver_id", "config_digest")
"""02-architecture.md:85, :482, :677, :831 -- TWO components. `dispatch_key` at :481 has three
(`sha256(driver | config_digest | isolation)[:16]`) and is the QUEUE's key, not the pool's; this
literal is what fails if the two are ever conflated."""

# A fixed config and the digest `omniweave_core.identity.config_digest` computes for it, written
# out. The recipe is `sha256_canonical` over the FULL resolved config (identity.py:350) and it
# keys every worker in the pool, so if the recipe moves, every worker in every run is re-keyed and
# one configuration's work can be served under another's settings. Recomputing the expectation
# here would pin agreement between config_digest and itself; this pins the value.
CONFIG_A = {"drivers.pdf.dpi": 200}
CONFIG_B = {"drivers.pdf.dpi": 300}
DIGEST_A = "f900649e856627099d5338a4591d2e0dd7a6475993332d8ab72eaf2572d943ce"
DIGEST_B = "fb0a5eebc137be065e2a3f57a6d2d0df6cb9bb967c26cebe897dc18a922567bb"

DRIVER_ID = "parse.pdf.pdfium"

# The module roots `host/subproc.py` may import. INV-2/G1 (stdlib only), G23 (no `asyncio`, no
# `selectors`) and INV-17 (`sqlite3` only under `store/`) are all statements about this set, and
# adding an import that breaks one of them is what makes this red.
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "contextlib",
        "ctypes",
        "dataclasses",
        "enum",
        "io",
        "msvcrt",
        "os",
        "queue",
        "socket",
        "subprocess",
        "sys",
        "threading",
        "types",
        "typing",
        "omniweave_core",
        "omniweave_ports",
    }
)

TOOL_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "argparse",
        "collections",
        "contextlib",
        "dataclasses",
        "os",
        "pathlib",
        "sys",
        "threading",
        "time",
        "typing",
        "omniweave_core",
        "omniweave_ports",
    }
)
"""What `tools/ow_host.py` may import. Wider than the module's -- `argparse`, `time` and a
`Path` are the whole reason a runner exists under `tools/` -- and `subprocess` is ABSENT, because
the spawn is `host/subproc.py`'s `spawn_worker()` and a runner with its own `Popen` would have
built a second spawn site outside the two the semgrep bank names."""


# ---------------------------------------------------------------------------------------------
# Fakes. A worker without a process, a transport without a pipe, a clock without a clock.
# ---------------------------------------------------------------------------------------------


class Clock:
    """An injected `now_ms`. `step` makes it advance on every read.

    Every deadline in the module is measured against a `Callable[[], int]`, so a test can make a
    ten-second timeout fire in ten microseconds. `step = 0` is a frozen clock, which is what the
    pool's TTL tests want; a non-zero step is what makes a supervisor loop terminate.
    """

    def __init__(self, *, now: int = 0, step: int = 0) -> None:
        self.value = now
        self.step = step
        self.reads = 0

    def __call__(self) -> int:
        self.reads += 1
        current = self.value
        self.value += self.step
        return current

    def advance(self, ms: int) -> None:
        self.value += ms


class FakeProcess:
    """A `WorkerProcess` that never existed. Counts what the host did to it.

    `subprocess.Popen` satisfies the same Protocol, which is the point of the Protocol: the
    lifecycle tests run without a fork and the transport tests run with one.
    """

    def __init__(self, *, pid: int = 4321, status: int | None = None) -> None:
        self.pid = pid
        self.status = status
        self.kills = 0
        self.terminates = 0
        self.waited: list[float | None] = []

    def poll(self) -> int | None:
        return self.status

    def terminate(self) -> None:
        self.terminates += 1

    def kill(self) -> None:
        self.kills += 1
        if self.status is None:
            self.status = 1

    def wait(self, timeout: float | None = None) -> int:
        self.waited.append(timeout)
        if self.status is None:
            raise subprocess.TimeoutExpired("fake-worker", timeout or 0.0)
        return self.status


class FakeChannel:
    """A `ByteChannel` over bytes in hand. Records what was asked for and what was sent.

    `block_at_eof` is the hostile case section 6.5 is about: a worker that sends the first half of
    a frame and then nothing, ever. With it set, `recv` parks instead of returning `b""`, so the
    only thing that can end an invocation is the host's own clock -- which is the property under
    test.
    """

    def __init__(self, *chunks: bytes, block_at_eof: bool = False) -> None:
        self.inbound = bytearray(b"".join(chunks))
        self.sent = bytearray()
        self.asked: list[int] = []
        self.closed = False
        self._block = block_at_eof
        self._lock = threading.Lock()
        self._gate = threading.Event()

    def feed(self, data: bytes) -> None:
        with self._lock:
            self.inbound.extend(data)
        self._gate.set()

    def recv(self, size: int) -> bytes:
        self.asked.append(size)
        while True:
            with self._lock:
                if self.inbound:
                    taken = bytes(self.inbound[:size])
                    del self.inbound[:size]
                    return taken
                if self.closed or not self._block:
                    return b""
            self._gate.wait(0.005)
            self._gate.clear()

    def sendall(self, data: bytes) -> None:
        with self._lock:
            self.sent.extend(data)

    def close(self) -> None:
        self.closed = True
        self._gate.set()

    def frames_sent(self) -> tuple[wire.Frame, ...]:
        """Everything the HOST wrote, decoded. What crossed the wire, not what was intended."""
        frames: list[wire.Frame] = []
        buffer = bytes(self.sent)
        offset = 0
        while offset < len(buffer):
            header_len, body_len = wire.decode_prefix(buffer[offset : offset + wire.PREFIX_BYTES])
            start = offset + wire.PREFIX_BYTES
            header = buffer[start : start + header_len]
            body = buffer[start + header_len : start + header_len + body_len]
            frames.append(wire.decode(header, body))
            offset = start + header_len + body_len
        return tuple(frames)


class FloodChannel:
    """An endless stream of one frame, counting how many it has HANDED OUT.

    The bounded queue is a claim about a number nobody can see from outside the host
    (04-driver-system.md:1793), and this is the instrument: once the queue is full the reader
    thread blocks in `put`, stops calling `recv`, and `served` stops growing. A channel that kept
    being read would show it.
    """

    def __init__(self, frame: bytes) -> None:
        self._frame = frame
        self._buffer = bytearray()
        self.served = 0
        self.closed = False
        self._lock = threading.Lock()

    def recv(self, size: int) -> bytes:
        with self._lock:
            if self.closed:
                return b""
            while len(self._buffer) < size:
                self._buffer.extend(self._frame)
                self.served += 1
            taken = bytes(self._buffer[:size])
            del self._buffer[:size]
            return taken

    def sendall(self, data: bytes) -> None:  # noqa: ARG002 -- one direction, by design
        """A flood channel is read-only: nothing the host writes has anywhere to go."""
        return

    def close(self) -> None:
        with self._lock:
            self.closed = True


def settings(**overrides: object) -> sp.HostSettings:
    """A `HostSettings` built from the plan's literals, with a fast tick for the tests.

    `tick_ms` is five and not 250 on purpose: the tick is how long a supervisor blocks on the
    queue before it re-reads the clock, so the plan's 250 would make every deadline test a
    quarter-second of real time per tick. The 250 itself is pinned in
    `test_host_settings_reads_the_five_numbers_off_a_resolved_config`, against a `Config`.
    """
    base: dict[str, object] = {
        "worker_idle_ttl_s": WORKER_IDLE_TTL_S,
        "crash_threshold": CRASH_THRESHOLD,
        "crash_window_s": CRASH_WINDOW_S,
        "tick_ms": 5,
        "max_workers": dict(MAX_WORKERS),
    }
    base.update(overrides)
    return sp.HostSettings(**base)  # type: ignore[arg-type]


def worker_on(
    channel: sp.ByteChannel,
    *,
    clock: Clock | None = None,
    proc: FakeProcess | None = None,
    ring: sp.StderrRing | None = None,
    host: sp.HostSettings | None = None,
) -> tuple[sp.Worker, FakeProcess, Clock]:
    """A `Worker` over a fake process and a fake transport."""
    process = proc if proc is not None else FakeProcess()
    ticker = clock if clock is not None else Clock(step=25)
    built = sp.Worker(
        sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A),
        process,
        channel,
        settings=host if host is not None else settings(),
        now_ms=ticker,
        stderr=ring if ring is not None else sp.StderrRing(),
    )
    return built, process, ticker


def units(count: int = 2) -> tuple[UnitRef, ...]:
    return tuple(
        UnitRef(
            uri=f"file:///u{index}.pdf",
            part="",
            content_sha256="sha256:" + f"{index:064d}",
            byte_len=0,
        )
        for index in range(count)
    )


def invocation(count: int = 2, **overrides: object) -> sp.Invocation:
    base: dict[str, object] = {
        "invoke_id": "inv-1",
        "units": units(count),
        "deadline_ms": 0,
        "budget_micros": 0,
    }
    base.update(overrides)
    return sp.Invocation(**base)  # type: ignore[arg-type]


def result_frame(index: int, **header: object) -> bytes:
    return wire.encode(wire.FrameKind.RESULT, {"invoke_id": "inv-1", "unit_index": index, **header})


def deadlines(progress: int = 400, wall: int = 5_000, caller: int = 0) -> sp.Deadlines:
    return sp.Deadlines(progress_ms=progress, wall_ms_hard=wall, deadline_ms=caller)


_T = TypeVar("_T")


def run_bounded(work: Callable[[], _T], *, patience_s: float = 10.0) -> _T:
    """Call `work` on a daemon thread, so a supervisor that never returns FAILS the test.

    The deadline tests in this file were written as `started = time.monotonic()`, then `invoke`,
    then `assert elapsed < 5.0`. That last assertion is UNREACHABLE when the mechanism under test
    does nothing: replacing `FrameReader.get`'s `self._queue.get(timeout=...)` with
    `self._queue.get()` -- a blocking read with no deadline, which is the defect
    04-driver-system.md:1794 is about -- makes the call not return, and the whole `pytest` session
    hangs with no output and no exit code. That is strictly worse than a red test, because a
    hung job carries no diagnostic and a hung developer run is usually interrupted rather than
    read.

    So the bound is the JOIN and the assertion is `not thread.is_alive()`. The thread is a daemon
    so a supervisor that is still spinning cannot outlive the session, and any exception the
    supervisor raised is re-raised HERE, on the caller's thread, so `pytest.raises` still works
    around it.
    """
    box: list[_T] = []
    failed: list[Exception] = []

    def run() -> None:
        try:
            box.append(work())
        except Exception as exc:  # re-raised on the caller's thread below
            failed.append(exc)

    thread = threading.Thread(target=run, name="ow-test-bounded", daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(patience_s)
    alive = thread.is_alive()
    elapsed = time.monotonic() - started
    assert not alive, f"the call had not returned after {elapsed:.1f}s: it is not bounded"
    if failed:
        raise failed[0]
    return box[0]


def invoke_bounded(
    worker: sp.Worker,
    payload: sp.Invocation,
    *,
    limits: sp.Deadlines,
    memory_mb: int = 0,
    patience_s: float = 10.0,
) -> sp.InvokeReport:
    """`Worker.invoke` under `run_bounded`. Every deadline test in this file goes through here."""
    return run_bounded(
        lambda: worker.invoke(payload, deadlines=limits, memory_mb=memory_mb),
        patience_s=patience_s,
    )


class ReadyReader:
    """A `FrameReader` stand-in whose queue is NEVER empty: `get` returns a frame at once, always.

    `FloodChannel` was meant to be this and is not, and the difference decides whether the tick's
    ORDER is testable. A real reader thread cannot keep a real `Queue` occupied against a
    supervisor that pops one frame per tick on a fake clock, so `get` returns `None` within a tick
    or two, the supervisor's POST-read deadline check runs, and the invocation ends -- which is
    why deleting the PRE-read check leaves `test_a_log_flood_cannot_extend_a_drivers_own_wall_clock`
    green (measured: 175 passed, that test in under 5 ms).

    This double removes the race. There is always a frame, so the frame branch -- which returns
    without consulting the clock -- is the only branch `_await_frame` can take, and the check
    before the queue read is the only thing that can end the invocation.
    """

    def __init__(self, frame: wire.Frame) -> None:
        self._frame = frame
        self.gets = 0

    def get(self, *, timeout_ms: int) -> wire.Frame:  # noqa: ARG002 -- never empty, never waits
        self.gets += 1
        return self._frame

    def depth(self) -> int:
        return 1

    def alive(self) -> bool:
        return True


def one_frame(kind: wire.FrameKind, header: dict[str, object]) -> wire.Frame:
    """One `wire.Frame`, built through the real grammar rather than by constructor."""
    frame = sp.next_frame(FakeChannel(wire.encode(kind, header)))  # type: ignore[arg-type]
    assert frame is not None
    return frame


# ---------------------------------------------------------------------------------------------
# The resolve() round trip needs a card and a catalog. Copied in miniature from
# `test_drivers_resolve.py`, whose fixtures are the reference; nothing here re-implements
# `resolve()`'s inputs, it only builds the smallest catalog the quarantine gate can be seen in.
# ---------------------------------------------------------------------------------------------

MINIMAL_CARD = """card_schema = 1

[driver]
id = "parse.pdf.pdfium"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/pdf"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

HOST_ENV = ProbeEnv(
    platform="linux",
    machine="x86_64",
    python=(3, 12),
    which={},
    gpu_present=False,
    vram_gb=0.0,
    offline=False,
)


def pdf_card() -> DriverCard:
    loaded = load_card(MINIMAL_CARD.encode("utf-8"), origin="entry_point", source="driver.toml")
    assert isinstance(loaded, DriverCard)
    return loaded


def catalog_of(card: DriverCard) -> Catalog:
    return Catalog.assemble(
        validity_key=hashlib.sha256(b"host-subproc").hexdigest(),
        cards={card.identity.id: card},
        probe_status={},
        trust={card.identity.id: TrustTier.FIRST_PARTY},
        tombstones=(),
    )


def policy_with(quarantined: frozenset[str]) -> Policy:
    return Policy(
        require_lock=False,
        allow_unattested=True,
        host_env=HOST_ENV,
        quarantined=quarantined,
    )


def requirement() -> Requirement:
    return Requirement(port="parse/1", format="application/pdf")


# =============================================================================================
# 1. The grammar has ONE home, and it is `wire.py`
# =============================================================================================


def module_constants(path: Path) -> dict[str, object]:
    """Every module-level constant assignment in `path`, by name, with its literal value.

    `ast` and not a regex, and module level only: a duplicate `KIND_KEY` shipped in the first
    draft of `subproc.py`, and a comment mentioning `"kind"` is not a definition site.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, object] = {}
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            first = node.targets[0]
            if isinstance(first, ast.Name):
                target, value = first.id, node.value
        if target is None or not isinstance(value, ast.Constant):
            continue
        found[target] = value.value
    return found


def test_no_constant_in_subproc_respells_a_cap_or_the_kind_key_that_wire_owns() -> None:
    """`wire.py` is authoritative, so a second spelling of one of its facts is a defect.

    02-architecture.md:238 makes `wire.py` framing's sole home and INV-21 forbids a second home
    for one fact. The values checked are the three caps and the `kind` header key; a module-level
    constant equal to any of them in `subproc.py` is the duplicate this test exists to catch --
    and it caught one, a `KIND_KEY: Final = "kind"` whose docstring additionally described the
    kind as an int while `wire.encode` writes the NAME.
    """
    owned = {wire.MAX_HEADER_BYTES, wire.MAX_BODY_BYTES, wire.MAX_HEADER_DEPTH, wire.KIND_KEY}
    duplicated = {
        name: value for name, value in module_constants(SUBPROC_SOURCE).items() if value in owned
    }
    assert duplicated == {}, duplicated


def test_subproc_declares_no_constant_twice() -> None:
    """One name, one definition site. A second assignment is dead code at best.

    The first draft declared `RESULT_UNIT_INDEX_KEY` twice, with two different docstrings, and
    ruff did not complain because pyflakes' redefinition check does not cover plain assignments.
    """
    tree = ast.parse(SUBPROC_SOURCE.read_text(encoding="utf-8"), filename=str(SUBPROC_SOURCE))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
        elif isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == []


@pytest.mark.parametrize("kind", sorted(wire.DRIVER_TO_HOST, key=lambda item: item.name))
def test_the_host_refuses_to_send_any_of_the_six_driver_to_host_kinds(
    kind: wire.FrameKind,
) -> None:
    """A host that could send `RESULT` has given a third party's grammar to itself.

    Pinned kind by kind rather than against one excluded member: a closed set pinned against a
    single member is pinned against nothing. 04-driver-system.md:1693's direction column.
    """
    channel = FakeChannel()
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="drv->host"):
        worker.send(kind, {})
    assert bytes(channel.sent) == b""


@pytest.mark.parametrize("kind", sorted(wire.HOST_TO_DRIVER, key=lambda item: item.name))
def test_the_host_may_send_each_of_the_five_host_to_driver_kinds(kind: wire.FrameKind) -> None:
    """The other half of the same closed set, so the refusal above is not a refusal of
    everything."""
    channel = FakeChannel()
    worker, _proc, _clock = worker_on(channel)
    worker.send(kind, {})
    assert [frame.kind for frame in channel.frames_sent()] == [kind]


def test_an_invoke_carries_the_four_keys_the_plan_prints_and_the_two_we_declare() -> None:
    """04-driver-system.md:1699's `INVOKE{invoke_id, units, deadline_ms, budget_micros}`.

    The fifth key, `inline_unit_index`, is ours and is argued in `Invocation.as_header`: :1674's
    frame has ONE body and :1699's `units` is a LIST, so a batch with inline bytes cannot say
    whose bytes they are without it. Pinned here so the addition stays visible rather than
    becoming folklore, and so a SIXTH key cannot appear unnoticed.
    """
    channel = FakeChannel()
    worker, _proc, _clock = worker_on(channel)
    worker.send(wire.FrameKind.INVOKE, invocation().as_header())
    sent = channel.frames_sent()[0]
    assert sent.kind is wire.FrameKind.INVOKE
    assert sorted(sent.header) == [
        "budget_micros",
        "deadline_ms",
        "inline_unit_index",
        "invoke_id",
        "units",
    ]
    assert sorted(sent.header["units"][0]) == [  # type: ignore[index]
        "byte_len",
        "content_sha256",
        "part",
        "uri",
    ]


def test_an_invoke_with_two_inline_bodies_is_refused_because_the_grammar_cannot_express_it() -> (
    None
):
    """The gap :1674 leaves, failed closed rather than guessed.

    One header, one body, and a list of units: two units with inline bytes are unrecoverable
    without an offset table, and an offset table is grammar this module may not invent. So a body
    with no `inline_unit_index` is a refusal, and the fix names the two ways out.
    """
    with pytest.raises(DriverHostError, match="inline_unit_index"):
        sp.Invocation(
            invoke_id="inv-1", units=units(2), deadline_ms=0, budget_micros=0, body=b"bytes"
        )


def test_an_invoke_body_over_inline_max_is_refused_at_construction() -> None:
    """04-driver-system.md:1676: above `INLINE_MAX` a unit travels as a blob ref, not a body."""
    with pytest.raises(DriverHostError, match="INLINE_MAX"):
        sp.Invocation(
            invoke_id="inv-1",
            units=units(1),
            deadline_ms=0,
            budget_micros=0,
            body=b"x" * (wire.MAX_BODY_BYTES + 1),
            inline_unit_index=0,
        )


def test_an_invoke_with_no_units_is_refused() -> None:
    """A batch is a set of claimed rows; an empty one is a dispatch nobody asked for."""
    with pytest.raises(DriverHostError, match="no units"):
        sp.Invocation(invoke_id="inv-1", units=(), deadline_ms=0, budget_micros=0)


def test_the_plans_own_frame_fence_prints_no_kind_field_and_that_gap_is_recorded(plan) -> None:
    """A FINDING, pinned so it cannot be quietly lost.

    04-driver-system.md:1670-1676 prints the frame as four fields --
    `u32 header_len_le | u32 body_len_le | JSON header (UTF-8) | raw body bytes` -- and none of
    them is the kind, while :1690 declares eleven kinds and 02-architecture.md:831 makes an
    unknown `kind` a protocol error. A kind that is a protocol error when unknown has to be on
    the wire, so it rides in the JSON header, whose printed payload column shows no such key for
    any of the eleven rows. `wire.py` resolves it by carrying the kind's NAME at `wire.KIND_KEY`.
    """
    plan.require()
    fence = [
        line
        for line in plan.lines("04-driver-system.md")[1665:1680]
        if line.strip().startswith("Frame")
    ]
    assert fence, "04-driver-system.md's frame grammar fence moved"
    assert "kind" not in fence[0]
    assert "header_len_le" in fence[0] and "body_len_le" in fence[0]


# =============================================================================================
# 2. The three deadlines
# =============================================================================================


def test_the_three_limit_spellings_are_the_plans_three_in_the_plans_order() -> None:
    """04-driver-system.md:1733-1735. `deadline_ms`'s spelling is ours; see `LIMIT_NAMES`."""
    assert sp.LIMIT_NAMES == LIMIT_NAMES


def test_a_progress_frame_moves_the_progress_deadlines_origin(pure_unit) -> None:  # noqa: ARG001
    """04-driver-system.md:1735: *"`PROGRESS` is the only frame that resets `progress_ms`."*"""
    countdown = sp.Countdown(deadlines(progress=100), started_ms=0)
    assert countdown.expired(150) == "progress_ms"
    countdown.note_progress(150)
    assert countdown.expired(200) is None
    assert countdown.expired(260) == "progress_ms"


def test_a_log_frame_resets_nothing_because_a_chatty_driver_is_not_a_live_one(
    pure_unit,  # noqa: ARG001
) -> None:
    """04-driver-system.md:1735-1737: a driver logging in a tight loop *"would otherwise look
    alive forever, which is the failure `progress_ms` exists to catch"*.

    The assertion is that `note_log` leaves the origin where it was -- a no-op with a name, so
    that a reviewer can see the `LOG` path was considered and rejected rather than forgotten.
    """
    countdown = sp.Countdown(deadlines(progress=100), started_ms=0)
    countdown.note_log(90)
    assert countdown.last_progress_ms == 0
    assert countdown.expired(120) == "progress_ms"


def test_a_chatty_driver_hits_wall_ms_hard_and_the_verdict_names_it(pure_unit) -> None:  # noqa: ARG001
    """04-driver-system.md:1729: the chatty hang is `TIMEOUT` with `limit = "wall_ms_hard"`."""
    countdown = sp.Countdown(deadlines(progress=1_000, wall=500), started_ms=0)
    for moment in range(0, 500, 100):
        countdown.note_progress(moment)
    assert countdown.expired(600) == "wall_ms_hard"


def test_the_callers_own_deadline_fires_and_is_named_separately(pure_unit) -> None:  # noqa: ARG001
    """`deadline_ms` rides on the `INVOKE` (04-driver-system.md:1699) and is the third of the
    three (:1734). The plan prints no outcome row for it, so its `limit` spelling is ours."""
    countdown = sp.Countdown(deadlines(progress=10_000, wall=10_000, caller=300), started_ms=0)
    assert countdown.expired(299) is None
    assert countdown.expired(300) == "deadline_ms"


@pytest.mark.parametrize("field", LIMIT_NAMES)
def test_a_zero_deadline_is_unbounded_by_that_limit_and_only_that_one(field: str) -> None:
    """A card that declares no `progress_ms` is not a card with a zero-millisecond one.

    04-driver-system.md:769 defaults the `[isolation]` deadlines to none, and `card.py:900-901`
    carries that as `0`. Parametrised over all three, because zero has to mean the same thing in
    each and a single case would not show it.
    """
    values = dict.fromkeys(LIMIT_NAMES, 10_000)
    values[field] = 0
    countdown = sp.Countdown(sp.Deadlines(**values), started_ms=0)  # type: ignore[arg-type]
    assert countdown.expired(9_999) is None
    fired = countdown.expired(10_001)
    assert fired is not None and fired != field


def test_when_two_deadlines_have_elapsed_the_earlier_one_is_reported(pure_unit) -> None:  # noqa: ARG001
    """The verdict names WHICH limit fired, so the answer cannot be dict ordering.

    `progress_ms` here elapsed at 100 and `wall_ms_hard` at 900, so at 1000 the widest overshoot
    -- the deadline that fired FIRST in time -- is `progress_ms`, and that is what the operator
    needs to read: the driver went quiet long before it ran out of wall clock.
    """
    countdown = sp.Countdown(deadlines(progress=100, wall=900), started_ms=0)
    assert countdown.expired(1_000) == "progress_ms"


def test_a_tie_between_two_deadlines_breaks_in_the_plans_printed_order(pure_unit) -> None:  # noqa: ARG001
    """Both at the same millisecond: the answer is `progress_ms`, the first of `LIMIT_NAMES`.

    **What this cannot show, and what `Countdown`'s own docstring claims it does.** That docstring
    says a tie is *"otherwise decided by dict ordering, which is not a contract"*, and the final
    loop walks `LIMIT_NAMES` to avoid it. But `expired()` inserts the three overshoots in exactly
    `LIMIT_NAMES` order every time, so the dict's order and the tuple's order are the same order
    by construction: replacing `for name in LIMIT_NAMES` with `for name in overshoot` cannot
    change an answer, and it does not (measured: green). The loop is documentation, the
    substitution is an equivalent mutant, and no test can separate them. What IS pinned is the
    outcome -- and, in the test above, that `LIMIT_NAMES` is the plan's tuple.
    """
    countdown = sp.Countdown(deadlines(progress=500, wall=500), started_ms=0)
    assert countdown.expired(500) == "progress_ms"
    # The second and third tie with the first unbounded: `wall_ms_hard` precedes `deadline_ms`
    # in the plan's order, so a tie between those two names the wall clock.
    other = sp.Countdown(
        sp.Deadlines(progress_ms=0, wall_ms_hard=500, deadline_ms=500), started_ms=0
    )
    assert other.expired(500) == "wall_ms_hard"


def test_the_supervisor_never_blocks_longer_than_one_tick(pure_unit) -> None:  # noqa: ARG001
    """The wall clock is re-read every `loop_lag_max_ms` even when the next deadline is an hour
    away (04-driver-system.md:1769), which is what makes the watchdog free."""
    countdown = sp.Countdown(deadlines(progress=3_600_000, wall=3_600_000), started_ms=0)
    assert countdown.wait_ms(0, tick_ms=250) == 250


def test_the_supervisor_never_overshoots_the_nearest_deadline(pure_unit) -> None:  # noqa: ARG001
    """A 250 ms tick must not sleep through a 10 ms remainder, or every deadline is late by a
    quarter second under load."""
    countdown = sp.Countdown(deadlines(progress=10, wall=10_000), started_ms=0)
    assert countdown.wait_ms(0, tick_ms=250) == 10
    assert countdown.wait_ms(9, tick_ms=250) == 1


def test_a_wait_never_goes_negative_because_zero_means_look_at_the_clock_now(
    pure_unit,  # noqa: ARG001
) -> None:
    """A negative timeout on `Queue.get` is an immediate `Empty` on some builds and a `ValueError`
    on others; the caller's contract is that zero means "the deadline has fired"."""
    countdown = sp.Countdown(deadlines(progress=10, wall=10), started_ms=0)
    assert countdown.wait_ms(5_000, tick_ms=250) == 0


# =============================================================================================
# 3. `HostVerdict` -- the host's own failures, which are not `DriverError`s
# =============================================================================================


def test_a_crash_verdict_carries_the_exit_status_and_the_last_four_kib_of_stderr() -> None:
    """02-architecture.md:831: *"synthesised from the exit status plus the last 4 KiB of the
    stderr ring"* -- and the LAST four, which is what a tail is."""
    ring = sp.StderrRing()
    ring.feed(b"A" * 9_000 + b"TAIL")
    verdict = sp.HostVerdict.crashed(exit_status=3, stderr_tail=ring.tail())
    assert verdict.failure_class is FailureClass.DRIVER_CRASHED
    assert verdict.permanent is True
    assert verdict.exit_status == 3
    assert len(verdict.stderr_tail) == STDERR_RING_BYTES
    assert verdict.stderr_tail.endswith(b"TAIL")
    assert "3" in verdict.message


def test_a_crash_with_no_status_says_so_rather_than_printing_none_as_a_status() -> None:
    """An EOF from a child that has not exited is a worker that closed its own transport.

    The message has to distinguish it, because `exit status None` reads like a status and the
    operator's next question -- was it signalled? -- has a different answer in each case.
    """
    verdict = sp.HostVerdict.crashed(exit_status=None, stderr_tail=b"")
    assert verdict.exit_status is None
    assert "did not exit" in verdict.message


def test_a_timeout_verdict_refuses_a_limit_that_is_not_one_of_the_three() -> None:
    """`limit` is what `ow drivers explain` prints and what an operator raises; a spelling nobody
    declared is a knob nobody can find."""
    with pytest.raises(DriverHostError, match="not one of the three deadlines"):
        sp.HostVerdict.timed_out("elapsed_ms", elapsed_ms=1)


def test_a_host_detected_timeout_is_permanent_and_is_not_expressible_as_a_driver_error() -> None:
    """08-runtime.md:567 and 02-architecture.md:1014: driver-reported `timeout` is TRANSIENT and
    host-detected `timeout` is `failed_permanent`.

    `DriverError.__post_init__` enforces charter D3's *"`retry_after_ms` REQUIRED iff
    transient"*, so a host that built one would have to invent a cooldown it has no basis for
    AND would mis-state the verdict. Raising is the honest answer.
    """
    verdict = sp.HostVerdict.timed_out("progress_ms", elapsed_ms=700)
    assert verdict.permanent is True
    assert verdict.limit == "progress_ms"
    with pytest.raises(DriverHostError, match="failed_permanent"):
        verdict.as_driver_error()


def test_a_synthesised_crash_does_convert_to_a_driver_error() -> None:
    """02-architecture.md:1060 says `host/subproc.py` *"reconstructs a `DriverError`"*, and for
    `driver_crashed` it can: the class is permanent, so no `retry_after_ms` is owed."""
    error = sp.HostVerdict.crashed(exit_status=1, stderr_tail=b"").as_driver_error()
    assert isinstance(error, DriverError)
    assert error.cls is FailureClass.DRIVER_CRASHED
    assert error.retry_after_ms is None


def test_a_driver_reported_failure_is_carried_through_without_reclassification() -> None:
    """02-architecture.md:1060: the worker serialises the five `DriverError` fields and the host
    reconstructs them. The retry ladder is `run/pipeline.py`'s `classify()`, never this
    module's, so a transient class keeps its cooldown and is not permanent here."""
    verdict = sp.HostVerdict.from_driver(
        DriverError(cls=FailureClass.RATE_LIMITED, message="429", retry_after_ms=1_500)
    )
    assert verdict.failure_class is FailureClass.RATE_LIMITED
    assert verdict.retry_after_ms == 1_500
    assert verdict.permanent is False
    assert verdict.detected_by == "driver"


def test_the_memory_verdict_names_the_knob_that_would_need_raising() -> None:
    """04-driver-system.md:1730: `FAILED_PERMANENT{RESOURCE_LIMIT}`, `limit = "memory_mb"`."""
    verdict = sp.HostVerdict.over_memory(observed_bytes=700 * 1_048_576, cap_mb=512)
    assert verdict.failure_class is FailureClass.RESOURCE_LIMIT
    assert verdict.limit == "memory_mb"
    assert "512" in verdict.message


def test_the_five_failure_modes_are_the_five_the_document_tabulates(plan) -> None:
    """04-driver-system.md:1723's heading says *"The five failure modes"* and its table has five
    rows; the number and the enumeration AGREE, which is worth checking rather than assuming.

    The fifth row is `malicious`, whose detector is *"not detected"*: it is in the transcription
    so that four handled modes can never be read as five.
    """
    plan.require()
    lines = plan.lines("04-driver-system.md")
    rows = [line for line in lines[1724:1731] if line.startswith("| **") and line.count("|") == 5]
    assert len(rows) == 5
    assert len(sp.FAILURE_MODES) == len(rows)
    assert [mode.limit for mode in sp.FAILURE_MODES] == [
        None,
        "progress_ms",
        "wall_ms_hard",
        "memory_mb",
        None,
    ]
    assert sp.FAILURE_MODES[4].detector == "not detected"


# =============================================================================================
# 4. AIMD -- and the recovery half, which is the half that makes it correct
# =============================================================================================


def test_the_recovery_streak_is_the_plans_twenty() -> None:
    """02-architecture.md:831, 08-runtime.md:770, 12-performance.md:1027."""
    assert sp.AIMD_RECOVERY_STREAK == AIMD_RECOVERY_STREAK


def test_the_four_batch_events_are_a_projection_of_failure_class_and_not_a_taxonomy() -> None:
    """08-runtime.md:762 states the constraint: *"`BatchEvent` is a projection of `FailureClass`,
    not a second taxonomy."* Four members, and no `TIMEOUT`: a smaller batch does not make a
    hanging driver finish."""
    assert tuple(event.value for event in sp.BatchEvent) == BATCH_EVENTS


def test_an_oom_halves_the_batch(pure_unit) -> None:  # noqa: ARG001
    """08-runtime.md:766: `RESOURCE_LIMIT | WORKER_DIED -> max(1, batch // 2)`."""
    state = sp.AimdState(batch=32, clean_streak=0, card_max=32)
    assert sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT).batch == 16


def test_halving_bottoms_out_at_one_and_never_reaches_zero(pure_unit) -> None:  # noqa: ARG001
    """`max(1, ...)`: a batch of zero claims nothing and the driver would never run again."""
    state = sp.AimdState(batch=1, clean_streak=0, card_max=32)
    assert sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT).batch == 1


def test_a_crash_goes_straight_to_one_to_localise_the_poison_unit(pure_unit) -> None:  # noqa: ARG001
    """08-runtime.md:768 and 04-driver-system.md:1718: `DRIVER_CRASHED -> 1`."""
    state = sp.AimdState(batch=32, clean_streak=0, card_max=32)
    assert sp.adapt_batch(state, sp.BatchEvent.DRIVER_CRASHED).batch == 1


def test_nineteen_clean_batches_do_not_raise_the_batch_size(pure_unit) -> None:  # noqa: ARG001
    """ "Twenty consecutive" is the claim, so nineteen has to be visibly not enough."""
    state = sp.AimdState(batch=8, clean_streak=0, card_max=32)
    for _ in range(AIMD_RECOVERY_STREAK - 1):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 8
    assert state.clean_streak == AIMD_RECOVERY_STREAK - 1


def test_the_twentieth_clean_batch_raises_the_batch_by_exactly_one(pure_unit) -> None:  # noqa: ARG001
    """ADDITIVE increase. 08-runtime.md:770: `min(batch + 1, card_max)`."""
    state = sp.AimdState(batch=8, clean_streak=0, card_max=32)
    for _ in range(AIMD_RECOVERY_STREAK):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 9


def test_a_non_clean_event_resets_the_streak_so_twenty_means_twenty_in_a_row(
    pure_unit,  # noqa: ARG001
) -> None:
    """The load-bearing word in 02-architecture.md:831 is CONSECUTIVE.

    Without the reset, nineteen clean batches, one OOM and one clean batch would raise the
    ceiling, and the counter would be measuring twenty clean batches EVER. The halving in the
    middle is asserted too, so the test cannot pass by the streak never advancing at all.
    """
    state = sp.AimdState(batch=8, clean_streak=0, card_max=32)
    for _ in range(AIMD_RECOVERY_STREAK - 1):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    state = sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT)
    assert state.batch == 4
    assert state.clean_streak == 0
    state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 4


def test_a_crash_also_resets_the_streak(pure_unit) -> None:  # noqa: ARG001
    """The other non-clean arm. Two arms, two tests: a reset carried by one of them is a reset
    the other can lose."""
    state = sp.AimdState(batch=8, clean_streak=AIMD_RECOVERY_STREAK - 1, card_max=32)
    after = sp.adapt_batch(state, sp.BatchEvent.DRIVER_CRASHED)
    assert (after.batch, after.clean_streak) == (1, 0)


def test_the_streak_resets_on_the_increase_so_recovery_is_one_step_per_twenty(
    pure_unit,  # noqa: ARG001
) -> None:
    """OUR rule, and reported as a gap: the plan's snippet prints the decision and not the
    bookkeeping.

    Forty clean batches are +2 and not +21. Additive increase is a RATE and a rate needs a
    denominator; without this the twenty-first batch and every batch after it would increment,
    which is not additive increase but a ramp.
    """
    state = sp.AimdState(batch=1, clean_streak=0, card_max=32)
    for _ in range(AIMD_RECOVERY_STREAK * 2):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 3


def test_the_increase_stops_at_the_cards_batch_max_units(pure_unit) -> None:  # noqa: ARG001
    """`min(batch + 1, card_max)`: the card's ceiling is the card's, and AIMD may not raise it."""
    state = sp.AimdState(batch=4, clean_streak=0, card_max=4)
    for _ in range(AIMD_RECOVERY_STREAK * 3):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 4


def test_a_halved_batch_climbs_all_the_way_back_because_halve_and_never_recover_is_the_bug(
    pure_unit,  # noqa: ARG001
) -> None:
    """THE property, in the plan's own words (02-architecture.md:831, 12-performance.md:1027):
    *"halve-and-never-recover lets one foreign process permanently cap a driver"*.

    One OOM takes 32 to 16; enough clean batches must take it back to 32. Testing the halving
    alone would leave a module that halves once and caps the driver for the rest of the run
    entirely green, which is the mechanism's whole failure mode.
    """
    state = sp.AimdState(batch=32, clean_streak=0, card_max=32)
    state = sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT)
    assert state.batch == 16
    for _ in range(AIMD_RECOVERY_STREAK * 16 + 1):
        state = sp.adapt_batch(state, sp.BatchEvent.CLEAN)
    assert state.batch == 32


def test_adapt_batch_returns_a_new_state_and_mutates_nothing(pure_unit) -> None:  # noqa: ARG001
    """Pure, and over a `NamedTuple`, so the dispatcher can keep the old value for a retry."""
    state = sp.AimdState(batch=32, clean_streak=7, card_max=32)
    once = sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT)
    twice = sp.adapt_batch(state, sp.BatchEvent.RESOURCE_LIMIT)
    assert state == sp.AimdState(batch=32, clean_streak=7, card_max=32)
    assert once == twice


def test_only_a_crash_earns_the_retry_and_only_once(pure_unit) -> None:  # noqa: ARG001
    """04-driver-system.md:1718 and 02-architecture.md:831: *"retries **once at `batch = 1`**"*.

    "Once" is the load-bearing word: a ladder reading it as "until it stops crashing" multiplies
    a segfaulting driver by the batch size. An OOM halves and re-dispatches through the ordinary
    path, and a timeout is permanent (08-runtime.md:567), so neither earns a retry here.
    """
    assert sp.retry_batch_size(sp.BatchEvent.DRIVER_CRASHED, attempt=0) == 1
    assert sp.retry_batch_size(sp.BatchEvent.DRIVER_CRASHED, attempt=1) is None
    assert sp.retry_batch_size(sp.BatchEvent.DRIVER_CRASHED, attempt=2) is None
    for event in (sp.BatchEvent.CLEAN, sp.BatchEvent.RESOURCE_LIMIT, sp.BatchEvent.WORKER_DIED):
        assert sp.retry_batch_size(event, attempt=0) is None


def test_no_failure_class_projects_onto_worker_died_and_that_is_a_reported_seam() -> None:
    """A FINDING, pinned. 08-runtime.md:528 says a worker that segfaults mid-batch *"feeds
    `WORKER_DIED` to `adapt_batch`"*, while 08-runtime.md:768's own snippet, 02-architecture.md
    :1019 and 04-driver-system.md:1727 all give that same event the `DRIVER_CRASHED` treatment --
    a retry once at `batch = 1`. Halving and going to one are different post-states, so the two
    readings are not compatible.

    This module takes the three-document side: a worker death observed HERE is `DRIVER_CRASHED`.
    `WORKER_DIED` stays in the vocabulary because 08's snippet declares it and because a worker
    that dies BETWEEN batches is the dispatcher's observation, not the host's -- but nothing here
    produces it, and this test is where that is stated rather than left to a reader.
    """
    produced = {
        sp._event_for(sp.HostVerdict(failure_class=cls, message="", permanent=True))
        for cls in FailureClass
    }
    assert sp.BatchEvent.WORKER_DIED not in produced
    assert produced == {
        sp.BatchEvent.CLEAN,
        sp.BatchEvent.RESOURCE_LIMIT,
        sp.BatchEvent.DRIVER_CRASHED,
    }


# =============================================================================================
# 5. Quarantine: per driver, per run, one home, and the round trip through `resolve()`
# =============================================================================================


def ledger() -> sp.CrashLedger:
    return sp.CrashLedger(threshold=CRASH_THRESHOLD, window_s=CRASH_WINDOW_S)


def test_two_crashes_inside_the_window_do_not_quarantine_and_the_third_does() -> None:
    """04-driver-system.md:1720: `crash_quarantine = { crashes = 3, window_s = 60 }`.

    The verdict is asserted at every crash and not only at the third, because a ledger that
    quarantined on the FIRST crash would pass a test that only looked at the end.
    """
    book = ledger()
    assert book.record(DRIVER_ID, now_ms=0) is False
    assert book.record(DRIVER_ID, now_ms=1_000) is False
    assert book.record(DRIVER_ID, now_ms=2_000) is True
    assert book.quarantined() == frozenset({DRIVER_ID})


def test_three_crashes_spread_beyond_the_window_do_not_quarantine() -> None:
    """A corpus with three bad documents in it over an hour is not a dead driver. The window is
    what separates a broken driver from a broken corpus."""
    book = ledger()
    for index in range(6):
        assert book.record(DRIVER_ID, now_ms=index * (CRASH_WINDOW_S * 1_000 + 1)) is False
    assert book.quarantined() == frozenset()


def test_the_window_boundary_is_exclusive_at_exactly_window_s() -> None:
    """A crash exactly `window_s` old has left the window. The boundary is ours -- the plan says
    "in 60 s" and not which end is closed -- and it is pinned here so it cannot drift.

    This half pins `crashes_in_window`, which REPORTS. `record` carries a second copy of the same
    comparison and is the one that DECIDES; the test below pins that one, because relaxing only
    the deciding copy to `<=` left this file green.
    """
    book = ledger()
    book.record(DRIVER_ID, now_ms=0)
    book.record(DRIVER_ID, now_ms=10)
    assert book.crashes_in_window(DRIVER_ID, now_ms=CRASH_WINDOW_S * 1_000) == 1


def test_the_window_the_quarantine_decision_uses_is_exclusive_at_the_boundary_too() -> None:
    """`record()` filters the window itself, and its filter is the one with consequences.

    `crashes_in_window` is a read-only accessor -- nothing in the module or the runner branches on
    it -- so a boundary pinned only there is a boundary pinned nowhere: widening `record`'s
    `now_ms - at < window_ms` to `<=` quarantines a driver on a crash that is exactly `window_s`
    old, and no test noticed. Two crashes and then a third at exactly the window is therefore two
    crashes inside it and not three.
    """
    book = ledger()
    assert book.record(DRIVER_ID, now_ms=0) is False
    assert book.record(DRIVER_ID, now_ms=1) is False
    assert book.record(DRIVER_ID, now_ms=CRASH_WINDOW_S * 1_000) is False
    assert book.quarantined() == frozenset()
    assert book.crashes_in_window(DRIVER_ID, now_ms=CRASH_WINDOW_S * 1_000) == 2


def test_a_quarantine_is_sticky_for_the_run_and_no_later_crash_or_success_clears_it() -> None:
    """04-driver-system.md:1720 is *"for the run"*, and `resolve()` re-planning is the recovery
    path (02-architecture.md:831). A ledger that forgot on success would re-offer a driver that
    crashes every fourth document forever.

    There is no `clear`, no `forget` and no `reset` on the class, and that absence is asserted:
    a run-scoped fact needs no cleanup step, and a cleanup step is only tested by state the next
    run will not recreate.
    """
    book = ledger()
    for moment in (0, 1, 2):
        book.record(DRIVER_ID, now_ms=moment)
    assert book.quarantined() == frozenset({DRIVER_ID})
    assert book.record(DRIVER_ID, now_ms=10_000_000) is True
    assert book.quarantined() == frozenset({DRIVER_ID})
    assert [name for name in dir(book) if name in {"clear", "reset", "forget", "release"}] == []


def test_one_drivers_crashes_never_quarantine_another() -> None:
    """Keyed on `driver_id`, and the whole point of :1720's *"the **driver** -- not the unit"*."""
    book = ledger()
    for moment in (0, 1, 2):
        book.record(DRIVER_ID, now_ms=moment)
    assert book.record("parse.office.anydoc", now_ms=3) is False
    assert book.quarantined() == frozenset({DRIVER_ID})


def test_the_ledger_refuses_a_threshold_that_would_quarantine_on_no_crash() -> None:
    """`crashes = 0` would take every driver out before the first document."""
    with pytest.raises(DriverHostError, match="no crash at all"):
        sp.CrashLedger(threshold=0, window_s=CRASH_WINDOW_S)


def test_the_pool_records_a_crash_against_the_driver_and_publishes_one_set() -> None:
    """INV-21: the host PRODUCES `quarantined()` and there is no second channel.

    The type is `frozenset[str]` because that is exactly what
    `omniweave_core.drivers.resolve.Policy.quarantined` holds; anything else would need a
    conversion, and a conversion is where a second representation starts.
    """
    clock = Clock(step=1_000)
    pool = sp.WorkerPool(spawn=lambda _request: FakeProcess(), settings=settings(), now_ms=clock)
    for _ in range(CRASH_THRESHOLD - 1):
        assert pool.note_crash(DRIVER_ID) is False
    assert pool.note_crash(DRIVER_ID) is True
    assert pool.quarantined() == frozenset({DRIVER_ID})
    assert isinstance(pool.quarantined(), frozenset)


def test_three_crashes_in_the_window_stop_resolve_from_offering_that_driver() -> None:
    """THE ROUND TRIP, end to end: 02-architecture.md:831's own sentence.

    *"three crashes in 60 s quarantines the **driver** for the run, not the unit; `resolve()`
    then returns `RejectCode.QUARANTINED` and the router re-plans."* The host produces the set,
    `Policy` carries it, `resolve()`'s sixteenth gate reads it.

    The SAME requirement and the SAME catalog are resolved twice -- once with the set the pool
    produced and once with an empty one -- so what changed the outcome is demonstrably the
    quarantine and not the fixture. A test that only ran the rejecting half would pass over a
    catalog that never offered the driver at all.
    """
    clear_memo()
    card = pdf_card()
    catalog = catalog_of(card)
    clock = Clock(step=1_000)
    pool = sp.WorkerPool(spawn=lambda _request: FakeProcess(), settings=settings(), now_ms=clock)

    offered = resolve(requirement(), catalog, policy_with(frozenset()))
    assert [candidate.driver_id for candidate in offered.candidates] == [DRIVER_ID]

    for _ in range(CRASH_THRESHOLD):
        pool.note_crash(DRIVER_ID)
    refused = resolve(requirement(), catalog, policy_with(pool.quarantined()))
    assert refused.candidates == ()
    assert [rejection.code for rejection in refused.rejected] == [RejectCode.QUARANTINED]
    assert "quarantined" in refused.rejected[0].detail


def test_two_crashes_leave_resolve_still_offering_the_driver() -> None:
    """The threshold is a threshold. Two crashes is a driver having a bad day, and taking it out
    of every plan would be a worse outage than the crashes."""
    clear_memo()
    catalog = catalog_of(pdf_card())
    clock = Clock(step=1_000)
    pool = sp.WorkerPool(spawn=lambda _request: FakeProcess(), settings=settings(), now_ms=clock)
    for _ in range(CRASH_THRESHOLD - 1):
        pool.note_crash(DRIVER_ID)
    still = resolve(requirement(), catalog, policy_with(pool.quarantined()))
    assert [candidate.driver_id for candidate in still.candidates] == [DRIVER_ID]


# =============================================================================================
# 6. The worker key, and why it is a correctness property
# =============================================================================================


def test_the_worker_key_is_exactly_driver_id_and_config_digest() -> None:
    """02-architecture.md:85, :482. TWO components; `dispatch_key` (:481) has three and is the
    queue's. Conflating them gives one driver two workers for one configuration whenever the
    isolation grant differs by a shortfall."""
    assert sp.WorkerKey._fields == WORKER_KEY_FIELDS


def test_the_config_digest_that_keys_a_worker_is_identitys_and_its_value_is_pinned() -> None:
    """`config_digest` is `sha256_canonical` over the full resolved config (identity.py:350).

    The expectation is a LITERAL, not a second call: two configs that differ must key two
    workers, and a test that computed both sides from `config_digest` would still pass if the
    recipe changed under it -- which would re-key every worker in every run and is exactly the
    change that must not happen silently.
    """
    assert config_digest(CONFIG_A) == DIGEST_A
    assert config_digest(CONFIG_B) == DIGEST_B
    assert DIGEST_A != DIGEST_B


def test_one_key_gets_one_worker_and_a_second_acquire_reuses_it() -> None:
    """*"One long-lived worker per `(driver_id, config_digest)`"* (04-driver-system.md:1670).

    The spawn is counted, because "reuse" is a claim about a process that was NOT created and
    the returned object being identical is not by itself evidence of that.
    """
    built: list[sp.Worker] = []
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=settings(), now_ms=Clock())
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)

    def build() -> sp.Worker:
        worker, _proc, _clock = worker_on(FakeChannel())
        built.append(worker)
        return worker

    first = pool.acquire(key, cost_class="free", build=build)
    second = pool.acquire(key, cost_class="free", build=build)
    assert first is second
    assert len(built) == 1
    assert pool.live_keys() == (key,)


def test_a_changed_configuration_gets_a_new_worker_and_never_the_first_ones() -> None:
    """A CORRECTNESS property and not a cache optimisation (02-architecture.md:85).

    Two configurations sharing a worker means one configuration's work is done under the other's
    settings -- a wrong answer, not a slow one. So the second digest must spawn, and both workers
    must be live afterwards: a pool that EVICTED the first would also be wrong, because the first
    configuration's next batch would then pay the model load again.
    """
    keys: list[sp.WorkerKey] = []
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=settings(), now_ms=Clock())

    def build_for(key: sp.WorkerKey) -> sp.Worker:
        keys.append(key)
        return sp.Worker(
            key,
            FakeProcess(),
            FakeChannel(),
            settings=settings(),
            now_ms=Clock(),
            stderr=sp.StderrRing(),
        )

    key_a = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=config_digest(CONFIG_A))
    key_b = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=config_digest(CONFIG_B))
    first = pool.acquire(key_a, cost_class="free", build=lambda: build_for(key_a))
    second = pool.acquire(key_b, cost_class="free", build=lambda: build_for(key_b))
    assert first is not second
    assert keys == [key_a, key_b]
    assert sorted(pool.live_keys()) == sorted([key_a, key_b])


def test_the_pool_refuses_a_worker_built_for_another_key() -> None:
    """The key is the pool's whole contract, so a `build` that returns something else is a bug
    the pool must not file under the key it was asked for."""
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=settings(), now_ms=Clock())
    other = sp.WorkerKey(driver_id="parse.office.anydoc", config_digest=DIGEST_B)

    def build() -> sp.Worker:
        worker, _proc, _clock = worker_on(FakeChannel())
        return worker  # keyed (parse.pdf.pdfium, DIGEST_A)

    with pytest.raises(DriverHostError, match="returned a worker keyed"):
        pool.acquire(other, cost_class="free", build=build)
    assert pool.live_keys() == ()


# =============================================================================================
# 7. The pool: `max_workers` per cost class, and `worker_idle_ttl_s`
# =============================================================================================


def build_worker(key: sp.WorkerKey, *, clock: Clock, host: sp.HostSettings) -> sp.Worker:
    return sp.Worker(
        key,
        FakeProcess(status=0),
        FakeChannel(),
        settings=host,
        now_ms=clock,
        stderr=sp.StderrRing(),
    )


def test_the_pool_refuses_the_worker_that_would_exceed_max_workers_rather_than_clamping() -> None:
    """08-runtime.md:704: the analogous check is *"a **refusal** naming `[drivers]
    max_workers`"*, because *"a silent clamp would have made an operator's `max_workers = 4` a
    lie recorded nowhere"* (:735). Four `free` workers under `max_workers.free = 4`, then a
    refusal that names the knob."""
    host = settings(max_workers={"free": 2, "local_compute": 4, "billed_api": 8})
    clock = Clock()
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    for index in range(2):
        key = sp.WorkerKey(driver_id=f"parse.a.{index}", config_digest=DIGEST_A)
        pool.acquire(
            key, cost_class="free", build=lambda k=key: build_worker(k, clock=clock, host=host)
        )
    third = sp.WorkerKey(driver_id="parse.a.2", config_digest=DIGEST_A)
    with pytest.raises(DriverHostError, match=r"max_workers"):
        pool.acquire(
            third, cost_class="free", build=lambda: build_worker(third, clock=clock, host=host)
        )
    assert pool.live_count("free") == 2


def test_the_cap_is_per_cost_class_and_a_full_class_does_not_block_another() -> None:
    """`max_workers` is a TABLE per cost class (04-driver-system.md:1782), so a `free` class at
    its ceiling has no bearing on a `billed_api` worker."""
    host = settings(max_workers={"free": 1, "local_compute": 4, "billed_api": 8})
    clock = Clock()
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    free_key = sp.WorkerKey(driver_id="parse.a.free", config_digest=DIGEST_A)
    billed_key = sp.WorkerKey(driver_id="parse.a.billed", config_digest=DIGEST_A)
    pool.acquire(
        free_key, cost_class="free", build=lambda: build_worker(free_key, clock=clock, host=host)
    )
    pool.acquire(
        billed_key,
        cost_class="billed_api",
        build=lambda: build_worker(billed_key, clock=clock, host=host),
    )
    assert (pool.live_count("free"), pool.live_count("billed_api")) == (1, 1)


def test_an_unknown_cost_class_is_refused_and_the_three_are_named() -> None:
    """A typo in a cost class would otherwise mean "no cap", which is the direction that fails
    open."""
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=settings(), now_ms=Clock())
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)
    with pytest.raises(DriverHostError, match="billed_api"):
        pool.acquire(
            key,
            cost_class="free_tier",
            build=lambda: build_worker(key, clock=Clock(), host=settings()),
        )


def test_a_worker_idle_for_exactly_the_ttl_survives_one_more_tick() -> None:
    """The comparison is strictly greater, which is OUR boundary: 08-runtime.md:2590 gives the
    300 s and not which end is closed. Pinned so it cannot drift silently."""
    host = settings()
    clock = Clock(now=1_000_000)
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(status=0), settings=host, now_ms=clock)
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)
    pool.acquire(key, cost_class="free", build=lambda: build_worker(key, clock=clock, host=host))
    clock.advance(WORKER_IDLE_TTL_S * 1_000)
    assert pool.reap_idle() == ()
    clock.advance(1)
    assert pool.reap_idle() == (key,)
    assert pool.live_keys() == ()


def test_the_ttl_is_measured_from_the_last_use_and_not_from_the_spawn() -> None:
    """12-performance.md:723 prices the worker's fixed cost as *"the single largest fixed cost in
    the pipeline, at 21x the in-process call it wraps"*, which a BUSY worker has already paid.
    A TTL measured from the spawn would reap a worker in the middle of a corpus."""
    host = settings()
    clock = Clock(now=0)
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(status=0), settings=host, now_ms=clock)
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)
    worker = pool.acquire(
        key, cost_class="free", build=lambda: build_worker(key, clock=clock, host=host)
    )
    clock.advance(WORKER_IDLE_TTL_S * 1_000 - 1)
    worker.touch()
    clock.advance(WORKER_IDLE_TTL_S * 1_000)
    assert pool.reap_idle() == ()


def test_a_reaped_worker_is_stopped_and_forgotten_so_the_next_acquire_spawns() -> None:
    """A pool that reaped without forgetting would hand out a dead worker, and one that forgot
    without stopping would leak the process the TTL exists to release."""
    host = settings()
    clock = Clock(now=0)
    processes: list[FakeProcess] = []
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)

    def build() -> sp.Worker:
        proc = FakeProcess(status=0)
        processes.append(proc)
        return sp.Worker(
            key, proc, FakeChannel(), settings=host, now_ms=clock, stderr=sp.StderrRing()
        )

    pool.acquire(key, cost_class="free", build=build)
    clock.advance(WORKER_IDLE_TTL_S * 1_000 + 1)
    assert pool.reap_idle() == (key,)
    pool.acquire(key, cost_class="free", build=build)
    assert len(processes) == 2
    assert processes[0].waited  # it was asked to exit, not just dropped


def test_a_stopped_worker_is_never_handed_out_again() -> None:
    """`acquire` checks `Worker.stopped` and nothing tested the branch.

    A worker is stopped by the crash path, by `reap_idle` and by `stop()` on the graceful exit,
    and after any of them its channel is closed and its child is gone. Deleting the `stopped`
    check from `acquire` -- so the pool hands the dead one back -- left this file green, which
    means every `INVOKE` after a mid-run stop would have gone to a closed pipe. The spawn count
    is what carries the claim: the second `acquire` must BUILD, not return.
    """
    host = settings()
    clock = Clock()
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)
    built: list[sp.Worker] = []

    def build() -> sp.Worker:
        worker = build_worker(key, clock=clock, host=host)
        built.append(worker)
        return worker

    first = pool.acquire(key, cost_class="free", build=build)
    assert first.stopped is False
    first.stop()
    assert first.stopped is True
    second = pool.acquire(key, cost_class="free", build=build)
    assert second is not first
    assert len(built) == 2
    assert pool.live_keys() == (key,)


def test_discard_forgets_the_worker_the_crash_path_has_already_killed() -> None:
    """`discard()` is the crash path's bookkeeping and NO test exercised it.

    Replacing its whole body with `return` left this file green, and the defect that shape ships
    is specific: a worker the host has just killed stays in `live_keys()`, keeps counting against
    `[drivers] max_workers` for the rest of the run, and the next `acquire` for its key hands
    back the corpse. The channel close is asserted too, because releasing the transport the
    reader thread is parked on is what dropping the entry is FOR.
    """
    host = settings(max_workers={"free": 1, "local_compute": 4, "billed_api": 8})
    clock = Clock()
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    key = sp.WorkerKey(driver_id=DRIVER_ID, config_digest=DIGEST_A)
    channel = FakeChannel()
    worker = pool.acquire(
        key,
        cost_class="free",
        build=lambda: sp.Worker(
            key,
            FakeProcess(status=-11),
            channel,
            settings=host,
            now_ms=clock,
            stderr=sp.StderrRing(),
        ),
    )
    worker.kill()
    pool.discard(key)
    assert pool.live_keys() == ()
    assert pool.live_count("free") == 0
    assert channel.closed is True
    # `max_workers.free = 1`: a pool that had not forgotten would refuse this spawn.
    again = pool.acquire(
        key, cost_class="free", build=lambda: build_worker(key, clock=clock, host=host)
    )
    assert again is not worker


def test_closing_the_pool_stops_every_worker_and_leaves_no_key() -> None:
    """End of run. Run-scoped, never a daemon (02-architecture.md:155, :677)."""
    host = settings()
    clock = Clock()
    pool = sp.WorkerPool(spawn=lambda _r: FakeProcess(), settings=host, now_ms=clock)
    for index in range(3):
        key = sp.WorkerKey(driver_id=f"parse.a.{index}", config_digest=DIGEST_A)
        pool.acquire(
            key, cost_class="free", build=lambda k=key: build_worker(k, clock=clock, host=host)
        )
    pool.close()
    assert pool.live_keys() == ()
    assert pool.live_count("free") == 0


def test_host_settings_reads_the_five_numbers_off_a_resolved_config(tmp_path: Path) -> None:
    """The five are `config.py`'s and this module declares none of them.

    Every expectation is the PLAN's literal (08-runtime.md:2590-2591, :2444 and
    04-driver-system.md:1769-1774) and not a second read of the config, so the test pins the
    numbers rather than pinning `config.py` against itself.
    """
    from omniweave_core.config import load  # noqa: PLC0415 -- see the note below

    # Imported inside the test because `HostSettings.from_config` takes `object` and reaches
    # through `getattr` precisely so that `host/subproc.py` need not import `config`; a
    # module-level import here would be a wider dependency than the subject has.
    cfg = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    resolved = sp.HostSettings.from_config(cfg)
    assert resolved.worker_idle_ttl_s == WORKER_IDLE_TTL_S
    assert (resolved.crash_threshold, resolved.crash_window_s) == (
        CRASH_THRESHOLD,
        CRASH_WINDOW_S,
    )
    assert resolved.tick_ms == LOOP_LAG_MAX_MS
    assert dict(resolved.max_workers) == MAX_WORKERS


def test_host_settings_has_no_defaults_so_a_number_cannot_drift_from_the_config() -> None:
    """INV-21. A default here would be a second home for a `[drivers]` key and the two could
    disagree silently -- which is the failure 08-runtime.md:735 describes for `max_workers`."""
    with pytest.raises(TypeError):
        sp.HostSettings()  # type: ignore[call-arg]


def test_from_config_refuses_something_that_is_not_a_resolved_config() -> None:
    """`getattr(cfg, "get")` is the whole duck type, so the refusal has to name what was wrong."""
    with pytest.raises(DriverHostError, match="not a resolved Config"):
        sp.HostSettings.from_config(object())


# =============================================================================================
# 8. The reader that does not oblige a hostile driver (04-driver-system.md section 6.5)
# =============================================================================================


def test_a_prefix_declaring_four_gigabytes_is_refused_before_a_single_byte_is_allocated() -> None:
    """04-driver-system.md:1791: *"checked **before** any allocation; the reader allocates
    exactly the declared length and never speculatively"*.

    The assertion is not only that it raises: the channel RECORDS every size it was asked for,
    and the 4 GiB is never among them. A reader that refused after the read would have asked.
    """
    liar = (0xFFFFFFFF).to_bytes(4, "little") + (0).to_bytes(4, "little")
    channel = FakeChannel(liar)
    with pytest.raises(DriverHostError, match="header_too_large"):
        sp.next_frame(channel)
    assert channel.asked == [wire.PREFIX_BYTES]


def test_a_body_longer_than_inline_max_is_refused_before_it_is_read() -> None:
    """The other cap, and the same order. `body_len <= INLINE_MAX` (04-driver-system.md:1676)."""
    liar = (10).to_bytes(4, "little") + (wire.MAX_BODY_BYTES + 1).to_bytes(4, "little")
    channel = FakeChannel(liar)
    with pytest.raises(DriverHostError, match="body_too_large"):
        sp.next_frame(channel)
    assert channel.asked == [wire.PREFIX_BYTES]


def test_a_frame_whose_header_stops_short_is_a_truncation_and_not_a_partial_frame() -> None:
    """Framing cannot tell "not yet" from "never" without a clock, so a short read at EOF is a
    refusal. The distinction that DOES exist is the one below: nothing at all is a clean EOF."""
    whole = wire.encode(wire.FrameKind.LOG, {"level": "info", "event": "x"})
    channel = FakeChannel(whole[:-4])
    with pytest.raises(DriverHostError, match="header_truncated"):
        sp.next_frame(channel)


def test_a_body_shorter_than_the_declared_length_is_a_truncation() -> None:
    """A body that is not the declared length is 04-driver-system.md section 6.5's third attack."""
    whole = wire.encode(wire.FrameKind.RESULT, {"unit_index": 0}, b"0123456789")
    channel = FakeChannel(whole[:-5])
    with pytest.raises(DriverHostError, match="body_truncated"):
        sp.next_frame(channel)


def test_nothing_at_all_at_a_frame_boundary_is_a_clean_end_of_stream() -> None:
    """The one distinction `wire.read_frame` cannot make and must not: a zero-byte read AT a
    frame boundary is a worker that exited, and that is a lifecycle fact."""
    assert sp.next_frame(FakeChannel()) is None


def test_a_worker_that_sends_a_host_to_driver_frame_is_refused_by_direction() -> None:
    """A worker that sends `INVOKE` is confused or hostile, and a host that read one would be
    taking dispatch orders from a third party's process (04-driver-system.md:1693)."""
    channel = FakeChannel(wire.encode(wire.FrameKind.INVOKE, {"invoke_id": "x"}))
    with pytest.raises(DriverHostError, match="direction_unexpected"):
        sp.next_frame(channel)


def test_a_frame_flood_fills_the_bounded_queue_and_then_the_host_stops_reading() -> None:
    """04-driver-system.md:1793, and the mechanism rather than the number.

    *"A full queue means the host **stops reading**; pipe backpressure stalls the driver, and
    `wall_ms_hard` fires. No frame is buffered on the host's behalf."* The channel counts frames
    it HANDED OUT, so a reader that kept draining into memory would show a number that keeps
    climbing; the assertion is that it stops within a frame or two of the bound.

    `flood.served` is the whole instrument. `reader.depth() <= FRAME_QUEUE_MAX` is `Queue`'s own
    invariant for a queue built with that `maxsize` and can fail only if the standard library
    does -- it is a sanity line, not a claim. The bound the HOST runs on is the DEFAULT this test
    overrides, and it is pinned by
    `test_the_queue_the_worker_actually_reads_into_is_bounded_without_being_told`.
    """
    flood = FloodChannel(wire.encode(wire.FrameKind.LOG, {"level": "info", "event": "spin"}))
    reader = sp.FrameReader(flood, maxsize=FRAME_QUEUE_MAX)
    deadline = time.monotonic() + 2.0
    while flood.served <= FRAME_QUEUE_MAX and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    assert reader.depth() <= FRAME_QUEUE_MAX
    assert flood.served <= FRAME_QUEUE_MAX + 4, flood.served
    flood.close()


def test_the_read_queues_bound_is_the_plans_frame_queue_max() -> None:
    """04-driver-system.md:1793 and :2849, glossary.md:662. Not a config key: a knob here would
    let an operator turn the backpressure off, which is the one thing it guarantees."""
    assert sp.FRAME_QUEUE_MAX == FRAME_QUEUE_MAX


def test_a_driver_that_says_nothing_forever_is_a_bounded_refusal_and_not_a_hang() -> None:
    """The whole of section 6.5 in one test: the read is blocking, the SUPERVISOR is not.

    The channel parks instead of ending, so the only thing that can finish this invocation is the
    host's clock. **The call is made on a thread and the bound is the join** -- see
    `invoke_bounded`: an `assert elapsed < 5.0` written after the call is unreachable on the one
    module this test exists to reject, the one whose queue read has no deadline, and a test that
    hangs instead of failing has told nobody anything.
    """
    channel = FakeChannel(block_at_eof=True)
    worker, _proc, _clock = worker_on(channel, clock=Clock(step=100))
    report = invoke_bounded(
        worker, invocation(1), limits=deadlines(progress=400, wall=10_000), patience_s=5.0
    )
    verdict = report.failures[0]
    assert verdict is not None
    assert verdict.failure_class is FailureClass.TIMEOUT
    assert verdict.limit == "progress_ms"
    assert verdict.permanent is True
    channel.close()


def test_a_frame_that_never_ends_is_refused_on_the_deadline_rather_than_waited_out() -> None:
    """A worker that sends half a frame and then parks: the reader is stuck mid-frame, so no
    terminal ever arrives, and the supervisor's own clock is what ends the invocation."""
    half = wire.encode(wire.FrameKind.RESULT, {"invoke_id": "inv-1", "unit_index": 0})[:6]
    channel = FakeChannel(half, block_at_eof=True)
    worker, _proc, _clock = worker_on(channel, clock=Clock(step=100))
    report = invoke_bounded(
        worker, invocation(1), limits=deadlines(progress=300, wall=10_000), patience_s=5.0
    )
    verdict = report.failures[0]
    assert verdict is not None and verdict.failure_class is FailureClass.TIMEOUT
    channel.close()


def test_a_log_flood_cannot_extend_a_drivers_own_wall_clock() -> None:
    """04-driver-system.md:1794: *"a driver cannot extend its own wall clock."*

    A real flood over a real reader thread: `wall_ms_hard` is short, `progress_ms` is generous
    and no `PROGRESS` frame is ever sent, so only the backstop can end the invocation, and the
    `LOG` frames are asserted to have arrived so the flood is known to have been real.

    **What this test does NOT pin, contrary to what it used to claim, is the ORDER of the tick.**
    Deleting `_await_frame`'s deadline check that runs BEFORE the queue read leaves this test
    green in under five milliseconds (measured: 175 passed), because a reader thread cannot keep
    a real `Queue` non-empty against a supervisor popping one frame per tick -- `get` returns
    `None` within a tick or two and the POST-read check ends the invocation instead. The order is
    pinned by `test_a_progress_flood_cannot_extend_the_wall_clock_when_the_queue_is_never_empty`
    below, which removes that race by removing the queue.
    """
    flood = FloodChannel(wire.encode(wire.FrameKind.LOG, {"level": "info", "event": "spin"}))
    worker, _proc, _clock = worker_on(flood, clock=Clock(step=50))
    report = invoke_bounded(
        worker, invocation(1), limits=deadlines(progress=100_000, wall=400), patience_s=5.0
    )
    verdict = report.failures[0]
    assert verdict is not None
    assert verdict.failure_class is FailureClass.TIMEOUT
    assert verdict.limit == "wall_ms_hard"
    assert report.progress_count == 0
    assert len(report.logs) > 0
    flood.close()


def test_a_progress_flood_cannot_extend_the_wall_clock_when_the_queue_is_never_empty() -> None:
    """04-driver-system.md:1794's own attack row: *"a `PROGRESS` flood to hold the worker alive |
    `progress_ms` resets, but `wall_ms_hard` does not, and it is the backstop. A driver cannot
    extend its own wall clock."*

    THE test for the tick's ORDER, and the reason the `LOG` flood above is not it. `_await_frame`
    returns from the frame branch WITHOUT consulting the clock -- deliberately, because the
    pre-read check has already done it -- so the whole of the ordering claim rests on that
    leading check. A reader with a real queue lets the post-read check cover for it whenever the
    queue happens to run dry, which it always does; `ReadyReader` never runs dry, so if the
    leading check is deleted this invocation never ends. Deleting it is a green suite today and a
    `patience_s` failure here.

    `PROGRESS` and not `LOG` because `PROGRESS` is the frame that DOES reset a deadline: the
    driver is resetting `progress_ms` on every frame and the only bound left is the one it cannot
    touch.
    """
    worker, _proc, clock = worker_on(FakeChannel(), clock=Clock(step=50))
    reader = ReadyReader(one_frame(wire.FrameKind.PROGRESS, {"done": 1, "total": 2}))
    worker._reader = reader  # the queue IS the race, so this test removes the queue
    report = invoke_bounded(
        worker, invocation(1), limits=deadlines(progress=100_000, wall=400), patience_s=5.0
    )
    verdict = report.failures[0]
    assert verdict is not None
    assert verdict.failure_class is FailureClass.TIMEOUT
    assert verdict.limit == "wall_ms_hard"
    assert report.progress_count > 0, "no frame was ever read, so nothing was held off"
    assert reader.gets > 0
    assert clock.value >= 400


def test_the_queue_the_worker_actually_reads_into_is_bounded_without_being_told() -> None:
    """The bound the HOST runs on is `FrameReader`'s DEFAULT, because `Worker` passes no `maxsize`.

    04-driver-system.md:1793: *"the host reads into a bounded queue, `frame_queue_max = 256` ...
    No frame is buffered on the host's behalf."* `test_a_frame_flood_fills_the_bounded_queue...`
    constructs the reader itself and passes `maxsize=FRAME_QUEUE_MAX`, which exercises a value no
    production caller ever passes: changing the signature's default to `maxsize=0` -- an unbounded
    queue, the one thing the mechanism exists to prevent -- leaves that test and the whole file
    green (measured: 175 passed). This test goes through a `Worker`, which is the only way the
    default is ever the value in force.

    `flood.served` is the instrument for the same reason it is there: a reader that kept draining
    into host memory shows a number that keeps climbing.
    """
    flood = FloodChannel(wire.encode(wire.FrameKind.LOG, {"level": "info", "event": "spin"}))
    worker, _proc, _clock = worker_on(flood)
    deadline = time.monotonic() + 2.0
    while flood.served <= FRAME_QUEUE_MAX and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    assert worker.reader.depth() <= FRAME_QUEUE_MAX
    assert flood.served <= FRAME_QUEUE_MAX + 4, flood.served
    flood.close()


def test_a_result_for_a_unit_outside_the_batch_kills_the_worker() -> None:
    """04-driver-system.md:1796: *"`unit_index` is validated against the batch; out of range is
    a protocol error and the worker is killed, not trusted."*

    The kill is asserted on the process, not inferred from the raise: a host that raised without
    killing would leave a process that has just claimed a unit outside its own batch running, and
    its next frame is not worth reading.
    """
    channel = FakeChannel(result_frame(99))
    worker, proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="unit_index 99"):
        worker.invoke(invocation(2), deadlines=deadlines())
    assert proc.kills == 1


@pytest.mark.parametrize("bad", [-1, True, "0", 2.0, None])
def test_a_unit_index_that_is_not_an_index_in_range_is_refused(bad: object) -> None:
    """A negative index is `list[-1]`, and `True` is `1` to `isinstance(x, int)`. Both would
    write a result onto the wrong unit, which is worse than refusing the frame."""
    channel = FakeChannel(result_frame(0, unit_index=bad))  # type: ignore[arg-type]
    worker, proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="unit_index"):
        worker.invoke(invocation(2), deadlines=deadlines())
    assert proc.kills == 1


def test_a_result_carrying_a_failure_class_outside_the_closed_set_is_a_protocol_error() -> None:
    """`FailureClass` has thirteen members and it is frozen at the end of P3
    (16-roadmap.md:499). A fourteenth from a driver is a protocol error, not a new class."""
    channel = FakeChannel(result_frame(0, failure_class="exploded"))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="thirteen FailureClass"):
        worker.invoke(invocation(1), deadlines=deadlines())


def test_a_result_reporting_a_transient_class_with_no_cooldown_is_named_not_a_value_error() -> None:
    """A hostile worker may send `failure_class = "timeout"` with no `retry_after_ms`, which
    `DriverError.__post_init__` refuses with a `ValueError`.

    An unnamed `ValueError` crossing the seam is what section 6.5 forbids -- the assertion is a
    bounded REFUSAL, and a refusal has a name and a fix. The refusal is ours (02:1060).
    """
    channel = FakeChannel(result_frame(0, failure_class="timeout", message="slow"))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="does not satisfy DriverError"):
        worker.invoke(invocation(1), deadlines=deadlines())


def test_a_result_claiming_ok_partial_with_no_reason_is_named_too() -> None:
    """`DriverResult.__post_init__` requires `partial_reason` for `ok_partial`, and the same
    argument applies: the refusal is named, and the worker's own handler owes the field."""
    channel = FakeChannel(result_frame(0, outcome="ok_partial"))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="does not satisfy DriverResult"):
        worker.invoke(invocation(1), deadlines=deadlines())


def test_an_outcome_outside_ok_and_ok_partial_is_refused() -> None:
    """INV-7 gives a driver exactly two outcomes; `skipped_cached` and the rest are the
    RUNNER's (08-runtime.md section 1.3)."""
    channel = FakeChannel(result_frame(0, outcome="skipped_cached"))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="not one of 'ok', 'ok_partial'"):
        worker.invoke(invocation(1), deadlines=deadlines())


def test_a_frame_a_worker_may_not_send_during_an_invoke_is_refused() -> None:
    """`HELLO_ACK` is a legal drv->host kind in the wrong PHASE. The direction and the phase are
    both grammar, and only the direction is `wire.py`'s to check."""
    channel = FakeChannel(wire.encode(wire.FrameKind.HELLO_ACK, {"driver_id": DRIVER_ID}))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="not a frame a worker may send"):
        worker.invoke(invocation(1), deadlines=deadlines())


# =============================================================================================
# 9. One RESULT per unit, and what happens to the units that get none
# =============================================================================================


def test_one_result_per_unit_makes_the_batch_invisible_to_the_ledgers() -> None:
    """04-driver-system.md:1715 and 08-runtime.md:776's I24: *"one `RESULT` frame per unit, one
    `work` transition per unit"*, so a batch of two produces two results and one clean event."""
    channel = FakeChannel(result_frame(0), result_frame(1))
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(2), deadlines=deadlines())
    assert [None if r is None else r.outcome for r in report.results] == ["ok", "ok"]
    assert report.failures == (None, None)
    assert report.event is sp.BatchEvent.CLEAN
    assert report.unanswered() == ()


def test_an_ok_partial_result_keeps_its_reason() -> None:
    """`ok_partial` requires `partial_reason` and the host carries the driver's own words."""
    channel = FakeChannel(result_frame(0, outcome="ok_partial", partial_reason="page 4 encrypted"))
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(1), deadlines=deadlines())
    first = report.results[0]
    assert isinstance(first, DriverResult)
    assert (first.outcome, first.partial_reason) == ("ok_partial", "page 4 encrypted")


def test_a_progress_frame_is_counted_and_a_log_frame_is_kept() -> None:
    """`PROGRESS` is the only frame that resets `progress_ms` (04:1735), which is only checkable
    if somebody counted them; `LOG` is *"structured only"* (:1701) and goes to the observability
    path rather than into the verdict."""
    channel = FakeChannel(
        wire.encode(wire.FrameKind.PROGRESS, {"invoke_id": "inv-1", "done": 1, "total": 2}),
        wire.encode(wire.FrameKind.LOG, {"level": "warn", "event": "slow_page"}),
        result_frame(0),
    )
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(1), deadlines=deadlines())
    assert report.progress_count == 1
    assert [dict(entry)["event"] for entry in report.logs] == ["slow_page"]


def test_a_worker_that_dies_mid_batch_puts_the_crash_on_exactly_one_unit() -> None:
    """04-driver-system.md:1719: *"The death is `FAILED_PERMANENT{DRIVER_CRASHED}` on **one**
    unit"*, and the retry at `batch = 1` is what localises which.

    So the other unanswered units stay unanswered -- `unanswered()` names them -- and the
    dispatcher returns them to `pending`. A host that spread the crash over the whole batch would
    have marked units permanently failed that nothing was ever attempted for
    (08-runtime.md:524-528).
    """
    ring = sp.StderrRing()
    ring.feed(b"Segmentation fault\n")
    channel = FakeChannel(result_frame(0))
    worker, proc, _clock = worker_on(channel, proc=FakeProcess(status=-11), ring=ring)
    report = worker.invoke(invocation(3), deadlines=deadlines())
    assert report.results[0] is not None
    crash = report.failures[1]
    assert crash is not None
    assert crash.failure_class is FailureClass.DRIVER_CRASHED
    assert crash.exit_status == -11
    assert crash.stderr_tail == b"Segmentation fault\n"
    assert report.failures[2] is None
    assert report.unanswered() == (2,)
    assert report.event is sp.BatchEvent.DRIVER_CRASHED
    assert proc.pid  # the process object is the one the verdict was synthesised from


def test_a_fatal_frame_lands_on_every_unit_that_will_now_never_be_answered() -> None:
    """04-driver-system.md:1705: `FATAL{failure_class, detail}` is *"the driver's last words"*.

    Unlike a crash, a `FATAL` is a statement about the whole invocation: the worker has told us
    it is done. Every unanswered unit takes it, because a unit with neither a result nor a
    failure is a work row nothing ever transitions.
    """
    channel = FakeChannel(
        result_frame(0),
        wire.encode(wire.FrameKind.FATAL, {"failure_class": "corrupt_input", "detail": "bad xref"}),
    )
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(3), deadlines=deadlines())
    assert report.results[0] is not None
    for index in (1, 2):
        verdict = report.failures[index]
        assert verdict is not None
        assert verdict.failure_class is FailureClass.CORRUPT_INPUT
        assert verdict.detected_by == "driver"
        assert "bad xref" in verdict.message
    assert report.unanswered() == ()


def test_a_fatal_with_an_unknown_class_is_a_driver_bug_and_not_a_protocol_error() -> None:
    """The one place a vocabulary violation is downgraded instead of killing, and the reason is
    attribution: a well-formed frame in which a dying driver says something we do not recognise
    is the driver being broken, which is what `driver_bug` means."""
    channel = FakeChannel(
        wire.encode(wire.FrameKind.FATAL, {"failure_class": "kaboom", "detail": "x"})
    )
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(1), deadlines=deadlines())
    verdict = report.failures[0]
    assert verdict is not None
    assert verdict.failure_class is FailureClass.DRIVER_BUG


def test_an_oom_verdict_projects_onto_the_halving_arm_and_a_timeout_onto_neither() -> None:
    """08-runtime.md:762's projection, from the host's side: only `driver_crashed` and
    `resource_limit` move the batch size, and a timeout leaves it alone because a smaller batch
    does not make a hanging driver finish."""
    channel = FakeChannel(
        result_frame(
            0,
            failure_class="resource_limit",
            limit="memory_mb",
            message="over",
            # A DRIVER-reported `resource_limit` is transient (08-runtime.md:567), so
            # charter D3 REQUIRES the cooldown; a frame without it is the refusal
            # `test_a_result_reporting_a_transient_class_with_no_cooldown...` asserts.
            retry_after_ms=30_000,
        )
    )
    worker, _proc, _clock = worker_on(channel)
    report = worker.invoke(invocation(1), deadlines=deadlines())
    assert report.event is sp.BatchEvent.RESOURCE_LIMIT

    silent = FakeChannel(block_at_eof=True)
    timed, _proc, _clock = worker_on(silent, clock=Clock(step=100))
    late = invoke_bounded(
        timed, invocation(1), limits=deadlines(progress=200, wall=10_000), patience_s=5.0
    )
    assert late.event is sp.BatchEvent.CLEAN
    silent.close()


# =============================================================================================
# 10. `HELLO` / `HELLO_ACK`, and `CARD_CODE_MISMATCH` before work
# =============================================================================================


def hello_ack(**overrides: object) -> bytes:
    header: dict[str, object] = {
        "driver_id": DRIVER_ID,
        "version": "0.1.0",
        "schema_version": 1,
        "port": "parse/1",
        "code_fingerprint": "sha256:" + "a" * 64,
        "isolation_granted": {"mode": "subproc"},
    }
    header.update(overrides)
    return wire.encode(wire.FrameKind.HELLO_ACK, header)


def test_the_handshake_sends_hello_and_reads_the_acks_five_keys() -> None:
    """04-driver-system.md:1696: `HELLO_ACK{driver_id, version, schema_version, port,
    code_fingerprint}`, plus `isolation_granted` echoed per DR10 *"so a shortfall is visible from
    both sides"*."""
    channel = FakeChannel(hello_ack())
    worker, _proc, _clock = worker_on(channel)
    ack = worker.hello(
        {"port": "parse/1", "driver_id": DRIVER_ID},
        expect={"driver_id": DRIVER_ID},
        deadlines=deadlines(),
    )
    assert (ack.driver_id, ack.version, ack.schema_version, ack.port) == (
        DRIVER_ID,
        "0.1.0",
        1,
        "parse/1",
    )
    assert ack.code_fingerprint.startswith("sha256:")
    assert dict(ack.isolation_granted) == {"mode": "subproc"}
    assert [frame.kind for frame in channel.frames_sent()] == [wire.FrameKind.HELLO]


@pytest.mark.parametrize(
    ("field", "value"),
    [("driver_id", "parse.pdf.other"), ("schema_version", 2), ("port", "derive/1")],
)
def test_an_ack_that_disagrees_with_the_card_is_card_code_mismatch_before_any_work(
    field: str, value: object
) -> None:
    """04-driver-system.md:1696 and `codes.toml`'s `OW_CARD_CODE_MISMATCH`: *"a `subproc` worker
    may be a different build than the card the host read from disk"*.

    Parametrised over three fields, because a comparison that only looked at `driver_id` would
    accept a worker built against another `schema_version` -- which is the case the symbol was
    allocated for.
    """
    channel = FakeChannel(hello_ack(**{field: value}))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError) as caught:
        worker.hello(
            {"port": "parse/1"},
            expect={"driver_id": DRIVER_ID, "schema_version": 1, "port": "parse/1"},
            deadlines=deadlines(),
        )
    assert caught.value.code() == "OW_CARD_CODE_MISMATCH"
    # The register row exists and the numeric resolves through it: `codes.toml`'s OW-D-073 says
    # the condition is checked twice on purpose and *"Refused BEFORE any work"*. Asserting the
    # numeric as well as the symbol is what makes this a register transcription rather than a
    # string the host made up -- a symbol with no row resolves to "" and would pass a
    # symbol-only check (errors.py's `numeric()` degrades rather than raising).
    assert caught.value.numeric() == "OW-D-073"
    assert field in str(caught.value)


def test_a_worker_that_answers_hello_with_the_wrong_frame_is_refused() -> None:
    """The handshake is not negotiable: a `RESULT` before a `HELLO_ACK` is a worker doing work
    nobody has asked it for."""
    channel = FakeChannel(result_frame(0))
    worker, _proc, _clock = worker_on(channel)
    with pytest.raises(DriverHostError, match="answered HELLO with RESULT"):
        worker.hello({}, expect={}, deadlines=deadlines())


def test_a_worker_that_never_answers_hello_is_a_bounded_refusal() -> None:
    """A cold worker that never gets as far as its own handshake must not hold the host: nothing
    has been dispatched, so the refusal says so."""
    channel = FakeChannel(block_at_eof=True)
    worker, _proc, _clock = worker_on(channel, clock=Clock(step=100))
    with pytest.raises(DriverHostError, match="did not answer HELLO"):
        run_bounded(
            lambda: worker.hello({}, expect={}, deadlines=deadlines(progress=300, wall=10_000)),
            patience_s=5.0,
        )
    channel.close()


def test_a_log_frame_during_the_handshake_is_drained_and_does_not_break_it() -> None:
    """A worker's import-time logging arrives before its ack. Dropping the handshake over it
    would fail every driver whose dependency prints a banner (04-driver-system.md:1683's reason
    for never parsing stdout)."""
    channel = FakeChannel(
        wire.encode(wire.FrameKind.LOG, {"level": "info", "event": "torch_loaded"}),
        hello_ack(),
    )
    worker, _proc, _clock = worker_on(channel)
    ack = worker.hello({}, expect={"driver_id": DRIVER_ID}, deadlines=deadlines())
    assert ack.driver_id == DRIVER_ID


# =============================================================================================
# 11. CANCEL, SHUTDOWN and the kill ladder
# =============================================================================================


def test_cancel_carries_the_generation_because_cancellation_is_not_a_signal() -> None:
    """04-driver-system.md:1738-1741: cancellation propagates *"by generation, not by signal"*,
    and the commit predicate `WHERE id=:id AND claimed_gen=:gen AND status='claimed'` is what
    makes a superseded result write nothing.

    So `cancel()` waits for no acknowledgement and kills nothing: the correctness of
    cancellation does not depend on the driver's cooperation, only its promptness.
    """
    channel = FakeChannel()
    worker, proc, _clock = worker_on(channel)
    worker.cancel("inv-1", generation=7)
    frame = channel.frames_sent()[0]
    assert frame.kind is wire.FrameKind.CANCEL
    assert frame.header == {"invoke_id": "inv-1", "generation": 7}
    assert (proc.kills, proc.terminates) == (0, 0)


def test_stop_sends_shutdown_first_and_waits_the_grace() -> None:
    """04-driver-system.md:126 and :1728: `SHUTDOWN`, then the uncatchable step. On Windows the
    catchable half IS the frame -- `Popen.terminate()` is already `TerminateProcess` -- so the
    ladder is one frame plus one kill and the frame has to go first."""
    channel = FakeChannel()
    worker, proc, _clock = worker_on(channel, proc=FakeProcess(status=0))
    assert worker.stop(grace_ms=250) == 0
    frame = channel.frames_sent()[0]
    assert frame.kind is wire.FrameKind.SHUTDOWN
    assert frame.header == {"grace_ms": 250}
    assert proc.waited == [0.25]
    assert proc.kills == 0
    assert channel.closed is True


def test_a_worker_that_ignores_shutdown_is_killed_uncatchably() -> None:
    """The plan's `SIGKILL at +5 s`, whose Windows counterpart is `TerminateProcess` -- which,
    as `store/crashmatrix.py` records, *"cannot be caught, handled or ignored"*."""
    channel = FakeChannel()
    worker, proc, _clock = worker_on(channel, proc=FakeProcess(status=None))
    assert worker.stop(grace_ms=10) == 1
    assert proc.kills == 1
    assert channel.closed is True


def test_the_kill_grace_is_the_plans_five_seconds() -> None:
    """04-driver-system.md:126, :1728; 05-ingest-and-routing.md:3054. Reported as owed to
    `config.py`, which declares no `runtime.shutdown_grace_ms` (08-runtime.md:2406, :2603)."""
    assert sp.KILL_GRACE_MS == KILL_GRACE_MS


def test_stopping_twice_does_not_send_a_second_shutdown() -> None:
    """The pool's `close()` may follow a `reap_idle()`, and a worker is not owed two goodbyes."""
    channel = FakeChannel()
    worker, _proc, _clock = worker_on(channel, proc=FakeProcess(status=0))
    worker.stop(grace_ms=10)
    worker.stop(grace_ms=10)
    assert [frame.kind for frame in channel.frames_sent()] == [wire.FrameKind.SHUTDOWN]


def test_a_dead_transport_does_not_stop_the_kill_path() -> None:
    """A worker whose pipe has already gone needs no goodbye; the uncatchable step is the
    mechanism and a raise from `sendall` must not skip it."""

    class Broken(FakeChannel):
        def sendall(self, data: bytes) -> None:  # noqa: ARG002 -- the raise is the whole body
            raise OSError("the pipe is gone")

    channel = Broken()
    worker, proc, _clock = worker_on(channel, proc=FakeProcess(status=None))
    worker.stop(grace_ms=10)
    assert proc.kills == 1


# =============================================================================================
# 12. The stderr ring
# =============================================================================================


def test_the_ring_keeps_the_last_four_kib_and_drops_the_front() -> None:
    """15-observability.md:1373 and 02-architecture.md:831: the TAIL. A ring that kept the head
    would attach a driver's import banner to every crash and never the traceback."""
    ring = sp.StderrRing()
    ring.feed(b"H" * STDERR_RING_BYTES)
    ring.feed(b"TAIL")
    tail = ring.tail()
    assert len(tail) == STDERR_RING_BYTES
    assert tail.endswith(b"TAIL")
    assert tail.startswith(b"H")


def test_the_ring_returns_bytes_and_never_a_decoded_string() -> None:
    """15-observability.md:1333: the tail is *"never parsed for a code"* and passes `redact()`
    before storage. Decoding here would be the first step towards parsing it -- and a driver's
    stderr is not guaranteed to be UTF-8 at all."""
    ring = sp.StderrRing()
    ring.feed(b"\xff\xfe not utf-8")
    assert isinstance(ring.tail(), bytes)


def test_the_ring_is_the_plans_four_kib() -> None:
    assert sp.STDERR_RING_BYTES == STDERR_RING_BYTES


def test_concurrent_feeds_do_not_tear_the_ring() -> None:
    """Two drain threads feed it -- stdout and stderr -- and the crash synthesis reads it while
    they do. Without the lock the tail can be a torn buffer, which is the one thing a crash
    report must not be."""
    ring = sp.StderrRing(max_bytes=512)
    stop = threading.Event()

    def feeder(mark: bytes) -> None:
        while not stop.is_set():
            ring.feed(mark * 64)

    threads = [threading.Thread(target=feeder, args=(mark,)) for mark in (b"a", b"b")]
    for thread in threads:
        thread.start()
    for _ in range(200):
        assert len(ring.tail()) <= 512
    stop.set()
    for thread in threads:
        thread.join(2.0)


# =============================================================================================
# 13. Isolation: what was granted, and what this OS did not give
# =============================================================================================


def granted(**overrides: object) -> tuple[sp.IsolationGranted, tuple[sp.IsolationShortfall, ...]]:
    base: dict[str, object] = {
        "mode": Isolation.SUBPROC,
        "batch_max_units": 32,
        "platform": "win32",
        "address_space_capped": True,
        "net_blocked_requested": False,
        "cpu_cap_requested": False,
        "fd_cap_requested": False,
    }
    base.update(overrides)
    return sp.grant_isolation(**base)  # type: ignore[arg-type]


def test_isolation_granted_is_the_closed_eight_key_record() -> None:
    """04-driver-system.md:1707-1703: *"a closed, eight-key record"*, and its braced list names
    eight keys -- the number and the enumeration agree. The keys are pinned as a literal so a
    ninth cannot ride along on the `HELLO` unnoticed."""
    record, _shortfalls = granted()
    assert tuple(record.as_header()) == ISOLATION_GRANTED_KEYS


def test_every_boolean_is_what_was_obtained_and_never_what_the_card_asked_for() -> None:
    """04-driver-system.md:1745 (DR10): *"what was not obtained is recorded rather than
    claimed"*. Asking for a control this OS lacks must not set its bit."""
    record, _shortfalls = granted(
        cpu_cap_requested=True, fd_cap_requested=True, net_blocked_requested=True
    )
    assert record.cpu_capped is False
    assert record.fd_capped is False
    assert record.net_blocked is False


@pytest.mark.parametrize(
    ("request_key", "control"),
    [
        ("cpu_cap_requested", "cpu_capped"),
        ("fd_cap_requested", "fd_capped"),
        ("net_blocked_requested", "net_blocked"),
    ],
)
def test_a_control_the_card_asked_for_and_windows_lacks_becomes_one_shortfall(
    request_key: str, control: str
) -> None:
    """04-driver-system.md:1710-1711: *"Any boolean that is `false` where the card asked for the
    property becomes one `Degradation(kind="isolation_shortfall")` on the result, naming the
    control and the OS."* One per control, because a shortfall list that named only the first
    would hide the other two."""
    _record, shortfalls = granted(**{request_key: True})
    named = {item.control: item for item in shortfalls}
    assert control in named
    assert named[control].os_name == "win32"
    assert control in named[control].message()
    assert "win32" in named[control].message()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", (True, True, True)),
        ("darwin", (True, True, False)),
    ],
)
def test_a_control_the_platform_does_have_is_granted_and_not_reported_as_a_shortfall(
    platform: str, expected: tuple[bool, bool, bool]
) -> None:
    """The GRANTING direction of 04-driver-system.md:1748-1756, which win32 cannot show.

    Every cell this machine can execute is a `None` -- Windows has no CPU cap, no fd cap and no
    no-egress row -- so on win32 alone `cpu_capped`, `fd_capped` and `net_blocked` can be
    hard-coded to `False` and every other assertion in this file still passes (measured).
    `grant_isolation` is a pure function of a table and its `platform` argument, so the other two
    columns are testable here even though their controls are not: Linux grants all three, and
    macOS grants the two rlimits and not the namespace (:1755's macOS cell records no recipe).

    A shortfall is asserted ABSENT for what was granted and PRESENT for what was not, because
    :1710 conditions the degradation on the boolean and not on the request.
    """
    record, shortfalls = granted(
        platform=platform,
        cpu_cap_requested=True,
        fd_cap_requested=True,
        net_blocked_requested=True,
    )
    assert (record.cpu_capped, record.fd_capped, record.net_blocked) == expected
    assert record.rss_sampled is True
    named = {item.control for item in shortfalls}
    assert "cpu_capped" not in named
    assert "fd_capped" not in named
    assert ("net_blocked" in named) is (expected[2] is False)


def test_a_control_nobody_asked_for_produces_no_shortfall() -> None:
    """:1710 conditions the degradation on *"`false` where the card asked for the property"*. A
    `Degradation` for a control nobody wanted trains a reader to ignore the channel."""
    _record, shortfalls = granted()
    assert [item.control for item in shortfalls] == []


def test_an_address_space_cap_that_was_not_obtained_is_a_shortfall_for_this_worker() -> None:
    """Windows has the control (`JOB_OBJECT_LIMIT_PROCESS_MEMORY`) but a job object can fail to
    be created, and that is a fact about ONE worker rather than about the platform. A table
    lookup would claim it for every worker, which is precisely what DR10 forbids."""
    record, shortfalls = granted(address_space_capped=False)
    assert record.address_space_capped is False
    assert "address_space_capped" in {item.control for item in shortfalls}


def test_the_degradation_kind_is_the_one_literal_from_the_observability_vocabulary() -> None:
    """15-observability.md:981's list is the sole home of the twenty-seven kinds, and this type
    transcribes one name rather than redeclaring the vocabulary."""
    assert sp.IsolationShortfall.DEGRADATION_KIND == "isolation_shortfall"


def test_an_unknown_platform_claims_nothing_and_says_so() -> None:
    """Fail closed: a platform with no recorded recipe gets `rss_sampled = False` and a
    shortfall, rather than a record claiming controls nobody has checked."""
    record, shortfalls = granted(platform="haiku")
    assert record.rss_sampled is False
    assert "rss_sampled" in {item.control for item in shortfalls}


def test_the_per_os_control_table_transcribes_the_documents_three_columns(plan) -> None:
    """04-driver-system.md:1748-1756 is a seven-row, three-column table and
    `CONTROLS_BY_PLATFORM` is its transcription.

    The test reads the DOCUMENT: seven control rows, three platforms, and the three Windows cells
    the plan writes as *"not available"* or *"not applicable"* are the three this module carries
    as `None`. A transcription checked against itself would prove nothing.
    """
    plan.require()
    lines = plan.lines("04-driver-system.md")
    rows = [line for line in lines[1747:1757] if line.startswith("| ") and "|---" not in line]
    header, *body = rows
    assert [cell.strip() for cell in header.strip("|").split("|")] == [
        "control",
        "Linux",
        "macOS",
        "Windows",
    ]
    assert len(body) == 7
    assert set(sp.CONTROLS_BY_PLATFORM) == {"linux", "darwin", "win32"}
    windows = {
        cells[0].strip().strip("*"): cells[3].strip()
        for cells in (row.strip("|").split("|") for row in body)
    }
    assert "not available" in windows["CPU cap"]
    assert "not applicable" in windows["file-descriptor cap"]
    assert "not available" in windows["no-egress"]
    win = sp.CONTROLS_BY_PLATFORM["win32"]
    assert (win.cpu_cap, win.fd_cap, win.no_egress) == (None, None, None)
    assert "Job Object" in win.address_space_cap
    assert "GetProcessMemoryInfo" in win.rss_sampling
    assert "SetPriorityClass" in win.priority


def test_the_macos_column_keeps_rlimit_data_and_not_rlimit_as() -> None:
    """04-driver-system.md:1758-1762 says this is *"the one a reviewer should check, because
    getting it wrong is silent"*: `graphify/watch.py:221` selects `RLIMIT_DATA` on darwin because
    *"RLIMIT_AS is unreliable under Apple's libmalloc"*, and omniweave takes that split verbatim."""
    darwin = sp.CONTROLS_BY_PLATFORM["darwin"]
    assert "RLIMIT_DATA" in darwin.address_space_cap
    assert "NOT RLIMIT_AS" in darwin.address_space_cap
    assert "RLIMIT_AS" in sp.CONTROLS_BY_PLATFORM["linux"].address_space_cap


# =============================================================================================
# 14. The Windows instruments: psapi, the job object, the priority
# =============================================================================================


@WINDOWS_ONLY
def test_peak_rss_reports_a_positive_reading_for_this_process_and_names_how() -> None:
    """04-driver-system.md:1751's Windows cell is `GetProcessMemoryInfo` via `ctypes`, and
    `DriverMetrics.peak_rss_bytes` carries the sample into the ledger so an OOM is diagnosable
    BEFORE it happens (:1765). The second element of the tuple exists because Windows reports a
    PEAK and procfs reports the CURRENT resident set -- not the same quantity."""
    observed, how = sp.peak_rss_bytes(os.getpid())
    assert observed is not None and observed > 0
    assert "GetProcessMemoryInfo" in how or "PeakWorkingSet" in how


@WINDOWS_ONLY
def test_peak_rss_of_a_process_that_does_not_exist_is_a_reason_and_never_a_raise() -> None:
    """A watchdog that raised while sampling would turn a memory question into a host crash, and
    04-driver-system.md:1769's whole argument for the watchdog is that it is free."""
    observed, why = sp.peak_rss_bytes(999_999)
    assert observed is None
    assert "OpenProcess" in why


@WINDOWS_ONLY
def test_the_watchdog_fires_when_the_sampled_rss_is_over_the_cards_memory_mb() -> None:
    """04-driver-system.md:1730: `FAILED_PERMANENT{RESOURCE_LIMIT}`, `limit = "memory_mb"`.

    `memory_mb = 0` is the "no cap" case and IS asserted, in the second half -- the docstring
    claimed that for a while over a body that only ever passed `memory_mb = 1`, so widening the
    guard from `> 0` to `>= 0` left this file green. The no-cap arm matters twice: a watchdog
    that sampled unconditionally would spend an `OpenProcess` per tick on every worker in the
    pool, and -- because this interpreter's peak RSS is over any cap of zero bytes -- it would
    also fail every invocation that declared no cap at all.
    """
    # This interpreter is the sampled process: a fake pid samples nothing, and a
    # watchdog test whose sampler returns `(None, why)` would be asserting the deadline.
    channel = FakeChannel(block_at_eof=True)
    worker, _proc, _clock = worker_on(
        channel, clock=Clock(step=50), proc=FakeProcess(pid=os.getpid())
    )
    report = invoke_bounded(
        worker,
        invocation(1),
        limits=deadlines(progress=100_000, wall=100_000),
        memory_mb=1,
        patience_s=5.0,
    )
    verdict = report.failures[0]
    assert verdict is not None
    assert verdict.failure_class is FailureClass.RESOURCE_LIMIT
    assert verdict.limit == "memory_mb"
    channel.close()

    uncapped = FakeChannel(block_at_eof=True)
    free, _proc2, _clock2 = worker_on(
        uncapped, clock=Clock(step=200), proc=FakeProcess(pid=os.getpid())
    )
    ran = invoke_bounded(
        free,
        invocation(1),
        limits=deadlines(progress=1_000, wall=100_000),
        memory_mb=0,
        patience_s=5.0,
    )
    unbounded = ran.failures[0]
    assert unbounded is not None
    assert unbounded.failure_class is FailureClass.TIMEOUT, "memory_mb = 0 is no cap, not a cap"
    uncapped.close()


@WINDOWS_ONLY
def test_a_job_object_holds_the_child_and_says_so_when_asked() -> None:
    """04-driver-system.md:1728's *"whole process group"* has no Windows counterpart, and this is
    the substitute: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` plus `TerminateJobObject`.

    `pids()` reads the assignment back, so "the child is in the job" is an assertion and not an
    assumption -- a job object nobody was assigned to is the silent failure this replaces. Under
    a launcher trampoline (`uv`'s venv) the job holds BOTH the shim and the grandchild, which is
    exactly why the plan reaps a group rather than a process.
    """
    proc = subprocess.Popen(  # this interpreter, a fixed argv, no shell
        [sys.executable, "-c", "import threading; threading.Event().wait(30)"],
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    job = sp.JobObject(memory_limit_bytes=256 * 1_048_576)
    try:
        job.assign(proc.pid)
        assert proc.pid in job.pids()
        job.terminate()
        assert proc.wait(timeout=10) is not None
        assert job.pids() == ()
    finally:
        job.close()
        assert job.closed is True
        if proc.poll() is None:  # pragma: no cover -- TerminateJobObject does not fail
            proc.kill()


@WINDOWS_ONLY
def test_lowering_a_childs_priority_is_observable_and_is_below_normal() -> None:
    """04-driver-system.md:1754 and :1763: `SetPriorityClass(BELOW_NORMAL)` is `os.nice(10)`'s
    counterpart, carrying graphify's reason -- *"a background rebuild must lose to the user's
    editor"* -- with the higher stake :1764 names: a VLM parse can allocate gigabytes and an
    OOM-killer visit takes the user's editor with it.

    Read back with `GetPriorityClass`, on a CHILD: a test that lowered its own priority would
    have changed the test runner's.
    """
    below_normal = 0x00004000
    proc = subprocess.Popen(  # this interpreter, a fixed argv, no shell
        [sys.executable, "-c", "import threading; threading.Event().wait(30)"],
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        obtained, how = sp.lower_priority(proc.pid)
        assert obtained is True
        assert "BELOW_NORMAL" in how
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        handle = kernel32.OpenProcess(0x1000, 0, proc.pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        assert handle
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        try:
            assert kernel32.GetPriorityClass(handle) == below_normal
        finally:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(handle)
    finally:
        proc.kill()
        proc.wait(timeout=10)


@WINDOWS_ONLY
def test_lowering_the_priority_of_a_process_that_is_gone_is_a_reason_and_not_a_raise() -> None:
    """Never raises: a priority the host could not set is a fact for the row, not an outage."""
    obtained, why = sp.lower_priority(999_999)
    assert obtained is False
    assert "OpenProcess" in why


# =============================================================================================
# 15. The transport, on the platform that has it
# =============================================================================================

PIPE_PREFIX = "\\\\.\\pipe\\"


def pipe_address(tag: str) -> str:
    return f"{PIPE_PREFIX}ow-test-{os.getpid()}-{tag}"


def test_the_owner_only_dacl_has_exactly_one_ace_and_is_protected() -> None:
    """02-architecture.md:428 says *"owner-only"*, and `D:P(A;;GA;;;<sid>)` is that: `P` sets
    `SE_DACL_PROTECTED` so no inherited ACE can widen the pipe, and there is one ACE.

    Nothing for `BA` (Administrators) and nothing for `SY` (SYSTEM), however conventional those
    look in a Windows service: an ACE for a second principal is not owner-only.
    """
    sddl = sp.owner_only_sddl("S-1-5-21-1-2-3-1001")
    assert sddl == "D:P(A;;GA;;;S-1-5-21-1-2-3-1001)"
    assert sddl.count("(") == 1
    assert ";;;BA)" not in sddl and ";;;SY)" not in sddl


@WINDOWS_ONLY
def test_the_current_user_sid_is_a_real_principal_and_not_an_sddl_alias() -> None:
    """The aliases that look right are not: `CO` (CREATOR OWNER) is substituted only in an
    INHERITABLE ACE and `OW` (OWNER RIGHTS) is a separate well-known SID, so a DACL written with
    either grants nobody access on a non-inheritable object."""
    sid = sp.current_user_sid()
    assert re.fullmatch(r"S-1-5-21-\d+-\d+-\d+-\d+", sid), sid


@WINDOWS_ONLY
def test_a_pipe_name_outside_the_local_namespace_is_refused() -> None:
    r"""`\\.\pipe\` is local by construction; `\\server\pipe\` is SMB. The refusal is the first
    half of "not reachable off-box" and `PIPE_REJECT_REMOTE_CLIENTS` is the second."""
    with pytest.raises(DriverHostError, match="not a local pipe name"):
        sp.NamedPipeListener("\\\\somehost\\pipe\\ow-s4")


@WINDOWS_ONLY
def test_the_two_pipe_names_are_derived_once_for_both_ends() -> None:
    """Both ends need the same two names and only the host knows the base, so the derivation has
    one site (`pipe_names`) and the suffixes are its."""
    h2d, d2h = sp.pipe_names("\\\\.\\pipe\\ow-s4-1")
    assert h2d == "\\\\.\\pipe\\ow-s4-1-h2d"
    assert d2h == "\\\\.\\pipe\\ow-s4-1-d2h"
    assert (sp.H2D_SUFFIX, sp.D2H_SUFFIX) == ("-h2d", "-d2h")


@WINDOWS_ONLY
def test_first_pipe_instance_refuses_a_name_something_else_already_holds() -> None:
    """A squatter that created the name first would receive our `HELLO`, which carries
    `effective_config`, the roots and `blob_base`. A DACL cannot express this -- the squatter's
    pipe would carry the squatter's DACL -- so the flag is the half of "owner-only" that the
    security descriptor is not."""
    address = pipe_address("dup")
    held = sp.NamedPipeListener(address)
    try:
        with pytest.raises(DriverHostError, match="CreateNamedPipeW"):
            sp.NamedPipeListener(address)
    finally:
        held.close()


@WINDOWS_ONLY
def test_an_accept_that_nobody_connects_to_is_a_bounded_refusal_and_close_returns() -> None:
    """TWO bounds, and the second one shipped broken.

    The accept is bounded by its own deadline. The CLEANUP was not: a timed-out accept leaves the
    waiter parked inside `ConnectNamedPipe`, which is a pending synchronous I/O, and `CloseHandle`
    on such a handle does not return until the operation completes -- so `close()` hung forever on
    the failure path. A bounded refusal whose cleanup is unbounded is not a bounded refusal, and
    this test is the regression for it.
    """
    listener = sp.NamedPipeListener(pipe_address("lonely"))
    started = time.monotonic()
    with pytest.raises(DriverHostError, match="within 300 ms"):
        listener.accept(timeout_ms=300)
    accept_ms = (time.monotonic() - started) * 1000
    assert 250 < accept_ms < 4_000, accept_ms
    closing = time.monotonic()
    listener.close()
    assert (time.monotonic() - closing) < 2.0


@WINDOWS_ONLY
def test_a_cancelled_accept_releases_the_pipe_name_for_the_next_attempt() -> None:
    """`CancelSynchronousIo` is what makes the waiter end rather than park to process exit, and
    the observable consequence is that `FILE_FLAG_FIRST_PIPE_INSTANCE` will accept the same name
    again. A leaked wait would show up here as a `CreateNamedPipeW` failure."""
    address = pipe_address("recycle")
    first = sp.NamedPipeListener(address)
    with pytest.raises(DriverHostError):
        first.accept(timeout_ms=200)
    first.close()
    second = sp.NamedPipeListener(address)
    second.close()


@WINDOWS_ONLY
def test_a_frame_crosses_the_real_transport_in_both_directions() -> None:
    """The round trip, over two real owner-only pipes: `HELLO` out, `HELLO_ACK` back.

    `connect()` is the WORKER's end and lives in this module rather than in a `tools/` script for
    exactly this reason -- a worker with its own copy of the frame layout is how two ends of one
    protocol drift.
    """
    address = pipe_address("roundtrip")
    listener = sp.NamedPipeListener(address)
    seen: dict[str, object] = {}
    done = threading.Event()

    def worker_side() -> None:
        channel = sp.connect(address, timeout_ms=5_000)
        try:
            frame = sp.next_frame(channel, expect=wire.Direction.HOST_TO_DRIVER)
            seen["kind"] = None if frame is None else frame.kind
            seen["body"] = b"" if frame is None else frame.body
            channel.sendall(wire.encode(wire.FrameKind.HELLO_ACK, {"driver_id": DRIVER_ID}))
            seen["ready"] = True
            # The worker holds its end until the host has read the ack: closing first would
            # make the host's read an EOF and the test would pass for the wrong reason.
            done.wait(5.0)
        finally:
            channel.close()

    thread = threading.Thread(target=worker_side, daemon=True)
    thread.start()
    try:
        host = listener.accept(timeout_ms=5_000)
        host.sendall(wire.encode(wire.FrameKind.HELLO, {"port": "parse/1"}, b"\x00\x1a\xffbody"))
        ack = sp.next_frame(host)
        assert ack is not None
        assert ack.kind is wire.FrameKind.HELLO_ACK
        assert ack.header["driver_id"] == DRIVER_ID
        assert seen["kind"] is wire.FrameKind.HELLO
        assert seen["body"] == b"\x00\x1a\xffbody"
        host.close()
    finally:
        done.set()
        thread.join(5.0)
        listener.close()


@WINDOWS_ONLY
def test_the_host_can_write_while_its_reader_thread_has_a_read_pending() -> None:
    """THE reason the Windows arm is two pipes, as a regression test.

    Windows serialises operations on a SYNCHRONOUS handle: while one thread has a `ReadFile`
    pending, another thread's `WriteFile` on the same handle waits for it. With one duplex pipe
    every `Worker.send` blocked behind `FrameReader`'s parked read and the handshake never
    completed -- measured, not theorised. Two one-way pipes make the two operations independent,
    and this test fails outright (by timing out) if that changes back.
    """
    address = pipe_address("duplex")
    listener = sp.NamedPipeListener(address)
    client: dict[str, sp.ByteChannel] = {}

    def worker_side() -> None:
        client["channel"] = sp.connect(address, timeout_ms=5_000)

    thread = threading.Thread(target=worker_side, daemon=True)
    thread.start()
    try:
        host = listener.accept(timeout_ms=5_000)
        thread.join(5.0)
        parked = threading.Thread(target=lambda: host.recv(8), daemon=True)
        parked.start()
        threading.Event().wait(0.2)
        started = time.monotonic()
        host.sendall(b"12345678")
        assert (time.monotonic() - started) < 2.0
        client["channel"].sendall(b"87654321")
        parked.join(5.0)
        assert not parked.is_alive()
        host.close()
    finally:
        if "channel" in client:
            client["channel"].close()
        listener.close()


@WINDOWS_ONLY
def test_accepting_twice_on_one_listener_is_refused() -> None:
    """`nMaxInstances = 1`: one client per pipe, so a listener is one worker's and the second
    call has no handle to give away."""
    address = pipe_address("once")
    listener = sp.NamedPipeListener(address)
    with pytest.raises(DriverHostError):
        listener.accept(timeout_ms=100)
    with pytest.raises(DriverHostError, match="already accepted or been closed"):
        listener.accept(timeout_ms=100)
    listener.close()


@WINDOWS_ONLY
def test_a_worker_that_connects_to_nothing_gives_up_inside_its_deadline() -> None:
    """The child's end is bounded too: a worker whose host has already gone must not spin."""
    started = time.monotonic()
    with pytest.raises(DriverHostError, match="could not open"):
        sp.connect(pipe_address("absent"), timeout_ms=300)
    assert (time.monotonic() - started) < 5.0


def test_the_unix_socket_arm_is_the_one_this_machine_cannot_run() -> None:
    """02-architecture.md:428 offers *"a 0600 unix socket or an owner-only named pipe"*, and
    `socket.AF_UNIX` is absent from CPython on Windows -- the kernel has had `AF_UNIX` since
    build 17063 but the interpreter does not expose it. So the socket arm cannot even be
    CONSTRUCTED here, and this asserts the refusal rather than the socket.

    `store/crashmatrix.py`'s docstring is the precedent: name the shortfall, do not paper over it.
    """
    if not WINDOWS:  # pragma: no cover -- POSIX, where the other arm is the live one
        pytest.skip("the AF_UNIX arm is the live one off Windows")
    assert not hasattr(socket, "AF_UNIX")
    with pytest.raises(DriverHostError, match="AF_UNIX is absent"):
        sp.UnixSocketListener("/tmp/ow-s4.sock")  # noqa: S108 -- never created; the raise is it


def test_the_unix_socket_is_chmodded_before_it_listens() -> None:
    """The order is the whole point: a socket listening at mode 0777 for even one scheduler
    quantum is a socket any local process may connect to, and 02-architecture.md:428's "0600" is
    a claim about the socket's whole life.

    THIS RUNS ON EVERY CELL, INCLUDING THIS ONE, and that is the reason it is written over the
    source text rather than over a socket. The AF_UNIX arm cannot be CONSTRUCTED on Windows
    (`socket.AF_UNIX` is absent from CPython there, as the test above asserts), so an assertion
    that chmod happened could only ever run on POSIX -- but an assertion that chmod is WRITTEN
    before `listen` is a fact about the module and needs no socket at all. It was previously
    skipped here under `skipif(WINDOWS)`, which left the ordering claim -- the half of
    02-architecture.md:428 that a reviewer cannot see by reading a mode bit -- pinned by nothing
    on two of the nine matrix cells. A source-order assertion is a weaker instrument than a
    `stat()` on a live socket and it is named as one; what it is not is unrunnable.
    """
    source = SUBPROC_SOURCE.read_text(encoding="utf-8")
    chmod_at = source.index("os.chmod(path, 0o600)")
    listen_at = source.index("self._sock.listen(1)")
    assert chmod_at < listen_at


def test_listener_for_picks_the_arm_this_platform_has() -> None:
    """One selection site, so no caller writes the platform test twice."""
    if WINDOWS:
        listener = sp.listener_for(pipe_address("select"))
        assert isinstance(listener, sp.NamedPipeListener)
        listener.close()
    else:  # pragma: no cover -- POSIX
        assert sp.listener_for.__doc__ is not None


# =============================================================================================
# 16. The spawn, and the discipline the semgrep exemption comes with
# =============================================================================================


def test_a_spawn_request_has_no_default_cwd() -> None:
    """The semgrep rule that exempts this file says what the ban is FOR, and `cwd` is its first
    item: graphify #2316 ran `git rev-parse HEAD` without `cwd=` and stamped the invoking repo's
    commit into the target's graph. A default would be the process's own working directory --
    the ambient input `os.getcwd()` is separately banned for."""
    with pytest.raises(TypeError):
        sp.SpawnRequest(argv=("python",), env={}, address="x")  # type: ignore[call-arg]


def test_a_spawn_request_refuses_an_empty_cwd_and_an_empty_argv() -> None:
    """Required is not the same as non-empty, and `cwd=""` inherits ours."""
    with pytest.raises(DriverHostError, match="no argv"):
        sp.SpawnRequest(argv=(), cwd=".", env={}, address="x")
    with pytest.raises(DriverHostError, match="cwd is empty"):
        sp.SpawnRequest(argv=("python",), cwd="", env={}, address="x")


def test_the_only_popen_in_the_module_passes_cwd_env_and_shell_false() -> None:
    """A STATIC assertion over the one spawn site, so the graphify defect cannot come back.

    `ast` and not a string search: the keywords have to be on the `Popen` CALL, and a comment
    promising `cwd=` is not a keyword. `shell=False` is asserted as a literal because
    04-driver-system.md:1098 requires it for `[driver] exec` and a tuple argv with `shell=True`
    is still a shell.
    """
    tree = ast.parse(SUBPROC_SOURCE.read_text(encoding="utf-8"), filename=str(SUBPROC_SOURCE))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Popen"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    assert "cwd" in keywords
    assert "env" in keywords
    shell = keywords.get("shell")
    assert isinstance(shell, ast.Constant) and shell.value is False
    stdin = keywords.get("stdin")
    assert isinstance(stdin, ast.Attribute) and stdin.attr == "DEVNULL"


@WINDOWS_ONLY
def test_a_real_spawn_runs_in_the_cwd_we_passed_and_not_in_ours(tmp_path: Path) -> None:
    """The graphify defect, as a live test.

    The child prints its own working directory to stderr, the host reads it out of the bounded
    ring, and it is `tmp_path` -- not the repository the test runs in. That is the whole content
    of the semgrep rule's first clause, and a static check cannot show it.
    """
    ring = sp.StderrRing()
    request = sp.SpawnRequest(
        argv=(sys.executable, "-c", "import os,sys; sys.stderr.write(os.getcwd())"),
        cwd=str(tmp_path),
        env={
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": os.environ.get("PATH", ""),
        },
        address=pipe_address("cwd"),
    )
    proc = sp.spawn_worker(request, stderr=ring, stdout=sp.StderrRing())
    assert proc.wait(timeout=30) == 0
    deadline = time.monotonic() + 5.0
    while not ring.tail() and time.monotonic() < deadline:
        threading.Event().wait(0.02)
    reported = Path(ring.tail().decode("utf-8", "replace").strip()).resolve()
    assert reported == tmp_path.resolve()
    assert reported != Path.cwd().resolve()


@WINDOWS_ONLY
def test_a_spawn_does_not_inherit_the_hosts_environment(tmp_path: Path) -> None:
    """`env` is a complete mapping and not an overlay: an inherited environment carries the
    host's `PYTHONPATH`, its proxy variables and its tokens into a third party's process."""
    os.environ["OW_HOST_SECRET"] = "do-not-cross-the-seam"  # noqa: S105 -- the point
    try:
        ring = sp.StderrRing()
        request = sp.SpawnRequest(
            argv=(
                sys.executable,
                "-c",
                "import os,sys; sys.stderr.write(os.environ.get('OW_HOST_SECRET','absent'))",
            ),
            cwd=str(tmp_path),
            env={
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PATH": os.environ.get("PATH", ""),
            },
            address=pipe_address("env"),
        )
        proc = sp.spawn_worker(request, stderr=ring, stdout=sp.StderrRing())
        assert proc.wait(timeout=30) == 0
        deadline = time.monotonic() + 5.0
        while not ring.tail() and time.monotonic() < deadline:
            threading.Event().wait(0.02)
        assert ring.tail().decode() == "absent"
    finally:
        del os.environ["OW_HOST_SECRET"]


@WINDOWS_ONLY
def test_a_real_crash_is_synthesised_from_the_exit_status_and_the_tail() -> None:
    """02-architecture.md:831 over a real process: 9 KiB of stderr, exit 3, a 4 KiB tail.

    The exit status is what makes this different from an EOF: `synthesise_crash` waits a bounded
    moment for the reap, because the transport closes before the parent learns the status -- and
    a verdict *"synthesised from the exit status"* whose status is `None` has synthesised nothing.
    """
    ring = sp.StderrRing()
    request = sp.SpawnRequest(
        argv=(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x' * 9000); sys.stderr.flush(); raise SystemExit(3)",
        ),
        cwd=str(REPO_ROOT),
        env={
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": os.environ.get("PATH", ""),
        },
        address=pipe_address("crash"),
    )
    proc = sp.spawn_worker(request, stderr=ring, stdout=sp.StderrRing())
    assert proc.wait(timeout=30) == 3
    deadline = time.monotonic() + 5.0
    while len(ring.tail()) < STDERR_RING_BYTES and time.monotonic() < deadline:
        threading.Event().wait(0.02)
    verdict = sp.synthesise_crash(proc, ring, wait_ms=LOOP_LAG_MAX_MS)
    assert verdict.failure_class is FailureClass.DRIVER_CRASHED
    assert verdict.exit_status == 3
    assert len(verdict.stderr_tail) == STDERR_RING_BYTES
    assert verdict.permanent is True


# =============================================================================================
# 17. Purity: what this module may import, and what a bare core import may not load
# =============================================================================================


def import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_the_module_imports_only_the_standard_library_and_the_two_first_party_roots() -> None:
    """INV-2/G1: `omniweave_core` has zero third-party runtime dependencies, and
    04-driver-system.md:1769 makes the point for the watchdog specifically -- `resource`, `ctypes`
    and `os` are core-permitted, so it *"adds no dependency"*."""
    assert import_roots(SUBPROC_SOURCE) <= ALLOWED_IMPORT_ROOTS


def test_the_module_imports_neither_asyncio_nor_selectors_nor_sqlite3() -> None:
    """G23: core imports neither `asyncio` nor `selectors`; the single event loop lives in
    `omniweave/run/` (INV-3). INV-17 keeps `sqlite3` under `store/`.

    The bounded queue plus a daemon thread is what replaces the selector, and the reason is in
    `FrameReader`'s docstring: a `get(timeout=...)` the supervisor can put a deadline on works
    identically over a named pipe, where a deadline on the read itself would need overlapped I/O.
    """
    roots = import_roots(SUBPROC_SOURCE)
    assert "asyncio" not in roots
    assert "selectors" not in roots
    assert "sqlite3" not in roots


def test_a_bare_core_import_does_not_load_the_host(interpreter) -> None:
    """G17: `import omniweave_core` must load none of the nine lazy names, and `host` is one.

    A fresh interpreter is the only witness -- once a pytest session has imported half the tree
    for its own reasons, `sys.modules` cannot answer the question.
    """
    loaded = interpreter.modules_added_by("import omniweave_core")
    assert "omniweave_core.host.subproc" not in loaded
    assert "omniweave_core.host" not in loaded


def test_the_semgrep_bank_already_exempts_this_path_and_needs_no_widening() -> None:
    """A REGISTER is a transcription (rule 4), and this one already carries what W3.2 needs.

    `tools/semgrep/omniweave.yaml`'s `omniweave-no-subprocess-outside-toolchain-and-host-subproc`
    excludes exactly two paths -- `toolchain.py` (S2) and `host/subproc.py` (S4) -- and
    02-architecture.md:441 says *"only `omniweave_core.toolchain` and
    `omniweave_core.host.subproc` may import `subprocess` (G8)"*. So the exemption is asserted,
    not requested: if a third home is ever needed, that is a finding and not an edit.
    """
    bank = (REPO_ROOT / "tools" / "semgrep" / "omniweave.yaml").read_text(encoding="utf-8")
    rule = bank[bank.index("omniweave-no-subprocess-outside-toolchain-and-host-subproc") :]
    rule = rule[: rule.index("- id:", 10)]
    excluded = re.findall(r'-\s+"([^"]+)"', rule)
    assert "packages/omniweave-core/src/omniweave_core/host/subproc.py" in excluded
    assert "packages/omniweave-core/src/omniweave_core/toolchain.py" in excluded
    assert len([path for path in excluded if path.endswith(".py")]) == 2


def test_the_ruff_ban_names_the_same_two_homes() -> None:
    """`pyproject.toml`'s `banned-api` is *"the independent second enforcer"* (the rule's own
    message), and two enforcers that named different paths would be worse than one."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        '"subprocess".msg = "S2/S4 only: omniweave_core.toolchain, omniweave_core.host.subproc."'
        in pyproject
    )
    assert '"packages/omniweave-core/src/omniweave_core/host/subproc.py" = ["TID251"]' in pyproject


# =============================================================================================
# 18. `tools/ow_host.py` -- the D25 runner
# =============================================================================================


def test_the_runner_declares_nine_scenarios_over_eight_behaviours() -> None:
    """The counts are DERIVED from the tables rather than asserted as prose: `quarantine` drives
    the `crash` behaviour three times, which is why the two numbers differ."""
    assert len(runner.SCENARIOS) == 9
    assert len({scenario.name for scenario in runner.SCENARIOS}) == 9
    assert len(runner.BEHAVIOURS) == 8
    assert len(set(runner.BEHAVIOURS)) == 8


def test_every_scenario_names_a_plan_clause() -> None:
    """A runner whose rows do not cite the plan is a runner nobody can check against it."""
    for scenario in runner.SCENARIOS:
        assert re.search(r"\d{2}:\d{3,4}|:\d{3,4}", scenario.clause), scenario


def test_the_runner_lists_its_scenarios_and_exits_clean() -> None:
    """`--list` is the cheap half of the runner: it names the table without spawning anything, so
    a CI job can print what it is about to do."""
    out = StringIO()
    assert runner.main(["--list"], out=out) == runner.EXIT_CLEAN
    printed = out.getvalue()
    for scenario in runner.SCENARIOS:
        assert scenario.name in printed


def test_the_runner_keys_its_stub_worker_the_way_the_pool_does() -> None:
    """The runner's key is `identity.config_digest`'s, not a string it made up, because the
    thing under test is the pool's key and a runner with its own digest would be testing itself."""
    key = runner.worker_key()
    assert key.driver_id == runner.DRIVER_ID
    assert key.config_digest == config_digest(runner.STUB_CONFIG)
    assert len(key.config_digest) == 64


def test_the_runners_environment_is_curated_and_carries_no_secret() -> None:
    """`worker_env()` is a complete mapping of a few named variables; a runner that passed
    `os.environ` would have undone `SpawnRequest`'s whole reason for taking one."""
    os.environ["OW_HOST_SECRET"] = "no"  # noqa: S105 -- a marker, not a credential
    try:
        env = dict(runner.worker_env())
    finally:
        del os.environ["OW_HOST_SECRET"]
    assert "OW_HOST_SECRET" not in env
    assert set(env) <= {
        "SYSTEMROOT",
        "SystemRoot",
        "PATH",
        "TEMP",
        "TMP",
        "PYTHONUTF8",
        "PYTHONDONTWRITEBYTECODE",
    }


def test_the_runner_builds_no_argparse_cli_inside_a_package() -> None:
    """Ledger D25: the library function lives in the package and the argv lives in `tools/`.

    `argparse` in `host/subproc.py` would have made a CLI out of a seam, and P7's `ow` is what
    wraps this. The assertion is over the module's imports, which is where a CLI would show up.
    """
    assert "argparse" not in import_roots(SUBPROC_SOURCE)
    assert "argparse" in import_roots(TOOL_PATH)


def test_the_runner_binds_driver_host_error_at_module_scope_and_never_in_a_function() -> None:
    """A REGRESSION test for a failure that only appears in a full-suite run.

    `tests/unit/test_errors.py` calls `importlib.reload(errors)`, which rebuilds every class
    object in that module. A `from omniweave_core.errors import DriverHostError` executed INSIDE
    a function after that reload binds the new class, while `host/subproc.py` -- imported once,
    before it -- still raises the old one, so `except DriverHostError` stops matching. The
    runner's `card_mismatch` scenario escaped as an unhandled exception in exactly that
    collection order and passed when its own file ran alone, which is the worst available failure
    mode. `test_host_wire.py`'s header records the same trap.

    So the assertion is structural: `omniweave_core.errors` is imported at module scope and at
    NO function scope. A test that merely ran the runner would go green again the moment the
    ordering changed.
    """
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"), filename=str(TOOL_PATH))
    module_level = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "omniweave_core.errors" in module_level
    nested = [
        node.module
        for parent in ast.walk(tree)
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(parent)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert "omniweave_core.errors" not in nested, nested


def test_the_runner_imports_no_subprocess_of_its_own() -> None:
    """The spawn is `spawn_worker()`'s, in the module the semgrep bank exempts. A runner with its
    own `Popen` would have built a third spawn site, which the bank does not name and 02:441
    forbids."""
    roots = import_roots(TOOL_PATH)
    assert roots <= TOOL_IMPORT_ROOTS, roots - TOOL_IMPORT_ROOTS
    assert "subprocess" not in roots


@WINDOWS_ONLY
def test_the_runner_drives_a_real_worker_through_every_scenario_and_reports_clean() -> None:
    """The whole runner, against real children: nine scenarios, one process each (three for
    `quarantine`), a HELLO / INVOKE / CANCEL cycle, a kill, and a report.

    **The rows, not the exit code, and not the word "clean" either.** A regex that reads the
    check count as one-or-more digits admits ZERO: with every `Observation` rebuilt as
    `checks=()` the runner prints
    *"9 scenarios, 0 checks, 0 failed"*, exits `0`, says `clean` -- `all(())` is `True`, so an
    observation that asserted nothing is `ok` -- and this test used to pass. So the tally is
    cross-checked against the `ok` LINES the per-check loop emitted (a different code path from
    the `sum`), every scenario is required to have left at least one of them under its own
    header, and the total is floored at a literal.

    The floor is 27 and the runner currently prints 35. It is a floor and not the number: pinning
    35 would fail on the next check anybody adds, while a floor that is three per scenario cannot
    be met by a table that quietly stopped asserting.

    The call itself is bounded (`run_bounded`), because the subject of nine of these checks is a
    HOST and a host with a broken deadline does not fail this test -- it hangs the session. That
    happened: with `FrameReader.get`'s timeout removed, the `silent` scenario blocked forever and
    `pytest` never finished.
    """
    out = StringIO()
    code = run_bounded(lambda: runner.main([], out=out), patience_s=120.0)
    printed = out.getvalue()
    assert code == runner.EXIT_CLEAN, printed
    assert "ow-host: clean" in printed
    assert "FAIL" not in printed
    tally = re.search(r"ow-host: (\d+) scenarios, (\d+) checks, (\d+) failed", printed)
    assert tally is not None, printed
    assert (int(tally[1]), int(tally[3])) == (9, 0), printed
    ok_lines = [line for line in printed.splitlines() if line.startswith("  ok ")]
    assert int(tally[2]) == len(ok_lines), printed
    assert int(tally[2]) >= 27, printed
    sections = printed.split("\now-host: ")
    for scenario in runner.SCENARIOS:
        assert f"ow-host: {scenario.name}" in printed
        mine = [part for part in sections if part.startswith(f"{scenario.name} -- ")]
        assert len(mine) == 1, scenario.name
        assert [line for line in mine[0].splitlines() if line.startswith("  ok ")], scenario.name
    # The Windows shortfalls are PRINTED, because :1745 requires them recorded and a report that
    # granted a control it did not obtain would be the claim DR10 forbids.
    assert "cpu_capped was not obtained on win32" in printed
    assert "fd_capped was not obtained on win32" in printed
    assert "net_blocked was not obtained on win32" in printed


@WINDOWS_ONLY
def test_the_scenario_flag_runs_that_scenario_and_only_that_one() -> None:
    """`--scenario` is repeatable and documented, and no test had ever passed it.

    A flag nobody exercises is an invocation nobody has run: the filter is
    `if scenario.name not in wanted: continue`, and dropping it -- or inverting it -- is invisible
    to a suite that only ever calls `main([])` and `main(["--list"])`. Inverting it is worse than
    invisible, because a run that skipped every scenario would print *"0 scenarios, 0 checks,
    0 failed"* and the word `clean`.

    `card_mismatch` is the scenario chosen because it is the cheapest that still spawns a real
    child, and the assertion is two-sided: its own header and check are present, and the other
    eight names are absent from the report.
    """
    out = StringIO()
    code = run_bounded(
        lambda: runner.main(["--scenario", "card_mismatch"], out=out), patience_s=60.0
    )
    printed = out.getvalue()
    assert code == runner.EXIT_CLEAN, printed
    assert "ow-host: card_mismatch --" in printed
    assert re.search(r"ow-host: 1 scenarios, [1-9]\d* checks, 0 failed", printed), printed
    for other in runner.SCENARIOS:
        if other.name == "card_mismatch":
            continue
        assert f"ow-host: {other.name} --" not in printed, other.name
