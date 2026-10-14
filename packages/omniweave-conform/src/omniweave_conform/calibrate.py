"""Calibration's two tests: `separation()` for ordinals, `sharpness()` for probabilities. **D824.**

13-quality.md section 9.3 prints both, and section 9.2 assigns each signal one:

- **`separation(rows)`** is Q-G11, for an ORDINAL signal (`block.trust`). It passes when `p_hat`
  is strictly increasing across the buckets AND adjacent Wilson 95% intervals do not overlap, at
  n >= 150 per bucket per slice. Below n it is `unknown`, and the slice is named, never pooled.
- **`sharpness(rows)`** is Q-G12, for a PROBABILITY signal (`garble.score`, `page.ocr_score`,
  `retrieval.confidence`). It passes at ECE <= 0.05 and Brier <= 0.08 over 10 equal-mass bins,
  at n >= 1000.

*"Both conditions in `separation()` are necessary and independently violable"* (13:1499), and P-21
asserts the second: a monotone-but-overlapping input returns `unknown`, never `pass`. ECE is
`NULL` for an ordinal, *"which is correct rather than missing"*. 16-roadmap.md W10.5 is the work
item; every interval is `stats.wilson()` (D813), and the rows are `oweval.Calibration` (D814).

## Rulings

1. **An ordinal bucket is one level**, `[level, level + 1)` as 13:1508-1510 print them, and
   every level below `levels` gets one, empty or not. An empty bucket has no `p_hat` and no
   interval.
2. **`separation()` is three-valued, in this order.** A bucket under `min_n` makes it `unknown`. A
   `p_hat` that fails to rise is `fail`: enough data said the order is wrong. A rising `p_hat` whose
   adjacent intervals touch or overlap is `unknown` (P-21): the order may be right and this sample
   cannot tell. Otherwise `pass`.
3. **Equal-mass bins are equal counts, and a tie never straddles two.** The scores are sorted
   and cut where `bins` runs of sizes differing by at most one would end, the larger first; a
   cut inside a run of equal scores moves to the run's end. So a signal with few distinct values
   has fewer, larger bins. Splitting a tie would grade identical scores differently by input
   order: all-0.9 scores that are 90% right would read as nine perfect bins and one hopeless one,
   an ECE of 0.18 for a signal whose ECE is 0.
4. **ECE is `Σ (n_b / N) · |accuracy_b - confidence_b|`** over the bins, confidence being the mean
   score in the bin; **Brier is `mean((score - label)²)`** over every row. Neither depends on the
   binning but ECE.
5. **`sharpness()` is `unknown` below `min_n`**, `pass` at both bounds, `fail` otherwise. The bounds
   are inclusive, `<=` as printed.
6. **A score is a finite number in [0, 1]**, and anything else is refused, not clamped: a
   probability signal that emits 1.3 is a defect in the signal.
7. **A row of `eval_calibration` is one bucket or one bin.** An ordinal's rows carry no ECE or
   Brier; a probability's rows carry the signal's ECE and Brier on every bin, since the columns are
   per row and the measures are per signal. An empty bucket writes no row: `p_hat` is NOT NULL.

Specified in 13-quality.md sections 9.2, 9.3 and 9.5, and 16-roadmap.md W10.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.store.oweval import Calibration

from omniweave_conform.stats import wilson

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "BINS",
    "BRIER_MAX",
    "ECE_MAX",
    "SEPARATION_MIN_N",
    "SHARPNESS_MIN_N",
    "Bucket",
    "Sharpness",
    "brier",
    "ece",
    "equal_mass_bins",
    "ordinal_buckets",
    "rows",
    "separation",
    "sharpness",
]

EvalStatus = Literal["pass", "fail", "unknown"]

SEPARATION_MIN_N: Final = 150
"""13:1490: *"at n >= 150 per bucket per slice"*."""

SHARPNESS_MIN_N: Final = 1000
"""13:1494: *"n >= 1000"*."""

ECE_MAX: Final = 0.05
BRIER_MAX: Final = 0.08
"""13:1494: *"ECE <= 0.05 and Brier <= 0.08"*, RT6 verbatim."""

BINS: Final = 10
"""13:1494: *"10 equal-mass bins"*."""


@dataclass(frozen=True, slots=True)
class Bucket:
    """One bucket or bin: its bounds, its counts, and its accuracy with a Wilson interval.

    `confidence` is the mean score of a probability bin and `None` for an ordinal bucket, which has
    a level and not a score. `p_hat` and the interval are `None` exactly when `n` is 0.
    """

    bucket: int
    lo: float
    hi: float
    n: int
    n_correct: int
    p_hat: float | None
    wilson_lo: float | None
    wilson_hi: float | None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Sharpness:
    """`sharpness()`'s answer: the status, the two measures, and the bins they came from."""

    status: EvalStatus
    ece: float | None
    brier: float | None
    bins: tuple[Bucket, ...]


def ordinal_buckets(labels: Iterable[tuple[int, bool]], levels: int) -> tuple[Bucket, ...]:
    """Ruling 1: one bucket per level, `[level, level + 1)`, empty or not."""
    n = [0] * levels
    ok = [0] * levels
    for level, correct in labels:
        if not 0 <= level < levels:
            raise ValueError(f"an ordinal level {level} is outside 0..{levels - 1}")
        n[level] += 1
        ok[level] += bool(correct)
    return tuple(_bucket(i, float(i), float(i + 1), n[i], ok[i]) for i in range(levels))


