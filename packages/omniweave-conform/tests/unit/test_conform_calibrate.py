"""`omniweave_conform.calibrate`: `separation()`, `sharpness()`, ECE and Brier. D824."""

from __future__ import annotations

import math

import pytest
from omniweave_conform.calibrate import (
    BINS,
    BRIER_MAX,
    ECE_MAX,
    SEPARATION_MIN_N,
    SHARPNESS_MIN_N,
    brier,
    ece,
    equal_mass_bins,
    ordinal_buckets,
    rows,
    separation,
    sharpness,
)
from omniweave_conform.stats import wilson


def _labels(level: int, n: int, correct: int) -> list[tuple[int, bool]]:
    return [(level, i < correct) for i in range(n)]


def _docx() -> list[tuple[int, bool]]:
    """13:1508-1510's office/docx slice: 74/212, 571/688 and 4009/4102."""
    return [*_labels(0, 212, 74), *_labels(1, 688, 571), *_labels(2, 4102, 4009)]


def test_the_thresholds_are_the_plans() -> None:
    assert (SEPARATION_MIN_N, SHARPNESS_MIN_N, ECE_MAX, BRIER_MAX, BINS) == (
        150,
        1000,
        0.05,
        0.08,
        10,
    )


# --- separation ------------------------------------------------------------------------------


def test_the_plans_worked_slice_separates() -> None:
    buckets = ordinal_buckets(_docx(), 3)
    assert [(b.bucket, b.lo, b.hi, b.n, b.n_correct) for b in buckets] == [
        (0, 0.0, 1.0, 212, 74),
        (1, 1.0, 2.0, 688, 571),
        (2, 2.0, 3.0, 4102, 4009),
    ]
    assert (buckets[0].wilson_lo, buckets[0].wilson_hi) == wilson(74, 212)
    assert separation(buckets) == "pass"


def test_a_small_bucket_is_unknown() -> None:
    """13:1513's scan-degraded slice: n = 96 < 150, and the slice is named, never pooled."""
    small = [*_labels(0, 96, 30), *_labels(1, 688, 571), *_labels(2, 4102, 4009)]
    assert separation(ordinal_buckets(small, 3)) == "unknown"
    assert separation(ordinal_buckets(small, 3), min_n=96) == "pass"


def test_monotone_but_overlapping_is_unknown_never_pass() -> None:
    """P-21: the order may be right; this sample cannot tell."""
    labels = [*_labels(0, 200, 100), *_labels(1, 200, 110), *_labels(2, 200, 120)]
    buckets = ordinal_buckets(labels, 3)
    assert buckets[0].p_hat < buckets[1].p_hat < buckets[2].p_hat  # type: ignore[operator]
    assert separation(buckets) == "unknown"


def test_out_of_order_with_enough_data_fails() -> None:
    labels = [*_labels(0, 300, 280), *_labels(1, 300, 150), *_labels(2, 300, 290)]
    assert separation(ordinal_buckets(labels, 3)) == "fail"
    level = [*_labels(0, 300, 150), *_labels(1, 300, 150), *_labels(2, 300, 290)]
    assert separation(ordinal_buckets(level, 3)) == "fail"


def test_an_empty_level_still_gets_its_bucket() -> None:
    buckets = ordinal_buckets(_labels(0, 10, 5), 3)
    assert [b.n for b in buckets] == [10, 0, 0]
    assert (buckets[1].p_hat, buckets[1].wilson_lo) == (None, None)
    assert separation(buckets) == "unknown"
    assert separation(()) == "unknown"
    with pytest.raises(ValueError, match=r"outside 0\.\.2"):
        ordinal_buckets([(3, True)], 3)


# --- equal-mass bins, ECE and Brier ----------------------------------------------------------


def test_equal_mass_bins_differ_by_at_most_one_larger_first() -> None:
    scored = [(i / 24, i % 2 == 0) for i in range(25)]
    bins = equal_mass_bins(scored)
    assert [b.n for b in bins] == [3, 3, 3, 3, 3, 2, 2, 2, 2, 2]
    assert (bins[0].lo, bins[0].hi) == (0.0, 2 / 24)
    assert bins[-1].hi == 1.0
    assert bins[0].confidence == pytest.approx(1 / 24)


def test_a_tie_stays_in_one_bin() -> None:
    """Ruling 3: a cut inside a run of equal scores moves to the run's end."""
    scored = [(0.5, i < 3) for i in range(6)]
    bins = equal_mass_bins(scored, bins=2)
    assert [(b.n, b.n_correct, b.lo, b.hi) for b in bins] == [(6, 3, 0.5, 0.5)]
    mixed = [(0.1, False)] * 3 + [(0.5, True)] * 4 + [(0.9, True)] * 3
    assert [b.n for b in equal_mass_bins(mixed, bins=2)] == [7, 3]


def test_a_perfectly_calibrated_signal_scores_zero() -> None:
    scored = [(0.0, False)] * 500 + [(1.0, True)] * 500
    assert ece(equal_mass_bins(scored)) == 0.0
    assert brier(scored) == 0.0


def test_ece_is_the_count_weighted_gap() -> None:
    """Every score 0.9 and half of them right: one bin's gap of 0.4 is the whole ECE."""
    scored = [(0.9, i % 2 == 0) for i in range(100)]
    assert ece(equal_mass_bins(scored, bins=1)) == pytest.approx(0.4)
    assert ece(equal_mass_bins(scored)) == pytest.approx(0.4)
    assert brier(scored) == pytest.approx((0.1**2 + 0.9**2) / 2)


