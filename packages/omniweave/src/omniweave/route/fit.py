"""The isotonic threshold fitter behind `ow route propose`. W5.2's other half, with the linter.

05-ingest-and-routing.md section 8.3 (:2986-2996) is the whole specification and it is three
sentences, each of which decides something:

> `ow route propose` fits one `[thresholds]` entry per slice by **one-dimensional isotonic
> regression** over the decision log -- possible only because `@thresholds.<name>` is a
> compile-time substitution rather than an expression -- and emits a **TOML diff a human
> commits**. The objective, stated so it can be checked: for threshold `t` on signal `s` within
> one slice, the label is `1 - agree.decode_vs_page` on the decisions that escalated (plus `audit`
> divergence where present), and the fit maximises `Σ divergence_avoided(t) - Σ micros(t)` -- both
> terms already in the same unit, because the `PriceBook` converted one of them -- with
> monotonicity in `t` making the fit isotonic rather than a grid search. The report prints `(n,
> ci95, method, slice_key, corpus_digest, MeasuredOn, witness)` for every number, per INV-19; a
> slice at `UNKNOWN` yields **no proposal at all** rather than a proposal with no evidence.

## Why isotonic, and what "rather than a grid search" is contrasted with

The estimator is monotone regression on the LABEL, not a sweep over hyperparameters. `divergence`
against `s` is noisy per decision and monotone in expectation -- a higher `garble.score` means the
cheap read was more likely wrong -- so pooling adjacent violators (`isotonic()`) is the exact
least-squares fit under that single assumption and needs no bandwidth, no bin count and no seed.
That is what makes it reproducible: INV-19 requires an RNG-free harness, and PAVA has nothing to
seed.

The threshold search itself is then a single right-to-left sweep over the distinct observed values,
which is exact. It is written that way rather than assuming the objective is unimodal: the label is
monotone after the fit, but `micros` is a measured cost that need not be, and an argmax found by
walking downhill from the crossing point would be wrong on a corpus where the expensive rung is
cheaper on exactly the documents that need it.

## The unit conversion is a parameter, because no `PriceBook` row prices a divergence point

*"Both terms already in the same unit, because the `PriceBook` converted one of them."* Section
6.2's `PriceBook` prices seven physical units -- CPU ms, GPU ms, tokens, calls, bytes -- and none
of them is a unit of divergence. The conversion the sentence assumes exists has no row, so
`divergence_micros` is an explicit argument named for what it means: **what one whole unit of
avoided divergence is worth in micros.** Inventing a default here would put a number nobody chose
inside every proposal the framework ever emits. D209.

## A slice at UNKNOWN yields nothing, and so does a slice under `min_n`

Both refusals are the same refusal at two grains. `fit()` returns `None` rather than a `Proposal`
with a wide interval, because section 8.2's scoreboard already says what `UNKNOWN` means -- *"On day
one an operator sees a wall of `UNKNOWN` across every slice, which is the truth"* -- and a fitter
that proposed anyway would be the first thing in the loop to overrule it. `min_n` defaults to
`MIN_SLICE_N`, which is `min_audit_n`'s thirty, reused rather than reinvented.

## What this module does not do

It does not write. *"`ow route promote` applies a reviewed diff. Neither writes without a commit."*
`render_diff()` returns lines; the file write, the dirty-tree refusal and the `atomic_write` are
section 8.3's `auto_demote` writer and W5.5's command, not a fitter's business.

It does not fit two thresholds together. *"**v2, explicitly.** Multi-dimensional threshold
fitting -- two thresholds moving together -- and per-slice rule ordering proposals. Both need the
joint distribution that one-dimensional isotonic regression avoids needing."*

Specified in 05-ingest-and-routing.md section 8.3; INV-19 in 13-quality.md:5; scheduled by
16-roadmap.md:604.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.drivers.card import MIN_SLICE_N, WITNESSES

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.drivers.card import MeasuredOn

__all__ = [
    "DIRECTIONS",
    "METHOD",
    "SCOREBOARD_UNKNOWN",
    "Z95",
    "Observation",
    "Proposal",
    "ci95",
    "fit",
    "isotonic",
    "render_diff",
]

METHOD: Final[str] = "isotonic_pava_1d"
"""INV-19's `method` column for every number this module produces. One value, because there is one
estimator: 05:2999 puts the multi-dimensional fit in v2 explicitly."""

DIRECTIONS: Final[tuple[str, ...]] = ("above", "below")
"""Which side of `t` escalates. `garble.score >= @thresholds.garble_escalate` is `"above"`;
`ink.coverage < @thresholds.ink_coverage_min` is `"below"`. It is a parameter and not a derivation,
because the rule that reads a threshold is where the comparison lives and a threshold is named in
`[thresholds]` without one -- the same flatness D204 files from the other side."""

SCOREBOARD_UNKNOWN: Final[str] = "UNKNOWN"
"""05:2878's zero value. A slice at it yields no proposal at all."""

