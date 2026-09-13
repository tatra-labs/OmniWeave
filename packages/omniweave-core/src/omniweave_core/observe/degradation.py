"""`Degradation` -- the framework's one typed downgrade record, its twenty-seven kinds, and the
roll-up the manifest stores.

15-observability.md:964-1168 is *"the type's sole home"* (charter section 9 erratum `E15`) and this
module is that section: the `Literal`, the record, the six rules, the twenty-seven-row register, the
seven that force `degraded`, and `DegradationRollup`. Everything here is a transcription except the
two places marked otherwise, and both are reported.

**It is carried, never raised.** 02-architecture.md section 7.1's six-vocabulary table places it
beside `OwError`, `Diag`, `Finding`, `Rejection` and the `quarantine` row: an `OwError` stops
something, a `Degradation` records that something continued in a worse state. Nothing in this module
subclasses `Exception` and nothing in it can be raised.

## Why this is landing at P4 and not where its roadmap row put it

16-roadmap.md:414 schedules `Degradation` in **W2.1**, inside `omniweave_core.model`, and P2 shipped
that cell without it. 15:975 homes the file at `omniweave_core/observe/degradation.py` instead. Two
homes, one type, and neither built -- so four cells have been transcribing its `kind` literal rather
than constructing it:

| site | the literal it carries | what it wanted |
|---|---|---|
| `host/subproc.py`'s `IsolationShortfall.DEGRADATION_KIND` | `"isolation_shortfall"` | row 12 |
| `omniweave/run/dispatch.py`'s `REGEN_DEGRADATION_KIND` | `"budget"` | row 1 |
| `events.py`'s `EVENTS_DROPPED_DEGRADATION` | `"events_dropped"` | row 27 |
| `operator.py`'s `StepResult.degradations` | a quoted forward reference | the type itself |

W4.8's run manifest is what forces it: 15:1149 types `manifest.degradations` as
`dict[DegradationKind, DegradationRollup]`, and 15:1155 prints `DegradationRollup` as *"the VALUE of
one `manifest.degradations[<kind>]` entry"* -- the roll-up exists **for** the manifest and cannot
land before the type it rolls up. So this is a P2 debt discharged at the cell that needed it, not P7
work pulled forward. Reported, with the two homes.

## The one field that is not the printed type, and why

15:976 says `rung_reached` is `omniweave_core.route.rung.Rung` (05-ingest-and-routing.md section
5.2's escalation ladder: `GATE`, `DECODE`, `PAGE`, `REGEN`, `DEGRADE`). That module is **W5.4**
(16-roadmap.md:606) and does not exist. Unlike `operator.py`'s five quoted forward references this
one cannot be quoted, because this module is **T-SCHEMA**: `tools/schemagen.py` resolves its
annotations with `typing.get_type_hints()` to emit `schema/run-manifest-v1.json`, and there an
unresolvable name is a `NameError` rather than a suppressed lint.

So the field ships as `str | None` carrying `Rung.name`, which is what the wire form is either way,
with `RUNG_LADDER` below transcribing the five member names so the value can be checked against them
today and `Rung` can replace both the day W5.4 lands. Reported.

**Not to be confused with `omniweave_core.work.Rung`**, which is a row of 08-runtime.md section
1.6's RETRY ladder -- a different type with the same name in the same distribution. That collision
is the plan's and is noted here rather than resolved, because renaming either is a terminology-lock
change.

## What is deliberately NOT here

* **`FORCES_DEGRADED`'s consumer.** 15:1163 puts `build_verdict()` and the fifteen absence gates in
  07-store-and-retrieval.md section 6; this module exports the set and reads none of it.
* **`schema/degradation-v1.json`.** 15:975 says it is generated from this module and byte-diffed by
  G6, and it is not one of the thirteen schemas that 02 row 49, 11 section 1.7 and 18 section 8 all
  enumerate -- three lists that agree with each other and not with this one. Reported; the schema is
  not invented here, because a fourteenth file under `schema/` that `tools/schemagen.py`'s inventory
  does not carry is a hand-written file in a T-GENERATED directory.
* **The per-carrier serialisation.** A `Degradation` lives in `route_decision.degradations`,
  `artifact.degradations`, the query-ledger row and the run manifest (rule 4), and each of those
  rows already names its own subject -- which is exactly why this record carries no `run_id`,
  `query_hash` or `artifact_gen`.

Specified in 15-observability.md section 6.3, 02-architecture.md section 7.1, and
_notes/charter.md section 5 X21 with section 9 erratum E15.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, get_args

from omniweave_core.errors import ConfigError

__all__ = [
    "CHARTER_KINDS",
    "DEGRADATION_KINDS",
    "ERRATUM_E15_KINDS",
    "FORCES_DEGRADED",
    "MAX_ROLLUP_PARTS",
    "RESERVED_KINDS",
    "RUNG_LADDER",
    "Degradation",
    "DegradationKind",
    "DegradationRollup",
    "register_order",
    "rollup",
]


# =============================================================================================
# 1. The closed vocabulary. Twenty-seven, extended by literal, never re-invented per layer
# =============================================================================================

DegradationKind = Literal[
    # routing and admission
    "budget",
    "signal_unavailable",
    "driver_unavailable",
    "acceptor_exhausted",
    "rung_ceiling",
    "policy_pruned",
    "auto_demote",
    "no_driver",
    # drivers, isolation, packaging and the toolchain
    "discovery_slow",
    "quarantine",
    "deprecation",
    "isolation_shortfall",
    "toolchain_missing",
    "pin",
    # store, cache and the read path
    "store_busy",
    "stat_stale",
    "pushdown_unavailable",
    "vector_scan_over_budget",
    "hub_capped",
    "segment_lift_capped",
    "cache_disabled_no_space",
    "ledger_reset_by_compaction",
    # generation, governance and telemetry
    "grant_missing",
    "compile_normalized",
    "scope_clamped",
    "calibration_stale",
    "events_dropped",
]
"""15-observability.md:978-996's literal, transcribed with its four comment groups.

