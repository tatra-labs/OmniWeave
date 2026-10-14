"""`OutUnit`, `Plan`, the seven `UnitOutcome`s and `classify_and_assert()`. **D741.**

09-generation.md section 3.7 (the two types, printed field by field), section 5.5 (the seven
outcomes and the total classifier) and section 9 (`ManualReason`); charter OUT8. A `Plan` is the
commissioned roster and the gate's verdict, never the report (OUT23). `classify_and_assert()` gives
every unit exactly one outcome or writes nothing.

## Rulings (the ledger's D741)

1. **An `OutUnit` and a `Plan` refuse a malformed shape at construction**, with `ValueError` as
   `Finding` does: these are the framework's invariants, and a half-filled one is a bug in whoever
   built it, not a finding about the IL. 09 lists four for `OutUnit` (the id grammar, `ord >= 1`, an
   `il_path` under `il/`, and no half-filled source triple). `Plan` adds `unit_count == len(units)`
   and a contiguous, unique `ord` and `id` roster, which 09's field comments state.
2. **The classifier is section 5.5's pseudocode, in its order, as a pure function.** The two facts
   it cannot read off a unit are arguments: `baked` maps each unit a bake row fired in to its
   reason, and `visual_changed` is the predicate over `visual = true` rows, which the
   ConstructTable does not carry yet.
3. **A unit with no `nsig` is unclassifiable**, `OW_TARGET_UNIT_UNCLASSIFIED`, on any path. 09
   section 3.7 decision 4: a `Plan` reaching the classifier with any `nsig is None` raises rather
   than falling through to `native`, the branch a missing `nsig` would otherwise silently take.
4. **`Classified` holds the `artifact_unit` CHECK**: `manual_required` and `baked` need a reason.
5. **The sum is asserted over the outcomes, not over the roster**, so a classifier that reported a
   unit twice or dropped one fails `OW-T-005` as the charter says, and the artefact is not written.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Never

from omniweave_core.errors import TargetError
from omniweave_core.model.block import Cite
from omniweave_core.out.brief import Brief
from omniweave_core.out.gate import GateStatus

__all__ = [
    "PLAN_SCHEMA",
    "Classified",
    "ManualReason",
    "OutUnit",
    "Plan",
    "UnitOutcome",
    "classify_and_assert",
]

PLAN_SCHEMA: Final = "omniweave.out-plan/1"
_UNIT_ID: Final = re.compile(r"u\d{2,}")
_FIX: Final = "ow explain OW-T-005"


class UnitOutcome(StrEnum):
    """09 section 5.5: every unit lands in exactly one."""

    NATIVE = "native"
    BAKED = "baked"
    PASSTHROUGH = "passthrough"
    CLONED_PASSTHROUGH = "cloned_passthrough"
    PATCHED = "patched"
    REBUILT = "rebuilt"
    MANUAL_REQUIRED = "manual_required"


class ManualReason(StrEnum):
    """09 section 9: CLOSED. ppt-master's realization table, as data."""

    UNVERIFIABLE_WORDING = "unverifiable_wording"
    UNVERIFIABLE_IDENTITY = "unverifiable_identity"
    UNVERIFIABLE_DATA = "unverifiable_data"
    INSUFFICIENT_SOURCE = "insufficient_source"
    UNREPRESENTABLE = "unrepresentable"
    LICENCE_BARRED = "licence_barred"
    MEASUREMENT_FAILED = "measurement_failed"


@dataclass(frozen=True, slots=True)
class OutUnit:
    """One unit of a roster (09 section 3.7). It carries no outcome: that is the receipt's."""

    id: str
    ord: int
    il_path: str
    anchor: str = ""
    nsig: str | None = None
    source_part: str | None = None
    source_nsig: str | None = None
    source_ord: int | None = None
    manual_reason: ManualReason | None = None

    def __post_init__(self) -> None:
        if _UNIT_ID.fullmatch(self.id) is None:
            raise ValueError(f"unit id {self.id!r} does not match ^u\\d{{2,}}$")
        if self.ord < 1:
            raise ValueError(f"{self.id}: ord {self.ord} is below 1")
        if not self.il_path.startswith("il/"):
            raise ValueError(f"{self.id}: il_path {self.il_path!r} is not job-relative under il/")
        if self.source_part is None and (
            self.source_nsig is not None or self.source_ord is not None
        ):
            raise ValueError(f"{self.id}: a source nsig or ord without a source_part")


