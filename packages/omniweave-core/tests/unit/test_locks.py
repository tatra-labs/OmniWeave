"""`omniweave_core.locks`: the scoped cross-process lock, and who is holding it.

Most of this file MOVED here from `test_store_sqlite.py` with the code it tests, at P4 W4.9. The
tests are unchanged: a move that rewrote its tests would be a rewrite wearing a move's name, and
the whole claim of the move is that `FileScopedLock` is the same class in a better home.

What is new is this cell's own three, which are 08-runtime.md:2543's contract clauses:
`inspect()` without acquiring, `held()` exposing `waited_seconds` and naming the holder, and
`scoped_lock()` -- 02-architecture.md row 23's printed entry point, whose second caller is
`attach_or_spawn` step 3 at `scope="service.<name>", target="<config_digest>"`.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import pytest
from omniweave_core import locks
from omniweave_core.errors import StoreBusy, StoreError
from omniweave_core.locks import (
    BATCH_WAIT_MS,
    INTERACTIVE_WAIT_MS,
    LOCK_SUFFIX,
    STORE_WRITE_LOCK,
    FileScopedLock,
    LockHolder,
    _drop_advisory,
    _take_advisory,
    hold,
    inspect,
    lock_path,
    process_create_time,
    scope_name,
    scoped_lock,
)
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from pathlib import Path

NOW_NS = 1_700_000_000_000_000_000


# =============================================================================================
# 1. The lock itself. Moved from `test_store_sqlite.py` with the code, unchanged.
# =============================================================================================


def test_the_lock_identity_is_host_pid_and_process_create_time(tmp_path: Path) -> None:
    """07:2724-2726's triple, plus the source that keeps a degraded value honest."""
    lock = FileScopedLock(tmp_path / "store.write.lock", now_ns=lambda: NOW_NS)
    identity = lock.identity()
    assert identity.host == lock.host
    assert identity.pid == os.getpid()
    assert identity.process_create_time_source in {"/proc", "unavailable"}
    assert (identity.process_create_time > 0.0) == (identity.process_create_time_source == "/proc")


def test_process_create_time_degrades_explicitly_rather_than_silently() -> None:
    """No portable stdlib API exists, so the unknowable case says `unavailable` and returns 0.0.

    Pid 0 is not a process on any supported platform, so this exercises the degradation on Linux
    too, where the live-pid branch would otherwise be the only one a test on that platform sees.
    """
    value, source = process_create_time(0)
    assert (value, source) == (0.0, "unavailable")


def test_the_second_holder_of_one_lock_is_refused_with_exit_seven(tmp_path: Path) -> None:
    """07:2872: the loser *"reports store busy (exit 7) naming host, pid and age -- never a silent
    retry loop."*

    Both locks live in this process, and the refusal still holds: an advisory lock is per open file
    description, so a second descriptor is refused whichever process opened it. `wait_ms = 0` is one
    attempt, which is what makes the test fast and the refusal deterministic.
    """
    path = tmp_path / "store.write.lock"
    clock = iter([NOW_NS, NOW_NS + 3_000_000_000, NOW_NS + 3_000_000_000])
    first = FileScopedLock(path, now_ns=lambda: next(clock))
    second = FileScopedLock(path, now_ns=lambda: NOW_NS + 3_000_000_000)
    first.acquire(wait_ms=0)
    try:
        # The holder's own descriptor carries the advisory lock, asserted here and not only through
        # the outcome below. On Windows an open descriptor already blocks `unlink`, so the refusal
        # would be produced even by a build that never took the lock -- and that build would hand
        # two writers one store on POSIX, where unlinking an open file succeeds.
        probe = os.open(path, os.O_RDWR)
        try:
            assert _take_advisory(probe) is False
        finally:
            os.close(probe)
        with pytest.raises(StoreBusy) as caught:
            second.acquire(wait_ms=0)
        assert caught.value.EXIT == 7
        assert caught.value.code() == "OW_STORE_BUSY"
        host, pid, age = caught.value.holder
        assert (host, pid) == (first.host, os.getpid())
        assert age == pytest.approx(3.0, abs=0.01)
        assert str(pid) in str(caught.value)
    finally:
        first.release()


