"""The absence suite's deterministic half: every built Injector damaged, read, fixed, read again.

**D869.** 13-quality.md section 8.6's paired-damage half, which `tools/ow_damage.py` has run since
P6 as *"`ow eval run --suite absence --deterministic-half`"* while `ow eval` did not exist. The
library half was always here (`damage`: the thirteen-row table, the Injectors built and
`assess()`); this module is the harness the script held, moved so the verb can run it. The script
now calls it.

## One `(Injector, fixture)` pair, four runs

1. **pristine**: the fixture's documents through a real `ow add`, shared by every pair over the
   same documents.
2. **damaged**: the same documents with the Injector applied to one file, under `PROJECT` and the
   Injector's own `config`.
3. **the fix**: the damaged run's `DegradeCause.fix` for the expected gate, split by
   `damage.split_fix()`, admitted by the caller's `admit`, and run as an `ow` child with no shell.
   A source-bytes Injector restores the file first; `encrypt` and `inflate` repair what their
   cause's detail tells a user to (D640, D643, D644).
4. **fixed**: the verdict after the fix, which must be the pristine run's.

## Rulings

1. **`admit` is the caller's.** 13:1306 parses the fix against the `ow` Action registry, which is
   `omniweave`'s, and this distribution may not import it (`tools/layers.toml`). So the check is a
   parameter: `omniweave.surface.admit.admit`, handed in by the verb and by the script. It takes
   and returns builtins, an argv and `str | None`.
2. **Every `ow` is a child**, with the fixture's own `HOME` and `OMNIWEAVE_HOME`, as the script
   ran them: `ow add` and the fix. A query is one read-only `execute()` in this process, which is
   what `ow query` runs, so the assertions read the `Verdict` and never the prose.
3. **The clock is injected.** `ask()` takes `now_ns`, the reader's wall clock, as every library
   read does, where the script read `time.time_ns()`.
4. **The fixtures are generated** by the repository's `fixtures/gen/gen_reference_corpora.py` at
   `quick` scale, loaded from `root`, so the suite runs from a checkout, as the register's
   `[[subject]]` paths require too.
5. **A question is asked under `HARNESS_BUDGET_SCALE` times the shipped query budget** (D942).
   The suite judges honesty, not latency. Under the shipped 15-80 ms channel budgets, a slow CI
   runner's first query after a fresh `ow add` overran one, and gate 1 `timed_out` fired on a
   run that was otherwise its pristine self, so `mask_format`'s fix read as failing twice on
   Windows CI. Scaling every figure keeps the channels plus the reserve equal to `query_ms`, as
   `ow route lint` check 3 requires; the snapshot is held at `MAX_SNAPSHOT_MS`. The test tree's
   own scaling (`packages/conftest.py`, D689) never reached here: the suite runs as
   `tools/ow_damage.py` or `ow eval run`, a process of its own with the shipped defaults. The
   `stall` Injector, when built, damages a deadline of its own.

Specified in 13-quality.md sections 8.6 and 13.3, and 16-roadmap.md section 9's P6 exit line.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave_core.host.subproc import Captured, run_captured

from omniweave_conform.damage import (
    INJECTORS,
    Assessment,
    FixRefusedError,
    Injector,
    Observed,
    assess,
    observed,
    split_fix,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from types import ModuleType

    from omniweave_core.retrieve.types import QueryBudget

__all__ = [
    "ADD_TIMEOUT_S",
    "FIXTURES",
    "GENERATOR",
    "HARNESS_BUDGET_SCALE",
    "PROJECT",
    "Damaged",
    "Fixture",
    "Suite",
    "build",
    "documents_digest",
    "documents_of",
    "generator",
    "harness_budget",
    "run_pair",
    "run_suite",
]

ADD_TIMEOUT_S: Final = 600
GENERATOR: Final = Path("fixtures") / "gen" / "gen_reference_corpora.py"
"""Ruling 4: the generator, relative to the checkout's root."""

