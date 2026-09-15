"""`page_renders`, `service_attaches`, `signal_computations` -- INV-13 as three numbers.

01-principles.md:403 is the enforcement clause and it is one sentence long:

> `X` -- the `service_attaches`, `page_renders` and `signal_computations` counters are **exact**:
> plus or minus one fails.

05:1149 is what they are exact *about*: *"A clean born-digital page computes zero `LOCAL_COMPUTE`
signals (INV-13, RT4) ... the `service_attaches`, `page_renders` and `signal_computations` counters
are **exact** -- a deviation of one fails the gate."* And 08:1204 says why the number and not the
promise: the `service_attaches` counter is exact *"precisely so a refactor cannot quietly warm a VLM
for a corpus that never needed one."*

## Why a set and not a sum

Each of the three is the **cardinality of a set whose key the plan already fixes**, and that is what
makes plus-or-minus-one a usable gate rather than a flaky one:

- `signal_computations` -- the signals computed, keyed `(unit_part, signal_key)`: `route_signal`'s
  primary key less its version column (05:2345).
- `page_renders` -- the rasters produced, keyed `(unit_part, profile)`: one raster per profile per
  part, cached through *"`cache_index` layer `render`"* (05:2356).
- `service_attaches` -- the model servers started or joined, keyed by service id. 05:2474 puts the
  model load *"once per run, recorded on the run manifest, visible in the `service_attaches`
  counter. Charging it per decision double-counts it."*

A counter kept as a running sum has to be incremented at exactly one site, and every cache hit,
every retry and every second reader of a signal is a place to get it wrong by one. A counter kept as
a set cannot be wrong by one for any of those reasons: a repeat is a member already present. So
`Counters.computed()` returns whether the call was the **first**, and the acquirer can call it on
every read without thinking about it.

The three sets are also exactly the three cache keys, which is not a coincidence: a counter that
disagreed with its cache would be measuring something the system does not do.

## What this module does not do

It does not acquire anything, and it does not decide. `DemandPlan` decides which keys a rung may
compute; the acquisition loop in `omniweave.run` computes them and tells this module what it did.
The one derivation offered here is `predicted()`, and it is deliberately narrow: given a demand plan
and the groups that ran, `signal_computations` follows exactly, because a group is computed as a
whole (05:1110). `page_renders` and `service_attaches` do not follow, and D214 says why -- no
`SignalSpec` column says a key needs a raster, and no plan says whether the `glyph` raster a `PAGE`
driver receives is one of the renders this counter counts. So they are observed and never predicted.

## The tolerance is a constant and it is zero

`EXACT` is `0` and there is no other value in this module. 13-quality.md:307 allows a second class
-- *"Counters are `exact` by default (±1 fails) or `ratchet` with a tolerance"* -- and then closes
it at 13-quality.md:308: *"the temptation to add a `ratchet` counter for a number you have not
stabilised is how the class erodes."* All three of these are `exact` in the charter's own register,
so a tolerance parameter here would exist solely to be passed a wrong value.

Specified in 01-principles.md INV-13; 05-ingest-and-routing.md sections 4.3 and 6.3; RT4 at
05:3344; scheduled by 16-roadmap.md:606.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable

    from omniweave.route.demand import DemandPlan, Group

__all__ = [
    "COUNTERS",
    "EXACT",
    "RENDER_PROFILES",
    "Counters",
    "Mismatch",
    "Tally",
    "compare",
    "predicted",
]

COUNTERS: Final[tuple[str, str, str]] = (
    "page_renders",
    "service_attaches",
    "signal_computations",
)
"""The closed set, in the order `ow eval counters --check` names them (16-roadmap.md:635).

Three and never four. 13-quality.md:308 fixes the register -- *"The charter's sixteen rows stand
unchanged and this document adds none"* -- and two of these three are among those sixteen. The
order here is the CLI's rather than 01:403's prose order, because the CLI's is the one a reader
copies out of a terminal and pastes into an issue."""

_Member = TypeVar("_Member")
"""What `_first()` counts. A tuple for two of the three sets and a plain `str` for the third,
which is why it is a parameter: `set` is invariant, so a `set[object]` parameter would refuse
`set[str]`."""

EXACT: Final[int] = 0
"""The tolerance, for all three. `exact` in 13-quality.md section 2.8 means `±1 fails`, which is a
tolerance of zero -- the two spellings say the same thing and this is the arithmetic one."""

RENDER_PROFILES: Final[tuple[str, str]] = ("structure", "glyph")
"""05:907's two, cheapest first: `[render.structure]` at a 692 px floor, `[render.glyph]` at 1384.

