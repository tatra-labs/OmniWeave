"""The OUT conformance suite: a target's declared laws, run against its golden fixture. **D759.**

09-generation.md section 11.4: "`omniweave_core/out/roundtrip.py` exposes `r1 ... r7` as executable
predicates, imported by `omniweave-conform`'s `target` suite. The suite is parameterized over
`fixtures/out/golden/<target>/`... and a target's card declares which laws apply. A law the card
does not declare is **reported as not applicable**, not silently absent." This module is that
suite's runner. D757's predicates judge, and this gathers the facts each one is stated over by
checking and compiling the golden fixture in a scratch directory.

## Rulings

1. **The suite is not one of the twelve.** `SuiteResult` names only the twelve card-level suites,
   which `[quality.suites]` closes. The `target` suite reports per law, so it has its own
   `TargetReport`. Its verdict is `Verdict.worst()` over the laws the card declares, which keeps
   a law nobody checked out of the verdict entirely.
2. **The golden fixture must pass its own gate first.** Section 2's call order makes `lower()`
   unreachable behind any other status (OUT23). A golden fixture that does not pass leaves every
   declared law `unknown`, naming the status, and lowers nothing. `manual-required` compiles as a
   draft: exercising `ow:manual`, a mandatory row, needs a manual region, and a manual region is
   that gate.
3. **The fixture's cites resolve against the fixture.** `cites.json` maps each token to the block
   facts a resolver would return. A golden fixture is self-contained, so it never needs a corpus.
4. **R1 compiles twice, in two scratch directories, and compares the card's declared classes.**
   `part` is the receipt's `part_digest` and `byte` is the artefact's sha256. A class the suite
   cannot measure (`frame`, `render`) is R1's own "unmeasured" failure, never a pass.
5. **R7 is the classifier and the receipt together.** `classify_and_assert()` must place every
   unit, and the receipt `postflight()` writes must say the same outcome per unit (OUT8). A
   disagreement is an R7 failure of its own kind.
6. **R5's third and fourth clauses are computed, and its first two need a reader.** A row is
   exercised when its selector matches something in the golden IL. A mutation inserts a byte into
   the row's payload (an attribute's value, or an element's start tag) in a scratch copy, then
   reloads the bundle to check whether `il_digest_rt` moved. Observed loss and its diagnostics
   need `read_back`, which this suite does not invoke yet, so R5 is `unknown` when clauses 3 and 4
   hold and fails when either does not.
7. **`attr.ow-el` is exempt from R5's fourth clause, and the report says so.** `data-ow-el` is the
   address. `canonical_subtree()` drops it by normalization, so `il_digest_rt` cannot see it,
   and its survival is R2's to prove. 09 makes the row `exact` and R5 asks every exact row to move
   `il_digest_rt`. Taken literally, that fails for every target, so the exemption is named rather
   than silent.
8. **R6 and the reader laws are `unknown` until there is a source artefact and a reader.** R6 is
   about parts a source artefact carries that IL cannot represent. A golden fixture is IL alone,
   so R6 has no case to judge. R2, R3 and R4 read an artefact back.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.errors import TargetError
from omniweave_core.model.enums import Quote
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.cites import CitedBlock
from omniweave_core.out.compile import check
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle
from omniweave_core.out.plan import Plan, classify_and_assert
from omniweave_core.out.roundtrip import Failure, LawResult, applicable, r1, r5, r7
from omniweave_ports import ArtifactKind

from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_conform.result import Verdict

if TYPE_CHECKING:
    from typing import BinaryIO

    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.out.compile import CompileV1
    from omniweave_core.out.constructs import Construct, ConstructTable
    from omniweave_core.out.ledger import AssetSource, LedgerRow
    from omniweave_ports import DriverResult

__all__ = ["CITES", "LawOutcome", "TargetReport", "run_target"]

CITES: Final = "cites.json"
_EL_SELECTOR: Final = "@data-ow-el"
_MUTANT: Final = ' data-ow-mutant=""'
_BRIEF: Final = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n",
    baseline=(),
)
"""The Brief a golden compile carries: the minimal one, because no golden rule reads it."""


@dataclass(frozen=True, slots=True)
class LawOutcome:
    """One law's place in the report: checked, not applicable, or unknown with its reason."""

    law: str
    status: Literal["checked", "not-applicable", "unknown"]
    result: LawResult | None = None
    reason: str = ""

    @property
    def verdict(self) -> Verdict:
        if self.status == "checked" and self.result is not None:
            return Verdict.PASS if self.result.passed else Verdict.FAIL
        return Verdict.UNKNOWN