Z95: Final[float] = 1.959964
"""The two-sided 95% normal quantile. A normal quantile and not a `t`, because `min_n` is thirty --
`MIN_SLICE_N`, which 04 section 2.6 takes from `min_audit_n` -- and below thirty this module returns
no proposal rather than a wider interval. Carrying a `t` table to widen an interval nobody is
allowed to publish would be arithmetic in service of a refused case."""

_EPSILON: Final[float] = 1e-12


# --------------------------------------------------------------------------------------------
# 1. Pool Adjacent Violators. The estimator, and the only thing here with a literature.
# --------------------------------------------------------------------------------------------


def isotonic(values: Sequence[float], weights: Sequence[float] | None = None) -> tuple[float, ...]:
    """The exact weighted least-squares NON-DECREASING fit to `values`, in O(n). PAVA.

    One pass with a stack of pooled blocks: push each point as its own block, and while the block
    below has a greater mean, pool the two. The stack is non-decreasing by construction when the
    loop ends, and the pooled mean is the least-squares answer for every point in a block -- which
    is why the result has runs of equal values rather than a curve, and why a fitted threshold
    always lands on a boundary between two runs.

    Exact, deterministic and seedless. INV-19 requires an RNG-free harness for any published number
    (13-quality.md:5) and this is what makes the requirement free rather than a discipline: there is
    nothing in PAVA to seed, no bandwidth to pick and no bin count to argue about.

    `weights` default to one each. A zero or negative weight is refused rather than skipped: it is
    almost always a caller dividing by a count that was zero, and pooling it silently would move the
    fit by an amount nothing in the report would explain.
    """
    points = list(values)
    if not points:
        return ()
    scale = [1.0] * len(points) if weights is None else [float(one) for one in weights]
    if len(scale) != len(points):
        raise ValueError(f"isotonic() got {len(points)} values and {len(scale)} weights")
    if any(one <= 0.0 for one in scale):
        raise ValueError("isotonic() weights must be positive; a zero weight is a caller's bug")
    stack: list[tuple[float, float, int]] = []  # (weighted sum, weight, how many points pooled)
    for value, weight in zip(points, scale, strict=True):
        block = (value * weight, weight, 1)
        while stack and stack[-1][0] / stack[-1][1] > block[0] / block[1] + _EPSILON:
            below = stack.pop()
            block = (below[0] + block[0], below[1] + block[1], below[2] + block[2])
        stack.append(block)
    fitted: list[float] = []
    for total, weight, count in stack:
        fitted.extend([total / weight] * count)
    return tuple(fitted)


def ci95(samples: Sequence[float]) -> tuple[float, float]:
    """The 95% interval on the MEAN of `samples`, normal, from the sample standard deviation.

    A normal interval on a mean and **not a Wilson interval on a proportion**, and the difference is
    not pedantry: `1 - agree.decode_vs_page` is a normalised edit distance in `[0, 1]`, continuous,
    and Wilson models a count of successes out of `n` trials. Applying it here would report an
    interval for an experiment nobody ran. A single sample has no interval and returns its own value
    twice, which is honest and is also below `min_n` and therefore never published.
    """
    n = len(samples)
    if n == 0:
        return (math.nan, math.nan)
    mean = math.fsum(samples) / n
    if n == 1:
        return (mean, mean)
    variance = math.fsum((one - mean) ** 2 for one in samples) / (n - 1)
    half = Z95 * math.sqrt(variance / n)
    return (mean - half, mean + half)


