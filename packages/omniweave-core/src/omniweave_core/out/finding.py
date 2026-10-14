"""The OUT diagnostic: `Severity`, `Provenance`, `Finding` and the fold. **D737.**

09-generation.md section 4.1-4.2 and section 14.3; charter OUT6 and OUT7. `Severity` decides
**blocking** and `Provenance` decides **ownership**. They are orthogonal, and the table in 09
section 4.1 is what each of the twelve cells does. A `Finding` carries the `codes.toml` **symbol**
(the stored and wire form), and the numeric `OW-T-nnn` is resolved at render time.

## Rulings (the ledger's D737)

1. **The fold key is 09's four fields, split by severity and provenance.** 09 section 4.2 folds
   on `(code, rule, unit, canonical)`, and keeps `unit` so a per-unit fix stays per-unit and
   `canonical` so two replacement values do not merge into one ambiguous recommendation. Severity
   decides blocking and provenance decides which fix prints, so by the same reasoning a group whose
   members disagree on either is two findings: an inherited warning folded into an introduced one
   would move `introduced_warning_count`, and a warning folded into an error would hide one or
   promote the other. `fold_key()` is the six fields.
2. **A folded finding keeps its first member's fields, and sums the counts.** The runner emits in
   roster and rule order, so "first" is deterministic. `examples` are the first three distinct
   examples across the members, in order.
3. **A finding with no unit has `unit = ""`**: a document-scope rule's, and the framework's own.
   The console prints it as `-`.
4. **The re-fold drops `unit` and records it.** Past `MAX_FOLDED_FINDINGS` the set re-folds on the
   key less `unit` (09 section 14.3). A re-folded finding has `unit = ""`, `at` and `el` cleared
   because they named one unit, `units_affected` the number of units it covers and `unit_examples`
   the first three. Those two fields are 14.3's *"carries `units_affected: int` and up to 3 example
   unit ids"*, which section 4.2's field list has no place for. A finding that was never re-folded
   has `units_affected = None`.
5. **`fix` is checked after stripping**: a fix of spaces is as empty as `""`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Literal

from omniweave_core.limits import MAX_FOLDED_FINDINGS

__all__ = [
    "EXAMPLES_MAX",
    "SEVERITY_ORDER",
    "Finding",
    "FindingSet",
    "Provenance",
    "Severity",
    "Truncation",
]


class Severity(StrEnum):
    """Decides **blocking** (09 section 4.1)."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Provenance(StrEnum):
    """Decides **ownership**, and so which fix command prints (09 section 4.1)."""

    INTRODUCED = "introduced"
    """The generator authored it. The only provenance a rule may emit."""
    INHERITED = "inherited"
    """Byte-identical in the template it derives from: its `el`'s `nsig` is the template's."""
    IMPORTED = "imported"
    """Arrived through `project()` of a tolerant read."""
    FRAMEWORK = "framework"
    """omniweave itself: a skipped check, a truncation, a rule that raised."""


SEVERITY_ORDER: Final[dict[Severity, int]] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}
"""The console's and the JSON's sort: errors first (09 section 4.2)."""

EXAMPLES_MAX: Final = 3
"""At most three examples a folded finding, asserted (OUT7)."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic, possibly folded. 09 section 4.2's shape, plus ruling 4's two fields."""

    code: str
    """THE SYMBOL, e.g. `OW_TARGET_BLEND_REQUIRES_BAKE`."""
    severity: Severity
    provenance: Provenance
    rule: str
    """`pptx.style.blend@1`, id@version."""
    unit: str
    """`u03`, or `""` for a finding no unit owns (ruling 3)."""
    msg: str
    fix: str
    """THE EXACT COMMAND. Never empty (OUT6)."""
    at: str | None = None
    """`il/u03.svg:41:9`, the convenience, which a reflow moves."""
    el: str | None = None
    """`u03/e17`, a `data-ow-el` address, the durable anchor."""
    construct: str | None = None
    canonical: str | None = None
    """Required iff the construct's disposition is `normalize`; the runner holds that."""
    count: int = 1
    examples: tuple[str, ...] = ()
    units_affected: int | None = None
    """Ruling 4: set only by the re-fold."""
    unit_examples: tuple[str, ...] = ()
    """Ruling 4: at most three unit ids, set only by the re-fold."""

    def __post_init__(self) -> None:
        who = f"{self.code} from {self.rule}"
        if not self.fix.strip():
            raise ValueError(f"{who}: every Finding names the exact command that clears it")
        if self.count < 1:
            raise ValueError(f"{who}: count {self.count} is below 1")
        if len(self.examples) > EXAMPLES_MAX:
            raise ValueError(f"{who}: {len(self.examples)} examples, at most {EXAMPLES_MAX}")
        if len(self.unit_examples) > EXAMPLES_MAX:
            raise ValueError(f"{who}: {len(self.unit_examples)} unit examples")
        if self.units_affected is None and self.unit_examples:
            raise ValueError(f"{who}: unit examples on a finding never re-folded")

    def fold_key(self) -> tuple[str, str, str, str | None, Severity, Provenance]:
        """Ruling 1: 09's `(code, rule, unit, canonical)`, split by severity and provenance."""
        return (self.code, self.rule, self.unit, self.canonical, self.severity, self.provenance)

    def sort_key(self) -> tuple[int, str, str, str, str]:
        """09 section 4.2's `(severity, unit, code)`, then the rule and the anchor, so the order
        is total and a report is the same bytes twice."""
        return (
            SEVERITY_ORDER[self.severity],
            self.unit,
            self.code,
            self.rule,
            self.el or self.at or "",
        )


