"""`compile.text.owtext`, the reference `compile/1` target. **D758.**

09-generation.md section 12.5 and 18-api-sketch.md section 6.2, which prints this driver whole.
Ten constructs (`constructs.toml`), five rules, one text artefact. Its job is to exercise the
contract's refusal branches in CI without a browser: `citations = "sidecar"`, `fidelity = "none"`,
`bake = "unavailable"`, `measure = "none"`, one `normalize` row, one conditional
`forbidden_when` row, and one unreachable `bake` row.

## Rulings (where this departs from the sketch, and why)

1. **The cite rule batches, once per unit.** The sketch calls `ctx.cites.by_cite()` per token, and
   09 section 10 says the `order = 80` rule "calls the batch form once per unit". The rule is
   therefore at order 80, the cross-reference band, and calls `by_cites()` once. Its fix is
   `ow open <cite>`, because `RuleCtx` carries no Plan to name a corpus from.
2. **`postflight()`'s `part_digest` is the receipt's hex.** The sketch calls `.hex()` on
   `part_digest()`, which returns `sha256:<hex>`, so it goes through `receipt_part_digest()`
   (D748 ruling 3) instead.
3. **The unreachable `bake` row is refused in `lower()`, as preflight check 5.** 09 section 5.1
   says `bake` must be reachable for every unit that needs it, and `bake = "unavailable"`, so a
   unit carrying `text-shadow` is refused before a byte is written. The refusal is a
   `TargetError` carrying `OW_TARGET_BAKE_UNAVAILABLE`, because `DriverError` has no field for an
   `OW-T` code. Its message names both exits, `manual.BAKE_EXITS` (D876).
4. **`project()` refuses by name.** The card says `project = false`, so the call is
   `OW_TARGET_PROJECT_UNAVAILABLE` naming the card key: the honest answer for `fidelity = none`.
5. **The receipt reports the framework's classification** (D777). The sketch writes each unit
   `native`, or `manual_required` where a reason stands, which holds on the create path only.
   An edit (`ow out back`) carries each unit's source, and the framework then classifies it
   `passthrough`, `cloned_passthrough`, `patched` or `rebuilt`, and refuses a receipt that says
   otherwise (`OW_TARGET_UNIT_UNCLASSIFIED`, OUT8). So `postflight()` reports
   `classify_and_assert()`'s answer, with the runner's defaults: nothing baked, every edited
   unit visually changed. owtext rewrites every byte it emits, so it has no part to keep.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar, Final

from omniweave_core.errors import TargetError
from omniweave_core.model.doc import Doc
from omniweave_core.out import (
    ArtefactDeterminism,
    AssetLedger,
    CarrierDoc,
    CheckValue,
    Finding,
    ILBundle,
    Plan,
    Provenance,
    Receipt,
    RuleCtx,
    RuleSpec,
    Severity,
    TextMeasure,
    classify_and_assert,
    html_carrier,
    part_digest,
)
from omniweave_core.out.manual import BAKE_EXITS
from omniweave_core.out.receipt import receipt_part_digest
from omniweave_ports import (
    ArtifactRef,
    DriverIO,
    DriverResult,
    ProbeEnv,
    ProbeStatus,
    ProbeVerdict,
    Scalar,
)

from omniweave_conform.suites.target.owtext.normalizers import lower_ascii

__all__ = ["HERE", "OwTextCompiler"]

HERE: Final = Path(__file__).parent
"""The card, `constructs.toml`, `kind_map.toml` and `normalizers.py` sit beside this file."""


def rule_no_script(ctx: RuleCtx) -> Iterable[Finding]:
    """`elem.script` is `forbidden`: an INTRODUCED error, because the generator authored it."""
    assert ctx.doc is not None and ctx.unit is not None
    for n in ctx.doc.select("html|script"):
        yield Finding(
            code="OW_TARGET_SCRIPT_FORBIDDEN",
            severity=Severity.ERROR,
            provenance=Provenance.INTRODUCED,
            rule="owtext.elem.script@1",
            unit=ctx.unit.id,
            construct="elem.script",
            msg="<script> has no text mapping and is forbidden by owtext/1",
            fix="ow out constructs owtext --construct elem.script",
            at=n.at,
            el=n.el,
        )


def rule_id_with_style(ctx: RuleCtx) -> Iterable[Finding]:
    """The `forbidden_when` row: `attr.id` is native until a `<style>` block is in the unit."""
    assert ctx.doc is not None and ctx.unit is not None
    if not ctx.doc.select("html|style"):
        return
    for n in ctx.doc.select("@id"):
        yield Finding(
            code="OW_TARGET_ID_WITH_STYLE",
            severity=Severity.ERROR,
            provenance=Provenance.INTRODUCED,
            rule="owtext.attr.id@1",
            unit=ctx.unit.id,
            construct="attr.id",
            msg=f"id={n.attr('id')!r} with a <style> block present in the same unit",
            fix="ow out constructs owtext --construct attr.id",
            at=n.at,
            el=n.el,
        )


def rule_el_unique(ctx: RuleCtx) -> Iterable[Finding]:
    """OUT21: `data-ow-el` is minted once and refuses on a duplicate."""
    assert ctx.doc is not None and ctx.unit is not None
    seen: dict[str, str | None] = {}
    for n in ctx.doc.select("@data-ow-el"):
        el = n.attr("data-ow-el") or ""
        if el in seen:
            yield Finding(
                code="OW_TARGET_EL_DUPLICATE",
                severity=Severity.ERROR,
                provenance=Provenance.INTRODUCED,
                rule="owtext.attr.ow-el@1",
                unit=ctx.unit.id,
                construct="attr.ow-el",
                msg=f"data-ow-el={el!r} appears at {seen[el]} and {n.at}",
                fix="ow out constructs owtext --construct attr.ow-el",
                at=n.at,
                el=el,
            )
        seen[el] = n.at


def rule_class_lower(ctx: RuleCtx) -> Iterable[Finding]:
    """The `normalize` row: a WARNING carrying `canonical`, folded to one finding with a count."""
    assert ctx.doc is not None and ctx.unit is not None
    classes = [(n, n.attr("class") or "") for n in ctx.doc.select("@class")]
    bad = [n for n, value in classes if value != lower_ascii(value)]
    if bad:
        yield Finding(
            code="OW_TARGET_CLASS_NOT_LOWER",
            severity=Severity.WARNING,
            provenance=Provenance.INTRODUCED,
            rule="owtext.attr.class@1",
            unit=ctx.unit.id,
            construct="attr.class.upper",
            canonical="lower-case ASCII class names",
            msg=f"{len(bad)} class attributes are not lower-case ASCII",
            fix=f"ow out normalize --unit {ctx.unit.id} --construct attr.class.upper",
            count=len(bad),
            examples=tuple(n.attr("class") or "" for n in bad[:3]),
            at=bad[0].at,
            el=bad[0].el,
        )


def rule_cite_resolves(ctx: RuleCtx) -> Iterable[Finding]:
    """Ruling 1: every cite on the unit resolves, in one batch (09 section 10)."""
    assert ctx.doc is not None and ctx.unit is not None
    nodes = ctx.doc.select("@data-ow-cite")
    tokens = tuple(dict.fromkeys(c for n in nodes for c in (n.attr("data-ow-cite") or "").split()))
    if not tokens:
        return
    found = ctx.cites.by_cites(tokens)
    for n in nodes:
        for c in (n.attr("data-ow-cite") or "").split():
            if found.get(c) is None:
                yield Finding(
                    code="OW_TARGET_CITE_UNRESOLVED",
                    severity=Severity.ERROR,
                    provenance=Provenance.INTRODUCED,
                    rule="owtext.attr.ow-cite@1",
                    unit=ctx.unit.id,
                    construct="attr.ow-cite",
                    msg=f"cite {c!r} resolves to no live block in this corpus",
                    fix=f"ow open {c}",
                    at=n.at,
                    el=n.el,
                )


class OwTextCompiler:
    """The reference `compile/1` target. Ten constructs, four laws, no browser, no bake."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:  # noqa: ARG003 -- the protocol's shape.
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib html.parser only")

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY. Loads nothing, opens nothing."""
        self.newline = str(config.get("newline", "\n"))

    def carrier(self, path: str, text: str) -> CarrierDoc:
        return html_carrier(path, text, strict=False)

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        return {
            "structure": (
                RuleSpec(
                    "owtext.elem.script@1",
                    1,
                    "unit",
                    frozenset({"OW_TARGET_SCRIPT_FORBIDDEN"}),
                    rule_no_script,
                ),
                RuleSpec(
                    "owtext.attr.ow-el@1",
                    1,
                    "unit",
                    frozenset({"OW_TARGET_EL_DUPLICATE"}),
                    rule_el_unique,
                ),
                RuleSpec(
                    "owtext.attr.id@1",
                    1,
                    "unit",
                    frozenset({"OW_TARGET_ID_WITH_STYLE"}),
                    rule_id_with_style,
                ),
            ),
            "style": (
                RuleSpec(
                    "owtext.attr.class@1",
                    2,
                    "unit",
                    frozenset({"OW_TARGET_CLASS_NOT_LOWER"}),
                    rule_class_lower,
                ),
            ),
            "cross-reference": (
                RuleSpec(
                    "owtext.attr.ow-cite@1",
                    80,
                    "unit",
                    frozenset({"OW_TARGET_CITE_UNRESOLVED"}),
                    rule_cite_resolves,
                    needs=frozenset({"cites"}),
                ),
            ),
        }

    def measure(self) -> TextMeasure | None:
        """`measure = "none"`: a rule needing it is a recorded skip, never a pass (OUT3)."""
        return None

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        """IL to one text file, in `plan.units` order; ruling 3 refuses an unreachable bake."""
        del ledger  # owtext/1 has no asset construct: `[capability.compile] assets = []`
        out = []
        for unit in plan.units:
            doc = self.carrier(unit.il_path, il.text(unit.il_path))
            shadowed = doc.select("@style|text-shadow")
            if shadowed:
                raise TargetError(
                    f"{unit.id}: text-shadow needs its bake row, and this card's bake is "
                    f'"unavailable" (at {shadowed[0].at}); {BAKE_EXITS}',
                    symbol="OW_TARGET_BAKE_UNAVAILABLE",
                    fix="ow out constructs owtext --construct style.text-shadow",
                )
            body = self.newline.join(n.text_content() for n in doc.select("html|p"))
            out.append(f"== {unit.id} ==" + self.newline + body)
        payload = (self.newline.join(out) + self.newline).encode("utf-8")
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("artifact", payload, io),))

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        """Reads the artefact back and records the checks; it never decides the gate (OUT23)."""
        data = Path(artifact).read_bytes()
        classified = classify_and_assert(plan, baked={}, visual_changed=lambda _unit: True)
        return Receipt(
            schema="omniweave.out-receipt/1",
            target="owtext",
            slug=plan.slug,
            artifact_gen=plan.artifact_gen,
            output={
                "path": artifact,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            part_digest=receipt_part_digest(part_digest({f"{plan.slug}.txt": data})),
            determinism=(ArtefactDeterminism.PART, ArtefactDeterminism.BYTE),
            gate_status=plan.gate_status,
            delivery=plan.delivery,
            checks=(
                CheckValue("unit_count", "passed", f"{len(plan.units)} == unit_count"),
                CheckValue("byte_len", "passed", str(len(data))),
                CheckValue("citations_channel", "passed", "sidecar, as carded"),
                CheckValue(
                    "bake_used",
                    "enforced-at-build",
                    'bake = "unavailable"',
                    fixture="packages/omniweave-conform/tests/unit/test_target_owtext.py"
                    "::test_an_unreachable_bake_is_refused_before_a_byte",
                ),
                CheckValue("measure_available", "not-applicable", 'measure = "none"'),
            ),
            units={unit: c.outcome for unit, c in classified.items()},
            counts=dict(Counter(c.outcome for c in classified.values())),
            portability={
                "generic_only_font_stacks": (),
                "unresolved_brief_tokens": (),
                "external_asset_refs": (),
                "unsafe_exported_faces": (),
            },
            normalizations=(),
            degradations=(),
            skipped_checks=(),
            truncations=(),
        )

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        """Ruling 4: `[compile.round_trip] project = false`, refused by name."""
        del doc, io
        raise TargetError(
            "compile.text.owtext cannot project a Doc back to IL: its card says "
            "[compile.round_trip] project = false, and fidelity = none claims no round trip",
            symbol="OW_TARGET_PROJECT_UNAVAILABLE",
            fix="ow out compile --target owtext   # from the retained IL, not a projection",
        )
