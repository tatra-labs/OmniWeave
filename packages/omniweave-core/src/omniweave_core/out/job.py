"""The JobDir layout: `ILFile` (**D737**), `ILBundle` (**D744**), `Job` (**D763**) and
`scaffold()` (**D764**).

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

## Rulings (the ledger's D763)

18. **`job.json` is `Job`: `schema`, `plan`, `traceparent` and `determinism`, and nothing
    else.** 09 Q11 asked for it to be printed with schema `omniweave.out-job/1`. The four
    keys are the ones the plan names inside `job.json`: section 3.7's `Plan`, 15
    section 2.5's S2 `traceparent`, and section 12.3's `determinism.clock_ns`. A Toolchain
    child may read all four. It refuses an unknown `schema` or `plan.schema` before reading
    anything else, echoes `traceparent` into its receipt, and writes every OPC timestamp
    as `clock_ns`. The JobDir's other files (`brief.md`, `il/`, `assets/`, `validation/`,
    `out/`) are named by layout, never by a key.
19. **Closed at every level**, `OW_TARGET_JOB_INVALID` (`OW-T-518`, appended): an
    unknown key, a missing one (a nullable key included, because a producer writes every
    key), a value outside its grammar, or a `Plan` that `Plan` itself refuses. This is
    `[compile]`'s hard-error-on-unknown-key rule, as Q11 asks.
20. **The bytes are fixed:** UTF-8, two-space indent, LF, the cites sorted, and one
    trailing newline. The file is written to a sibling and renamed over, so a reader never
    sees half a job.
21. **The embedded `Brief` must digest to `plan.brief_digest`.** `job.json` holds the frozen
    Brief that 13.3's stage diagram freezes, and `brief.md` is its readable copy. A plan
    whose Brief and digest disagree has no single answer to what was commissioned.

## Rulings (the ledger's D764)

22. **`scaffold()` writes the JobDir 02 section 5 row 2 lists:** `job.json`, `brief.md`,
    `il/il.toml`, `assets/index.json`, `validation/` and `out/`. It stages the whole
    directory beside its final name and renames it in, so a JobDir either exists whole or
    not at all. A failure removes the staged copy, and an existing JobDir or staged copy
    is `OW_TARGET_JOB_EXISTS` (`OW-T-520`), because a scaffold never writes over one.
23. **The path is `<cache_root>/jobs/<run_id>/<slug>@<gen>/`** (09 section 5.4). The
    slug becomes a directory name and `artifact.slug`, so it must be lower-case letters,
    digits and hyphens, 1 to 64 long (`OW_TARGET_SLUG_INVALID`, `OW-T-519`), the shape
    of 09's `q3-board`. The plan gives the slug no grammar.
24. **The commissioned roster is the Brief's `## rhythm` rows**, in numeric id order, each
    with its anchor. 09 section 3.2 writes `plan.units` "from the Brief's unit count",
    13.1's second scoping question is that count, and `## rhythm` is the one section
    keyed by unit. A rhythm with no row commissions nothing and is
    `OW_TARGET_BRIEF_INVALID`. A unit's file is `il/<id>.<carrier>`.
25. **`il/il.toml` starts with no `[[unit]]` row.** Section 3.2 has the authoring agent edit
    it "as units are added", and the early stage checks "every unit authored so far". A
    row with no file is `OW-T-507`, so a scaffold that wrote every row would fail every
    check until the last unit was written.
26. **The scaffolded `Plan` says what a scaffold knows.** `gate_status` is `not-provided`,
    `cites` is empty and `delivery` is `release`. `il_digest` is the scaffolded `il/`
    (`il.toml` alone), `ledger_digest` is the empty ledger's, and `toolchain_digest` is
    `None`: a Toolchain's digest is resolved when it is installed, not when a job is
    named. A check and a compile replace what they compute.

## Rulings (the ledger's D771)

27. **A compile worker is invoked over one unit, the job document.** 09 section 7.1 gives a
    compile job a synthetic document: `uri` `ow-job://<corpus>/<artifact_slug>/<job_digest>`,
    `media_type` `application/vnd.omniweave.job+json`, and digests over "the canonical job
    record". That record is `canonical(job.as_json())`, sorted keys and no whitespace, and not
    ruling 20's file bytes, which keep the Brief's section order: a frame's header is encoded
    with sorted keys, so a job that crossed one writes other file bytes and the same record.
    `job_unit()` is the `UnitRef` whose `content_sha256` is the record's sha256, and a worker
    that is handed a `job` whose record digests otherwise refuses it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Never

from omniweave_ports import UnitRef

from omniweave_core.canonical import canonical
from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.events import TRACEPARENT_RE
from omniweave_core.limits import MAX_IL_FILE_BYTES
from omniweave_core.model.block import Cite
from omniweave_core.out.brief import Brief, Prohibition, Template
from omniweave_core.out.carrier import CarrierDoc, CarrierParseError, ParseError
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.constructs import ConstructTable, Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.ledger import ledger_digest, write_index
from omniweave_core.out.manual import ManualRegion, manual_regions
from omniweave_core.out.plan import PLAN_SCHEMA, ManualReason, OutUnit, Plan

if TYPE_CHECKING:
    from omniweave_core.out.card import CompileCard

__all__ = [
    "BRIEF_MD",
    "IL_SCHEMA",
    "JOBS_DIR",
    "JOB_JSON",
    "JOB_MEDIA_TYPE",
    "JOB_SCHEMA",
    "UNPARSED_HEX",
    "UNREADABLE",
    "ILBundle",
    "ILFile",
    "Job",
    "JobDeterminism",
    "elided",
    "job_path",
    "job_unit",
    "read_il_files",
    "scaffold",
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


# ---------------------------------------------------------------------------------------------
# job.json, the JobDir's envelope (D763)
# ---------------------------------------------------------------------------------------------

JOB_SCHEMA: Final = "omniweave.out-job/1"
JOB_JSON: Final = "job.json"
_JOB_FIX: Final = "ow explain OW-T-518"
_CITE_TOKEN: Final = re.compile(r"d\d+#\d+")
_TRACEPARENT: Final = re.compile(TRACEPARENT_RE)


@dataclass(frozen=True, slots=True)
class JobDeterminism:
    """`job.json`'s `determinism`: the instant every OPC timestamp is written as (09 section 12.3).

    `dcterms:created == dcterms:modified == job.determinism.clock_ns`, so the wall clock never
    reaches a part. It is read once from the injected `Clock` when the job is scaffolded.
    """

    clock_ns: int


@dataclass(frozen=True, slots=True)
class Job:
    """`job.json` (`omniweave.out-job/1`): the `Plan`, the trace context and the clock (09 Q11).

    09 Q11 found that `Plan` was versioned and its envelope was not, so a Toolchain child could
    refuse an unknown `plan.schema` and could not refuse an unknown envelope.
    """

    schema: Literal["omniweave.out-job/1"]
    plan: Plan
    traceparent: str
    determinism: JobDeterminism

    def __post_init__(self) -> None:
        if self.schema != JOB_SCHEMA:
            _job_invalid(f"schema {self.schema!r} is not {JOB_SCHEMA!r}")
        if _TRACEPARENT.fullmatch(self.traceparent) is None:
            _job_invalid(f"traceparent {self.traceparent!r} is not 00-<32 hex>-<16 hex>-01")
        clock = self.determinism.clock_ns
        if isinstance(clock, bool) or not isinstance(clock, int) or clock < 0:
            _job_invalid(f"determinism.clock_ns {clock!r} is not a non-negative integer")
        if self.plan.brief.digest() != self.plan.brief_digest:
            _job_invalid(
                f"plan.brief digests to {self.plan.brief.digest()}, not plan.brief_digest "
                f"{self.plan.brief_digest}"
            )

    def as_json(self) -> dict[str, Any]:
        """Every key, `None` as `null`: the shape `schema/job-v1.json` requires."""
        plan = self.plan
        return {
            "schema": self.schema,
            "plan": {
                "schema": plan.schema,
                "target": plan.target,
                "slug": plan.slug,
                "artifact_gen": plan.artifact_gen,
                "delivery": plan.delivery,
                "units": [_unit_json(unit) for unit in plan.units],
                "unit_count": plan.unit_count,
                "brief": _brief_json(plan.brief),
                "corpus": plan.corpus,
                "cites": {str(cite): gen for cite, gen in sorted(plan.cites.items())},
                "gate_status": plan.gate_status.value,
                "il_digest": plan.il_digest,
                "constructs_digest": plan.constructs_digest,
                "ledger_digest": plan.ledger_digest,
                "brief_digest": plan.brief_digest,
                "card_sha256": plan.card_sha256,
                "toolchain_digest": plan.toolchain_digest,
                "parent_gen": plan.parent_gen,
            },
            "traceparent": self.traceparent,
            "determinism": {"clock_ns": self.determinism.clock_ns},
        }

    def to_bytes(self) -> bytes:
        """Ruling 20: UTF-8, two-space indent, LF, one trailing newline. Byte-stable."""
        return (json.dumps(self.as_json(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    @classmethod
    def from_json(cls, raw: object) -> Job:
        """Ruling 19: closed at every level. A key unknown or missing anywhere is a refusal."""
        top = _object(raw, "job.json", _JOB_KEYS)
        plan = _object(top["plan"], "plan", _PLAN_KEYS)
        determinism = _object(top["determinism"], "determinism", frozenset({"clock_ns"}))
        try:
            built = Plan(
                schema=_string(plan, "schema", "plan"),  # type: ignore[arg-type]
                target=_string(plan, "target", "plan"),
                slug=_string(plan, "slug", "plan"),
                artifact_gen=_integer(plan, "artifact_gen", "plan"),
                delivery=_string(plan, "delivery", "plan"),  # type: ignore[arg-type]
                units=tuple(_unit(one, n) for n, one in enumerate(_array(plan, "units", "plan"))),
                unit_count=_integer(plan, "unit_count", "plan"),
                brief=_brief(plan["brief"]),
                corpus=_string(plan, "corpus", "plan"),
                cites=_cites(plan["cites"]),
                gate_status=_gate(plan["gate_status"]),
                il_digest=_string(plan, "il_digest", "plan"),
                constructs_digest=_string(plan, "constructs_digest", "plan"),
                ledger_digest=_string(plan, "ledger_digest", "plan"),
                brief_digest=_string(plan, "brief_digest", "plan"),
                card_sha256=_string(plan, "card_sha256", "plan"),
                toolchain_digest=_optional_string(plan, "toolchain_digest", "plan"),
                parent_gen=_optional_integer(plan, "parent_gen", "plan"),
            )
        except ValueError as exc:
            _job_invalid(f"plan: {exc}")
        return cls(
            schema=_string(top, "schema", "job.json"),  # type: ignore[arg-type]
            plan=built,
            traceparent=_string(top, "traceparent", "job.json"),
            determinism=JobDeterminism(_integer(determinism, "clock_ns", "determinism")),
        )

    @classmethod
    def load(cls, job_dir: Path) -> Job:
        """`<job_dir>/job.json`, read and asserted."""
        path = job_dir / JOB_JSON
        try:
            raw = json.loads(_bounded(path).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _job_invalid(f"{JOB_JSON} does not load: {type(exc).__name__}: {exc}")
        return cls.from_json(raw)

    def write(self, job_dir: Path) -> Path:
        """Ruling 20's bytes at `<job_dir>/job.json`, written whole or not at all."""
        path = job_dir / JOB_JSON
        staged = path.with_name(path.name + ".tmp")
        staged.write_bytes(self.to_bytes())
        staged.replace(path)
        return path


