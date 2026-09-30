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

**`encrypt` restores nothing: the user does what the refusal says, then runs the fix.** An
encrypted file is not damaged bytes; it is a file whose password the build was not given, and the
file stays encrypted (ADR-15 D15.6). Gate 9's detail says how to give it one on this machine
(D15.5): an `OW_SECRET_<NAME>` variable and a `password_file` line. `supply_password()` reads both
out of that detail and nowhere else, so the fourth clause holds only if the message a user would
follow is one that works: a detail that stopped naming the line would fail the pair by name.

**`inflate` restores nothing either: the user raises the limit, then runs the fix.** The fixture is
built with `[ingest] max_parts = INFLATE_MAX_PARTS` (`Injector.config`), and the PDF is padded to
one page above it (D644). Gate 9's detail names the count and the value that admits it, and
`raise_limit()` sets the `OMNIWEAVE_INGEST_MAX_PARTS` twin the detail names, and nothing else.

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

import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.retrieve.types import ABSENCE_GATES

from omniweave_conform.pdfcrypt import encrypt_pdf
from omniweave_conform.pdfpages import pad_pages

if TYPE_CHECKING:
    from omniweave_core.retrieve.verdict import Verdict

__all__ = [
    "DAMAGE_PASSWORD",
    "INFLATE_MAX_PARTS",
    "INJECTORS",
    "MASK",
    "PASSWORD_FILE",
    "TABLE",
    "Assessment",
    "Cause",
    "Clause",
    "FixRefusedError",
    "Injector",
    "Observed",
    "Repair",
    "Row",
    "assess",
    "chaos",
    "encrypt",
    "inflate",
    "mask_format",
    "observed",
    "raise_limit",
    "split_fix",
    "supply_password",
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


def chaos(data: bytes) -> bytes:
    """13:1285: *"truncates a part mid-stream at a fixed byte offset"*. The offset is the midpoint.

    A PDF loses its cross-reference table and `%%EOF`, and an OOXML file its ZIP central directory,
    which are what `route.detect.structural_check` reads (05:2240). Half and not a constant,
    because the fixtures are a kilobyte and a 4 KiB offset would leave most of them whole.
    """
    if len(data) < 2:  # noqa: PLR2004 -- one byte cannot be cut in two
        msg = f"chaos needs at least 2 bytes to cut, and got {len(data)}"
        raise ValueError(msg)
    return data[: len(data) // 2]


DAMAGE_PASSWORD: Final[str] = "ow-damage"  # noqa: S105 -- a fixture's, by design
"""The user password `encrypt` applies, and the one `supply_password` gives back."""

PASSWORD_FILE: Final[str] = "passwords.toml"  # noqa: S105 -- a file name
"""The password file `supply_password` writes, beside the fixture's `omniweave.toml`."""


def encrypt(data: bytes) -> bytes:
    """13:1283 as ADR-15 D15.6 rules it: *"user-password encryption to the document"*.

    RC4-128 under a user password and a different owner password, so pdfium refuses the file with
    no password and `gate.encrypted` refuses the unit. `pdfcrypt.encrypt_pdf` refuses a PDF with
    an object stream or a cross-reference stream by name, which is a fixture this cannot damage.
    """
    return encrypt_pdf(data, user_password=DAMAGE_PASSWORD, owner_password=DAMAGE_PASSWORD + "-o")


@dataclass(frozen=True, slots=True)
class Repair:
    """What a user does before the fix, as the damaged run's cause says: files, and environment.

    `append` maps a path relative to the fixture's project to the text appended to it, and `env`
    is added to the fix child's environment. The secret is in `env` and nowhere on disk.
    """

    append: Mapping[str, str] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)


_LINE: Final = re.compile(r"add the line `(.+?)` to the password file")
_VARIABLE: Final = re.compile(r"\bset (OW_SECRET_[A-Z0-9_]+)\b")


def supply_password(detail: str) -> Repair:
    """The password, supplied the way gate 9's `encrypted` detail says (ADR-15 D15.5).

    The detail's `OW_SECRET_<NAME>` variable, set to `DAMAGE_PASSWORD`, and its `password_file`
    line, written to `PASSWORD_FILE` and named by `[ingest] password_file`. Raises
    `FixRefusedError` when the detail does not name both, which is the fourth clause failing.
    """
    line, variable = _LINE.search(detail), _VARIABLE.search(detail)
    if line is None or variable is None:
        msg = (
            "the encrypted cause does not say how to supply a password: it names no "
            f"{'password_file line' if line is None else 'OW_SECRET_ variable'} (ADR-15 D15.5)"
        )
        raise FixRefusedError(msg)
    return Repair(
        append={
            PASSWORD_FILE: line.group(1) + "\n",
            "omniweave.toml": f'\n[ingest]\npassword_file = "{PASSWORD_FILE}"\n',
        },
        env={variable.group(1): DAMAGE_PASSWORD},
    )


INFLATE_MAX_PARTS: Final[int] = 3
"""The `[ingest] max_parts` an `inflate` fixture is built under. D644.

Small, so the padded file is a kilobyte and parses in a moment, and not below any pristine file's
count: the archive's longest PDF has three pages, which is also why one of the two fixtures is it,
padded by one page."""


def inflate(data: bytes) -> bytes:
    """13:1294: *"generates a fixture exactly one row above a `[limits]` value"*.

    The row is a page, since a PDF's `unit.part_count` is its page count, and the value is
    `INFLATE_MAX_PARTS`, which `Injector.config` sets. `pdfpages.pad_pages` appends copies of the
    last page in an incremental update, so the pristine bytes are the file's first bytes still.
    """
    return pad_pages(data, to_pages=INFLATE_MAX_PARTS + 1)


_LIMIT: Final = re.compile(r"\bset (OMNIWEAVE_INGEST_MAX_PARTS)=(\d+)\b")


def raise_limit(detail: str) -> Repair:
    """The limit, raised the way gate 9's `resource_limit` detail says (D644).

    The detail names both forms of `[ingest] max_parts`: the file's line and its environment twin.
    The twin is the one a repair can set without rewriting the fixture's `omniweave.toml`, whose
    `[ingest]` table already holds the lower value. Raises `FixRefusedError` when the detail names
    no value, which is the fourth clause failing.
    """
    found = _LIMIT.search(detail)
    if found is None:
        msg = (
            "the resource_limit cause does not say which limit to raise: it names no "
            "OMNIWEAVE_INGEST_MAX_PARTS value (D644)"
        )
        raise FixRefusedError(msg)
    return Repair(env={found.group(1): found.group(2)})


@dataclass(frozen=True, slots=True)
class Injector:
    """One built Injector: its row, the damage, and the file suffixes it applies to."""

    row: Row
    damages: str
    applies_to: frozenset[str]
    transform: Callable[[bytes], bytes]
    restores_source: bool
    """True when the damage is to the user's own file (D640): the fix runs after a restore."""
    repair: Callable[[str], Repair] | None = None
    """What the user does before the fix, read from the damaged run's cause detail (`encrypt`)."""
    config: str = ""
    """TOML the damaged project's `omniweave.toml` ends with: the `[limits]` value (`inflate`)."""

    @property
    def name(self) -> str:
        return self.row.name


INJECTORS: Final[Mapping[str, Injector]] = MappingProxyType(
    {
        "encrypt": Injector(
            row=next(row for row in TABLE if row.name == "encrypt"),
            damages="applies user-password encryption to the document",
            applies_to=frozenset({".pdf"}),
            transform=encrypt,
            restores_source=False,
            repair=supply_password,
        ),
        "chaos": Injector(
            row=next(row for row in TABLE if row.name == "chaos"),
            damages="truncates a part mid-stream at a fixed byte offset",
            applies_to=frozenset({".docx", ".xlsx", ".pptx", ".pdf"}),
            transform=chaos,
            restores_source=True,
        ),
        "mask_format": Injector(
            row=next(row for row in TABLE if row.name == "mask_format"),
            damages="rewrites the leading magic bytes so no enabled driver accepts the unit",
            applies_to=frozenset({".docx", ".xlsx", ".pptx", ".pdf"}),
            transform=mask_format,
            restores_source=True,
        ),
        "inflate": Injector(
            row=next(row for row in TABLE if row.name == "inflate"),
            damages="generates a fixture exactly one row above a [limits] value",
            applies_to=frozenset({".pdf"}),
            transform=inflate,
            restores_source=False,
            repair=raise_limit,
            config=f"\n[ingest]\nmax_parts = {INFLATE_MAX_PARTS}\n",
        ),
    }
)
"""The Injectors built, each with its passing assertion (13:1314): `encrypt` (D643),
`mask_format` (D640), `chaos` (D641) and `inflate` (D644). `TABLE` order, so the report reads as
the plan's table does."""


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