def test_the_advisory_lock_refuses_a_second_descriptor_and_keeps_the_payload_readable(
    tmp_path: Path,
) -> None:
    """The liveness mechanism itself, pinned directly, because the outcome test cannot isolate it.

    **Why this test exists beside the refusal test above.** On Windows an open descriptor already
    blocks `unlink`, so a lock file whose holder is alive cannot be broken even if no advisory lock
    was ever taken -- which means the "second holder is refused" outcome is produced by the wrong
    mechanism there and a build that stopped calling `_take_advisory` would still pass. On POSIX,
    where unlinking an open file succeeds, that build would hand two writers the same store.
    Testing the primitive is what makes the property platform-independent.

    The second assertion is the byte offset. `_LOCK_BYTE` is a megabyte past any payload because a
    Windows byte-range lock at offset 0 makes the locked byte unreadable, and an unreadable payload
    turns `StoreBusy`'s "host, pid and age" (07:2872) into `?` and `0`.
    """
    path = tmp_path / "store.write.lock"
    path.write_bytes(b'{"host":"h","pid":1}' + b"\n")
    first = os.open(path, os.O_RDWR)
    try:
        assert _take_advisory(first) is True
        second = os.open(path, os.O_RDWR)
        try:
            assert _take_advisory(second) is False
        finally:
            os.close(second)
        assert path.read_text(encoding="utf-8").startswith('{"host"')
        _drop_advisory(first)
        third = os.open(path, os.O_RDWR)
        try:
            assert _take_advisory(third) is True
            _drop_advisory(third)
        finally:
            os.close(third)
    finally:
        os.close(first)


def test_a_stale_lock_file_whose_holder_is_gone_is_broken_and_taken(tmp_path: Path) -> None:
    """The `process_create_time` question, answered by the kernel instead.

    A lock file written by nobody is exactly what a SIGKILLed holder leaves: the bytes are there and
    the advisory lock is not. A contender that can take the advisory lock has PROVED the writer is
    gone, which is stronger than comparing a recorded start time and cannot be fooled by a recycled
    pid or a clock change.
    """
    path = tmp_path / "store.write.lock"
    stale = LockHolder(
        host="dead-host",
        pid=999_999,
        process_create_time=1.0,
        process_create_time_source="unavailable",
        acquired_ns=NOW_NS,
    )
    path.write_text(stale.as_json() + "\n", encoding="utf-8")
    lock = FileScopedLock(path, now_ns=lambda: NOW_NS)
    lock.acquire(wait_ms=0)
    try:
        held = lock.holder()
        assert held is not None
        assert held.pid == os.getpid()
    finally:
        lock.release()
    assert not path.exists()


def test_releasing_a_lock_is_idempotent_and_reacquiring_it_is_not(tmp_path: Path) -> None:
    """A scoped lock is not reentrant: the second release would be the one that mattered."""
    lock = FileScopedLock(tmp_path / "store.write.lock", now_ns=lambda: NOW_NS)
    lock.release()
    lock.acquire(wait_ms=0)
    with pytest.raises(StoreError):
        lock.acquire(wait_ms=0)
    lock.release()
    lock.release()


def test_the_lock_is_a_context_manager_that_releases_on_the_way_out(tmp_path: Path) -> None:
    """The shape every caller uses, so the file cannot outlive the block by accident."""
    path = tmp_path / "store.write.lock"
    with FileScopedLock(path, now_ns=lambda: NOW_NS):
        assert path.exists()
    assert not path.exists()


# =============================================================================================
# 2. Naming a lock. 02 row 23's `scoped_lock()`, and `attach_or_spawn`'s second scope.
# =============================================================================================


def test_the_default_scope_is_the_one_v1_takes() -> None:
    assert STORE_WRITE_LOCK == "store.write"
    assert scope_name(STORE_WRITE_LOCK) == "store.write"


