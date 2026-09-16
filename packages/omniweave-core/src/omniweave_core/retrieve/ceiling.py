"""`ceiling()` -- the denominator, which counts Channels that LOOKED and not Channels that scored.

07:1394 is the formula and its status set is the entire content of the module:

> `ceiling = sum over c of _weight(c) / (k + 1)`, over `c.status in (OK, EMPTY)` OR
> (`c.status is OFF and c.reason == OffReason.QUERY_DEADLINE`)

`fuse()` sums over `OK` alone. The difference is deliberate and 07:1445 forbids removing it:
*"Nobody may "simplify" it to match `fuse()`, and nobody may drop the `OFF(query_deadline)`
carve-out."* An `EMPTY` Channel's weight is in the denominator because *"it discloses "we looked
there and found nothing", which is exactly the confidence penalty an honest ceiling should
carry"*.

## The one branch, and why it is a frozenset rather than a comment

07:1415: *"`OFF` is two different things and only one of them is ceiling-exempt."* `OFF(vectors)`
and `OFF(not_in_plan)` are operator choices -- *"the Channel was never going to look, so its weight
has no business in a denominator that measures "we looked there""*. `OFF(query_deadline)` is a
runtime shortfall, and exempting it *"shrinks the denominator and makes a worse answer report
higher confidence, which is the exact inversion `ceiling()` exists to prevent"*.

The membership is `CEILING_BEARING` and the predicate is `ChannelResult.counts_in_ceiling`, both of
them W6.1's. This module deliberately re-derives neither: 07:1215 closes `OffReason` *"because
`ceiling()` branches on it"*, and a second reading of that branch here is the drift the closure
exists to prevent. D236 is the gap this leaves -- three `OFF` reasons are printed in the document
outside the closed enum (`short_circuit`, `narrowing_empty`, `vectors_disabled`) and none has a
ruling, so all three fall through as NOT ceiling-bearing. Worked plans (1) and (2) are the evidence
that the fall-through is the reading the document's own arithmetic uses: 07:1850 excludes an
`OFF(vectors_disabled)` semantic Channel from `4.6 / 61`, and 07:1867 excludes four
`OFF(short_circuit)` Channels from `2.0 / 61`.

## `k + 1` from the argument, never `CEILING_WEIGHT_DENOMINATOR`

07:1408 is a rule with a name attached: *"**Never hardcode `1/(k+1)`.** These weights are not
normalised to sum to 1, so the ceiling genuinely depends on which Channels ran."*
`CEILING_WEIGHT_DENOMINATOR` is `RRF_K + 1` and is what that rule leaves standing -- a name for the
DEFAULT's denominator, so no reader has to recognise 61. It is not what this function divides by.
`ceiling()` takes its own `k`, and a ceiling normalising by 61 while `fuse()` scored with a `k` the
same caller passed is a ceiling from a different scorer, which is the whole of what ST6 is about.
The two agree at the default and the test that pins them together says so.

## `confidence()` is here because the denominator's two zeros are

07:1397 prints `confidence = best_score / ceiling` and 07:2010 shapes the field as `float | None`
with one of its undefined cases stated -- *"None with best_score"*, i.e. no Channel ranked
anything. The other case is D258's: 07:1484 blesses `0.0` as an explicit per-query weight, so a
channel set whose only ceiling-bearing members carry weight `0.0` produces a real `best_score` over
a `0.0` ceiling, and `best / ceiling` is `0/0`. Both cases are `None` here, at one site, rather
than a formula spelled a second time inside `build_verdict()` and a third inside
`ow query --explain`.

This is not a second constructor for `Verdict` -- 07:2132 keeps that to `build_verdict()` (W6.5).
It computes one field.

Specified in 07-store-and-retrieval.md sections 5.1, 5.3 and 6.7; scheduled by 16-roadmap.md:659.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from omniweave_core.retrieve.types import DEFAULT_WEIGHTS, RRF_K, _channel_set, _weight

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_core.retrieve.types import ChannelResult

__all__ = ["ceiling", "confidence"]


def ceiling(
    results: Iterable[ChannelResult],
    *,
    k: int = RRF_K,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> float:
    """07:1388. The best score attainable by a hit ranked first in every Channel that looked.

    `math.fsum` for `fuse()`'s reason: the sum must not depend on the order the Channels arrive
    in, because half (a) of ST6 compares this number against one summed over the same terms in a
    different order.

    Returns `0.0` over an empty channel set and over one whose members all declined to look. That
    is a denominator, and D258 is that nothing says so.
    """
    return math.fsum(
        _weight(result, weights) / (k + 1)
        for result in _channel_set(results)
        if result.counts_in_ceiling
    )


def confidence(best_score: float | None, score_ceiling: float) -> float | None:
    """07:1397's ratio, with both of its undefined cases as `None` (07:2010, D258).

    `None` is not a low confidence and a surface may not render it as one: 07:2140's ladder
    compares against `fusion.low_confidence`, and a `0.0` substituted here would make "nothing was
    ranked" and "everything ranked badly" the same verdict.
    """
    if best_score is None or score_ceiling == 0.0:
        return None
    return best_score / score_ceiling
