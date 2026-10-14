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

## Rulings (D784)

9. **A golden fixture may freeze assets.** Each file under `<golden>/assets/` is a frozen
   `image` asset, slotted by its sha256, in a `FrozenLedger` the golden compile reads, and the
   Plan's `ledger_digest` is that ledger's. A fixture with no `assets/` gets the empty ledger, so
   a read is still the target's refusal. docx's golden needs one: `media.img` is an `exact` row,
   and R5 asks the golden to use every exact row.
10. **The scratch JobDir has its `job.json`.** A target may read the job's clock there (09
    section 12.3), as docx does for `dcterms`. The clock is fixed, so R1's two compiles are of one
    job, as a recompile of one JobDir is.
11. **The golden Plan pins its cites as the compile does** (`run.out_compile` ruling 18): each
    cite the IL names, resolved through `cites.json`, at the generation it resolved at. A target
    that embeds its citations reads them there.
13. **R2 runs when a reader is given** (D787). The suite has the target's compiler and not its
    `read_back`, which is a separate `parse/1` card, so the caller hands the reader in. The
    golden is compiled once and read back, and R2 is judged over every element of the golden IL
    that carries a `data-ow-el`, each under its construct (the first native element row that
    matches it, as a target's walk dispatches it) and the card's own `kind_map.toml`. A block's
    cites are its `x.ow.cites` (D785). With no reader, R2 is `unknown` and says why.
14. **R3 names its missing half.** R3 compiles `project(read_back(compile(I)))`. A card with
    `[compile.round_trip] project = false` declares no projection, so R3 is `unknown` naming that
    key rather than the reader.
12. **R5's exemption names the table's own address row.** owtext calls it `attr.ow-el` and docx
    `ow.el`; the exemption is by selector, `@data-ow-el`, and the reason now says which row.
15. **R4 named what it needed** (D805) until D808 built it (ruling 16). pptx is the first card
    to claim it (`fidelity = "passthrough"`).
16. **R4 recompiles the golden as its own next generation** (D808). A card claiming R4 names
    each unit's part (`[compile.round_trip] unit_part`, the card's ruling 7), and its
    artefact is a package of members. R4(a): the golden is compiled, then compiled again as
    the next generation with each unit edited from itself (its source part, nsig and ord
    the first compile's), so every unit must be copied, each unit's part its source's byte
    for byte. R4(b): a golden may carry `edit/`, IL files that replace their units.
    Recompiled against the first compile, each unit the edit does not touch must be
    `passthrough` or `patched`, and a copied unit's part its source's. The outcomes are the
    receipt's, what the compile reports. An `edit/` file that leaves its unit's nsig where
    it was is an `unedited` failure, since R4(b) would then hold of no edit. A golden with no
    `edit/` leaves R4 `unknown` when (a) holds, saying so. R4 reads no artefact back: an
    owsvg/1 edit restores the retained IL, and so does this.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io as io_module
import json
import shutil
import tomllib
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.errors import TargetError
from omniweave_core.events import traceparent
from omniweave_core.model.block import Cite
from omniweave_core.model.enums import Quote
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.card import CompileCard
from omniweave_core.out.carrier import parse_selector
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.cites import CitedBlock
from omniweave_core.out.compile import check
from omniweave_core.out.constructs import Disposition, RoundTrip
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import JOB_SCHEMA, ILBundle, Job, JobDeterminism
from omniweave_core.out.ledger import FrozenLedger, LedgerRow, slot
from omniweave_core.out.plan import Plan, UnitOutcome, classify_and_assert
from omniweave_core.out.roundtrip import (
    Failure,
    ILElement,
    LawResult,
    ReadBlock,
    applicable,
    r1,
    r2,
    r4a,
    r4b,
    r5,
    r7,
)
from omniweave_core.store.fragment import records_of
from omniweave_ports import ArtifactKind
from omniweave_ports.types import PartSelector, UnitRef

from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_conform.result import Verdict

if TYPE_CHECKING:
    from typing import BinaryIO

    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.out.compile import CompileV1
    from omniweave_core.out.constructs import Construct, ConstructTable
    from omniweave_core.out.ledger import AssetLedger
    from omniweave_ports import DriverResult, ParseV1

__all__ = ["ASSETS", "CITES", "EDIT", "GOLDEN_CLOCK_NS", "LawOutcome", "TargetReport", "run_target"]

CITES: Final = "cites.json"
ASSETS: Final = "assets"
EDIT: Final = "edit"
"""Ruling 16: the golden's edited units, one IL file each, which R4(b) recompiles."""
_COPIED: Final = frozenset({UnitOutcome.PASSTHROUGH, UnitOutcome.CLONED_PASSTHROUGH})
GOLDEN_CLOCK_NS: Final = 1_700_000_000_000_000_000
"""Ruling 10: the instant every golden compile's `job.json` names."""
_TRACEPARENT: Final = traceparent("0" * 31 + "1", "0" * 15 + "1")
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
    reader: ParseV1 | None = None,
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
    ledger = _golden_ledger(golden / ASSETS, bundle)
    cites = _FixtureCites(golden / CITES)
    plan = _plan(
        target,
        bundle,
        constructs,
        checked.status,
        ledger=ledger,
        pins=_pins(bundle, compiler, cites),
    )
    Job(JOB_SCHEMA, plan, _TRACEPARENT, JobDeterminism(GOLDEN_CLOCK_NS)).write(job)
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
            ledger=ledger,
            reader=reader,
            kind_map_path=Path(str(card.source)).parent / str(round_trip.get("kind_map", "")),
            projects=bool(round_trip.get("project", False)),
            part_of=CompileCard.of(card).part_of,
            golden=golden,
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
    ledger: AssetLedger,
    reader: ParseV1 | None,
    kind_map_path: Path,
    projects: bool,
    part_of: Callable[[int], str],
    golden: Path,
) -> LawOutcome:
    if law == "r2" and reader is not None:
        return _r2(
            compiler=compiler,
            plan=plan,
            bundle=bundle,
            constructs=constructs,
            ledger=ledger,
            reader=reader,
            kind_map_path=kind_map_path,
            workdir=workdir,
        )
    if law == "r1":
        first = _compile(compiler, plan, bundle, ledger, workdir / "r1-a")
        second = _compile(compiler, plan, bundle, ledger, workdir / "r1-b")
        return LawOutcome("r1", "checked", r1(declared, first[0], second[0]))
    if law == "r7":
        return LawOutcome("r7", "checked", _r7(compiler, plan, bundle, ledger, workdir / "r7"))
    if law == "r5":
        return _r5(constructs, compiler, bundle, job, workdir / "r5")
    if law == "r4":
        return _r4(
            compiler=compiler,
            plan=plan,
            bundle=bundle,
            constructs=constructs,
            ledger=ledger,
            part_of=part_of,
            edits=golden / EDIT,
            job=job,
            workdir=workdir / "r4",
        )
    reasons = {
        "r6": "R6 judges a source artefact's unrepresented parts; a golden fixture is IL alone",
    }
    if not projects:
        reasons["r3"] = (
            "R3 compiles project(read_back(compile(I))), and the card says "
            "[compile.round_trip] project = false"
        )
    reason = reasons.get(law, f"{law} reads the artefact back, and no read_back driver was given")
    return LawOutcome(law, "unknown", reason=reason)


