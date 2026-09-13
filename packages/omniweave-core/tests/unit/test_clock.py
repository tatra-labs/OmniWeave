"""`omniweave_core.clock`: the injected Protocol, and the one module that reads the machine.

The load-bearing test is `test_the_substitution_is_taken_only_for_a_clock_the_interpreter_calls_
monotonic`. D154's ladder buys resolution, and the thing it must not spend to get it is
monotonicity: `Cancellation.at_mono_ns` is measured from this clock and 08:377 says a backward step
*"must not turn a 5 s grace into an hour or a no-op"*.

`test_this_platforms_monotonic_resolution` records rather than asserts. It is the evidence half of
D154 and it reports whichever runner it happens to be on, so a Linux CI run and a Windows developer
run both say something true instead of one of them failing.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave_core.clock import (
    MICROSECOND_NS,
    MONOTONIC_MAX_RESOLUTION_NS,
    Clock,
    ClockFacts,
    SystemClock,
    clock_facts,
)

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Callable

CLOCK_PY = Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "clock.py"

FINE = ClockFacts(
    source="monotonic_ns",
    resolution_ns=1,
    monotonic_resolution_ns=1,
    perf_counter_monotonic=True,
)
COARSE = ClockFacts(
    source="perf_counter_ns",
    resolution_ns=100,
    monotonic_resolution_ns=15_625_000,
    perf_counter_monotonic=True,
)


# =============================================================================================
# 1. The Protocol
# =============================================================================================


def test_two_lines_satisfy_the_protocol() -> None:
    """The property the Protocol exists to buy, asserted rather than asserted about."""

    class Counter:
        def monotonic_ns(self) -> int:
            return 7

        def wall_ns(self) -> int:
            return 11

    checked: Clock = Counter()
    assert (checked.monotonic_ns(), checked.wall_ns()) == (7, 11)
    assert isinstance(checked, Clock), "the Protocol is runtime_checkable so a seam can assert it"


def test_the_shipped_clock_satisfies_it() -> None:
    checked: Clock = SystemClock()
    assert isinstance(checked, Clock)


def test_an_object_missing_one_reading_is_not_a_clock() -> None:
    class WallOnly:
        def wall_ns(self) -> int:
            return 0

    assert not isinstance(WallOnly(), Clock)


# =============================================================================================
# 2. The two readings, and the rule that they are never interchangeable
# =============================================================================================


def test_monotonic_advances_and_never_goes_backwards() -> None:
    clock = SystemClock()
    readings = [clock.monotonic_ns() for _ in range(50)]
    assert readings == sorted(readings)
    assert all(isinstance(value, int) for value in readings)


def test_wall_is_an_epoch_reading_and_monotonic_is_not() -> None:
    """*"`wall_ns()` is for correlation ... and for nothing else."*"""
    clock = SystemClock()
    wall = clock.wall_ns()
    assert wall > 1_700_000_000_000_000_000, "a plausible ns-since-epoch reading"
    assert clock.monotonic_ns() != pytest.approx(wall, rel=0.5), "monotonic has its own origin"


def test_a_duration_is_a_difference_of_two_monotonic_readings() -> None:
    clock = SystemClock()
    before = clock.monotonic_ns()
    time.sleep(0.01)
    assert clock.monotonic_ns() - before > 0


# =============================================================================================
# 3. The per-OS ladder. D154.
# =============================================================================================


def test_this_platforms_monotonic_resolution() -> None:
    """Evidence, not an assertion: what `monotonic` can resolve on whichever runner this is.

    D154's measurement was `0.015625` on Windows against `perf_counter`'s `1e-07`. A test that
    asserted a number would fail on the other six matrix cells for being right.
    """
    facts = clock_facts()
    assert facts.monotonic_resolution_ns > 0
    assert facts.source in ("monotonic_ns", "perf_counter_ns")
    assert facts.resolution_ns <= facts.monotonic_resolution_ns


def test_a_coarse_monotonic_is_passed_over_for_perf_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Windows case, forced: 15.6 ms cannot time a serialise, and the ban prescribes it."""
    monkeypatch.setattr(time, "get_clock_info", _info(monotonic=0.015625, perf=1e-07))
    facts = clock_facts()
    assert facts.source == "perf_counter_ns"
    assert facts.substituted is True
    assert facts.monotonic_resolution_ns == 15_625_000
    assert facts.resolution_ns == 100


def test_a_fine_monotonic_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux and macOS: `clock_gettime(CLOCK_MONOTONIC)` at 1 ns needs no substitution."""
    monkeypatch.setattr(time, "get_clock_info", _info(monotonic=1e-09, perf=1e-09))
    facts = clock_facts()
    assert facts.source == "monotonic_ns"
    assert facts.substituted is False
    assert facts.coarse is False


def test_the_substitution_is_taken_only_for_a_clock_the_interpreter_calls_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolution is never bought with monotonicity. 08:377 is why.

    A backward step *"must not turn a 5 s grace into an hour or a no-op"*, and `Cancellation.
    at_mono_ns` is measured from this reading. So a `perf_counter` the interpreter does not call
    monotonic is refused even where it is 150,000x finer, and the shortfall is recorded instead.
    """
    monkeypatch.setattr(
        time, "get_clock_info", _info(monotonic=0.015625, perf=1e-07, perf_monotonic=False)
    )
    facts = clock_facts()
    assert facts.source == "monotonic_ns"
    assert facts.perf_counter_monotonic is False
    assert facts.coarse is True, "and the manifest can say `unmeasured` rather than `0`"


