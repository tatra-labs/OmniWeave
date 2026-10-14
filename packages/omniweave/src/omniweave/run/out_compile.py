"""`compile_artifact()` -- the compile-time call order's second half, the runner's. **D755.**

09-generation.md section 2 prints the call order as "the runner's middleware order". D749's
`omniweave_core.out.compile.check()` is its first half, from `ILBundle.load()` to `gate_status()`.
This is the rest:

```
IF status != PASSED: STOP. lower() is not called.                           (OUT5, OUT23)
-> marker.assert_clean()             # AFTER the gate, BEFORE lower()       (OUT16)
-> restriction aggregate #2          # at compile time, the same SQL        (OUT11, DR17)
-> lookup_before_build(six digests)  # a hit reuses bytes + part_digest     (OUT12)
-> lower(plan, il, ledger, io)       # -> DriverResult, into io.tmpdir
-> postflight(artifact, plan)        # -> Receipt
-> classify_and_assert(plan)         # sum(UnitOutcome) == unit_count, else FATAL (OUT8)
-> seal: artifact + artifact_unit + artifact_asset + artifact_cite, sealed_at_ns
```

It lives in the runner, beside `dispatch.py`, rather than in `omniweave_core.out`. One reason is
that 09 calls it the runner's order and the seal is "the runner"'s row in 02-architecture.md's
compile walkthrough. The other is that the seal's rows are `omniweave_core.store.artifact`'s:
that module imports `omniweave_core.out`, so `out` importing it back would be a cycle.

## Rulings

1. **A closed gate is an answer, not an exception.** Like `check()`, this returns its status and
   09 section 15's exit: a release needs `passed`, a draft needs `manual-required`
   (`--accept-manual`, 09 section 9, and D748's receipt ruling 2), and anything else returns
   before `lower()` with nothing written. A draft asked of a gate that passed is a usage error:
   a draft receipt cannot carry `passed`, and the answer is a release. The gate is read from
   `validation/final.json` against the bundle as it loads now, so a report that describes
   other bytes is `stale`.
2. **The Plan's purity inputs must be the ones the compile computes.** A Plan whose `il_digest`,
   `constructs_digest` or `ledger_digest` differs from the bundle's, the table's or the ledger's
   was made against other inputs and is `stale`. The purity key is built from the computed
   values, so a stale Plan can never select another compile's bytes.
3. **Preflight's framework half raises.** The checks are the three rosters (`OW-T-507`), every
   `asset-slot:` frozen (`OW-T-506`, preflight check 2), and every cite resolving
   (`OW-T-101`). 09 says "a row written by a compile is never NULL", and section 5.1 makes
   preflight a raise, not a finding.
4. **Restriction aggregate #2 runs over the rows the seal would write.** It reads the ledger's
   asset ids and the resolved cites' block ids with D751's one statement. A barred item returns
   `restricted`, exit 6, naming every offending asset and cite, and nothing is lowered.
5. **The lookup comes before `lower()`, and a hit lowers nothing.** It returns the earlier
   compile's row and places its bytes again from CAS if they are missing, because a hit "reuses
   bytes + part_digest" and never recompiles (OUT12).
6. **The artefact is one `artifact` ref, and the receipt must describe it.** `lower()` returns
   exactly one `ArtifactKind.ARTIFACT` ref. Its bytes are written to `io.tmpdir` for
   `postflight()`. The receipt is then refused unless its target, slug, generation and delivery
   are the Plan's, its `output` names those bytes' length and sha256, and its per-unit outcomes
   are exactly the classifier's. The framework classifies and the target reports, so a
   disagreement is `OW-T-005` (OUT8).
7. **Cite rows are read from the IL, and only the store proves verbatim.** 09 section 10 prints
   `data-ow-cite` and never the attribute that carries a citation's `kind` or span. So a target
   that declares them (`data-ow-cite-kind`, `data-ow-cite-span="a:b"`) has them read. Otherwise a
   row is `derived` with no span, the weakest claim. `verbatim` is set only where
   `out.cites.verbatim()` proves it, on a `quote` with a span.
8. **The artefact goes into CAS before the seal, and onto `output_root` after it.** 09 section 2:
   "nothing before `seal` touches `output_root`". The bytes are a CAS object (so a hit can
   re-place them), the row names `<slug>@<gen>/<slug><suffix>`, and the placed copy is written to a
   sibling and renamed. The receipt lands at `out/receipt.json` in the JobDir, and the row stores
   the sha256 of exactly those bytes.
9. **D756: once preflight check 3 holds, `plan.units` are the bundle's** (09 section 3.7 note
   4). Each unit's `nsig` and `manual_reason` are copied from the parse the gate was decided on,
   so the classifier and the seal never read a Plan's stale or absent copy. A unit the carrier
   refused has no `nsig`, and `classify_and_assert()` raises `OW-T-005` for it.
10. **D770: `CompileHost.of()` reads a real run's host off the card.** The media type and
    suffix are `[compile]`'s, the stamp is the OR of the card's licence tables'
    restriction bits, the producer is the store's row, and the policy's `barred_mask`
    is 0 until a policy carries one.
11. **D772: `lower()` and `postflight()` are a `Lowering`, and where it runs is the caller's.**
    `in_process()` runs the target here, staged in `io.tmpdir`: the conformance kit's seam and
    the tests'. `CompileWorker` runs it in an S4 worker, launched for one compile and stopped
    after it, because every compile card asks for `subproc` (04 section 6.1). The worker reads the
    JobDir against the Plan's digests (D771), so a `Lowering` takes the Plan this call order
    refreshed and the JobDir it gated.
12. **A worker's answer is read back as the in-process one is.** Its one `RESULT` names one
    `artifact` and one `receipt` ref, both read from the run's CAS, and the receipt is built
    again (`Receipt.from_json`). A failure whose message is a refusal raises that refusal under
    its own symbol. Any other failure (a crash, a timeout, a resource limit, a driver bug) is
    `OW_TARGET_COMPILE_FAILED`, naming its class. Nothing is sealed either way.
13. **The worker's output ceiling is `MAX_CONTAINER_TOTAL_BYTES`.** No limit names an artefact's
    size, and an artefact is the container a parse reads back: a compile that wrote more than a
    parse accepts would be one `ow out verify` could not open.
14. **D773: the Plan's `gate_status` is the gate this call order decided.** A scaffolded Plan
    says `not-provided` (`out.job` ruling 26), and the target writes its receipt's gate from the
    Plan, so the Plan `lower()` sees carries the status the report gave, beside the units
    ruling 9 refreshes.
15. **D773: a run's CAS is the corpus store's sibling `cas/`**, the directory `ingest` writes,
    created on first use: a store that was only migrated has none, and the worker writes the
    artefact into it before the seal.
16. **D773: a CLI compile's Plan is `job.json`'s, with what the compile computes put in.**
    A scaffolded Plan carries the scaffold's `il_digest` and an empty ledger's digest (`out.job`
    ruling 26), so `plan_of()` puts in the bundle's, the table's and the ledger's, and the
    delivery `--accept-manual` asks for. Ruling 2 still holds a Plan a caller computed itself.
17. **D775: the Brief is retained beside the IL, before the seal.** `out.retain.freeze_brief()`
    puts the Plan's Brief into CAS as `brief_digest`'s preimage, so the row's `brief_digest`
    names the Brief this compile read. A lookup hit retains nothing: the compile it reuses
    already did.
18. **D783: the Plan `lower()` sees carries the pinned cites.** 09 section 3.7 prints
    `Plan.cites` as each cite token's `doc_gen`, *"PINNED at plan time"*, and nothing filled
    it: a scaffolded Plan's map is empty, because the IL is not yet written. This call order's
    resolution is the pin, so the map is each resolved block's canonical cite and the
    generation it resolved at, the one the seal's `artifact_cite` rows carry. A target that
    embeds its citations (docx) reads them from the Plan, so the part it writes and the rows the
    store keeps name the same generations.
19. **D809: a copied unit's part is its parent's, byte for byte, or nothing is sealed.** 09
    section 5.5 defines `passthrough` as the source's container part copied, its sha256
    "asserted equal to the source's", and the classifier decides it from the nsig alone. So
    for an edit (`Plan.parent_gen`) of a target whose card names its units' parts
    (`unit_part`), the parent's artefact is read from CAS. Each `passthrough` or
    `cloned_passthrough` unit's part must then be byte for byte the part its `source_ord`
    lowered to. A part that moved, or that either package lacks, is
    `OW_TARGET_COPY_MOVED` (`OW-T-530`), R4(a)'s failures named.
20. **D809: the row names the generation it edits**, `parent_artifact_gen`, from
    `Plan.parent_gen`. A create names none.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import TargetError, UsageError
from omniweave_core.host import subproc
from omniweave_core.limits import MAX_CONTAINER_TOTAL_BYTES
from omniweave_core.model.block import Cite
from omniweave_core.out.card import part_of
from omniweave_core.out.cites import verbatim
from omniweave_core.out.compile import CompileV1, artefact, ref_bytes, refusal_of
from omniweave_core.out.gate import GateStatus, exit_code, gate_status
from omniweave_core.out.job import ILBundle, Job, job_unit
from omniweave_core.out.marker import assert_clean
from omniweave_core.out.plan import Classified, OutUnit, Plan, UnitOutcome, classify_and_assert
from omniweave_core.out.receipt import Receipt
from omniweave_core.out.report import OutReport, parse_digest, report_path
from omniweave_core.out.retain import freeze, freeze_brief
from omniweave_core.out.roundtrip import r4a
from omniweave_core.store.artifact import (
    CITE_KINDS,
    ArtifactDraft,
    ArtifactRow,
    CiteRow,
    PureKey,
    Restricted,
    Sealed,
    SqliteArtifactStore,
    UnitRow,
)
from omniweave_ports import ArtifactKind, Isolation

from omniweave.run.pipeline import compile_host

if TYPE_CHECKING:
    from omniweave_core.blobs import BlobStore
    from omniweave_core.canonical import JsonValue
    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.out.card import CompileCard
    from omniweave_core.out.cites import CitedBlock, CiteResolver
    from omniweave_core.out.constructs import ConstructTable
    from omniweave_core.out.ledger import AssetLedger, BlobReader
    from omniweave_core.store.ledger import SqliteAssetLedger
    from omniweave_ports import DriverIO

__all__ = [
    "CompileHost",
    "CompileWorker",
    "Compiled",
    "Lowered",
    "Lowering",
    "compile_artifact",
    "in_process",
    "lowered",
    "plan_of",
    "store_cas",
]

_SLOT: Final = "asset-slot:"
_FIX_CHECK: Final = "ow out check --stage final"


@dataclass(frozen=True, slots=True)
class CompileHost:
    """What the runner resolved before the call order: the driver, its card's stamp, the policy."""

    compile_driver: str
    media_type: str
    suffix: str
    """The artefact's file suffix, `.pptx`: the row's path is `<slug>@<gen>/<slug><suffix>`."""
    producer_id: int
    restriction_bits: int
    """The card's stamp (INV-16); the seal ORs in every source's."""
    barred_mask: int
    """The effective policy's `restriction_bits` mask (14-security.md); 0 bars nothing."""
    unit_part: str = ""
    """Ruling 19: the member each unit lowers to, `[compile.round_trip] unit_part`."""

    @classmethod
    def of(
        cls,
        card: DriverCard,
        compiled: CompileCard,
        *,
        producer_id: int,
        barred_mask: int = 0,
    ) -> CompileHost:
        """Ruling 10 (D770): every field a real run reads off the card, or is handed.

        The media type and suffix are the card's `[compile]` keys. The restriction bits are
        the card's stamp (INV-16): the OR over its code and weights licence tables, as
        `drivers.licence.restriction_bits()` reads one. `producer_id` is the store's row
        (`store.artifact.ensure_producer`). `barred_mask` is the policy's, and no shipped
        policy carries one yet (09 section 7.3 leaves it to 14, which prints none), so it
        defaults to 0, which bars nothing.
        """
        from omniweave_core.drivers.licence import restriction_bits  # noqa: PLC0415

        bits = restriction_bits(card.licence_code)
        if card.licence_weights is not None:
            bits |= restriction_bits(card.licence_weights)
        return cls(
            compile_driver=compiled.driver,
            media_type=compiled.media_type,
            suffix=compiled.suffix,
            producer_id=producer_id,
            restriction_bits=bits,
            barred_mask=barred_mask,
            unit_part=compiled.unit_part,
        )


