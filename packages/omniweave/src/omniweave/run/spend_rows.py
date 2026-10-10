"""`route_spend`: the bill, one row an attempt, in the completion's transaction. **D733.**

05 section 6.4: *"The reservation is a promise; this row is the bill. It is written by the runner on
**every attempt**, in the same transaction as the derived rows, the `work` transition, the `dep`
rows and the reservation commit (I20)."* `SqliteStore.complete()` has carried an empty `spend_row`
participant since P2 (`store.queue`'s module table). This module fills it, and `ow ingest` wires it.

## Rulings (the ledger's D733)

1. **A row is written for every completion that names a decision and measured a Spend.** The
   decision is the work row's own, read by the statement, so a row with none writes nothing:
   `route_spend.decision_id` is `NOT NULL`, and an `op.*` row or a free Pass has no decision
   (05:2583). A `StepResult` whose metrics carry no Spend writes nothing either. `None` is "nothing
   was measured", not a zero bill (D139).
2. **`attempt` is the decision's next.** One decision can be several work rows (the same document
   in two folders is one decision, 05:1915) and several attempts (05:2594), and the primary key is
   `(decision_id, attempt)`. So the attempt is counted over the decision's rows, in the same
   statement that writes it.
3. **The seven dimensions are the Spend's, and `micros` is the result's**, priced by the runner and
   0 until a `PriceBook` prices it (INV-15).
4. **A hit is `was_cache_hit = 1` with the Spend it replays** (05:2556-2572: *"a hit replays the
   cached `Spend` and bills 0"*). `would_have_been_micros` is 0 until a `PriceBook` prices it too.
5. **`outcome` is the `StepResult`'s wire value**, so a failed attempt is a row as a paid one is.

## Pricing (D734)

6. **The runner prices each attempt at commit, from the run's `PriceBook`**: `micros` is the
   attempt's `Spend.micros(book)`, INV-15's one site. A hit bills 0, and its
   `would_have_been_micros` is the Spend it replays, priced the same way (05:2556). With no book
   both are 0, because unpriced is not free (05:2410), and the result's own `micros` stands.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.store.queue import Statement

from omniweave.route.spend import Spend

if TYPE_CHECKING:
    from omniweave_core.store.queue import Contribution, StepResultView

    from omniweave.route.spend import PriceBook

__all__ = ["SPEND_SQL", "priced", "spend_row"]

SPEND_SQL: Final = """
INSERT INTO route_spend(decision_id, attempt, provider, wall_ms, cpu_ms, gpu_ms, tokens_in,
                        tokens_out, calls, bytes_egress, micros, was_cache_hit,
                        would_have_been_micros, outcome)
SELECT w.decision_id,
       (SELECT IFNULL(MAX(s.attempt), 0) + 1 FROM route_spend AS s
         WHERE s.decision_id = w.decision_id),
       :provider, :wall_ms, :cpu_ms, :gpu_ms, :tokens_in, :tokens_out, :calls, :bytes_egress,
       :micros, :was_cache_hit, :would_have_been_micros, :outcome
  FROM work AS w
 WHERE w.id = :id AND w.decision_id IS NOT NULL
"""
"""Rulings 1-5: one row, its decision and attempt read off the work row and the ledger."""

_DIMENSIONS: Final = (
    "wall_ms",
    "cpu_ms",
    "gpu_ms",
    "tokens_in",
    "tokens_out",
    "calls",
    "bytes_egress",
)


def priced(book: PriceBook | None) -> Contribution:
    """`SqliteStore`'s `spend_row` contribution, pricing through `book` (ruling 6)."""

    def contribute(row_id: int, result: StepResultView) -> tuple[Statement, ...]:
        return _row(row_id, result, book)

    return contribute


def spend_row(row_id: int, result: StepResultView) -> tuple[Statement, ...]:
    """The contribution with no book: the attempt's row, unpriced (rulings 1-5)."""
    return _row(row_id, result, None)


def _row(row_id: int, result: StepResultView, book: PriceBook | None) -> tuple[Statement, ...]:
    """The attempt's row, or none when nothing was measured (ruling 1)."""
    metrics: Any = result.metrics
    spend = getattr(metrics, "spend", None)
    if spend is None:
        return ()
    dims = {d: int(getattr(spend, d, 0)) for d in _DIMENSIONS}
    provider = str(getattr(spend, "provider", ""))
    hit = bool(getattr(metrics, "was_cache_hit", False))
    worth = 0 if book is None else Spend(**dims, provider=provider).micros(book)
    params: dict[str, object] = dict(dims)
    params.update(
        id=row_id,
        provider=provider,
        micros=int(getattr(metrics, "micros", 0)) if book is None else (0 if hit else worth),
        was_cache_hit=int(hit),
        would_have_been_micros=worth if hit else 0,
        outcome=str(result.outcome),
    )
    return (
        Statement(
            participant="spend_row",
            name="route_spend",
            sql=SPEND_SQL,
            params=MappingProxyType(params),
        ),
    )
