"""Eval staging: one NDJSON file per worker, and the import that makes them one write. **D815.**

13-quality.md section 2.10: *"no test process ever opens `.oweval`. Each worker appends
newline-delimited JSON to `eval/staging/<run_id>.<worker_id>.ndjson`, one object per verdict,
counter or perf reading, and owns that file exclusively -- no locking, no `busy_timeout`, no
contention. `ow eval import` runs once at job end, reads every staging file ... and writes
`.oweval` in **one** transaction."* `StagingWriter` is the worker's half and `import_staging()`
the job's; the transaction is `omniweave_core.store.oweval.write()`'s (D814).

A worker that dies mid-write leaves a truncated final line, and 13:389-391 says what follows:
*"The importer drops it, counts it into `not_measured[]`, and sets `eval_run.status = 'partial'` --
never `'ok'`, and never silently."* Section 8.7 widens `partial` to a run in which any assertion
produced no verdict.

## Rulings

1. **A staging line is one row**: `{"t": <table>, ...the row's fields}`, keys sorted, compact,
   one line, written whole and flushed. `t` is `eval_verdict`, `eval_counter` or `eval_perf`, the
   three 13:383 names.
2. **A writer owns its file.** It opens `<run_id>.<worker_id>.ndjson` in exclusive-create mode,
   so a second writer for the same worker fails rather than interleaving. `worker_id` may not hold
   a dot, so the name parses back; neither part may hold a path separator or NUL.
3. **Only a final line may be truncated.** The bytes after a file's last newline are a write that
   did not finish: they are dropped undecoded, since the cut may fall inside a character, and
   named in the run's `not_measured`. A line that ended and does not parse refuses the import,
   naming the file and line: that is corruption, not a death.
4. **A row belongs to its file's run.** A line whose `run_id` is not the file's is refused.
5. **The run row is the caller's**, because its `MeasuredOn`, corpus and timing basis are the
   controller's and no worker's. The importer only lowers its status: to `partial` when a file of
   the run lost a line or an assertion of the run's corpus has no verdict, and never above what the
   caller gave, so an `unknown` run stays `unknown`. Each loss is a `not_measured` entry, after the
   caller's own: one per truncated file, and one per slice with a missing assertion, counting it
   against the slice's total (13:1338, *"names the missing slices and the reason"*). An assertion
   with no slices counts against `*`. A `rejected` assertion is not expected to answer: 13:1022
   gives `checked` three states, and only `NULL`'s is *"runs and never scores"*; one a reviewer
   rejected is out of the benchmark, so its silence is not a loss.
6. **One import is one write**, of the corpora, assertions, runs and every staged row. A run
   already in the file is refused by the store, so a second import of the same staging fails
   whole and writes nothing. The staging files are left where they are.

Specified in 13-quality.md sections 2.10 and 8.7.
"""

from __future__ import annotations

import json
from collections import Counter as Tally
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.store.oweval import (
    Assertion,
    Batch,
    Corpus,
    Counter,
    Perf,
    Run,
    Verdict,
    open_oweval,
    write,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "SUFFIX",
    "Imported",
    "Staged",
    "StagingError",
    "StagingWriter",
    "import_staging",
    "read_staging",
    "staging_path",
]

SUFFIX: Final = ".ndjson"
UNSLICED: Final = "*"
REJECTED: Final = "rejected"
"""`eval_assertion.checked`'s review verdict against an assertion, which therefore does not run."""
_ROWS: Final[Mapping[str, type[Verdict | Counter | Perf]]] = {
    Verdict.TABLE: Verdict,
    Counter.TABLE: Counter,
    Perf.TABLE: Perf,
}
_STATUS_RANK: Final = {"ok": 0, "partial": 1, "unknown": 2}


class StagingError(ValueError):
    """A staging file that is corrupt rather than truncated, or a name that cannot be one."""


def staging_path(root: Path, run_id: str, worker_id: str) -> Path:
    """`<root>/<run_id>.<worker_id>.ndjson` (13:382), refusing a name that would not parse back."""
    for label, part in (("run_id", run_id), ("worker_id", worker_id)):
        if not part or any(c in part for c in "/\\\x00"):
            raise StagingError(f"{label} {part!r} cannot name a staging file")
    if "." in worker_id:
        raise StagingError(f"worker_id {worker_id!r} may not contain a dot")
    return root / f"{run_id}.{worker_id}{SUFFIX}"


class StagingWriter:
    """One worker's staging file, opened exclusively (ruling 2). A context manager."""

    def __init__(self, root: Path, run_id: str, worker_id: str) -> None:
        self.run_id = run_id
        self.path = staging_path(root, run_id, worker_id)
        root.mkdir(parents=True, exist_ok=True)
        self._out: TextIO = self.path.open("x", encoding="utf-8", newline="\n")

    def __enter__(self) -> StagingWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._out.close()

    def add(self, row: Verdict | Counter | Perf) -> None:
        """Append `row` as one whole line, flushed (ruling 1)."""
        if row.run_id != self.run_id:
            raise StagingError(f"a row of {row.run_id!r} cannot be staged for {self.run_id!r}")
        line = json.dumps({"t": row.TABLE, **asdict(row)}, sort_keys=True, separators=(",", ":"))
        self._out.write(line + "\n")
        self._out.flush()


