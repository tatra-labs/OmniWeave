"""G21: SIGKILL a real process at a statement boundary in `Store.complete()`, resume, compare.

`tools/gates.toml`'s G21 row is the specification and this is its runner. The assertion cell reads
*"kill-9 at three points; `ow resume`; store equals an uninterrupted run"*, `jobs = ["crash"]`,
`budget_s = 240`, `pr = true`, `nightly = true`, `nightly_note = "full matrix"`. Both halves are
here and they are one code path: **no arguments** draws three points and is the PR job; `--all`
walks every boundary of every fixture and is the nightly `ow-bench-1` row (11-repo-layout.md
section 6.5, *"the full G21 crash matrix"*).

16-roadmap.md:445 spells P2's exit line as `uv run ow test crash-matrix
--statement-boundaries all` followed by `uv run tools/gate_crash.py   # G21`. `ow` is P7's
(16 section 10) and does not exist yet, exactly as `tools/schemagen.py` is `ow schema emit`'s
runner at P1; `omniweave_core.store.crashmatrix.crash_matrix()` is the library function that verb
wires, and this script is its process-killing driver.

## What this script adds that the library cannot

`omniweave_core/store/crashmatrix.py` is library code, and `subprocess` is banned under
`packages/*/src/**` (02-architecture.md:392, enforced as an `ast` check by
`tools/gate_semgrep.py`). `tools/` is not library code -- `tools/gate_semgrep.py:26-37` takes that
reading for itself in as many words -- so the process control lives here:

* the PARENT spawns a child for one cycle, waits for it to report that it is parked at the target
  boundary, and sends the signal;
* the CHILD (`--child`) drives one scenario with a boundary hook that writes a ready file and then
  blocks forever. It never exits on its own. Everything it did to the store, it did before it
  parked, and it is killed standing on the boundary.

`Popen.kill()` is `SIGKILL` on POSIX and `TerminateProcess` on Windows. Both are uncatchable and
both run no `atexit`, no `__del__` and no `Connection.close()`, which is the property the matrix
depends on; `crashmatrix.py`'s module docstring states the one thing the Windows cell does not
reproduce and why it does not matter here.

## Why the three points are reproducible, and how to reproduce them

`random` is banned in library code and 11-repo-layout.md:2185 gives the reason as a message
string: *"Sampling is blake2b. Determinism is a gate, not a habit."* So the three points are a
keyed `blake2b` over each candidate's own name, and this script PRINTS them. A failure on CI is
re-run locally with the same `--salt`, or with `--point mode/boundary` to run exactly one.

## Exit codes

0 every cycle converged, 1 a cycle diverged or the budget was breached in PR mode, 2 the gate did
not run (a bad argument, a child that never parked, a workspace that could not be made). 1 and 2
are distinguished because CI treats both as failure and a human needs to know which.

Specified in 11-repo-layout.md section 6.4 (G21) and 6.5, 16-roadmap.md:422 and :436-445,
17-risks.md:861, 07-store-and-retrieval.md:2730-2733 and 13-quality.md:252.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: TID251 - gate harness, not library code; see the module docstring.
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from omniweave_core.store import crashmatrix as cm

SELF = Path(__file__).resolve()
"""This file, by absolute path. The child is spawned as `sys.executable SELF --child ...`, so the
path has to be the resolved one rather than `argv[0]`: a gate invoked as `tools/gate_crash.py`
from another directory would otherwise spawn a child that does not exist."""

__all__ = [
    "BUDGET_S",
    "CHILD_PARK_TIMEOUT_S",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "NOW_MS",
    "NOW_NS",
    "Cycle",
    "Emit",
    "Killer",
    "child",
    "main",
    "spawn_kill",
]

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

BUDGET_S = 240
"""`tools/gates.toml`'s G21 `budget_s`. PR mode fails past it; `--all` reports and does not.

Section 6.4 puts the number on the row and 11-repo-layout.md section 6.5 puts the full matrix on
the nightly runner, so the budget belongs to the three-point job. A nightly that overran would be
reported by the job's own timeout, not by this."""

CHILD_PARK_TIMEOUT_S = 60.0
"""How long the parent waits for a child to reach its boundary before calling the cycle not-run.

A child that never parks is a harness failure and not a store failure, and the two must not read
alike: this is the difference between exit 2 and exit 1."""

