"""The delivery evidence: `ArtefactDeterminism`, `CheckValue`, `Receipt`, the status. **D748.**

09-generation.md section 5.3 (the receipt, its six check values, the console line and the three-way
report status) and section 6 (determinism is a declared set, `part` the floor). A `Receipt` is
written by `postflight()` after `lower()`, against the produced artefact; a `CheckValue` decides
neither blocking nor ownership, and nothing that writes one may gate.

## Rulings (the ledger's D748)

1. **A receipt is internally consistent or it is not built.** `Receipt.__post_init__` refuses:
   a repeated check name (`verify` reads a check by name), `counts` that are not the tally of
   `units`, a determinism set without `part` (the floor every target has), a `part_digest` that is
   not 64 hex, and an `output` without `path`, `bytes` and `sha256`.
2. **`delivery` follows the gate**: a `release` receipt carries `passed`, and a `draft` receipt
   carries `manual-required`, unchanged, because `--accept-manual` is no bypass (09 section 9).
3. **`part_digest` is hex on the receipt.** 09 types it HEX, and `artifact.part_digest` is the BLOB
   of those bytes; `opc.part_digest()`'s `sha256:` prefix is the digest's spelling elsewhere and is
   removed here, once, by `receipt_part_digest()`.
4. **`degradations` are structured records, not `Degradation`s.** `Degradation` lives in
   `omniweave.route`, which `omniweave_core` may not import; the receipt carries each as the mapping
   its `kind` and fields serialise to.
5. **The report status is 09's three-way derivation over its signals, never a gate status**:
   `failed` when the gate failed; `passed` only when the gate passed with no introduced warning,
   every portability list empty and no normalization; `passed-with-warnings` otherwise. It takes
   the signals and not a `Receipt`, because a receipt never carries `failed` (ruling 2) and
   `ow out check` prints the status before any receipt exists.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import UnitOutcome

__all__ = [
    "RECEIPT_SCHEMA",
    "ArtefactDeterminism",
    "CheckValue",
    "Receipt",
    "console_line",
    "receipt_part_digest",
    "report_status",
]

RECEIPT_SCHEMA: Final = "omniweave.out-receipt/1"
_CHECK_NAME: Final = re.compile(r"[a-z][a-z0-9_]{2,39}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_VALUES: Final = frozenset(
    {"passed", "warning", "failed", "enforced-at-build", "not-applicable", "skipped"}
)


class ArtefactDeterminism(StrEnum):
    """09 section 6: a declared set, compared superset-wise, never a boolean."""

    PART = "part"
    BYTE = "byte"
    FRAME = "frame"
    RENDER = "render"


@dataclass(frozen=True, slots=True)
class CheckValue:
    """One row of `Receipt.checks`, written after `lower()`, against the artefact."""

    name: str
    value: Literal["passed", "warning", "failed", "enforced-at-build", "not-applicable", "skipped"]
    detail: str | None = None
    fixture: str | None = None
    """Required iff `value == "enforced-at-build"`: the kit test that proves the claim."""

    def __post_init__(self) -> None:
        if _CHECK_NAME.fullmatch(self.name) is None:
            raise ValueError(f"check name {self.name!r} is not ^[a-z][a-z0-9_]{{2,39}}$")
        if self.value not in _VALUES:
            raise ValueError(f"{self.name}: {self.value!r} is not one of {sorted(_VALUES)}")
        if (self.value == "enforced-at-build") != (self.fixture is not None):
            raise ValueError(
                f"{self.name}: a fixture is required iff the value is enforced-at-build"
            )


@dataclass(frozen=True, slots=True)
class Receipt:
    """09 section 5.3's receipt, refused unless consistent (ruling 1)."""

    schema: Literal["omniweave.out-receipt/1"]
    target: str
    slug: str
    artifact_gen: int
    output: Mapping[str, int | str]
    part_digest: str
    determinism: tuple[ArtefactDeterminism, ...]
    gate_status: GateStatus
    delivery: Literal["release", "draft"]
    checks: tuple[CheckValue, ...]
    units: Mapping[str, UnitOutcome]
    counts: Mapping[UnitOutcome, int]
    portability: Mapping[str, tuple[str, ...]]
    normalizations: tuple[Mapping[str, str], ...]
    degradations: tuple[Mapping[str, Any], ...]
    skipped_checks: tuple[Mapping[str, str], ...]
    truncations: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise ValueError(f"receipt schema {self.schema!r} is not {RECEIPT_SCHEMA!r}")
        names = [c.name for c in self.checks]
        repeated = sorted(n for n, k in Counter(names).items() if k > 1)
        if repeated:
            raise ValueError(f"check names repeat: {repeated}")
        if dict(self.counts) != dict(Counter(self.units.values())):
            raise ValueError(f"counts {dict(self.counts)} are not the tally of the units")
        if ArtefactDeterminism.PART not in self.determinism:
            raise ValueError("determinism must include part: the floor every target has")
        if _HEX64.fullmatch(self.part_digest) is None:
            raise ValueError(f"part_digest {self.part_digest!r} is not 64 hex (ruling 3)")
        if not {"path", "bytes", "sha256"} <= set(self.output):
            raise ValueError(f"output {sorted(self.output)} needs path, bytes and sha256")
        expected = GateStatus.PASSED if self.delivery == "release" else GateStatus.MANUAL_REQUIRED
        if self.gate_status is not expected:
            raise ValueError(
                f"a {self.delivery} receipt carries gate {expected}, not {self.gate_status}"
            )

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target": self.target,
            "slug": self.slug,
            "artifact_gen": self.artifact_gen,
            "output": dict(self.output),
            "part_digest": self.part_digest,
            "determinism": [d.value for d in self.determinism],
            "gate_status": self.gate_status.value,
            "delivery": self.delivery,
            "checks": [
                {
                    k: v
                    for k, v in (
                        ("name", c.name),
                        ("value", c.value),
                        ("detail", c.detail),
                        ("fixture", c.fixture),
                    )
                    if v is not None
                }
                for c in self.checks
            ],
            "units": {u: o.value for u, o in self.units.items()},
            "counts": {
                o.value: n for o, n in sorted(self.counts.items(), key=lambda kv: kv[0].value)
            },
            "portability": {k: list(v) for k, v in self.portability.items()},
            "normalizations": [dict(n) for n in self.normalizations],
            "degradations": [dict(d) for d in self.degradations],
            "skipped_checks": [dict(s) for s in self.skipped_checks],
            "truncations": [dict(t) for t in self.truncations],
        }


