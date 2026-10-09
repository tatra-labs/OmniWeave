"""GR8 - the graph built step by step equals the graph built once. **D678.**

06-structure-extraction.md section 10.4 is the specification: *"60 documents, 20 shuffled steps
including 3 edits, 2 deletions and 1 driver-version re-parse, asserting equality on
`canonical_projection()` modulo surrogate ids"*, and it is **blocking, not nightly**. 16-roadmap.md
:803 puts `uv run tools/gate_incremental_graph.py` in P8's exit criteria. G19
(`tools/gate_incremental.py`) is the store-level sibling and diffs `.owdoc` exports; this one
diffs the graph, through the real `ow add`, so every step re-runs the whole resolve-and-cluster
closure exactly as a user's next `ow add` would.

THE TWO SIDES
-------------
* **incremental** -- one project. `INITIAL` documents are written and added, then each of the
  `STEPS` steps changes the source folder and runs `ow add docs` again.
* **full** -- a second project holding the files the first one ends with, added once.

Both are compared on `omniweave_core.store.projection.canonical_projection()` (D675): entities,
edges, claims, communities, unresolved references and anchors, with every surrogate id taken out,
a document named by its `doc_key` and a location by `(doc_key, addr)`.

THE RULINGS THE PLAN LEAVES OPEN, AND HOW THEY ARE TAKEN HERE
-------------------------------------------------------------
1. **"60 documents" is every document the corpus ever holds.** The 20 steps are the plan's 3 edits,
   2 deletions and 1 driver-version re-parse, and 14 more; those 14 are additions, the one change
   06:2336's matrix lists that the plan's mix does not, and the one that exercises the
   `ref_unresolved` retry (a reference made before its definition existed). So `INITIAL = 60 - 14
   = 46` documents are added first, 14 arrive one per step, and 58 remain at the end.
2. **The corpus is generated, deterministically, from `SEED`.** Contracts in markdown with numbered
   headings, defined terms drawn from one shared pool (so a term is defined in one document and
   used in others), party aliases, `Section`/`Schedule` references that resolve and some that do
   not, and `GL-` identifiers. The steps are shuffled by the same seed, and each edit or deletion
   targets a document present at that step.
3. **A deletion is the file removed AND `discover.retire_document` run for it.** 06:2348:
   *"`ow store rm --doc d7` is tier-blind and explicit; deletion is never inferred"*, and a file
   that disappears only makes its unit `out_of_scope` (05:365-372). That verb is not dispatched,
   so the gate issues what it will -- G19's precedent (`tools/incremental_index.py`, *"what runs
   here is the statement that verb will issue"*). The function is the one `retire_replaced` runs
   for an edited file's old document, so the two paths cannot drift.
4. **The driver-version re-parse is NOT RUN, and the gate says so.** 06:2334's matrix says what it
   must do -- *"a parse driver bumped, same text: 0 Segments, 0 rows deleted"* -- but no mechanism
   re-parses a settled document because its parse driver moved: the change-detection ladder keys
   on the bytes, and `ow add` has no re-parse switch. Until one exists the step is recorded as an
   absence, the other nineteen still run, and the exit code is 2 (DID NOT RUN), never 0. A gate
   that passed without its hardest step is how the weaker gate becomes the only gate.

Run it:

    uv run tools/gate_incremental_graph.py              # 60 documents, 20 steps
    uv run tools/gate_incremental_graph.py --keep DIR   # ... leaving both projects in DIR

Exit codes: `0` the projections are equal and every step ran, `1` they differ, `2` did not run
(an `ow add` failed, or a step kind has no mechanism).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3  # noqa: TID251 -- not library code: it reads the stores and issues the deletion.
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, MutableSequence, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Final, TextIO, TypeVar

from omniweave.run.discover import RETIRED_X, retire_document
from omniweave_core.host.subproc import run_captured
from omniweave_core.store.projection import CanonicalProjection, canonical_projection

__all__ = [
    "ABSENT",
    "DOCUMENTS",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "GATE",
    "INITIAL",
    "MIX",
    "SEED",
    "STEPS",
    "Report",
    "Step",
    "corpus",
    "main",
    "run",
    "script",
]

GATE: Final = "GR8"

DOCUMENTS: Final = 60
STEPS: Final = 20
MIX: Final[Mapping[str, int]] = {"edit": 3, "delete": 2, "driver_version": 1, "add": 14}
"""06:2405's three kinds, and the additions that make up the twenty (ruling 1)."""

INITIAL: Final = DOCUMENTS - MIX["add"]
SEED: Final = 8

