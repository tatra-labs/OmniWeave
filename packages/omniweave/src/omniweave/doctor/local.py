"""Four `ow doctor` rows that read only this machine and the configuration. D953.

15-observability.md:1514-1540 is the table. Each row here asks something no store or driver has
to answer, so each runs on every `ow doctor`, and each failing row names the command that clears
it (15:1510):

- **D-01**: `sqlite3.sqlite_version_info >= MIN_SQLITE`. The store's DDL needs 3.42's
  `unixepoch('subsec')` (`limits.MIN_SQLITE`), so an older library fails, with the row's fix.
- **D-05**: every `[corpora]` path resolves, and `[serve] default_corpus` names an entry.
  `startup.declared_corpus()` already raises `OW-A-002` for the second, so its refusal is the
  finding. *Resolves* is read as: a corpus's store path is not a directory, and its nearest
  existing ancestor is one, so the first `ow add` can create it; and its source root exists.
  A store not written yet is not a failure: 10:540's server starts before the first `ow add`.
- **D-11**: free space on the cache root is at least `[cache] min_free_bytes`, and on the output
  root at least 1 GiB, each read on the volume of the root's nearest existing ancestor. A
  warning, and only a warning prints the free bytes: an ok line that carried them would
  differ between two runs a moment apart. 15:1524's fix is `ow cache prune`, which is
  rostered and not built, so the fix names the shortfall and the volume instead of a command
  that would be refused.
- **D-15**: `[observe] ndjson_path`'s directory is writable, and on POSIX mode 0700. A
  warning: a run that cannot write its shard degrades to the console and continues (15:402-404).
  A project with no `ndjson` sink, or no project, writes no shard, and that is reported as fine.

Every path is resolved as a run resolves it (`surface.ingest.root_of`, `surface.serve.stores`,
`run.trace.shard_of`), so the doctor and the run cannot disagree about where a root is. Nothing
here writes, and the two machine readings are arguments, so a test hands in a version or a
volume's free bytes.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.limits import MIN_SQLITE

from omniweave.sdk.reports import DoctorFinding

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from omniweave_core.config import Config

__all__ = [
    "LOCAL",
    "OUTPUT_MIN_FREE_BYTES",
    "check_corpora",
    "check_events_dir",
    "check_free_space",
    "check_sqlite",
]

LOCAL: Final[tuple[str, ...]] = ("D-01", "D-05", "D-11", "D-15")
"""The rows this module checks."""

OUTPUT_MIN_FREE_BYTES: Final[int] = 1 << 30
"""15:1524's *"on `output` >= 1 GiB"*. No key carries it; the cache's floor is `[cache]
min_free_bytes`."""

_PRIVATE: Final[int] = 0o077


def check_sqlite(version: tuple[int, ...] | None = None) -> DoctorFinding:
    """D-01 (15:1514), through the store's own refusal, `refuse_old_sqlite()`.

    INV-17 keeps `sqlite3` inside `omniweave_core.store`, and the store already refuses below
    `MIN_SQLITE` at open with `OW_SQLITE_TOO_OLD` and the row's fix. So the row asks that refusal
    and reports it, and the floor and the fix stay in one place. `version` stands in for the
    linked library's in a test.
    """
    from omniweave_core.errors import ConfigError  # noqa: PLC0415
    from omniweave_core.store import sqlite as ow  # noqa: PLC0415 -- the doctor verb pays

    floor = ".".join(map(str, MIN_SQLITE))
    try:
        ow.refuse_old_sqlite(version)
    except ConfigError as error:
        return DoctorFinding("D-01", f"{error.code()}: {error}", "error", error.fix)
    return DoctorFinding("D-01", f"the linked SQLite meets the {floor} floor", "ok", "")


def check_corpora(config: Config, *, cwd: Path) -> tuple[DoctorFinding, ...]:
    """D-05 (15:1518): the default corpus names an entry, and each corpus's paths resolve."""
    from omniweave_core.errors import UsageError  # noqa: PLC0415

    from omniweave.surface.serve import stores  # noqa: PLC0415 -- the doctor verb pays
    from omniweave.surface.startup import corpora, declared_corpus  # noqa: PLC0415

    findings: list[DoctorFinding] = []
    try:
        name, why = declared_corpus(config)
    except UsageError as error:
        findings.append(DoctorFinding("D-05", f"{error.code()}: {error}", "error", error.fix))
    else:
        detail = why if name is not None else f"no default corpus: {why}"
        findings.append(DoctorFinding("D-05", detail, "ok", ""))
    declared = corpora(config)
    paths, sources = (
        stores(config, declared, cwd=cwd),
        stores(config, declared, cwd=cwd, field="source"),
    )
    for one in declared:
        store, source = Path(paths[one]), Path(sources[one])
        if store.is_dir():
            findings.append(
                DoctorFinding(
                    "D-05",
                    f"corpus {one!r}: its store path {store.as_posix()} is a directory, and a "
                    "store is a file",
                    "error",
                    f"set [corpora.{one}] path to a file such as .omniweave/{one}.owstore",
                )
            )
            continue
        ancestor = _nearest(store.parent)
        if not ancestor.is_dir():
            findings.append(
                DoctorFinding(
                    "D-05",
                    f"corpus {one!r}: its store path {store.as_posix()} sits under "
                    f"{ancestor.as_posix()}, which is a file, so no store can be created there",
                    "error",
                    f"set [corpora.{one}] path to a location under a directory",
                )
            )
            continue
        if not source.is_dir():
            findings.append(
                DoctorFinding(
                    "D-05",
                    f"corpus {one!r}: its source root {source.as_posix()} does not exist",
                    "error",
                    f"create {source.as_posix()}, or set [corpora.{one}] source",
                )
            )
            continue
        state = "written" if store.is_file() else "not written yet; the first ow add creates it"
        findings.append(
            DoctorFinding("D-05", f"corpus {one!r}: store {store.as_posix()} ({state})", "ok", "")
        )
    return tuple(findings)


