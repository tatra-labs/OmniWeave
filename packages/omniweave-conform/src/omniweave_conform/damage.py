"""The paired-damage suite's library half: the thirteen Injectors and the three assertions.

13-quality.md section 8.6, Construction 2: *"Inject one `Diag` code at a time into a pristine
corpus and assert the answer degrades to a **named cause** rather than a confident zero."*
`degradation_detection` is a **hard gate at 1.000** over every `(Injector, fixture)` pair, and
13:2118 defines the set as *"one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`"*, which is thirteen.
`TABLE` is that population, in 13:1281-1295's order, with the gate 07:2218-2232 says each reaches.

**An Injector lands behind its own passing assertion, in the same PR, or not at all** (13:1314).
So `INJECTORS` holds only the ones built, and `TABLE` names the rest. The report prints both,
which keeps a hard gate over one Injector from reading as a claim about thirteen.

## The three assertions, and a fourth that makes them mean something

13:1297: *"the damaged run's `Verdict.state` is `degraded` (never `ok`, never `absent`); the fired
gate list contains the expected gate **in precedence order**; and the `DegradeCause.fix` string is
a command that, when executed against the damaged store, produces an undamaged run."* `assess()`
checks those three, and one more first: the pristine run must not already name the expected gate
with the Injector's code. Otherwise the fixture is vacuous, and 13:1320 names that failure:
*"an injector whose gate passes vacuously is an injector that tests nothing"*.

**A source-bytes Injector restores the source before the fix runs. D640.** `mask_format`, `chaos`
and `encrypt` damage the user's own file, and no command repairs bytes the user owns: the fix
for them is the command that reads the file again, which is only a fix once the file is sound.
So the counterfactual is *restore, then run the fix*, and the assertion is that together they
produce the pristine run's verdict. An Injector that damages the store instead (`drop_part`,
`strip_integrity`) runs its fix with nothing restored, as 13:1297 has it.

## The fix is split, not shelled

13:1306: *"the harness parses the string against the `ow` Action registry, refuses anything whose
verb is not a known Action or whose parameters are not that Action's, and invokes it in-process
with no shell."* `split_fix()` is the half this package can own: POSIX `shlex`, `ow` first, and no
empty string, because an empty `fix` for an Injector's cause is *"a failure of
`degradation_detection`, not an exemption from it"*. Admission against the registry needs
`omniweave`, which this distribution may not import (11-repo-layout.md:614-618), so the runner
passes it in as `admit`.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.retrieve.types import ABSENCE_GATES

if TYPE_CHECKING:
    from omniweave_core.retrieve.verdict import Verdict

__all__ = [
    "INJECTORS",
    "MASK",
    "TABLE",
    "Assessment",
    "Cause",
    "Clause",
    "FixRefusedError",
    "Injector",
    "Observed",
    "Row",
    "assess",
    "mask_format",
    "observed",
    "split_fix",
]

PARSE_GAP: Final[str] = "parse_gap_in_scope"


@dataclass(frozen=True, slots=True)
class Row:
    """One row of 13:1281-1295: the Injector, the `Diag` it injects, and the gate it must fire."""

    name: str
    diag: str
    gate: str


TABLE: Final[tuple[Row, ...]] = (
    Row("encrypt", "OW_ENCRYPTED", PARSE_GAP),
    Row("strip_text_layer", "OW_NEEDS_OCR", PARSE_GAP),
    Row("chaos", "OW_MALFORMED", PARSE_GAP),
    Row("drop_part", "OW_MISSING_PART", "coverage_incomplete"),
    Row("budget", "OW_TRUNCATED_BY_BUDGET", "pending_work_in_scope"),
    Row("deny_probe", "OW_DRIVER_UNAVAILABLE", "channel_unavailable"),
    Row("downgrade_origin_span", "OW_ORIGIN_SPAN_DOWNGRADE", PARSE_GAP),
    Row("rotate_embedder", "OW_INDEX_MODEL_CHANGED", "space_mismatch"),
    Row("stall", "OW_TIMEOUT", "timed_out"),
    Row("mask_format", "OW_UNSUPPORTED_FORMAT", PARSE_GAP),
    Row("inflate", "OW_RESOURCE_LIMIT", PARSE_GAP),
    Row("strip_integrity", "OW_INTEGRITY_UNCHECKED", PARSE_GAP),
    Row("synopsize", "OW_TABLE_SYNOPSIS_ONLY", PARSE_GAP),
)
"""The thirteen, one per member of `ABSENCE_BLOCKING_DIAGS` and in its order (13:2118).

The gate column is 07:2218-2232's join: six gates are `Diag`-driven, and gate 9 takes eight of
the thirteen. A test holds the diag column to `ABSENCE_BLOCKING_DIAGS`, so a fourteenth code
cannot join that tuple without an Injector row to go with it.
"""

MASK: Final[bytes] = b"\x00OWMASK\x00"
"""What `mask_format` writes over a unit's first eight bytes.

It matches no magic of 05 section 2.2, and the NUL is what stops detection's text probes and its
extension rung from reading the file as anything else: `route.detect` trusts an extension only on
bytes that are not binary. So detection names `unknown`, and `gate.unsupported-source` refuses."""


def mask_format(data: bytes) -> bytes:
    """13:1292: *"rewrites the leading magic bytes so no enabled driver accepts the unit"*.

    The length is kept, so every byte past the mask is the pristine file's and the damage is the
    magic and nothing else.
    """
    if len(data) <= len(MASK):
        msg = f"mask_format needs more than {len(MASK)} bytes to mask, and got {len(data)}"
        raise ValueError(msg)
    return MASK + data[len(MASK) :]


@dataclass(frozen=True, slots=True)
class Injector:
    """One built Injector: its row, the damage, and the file suffixes it applies to."""

    row: Row
    damages: str
    applies_to: frozenset[str]
    transform: Callable[[bytes], bytes]
    restores_source: bool
    """True when the damage is to the user's own file (D640): the fix runs after a restore."""

    @property
    def name(self) -> str:
        return self.row.name


