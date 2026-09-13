"""The cross-process scoped lock: `O_CREAT|O_EXCL` plus `flock`, and who is holding it.

02-architecture.md section 2 row 23 is this module's charter, shared with `omniweave_core.clock`:

> | 23 | Locks, clock | `omniweave_core.locks`, `.clock` | **the scoped cross-process lock
> (`O_CREAT|O_EXCL` + `flock`, holder identity `(host, pid, process_create_time)`)**; the injected
> `Clock` protocol | ambient time ... | `scoped_lock()`, `Clock` | T-INTERNAL |

16-roadmap.md:549 schedules it as P4 W4.9, beside `clock.py` and `modelserver.py`.

## This is a move, and the file it came from asked for it

`FileScopedLock`, `LockHolder` and `process_create_time` shipped at P2 inside
`omniweave_core.store.sqlite`, because the store thread needed a writer lock before this module
existed. That file's `ScopedLock` docstring recorded the debt in as many words:

> **When `omniweave_core.locks` lands, `FileScopedLock` MOVES there and this Protocol stays.** That
> is the whole point of the split: the store thread depends on the shape, the shape is three
> methods, and INV-21's one-home rule is then satisfied by deleting one class from this file.

That is exactly what happened. The three names arrive here unchanged; `ScopedLock` stays there,
because the Protocol is the store thread's statement of what it needs and not a fact about locking.
`store/sqlite.py` re-exports the three so that no import outside it had to move, which is a pointer
rather than a second home -- the device `store/queue.py` uses for `DEP_KINDS`.

## The two mechanisms, and why neither alone is enough

02-architecture.md:746 fixes both:

1. **`O_CREAT|O_EXCL`** is the mutual exclusion. Creating the file is the atomic act.
2. **The advisory lock** (`fcntl.flock`, or `msvcrt.locking` on Windows) is the STALENESS test. A
   holder that was SIGKILLed leaves the file behind, and the file alone cannot tell a live holder
   from a dead one. The kernel can: if a contender takes the advisory lock on an existing file, the
   writer of that file is gone.

The holder identity is `(host, pid, process_create_time)` and 07:2724-2726 says what the third
component is for -- *"what stops a recycled pid from looking like a live holder."* On every platform
but Linux the standard library cannot read another process's start time (see `process_create_time`),
so the advisory lock carries that duty and the triple carries the operator-facing message. That
degradation is explicit rather than silent, which is the whole of the argument for it.

## What this cell adds to the moved code

08-runtime.md:2543 states four contract clauses a T3 substitute must keep, and three of them are
answers this module owes on a single node too:

| clause | here |
|---|---|
| *"`inspect()` without acquiring"* | `inspect()` -- reads the file, probes liveness |
| *"`held()` exposing `waited_seconds` and **naming the holder**"* | `Held`, returned by `hold()` |
| *"never stolen"* past a lease | vacuous here, binding on T3: this lock has no lease |
| the fourth is the mechanism itself | `FileScopedLock` |

and 02 row 23's printed entry point, `scoped_lock()`, which turns a scope name and a target into a
lock file under a root. `attach_or_spawn` step 3 (08:1046) is the second caller the naming scheme
has to serve -- *"scope=`service.<name>`, target=`<config_digest>`"* -- so the name is a pair rather
than a string, and `store.write` is the degenerate case with no target.

## The wait budgets live here

02 §5.4: *"how long a caller waits -- passed per call, not global: `[runtime] interactive_wait_ms =
2000` for a foreground command, `batch_wait_lock_ms = 60000` for an ingest."* Both name the **lock**
in their own names, so both are this module's, and `store/sqlite.py` re-exports them for the same
reason it re-exports the class: `Unit.wait_ms` is *"the `store.write` budget THIS unit pays"* and
every caller that spells one of these constants is naming that budget.

Stdlib only (INV-2 / G1), and not one of the nine LAZY names: a lock is taken before a store is
opened, so this module may not be reachable only through the store.

Tier T-INTERNAL: 02-architecture.md section 2 row 23.

Specified in 02-architecture.md section 2 row 23 and section 5.4, 07-store-and-retrieval.md
sections 10.1 and 10.6 (:2721-2730, :2872) and 08-runtime.md section 9.3 (:2543).
"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from omniweave_core.errors import StoreBusy, StoreError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover -- Windows has no fcntl.
    _fcntl = None
try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover -- POSIX has no msvcrt.
    _msvcrt = None

__all__ = [
    "BATCH_WAIT_MS",
    "INTERACTIVE_WAIT_MS",
    "LOCK_SUFFIX",
    "STORE_WRITE_LOCK",
    "FileScopedLock",
    "Held",
    "LockHolder",
    "LockState",
    "hold",
    "inspect",
    "lock_path",
    "process_create_time",
    "scope_name",
    "scoped_lock",
]


INTERACTIVE_WAIT_MS: Final = 2_000
BATCH_WAIT_MS: Final = 60_000
"""The two `store.write` wait budgets, PASSED PER CALL and never configured globally (07:2726-2729).