@dataclass(frozen=True, slots=True)
class TargetReport:
    """Ruling 1: the `target` suite's report, one outcome per law."""

    target: str
    gate: GateStatus
    laws: tuple[LawOutcome, ...]

    @property
    def verdict(self) -> Verdict:
        return Verdict.worst(o.verdict for o in self.laws if o.status != "not-applicable")

    def law(self, name: str) -> LawOutcome:
        return next(o for o in self.laws if o.law == name)


def run_target(
    compiler: CompileV1,
    card: DriverCard,
    constructs: ConstructTable,
    golden: Path,
    *,
    workdir: Path,
) -> TargetReport:
    """Rulings 2-8 over one golden fixture, in `workdir` and never in the fixture itself."""
    sibling = dict(card.compile_sibling)
    round_trip: Mapping[str, Any] = sibling.get("round_trip", {})  # type: ignore[assignment]
    claim = applicable(round_trip.get("laws", ()), str(round_trip.get("fidelity", "none")))
    target = str(sibling.get("target", ""))
    job = workdir / "job"
    shutil.copytree(golden / "il", job / "il")
    checked = check(
        job,
        compiler,
        target=target,
        constructs=constructs,
        stage="final",
        cites=_FixtureCites(golden / CITES),
    )
    outcomes = {law: LawOutcome(law, "not-applicable") for law in claim.not_applicable}
    if checked.status not in {GateStatus.PASSED, GateStatus.MANUAL_REQUIRED}:
        reason = f"the golden fixture's gate is {checked.status}; lower() is unreachable (OUT23)"
        outcomes |= {law: LawOutcome(law, "unknown", reason=reason) for law in claim.applies}
        return _report(target, checked.status, outcomes)

    bundle = ILBundle.load(job / "il", carrier=compiler.carrier, constructs=constructs)
    plan = _plan(target, bundle, constructs, checked.status)
    capability = dict(card.compile_capability)
    declared = tuple(str(c) for c in capability.get("determinism", ()))  # type: ignore[union-attr]
    for law in claim.applies:
        outcomes[law] = _law(
            law,
            compiler=compiler,
            plan=plan,
            bundle=bundle,
            constructs=constructs,
            declared=declared,
            job=job,
            workdir=workdir,
        )
    return _report(target, checked.status, outcomes)


def _report(target: str, gate: GateStatus, outcomes: Mapping[str, LawOutcome]) -> TargetReport:
    return TargetReport(target, gate, tuple(outcomes[law] for law in sorted(outcomes)))


def _law(
    law: str,
    *,
    compiler: CompileV1,
    plan: Plan,
    bundle: ILBundle,
    constructs: ConstructTable,
    declared: tuple[str, ...],
    job: Path,
    workdir: Path,
) -> LawOutcome:
    if law == "r1":
        first = _compile(compiler, plan, bundle, workdir / "r1-a")
        second = _compile(compiler, plan, bundle, workdir / "r1-b")
        return LawOutcome("r1", "checked", r1(declared, first[0], second[0]))
    if law == "r7":
        return LawOutcome("r7", "checked", _r7(compiler, plan, bundle, workdir / "r7"))
    if law == "r5":
        return _r5(constructs, compiler, bundle, job, workdir / "r5")
    reason = {
        "r6": "R6 judges a source artefact's unrepresented parts; a golden fixture is IL alone",
    }.get(law, f"{law} reads the artefact back, and this suite invokes no read_back driver yet")
    return LawOutcome(law, "unknown", reason=reason)