NOW_NS = 1_757_400_000_000_000_000
"""The injected wall clock, fixed. `time.time` is banned in library code and every store clock is
a parameter, so the fixture stamps its migration ledger with a constant -- which is one of the
things that makes two runs byte-identical rather than merely equivalent."""

NOW_MS = 1 << 62
"""The `now_ms` `ow resume` reaps with: past any lease this harness mints (07:59 injects it)."""

Killer = Callable[[Path, Path, cm.Scenario, str], cm.RunReport]
"""What `crashmatrix.verify_boundary()` takes as its `kill` seam: `(path, cas, scenario, boundary)`
-> a `RunReport`. `cm.simulate_kill_at` is the in-process model and `spawn_kill()` builds the real
one, and the two are interchangeable precisely because everything else about a cycle is shared."""

_READY = "ready"
"""The child's ready file, beside the store. Its existence means "parked, kill me now"."""


Emit = Callable[[str], None]
"""One line of the report. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""


def _emitter(out: TextIO) -> Emit:
    """Bind the report to a stream.

    `main(argv, *, out)` is the house shape (`tools/gate_incremental.py`,
    `tools/gate_migrations.py`) and this is the reason: a test asserts the report's TEXT -- that
    the three drawn points are printed, that a divergence names the table it diverged on -- and a
    gate that wrote to `sys.stdout` unconditionally would make every such assertion a `capsys`
    reading of a global.
    """

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    return emit


# ---------------------------------------------------------------------------------------------
# The child: drive one scenario and park on the boundary.
# ---------------------------------------------------------------------------------------------


def child(root: Path, mode: str, boundary: str, *, emit: Emit) -> int:
    """Run one scenario against the store in `root` and BLOCK FOREVER at `boundary`.

    Never returns cleanly when it reaches the boundary -- that is the point. It writes `ready` and
    then waits on an event nothing will ever set, so the parent's `kill()` finds a process standing
    exactly between two statements of `complete()`'s transaction, holding an uncommitted write.

    `threading.Event().wait()` rather than a sleep loop: a loop would wake, and a woken process is
    a process that might run one more statement between the parent's decision and its signal.

    If the boundary is never reached the run finishes and this returns 1, which the parent reads
    as a harness failure. A cycle that silently did not kill anything is the check that cannot
    fail.
    """
    by_mode = {scenario.mode: scenario for scenario in cm.SCENARIOS}
    if mode not in by_mode:
        emit(f"child: no scenario {mode!r}")
        return EXIT_NOT_RUN
    scenario = by_mode[mode]
    if boundary not in cm.boundaries_of(scenario):
        emit(f"child: {boundary!r} is not a boundary of {mode!r}")
        return EXIT_NOT_RUN
    ready = root / _READY

    def park(name: str) -> None:
        if name != boundary:
            return
        ready.write_text(f"{mode}\n{boundary}\n", encoding="utf-8")
        threading.Event().wait()  # forever: the parent kills this process.

    cm.run_scenario(root / "index.owstore", root / "cas", scenario, on_boundary=park)
    emit(f"child: finished without reaching {boundary!r}")
    return EXIT_FAIL


# ---------------------------------------------------------------------------------------------
# The parent: spawn, wait for the park, kill.
# ---------------------------------------------------------------------------------------------


def spawn_kill(*, timeout_s: float = CHILD_PARK_TIMEOUT_S) -> Killer:
    """Build the `kill` callable `crashmatrix.verify_boundary()` takes. Real processes, real signal.

    The seam is deliberate and is the reason the cheap harness and this gate cannot test different
    things: `verify_boundary()` does the seeding, the resume and the comparison itself, and the
    only thing that differs between `simulate_kill_at` and this is HOW the process stops.

    Returns a `RunReport` whose `reached` is empty -- the child took its trace with it, which is
    what makes this a real kill and not a co-operative one. `crashmatrix`'s own test suite is
    where `reached` is asserted, against the in-process model.
    """

    def kill(path: Path, _cas: Path, scenario: object, boundary: str) -> cm.RunReport:
        mode = scenario.mode  # type: ignore[attr-defined]
        root = path.parent
        ready = root / _READY
        ready.unlink(missing_ok=True)
        proc = subprocess.Popen(  # noqa: S603 - argv is this file's own path plus fixed flags.
            [
                sys.executable,
                str(SELF),
                "--child",
                "--root",
                str(root),
                "--mode",
                str(mode),
                "--boundary",
                boundary,
            ]
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if ready.exists():
                break
            if proc.poll() is not None:
                raise ChildNeverParkedError(
                    f"the child for {mode}/{boundary} exited {proc.returncode} before parking"
                )
            time.sleep(0.01)
        else:
            proc.kill()
            proc.wait(timeout=30)
            raise ChildNeverParkedError(f"the child for {mode}/{boundary} never parked")
        proc.kill()
        proc.wait(timeout=30)
        ready.unlink(missing_ok=True)
        return cm.RunReport(
            scenario=str(mode),
            derived=False,
            completed=False,
            superseded=False,
            reached=(),
            killed_at=boundary,
        )

    return kill


class ChildNeverParkedError(RuntimeError):
    """The child did not reach its boundary. A HARNESS failure, and exit 2 rather than exit 1.

    A store that did not converge is a finding; a cycle that never killed anything is a gate that
    did not run, and 11-repo-layout.md section 6.8 refuses a check that cannot fail. Keeping the
    two apart is the whole reason this class exists rather than a `False`.
    """


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cycle:
    """One kill-and-verify cycle, as this script reports it."""

    label: str
    ok: bool
    seconds: float
    integrity: str
    differences: tuple[str, ...]
    reclaimed_wal_bytes: int


def _points(args: argparse.Namespace) -> tuple[tuple[str, str], ...]:
    """Which cycles to run: `--all`, an explicit `--point`, or the blake2b-drawn three."""
    population = cm.matrix_boundaries()
    if args.point:
        chosen: list[tuple[str, str]] = []
        for spec in args.point:
            mode, _, boundary = spec.partition("/")
            pair = (mode, boundary)
            if pair not in population:
                raise ValueError(f"{spec!r} is not a point of the matrix; use --list to see them")
            chosen.append(pair)
        return tuple(chosen)
    if args.all:
        return population
    return cm.kill_points(population, salt=args.salt.encode(), count=args.points)


def _run(args: argparse.Namespace, workspace: Path, emit: Emit) -> tuple[list[Cycle], float]:
    """Every cycle, one at a time, each in its own directory under `workspace`."""
    chosen = _points(args)
    emit(
        f"crash matrix  {len(cm.SCENARIOS)} fixtures, {len(cm.matrix_boundaries())} boundaries, "
        f"running {len(chosen)}"
    )
    emit(f"  salt={args.salt!r}  kill={'in-process model' if args.in_process else 'SIGKILL'}")
    for mode, boundary in chosen:
        emit(f"  point  {mode}/{boundary}")
    emit("")

    base_dir = workspace / "baseline"
    base_dir.mkdir(parents=True)
    started = time.perf_counter()
    baseline = cm.baseline(base_dir, now_ns=NOW_NS, scenarios=cm.SCENARIOS)
    emit(f"baseline  owdoc={baseline.owdoc[:16]}  work={baseline.work[:16]}")

    killer = cm.simulate_kill_at if args.in_process else spawn_kill(timeout_s=args.park_timeout_s)
    cycles: list[Cycle] = []
    for index, (mode, boundary) in enumerate(chosen):
        cycle_dir = workspace / f"cycle{index:03d}"
        cycle_dir.mkdir(parents=True)
        at = time.perf_counter()
        result = cm.verify_boundary(
            cycle_dir,
            mode,
            boundary,
            now_ns=NOW_NS,
            now_ms=NOW_MS,
            baseline=baseline,
            kill=killer,  # type: ignore[arg-type]
        )
        cycles.append(
            Cycle(
                label=result.label,
                ok=result.ok,
                seconds=time.perf_counter() - at,
                integrity=result.integrity,
                differences=result.differences,
                reclaimed_wal_bytes=result.reclaimed_wal_bytes,
            )
        )
        if result.ok and not args.keep:
            shutil.rmtree(cycle_dir, ignore_errors=True)
    return cycles, time.perf_counter() - started


def _parser() -> argparse.ArgumentParser:
    """Every flag, in one place. The four suppressed ones are the child protocol, not a UI."""
    parser = argparse.ArgumentParser(
        description="G21 -- kill-9 at a statement boundary in Store.complete(), resume, compare."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="the nightly full matrix: every boundary of every fixture",
    )
    parser.add_argument(
        "--points", type=int, default=cm.PR_POINTS, help="how many points the PR job draws"
    )
    parser.add_argument(
        "--point",
        action="append",
        default=[],
        metavar="MODE/BOUNDARY",
        help="run exactly this point; repeatable. Reproduces one reported failure",
    )
    parser.add_argument(
        "--salt",
        default=cm.MATRIX_SALT.decode(),
        help="the blake2b sampling salt; change it to draw a different three",
    )
    parser.add_argument("--list", action="store_true", help="print the matrix and exit")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="use the in-process model instead of spawning and killing (fast local check)",
    )
    parser.add_argument(
        "--workspace", type=Path, default=None, help="where to build the stores; default a tempdir"
    )
    parser.add_argument("--keep", action="store_true", help="keep every cycle's store on disk")
    parser.add_argument(
        "--park-timeout-s",
        type=float,
        default=CHILD_PARK_TIMEOUT_S,
        help="how long to wait for a child to reach its boundary",
    )
    parser.add_argument(
        "--budget-s",
        type=int,
        default=BUDGET_S,
        help="G21's budget cell; 0 disables the check. Reported either way",
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--mode", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--boundary", default=None, help=argparse.SUPPRESS)
    return parser


def _list(args: argparse.Namespace, emit: Emit) -> int:
    """`--list`: the whole matrix, then the points this salt draws. Reproducibility, printed."""
    for mode, boundary in cm.matrix_boundaries():
        emit(f"{mode}/{boundary}")
    emit("")
    for mode, boundary in cm.kill_points(salt=args.salt.encode(), count=args.points):
        emit(f"drawn  {mode}/{boundary}")
    return EXIT_CLEAN


def _report(cycles: list[Cycle], seconds: float, args: argparse.Namespace, emit: Emit) -> int:
    """Print every cycle and decide the exit code: 0 converged, 1 diverged or over budget.

    The budget check is PR-only. `tools/gates.toml` puts `budget_s = 240` on G21's row and
    11-repo-layout.md section 6.5 puts the full matrix on the nightly `ow-bench-1` runner, so the
    cell is the three-point job's promise and `--all` is measured rather than gated.
    """
    emit("")
    for cycle in cycles:
        verdict = "ok  " if cycle.ok else "FAIL"
        emit(f"  {verdict}  {cycle.seconds:6.2f}s  {cycle.label}")
        if not cycle.ok:
            emit(f"        integrity: {cycle.integrity}")
            for difference in cycle.differences:
                emit(f"        diverged:  {difference}")
    failed = [cycle for cycle in cycles if not cycle.ok]
    scope = "full matrix" if args.all else f"{len(cycles)} point(s)"
    emit("")
    emit(f"crash  {scope} in {seconds:.1f}s  (G21 budget {args.budget_s}s)")
    if failed:
        emit(
            f"crash FAIL  {len(failed)} of {len(cycles)} cycle(s) did not converge to the "
            f"uninterrupted run."
        )
        return EXIT_FAIL
    if args.budget_s and seconds > args.budget_s and not args.all:
        emit(
            f"crash FAIL  converged, but {seconds:.1f}s exceeds G21's {args.budget_s}s budget "
            f"cell in tools/gates.toml."
        )
        return EXIT_FAIL
    emit(
        f"crash ok  {len(cycles)} kill-and-verify cycle(s); every resumed store equals the "
        f"uninterrupted run byte for byte in the .owdoc export."
    )
    return EXIT_CLEAN


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    """Draw the points, run the cycles, report. 0 converged, 1 diverged, 2 did not run."""
    emit = _emitter(sys.stdout if out is None else out)
    args = _parser().parse_args(argv)

    if args.child:
        if args.root is None or args.mode is None or args.boundary is None:
            emit("crash DID NOT RUN  --child needs --root, --mode and --boundary")
            return EXIT_NOT_RUN
        return child(args.root, args.mode, args.boundary, emit=emit)

    if args.list:
        return _list(args, emit)

    owned = args.workspace is None
    workspace = Path(tempfile.mkdtemp(prefix="ow-crash-")) if owned else args.workspace
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        cycles, seconds = _run(args, workspace, emit)
    except (ChildNeverParkedError, ValueError, OSError) as exc:
        emit(f"crash DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    finally:
        if owned and not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)

    return _report(cycles, seconds, args, emit)


if __name__ == "__main__":
    raise SystemExit(main())