def _r4(
    *,
    compiler: CompileV1,
    plan: Plan,
    bundle: ILBundle,
    constructs: ConstructTable,
    ledger: AssetLedger,
    part_of: Callable[[int], str],
    edits: Path,
    job: Path,
    workdir: Path,
) -> LawOutcome:
    """Ruling 16: R4(a) over a recompile with zero edits, and R4(b) over the golden's edit."""
    _compile(compiler, plan, bundle, ledger, workdir / "source")
    source = _members(workdir / "source" / f"{plan.slug}.artefact")
    outcomes, copied = _recompiled(
        compiler=compiler,
        plan=_edit_of(plan, bundle, bundle, part_of),
        bundle=bundle,
        ledger=ledger,
        source=source,
        part_of=part_of,
        scratch=workdir / "zero",
    )
    failures = list(r4a(outcomes, copied).failures)
    if not edits.is_dir():
        result = LawResult("r4", tuple(failures))
        if failures:
            return LawOutcome("r4", "checked", result)
        return LawOutcome(
            "r4",
            "unknown",
            result,
            f"R4(a) holds; R4(b) recompiles the golden's {EDIT}/, which it does not carry",
        )
    shutil.copytree(job, workdir / "edit")  # its job.json too: a target may read the clock
    il = workdir / "edit" / "il"
    names = sorted(p.name for p in edits.iterdir() if p.is_file())
    for name in names:
        shutil.copyfile(edits / name, il / name)
    edited = ILBundle.load(il, carrier=compiler.carrier, constructs=constructs)
    touched = frozenset(u.id for u in edited.units if u.il_path.removeprefix("il/") in names)
    sealed = {u.id: u.nsig for u in bundle.units}
    failures += [
        Failure("unedited", u.id, f"{EDIT}/ leaves {u.id} as it was: R4(b) holds of no edit")
        for u in edited.units
        if u.id in touched and u.nsig == sealed[u.id]
    ]
    outcomes, copied = _recompiled(
        compiler=compiler,
        plan=_edit_of(plan, bundle, edited, part_of),
        bundle=edited,
        ledger=ledger,
        source=source,
        part_of=part_of,
        scratch=workdir / "edited",
    )
    failures += r4b(outcomes, {u: frozenset({u}) for u in outcomes}, touched).failures
    kept = {u: o for u, o in outcomes.items() if o in _COPIED}
    failures += r4a(kept, copied).failures
    return LawOutcome("r4", "checked", LawResult("r4", tuple(failures)))


