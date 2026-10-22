"""`ow bench query`: warm end-to-end query latency over a store `ow add` built. **D915.**

12-performance.md section 7.1's `query` row: *"per-Channel and end-to-end p50/p95/p99 at 10k / 1M /
10M / 20M / 30M / 50M Blocks, `vectors` off and on, each scale measured **after** an FTS5 `'merge'`
... generated stores + `fixtures/store/golden-queries.jsonl`"*, writing `query.warm_p50_ms`, B26,
B27 and **F50**. 07-store-and-retrieval.md section 4.4's per-scale table is labelled an estimate
there, and F50 is its measurement. Until now the subject was blocked on *"the retrieval Channels and
the golden query set"*: the Channels have since landed, and D915 commits the query set.

## Rulings

1. **The store is the product's.** `build()` writes `gen_5000p_pdf`'s document at `pages` into a
   project and runs `Corpus.add` on it, so the FTS indexes, heads and segments are the ones a user's
   store holds. A stub ingest would time a store no query ever reads.
2. **The FTS indexes are merged before anything is timed** (`store.maintenance.fts_merge`, until it
   reports no work left), as section 7.1 asks, so segment accumulation is not confounded with size.
3. **Warm means each query asked once, untimed, then `runs` timed passes** over the whole set
   through one SDK handle, `Corpus.query` with its defaults: `vectors` off, four Channels, as B27
   prints. Every sample is kept, and p50, p95 and p99 are `bench.Series`'s nearest rank.
4. **The clock is injected** (`omniweave_core.clock`), as `bench.Samples` takes it: library code may
   not read the machine's clock, and Windows' `monotonic_ns` is coarser than a warm query.
5. **What it does not measure is named, not approximated**: the per-Channel split (no Channel
   reports its own time to the SDK), `vectors` on (no encoder is installed by default), and every
   scale above the store built here. `F50` is the store's block count beside the p50, and whether
   the default narrowing passed `PREFILTER_MAX`, since that is where 07's estimate and a measured
   store part company.
6. **It writes no budget verdict.** `query.warm_p50_ms` is an `ow-bench-1` budget
   (12-performance.md:1966); this harness returns a value, and the runner prints the budget beside
   it as an indication, naming the machine.

## Rulings (D916)

7. **A run is kept as `.oweval` rows**, `batch_of()`: one `eval_corpus` row for the query set and
   the generator it reads (digested, so a changed set or generator is a new version), one
   `eval_run` of suite `perf` whose `hardware` names the machine, and one `eval_perf` row for
   `query.warm_p50_ms`, its `work_ns` the warm p50.
8. **The perf row's status is `unstable` or `unknown`, never `pass` or `fail`.** 12-performance.md
   section 1.2 judges a budget against its seven-run rolling median on `ow-bench-1`, and one hosted
   run is neither seven runs nor that machine. So the Pacer is read before and after the timed
   passes and the row is `unstable` when the two disagree past `INSTABILITY_PCT`, as `bench.paced`
   rules, and `unknown` otherwise. `release-check` refuses both, which is what an unpinned number
   is owed.

Specified in 12-performance.md sections 1.2, 7.1 and 7.4, rows B26, B27 and F50, and
07-store-and-retrieval.md section 4.4.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.clock import SystemClock
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.host.activate import code_fingerprint
from omniweave_core.limits import PREFILTER_MAX
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.maintenance import fts_merge
from omniweave_core.store.oweval import Batch, Corpus, Perf, Run

from omniweave.run.bench import INSTABILITY_PCT, Series, disagreement, time_ratio

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "BUDGET",
    "PROJECT",
    "QUERIES",
    "Query",
    "QueryResult",
    "batch_of",
    "build",
    "load_queries",
    "merge",
    "query",
]

QUERIES: Final = Path("fixtures") / "store" / "golden-queries.jsonl"
"""Ruling 3's set, relative to the repository root."""
QUERY_SCHEMA: Final = "omniweave.golden-queries/1"
GENERATOR: Final = Path("fixtures") / "gen" / "gen_5000p_pdf.py"
PROJECT: Final = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""Ruling 1's project: one corpus, and the three `[drivers]` opt-ins a scratch project needs."""
STORE: Final = Path(".omniweave") / "docs.owstore"
BUDGET: Final = "query.warm_p50_ms"
"""Ruling 7's `eval_perf.budget_id`, B27's committed budget."""
NOT_APPLICABLE: Final = "n/a"
MAX_MERGE_WINDOWS: Final = 64
"""Ruling 2's bound: windows of `fts_merge` before the index is reported still unmerged."""


