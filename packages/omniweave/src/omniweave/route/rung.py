"""`Rung` -- the seven-member escalation ladder -- and `LANES`, which is derived and not declared.

02-architecture.md section 2 row 35 gives `omniweave.route` *"`Rung` (7, closed, ordered)"* and
*"`LANES` (open)"*; 11-repo-layout.md:250 puts `rung.py` in the tree; 05-ingest-and-routing.md
Part 3 (:836-844) prints the seven rows this module transcribes.

**This file is W5.4's first half, landed at W5.1, for the same reason `spend.py` is here.**
16-roadmap.md:606 schedules `route/rung.py` with W5.4 beside the `BEFORE INSERT` trigger, the
compiler-parity gate and the three exact counters -- none of which this file contains. What W5.1
needs is the ordinal type itself: `SignalSpec.requires` is `tuple[Rung, ...]` (05:2116) and the
day-one registry names `DECODE`, `PAGE` and `REGEN` in that column, so the registry cannot be read
at all without it. `route/__init__.py` already states the precedent in its own words -- *"`spend.py`
is here and the rest is P5's"*, because W4.5's ledger could not be checked without a pricer. Same
move, same argument, and the trigger stays W5.4's.

## The ladder is ordinal, and `DEGRADE` is why that is not obvious

| `Rung` | what runs | cost per part |
|---|---|---|
| `GATE` = 0 | nothing: limits, encryption, format, corpus and trigger clamps, lanes | 0 |
| `DECODE` = 1 | deterministic decode of a text layer, office XML or a text format | 4.4 ms |
| `REPAIR` = 2 | surgical per-block repair on an otherwise-good part | one crop call |
| `PAGE` = 3 | one full-part model call | olmocr p50 2.4 s, 854 micros |
| `REGEN` = 4 | regeneration of the failed subset on a temperature ladder | 1-3x a `PAGE` |
| `DEGRADE` = 5 | a different, **cheaper** strategy, always marked `degraded` | <= `DECODE` |
| `ENRICH` = 6 | a cross-part model pass, scoped by block type, non-fatal | varies; billed |

`DEGRADE` sits above `PAGE` and costs less than `DECODE`. 05:862 makes that the whole reason the
ordinal and the price are two types: *"It has a higher `Rung` than `PAGE` while running a cheaper
driver. That is the entire reason `Rung` and `Spend` are separate types: `child.rung > parent.rung`
stays enforceable (RT8's trigger) while the cost goes down."* So an `IntEnum` -- the ordering is
load-bearing, it is the monotone loop's iteration order (05:1090), and it is the comparison RT8's
trigger performs in SQL -- and no cost, capability or driver on the member. The blueprint's numbered
tiers `0..3` plus `S` are struck for exactly the conflation this avoids (05:830).

## `LANES` is `frozenset(member.value for member in Lane)` and INV-21 says so in those words

The plan contradicts itself about where the lane vocabulary lives, and
`omniweave_core.model.enums.Lane`'s docstring settles it against itself: charter.md:2415 calls the
eleven-member registry *"An OPEN registry"* and 02-architecture.md:259 puts a `LANES` frozenset
here, while charter.md:942, charter.md:4834 and 03:2311 all list `lane` among `enum_val`'s CLOSED
domains. The `enum_val` DDL wins because `ord` IS THE STORED VALUE, and `Lane`'s docstring then
prescribes this module's half verbatim: *"A `LANES` frozenset, if `omniweave.route` still wants one,
is `frozenset(member.value for member in Lane)` and not a second declaration (INV-21)."*

So `LANES` is a comprehension over the enum and has no literal in this file. A second literal would
be the defect INV-21 names: two spellings of one vocabulary, drifting silently, with `enum_val`
holding ordinals for one of them.

`PARSE_LANES` is the five 05 section 3.1 admits at `GATE` or `DECODE`-select; the other six are
[06](06-structure-extraction.md)'s graph lanes. It is a subset of `LANES` by construction and a test
asserts that rather than a comment claiming it.

Core plus this package's own `Lane` import. No store, no clock, no IO.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md Part 3 (:824-880), 02-architecture.md section 2 row 35,
11-repo-layout.md:250 and 16-roadmap.md:606.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

from omniweave_core.model.enums import Lane

__all__ = [
    "LANES",
    "PARSE_LANES",
    "RUNG_BY_NAME",
    "TERMINAL_RUNGS",
    "Rung",
]


class Rung(IntEnum):
    """05:838-844's seven rows, in the plan's order, with the plan's ordinals.

    `IntEnum` and not `StrEnum`, which is the opposite of every vocabulary in
    `omniweave_core.model.enums`, and the reason is that this one is COMPARED. 05:1090's loop
    iterates `GATE, DECODE, REPAIR, PAGE, REGEN, DEGRADE, ENRICH` monotonically and never revisits;
    `escalate_to` must be *"strictly greater than `rung`"* (05:1939); and RT8's generated
    `BEFORE INSERT` trigger enforces `child.rung > parent.rung` in SQL. A string vocabulary would
    make all three a lookup, and the SQL one impossible without a join.

    The stored spelling is still the NAME -- 05:1216 fixes the policy grammar's literals as
    `SCREAMING_SNAKE`, *"`rung = "GATE"` and the other `Rung` literals"* -- so `Rung['DECODE']` and
    `member.name` are the round trip, not `str(member)`, which on an `IntEnum` is the integer.
    `RUNG_BY_NAME` is that lookup, so no caller writes `Rung[...]` and gets a bare `KeyError`.
    """

    GATE = 0
    DECODE = 1
    REPAIR = 2
    PAGE = 3
    REGEN = 4
    DEGRADE = 5
    ENRICH = 6


RUNG_BY_NAME: Final[dict[str, Rung]] = {member.name: member for member in Rung}
"""`'DECODE' -> Rung.DECODE`. The one spelling a policy file, a `signals.toml` and a stored row use.

