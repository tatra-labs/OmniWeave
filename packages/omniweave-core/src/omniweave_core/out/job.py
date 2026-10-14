"""The JobDir layout: `ILFile` (**D737**) and `ILBundle` (**D744**).

09-generation.md section 3.7 prints both here. `ILFile` is one row a file under `il/`, and
`il_digest` (09 section 4.5) is a function of those rows and of nothing else. `ILBundle` is the
generation: `il.toml`'s roster checked against the filesystem, every unit parsed exactly once in
`ord` order, and both digests computed over that one parse (09 section 11.3).

## Rulings (the ledger's D737)

8. **`il/` is read flat, and a dot-file is not IL.** `ILFile.name` is a basename and the digest
   sorts by basename, so a subdirectory contributes nothing. A name beginning with `.` is skipped:
   `il/.stamp.lock` (09 section 4.3) is `ow out stamp`'s transient lock, and a digest that moved
   while a stamper held it would make every concurrent check stale.
9. **An empty file is readable.** 09's `byte_len` is *"0 iff sha256 == unreadable"*, which an empty
   `il.toml` contradicts: it has a digest and no bytes. Only the unreadable direction holds.
10. **An unreadable file's error names the error and not the path**: the exception's class and its
    `strerror`. The digest is basename-sorted so moving the job directory does not change it, and a
    report quoting an absolute path would change with the directory all the same.

## Rulings (the ledger's D744)

11. **`ILBundle.load()` takes the carrier and the table.** 09 prints `load(il_dir)`, and says the
    load parses each unit (for `nsig`) and derives `il_digest_rt`'s exclusion set from
    `constructs.toml`: neither is reachable from a path alone.
12. **`il.toml` is asserted as it loads**, `OW_TARGET_IL_TOML_INVALID` (`OW-T-011`): its schema,
    `il` and a `sha256:` `constructs_digest`, `origin` absent or `"project"`, no unknown key, each
    `[[unit]]` an `OutUnit` with a basename `file`, `ord` 1..n, and no repeated id or file.
13. **The bundle-against-filesystem difference names every id both ways**,
    `OW_TARGET_ROSTER_MISMATCH` (`OW-T-507`): a row with no file and a file with no row.
    `il.toml` and `template.nsig` are the bundle's own files, not units.
14. **`il_digest_rt` elides the selectors of the rows whose `round_trip` is not `exact`, except a
    normalize row's.** A normalize row inherits its native row's selector, so eliding it would
    elide the exact row's payload too, and a semantic mutation of that row could no longer move
    `il_digest_rt`: R5's third clause would pass vacuously.
15. **A unit the carrier refuses still loads**, with no `nsig` and no addresses, and contributes
    64 zeros to `il_digest_rt` (`UNPARSED_HEX`). Order 0 reports the refusal; a load error
    would hide every other unit's findings. A recovering read with problems counts as refused.
16. **`text()` and `data()` re-read from `root`, `take(N+1)`-then-check**, so no bundle holds
    bytes (09 section 3.7 decision 1). Undecodable text raises `CarrierParseError`, which is
    order 0's to record, and a file past `MAX_IL_FILE_BYTES` raises `ResourceLimit`.

## Rulings (the ledger's D756)

17. **The one parse also reads each unit's `ow:manual` regions** (`out.manual`). They are kept
    on `ILBundle.manual` for the gate, and the first region with a known reason becomes
    `OutUnit.manual_reason`, which is what `classify_and_assert()` reads. A unit the carrier
    refuses has no regions, because a unit nobody parsed asserts nothing.
"""

from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Final, Never

from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.limits import MAX_IL_FILE_BYTES
from omniweave_core.out.carrier import CarrierDoc, CarrierParseError, ParseError
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.constructs import ConstructTable, Disposition, RoundTrip
from omniweave_core.out.manual import ManualRegion, manual_regions
from omniweave_core.out.plan import OutUnit