ABSENT: Final[Mapping[str, str]] = {
    "driver_version": (
        "no mechanism re-parses a settled document because its parse driver moved: the "
        "change-detection ladder keys on the bytes and `ow add` has no re-parse switch (D678)"
    ),
}
"""Step kinds the gate cannot run yet, each with the reason it prints (ruling 4)."""

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

PROJECT: Final = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
STORE: Final = Path(".omniweave") / "docs.owstore"
ADD_TIMEOUT_S: Final = 600
_MEMBERS: Final = tuple(member.name for member in fields(CanonicalProjection))

# ---------------------------------------------------------------------------------------------
# The draw
# ---------------------------------------------------------------------------------------------

_T = TypeVar("_T")


class _Draw:
    """A seeded stream of choices: blake2b over a label and a counter, never `random`.

    `pyproject.toml`'s `TID251` bans `random` repo-wide (*"Sampling is blake2b. Determinism is a
    gate, not a habit"*), so the corpus and the script are the same bytes on every interpreter.
    """

    def __init__(self, label: str) -> None:
        self._label = label.encode("utf-8")
        self._count = 0

    def below(self, bound: int) -> int:
        self._count += 1
        digest = hashlib.blake2b(self._label + self._count.to_bytes(8, "big"), digest_size=8)
        return int.from_bytes(digest.digest(), "big") % bound

    def between(self, low: int, high: int) -> int:
        return low + self.below(high - low + 1)

    def choice(self, items: Sequence[_T]) -> _T:
        return items[self.below(len(items))]

    def shuffle(self, items: MutableSequence[_T]) -> None:
        for index in range(len(items) - 1, 0, -1):
            other = self.below(index + 1)
            items[index], items[other] = items[other], items[index]

    def sample(self, items: Sequence[_T], k: int) -> list[_T]:
        pool = list(items)
        self.shuffle(pool)
        return pool[:k]


# ---------------------------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------------------------

_TERMS: Final = (
    "Business Day", "Lender", "Agent", "Borrower", "Facility", "Interest Period", "Margin",
    "Notice", "Security", "Guarantor", "Commitment", "Default", "Loan", "Obligor", "Party",
    "Repayment Date", "Reference Rate", "Tax", "Termination Date", "Utilisation", "Account Bank",
    "Arranger", "Fee Letter", "Holding Company", "Material Adverse Effect", "Permitted Lien",
    "Subsidiary", "Transaction Document", "Availability Period", "Break Costs",
)  # fmt: skip
_PARTIES: Final = (
    ("International Business Machines Corporation", "IBM"),
    ("Acme Holdings Ltd.", "Acme"),
    ("Beta Bank plc", "Beta"),
    ("Gamma Capital LLP", "Gamma"),
    ("Delta Industries Inc.", "Delta"),
    ("Epsilon Partners LP", "Epsilon"),
    ("Zeta Logistics GmbH", "Zeta"),
    ("Eta Energy S.A.", "Eta"),
)
_HEADINGS: Final = (
    "Payment", "Interest", "Representations", "Undertakings", "Events of Default", "Fees",
    "Assignment", "Notices", "Governing Law", "Costs and Expenses",
)  # fmt: skip
_MEANINGS: Final = (
    "any day on which banks in London are open",
    "each person listed in Schedule 1",
    "the facility made available under this agreement",
    "a written notice delivered in accordance with Section 2",
    "the rate determined under Schedule 1",
)


def _document(index: int, rng: _Draw) -> str:
    """One contract: a title, two parties, defined terms, numbered sections and a schedule."""
    (full_a, alias_a), (full_b, alias_b) = rng.sample(_PARTIES, 2)
    defined = rng.sample(_TERMS, 3)
    used = rng.sample(_TERMS, 2)
    sections = rng.between(3, 5)
    lines = [
        f"# Agreement {index:03d}",
        "",
        f'{full_a} ("{alias_a}") and {full_b} (hereinafter, the "{alias_b}") agree as follows.',
        "",
        "## 1. Definitions",
        "",
        f'"{defined[0]}" means {rng.choice(_MEANINGS)}.',
        "",
        f'"{defined[1]}" shall have the meaning set forth in Schedule 1.',
        "",
        f'"{defined[2]}" means {rng.choice(_MEANINGS)}.',
        "",
    ]
    for number, heading in enumerate(rng.sample(_HEADINGS, sections - 1), start=2):
        cited = rng.between(1, sections + 2)  # past the last heading: an unresolved reference
        lines += [
            f"## {number}. {heading}",
            "",
            f"The {alias_b} pays {alias_a} on each {used[0]}, subject to Section {cited} and "
            f"ref GL-{rng.between(1000, 9999)}.",
            "",
            f"Each {used[1]} and each {defined[number % 3]} is subject to Schedule 1.",
            "",
        ]
    lines += ["## Schedule 1 - Parties", "", f"{full_a} and {full_b}.", ""]
    return "\n".join(lines)