*"TWENTY-SEVEN, closed. The register below is the normative list; adding a member is one edit to
that table, to this literal and to section 4.2's series-count note, in the same change."* A
`Literal` and not a `StrEnum` because that is what the plan prints and because `schemagen` renders
it as a closed `enum` in the generated schema either way -- and because charter section 5 X21's
*"extended by literal, never re-invented per layer"* is the rule this spelling states.

The order is the document's, not alphabetical: the four groups are how a reader finds a member, and
15:4.2 makes `ow_degradation_total{kind}` *"exactly twenty-seven series -- a closed enum, inside
section 4.1's cardinality contract, and the second metric after `ow_diag_total` whose series count
is a fact about a file in the repository rather than about the data."*"""

DEGRADATION_KINDS: Final[tuple[str, ...]] = get_args(DegradationKind)
"""The same twenty-seven as a tuple, in the literal's order. For iteration and for validation.

Derived with `get_args` rather than re-listed: two spellings of one closed vocabulary is the failure
mode the vocabulary exists to prevent, and INV-21 allows a fact one home."""

CHARTER_KINDS: Final[frozenset[str]] = frozenset(
    {
        "budget",
        "signal_unavailable",
        "driver_unavailable",
        "acceptor_exhausted",
        "policy_pruned",
        "auto_demote",
        "quarantine",
        "deprecation",
        "isolation_shortfall",
        "toolchain_missing",
        "pin",
        "hub_capped",
        "segment_lift_capped",
        "ledger_reset_by_compaction",
        "grant_missing",
        "calibration_stale",
    }
)
"""15:1128 -- *"Rows 1-4, 6, 7, 10-14, 19, 20, 22, 23 and 26 are the charter's sixteen."*

Carried because the split is the erratum's warrant: a reader asking why a closed literal grew needs
to see which members the charter admitted and which `E15` added, and a row number is not something
code can check. Sixteen here and eleven below, and the two partition the twenty-seven."""

ERRATUM_E15_KINDS: Final[frozenset[str]] = frozenset(DEGRADATION_KINDS) - CHARTER_KINDS
"""15:1129 -- *"Rows 5, 8, 9, 15-18, 21, 24, 25 and 27 are the eleven the charter's closed literal
did not admit and that written plan documents already construct -- registered as `15#1` in risks and
as `E15` in the charter's section 9 errata, whose closing condition is this table."*

A difference and not a second list, for `DEGRADATION_KINDS`' reason."""