def test_ece_weights_each_bin_by_its_count() -> None:
    """Bins of 7 and 3 with gaps of 17/70 and 0.1: 0.7 x 17/70 + 0.3 x 0.1 = 0.2, where an
    unweighted mean would say 0.171."""
    mixed = [(0.1, False)] * 3 + [(0.5, True)] * 4 + [(0.9, True)] * 3
    assert ece(equal_mass_bins(mixed, bins=2)) == pytest.approx(0.2)


@pytest.mark.parametrize("bad", [-0.1, 1.01, math.nan, math.inf])
def test_a_score_outside_zero_to_one_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="finite number in"):
        brier([(bad, True)])
    with pytest.raises(ValueError, match="finite number in"):
        equal_mass_bins([(bad, True)])


def test_nothing_to_measure_is_refused() -> None:
    with pytest.raises(ValueError, match="no rows"):
        brier([])
    with pytest.raises(ValueError, match="no rows"):
        ece(())


# --- sharpness -------------------------------------------------------------------------------


def _calibrated(n: int) -> list[tuple[float, bool]]:
    """Ten score levels, each right in exactly its own proportion of rows."""
    out = []
    per = n // 10
    for level in range(10):
        score = (level + 0.5) / 10
        right = round(score * per)
        out += [(score, i < right) for i in range(per)]
    return out


def _sharp(n: int) -> list[tuple[float, bool]]:
    """Half the rows at 0.02 and 2% right, half at 0.98 and 98% right: calibrated and sharp."""
    half = n // 2
    low = [(0.02, i < round(0.02 * half)) for i in range(half)]
    high = [(0.98, i < round(0.98 * half)) for i in range(half)]
    return low + high


def test_a_calibrated_sharp_signal_passes() -> None:
    got = sharpness(_sharp(2000))
    assert got.status == "pass"
    assert got.ece == pytest.approx(0.0, abs=1e-12)
    assert got.brier == pytest.approx(0.0196, abs=1e-12)
    assert len(got.bins) == 2


def test_a_calibrated_but_blunt_signal_fails_on_brier() -> None:
    """Calibration is not sharpness: ten honest levels from 0.05 to 0.95 have ECE 0 and a Brier
    of 0.1675, which is what RT6's second bound exists to refuse."""
    got = sharpness(_calibrated(2000))
    assert got.ece == pytest.approx(0.0, abs=1e-12)
    assert got.brier == pytest.approx(0.1675)
    assert got.status == "fail"


def test_an_overconfident_signal_fails() -> None:
    got = sharpness([(0.9, i % 2 == 0) for i in range(1200)])
    assert got.status == "fail"
    assert got.ece == pytest.approx(0.4)
    assert len(got.bins) == 1


def test_an_underconfident_signal_fails_on_ece_alone() -> None:
    """0.9 everywhere and always right: Brier 0.01 passes, ECE 0.1 does not."""
    got = sharpness([(0.9, True)] * 1200)
    assert got.brier == pytest.approx(0.01)
    assert got.ece == pytest.approx(0.1)
    assert got.status == "fail"


def test_sharpness_under_a_thousand_is_unknown() -> None:
    got = sharpness(_calibrated(990))
    assert (got.status, got.ece, got.brier, got.bins) == ("unknown", None, None, ())
    assert sharpness(_calibrated(990), min_n=990).status != "unknown"


def test_one_score_everywhere_is_one_bin_and_fails_on_brier_alone() -> None:
    """All 0.9 and 90% right: one bin, ECE 0, Brier 0.09. Split by input order, the same rows
    would read as nine perfect bins and one hopeless one, an ECE of 0.18."""
    got = sharpness([(0.9, i < 1080) for i in range(1200)])
    assert len(got.bins) == 1
    assert got.ece == pytest.approx(0.0, abs=1e-12)
    assert got.brier == pytest.approx(0.09)
    assert got.status == "fail"


# --- rows ------------------------------------------------------------------------------------


def test_rows_are_one_per_non_empty_bucket_and_carry_the_signals_measures() -> None:
    buckets = ordinal_buckets(_labels(0, 200, 50), 3)
    out = rows(
        buckets,
        eval_set_id="parse-cal@2026.09",
        score_kind="block.trust",
        producer_id=41,
        slice_key="office/docx",
        label_sources=("human",),
        measured_at_ns=7,
        harness_version="0.1.0",
    )
    assert [(r.bucket, r.n, r.n_correct, r.ece, r.brier) for r in out] == [(0, 200, 50, None, None)]
    assert (out[0].wilson_lo, out[0].wilson_hi) == wilson(50, 200)
    probability = sharpness(_calibrated(2000))
    binned = rows(
        probability.bins,
        eval_set_id="garble-cal@2026.09",
        score_kind="garble.score",
        producer_id=3,
        slice_key="*",
        label_sources=("synth_ocr:L3",),
        measured_at_ns=7,
        harness_version="0.1.0",
        ece_value=probability.ece,
        brier_value=probability.brier,
    )
    assert len(binned) == BINS
    assert {r.ece for r in binned} == {probability.ece}