*"A lock timeout is a UX decision: codegraph's 120 s wait presented as a frozen, hung agent and was
cut to 5 s."* 08-runtime.md:2583 names the same pair from the runtime's side as
`[runtime] interactive_wait_ms` / `batch_wait_lock_ms` = 2000 / 60000, *"the two named `store.write`
wait budgets, passed per call"*, and 02-architecture.md section 5.4 gives the asymmetry its purpose:
a human at a terminal learns in two seconds that an ingest holds the lock, and the ingest is not
thrown off it because someone typed `ow query`.

**They live here and not in `omniweave_core.limits`, and the reason is limits.py's own rule.** That
module holds *"every `MAX_*` ceiling, the one `MIN_SQLITE` floor, and `effective()`"*
(02-architecture.md:231) under INV-22, *"a ceiling is never a target and never a setting"*. These
two are neither ceilings nor floors: they are the default arguments of one call, and the plan says
so in the same sentence that names them.

They moved from `store/sqlite.py` with the lock at W4.9, because 02 section 5.4 names both in the
row titled *"how long a caller waits"* -- the lock's row -- and `Unit.wait_ms` is documented there
as *"the `store.write` budget THIS unit pays"*.
"""

STORE_WRITE_LOCK: Final = "store.write"
"""The scoped lock's name (07:2724, 02-architecture.md:746). One string, one site.

The only scope v1 actually takes on this mechanism. `attach_or_spawn` takes `service.<name>`
(08:1046), which is why `scope_name()` exists rather than a second constant.
"""

LOCK_SUFFIX: Final = ".lock"
"""What `lock_path()` appends. Not `omniweave.index.lock`, which is a corpus receipt (02:1168)."""


# --------------------------------------------------------------------------------------------
# 1. Who holds a lock: `(host, pid, process_create_time)`.
# --------------------------------------------------------------------------------------------


def process_create_time(pid: int) -> tuple[float, str]:
    """`(process_create_time, source)` for `pid`, from the standard library only.

    The third component of the `store.write` holder identity, and 07:2724-2726 says exactly what it
    is for: *"holder identity is `(host, pid, process_create_time)` -- the third component is what
    stops a recycled pid from looking like a live holder."*

    **There is no portable standard-library API for another process's start time, so this degrades
    explicitly.** What each platform gives:

    * **Linux** -- `/proc/<pid>`'s own inode carries the process's start time. `st_ctime` on that
      directory is the moment the kernel created it, which is the moment the process started.
      Source `"/proc"`.
    * **macOS, the BSDs, Windows** -- nothing. The answer lives behind `sysctl(KERN_PROC)` and
      `GetProcessTimes`, and reaching either needs `ctypes` against a platform ABI or a third-party
      dependency, which INV-2 forbids core outright. Source `"unavailable"`, value `0.0`.

    **The degradation costs the operator-facing message and not the correctness property**, and that
    is why it is acceptable rather than merely admitted. The recycled-pid question is answered by
    `FileScopedLock` with an OS-held advisory lock, which the kernel releases when the holder dies
    whatever its pid becomes afterwards -- strictly stronger than comparing a start time, because it
    cannot be fooled by a clock change either. `process_create_time` remains in the identity because
    `15-observability.md:1537`'s doctor row `D-24` prints it: *"a live `store.write` lock: prints
    holder host, pid, `process_create_time`, age"*. Where it reads `0.0` the source string says
    `unavailable` and the doctor line says so rather than printing a plausible zero.
    """
    try:
        return (Path(f"/proc/{pid}").stat().st_ctime, "/proc")
    except OSError:
        return (0.0, "unavailable")


@dataclass(frozen=True, slots=True)
class LockHolder:
    """Who holds a scoped lock: `(host, pid, process_create_time)` plus what a report needs.

    The triple is 07:2724-2726's and 02-architecture.md:746's. `process_create_time_source` is this
    module's addition and is not a second copy of anything: it records WHICH mechanism answered, so
    a `0.0` reads as "this platform cannot tell" rather than as "the epoch". `acquired_ns` is a wall
    clock supplied by the lock's caller, and `age_s` against another supplied wall clock is what
    `StoreBusy.holder`'s third component is (`errors.py:247`, 18-api-sketch.md:450).
    """

    host: str
    pid: int
    process_create_time: float
    process_create_time_source: str
    acquired_ns: int

    def age_s(self, now_ns: int) -> float:
        """Seconds since `acquired_ns`, against a wall clock the caller reads.

        Negative would mean the holder's clock is ahead of ours, which on a shared mount is
        possible; it is clamped to 0.0 rather than reported, because a negative age in an error
        message reads as a bug in the message and the fact it would carry is "the clocks disagree",
        which is not what this error is about.
        """
        return max(0.0, (now_ns - self.acquired_ns) / 1e9)

    def as_json(self) -> str:
        """The lock file's payload: sorted keys, no spaces, one line.

        Sorted and separator-pinned because the file is read by another process and by a human, and
        a byte-stable rendering is what makes "the lock file changed" a meaningful observation.
        """
        return json.dumps(
            {
                "host": self.host,
                "pid": self.pid,
                "process_create_time": self.process_create_time,
                "process_create_time_source": self.process_create_time_source,
                "acquired_ns": self.acquired_ns,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# --------------------------------------------------------------------------------------------
# 2. The mechanism: `O_CREAT|O_EXCL` for exclusion, an advisory lock for staleness.
# --------------------------------------------------------------------------------------------

_LOCK_BYTE: Final = 1 << 20
"""The byte offset Windows byte-range locking uses, and it is NOT 0.

