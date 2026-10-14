"""`omniweave_conform.rollup`: verdicts to `eval_metric` rows. D816."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from omniweave_conform.rollup import MACRO, RATES, Rate, rollup
from omniweave_conform.stats import wilson
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import (
    Assertion,
    Batch,
    Corpus,
    Metric,
    Run,
    Verdict,
    open_oweval,
    write,
)

if TYPE_CHECKING:
    from pathlib import Path

_MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="pdfium",
    runtime_version="6721",
    sampling="{}",
    prompt_version="n/a",
    hardware="x86_64-windows 8c/16GiB",
    corpus="golden@2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    harness_version="0.1.0",
)

_RUN = Run(
    run_id="run-1",
    suite="parse",
    corpus_id="golden",
    corpus_version="2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    subject="parse.pdf.pdfium",
    subject_version="0.1.0",
    producer_id=None,
    measured_on=_MEASURED,
    timing_basis="in_process",
    witness="ci",
    cassette="required",
    policy_digest=None,
    pricebook_digest=None,
    harness_version="0.1.0",
    code_fingerprint="c0ffee",
    hardware="x86_64-windows 8c/16GiB",
    started_ns=1,
    ended_ns=2,
    status="ok",
)

ORDER = RATES["order_acc"]


def _assertion(
    assertion_id: str,
    slices: tuple[str, ...],
    *,
    kind: str = "order",
    checked: str | None = "verified",
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        corpus_id="golden",
        corpus_version="2026.09",
        doc="d",
        page=1,
        type=kind,
        spec={},
        addr=None,
        evaluable_in="both",
        checked=checked,
        derived_from_sha256="sha256:" + "cd" * 32,
        slices=slices,
    )


def _verdict(assertion_id: str, slice_key: str, passed: bool, **over: object) -> Verdict:
    row = Verdict(
        run_id="run-1",
        assertion_id=assertion_id,
        evaluator="owdoc",
        passed=passed,
        score=None,
        slice_key=slice_key,
    )
    return replace(row, **over)


def _slice(name: str, n: int, passed: int) -> tuple[list[Assertion], list[Verdict]]:
    """`n` verified order assertions in slice `name`, the first `passed` of them passing."""
    assertions = [_assertion(f"{name}-{i}", (name,)) for i in range(n)]
    verdicts = [_verdict(a.assertion_id, name, i < passed) for i, a in enumerate(assertions)]
    return assertions, verdicts


def _two_slices() -> tuple[list[Assertion], list[Verdict]]:
    a1, v1 = _slice("pdf/born_digital/a", 40, 30)
    a2, v2 = _slice("pdf/born_digital/b", 40, 20)
    return a1 + a2, v1 + v2


def _rows(got: object) -> dict[str, Metric]:
    return {row.slice_key: row for row in got.metrics}  # type: ignore[attr-defined]


# --- the register ----------------------------------------------------------------------------


def test_the_headline_is_eval_metrics_default_slice() -> None:
    """`__macro__`, the column's DDL default, so a row written without a slice is the headline."""
    assert MACRO == "__macro__" == Metric.__dataclass_fields__["slice_key"].default


def test_the_three_direct_rollups() -> None:
    assert {name: (sorted(r.types), r.truth_kind) for name, r in RATES.items()} == {
        "table_rel_acc": (["cell_rel", "table"], "human"),
        "order_acc": (["order"], "rendered"),
        "field_acc": (["absent_field", "field", "null_kept"], "human"),
    }


@pytest.mark.parametrize("truth_kind", ["agreement", "self", "native_run", "vibes"])
def test_a_rate_refuses_a_truth_kind_that_is_not_accuracy(truth_kind: str) -> None:
    with pytest.raises(QualityError):
        Rate("order_acc", frozenset({"order"}), truth_kind)


# --- rows ------------------------------------------------------------------------------------


def test_each_slice_is_a_wilson_rate_and_the_macro_is_their_mean() -> None:
    assertions, verdicts = _two_slices()
    got = rollup(_RUN, ORDER, verdicts, assertions, evaluator="owdoc")
    rows = _rows(got)
    assert list(rows) == ["pdf/born_digital/a", "pdf/born_digital/b", MACRO]
    a = rows["pdf/born_digital/a"]
    assert (a.value, a.n, a.method, a.state, a.truth_kind) == (
        0.75,
        40,
        "closed_form",
        "ok",
        "rendered",
    )
    assert (a.ci_lo, a.ci_hi) == wilson(30, 40)
    head = rows[MACRO]
    assert head.value == pytest.approx(0.625)
    assert (head.n, head.method, head.state) == (80, "closed_form", "ok")
    assert head.ci_lo is not None
    assert head.ci_lo < 0.625 < head.ci_hi  # type: ignore[operator]
    assert (got.unscored, got.missing, got.expected) == (0, 0, 80)


def test_a_small_slice_is_unknown_and_out_of_the_macro() -> None:
    big_a, big_v = _slice("office/docx", 40, 40)
    small_a, small_v = _slice("office/xlsx", 12, 0)
    got = rollup(_RUN, ORDER, big_v + small_v, big_a + small_a, evaluator="owdoc")
    rows = _rows(got)
    small = rows["office/xlsx"]
    assert (small.value, small.n, small.method, small.state) == (None, 12, "none", "unknown")
    assert (small.ci_lo, small.ci_hi) == (None, None)
    assert rows[MACRO].value == 1.0
    assert rows[MACRO].n == 40


