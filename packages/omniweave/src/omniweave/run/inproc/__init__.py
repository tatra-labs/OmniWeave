"""`ow bench inproc`: F2's marshal question, over `fixtures/office-200`. **D656.**

12-performance.md section 7.1's row: *"wall, peak RSS and GIL-held fraction at `max_inproc` in
{1,2,4,8} against the pure-Rust path"*, writing B02/B03 and closing **F2**, whose fallback is
anydoc's fork trigger. 17-risks.md K-9 states the line: *"F2 shows the anydoc eager marshal
exceeding 30% of wall time"*. And ADR-13 D13.2 hangs `rss.office200_peak_bytes` on the same
corpus: the peak RSS of `parse.office.anydoc`'s S4 worker, the clause-2 tripwire in
`vendor/anydoc/FORK-TRIGGER.md`.

## What is measured, and the one comparison that does not mean what it sounds like

`anydoc.to_document(data, fmt)` decodes inside `py.detach` (`vendor/anydoc/python/src/lib.rs:194`)
and then marshals the whole `Document` into Python objects with the GIL held. `to_markdown_bytes`
is the pure-Rust path: the decode and a Markdown render, all detached, and one string back. So:

* **GIL-held fraction is the measurement F2 asks for.** The marshal is exactly the part of
  `to_document` that holds the GIL, and a GIL held is time no other thread in the host -- the
  Supervisor, the store thread, another in-process driver -- can run. `_Probe` measures it: a
  thread that loops on `time.sleep(0)`, which drops the GIL and asks for it straight back. Under a
  100 µs switch interval a free GIL comes back in a few microseconds and a held one only when the
  holder is made to yield, so the probe spends almost exactly the time another thread holds the
  GIL waiting for it: the sum of its slow iterations over the wall is the held fraction. It costs
  one busy core, and each child first probes one idle second, so the report carries the
  instrument's own floor (about 1% on the build machine) beside every figure.
  **Why not a sleeping sampler.** The first version slept 1 ms and counted late wake-ups. Windows
  wakes a 1 ms sleep late often enough that the pure-Rust path read 21%, the same as the marshal:
  it measured the timer, and a GIL held under a 100 µs interval delays a waiter by less than any
  usable threshold anyway.
* **Wall against the pure-Rust path is printed and is not the marshal's cost.** The Markdown
  render is Rust work `to_document` does not do; over this corpus `to_markdown_bytes` was the
  SLOWER of the two (8.7 s against 7.6 s single-threaded on the build machine), so `wall(document)
  - wall(rust)` is negative and means nothing about the marshal. The two walls side by side do say
  whether threads help each path, which is B02/B03's question.
* **Peak RSS is per configuration**, so each one runs in its own child process
  (`python -m omniweave.run.inproc child ...`): a process's peak never comes down, and a
  second configuration in the same process would report the first one's.
* **`rss.office200_peak_bytes` is the S4 worker's**, not the child's. `ow add` over a scratch
  project holding the corpus, on the drivers a checkout resolves, and the largest
  `work.peak_rss_bytes` of the `parse.office.anydoc` rows -- the host's job-wide sample (D629), as
  `tools/measure_store.py` reads `rss.gen5000p_peak_bytes`.

Every document's bytes are read before the clock starts, so the timed loop calls anydoc and
nothing else. A document anydoc refuses is counted, not raised: the corpus is generated to parse
(D656 measured 200 of 200), and a refusal in a later anydoc is a fact the report should carry.

**Library code, under the library's rules (G8).** The clock is a `Clock`, `SystemClock` by default,
whose `monotonic_ns` is `perf_counter_ns` where the interpreter reports it monotonic; the children
run through `host.subproc.run_captured`, the one sanctioned run-and-capture; the store is read
through `store.sqlite.connect_readonly`; and the child's entry point is this package's
`__main__.py`, the one place a `SystemExit` belongs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.clock import SystemClock
from omniweave_core.host.subproc import peak_rss_bytes, run_captured
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "MODES",
    "THREADS",
    "InprocPoint",
    "InprocResult",
    "WorkerPeak",
    "inproc",
    "main",
]

MODES: Final[tuple[str, ...]] = ("rust", "document")
"""`rust` is `to_markdown_bytes`, the pure-Rust path; `document` is `to_document`, the marshal."""

THREADS: Final[tuple[int, ...]] = (1, 2, 4, 8)
"""12:1471's `max_inproc` points."""

SWITCH_INTERVAL_S: Final = 0.0001
"""The child's `sys.setswitchinterval`: a held GIL is surrendered to the probe within 100 µs."""