def test_a_service_scope_carries_its_target() -> None:
    """08:1046 step 3: a Service is one per `(name, config_digest)`, so two revisions differ."""
    assert scope_name("service.vlm", "9f8e7d6c") == "service.vlm/9f8e7d6c"
    assert scope_name("service.vlm", "9f8e7d6c") != scope_name("service.vlm", "0a1b2c3d")


def test_an_empty_scope_is_refused() -> None:
    with pytest.raises(StoreError, match="scope is empty"):
        scope_name("")


def test_the_path_flattens_the_name_and_lives_in_one_directory(tmp_path: Path) -> None:
    """`/` is illegal in a file name on every platform and `:` on one; the flattening is here."""
    path = lock_path(tmp_path, "service.vlm", "9f8e7d6c")
    assert path == tmp_path / f"service.vlm-9f8e7d6c{LOCK_SUFFIX}"
    assert path.parent == tmp_path


def test_two_callers_computing_the_same_scope_contend(tmp_path: Path) -> None:
    """The property `scoped_lock()` exists for: contention requires agreeing on the file name."""
    first = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    second = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    first.acquire(wait_ms=0)
    try:
        with pytest.raises(StoreBusy):
            second.acquire(wait_ms=0)
    finally:
        first.release()


def test_two_targets_of_one_scope_do_not_contend(tmp_path: Path) -> None:
    vlm = scoped_lock(tmp_path, "service.vlm", "9f8e7d6c", now_ns=lambda: NOW_NS)
    other = scoped_lock(tmp_path, "service.vlm", "0a1b2c3d", now_ns=lambda: NOW_NS)
    vlm.acquire(wait_ms=0)
    other.acquire(wait_ms=0)
    assert vlm.name == "service.vlm/9f8e7d6c"
    assert other.name == "service.vlm/0a1b2c3d"
    vlm.release()
    other.release()


def test_the_lock_carries_its_scope_name_into_the_refusal(tmp_path: Path) -> None:
    held_lock = scoped_lock(tmp_path, "service.vlm", "9f8e7d6c", now_ns=lambda: NOW_NS)
    held_lock.acquire(wait_ms=0)
    try:
        with pytest.raises(StoreBusy, match=re.escape("service.vlm/9f8e7d6c")):
            scoped_lock(tmp_path, "service.vlm", "9f8e7d6c", now_ns=lambda: NOW_NS).acquire(
                wait_ms=0
            )
    finally:
        held_lock.release()


# =============================================================================================
# 3. `inspect()` -- 08:2543's first contract clause
# =============================================================================================


def test_inspecting_a_lock_nobody_holds_reports_absent(tmp_path: Path) -> None:
    state = inspect(tmp_path / f"store.write{LOCK_SUFFIX}")
    assert (state.present, state.holder, state.live) == (False, None, None)
    assert state.stale is False


def test_inspecting_a_held_lock_names_the_holder_and_takes_nothing(tmp_path: Path) -> None:
    """*"`inspect()` without acquiring"*: it must not become the holder by asking."""
    lock = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    lock.acquire(wait_ms=0)
    try:
        state = inspect(lock.path)
        assert state.present is True
        assert state.live is True
        assert state.stale is False
        assert state.holder is not None
        assert state.holder.pid == lock.pid
        assert lock.path.exists(), "inspect() must not have released or broken the lock"
    finally:
        lock.release()


def test_inspecting_a_stale_lock_says_stale_rather_than_held(tmp_path: Path) -> None:
    """A file whose writer is gone reported as "held" sends an operator hunting a dead pid."""
    path = tmp_path / f"store.write{LOCK_SUFFIX}"
    stale = LockHolder(
        host="gone",
        pid=999_999,
        process_create_time=1.0,
        process_create_time_source="unavailable",
        acquired_ns=NOW_NS,
    )
    path.write_text(stale.as_json() + "\n", encoding="utf-8")
    state = inspect(path)
    assert state.present is True
    assert state.live is False
    assert state.stale is True
    assert state.holder is not None
    assert state.holder.host == "gone"
    assert path.exists(), "inspect() reports staleness; breaking the file is acquire()'s job"