@dataclass(frozen=True, slots=True)
class Compiled:
    """What one compile returns: its gate, its exit, and the sealed row when there is one."""

    status: GateStatus
    exit: int
    sealed: Sealed | None = None
    path: Path | None = None
    receipt: Receipt | None = None
    restricted: tuple[Restricted, ...] = ()


def compile_artifact(
    job_dir: Path,
    compiler: CompileV1,
    plan: Plan,
    *,
    host: CompileHost,
    constructs: ConstructTable,
    ledger: SqliteAssetLedger,
    cites: CiteResolver,
    artifacts: SqliteArtifactStore,
    blobs: BlobStore,
    lowering: Lowering,
    output_root: Path,
    baked: Mapping[str, str] | None = None,
    visual_changed: Callable[[OutUnit], bool] | None = None,
) -> Compiled:
    """09 section 2's call order from the gate to the seal (rulings 1-8, 11)."""
    bundle = ILBundle.load(job_dir / "il", carrier=compiler.carrier, constructs=constructs)
    report = OutReport.load(report_path(job_dir, "final"))
    status, _ = gate_status(report, parse_digest(bundle.il_digest))
    if plan.delivery == "draft" and status is GateStatus.PASSED:
        raise UsageError(
            "a draft is --accept-manual's answer to a manual-required gate, and this gate passed",
            fix=f"ow out compile --target {plan.target}   # a release",
        )
    if status not in _ALLOWED[plan.delivery]:
        return Compiled(status, exit_code(status, report))
    if (plan.il_digest, plan.constructs_digest, plan.ledger_digest) != (
        bundle.il_digest,
        constructs.digest(),
        ledger.digest(),
    ):
        return Compiled(GateStatus.STALE, exit_code(GateStatus.STALE, report))

    assert_clean(bundle)
    _same_roster(plan, bundle)
    plan = replace(
        plan,
        units=tuple(
            replace(mine, nsig=theirs.nsig, manual_reason=theirs.manual_reason)
            for mine, theirs in zip(plan.units, bundle.units, strict=True)
        ),
        gate_status=status,
    )
    ledger.assert_frozen(_slots(bundle))
    cited = _cited(bundle, compiler)
    resolved = cites.by_cites(tuple(sorted({c for _, _, tokens, _, _ in cited for c in tokens})))
    _all_resolve(resolved)
    pinned = {Cite(b.cite): b.doc_gen for b in resolved.values() if b is not None}
    plan = replace(plan, cites=dict(sorted(pinned.items())))

    restricted = artifacts.restricted(
        asset_ids=[r.asset_id for r in ledger.rows()],
        block_ids=[b.block_id for b in resolved.values() if b is not None],
        barred_mask=host.barred_mask,
    )
    if restricted:
        closed = GateStatus.RESTRICTED
        return Compiled(closed, exit_code(closed, report), restricted=restricted)

    key = PureKey(
        target=plan.target,
        slug=plan.slug,
        delivery=plan.delivery,
        il_digest=bundle.il_digest,
        constructs_digest=constructs.digest(),
        ledger_digest=ledger.digest(),
        card_sha256=plan.card_sha256,
        brief_digest=plan.brief_digest or None,
        toolchain_digest=plan.toolchain_digest,
    )
    earlier = artifacts.lookup(key)
    if earlier is not None:
        return Compiled(status, 0, Sealed(earlier, hit=True), _place(earlier, blobs, output_root))

    done = lowering(job_dir, plan, bundle, ledger)
    body, receipt = done.body, done.receipt
    classified = classify_and_assert(
        plan,
        baked=baked or {},
        visual_changed=visual_changed or (lambda _u: True),
    )
    _receipt_agrees(receipt, plan, body, classified, status)
    _copies_hold(plan, classified, body, host.unit_part, artifacts=artifacts, blobs=blobs)

    retained = freeze(bundle, blobs)
    freeze_brief(plan.brief, blobs)
    sha = blobs.put(BytesIO(body)).hex()
    receipt_bytes = receipt.to_bytes()
    receipt_path = job_dir / "out" / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(receipt_bytes)
    report_bytes = report_path(job_dir, "final").read_bytes()
    draft = ArtifactDraft(
        key=key,
        artifact_gen=plan.artifact_gen,
        parent_artifact_gen=plan.parent_gen,
        origin="authored",
        compile_driver=host.compile_driver,
        media_type=host.media_type,
        path=f"{plan.slug}@{plan.artifact_gen}/{plan.slug}{host.suffix}",
        sha256="sha256:" + sha,
        byte_len=len(body),
        part_digest="sha256:" + receipt.part_digest,
        il_store_ref=retained.il_store_ref,
        determinism=tuple(d.value for d in receipt.determinism),
        gate_status=status,
        report_sha256="sha256:" + hashlib.sha256(report_bytes).hexdigest(),
        receipt_sha256="sha256:" + hashlib.sha256(receipt_bytes).hexdigest(),
        producer_id=host.producer_id,
        units=tuple(
            UnitRow(
                unit=u.id,
                ord=u.ord,
                outcome=classified[u.id].outcome,
                il_path=u.il_path,
                il_sha256=retained.units[u.id],
                nsig=u.nsig or "",  # a unit with no nsig is OW-T-005 above
                reason=classified[u.id].reason,
            )
            for u in plan.units
        ),
        assets=ledger.joins(),
        cites=_cite_rows(cited, resolved),
        restriction_bits=host.restriction_bits,
        degradations=receipt.degradations,
    )
    sealed = artifacts.seal(draft)
    return Compiled(status, 0, sealed, _place(sealed.row, blobs, output_root), receipt)