PROJECT: Final = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""`bench/serve/first_answer.py`'s project: one corpus, the default, and D576's three opt-ins."""


@dataclass(frozen=True, slots=True)
class Fixture:
    """Documents from one reference corpus, the file to damage, and the question to ask."""

    corpus: str
    paths: tuple[str, ...]
    target: str
    question: str

    @property
    def name(self) -> str:
        return f"{self.corpus}/{self.target}"


_ARCHIVE: Final = (
    "insurance/home-policy-2024.pdf",
    "letters/oakridge-renewal-2024.docx",
    "medical/lab-results-2024.pdf",
    "tax/tax-summary-2023.docx",
)

_ROOM: Final = (
    "finance/cap-table-2024.xlsx",
    "hr/headcount-2024.xlsx",
    "legal/nda-northwind.docx",
)

_LDL: Final = Fixture(
    "personal_archive",
    _ARCHIVE,
    "medical/lab-results-2024.pdf",
    "What was the LDL cholesterol result in the 2024 lab results?",
)
_FLOOD: Final = Fixture(
    "personal_archive",
    _ARCHIVE,
    "insurance/home-policy-2024.pdf",
    "What does section 5 of the home insurance policy say about flood damage?",
)

FIXTURES: Final[Mapping[str, tuple[Fixture, ...]]] = {
    "encrypt": (_LDL, _FLOOD),
    "chaos": (
        Fixture(
            "data_room",
            _ROOM,
            "hr/headcount-2024.xlsx",
            "What total headcount does the 2024 headcount report give?",
        ),
        _LDL,
    ),
    "inflate": (_LDL, _FLOOD),
    "mask_format": (
        Fixture(
            "personal_archive",
            _ARCHIVE,
            "tax/tax-summary-2023.docx",
            "What refund does the 2023 tax summary show?",
        ),
        _LDL,
    ),
}
"""Each built Injector's fixtures: an OOXML file and a PDF, the two structures detection reads.
`encrypt` applies to a PDF alone (ADR-15 D15.6), so both of its fixtures are PDFs, one page and
three. So do `inflate`'s, padded to one page above `INFLATE_MAX_PARTS`: by three pages and by one.
Masked, they are the two ways it names a format (`route/detect.py` steps 2 and 3); cut, they are
the two structural checks of `unit.corrupt`, a ZIP central directory and a PDF trailer (D641).
`chaos` takes its OOXML file from the data room, a spreadsheet, as the bench's own task does."""


@dataclass(frozen=True, slots=True)
class Damaged:
    """One pair's damaged run, and the run after its fix, or why the fix did not run."""

    damaged: Observed
    fixed: Observed | None
    refusal: str | None


@dataclass(frozen=True, slots=True)
class Suite:
    """One run of the deterministic half: every pair's assessment, and the documents it read."""

    assessments: tuple[Assessment, ...]
    documents: Mapping[str, bytes]
    """Every document any pair read, keyed `<corpus>/<path>`, for the corpus digest."""


def generator(root: Path) -> ModuleType:
    """The checkout's reference-corpus generator, loaded once by path (ruling 4)."""
    path = root / GENERATOR
    spec = importlib.util.spec_from_file_location("omniweave_gen_reference_corpora", path)
    if spec is None or spec.loader is None or not path.is_file():
        msg = f"cannot load the reference-corpus generator at {path}"
        raise RuntimeError(msg)
    module = sys.modules.get(spec.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def documents_of(fixture: Fixture, root: Path) -> dict[str, bytes]:
    """The fixture's documents, the generator's own bytes at `quick` scale (ruling 4)."""
    wanted = set(fixture.paths)
    found = {
        doc.path: doc.to_bytes()
        for doc in generator(root).documents(fixture.corpus, "quick")
        if doc.path in wanted
    }
    missing = wanted - set(found)
    if missing:
        msg = f"{fixture.corpus} has no {sorted(missing)} at quick scale"
        raise RuntimeError(msg)
    return found


def _env(work: Path) -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {**kept, "HOME": str(home), "USERPROFILE": str(home), "OMNIWEAVE_HOME": str(work / "ow")}


def _ow(work: Path, argv: Sequence[str], extra: Mapping[str, str] | None = None) -> Captured:
    """`ow <argv>` in `work/project`, as a child with no shell (ruling 2). Never raises."""
    return run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(work / "project"),
        env={**_env(work), **(extra or {})},
        timeout_s=ADD_TIMEOUT_S,
    )