def _plan(target: str, bundle: ILBundle, constructs: ConstructTable, gate: GateStatus) -> Plan:
    """Ruling 2: a release of a passed gate, a draft of a manual-required one."""
    return Plan(
        schema="omniweave.out-plan/1",
        target=target,
        slug="golden",
        artifact_gen=1,
        delivery="release" if gate is GateStatus.PASSED else "draft",
        units=bundle.units,
        unit_count=len(bundle.units),
        brief=_BRIEF,
        corpus="golden",
        cites={},
        gate_status=gate,
        il_digest=bundle.il_digest,
        constructs_digest=constructs.digest(),
        ledger_digest="sha256:" + hashlib.sha256(b"[]").hexdigest(),
        brief_digest=_BRIEF.digest(),
        card_sha256="sha256:" + "0" * 64,
    )


def _compile(
    compiler: CompileV1, plan: Plan, bundle: ILBundle, scratch: Path
) -> tuple[dict[str, str], Any]:
    """Ruling 4: one in-process compile, and the digests R1 compares."""
    io = make_io(MemoryBlobStore(scratch / "kit"), scratch / "io")
    body = _artefact(compiler.lower(plan, bundle, _NO_ASSETS, io), io)
    staged = scratch / f"{plan.slug}.artefact"
    staged.write_bytes(body)
    receipt = compiler.postflight(str(staged), plan)
    digests = {
        "part": "sha256:" + receipt.part_digest,
        "byte": "sha256:" + hashlib.sha256(body).hexdigest(),
    }
    return digests, receipt


def _artefact(result: DriverResult, io: Any) -> bytes:
    refs = [r for r in result.produced if r.kind == ArtifactKind.ARTIFACT]
    if len(refs) != 1:
        raise TargetError(
            f"lower() returned {len(refs)} artifact refs; a compile produces exactly one",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: its lower() must return one artifact",
        )
    if refs[0].inline is not None:
        return refs[0].inline
    with io.blobs.open((refs[0].blob or "").removeprefix("cas://")) as handle:
        return handle.read()


def _r7(compiler: CompileV1, plan: Plan, bundle: ILBundle, scratch: Path) -> LawResult:
    """Ruling 5: the classifier places every unit, and the receipt says the same."""
    try:
        classified = classify_and_assert(plan, baked={}, visual_changed=lambda _u: True)
    except TargetError as exc:
        return LawResult("r7", (Failure("unclassified", plan.slug, str(exc)),))
    outcomes = {u: c.outcome for u, c in classified.items()}
    result = r7([u.id for u in plan.units], outcomes)
    _, receipt = _compile(compiler, plan, bundle, scratch)
    said = dict(receipt.units)
    if said == outcomes:
        return result
    disagree = Failure(
        "receipt-disagrees",
        plan.slug,
        f"the receipt says {sorted((u, str(o)) for u, o in said.items())}, the classifier "
        f"{sorted((u, str(o)) for u, o in outcomes.items())}",
    )
    return LawResult("r7", (*result.failures, disagree))


def _r5(
    constructs: ConstructTable, compiler: CompileV1, bundle: ILBundle, job: Path, scratch: Path
) -> LawOutcome:
    """Rulings 6 and 7: clauses 3 and 4, computed; clauses 1 and 2 left to a reader."""
    exact = [
        row
        for row in constructs.rows
        if row.round_trip is RoundTrip.EXACT and row.disposition is not Disposition.NORMALIZE
    ]
    exercised: set[str] = set()
    moved: set[str] = set()
    for row in exact:
        mutated = _mutate(row, bundle, compiler)
        if mutated is None:
            continue
        exercised.add(row.id)
        if row.selector == _EL_SELECTOR or _moves(
            mutated,
            bundle=bundle,
            compiler=compiler,
            constructs=constructs,
            job=job,
            scratch=scratch / row.id,
        ):
            moved.add(row.id)
    result = r5(
        declared_loss=frozenset(),
        observed_loss=frozenset(),
        loss_shown=frozenset(),
        exact=frozenset(row.id for row in exact),
        exercised=frozenset(exercised),
        moved=frozenset(moved),
    )
    if not result.passed:
        return LawOutcome("r5", "checked", result)
    return LawOutcome(
        "r5",
        "unknown",
        result,
        "clauses 3 and 4 hold (attr.ow-el exempt from clause 4: canonical_subtree drops the "
        "address, and its survival is R2's); clauses 1 and 2 need a read_back driver",
    )