RESERVED_KINDS: Final[frozenset[str]] = frozenset(
    {"acceptor_exhausted", "auto_demote", "toolchain_missing"}
)
"""15:1132 -- *"Three members ... are charter grants that no document constructs yet; their rows
name
the first site each will land in, so a reader can tell a reserved member from a live one."*

Declared rather than left implicit because "nothing constructs this yet" and "nothing should ever
construct this" look identical from a call site. Nothing here refuses a reserved member: they are
grants, and the first site to need one is entitled to it."""

FORCES_DEGRADED: Final[frozenset[str]] = frozenset(
    {
        "stat_stale",
        "pushdown_unavailable",
        "vector_scan_over_budget",
        "hub_capped",
        "segment_lift_capped",
        "scope_clamped",
        "calibration_stale",
    }
)
"""The seven of 15:1134 -- rows 16-20, 25 and 26. *"That is this type's entire interface to the
honest-absence contract, and it is small on purpose."*

15:1141-1147 gives the line the seven are on the far side of: a downgrade that happened during
INGEST *"is disclosed on the document and in the manifest and does not by itself make a later query
dishonest"*, and five more can occur during a query and still do not force it *"because each of them
changes what the SYSTEM did and not what the RANKING means: a lock wait, a pass-through cache, a
re-sent evidence block, an accepted rewrite, a dropped span. The seven that do force it each say the
same thing -- the ranking the caller is looking at is not the ranking the corpus supports."*

Read by `build_verdict()`, which is 07-store-and-retrieval.md section 6's and not this module's.
15:1166 is explicit that the set is defined here so *"the read path imports one name and this
document keeps the count."*"""

RUNG_LADDER: Final[tuple[str, ...]] = ("GATE", "DECODE", "PAGE", "REGEN", "DEGRADE")
"""05-ingest-and-routing.md section 5.2's escalation ladder, lowest first. NOT the retry ladder.

Here only because `rung_reached` cannot carry `omniweave_core.route.rung.Rung` until W5.4 builds it
-- the module docstring argues why a quoted forward reference is not available to a T-SCHEMA module.
Transcribing the five names is what lets the field be checked today; when `Rung` lands, the
annotation becomes `Rung | None` and this tuple goes with it.

`GATE` is 0 and `DEGRADE` is last, which is the order 05:838's table prints and the order the
generated `BEFORE INSERT` trigger of W5.4 enforces as `child.rung > parent.rung`."""