BLOCKED_NS: Final = 20_000
"""A probe iteration slower than this waited for the GIL. A free one returns in a few µs."""

IDLE_S: Final = 1.0
"""How long each child probes with nothing running, for the instrument's floor."""

PROJECT_TOML: Final = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""The scratch project the worker measurement ingests: one corpus, named for the built-in
`serve.default_corpus` so `ow add` resolves it, and the three `[drivers]`
opt-ins a checkout needs before a first-party driver resolves (D576). `inproc = []` puts anydoc in
its S4 worker, which is the process `rss.office200_peak_bytes` bounds."""

OFFICE_DRIVER: Final = "parse.office.anydoc"
CHILD_TIMEOUT_S: Final = 900
"""One configuration's child: the corpus decodes in about ten seconds on one thread."""

ADD_TIMEOUT_S: Final = 7_200
"""Two hours. Every spreadsheet cell is a Block and the store writes about 1,200 a second, so
the corpus's million-odd cells are most of a 20-30 minute ingest on the build machine (D656)."""


@dataclass(frozen=True, slots=True)
class InprocPoint:
    """One `(mode, threads)` configuration, run in its own process."""

    mode: str
    threads: int
    documents: int
    refused: int
    wall_s: float
    peak_rss: int | None
    peak_rss_source: str
    gil_held: float
    gil_idle: float

    @property
    def docs_per_s(self) -> float:
        return self.documents / self.wall_s if self.wall_s else 0.0


@dataclass(frozen=True, slots=True)
class WorkerPeak:
    """`rss.office200_peak_bytes`'s measurement: the anydoc worker's peak over the corpus."""

    peak_rss: int | None
    rows: int
    done: int
    seconds: float
    how: str = "work.peak_rss_bytes: the host's sample over the worker's job (D629)"


@dataclass(frozen=True, slots=True)
class InprocResult:
    corpus: Path
    documents: int
    corpus_bytes: int
    points: tuple[InprocPoint, ...]
    worker: WorkerPeak | None


# =============================================================================================
# The parent: one child per configuration, then the worker
# =============================================================================================


def inproc(
    corpus: Path,
    *,
    workspace: Path,
    threads: Sequence[int] = THREADS,
    modes: Sequence[str] = MODES,
    worker: bool = True,
    python: str = sys.executable,
    clock: Clock | None = None,
) -> InprocResult:
    """Run every `(mode, threads)` point in a fresh child, then `ow add` for the worker's peak."""
    clock = clock or SystemClock()
    files = _files(corpus)
    if not files:
        msg = (
            f"{corpus} holds no documents; `uv run python fixtures/gen/gen_office200.py` writes it"
        )
        raise ValueError(msg)
    points = tuple(_child(python, corpus, mode=mode, threads=n) for mode in modes for n in threads)
    peak = _worker_peak(corpus, workspace, python, clock) if worker else None
    return InprocResult(
        corpus=corpus,
        documents=len(files),
        corpus_bytes=sum(path.stat().st_size for path in files),
        points=points,
        worker=peak,
    )


def _files(corpus: Path) -> list[Path]:
    return sorted(path for path in corpus.rglob("*") if path.is_file())


def _child(python: str, corpus: Path, *, mode: str, threads: int) -> InprocPoint:
    argv = [python, "-m", "omniweave.run.inproc", "child", "--mode", mode]
    argv += ["--threads", str(threads), "--corpus", str(corpus)]
    done = run_captured(
        argv, stdin=b"", cwd=str(corpus), env=dict(os.environ), timeout_s=CHILD_TIMEOUT_S
    )
    if done.returncode != 0:
        said = done.failed or done.stderr.decode("utf-8", "replace")[-800:]
        msg = f"the {mode} x {threads} child exited {done.returncode}: {said}"
        raise RuntimeError(msg)
    lines = done.stdout.decode("utf-8").strip().splitlines()
    return InprocPoint(**json.loads(lines[-1]))


