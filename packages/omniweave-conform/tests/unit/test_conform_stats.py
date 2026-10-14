"""`omniweave_conform.stats`: 13-quality.md section 3's closed-form statistics. D813."""

from __future__ import annotations

import hashlib
import itertools
import math
from fractions import Fraction
from statistics import NormalDist

import pytest
from omniweave_conform import stats
from omniweave_conform.stats import (
    CLOSED_FORM_FROM,
    EXACT_BELOW,
    RESAMPLES,
    Slice,
    in_review_sample,
    judge_swaps,
    macro,
    paired,
    perm_seed,
    rate,
    split_bucket,
    split_of,
    wilson,
)

_Z = NormalDist().inv_cdf(0.975)


def _brute(d: list[Fraction]) -> Fraction:
    """Every sign flip in exact arithmetic: the share with `abs(Σ) >= abs(Σd)`."""
    observed = abs(sum(d))
    hits = sum(
        1
        for signs in itertools.product((1, -1), repeat=len(d))
        if abs(sum(s * v for s, v in zip(signs, d, strict=True))) >= observed
    )
    return Fraction(hits, 2 ** len(d))


def _eighths(n: int, salt: str) -> list[Fraction]:
    """`n` differences in [-2, 2) in steps of 1/8, chosen by digest: exact in binary floating
    point, so the float path and the Fraction oracle see the same numbers."""
    out = []
    for i in range(n):
        byte = hashlib.blake2b(f"{salt}:{i}".encode()).digest()[0]
        out.append(Fraction(byte % 32 - 16, 8))
    return out


# --- the methods ------------------------------------------------------------------------------


def test_methods_are_eval_metric_check_in_order() -> None:
    assert stats.METHODS == ("closed_form", "exact", "resampled", "none")
    assert stats.SPLITS == ("fit", "validation", "holdout")


# --- Wilson -----------------------------------------------------------------------------------


def test_wilson_reproduces_the_worked_calibration_rows() -> None:
    """13-quality.md:1507's three office/docx buckets, at three decimals. The plan prints 0.416
    and 0.982 for the first and third upper bounds; Wilson's are 0.4154 and 0.9815 (D813)."""
    cases = {
        (74, 212): (0.349, 0.288, 0.415),
        (571, 688): (0.830, 0.800, 0.856),
        (4009, 4102): (0.977, 0.972, 0.981),
    }
    for (k, n), (p_hat, lo, hi) in cases.items():
        got = rate(k, n)
        assert got.method == "closed_form"
        assert got.n == n
        assert got.value is not None
        assert got.ci_lo is not None
        assert got.ci_hi is not None
        assert (round(got.value, 3), round(got.ci_lo, 3), round(got.ci_hi, 3)) == (p_hat, lo, hi)


def test_wilson_uses_the_computed_quantile() -> None:
    """At k = 0 the upper bound is z²/(n + z²) exactly, so z itself is visible."""
    assert stats.Z95 == _Z
    _, hi = wilson(0, 40)
    assert hi == pytest.approx(_Z * _Z / (40 + _Z * _Z), rel=1e-12)


def test_wilson_is_not_the_normal_approximation_at_p_one() -> None:
    """The normal interval at 30/30 is the point [1, 1]; Wilson's lower bound is below it."""
    lo, hi = wilson(30, 30)
    assert hi == 1.0
    assert lo == pytest.approx(30 / (30 + _Z * _Z), rel=1e-12)
    lo0, hi0 = wilson(0, 30)
    assert lo0 == 0.0
    assert hi0 == pytest.approx(1 - lo, rel=1e-12)


def test_wilson_is_symmetric_in_successes_and_failures() -> None:
    for k, n in ((3, 17), (50, 51), (12, 400)):
        lo, hi = wilson(k, n)
        lo_c, hi_c = wilson(n - k, n)
        assert lo == pytest.approx(1 - hi_c, abs=1e-12)
        assert hi == pytest.approx(1 - lo_c, abs=1e-12)


@pytest.mark.parametrize(("k", "n"), [(0, 0), (-1, 5), (6, 5), (1, -1)])
def test_wilson_refuses_impossible_counts(k: int, n: int) -> None:
    with pytest.raises(ValueError, match="wilson needs"):
        wilson(k, n)


def test_a_rate_over_nothing_has_no_value() -> None:
    assert rate(0, 0) == stats.Estimate(value=None, n=0, ci_lo=None, ci_hi=None, method="none")


# --- the macro mean ---------------------------------------------------------------------------


def test_macro_is_the_mean_of_slice_means_with_the_plans_se() -> None:
    a = Slice(key="office/docx", n=40, mean=0.9, sd=0.2)
    b = Slice(key="pdf/scan", n=100, mean=0.6, sd=0.5)
    got = macro([a, b])
    assert got.admitted == ("office/docx", "pdf/scan")
    assert got.unknown == ()
    assert got.estimate.value == pytest.approx(0.75)
    se = math.sqrt((0.2**2 / 40 + 0.5**2 / 100) / 4)
    assert got.se == pytest.approx(se, rel=1e-12)
    assert got.estimate.ci_lo == pytest.approx(0.75 - _Z * se, rel=1e-12)
    assert got.estimate.ci_hi == pytest.approx(0.75 + _Z * se, rel=1e-12)
    assert got.estimate.n == 140
    assert got.estimate.method == "closed_form"