def build(work: Path, documents: Mapping[str, bytes], *, config: str = "") -> None:
    """Write the project and its documents under `work`, then `ow add docs`."""
    project = work / "project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT + config, encoding="utf-8")
    for path, data in documents.items():
        target = project / "docs" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    added = _ow(work, ("add", "docs"))
    if added.returncode != 0:
        tail = added.stderr.decode("utf-8", "replace")[-1200:]
        msg = f"ow add over {work} exited {added.returncode}:\n{tail}"
        raise RuntimeError(msg)


HARNESS_BUDGET_SCALE: Final = 20
"""Ruling 5: the factor every figure of the shipped `QueryBudget` is multiplied by."""


def harness_budget() -> QueryBudget:
    """Ruling 5: the shipped budget, every figure scaled, the snapshot at its cap."""
    from omniweave_core.limits import MAX_SNAPSHOT_MS  # noqa: PLC0415
    from omniweave_core.retrieve.types import QueryBudget  # noqa: PLC0415

    shipped = QueryBudget()
    scale = HARNESS_BUDGET_SCALE
    return QueryBudget(
        query_ms=shipped.query_ms * scale,
        hydration_reserve_ms=shipped.hydration_reserve_ms * scale,
        embed_ms=shipped.embed_ms * scale,
        snapshot_ms=MAX_SNAPSHOT_MS,
        federate_ms=shipped.federate_ms * scale,
        channel_ms={name: ms * scale for name, ms in shipped.channel_ms.items()},
    )


def ask(work: Path, question: str, *, now_ns: Callable[[], int]) -> Observed:
    """One read-only `execute()` over the fixture's store: `ow query`'s own read (ruling 3)."""
    from omniweave_core.retrieve.execute import execute  # noqa: PLC0415
    from omniweave_core.retrieve.types import Query, RetrievalPolicy  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(work / "project" / ".omniweave" / "docs.owstore")
    try:
        reader = store_reader.SqliteReader(connection, now_ns=now_ns())
        retrieval = execute(
            reader, Query(text=question, budget=harness_budget()), RetrievalPolicy()
        )
    finally:
        connection.close()
    return observed(retrieval.response.verdict)


def run_pair(
    injector: Injector,
    fixture: Fixture,
    work: Path,
    *,
    documents: Mapping[str, bytes],
    admit: Callable[[Sequence[str]], str | None],
    now_ns: Callable[[], int],
) -> Damaged:
    """Damage one file, build, read, run the fix, and read again. Needs no pristine run."""
    damaged_docs = dict(documents)
    damaged_docs[fixture.target] = injector.transform(documents[fixture.target])
    build(work, damaged_docs, config=injector.config)
    damaged = ask(work, fixture.question, now_ns=now_ns)
    cause = damaged.cause(injector.row.gate)
    refusal: str | None
    argv: tuple[str, ...] = ()
    try:
        argv = split_fix("" if cause is None else cause.fix)
        refusal = admit(argv)
    except FixRefusedError as exc:
        refusal = str(exc)
    if refusal is not None:
        return Damaged(damaged, None, refusal)
    if injector.restores_source:
        (work / "project" / "docs" / fixture.target).write_bytes(documents[fixture.target])
    extra: Mapping[str, str] = {}
    if injector.repair is not None:
        try:
            repair = injector.repair("" if cause is None else cause.detail)
        except FixRefusedError as exc:
            return Damaged(damaged, None, str(exc))
        for relative, text in repair.append.items():
            with (work / "project" / relative).open("a", encoding="utf-8") as handle:
                handle.write(text)
        extra = repair.env
    ran = _ow(work, argv[1:], extra)
    if ran.returncode != 0:
        tail = ran.stderr.decode("utf-8", "replace")[-600:]
        return Damaged(damaged, None, f"the fix exited {ran.returncode} {ran.failed}: {tail}")
    return Damaged(damaged, ask(work, fixture.question, now_ns=now_ns), None)