Measured on Windows 11: `msvcrt.locking` at offset 0 makes the locked byte unreadable to every
handle, this process's included, so a contender trying to READ the holder's identity out of the lock
file gets `PermissionError` and reports "no holder" for a lock that is very much held -- turning the
`StoreBusy` message that names host, pid and age (07:2872) into `?` and `0`. Locking one byte a
megabyte past any plausible payload keeps the identity readable while the lock itself stays
exclusive; Windows permits a range beyond end-of-file, which is what makes the offset free.

`fcntl.flock` needs no offset: it locks the open file description as a whole and blocks no read.
"""


def _take_advisory(fd: int) -> bool | None:
    """Try to take an OS advisory lock on `fd`. `True`/`False` taken or refused, `None` unknowable.

    The liveness half of 02-architecture.md:746's `O_CREAT|O_EXCL` plus `flock`. An advisory lock is
    the one liveness signal that cannot be wrong: the kernel drops it when the holding process dies,
    however it died and whatever pid is issued next. `None` means neither `fcntl` nor `msvcrt` is
    importable, which is not a platform this framework has met; the caller degrades to "assume the
    holder is live", which errs towards refusing a write rather than towards two writers.
    """
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    if _msvcrt is not None:
        os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
        try:
            _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    return None  # pragma: no cover -- no platform in the support matrix reaches this.


def _drop_advisory(fd: int) -> None:
    """Release an advisory lock taken by `_take_advisory`, tolerating a platform that has none."""
    if _fcntl is not None:
        with suppress(OSError):
            _fcntl.flock(fd, _fcntl.LOCK_UN)
    elif _msvcrt is not None:
        os.lseek(fd, _LOCK_BYTE, os.SEEK_SET)
        with suppress(OSError):
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)


@dataclass(eq=False)
class FileScopedLock:
    """`store.write` as a lock FILE plus an advisory lock on it. The shipped `ScopedLock`.

    02-architecture.md:746 fixes both mechanisms and this class is exactly those two:

    1. **`O_CREAT|O_EXCL`** is the mutual exclusion. Creating the file is the atomic act; the winner
       writes its `LockHolder` payload into it.
    2. **The advisory lock** (`fcntl.flock`, or `msvcrt.locking` on Windows) is the STALENESS test.
       A holder that was SIGKILLed leaves the file behind, and the file alone cannot distinguish a
       live holder from a dead one -- which is the same question `process_create_time` exists to
       answer and which the kernel answers better: if a contender can take the advisory lock on an
       existing file, the writer of that file is gone, and the file is broken and retried.

    **The wait is passed per call and never configured** (07:2726-2729). `acquire(wait_ms=...)`
    polls
    at `_POLL_MS` until the budget is spent and then raises `StoreBusy`, whose `EXIT = 7` and whose
    `.holder` is `(host, pid, age_s)` -- errors.py:246-261 and 18-api-sketch.md:450, *"the only code
    for which a bare retry is correct"*. **Never a silent retry loop** (07:2872).

    `now_ns` is a wall clock the caller supplies, because `time.time` is banned in library code
    (02-architecture.md:392). It is read twice: once to stamp `acquired_ns` into the payload, and
    once per refusal to compute the holder's age. A test supplies a counter and gets a deterministic
    age.

    `path` is the lock file. It is NOT `omniweave.index.lock` -- that is the committed corpus
    receipt
    (02-architecture.md:1168) and has nothing to do with this. A caller names
    `<cache_root>/store.write.lock` or equivalent; this class takes the path and no policy.
    """

    path: Path
    now_ns: Callable[[], int]
    name: str = STORE_WRITE_LOCK
    host: str = field(default_factory=socket.gethostname)
    pid: int = field(default_factory=os.getpid)
    _fd: int | None = field(default=None, init=False, repr=False)

    _POLL_MS: ClassVar[int] = 25
    """The poll interval while waiting. `ClassVar`, not `Final`: `dataclasses` excludes only
    `ClassVar`, so a bare `Final = 25` in a dataclass body becomes a seventh FIELD with a default
    -- measured, and the reason this annotation is spelled the long way."""

    def identity(self) -> LockHolder:
        """This process's `LockHolder`, stamped with the caller's clock."""
        created, source = process_create_time(self.pid)
        return LockHolder(
            host=self.host,
            pid=self.pid,
            process_create_time=created,
            process_create_time_source=source,
            acquired_ns=self.now_ns(),
        )

    def holder(self) -> LockHolder | None:
        """Read the lock file's payload, or `None` when there is no live holder.

        A file whose payload does not parse is reported as a holder with `pid = 0` rather than as no
        holder, because "there is a lock file I cannot read" must not resolve to "the lock is free".
        """
        return _read_holder(self.path)

    def acquire(self, *, wait_ms: int = INTERACTIVE_WAIT_MS) -> None:
        """Take the lock within `wait_ms`, or raise `StoreBusy` naming host, pid and age.

        The loop is: try `O_CREAT|O_EXCL`; on `FileExistsError` try to break a dead holder's file;
        sleep `_POLL_MS`; repeat until the budget is spent. `wait_ms = 0` is one attempt and no
        sleep, which is what a caller that has already enqueued its work wants when it is only
        probing.

        Re-entering on a lock this object already holds is a usage error, not a no-op: two
        `acquire()` calls and one `release()` would leave the file behind with nobody watching it.
        """
        if self._fd is not None:
            raise StoreError(
                f"{self.name} is already held by this object; a scoped lock is not reentrant, "
                f"because the second release would be the one that mattered",
                fix="release the lock before acquiring it again",
            )
        deadline = time.monotonic_ns() + wait_ms * 1_000_000
        while True:
            if self._try_create():
                return
            if self._break_if_dead() and self._try_create():
                return
            if time.monotonic_ns() >= deadline:
                break
            time.sleep(self._POLL_MS / 1000)
        self._refuse(wait_ms)

    def _try_create(self) -> bool:
        """One `O_CREAT|O_EXCL` attempt; on success write the payload and hold the descriptor."""
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        except FileExistsError:
            return False
        except OSError as error:
            raise StoreError(
                f"cannot create the {self.name} lock at {self.path}: {error}",
                fix="check that the cache root is writable",
            ) from error
        os.write(fd, self.identity().as_json().encode("utf-8") + b"\n")
        _take_advisory(fd)
        self._fd = fd
        return True

    def _break_if_dead(self) -> bool:
        """Unlink a lock file whose writer is gone, proved by taking the advisory lock on it.

        Returns whether it broke one, so `acquire` retries the `O_CREAT|O_EXCL` immediately rather
        than sleeping a poll interval -- which is what makes `acquire(wait_ms=0)` against a stale
        file succeed instead of refusing.

        `taken is None` means the platform offers no advisory lock at all, in which case the file is
        left alone: refusing a write is recoverable and two writers are not.
        """
        try:
            fd = os.open(self.path, os.O_RDWR)
        except OSError:
            return False
        try:
            if _take_advisory(fd) is not True:
                return False
            _drop_advisory(fd)
        finally:
            os.close(fd)
        try:
            self.path.unlink()
        except OSError:
            return False
        return True

    def _refuse(self, wait_ms: int) -> None:
        """Raise `StoreBusy` (exit 7) naming host, pid and age. Never a silent retry."""
        held = self.holder()
        host = held.host if held else "?"
        pid = held.pid if held else 0
        age = held.age_s(self.now_ns()) if held else 0.0
        raise StoreBusy(
            f"another writer holds {self.name}: host {host}, pid {pid}, age {age:.1f}s; "
            f"waited {wait_ms} ms",
            holder=(host, pid, age),
            symbol="OW_STORE_BUSY",
            fix=f"wait for {host}:{pid} to finish, or `ow store repair` if it is gone",
        )

    def release(self) -> None:
        """Drop the advisory lock, close the descriptor and unlink the file. Idempotent."""
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        _drop_advisory(fd)
        os.close(fd)
        with suppress(OSError):
            self.path.unlink()

    def __enter__(self) -> FileScopedLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _read_holder(path: Path) -> LockHolder | None:
    """Parse a lock file's payload. `None` only when the file cannot be READ at all.

    Factored out of `FileScopedLock.holder()` at W4.9 so `inspect()` shares it rather than parsing
    the payload a second time -- the payload's shape is `LockHolder.as_json()`'s and one reader is
    what keeps that true.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return LockHolder(
        host=str(data.get("host", "?")),
        pid=int(data.get("pid", 0)),
        process_create_time=float(data.get("process_create_time", 0.0)),
        process_create_time_source=str(data.get("process_create_time_source", "unavailable")),
        acquired_ns=int(data.get("acquired_ns", 0)),
    )