__all__ = [
    "IL_SCHEMA",
    "UNPARSED_HEX",
    "UNREADABLE",
    "ILBundle",
    "ILFile",
    "elided",
    "read_il_files",
]

UNREADABLE: Final = "unreadable"
"""What an unreadable file contributes to `il_digest` in place of its hex (09 section 4.5)."""

_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_BUFFER: Final = 1 << 20
"""`il_digest` streams (09 section 14.2): a fixed buffer, so an 8 GiB bundle digests in constant
memory."""


@dataclass(frozen=True, slots=True)
class ILFile:
    """One file under `il/`, `il.toml` included (09 section 3.7)."""

    name: str
    """A basename, never a path."""
    sha256: str
    """64 lower-case hex, or `UNREADABLE`."""
    byte_len: int
    error: str | None = None
    """Non-`None` iff `sha256 == UNREADABLE`."""

    def __post_init__(self) -> None:
        if not self.name or self.name in {".", ".."} or "/" in self.name or "\\" in self.name:
            raise ValueError(f"{self.name!r} is not a basename under il/")
        unreadable = self.sha256 == UNREADABLE
        if not unreadable and _HEX64.fullmatch(self.sha256) is None:
            raise ValueError(
                f"{self.name}: {self.sha256!r} is neither 64 lower-case hex nor {UNREADABLE!r}"
            )
        if unreadable != (self.error is not None):
            raise ValueError(f"{self.name}: an error is recorded iff the file is unreadable")
        if self.byte_len < 0 or (unreadable and self.byte_len):
            raise ValueError(f"{self.name}: byte_len {self.byte_len} (ruling 9)")


def read_il_files(root: Path) -> tuple[ILFile, ...]:
    """Every file directly under `root`, sorted by basename (rulings 8-10)."""
    names = sorted(
        entry.name
        for entry in os.scandir(root)
        if not entry.name.startswith(".") and not entry.is_dir()
    )
    return tuple(_read(root / name) for name in names)


def _read(path: Path) -> ILFile:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_BUFFER):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        return ILFile(
            path.name, UNREADABLE, 0, f"{type(exc).__name__}: {exc.strerror or 'unreadable'}"
        )
    return ILFile(path.name, digest.hexdigest(), size)


# ---------------------------------------------------------------------------
# ILBundle (09 sections 3.2, 3.7 and 11.3), D744
# ---------------------------------------------------------------------------

IL_SCHEMA: Final = "omniweave.out-il/1"
IL_TOML: Final = "il.toml"
TEMPLATE_NSIG: Final = "template.nsig"
"""09 section 4.1's stamped template nsig set: one hex value a line, sorted."""
_TOP_KEYS: Final = frozenset({"schema", "il", "constructs_digest", "origin", "unit"})
_UNIT_KEYS: Final = frozenset({"id", "ord", "file", "anchor"})
_NSIG_LINE: Final = re.compile(r"[0-9a-f]{8}")