def _worker_peak(corpus: Path, workspace: Path, python: str, clock: Clock) -> WorkerPeak:
    """`ow add` over a scratch project holding the corpus; the anydoc rows' largest peak."""
    project = workspace / "project"
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(corpus, project / "docs")
    (project / "omniweave.toml").write_text(PROJECT_TOML, encoding="utf-8")
    env = {**os.environ, "OMNIWEAVE_HOME": str(workspace / "owhome")}
    started = clock.monotonic_ns()
    done = run_captured(
        [python, "-m", "omniweave", "add", "docs"],
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=ADD_TIMEOUT_S,
    )
    seconds = (clock.monotonic_ns() - started) / 1e9
    if done.returncode is None:
        msg = f"ow add over {corpus} did not finish ({done.failed}); the project is {project}"
        raise RuntimeError(msg)
    if done.returncode != 0:
        said = (done.stdout + done.stderr).decode("utf-8", "replace")[-800:]
        msg = f"ow add exited {done.returncode}: {said}"
        raise RuntimeError(msg)
    connection = ow.connect_readonly(project / ".omniweave" / "index.owstore")
    try:
        rows = connection.execute(
            "SELECT status, peak_rss_bytes FROM work WHERE driver = ?", (OFFICE_DRIVER,)
        ).fetchall()
    finally:
        connection.close()
    peaks = [int(peak) for _, peak in rows if peak]
    return WorkerPeak(
        peak_rss=max(peaks) if peaks else None,
        rows=len(rows),
        done=sum(1 for status, _ in rows if status == "done"),
        seconds=round(seconds, 1),
    )


# =============================================================================================
# The child: one configuration, one process, one JSON line
# =============================================================================================


class _Probe(threading.Thread):
    """Loops on `time.sleep(0)` and sums the iterations that had to wait for the GIL."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(name="gil-probe", daemon=True)
        self.stop = threading.Event()
        self.blocked_ns = 0
        self.elapsed_ns = 0
        self._now = clock.monotonic_ns

    def run(self) -> None:
        now = self._now
        started = now()
        while not self.stop.is_set():
            before = now()
            time.sleep(0)
            waited = now() - before
            if waited > BLOCKED_NS:
                self.blocked_ns += waited
        self.elapsed_ns = now() - started

    @property
    def held(self) -> float:
        return round(self.blocked_ns / self.elapsed_ns, 4) if self.elapsed_ns else 0.0


def _probed(run: Callable[[], object], clock: Clock) -> tuple[float, float]:
    """`(wall seconds, GIL-held fraction)` of `run()`, with the probe running beside it."""
    probe = _Probe(clock)
    probe.start()
    started = clock.monotonic_ns()
    try:
        run()
    finally:
        wall = (clock.monotonic_ns() - started) / 1e9
        probe.stop.set()
        probe.join()
    return wall, probe.held


def _self_peak() -> tuple[int | None, str]:
    """This process's own peak: psapi on Windows, `ru_maxrss` (KiB on Linux) elsewhere."""
    if sys.platform == "win32":
        return peak_rss_bytes(os.getpid())
    import resource  # noqa: PLC0415 -- POSIX only

    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":  # pragma: no cover -- not a machine this was built on
        return (raw, "getrusage ru_maxrss (bytes, darwin)")
    return (raw * 1024, "getrusage ru_maxrss (KiB on linux, scaled to bytes)")


def _child_main(mode: str, threads: int, corpus: Path, clock: Clock) -> dict[str, object]:
    import anydoc  # noqa: PLC0415 -- the child only: the parent never loads the decoder

    work = [(path.read_bytes(), path.suffix[1:]) for path in _files(corpus)]
    call = anydoc.to_markdown_bytes if mode == "rust" else anydoc.to_document

    def one(item: tuple[bytes, str]) -> bool:
        try:
            call(item[0], cast("Any", item[1]))  # a `Format` literal, by extension
        except Exception:  # a refusal is counted; see the module docstring
            return False
        return True

    sys.setswitchinterval(SWITCH_INTERVAL_S)
    _, idle = _probed(lambda: time.sleep(IDLE_S), clock)
    results: list[bool] = []

    def run() -> None:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            results.extend(pool.map(one, work))

    wall, held = _probed(run, clock)
    refused = results.count(False)
    peak, source = _self_peak()
    point = InprocPoint(
        mode=mode,
        threads=threads,
        documents=len(work),
        refused=refused,
        wall_s=round(wall, 3),
        peak_rss=peak,
        peak_rss_source=source,
        gil_held=held,
        gil_idle=idle,
    )
    return asdict(point)


def main(argv: Sequence[str] | None = None) -> int:
    """The child's command line: one configuration, one JSON line on stdout."""
    parser = argparse.ArgumentParser(prog="python -m omniweave.run.inproc")
    sub = parser.add_subparsers(dest="command", required=True)
    child = sub.add_parser("child", help="one configuration; prints one JSON line")
    child.add_argument("--mode", choices=MODES, required=True)
    child.add_argument("--threads", type=int, required=True)
    child.add_argument("--corpus", type=Path, required=True)
    args = parser.parse_args(argv)
    point = _child_main(args.mode, args.threads, args.corpus, SystemClock())
    sys.stdout.write(json.dumps(point) + "\n")
    return 0