def _pristine(
    work: Path,
    documents: Mapping[str, bytes],
    questions: Sequence[str],
    now_ns: Callable[[], int],
) -> list[Observed]:
    build(work, documents)
    return [ask(work, question, now_ns=now_ns) for question in questions]


def run_suite(
    chosen: Sequence[str],
    *,
    root: Path,
    admit: Callable[[Sequence[str]], str | None],
    now_ns: Callable[[], int],
    workers: int = 4,
    keep: Path | None = None,
) -> Suite:
    """Every pair of the `chosen` Injectors, assessed. `keep` keeps each fixture project there.

    A fixture that will not build raises `RuntimeError` naming it: the suite could not run, which
    is not a pair that failed.
    """
    work_root = keep or Path(tempfile.mkdtemp(prefix="ow-damage-"))
    pairs = [
        (INJECTORS[name], index, fixture)
        for name in chosen
        for index, fixture in enumerate(FIXTURES.get(name, ()))
    ]
    results: list[Assessment] = []
    try:
        sets = list(dict.fromkeys((fixture.corpus, fixture.paths) for _i, _n, fixture in pairs))
        documents = {
            key: documents_of(next(f for _i, _n, f in pairs if (f.corpus, f.paths) == key), root)
            for key in sets
        }
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            pristine_runs = {
                key: pool.submit(
                    _pristine,
                    work_root / f"pristine-{number}",
                    documents[key],
                    [f.question for _i, _n, f in pairs if (f.corpus, f.paths) == key],
                    now_ns,
                )
                for number, key in enumerate(sets)
            }
            damaged_runs = [
                pool.submit(
                    run_pair,
                    injector,
                    fixture,
                    work_root / f"{injector.name}-{index}",
                    documents=documents[(fixture.corpus, fixture.paths)],
                    admit=admit,
                    now_ns=now_ns,
                )
                for injector, index, fixture in pairs
            ]
            pristine_of = {key: future.result() for key, future in pristine_runs.items()}
            for (injector, _index, fixture), future in zip(pairs, damaged_runs, strict=True):
                key = (fixture.corpus, fixture.paths)
                same_set = [f for _i, _n, f in pairs if (f.corpus, f.paths) == key]
                pristine = pristine_of[key][same_set.index(fixture)]
                run = future.result()
                results.append(
                    assess(
                        injector,
                        fixture.name,
                        pristine=pristine,
                        damaged=run.damaged,
                        fixed=run.fixed,
                        fix_refusal=run.refusal,
                    )
                )
        read = {
            f"{corpus}/{path}": data
            for (corpus, _paths), docs in documents.items()
            for path, data in docs.items()
        }
    finally:
        if keep is None:
            shutil.rmtree(work_root, ignore_errors=True)
    return Suite(assessments=tuple(results), documents=read)


def documents_digest(documents: Mapping[str, bytes]) -> str:
    """`eval_corpus.corpus_digest`'s recipe over generated documents: sorted `(name, sha256)`."""
    framed = hashlib.sha256()
    for name in sorted(documents):
        digest = hashlib.sha256(documents[name]).hexdigest()
        framed.update(name.encode("utf-8") + b"\x00" + digest.encode("ascii") + b"\x00")
    return framed.hexdigest()