@dataclass(frozen=True, slots=True)
class Lowered:
    """What a `Lowering` returns: the artefact's bytes and the receipt `postflight()` wrote."""

    body: bytes
    receipt: Receipt


class Lowering(Protocol):
    """Ruling 11: `lower()` then `postflight()` over the gated bundle, wherever the target runs."""

    def __call__(
        self, job_dir: Path, plan: Plan, bundle: ILBundle, ledger: AssetLedger
    ) -> Lowered: ...


def in_process(compiler: CompileV1, io: DriverIO, suffix: str) -> Lowering:
    """Ruling 11: the target in this process, its artefact staged in `io.tmpdir`."""

    def lowering(job_dir: Path, plan: Plan, bundle: ILBundle, ledger: AssetLedger) -> Lowered:
        del job_dir
        result = compiler.lower(plan, bundle, ledger, io)
        _, body = artefact(result, io.blobs)
        staged = Path(io.tmpdir) / f"{plan.slug}{suffix}"
        staged.write_bytes(body)
        return Lowered(body, compiler.postflight(str(staged), plan))

    return lowering


_HELLO_DEADLINES: Final = subproc.Deadlines(progress_ms=0, wall_ms_hard=60_000, deadline_ms=0)
"""The `HELLO` exchange's bound, the parse Operator's: a minute to start and activate."""


