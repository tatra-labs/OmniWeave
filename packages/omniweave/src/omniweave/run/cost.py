"""What a corpus spent, sliced: `ow cost --by <slicing>`'s rows, read off the ledger. D838, D839.

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
   unit_part)` pairs a row's decisions cover.
2. **The class is `route_decision.cost_class`, frozen at decision time** (05's DDL comment): the
   live catalogue would re-label history after a card upgrade. Every slicing keeps it, so a row is
   always `(key, class)`.
3. **Every decision is a row, spend or not.** A `free` driver writes no spend row and still parsed
   units, which is why the plan's sample prints `parse.pdf.pdfium  free  18,402 ... 0`. An empty
   key has a name: a decision with `driver = ''` (a gate refusal) is `(no driver)`, and a provider
   of `''` is `local`, the ledger's own convention for it.
4. **`op.*` rows.** Under `--by driver` each is named for its operator, as the plan's sample prints
   `op.resolve`. Under `--by day` they fall on the day of their last attempt. Under every other
   slicing they are one row keyed `op`, 08:2343's synthetic driver row: an operator has no
   provider, lane, rung or slice. Their figures are `work`'s, the units they ran over and
   `Σ cost_micros`.
5. **A window is a generation, a time, or the whole ledger.**
   - `--run R` keeps run R's generation: its decisions, and the `op.*` rows claimed in it
     (`claimed_gen`). `route_spend` has no `run_id`, so this inherits D158's limit, and the
     reconcile line uses the same join, so it agrees with itself.
   - `--since` keeps decisions whose `decided_at` (wall ms) is at or after the cutoff, and
     `op.*` rows whose `last_attempt_at` is.
6. **The slicings are `SLICINGS`' keys, each a fixed SQL expression, and never a caller's text.**
   `day` is the UTC date of `decided_at`. `document` is not one: one decision serves several
   documents, so a per-document bill needs section 5.3's apportionment, and a row per document
   would sum to more than the bill.
7. **Rows sort by `micros` descending, then by key and class.** What cost the most is read first,
   and ties are stable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "NO_DRIVER",
    "SINCE_UNITS",
    "SLICINGS",
    "RowCost",
    "RunWindow",
    "by_key",
    "earliest_decision",
    "manifest_billed",
    "run_window",
    "since_ms",
]

NO_DRIVER: Final = "(no driver)"
"""Ruling 3: a decision with `driver = ''` (05: *"'' == no driver ran"*)."""

SLICINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "driver": "d.driver",
        "provider": "COALESCE(s.provider, '')",
        "lane": "d.lane",
        "rung": "CAST(d.rung AS TEXT)",
        "slice": "d.slice_key",
        "day": "date(d.decided_at / 1000, 'unixepoch')",
    }
)
"""Ruling 6: each served `--by`, and the expression its rows group on."""

_OP_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {"driver": "operator", "day": "date(last_attempt_at / 1000, 'unixepoch')"}
)
"""Ruling 4: what an `op.*` row is keyed by; every other slicing keys it `'op'`."""

_EMPTY: Final[Mapping[str, str]] = MappingProxyType({"driver": NO_DRIVER, "provider": "local"})
"""Ruling 3: an empty key's name; any other slicing's empty key is `(none)`."""

SINCE_UNITS: Final[Mapping[str, int]] = MappingProxyType(
    {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
)
"""`--since <dur>`: a positive integer and one of these units, in milliseconds."""

_SINCE: Final = re.compile(r"([1-9][0-9]*)([mhd])")

_WINDOW: Final = (
    "(:generation IS NULL OR d.generation = :generation)"
    " AND (:since_ms IS NULL OR d.decided_at >= :since_ms)"
)

_RUN_SQL: Final = "SELECT generation, manifest_path FROM run WHERE run_id = :run_id"
_EARLIEST_SQL: Final = "SELECT MIN(decided_at) FROM route_decision"


@dataclass(frozen=True, slots=True)
class RowCost:
    """One row: 15 section 5.4's ten columns, keyed by whatever the slicing is."""

    key: str
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


def since_ms(text: str) -> int:
    """`--since`'s duration in milliseconds. `ValueError` for anything but `<n>m|h|d`."""
    match = _SINCE.fullmatch(text)
    if match is None:
        raise ValueError(f"{text!r} is not a duration: a positive integer and m, h or d, e.g. 7d")
    return int(match.group(1)) * SINCE_UNITS[match.group(2)]


