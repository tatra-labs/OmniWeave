"""`manual_required`: the `ow:manual` region, and `ManualEvidence`. **D756.**

09-generation.md section 9. `manual_required` is three things: a mandatory IL construct
(`ow:manual`), a `UnitOutcome` whose `reason` is NOT NULL, and a `GateStatus`. `ManualReason`, the
closed vocabulary, is `omniweave_core.out.plan`'s (D741). This module reads the construct out of a
parsed unit, carries it to the gate and the classifier, and holds the observation record a human
reviews.

## Rulings

1. **A region is an element carrying `data-ow-manual`, and its value is the reason.** Every
   ConstructTable must carry `ow:manual` (09 section 3.4), and the reference row is
   `html|div[data-ow-manual]`, whose value 09 canonicalizes as "a ManualReason". The framework
   reads the attribute, not the element, so one reader serves both carriers.
2. **A value outside `ManualReason` is a framework error, never a guess.**
   `OW_TARGET_MANUAL_REASON_UNKNOWN` (`OW-T-513`, appended; the reference table already names the
   symbol) is an error finding at the region, so the gate fails. It must not become
   `manual-required`, because `artifact_unit.reason` would then hold a word no reader can act
   on.
3. **A unit's `manual_reason` is its first region's**, in document order. `OutUnit` holds one
   reason, and `classify_and_assert()` needs only to know there is one. The report lists every
   region with its unit, `el` and reason, because 09's gate message "names each unit, its
   `ManualReason` and the region".
4. **`ManualEvidence` records only what is visibly present**, and its reader refuses anything
   else. That means the source frame (path, sha256, pixel size) and, per region, a stable id, a
   bbox inside the frame, the observed family, readable text, a confidence in [0, 1], the observed
   sufficiency, boundary completeness, occlusion, identity and data verifiability, and overlap and
   z-order. A key naming a realization choice, a prompt, an output file or an IL binding is an
   unknown key and refused. Keeping the observation free of decisions is what makes it
   re-reviewable (09 section 9).
5. **An unreachable `bake` names its two exits, and both are this module's** (D876). 00-vision.md
   V10-9 and 16-roadmap.md:920 want `bake` `unavailable` *"with both exits named in the error"*,
   and 09 section 9's table gives the second: *"a construct with no `native` row and no reachable
   `bake`"* is `unrepresentable`, never silently dropped. So the exits are a spelling the table
   maps natively, or an `ow:manual` region with that reason standing in for the construct, which
   the gate holds at `manual-required` until `--accept-manual` (`gate.CLEARS`). The region must
   replace the construct, not wrap it: an error inside a region still fails the gate first.
   `BAKE_EXITS` is the one wording, so the table's finding and a target's preflight refusal
   cannot name different exits.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.plan import ManualReason

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierDoc

__all__ = [
    "BAKE_EXITS",
    "EVIDENCE_SCHEMA",
    "MANUAL_ATTRIBUTE",
    "REASON_UNKNOWN",
    "EvidenceRegion",
    "ManualEvidence",
    "ManualRegion",
    "manual_regions",
]

MANUAL_ATTRIBUTE: Final = "data-ow-manual"
REASON_UNKNOWN: Final = "OW_TARGET_MANUAL_REASON_UNKNOWN"
EVIDENCE_SCHEMA: Final = "omniweave.out-manual-evidence/1"
_REASONS: Final = frozenset(r.value for r in ManualReason)
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
BAKE_EXITS: Final = (
    "two exits: rewrite it as a construct this target's table maps natively, or replace it with "
    f'an ow:manual region, {MANUAL_ATTRIBUTE}="{ManualReason.UNREPRESENTABLE.value}", and '
    "compile with --accept-manual"
)
"""Ruling 5: what an unreachable `bake` tells its author, in every error that reports one."""
_REGION_ID: Final = re.compile(r"[A-Za-z0-9_.-]{1,64}")


@dataclass(frozen=True, slots=True)
class ManualRegion:
    """Ruling 1: one `ow:manual` region of one unit."""

    unit: str
    el: str | None
    raw: str
    at: str | None = None

    @property
    def reason(self) -> ManualReason | None:
        """The `ManualReason` the value names, or `None` for a value outside it (ruling 2)."""
        return ManualReason(self.raw) if self.raw in _REASONS else None

    def as_json(self) -> dict[str, Any]:
        """The report's `manual_units` row: the unit, the region and the reason (ruling 3)."""
        return {"unit": self.unit, "el": self.el, "reason": self.raw}

    def finding(self) -> Finding:
        """Ruling 2: the framework's error for a value outside `ManualReason`."""
        return Finding(
            code=REASON_UNKNOWN,
            severity=Severity.ERROR,
            provenance=Provenance.FRAMEWORK,
            rule="ow.manual@1",
            unit=self.unit,
            msg=f"{MANUAL_ATTRIBUTE}={self.raw!r} is not a ManualReason: {sorted(_REASONS)}",
            fix="ow out constructs --construct ow:manual   # the seven reasons",
            at=self.at,
            el=self.el,
        )


def manual_regions(unit: str, doc: CarrierDoc) -> tuple[ManualRegion, ...]:
    """Ruling 1: every element carrying `data-ow-manual`, in document order."""
    return tuple(
        ManualRegion(unit, node.el, node.attr(MANUAL_ATTRIBUTE) or "", node.at)
        for node in doc.select(f"@{MANUAL_ATTRIBUTE}")
    )