@dataclass(frozen=True, slots=True)
class CompileWorker:
    """Ruling 11: the target in an S4 worker, launched for one compile and stopped after it.

    The caller names what only the caller knows: the interpreter, the environment the worker
    inherits (`operators.parse.worker_env()`), the transport's address and the scratch root.
    `blobs` is the run's CAS, which the worker writes the artefact and the receipt into.
    """

    card: DriverCard
    effective_config: Mapping[str, JsonValue]
    blobs: BlobStore
    tmp: Path
    settings: subproc.HostSettings
    executable: str
    env: Mapping[str, str]
    address: str
    now_ms: Callable[[], int]
    deadline_ms: int = 0
    spawn: Callable[..., subproc.WorkerProcess] = field(default=subproc.spawn_worker)

    def __call__(self, job_dir: Path, plan: Plan, bundle: ILBundle, ledger: AssetLedger) -> Lowered:
        del bundle, ledger  # the worker loads both from the JobDir, held to the Plan's digests
        job = replace(Job.load(job_dir), plan=plan)
        unit = job_unit(job)
        spec = self.card.isolation
        worker = self._launch(job_dir)
        try:
            report = compile_host(
                worker,
                subproc.Invocation(
                    invoke_id=f"compile-{unit.content_sha256[:16]}",
                    units=(unit,),
                    deadline_ms=self.deadline_ms,
                    budget_micros=0,
                    job=job.as_json(),
                    job_dir=str(job_dir),
                ),
                deadlines=subproc.Deadlines(
                    progress_ms=spec.progress_ms,
                    wall_ms_hard=spec.wall_ms_hard,
                    deadline_ms=self.deadline_ms,
                ),
                memory_mb=spec.memory_mb,
            )
        finally:
            worker.stop()
        return lowered(report, self.blobs)

    def _launch(self, job_dir: Path) -> subproc.Worker:
        card = self.card
        self.tmp.mkdir(parents=True, exist_ok=True)
        isolation, _shortfalls = subproc.grant_isolation(
            mode=Isolation.SUBPROC,
            batch_max_units=card.isolation.batch_max_units,
            platform=sys.platform,
            address_space_capped=sys.platform == "win32" and card.isolation.memory_mb > 0,
            net_blocked_requested=not card.hardware.needs_network,
            cpu_cap_requested=False,
            fd_cap_requested=False,
        )
        port = f"{card.identity.port.value}/{card.identity.port_major}"
        hello = {
            "port": port,
            "card_schema": card.card_schema,
            "card_sha256": card.card_sha256,
            "driver_id": card.identity.id,
            "effective_config": dict(self.effective_config),
            "roots": {"source_ro": str(job_dir), "tmp": str(self.tmp)},
            "blob_base": str(self.blobs.root),
            "isolation_granted": dict(isolation.as_header()),
            "traceparent": "",
            "max_output_bytes": MAX_CONTAINER_TOTAL_BYTES,
            "egress_mode": "granted",
            "card_source": card.source,
            "card_origin": card.origin,
        }
        worker, _ack = subproc.launch(
            subproc.WorkerKey(card.identity.id, sha256_canonical(dict(self.effective_config))),
            subproc.SpawnRequest(
                argv=subproc.worker_argv(self.executable, self.address),
                cwd=str(self.tmp),
                env=dict(self.env),
                address=self.address,
            ),
            hello=hello,
            expect={
                "driver_id": card.identity.id,
                "version": card.identity.version,
                "schema_version": card.identity.schema_version,
                "port": port,
            },
            deadlines=_HELLO_DEADLINES,
            settings=self.settings,
            now_ms=self.now_ms,
            memory_mb=card.isolation.memory_mb,
            spawn=self.spawn,
        )
        return worker


