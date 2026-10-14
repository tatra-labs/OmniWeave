"""`CompileV1`, the fifth Port, and `check()`, the framework's half of the call order. **D749.**

09-generation.md section 2 (the seven methods, the method table, the call order) and section 4.3
(four stages, one report path each). `CompileV1` is the one Port protocol outside
`omniweave_ports`, because it references `Plan`, `ILBundle`, `AssetLedger`, `RuleSpec` and
`CarrierDoc`. There is no `validate()`: the framework parses with the target's `carrier()`,
enumerates its `rules()`, runs them with `run_pack()` and decides with `gate_status()`, so a target
that could run its own gate could not skip it.

## Rulings (the ledger's D749)

4. **`check()` is the call order's first half**, `ILBundle.load()` through `gate_status()`, writing
   `validation/<stage>.json`: the engine `ow out check` drives. The second half, from
   `assert_clean()` to `seal`, needs the store's `artifact` rows (W9.7) and is not built.
5. **Each stage takes 09 section 4.3's roster**: `early` every authored unit, `first-unit` exactly
   `u01`, `unit` exactly the one named, `final` the complete declared roster. Given the Plan's
   roster, `final` holds the bundle to it both ways (`OW_TARGET_ROSTER_MISMATCH`), which is
   preflight check 3 at check time. A stage whose roster is absent is refused, never run empty.
6. **A need is met when the compile has what it names**: `measure` when `CompileV1.measure()`
   returns an estimator, `cites` and `assets` when the caller hands a resolver and a ledger. Today
   neither is built, so a rule needing them is a recorded skip and the gate `unverified`, which is
   OUT3's honest answer and never a pass. D754: `cites` is met by the `CiteResolver` the caller
   hands `check(cites=...)`, which `RuleCtx.cites` then is. Without one, `RuleCtx.cites` is
   `NO_CITES`, which refuses, so a rule that reads cites without declaring the need raises
   rather than passing on an empty answer.
7. **A corrupt marker is a recorded skip**: 09 section 8.1 makes it a `FRAMEWORK` info finding and
   the gate `unverified`, because a marker nobody can read may be a `must`. It joins
   `skipped_checks` as `needs = "marker"`, which is what moves `gate_status()`.
8. **`RuleCtx.measure(n)` is exactly `m.box(n) if m is not None else None`** over the one
   estimator `measure()` returned, read once a check (OUT2): one wrapper, no second path.
9. **D756: every `ow:manual` region of the roster reaches the report.** A region with a known
   reason is a `manual_units` row (unit, `el`, reason), which is what makes the gate
   `manual-required`. A value outside `ManualReason` is the framework's error finding, so the
   gate fails rather than asking a human to act on a word nobody defined.

## Rulings (the ledger's D771)

10. **`lower_job()` is the half of the call order a compile worker runs**: `ILBundle.load()` with
    the target's own carrier, `lower()` over `FrozenLedger`, the one artefact staged in
    `io.tmpdir`, then `postflight()`. The card's `[isolation] requires = "subproc"` puts these in
    the S4 worker, and the gate, the lookup, the restriction aggregate and the seal stay with the
    host, which holds the store (INV-6). The `DriverResult` is `lower()`'s own: its one artefact
    ref, which the meter has already counted, then the receipt's bytes as a `receipt` ref.
11. **The worker lowers only the JobDir the host gated.** It recomputes `il_digest`,
    `constructs_digest` and `ledger_digest` and refuses any that differs from the Plan's, as
    `OW_TARGET_JOB_CHANGED`, because the host seals the Plan's digests and a file edited between
    the gate and the worker would otherwise be sealed under them.
12. **A refusal crosses with its symbol.** 02-architecture.md:1060 lets five `DriverError` fields
    cross a `RESULT`, and none is a symbol. `refusal_message()` puts the symbol and the fix
    first, one line each, so the worker's bound on a message cuts only the text, and
    `refusal_of()` reads them back on the host as a `TargetError`. A message in another shape is
    no refusal, and reads back as `None`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import ClassVar, Final, Never, Protocol

from omniweave_ports import (
    ArtifactKind,
    ArtifactRef,
    DriverIO,
    DriverResult,
    ProbeEnv,
    ProbeVerdict,
    Scalar,
)

from omniweave_core.clock import Clock
from omniweave_core.errors import OwError, TargetError
from omniweave_core.model.doc import Doc
from omniweave_core.out.brief import Brief
from omniweave_core.out.carrier import CarrierDoc, CarrierNode
from omniweave_core.out.cites import NO_CITES, CiteResolver
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import FindingSet
from omniweave_core.out.gate import GateStatus, exit_code
from omniweave_core.out.job import ILBundle, Job
from omniweave_core.out.ledger import AssetLedger, BlobReader, FrozenLedger
from omniweave_core.out.plan import OutUnit, Plan
from omniweave_core.out.receipt import Receipt
from omniweave_core.out.report import OutReport, SkippedCheck
from omniweave_core.out.rules import Box, DocIndex, RuleCtx, RuleSpec, TextMeasure, run_pack

__all__ = [
    "CheckResult",
    "CompileV1",
    "artefact",
    "check",
    "lower_job",
    "ref_bytes",
    "refusal_message",
    "refusal_of",
]

_MARKER_FIX = "ow out check --markers   # names the marker; re-place it or remove its line"
_SYMBOL: Final = re.compile(r"OW_[A-Z0-9_]+")


class CompileV1(Protocol):
    """09 section 2: seven methods. THERE IS NO `validate()`."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict: ...

    def __init__(self, **config: Scalar) -> None: ...

    def carrier(self, path: str, text: str) -> CarrierDoc: ...

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]: ...

    def measure(self) -> TextMeasure | None: ...

    def lower(
        self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO
    ) -> DriverResult: ...

    def postflight(self, artifact: str, plan: Plan) -> Receipt: ...

    def project(self, doc: Doc, io: DriverIO) -> ILBundle: ...


