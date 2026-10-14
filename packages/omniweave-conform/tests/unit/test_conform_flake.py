"""`omniweave_conform.flake`: Q-G18's window, line and register. D836."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from omniweave_conform.flake import (
    MAX_QUARANTINE_DAYS,
    QUARANTINE_ABOVE,
    WINDOW_DAYS,
    Quarantined,
    Window,
    flaky,
    judge,
    register,
    window,
)
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Flake

TODAY = dt.date(2026, 10, 14)


def _row(test: str, day: str, runs: int, fails: int, green: int = 0) -> Flake:
    return Flake(test_id=test, day=day, runs=runs, fails=fails, reran_green=green)


def test_the_constants_are_the_plans() -> None:
    assert (QUARANTINE_ABOVE, WINDOW_DAYS, MAX_QUARANTINE_DAYS) == (0.02, 30, 60)


def test_the_window_is_the_days_ending_today_inclusive() -> None:
    rows = [
        _row("t", "2026-10-14", 10, 1),
        _row("t", "2026-09-15", 10, 1),
        _row("t", "2026-09-14", 10, 9),
        _row("t", "2026-10-15", 10, 9),
        _row("t", "20261001", 10, 9),
        _row("t", "2026-02-30", 10, 9),
    ]
    assert window(rows, TODAY) == {"t": Window("t", runs=20, fails=2, reran_green=0)}
    assert window(rows, TODAY, days=1) == {"t": Window("t", runs=10, fails=1, reran_green=0)}


def test_flaky_is_strictly_above_two_percent() -> None:
    windows = window(
        [
            _row("at_the_line", "2026-10-01", 600, 12),
            _row("over", "2026-10-01", 600, 13),
            _row("idle", "2026-10-01", 0, 0),
        ],
        TODAY,
    )
    assert [w.test_id for w in flaky(windows)] == ["over"]
    assert windows["idle"].rate == 0.0


def test_a_green_rerun_is_still_a_failure() -> None:
    (only,) = flaky(window([_row("t", "2026-10-01", 40, 2, green=2)], TODAY))
    assert (only.fails, only.reran_green) == (2, 2)


_GOOD: dict[str, Any] = {
    "test_id": "tests/unit/test_a.py::test_b",
    "since": "2026-09-01",
    "expires": "2026-10-31",
    "owner": "quality",
    "reason": "one run in forty",
}


def test_a_register_row_reads_and_issue_is_optional() -> None:
    (row,) = register({"quarantined": [_GOOD]})
    assert row == Quarantined(
        "tests/unit/test_a.py::test_b",
        dt.date(2026, 9, 1),
        dt.date(2026, 10, 31),
        "quality",
        "one run in forty",
        "",
    )
    assert register({"quarantined": [{**_GOOD, "issue": "#812"}]})[0].issue == "#812"
    assert register({}) == ()


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ({"quarantined": {"test_id": "x"}}, "not an array of tables"),
        ({"quarantined": ["x"]}, r"#1 is not a table"),
        (
            {"quarantined": [{k: v for k, v in _GOOD.items() if k != "reason"}]},
            r"missing \['reason'\]",
        ),
        ({"quarantined": [{**_GOOD, "owner": ""}]}, r"missing \['owner'\]"),
        ({"quarantined": [{**_GOOD, "until": "x"}]}, r"unknown \['until'\]"),
        ({"quarantined": [{**_GOOD, "since": "2026-9-1"}]}, "must be YYYY-MM-DD"),
        ({"quarantined": [{**_GOOD, "expires": "2026-09-01"}]}, "must fall after since"),
        ({"quarantined": [{**_GOOD, "expires": "2026-11-01"}]}, "within 60 days"),
        ({"quarantined": [_GOOD, _GOOD]}, "quarantined twice"),
    ],
)
def test_a_register_that_cannot_be_trusted_is_refused(rows: dict[str, Any], match: str) -> None:
    with pytest.raises(QualityError, match=match):
        register(rows)


def test_sixty_days_exactly_is_allowed() -> None:
    assert register({"quarantined": [{**_GOOD, "expires": "2026-10-31"}]})[0].expires == dt.date(
        2026, 10, 31
    )


def test_judge_names_the_unquarantined_the_expired_and_the_recovered() -> None:
    windows = window(
        [
            _row("a_flaky", "2026-10-10", 50, 5, green=4),
            _row("b_quarantined_flaky", "2026-10-10", 50, 5),
            _row("c_recovered", "2026-10-10", 50, 0),
        ],
        TODAY,
    )
    rows = register(
        {
            "quarantined": [
                {**_GOOD, "test_id": "b_quarantined_flaky"},
                {**_GOOD, "test_id": "c_recovered"},
                {**_GOOD, "test_id": "d_expired", "since": "2026-08-15", "expires": "2026-10-14"},
            ]
        }
    )
    found = judge(windows, rows, TODAY)
    assert [(f.test_id, f.failing, f.detail) for f in found] == [
        (
            "a_flaky",
            True,
            "5 of 50 runs failed (10.0%, 4 green on re-run); quarantine it to informational",
        ),
        ("c_recovered", False, "no longer flaky over the window; it may return to its tier"),
        (
            "d_expired",
            True,
            "quarantine expired 2026-10-14; back to its tier, or delete it with the reason",
        ),
    ]
