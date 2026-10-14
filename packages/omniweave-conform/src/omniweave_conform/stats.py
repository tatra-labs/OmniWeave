"""Closed-form statistics with no RNG on the default path: 13-quality.md section 3. **D813.**

16-roadmap.md W10.1's statistics half: *"macro mean at `min_slice_n = 30`,
`se = sqrt((1/S²)·Σ sd_s²/n_s)`, Wilson everywhere, the sign-flip permutation test's exact
asymptotic with exact enumeration below N = 20"*. 13-quality.md:393 states the reason in one line:
*"Every interval, every p-value and every calibration bucket is closed-form."* olmOCR-Bench calls
`np.random` unseeded and its published intervals do not reproduce; nothing here can draw a number
that is not a function of its inputs.

`Method` is `eval_metric.method`'s domain, and every result below says which member produced it:

| quantity | function | method |
|---|---|---|
| a rate | `rate()` | `closed_form`: Wilson 95% |
| the headline over slices | `macro()` | `closed_form`, or `none` with no admissible slice |
| paired A/B, N < 20 | `paired()` | `exact`: every one of the 2^N sign flips |
| paired A/B, 20 <= N < 200 | `paired()` | `resampled`, with the seed it used |
| paired A/B, N >= 200 | `paired()` | `closed_form`: `p = 2(1 - Φ(abs(Σd) / sqrt(Σd²)))` |

The three paired bands are disjoint and exhaustive on N (13:408). Where 13:418 wants a random choice
it takes a keyed digest instead, and the three it names are here: `split_of()`,
`in_review_sample()` and `judge_swaps()`.

## Rulings

1. **Wilson's z is `NormalDist().inv_cdf(0.975)`**, computed rather than typed. 13:401's interval is
   "Wilson 95%", and 1.96 is a rounding of that quantile, not the quantile.
2. **A slice under `min_slice_n` is excluded from the macro mean and named.** 13:406's row is the
   slice's own (`method = none`, `state = 'unknown'`); its last clause, *"it never silently drops
   out of the macro mean"*, is met by `Macro.unknown`, which names every excluded slice for the
   report. `S` is the number of admitted slices. With none admitted, the macro's value is `None`
   and its method is `none`.
3. **The macro's interval is `value ± z·se`, unclamped.** `se` is 13:402's formula over the
   admitted slices, and clamping the bounds to [0, 1] would print an interval `se` does not
   describe. `sd` is the sample standard deviation (n - 1), and 0 for a one-item slice.
4. **A pair counts toward N whether or not it differs.** A zero difference adds nothing to `Σd` or
   to `Σd²` under any flip, so it changes no p; the bands are on N as 13:403-405 print it. A
   comparison over no pairs has no p: `method = none`. Every difference zero is `p = 1` in every
   band, the exact answer: each flip ties the observed statistic.
5. **Ties are counted.** A flip whose `abs(T)` equals the observed one is as extreme as it, which
   includes the identity flip and its mirror. Floating sums of the same terms in another order
   can differ in the last place, so a flip within `TIE_REL · Σabs(d)` of the observed `abs(Σd)`
   counts as a tie.
6. **The exact band meets in the middle.** Each half's 2^(N/2) signed sums are taken with
   `math.fsum`, one half is sorted, and each sum of the other half counts its partners by
   bisection. N = 19 is 1,536 sums rather than 524,288, and every sum is correctly rounded.
7. **The resampled band draws `RESAMPLES = 9,999` sign vectors** and reports
   `p = (1 + c) / (RESAMPLES + 1)`, `c` counting the draws at least as extreme. 13:404 fixes the
   seed and not the count; 9,999 resolves p to 1e-4, a hundredth of `guard_p_max = 0.01`. Draw
   `r` is the bits of `blake2b(seed ‖ r)`, 512 of them, which covers N's ceiling of 199.
8. **The seed is `blake2b(run_id ‖ metric ‖ "ow-perm-1")`'s first 8 bytes**, big-endian
   (13:404), and `Paired.seed` carries it. `eval_metric` has no column for it, but `run_id` and
   `metric` are the row's own key, so the row determines it.
9. **`‖` is a NUL between fields.** Concatenation alone makes `("ab", "c")` and `("a", "bc")` one
   input, so every digest here joins its UTF-8 fields with NUL, the framing the charter gives
   `corpus_digest`. A field containing NUL is refused.
10. **A `% 100` bucket is the whole 64-byte digest, read big-endian, mod 100**, and the judge's
    order is `digest[0] & 1`, both as 13:418-420 print them. `split_of()` cuts at 13:1422's
    boundaries: below 70 is `fit`, [70, 85) `validation`, [85, 100) `holdout`. The
    scoreboard's 85/15 is the same function (13:1250).

Specified in 13-quality.md sections 3, 9.1 and 11.1, and 16-roadmap.md W10.1.
"""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from statistics import NormalDist
from typing import TYPE_CHECKING, Final, Literal, get_args