@dataclass(frozen=True, slots=True)
class ILBundle:
    """One generation's IL: `il.toml`'s roster, every file's row, and both bundle digests."""

    schema: str
    il: str
    root: str
    """The absolute `<job_dir>/il/`: the only path in the type."""
    constructs_digest: str
    units: tuple[OutUnit, ...]
    files: tuple[ILFile, ...]
    il_digest: str
    il_digest_rt: str
    els: Mapping[str, frozenset[str]]
    origin: str | None = None
    """`"project"` when the bundle came out of `project()` (09 section 4.1's `IMPORTED`)."""
    template_nsigs: frozenset[str] = frozenset()
    manual: Mapping[str, tuple[ManualRegion, ...]] = MappingProxyType({})
    """D756: unit -> its `ow:manual` regions, in document order (09 section 9)."""

    @classmethod
    def load(
        cls,
        il_dir: str | Path,
        *,
        carrier: Callable[[str, str], CarrierDoc],
        constructs: ConstructTable,
    ) -> ILBundle:
        """Rulings 11-16: one parse a unit in `ord` order, each tree dropped as the next starts."""
        from omniweave_core.out.report import il_digest  # noqa: PLC0415 -- report imports ILFile.

        root = Path(il_dir)
        files = read_il_files(root)
        roster = _roster(root / IL_TOML)
        _three_ways(roster.units, files)
        by_name = {f.name: f for f in files}
        units: list[OutUnit] = []
        rt: dict[str, ILFile] = dict(by_name)
        els: dict[str, frozenset[str]] = {}
        manual: dict[str, tuple[ManualRegion, ...]] = {}
        for unit in roster.units:
            name = unit.il_path.removeprefix("il/")
            file = by_name[name]
            doc = None if file.sha256 == UNREADABLE else _parse(root, unit, carrier)
            if doc is None:
                units.append(unit)
                if file.sha256 != UNREADABLE:
                    rt[name] = ILFile(name, UNPARSED_HEX, file.byte_len)
                continue
            els[unit.id] = frozenset(n.el for n in doc.select("@data-ow-el") if n.el)
            regions = manual_regions(unit.id, doc)
            if regions:
                manual[unit.id] = regions
            reason = next((r.reason for r in regions if r.reason is not None), None)
            units.append(replace(unit, nsig=doc.root().nsig, manual_reason=reason))
            rt[name] = ILFile(name, _rt_hex(doc, constructs), file.byte_len)
        return cls(
            schema=IL_SCHEMA,
            il=roster.il,
            root=str(root.resolve()),
            constructs_digest=roster.constructs_digest,
            units=tuple(units),
            files=files,
            il_digest=il_digest(files),
            il_digest_rt=il_digest(tuple(rt.values())),
            els=MappingProxyType(els),
            origin=roster.origin,
            template_nsigs=_template(root / TEMPLATE_NSIG),
            manual=MappingProxyType(manual),
        )

    def data(self, il_path: str) -> bytes:
        """The bytes `il_digest` hashed, read again, bounded by `MAX_IL_FILE_BYTES` (ruling 16)."""
        return _bounded(Path(self.root) / _name(il_path))

    def text(self, il_path: str) -> str:
        """`OutUnit.il_path`'s text, UTF-8 strict. Undecodable bytes are order 0's to report."""
        try:
            return self.data(il_path).decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"not UTF-8: {exc.reason} at byte {exc.start}"
            raise CarrierParseError(ParseError(f"{il_path}:1:1", msg)) from None


UNPARSED_HEX: Final = "0" * 64
"""Ruling 15: a parse failure is not a digest. A refused unit contributes 64 zeros to
`il_digest_rt`, a value no sha256 is assumed to take, so the bundle still has an `il_digest_rt` and
the refusal is order 0's finding rather than a load error."""


@dataclass(frozen=True, slots=True)
class _Roster:
    il: str
    constructs_digest: str
    origin: str | None
    units: tuple[OutUnit, ...]


