"""Counters: `eval/counters.toml`, read and checked, and the exact-or-ratchet judgement. **D823.**

13-quality.md section 2.8: *"Time is the **last** signal, not the first. A silent re-render, a
re-billed free operator and a 100% cache miss all leave a clock untouched"*, so `eval/counters.toml`
is evaluated before `eval/perf.toml`. *"Counters are `exact` by default (±1 fails) or `ratchet`
with a tolerance"*, and every row declares a `source` over `{manifest, route_spend,
driver_observation, ci}` (ADR-11 decision 8). 16-roadmap.md W10.4 names the file. This module reads
it and judges one counter against its baseline; harvesting a run's counts from its three sources
is Q-G5's, which arrives with the run manifest's harvest.

## Rulings

1. **The file's schema is closed.** A row is `id`, `class`, `source`, `tolerance` where `class` is
   `ratchet`, and an optional `note`; an unknown key, a second row for one id, a source outside the
   four, an exact row with a tolerance and a ratchet row without one are each refused. A
   `[gate]` table names an owner and a `review_by`, as every gate row does (Q-G17).
2. **`exact` fails any delta, in either direction.** A counter that fell by one is as unexplained
   as one that rose: a cache hit that became a miss moves both `cache_hits` and `cache_misses`.
3. **`ratchet` fails a rise past `tolerance` and passes a fall.** A fall is the new floor; the
   ratchet only turns one way. The comparison is `current <= baseline * (1 + tolerance)`, so a
   baseline of zero admits zero and nothing else.
4. **A row's `id` names one counter or a `name.*` family**, and a counter falls under the first
   row that matches it. `ci.job_seconds.*` is the file's one family, one counter per CI job.
5. **`ci` rows never reach `eval_counter`.** `run_sourced()` is the three classes Q-G5 compares,
   and a `ci` row is read for shape and compared against nothing (13:1989), because `eval_counter`
   keys on a `run_id` a CI job does not have.

Specified in 13-quality.md sections 2.8 and 14, ADR-11 decision 8, 11-repo-layout.md section 6.2,
and the charter's `eval/counters.toml`.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, NoReturn, get_args

from omniweave_core.errors import QualityError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CLASSES",
    "RUN_SOURCES",
    "SOURCES",
    "CounterRow",
    "Counters",
    "judge",
    "load_counters",
]

CounterClass = Literal["exact", "ratchet"]
Source = Literal["manifest", "route_spend", "driver_observation", "ci"]
Judgement = Literal["pass", "fail"]

CLASSES: Final[tuple[str, ...]] = get_args(CounterClass)
SOURCES: Final[tuple[str, ...]] = get_args(Source)
RUN_SOURCES: Final = frozenset(SOURCES) - {"ci"}
"""The three a run harvests, and the only three Q-G5 compares (ruling 5)."""

_KEYS: Final = frozenset({"id", "class", "tolerance", "source", "note"})
_FIX: Final = "fix eval/counters.toml: the row schema is in its header"


@dataclass(frozen=True, slots=True)
class CounterRow:
    """One `[[counter]]` row, checked (ruling 1)."""

    id: str
    cls: CounterClass
    source: Source
    tolerance: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.cls not in CLASSES:
            _refuse(f"counter {self.id!r}: class {self.cls!r} is not exact or ratchet")
        if self.source not in SOURCES:
            _refuse(f"counter {self.id!r}: source {self.source!r} is not one of {SOURCES}")
        if self.cls == "exact" and self.tolerance is not None:
            _refuse(f"counter {self.id!r} is exact and carries a tolerance")
        if self.cls == "ratchet" and not (self.tolerance is not None and 0 < self.tolerance < 1):
            _refuse(f"counter {self.id!r} is a ratchet and needs a tolerance in (0, 1)")


@dataclass(frozen=True, slots=True)
class Counters:
    """The file: its gate's owner and review date, and its rows in file order."""

    owner: str
    review_by: str
    rows: tuple[CounterRow, ...]

    def row_for(self, counter: str) -> CounterRow | None:
        """The first row naming `counter` or a family it falls in (ruling 4)."""
        for row in self.rows:
            if fnmatch.fnmatchcase(counter, row.id):
                return row
        return None

    def run_sourced(self) -> tuple[CounterRow, ...]:
        """Ruling 5: the rows a run harvests, `ci` excluded."""
        return tuple(row for row in self.rows if row.source in RUN_SOURCES)


def load_counters(path: Path) -> Counters:
    """Read `eval/counters.toml` and refuse anything outside its schema (ruling 1)."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    gate = raw.get("gate", {})
    if not gate.get("owner") or not gate.get("review_by"):
        _refuse("eval/counters.toml has no [gate] owner and review_by")
    rows = []
    for item in raw.get("counter", []):
        unknown = sorted(set(item) - _KEYS)
        if unknown:
            _refuse(f"counter {item.get('id')!r} carries unknown keys {unknown}")
        tolerance = item.get("tolerance")
        rows.append(
            CounterRow(
                id=str(item["id"]),
                cls=item["class"],
                source=item["source"],
                tolerance=None if tolerance is None else float(tolerance),
                note=str(item.get("note", "")),
            )
        )
    ids = [row.id for row in rows]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        _refuse(f"eval/counters.toml repeats {repeated}")
    return Counters(owner=str(gate["owner"]), review_by=str(gate["review_by"]), rows=tuple(rows))


def judge(row: CounterRow, baseline: int, current: int) -> Judgement:
    """Rulings 2 and 3: `exact` fails any delta, `ratchet` a rise past its tolerance."""
    if baseline < 0 or current < 0:
        _refuse(f"counter {row.id!r}: a count is not negative ({baseline} -> {current})")
    if row.cls == "exact":
        return "pass" if current == baseline else "fail"
    assert row.tolerance is not None  # CounterRow refuses a ratchet without one
    return "pass" if current <= baseline * (1 + row.tolerance) else "fail"


def _refuse(message: str) -> NoReturn:
    raise QualityError(message, fix=_FIX)