_JOB_KEYS: Final = frozenset({"schema", "plan", "traceparent", "determinism"})
_PLAN_KEYS: Final = frozenset(
    {
        "schema", "target", "slug", "artifact_gen", "delivery", "units", "unit_count", "brief",
        "corpus", "cites", "gate_status", "il_digest", "constructs_digest", "ledger_digest",
        "brief_digest", "card_sha256", "toolchain_digest", "parent_gen",
    }
)  # fmt: skip
_OUT_UNIT_KEYS: Final = frozenset(
    {
        "id", "ord", "il_path", "anchor", "nsig", "source_part", "source_nsig", "source_ord",
        "manual_reason",
    }
)  # fmt: skip
_BRIEF_KEYS: Final = frozenset({"sections", "forbidden", "template"})


def _unit_json(unit: OutUnit) -> dict[str, Any]:
    return {
        "id": unit.id,
        "ord": unit.ord,
        "il_path": unit.il_path,
        "anchor": unit.anchor,
        "nsig": unit.nsig,
        "source_part": unit.source_part,
        "source_nsig": unit.source_nsig,
        "source_ord": unit.source_ord,
        "manual_reason": None if unit.manual_reason is None else unit.manual_reason.value,
    }


def _brief_json(brief: Brief) -> dict[str, Any]:
    template = brief.template
    return {
        "sections": {name: dict(rows) for name, rows in brief.sections.items()},
        "forbidden": [{"text": one.text, "tier": one.tier} for one in brief.forbidden],
        "template": None
        if template is None
        else {
            "ref": template.ref,
            "units": None if template.units is None else list(template.units),
        },
    }


