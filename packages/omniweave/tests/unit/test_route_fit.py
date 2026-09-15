"""`omniweave.route.fit` against 05-ingest-and-routing.md section 8.3 and INV-19.

Three groups, and they are three different kinds of claim. `isotonic()` is an estimator with a
literature, so its tests are the ones any PAVA implementation must pass -- including the weighted
case, which is where a hand-rolled one goes wrong. `fit()` is a search whose answer must be the
breakpoint a synthetic corpus was built around, so its tests construct the answer and then look for
it. `Proposal` and `render_diff()` are about what the framework is allowed to SAY, so their tests
are mostly refusals: no proposal at `UNKNOWN`, no proposal under `MIN_SLICE_N`, no `witness` but
`"self"`, and no `+` line when two slices disagree.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest
from omniweave.route import fit as rf
from omniweave_core.drivers.card import MIN_SLICE_N, MeasuredOn

MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="cpython",
    runtime_version="3.12",
    sampling="n/a",
    prompt_version="n/a",
    hardware="ci",
    corpus="fixtures/route/mixed-40",
    corpus_digest="sha256:" + "0" * 64,
    harness_version="0.1.0",
)
"""A pure-code path writes the literal `"n/a"` where a field does not apply (04 section 2.6), which
is what a threshold fit does with `weights` and `prompt_version`: there is no model in it."""


def _corpus(
    breakpoint_at: float = 0.55, *, n: int = 120, micros: int = 200, low: float = 0.02
) -> list[rf.Observation]:
    """A step: divergence is `low` below the breakpoint and 0.65 above it. The answer, planted."""
    return [
        rf.Observation(
            signal=round(i / (n - 1), 4),
            divergence=low if i / (n - 1) < breakpoint_at else 0.65,
            micros=micros,
            decision_id=f"dec_{i:03d}",
        )
        for i in range(n)
    ]


# --------------------------------------------------------------------------------------------
# 1. PAVA.
# --------------------------------------------------------------------------------------------


def test_an_already_monotone_sequence_is_returned_unchanged() -> None:
    """The fit is a projection: a point already in the cone is its own image."""
    assert rf.isotonic([1.0, 2.0, 3.0]) == (1.0, 2.0, 3.0)
    assert rf.isotonic([]) == ()
    assert rf.isotonic([7.0]) == (7.0,)


def test_adjacent_violators_are_pooled_to_their_mean() -> None:
    """`[3, 1]` violates; the least-squares non-decreasing fit is `[2, 2]` and not `[1, 3]`, which
    is the difference between a projection and a sort."""
    assert rf.isotonic([3.0, 1.0]) == (2.0, 2.0)
    assert rf.isotonic([3.0, 1.0, 2.0, 5.0, 4.0]) == (2.0, 2.0, 2.0, 4.5, 4.5)


def test_pooling_cascades_backwards() -> None:
    """One low value at the end can pool the whole prefix, which is the case a single-pass
    implementation without a stack gets wrong."""
    assert rf.isotonic([4.0, 3.0, 2.0, 1.0]) == (2.5, 2.5, 2.5, 2.5)


def test_the_fit_is_weighted_and_the_weights_move_the_pooled_mean() -> None:
    """Unweighted, `[1, 0]` pools to 0.5. With the second point counted three times it is 0.25 --
    which is what a fit over per-slice aggregates rather than per-decision rows needs."""
    assert rf.isotonic([1.0, 0.0]) == (0.5, 0.5)
    assert rf.isotonic([1.0, 0.0], [1.0, 3.0]) == (0.25, 0.25)


def test_the_fit_preserves_the_weighted_total() -> None:
    """A property rather than a case: pooling redistributes mass inside a block and never creates
    or destroys it, so the weighted sum is invariant."""
    values = [0.9, 0.1, 0.4, 0.8, 0.2, 0.7]
    weights = [1.0, 2.0, 1.0, 3.0, 1.0, 2.0]
    fitted = rf.isotonic(values, weights)
    assert math.isclose(
        math.fsum(f * w for f, w in zip(fitted, weights, strict=True)),
        math.fsum(v * w for v, w in zip(values, weights, strict=True)),
    )
    assert all(a <= b + 1e-9 for a, b in pairwise(fitted))


def test_a_zero_weight_is_refused_rather_than_skipped() -> None:
    """Almost always a caller dividing by a count that was zero. Skipping it would move the fit by
    an amount nothing in the report would explain."""
    with pytest.raises(ValueError, match="positive"):
        rf.isotonic([1.0, 2.0], [1.0, 0.0])
    with pytest.raises(ValueError, match="weights"):
        rf.isotonic([1.0, 2.0], [1.0])


# --------------------------------------------------------------------------------------------
# 2. The interval.
# --------------------------------------------------------------------------------------------


def test_ci95_is_an_interval_on_the_mean_and_shrinks_with_n() -> None:
    small = rf.ci95([0.1, 0.9] * 15)
    large = rf.ci95([0.1, 0.9] * 150)
    assert small[0] < 0.5 < small[1]
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_a_constant_sample_has_a_zero_width_interval_and_one_sample_has_none() -> None:
    """Zero variance is a real answer and not a degenerate one: every escalated decision in a
    synthetic corpus diverging identically really does pin the mean."""
    assert rf.ci95([0.4] * 40) == (0.4, 0.4)
    assert rf.ci95([0.4]) == (0.4, 0.4)
    assert all(math.isnan(bound) for bound in rf.ci95([]))


# --------------------------------------------------------------------------------------------
# 3. The fit itself.
# --------------------------------------------------------------------------------------------


def _fit(observations: list[rf.Observation], **kw: object) -> rf.Proposal | None:
    return rf.fit(
        observations,
        name="garble_escalate",
        current=0.50,
        slice_key="pdf/workiva/true/en",
        measured_on=MEASURED,
        divergence_micros=1000.0,
        **kw,  # type: ignore[arg-type]
    )


def test_the_fit_finds_the_breakpoint_the_corpus_was_built_around() -> None:
    """The whole point, stated as a number: divergence steps at 0.55, escalation costs 200 micros
    and a unit of divergence is worth 1,000, so escalating below the step loses 180 micros a part
    and the argmax is the first observation at or above it."""
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    assert proposal.proposed == pytest.approx(0.5546, abs=1e-4)
    assert proposal.n == 120
    assert proposal.method == rf.METHOD
    assert proposal.gain > 0


def test_the_boundary_decision_is_named_so_the_move_has_a_witness() -> None:
    """A threshold move nobody can point at one row for is a number without provenance; the
    `decision_id` at the boundary is the row `ow route explain` opens."""
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    assert proposal.boundary_decision_id == "dec_066"


def test_a_cheaper_escalation_moves_the_threshold_down() -> None:
    """The objective is a real trade and both terms move it. At 20 micros a part the fit is happy
    to escalate a wider band; at 10,000 it will not escalate at all and proposes the top."""
    cheap = _fit(_corpus(0.55, micros=20, low=0.05))
    dear = _fit(_corpus(0.55, micros=10_000))
    assert cheap is not None
    assert dear is not None
    assert cheap.proposed < dear.proposed


def test_a_below_direction_reads_the_other_end_of_the_axis() -> None:
    """`ink.coverage < @thresholds.ink_coverage_min` escalates the LOW end, so the escalating set
    is a suffix of the reversed order and the same sweep answers."""
    rising = [
        rf.Observation(signal=i / 99, divergence=0.7 if i / 99 < 0.3 else 0.01, micros=200)
        for i in range(100)
    ]
    proposal = rf.fit(
        rising,
        name="ink_coverage_min",
        current=0.25,
        slice_key="s",
        measured_on=MEASURED,
        divergence_micros=1000.0,
        direction="below",
    )
    assert proposal is not None
    assert proposal.proposed == pytest.approx(0.2929, abs=1e-3)
    assert proposal.direction == "below"


def test_an_unknown_slice_yields_no_proposal_at_all() -> None:
    """05:2995, and the plan means *at all*: *"a slice at `UNKNOWN` yields no proposal at all
    rather than a proposal with no evidence"*. The scoreboard has already said this slice has too
    few audits to speak; a fitter that spoke anyway would make the three-valued state cosmetic."""
    assert _fit(_corpus(), state=rf.SCOREBOARD_UNKNOWN) is None


def test_a_slice_below_min_n_yields_no_proposal() -> None:
    """The same refusal at the fit's own grain, and `MIN_SLICE_N` is `min_audit_n`'s thirty reused
    rather than reinvented."""
    assert MIN_SLICE_N == 30
    assert _fit(_corpus()[:29]) is None
    assert _fit(_corpus(0.55, n=60)) is not None


def test_a_column_that_never_varies_yields_no_proposal() -> None:
    """A threshold separates. Where the signal is constant every candidate is the same candidate,
    and the fit would report whichever one the sort happened to reach first."""
    flat = [
        rf.Observation(signal=0.5, divergence=0.3, micros=100, decision_id=f"d{i}")
        for i in range(60)
    ]
    assert _fit(flat) is None


def test_a_threshold_already_at_the_argmax_yields_no_proposal() -> None:
    """There is no diff to emit, which is the point of a command whose output a human commits."""
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    assert (
        rf.fit(
            _corpus(0.55),
            name="garble_escalate",
            current=proposal.proposed,
            slice_key="s",
            measured_on=MEASURED,
            divergence_micros=1000.0,
        )
        is None
    )


def test_the_fit_does_not_depend_on_the_input_order() -> None:
    """INV-19 wants an RNG-free harness; this is the other half of reproducibility. Two runs of
    `ow route propose` over one log must produce one diff, and a `GROUP BY` promises no order."""
    rows = _corpus(0.55)
    forward = _fit(rows)
    backward = _fit(list(reversed(rows)))
    assert forward is not None
    assert backward is not None
    assert forward.proposed == backward.proposed
    assert forward.boundary_decision_id == backward.boundary_decision_id


# --------------------------------------------------------------------------------------------
# 4. What a proposal is allowed to say.
# --------------------------------------------------------------------------------------------


def test_a_proposal_carries_every_inv_19_field_on_one_line() -> None:
    """*"The report prints `(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)` for
    every number, per INV-19"* (05:2994). A number printed without them is a rejectable defect."""
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    line = proposal.render()
    for fragment in (
        "n=120",
        "ci95",
        rf.METHOD,
        "pdf/workiva/true/en",
        proposal.corpus_digest,
        "witness=self",
        "boundary dec_066",
    ):
        assert fragment in line


