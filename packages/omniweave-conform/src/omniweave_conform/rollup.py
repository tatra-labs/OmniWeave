"""Verdicts to metrics: the rate rollup 13-quality.md section 8.3's direct rows name. **D816.**

Section 8.3: *"A floor with no definition is not a gate, so every metric names the `eval_verdict`
rollup that computes it. All are macro-averaged over slices with `min_slice_n = 30` unless the row
says otherwise."* Three of its rows are a pass rate over assertion types and nothing more:
`table_rel_acc` (*"the fraction of `table` and `cell_rel` assertions that pass. A direct verdict
rollup"*), `order_acc` (*"the fraction of `order` assertions that pass"*) and the ungated
`field_acc` (*"the fraction of `field` + `absent_field` + `null_kept` assertions that pass"*).
`RATES` holds the three, and `rollup()` turns one run's verdicts into its `eval_metric` rows, with
`omniweave_conform.stats` (D813) for every interval.

## Rulings

1. **A rate's population is its types' verdicts on assertions that score**, each type judged by
   ITS evaluator -- the caller's by default, and `Rate.evaluators`' where a type names one
   (D1024, a user ruling of 2026-10-30). It read *"one evaluator's verdicts"* until then, which
   `table_rel_acc` could not satisfy: see `Rate.evaluators`. An assertion
   scores when `checked = 'verified'`. `checked IS NULL` *"runs and never scores"* (13:1022), and
   its verdicts are counted in `Rollup.unscored`, because *"the excluded count is printed on every
   report"*. A `rejected` assertion does not run (D815). `eval_metric` has no evaluator column, so
   a metric row is one evaluator's, named by the caller.
2. **A verdict's slice is its `slice_key`**, the corpus vocabulary 13:1150 gives
   `eval_metric.slice_key`, never the router's Slice.
3. **Each slice gets a row**: a Wilson rate at `n >= min_slice_n`, and below it `method = none`,
   `state = unknown` and no value (13:406). The `__macro__` row is `stats.macro()` over each slice's
   0/1 scores, so its value is the mean of the slice rates; with no slice admitted it is `unknown`.
4. **Section 8.7's rule 3 is applied per metric.** A metric's expected population is every
   verified assertion of its types in the run's corpus, and an assertion is missing when it has no
   verdict from the evaluator. Above `MAX_PARTIAL_FRAC` missing, or with a slice whose every
   expected assertion is missing, every row of the metric is `unknown`. Below, the rows stand and
   `n` is what ran (rule 1 of 8.7). An expected assertion's slices are its `slices`, because a
   missing one has no verdict to read a slice from; an unsliced one is `*`.
5. **An `unknown` run yields `unknown` rows.** Its numbers measured nothing anyone may read, and
   the view leaves the run out besides.
6. **Every rate here is an accuracy column**, so its `TruthKind` passes
   `quality.check_accuracy_column()` when the rollup is defined: `agreement` and `self` may never
   anchor one (Q-G9), and `native_run` anchors fidelity only.

Specified in 13-quality.md sections 3, 8.1, 8.3 and 8.7.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import MIN_SLICE_N
from omniweave_core.limits import MAX_PARTIAL_FRAC
from omniweave_core.quality import check_accuracy_column
from omniweave_core.store.oweval import Assertion, Metric, Run, Verdict

from omniweave_conform.stats import Slice, macro, rate

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["MACRO", "NO_OVERRIDE", "RATES", "VERIFIED", "Rate", "Rollup", "rollup"]

MACRO: Final = "__macro__"
"""`eval_metric.slice_key`'s default: the headline row."""

VERIFIED: Final = "verified"
UNSLICED: Final = "*"


NO_OVERRIDE: Final[Mapping[str, str]] = MappingProxyType({})
"""A rate whose every type is judged by the caller's evaluator."""


@dataclass(frozen=True, slots=True)
class Rate:
    """One direct verdict rollup: a metric, the assertion types it counts, and its `TruthKind`."""

    metric: str
    types: frozenset[str]
    truth_kind: str
    evaluators: Mapping[str, str] = NO_OVERRIDE
    """D1024: the evaluator that judges a TYPE, where it is not the caller's default.

    Ruling 1 says a rate's population is "one evaluator's verdicts", and for two of the three
    rates it still is. `table_rel_acc` cannot be: 13:1100 defines it over `table` AND `cell_rel`
    assertions, and a `cell_rel` is a claim about the parsed `Grid`'s spans and header chains,
    which the text evaluator structurally cannot see -- `judge()` sends it to `owdoc`. With one
    evaluator for the metric, every `cell_rel` counted as EXPECTED and arrived MISSING, and 18 of
    58 is 31% against `MAX_PARTIAL_FRAC = 0.02`, so ruling 4 turned every row of the metric
    `unknown` the moment a reviewer verified one. The metric could never compute, which is not
    what either clause intended.
    """

    def __post_init__(self) -> None:
        """Ruling 6, and ruling 1's amendment: an override names a type this rate counts."""
        check_accuracy_column(self.metric, self.truth_kind)
        stray = sorted(set(self.evaluators) - self.types)
        if stray:
            message = f"{self.metric}: evaluators names {stray}, which it does not count"
            raise ValueError(message)

    def judge_of(self, assertion_type: str, default: str) -> str:
        """Which evaluator's verdict scores this type (D1024)."""
        return self.evaluators.get(assertion_type, default)


