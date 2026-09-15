"""`ow bench <subject>`'s runner: the exclusive lock, the argument parsing, and the report.

**Why a `tools/` script and not a CLI in the package.** `omniweave.cli` is P7's (16-roadmap.md
section 10). This is the fifth application of the standing pattern (ledger D25): `ow schema emit`
shipped as `tools/schemagen.py` at P1, `ow store verify` as `store/verify.py` plus
`tools/gate_crash.py`, `ow test crash-matrix` as `store/crashmatrix.py` plus the same gate,
`ow eval perf` as `store/inspect.py` plus `tools/measure_store.py`, and `ow ingest --scope` as
`omniweave_core.acquire` plus `tools/ow_discover.py`. In each the LIBRARY FUNCTION lives in the
package and a `tools/` script drives it, so P7 wraps a function rather than re-implementing one.

`omniweave.run.bench` is the library half and 12-performance.md section 7.1 names that file
explicitly -- *"the registry is one function per subject in
`packages/omniweave/src/omniweave/run/bench.py`"*. Everything below is a lock, an argument parser
and a printer: there is no measurement in this file, and that is what makes it a driver of the
harness rather than a second harness.

## The lock, and why it is exit 7 and not a queue

12-performance.md section 1.2's third limit:

> Two concurrent bench runs invalidate both. `ow bench` takes an exclusive `flock` on
> `$OMNIWEAVE_HOME/bench.lock` and a second run **refuses with exit 7** -- the same store-busy exit
> code -- naming host, pid and age. It does not queue, because a queued run measures a page cache
> the first run warmed.

All three clauses are `omniweave_core.locks` already: `FileScopedLock` is `O_CREAT|O_EXCL` plus an
advisory lock, `acquire(wait_ms=0)` is *"one attempt and no wait"*, and the refusal it raises is
`StoreBusy`, whose `EXIT` is **7** and whose message already names host, pid and age. So this file
composes three things that exist and adds none.

`$OMNIWEAVE_HOME` is read from the environment because `os.getcwd()` and an ambient config root are
both banned (02-architecture.md section 8.4 decision (e)); `--home` overrides it and a temporary
directory is the last resort, which `--home` exists so a caller never has to accept by accident.
The lock SCOPE is `bench` rather than `store.write`: two different exclusions, and a bench that
took the store's lock would block an ingest it is not running.

## What it prints, and what it refuses to

Section 7.4 publishes a bench through an `eval_perf` row into `eval/results/**.json`. Neither
exists. `bench.PUBLICATION` carries the argument and this script PRINTS it, because a harness whose
output goes nowhere should say so on every run rather than in a docstring nobody opens.

INV-19 -- *"publishing a number without `(n, ci95, method, MeasuredOn, witness)` is a rejectable
defect"* -- is why the report carries `n`, the percentile METHOD, and the machine: three of the five
are available here, `ci95` needs repeated runs the caller sequences, and `witness` is a scoreboard
concept with no scoreboard to be on.

## Exit codes

0 the bench ran and the report was written. 2 it did not run (a bad argument, a subject that is
blocked, a drain that did not finish). **7 another bench holds the lock**, which is section 1.2's
number and `StoreBusy.EXIT`.

There is no exit 1: a bench has no verdict. `tools/gate_scale.py` is the gate over this same loop
and exit 1 is its.

Specified in 12-performance.md sections 1.2, 7.1, 7.2 and 7.4 and rows B22 and F8,
08-runtime.md:2715, and 16-roadmap.md:550 (P4 W4.10).
"""

from __future__ import annotations

import argparse
import asyncio  # noqa: TID251 -- a tools/ driver of omniweave.run; the ban scopes core.
import math
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave.run import bench
from omniweave_core import config as configmod
from omniweave_core import locks
from omniweave_core.clock import SystemClock
from omniweave_core.errors import OwError, StoreBusy

if TYPE_CHECKING:  # pragma: no cover -- annotations only.
    from collections.abc import Sequence

__all__ = [
    "BENCH_SCOPE",
    "DEFAULT_UNITS",
    "EXIT_BUSY",
    "EXIT_CLEAN",
    "EXIT_NOT_RUN",
    "F8_TRIGGER_MS",
    "HOME_ENV",
    "PERCENTILES",
    "PLAN_UNITS",
    "bench_lock",
    "main",
    "report_scheduler",
    "resolve",
    "subjects_table",
]

