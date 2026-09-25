"""`tools/ow_host.py` driving real workers: the two runner tests that spawn, at T3.

13 §2.7's placement table puts a test that *"spawns a subprocess or a Driver host"* at T3,
`tests/conform/`, and 13 §11.2 runs T3 as its own job. These two were written into
`tests/unit/test_host_subproc.py` (W4.x), where they ran in the same pool as every T1 test.

**Why they moved, measured.** The runner starts each worker at `BELOW_NORMAL_PRIORITY_CLASS` and
waits `CONNECT_MS = 10_000` for it to open its pipe. Alone, the full runner takes 3.2 s. Under a
32-worker `pytest -n auto` of `omniweave-core`, it failed 3 runs in 5, each time on one handshake
that took more than ten seconds (D502). A below-normal child behind 32 normal-priority workers is
starved, which is what its priority class is for. So the answer is the tier the plan already
gives, not a wider constant.

The table-reading runner tests (`--list`, the scenario counts, the curated environment) spawn
nothing and stay at T1, beside the pool tests they check the runner against.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.conform


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


TOOL_PATH = _repo_root(Path(__file__).resolve()) / "tools" / "ow_host.py"
_NAME = "omniweave_ow_host"

# Loaded by path, as `test_host_subproc.py` loads it, and reused when that module already did:
# two executions would give two `runner` objects whose `SCENARIOS` are different tuples.
if _NAME in sys.modules:
    runner = sys.modules[_NAME]
else:
    _SPEC = importlib.util.spec_from_file_location(_NAME, TOOL_PATH)
    if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repo
        message = f"cannot load {TOOL_PATH}"
        raise RuntimeError(message)
    runner = importlib.util.module_from_spec(_SPEC)
    sys.modules[_NAME] = runner
    _SPEC.loader.exec_module(runner)

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the named-pipe arm, job objects and psapi are the Windows cells of S4",
)

_T = TypeVar("_T")


def run_bounded(work: Callable[[], _T], *, patience_s: float) -> _T:
    """`test_host_subproc.run_bounded`, for the same reason: a runner that never returns FAILS.

    The bound is the join, on a daemon thread, and an exception is re-raised on the caller's
    thread. The test directories are not packages, so the helper is repeated rather than imported.
    """
    box: list[_T] = []
    failed: list[Exception] = []

    def run() -> None:
        try:
            box.append(work())
        except Exception as exc:  # re-raised on the caller's thread below
            failed.append(exc)

    thread = threading.Thread(target=run, name="ow-test-bounded", daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(patience_s)
    elapsed = time.monotonic() - started
    assert not thread.is_alive(), f"the call had not returned after {elapsed:.1f}s: not bounded"
    if failed:
        raise failed[0]
    return box[0]


@WINDOWS_ONLY
def test_the_runner_drives_a_real_worker_through_every_scenario_and_reports_clean() -> None:
    """The whole runner, against real children: nine scenarios, one process each (three for
    `quarantine`), a HELLO / INVOKE / CANCEL cycle, a kill, and a report.

    **The rows, not the exit code, and not the word "clean" either.** A regex that reads the
    check count as one-or-more digits admits ZERO: with every `Observation` rebuilt as
    `checks=()` the runner prints
    *"9 scenarios, 0 checks, 0 failed"*, exits `0`, says `clean` -- `all(())` is `True`, so an
    observation that asserted nothing is `ok` -- and this test used to pass. So the tally is
    cross-checked against the `ok` LINES the per-check loop emitted (a different code path from
    the `sum`), every scenario is required to have left at least one of them under its own
    header, and the total is floored at a literal.

    The floor is 27 and the runner currently prints 35. It is a floor and not the number: pinning
    35 would fail on the next check anybody adds, while a floor that is three per scenario cannot
    be met by a table that quietly stopped asserting.

    The call itself is bounded (`run_bounded`), because the subject of nine of these checks is a
    HOST and a host with a broken deadline does not fail this test -- it hangs the session. That
    happened: with `FrameReader.get`'s timeout removed, the `silent` scenario blocked forever and
    `pytest` never finished.
    """
    out = StringIO()
    code = run_bounded(lambda: runner.main([], out=out), patience_s=120.0)
    printed = out.getvalue()
    assert code == runner.EXIT_CLEAN, printed
    assert "ow-host: clean" in printed
    assert "FAIL" not in printed
    tally = re.search(r"ow-host: (\d+) scenarios, (\d+) checks, (\d+) failed", printed)
    assert tally is not None, printed
    assert (int(tally[1]), int(tally[3])) == (9, 0), printed
    ok_lines = [line for line in printed.splitlines() if line.startswith("  ok ")]
    assert int(tally[2]) == len(ok_lines), printed
    assert int(tally[2]) >= 27, printed
    sections = printed.split("\now-host: ")
    for scenario in runner.SCENARIOS:
        assert f"ow-host: {scenario.name}" in printed
        mine = [part for part in sections if part.startswith(f"{scenario.name} -- ")]
        assert len(mine) == 1, scenario.name
        assert [line for line in mine[0].splitlines() if line.startswith("  ok ")], scenario.name
    # The Windows shortfalls are PRINTED, because :1745 requires them recorded and a report that
    # granted a control it did not obtain would be the claim DR10 forbids.
    assert "cpu_capped was not obtained on win32" in printed
    assert "fd_capped was not obtained on win32" in printed
    assert "net_blocked was not obtained on win32" in printed


@WINDOWS_ONLY
def test_the_scenario_flag_runs_that_scenario_and_only_that_one() -> None:
    """`--scenario` is repeatable and documented, and no test had ever passed it.

    A flag nobody exercises is an invocation nobody has run: the filter is
    `if scenario.name not in wanted: continue`, and dropping it -- or inverting it -- is invisible
    to a suite that only ever calls `main([])` and `main(["--list"])`. Inverting it is worse than
    invisible, because a run that skipped every scenario would print *"0 scenarios, 0 checks,
    0 failed"* and the word `clean`.

    `card_mismatch` is the scenario chosen because it is the cheapest that still spawns a real
    child, and the assertion is two-sided: its own header and check are present, and the other
    eight names are absent from the report.
    """
    out = StringIO()
    code = run_bounded(
        lambda: runner.main(["--scenario", "card_mismatch"], out=out), patience_s=60.0
    )
    printed = out.getvalue()
    assert code == runner.EXIT_CLEAN, printed
    assert "ow-host: card_mismatch --" in printed
    assert re.search(r"ow-host: 1 scenarios, [1-9]\d* checks, 0 failed", printed), printed
    for other in runner.SCENARIOS:
        if other.name == "card_mismatch":
            continue
        assert f"ow-host: {other.name} --" not in printed, other.name