def plan_of(
    scaffolded: Plan,
    *,
    bundle: ILBundle,
    constructs: ConstructTable,
    ledger: AssetLedger,
    draft: bool,
) -> Plan:
    """Ruling 16: `job.json`'s Plan with what a compile computes put in, and the delivery asked."""
    return replace(
        scaffolded,
        delivery="draft" if draft else "release",
        il_digest=bundle.il_digest,
        constructs_digest=constructs.digest(),
        ledger_digest=ledger.digest(),
    )


def store_cas(store: Path) -> BlobStore:
    """Ruling 15: the corpus store's CAS, `ingest.CAS_DIR` beside it, created on first use."""
    from omniweave_core.blobs import BlobStore  # noqa: PLC0415 -- the runtime type, here only

    from omniweave.run.ingest import CAS_DIR  # noqa: PLC0415 -- one name for the directory

    root = store.parent / CAS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return BlobStore(root)


def lowered(report: subproc.InvokeReport, blobs: BlobReader) -> Lowered:
    """Ruling 12: the worker's one `RESULT` as the artefact and its receipt, or its failure."""
    result, failure = report.results[0], report.failures[0]
    if failure is not None:
        refused = refusal_of(failure.message)
        if refused is not None:
            raise refused
        raise _failed(f"{failure.failure_class.value}: {failure.message}")
    if result is None:
        raise _failed("the worker never answered the job's unit")
    _, body = artefact(result, blobs)
    receipts = [r for r in result.produced if r.kind == ArtifactKind.RECEIPT]
    if len(receipts) != 1:
        raise TargetError(
            f"the worker returned {len(receipts)} receipt refs; a compile returns exactly one",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: postflight() writes one receipt",
        )
    try:
        document = json.loads(ref_bytes(receipts[0], blobs))
    except ValueError as exc:
        raise TargetError(
            f"the worker's receipt is not JSON: {exc}",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: postflight() writes one receipt",
        ) from exc
    return Lowered(body, Receipt.from_json(document))