EXIT_CLEAN: Final = 0
EXIT_NOT_RUN: Final = 2
EXIT_BUSY: Final = StoreBusy.EXIT
"""**7**, read off the exception rather than transcribed.

12-performance.md section 1.2 calls it *"the same store-busy exit code"*, and a second spelling of
the number is a second number to keep in step with the first."""

BENCH_SCOPE: Final = "bench"
"""The lock scope. NOT `store.write`: `locks.STORE_WRITE_LOCK` is one per store and this is one per
machine, and a bench that took the store's lock would block an ingest it is not running."""

HOME_ENV: Final = "OMNIWEAVE_HOME"
"""Where section 1.2 puts `bench.lock`. Read from the environment, never from an ambient default."""

DEFAULT_UNITS: Final = 20_000
"""Units when `--units` is absent.

**Not 1,000,000, which is what section 7.1 asks for**, and the difference is a measurement rather
than a preference: `tools/gate_scale.py` measured 100,000 units at 102 transitions/s on this
workspace's runner, so a million is a day and a half. The number section 7.1 names is what
`ow-bench-1` runs once the claim stops being `O(claimable)` (D190); until then a default that took
a day would mean nobody ran the bench at all. The report prints what a million would cost at the
rate it just measured, so the gap is a number on every run and not a footnote here."""

PLAN_UNITS: Final = 1_000_000
"""12-performance.md section 7.1's own figure, kept so the report can price the gap."""

F8_TRIGGER_MS: Final = 1.0
"""12-performance.md:153: B22's p95 ceiling, and **F8's own trigger**.

The B22 row reads *"F8 is the measurement and names p95 > 1 ms as the trigger for widening group
commit"*, so this number is not a budget the bench enforces -- it has no verdict -- but the
threshold whose crossing is the finding the bench exists to report."""

PERCENTILES: Final = ("p50", "p95", "p99")
"""What `--report` may name. Section 7.1 bolds the third: *"p50/p95/**p99**"*.

All three are printed whatever is asked for, and the flag is still validated rather than ignored:
`--report p90` is a caller expecting a number this harness does not compute, and silently printing
three others would answer a question nobody asked."""


def bench_lock(home: Path) -> locks.FileScopedLock:
    """`$OMNIWEAVE_HOME/bench.lock`'s lock, with this process's clock. Section 1.2's third limit."""
    return locks.scoped_lock(home, BENCH_SCOPE, now_ns=SystemClock().wall_ns)


def subjects_table(out: TextIO) -> None:
    """Every subject, and for the blocked ones what is in the way. `ow bench --list`.

    Printed in `SUBJECTS` order, which is section 7.1's table order, so a reader comparing the two
    is comparing two lists in one order rather than two sets.
    """
    runnable = bench.runnable()
    print(
        f"ow bench <subject> -- {len(bench.SUBJECTS)} subjects, {len(runnable)} runnable", file=out
    )
    print("", file=out)
    for name, subject in bench.SUBJECTS.items():
        mark = "  RUNS" if subject.runnable else "  --  "
        charter = " (charter)" if name in bench.CHARTER_FOUR else ""
        print(f"{mark}  {name}{charter}", file=out)
        for line in _wrapped("          ", subject.measures):
            print(line, file=out)
        if not subject.runnable:
            for line in _wrapped("          blocked by: ", subject.blocked_by):
                print(line, file=out)


def _wrapped(prefix: str, text: str, *, width: int = 96) -> list[str]:
    """`text` under `prefix`, continuations indented to it. No dependency, nothing ragged."""
    body = textwrap.wrap(text, width=width - len(prefix)) or [""]
    pad = " " * len(prefix)
    return [prefix + body[0], *(pad + line for line in body[1:])]


def _series_lines(series: bench.Series) -> list[str]:
    """One series as section 7.1's three percentiles plus what INV-19 needs beside them."""
    return [
        f"  {series.name:<16} n = {series.n:>9,}   p50 {series.p50:8.4f}   p95 {series.p95:8.4f}"
        f"   p99 {series.p99:8.4f}   max {series.worst:9.4f}  {series.unit}",
        f"  {'':<16} mean {series.mean:8.4f} {series.unit}   total {series.total / 1e3:8.2f} s",
    ]