def check_free_space(
    config: Config, *, cwd: Path, free: Callable[[Path], int] | None = None
) -> tuple[DoctorFinding, ...]:
    """D-11 (15:1524). `free` reads a volume's free bytes; it defaults to `shutil.disk_usage`."""
    from omniweave.surface.ingest import root_of  # noqa: PLC0415 -- the doctor verb pays

    read = free if free is not None else (lambda path: shutil.disk_usage(path).free)
    floor = config.get("cache.min_free_bytes")
    floors = (
        ("cache", root_of(config, "roots.cache", cwd), int(floor) if isinstance(floor, int) else 0),
        ("output", root_of(config, "roots.output", cwd), OUTPUT_MIN_FREE_BYTES),
    )
    findings: list[DoctorFinding] = []
    for label, root, need in floors:
        volume = _nearest(root)
        have = read(volume)
        if have >= need:
            findings.append(
                DoctorFinding(
                    "D-11",
                    f"{label} root {root.as_posix()}: at least the {need} bytes it needs are free",
                    "ok",
                    "",
                )
            )
            continue
        findings.append(
            DoctorFinding(
                "D-11",
                f"{label} root {root.as_posix()}: {have} bytes free on its volume, under the "
                f"{need} it needs",
                "warning",
                f"free {need - have} bytes on the volume holding {volume.as_posix()}",
            )
        )
    return tuple(findings)


def check_events_dir(
    config: Config, *, env: Mapping[str, str], posix: bool | None = None
) -> DoctorFinding:
    """D-15 (15:1528): the event shards' directory is writable, and 0700 on POSIX."""
    from omniweave.run.trace import shard_of  # noqa: PLC0415 -- the doctor verb pays

    probe = shard_of(config, "r_0", env=env)
    if probe is None:
        return DoctorFinding(
            "D-15", "no event shard is written here: no project, or no ndjson sink", "ok", ""
        )
    directory = probe.parent
    target = directory if directory.is_dir() else _nearest(directory)
    if not os.access(target, os.W_OK):
        return DoctorFinding(
            "D-15",
            f"{target.as_posix()} is not writable, so a run's events degrade to the console",
            "warning",
            f"make {target.as_posix()} writable by this user",
        )
    on_posix = (sys.platform != "win32") if posix is None else posix
    if on_posix and directory.is_dir() and stat.S_IMODE(directory.stat().st_mode) & _PRIVATE:
        return DoctorFinding(
            "D-15",
            f"{directory.as_posix()} is readable by others; 15:1465 makes it mode 0700",
            "warning",
            f"chmod 700 {directory.as_posix()}",
        )
    state = "exists" if directory.is_dir() else "is created by the first run"
    return DoctorFinding("D-15", f"{directory.as_posix()} is writable and {state}", "ok", "")


def _nearest(path: Path) -> Path:
    """`path`, or its nearest ancestor that exists."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path