def _unit(raw: object, n: int) -> OutUnit:
    where = f"plan.units[{n}]"
    row = _object(raw, where, _OUT_UNIT_KEYS)
    reason = _optional_string(row, "manual_reason", where)
    try:
        manual = None if reason is None else ManualReason(reason)
    except ValueError:
        _job_invalid(f"{where}: manual_reason {reason!r} is not a ManualReason")
    return OutUnit(
        id=_string(row, "id", where),
        ord=_integer(row, "ord", where),
        il_path=_string(row, "il_path", where),
        anchor=_string(row, "anchor", where),
        nsig=_optional_string(row, "nsig", where),
        source_part=_optional_string(row, "source_part", where),
        source_nsig=_optional_string(row, "source_nsig", where),
        source_ord=_optional_integer(row, "source_ord", where),
        manual_reason=manual,
    )


def _brief(raw: object) -> Brief:
    row = _object(raw, "plan.brief", _BRIEF_KEYS)
    sections = row["sections"]
    if not isinstance(sections, dict) or not all(
        isinstance(name, str)
        and isinstance(rows, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in rows.items())
        for name, rows in sections.items()
    ):
        _job_invalid("plan.brief.sections is not an object of string-to-string objects")
    forbidden = []
    for n, one in enumerate(_array(row, "forbidden", "plan.brief")):
        where = f"plan.brief.forbidden[{n}]"
        item = _object(one, where, frozenset({"text", "tier"}))
        tier = _string(item, "tier", where)
        if tier not in ("baseline", "user"):
            _job_invalid(f"{where}: tier {tier!r} is baseline or user")
        forbidden.append(Prohibition(_string(item, "text", where), tier))  # type: ignore[arg-type]
    template = None
    if row["template"] is not None:
        item = _object(row["template"], "plan.brief.template", frozenset({"ref", "units"}))
        units = item["units"]
        if units is not None and (
            not isinstance(units, list) or not all(isinstance(u, str) for u in units)
        ):
            _job_invalid("plan.brief.template.units is neither null nor a list of unit ids")
        template = Template(
            _string(item, "ref", "plan.brief.template"), None if units is None else tuple(units)
        )
    return Brief(
        sections=MappingProxyType(
            {name: MappingProxyType(dict(rows)) for name, rows in sections.items()}
        ),
        forbidden=tuple(forbidden),
        template=template,
    )