# =============================================================================================
# 2. The record, and the six rules that hold over it
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Degradation:
    """One downgrade, carried. 15-observability.md:995-1024, field for field and default for
    default.

    Eleven fields in four groups, and the grouping is the plan's: what happened (`kind`, `message`),
    what was downgraded (`unit_uri`, `parts_affected`, `wanted_driver`), the arithmetic when the
    cause was a bound (`unit_dim`, `spent`, `limit`, `rung_reached`), and the recovery (`knob`,
    `fix_command`).

    **`message` must name the knob or the command in prose** (rule 1). `knob` and `fix_command`
    carry the same fact machine-readably, and `knob = None` is *"a positive assertion, not an
    omission: it says a configuration change cannot help"* -- row 10's *"raise nothing -- fix the
    driver"* and row 12's *"none -- the platform is the limit"* are the two rows that mean it. The
    CI half of rule 1 -- resolving the quoted key out of a message template against the config and
    policy schemas -- is a test over the construction SITES, not a check this constructor can make:
    it needs the schemas, and a record built from a config value it has never seen is legitimate.

    **`unit_dim is None` implies `spent == limit == 0`** (rule 2), asserted below. *"Seventeen of
    the
    twenty-seven members carry no arithmetic, and a zero pair rendered as '0 of 0 spent' is the
    defect this rule exists to prevent."*

    **A resource that runs out is `kind="budget"` with a new `unit_dim`, never a new member** (rule
    3). Nothing here enforces that -- it is a rule about what a call site chooses -- but it is why
    `unit_dim` is an open `str` and `kind` is closed: VRAM pressure evicting a GPU group is
    `Degradation(kind="budget", unit_dim="vram_bytes", wanted_driver=...)` rather than a
    twenty-eighth member.

    **No `run_id`, `query_hash` or `artifact_gen`** (rule 4): *"The carrier identifies the subject
    ... Duplicating the key onto the record would give one fact two homes and two ways to
    disagree."*

    **`parts_affected` is the field name and the serialised key, everywhere** (rule 5). There is no
    short form and this module defines no wire alias; 15:1057 records that one charter transcript
    prints `parts:` and that it is *"wrong against this rule, not licensed by it."*

    **Every `Degradation` is visible on every surface it reaches** (rule 6, I18), so there is no
    suppressed variant and therefore no visibility flag on the record.
    """

    kind: DegradationKind
    message: str
    unit_uri: str | None = None
    parts_affected: tuple[int, ...] = ()
    wanted_driver: str | None = None
    unit_dim: str | None = None
    spent: int = 0
    limit: int = 0
    rung_reached: str | None = None
    knob: str | None = None
    fix_command: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DEGRADATION_KINDS:
            raise ConfigError(
                f"{self.kind!r} is not a DegradationKind; the vocabulary is closed at "
                f"{len(DEGRADATION_KINDS)} members",
                fix=(
                    "use one of the twenty-seven, or amend 15-observability.md section 6.3's "
                    "register, its literal and section 4.2's series-count note in one change"
                ),
            )
        if not self.message:
            raise ConfigError(
                f"a {self.kind} degradation with no message; rule 1 makes the message the human "
                f"half and it must name the knob or the command that would undo this",
                fix="give it one sentence naming the knob, or the remedy when no knob helps",
            )
        if self.unit_dim is None and (self.spent or self.limit):
            raise ConfigError(
                f"a {self.kind} degradation names no unit_dim and carries spent={self.spent} "
                f"limit={self.limit}; rule 2 makes a bound's arithmetic conditional on the bound",
                fix="name the exhausted dimension, or leave spent and limit at zero",
            )
        if self.spent < 0 or self.limit < 0:
            raise ConfigError(
                f"a {self.kind} degradation carries spent={self.spent} limit={self.limit}; "
                f"neither is ever negative",
                fix="pass the amount consumed and the bound it was measured against",
            )
        if self.rung_reached is not None and self.rung_reached not in RUNG_LADDER:
            raise ConfigError(
                f"{self.rung_reached!r} is not a rung; 05-ingest-and-routing.md section 5.2's "
                f"ladder is {RUNG_LADDER}",
                fix="pass Rung.name, or None on a read-path record -- the ladder is the router's",
            )
        if any(part < 1 for part in self.parts_affected):
            raise ConfigError(
                f"parts_affected {self.parts_affected} holds a part below 1; the ordinals are "
                f"1-BASED (15-observability.md:1002)",
                fix="pass 1-based part ordinals, which is what section 7's ingest report prints",
            )

    @property
    def forces_degraded(self) -> bool:
        """Whether an instance reaching a query forces `Verdict.state = "degraded"`. 15:1134."""
        return self.kind in FORCES_DEGRADED

    @property
    def is_bound(self) -> bool:
        """Whether this record carries arithmetic. Rule 2's predicate, named once."""
        return self.unit_dim is not None


# =============================================================================================
# 3. The roll-up: what the manifest stores, and why it stays bounded
# =============================================================================================

MAX_ROLLUP_PARTS: Final = 64
"""15:1153 -- *"matches `MAX_SPAN_BUFFER_EVENTS` (section 2.4); section 7's report prints a count."*

15:1151 gives the reason a roll-up exists at all: section 1.1 *"claims the manifest's
`degradations[]` is bounded because it is 'a dict keyed by a closed vocabulary'. That holds only
with a roll-up, because a 188-part document can produce 188 `budget` records."* With one, the
manifest is at most twenty-seven entries of bounded width, *"which is what makes it safe to rewrite
the manifest incrementally at every Stage boundary and at every `degrade()`."*

The number is deliberately the same as the span buffer's rather than independently chosen; both cap
a per-unit accumulation a reader will skim, and one number is one thing to reason about."""