Family = Literal["text", "graphic", "image", "unknown"]
Sufficiency = Literal["sufficient", "insufficient", "unknown"]
_FAMILIES: Final = frozenset({"text", "graphic", "image", "unknown"})
_SUFFICIENCY: Final = frozenset({"sufficient", "insufficient", "unknown"})
_REGION_KEYS: Final = frozenset(
    {
        "id",
        "bbox",
        "family",
        "text",
        "confidence",
        "sufficiency",
        "boundary_complete",
        "occluded",
        "identity_verifiable",
        "data_verifiable",
        "overlaps",
        "z",
    }
)
_TOP_KEYS: Final = frozenset({"schema", "source", "sha256", "width", "height", "regions"})


@dataclass(frozen=True, slots=True)
class EvidenceRegion:
    """Ruling 4: what one region visibly is. No choice about what to make of it."""

    id: str
    bbox: tuple[int, int, int, int]
    """`(x, y, w, h)` in the frame's pixels."""
    family: Family
    confidence: float
    sufficiency: Sufficiency
    boundary_complete: bool
    occluded: bool
    text: str | None = None
    """Verbatim, and only where it is readable."""
    identity_verifiable: bool | None = None
    data_verifiable: bool | None = None
    overlaps: tuple[str, ...] = ()
    z: int | None = None

    def __post_init__(self) -> None:
        if _REGION_ID.fullmatch(self.id) is None:
            raise ValueError(f"region id {self.id!r} is not a stable token")
        x, y, w, h = self.bbox
        if min(x, y) < 0 or w <= 0 or h <= 0:
            raise ValueError(f"region {self.id}: bbox {self.bbox} is not a box")
        if self.family not in _FAMILIES:
            raise ValueError(f"region {self.id}: family {self.family!r} is not {sorted(_FAMILIES)}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"region {self.id}: confidence {self.confidence} is not in [0, 1]")
        if self.sufficiency not in _SUFFICIENCY:
            raise ValueError(
                f"region {self.id}: sufficiency {self.sufficiency!r} is not {sorted(_SUFFICIENCY)}"
            )
        if self.id in self.overlaps:
            raise ValueError(f"region {self.id} overlaps itself")


@dataclass(frozen=True, slots=True)
class ManualEvidence:
    """Ruling 4: one source frame and its regions, observed and never decided."""

    source: str
    sha256: str
    width: int
    height: int
    regions: tuple[EvidenceRegion, ...]

    def __post_init__(self) -> None:
        if _HEX64.fullmatch(self.sha256) is None:
            raise ValueError(f"frame sha256 {self.sha256!r} is not 64 lower-case hex")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"frame {self.width}x{self.height} has no pixels")
        ids = [r.id for r in self.regions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"region ids repeat: {ids}")
        for region in self.regions:
            x, y, w, h = region.bbox
            if x + w > self.width or y + h > self.height:
                raise ValueError(f"region {region.id}: bbox {region.bbox} leaves the frame")
            stray = sorted(set(region.overlaps) - set(ids))
            if stray:
                raise ValueError(f"region {region.id} overlaps unknown regions {stray}")

    @classmethod
    def from_json(cls, doc: Mapping[str, Any]) -> ManualEvidence:
        """Ruling 4: exactly the observation keys, so a decision cannot ride along."""
        _keys("evidence", doc, _TOP_KEYS)
        if doc["schema"] != EVIDENCE_SCHEMA:
            raise ValueError(f"evidence schema {doc['schema']!r} is not {EVIDENCE_SCHEMA!r}")
        regions = []
        for raw in _seq(doc["regions"]):
            _keys("region", raw, _REGION_KEYS, optional=_REGION_KEYS - _REQUIRED_REGION)
            regions.append(
                EvidenceRegion(
                    id=raw["id"],
                    bbox=tuple(raw["bbox"]),  # type: ignore[arg-type]
                    family=raw["family"],
                    confidence=float(raw["confidence"]),
                    sufficiency=raw["sufficiency"],
                    boundary_complete=bool(raw["boundary_complete"]),
                    occluded=bool(raw["occluded"]),
                    text=raw.get("text"),
                    identity_verifiable=raw.get("identity_verifiable"),
                    data_verifiable=raw.get("data_verifiable"),
                    overlaps=tuple(raw.get("overlaps", ())),
                    z=raw.get("z"),
                )
            )
        return cls(doc["source"], doc["sha256"], doc["width"], doc["height"], tuple(regions))


_REQUIRED_REGION: Final = frozenset(
    {"id", "bbox", "family", "confidence", "sufficiency", "boundary_complete", "occluded"}
)


def _keys(
    what: str, doc: Any, allowed: frozenset[str], *, optional: frozenset[str] = frozenset()
) -> None:
    if not isinstance(doc, Mapping):
        raise TypeError(f"{what} is not an object")
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise ValueError(f"{what} records {unknown}, which are not observations (09 section 9)")
    missing = sorted(allowed - optional - set(doc))
    if missing:
        raise ValueError(f"{what} is missing {missing}")


def _seq(value: Any) -> Sequence[Any]:
    if not isinstance(value, list):
        raise TypeError("regions is not a list")
    return value