@dataclass(frozen=True, slots=True)
class Query:
    """One row of the golden set."""

    id: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    """What one bench run measured, and what it did not (ruling 5)."""

    pages: int
    blocks: int
    runs: int
    total: Series
    by_kind: tuple[Series, ...]
    merged: bool
    narrowing_all: bool
    not_measured: tuple[str, ...]
    pacer_before_ns: int = 0
    pacer_after_ns: int = 0
    """Ruling 8: the Pacer read just before and just after the timed passes; 0 is not read."""


def load_queries(root: Path) -> tuple[Query, ...]:
    """Ruling 3's set, its schema line checked."""
    lines = (root / QUERIES).read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0]) if lines else {}
    if head.get("schema") != QUERY_SCHEMA:
        msg = f"{QUERIES.as_posix()} is not {QUERY_SCHEMA}; regenerate it"
        raise ValueError(msg)
    return tuple(
        Query(id=str(row["id"]), kind=str(row["kind"]), text=str(row["text"]))
        for row in map(json.loads, lines[1:])
    )


def build(root: Path, project: Path, *, pages: int) -> Path:
    """Ruling 1: the generated document at `pages`, added by `ow add` into `project`."""
    import omniweave  # noqa: PLC0415 -- the SDK is the product path, imported where it is used

    spec = importlib.util.spec_from_file_location("_ow_bench_gen5000p", root / GENERATOR)
    if spec is None or spec.loader is None:
        msg = f"no generator at {GENERATOR.as_posix()}"
        raise ValueError(msg)
    generator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = generator
    spec.loader.exec_module(generator)
    docs = project / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    generator.generate(docs / f"gen{pages:05d}p.pdf", pages=pages)
    (project / "omniweave.toml").write_bytes(PROJECT.encode())
    corpus = omniweave.corpus(None, config=project / "omniweave.toml", cwd=project, readonly=False)
    corpus.add([str(docs)])
    return project / STORE


def merge(store: Path) -> bool:
    """Ruling 2: merge every FTS index until it reports no work left; whether it got there."""
    connection = store_sqlite.connect(store)
    try:
        return any(fts_merge(connection).exhausted for _ in range(MAX_MERGE_WINDOWS))
    finally:
        connection.close()


def query(
    project: Path,
    queries: Sequence[Query],
    *,
    pages: int,
    runs: int,
    merged: bool,
    clock: Clock | None = None,
) -> QueryResult:
    """Rulings 3-5: the set asked once untimed, then `runs` timed passes, every sample kept."""
    import omniweave  # noqa: PLC0415 -- as in `build`

    if runs < 1:
        msg = f"--runs {runs}; a warm measurement needs at least one timed pass"
        raise ValueError(msg)
    timer = clock if clock is not None else SystemClock()
    corpus = omniweave.corpus(None, config=project / "omniweave.toml", cwd=project, readonly=True)
    for one in queries:
        corpus.query(one.text)
    samples: dict[str, list[float]] = {}
    for _ in range(runs):
        for one in queries:
            start = timer.monotonic_ns()
            corpus.query(one.text)
            samples.setdefault(one.kind, []).append((timer.monotonic_ns() - start) / 1e6)
    blocks = _blocks(project / STORE)
    return QueryResult(
        pages=pages,
        blocks=blocks,
        runs=runs,
        total=Series.of("end-to-end", [ms for kind in samples.values() for ms in kind]),
        by_kind=tuple(Series.of(kind, values) for kind, values in samples.items()),
        merged=merged,
        narrowing_all=blocks > PREFILTER_MAX,
        not_measured=(
            "per-Channel p50/p95/p99: no Channel reports its own time to the SDK",
            "vectors on: no encoder is installed by default",
            f"every scale above {blocks:,} blocks: this run built one store",
        ),
    )