# --------------------------------------------------------------------------------------------
# 3. Naming a lock, and taking one. 02 row 23's `scoped_lock()`.
# --------------------------------------------------------------------------------------------


def scope_name(scope: str, target: str = "") -> str:
    """`'store.write'`, or `'service.vlm/9f8e7d6c'` -- a scope and the thing it is scoped to.

    08:1046, `attach_or_spawn` step 3, is the second caller and the one that forces the shape:
    *"TAKE THE SCOPED LOCK scope=`service.<name>`, target=`<config_digest>`"*. A Service is one per
    `(name, config_digest)`, so two revisions of one model must take two different locks; a scope
    string with no target could not express that and `store.write`, which is one per store, needs
    no target at all.

    The separator is `/` because a lock name is not a file name -- `lock_path()` is what turns it
    into one, and it is the only function that has to know that `:` is illegal on Windows.
    """
    if not scope:
        raise StoreError("a lock scope is empty", fix="name the scope, e.g. 'store.write'")
    return f"{scope}/{target}" if target else scope


def lock_path(root: Path, scope: str, target: str = "") -> Path:
    """Where `scope_name(scope, target)`'s lock file lives under `root`.

    The name is flattened with `-`: `service.vlm/9f8e7d6c` becomes `service.vlm-9f8e7d6c.lock`. One
    directory rather than a tree, because a lock file is created and unlinked constantly and an
    empty directory left behind per scope would be litter that nothing sweeps.

    `root` is a caller's -- `roots.cache` in practice -- and this module takes no view on it. INV-21
    keeps `roots` in `omniweave_core.config`, and a lock module that resolved its own root would be
    a second place the cache root is decided.
    """
    flat = scope_name(scope, target).replace("/", "-")
    return root / f"{flat}{LOCK_SUFFIX}"