@dataclass(frozen=True, slots=True)
class CheckResult:
    """What `ow out check` prints from: the report, its gate, and the exit 09 section 15 maps."""

    report: OutReport
    status: GateStatus
    introduced_warning_count: int
    exit: int
    path: Path


@dataclass(slots=True)
class _Ctx:
    """The framework's `RuleCtx` (ruling 8). Built once a unit and once for pass B."""

    doc: CarrierDoc | None
    unit: OutUnit | None
    index: DocIndex
    constructs: ConstructTable
    brief: Brief | None
    limits: Mapping[str, int]
    estimator: TextMeasure | None = field(default=None, repr=False)
    cites: CiteResolver = field(default=NO_CITES, repr=False)

    def measure(self, n: CarrierNode) -> Box | None:
        return self.estimator.box(n) if self.estimator is not None else None


@dataclass(frozen=True, slots=True)
class _Roster:
    """`run_pack()`'s view of the bundle for one stage: its roster, the bundle's text."""

    units: tuple[OutUnit, ...]
    bundle: ILBundle

    def text(self, il_path: str) -> str:
        return self.bundle.text(il_path)


def check(
    job_dir: Path,
    compiler: CompileV1,
    *,
    target: str,
    constructs: ConstructTable,
    stage: str,
    unit: str | None = None,
    plan_units: Sequence[str] | None = None,
    brief: Brief | None = None,
    fixes: Mapping[str, str] | None = None,
    limits: Mapping[str, int] | None = None,
    clock: Clock | None = None,
    cites: CiteResolver | None = None,
) -> CheckResult:
    """Rulings 4-8: load, run the pack over the stage's roster, fold, gate, write the report."""
    bundle = ILBundle.load(job_dir / "il", carrier=compiler.carrier, constructs=constructs)
    roster = _roster(bundle, stage, unit, plan_units)
    estimator = compiler.measure()
    met = frozenset(
        ({"measure"} if estimator is not None else set())
        | ({"cites"} if cites is not None else set())
    )
    resolver = NO_CITES if cites is None else cites

    def mk_ctx(u: OutUnit | None, doc: CarrierDoc | None, index: DocIndex) -> RuleCtx:
        return _Ctx(doc, u, index, constructs, brief, limits or {}, estimator, resolver)

    run = run_pack(
        compiler.rules(),
        _Roster(roster, bundle),
        mk_ctx,
        carrier=compiler.carrier,
        stage=stage,
        met=met,
        fixes=fixes or {},
        constructs=constructs,
        clock=clock,
    )
    corrupt = [
        SkippedCheck(
            "ow.marker@1", "marker", f"marker {m.id} on {m.el} does not decode", _MARKER_FIX
        )
        for m in run.index.markers
        if m.state == "corrupt"
    ]
    regions = [r for u in roster for r in bundle.manual.get(u.id, ())]
    unknown = [r.finding() for r in regions if r.reason is None]
    report = OutReport.build(
        stage=stage,
        target=target,
        constructs_digest=constructs.digest(),
        files=bundle.files,
        units=[u.id for u in roster],
        findings=FindingSet((*run.findings.findings, *unknown)) if unknown else run.findings,
        skipped=(*run.skipped, *corrupt),
        manual=[r.as_json() for r in regions if r.reason is not None],
        markers=[m.as_json() for m in run.index.markers],
        timings=run.timings,
    )
    path = report.write(job_dir)
    status, introduced = report.gate()
    return CheckResult(report, status, introduced, exit_code(status, report), path)