The signal side renders at `structure` and only at `structure` -- 05:2290 names it for `ink.tiles`
and `ink.coverage` -- so a `glyph` raster in a run is always a driver's, which is the one fact that
lets a reader attribute a render without a stack trace."""


# --------------------------------------------------------------------------------------------
# 1. The reading.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tally:
    """Three integers and nothing else. What a run reports and what a baseline stores.

    Frozen, because it is a *reading*: a number that could be edited after the run that produced it
    is not evidence of anything. `Counters` is the mutable half and `Counters.tally()` is the only
    way across.
    """

    page_renders: int = 0
    service_attaches: int = 0
    signal_computations: int = 0

    def __sub__(self, other: Tally) -> Tally:
        """Component-wise, signed. The delta a gate prints; negative is as interesting as positive.

        A counter that went **down** after a refactor is the cache-miss defect read backwards --
        13:302 gives the case *"a silent re-render, a re-billed free operator and a 100% cache miss
        all leave a clock untouched"*, and the last of those shows up here as a signal count that
        rose while a render count fell. Clamping at zero would hide exactly that.
        """
        return Tally(
            page_renders=self.page_renders - other.page_renders,
            service_attaches=self.service_attaches - other.service_attaches,
            signal_computations=self.signal_computations - other.signal_computations,
        )

    def get(self, name: str) -> int:
        """By counter name, for the `--check <list>` form. Refuses a name outside `COUNTERS`."""
        if name not in COUNTERS:
            raise KeyError(f"{name!r} is not one of {', '.join(COUNTERS)}")
        return int(getattr(self, name))

    def render(self) -> str:
        """`'page_renders=0 service_attaches=0 signal_computations=5'`, in `COUNTERS` order."""
        return " ".join(f"{name}={self.get(name)}" for name in COUNTERS)


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One counter that moved. `expected` is the baseline, `observed` is this run.

    Carries both numbers and not only the delta, because the operator's next question after "it
    moved by 3" is always "from what" -- and a message that answers only the first sends them to
    `git log` for the second.
    """

    counter: str
    expected: int
    observed: int

    @property
    def delta(self) -> int:
        return self.observed - self.expected

    def render(self) -> str:
        return (
            f"{self.counter}: expected {self.expected}, observed {self.observed} "
            f"({self.delta:+d}); this counter is exact, so any delta fails"
        )


def compare(
    observed: Tally, expected: Tally, *, only: Iterable[str] = COUNTERS
) -> tuple[Mismatch, ...]:
    """Every counter that differs, in `COUNTERS` order. `()` is a pass.

    `only` is `ow eval counters --check page_renders,service_attaches,signal_computations`'s
    argument (16-roadmap.md:635) -- a subset, never a superset: a name outside `COUNTERS` raises
    from `Tally.get()` rather than being silently ignored, because a typo in a `--check` list that
    quietly checked nothing is a green gate that tested nothing.

    Returns findings rather than raising on the first, for `lint.py`'s reason: a run that moved two
    counters should say so once, and a gate that stopped at the first would take two CI rounds to
    show the same information.
    """
    wanted = frozenset(only)
    return tuple(
        Mismatch(counter=name, expected=expected.get(name), observed=observed.get(name))
        for name in COUNTERS
        if name in wanted and observed.get(name) - expected.get(name) != EXACT
    )


