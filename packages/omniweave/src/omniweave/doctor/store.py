"""`ow doctor` rows that read a corpus's store from outside it. D959, D969.

15-observability.md:1514-1540 is the table. D-23 (D969, `check_abandoned`) opens each store
read-only, which perturbs nothing and answers while another process writes; D-24 opens none.
D-24 is the first row here:

- **D-24** (15:1537): *"a live `store.write` lock: prints holder host, pid,
  `process_create_time`, age"*, severity `info`. For each declared corpus, the lock file beside
  its store (`locks.store_write_lock`'s path, D560) is asked through `locks.inspect()`, which takes
  nothing and breaks nothing. `LockState`'s docstring names this row as the reason it has three
  states: no lock, a lock whose writer is alive, and a lock whose writer is gone. The third
  is printed as stale, because a stale file reported as held sends an operator looking for a
  process that does not exist, and the next writer breaks it.

An info row is never a warning or a failure, so every D-24 finding is `ok`. 15:1537's *"exit 7
if a write verb was requested"* belongs to a write verb, and `ow doctor` is not one. D-24 opens
no store: a doctor must answer when the store is locked, and that is when this row matters.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave.sdk.reports import DoctorFinding

if TYPE_CHECKING:
    from collections.abc import Callable

    from omniweave_core.config import Config
    from omniweave_core.locks import LockHolder

__all__ = ["STORE", "UNREADABLE", "check_abandoned", "check_write_locks"]

STORE: Final[tuple[str, ...]] = ("D-23", "D-24")
"""The rows this module checks."""

_NAMED: Final = 3
"""How many abandoned documents D-23 names before it counts the rest."""

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


def check_abandoned(
    config: Config,
    *,
    cwd: Path,
    read: Callable[[Path], list[tuple[str, int, bool]]] | None = None,
) -> tuple[DoctorFinding, ...]:
    """D-23 (15:1536): *"no abandoned `staged_gen` rows outside the current run"*, warn. D969.

    The build stages a generation as pages above `doc.gen` (03:75-80), not as `staged_gen`, so
    the question is `store.doc.ABANDONED_SQL`'s: which documents hold pages above their committed
    generation. They are invisible to every reader. A re-parse of the document sweeps them
    (`store.doc.sweep_abandoned`, 08:480-484), so the fix is to add the file again. 15:1536 names
    `--allow-abandoned-gen`, which is not built: the sweep runs at the re-parse, so a doctor that
    reports first is the inspection the flag was for.

    *"Outside the current run"*: a live `store.write` lock (D-24) means a parse may be in flight,
    and its pages are not abandoned, so that store is reported and not warned about. A store is
    opened read-only, which perturbs nothing and answers while another process writes.
    """
    from omniweave_core.locks import STORE_WRITE_LOCK, inspect, lock_path  # noqa: PLC0415

    from omniweave.surface.serve import stores  # noqa: PLC0415 -- the doctor verb pays
    from omniweave.surface.startup import corpora  # noqa: PLC0415

    declared = corpora(config)
    if not declared:
        return (
            DoctorFinding("D-23", "no corpus is declared, so no generation is staged", "ok", ""),
        )
    findings: list[DoctorFinding] = []
    for name, path in stores(config, declared, cwd=cwd).items():
        store = Path(path)
        if not store.is_file():
            findings.append(DoctorFinding("D-23", f"corpus {name!r}: no store yet", "ok", ""))
            continue
        found = (_abandoned if read is None else read)(store)
        held = [(uri, count) for uri, count, quarantined in found if quarantined]
        rows = [(uri, count) for uri, count, quarantined in found if not quarantined]
        if held:
            detail = (
                f"{sum(count for _u, count in held)} page(s) of {len(held)} quarantined "
                "generation(s), kept for `ow doc diff` (03:1298-1302)"
            )
            findings.append(DoctorFinding("D-23", f"corpus {name!r}: {detail}", "ok", ""))
        if not rows and not held:
            detail = "no page sits above its document's committed generation"
            findings.append(DoctorFinding("D-23", f"corpus {name!r}: {detail}", "ok", ""))
            continue
        if not rows:
            continue
        pages = sum(count for _uri, count in rows)
        named = ", ".join(f"{uri} ({count})" for uri, count in rows[:_NAMED])
        more = f", and {len(rows) - _NAMED} more" if len(rows) > _NAMED else ""
        if inspect(lock_path(store.parent, STORE_WRITE_LOCK, store.name)).live:
            detail = (
                f"{pages} staged page(s) in {len(rows)} document(s), and a run holds store.write, "
                "so they may be a parse in flight"
            )
            findings.append(DoctorFinding("D-23", f"corpus {name!r}: {detail}", "ok", ""))
            continue
        findings.append(
            DoctorFinding(
                "D-23",
                f"corpus {name!r}: {pages} page(s) of an abandoned parse in {len(rows)} "
                f"document(s), invisible to every reader: {named}{more}",
                "warning",
                f"ow add {rows[0][0]}   # a re-parse sweeps the abandoned generation",
            )
        )
    return tuple(findings)


def _abandoned(store: Path) -> list[tuple[str, int, bool]]:
    """`ABANDONED_SQL` over `store`, opened read-only. `read=` stands in for it in a test."""
    from omniweave_core.store.doc import ABANDONED_SQL  # noqa: PLC0415
    from omniweave_core.store.sqlite import connect_readonly  # noqa: PLC0415

    connection = connect_readonly(store)
    try:
        return [
            (str(uri), int(count), bool(held))
            for uri, count, held in connection.execute(ABANDONED_SQL)
        ]
    finally:
        connection.close()


def _who(holder: LockHolder, now_ns: int) -> str:
    """15:1537's four fields: host, pid, `process_create_time` (and what read it), and age."""
    return (
        f"host {holder.host}, pid {holder.pid}, process_create_time "
        f"{holder.process_create_time} ({holder.process_create_time_source}), "
        f"acquired {holder.age_s(now_ns):.0f} s ago"
    )