@dataclass(frozen=True, slots=True)
class Truncation:
    """A `truncations` entry (09 section 4.2): the absence of a finding past it proves nothing.

    `kind = "rule"` is a rule cut at `MAX_FINDINGS_PER_RULE`, naming it; `kind = "refold"` is the
    second fold, which names no rule.
    """

    kind: Literal["rule", "refold"]
    before: int
    after: int
    rule: str | None = None

    def as_json(self) -> dict[str, object]:
        """`{"kind": "refold", "from": 120000, "to": 60}`, 09 section 14.3's spelling."""
        doc: dict[str, object] = {"kind": self.kind, "from": self.before, "to": self.after}
        if self.rule is not None:
            doc["rule"] = self.rule
        return doc


@dataclass(frozen=True, slots=True)
class FindingSet:
    """Findings with the truncations that qualify them. Immutable; `fold()` returns a new set."""

    findings: tuple[Finding, ...] = ()
    truncations: tuple[Truncation, ...] = ()

    def __add__(self, other: FindingSet) -> FindingSet:
        return FindingSet(self.findings + other.findings, self.truncations + other.truncations)

    def fold(self, *, limit: int | None = None) -> FindingSet:
        """OUT7, then section 14.3's re-fold past `limit`, `MAX_FOLDED_FINDINGS` unless given.

        Idempotent: a re-folded set is not re-folded again, so a second `fold()` adds no second
        truncation.
        """
        ceiling = MAX_FOLDED_FINDINGS if limit is None else limit
        folded = _fold(self.findings)
        if len(folded) <= ceiling or all(f.units_affected is not None for f in folded):
            return FindingSet(folded, self.truncations)
        refolded = _refold(folded)
        return FindingSet(
            refolded,
            (*self.truncations, Truncation("refold", before=len(folded), after=len(refolded))),
        )


def _fold(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Rulings 1-2: group in first-seen order, sum counts, keep three distinct examples."""
    groups: dict[tuple[object, ...], list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.fold_key(), []).append(finding)
    return tuple(_merge(members) for members in groups.values())


def _merge(members: list[Finding]) -> Finding:
    first = members[0]
    if len(members) == 1:
        return first
    return replace(
        first,
        count=sum(m.count for m in members),
        examples=_distinct(e for m in members for e in m.examples),
    )


def _refold(folded: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Ruling 4: the key less `unit`; the units counted, and the first three named."""
    groups: dict[tuple[object, ...], list[Finding]] = {}
    for finding in folded:
        code, rule, _, canonical, severity, provenance = finding.fold_key()
        groups.setdefault((code, rule, canonical, severity, provenance), []).append(finding)
    return tuple(
        replace(
            members[0],
            unit="",
            at=None,
            el=None,
            count=sum(m.count for m in members),
            examples=_distinct(e for m in members for e in m.examples),
            units_affected=sum(_units(m) for m in members),
            unit_examples=_distinct(
                u for m in members for u in (m.unit_examples or (m.unit,)) if u
            ),
        )
        for members in groups.values()
    )


def _units(finding: Finding) -> int:
    if finding.units_affected is not None:
        return finding.units_affected
    return 1 if finding.unit else 0


def _distinct(values: Iterable[str]) -> tuple[str, ...]:
    """The first `EXAMPLES_MAX` distinct values, in order."""
    seen: dict[str, None] = {}
    for value in values:
        if len(seen) == EXAMPLES_MAX:
            break
        seen.setdefault(value, None)
    return tuple(seen)