RATES: Final[Mapping[str, Rate]] = {
    one.metric: one
    for one in (
        Rate(
            "table_rel_acc",
            frozenset({"table", "cell_rel"}),
            "human",
            MappingProxyType({"cell_rel": "owdoc"}),
        ),
        Rate("order_acc", frozenset({"order"}), "rendered"),
        Rate("field_acc", frozenset({"field", "absent_field", "null_kept"}), "human"),
    )
}
"""Section 8.3's three direct rollups, each with the `TruthKind` its row prints. `field_acc` is
ungated and its row prints none; `human` is what `doc_acc` and `hallucination_rate` print over the
same `field` assertions."""


@dataclass(frozen=True, slots=True)
class Rollup:
    """One metric's rows for one run, and what the rows do not count."""

    metrics: tuple[Metric, ...]
    unscored: int
    """Verdicts on `checked IS NULL` assertions: run, never scored, and printed (ruling 1)."""
    missing: int
    expected: int


def rollup(
    run: Run,
    spec: Rate,
    verdicts: Iterable[Verdict],
    assertions: Iterable[Assertion],
    *,
    evaluator: str,
    min_n: int = MIN_SLICE_N,
) -> Rollup:
    """`spec`'s rows for `run`: one per slice, then `__macro__` (rulings 1-5)."""
    by_id = {a.assertion_id: a for a in assertions if _ours(a, run, spec)}
    scores: dict[str, list[float]] = defaultdict(list)
    answered: set[str] = set()
    unscored = 0
    for verdict in verdicts:
        assertion = by_id.get(verdict.assertion_id)
        if assertion is None or verdict.run_id != run.run_id:
            continue
        #  D1024: the evaluator is the TYPE's, falling back to the caller's.
        if verdict.evaluator != spec.judge_of(assertion.type, evaluator):
            continue
        answered.add(assertion.assertion_id)
        if assertion.checked == VERIFIED:
            scores[verdict.slice_key].append(1.0 if verdict.passed else 0.0)
        elif assertion.checked is None:
            unscored += 1
    expected = [a for a in by_id.values() if a.checked == VERIFIED]
    missing = [a for a in expected if a.assertion_id not in answered]
    if run.status == "unknown" or _too_partial(expected, missing):
        keys = [*sorted(scores), MACRO]
        counts = {key: len(values) for key, values in scores.items()}
        counts[MACRO] = sum(counts.values())
        rows = [_unknown(run, spec, key, counts[key]) for key in keys]
    else:
        rows = [_slice_row(run, spec, key, scores[key], min_n) for key in sorted(scores)]
        rows.append(_macro_row(run, spec, scores, min_n))
    return Rollup(
        metrics=tuple(rows), unscored=unscored, missing=len(missing), expected=len(expected)
    )


def _ours(assertion: Assertion, run: Run, spec: Rate) -> bool:
    """The assertions `spec` counts for `run`. A `rejected` one never scores and is never
    expected, because only `verified` scores and only `NULL` is counted unscored."""
    return assertion.type in spec.types and (assertion.corpus_id, assertion.corpus_version) == (
        run.corpus_id,
        run.corpus_version,
    )


def _too_partial(expected: list[Assertion], missing: list[Assertion]) -> bool:
    """Ruling 4: above `MAX_PARTIAL_FRAC` missing, or a slice with nothing that ran."""
    if not expected or not missing:
        return False
    if len(missing) / len(expected) > MAX_PARTIAL_FRAC:
        return True
    total: dict[str, int] = defaultdict(int)
    lost: dict[str, int] = defaultdict(int)
    gone = {a.assertion_id for a in missing}
    for assertion in expected:
        for key in assertion.slices or (UNSLICED,):
            total[key] += 1
            lost[key] += assertion.assertion_id in gone
    return any(lost[key] == total[key] for key in total)


def _slice_row(run: Run, spec: Rate, key: str, values: list[float], min_n: int) -> Metric:
    n = len(values)
    if n < min_n:
        return _unknown(run, spec, key, n)
    estimate = rate(int(sum(values)), n)
    return Metric(
        run_id=run.run_id,
        metric=spec.metric,
        slice_key=key,
        value=estimate.value,
        n=n,
        ci_lo=estimate.ci_lo,
        ci_hi=estimate.ci_hi,
        method=estimate.method,
        truth_kind=spec.truth_kind,
        state="ok",
    )


def _macro_row(run: Run, spec: Rate, scores: Mapping[str, list[float]], min_n: int) -> Metric:
    headline = macro((Slice.of(key, values) for key, values in sorted(scores.items())), min_n=min_n)
    estimate = headline.estimate
    if estimate.value is None:
        return _unknown(run, spec, MACRO, sum(len(values) for values in scores.values()))
    return Metric(
        run_id=run.run_id,
        metric=spec.metric,
        slice_key=MACRO,
        value=estimate.value,
        n=estimate.n,
        ci_lo=estimate.ci_lo,
        ci_hi=estimate.ci_hi,
        method=estimate.method,
        truth_kind=spec.truth_kind,
        state="ok",
    )


def _unknown(run: Run, spec: Rate, key: str, n: int) -> Metric:
    return Metric(
        run_id=run.run_id,
        metric=spec.metric,
        slice_key=key,
        value=None,
        n=n,
        ci_lo=None,
        ci_hi=None,
        method="none",
        truth_kind=spec.truth_kind,
        state="unknown",
    )