def _failed(detail: str) -> TargetError:
    return TargetError(
        f"the compile worker failed, and nothing was sealed: {detail}",
        symbol="OW_TARGET_COMPILE_FAILED",
        fix="ow explain OW-T-526",
    )


_ALLOWED: Final[Mapping[str, frozenset[GateStatus]]] = {
    "release": frozenset({GateStatus.PASSED}),
    "draft": frozenset({GateStatus.MANUAL_REQUIRED}),
}
"""Ruling 1: OUT5's one release status, and `--accept-manual`'s draft."""


def _same_roster(plan: Plan, bundle: ILBundle) -> None:
    """Preflight check 3: the Plan's roster is the bundle's, id for id and ord for ord."""
    want = [(u.id, u.ord) for u in plan.units]
    have = [(u.id, u.ord) for u in bundle.units]
    if want != have:
        raise TargetError(
            f"the plan's roster {want} is not the bundle's {have}",
            symbol="OW_TARGET_ROSTER_MISMATCH",
            fix=_FIX_CHECK,
        )


def _slots(bundle: ILBundle) -> set[str]:
    """Every `asset-slot:<sha256>` the bundle's units hold, read from the text (OUT9)."""
    found: set[str] = set()
    for unit in bundle.units:
        text = bundle.text(unit.il_path)
        start = text.find(_SLOT)
        while start != -1:
            found.add(text[start : start + len(_SLOT) + 64])
            start = text.find(_SLOT, start + 1)
    return found


