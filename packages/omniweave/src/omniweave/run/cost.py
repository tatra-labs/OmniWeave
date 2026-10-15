"""What a corpus spent, by driver: `ow cost --by driver`'s rows, read off the ledger. **D838.**

15-observability.md section 5.4 prints the verb and its table:

    driver  class  units  calls  tokens_in  tokens_out  gpu_ms  micros  hits  saved

with a `TOTAL` that is the sum of the `micros` column, a `saved` line whose ratio is `saved /
TOTAL`, and a reconcile line, `Σ route_spend.micros == manifest.cost.billed_micros`.
08-runtime.md:2340-2344 adds the `op.*` rows: `manifest.cost.op_micros` is `Σ work.cost_micros`
over them, and `ow cost --by driver` shows them *"so they are visible rather than merely recorded"*.

This module reads; `omniweave.surface.cost` prints.

## Rulings

1. **A routed row's numbers are `route_spend`'s, joined to `route_decision` directly.** The
   `spend_attribution` view joins through `route_unit_decision`, and one decision serves several
   unit rows (one blob in three folders is one decision and three rows), so summing over the view
   repeats spend rows. `units` alone reads `route_unit_decision`: the distinct `(unit_uri,
   unit_part)` pairs a driver's decisions cover.
2. **The class is `route_decision.cost_class`, frozen at decision time** (05's DDL comment): the
   live catalogue would re-label history after a card upgrade.
3. **Every decision is a row, spend or not.** A `free` driver writes no spend row and still parsed
   units, which is why the plan's sample prints `parse.pdf.pdfium  free  18,402 ... 0`. A decision
   whose `driver` is `''` (a gate refusal, no driver ran) is the row `(no driver)`.
4. **An `op.*` row is named for its operator,** as the plan's sample prints `op.resolve`, rather
   than folded into one synthetic `op` row: one row per operator says which one spent. Its numbers
   are `work`'s: `units` is the distinct units it ran over, and `micros` is `Σ cost_micros`.
5. **A run is its generation.** `--run R` reads `run.generation` and keeps the decisions of that
   generation, and the `op.*` work rows claimed in it (`claimed_gen`). `route_spend` has no
   `run_id`, so this inherits D158's limit: a resumed run's re-attempts join to the generation
   that first decided them. The reconcile line uses the same join, so it agrees with itself.
6. **Rows sort by `micros` descending, then by driver.** What cost the most is read first, and
   ties are stable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "NO_DRIVER",
    "DriverCost",
    "RunWindow",
    "by_driver",
    "manifest_billed",
    "run_window",
]

NO_DRIVER: Final = "(no driver)"
"""Ruling 3: how a decision with `driver = ''` (05: *"'' == no driver ran"*) is labelled."""

_SPEND_SQL: Final = """
SELECT d.driver, d.cost_class,
       COALESCE(SUM(s.calls), 0), COALESCE(SUM(s.tokens_in), 0),
       COALESCE(SUM(s.tokens_out), 0), COALESCE(SUM(s.gpu_ms), 0),
       COALESCE(SUM(s.micros), 0), COALESCE(SUM(s.was_cache_hit), 0),
       COALESCE(SUM(s.would_have_been_micros), 0)
  FROM route_decision d
  LEFT JOIN route_spend s ON s.decision_id = d.decision_id
 WHERE :generation IS NULL OR d.generation = :generation
 GROUP BY d.driver, d.cost_class
"""

_UNITS_SQL: Final = """
SELECT driver, cost_class, COUNT(*) FROM (
  SELECT DISTINCT d.driver, d.cost_class, u.unit_uri, u.unit_part
    FROM route_unit_decision u
    JOIN route_decision d ON d.decision_id = u.decision_id
   WHERE :generation IS NULL OR d.generation = :generation)
 GROUP BY driver, cost_class
"""

_OP_SQL: Final = """
SELECT operator, cost_class, COUNT(DISTINCT unit_uri || char(0) || unit_part),
       COALESCE(SUM(cost_micros), 0)
  FROM work
 WHERE operator LIKE 'op.%' AND (:generation IS NULL OR claimed_gen = :generation)
 GROUP BY operator, cost_class
"""

_RUN_SQL: Final = "SELECT generation, manifest_path FROM run WHERE run_id = :run_id"


@dataclass(frozen=True, slots=True)
class DriverCost:
    """One `--by driver` row: 15 section 5.4's ten columns."""

    driver: str
    cost_class: str
    units: int
    calls: int
    tokens_in: int
    tokens_out: int
    gpu_ms: int
    micros: int
    hits: int
    saved: int


@dataclass(frozen=True, slots=True)
class RunWindow:
    """Ruling 5: a run's generation, and where its manifest is (`''` when none was written)."""

    run_id: str
    generation: int
    manifest_path: str


def by_driver(connection: Any, *, generation: int | None = None) -> tuple[DriverCost, ...]:
    """Rulings 1-4 and 6: every driver's and every `op.*` operator's row, costliest first.

    `connection` is the store's read-only connection; its type is not named here, because
    `sqlite3` is the store's alone.
    """
    params = {"generation": generation}
    units = {
        (str(driver), str(cost_class)): int(count)
        for driver, cost_class, count in connection.execute(_UNITS_SQL, params)
    }
    rows = [
        DriverCost(
            driver=str(driver) or NO_DRIVER,
            cost_class=str(cost_class),
            units=units.get((str(driver), str(cost_class)), 0),
            calls=int(calls),
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            gpu_ms=int(gpu_ms),
            micros=int(micros),
            hits=int(hits),
            saved=int(saved),
        )
        for driver, cost_class, calls, tokens_in, tokens_out, gpu_ms, micros, hits, saved in (
            connection.execute(_SPEND_SQL, params)
        )
    ]
    rows.extend(
        DriverCost(str(operator), str(cost_class), int(count), 0, 0, 0, 0, int(micros), 0, 0)
        for operator, cost_class, count, micros in connection.execute(_OP_SQL, params)
    )
    return _ordered(rows)


def run_window(connection: Any, run_id: str) -> RunWindow | None:
    """Ruling 5: the run's generation and manifest path, or `None` for a run the store lacks."""
    row = connection.execute(_RUN_SQL, {"run_id": run_id}).fetchone()
    return None if row is None else RunWindow(run_id, int(row[0]), str(row[1]))


def manifest_billed(path: str) -> int | None:
    """`manifest.cost.billed_micros` from a run's manifest JSON, or `None` when it cannot be read.

    15:44 makes the manifest the run's figures, written by the run; `ow cost` reads it back to
    reconcile against the ledger, and an absent or unreadable one is said, never guessed. `''`,
    the path a run with no `output_root` records, reads as the working directory and fails as
    any unreadable file does.
    """
    try:
        document = json.loads(Path(path).read_bytes())
        value = document["cost"]["billed_micros"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ordered(rows: Iterable[DriverCost]) -> tuple[DriverCost, ...]:
    return tuple(sorted(rows, key=lambda row: (-row.micros, row.driver, row.cost_class)))