def test_a_slice_under_min_slice_n_is_named_and_out_of_the_mean() -> None:
    """At n = 30 a slice is in; at 29 it is named in `unknown` and S counts only the others."""
    at = Slice(key="in", n=30, mean=0.5, sd=0.1)
    under = Slice(key="small", n=29, mean=0.0, sd=0.1)
    got = macro([under, at])
    assert stats.MIN_SLICE_N == 30
    assert got.admitted == ("in",)
    assert got.unknown == ("small",)
    assert got.estimate.value == pytest.approx(0.5)
    assert got.se == pytest.approx(0.1 / math.sqrt(30), rel=1e-12)


def test_a_macro_with_no_admissible_slice_is_none() -> None:
    got = macro([Slice(key="a", n=5, mean=1.0, sd=0.0)])
    assert got.estimate.method == "none"
    assert got.estimate.value is None
    assert got.estimate.ci_lo is None
    assert got.se is None
    assert got.unknown == ("a",)
    assert macro([]).estimate.method == "none"


def test_macro_honours_a_register_min_n() -> None:
    got = macro([Slice(key="a", n=5, mean=1.0, sd=0.0)], min_n=5)
    assert got.admitted == ("a",)


def test_macro_refuses_duplicate_keys() -> None:
    row = Slice(key="a", n=40, mean=1.0, sd=0.0)
    with pytest.raises(ValueError, match="duplicate slice keys"):
        macro([row, row])


def test_slice_of_takes_the_sample_sd() -> None:
    got = Slice.of("s", [1, 2, 3, 4])
    assert got.n == 4
    assert got.mean == 2.5
    assert got.sd == pytest.approx(math.sqrt(5 / 3), rel=1e-12)
    assert Slice.of("one", [7.0]).sd == 0.0
    with pytest.raises(ValueError, match="no values"):
        Slice.of("empty", [])
    with pytest.raises(ValueError, match="finite"):
        Slice.of("nan", [1.0, math.nan])


# --- the paired test: the bands ---------------------------------------------------------------


def test_the_bands_are_disjoint_and_exhaustive_on_n() -> None:
    assert (EXACT_BELOW, CLOSED_FORM_FROM) == (20, 200)
    ones = [1.0] * 200
    assert paired(ones[:19], run_id="r", metric="m").method == "exact"
    assert paired(ones[:20], run_id="r", metric="m").method == "resampled"
    assert paired(ones[:199], run_id="r", metric="m").method == "resampled"
    assert paired(ones, run_id="r", metric="m").method == "closed_form"


def test_no_pairs_is_no_p() -> None:
    got = paired([], run_id="r", metric="m")
    assert (got.n, got.p, got.method, got.seed) == (0, None, "none", None)


@pytest.mark.parametrize("n", [1, 5, 19, 20, 150, 200, 260])
def test_every_difference_zero_is_p_one_in_every_band(n: int) -> None:
    assert paired([0.0] * n, run_id="r", metric="m").p == 1.0


def test_a_non_finite_difference_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        paired([1.0, math.inf], run_id="r", metric="m")


# --- the exact band ---------------------------------------------------------------------------


def test_exact_counts_the_identity_and_its_mirror() -> None:
    assert paired([1.0] * 5, run_id="r", metric="m").p == 2 / 32
    assert paired([1.0] * 19, run_id="r", metric="m").p == 2 / 2**19
    assert paired([1.0, 2.0, 3.0], run_id="r", metric="m").p == 2 / 8


def test_exact_counts_a_non_identity_tie() -> None:
    """[1, 1, 2]: Σ = 4, and (+, +, +), (-, -, -) are the only flips at 4. [1, 1, 1, -1] has
    Σ = 2, and ten of its sixteen flips reach abs(2), eight of them exactly."""
    assert paired([1.0, 1.0, 2.0], run_id="r", metric="m").p == 2 / 8
    want = _brute([Fraction(1), Fraction(1), Fraction(1), Fraction(-1)])
    assert want == Fraction(10, 16)
    assert paired([1.0, 1.0, 1.0, -1.0], run_id="r", metric="m").p == float(want)


@pytest.mark.parametrize(("n", "salt"), [(4, "a"), (7, "b"), (12, "c"), (13, "d"), (14, "e")])
def test_exact_equals_brute_force_in_exact_arithmetic(n: int, salt: str) -> None:
    d = _eighths(n, salt)
    got = paired([float(v) for v in d], run_id="r", metric="m")
    assert got.method == "exact"
    assert got.p == float(_brute(d))