def _blocks(store: Path) -> int:
    """The store's live blocks, for F50's scale column."""
    connection = store_sqlite.connect_readonly(store)
    try:
        row = connection.execute("SELECT count(*) FROM block WHERE state = 0").fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


def batch_of(
    root: Path, result: QueryResult, *, machine: str, started_ns: int, ended_ns: int
) -> Batch:
    """Rulings 7 and 8: the corpus, the `perf` run and its `query.warm_p50_ms` row."""
    pacer_before_ns, pacer_after_ns = result.pacer_before_ns, result.pacer_after_ns
    if pacer_before_ns <= 0 or pacer_after_ns <= 0:
        msg = "a perf row needs the Pacer read before and after the timed passes"
        raise ValueError(msg)
    digest = _digest(root, (QUERIES, GENERATOR))
    corpus = Corpus(
        corpus_id=QUERIES.as_posix(),
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=1,
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    hardware = f"{machine} ({platform.system().lower()}-{platform.machine().lower()})"
    run_id = hashlib.blake2b(
        f"perf\x00omniweave\x00{digest}\x00{started_ns}".encode(), digest_size=16
    ).hexdigest()
    run = Run(
        run_id=run_id,
        suite="perf",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=digest,
        subject="omniweave",
        subject_version=version("omniweave"),
        producer_id=None,
        measured_on=MeasuredOn(
            weights=NOT_APPLICABLE,
            weights_revision=NOT_APPLICABLE,
            runtime=platform.python_implementation().lower(),
            runtime_version=platform.python_version(),
            sampling=NOT_APPLICABLE,
            prompt_version=NOT_APPLICABLE,
            hardware=hardware,
            corpus=f"{corpus.corpus_id}@{corpus.version}",
            corpus_digest=digest,
            harness_version=version("omniweave"),
        ),
        timing_basis="in_process",
        witness="self",
        cassette="off",
        policy_digest=None,
        pricebook_digest=None,
        harness_version=version("omniweave"),
        code_fingerprint=code_fingerprint(_sources()),
        hardware=hardware,
        started_ns=started_ns,
        ended_ns=ended_ns,
        status="ok",
        not_measured=(
            *result.not_measured,
            f"{BUDGET} pass or fail: the seven-run rolling median on ow-bench-1, which one run "
            f"on {machine} is not",
        ),
        confounders=(
            f"{result.blocks:,} blocks from {result.pages:,} generated pages, "
            f"FTS {'merged' if result.merged else 'not fully merged'}",
        ),
    )
    unstable = disagreement(pacer_before_ns, pacer_after_ns) * 100 > INSTABILITY_PCT
    work_ns = round(result.total.p50 * 1e6)
    perf = Perf(
        run_id=run_id,
        budget_id=BUDGET,
        pacer_before_ns=pacer_before_ns,
        pacer_after_ns=pacer_after_ns,
        work_ns=work_ns,
        time_ratio=time_ratio(work_ns, pacer_before_ns, pacer_after_ns),
        peak_rss_bytes=None,
        peak_wal_bytes=None,
        status="unstable" if unstable else "unknown",
    )
    return Batch(corpora=(corpus,), runs=(run,), perf=(perf,))


def _digest(root: Path, files: Sequence[Path]) -> str:
    """Ruling 7: sha256 over each file's path and bytes, NUL-framed, in the order given."""
    framed = hashlib.sha256()
    for relpath in files:
        framed.update(relpath.as_posix().encode() + b"\x00")
        framed.update(hashlib.sha256((root / relpath).read_bytes()).hexdigest().encode() + b"\x00")
    return framed.hexdigest()


def _sources() -> list[Path]:
    """Ruling 7's fingerprint: the store and retrieval code a query runs through."""
    import omniweave_core  # noqa: PLC0415 -- its path, not its contents

    base = Path(omniweave_core.__file__).parent
    return sorted(path for sub in ("store", "retrieve") for path in (base / sub).rglob("*.py"))