def report_scheduler(result: bench.SchedulerResult, out: TextIO) -> None:
    """The report. Numbers, the machine they were measured on, and what is not published."""
    print(
        f"ow bench scheduler -- {result.units:,} synthetic units, no-op operator,"
        f" storage {result.storage}",
        file=out,
    )
    print("", file=out)
    print(f"  machine       {result.cpus} cpus", file=out)
    print(f"  derived       workers {_table(result.workers)}", file=out)
    print(f"                inflight {_table(result.inflight)}", file=out)
    print(f"                [runtime.claim] batch {_table(result.claim_batch)}", file=out)
    print(
        f"                _next_width() asks for {result.claim_width},"
        f" which is min() of that table",
        file=out,
    )
    print(
        f"  water         queue_high_water {result.high_water:,}"
        f" / queue_low_water {result.low_water:,}, [runtime] plan_batch {result.plan_batch}",
        file=out,
    )
    print("", file=out)
    print(
        f"  roster        {result.units:,} unit rows in {result.roster_s:.2f} s;"
        f" the producer paused {result.pauses}x",
        file=out,
    )
    print(
        f"  drain         {result.completed:,} transitions in {result.drain_s:.2f} s"
        f" ({result.status}), {result.batches:,} batches",
        file=out,
    )
    print("", file=out)
    print(
        "CLAIM, COMMIT AND TOTAL -- 12-performance.md section 7.1; percentile = nearest rank",
        file=out,
    )
    for line in (*_series_lines(result.claim), *_series_lines(result.commit)):
        print(line, file=out)
    print(
        f"  {'total':<16} {result.ms_per_transition:8.4f} ms/transition wall"
        f"   {result.transitions_per_s:8.1f} transitions/s   (B22 budgets 0.45 ms)",
        file=out,
    )
    print("", file=out)
    for line in _findings(result):
        print(line, file=out)
    print("", file=out)
    for line in _wrapped("  NOT PUBLISHED: ", bench.PUBLICATION):
        print(line, file=out)


def _findings(result: bench.SchedulerResult) -> list[str]:
    """The numbers a reader acts on, each naming the mechanism it belongs to.

    **The projection is labelled a FLOOR and the label is load-bearing.** A claim is `O(claimable)`
    (D190), so scaling a drain linearly in `units` is only sound if the claimable set was at its
    working depth throughout -- and a run whose producer never paused never reached
    `queue_high_water` at all. `_depth_note` is that qualification, and it is printed rather than
    left to a reader who would otherwise take a shallow run's rate as the corpus's.
    """
    watched = (("claim", result.claim), ("commit", result.commit))
    over = [name for name, series in watched if series.p95 > F8_TRIGGER_MS]
    if len(over) == len(watched):
        verdict = f"BOTH ABOVE IT: {', '.join(over)}"
    elif over:
        verdict = f"{over[0]} is above it"
    else:
        verdict = "neither is above it"
    projected = result.drain_s * PLAN_UNITS / result.completed if result.completed else math.nan
    return [
        "WHAT THE DISTRIBUTION SAYS",
        f"  Store.claim is {result.claim_share * 100:.0f}% of the drain's wall clock,"
        f" and the claimer is ONE coroutine",
        f"  {result.rows_per_claim:.2f} rows per claim statement"
        f"  (1.00 means every row paid a whole statement -- D191)",
        f"  F8's trigger is p95 > {F8_TRIGGER_MS:g} ms on B22 -- {verdict}:",
        f"      claim p95 {result.claim.p95:8.4f} ms      commit p95 {result.commit.p95:8.4f} ms",
        "",
        *_depth_note(result),
        f"  section 7.1 asks for {PLAN_UNITS:,} units. At the rate just measured that is AT LEAST"
        f" {projected / 3600:.1f} h;",
        f"  this run did {result.units:,} in {result.drain_s / 60:.1f} min. See D190.",
    ]


def _depth_note(result: bench.SchedulerResult) -> list[str]:
    """Whether the run reached the depth the claim's cost is a function of. D190's qualification."""
    if result.pauses:
        return [
            f"  The producer paused {result.pauses}x, so the claimable set reached"
            f" queue_high_water = {result.high_water:,} and",
            "  the claim paid its working-depth cost. The rate below scales.",
        ]
    return [
        f"  THE PRODUCER NEVER PAUSED, so the claimable set stayed below queue_high_water ="
        f" {result.high_water:,}.",
        "  A claim is O(claimable) (D190), so every figure above is a SHALLOW-QUEUE figure and the",
        f"  projection below is a floor: run --units above {result.high_water:,} for the depth a",
        "  corpus actually holds the queue at.",
    ]