def test_a_slice_of_exactly_min_slice_n_is_rated() -> None:
    assertions, verdicts = _slice("s", 30, 27)
    rows = _rows(rollup(_RUN, ORDER, verdicts, assertions, evaluator="owdoc"))
    assert (rows["s"].value, rows["s"].n, rows["s"].state) == (0.9, 30, "ok")
    assert (rows[MACRO].value, rows[MACRO].state) == (pytest.approx(0.9), "ok")


def test_unchecked_assertions_run_and_never_score() -> None:
    assertions, verdicts = _slice("s", 40, 40)
    extra = [_assertion(f"u{i}", ("s",), checked=None) for i in range(5)]
    got = rollup(
        _RUN,
        ORDER,
        verdicts + [_verdict(a.assertion_id, "s", False) for a in extra],
        assertions + extra,
        evaluator="owdoc",
    )
    assert got.unscored == 5
    assert _rows(got)["s"].n == 40
    assert _rows(got)["s"].value == 1.0


def test_only_this_run_this_evaluator_this_corpus_and_these_types_count() -> None:
    assertions, verdicts = _slice("s", 40, 40)
    other_type = _assertion("t1", ("s",), kind="table")
    other_corpus = replace(_assertion("c1", ("s",)), corpus_version="2026.10")
    rejected = _assertion("r1", ("s",), checked="rejected")
    noise = [
        _verdict("s-0", "s", False, evaluator="text"),
        _verdict("s-1", "s", False, run_id="run-2"),
        _verdict("t1", "s", False),
        _verdict("c1", "s", False),
        _verdict("r1", "s", False),
    ]
    got = rollup(
        _RUN,
        ORDER,
        noise + verdicts,
        [*assertions, other_type, other_corpus, rejected],
        evaluator="owdoc",
    )
    assert _rows(got)["s"].n == 40
    assert _rows(got)["s"].value == 1.0
    assert got.expected == 40


def test_no_verdicts_is_one_unknown_headline() -> None:
    got = rollup(_RUN, ORDER, [], [], evaluator="owdoc")
    assert [(m.slice_key, m.state, m.value, m.n) for m in got.metrics] == [
        (MACRO, "unknown", None, 0)
    ]


# --- section 8.7 -----------------------------------------------------------------------------


def test_two_percent_missing_publishes_over_what_ran() -> None:
    """2 of 100 missing is at MAX_PARTIAL_FRAC, not above it: the rows stand, `n` is 98."""
    assertions, verdicts = _slice("s", 100, 100)
    got = rollup(_RUN, ORDER, verdicts[2:], assertions, evaluator="owdoc")
    assert (got.missing, got.expected) == (2, 100)
    assert _rows(got)["s"].state == "ok"
    assert _rows(got)["s"].n == 98


def test_more_than_two_percent_missing_makes_every_row_unknown() -> None:
    assertions, verdicts = _slice("s", 100, 100)
    got = rollup(_RUN, ORDER, verdicts[3:], assertions, evaluator="owdoc")
    assert {(m.state, m.value, m.method) for m in got.metrics} == {("unknown", None, "none")}
    assert _rows(got)["s"].n == 97
    assert _rows(got)[MACRO].n == 97


def test_a_slice_with_nothing_that_ran_makes_every_row_unknown() -> None:
    """One assertion of 101 is missing, under the fraction, but it was its slice's only one."""
    assertions, verdicts = _slice("s", 100, 100)
    lone = _assertion("lone", ("other",))
    got = rollup(_RUN, ORDER, verdicts, [*assertions, lone], evaluator="owdoc")
    assert (got.missing, got.expected) == (1, 101)
    assert {m.state for m in got.metrics} == {"unknown"}


def test_an_unsliced_assertion_counts_against_star() -> None:
    assertions, verdicts = _slice("s", 100, 100)
    lone = _assertion("lone", ())
    got = rollup(_RUN, ORDER, verdicts, [*assertions, lone], evaluator="owdoc")
    assert {m.state for m in got.metrics} == {"unknown"}


def test_an_unknown_run_yields_unknown_rows() -> None:
    assertions, verdicts = _two_slices()
    got = rollup(replace(_RUN, status="unknown"), ORDER, verdicts, assertions, evaluator="owdoc")
    assert {(m.state, m.value) for m in got.metrics} == {("unknown", None)}


def test_a_partial_run_under_the_fraction_still_publishes() -> None:
    assertions, verdicts = _two_slices()
    got = rollup(replace(_RUN, status="partial"), ORDER, verdicts, assertions, evaluator="owdoc")
    assert {m.state for m in got.metrics} == {"ok"}


# --- into the store --------------------------------------------------------------------------


def test_the_rows_satisfy_eval_metric(tmp_path: Path) -> None:
    assertions, verdicts = _two_slices()
    small_a, small_v = _slice("tiny", 3, 1)
    got = rollup(_RUN, ORDER, verdicts + small_v, assertions + small_a, evaluator="owdoc")
    corpus = Corpus(
        corpus_id="golden",
        version="2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        tier="A",
        n_docs=1,
        n_assertions=83,
        n_checked=83,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=True,
    )
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(
            connection,
            Batch(
                corpora=(corpus,),
                assertions=tuple(assertions + small_a),
                runs=(_RUN,),
                verdicts=tuple(verdicts + small_v),
                metrics=got.metrics,
            ),
        )
        rows = connection.execute(
            "SELECT slice_key, state FROM eval_metric ORDER BY slice_key"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [
        (MACRO, "ok"),
        ("pdf/born_digital/a", "ok"),
        ("pdf/born_digital/b", "ok"),
        ("tiny", "unknown"),
    ]