def test_corpus_digest_has_no_field_of_its_own() -> None:
    """04 section 2.6: *"`corpus_digest` lives here and has no row-level twin: two fields that must
    agree are one field plus a bug."* The property reads `MeasuredOn`'s."""
    from dataclasses import fields  # noqa: PLC0415 -- one assertion needs it

    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    assert "corpus_digest" not in {f.name for f in fields(proposal)}
    assert proposal.corpus_digest == MEASURED.corpus_digest


def test_a_locally_produced_row_may_only_be_witness_self() -> None:
    """13-quality.md:1785: *"There is no flag that sets `ci`."* A fit over an operator's own
    decision log is as local as a row gets, and `ci` is the only ranked value."""
    with pytest.raises(ValueError, match="witness"):
        rf.Proposal(
            name="t",
            slice_key="s",
            current=0.1,
            proposed=0.2,
            direction="above",
            n=40,
            ci95=(0.1, 0.3),
            measured_on=MEASURED,
            objective=1.0,
            objective_now=0.0,
            witness="trust_me",
        )


def test_a_proposal_cannot_be_constructed_below_min_slice_n() -> None:
    """The refusal is on the TYPE and not only in `fit()`, because the `[[quality.benchmark]]` rule
    it borrows is a load-time refusal too: a row below `n = 30` is refused, not caveated."""
    with pytest.raises(ValueError, match="MIN_SLICE_N"):
        rf.Proposal(
            name="t",
            slice_key="s",
            current=0.1,
            proposed=0.2,
            direction="above",
            n=29,
            ci95=(0.1, 0.3),
            measured_on=MEASURED,
            objective=1.0,
            objective_now=0.0,
        )