@dataclass(frozen=True, slots=True)
class DegradationRollup:
    """One `manifest.degradations[<kind>]` entry. 15:1155-1164, field for field.

    **`truncated` is what stops a cap from reading as a total.** 15:1163: *"either cap was hit, so a
    reader never reads the cap as the total."* `n` is the honest count and always the full one --
    only `units` and `parts_affected` are capped -- so a 188-part document rolls up as `n = 188`
    with sixty-four units listed and `truncated = True`, and no reader has to guess.

    **No field has a default**, which is 15:1155-1164 as printed: every one of the eight is
    produced by the merge, and a default would let a caller build a half-merged entry the
    manifest then writes. `rollup()` is the only constructor a call site needs.

    **`exemplar` is the first record verbatim** because it *"carries message, knob and fix"* -- the
    three fields a human needs and the three a merge cannot combine. Merging two messages would
    produce a sentence neither call site wrote.

    **`first_ns` and `last_ns` are the host `Clock` at merge time**, injected and never ambient
    (15:1159, and 15:1160 states the reason in one clause: *"A driver contributes no field to the
    manifest"*). They are arguments to `rollup()` for the same reason `Event`'s two clocks are read
    by the sink: a timestamp that crossed a seam is not comparable with the host's.
    """

    kind: DegradationKind
    n: int
    first_ns: int
    last_ns: int
    units: tuple[str, ...]
    parts_affected: tuple[int, ...]
    truncated: bool
    exemplar: Degradation

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ConfigError(
                f"a rollup of {self.n} records; an entry exists because something was merged",
                fix="build these with rollup(), which refuses an empty sequence",
            )
        if self.exemplar.kind != self.kind:
            raise ConfigError(
                f"a {self.kind} rollup whose exemplar is a {self.exemplar.kind}",
                fix="roll up records of one kind; the manifest's key IS the kind",
            )
        if self.last_ns < self.first_ns:
            raise ConfigError(
                f"a rollup whose last_ns {self.last_ns} precedes its first_ns {self.first_ns}",
                fix="pass the host Clock's reading at each merge, which never goes backwards",
            )


def rollup(
    records: tuple[Degradation, ...] | list[Degradation],
    *,
    first_ns: int,
    last_ns: int | None = None,
) -> DegradationRollup:
    """Merge records of one kind into the entry the manifest stores. 15:1151-1164.

    Refuses a mixed-kind sequence rather than picking one: the manifest keys on the kind, so a
    rollup that silently dropped the odd record would put a `quarantine` under `budget` and lose it.

    `units` and `parts_affected` are **deduplicated and ordered** before the cap -- units in
    first-appearance order, parts ascending -- so two runs over the same records produce the same
    entry. Ordering `units` by appearance rather than sorting keeps the first document that
    degraded first in the list, which is the one an operator reads; parts are ordinals and sort.

    `last_ns` defaults to `first_ns`, which is the single-record case and the common one.
    """
    if not records:
        raise ConfigError(
            "rolling up no records; a manifest entry exists because something was merged",
            fix="call this with the records for one kind, or omit the entry",
        )
    kinds = {record.kind for record in records}
    if len(kinds) > 1:
        raise ConfigError(
            f"rolling up {len(kinds)} kinds together: {sorted(kinds)}. The manifest keys on the "
            f"kind, so one entry is one kind",
            fix="group by kind first; manifest.degradations[<kind>] is the grouping",
        )
    seen: dict[str, None] = {}
    parts: set[int] = set()
    for record in records:
        if record.unit_uri is not None:
            seen.setdefault(record.unit_uri, None)
        parts.update(record.parts_affected)
    units = tuple(seen)
    ordered_parts = tuple(sorted(parts))
    truncated = len(units) > MAX_ROLLUP_PARTS or len(ordered_parts) > MAX_ROLLUP_PARTS
    return DegradationRollup(
        kind=records[0].kind,
        n=len(records),
        first_ns=first_ns,
        last_ns=first_ns if last_ns is None else last_ns,
        units=units[:MAX_ROLLUP_PARTS],
        parts_affected=ordered_parts[:MAX_ROLLUP_PARTS],
        truncated=truncated,
        exemplar=records[0],
    )


_BY_KIND: Final[MappingProxyType[str, int]] = MappingProxyType(
    {kind: index for index, kind in enumerate(DEGRADATION_KINDS)}
)
"""Each member's position in the register, for a deterministic ordering of a manifest's entries.

The manifest is a JSON document a human diffs between runs, so its `degradations` map is written in
register order rather than in the order the run happened to degrade -- two runs that degraded the
same way produce the same bytes. `sorted(entries, key=register_order)` is the one call site."""


def register_order(kind: str) -> int:
    """This kind's row number, zero-based. Raises on a kind outside the closed vocabulary."""
    position = _BY_KIND.get(kind)
    if position is None:
        raise ConfigError(
            f"{kind!r} is not a DegradationKind",
            fix=f"use one of {len(DEGRADATION_KINDS)}: {', '.join(DEGRADATION_KINDS[:4])}, ...",
        )
    return position
