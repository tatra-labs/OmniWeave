"""The rule runner: `RuleSpec`, `RuleCtx`, `DocIndex`, `Box`, `TextMeasure`, `run_pack()`. D742.

09-generation.md section 4.4 (the types, the two passes, the phase bands), section 4.1 (a rule may
only emit `INTRODUCED`), section 14.1 (`MAX_FINDINGS_PER_RULE`), section 14.2 (one parsed unit
resident) and section 14.4 (a rule that raises). The framework runs the gate; a target only supplies
the rules, so a target that could run its own gate could not skip it.

## Rulings (the ledger's D742)

1. **`run_pack()` takes the carrier as an argument.** 09 prints `run_pack(pack, bundle, mk_ctx)`
   and says pass A calls `carrier(path, text)` at order 0, which is the target's
   `CompileV1.carrier`. The runner cannot call a method it was not handed.
2. **Order 0 is the framework's, and a pack rule may not take it.** A `RuleSpec` is refused at
   construction outside the band its scope allows: `unit` and `node` in 1-89, `document` in 90-99.
3. **A parse failure is one `OW_TARGET_IL_MALFORMED` error a problem**, at the problem's position,
   and the unit's remaining rules are skipped: the short circuit is per unit. A recovering read that
   recorded problems has failed order 0 too, because every later rule assumes a well-formed tree. A
   `ResourceLimit` from the parse is not a finding: it is fatal and names its knob.
4. **A forged provenance raises `OW_TARGET_RULE_FORGED_PROVENANCE` and stops the run.** 09 says
   `run_pack()` raises. A rule that claims ownership the framework decides is a broken target, not
   a finding about the IL.
5. **A rule that raises is one `OW_TARGET_RULE_RAISED` framework error** naming the rule and the
   exception's type, and the run continues (09 section 14.4). The gate is `failed`: a crashing rule
   is a framework-visible defect, never a silent pass.
6. **`MAX_FINDINGS_PER_RULE` is per rule across the run**, counted in findings emitted before the
   fold. Past it a rule's findings are dropped, still counted, and one `rule` truncation names it,
   so the gate is `unverified`.
7. **An unmet need is skipped once per rule, not once per unit.** The `SkippedCheck` names the rule
   and the need, and the fix is the caller's per need, which only the target knows
   (`uv pip install 'omniweave-target-pptx[measure]'`).
8. **`DocIndex` is filled from what a stamped tree shows.** `els`, `cites`, `slots` and
   `construct_counts` are collected per unit. `nsigs` waits for the canonicaliser, `markers` for
   the `OWC1` scan, and `value_occurrences` for the rules that count values. Each is an empty
   mapping until then, never absent.
9. **`rule_timings_ms` is read from the injected `Clock`**, `SystemClock` unless the caller
   passes one. Library code reads no ambient clock (`omniweave-no-time-time-in-library-code`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, Protocol

from omniweave_core.clock import Clock, SystemClock
from omniweave_core.errors import TargetError
from omniweave_core.limits import MAX_FINDINGS_PER_RULE
from omniweave_core.out.carrier import CarrierDoc, CarrierNode, CarrierParseError, ParseError
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Finding, FindingSet, Provenance, Severity, Truncation
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.report import SkippedCheck

__all__ = [
    "Box",
    "DocIndex",
    "PackRun",
    "Roster",
    "Rule",
    "RuleCtx",
    "RuleSpec",
    "TextMeasure",
    "run_pack",
]

NEEDS: Final = frozenset({"measure", "cites", "assets"})
_BANDS: Final[dict[str, range]] = {
    "unit": range(1, 90),
    "node": range(1, 90),
    "document": range(90, 100),
}
_SLOT: Final = re.compile(r"asset-slot:([0-9a-f]{64})")
_CITE_ATTRIBUTE: Final = "data-ow-cite"
_NEED_FIX: Final = "ow out targets   # names the extra each target's needs require"


@dataclass(frozen=True, slots=True)
class Box:
    """One measured layout, in IL user units (09 section 4.4)."""

    advance: float
    height: float
    ascent: float
    descent: float
    lines: int
    overflow: bool


class TextMeasure(Protocol):
    def box(self, n: CarrierNode) -> Box | None:
        """The one method `RuleCtx.measure` delegates to. `None` is a recorded skip."""
        ...


@dataclass(frozen=True, slots=True)
class DocIndex:
    """What a document-scope rule may know, bounded by the roster and never by the node count."""

    units: tuple[str, ...]
    els: Mapping[str, frozenset[str]]
    nsigs: Mapping[str, str]
    construct_counts: Mapping[str, Counter[str]]
    cites: Mapping[str, frozenset[str]]
    slots: Mapping[str, frozenset[str]]
    markers: tuple[object, ...]
    value_occurrences: Mapping[str, Counter[str]]


class RuleCtx(Protocol):
    """What a rule reads (09 section 4.4). `doc` and `unit` are `None` iff the scope is document."""

    @property
    def doc(self) -> CarrierDoc | None: ...

    @property
    def unit(self) -> OutUnit | None: ...

    @property
    def index(self) -> DocIndex: ...

    @property
    def limits(self) -> Mapping[str, int]: ...

    def measure(self, n: CarrierNode) -> Box | None: ...


Rule = Callable[[RuleCtx], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """One rule of a pack. Ruling 2: its order sits in the band its scope allows."""

    id: str
    order: int
    scope: Literal["document", "unit", "node"]
    codes: frozenset[str]
    fn: Rule
    needs: frozenset[str] = frozenset()
    final_only: bool = False

    def __post_init__(self) -> None:
        band = _BANDS.get(self.scope)
        if band is None:
            raise ValueError(f"{self.id}: scope {self.scope!r} is document, unit or node")
        if self.order not in band:
            raise ValueError(
                f"{self.id}: a {self.scope} rule's order is {band.start}-{band.stop - 1}"
            )
        if not self.codes:
            raise ValueError(f"{self.id}: a rule declares every code it may emit")
        if not self.needs <= NEEDS:
            raise ValueError(
                f"{self.id}: needs {sorted(self.needs - NEEDS)} is not one of {sorted(NEEDS)}"
            )


class Roster(Protocol):
    """What `run_pack()` reads of a bundle: its units, and each unit's text."""

    @property
    def units(self) -> tuple[OutUnit, ...]: ...

    def text(self, il_path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class PackRun:
    """`run_pack()`'s result: what `OutReport.build()` takes, plus the index pass B read."""

    findings: FindingSet
    skipped: tuple[SkippedCheck, ...]
    timings: Mapping[str, int]
    index: DocIndex


@dataclass(slots=True)
class _Tally:
    """Per-rule state across the run: rulings 6 and 7, and the timings on the injected clock."""

    clock: Clock
    emitted: Counter[str] = field(default_factory=Counter)
    nanos: Counter[str] = field(default_factory=Counter)
    skipped: dict[str, SkippedCheck] = field(default_factory=dict)


def run_pack(
    pack: Mapping[str, Sequence[RuleSpec]],
    bundle: Roster,
    mk_ctx: Callable[[OutUnit | None, CarrierDoc | None, DocIndex], RuleCtx],
    *,
    carrier: Callable[[str, str], CarrierDoc],
    stage: str,
    met: frozenset[str],
    fixes: Mapping[str, str],
    constructs: ConstructTable | None = None,
    clock: Clock | None = None,
) -> PackRun:
    """09 section 4.4's two passes. Never holds more than one parsed unit."""
    specs = sorted((s for group in pack.values() for s in group), key=lambda s: (s.order, s.id))
    eligible = [s for s in specs if stage == "final" or not s.final_only]
    per_unit = [s for s in eligible if s.scope != "document"]
    documents = [s for s in eligible if s.scope == "document"]
    tally = _Tally(clock or SystemClock())
    found = FindingSet()
    index = _Index(tuple(u.id for u in bundle.units))
    for unit in bundle.units:
        doc = _parse(unit, bundle, carrier)
        if isinstance(doc, list):
            found += FindingSet(tuple(doc)).fold(limit=1 << 62)
            continue
        index.add(unit.id, doc, constructs)
        ctx = mk_ctx(unit, doc, index.snapshot())
        unit_found = _run(per_unit, ctx, unit=unit.id, met=met, fixes=fixes, tally=tally)
        found += FindingSet(tuple(unit_found)).fold(limit=1 << 62)
    final = index.snapshot()
    ctx = mk_ctx(None, None, final)
    found += FindingSet(tuple(_run(documents, ctx, unit="", met=met, fixes=fixes, tally=tally)))
    truncations = tuple(
        Truncation("rule", before=n, after=MAX_FINDINGS_PER_RULE, rule=rule)
        for rule, n in sorted(tally.emitted.items())
        if n > MAX_FINDINGS_PER_RULE
    )
    return PackRun(
        findings=FindingSet(found.findings, found.truncations + truncations),
        skipped=tuple(tally.skipped.values()),
        timings={rule: nanos // 1_000_000 for rule, nanos in sorted(tally.nanos.items())},
        index=final,
    )


def _parse(
    unit: OutUnit, bundle: Roster, carrier: Callable[[str, str], CarrierDoc]
) -> CarrierDoc | list[Finding]:
    """Order 0 (ruling 3): the document, or the findings that short-circuit the unit."""
    try:
        doc = carrier(unit.il_path, bundle.text(unit.il_path))
    except CarrierParseError as exc:
        return [_malformed(unit, exc.error)]
    if doc.problems:
        return [_malformed(unit, problem) for problem in doc.problems]
    return doc


def _malformed(unit: OutUnit, error: ParseError) -> Finding:
    return Finding(
        code="OW_TARGET_IL_MALFORMED",
        severity=Severity.ERROR,
        provenance=Provenance.INTRODUCED,
        rule="ow.il.parse@1",
        unit=unit.id,
        msg=error.msg,
        fix=f"ow out check --stage unit --unit {unit.id}   # after repairing {error.at}",
        at=error.at,
    )


def _run(
    specs: Sequence[RuleSpec],
    ctx: RuleCtx,
    *,
    unit: str,
    met: frozenset[str],
    fixes: Mapping[str, str],
    tally: _Tally,
) -> list[Finding]:
    out: list[Finding] = []
    for spec in specs:
        unmet = sorted(spec.needs - met)
        if unmet:
            for need in unmet:
                tally.skipped.setdefault(
                    f"{spec.id}:{need}",
                    SkippedCheck(
                        spec.id,
                        need,
                        f"{need} is not available to this check",
                        fixes.get(need, _NEED_FIX),
                    ),
                )
            continue
        started = tally.clock.monotonic_ns()
        try:
            emitted = list(spec.fn(ctx))
        except Exception as exc:
            out.append(_raised(spec, unit, exc))
            continue
        finally:
            tally.nanos[spec.id] += tally.clock.monotonic_ns() - started
        for finding in emitted:
            if finding.provenance is not Provenance.INTRODUCED:
                raise TargetError(
                    f"rule {spec.id} emitted {finding.code} as {finding.provenance}; a rule may "
                    "only emit introduced, and the framework stamps the other three",
                    symbol="OW_TARGET_RULE_FORGED_PROVENANCE",
                    fix="ow explain OW-T-004",
                )
            tally.emitted[spec.id] += 1
            if tally.emitted[spec.id] <= MAX_FINDINGS_PER_RULE:
                out.append(finding)
    return out


def _raised(spec: RuleSpec, unit: str, exc: Exception) -> Finding:
    return Finding(
        code="OW_TARGET_RULE_RAISED",
        severity=Severity.ERROR,
        provenance=Provenance.FRAMEWORK,
        rule=spec.id,
        unit=unit,
        msg=f"rule {spec.id} raised {type(exc).__name__}; a crashing rule is a defect, not a pass",
        fix="ow explain OW-T-010   # report the rule to its target",
    )


class _Index:
    """`DocIndex`, built incrementally: one unit's contribution at a time (ruling 8)."""

    def __init__(self, units: tuple[str, ...]) -> None:
        self.units = units
        self.els: dict[str, frozenset[str]] = {}
        self.cites: dict[str, frozenset[str]] = {}
        self.slots: dict[str, frozenset[str]] = {}
        self.constructs: dict[str, Counter[str]] = {}

    def add(self, unit: str, doc: CarrierDoc, table: ConstructTable | None) -> None:
        els: set[str] = set()
        cites: set[str] = set()
        slots: set[str] = set()
        counts: Counter[str] = Counter()
        for node in doc.select("@data-ow-el"):
            if node.el:
                els.add(node.el)
        for node in doc.select(f"@{_CITE_ATTRIBUTE}"):
            cites.update((node.attr(_CITE_ATTRIBUTE) or "").split())
        slots.update(_SLOT.findall(doc.source()))
        if table is not None:
            for row in table.rows:
                counts[row.id] += len(doc.select(row.selector))
            counts = +counts
        self.els[unit] = frozenset(els)
        self.cites[unit] = frozenset(cites)
        self.slots[unit] = frozenset(slots)
        self.constructs[unit] = counts

    def snapshot(self) -> DocIndex:
        return DocIndex(
            units=self.units,
            els=MappingProxyType(dict(self.els)),
            nsigs=MappingProxyType({}),
            construct_counts=MappingProxyType(dict(self.constructs)),
            cites=MappingProxyType(dict(self.cites)),
            slots=MappingProxyType(dict(self.slots)),
            markers=(),
            value_occurrences=MappingProxyType({}),
        )