def separation(buckets: Sequence[Bucket], *, min_n: int = SEPARATION_MIN_N) -> EvalStatus:
    """Q-G11 (ruling 2): `unknown` under `min_n`, `fail` out of order, `unknown` if any adjacent
    intervals meet, and `pass` only when both conditions hold."""
    if not buckets or any(b.n < min_n for b in buckets):
        return "unknown"
    pairs = list(pairwise(buckets))
    if any(_p(low) >= _p(high) for low, high in pairs):
        return "fail"
    if any(_hi(low) >= _lo(high) for low, high in pairs):
        return "unknown"
    return "pass"


def equal_mass_bins(scored: Sequence[tuple[float, bool]], bins: int = BINS) -> tuple[Bucket, ...]:
    """Ruling 3: near-equal counts, larger first, each cut moved past a tie it would split."""
    _check_scores(scored)
    ordered = sorted(scored, key=lambda row: row[0])
    size, extra = divmod(len(ordered), bins)
    cuts, at = [], 0
    for b in range(bins):
        at += size + (1 if b < extra else 0)
        cut = max(at, cuts[-1] if cuts else 0)
        while 0 < cut < len(ordered) and ordered[cut][0] == ordered[cut - 1][0]:
            cut += 1
        cuts.append(cut)
    out, start = [], 0
    for b, cut in enumerate(cuts):
        members = ordered[start:cut]
        start = cut
        if not members:
            continue
        scores = [score for score, _ in members]
        correct = sum(1 for _, right in members if right)
        out.append(
            _bucket(
                b,
                scores[0],
                scores[-1],
                len(members),
                correct,
                confidence=math.fsum(scores) / len(members),
            )
        )
    return tuple(out)


def ece(bins: Sequence[Bucket]) -> float:
    """Ruling 4: the count-weighted mean gap between each bin's accuracy and its confidence."""
    total = sum(b.n for b in bins)
    if total == 0:
        raise ValueError("ECE over no rows is undefined")
    return math.fsum(
        (b.n / total) * abs((b.n_correct / b.n) - (b.confidence or 0.0)) for b in bins if b.n
    )


def brier(scored: Sequence[tuple[float, bool]]) -> float:
    """Ruling 4: the mean squared gap between each score and its 0-or-1 label."""
    _check_scores(scored)
    if not scored:
        raise ValueError("Brier over no rows is undefined")
    return math.fsum((s - (1.0 if c else 0.0)) ** 2 for s, c in scored) / len(scored)


def sharpness(
    scored: Sequence[tuple[float, bool]], *, min_n: int = SHARPNESS_MIN_N, bins: int = BINS
) -> Sharpness:
    """Q-G12 (ruling 5): `unknown` under `min_n`, else both bounds or `fail`."""
    _check_scores(scored)
    if len(scored) < min_n:
        return Sharpness(status="unknown", ece=None, brier=None, bins=())
    binned = equal_mass_bins(scored, bins)
    e, b = ece(binned), brier(scored)
    status: EvalStatus = "pass" if e <= ECE_MAX and b <= BRIER_MAX else "fail"
    return Sharpness(status=status, ece=e, brier=b, bins=binned)


def rows(
    buckets: Sequence[Bucket],
    *,
    eval_set_id: str,
    score_kind: str,
    producer_id: int,
    slice_key: str,
    label_sources: tuple[str, ...],
    measured_at_ns: int,
    harness_version: str,
    ece_value: float | None = None,
    brier_value: float | None = None,
) -> tuple[Calibration, ...]:
    """Ruling 7: one `eval_calibration` row per non-empty bucket."""
    out = []
    for b in buckets:
        if b.n == 0 or b.p_hat is None or b.wilson_lo is None or b.wilson_hi is None:
            continue
        out.append(
            Calibration(
                eval_set_id=eval_set_id,
                score_kind=score_kind,
                producer_id=producer_id,
                slice_key=slice_key,
                bucket=b.bucket,
                bucket_lo=b.lo,
                bucket_hi=b.hi,
                n=b.n,
                n_correct=b.n_correct,
                p_hat=b.p_hat,
                wilson_lo=b.wilson_lo,
                wilson_hi=b.wilson_hi,
                ece=ece_value,
                brier=brier_value,
                label_sources=label_sources,
                measured_at_ns=measured_at_ns,
                harness_version=harness_version,
            )
        )
    return tuple(out)


def _bucket(
    index: int, lo: float, hi: float, n: int, n_correct: int, *, confidence: float | None = None
) -> Bucket:
    if n == 0:
        return Bucket(index, lo, hi, 0, 0, None, None, None, confidence)
    w_lo, w_hi = wilson(n_correct, n)
    return Bucket(index, lo, hi, n, n_correct, n_correct / n, w_lo, w_hi, confidence)


def _check_scores(scored: Sequence[tuple[float, bool]]) -> None:
    """Ruling 6."""
    for score, _ in scored:
        if not (math.isfinite(score) and 0.0 <= score <= 1.0):
            raise ValueError(f"a probability score is a finite number in [0, 1], not {score!r}")


def _p(bucket: Bucket) -> float:
    assert bucket.p_hat is not None
    return bucket.p_hat


def _lo(bucket: Bucket) -> float:
    assert bucket.wilson_lo is not None
    return bucket.wilson_lo


def _hi(bucket: Bucket) -> float:
    assert bucket.wilson_hi is not None
    return bucket.wilson_hi