def _mutate(row: Construct, bundle: ILBundle, compiler: CompileV1) -> tuple[str, str] | None:
    """Ruling 6: the first unit whose IL the row's selector matches, with one byte of payload
    changed: `(il_path, mutated text)`, or `None` when nothing in the fixture exercises it."""
    attribute = (
        row.selector[1:] if row.selector.startswith("@") and "|" not in row.selector else None
    )
    for unit in bundle.units:
        text = bundle.text(unit.il_path)
        for node in compiler.carrier(unit.il_path, text).select(row.selector):
            if not isinstance(node, Node):
                continue
            if attribute is None:
                cut = node.start + 1 + len(node.tag.split("|")[-1])
                return unit.il_path, text[:cut] + _MUTANT + text[cut:]
            head = text[node.start : node.start_end]
            for quote in ('"', "'"):
                at = head.find(f"{attribute}={quote}")
                if at != -1:
                    end = head.find(quote, at + len(attribute) + 2)
                    cut = node.start + end
                    return unit.il_path, text[:cut] + "~" + text[cut:]
    return None


def _moves(
    mutated: tuple[str, str],
    *,
    bundle: ILBundle,
    compiler: CompileV1,
    constructs: ConstructTable,
    job: Path,
    scratch: Path,
) -> bool:
    il_path, text = mutated
    copy = scratch / "il"
    shutil.copytree(job / "il", copy)
    (copy / il_path.removeprefix("il/")).write_text(text, encoding="utf-8", newline="")
    again = ILBundle.load(copy, carrier=compiler.carrier, constructs=constructs)
    return again.il_digest_rt != bundle.il_digest_rt


class _FixtureCites:
    """Ruling 3: the golden fixture's own `cites.json`, as a `CiteResolver`."""

    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        self._blocks = {
            cite: CitedBlock(
                cite=cite,
                block_id=int(facts["block_id"]),
                doc_ord=int(facts["doc_ord"]),
                doc_gen=int(facts["doc_gen"]),
                text=facts.get("text"),
                quote=Quote[str(facts.get("quote", "normalized")).upper()],
                restriction_bits=int(facts.get("restriction_bits", 0)),
            )
            for cite, facts in raw.items()
        }

    def by_cite(self, cite: str) -> CitedBlock | None:
        return self._blocks.get(cite)

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        return {c: self._blocks.get(c) for c in cites}


class _NoAssets:
    """The ledger a golden compile is handed: nothing frozen, so any read is the target's bug."""

    def slot(self, sha256: str) -> str:
        return "asset-slot:" + sha256

    def freeze(self, src: AssetSource, *, role: str, unit: str) -> LedgerRow:
        del src  # nothing is read: a golden compile freezes nothing
        raise TargetError(
            f"a golden compile freezes nothing ({role} for {unit})",
            symbol="OW_TARGET_ASSET_UNFROZEN",
            fix="freeze golden assets into the fixture, not during the compile",
        )

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(b"[]").hexdigest()

    def open(self, slot: str) -> BinaryIO:
        raise TargetError(
            f"{slot} is not in a golden compile's ledger",
            symbol="OW_TARGET_ASSET_UNFROZEN",
            fix="freeze golden assets into the fixture, not during the compile",
        )


_NO_ASSETS: Final = _NoAssets()