def _roster(path: Path) -> _Roster:
    """`il.toml`, asserted (ruling 12)."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _invalid(f"{IL_TOML} does not load: {exc}")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        _invalid(f"{IL_TOML}: unknown key(s) {unknown}")
    if raw.get("schema") != IL_SCHEMA:
        _invalid(f"{IL_TOML}: schema {raw.get('schema')!r} is not {IL_SCHEMA!r}")
    il, digest, origin = raw.get("il"), raw.get("constructs_digest"), raw.get("origin")
    if (
        not isinstance(il, str)
        or not il
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
    ):
        _invalid(f"{IL_TOML}: il and constructs_digest are required")
    if origin is not None and origin != "project":
        _invalid(f'{IL_TOML}: origin is "project" or absent')
    rows = raw.get("unit", [])
    if not isinstance(rows, list):
        _invalid(f"{IL_TOML}: [[unit]] is an array of tables")
    units = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) - _UNIT_KEYS
            or not {"id", "ord", "file"} <= set(row)
        ):
            _invalid(f"{IL_TOML}: a [[unit]] is id, ord, file and an optional anchor: {row!r}")
        file = str(row["file"])
        if file != _name(file) or file in {IL_TOML, TEMPLATE_NSIG}:
            _invalid(
                f"{IL_TOML}: unit {row['id']!r} file {file!r} is not a unit basename under il/"
            )
        try:
            units.append(
                OutUnit(
                    id=str(row["id"]),
                    ord=row["ord"],
                    il_path="il/" + file,
                    anchor=str(row.get("anchor", "")),
                )
            )
        except (ValueError, TypeError) as exc:
            _invalid(f"{IL_TOML}: {exc}")
    ords = [u.ord for u in units]
    if ords != list(range(1, len(units) + 1)):
        _invalid(f"{IL_TOML}: ords {ords} are not 1..{len(units)} in roster order")
    if len({u.id for u in units}) != len(units) or len({u.il_path for u in units}) != len(units):
        _invalid(f"{IL_TOML}: a unit id or file repeats")
    return _Roster(il, digest, origin, tuple(units))


def _three_ways(units: tuple[OutUnit, ...], files: tuple[ILFile, ...]) -> None:
    """Ruling 13: `il.toml` against the filesystem, both directions, every id named."""
    named = {u.il_path.removeprefix("il/"): u.id for u in units}
    present = {f.name for f in files} - {IL_TOML, TEMPLATE_NSIG}
    missing = sorted(named[n] for n in set(named) - present)
    orphans = sorted(present - set(named))
    if missing or orphans:
        raise TargetError(
            f"il/ disagrees with {IL_TOML}: units with no file {missing}, "
            f"files with no unit {orphans}",
            symbol="OW_TARGET_ROSTER_MISMATCH",
            fix="ow explain OW-T-507   # add the [[unit]] row or the file, or remove the leftover",
        )


def _parse(
    root: Path, unit: OutUnit, carrier: Callable[[str, str], CarrierDoc]
) -> CarrierDoc | None:
    """Ruling 15: a unit the carrier refuses is order 0's finding, not the load's error."""
    try:
        text = _bounded(root / _name(unit.il_path)).decode("utf-8")
        doc = carrier(unit.il_path, text)
    except (CarrierParseError, UnicodeDecodeError):
        return None
    return None if doc.problems else doc


def _rt_hex(doc: CarrierDoc, constructs: ConstructTable) -> str:
    """09 section 11.3: the canonical root with every non-exact construct's payload elided."""
    from omniweave_core.out.report import canonical_subtree  # noqa: PLC0415 -- a cycle.

    root = doc.root()
    if not isinstance(root, Node):
        raise TypeError(f"{root!r} is not a carrier node")
    return hashlib.sha256(canonical_subtree(root, elide=elided(constructs))).hexdigest()


def elided(constructs: ConstructTable) -> tuple[str, ...]:
    """Ruling 14: the selectors whose payload `il_digest_rt` leaves out, derived from the table."""
    return tuple(
        row.selector
        for row in constructs.rows
        if row.round_trip is not RoundTrip.EXACT and row.disposition is not Disposition.NORMALIZE
    )


def _template(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not all(_NSIG_LINE.fullmatch(line) for line in lines):
        _invalid(f"{TEMPLATE_NSIG} holds a line that is not 8 hex")
    return frozenset(lines)


def _bounded(path: Path) -> bytes:
    """`take(N+1)`-then-check at the read boundary (09 section 14.3)."""
    with path.open("rb") as handle:
        data = handle.read(MAX_IL_FILE_BYTES + 1)
    if len(data) > MAX_IL_FILE_BYTES:
        raise ResourceLimit(
            f"{path.name} is above MAX_IL_FILE_BYTES ({MAX_IL_FILE_BYTES})",
            limit="MAX_IL_FILE_BYTES",
            fix="split the unit; widening the ceiling is a fork",
        )
    return data


def _name(il_path: str) -> str:
    return il_path.removeprefix("il/")


def _invalid(msg: str) -> Never:
    raise TargetError(msg, symbol="OW_TARGET_IL_TOML_INVALID", fix="ow explain OW-T-011")