from omniweave_core.drivers.card import MIN_SLICE_N

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "CLOSED_FORM_FROM",
    "EXACT_BELOW",
    "METHODS",
    "RESAMPLES",
    "SPLITS",
    "Z95",
    "Estimate",
    "Macro",
    "Method",
    "Paired",
    "Slice",
    "in_review_sample",
    "judge_swaps",
    "macro",
    "paired",
    "perm_seed",
    "rate",
    "split_bucket",
    "split_of",
    "wilson",
]

Method = Literal["closed_form", "exact", "resampled", "none"]
"""`eval_metric.method`'s CHECK, in the charter's order."""

METHODS: Final[tuple[str, ...]] = get_args(Method)

Split = Literal["fit", "validation", "holdout"]

SPLITS: Final[tuple[str, ...]] = get_args(Split)

Z95: Final[float] = NormalDist().inv_cdf(0.975)
"""Ruling 1: the two-sided 95% quantile, computed."""

EXACT_BELOW: Final = 20
"""13:403: exact enumeration of all 2^N sign flips for N < 20."""

CLOSED_FORM_FROM: Final = 200
"""13:405: the asymptotic for N >= 200. Between the two, the seeded resample."""

RESAMPLES: Final = 9_999
"""Ruling 7."""

TIE_REL: Final = 1e-9
"""Ruling 5: a flip this close to the observed statistic, relative to `Σabs(d)`, ties it."""

PERM_SALT: Final = "ow-perm-1"
SPLIT_SALT: Final = "ow-split-1"
REVIEW_SALT: Final = "ow-review-1"
JUDGE_SALT: Final = "ow-judge-1"

FIT_BELOW: Final = 70
HOLDOUT_FROM: Final = 85
REVIEW_PERCENT: Final = 5
"""13:419: *"the 5% visual review sample"*."""

_SEED_BYTES: Final = 8
_DRAW_INDEX_BYTES: Final = 4


@dataclass(frozen=True, slots=True)
class Estimate:
    """One number with its interval, in `eval_metric`'s columns: `value`, `n`, `ci_lo`, `ci_hi`
    and `method`. `value` and both bounds are `None` exactly when `method` is `none`."""

    value: float | None
    n: int
    ci_lo: float | None
    ci_hi: float | None
    method: Method


@dataclass(frozen=True, slots=True)
class Slice:
    """One slice's per-item scores, summarised: its key, `n`, mean and sample sd (ruling 3)."""

    key: str
    n: int
    mean: float
    sd: float

    @classmethod
    def of(cls, key: str, values: Iterable[float]) -> Slice:
        """Summarise `values`. An empty slice has no mean and is refused."""
        items = [float(v) for v in values]
        if not items:
            raise ValueError(f"slice {key!r} has no values")
        _finite(items)
        n = len(items)
        mean = math.fsum(items) / n
        sd = math.sqrt(math.fsum((v - mean) ** 2 for v in items) / (n - 1)) if n > 1 else 0.0
        return cls(key=key, n=n, mean=mean, sd=sd)


@dataclass(frozen=True, slots=True)
class Macro:
    """13:402's headline: the macro mean over the admitted slices, its `se`, and every slice
    `min_slice_n` excluded, by key (ruling 2)."""

    estimate: Estimate
    se: float | None
    admitted: tuple[str, ...]
    unknown: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Paired:
    """A paired A/B's sign-flip test: N, `Σd`, the two-sided p and the band that produced it.
    `seed` is the resampled band's (ruling 8) and `None` in the other two."""

    n: int
    statistic: float
    p: float | None
    method: Method
    seed: int | None


