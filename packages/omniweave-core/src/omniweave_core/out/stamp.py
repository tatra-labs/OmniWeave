"""`ow out stamp`: `data-ow-el` minted once on every citable, text-bearing element. **D767.**

09 section 4.3's table: `ow out stamp` reads every IL file under `il/` and writes "`data-ow-el` on
every citable and text-bearing element **that has none**; never renumbers an existing one (OUT21)".
It is idempotent, and exits 0, or 70 "if a reparse fails, having written nothing". It writes
"through the same transactional splice as the marker applier", and it takes "an exclusive
`il/.stamp.lock` (O_CREAT|O_EXCL, holding pid and start time, stale after 300 s) because the
per-unit `e` counter is `max(existing ordinal) + 1`".

## Rulings

1. **An element is stamped when it has no `data-ow-el` and either bears text or carries a cite.** It
   bears text when the carrier's `visible_text()` of it is not empty. Both carriers collapse a
   whitespace-only run to nothing, and the rule takes in the unit root and every container of text.
   It carries a cite when it has `data-ow-cite`, whether or not it has text. An element whose tag
   the table's `ignore` names is never stamped.
2. **The address is `<unit>/e<N>`.** N counts up from the largest ordinal the unit already uses,
   in document order. An existing address is never renumbered or repaired: a duplicate is
   `OW-T-405`'s to report at check time, and an address naming another unit is left as written.
3. **The attribute goes just before the start tag's `>` or `/>`**, through `CarrierDoc.splice()`,
   which reparses strictly. A unit whose read had to recover is never written.
4. **All units or none.** Every unit's new text is computed and reparsed before any file is
   written. A unit that does not reparse is `OW_TARGET_STAMP_REFUSED` (`OW-T-522`), and nothing is
   written. Each file is then written to a sibling and renamed over, so a crash leaves each file
   whole: the sibling is a dot-file, which `ILBundle` never counts as a unit.
5. **The lock is `il/.stamp.lock`**, created exclusively and holding the pid and the start time
   from the injected clock. A lock younger than 300 s is `OW_TARGET_STAMP_LOCKED` (`OW-T-521`).
   An older one is stale: it is replaced, and the stamp says so. The lock is removed when the
   stamp ends, however it ends. `ILFile` skips dot-files, so the lock never moves `il_digest`.
6. **The roster is `il.toml`'s**, loaded by `ILBundle.load()`, which already refuses a row with no
   file and a file with no row. A stamp of a bundle that does not load writes nothing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Never

from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import CarrierParseError, ParseError, Splice
from omniweave_core.out.carrier.tree import Doc, Node
from omniweave_core.out.job import ILBundle

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from omniweave_core.clock import Clock
    from omniweave_core.out.carrier import CarrierDoc
    from omniweave_core.out.constructs import ConstructTable
    from omniweave_core.out.plan import OutUnit

__all__ = ["LOCK_NAME", "STALE_LOCK_NS", "Stamped", "stamp"]

LOCK_NAME: Final = ".stamp.lock"
STALE_LOCK_NS: Final = 300 * 1_000_000_000
"""09 section 4.3: "stale after 300 s"."""

_EL: Final = "data-ow-el"
_CITE: Final = "data-ow-cite"
_ADDRESS: Final = re.compile(r"(u\d{2,})/e(\d+)")
_FIX: Final = "ow out stamp --job <job_dir>"


@dataclass(frozen=True, slots=True)
class Stamped:
    """What a stamp minted: each unit's new addresses in document order, and what it replaced."""

    minted: Mapping[str, tuple[str, ...]]
    written: tuple[str, ...]
    """The `il/` basenames whose bytes changed, in roster order."""
    stale_lock: bool = False
    """A lock older than 300 s was found and replaced (ruling 5)."""