# --------------------------------------------------------------------------------------------
# 2. What the fitter reads and what it returns.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One decision from the log, reduced to the four numbers the fit reads.

    `divergence` is 05:2990's label: *"`1 - agree.decode_vs_page` on the decisions that escalated
    (plus `audit` divergence where present)"*. It is what the cheap path got wrong, so escalating
    AVOIDS it -- which is why the objective adds it on the escalating side rather than subtracting
    it.

    `micros` is what the escalation cost, from `route_spend` (05:2553, *"the authority on what was
    actually paid"*) and not from an estimate. `decision_id` is carried so the boundary decision can
    be named in the proposal: a threshold move that nobody can point at one row for is a number
    without a witness.
    """

    signal: float
    divergence: float
    micros: int
    decision_id: str = ""


@dataclass(frozen=True, slots=True)
class Proposal:
    """One fitted `[thresholds]` entry, with INV-19's seven fields and nothing optional.

    **`corpus_digest` is not a field here.** `MeasuredOn` carries it and 04 section 2.6 is explicit
    that it *"has no row-level twin: two fields that must agree are one field plus a bug"*, so this
    record reads it through a property.

    `witness` is `"self"` and the constructor refuses anything else a caller has not justified:
    13-quality.md:1785 is *"`witness = "self"`, always, for a locally produced row. There is no flag
    that sets `ci`."* A fit over an operator's own decision log is as local as a row gets.
    """

    name: str
    slice_key: str
    current: float
    proposed: float
    direction: Literal["above", "below"]
    n: int
    ci95: tuple[float, float]
    measured_on: MeasuredOn
    objective: float
    objective_now: float
    boundary_decision_id: str = ""
    method: str = METHOD
    witness: str = "self"

    def __post_init__(self) -> None:
        if self.witness not in WITNESSES:
            raise ValueError(f"witness is one of {WITNESSES}; got {self.witness!r}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction is one of {DIRECTIONS}; got {self.direction!r}")
        if self.n < MIN_SLICE_N:
            raise ValueError(
                f"a proposal over n={self.n} is below MIN_SLICE_N={MIN_SLICE_N}; "
                "fit() returns None rather than publishing one"
            )

    @property
    def corpus_digest(self) -> str:
        """`MeasuredOn`'s, never a second copy. 04 section 2.6."""
        return self.measured_on.corpus_digest

    @property
    def gain(self) -> float:
        """Micros the move is worth, per the fit. Zero means the current value IS the fit."""
        return self.objective - self.objective_now

    def render(self) -> str:
        """The one line the report prints, with every INV-19 field on it."""
        low, high = self.ci95
        return (
            f"{self.name} = {self.proposed:g}  (was {self.current:g}, slice {self.slice_key}, "
            f"n={self.n}, ci95 {low:.4f}-{high:.4f}, {self.method}, "
            f"corpus {self.corpus_digest}, witness={self.witness}, "
            f"gain {self.gain:+.0f} micros, boundary {self.boundary_decision_id or 'n/a'})"
        )


# --------------------------------------------------------------------------------------------
# 3. The fit.
# --------------------------------------------------------------------------------------------


def fit(
    observations: Iterable[Observation],
    *,
    name: str,
    current: float,
    slice_key: str,
    measured_on: MeasuredOn,
    divergence_micros: float,
    direction: Literal["above", "below"] = "above",
    state: str = "OK",
    min_n: int = MIN_SLICE_N,
) -> Proposal | None:
    """One threshold, one slice. `None` when there is no evidence or nothing to propose.

    Four refusals, and each returns `None` rather than a `Proposal` a reader would have to discount:

    1. **`state == "UNKNOWN"`.** 05:2995, in the plan's own italics: a slice at `UNKNOWN` yields
       *"no proposal at all rather than a proposal with no evidence"*. The scoreboard has already
       decided this slice has too few audits to speak, and a fitter that spoke anyway would make
       the three-valued state cosmetic.
    2. **`n < min_n`.** The same refusal at the fit's own grain.
    3. **one distinct signal value.** A threshold separates; a column that never varies has no
       separation to find, and every candidate is the same candidate.
    4. **the argmax IS the current value.** There is no diff to emit, which is the point of a
       command whose output a human commits.

    `divergence_micros` converts the label into the cost unit. See the module docstring: no
    `PriceBook` row does it, so the caller supplies the exchange rate and the number it produces is
    traceable to a decision somebody made rather than to a default nobody chose.
    """
    rows = _ordered(observations, direction)
    if state == SCOREBOARD_UNKNOWN or len(rows) < min_n:
        return None
    distinct = {row.signal for row in rows}
    if len(distinct) < 2:  # noqa: PLR2004 -- two is "varies at all", not a magic number
        return None
    fitted = isotonic([row.divergence for row in rows])
    best, boundary, objective = _argmax(rows, fitted, divergence_micros)
    if abs(best - current) < _EPSILON:
        return None
    return Proposal(
        name=name,
        slice_key=slice_key,
        current=current,
        proposed=best,
        direction=direction,
        n=len(rows),
        ci95=ci95([row.divergence for row in rows if _escalates(row.signal, best, direction)]),
        measured_on=measured_on,
        objective=objective,
        objective_now=_objective_at(rows, fitted, divergence_micros, current, direction),
        boundary_decision_id=boundary,
    )


def _ordered(observations: Iterable[Observation], direction: str) -> tuple[Observation, ...]:
    """Sorted so that the escalating set is always a SUFFIX, whichever way the rule compares.

    `"above"` escalates the high end, so ascending; `"below"` escalates the low end, so descending.
    Collapsing the two directions into one orientation here is what lets the sweep, the isotonic fit
    and the argmax each be written once -- and the fit's monotonicity assumption is then always the
    same assumption: divergence rises towards the escalating end.

    The tie-break is `decision_id` and not the input order, because two runs of `ow route propose`
    over one log must produce one diff, and a `GROUP BY` does not promise an order.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"direction is one of {DIRECTIONS}; got {direction!r}")
    rows = list(observations)
    rows.sort(key=lambda row: (row.signal, row.decision_id), reverse=direction == "below")
    return tuple(rows)


def _escalates(signal: float, threshold: float, direction: str) -> bool:
    """The rule's own comparison, as the fitter models it: `s >= t` above, `s <= t` below."""
    return signal >= threshold if direction == "above" else signal <= threshold


def _argmax(
    rows: Sequence[Observation], fitted: Sequence[float], divergence_micros: float
) -> tuple[float, str, float]:
    """The best threshold, the decision at the boundary, and the objective there.

    Candidates are the **distinct** signal values, taken at the first row of each run, because the
    escalating set of a threshold is `{s >= t}` and a candidate inside a run of equal values would
    name a set the comparison cannot produce. The sweep runs right to left accumulating
    `divergence_micros * fitted - micros`, so every candidate's objective is one addition.
    """
    running = 0.0
    best_value, best_id, best_objective = rows[-1].signal, rows[-1].decision_id, -math.inf
    for index in range(len(rows) - 1, -1, -1):
        running += divergence_micros * fitted[index] - rows[index].micros
        starts_a_run = index == 0 or rows[index - 1].signal != rows[index].signal
        if starts_a_run and running > best_objective:
            best_value, best_id, best_objective = (
                rows[index].signal,
                rows[index].decision_id,
                running,
            )
    return best_value, best_id, best_objective


def _objective_at(
    rows: Sequence[Observation],
    fitted: Sequence[float],
    divergence_micros: float,
    threshold: float,
    direction: str,
) -> float:
    """The same objective at the threshold the policy ships, so `Proposal.gain` is a real delta."""
    return math.fsum(
        divergence_micros * fitted[index] - row.micros
        for index, row in enumerate(rows)
        if _escalates(row.signal, threshold, direction)
    )


# --------------------------------------------------------------------------------------------
# 4. The diff a human commits.
# --------------------------------------------------------------------------------------------


def render_diff(
    proposals: Iterable[Proposal], *, path: str, current: Mapping[str, float]
) -> tuple[str, ...]:
    """A unified diff over one policy file's `[thresholds]` block. Lines, not a write.

    **Two proposals for one threshold name are not merged, and that is D208 made visible.** 05:2986
    fits *"one `[thresholds]` entry per slice"* and the grammar has exactly one flat `[thresholds]`
    table with no slice dimension: `@thresholds.<name>` is *"a compile-time substitution"* (05:977)
    and compile time is before any unit's slice is known, so there is nowhere for a per-slice number
    to land. When the slices agree this function emits the change; when they disagree it emits the
    fitted numbers as comments and **no `+` line**, so the operator reads the disagreement in the
    diff instead of committing whichever slice happened to sort first.

    `current` is the file's `[thresholds]` table, passed in rather than read off a `RoutePolicy`,
    because the diff is against the FILE and a compiled policy is six files merged.
    """
    by_name: dict[str, list[Proposal]] = {}
    for proposal in proposals:
        by_name.setdefault(proposal.name, []).append(proposal)
    if not by_name:
        return ()
    lines = [f"--- a/{path}", f"+++ b/{path}", " [thresholds]"]
    for target in sorted(by_name):
        lines.extend(_hunk(target, by_name[target], current.get(target)))
    return tuple(lines)


def _hunk(name: str, proposals: Sequence[Proposal], current: float | None) -> list[str]:
    values = {proposal.proposed for proposal in proposals}
    lines = [f"#  {proposal.render()}" for proposal in proposals]
    if current is None:
        lines.append(
            f"#  {name} is not declared in [thresholds]; a fit has nothing to replace. "
            "`ow route propose` proposes, it does not introduce"
        )
        return lines
    if len(values) > 1:
        lines.append(
            f"#  {len(values)} slices fitted {name} to {len(values)} different values and "
            "[thresholds] is one flat table with no slice dimension (D208), so this hunk "
            "proposes nothing. Pick one, or split the rule by slice and carry the number inline"
        )
        return lines
    lines.append(f"-{name} = {current:g}")
    lines.append(f"+{name} = {next(iter(values)):g}")
    return lines