def _edit_of(plan: Plan, source: ILBundle, edited: ILBundle, part_of: Callable[[int], str]) -> Plan:
    """Ruling 16: the next generation of `plan`, each unit edited from its own in `source`."""
    sealed = {u.id: u for u in source.units}
    units = tuple(
        dataclasses.replace(
            u,
            source_part=part_of(sealed[u.id].ord),
            source_nsig=sealed[u.id].nsig,
            source_ord=sealed[u.id].ord,
        )
        for u in edited.units
    )
    return dataclasses.replace(plan, artifact_gen=plan.artifact_gen + 1, units=units)


def _recompiled(
    *,
    compiler: CompileV1,
    plan: Plan,
    bundle: ILBundle,
    ledger: AssetLedger,
    source: Mapping[str, bytes],
    part_of: Callable[[int], str],
    scratch: Path,
) -> tuple[dict[str, UnitOutcome], dict[str, tuple[str, str]]]:
    """Ruling 16: each unit's outcome as the receipt reports it, and each copied unit's part
    beside its source's."""
    _, receipt = _compile(compiler, plan, bundle, ledger, scratch)
    members = _members(scratch / f"{plan.slug}.artefact")
    outcomes = dict(receipt.units)
    copied: dict[str, tuple[str, str]] = {}
    for unit in plan.units:
        new = members.get(part_of(unit.ord))
        old = source.get(part_of(unit.source_ord or 0))
        if outcomes[unit.id] in _COPIED and new is not None and old is not None:
            copied[unit.id] = (_sha(new), _sha(old))
    return outcomes, copied


def _members(path: Path) -> dict[str, bytes]:
    """Ruling 16: a package's members by name; none for an artefact that is not one."""
    try:
        with zipfile.ZipFile(path) as zf:
            return {info.filename: zf.read(info) for info in zf.infolist()}
    except zipfile.BadZipFile:
        return {}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _r2(
    *,
    compiler: CompileV1,
    plan: Plan,
    bundle: ILBundle,
    constructs: ConstructTable,
    ledger: AssetLedger,
    reader: ParseV1,
    kind_map_path: Path,
    workdir: Path,
) -> LawOutcome:
    """Ruling 13: the golden compiled once, read back, and R2 over its addressed elements."""
    if not kind_map_path.is_file():
        return LawOutcome("r2", "unknown", reason=f"no kind_map at {kind_map_path.name}")
    kind_map = {
        str(k): str(v)
        for k, v in tomllib.loads(kind_map_path.read_text(encoding="utf-8"))["kind"].items()
    }
    scratch = workdir / "r2"
    _compile(compiler, plan, bundle, ledger, scratch)
    body = (scratch / f"{plan.slug}.artefact").read_bytes()
    store = MemoryBlobStore(scratch / "read")
    unit = UnitRef(
        uri=f"golden:{plan.slug}",
        part="",
        content_sha256=store.add(body),
        byte_len=len(body),
    )
    io = make_io(store, scratch / "read-io")
    fragment = reader.parse(unit, PartSelector(), io)
    blocks = [
        ReadBlock(
            el=(record.get("x") or {}).get("x.ow.el"),
            kind=str(record.get("kind")),
            text=record.get("text"),
            cites=frozenset((record.get("x") or {}).get("x.ow.cites", ())),
        )
        for ref in fragment.produced
        if ref.kind == ArtifactKind.DOC_FRAGMENT
        for record in records_of(_bytes(ref, io))
        if record.get("t") == "block"
    ]
    return LawOutcome(
        "r2", "checked", r2(_addressed(bundle, compiler, constructs), blocks, kind_map)
    )


