"""Q-G18, flake control: above 2% over 30 days a test is quarantined, visibly. **D836.**

13-quality.md section 2.7 (:273-298): *"`eval_flake` records `(test_id, day, runs, fails,
reran_green)`. Above 2% failure over a rolling 30-day window ... a test is quarantined to
`informational` (`Q-G18`)."* Quarantine is not a mode, because there is no `--warn-only` anywhere.
It is a byte-diff-gated register, `eval/quarantine.toml`, where *"`expires` is at most 60 days
after `since`"*. Section 15 (:2002): *"`eval_flake` over a 30-day window; > 2% quarantines into
the byte-diff-gated register with an expiry"*. 16-roadmap.md:983 lists `uv run
tools/gate_flake.py --window 30d` among P10's exit criteria.

- `window()` rolls `eval_flake` rows up per test over the days that count.
- `flaky()` names the tests above the line.
- `register()` reads `eval/quarantine.toml`.
- `judge()` is the gate.

`tools/gate_flake.py` drives them.

## Rulings

1. **The window is the `days` days ending today, inclusive** (`today - days + 1` .. `today`). A
   row with a day outside it, or one that is not `YYYY-MM-DD`, does not count. The clock is an
   argument: library code reads no wall clock.
2. **Flaky is `fails / runs > 0.02` over the window, strictly.** 12 failures in 600 runs is the
   plan's own example of the line, and it is not over it. A test with no runs in the window is
   not flaky; it is unmeasured.
3. **A re-run that went green is still a failure.** `reran_green` is recorded and printed, and
   it never lowers `fails`. A test that passes on retry is the flake this gate exists to see.
4. **The register is `[gate]` plus `[[quarantined]]` rows,** each with `test_id`, `since`,
   `expires`, `owner` and `reason` (`issue` optional). It is refused as a whole when a row lacks a
   key or carries an unknown one, when a date is unreadable, when `expires` is not after `since`
   or is more than 60 days after it, or when one test is quarantined twice. A register that cannot
   be trusted gates nothing.
5. **`judge()` names three things:**
   - a flaky test with no quarantine row: *"quarantine it to informational"*;
   - a row whose `expires` is today or earlier, read as Q-G17 reads `review_by`: *"back to its
     tier, or delete it with the reason"*;
   - a quarantined test no longer flaky over the window, which is a note and never a failure:
     it may return to its tier.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import QualityError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_core.store.oweval import Flake

__all__ = [
    "MAX_QUARANTINE_DAYS",
    "QUARANTINE_ABOVE",
    "WINDOW_DAYS",
    "Finding",
    "Quarantined",
    "Window",
    "flaky",
    "judge",
    "register",
    "window",
]

QUARANTINE_ABOVE: Final = 0.02
"""13:274: *"Above 2% failure"*."""
WINDOW_DAYS: Final = 30
"""13:274: *"a rolling 30-day window"*."""
MAX_QUARANTINE_DAYS: Final = 60
"""13:295: *"`expires` is at most 60 days after `since`"*."""

_KEYS: Final = frozenset({"test_id", "since", "expires", "owner", "reason", "issue"})
_REQUIRED: Final = ("test_id", "since", "expires", "owner", "reason")
_FIX: Final = "mend eval/quarantine.toml's row"


@dataclass(frozen=True, slots=True)
class Window:
    """One test's runs, fails and green re-runs over the window."""

    test_id: str
    runs: int
    fails: int
    reran_green: int

    @property
    def rate(self) -> float:
        return self.fails / self.runs if self.runs else 0.0


@dataclass(frozen=True, slots=True)
class Quarantined:
    """One `[[quarantined]]` row."""

    test_id: str
    since: dt.date
    expires: dt.date
    owner: str
    reason: str
    issue: str


@dataclass(frozen=True, slots=True)
class Finding:
    """What `judge()` names: `failing` findings fail the gate, the rest are notes."""

    test_id: str
    detail: str
    failing: bool


def window(rows: Iterable[Flake], today: dt.date, days: int = WINDOW_DAYS) -> dict[str, Window]:
    """Ruling 1: each test's rows over the `days` days ending `today`."""
    first = today - dt.timedelta(days=days - 1)
    totals: dict[str, list[int]] = {}
    for row in rows:
        day = _date(row.day)
        if day is None or not first <= day <= today:
            continue
        total = totals.setdefault(row.test_id, [0, 0, 0])
        total[0] += row.runs
        total[1] += row.fails
        total[2] += row.reran_green
    return {
        test_id: Window(test_id, runs, fails, green)
        for test_id, (runs, fails, green) in sorted(totals.items())
    }


def flaky(windows: Mapping[str, Window]) -> tuple[Window, ...]:
    """Ruling 2: strictly above the line, with at least one run."""
    return tuple(w for w in windows.values() if w.runs and w.rate > QUARANTINE_ABOVE)


def register(doc: Mapping[str, Any]) -> tuple[Quarantined, ...]:
    """Ruling 4: the `[[quarantined]]` rows, or `QualityError` naming the first bad one."""
    rows = doc.get("quarantined", [])
    if not isinstance(rows, list):
        raise _error("`quarantined` is not an array of tables")
    out: list[Quarantined] = []
    seen: set[str] = set()
    for at, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise _error(f"[[quarantined]] #{at} is not a table")
        missing = [key for key in _REQUIRED if not isinstance(row.get(key), str) or not row[key]]
        unknown = sorted(set(row) - _KEYS)
        if missing or unknown:
            raise _error(f"[[quarantined]] #{at}: missing {missing}, unknown {unknown}")
        since, expires = _date(row["since"]), _date(row["expires"])
        if since is None or expires is None:
            raise _error(f"[[quarantined]] #{at}: since and expires must be YYYY-MM-DD")
        if not since < expires <= since + dt.timedelta(days=MAX_QUARANTINE_DAYS):
            raise _error(
                f"[[quarantined]] #{at}: expires {expires} must fall after since {since} and "
                f"within {MAX_QUARANTINE_DAYS} days of it"
            )
        if row["test_id"] in seen:
            raise _error(f"{row['test_id']} is quarantined twice")
        seen.add(row["test_id"])
        out.append(
            Quarantined(
                row["test_id"], since, expires, row["owner"], row["reason"], row.get("issue", "")
            )
        )
    return tuple(out)


def judge(
    windows: Mapping[str, Window], quarantined: Iterable[Quarantined], today: dt.date
) -> tuple[Finding, ...]:
    """Ruling 5, in test-id order."""
    rows = {row.test_id: row for row in quarantined}
    out: list[Finding] = []
    for test in flaky(windows):
        if test.test_id not in rows:
            out.append(
                Finding(
                    test.test_id,
                    f"{test.fails} of {test.runs} runs failed ({test.rate:.1%}, "
                    f"{test.reran_green} green on re-run); quarantine it to informational",
                    failing=True,
                )
            )
    for test_id, row in sorted(rows.items()):
        if row.expires <= today:
            out.append(
                Finding(
                    test_id,
                    f"quarantine expired {row.expires}; back to its tier, or delete it with the "
                    "reason",
                    failing=True,
                )
            )
        elif test_id in windows and windows[test_id] not in flaky(windows):
            out.append(
                Finding(
                    test_id, "no longer flaky over the window; it may return to its tier", False
                )
            )
    return tuple(sorted(out, key=lambda one: (one.test_id, not one.failing)))


def _date(value: object) -> dt.date | None:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str) or len(value) != len("YYYY-MM-DD"):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _error(message: str) -> QualityError:
    return QualityError(f"Q-G18: eval/quarantine.toml: {message}", fix=_FIX)
