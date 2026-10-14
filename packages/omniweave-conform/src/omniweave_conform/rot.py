"""Q-G27, metric rot: no metric published ungated for more than two corpus releases. **D829.**

13-quality.md section 8.3 (:1143-1146): *"`Q-G27` bounds that state: a metric published ungated
for more than **two corpus releases** either gains a gate row or is removed from the scoreboard.
An eternally ungated metric is decoration. A row that names a future version --
`source_reread_rate`'s `budget_max = 0.25` from v1.0 -- satisfies the clock, because the
commitment is dated and reviewable rather than absent."* Section 13.1 (:103) names its inputs,
`eval/results/**.json` plus `eval/gates.toml`, and :1832 what it stops: *"a board full of numbers
nobody has committed to, which is indistinguishable from a board full of numbers"*. 16-roadmap.md
W10.11 is the work item.

`gated()` reads the register, `published()` reads the tree `omniweave_conform.scoreboard` writes,
and `rot()` is the gate. `tools/gate_metric_rot.py` drives them.

## Rulings

1. **A metric is gated when any `[[gate]]` row of `eval/gates.toml` names it**, whatever the
   row's slice, class or `active_from`. A dated future row is a commitment and satisfies the clock
   (:1145). Whether a row is past its `review_by` is Q-G17's question, not this gate's.
2. **The clock counts the releases a metric was published at, one corpus at a time.** A release
   is a row's `(corpus_id, corpus_version)`, so a metric over two corpora runs two clocks. A
   release that did not publish the metric does not advance its clock: the tree is the only
   record of what was published, and no release calendar is committed to count against.
3. **Every published row counts, whatever its standing.** An UNKNOWN or WITHHELD row is on the
   board (section 11.3) and is as much decoration as a number nobody gated.
4. **More than `RELEASES` fails**, so a metric's third release is the first that rots. Two
   releases are the grace a new metric has to earn a gate or leave the board.
5. **A tree or register that cannot be read is refused, not passed.** A file that is not a JSON
   list of rows, each naming a string `metric`, `corpus_id` and `corpus_version`, or a `[[gate]]`
   row with no string `metric`, raises `QualityError`. A gate that skips what it cannot parse
   passes exactly the board it exists to fail.

Specified in 13-quality.md sections 8.3, 13.1 and 15, and 16-roadmap.md W10.11.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import QualityError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FIX", "RELEASES", "Clock", "gated", "published", "rot"]

RELEASES: Final = 2
"""The releases an ungated metric may be published at (:1143). The third fails."""

_KEYS: Final = ("metric", "corpus_id", "corpus_version")
FIX: Final = (
    "add a [[gate]] row for the metric to eval/gates.toml (a dated active_from counts), "
    "or stop publishing it"
)
"""What a rotten clock's report tells its reader to do: :1143's two ways out."""

_UNREADABLE: Final = "re-export the tree with ow eval publish, or mend eval/gates.toml's row"


@dataclass(frozen=True, slots=True)
class Clock:
    """One ungated metric's clock on one corpus: the releases it was published at, sorted."""

    metric: str
    corpus_id: str
    versions: tuple[str, ...]

    @property
    def rotten(self) -> bool:
        """Ruling 4."""
        return len(self.versions) > RELEASES

    def line(self) -> str:
        """The report's line for this clock."""
        return (
            f"{self.metric} on {self.corpus_id}: {len(self.versions)} of {RELEASES} ungated "
            f"release(s) ({', '.join(self.versions)})"
        )


def gated(register: Mapping[str, Any]) -> frozenset[str]:
    """Every metric a `[[gate]]` row names (ruling 1)."""
    rows = register.get("gate", [])
    if not isinstance(rows, list):
        raise _error("eval/gates.toml: `gate` is not an array of tables")
    names = set()
    for at, row in enumerate(rows, start=1):
        metric = row.get("metric") if isinstance(row, dict) else None
        if not _named(metric):
            raise _error(f"eval/gates.toml: [[gate]] #{at} names no metric")
        names.add(metric)
    return frozenset(names)


def published(files: Mapping[str, str]) -> dict[tuple[str, str], frozenset[str]]:
    """`(metric, corpus_id) -> corpus versions` over a scoreboard tree (rulings 2, 3 and 5)."""
    seen: dict[tuple[str, str], set[str]] = {}
    for path, text in sorted(files.items()):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _error(f"{path}: not JSON ({exc.msg}, line {exc.lineno})") from exc
        if not isinstance(rows, list):
            raise _error(f"{path}: not a list of rows")
        for at, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or not all(_named(row.get(key)) for key in _KEYS):
                raise _error(f"{path}: row {at} does not name its {', '.join(_KEYS)}")
            seen.setdefault((row["metric"], row["corpus_id"]), set()).add(row["corpus_version"])
    return {key: frozenset(versions) for key, versions in seen.items()}


def rot(files: Mapping[str, str], register: Mapping[str, Any]) -> tuple[Clock, ...]:
    """Every ungated metric's clock, in `(metric, corpus)` order. Q-G27 fails on a `rotten` one."""
    names = gated(register)
    return tuple(
        Clock(metric, corpus_id, tuple(sorted(versions)))
        for (metric, corpus_id), versions in sorted(published(files).items())
        if metric not in names
    )


def _named(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _error(message: str) -> QualityError:
    return QualityError(f"Q-G27: {message}", fix=_UNREADABLE)