_Cited = tuple[str, str, tuple[str, ...], str, tuple[str | None, str | None]]
"""One cited element: unit, el, cite tokens, visible text, and `(kind, span)` as written."""


def _cited(bundle: ILBundle, compiler: CompileV1) -> list[_Cited]:
    rows: list[_Cited] = []
    for unit in bundle.units:
        doc = compiler.carrier(unit.il_path, bundle.text(unit.il_path))
        for node in doc.select("@data-ow-cite"):
            tokens = tuple((node.attr("data-ow-cite") or "").split())
            if not tokens:
                continue
            if not node.el:
                raise TargetError(
                    f"{unit.il_path}: an element cites {' '.join(tokens)} and carries no "
                    "data-ow-el, so its citation row has no address",
                    symbol="OW_TARGET_IL_MALFORMED",
                    fix="ow out stamp",
                )
            facts = (node.attr("data-ow-cite-kind"), node.attr("data-ow-cite-span"))
            rows.append((unit.id, node.el, tokens, node.text_content(), facts))
    return rows


def _all_resolve(resolved: Mapping[str, CitedBlock | None]) -> None:
    missing = sorted(c for c, b in resolved.items() if b is None)
    if missing:
        raise TargetError(
            f"{len(missing)} cite(s) name no live block in this corpus: {', '.join(missing)}",
            symbol="OW_TARGET_CITE_UNRESOLVED",
            fix=f"ow open {missing[0]}",
        )


def _cite_rows(
    cited: list[_Cited],
    resolved: Mapping[str, CitedBlock | None],
) -> tuple[CiteRow, ...]:
    """Ruling 7: one row per (unit, el, cite); `verbatim` only where the predicate proves it."""
    rows: dict[tuple[str, str, str], CiteRow] = {}
    for unit, el, tokens, visible, (kind, span_text) in cited:
        if kind is not None and kind not in CITE_KINDS:
            raise TargetError(
                f"{unit}/{el}: data-ow-cite-kind {kind!r} is not one of {sorted(CITE_KINDS)}",
                symbol="OW_TARGET_IL_MALFORMED",
                fix=f"ow out check --stage unit --unit {unit}",
            )
        span = _span(unit, el, span_text) if len(tokens) == 1 else None
        for token in tokens:
            block = resolved[token]
            if block is None:  # pragma: no cover -- _all_resolve refused this before.
                continue
            claimed = kind or "derived"
            proved = claimed == "quote" and verbatim(visible, block, span)
            rows[unit, el, block.cite] = CiteRow(
                unit=unit,
                el=el,
                cite=block.cite,
                block_id=block.block_id,
                doc_gen=block.doc_gen,
                kind=claimed,  # type: ignore[arg-type]
                span_a=None if span is None else span[0],
                span_b=None if span is None else span[1],
                verbatim=proved,
            )
    return tuple(rows[k] for k in sorted(rows))


