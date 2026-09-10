"""Drive a REAL `subproc` worker over a REAL owner-only named pipe, and print what happened.

`omniweave_core.host.subproc` is seam S4 (02-architecture.md:428) and this is its runner: nine
scenarios, each one a live child process on the far side of `omniweave-driver/1`, each one
asserting a clause of 02-architecture.md's S4 row or 04-driver-system.md section 6.3-6.5.

## Why this exists as a `tools/` script and not as a verb

There is no verb yet. 16-roadmap.md section 10 puts the CLI at P7 and `omniweave.run` at P4
(16-roadmap.md:493), so `ow` cannot wrap anything today; ledger D25's standing pattern -- applied
by `tools/schemagen.py` for `ow schema emit`, `tools/gate_crash.py` for `ow test crash-matrix`,
`tools/measure_store.py` for `ow eval perf` and `tools/ow_drivers.py` for `ow drivers` -- is to
put the mechanism in the package and the process control in `tools/`. This file is that half.

What it adds that `host/subproc.py` may not do is not `subprocess`: that module is one of the two
homes the semgrep bank names (`omniweave-no-subprocess-outside-toolchain-and-host-subproc`), so
the spawn itself is legal there and `spawn_worker()` lives there. What it adds is everything a
library may not have: an argv of its own, a report on stdout, `os.environ`, a working directory,
`time.monotonic` as a clock rather than as a parameter, exit codes, and a *stub driver* --
`--worker`, below -- whose whole purpose is to misbehave. `tools/gate_semgrep.py:26-37` takes the
same reading for itself in as many words: the ban is scoped to `packages/*/src/**` and a harness
whose job is to spawn is not library code.

## The nine scenarios, and the clause each one is

* `handshake` -- the child answers `HELLO_ACK`, one `PROGRESS` and one `RESULT` per unit.
  04:1696-1705's loop, and :1715's *"one `RESULT` per unit"*, which is what keeps a batch
  invisible to the `work` table.
* `card_mismatch` -- it answers with a different `driver_id`. :1696: *"any mismatch against the
  card is `CARD_CODE_MISMATCH` before work"*.
* `crash` -- it writes 9 KiB to stderr and calls `os._exit(3)` before any `RESULT`. 02:831: *"a
  worker that dies without a frame yields `driver_crashed` synthesised from the exit status plus
  the last 4 KiB of the stderr ring"*, and 04:1718's retry *"once at `batch = 1`"*.
* `quarantine` -- three crashes inside the window. :1720: `crash_quarantine = { crashes = 3,
  window_s = 60 }` quarantines the **driver**, *"not the unit"*, for the run.
* `silent` -- it answers `HELLO` and then nothing, ever. :1728's silent hang, which is
  `TIMEOUT` with `limit = "progress_ms"`.
* `flood` -- it streams `LOG` frames as fast as the pipe takes them. :1793's bounded queue and
  :1794's *"a driver cannot extend its own wall clock"*, which is `TIMEOUT{wall_ms_hard}`.
* `liar` -- it sends a prefix declaring a 4 GiB header. :1791: the caps are *"checked **before**
  any allocation"*.
* `truncated` -- it sends most of a frame and exits. The truncation refusal, which is OURS
  (02:1060), never a `driver_bug`.
* `impostor` -- it sends a `RESULT` for a unit outside the batch. :1796: *"out of range is a
  protocol error and the worker is killed, not trusted"*.

Every scenario ends by killing the child through a Windows **job object**, because :1728's
*"whole process group"* has no counterpart here (see `host/subproc.py`'s docstring) and
`JobObject.pids()` is what makes the reap observable rather than assumed.

## What this runner cannot observe on this machine

* **The AF_UNIX arm.** 02-architecture.md:428 offers *"a 0600 unix socket or an owner-only named
  pipe"*. `socket.AF_UNIX` is absent from CPython on Windows, so the named-pipe arm is the arm
  that runs and the socket arm is the arm that cannot even be constructed. Nothing here pretends
  otherwise: `sp.listener_for()` picks the arm and the report names which one it got.
* **A catchable termination.** There is no `SIGTERM`: `Popen.terminate()` IS `TerminateProcess`.
  The graceful half of :1728's ladder is therefore the `SHUTDOWN{grace_ms}` FRAME and the
  uncatchable half is `TerminateJobObject`. A driver that installs a `SIGTERM` handler and
  flushes is not reproducible here, and that is a fact about the driver's tidiness rather than
  about the host's availability -- which is the property section 6.5 is about.
* **A real segfault.** `crash` is `os._exit(3)`, not a memory fault. What the host reads is the
  exit status either way, and on Windows a signalled child does not exist: `TerminateProcess`
  sets whatever code the killer passed. The status is printed raw for that reason.
* **`RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NOFILE` and `os.nice`.** There is no `resource` module
  here. The address-space cap is the job object's `JOB_OBJECT_LIMIT_PROCESS_MEMORY`, the RSS
  sample is `K32GetProcessMemoryInfo`, the priority is `SetPriorityClass(BELOW_NORMAL)`, and the
  CPU and file-descriptor caps do not exist at all -- 04-driver-system.md:1752-1753's Windows
  cells are *"not available; `wall_ms_hard` only"* and *"not applicable"*. The report prints the
  granted record and every shortfall, because :1745 requires that what was not obtained be
  *"recorded rather than claimed"*.

## Exit codes

`0` every scenario behaved as its clause says. `1` a scenario ran and disagreed -- the report
names the check. `2` the runner did not run: a bad argument, a child that never connected, a pipe
that could not be created. `1` and `2` are distinguished because CI treats both as failure and a
human needs to know whether to read the plan or the harness (`tools/gate_crash.py`'s reasoning).

Specified in 04-driver-system.md sections 6.2-6.6, 02-architecture.md section 3.4 (S4) and
section 5.6's S4 row (:831), and 16-roadmap.md:482 (W3.2).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from omniweave_core.errors import DriverHostError
from omniweave_core.host import subproc as sp
from omniweave_core.host import wire
from omniweave_core.identity import config_digest
from omniweave_ports.types import FailureClass, Isolation, UnitRef

# `DriverHostError` is bound by DIRECT IMPORT here and never inside a function, and that is not
# style. `tests/unit/test_errors.py` calls `importlib.reload(errors)` to reset a memoised
# register read, and a reload REBUILDS every class object in that module -- so a
# `from omniweave_core.errors import DriverHostError` executed inside a function AFTER that
# reload binds the new class while `host/subproc.py`, imported once before it, still raises the
# old one. `except DriverHostError` then stops matching, and it stops matching only in a
# full-suite run: this runner's `card_mismatch` scenario escaped as an unhandled exception in
# exactly that order and passed when the file ran alone. A module-scope import binds at the same
# moment `subproc.py`'s own does, so the two name one object under every collection order.
# `test_host_wire.py`'s header records the same trap for the same reason.

__all__ = [
    "BEHAVIOURS",
    "CODE_FINGERPRINT",
    "DRIVER_ID",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "PIPE_PREFIX",
    "SCENARIOS",
    "SELF",
    "STUB_CONFIG",
    "Check",
    "Cycle",
    "Emit",
    "Observation",
    "Scenario",
    "cycle",
    "main",
    "worker",
    "worker_env",
    "worker_key",
]

SELF: Final = Path(__file__).resolve()
"""This file, absolute. The child is `sys.executable SELF --worker ...`, and `argv[0]` would be
whatever the caller typed -- a runner invoked as `tools/ow_host.py` from another directory would
otherwise spawn a child that does not exist (`tools/gate_crash.py` records the same trap)."""

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

PIPE_PREFIX: Final = "\\\\.\\pipe\\"
r"""`\\.\pipe\` -- the local-only namespace. A pipe name outside it is refused by the listener,
and this prefix is what makes the transport unreachable off-box even before
`PIPE_REJECT_REMOTE_CLIENTS` (02-architecture.md:155)."""

DRIVER_ID: Final = "parse.probe.stub"
"""The stub's id. `parse.<family>.<impl>` is the `DriverId` grammar of 04-driver-system.md
section 5.1 (charter section 5 X35), and the family is `probe` rather than a real format so that
nothing here can be mistaken for a shipped driver."""

VERSION: Final = "0.0.1"
SCHEMA_VERSION: Final = 1
CODE_FINGERPRINT: Final = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
"""`HELLO_ACK`'s `code_fingerprint` (04-driver-system.md:1696). A stub has no wheel to fingerprint,
so it reports a zero digest and the host compares what it was TOLD to expect -- which is the
comparison `CARD_CODE_MISMATCH` is, and the `card_mismatch` scenario is its negative."""

STUB_CONFIG: Final = {"drivers.probe.stub.mode": "default"}
"""The stub's effective config. One key, because what the worker key needs from a config is a
DIGEST and the digest's input is `omniweave_core.identity.config_digest`'s, never re-derived."""

MEMORY_MB: Final = 512
"""The stub's `[isolation] memory_mb`, which the job object caps and the sampler watches. 512 is
the reference card's number (04-driver-system.md:922); nothing here depends on the value."""

BATCH_MAX_UNITS: Final = 32
"""The reference card's `[isolation] batch_max_units` (04-driver-system.md:925), which is also
`isolation_granted`'s eighth key and the AIMD ceiling."""

UNIT_COUNT: Final = 2
"""Units per `INVOKE`. Two, so that "one `RESULT` per unit" and "the death lands on ONE unit" are
different observations; a batch of one cannot tell them apart."""

CONNECT_MS: Final = 10_000
"""How long the child tries to open the pipe, and the host waits for it. A cold interpreter plus
`import omniweave_core.host.subproc` is 12-performance.md:723's 200-800 ms; ten seconds is slack
for a loaded CI box and is still a bounded refusal."""

PATIENCE_MS: Final = 15_000
"""The wall time past which a scenario's own refusal is called a hang rather than a refusal.

Every deadline in the scenarios below is at most a few seconds, so this is the outer bound the
runner asserts against -- the observation is "the refusal was BOUNDED", and a bound needs a
number that is not the deadline it is checking. Fifteen seconds is `CONNECT_MS` plus slack.
"""

GRACE_MS: Final = 500
"""The `SHUTDOWN{grace_ms}` the runner gives a child before `TerminateJobObject`.

Shorter than `sp.KILL_GRACE_MS` (5 s, 04-driver-system.md:1728) ON PURPOSE and only here: three
of the nine scenarios leave a child that will never read another frame, so the plan's grace would
be fifteen seconds of a runner waiting for children it has already diagnosed. The library keeps
the plan's number as its default; this is a runner's argument to `stop()`."""

TICK_MS: Final = 250
"""`runtime.loop_lag_max_ms` (config.py; 04-driver-system.md:1769). The runner constructs
`HostSettings` from literals rather than loading a `Config`, because a runner that read
`omniweave.toml` would report what an operator's file says instead of what the plan says."""

Emit = Callable[[str], None]
"""One line of the report. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""


def _emitter(out: TextIO) -> Emit:
    """Bind the report to a stream, so a test can read the TEXT rather than a global stdout."""

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    return emit


def worker_key() -> sp.WorkerKey:
    """`(driver_id, config_digest)` -- the pool's only key (02-architecture.md:85, :482).

    The digest comes from `omniweave_core.identity.config_digest` and is never spelled here: two
    spellings of one digest is how a pool serves one configuration's work under another's
    settings, which is the correctness property the key exists for.
    """
    return sp.WorkerKey(driver_id=DRIVER_ID, config_digest=config_digest(STUB_CONFIG))


def worker_env() -> Mapping[str, str]:
    """A CURATED environment for the child. Never `os.environ` wholesale.

    `SpawnRequest.env` is a complete mapping rather than an overlay, because an inherited
    environment carries the host's `PYTHONPATH`, its proxy variables and its tokens into a third
    party's process (`SpawnRequest`'s docstring). Three variables are kept and each has a reason:
    `SYSTEMROOT` because a Windows Python cannot initialise without it, `PATH` because the
    interpreter resolves its own DLLs through it, and `TEMP` because `tempfile` reads it. Nothing
    else crosses.
    """
    keep = ("SYSTEMROOT", "SystemRoot", "PATH", "TEMP", "TMP")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# ---------------------------------------------------------------------------------------------
# The stub driver: the child, and the nine ways it can behave.
# ---------------------------------------------------------------------------------------------

BEHAVIOURS: Final = (
    "ok",
    "wrong_id",
    "crash",
    "silent",
    "flood",
    "liar",
    "truncated",
    "impostor",
)
"""What `--behave` accepts. EIGHT, one per shape of misbehaviour the scenarios need; `quarantine`
reuses `crash` three times, which is why there are nine scenarios and eight behaviours."""


def _result_frames(invoke: wire.Frame, *, behave: str) -> Sequence[bytes]:
    """The frames the stub answers one `INVOKE` with, for the co-operative behaviours."""
    units = invoke.header.get("units")
    count = len(units) if isinstance(units, list) else 0
    invoke_id = str(invoke.header.get("invoke_id", ""))
    frames = [
        wire.encode(
            wire.FrameKind.PROGRESS,
            {"invoke_id": invoke_id, "unit_index": 0, "done": 0, "total": count},
        )
    ]
    indices = [count + 97] if behave == "impostor" else list(range(count))
    frames.extend(
        wire.encode(
            wire.FrameKind.RESULT,
            {"invoke_id": invoke_id, "unit_index": index, "outcome": "ok"},
        )
        for index in indices
    )
    return frames


def worker(address: str, behave: str, *, emit: Emit) -> int:
    """The stub driver, in the child process. Connects, handshakes, then misbehaves on demand.

    It uses `omniweave_core.host.subproc.connect()` and `omniweave_core.host.wire` rather than a
    private copy of the frame layout, and that is deliberate: a worker with its own copy of the
    grammar is how two ends of one protocol drift, which is the reason `connect()` and
    `next_frame()` live in the host module at all.

    `os._exit` is what `crash` uses -- never `sys.exit`, which unwinds, runs `atexit` and would
    flush a `RESULT` the scenario needs never to arrive.
    """
    if behave not in BEHAVIOURS:
        emit(f"worker: {behave!r} is not one of {BEHAVIOURS}")
        return EXIT_NOT_RUN
    channel = sp.connect(address, timeout_ms=CONNECT_MS)
    hello = sp.next_frame(channel, expect=wire.Direction.HOST_TO_DRIVER)
    if hello is None or hello.kind is not wire.FrameKind.HELLO:
        emit(f"worker: first frame was {hello and hello.kind.name}, not HELLO")
        return EXIT_NOT_RUN
    granted = hello.header.get("isolation_granted") or {}
    channel.sendall(
        wire.encode(
            wire.FrameKind.HELLO_ACK,
            {
                "driver_id": "parse.probe.other" if behave == "wrong_id" else DRIVER_ID,
                "version": VERSION,
                "schema_version": SCHEMA_VERSION,
                "port": str(hello.header.get("port", "")),
                "code_fingerprint": CODE_FINGERPRINT,
                # Echoed back per DR10, "so a shortfall is visible from both sides" (04:1708).
                "isolation_granted": granted,
            },
        )
    )
    while True:
        frame = sp.next_frame(channel, expect=wire.Direction.HOST_TO_DRIVER)
        if frame is None or frame.kind is wire.FrameKind.SHUTDOWN:
            return EXIT_CLEAN
        if frame.kind is not wire.FrameKind.INVOKE:
            continue  # CANCEL and PROBE: a stub has nothing to abandon and nothing to probe.
        if behave == "crash":
            # 9 KiB, so the host's 4 KiB tail is a TAIL and not the whole of it.
            sys.stderr.write("stub: simulated abnormal exit\n" * 300)
            sys.stderr.flush()
            os._exit(3)  # uncatchable by intent: sys.exit unwinds and would flush a RESULT
        if behave == "silent":
            threading.Event().wait()  # forever: the host's progress_ms is the only clock left
        if behave == "flood":
            while True:
                channel.sendall(
                    wire.encode(
                        wire.FrameKind.LOG,
                        {"level": "info", "event": "tight_loop", "fields": {"n": 1}},
                    )
                )
        if behave == "liar":
            channel.sendall((0xFFFFFFFF).to_bytes(4, "little") + (0).to_bytes(4, "little"))
            threading.Event().wait()
        if behave == "truncated":
            whole = wire.encode(wire.FrameKind.RESULT, {"unit_index": 0, "outcome": "ok"})
            channel.sendall(whole[:-5])
            return EXIT_CLEAN  # the EOF mid-frame is the point
        for payload in _result_frames(frame, behave=behave):
            channel.sendall(payload)


# ---------------------------------------------------------------------------------------------
# The parent: one cycle is a listener, a spawn, an accept, a job object and a HELLO.
# ---------------------------------------------------------------------------------------------


def _now_ms() -> int:
    """The runner's clock: monotonic, in milliseconds.

    `time.time` is banned in library code and every clock there is a parameter; `tools/` is not
    library code, and this is the parameter it passes. Monotonic and not wall, because every
    number it feeds is a deadline (glossary.md:473 gives the NTP-step reason).
    """
    return time.monotonic_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class Cycle:
    """One live worker and everything that has to be released when it dies."""

    worker: sp.Worker
    listener: sp.Listener
    process: sp.WorkerProcess
    job: sp.JobObject
    stderr: sp.StderrRing
    granted: sp.IsolationGranted
    shortfalls: tuple[sp.IsolationShortfall, ...]

    def finish(self) -> int | None:
        """`SHUTDOWN`, then the uncatchable step, then the listener. Returns the exit status."""
        status = self.worker.stop(grace_ms=GRACE_MS)
        self.listener.close()
        return status


def cycle(behave: str, *, settings: sp.HostSettings, tag: str, emit: Emit) -> Cycle:
    """Spawn one stub worker and complete the `HELLO` handshake, or raise `DriverHostError`.

    The order matters and is the plan's: the listener exists BEFORE the child, because a child
    that connects to a name nobody is listening on has to retry and a squatter that creates the
    name first would receive our `HELLO` (`FILE_FLAG_FIRST_PIPE_INSTANCE`, and see
    `NamedPipeListener`'s docstring). The job object is assigned BEFORE the first `INVOKE`, so a
    child that dies mid-batch is reaped with its grandchildren.
    """
    address = f"{PIPE_PREFIX}ow-s4-{os.getpid()}-{tag}"
    listener = sp.listener_for(address)
    emit(f"  transport   {type(listener).__name__} at {listener.address}")
    granted, shortfalls = sp.grant_isolation(
        mode=Isolation.SUBPROC,
        batch_max_units=BATCH_MAX_UNITS,
        platform=sys.platform,
        address_space_capped=False,  # set below, once the job object actually took the limit
        net_blocked_requested=True,
        cpu_cap_requested=True,
        fd_cap_requested=True,
    )
    ring = sp.StderrRing()
    stdout_ring = sp.StderrRing()
    request = sp.SpawnRequest(
        argv=(
            sys.executable,
            str(SELF),
            "--worker",
            "--address",
            address,
            "--behave",
            behave,
        ),
        # cwd is EXPLICIT, always: the semgrep rule's own message is that graphify #2316 ran
        # `git rev-parse HEAD` without it and stamped the wrong repo's commit into a graph.
        cwd=str(SELF.parent.parent),
        env=worker_env(),
        address=address,
    )
    process = sp.spawn_worker(request, stderr=ring, stdout=stdout_ring)
    job = sp.JobObject(memory_limit_bytes=MEMORY_MB * 1_048_576)
    # EVERYTHING from here to the ack is inside the guard, because a handshake that fails leaves
    # a child nobody has killed: `CARD_CODE_MISMATCH` is a REFUSAL BEFORE WORK
    # (04-driver-system.md:1696), and a refusal that leaks the process it refused is a slow way
    # to run out of workers. The first version of this runner leaked exactly one child per
    # mismatch, which surfaced as `Popen.__del__` complaining under pytest's
    # `filterwarnings = ["error"]` -- the leak is the host's fault, not the test's.
    channel: sp.ByteChannel | None = None
    worker_process: sp.Worker | None = None
    try:
        job.assign(process.pid)
        granted, shortfalls = sp.grant_isolation(
            mode=Isolation.SUBPROC,
            batch_max_units=BATCH_MAX_UNITS,
            platform=sys.platform,
            address_space_capped=process.pid in job.pids(),
            net_blocked_requested=True,
            cpu_cap_requested=True,
            fd_cap_requested=True,
        )
        lowered, how = sp.lower_priority(process.pid)
        emit(f"  spawned     pid {process.pid}, job pids {job.pids()}, priority {lowered} ({how})")
        channel = listener.accept(timeout_ms=CONNECT_MS)
        worker_process = sp.Worker(
            worker_key(),
            process,
            channel,
            settings=settings,
            now_ms=_now_ms,
            stderr=ring,
            job=job,
        )
        ack = worker_process.hello(
            {
                "port": "parse/1",
                "card_schema": 1,
                "card_sha256": "sha256:" + "0" * 64,
                "driver_id": DRIVER_ID,
                "effective_config": dict(STUB_CONFIG),
                "roots": {"source_ro": str(SELF.parent), "tmp": os.environ.get("TEMP", ".")},
                "blob_base": str(SELF.parent),
                "isolation_granted": dict(granted.as_header()),
                "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-00",
            },
            expect={"driver_id": DRIVER_ID, "schema_version": SCHEMA_VERSION},
            deadlines=sp.Deadlines(progress_ms=CONNECT_MS, wall_ms_hard=CONNECT_MS, deadline_ms=0),
        )
    except BaseException:
        if worker_process is not None:
            # The worker owns the transport and the job handle, so its own kill path is the one
            # that releases both; a second closer here would be a second owner.
            worker_process.kill()
        else:
            job.terminate()
            # `TerminateJobObject` has already run, so the only thing `wait` can raise is a
            # timeout -- and `subprocess.TimeoutExpired` cannot be named here without importing
            # `subprocess`, which this runner deliberately does not (the spawn is
            # `spawn_worker()`'s). A reap this runner could not confirm is not worth an import.
            with contextlib.suppress(Exception):
                process.wait(timeout=GRACE_MS / 1000)
            if channel is not None:
                channel.close()
            job.close()
        listener.close()
        raise
    emit(f"  hello_ack   {ack.driver_id} v{ack.version} port={ack.port}")
    for shortfall in shortfalls:
        emit(f"  shortfall   {shortfall.message()}")
    return Cycle(
        worker=worker_process,
        listener=listener,
        process=process,
        job=job,
        stderr=ring,
        granted=granted,
        shortfalls=shortfalls,
    )


def _units() -> tuple[UnitRef, ...]:
    """`UNIT_COUNT` units, no bytes. The stub parses nothing; the frames are the subject."""
    return tuple(
        UnitRef(
            uri=f"file:///stub/{index}.txt",
            part="",
            content_sha256="sha256:" + f"{index:064d}",
            byte_len=0,
        )
        for index in range(UNIT_COUNT)
    )


def _invocation(tag: str) -> sp.Invocation:
    return sp.Invocation(
        invoke_id=f"inv-{tag}",
        units=_units(),
        deadline_ms=0,
        budget_micros=0,
    )


class _DepthWatch:
    """Sample `FrameReader.depth()` while an invocation runs, and keep the maximum.

    The bounded queue is a claim about a number nobody can see from the outside
    (04-driver-system.md:1793), so the flood scenario needs an observer: a thread that reads the
    depth every 2 ms and remembers the largest value it ever saw. A queue that never exceeds its
    bound is the assertion, and this is the instrument.
    """

    def __init__(self, reader: sp.FrameReader) -> None:
        self._reader = reader
        self._stop = threading.Event()
        self.peak = 0
        self._thread = threading.Thread(target=self._run, name="ow-s4-depth", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._reader.depth())
            self._stop.wait(0.002)

    def __enter__(self) -> _DepthWatch:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(1.0)


# ---------------------------------------------------------------------------------------------
# The scenarios.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    """One assertion, with the plan clause it is."""

    label: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Observation:
    """What one scenario saw. `ok` iff every check passed."""

    scenario: str
    checks: tuple[Check, ...]
    lines: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


Runner = Callable[[sp.HostSettings, Emit], Observation]


def _handshake(settings: sp.HostSettings, emit: Emit) -> Observation:
    """`HELLO` / `INVOKE` / `CANCEL`, the co-operative path, one `RESULT` per unit."""
    live = cycle("ok", settings=settings, tag="handshake", emit=emit)
    try:
        report = live.worker.invoke(
            _invocation("handshake"),
            deadlines=sp.Deadlines(progress_ms=5_000, wall_ms_hard=20_000, deadline_ms=0),
            memory_mb=MEMORY_MB,
        )
        live.worker.cancel("inv-handshake", generation=1)
        answered = sum(1 for result in report.results if result is not None)
        status = live.finish()
        return Observation(
            scenario="handshake",
            checks=(
                Check(
                    "one RESULT per unit (04:1715)",
                    answered == UNIT_COUNT,
                    f"{answered} of {UNIT_COUNT} units answered",
                ),
                Check(
                    "no unit unanswered",
                    report.unanswered() == (),
                    f"unanswered={report.unanswered()}",
                ),
                Check(
                    "PROGRESS observed",
                    report.progress_count >= 1,
                    f"progress_count={report.progress_count}",
                ),
                Check(
                    "the batch is CLEAN for AIMD (08:762)",
                    report.event is sp.BatchEvent.CLEAN,
                    f"event={report.event.value}",
                ),
                Check(
                    "the child exited on SHUTDOWN, not on a kill",
                    status == 0,
                    f"exit status {status}",
                ),
                Check(
                    "rss_sampled and tmp_only_writable were granted (04:1751, :1756)",
                    live.granted.rss_sampled and live.granted.tmp_only_writable,
                    str(dict(live.granted.as_header())),
                ),
            ),
        )
    finally:
        live.worker.kill()
        live.listener.close()


def _card_mismatch(settings: sp.HostSettings, emit: Emit) -> Observation:
    """A worker whose `HELLO_ACK` disagrees with the card. Refused BEFORE any work."""
    try:
        live = cycle("wrong_id", settings=settings, tag="mismatch", emit=emit)
    except DriverHostError as exc:
        symbol = exc.code()
        return Observation(
            scenario="card_mismatch",
            checks=(
                Check(
                    "CARD_CODE_MISMATCH before work (04:1696)",
                    symbol == "OW_CARD_CODE_MISMATCH",
                    f"{symbol}: {exc}",
                ),
            ),
        )
    live.worker.kill()
    live.listener.close()
    return Observation(
        scenario="card_mismatch",
        checks=(Check("CARD_CODE_MISMATCH before work (04:1696)", False, "the host accepted it"),),
    )


def _crash_cycle(settings: sp.HostSettings, emit: Emit, *, tag: str) -> sp.InvokeReport:
    """One crash, end to end. Shared by `crash` and `quarantine`."""
    live = cycle("crash", settings=settings, tag=tag, emit=emit)
    try:
        return live.worker.invoke(
            _invocation(tag),
            deadlines=sp.Deadlines(progress_ms=10_000, wall_ms_hard=20_000, deadline_ms=0),
        )
    finally:
        live.worker.kill()
        live.listener.close()


def _crash(settings: sp.HostSettings, emit: Emit) -> Observation:
    """A worker that dies without a frame: `driver_crashed`, SYNTHESISED, on ONE unit."""
    report = _crash_cycle(settings, emit, tag="crash")
    failures = [verdict for verdict in report.failures if verdict is not None]
    first = failures[0] if failures else None
    tail = first.stderr_tail if first is not None else b""
    return Observation(
        scenario="crash",
        checks=(
            Check(
                "driver_crashed synthesised (02:831)",
                first is not None and first.failure_class is FailureClass.DRIVER_CRASHED,
                "" if first is None else f"{first.failure_class.value}: {first.message}",
            ),
            Check(
                "the death lands on ONE unit (04:1719)",
                len(failures) == 1,
                f"{len(failures)} of {UNIT_COUNT} units carry the verdict",
            ),
            Check(
                "the exit status is carried, not guessed",
                first is not None and first.exit_status is not None,
                f"exit_status={None if first is None else first.exit_status}",
            ),
            Check(
                f"the stderr TAIL is at most {sp.STDERR_RING_BYTES} bytes",
                0 < len(tail) <= sp.STDERR_RING_BYTES,
                f"{len(tail)} bytes of stderr attached",
            ),
            Check(
                "the retry is ONCE, at batch = 1 (04:1718)",
                sp.retry_batch_size(report.event, attempt=0) == 1
                and sp.retry_batch_size(report.event, attempt=1) is None,
                f"attempt 0 -> {sp.retry_batch_size(report.event, attempt=0)}, "
                f"attempt 1 -> {sp.retry_batch_size(report.event, attempt=1)}",
            ),
        ),
        lines=(f"  stderr tail {tail[-48:]!r}",),
    )


def _quarantine(settings: sp.HostSettings, emit: Emit) -> Observation:
    """Three crashes inside the window take the DRIVER out for the run, not the unit."""
    ledger = sp.CrashLedger(threshold=settings.crash_threshold, window_s=settings.crash_window_s)
    states = []
    for index in range(settings.crash_threshold):
        _report = _crash_cycle(settings, emit, tag=f"quar{index}")
        states.append(ledger.record(DRIVER_ID, now_ms=_now_ms()))
        emit(f"  crash {index + 1}     quarantined={states[-1]}")
    other = ledger.record("parse.other.driver", now_ms=_now_ms())
    return Observation(
        scenario="quarantine",
        checks=(
            Check(
                f"{settings.crash_threshold} crashes in {settings.crash_window_s} s "
                "quarantine the driver (04:1720)",
                states[-1] is True,
                f"per-crash verdicts {states}",
            ),
            Check(
                "the earlier crashes did NOT quarantine",
                not any(states[:-1]),
                f"per-crash verdicts {states}",
            ),
            Check(
                "the set resolve() reads carries exactly this driver (02:831)",
                ledger.quarantined() == frozenset({DRIVER_ID}),
                f"quarantined={sorted(ledger.quarantined())}",
            ),
            Check(
                "one crash does not quarantine another driver",
                other is False,
                f"parse.other.driver quarantined={other}",
            ),
        ),
    )


def _silent(settings: sp.HostSettings, emit: Emit) -> Observation:
    """A driver that says nothing: `TIMEOUT`, `limit = "progress_ms"`, and then the reap."""
    live = cycle("silent", settings=settings, tag="silent", emit=emit)
    started = _now_ms()
    try:
        report = live.worker.invoke(
            _invocation("silent"),
            deadlines=sp.Deadlines(progress_ms=600, wall_ms_hard=30_000, deadline_ms=0),
        )
    finally:
        pids_before = live.job.pids()
        live.worker.kill()
        live.listener.close()
    elapsed = _now_ms() - started
    verdict = next((item for item in report.failures if item is not None), None)
    return Observation(
        scenario="silent",
        checks=(
            Check(
                "TIMEOUT with limit = progress_ms (04:1728)",
                verdict is not None
                and verdict.failure_class is FailureClass.TIMEOUT
                and verdict.limit == "progress_ms",
                "" if verdict is None else f"{verdict.failure_class.value}/{verdict.limit}",
            ),
            Check(
                "host-detected TIMEOUT is permanent (08:567)",
                verdict is not None and verdict.permanent,
                f"permanent={None if verdict is None else verdict.permanent}",
            ),
            Check(
                "the refusal was BOUNDED, not a hang",
                elapsed < PATIENCE_MS,
                f"{elapsed} ms against progress_ms = 600",
            ),
            Check(
                "the job held the child before the reap (04:1728's process group)",
                live.process.pid in pids_before,
                f"job pids {pids_before}, child {live.process.pid}",
            ),
            Check(
                "the child is gone after TerminateJobObject",
                live.process.poll() is not None,
                f"poll()={live.process.poll()}",
            ),
        ),
    )


def _flood(settings: sp.HostSettings, emit: Emit) -> Observation:
    """Millions of `LOG` frames: a bounded queue, and a wall clock the driver cannot extend."""
    live = cycle("flood", settings=settings, tag="flood", emit=emit)
    started = _now_ms()
    try:
        with _DepthWatch(live.worker.reader) as watch:
            report = live.worker.invoke(
                _invocation("flood"),
                deadlines=sp.Deadlines(progress_ms=30_000, wall_ms_hard=1_200, deadline_ms=0),
            )
        peak = watch.peak
    finally:
        live.worker.kill()
        live.listener.close()
    elapsed = _now_ms() - started
    verdict = next((item for item in report.failures if item is not None), None)
    return Observation(
        scenario="flood",
        checks=(
            Check(
                "TIMEOUT with limit = wall_ms_hard (04:1794)",
                verdict is not None
                and verdict.failure_class is FailureClass.TIMEOUT
                and verdict.limit == "wall_ms_hard",
                "" if verdict is None else f"{verdict.failure_class.value}/{verdict.limit}",
            ),
            Check(
                f"the read queue never exceeded frame_queue_max = {sp.FRAME_QUEUE_MAX} (04:1793)",
                peak <= sp.FRAME_QUEUE_MAX,
                f"peak depth {peak}",
            ),
            Check(
                "LOG frames arrived, so the flood was real",
                len(report.logs) > 0,
                f"{len(report.logs)} LOG frames drained",
            ),
            Check(
                "no PROGRESS frame arrived, so nothing reset progress_ms",
                report.progress_count == 0,
                f"progress_count={report.progress_count}",
            ),
            Check(
                "a driver cannot extend its own wall clock",
                elapsed < PATIENCE_MS,
                f"{elapsed} ms against wall_ms_hard = 1200",
            ),
        ),
    )


def _hostile(behave: str, scenario: str, expect: str) -> Runner:
    """Build a scenario whose whole assertion is "the reader refused, and named the fault"."""

    def run(settings: sp.HostSettings, emit: Emit) -> Observation:
        live = cycle(behave, settings=settings, tag=scenario, emit=emit)
        started = _now_ms()
        message = ""
        refused = False
        try:
            live.worker.invoke(
                _invocation(scenario),
                deadlines=sp.Deadlines(progress_ms=8_000, wall_ms_hard=15_000, deadline_ms=0),
            )
        except DriverHostError as exc:
            refused = True
            message = str(exc)
        finally:
            live.worker.kill()
            live.listener.close()
        elapsed = _now_ms() - started
        return Observation(
            scenario=scenario,
            checks=(
                Check(
                    f"the reader refused with {expect}",
                    refused and expect in message,
                    message or "no refusal",
                ),
                Check(
                    "the refusal is OURS: a DriverHostError, not a driver_bug (02:1060)",
                    refused,
                    message or "no refusal",
                ),
                Check(
                    "bounded, not a hang",
                    elapsed < PATIENCE_MS,
                    f"{elapsed} ms",
                ),
            ),
        )

    return run


@dataclass(frozen=True, slots=True)
class Scenario:
    """One row of the runner's table: a name, a runner and the clause it exercises."""

    name: str
    run: Runner
    clause: str


SCENARIOS: Final = (
    Scenario("handshake", _handshake, "04:1696-1705, one RESULT per unit"),
    Scenario("card_mismatch", _card_mismatch, "04:1696 CARD_CODE_MISMATCH before work"),
    Scenario("crash", _crash, "02:831 driver_crashed synthesised, retry once at batch = 1"),
    Scenario("quarantine", _quarantine, "04:1720 three crashes in 60 s take the driver"),
    Scenario("silent", _silent, "04:1728 TIMEOUT{progress_ms} and the reap"),
    Scenario("flood", _flood, "04:1793-1794 the bounded queue and the wall clock"),
    Scenario(
        "liar",
        _hostile("liar", "liar", "header_too_large"),
        "04:1791 the cap is checked before any allocation",
    ),
    Scenario(
        "truncated",
        _hostile("truncated", "truncated", "truncated"),
        "02:1060 a framing fault is ours",
    ),
    Scenario(
        "impostor",
        _hostile("impostor", "impostor", "unit_index"),
        "04:1796 out of range kills the worker",
    ),
)
"""NINE scenarios over EIGHT behaviours: `quarantine` drives `crash` three times."""


# ---------------------------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------------------------


def _settings() -> sp.HostSettings:
    """The `[drivers]` numbers, as literals from the plan rather than from an operator's file.

    08-runtime.md:2590-2591 and :2444: `worker_idle_ttl_s = 300`,
    `crash_quarantine = {crashes = 3, window_s = 60}`,
    `max_workers = {free = 4, local_compute = 4, billed_api = 8}`; `tick_ms` is
    `runtime.loop_lag_max_ms = 250` (04-driver-system.md:1769).
    """
    return sp.HostSettings(
        worker_idle_ttl_s=300,
        crash_threshold=3,
        crash_window_s=60,
        tick_ms=TICK_MS,
        max_workers={"free": 4, "local_compute": 4, "billed_api": 8},
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow_host.py",
        description=(
            "Drive a real subproc worker over a real owner-only named pipe and print what "
            "happened. Nine scenarios, one clause each; exit 0 clean, 1 a disagreement, "
            "2 the runner did not run."
        ),
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
        help="run only this scenario; repeatable. The default is all nine.",
    )
    parser.add_argument("--list", action="store_true", help="print the scenario table and stop")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--address", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--behave", default="ok", help=argparse.SUPPRESS)
    return parser


def _child(address: str | None, behave: str, *, emit: Emit) -> int:
    """The `--worker` branch of `main`, so the parent's own return count stays readable.

    A `DriverHostError` here is the HOST going away mid-handshake, which is the parent's finding
    to report and not the child's: the child prints one line and exits 2, and the parent's own
    refusal -- an accept that timed out, a synthesised crash -- is what lands in the report.
    """
    if not address:
        emit("worker: --worker needs --address")
        return EXIT_NOT_RUN
    try:
        return worker(address, behave, emit=emit)
    except DriverHostError as exc:
        emit(f"worker: {exc}")
        return EXIT_NOT_RUN


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Run the scenarios and report. `0` clean, `1` a disagreement, `2` the runner did not run."""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    emit = _emitter(out if out is not None else sys.stdout)
    if args.worker:
        return _child(args.address, args.behave, emit=emit)
    if args.list:
        for scenario in SCENARIOS:
            emit(f"{scenario.name:<14} {scenario.clause}")
        return EXIT_CLEAN
    if sys.platform != "win32":
        emit(
            "ow-host: the named-pipe arm is the Windows arm of S4 and the AF_UNIX arm has not "
            "been exercised; this runner has no POSIX cell yet (02-architecture.md:428)"
        )
        return EXIT_NOT_RUN
    wanted = tuple(args.scenario) if args.scenario else tuple(s.name for s in SCENARIOS)
    settings = _settings()
    emit(f"ow-host: {wire.PROTOCOL} over {PIPE_PREFIX}, {sys.platform}, pid {os.getpid()}")
    emit(
        f"ow-host: worker key {worker_key().driver_id} @ {worker_key().config_digest[:16]}..., "
        f"crash_quarantine = {{crashes = {settings.crash_threshold}, "
        f"window_s = {settings.crash_window_s}}}"
    )
    observations: list[Observation] = []
    started = _now_ms()
    for scenario in SCENARIOS:
        if scenario.name not in wanted:
            continue
        emit("")
        emit(f"ow-host: {scenario.name} -- {scenario.clause}")
        try:
            observation = scenario.run(settings, emit)
        except DriverHostError as exc:
            emit(f"  NOT RUN     {exc}")
            emit(f"  fix         {exc.fix}")
            return EXIT_NOT_RUN
        observations.append(observation)
        for line in observation.lines:
            emit(line)
        for check in observation.checks:
            emit(f"  {'ok  ' if check.ok else 'FAIL'}        {check.label}: {check.detail}")
    emit("")
    failed = [item for item in observations if not item.ok]
    checks = sum(len(item.checks) for item in observations)
    emit(
        f"ow-host: {len(observations)} scenarios, {checks} checks, {len(failed)} failed, "
        f"{_now_ms() - started} ms"
    )
    if failed:
        emit(f"ow-host: FAIL {', '.join(item.scenario for item in failed)}")
        return EXIT_FAIL
    emit("ow-host: clean")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
