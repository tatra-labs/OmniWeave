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

Specified in 12-performance.md sections 7.1 and 7.4, rows B26, B27 and F50, and
07-store-and-retrieval.md section 4.4.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.clock import SystemClock
from omniweave_core.limits import PREFILTER_MAX
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.maintenance import fts_merge

from omniweave.run.bench import Series

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "PROJECT",
    "QUERIES",
    "Query",
    "QueryResult",
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