# --------------------------------------------------------------------------------------------
# 5. The diff a human commits.
# --------------------------------------------------------------------------------------------


def test_one_slice_produces_a_diff_with_a_minus_and_a_plus() -> None:
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    lines = rf.render_diff(
        [proposal], path="00-builtin-route.toml", current={"garble_escalate": 0.5}
    )
    assert lines[0].startswith("--- a/")
    assert " [thresholds]" in lines
    assert any(line.startswith("-garble_escalate = 0.5") for line in lines)
    assert any(line.startswith("+garble_escalate = 0.5546") for line in lines)
    assert sum(line.startswith("#") for line in lines) == 1


def test_two_slices_that_disagree_propose_nothing_and_say_why() -> None:
    """D208, made visible in the artefact rather than in a docstring. 05:2986 fits *"one
    `[thresholds]` entry per slice"* and the grammar has one flat `[thresholds]` with no slice
    dimension, so two fitted values have nowhere to land. Emitting whichever sorted first would be
    a silent choice inside a diff whose whole purpose is that a human reads it."""
    first = _fit(_corpus(0.55))
    second = rf.fit(
        _corpus(0.80),
        name="garble_escalate",
        current=0.50,
        slice_key="docx/~/true/de",
        measured_on=MEASURED,
        divergence_micros=1000.0,
    )
    assert first is not None
    assert second is not None
    assert first.proposed != second.proposed
    lines = rf.render_diff([first, second], path="x.toml", current={"garble_escalate": 0.5})
    assert not any(line.startswith("+") and not line.startswith("+++") for line in lines)
    assert not any(line.startswith("-") and not line.startswith("---") for line in lines)
    assert any("D208" in line for line in lines)
    assert sum(line.startswith("#") for line in lines) == 3  # two fits and the explanation


def test_a_threshold_the_file_does_not_declare_is_never_introduced() -> None:
    """`ow route propose` proposes; it does not invent a knob. A `+` line for an undeclared key
    would be a diff adding a threshold no rule reads, which check 1 would then have to explain."""
    proposal = _fit(_corpus(0.55))
    assert proposal is not None
    lines = rf.render_diff([proposal], path="x.toml", current={})
    assert not any(line.startswith("+") and not line.startswith("+++") for line in lines)
    assert any("not declared in [thresholds]" in line for line in lines)


def test_no_proposals_render_no_diff_at_all() -> None:
    """An empty diff is zero lines and not a header with nothing under it -- a file a human is
    asked to commit must not exist when there is nothing to commit."""
    assert rf.render_diff([], path="x.toml", current={"garble_escalate": 0.5}) == ()