def test_exact_ties_survive_float_rounding() -> None:
    """[0.1, -0.2, 0.7]: the identity flip, summed as a half plus a half, lands one rounding
    below `fsum`'s total, so without ruling 5 the observed statistic would not tie itself and
    p would be 4/8. In exact decimal arithmetic it is 6/8, and so is the result."""
    d = [0.1, -0.2, 0.7]
    exact = _brute([Fraction(str(v)) for v in d])
    assert exact == Fraction(6, 8)
    assert paired(d, run_id="r", metric="m").p == float(exact)
    d4 = [0.1, 0.2, -0.3, 0.7]
    assert paired(d4, run_id="r", metric="m").p == float(_brute([Fraction(str(v)) for v in d4]))


# --- the resampled band -----------------------------------------------------------------------


def test_the_seed_is_the_plans_digest_of_the_rows_key() -> None:
    want = int.from_bytes(hashlib.blake2b(b"run-7\x00recall\x00ow-perm-1").digest()[:8], "big")
    assert perm_seed("run-7", "recall") == want
    got = paired([1.0] * 30, run_id="run-7", metric="recall")
    assert got.seed == want
    assert perm_seed("run-7", "precision") != want
    assert perm_seed("ab", "c") != perm_seed("a", "bc")


def test_resampled_is_reproducible_from_the_row() -> None:
    d = [float(v) for v in _eighths(40, "rep")]
    one = paired(d, run_id="run-1", metric="m")
    assert paired(d, run_id="run-1", metric="m") == one
    assert one.method == "resampled"


def test_resampled_p_is_never_zero() -> None:
    """All 20 differences one: two flips in 2^20 are as extreme, and the resample floor is
    1 / (RESAMPLES + 1), a count that cannot report an impossibility."""
    got = paired([1.0] * 20, run_id="r", metric="m")
    assert got.p is not None
    assert 1 / (RESAMPLES + 1) <= got.p <= 3 / (RESAMPLES + 1)


def test_resampled_agrees_with_exact_enumeration() -> None:
    """At N = 20 the exact share is computable; 9,999 draws land within five standard errors."""
    d = [float(v) for v in _eighths(20, "agree")]
    threshold = abs(math.fsum(d)) - stats.TIE_REL * math.fsum(abs(v) for v in d)
    exact = stats._exact(d, threshold)
    got = paired(d, run_id="r", metric="m")
    assert got.p is not None
    assert 0.05 < exact < 0.95
    sigma = math.sqrt(exact * (1 - exact) / RESAMPLES)
    assert abs(got.p - exact) < 5 * sigma


# --- the closed-form band ---------------------------------------------------------------------


def test_closed_form_is_the_plans_asymptotic() -> None:
    d = [float(v) for v in _eighths(250, "asym")]
    got = paired(d, run_id="r", metric="m")
    z = abs(math.fsum(d)) / math.sqrt(math.fsum(v * v for v in d))
    assert got.method == "closed_form"
    assert got.p == pytest.approx(2 * (1 - NormalDist().cdf(z)), rel=1e-9)
    assert got.statistic == math.fsum(d)
    assert got.seed is None


# --- the digest choices -----------------------------------------------------------------------


def test_split_bucket_is_the_plans_digest() -> None:
    want = int.from_bytes(hashlib.blake2b(b"doc-3f2a\x00ow-split-1").digest(), "big") % 100
    assert split_bucket("doc-3f2a") == want


def test_split_of_cuts_at_seventy_and_eighty_five() -> None:
    seen: dict[int, str] = {}
    for i in range(5000):
        key = f"doc-{i}"
        seen.setdefault(split_bucket(key), split_of(key))
    assert set(seen) == set(range(100))
    for bucket, split in seen.items():
        want = "fit" if bucket < 70 else "validation" if bucket < 85 else "holdout"
        assert split == want, bucket


def test_the_split_is_balanced() -> None:
    counts = dict.fromkeys(stats.SPLITS, 0)
    for i in range(10_000):
        counts[split_of(f"k{i}")] += 1
    assert abs(counts["fit"] - 7000) < 200
    assert abs(counts["validation"] - 1500) < 150
    assert abs(counts["holdout"] - 1500) < 150


def test_the_review_sample_is_five_percent_by_digest() -> None:
    picked = [i for i in range(10_000) if in_review_sample("deck-a", str(i))]
    assert abs(len(picked) - 500) < 75
    for i in range(200):
        bucket = int.from_bytes(
            hashlib.blake2b(f"deck-a\x00{i}\x00ow-review-1".encode()).digest(), "big"
        )
        assert in_review_sample("deck-a", str(i)) is (bucket % 100 < 5)


def test_the_judge_order_is_the_low_bit_of_the_first_byte() -> None:
    swaps = 0
    for i in range(2000):
        first = hashlib.blake2b(f"a{i}\x00run-1\x00ow-judge-1".encode()).digest()[0]
        assert judge_swaps(f"a{i}", "run-1") is bool(first & 1)
        swaps += judge_swaps(f"a{i}", "run-1")
    assert abs(swaps - 1000) < 100


def test_a_nul_in_a_digest_field_is_refused() -> None:
    with pytest.raises(ValueError, match="NUL"):
        split_bucket("a\x00b")
    with pytest.raises(ValueError, match="NUL"):
        perm_seed("run", "m\x00")