def corpus(seed: int = SEED, documents: int = DOCUMENTS) -> dict[str, str]:
    """Every document the corpus ever holds, by file name, in arrival order."""
    rng = _Draw(f"{GATE}:{seed}:corpus")
    return {f"agreement-{index:03d}.md": _document(index, rng) for index in range(documents)}


_EDITS: Final[tuple[Callable[[str], str], ...]] = (
    # a heading renumbered: one defined name removed and another added (06:2328's third row)
    lambda text: text.replace("## 2. ", "## 7. ", 1),
    # a defined term deleted
    lambda text: "\n".join(
        line for line in text.split("\n") if "shall have the meaning set forth" not in line
    ),
    # a paragraph inserted mid-document, defining a term and citing a section that is not there
    lambda text: text.replace(
        "## 2. ", '"Clawback" means a repayment demanded under Section 9.\n\n## 2. ', 1
    ),
)
"""The three edits, applied in turn: each moves the graph a different way."""

# ---------------------------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Step:
    """One step: its kind and the file it touches (`""` for a corpus-wide kind)."""

    kind: str
    name: str = ""

    def render(self) -> str:
        return f"{self.kind}:{self.name}" if self.name else self.kind


def script(
    names: Sequence[str], mix: Mapping[str, int] = MIX, seed: int = SEED
) -> tuple[tuple[str, ...], tuple[Step, ...]]:
    """The initial roster and the shuffled steps. Each edit or deletion names a present file."""
    rng = _Draw(f"{GATE}:{seed}:script")
    kinds = [kind for kind, count in mix.items() for _ in range(count)]
    rng.shuffle(kinds)
    initial = tuple(names[: len(names) - mix.get("add", 0)])
    arriving = list(names[len(initial) :])
    present = list(initial)
    steps: list[Step] = []
    for kind in kinds:
        if kind == "add":
            name = arriving.pop(0)
            present.append(name)
        elif kind in {"edit", "delete"}:
            name = rng.choice(sorted(present))
            if kind == "delete":
                present.remove(name)
        else:
            name = ""
        steps.append(Step(kind, name))
    return initial, tuple(steps)


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Report:
    """What one run found. `differences` is `CanonicalProjection.differences`'s output."""

    steps: list[tuple[Step, float]] = field(default_factory=list)
    absent: list[Step] = field(default_factory=list)
    failure: str = ""
    sizes: dict[str, int] = field(default_factory=dict)
    differences: dict[str, tuple[list[object], list[object]]] = field(default_factory=dict)
    full_s: float = 0.0

    def exit_code(self) -> int:
        if self.differences:
            return EXIT_FAIL
        if self.failure or self.absent:
            return EXIT_NOT_RUN
        return EXIT_CLEAN


def _environment(root: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return {
        **keep,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(root / "ow"),
    }


def _project(root: Path, files: Mapping[str, str]) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "omniweave.toml").write_bytes(PROJECT.encode("utf-8"))
    for name, text in files.items():
        (root / "docs" / name).write_bytes(text.encode("utf-8"))
    return root


def _add(project: Path, env: Mapping[str, str]) -> str:
    """`ow add docs` in `project`. Returns `""`, or what it printed when it failed."""
    done = run_captured(
        (sys.executable, "-m", "omniweave", "add", "docs"),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=ADD_TIMEOUT_S,
    )
    if done.returncode == 0:
        return ""
    shown = (done.stdout + done.stderr).decode("utf-8", "replace")
    return f"ow add exited {done.returncode}:\n{shown[-3000:]}"