def _span(unit: str, el: str, text: str | None) -> tuple[int, int] | None:
    if text is None:
        return None
    a, sep, b = text.partition(":")
    if not sep or not a.isdigit() or not b.isdigit() or int(a) >= int(b):
        raise TargetError(
            f"{unit}/{el}: data-ow-cite-span {text!r} is not a:b with a < b",
            symbol="OW_TARGET_IL_MALFORMED",
            fix=f"ow out check --stage unit --unit {unit}",
        )
    return int(a), int(b)


def _receipt_agrees(
    receipt: Receipt,
    plan: Plan,
    body: bytes,
    classified: Mapping[str, Classified],
    status: GateStatus,
) -> None:
    """Ruling 6: the receipt describes this Plan, these bytes and the classifier's outcomes."""
    sha = hashlib.sha256(body).hexdigest()
    facts = {
        "target": (receipt.target, plan.target),
        "slug": (receipt.slug, plan.slug),
        "artifact_gen": (receipt.artifact_gen, plan.artifact_gen),
        "delivery": (receipt.delivery, plan.delivery),
        "gate_status": (receipt.gate_status, status),
        "output.bytes": (receipt.output.get("bytes"), len(body)),
        "output.sha256": (str(receipt.output.get("sha256", "")).removeprefix("sha256:"), sha),
    }
    wrong = {k: v for k, v in facts.items() if v[0] != v[1]}
    if wrong:
        named = "; ".join(
            f"{k} {got!r} is not {want!r}" for k, (got, want) in sorted(wrong.items())
        )
        raise TargetError(
            f"postflight's receipt does not describe this compile: {named}",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: postflight() must describe the artefact lower() produced",
        )
    said = {u: str(o) for u, o in receipt.units.items()}
    found = {u: str(c.outcome) for u, c in classified.items()}
    if said != found:
        raise TargetError(
            f"the receipt classifies units {said}, and the classifier says {found}",
            symbol="OW_TARGET_UNIT_UNCLASSIFIED",
            fix="report the target: the framework classifies, the receipt reports (OUT8)",
        )


_COPIED: Final = frozenset({UnitOutcome.PASSTHROUGH, UnitOutcome.CLONED_PASSTHROUGH})


def _copies_hold(
    plan: Plan,
    classified: Mapping[str, Classified],
    body: bytes,
    unit_part: str,
    *,
    artifacts: SqliteArtifactStore,
    blobs: BlobStore,
) -> None:
    """Ruling 19: each copied unit's part, byte for byte its parent's (R4(a) at the seal)."""
    if plan.parent_gen is None or not unit_part:
        return
    parent = artifacts.get(plan.slug, plan.parent_gen)
    with blobs.open(parent.sha256.removeprefix("sha256:")) as handle:
        source = _members(handle.read())
    members = _members(body)
    kept = {u: c.outcome for u, c in classified.items() if c.outcome in _COPIED}
    copied: dict[str, tuple[str, str]] = {}
    for unit in plan.units:
        new = members.get(part_of(unit_part, unit.ord))
        old = source.get(part_of(unit_part, unit.source_ord or 0))
        if unit.id in kept and new is not None and old is not None:
            copied[unit.id] = (hashlib.sha256(new).hexdigest(), hashlib.sha256(old).hexdigest())
    result = r4a(kept, copied)
    if not result.passed:
        raise TargetError(
            f"{plan.slug}@{plan.artifact_gen} copies from @{plan.parent_gen}, and "
            + "; ".join(f.msg for f in result.failures),
            symbol="OW_TARGET_COPY_MOVED",
            fix="ow explain OW-T-530",
        )


def _members(body: bytes) -> dict[str, bytes]:
    """Ruling 19: a package's members by name; none for bytes that are not one."""
    try:
        with zipfile.ZipFile(BytesIO(body)) as zf:
            return {info.filename: zf.read(info) for info in zf.infolist()}
    except zipfile.BadZipFile:
        return {}


def _place(row: ArtifactRow, blobs: BlobStore, output_root: Path) -> Path:
    """Ruling 8: the CAS object's bytes at `output_root/<row.path>`, written whole."""
    target = output_root / row.path
    sha = row.sha256.removeprefix("sha256:")
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.tmp")
    with blobs.open(sha) as source, staged.open("wb") as sink:
        shutil.copyfileobj(source, sink)
    staged.replace(target)
    return target