def _roster(
    bundle: ILBundle, stage: str, unit: str | None, plan_units: Sequence[str] | None
) -> tuple[OutUnit, ...]:
    """Ruling 5: 09 section 4.3's roster requirement for each stage."""
    units = bundle.units
    if stage == "first-unit":
        units = tuple(u for u in units if u.id == "u01")
    elif stage == "unit":
        units = tuple(u for u in units if u.id == unit)
    elif stage == "final" and plan_units is not None:
        _same_roster(tuple(u.id for u in units), tuple(plan_units))
    if not units:
        wanted = {"first-unit": "u01", "unit": unit or "a unit id"}.get(stage, "an authored unit")
        _mismatch(f"stage {stage} has no unit to check: it needs {wanted}")
    return units


def _same_roster(bundle: Iterable[str], plan: Iterable[str]) -> None:
    have, want = set(bundle), set(plan)
    if have != want:
        _mismatch(
            f"the bundle and the plan disagree: in the plan only {sorted(want - have)}, "
            f"in the bundle only {sorted(have - want)}"
        )


def _mismatch(msg: str) -> Never:
    raise TargetError(msg, symbol="OW_TARGET_ROSTER_MISMATCH", fix="ow explain OW-T-507")


# ---------------------------------------------------------------------------------------------
# The worker's half: lower() and postflight() over a gated JobDir (D771)
# ---------------------------------------------------------------------------------------------


def lower_job(
    compiler: CompileV1,
    job: Job,
    job_dir: Path,
    *,
    constructs: ConstructTable,
    suffix: str,
    io: DriverIO,
) -> DriverResult:
    """Rulings 10 and 11: the bundle the host gated, lowered, staged and post-flighted."""
    plan = job.plan
    bundle = ILBundle.load(job_dir / "il", carrier=compiler.carrier, constructs=constructs)
    ledger = FrozenLedger.of(job_dir, io.blobs)
    computed = {
        "il_digest": bundle.il_digest,
        "constructs_digest": constructs.digest(),
        "ledger_digest": ledger.digest(),
    }
    changed = [
        f"{name} is {value}, and the plan says {getattr(plan, name)}"
        for name, value in computed.items()
        if getattr(plan, name) != value
    ]
    if changed:
        raise TargetError(
            "the JobDir is not the one the host gated: " + "; ".join(changed),
            symbol="OW_TARGET_JOB_CHANGED",
            fix="ow out check --stage final",
        )
    result = compiler.lower(plan, bundle, ledger, io)
    ref, body = artefact(result, io.blobs)
    staged = Path(io.tmpdir) / f"{plan.slug}{suffix}"
    staged.write_bytes(body)
    receipt = compiler.postflight(str(staged), plan)
    return replace(
        result, produced=(ref, ArtifactRef.of(ArtifactKind.RECEIPT, receipt.to_bytes(), io))
    )


def artefact(result: DriverResult, blobs: BlobReader) -> tuple[ArtifactRef, bytes]:
    """`lower()`'s one `artifact` ref and its bytes, read inline or from the CAS (D755)."""
    refs = [r for r in result.produced if r.kind == ArtifactKind.ARTIFACT]
    if len(refs) != 1:
        raise TargetError(
            f"lower() returned {len(refs)} artifact refs; a compile produces exactly one",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: its lower() must return one artifact",
        )
    [ref] = refs
    return ref, ref_bytes(ref, blobs)


def ref_bytes(ref: ArtifactRef, blobs: BlobReader) -> bytes:
    """One ref's bytes: inline, or out of the CAS by its digest (D772)."""
    if ref.inline is not None:
        return ref.inline
    #  `cas://<hex>` or the sharded `cas://bb/18/<hex>` a worker's put returns: the digest is last.
    with blobs.open((ref.blob or "").rsplit("/", 1)[-1]) as handle:
        return handle.read()


def refusal_message(error: OwError) -> str:
    """Ruling 12: the symbol, the fix, then the text, each of the first two on one line."""
    return f"{error.code()}\n{' '.join(error.fix.split())}\n{error}"


def refusal_of(message: str) -> TargetError | None:
    """Ruling 12: `refusal_message()` read back, or `None` for a message it did not write."""
    symbol, _, rest = message.partition("\n")
    fix, found, text = rest.partition("\n")
    if _SYMBOL.fullmatch(symbol) is None or not found or not fix.strip():
        return None
    return TargetError(text, symbol=symbol, fix=fix)
