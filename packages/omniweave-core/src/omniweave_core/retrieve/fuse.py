"""`fuse()` -- weighted RRF at one key, `block_id`, with 1-based ranks.

07:1393 is the whole of the scorer, and the `over` clause is half of it:

> `score(b) = sum over c of _weight(c) / (k + rank(c, b))`, over `c.status == OK`

That filter is not a tidiness: a Channel that blew its own `budget_ms` returns
`UNAVAILABLE(timeout)` *"with what it has"* (07:1791), so an `UNAVAILABLE` result arrives carrying a
real `ranked` tuple and must contribute **nothing**. The two-deadline split's other side is the
opposite instruction -- a Channel pre-empted by the query deadline *"reports its partial ranking
with truncated_at_limit = True and status OK"* -- so `truncated_at_limit` is read by nobody here
and the partial ranking scores exactly like a complete one. One flag decides both, and it is
`status`.

## Rank fusion, never score blending, and why the key is the Block

07:1461 states the rejected alternative and prices it: *"A linear hybrid blend adds a raw `bm25()`
in the tens to a cosine in [0,1]: whichever Channel has the larger numeric range wins, a
single-Channel hit scores on the same additive scale as a consensus hit, and ties break on dict
insertion order."* Nothing in this module ever reads a Channel's own score, and no Channel reports
one -- `ChannelResult` carries a `ranked` ORDER and not a number, which is what makes that failure
unrepresentable rather than merely avoided.

07:1469 settles the key in one line: *"`block_id` is the only foreign-key target for a Block
(INV-1) and `cite` is the only citable token (INV-8)"*. A segment-keyed fusion would need a second
fusion at block level with the ceiling computed one level up, which 07:1474 calls *"precisely the
drift `ceiling()` exists to prevent"*.

## `math.fsum`, because the score is a published sort key

ST7 (07:3241) and P-10 (13:874) make a `FusedHit` sequence *"totally ordered on `(-score,
block_id)`"* and stable across a `VACUUM` and an FTS5 `optimize`. Float addition is not
associative, so a plain `sum()` makes that sort key a function of the order the Channels arrive in
as well as of the contributions themselves, and the difference lands in the last unit in the last
place -- invisible in every printed number, and enough to decide a tie. `math.fsum` is exactly
rounded, so the score is a function of the SET.

**This buys an exactness the plan states, not a bug anybody has seen.** A search over the five
shipped weights at every rank combination, and over 4,000 blake2b-drawn weight sets, finds no
input on which the two disagree: at five terms of comparable magnitude the divergence needs a
weight spread near the float epsilon, and nothing plausible has one. It costs nothing at five
terms, and it makes half (a) of ST6 hold EXACTLY -- both sides sum the same multiset of
`_weight / 61` -- rather than only to the 1e-12 the property is stated at.

## `_ranks()` rather than 07:1386's `_rank(ch, b)`

The printed helper is *"ch.rank_of[b] if present else 1 + ch.ranked.index(b)"*, which is the rule
this module implements and not the shape it implements it in. `fuse()` needs every rank of every
Channel, and `.index()` inside a loop over the same tuple is quadratic at a length
`ChannelSpec.limit` sets to `k x overfetch` -- 07:1738's over-fetch factor reaches 64, so a 20-hit
query can hand this module a 1,280-long `ranked` per Channel and 1.6M list scans for an answer that
one pass already has. `_ranks()` is that one pass, first occurrence winning, which is what
`.index()` means for the duplicate `ChannelResult` does not itself refuse.

`rank_of` is empty for every Channel but `semantic`, and 07:1511 is why it is not empty there:
*"A segment hit at rank r yields its member blocks at rank r"*. Up to 64 blocks share one rank, and
a positional derivation would spread them across 64 distinct ranks, destroying the region-level
property the rule preserves.

## `k` here is the SMOOTHING constant and there is a different `k` in the same plan

`fuse(chs, *, k=RRF_K, ...)` is 07:1387's signature and its `k` is `RRF_K = 60`. `Query.k`,
`PackSpec.k` and `FusionSpec.k` all spell the name too, and 07:2349 gives the first of them the
other meaning: *"`k = 20` bounds fusion output"*. This function applies no output bound -- a
`QueryPlan` carries `plan.fusion.k` and `plan.pack.k` as two different numbers, and slicing the
returned list to the second is the caller's. D257 records the collision, which is not caught by any
bound check because the wrong value is a plausible one.

Specified in 07-store-and-retrieval.md sections 5.3 and 5.4; scheduled by 16-roadmap.md:659.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import TYPE_CHECKING

from omniweave_core.retrieve.types import (
    DEFAULT_WEIGHTS,
    RRF_K,
    ChannelResult,
    ChannelStatus,
    FusedHit,
    _channel_set,
    _weight,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["fuse"]


def _ranks(result: ChannelResult) -> dict[int, int]:
    """07:1386's rule over a whole Channel: `rank_of` where it has an entry, else 1 + position.

    First occurrence wins, which is what `1 + ch.ranked.index(b)` means. 07:1228 makes `ranked`
    *"deterministic order, duplicate-free"* and the store-side `ChannelOutcome` refuses the second
    half at its constructor, on the ground that a Channel ranking one block twice would give it two
    RRF contributions. `ChannelResult` carries no such refusal, so the shape this function is
    stated over is the looser one and the first position is the reading that agrees with the
    printed helper.
    """
    ranks: dict[int, int] = {}
    for position, block_id in enumerate(result.ranked, start=1):
        if block_id not in ranks:
            ranks[block_id] = result.rank_of.get(block_id, position)
    return ranks


def fuse(
    results: Iterable[ChannelResult],
    *,
    k: int = RRF_K,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> list[FusedHit]:
    """07:1387. The `OK` Channels' ranks, fused at `block_id`, ordered `(-score, block_id)`.

    Every block any `OK` Channel ranked appears exactly once, carrying the contribution and the
    rank of each Channel that ranked it and of no other -- a Channel absent from
    `channel_ranks` did not rank that block, which is the disclosure 07:1458 says a tunable fusion
    owes. `score` is `math.fsum` over the same contributions the hit carries, so the two can never
    disagree and `--explain` prints an arithmetic a reader can check by adding it up.

    The output is unbounded: `PackSpec.k` bounds it, this `k` smooths it, and the module docstring
    says why those are two numbers.
    """
    contributions: dict[int, dict[str, float]] = {}
    ranks: dict[int, dict[str, int]] = {}
    for result in _channel_set(results):
        if result.status != ChannelStatus.OK:
            continue
        resolved = _weight(result, weights)
        for block_id, rank in _ranks(result).items():
            contributions.setdefault(block_id, {})[result.name] = resolved / (k + rank)
            ranks.setdefault(block_id, {})[result.name] = rank
    hits = [
        FusedHit(
            block_id=block_id,
            score=math.fsum(terms.values()),
            channel_contributions=MappingProxyType(dict(terms)),
            channel_ranks=MappingProxyType(dict(ranks[block_id])),
        )
        for block_id, terms in contributions.items()
    ]
    hits.sort(key=lambda hit: (-hit.score, hit.block_id))
    return hits