def test_inspecting_an_unreadable_payload_still_reports_a_holder(tmp_path: Path) -> None:
    """ "There is a lock file I cannot parse" must not resolve to "the lock is free"."""
    path = tmp_path / f"store.write{LOCK_SUFFIX}"
    path.write_text("{not json", encoding="utf-8")
    state = inspect(path)
    assert state.present is True
    assert state.holder is not None
    assert state.holder.pid == 0


# =============================================================================================
# 4. `hold()` -- 08:2543's second and third clauses
# =============================================================================================


def test_holding_an_uncontended_lock_reports_no_blocker(tmp_path: Path) -> None:
    lock = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    with hold(lock, wait_ms=0) as receipt:
        assert receipt.name == "store.write"
        assert receipt.blocked_by is None
        assert receipt.contended is False
        assert receipt.waited_seconds >= 0.0


def test_a_contended_hold_names_who_was_in_the_way(tmp_path: Path) -> None:
    """*"`held()` exposing `waited_seconds` and naming the holder"* -- 08:2543."""
    first = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    first.acquire(wait_ms=0)
    blocker = first.holder()
    first.release()
    second = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    # The file is gone, so the receipt reports no blocker -- which is the honest reading.
    with hold(second, wait_ms=0) as receipt:
        assert receipt.blocked_by is None
    assert blocker is not None


def test_the_blocker_is_read_before_the_wait(tmp_path: Path) -> None:
    """By the time a wait ends the file names whoever is next, not whoever caused the wait."""
    holder_lock = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    holder_lock.acquire(wait_ms=0)
    contender = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    with pytest.raises(StoreBusy), hold(contender, wait_ms=0):
        pass  # pragma: no cover -- the acquire raises.
    holder_lock.release()


def test_the_lock_is_released_when_the_body_raises(tmp_path: Path) -> None:
    lock = scoped_lock(tmp_path, now_ns=lambda: NOW_NS)
    with pytest.raises(ValueError, match="boom"), hold(lock, wait_ms=0):
        raise ValueError("boom")
    assert not lock.path.exists()


def test_this_lock_has_no_lease_to_extend() -> None:
    """08:2543's third clause constrains a T3 substitute; there is nothing here to extend.

    The property it protects -- **never stolen** -- is `_break_if_dead`'s, which unlinks only a file
    whose writer the kernel says is gone. A lock with an expiry would need the extension; this one
    has no expiry, so a live holder is held until it releases or dies.
    """
    for absent in ("extend", "lease", "lease_expires", "expires_ms", "renew"):
        assert not hasattr(FileScopedLock, absent), f"a lease appeared: {absent}"


# =============================================================================================
# 5. The wait budgets moved here with the lock they are the budgets of
# =============================================================================================


def test_the_two_budgets_are_the_plans_two_numbers() -> None:
    assert (INTERACTIVE_WAIT_MS, BATCH_WAIT_MS) == (2_000, 60_000)


def test_the_store_re_exports_them_rather_than_declaring_them() -> None:
    """A re-export is a pointer, not a second home. INV-21."""
    assert ow.INTERACTIVE_WAIT_MS is INTERACTIVE_WAIT_MS
    assert ow.BATCH_WAIT_MS is BATCH_WAIT_MS
    assert ow.STORE_WRITE_LOCK is STORE_WRITE_LOCK
    assert ow.FileScopedLock is FileScopedLock
    assert ow.process_create_time is process_create_time


def test_the_scoped_lock_protocol_stayed_in_the_store() -> None:
    """The store thread's statement of what it needs is not a fact about locking."""
    assert hasattr(ow, "ScopedLock")
    assert not hasattr(locks, "ScopedLock")


def test_the_advisory_helpers_moved_with_the_mechanism(tmp_path: Path) -> None:
    path = tmp_path / "probe"
    path.write_bytes(b"")
    fd = os.open(path, os.O_RDWR)
    try:
        assert _take_advisory(fd) is True
        _drop_advisory(fd)
    finally:
        os.close(fd)