def scoped_lock(
    root: Path,
    scope: str = STORE_WRITE_LOCK,
    target: str = "",
    *,
    now_ns: Callable[[], int],
) -> FileScopedLock:
    """02 row 23's printed entry point: a `FileScopedLock` for one scope under one root.

    A factory rather than a constructor call, because the path is derived and the derivation is the
    part two callers must agree on: `ow query` and `ow ingest` contend for `store.write` only if
    they compute the same file name from the same root, and `attach_or_spawn`'s double-check inside
    the lock is safe only if the outer and inner probes name one file.

    `now_ns` is required and has no default. `time.time` is banned in library code
    (02-architecture.md:392), so a wall reading is always a parameter -- and a lock that minted its
    own would be the one place in the framework where a test could not control the holder's age,
    which is precisely what the `StoreBusy` message prints.
    """
    return FileScopedLock(
        lock_path(root, scope, target), now_ns=now_ns, name=scope_name(scope, target)
    )


# --------------------------------------------------------------------------------------------
# 4. Looking without taking, and taking with a receipt. 08-runtime.md:2543.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LockState:
    """What `inspect()` reports: whether a lock file exists, who wrote it, and whether they live.

    Three fields and not a boolean, for the reason `Baseline` in `run/converge.py` is three
    states: *"absent"*, *"there and its writer is alive"* and *"there and its writer is gone"*
    are three different facts, and the third is the one `ow doctor` has to be
    able to print. `15-observability.md:1537`'s row D-24 asks for exactly that -- *"a live
    `store.write` lock: prints holder host, pid, `process_create_time`, age"* -- and a stale file
    reported as "held" sends an operator to look for a process that does not exist.

    `live` is `None` when the platform offers no advisory lock at all, which is not a platform this
    framework has met; it reads as *"cannot tell"* rather than as either answer.
    """

    present: bool
    holder: LockHolder | None
    live: bool | None

    @property
    def stale(self) -> bool:
        """A file whose writer is provably gone. Never true on a `live is None` platform."""
        return self.present and self.live is False