def _delete(project: Path, name: str) -> None:
    """Ruling 3: the file goes, and the explicit retirement `ow store rm --doc` will issue runs."""
    (project / "docs" / name).unlink()
    connection = sqlite3.connect(project / STORE, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        live = connection.execute(
            "SELECT doc_ord, gen, uri FROM doc WHERE json_extract(x, ?) IS NULL",
            (f'$."{RETIRED_X}"',),
        ).fetchall()
        found = [(int(o), int(g)) for o, g, uri in live if str(uri).endswith(f"/docs/{name}")]
        if len(found) != 1:
            connection.execute("ROLLBACK")
            raise RuntimeError(f"{name}: {len(found)} live documents, expected exactly one")
        retire_document(connection, *found[0])  # type: ignore[arg-type]
        connection.execute("COMMIT")
    finally:
        connection.close()


def _projection(project: Path) -> CanonicalProjection:
    connection = sqlite3.connect(project / STORE)
    try:
        return canonical_projection(connection)
    finally:
        connection.close()


def run(
    root: Path,
    *,
    documents: int = DOCUMENTS,
    mix: Mapping[str, int] = MIX,
    seed: int = SEED,
    out: TextIO | None = None,
) -> Report:
    """Both sides under `root`, and their comparison."""
    report = Report()
    say = (lambda line: print(line, file=out, flush=True)) if out is not None else (lambda _: None)
    files = corpus(seed, documents)
    initial, steps = script(tuple(files), mix, seed)
    env = _environment(root)
    incremental = _project(root / "incremental", {name: files[name] for name in initial})
    current = {name: files[name] for name in initial}

    started = time.perf_counter()
    if failure := _add(incremental, env):
        report.failure = f"the initial add: {failure}"
        return report
    say(f"  initial   {len(initial)} documents  {time.perf_counter() - started:6.1f} s")
    edits = 0
    for number, step in enumerate(steps, start=1):
        started = time.perf_counter()
        if step.kind in ABSENT:
            report.absent.append(step)
        elif step.kind == "add":
            current[step.name] = files[step.name]
            (incremental / "docs" / step.name).write_bytes(files[step.name].encode("utf-8"))
        elif step.kind == "edit":
            current[step.name] = _EDITS[edits % len(_EDITS)](current[step.name])
            edits += 1
            (incremental / "docs" / step.name).write_bytes(current[step.name].encode("utf-8"))
        elif step.kind == "delete":
            del current[step.name]
            _delete(incremental, step.name)
        if failure := _add(incremental, env):
            report.failure = f"step {number} ({step.render()}): {failure}"
            return report
        elapsed = time.perf_counter() - started
        report.steps.append((step, elapsed))
        note = "  NOT RUN" if step.kind in ABSENT else ""
        say(f"  step {number:2d}   {step.render():<28} {elapsed:6.1f} s{note}")

    started = time.perf_counter()
    full = _project(root / "full", current)
    if failure := _add(full, env):
        report.failure = f"the full rebuild: {failure}"
        return report
    report.full_s = time.perf_counter() - started
    say(f"  full      {len(current)} documents  {report.full_s:6.1f} s")

    after, rebuilt = _projection(incremental), _projection(full)
    report.sizes = {name: len(getattr(rebuilt, name)) for name in _MEMBERS}
    report.differences = after.differences(rebuilt)
    return report


def render(report: Report, out: TextIO) -> None:
    kinds = Counter(step.kind for step, _ in report.steps)
    print(f"{GATE}: {sum(kinds.values())} steps run ({dict(sorted(kinds.items()))})", file=out)
    print(
        "  projection  " + ", ".join(f"{k} {v}" for k, v in report.sizes.items()),
        file=out,
    )
    for step in report.absent:
        print(f"  NOT RUN  {step.render()}: {ABSENT[step.kind]}", file=out)
    if report.failure:
        print(f"  DID NOT RUN  {report.failure}", file=out)
    for member, (only_incremental, only_full) in report.differences.items():
        print(f"  DIFFERS  {member}", file=out)
        for row in only_incremental[:10]:
            print(f"    incremental only  {row!r}", file=out)
        for row in only_full[:10]:
            print(f"    full only         {row!r}", file=out)
    verdict = {EXIT_CLEAN: "PASS", EXIT_FAIL: "FAIL", EXIT_NOT_RUN: "DID NOT RUN"}
    equal = "equal" if not report.differences else "NOT equal"
    print(
        f"{GATE} {verdict[report.exit_code()]}: incremental and full are {equal} on "
        f"canonical_projection()",
        file=out,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate_incremental_graph", description=__doc__)
    parser.add_argument("--keep", type=Path, help="build both projects here and leave them")
    args = parser.parse_args(argv)
    if args.keep is not None:
        if args.keep.exists() and any(args.keep.iterdir()):
            sys.stderr.write(f"{args.keep} is not empty\n")
            return EXIT_NOT_RUN
        report = run(args.keep, out=sys.stdout)
    else:
        root = Path(tempfile.mkdtemp(prefix="gr8-"))
        try:
            report = run(root, out=sys.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    render(report, sys.stdout)
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