def _cites(raw: object) -> Mapping[Cite, int]:
    if not isinstance(raw, dict):
        _job_invalid("plan.cites is not an object")
    out: dict[Cite, int] = {}
    for token, gen in raw.items():
        if _CITE_TOKEN.fullmatch(token) is None:
            _job_invalid(f"plan.cites: {token!r} is not a cite token d<N>#<N>")
        if isinstance(gen, bool) or not isinstance(gen, int) or gen < 1:
            _job_invalid(f"plan.cites[{token!r}]: doc_gen {gen!r} is not a positive integer")
        out[Cite(token)] = gen
    return MappingProxyType(out)


def _gate(raw: object) -> GateStatus:
    try:
        return GateStatus(raw)
    except ValueError:
        _job_invalid(f"plan.gate_status {raw!r} is not one of the ten GateStatus values")


def _object(raw: object, where: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _job_invalid(f"{where} is not an object")
    unknown, missing = sorted(set(raw) - keys), sorted(keys - set(raw))
    if unknown:
        _job_invalid(f"{where} has unknown key(s) {unknown}: the envelope is closed")
    if missing:
        _job_invalid(f"{where} is missing {missing}")
    return raw


def _array(row: Mapping[str, Any], key: str, where: str) -> list[Any]:
    value = row[key]
    if not isinstance(value, list):
        _job_invalid(f"{where}.{key} is not an array")
    return value


def _string(row: Mapping[str, Any], key: str, where: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        _job_invalid(f"{where}.{key} = {value!r} is not a string")
    return value


def _optional_string(row: Mapping[str, Any], key: str, where: str) -> str | None:
    return None if row[key] is None else _string(row, key, where)


def _integer(row: Mapping[str, Any], key: str, where: str) -> int:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _job_invalid(f"{where}.{key} = {value!r} is not an integer")
    return value


def _optional_integer(row: Mapping[str, Any], key: str, where: str) -> int | None:
    return None if row[key] is None else _integer(row, key, where)


def _job_invalid(msg: str) -> Never:
    raise TargetError(f"{JOB_JSON}: {msg}", symbol="OW_TARGET_JOB_INVALID", fix=_JOB_FIX)


# ---------------------------------------------------------------------------------------------
# The scaffold: one JobDir, written whole (D764)
# ---------------------------------------------------------------------------------------------

BRIEF_MD: Final = "brief.md"
JOBS_DIR: Final = "jobs"
_SLUG: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_RUN_ID: Final = re.compile(r"r_[0-9A-HJKMNP-TV-Z]{26}")


JOB_MEDIA_TYPE: Final = "application/vnd.omniweave.job+json"
"""The synthetic job document's media type (09 section 7.1)."""


def job_unit(job: Job) -> UnitRef:
    """Ruling 27: the job document as the `UnitRef` a compile worker answers for."""
    data = canonical(job.as_json())
    digest = hashlib.sha256(data).hexdigest()
    plan = job.plan
    return UnitRef(
        uri=f"ow-job://{plan.corpus}/{plan.slug}/{digest}",
        part="",
        content_sha256=digest,
        byte_len=len(data),
        media_type=JOB_MEDIA_TYPE,
    )


def job_path(cache_root: Path, run_id: str, slug: str, artifact_gen: int) -> Path:
    """`<cache_root>/jobs/<run_id>/<artifact_slug>@<gen>/` (09 section 5.4; ruling 23)."""
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError(f"run id {run_id!r} is not r_ and 26 Crockford base32 characters")
    _slug(slug)
    if artifact_gen < 1:
        raise ValueError(f"artifact_gen {artifact_gen} is below 1")
    return cache_root / JOBS_DIR / run_id / f"{slug}@{artifact_gen}"


def scaffold(
    job_dir: Path,
    *,
    card: CompileCard,
    card_sha256: str,
    table: ConstructTable,
    brief_text: str,
    brief: Brief,
    slug: str,
    artifact_gen: int,
    corpus: str,
    traceparent: str,
    clock_ns: int,
) -> Job:
    """Rulings 22-26: the JobDir `ow out scaffold` writes, staged beside it and renamed in."""
    from omniweave_core.out.report import il_digest  # noqa: PLC0415 -- report imports this module

    _slug(slug)
    units = _commissioned(brief, card.carrier)
    staged = job_dir.with_name(job_dir.name + ".tmp")
    for path in (job_dir, staged):
        if path.exists():
            raise TargetError(
                f"{path} exists; a scaffold never writes over a JobDir",
                symbol="OW_TARGET_JOB_EXISTS",
                fix=f"ow out scaffold {card.target} --slug {slug}   # a fresh run id",
            )
    #  Every digest before the first write: none of them is inside the cleanup's `except`
    #  (G8's `omniweave-no-bare-except-around-identity`). `il/` holds `il.toml` alone, so its
    #  `il_digest` is that file's row, the one `read_il_files()` would record.
    il_toml = (
        f'schema = "{IL_SCHEMA}"\nil = "{table.il}"\nconstructs_digest = "{table.digest()}"\n'
    ).encode()
    scaffolded = ILFile(IL_TOML, hashlib.sha256(il_toml).hexdigest(), len(il_toml))
    job = Job(
        schema=JOB_SCHEMA,
        plan=Plan(
            schema=PLAN_SCHEMA,
            target=card.target,
            slug=slug,
            artifact_gen=artifact_gen,
            delivery="release",
            units=units,
            unit_count=len(units),
            brief=brief,
            corpus=corpus,
            cites=MappingProxyType({}),
            gate_status=GateStatus.NOT_PROVIDED,
            il_digest=il_digest((scaffolded,)),
            constructs_digest=table.digest(),
            ledger_digest=ledger_digest(()),
            brief_digest=brief.digest(),
            card_sha256=card_sha256,
            toolchain_digest=None,
        ),
        traceparent=traceparent,
        determinism=JobDeterminism(clock_ns),
    )
    job_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        for part in ("il", "validation", "out"):
            (staged / part).mkdir(parents=True)
        (staged / BRIEF_MD).write_bytes(brief_text.encode("utf-8"))
        (staged / "il" / IL_TOML).write_bytes(il_toml)
        write_index(staged, ())
        job.write(staged)
        staged.rename(job_dir)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return job


def _commissioned(brief: Brief, carrier: str) -> tuple[OutUnit, ...]:
    """Ruling 24: one unit a `## rhythm` row, in numeric id order, each with its anchor."""
    ids = sorted(brief.rhythm(), key=lambda unit: int(unit[1:]))
    if not ids:
        raise TargetError(
            f"{BRIEF_MD}: ## rhythm commissions no unit; the unit count is its rows",
            symbol="OW_TARGET_BRIEF_INVALID",
            fix="add one `- u01: { anchor: cover }` row a unit under ## rhythm",
        )
    return tuple(
        OutUnit(id=unit, ord=n, il_path=f"il/{unit}.{carrier}", anchor=brief.anchor(unit))
        for n, unit in enumerate(ids, start=1)
    )


def _slug(slug: str) -> None:
    if _SLUG.fullmatch(slug) is None:
        raise TargetError(
            f"slug {slug!r} is not lower-case letters, digits and hyphens, 1 to 64 long",
            symbol="OW_TARGET_SLUG_INVALID",
            fix="ow out scaffold <target> --slug q3-board",
        )