def inspect(path: Path) -> LockState:
    """Report on a lock without acquiring it. 08:2543's first contract clause.

    **It takes nothing and it breaks nothing.** The liveness probe acquires the advisory lock and
    releases it immediately, which is the only way to ask the kernel the question -- but it does not
    unlink the file even when the answer is "stale", because breaking a lock is `acquire()`'s job
    and a caller that only wanted to look must not have changed the world by looking.

    This is what `ow doctor` and `ow queue status` call. It is also what makes the `StoreBusy`
    message worth printing: the holder it names came from here.
    """
    if not path.exists():
        return LockState(present=False, holder=None, live=None)
    holder = _read_holder(path)
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return LockState(present=True, holder=holder, live=None)
    try:
        taken = _take_advisory(fd)
        if taken is True:
            _drop_advisory(fd)
    finally:
        os.close(fd)
    if taken is None:  # pragma: no cover -- no platform in the support matrix reaches this.
        return LockState(present=True, holder=holder, live=None)
    return LockState(present=True, holder=holder, live=not taken)


@dataclass(frozen=True, slots=True)
class Held:
    """The receipt `hold()` yields: who else was in the way, and for how long. 08:2543.

    *"`held()` exposing `waited_seconds` and **naming the holder**"*. `waited_seconds` is the
    time `acquire()` actually spent in its poll loop, not the budget it was given, so a contended
    lock and an uncontended one are distinguishable after the fact -- which is what makes
    `service_observation.queue_p95_ms`'s sibling question answerable for the store lock too.

    `blocked_by` is whoever held the file when the first attempt failed, or `None` when the first
    attempt won. It is read before the wait rather than after, because by the time the wait ends the
    holder that caused it has released and the file names whoever is next.
    """

    name: str
    waited_seconds: float
    blocked_by: LockHolder | None

    @property
    def contended(self) -> bool:
        return self.blocked_by is not None


@contextmanager
def hold(lock: FileScopedLock, *, wait_ms: int = INTERACTIVE_WAIT_MS) -> Iterator[Held]:
    """Take `lock`, yield the receipt, release on the way out -- including on a raise.

    **There is no lease and therefore nothing to extend.** 08:2543's third clause -- *"a live holder
    past its lease is extended once with a warning, never stolen"* -- constrains a T3 substitute
    (an advisory Postgres lock, or a lease row), and it is vacuous on this mechanism: an
    `O_CREAT|O_EXCL` file plus an advisory lock has no expiry, so a live holder is held until
    it releases or dies. The clause is transcribed rather than implemented, and the property
    it protects -- **never stolen** -- is what `_break_if_dead` already guarantees, by
    unlinking only a file whose writer the kernel says is gone.

    A raise inside the body releases the lock. `StoreBusy` from the acquire does not reach the body
    at all, which is the difference between "I could not take it" and "I took it and failed".
    """
    blocked_by = lock.holder()
    started = time.monotonic_ns()
    lock.acquire(wait_ms=wait_ms)
    waited = (time.monotonic_ns() - started) / 1e9
    try:
        yield Held(
            name=lock.name,
            waited_seconds=waited,
            blocked_by=blocked_by,
        )
    finally:
        lock.release()