def wilson(k: int, n: int) -> tuple[float, float]:
    """The Wilson 95% interval for `k` successes in `n` trials, never the normal approximation,
    which collapses to a point at p = 1, where the gates live (13:401)."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"wilson needs 0 <= k <= n and n > 0, not k={k} n={n}")
    p = k / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> Estimate:
    """A rate with its Wilson interval. `n = 0` has no rate: `method = none`."""
    if n == 0 and k == 0:
        return Estimate(value=None, n=0, ci_lo=None, ci_hi=None, method="none")
    lo, hi = wilson(k, n)
    return Estimate(value=k / n, n=n, ci_lo=lo, ci_hi=hi, method="closed_form")


def macro(slices: Iterable[Slice], *, min_n: int = MIN_SLICE_N) -> Macro:
    """The macro mean over the slices with `n >= min_n`, and the others named (ruling 2)."""
    rows = list(slices)
    keys = [row.key for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate slice keys: {sorted(keys)}")
    admitted = [row for row in rows if row.n >= min_n]
    unknown = tuple(row.key for row in rows if row.n < min_n)
    total_n = sum(row.n for row in admitted)
    if not admitted:
        none = Estimate(value=None, n=total_n, ci_lo=None, ci_hi=None, method="none")
        return Macro(estimate=none, se=None, admitted=(), unknown=unknown)
    s = len(admitted)
    value = math.fsum(row.mean for row in admitted) / s
    se = math.sqrt(math.fsum(row.sd * row.sd / row.n for row in admitted) / (s * s))
    estimate = Estimate(
        value=value,
        n=total_n,
        ci_lo=value - Z95 * se,
        ci_hi=value + Z95 * se,
        method="closed_form",
    )
    return Macro(
        estimate=estimate, se=se, admitted=tuple(row.key for row in admitted), unknown=unknown
    )


def paired(diffs: Sequence[float], *, run_id: str, metric: str) -> Paired:
    """The two-sided sign-flip test over paired differences, in the band N selects (13:403-405)."""
    d = [float(v) for v in diffs]
    _finite(d)
    n = len(d)
    if n == 0:
        return Paired(n=0, statistic=0.0, p=None, method="none", seed=None)
    total = math.fsum(d)
    threshold = abs(total) - TIE_REL * math.fsum(abs(v) for v in d)
    if n < EXACT_BELOW:
        return Paired(n=n, statistic=total, p=_exact(d, threshold), method="exact", seed=None)
    if n < CLOSED_FORM_FROM:
        seed = perm_seed(run_id, metric)
        p = _resampled(d, total, threshold, seed)
        return Paired(n=n, statistic=total, p=p, method="resampled", seed=seed)
    squares = math.fsum(v * v for v in d)
    p = 1.0 if squares == 0 else math.erfc(abs(total) / math.sqrt(squares) / math.sqrt(2))
    return Paired(n=n, statistic=total, p=p, method="closed_form", seed=None)


def perm_seed(run_id: str, metric: str) -> int:
    """Ruling 8: the resample's seed, which `(run_id, metric)` determines."""
    head = hashlib.blake2b(_frame(run_id, metric, PERM_SALT)).digest()[:_SEED_BYTES]
    return int.from_bytes(head, "big")


def split_bucket(doc_key: str) -> int:
    """`blake2b(doc_key ‖ "ow-split-1") % 100` (13:1422), the one split function."""
    return _bucket(doc_key, SPLIT_SALT)


def split_of(doc_key: str) -> Split:
    """Which of the three splits `doc_key` is in, at 13:1422's boundaries (ruling 10)."""
    bucket = split_bucket(doc_key)
    if bucket < FIT_BELOW:
        return "fit"
    if bucket < HOLDOUT_FROM:
        return "validation"
    return "holdout"


def in_review_sample(artifact_slug: str, unit: str) -> bool:
    """13:419: `blake2b(artifact_slug ‖ unit ‖ "ow-review-1") % 100 < 5`."""
    return _bucket(artifact_slug, unit, REVIEW_SALT) < REVIEW_PERCENT


def judge_swaps(assertion_id: str, run_id: str) -> bool:
    """13:420: `blake2b(assertion_id ‖ run_id ‖ "ow-judge-1")[0] & 1`, which presents the pair
    in its second order when set."""
    return bool(hashlib.blake2b(_frame(assertion_id, run_id, JUDGE_SALT)).digest()[0] & 1)


def _exact(d: list[float], threshold: float) -> float:
    """Ruling 6: the share of all 2^N sign flips at least as extreme as the observed sum."""
    if threshold <= 0:
        return 1.0
    half = len(d) // 2
    left = _signed_sums(d[:half])
    right = sorted(_signed_sums(d[half:]))
    count = 0
    for a in left:
        count += len(right) - bisect_left(right, threshold - a)
        count += bisect_right(right, -threshold - a)
    return count / (1 << len(d))


def _signed_sums(d: list[float]) -> list[float]:
    """Every `Σ ±d_i`, one per sign vector, each correctly rounded."""
    return [
        math.fsum(v if mask >> i & 1 else -v for i, v in enumerate(d))
        for mask in range(1 << len(d))
    ]


def _resampled(d: list[float], total: float, threshold: float, seed: int) -> float:
    """Ruling 7: `RESAMPLES` sign vectors, draw `r` the bits of `blake2b(seed ‖ r)`."""
    if threshold <= 0:
        return 1.0
    prefix = seed.to_bytes(_SEED_BYTES, "big")
    count = 0
    for r in range(RESAMPLES):
        draw = hashlib.blake2b(prefix + r.to_bytes(_DRAW_INDEX_BYTES, "big")).digest()
        bits = int.from_bytes(draw, "big")
        flipped = math.fsum(v for i, v in enumerate(d) if not bits >> i & 1)
        if abs(total - 2 * flipped) >= threshold:
            count += 1
    return (1 + count) / (RESAMPLES + 1)


def _bucket(*fields: str) -> int:
    return int.from_bytes(hashlib.blake2b(_frame(*fields)).digest(), "big") % 100


def _frame(*fields: str) -> bytes:
    """Ruling 9: UTF-8 fields joined by NUL, and a field holding NUL refused."""
    for field in fields:
        if "\x00" in field:
            raise ValueError(f"a digest field may not contain NUL: {field!r}")
    return b"\x00".join(field.encode("utf-8") for field in fields)


def _finite(values: list[float]) -> None:
    for v in values:
        if not math.isfinite(v):
            raise ValueError(f"not a finite number: {v!r}")