# --------------------------------------------------------------------------------------------
# 2. The instrument.
# --------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Counters:
    """The mutable half: three sets, filled by the acquisition loop as it goes.

    **Mutable and not frozen**, for `Evidence`'s reason (05:1858): it is a handle over something
    being filled, and freezing it would say something false about what it holds. The frozen thing is
    `tally()`'s result.

    Every method returns whether the call was the **first** for that key, so an acquirer can
    call it unconditionally -- on a cache hit as well as a miss -- and still get an exact count.
    That is the difference between this and a counter a caller has to remember to guard: the guard
    is here, once, and it is the set membership the cache is keyed on anyway.
    """

    signals: set[tuple[str, str]] = field(default_factory=set)
    """`(unit_part, signal_key)`. `route_signal`'s primary key less `signal_version` (05:2345).

    Less the version deliberately: a version bump invalidates the cached row and the signal is
    recomputed, which is a real computation and must count. Including the version would count it
    twice for the same part in a run that saw both -- which cannot happen, since a run resolves one
    provider version per key, but a counter whose key admits the impossible is one nobody can reason
    about."""

    renders: set[tuple[str, str]] = field(default_factory=set)
    """`(unit_part, profile)`. One raster per profile per part, which is what the `render` layer of
    `cache_index` is keyed on (05:2356). A part that is rasterised at `structure` for `ink.tiles`
    and again at `glyph` for a `PAGE` driver is two renders, because they are two images."""

    services: set[str] = field(default_factory=set)
    """Service ids, per RUN. 05:2474: the model load is *"paid once per run, recorded on the run
    manifest, visible in the `service_attaches` counter. Charging it per decision double-counts it;
    charging it per sequence under-counts the unsequenced case."* So the set has no part in its key
    and a `Counters` instance is per run."""

    def computed(self, key: str, *, unit_part: str = "") -> bool:
        """Record one signal computation. `True` if this is the first for `(unit_part, key)`.

        `unit_part` defaults to `''`, which is the unit grain -- the same convention `Evidence`'s
        scope and `route_signal`'s column use. 05:2659 spells the column and its reason in one
        comment: *"'' folds NULL (NULLs are distinct in a UNIQUE)"*. So `unit.format`, computed
        once for the whole unit, is one computation and not
        one per part, and a 188-page document does not report 188 of them.
        """
        return _first(self.signals, (unit_part, key))

    def computed_all(self, keys: Iterable[str], *, unit_part: str = "") -> int:
        """A whole group at once. Returns how many were new -- 05:1110's unit of acquisition.

        The caller passes the keys it actually computed, which on a given format is the group less
        the keys `resolve(key, format)` finds no provider for. This module does not do that
        filtering, because it needs the format and the registry and would then be deciding rather
        than counting.
        """
        return sum(self.computed(key, unit_part=unit_part) for key in keys)

    def rendered(self, profile: str, *, unit_part: str = "") -> bool:
        """Record one raster. `True` if this is the first at `(unit_part, profile)`.

        Refuses a profile outside `RENDER_PROFILES`: the two are `[render.structure]` and
        `[render.glyph]` (05:907) and `Modifiers.render` is typed to exactly those, so a third
        spelling here is a typo that would silently make the count one too high.
        """
        if profile not in RENDER_PROFILES:
            raise ValueError(
                f"{profile!r} is not a render profile; 05:907 declares "
                f"{' and '.join(RENDER_PROFILES)} and nothing else"
            )
        return _first(self.renders, (unit_part, profile))

    def attached(self, service: str) -> bool:
        """Record one attach-or-spawn. `True` if this run had not touched the service before.

        Attach and spawn are one event, because R-O3's mitigation column (17-risks.md:252) makes
        them one seam: *"S3 is
        attach-or-spawn with model-id verification on attach and lazy spawn -- nothing resident is
        started for a clean page (INV-13), and `service_attaches` is an **exact** counter."* A
        server that runs for a corpus that needed none is the same failure whether this process
        created it or joined it.
        """
        if not service:
            raise ValueError("a service attach with no service id cannot be counted")
        return _first(self.services, service)

    def tally(self) -> Tally:
        """The frozen reading. Three cardinalities, no arithmetic."""
        return Tally(
            page_renders=len(self.renders),
            service_attaches=len(self.services),
            signal_computations=len(self.signals),
        )


def _first(into: set[_Member], member: _Member) -> bool:
    """`set.add` with the first-time answer `set.add` does not return.

    A module function rather than a method because `set` is invariant: a `set[object]` parameter
    would refuse `set[str]`, and the three sets have two different member types.
    """
    if member in into:
        return False
    into.add(member)
    return True


# --------------------------------------------------------------------------------------------
# 3. The one derivation, and its boundary.
# --------------------------------------------------------------------------------------------


def predicted(plan: DemandPlan, groups: Iterable[Group]) -> int:
    """How many signals a plan computes if exactly `groups` run. `signal_computations`, derived.

    Exact, and the reason is 05:1110: *"Groups are computed in order and the rules re-evaluated
    after each"* -- a group is the unit, so the count is the sum of the group sizes and not a
    function of which rule matched. That is what makes the clean-page assertion checkable without a
    driver: run section 4.3's loop over a clean `Evidence`, collect the groups that ran, and the
    number is fixed before any provider is called.

    **Only this one is derived.** `page_renders` needs to know that computing `ink.tiles` rasterises
    the part, and `SignalSpec`'s twelve columns do not carry it; `service_attaches` needs the
    driver's card, which is not in a demand plan at all. Both are observed through `Counters`, and
    D214 files the gap.

    Deduplicated against the plan's own keys, so a caller that passes the same group twice gets the
    same answer -- the loop cannot compute a group twice (05:1131), and a helper that disagreed with
    that would be the wrong tool for checking it.
    """
    known = frozenset(plan.keys)
    return len({key for group in groups for key in group.keys if key in known})