INJECTORS: Final[Mapping[str, Injector]] = MappingProxyType(
    {
        "mask_format": Injector(
            row=next(row for row in TABLE if row.name == "mask_format"),
            damages="rewrites the leading magic bytes so no enabled driver accepts the unit",
            applies_to=frozenset({".docx", ".xlsx", ".pptx", ".pdf"}),
            transform=mask_format,
            restores_source=True,
        ),
    }
)
"""The Injectors built. One of thirteen, and each lands with its passing assertion (13:1314)."""


@dataclass(frozen=True, slots=True)
class Cause:
    """One `DegradeCause`, as the assertions read it."""

    gate: str
    diag_codes: tuple[str, ...]
    fix: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Observed:
    """What a run's `Verdict` said, reduced to what the three assertions compare."""

    state: str
    gates: tuple[str, ...]
    causes: tuple[Cause, ...]

    def cause(self, gate: str) -> Cause | None:
        return next((one for one in self.causes if one.gate == gate), None)

    def names(self, row: Row) -> bool:
        """Whether this run fires `row.gate` with `row.diag` behind it."""
        found = self.cause(row.gate)
        return found is not None and (row.gate != PARSE_GAP or row.diag in found.diag_codes)


def observed(verdict: Verdict) -> Observed:
    """A `Verdict` reduced to `Observed`."""
    return Observed(
        state=str(verdict.state),
        gates=tuple(verdict.gates),
        causes=tuple(
            Cause(
                gate=one.gate,
                diag_codes=tuple(one.diag_codes),
                fix=one.fix,
                detail=one.detail,
            )
            for one in verdict.degraded_because
        ),
    )


class FixRefusedError(ValueError):
    """A `fix` string the harness will not run. 13:1308: a failure, never an exemption."""


def split_fix(fix: str) -> tuple[str, ...]:
    """`fix` as an argv, POSIX-split and never shelled. Raises `FixRefusedError` with the reason.

    The split is POSIX `shlex` because `store.reader` quotes a path with `shlex.quote`. There is
    no shell, so a `;` or a `|` is a character of an argument and not an operator, and whatever it
    spells is refused by `admit` as a parameter the Action does not take.
    """
    if not fix.strip():
        msg = "the cause carries no fix, so there is no command to run (13:1308: a failure)"
        raise FixRefusedError(msg)
    try:
        argv = tuple(shlex.split(fix, posix=True))
    except ValueError as exc:
        msg = f"the fix does not split as a command line: {exc}"
        raise FixRefusedError(msg) from exc
    if not argv or argv[0] != "ow":
        msg = f"the fix is not an `ow` command: {fix!r}"
        raise FixRefusedError(msg)
    return argv


@dataclass(frozen=True, slots=True)
class Clause:
    """One assertion's outcome, with the sentence a failing run prints."""

    name: str
    ok: bool
    why: str


@dataclass(frozen=True, slots=True)
class Assessment:
    """The four clauses of one `(Injector, fixture)` pair. The pair passes iff all four hold."""

    injector: str
    fixture: str
    clauses: tuple[Clause, ...]

    @property
    def ok(self) -> bool:
        return all(clause.ok for clause in self.clauses)


def _in_precedence_order(gates: Sequence[str]) -> bool:
    return tuple(gates) == tuple(gate for gate in ABSENCE_GATES if gate in gates)


def assess(
    injector: Injector,
    fixture: str,
    *,
    pristine: Observed,
    damaged: Observed,
    fixed: Observed | None,
    fix_refusal: str | None = None,
) -> Assessment:
    """13:1297's three assertions, after the counterfactual that keeps them from being vacuous.

    `fixed` is the run after the fix executed, or `None` when it could not run; `fix_refusal`
    then says why. A fix that ran and left the verdict different from the pristine one fails the
    third clause by name, because a fix that does not fix is the failure 13:1297 is written for.
    """
    row = injector.row
    cause = damaged.cause(row.gate)
    clauses = [
        Clause(
            "counterfactual",
            not pristine.names(row),
            f"the pristine run already fires {row.gate} with {row.diag}, so the fixture is vacuous"
            if pristine.names(row)
            else f"the pristine run is {pristine.state} and does not fire {row.gate}",
        ),
        Clause(
            "degraded",
            damaged.state == "degraded",
            f"the damaged run is {damaged.state}; it must be degraded, never ok and never absent",
        ),
        Clause(
            "named cause",
            damaged.names(row) and _in_precedence_order(damaged.gates),
            f"gates {list(damaged.gates)}: {row.gate} must be among them with {row.diag} behind "
            f"it, in ABSENCE_GATES order"
            + ("" if cause is None else f"; its cause says: {cause.detail}"),
        ),
    ]
    if fixed is None:
        clauses.append(Clause("fix fixes", False, fix_refusal or "the fix did not run"))
    else:
        same = (fixed.state, fixed.gates) == (pristine.state, pristine.gates)
        clauses.append(
            Clause(
                "fix fixes",
                same,
                f"after `{'' if cause is None else cause.fix}` the run is {fixed.state} with "
                f"gates {list(fixed.gates)}; the pristine run is {pristine.state} with gates "
                f"{list(pristine.gates)}",
            )
        )
    return Assessment(injector=injector.name, fixture=fixture, clauses=tuple(clauses))
