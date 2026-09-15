"""`tools/ow_bench.py` -- the bench lock, the refusals, and the report.

12-performance.md section 1.2's third limit is the one thing in this file that is a RULE rather
than a rendering, and it is asserted first:

> Two concurrent bench runs invalidate both. `ow bench` takes an exclusive `flock` on
> `$OMNIWEAVE_HOME/bench.lock` and a second run **refuses with exit 7** -- the same store-busy exit
> code -- naming host, pid and age. It does not queue, because a queued run measures a page cache
> the first run warmed.

Every clause of it: the lock, the exit code, the naming, and **not queueing** -- which is the one a
later reader is most likely to "fix" into a wait, and which the test makes a red test instead.

**No test here runs a bench.** `main()` is exercised through its refusals and through `--list`, and
the measurement is `test_run_bench.py`'s. A CLI test that ran a real scheduler pass would be
testing `bench.scheduler` a second time and paying for it twice.

Specified in 12-performance.md sections 1.2, 7.1 and 7.4, and 16-roadmap.md:550 (P4 W4.10).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from omniweave.run import bench
from omniweave_core.errors import StoreBusy


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "ow_bench.py"

# Loaded by path, like every other `tools/` script under test: not `importlib.import_module`,
# which is banned outside `host/`, and not a `sys.path` mutation, which leaks into later tests.
_SPEC = importlib.util.spec_from_file_location("omniweave_ow_bench", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


def _run(argv: list[str]) -> tuple[int, str]:
    """The runner, with its report captured. Nothing here writes to the real stdout."""
    buffer = StringIO()
    code = runner.main(argv, out=buffer)
    return code, buffer.getvalue()


# ---------------------------------------------------------------------------------------------
# 1. The lock: section 1.2's third limit, clause by clause
# ---------------------------------------------------------------------------------------------


def test_the_exit_code_is_read_off_the_exception_and_is_seven() -> None:
    """*"the same store-busy exit code"*. Transcribing 7 would be a second number to keep."""
    assert runner.EXIT_BUSY == StoreBusy.EXIT == 7


def test_the_lock_is_a_bench_lock_and_not_the_stores(tmp_path: Path) -> None:
    """Two different exclusions. A bench holding `store.write` would block an ingest it is not
    running, and an ingest holding it would make every bench exit 7 for the wrong reason."""
    lock = runner.bench_lock(tmp_path)
    assert runner.BENCH_SCOPE == "bench"
    assert lock.name != "store.write"
    assert "bench" in lock.path.name
    assert lock.path.parent == tmp_path


def test_a_second_bench_refuses_with_exit_seven_and_names_the_holder(tmp_path: Path) -> None:
    """THE CLAUSE THIS FILE EXISTS FOR. Held lock, second invocation, exit 7, holder named.

    `--subject scheduler` is real work that must NOT start: the assertion is that the refusal comes
    before the store is built, which is what "it does not queue" means operationally.
    """
    held = runner.bench_lock(tmp_path)
    held.acquire(wait_ms=0)
    try:
        code, output = _run(
            ["scheduler", "--units", "10", "--home", str(tmp_path), "--root", str(tmp_path / "r")]
        )
    finally:
        held.release()
    assert code == runner.EXIT_BUSY
    assert "ANOTHER BENCH IS RUNNING" in output
    assert "host" in output and "pid" in output and "age" in output
    assert not (tmp_path / "r").exists(), "it refused before it built anything"


def test_the_refusal_says_it_does_not_queue_and_why(tmp_path: Path) -> None:
    """The clause a later reader is most likely to "fix" into a wait. Section 1.2 gives the reason
    and the message carries it, so the fix arrives with its own counter-argument."""
    held = runner.bench_lock(tmp_path)
    held.acquire(wait_ms=0)
    try:
        _code, output = _run(["scheduler", "--units", "10", "--home", str(tmp_path)])
    finally:
        held.release()
    assert "page cache" in output
    assert "invalidate both" in output


def test_the_lock_is_released_so_a_second_run_is_not_blocked_by_the_first(tmp_path: Path) -> None:
    """A lock leaked on the happy path would make every bench after the first exit 7."""
    code, _output = _run(["scheduler", "--units", "8", "--home", str(tmp_path)])
    assert code == runner.EXIT_CLEAN
    after = runner.bench_lock(tmp_path)
    after.acquire(wait_ms=0)  # raises StoreBusy if the first run kept it
    after.release()


# ---------------------------------------------------------------------------------------------
# 2. The refusals, each testable without a lock or a store
# ---------------------------------------------------------------------------------------------


def _args(**overrides: Any) -> Any:
    """A parsed-arguments stand-in, so each refusal is testable without a lock or a store."""
    values = {
        "subject": "scheduler",
        "list": False,
        "units": 10,
        "storage": "unknown",
        "report": "p50,p95,p99",
        "root": None,
        "home": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_no_subject_is_a_refusal_and_points_at_the_list() -> None:
    subject, refusal = runner.resolve(_args(subject=None))
    assert subject is None
    assert "--list" in refusal[0]


def test_a_subject_outside_the_closed_set_says_the_set_is_closed() -> None:
    """Section 7.1 states its own cardinality, so an unknown name is a plan question."""
    subject, refusal = runner.resolve(_args(subject="throughput"))
    assert subject is None
    assert "closed" in refusal[0]
    assert "plan edit" in refusal[0]
    for name in bench.SUBJECTS:
        assert name in refusal[0]


def test_a_blocked_subject_refuses_and_prints_what_is_in_the_way() -> None:
    """Not "unimplemented": the blocker. A reader who wants the number learns what has to land."""
    subject, refusal = runner.resolve(_args(subject="service"))
    assert subject is None
    assert "blocked" in refusal[0]
    assert any("model server" in line for line in refusal)


@pytest.mark.parametrize("name", ["inproc", "service", "rss"])
def test_the_three_blocked_charter_subjects_all_refuse(name: str) -> None:
    """16-roadmap.md:550 gives this cell four. Three of them cannot run and each says so."""
    subject, refusal = runner.resolve(_args(subject=name))
    assert subject is None
    assert refusal


def test_the_one_runnable_subject_resolves() -> None:
    subject, refusal = runner.resolve(_args(subject="scheduler"))
    assert subject is not None
    assert subject.name == "scheduler"
    assert refusal == []


def test_a_report_flag_naming_a_percentile_this_harness_does_not_compute_is_refused() -> None:
    """`--report p90` is a caller expecting a number. Printing three others would answer a
    question nobody asked, which is why the flag is validated rather than ignored."""
    subject, refusal = runner.resolve(_args(report="p50,p90"))
    assert subject is None
    assert "p90" in refusal[0]
    assert runner.PERCENTILES == ("p50", "p95", "p99")


def test_the_three_percentiles_section_7_1_asks_for_are_all_accepted() -> None:
    for spelling in ("p50", "p95", "p99", "p50,p95", "p50, p95, p99"):
        subject, refusal = runner.resolve(_args(report=spelling))
        assert subject is not None, (spelling, refusal)


def test_a_refused_invocation_never_reaches_the_lock(tmp_path: Path) -> None:
    """`resolve` runs before `acquire`, so a typo does not contend with a running bench."""
    code, output = _run(["nonsense", "--home", str(tmp_path)])
    assert code == runner.EXIT_NOT_RUN
    assert "DID NOT RUN" in output
    assert not list(tmp_path.glob("*.lock")), "no lock file was created"


# ---------------------------------------------------------------------------------------------
# 3. `--list`, and the report's obligations
# ---------------------------------------------------------------------------------------------


def test_list_names_every_subject_and_marks_the_runnable_one() -> None:
    code, output = _run(["--list"])
    assert code == runner.EXIT_CLEAN
    for name in bench.SUBJECTS:
        assert name in output
    assert output.count("RUNS") == len(bench.runnable()) == 1
    assert "13 subjects, 1 runnable" in output


def test_list_marks_the_charter_four_because_the_roadmap_line_names_them() -> None:
    _code, output = _run(["--list"])
    assert output.count("(charter)") == len(bench.CHARTER_FOUR) == 4


def test_the_report_carries_what_inv_19_can_supply_here(tmp_path: Path) -> None:
    """*"Publishing a number without (n, ci95, method, MeasuredOn, witness) is a rejectable
    defect."* Three of the five are available: `n` per series, the percentile METHOD, and the
    machine. `ci95` needs repeated runs a caller sequences and `witness` needs a scoreboard."""
    code, output = _run(["scheduler", "--units", "12", "--home", str(tmp_path)])
    assert code == runner.EXIT_CLEAN
    assert "n =" in output
    assert "percentile = nearest rank" in output
    assert "cpus" in output


def test_the_report_says_its_numbers_go_nowhere(tmp_path: Path) -> None:
    """A harness whose output reaches no scoreboard should say so on every run."""
    _code, output = _run(["scheduler", "--units", "12", "--home", str(tmp_path)])
    assert "NOT PUBLISHED" in output
    assert "eval_perf" in output


def test_a_shallow_run_says_it_is_shallow_and_calls_its_projection_a_floor(tmp_path: Path) -> None:
    """D190: a claim is O(claimable), so a run whose producer never paused never paid the
    working-depth cost. A linear projection from it understates by the depth ratio, and a reader
    taking that rate for the corpus's is the mistake this line exists to prevent."""
    _code, output = _run(["scheduler", "--units", "12", "--home", str(tmp_path)])
    assert "THE PRODUCER NEVER PAUSED" in output
    assert "AT LEAST" in output
    assert "D190" in output


def test_the_report_answers_f8_in_the_words_f8_is_written_in(tmp_path: Path) -> None:
    """B22's row: *"F8 ... names p95 > 1 ms as the trigger for widening group commit"*. The bench
    has no verdict, so it reports the threshold and which side of it each series fell."""
    _code, output = _run(["scheduler", "--units", "12", "--home", str(tmp_path)])
    assert runner.F8_TRIGGER_MS == 1.0
    assert "F8's trigger is p95 > 1 ms" in output
    assert "claim p95" in output and "commit p95" in output


def test_the_default_units_is_not_the_plans_million_and_the_report_prices_the_gap(
    tmp_path: Path,
) -> None:
    """Section 7.1 asks for 1,000,000. At the rate `tools/gate_scale.py` measured that is a day
    and a half, so the default is smaller and the report prints what a million would cost."""
    assert runner.DEFAULT_UNITS < runner.PLAN_UNITS == 1_000_000
    _code, output = _run(["scheduler", "--units", "12", "--home", str(tmp_path)])
    assert "1,000,000 units" in output