@dataclass(frozen=True, slots=True)
class Plan:
    """The commissioned roster, the gate's status and the six purity inputs (09 section 3.7)."""

    schema: Literal["omniweave.out-plan/1"]
    target: str
    slug: str
    artifact_gen: int
    delivery: Literal["release", "draft"]
    units: tuple[OutUnit, ...]
    unit_count: int
    brief: Brief
    corpus: str
    cites: Mapping[Cite, int]
    gate_status: GateStatus
    il_digest: str
    constructs_digest: str
    ledger_digest: str
    brief_digest: str
    card_sha256: str
    toolchain_digest: str | None = None

    def __post_init__(self) -> None:
        if self.schema != PLAN_SCHEMA:
            raise ValueError(f"plan schema {self.schema!r} is not {PLAN_SCHEMA!r}")
        if self.delivery not in {"release", "draft"}:
            raise ValueError(f"delivery {self.delivery!r} is release or draft")
        if self.artifact_gen < 1:
            raise ValueError(f"artifact_gen {self.artifact_gen} is below 1")
        if self.unit_count != len(self.units):
            raise ValueError(f"unit_count {self.unit_count} is not the roster's {len(self.units)}")
        ords = [u.ord for u in self.units]
        if ords != list(range(1, len(self.units) + 1)):
            raise ValueError(f"ords {ords} are not 1..{len(self.units)} in roster order")
        ids = [u.id for u in self.units]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"unit ids repeat: {sorted(i for i, n in Counter(ids).items() if n > 1)}"
            )


@dataclass(frozen=True, slots=True)
class Classified:
    """One unit's outcome, and the reason `artifact_unit`'s CHECK requires for two of them."""

    outcome: UnitOutcome
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome in {UnitOutcome.MANUAL_REQUIRED, UnitOutcome.BAKED} and not self.reason:
            raise ValueError(f"a {self.outcome} unit needs a reason")


def classify_and_assert(
    plan: Plan,
    *,
    baked: Mapping[str, str],
    visual_changed: Callable[[OutUnit], bool],
) -> dict[str, Classified]:
    """09 section 5.5, total; OW-T-005 and nothing written otherwise (OUT8)."""
    outcomes: dict[str, Classified] = {}
    for unit in plan.units:
        outcomes[unit.id] = _classify(unit, baked, visual_changed)
    counts = Counter(c.outcome for c in outcomes.values())
    if sum(counts.values()) != plan.unit_count:
        _unclassified(
            f"{sum(counts.values())} units classified against a roster of {plan.unit_count}: "
            + ", ".join(f"{o}={n}" for o, n in sorted(counts.items()))
        )
    return outcomes


def _classify(
    unit: OutUnit, baked: Mapping[str, str], visual_changed: Callable[[OutUnit], bool]
) -> Classified:
    if unit.nsig is None:
        _unclassified(f"{unit.id} reached the classifier with no nsig (09 section 3.7 decision 4)")
    if unit.manual_reason is not None:
        return Classified(UnitOutcome.MANUAL_REQUIRED, unit.manual_reason.value)
    if unit.source_part is None:
        reason = baked.get(unit.id)
        return Classified(UnitOutcome.BAKED, reason) if reason else Classified(UnitOutcome.NATIVE)
    if unit.source_nsig is None:
        _unclassified(f"{unit.id} is edited from {unit.source_part} and has no source nsig")
    if unit.nsig == unit.source_nsig and unit.ord == unit.source_ord:
        return Classified(UnitOutcome.PASSTHROUGH)
    if unit.nsig == unit.source_nsig:
        return Classified(UnitOutcome.CLONED_PASSTHROUGH)
    if not visual_changed(unit):
        return Classified(UnitOutcome.PATCHED)
    return Classified(UnitOutcome.REBUILT)


def _unclassified(msg: str) -> Never:
    raise TargetError(msg, symbol="OW_TARGET_UNIT_UNCLASSIFIED", fix=_FIX)
