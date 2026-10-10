"""`GateStatus` and `gate_status()`: ten values, one release, one order. **D737.**

09-generation.md section 4.5 and section 15; charter OUT3, OUT4 and OUT5. `gate_status()` is
09's function as printed, its order the contract: a report is read for bytes before content, so a
stale report's error count never sends an agent to lines that moved.

## Rulings (the ledger's D737)

6. **Every status but `passed` names a meaning and a command, and no two meanings are one.** OUT5's
   test asserts it over the nine. The command is 09 section 4.5's clearing column as something that
   runs: `unreadable` is cleared by the check that rewrites `validation/final.json`, so it needs no
   delete first, and `failed` by the check that prints each finding's own `fix`.
7. **The exit is 09 section 15's table.** `passed` is 0, `restricted` 6 (the fix is a grant, not an
   edit) and every other status 8. `unverified` is 64 when every skipped check is an unmet `needs`
   and nothing was truncated, which is *"because a declared engine is absent"*; a truncation is the
   rule's defect and stays 8.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from omniweave_core.out.report import OutReport

__all__ = ["CLEARS", "REPORT_SCHEMA", "GateStatus", "clears", "exit_code", "gate_status"]

REPORT_SCHEMA: Final = "omniweave.out-report/1"


class GateStatus(StrEnum):
    """Ten values. Exactly one permits a release (OUT5)."""

    NOT_PROVIDED = "not-provided"
    UNREADABLE = "unreadable"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    NON_FINAL = "non-final"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    STALE = "stale"
    RESTRICTED = "restricted"
    MANUAL_REQUIRED = "manual-required"
    PASSED = "passed"


_CHECK: Final = "ow out check --target {target} --stage final --json"

CLEARS: Final[dict[GateStatus, tuple[str, str]]] = {
    GateStatus.NOT_PROVIDED: ("the gate was never run", _CHECK),
    GateStatus.UNREADABLE: ("the report exists and does not parse", _CHECK),
    GateStatus.UNSUPPORTED_SCHEMA: ("the report is another schema version's", _CHECK),
    GateStatus.NON_FINAL: (
        "an early, first-unit or unit report was offered as a release gate",
        _CHECK,
    ),
    GateStatus.STALE: (
        "the report's il_digest is not the bundle's: it describes other bytes",
        _CHECK,
    ),
    GateStatus.FAILED: ("errors were found; each finding names its own fix", _CHECK),
    GateStatus.UNVERIFIED: (
        "a check could not run, or a rule's findings were truncated: no finding proves nothing",
        _CHECK,
    ),
    GateStatus.RESTRICTED: (
        "a restricted cite or asset is in the artefact",
        "ow out assets --explain",
    ),
    GateStatus.MANUAL_REQUIRED: (
        "a unit needs a human",
        "ow out compile --target {target} --accept-manual",
    ),
}
"""Ruling 6: status -> (what it means, the command that clears it). `passed` has no row."""


def gate_status(  # noqa: PLR0911 -- 09 section 4.5 as printed: one return a status.
    report: OutReport | None, il_digest: bytes
) -> tuple[GateStatus, int]:
    """09 section 4.5, as printed: the status and `introduced_warning_count`."""
    if report is None:
        return GateStatus.NOT_PROVIDED, 0
    if report.unreadable:
        return GateStatus.UNREADABLE, 0
    if report.schema != REPORT_SCHEMA:
        return GateStatus.UNSUPPORTED_SCHEMA, 0
    n = report.introduced_warning_count
    if report.stage != "final":
        return GateStatus.NON_FINAL, n
    if report.il_digest != il_digest:
        return GateStatus.STALE, n
    if report.counts["error"] > 0:
        return GateStatus.FAILED, n
    if report.skipped_checks or report.truncations:
        return GateStatus.UNVERIFIED, n
    if report.restricted_items:
        return GateStatus.RESTRICTED, n
    if report.manual_units:
        return GateStatus.MANUAL_REQUIRED, n
    return GateStatus.PASSED, n


def clears(status: GateStatus, target: str) -> tuple[str, str] | None:
    """Ruling 6: what `status` means and the command that clears it, or `None` for `passed`."""
    row = CLEARS.get(status)
    if row is None:
        return None
    means, fix = row
    return means, fix.format(target=target)


def exit_code(status: GateStatus, report: OutReport | None) -> int:
    """Ruling 7: 09 section 15's mapping."""
    if status is GateStatus.PASSED:
        return 0
    if status is GateStatus.RESTRICTED:
        return 6
    if status is GateStatus.UNVERIFIED and report is not None and not report.truncations:
        return 64
    return 8