def by_key(
    connection: Any,
    by: str,
    *,
    generation: int | None = None,
    cutoff_ms: int | None = None,
) -> tuple[RowCost, ...]:
    """Rulings 1-7: every row of the slicing `by` over the window, costliest first.

    `connection` is the store's read-only connection; its type is not named here, because
    `sqlite3` is the store's alone. `cutoff_ms` is the wall-clock millisecond a `--since` window
    starts at, computed by the caller from its injected clock.
    """
    key = SLICINGS[by]
    params = {"generation": generation, "since_ms": cutoff_ms}
    spend_sql = (
        f"SELECT {key}, d.cost_class, COALESCE(SUM(s.calls), 0), COALESCE(SUM(s.tokens_in), 0),"  # noqa: S608 -- `key` is a SLICINGS value, never input
        " COALESCE(SUM(s.tokens_out), 0), COALESCE(SUM(s.gpu_ms), 0), COALESCE(SUM(s.micros), 0),"
        " COALESCE(SUM(s.was_cache_hit), 0), COALESCE(SUM(s.would_have_been_micros), 0)"
        " FROM route_decision d LEFT JOIN route_spend s ON s.decision_id = d.decision_id"
        f" WHERE {_WINDOW} GROUP BY 1, 2"
    )
    units_sql = (
        "SELECT k, cost_class, COUNT(*) FROM ("  # noqa: S608 -- as above
        f" SELECT DISTINCT {key} AS k, d.cost_class, u.unit_uri, u.unit_part"
        " FROM route_unit_decision u JOIN route_decision d ON d.decision_id = u.decision_id"
        " LEFT JOIN route_spend s ON s.decision_id = d.decision_id"
        f" WHERE {_WINDOW}) GROUP BY 1, 2"
    )
    op_key = _OP_KEYS.get(by, "'op'")
    op_sql = (
        f"SELECT {op_key}, cost_class,"  # noqa: S608 -- as above
        " COUNT(DISTINCT unit_uri || char(0) || unit_part), COALESCE(SUM(cost_micros), 0)"
        " FROM work WHERE operator LIKE 'op.%'"
        " AND (:generation IS NULL OR claimed_gen = :generation)"
        " AND (:since_ms IS NULL OR last_attempt_at >= :since_ms)"
        " GROUP BY 1, 2"
    )
    units = {
        (_name(by, raw), str(cost_class)): int(count)
        for raw, cost_class, count in connection.execute(units_sql, params)
    }
    rows = [
        RowCost(
            key=_name(by, raw),
            cost_class=str(cost_class),
            units=units.get((_name(by, raw), str(cost_class)), 0),
            calls=int(calls),
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            gpu_ms=int(gpu_ms),
            micros=int(micros),
            hits=int(hits),
            saved=int(saved),
        )
        for raw, cost_class, calls, tokens_in, tokens_out, gpu_ms, micros, hits, saved in (
            connection.execute(spend_sql, params)
        )
    ]
    rows.extend(
        RowCost(_name(by, raw), str(cost_class), int(count), 0, 0, 0, 0, int(micros), 0, 0)
        for raw, cost_class, count, micros in connection.execute(op_sql, params)
    )
    return _ordered(_merged(rows))


def run_window(connection: Any, run_id: str) -> RunWindow | None:
    """Ruling 5: the run's generation and manifest path, or `None` for a run the store lacks."""
    row = connection.execute(_RUN_SQL, {"run_id": run_id}).fetchone()
    return None if row is None else RunWindow(run_id, int(row[0]), str(row[1]))


def earliest_decision(connection: Any) -> int | None:
    """The oldest `decided_at` the ledger holds, so a `--since` reaching past it can say so
    (15 section 5.4: *"a bill that silently starts where the sweep stopped is a bill with a
    hole"*). `None` for an empty ledger."""
    row = connection.execute(_EARLIEST_SQL).fetchone()
    return None if row is None or row[0] is None else int(row[0])


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


def _name(by: str, raw: object) -> str:
    text = "" if raw is None else str(raw)
    return text or _EMPTY.get(by, "(none)")


def _merged(rows: Iterable[RowCost]) -> list[RowCost]:
    """Rows sharing `(key, class)` summed into one: under `--by day` a routed row and an `op.*`
    row can fall on the same day and class, and a table with that pair twice is two answers."""
    merged: dict[tuple[str, str], RowCost] = {}
    for row in rows:
        seen = merged.get((row.key, row.cost_class))
        merged[(row.key, row.cost_class)] = (
            row
            if seen is None
            else RowCost(
                row.key,
                row.cost_class,
                seen.units + row.units,
                seen.calls + row.calls,
                seen.tokens_in + row.tokens_in,
                seen.tokens_out + row.tokens_out,
                seen.gpu_ms + row.gpu_ms,
                seen.micros + row.micros,
                seen.hits + row.hits,
                seen.saved + row.saved,
            )
        )
    return list(merged.values())


def _ordered(rows: Iterable[RowCost]) -> tuple[RowCost, ...]:
    return tuple(sorted(rows, key=lambda row: (-row.micros, row.key, row.cost_class)))