def receipt_part_digest(prefixed: str) -> str:
    """Ruling 3: `opc.part_digest()`'s `sha256:<hex>` as the receipt's hex."""
    hex_digest = prefixed.removeprefix("sha256:")
    if _HEX64.fullmatch(hex_digest) is None:
        raise ValueError(f"{prefixed!r} is not a sha256 digest")
    return hex_digest


def report_status(
    gate: GateStatus,
    introduced_warning_count: int,
    portability: Mapping[str, tuple[str, ...]],
    normalizations: tuple[Mapping[str, str], ...],
) -> str:
    """Ruling 5: `failed`, `passed` or `passed-with-warnings`; never a gate status."""
    if gate is GateStatus.FAILED:
        return "failed"
    clean = (
        gate is GateStatus.PASSED
        and introduced_warning_count == 0
        and not any(portability.values())
        and not normalizations
    )
    return "passed" if clean else "passed-with-warnings"


def console_line(receipt: Receipt, introduced_warning_count: int) -> str:
    """09 section 5.3's one-line console receipt, printed always."""
    counts = " ".join(
        f"{outcome.value}={receipt.counts[outcome]}"
        for outcome in UnitOutcome
        if receipt.counts.get(outcome)
    )
    determinism = ",".join(d.value for d in receipt.determinism)
    status = report_status(
        receipt.gate_status, introduced_warning_count, receipt.portability, receipt.normalizations
    )
    return (
        f"[POSTFLIGHT] slug={receipt.slug} gen={receipt.artifact_gen} "
        f"status={status} gate={receipt.gate_status.value} "
        f"units={len(receipt.units)}\n"
        f"             {counts} determinism={determinism} bytes={receipt.output['bytes']}"
    )