def _addressed(
    bundle: ILBundle, compiler: CompileV1, constructs: ConstructTable
) -> list[ILElement]:
    """Ruling 13: every element carrying `data-ow-el`, under its construct."""
    rows = [
        (row.id, parse_selector(row.selector, constructs.carrier))
        for row in constructs.rows
        if row.disposition is Disposition.NATIVE
    ]
    out: list[ILElement] = []
    for unit in bundle.units:
        doc = compiler.carrier(unit.il_path, bundle.text(unit.il_path))
        for node in doc.select(_EL_SELECTOR):
            construct = next(
                (rid for rid, s in rows if s.kind == "element" and s.matches(node)), ""
            )
            out.append(
                ILElement(
                    el=node.el or "",
                    construct=construct,
                    visible_text=doc.visible_text(node),
                    cites=frozenset((node.attr("data-ow-cite") or "").split()),
                )
            )
    return out


def _bytes(ref: Any, io: Any) -> bytes:
    if ref.inline is not None:
        return ref.inline
    with io.blobs.open((ref.blob or "").removeprefix("cas://")) as handle:
        return handle.read()


def _plan(
    target: str,
    bundle: ILBundle,
    constructs: ConstructTable,
    gate: GateStatus,
    *,
    ledger: AssetLedger,
    pins: Mapping[Cite, int],
) -> Plan:
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
        cites=dict(pins),
        gate_status=gate,
        il_digest=bundle.il_digest,
        constructs_digest=constructs.digest(),
        ledger_digest=ledger.digest(),
        brief_digest=_BRIEF.digest(),
        card_sha256="sha256:" + "0" * 64,
    )


def _compile(
    compiler: CompileV1, plan: Plan, bundle: ILBundle, ledger: AssetLedger, scratch: Path
) -> tuple[dict[str, str], Any]:
    """Ruling 4: one in-process compile, and the digests R1 compares."""
    io = make_io(MemoryBlobStore(scratch / "kit"), scratch / "io")
    body = _artefact(compiler.lower(plan, bundle, ledger, io), io)
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


def _r7(
    compiler: CompileV1, plan: Plan, bundle: ILBundle, ledger: AssetLedger, scratch: Path
) -> LawResult:
    """Ruling 5: the classifier places every unit, and the receipt says the same."""
    try:
        classified = classify_and_assert(plan, baked={}, visual_changed=lambda _u: True)
    except TargetError as exc:
        return LawResult("r7", (Failure("unclassified", plan.slug, str(exc)),))
    outcomes = {u: c.outcome for u, c in classified.items()}
    result = r7([u.id for u in plan.units], outcomes)
    _, receipt = _compile(compiler, plan, bundle, ledger, scratch)
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
        f"clauses 3 and 4 hold ({_address_row(constructs)} exempt from clause 4: "
        "canonical_subtree drops the "
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


class _GoldenBlobs:
    """Ruling 9: the fixture's asset files, as the blob reader a `FrozenLedger` opens."""

    def __init__(self, blobs: Mapping[str, bytes]) -> None:
        self._blobs = dict(blobs)

    def open(self, digest: str) -> BinaryIO:
        return io_module.BytesIO(self._blobs[digest])


def _golden_ledger(directory: Path, bundle: ILBundle) -> FrozenLedger:
    """Ruling 9: each file under `assets/`, frozen as an `image` for the first unit that slots
    it (the roster's first when none does)."""
    blobs: dict[str, bytes] = {}
    rows: list[LedgerRow] = []
    files = sorted(directory.iterdir()) if directory.is_dir() else []
    for n, path in enumerate(files, 1):
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        users = [u.id for u in bundle.units if slot(sha) in bundle.text(u.il_path)]
        blobs[sha] = data
        rows.append(LedgerRow(n, sha, slot(sha), "image", (users or [bundle.units[0].id])[0]))
    return FrozenLedger(rows, _GoldenBlobs(blobs))


def _pins(bundle: ILBundle, compiler: CompileV1, cites: _FixtureCites) -> dict[Cite, int]:
    """Ruling 11: every cite the IL names, at the generation `cites.json` resolves it at."""
    tokens = sorted(
        {
            token
            for unit in bundle.units
            for node in compiler.carrier(unit.il_path, bundle.text(unit.il_path)).select(
                "@data-ow-cite"
            )
            for token in (node.attr("data-ow-cite") or "").split()
        }
    )
    found = cites.by_cites(tuple(tokens))
    return {Cite(b.cite): b.doc_gen for b in found.values() if b is not None}


def _address_row(constructs: ConstructTable) -> str:
    """Ruling 12: the table's own name for its `@data-ow-el` row."""
    return next((r.id for r in constructs.rows if r.selector == _EL_SELECTOR), _EL_SELECTOR)