A mapping and not a function, because every caller wants the membership test as much as the lookup:
`signals.toml`'s `requires` list and the policy grammar's `rung =` key both have to refuse an
unknown literal BY NAME, and `key in RUNG_BY_NAME` is that refusal's condition.
"""

TERMINAL_RUNGS: Final[frozenset[Rung]] = frozenset({Rung.DEGRADE, Rung.ENRICH})
"""The two rungs 05:838-844's `terminal?` column marks unconditionally `yes`.

`GATE` is terminal *on `refuse`/`skip`* and `DECODE` is terminal *for office and text* -- both
conditional, so neither is a member: a set that folded a conditional terminal into an unconditional
one would tell the rung loop to stop after a `GATE` rule that merely clamped `max_cost_class`.
`RouteDecision.terminal` is the per-decision answer (05:1942) and this set is the structural one.
"""

LANES: Final[frozenset[str]] = frozenset(member.value for member in Lane)
"""Eleven lane tokens, DERIVED from `omniweave_core.model.enums.Lane` and never written out here.

INV-21, in `Lane`'s own words: a second declaration would be two spellings of one vocabulary, and
`enum_val` stores `Lane`'s ORDINALS -- so a drift here would not be a rename, it would be two
installs disagreeing about what the integer in the column means.
"""

PARSE_LANES: Final[frozenset[str]] = frozenset(
    {Lane.TEXT.value, Lane.TABLE.value, Lane.MATH.value, Lane.FIELDS.value, Lane.CAPTION.value}
)
"""The five 05 section 3.1 admits during parse. `text` is mandatory; the other four are admitted.

05:873: *"`text` is mandatory and always admitted. `table`, `math`, `fields` and `caption` are
**admitted by a lane-admission modifier** at `GATE` or `DECODE`-select, and each admitted lane then
runs its own rung loop with its own first-match-wins rule list and its own `route_decision` rows."*
The remaining six members of `Lane` -- `anchor`, `xref`, `entity`, `claim`, `community`, `summary`
-- are [06](06-structure-extraction.md)'s graph lanes and never reach a parse rung.
"""