@dataclass(frozen=True, slots=True)
class Staged:
    """Every row a staging directory holds, and the files whose final line was dropped."""

    verdicts: tuple[Verdict, ...]
    counters: tuple[Counter, ...]
    perf: tuple[Perf, ...]
    truncated: tuple[tuple[str, str], ...]
    """`(run_id, file name)` for each file that lost its final line."""


@dataclass(frozen=True, slots=True)
class Imported:
    """What one import wrote: each run's final status, and the row counts."""

    status: Mapping[str, str]
    verdicts: int
    counters: int
    perf: int
    dropped: int


def read_staging(root: Path) -> Staged:
    """Every `*.ndjson` under `root`, in name order (rulings 3 and 4)."""
    rows: dict[str, list[Any]] = {table: [] for table in _ROWS}
    truncated = []
    for path in sorted(root.glob(f"*{SUFFIX}")):
        run_id = path.name.removesuffix(SUFFIX).rpartition(".")[0]
        whole, _, tail = path.read_bytes().rpartition(b"\n")
        if tail:  # a write that did not finish, never decoded: it may end mid-character
            truncated.append((run_id, path.name))
        for number, raw in enumerate(whole.split(b"\n") if whole else (), 1):
            row = _row(raw)
            if row is None:
                raise StagingError(f"{path.name}:{number} is not a staging row")
            if row.run_id != run_id:
                raise StagingError(f"{path.name}:{number} is a row of {row.run_id!r}")
            rows[row.TABLE].append(row)
    return Staged(
        verdicts=tuple(rows[Verdict.TABLE]),
        counters=tuple(rows[Counter.TABLE]),
        perf=tuple(rows[Perf.TABLE]),
        truncated=tuple(truncated),
    )


def _row(line: bytes) -> Verdict | Counter | Perf | None:
    try:
        fields = json.loads(line.decode("utf-8"))
        kind = _ROWS[fields.pop("t")]
        return kind(**fields)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def import_staging(
    oweval_path: Path,
    staging_root: Path,
    *,
    corpora: Iterable[Corpus],
    assertions: Iterable[Assertion],
    runs: Iterable[Run],
) -> Imported:
    """Read every staging file, settle each run's status, and write it all in one transaction."""
    staged = read_staging(staging_root)
    corpus_rows, assertion_rows, run_rows = tuple(corpora), tuple(assertions), tuple(runs)
    bad = sorted(run.run_id for run in run_rows if run.status not in _STATUS_RANK)
    if bad:
        raise StagingError(f"runs with a status outside {sorted(_STATUS_RANK)}: {bad}")
    settled = tuple(_settle(run, staged, assertion_rows) for run in run_rows)
    named = {row.run_id for row in (*staged.verdicts, *staged.counters, *staged.perf)}
    named |= {run_id for run_id, _ in staged.truncated}
    strays = sorted(named - {run.run_id for run in settled})
    if strays:
        raise StagingError(f"staged rows name runs the import was not given: {strays}")
    batch = Batch(
        corpora=corpus_rows,
        assertions=assertion_rows,
        runs=settled,
        verdicts=staged.verdicts,
        counters=staged.counters,
        perf=staged.perf,
    )
    connection = open_oweval(oweval_path)
    try:
        write(connection, batch)
    finally:
        connection.close()
    return Imported(
        status={run.run_id: run.status for run in settled},
        verdicts=len(staged.verdicts),
        counters=len(staged.counters),
        perf=len(staged.perf),
        dropped=len(staged.truncated),
    )


def _settle(run: Run, staged: Staged, assertions: Sequence[Assertion]) -> Run:
    """Ruling 5: the caller's run, its status lowered and its losses named."""
    lost = [
        f"{name}: a truncated final line, dropped"
        for rid, name in staged.truncated
        if rid == run.run_id
    ]
    ours = [
        a
        for a in assertions
        if (a.corpus_id, a.corpus_version) == (run.corpus_id, run.corpus_version)
        and a.checked != REJECTED
    ]
    answered = {v.assertion_id for v in staged.verdicts if v.run_id == run.run_id}
    total, missing = Tally[str](), Tally[str]()
    for assertion in ours:
        for key in assertion.slices or (UNSLICED,):
            total[key] += 1
            if assertion.assertion_id not in answered:
                missing[key] += 1
    lost += [
        f"{key}: {missing[key]} of {total[key]} assertions produced no verdict"
        for key in sorted(missing)
    ]
    if not lost:
        return run
    status = run.status if _STATUS_RANK[run.status] > _STATUS_RANK["partial"] else "partial"
    return replace(run, status=status, not_measured=(*run.not_measured, *lost))
