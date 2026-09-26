"""`tools/gate_hook_latency.py`: G26's pure half -- budgets, trace parsing, p95 and the verdict.

The wall clock is never asserted here: 11:1646-1652 makes the module count the hard assertion
because a timing on a shared machine is a coin toss, and a unit test timing a spawn would be one.
The spawning half (the witness, the module count against this OS's baseline) is T3's, in
`tests/conform/test_gate_hook_latency_process.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "gate_hook_latency.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("gate_hook_latency", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


g = _load()
BUDGETS = g.Budgets(warm_ms=250.0, cold_ms=1000.0, self_deadline_ms=400.0)  # type: ignore[attr-defined]


def _baseline(**changes: object) -> object:
    fields = {
        "baseline_schema": 1,
        "os": "windows",
        "python": "3.12.0",
        "machine": "AMD64",
        "module_count": 2,
        "modules": ("json", "omniweave.hooks.main"),
        "warm_p95_ms": 100.0,
        "cold_p95_ms": 300.0,
        "recorded_at": "2026-09-26",
        "runner": "test",
    }
    fields.update(changes)
    return g.Baseline(**fields)  # type: ignore[attr-defined]


def _judge(**changes: object) -> tuple[str, ...]:
    args: dict[str, object] = {
        "witnessed": True,
        "warm_ms": [100.0] * 30,
        "modules": ("json", "omniweave.hooks.main"),
        "baseline": _baseline(),
    }
    args.update(changes)
    return g.judge(BUDGETS, **args)  # type: ignore[attr-defined]


def test_the_budgets_are_read_from_g26_and_agree_with_the_d1_row() -> None:
    """Warm and cold from `tools/gates.toml`'s G26 assertion, cross-checked against
    `gate_coldstart.py`'s D1 row; the self-deadline from the hook envelope. None restated."""
    read = g.budgets()  # type: ignore[attr-defined]
    assert (read.warm_ms, read.cold_ms, read.self_deadline_ms) == (250.0, 1000.0, 400.0)


def test_the_d394_gap_is_what_the_report_exists_to_show() -> None:
    """The self-deadline is below the cold budget, so a cold run between them is a healthy gate
    and a silent hook. The report counts those runs; this pins that the gap is still there."""
    read = g.budgets()  # type: ignore[attr-defined]
    assert read.self_deadline_ms < read.cold_ms


def test_the_trace_parser_reads_the_last_column_and_skips_the_header() -> None:
    trace = (
        "import time: self [us] | cumulative | imported package\n"
        "import time:       120 |        120 |   _io\n"
        "import time:       300 |        420 | omniweave.hooks.main\n"
        "not a trace line\n"
    )
    assert g.modules_of(trace) == frozenset({"_io", "omniweave.hooks.main"})  # type: ignore[attr-defined]


def test_p95_is_nearest_rank() -> None:
    """30 runs: the 29th smallest. 20 runs: the 19th. One run: itself."""
    assert g.p95([float(i) for i in range(1, 31)]) == 29.0  # type: ignore[attr-defined]
    assert g.p95([float(i) for i in range(1, 21)]) == 19.0  # type: ignore[attr-defined]
    assert g.p95([7.0]) == 7.0  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("prompt", "control", "ok"),
    [
        (["ow-hook-ups-noop-no-corpus"], ["ow-hook-unknown-noop-event"], True),
        (["ow-hook-unknown-noop-event"], ["ow-hook-unknown-noop-event"], False),
        (["ow-hook-ups-noop-no-corpus"], ["ow-hook-ups-noop-no-corpus"], False),
        ([], ["ow-hook-unknown-noop-event"], False),
    ],
)
def test_the_witness_needs_both_the_handler_and_the_control(
    prompt: list[str], control: list[str], ok: bool
) -> None:
    """D432's negative control, pure: a prompt on the no-op path fails, and so does a build that
    answers the control word the same way it answers `prompt`."""
    counters = {"prompt": prompt, g.CONTROL_WORD: control}  # type: ignore[attr-defined]
    assert g.discriminates(counters) is ok  # type: ignore[attr-defined]


def test_a_clean_run_has_no_failure() -> None:
    assert _judge() == ()


def test_a_prompt_that_reaches_no_handler_fails_before_any_timing_counts() -> None:
    (failure,) = _judge(witnessed=False)
    assert "no-op path (D432)" in failure


def test_a_warm_budget_breach_fails_and_names_the_budget() -> None:
    failures = _judge(warm_ms=[100.0] * 28 + [300.0] * 2, baseline=None)
    assert any("warm p95 300 ms > 250 ms" in one for one in failures), failures


def test_a_cold_breach_is_reported_and_fails_nothing() -> None:
    """D607: the cold figure is an upper bound on a state no real install is in, so it is
    information and not a verdict. The report says OVER BUDGET; `judge()` returns nothing."""
    cold = [300.0] * 9 + [1500.0]
    assert "cold_ms" not in g.judge.__code__.co_varnames, "judge() takes no cold figure"  # type: ignore[attr-defined]
    report = g.Report(BUDGETS, True, {}, [100.0] * 30, cold, (), None, ())  # type: ignore[attr-defined]
    (line,) = [one for one in report.lines() if one.startswith("G26  cold")]
    assert "OVER BUDGET" in line
    assert "fails nothing" in line


def test_a_new_module_on_the_hook_path_fails_and_is_named() -> None:
    """The hard assertion: deterministic, and what actually regresses -- one eager import."""
    (failure,) = _judge(modules=("json", "omniweave.hooks.main", "omniweave_core.store"))
    assert "3 modules on the hook path against the baseline's 2" in failure
    assert "omniweave_core.store" in failure


def test_the_band_is_twenty_five_percent_over_the_baseline() -> None:
    assert _judge(warm_ms=[125.0] * 30) == ()
    (failure,) = _judge(warm_ms=[126.0] * 30)
    assert "the baseline's 100 ms + 25% = 125 ms" in failure


def test_with_no_baseline_the_count_and_the_band_do_not_run() -> None:
    """UNMEASURED, not green: the report says so. Only the absolute budgets apply."""
    assert _judge(modules=("a", "b", "c", "d"), warm_ms=[200.0] * 30, baseline=None) == ()