def stamp(
    job_dir: Path,
    *,
    carrier: Callable[[str, str], CarrierDoc],
    constructs: ConstructTable,
    clock: Clock,
) -> Stamped:
    """Rulings 1-6 over `<job_dir>/il/`."""
    il = job_dir / "il"
    stale = _lock(il / LOCK_NAME, clock)
    try:
        bundle = ILBundle.load(il, carrier=carrier, constructs=constructs)
        ignored = tuple(constructs.ignore)
        planned: list[tuple[OutUnit, str, tuple[str, ...]]] = []
        for unit in bundle.units:
            try:
                doc = carrier(unit.il_path, bundle.text(unit.il_path))
            except CarrierParseError as exc:
                _refused(unit, exc.error)
            edits, minted = _edits(doc, unit.id, ignored)
            if not edits:
                continue
            written = doc.splice(edits)
            if isinstance(written, ParseError):
                _refused(unit, written)
            planned.append((unit, written, minted))
        for unit, written, _ in planned:
            path = il / unit.il_path.removeprefix("il/")
            staged = path.with_name(f".{path.name}.stamp")
            staged.write_bytes(written.encode("utf-8"))
            staged.replace(path)
        return Stamped(
            minted=MappingProxyType({unit.id: minted for unit, _, minted in planned}),
            written=tuple(unit.il_path.removeprefix("il/") for unit, _, _ in planned),
            stale_lock=stale,
        )
    finally:
        (il / LOCK_NAME).unlink(missing_ok=True)


def _refused(unit: OutUnit, error: ParseError) -> Never:
    """Ruling 4: a unit that does not read or reparse, and nothing written."""
    raise TargetError(
        f"{unit.il_path}: the unit does not reparse ({error.at}: {error.msg}); nothing was written",
        symbol="OW_TARGET_STAMP_REFUSED",
        fix=f"ow out check --stage unit --unit {unit.id}",
    )


def _edits(
    doc: CarrierDoc, unit: str, ignored: tuple[str, ...]
) -> tuple[list[Splice], tuple[str, ...]]:
    """Rulings 1-3: the attribute insertions for one unit, and the addresses they mint."""
    if not isinstance(doc, Doc):
        raise TypeError(f"{doc!r} is not a carrier document this stamp can splice")
    skip = {id(n) for selector in ignored for n in doc.select(selector)}
    nodes = list(doc.nodes())
    used = [
        int(match.group(2))
        for n in nodes
        if (match := _ADDRESS.fullmatch(n.attr(_EL) or "")) and match.group(1) == unit
    ]
    following = max(used, default=0)
    edits: list[Splice] = []
    minted: list[str] = []
    data = doc.source().encode("utf-8")
    for node in nodes:
        if node.attr(_EL) is not None or id(node) in skip:
            continue
        if not (node.attr(_CITE) is not None or doc.visible_text(node)):
            continue
        following += 1
        address = f"{unit}/e{following}"
        at = _before_close(data, node)
        edits.append(Splice(at, at, f' {_EL}="{address}"'))
        minted.append(address)
    return edits, tuple(minted)


def _before_close(data: bytes, node: Node) -> int:
    """Ruling 3: the byte offset of the start tag's `>`, or of the `/` of its `/>`."""
    close = node.start_end - 1
    return close - 1 if data[close - 1 : close] == b"/" else close


def _lock(path: Path, clock: Clock) -> bool:
    """Ruling 5: take the lock, replacing a stale one. True when one was replaced."""
    now = clock.wall_ns()
    stale = False
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            started = _started(path)
            if started is not None and now - started < STALE_LOCK_NS:
                raise TargetError(
                    f"{path.name} is held since {started} ns (pid {_pid(path)}); two stampers "
                    "would mint one address twice",
                    symbol="OW_TARGET_STAMP_LOCKED",
                    fix="wait for the other `ow out stamp`, or delete the lock if no stamp runs",
                ) from None
            path.unlink(missing_ok=True)
            stale = True
            continue
        try:
            os.write(handle, f"{os.getpid()} {now}\n".encode("ascii"))
        finally:
            os.close(handle)
        return stale
    raise TargetError(
        f"{path.name} could not be taken",
        symbol="OW_TARGET_STAMP_LOCKED",
        fix="wait for the other `ow out stamp`, or delete the lock if no stamp runs",
    )


def _started(path: Path) -> int | None:
    """The start time a lock holds, or `None` for one nobody can read (treated as stale)."""
    try:
        fields = path.read_text(encoding="ascii").split()
        return int(fields[1])
    except (OSError, UnicodeDecodeError, IndexError, ValueError):
        return None


def _pid(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").split()[0]
    except (OSError, UnicodeDecodeError, IndexError):
        return "unknown"
