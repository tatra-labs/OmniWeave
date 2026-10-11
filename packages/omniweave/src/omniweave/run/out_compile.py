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
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import TargetError, UsageError
from omniweave_core.out.cites import verbatim
from omniweave_core.out.compile import CompileV1
from omniweave_core.out.gate import GateStatus, exit_code, gate_status
from omniweave_core.out.job import ILBundle
from omniweave_core.out.marker import assert_clean
from omniweave_core.out.plan import Classified, OutUnit, Plan, classify_and_assert
from omniweave_core.out.receipt import Receipt
from omniweave_core.out.report import OutReport, parse_digest, report_path
from omniweave_core.out.retain import freeze
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
from omniweave_ports import ArtifactKind

if TYPE_CHECKING:
    from omniweave_core.blobs import BlobStore
    from omniweave_core.out.cites import CitedBlock, CiteResolver
    from omniweave_core.out.constructs import ConstructTable
    from omniweave_core.store.ledger import SqliteAssetLedger
    from omniweave_ports import DriverIO, DriverResult

__all__ = ["CompileHost", "Compiled", "compile_artifact"]

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
    io: DriverIO,
    output_root: Path,
    baked: Mapping[str, str] | None = None,
    visual_changed: Callable[[OutUnit], bool] | None = None,
) -> Compiled:
    """09 section 2's call order from the gate to the seal (rulings 1-8)."""
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
    ledger.assert_frozen(_slots(bundle))
    cited = _cited(bundle, compiler)
    resolved = cites.by_cites(tuple(sorted({c for _, _, tokens, _, _ in cited for c in tokens})))
    _all_resolve(resolved)

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

    result = compiler.lower(plan, bundle, ledger, io)
    body = _artefact(result, io)
    staged = Path(io.tmpdir) / f"{plan.slug}{host.suffix}"
    staged.write_bytes(body)
    receipt = compiler.postflight(str(staged), plan)
    classified = classify_and_assert(
        plan,
        baked=baked or {},
        visual_changed=visual_changed or (lambda _u: True),
    )
    _receipt_agrees(receipt, plan, body, classified, status)

    retained = freeze(bundle, blobs)
    with staged.open("rb") as handle:
        sha = blobs.put(handle).hex()
    receipt_bytes = (json.dumps(receipt.as_json(), sort_keys=True, indent=1) + "\n").encode()
    receipt_path = job_dir / "out" / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(receipt_bytes)
    report_bytes = report_path(job_dir, "final").read_bytes()
    draft = ArtifactDraft(
        key=key,
        artifact_gen=plan.artifact_gen,
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
                nsig=u.nsig or "",
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


def _artefact(result: DriverResult, io: DriverIO) -> bytes:
    """Ruling 6: exactly one `artifact` ref, read from inline bytes or the driver's CAS."""
    refs = [r for r in result.produced if r.kind == ArtifactKind.ARTIFACT]
    if len(refs) != 1:
        raise TargetError(
            f"lower() returned {len(refs)} artifact refs; a compile produces exactly one",
            symbol="OW_TARGET_PACKAGE_CORRUPT",
            fix="report the target: its lower() must return one artifact",
        )
    ref = refs[0]
    if ref.inline is not None:
        return ref.inline
    with io.blobs.open((ref.blob or "").removeprefix("cas://")) as handle:
        return handle.read()


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