def _table(values: object) -> str:
    items = sorted(values.items())  # type: ignore[attr-defined]
    return "{" + ", ".join(f"{name}: {value}" for name, value in items) + "}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ow bench <subject>: the performance harness. 12-performance.md section 7."
    )
    parser.add_argument(
        "subject",
        nargs="?",
        help=f"one of {', '.join(bench.SUBJECTS)}; omit with --list to see them",
    )
    parser.add_argument("--list", action="store_true", help="print every subject and exit")
    parser.add_argument(
        "--units",
        type=int,
        default=DEFAULT_UNITS,
        help=f"synthetic units for `scheduler` (default {DEFAULT_UNITS:,};"
        f" section 7.1 asks for {PLAN_UNITS:,})",
    )
    parser.add_argument(
        "--storage",
        choices=bench.STORAGE_MEDIA,
        default="unknown",
        help="a LABEL for the medium; nothing here can detect one",
    )
    parser.add_argument(
        "--report",
        default="p50,p95,p99",
        help="accepted and asserted, not a projection: every percentile is always printed",
    )
    parser.add_argument("--root", type=Path, default=None, help="where to build the store")
    parser.add_argument("--home", type=Path, default=None, help=f"overrides ${HOME_ENV}")
    return parser


def _home(explicit: Path | None, env: object) -> Path:
    """`--home`, else `$OMNIWEAVE_HOME`, else a temporary directory. Never an ambient default."""
    if explicit is not None:
        return Path(explicit)
    named = env.get(HOME_ENV) if hasattr(env, "get") else None  # type: ignore[union-attr]
    return Path(str(named)) if named else Path(tempfile.gettempdir()) / "omniweave-bench"


def resolve(args: argparse.Namespace) -> tuple[bench.Subject | None, list[str]]:
    """The subject this invocation names, or the lines saying why there is none.

    Lifted out of `main` because the four refusals are four DECISIONS and `main` is a sequence of
    effects -- lock, run, print. It also makes each refusal testable without a lock, a store or a
    temporary directory, which is what "a gate that cannot fail" costs when the refusal is buried
    in a function that needs three of them to reach it.
    """
    if args.subject is None:
        return None, ["DID NOT RUN: name a subject, or pass --list"]
    subject = bench.SUBJECTS.get(args.subject)
    if subject is None:
        return None, [
            f"DID NOT RUN: {args.subject!r} is not a subject. The set is closed and adding one is "
            f"a plan edit (12-performance.md section 7.1): {', '.join(bench.SUBJECTS)}"
        ]
    if not subject.runnable:
        return None, [
            f"DID NOT RUN: `ow bench {subject.name}` is blocked.",
            *_wrapped("  blocked by: ", subject.blocked_by),
        ]
    asked = [name.strip() for name in args.report.split(",")]
    unknown = [name for name in asked if name not in PERCENTILES]
    if unknown:
        return None, [
            f"DID NOT RUN: --report names {unknown}; section 7.1 asks for "
            f"{', '.join(PERCENTILES)} and this harness prints all three whatever is asked for"
        ]
    return subject, []


def main(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout) -> int:
    """Take the lock, run one subject, print. 0 ran, 2 did not run, 7 another bench holds it."""
    import os  # noqa: PLC0415 -- the one environment read, kept beside its only use.

    args = _parser().parse_args(argv)
    if args.list:
        subjects_table(out)
        return EXIT_CLEAN
    subject, refusal = resolve(args)
    if subject is None:
        for line in refusal:
            print(line, file=out)
        return EXIT_NOT_RUN

    home = _home(args.home, os.environ)
    home.mkdir(parents=True, exist_ok=True)
    lock = bench_lock(home)
    try:
        lock.acquire(wait_ms=0)
    except StoreBusy as busy:
        print(f"ANOTHER BENCH IS RUNNING: {busy}", file=out)
        print(
            "  12-performance.md section 1.2: two concurrent bench runs invalidate both, and",
            file=out,
        )
        print("  a queued run would measure a page cache the first run warmed.", file=out)
        return EXIT_BUSY

    temporary = args.root is None
    root = Path(tempfile.mkdtemp(prefix="ow-bench-")) if temporary else Path(args.root)
    try:
        config = configmod.load(cwd=root, env={})
        result = asyncio.run(
            bench.scheduler(root, units=args.units, config=config, storage=args.storage)
        )
    except OwError as exc:
        print(f"DID NOT RUN: {exc}", file=out)
        return EXIT_NOT_RUN
    except ValueError as exc:
        print(f"DID NOT RUN: {exc}", file=out)
        return EXIT_NOT_RUN
    finally:
        lock.release()
        if temporary:
            shutil.rmtree(root, ignore_errors=True)

    report_scheduler(result, out)
    return EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover -- the CLI entry point.
    raise SystemExit(main())