def test_a_coarse_reading_is_reported_rather_than_hidden() -> None:
    """*"A `0` from an unmeasurable clock is worse than an absence: it reads as free."*"""
    assert COARSE.coarse is False, "100 ns resolves a microsecond"
    stuck = ClockFacts(
        source="monotonic_ns",
        resolution_ns=15_625_000,
        monotonic_resolution_ns=15_625_000,
        perf_counter_monotonic=False,
    )
    assert stuck.coarse is True
    assert stuck.substituted is False


def test_the_threshold_is_a_millisecond_and_the_microsecond_is_the_report_scale() -> None:
    assert MONOTONIC_MAX_RESOLUTION_NS == 1_000_000
    assert MICROSECOND_NS == 1_000
    assert MONOTONIC_MAX_RESOLUTION_NS > MICROSECOND_NS


def test_no_platform_in_the_matrix_sits_near_the_line() -> None:
    """What makes one threshold honest: the two real answers are 1 ns and 15.6 ms."""
    assert 1 < MONOTONIC_MAX_RESOLUTION_NS < 15_625_000


# =============================================================================================
# 4. The clock decides once
# =============================================================================================


def test_the_source_is_resolved_at_construction_and_not_per_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clock that re-decided per call could difference two origins, which is meaningless."""
    calls = 0
    real = time.get_clock_info

    def counting(name: str) -> object:
        nonlocal calls
        calls += 1
        return real(name)  # type: ignore[arg-type]  -- the stub narrows to five literals

    monkeypatch.setattr(time, "get_clock_info", counting)
    clock = SystemClock()
    at_construction = calls
    for _ in range(20):
        clock.monotonic_ns()
    assert calls == at_construction


def test_facts_may_be_supplied_so_a_test_can_pin_the_branch() -> None:
    assert SystemClock(FINE).facts is FINE
    assert SystemClock(COARSE).facts.source == "perf_counter_ns"


def test_the_clock_carries_no_settable_state() -> None:
    """*"An attribute someone could set would be ambient time wearing an injection's clothes."*"""
    clock = SystemClock()
    assert not hasattr(clock, "__dict__")
    with pytest.raises(AttributeError):
        clock.monotonic_ns = lambda: 0  # type: ignore[method-assign]


# =============================================================================================
# 5. The scoped G8 exemption does not become a blanket one
# =============================================================================================


def test_this_module_calls_only_the_four_time_functions_it_is_exempted_for() -> None:
    """The exemption is path-scoped, so the file's own discipline is asserted here instead.

    `tools/gate_semgrep.py`'s `CLOCK` docstring points at this test by name. Without it, excluding
    the path would bless `time.time()` and `time.process_time()` in this file too.
    """
    tree = ast.parse(CLOCK_PY.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = node.func.value
            if isinstance(value, ast.Name) and value.id == "time":
                called.add(node.func.attr)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            called.add(node.attr)
    assert called <= {"time_ns", "monotonic_ns", "perf_counter_ns", "get_clock_info"}, called
    assert "time" not in called, "time.time() stays banned here too"
    assert "process_time" not in called
    assert "process_time_ns" not in called


def test_the_exemption_is_scoped_to_this_one_path() -> None:
    gate = (Path(__file__).resolve().parents[4] / "tools" / "gate_semgrep.py").read_text(
        encoding="utf-8"
    )
    assert 'CLOCK = "packages/omniweave-core/src/omniweave_core/clock.py"' in gate
    assert "exclude=(CLOCK,)" in gate
    bank = (Path(__file__).resolve().parents[4] / "tools" / "semgrep" / "omniweave.yaml").read_text(
        encoding="utf-8"
    )
    assert "packages/omniweave-core/src/omniweave_core/clock.py" in bank


def _info(*, monotonic: float, perf: float, perf_monotonic: bool = True) -> Callable[[str], object]:
    """A `time.get_clock_info` that answers from two numbers."""
    real = time.get_clock_info

    def info(name: str) -> object:
        if name == "monotonic":
            return type(
                "Info", (), {"resolution": monotonic, "monotonic": True, "adjustable": False}
            )()
        if name == "perf_counter":
            return type(
                "Info",
                (),
                {"resolution": perf, "monotonic": perf_monotonic, "adjustable": False},
            )()
        # The stub narrows `name` to five literals; a spy takes whatever it is handed.
        return real(name)  # type: ignore[arg-type]  # pragma: no cover -- two names asked.

    return info
