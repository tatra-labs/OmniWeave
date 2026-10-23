"""`ow doctor` rows that read a corpus's store from outside it. D959.

15-observability.md:1514-1540 is the table. D-24 is the first row here:

- **D-24** (15:1537): *"a live `store.write` lock: prints holder host, pid,
  `process_create_time`, age"*, severity `info`. For each declared corpus, the lock file beside
  its store (`locks.store_write_lock`'s path, D560) is asked through `locks.inspect()`, which takes
  nothing and breaks nothing. `LockState`'s docstring names this row as the reason it has three
  states: no lock, a lock whose writer is alive, and a lock whose writer is gone. The third
  is printed as stale, because a stale file reported as held sends an operator looking for a
  process that does not exist, and the next writer breaks it.

An info row is never a warning or a failure, so every finding here is `ok`. 15:1537's *"exit 7
if a write verb was requested"* belongs to a write verb, and `ow doctor` is not one. Nothing here
opens a store: a doctor must answer when the store is locked, and that is when this row matters.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave.sdk.reports import DoctorFinding

if TYPE_CHECKING:
    from omniweave_core.config import Config
    from omniweave_core.locks import LockHolder

__all__ = ["STORE", "UNREADABLE", "check_write_locks"]

STORE: Final[tuple[str, ...]] = ("D-24",)
"""The rows this module checks."""

UNREADABLE: Final = "a holder that could not be read"
"""A lock file whose payload does not parse: `_read_holder` reads it as pid 0, never as no
holder, because a lock file nobody can read must not resolve to "the lock is free"."""


def check_write_locks(config: Config, *, cwd: Path, now_ns: int) -> tuple[DoctorFinding, ...]:
    """D-24 (15:1537), once per declared corpus. `now_ns` is the wall clock a holder's age is
    read against, which the verb reads once from `SystemClock` and a test hands in."""
    from omniweave_core.locks import STORE_WRITE_LOCK, inspect, lock_path  # noqa: PLC0415

    from omniweave.surface.serve import stores  # noqa: PLC0415 -- the doctor verb pays
    from omniweave.surface.startup import corpora  # noqa: PLC0415

    declared = corpora(config)
    if not declared:
        return (
            DoctorFinding(
                "D-24", "no corpus is declared, so no store.write lock can be held", "ok", ""
            ),
        )
    findings: list[DoctorFinding] = []
    for name, path in stores(config, declared, cwd=cwd).items():
        store = Path(path)
        state = inspect(lock_path(store.parent, STORE_WRITE_LOCK, store.name))
        holder = state.holder
        who = _who(holder, now_ns) if holder and holder.pid else UNREADABLE
        if not state.present:
            detail = "no store.write lock is held"
        elif state.stale:
            detail = (
                f"a stale store.write lock from {who}: that process is gone, so the next writer "
                "breaks it"
            )
        elif state.live:
            detail = f"store.write is held by {who}"
        else:
            detail = (
                f"a store.write lock from {who}; this platform cannot tell whether it is still held"
            )
        findings.append(DoctorFinding("D-24", f"corpus {name!r}: {detail}", "ok", ""))
    return tuple(findings)


def _who(holder: LockHolder, now_ns: int) -> str:
    """15:1537's four fields: host, pid, `process_create_time` (and what read it), and age."""
    return (
        f"host {holder.host}, pid {holder.pid}, process_create_time "
        f"{holder.process_create_time} ({holder.process_create_time_source}), "
        f"acquired {holder.age_s(now_ns):.0f} s ago"
    )
