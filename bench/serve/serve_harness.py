"""`bench/serve/`'s measurement core: tasks, transcripts, and two numbers that travel together.

13-quality.md section 8.8 specifies the adoption harness: **30 scripted tasks** over three reference
corpora (F20), driven by a scripted agent with a fixed tool budget, reporting `source_reread_rate`
**paired with** `task_accuracy`. 00-vision.md section 10 makes the first number the framework's stop
condition and the pairing its guard against gaming. This module is the instrument's arithmetic --
everything that turns a set of transcripts into a verdict -- and nothing that produces a transcript.

## What is here, and what is not (W7.7a)

**Here:** the task catalogue and its shape (8 citation-shaped lookups, 8 open retrievals, 6 genuine
absences, 8 damaged corpora; 13:1365-1370); the transcript of one task's tool calls; the three
per-task facts (`reread`, `correct`, `mis_pick`); the per-arm report, sliced by source kind and
by task class and never a bare mean (13:1399-1401); Wilson 95% on every rate (13:401); `Q-G21`'s
pairing as a type; and the `Control guard` -- the omniweave arm's accuracy may not fall below
the control arm's at paired `p < 0.01` (13:1389-1391).

**Not here:** the scripted agent and its Cassettes, which need recorded model calls, and the three
reference corpora, which do not exist in the tree (D602). The catalogue ships empty rather than with
thirty invented tasks: a task is a question with a known answer over a known document, and an answer
key written against documents nobody has would be ground truth by assertion.

## Three rulings the plan does not make, stated where they bite

* **`task_accuracy` is the fraction RIGHT (D600).** 13:1380 and 00:776-777 define it as *"the
  fraction of tasks whose final answer is wrong"*, and in the same paragraph make *"`task_accuracy`
  falls"* the failing direction. Both cannot hold; the failing direction is the design, so the
  number is the fraction correct and the definition sentence is the defect.
* **One `reread` rule for both arms (D601).** 13:1373 counts a source read *"after an `ow_query` or
  `ow_open`"*; 13:1392 says the control arm's rate is *"1.0 by construction"*, and a control agent
  never calls either tool. Read literally, the control arm's rate is 0.0. So: a task rereads when it
  reads an indexed source at any point after its first omniweave call -- and with no omniweave call,
  at any point at all. One rule, and the control arm is 1.0 exactly when its agent must read to
  answer, which is what "by construction" means.
* **What counts as a read (D601).** 13:1373 names `Read`, `Grep` and *"shell `cat`"*. A metric that
  counted only `cat` could be driven down by an agent that switched to `head`, which is the gaming
  section 8.8 exists to prevent, so the shell arm counts every command in `SHELL_READERS`.

Stdlib only: this file runs in the harness's own process with no framework import, so a change to
the framework cannot move the instrument that measures it.
"""

from __future__ import annotations

import math
import re
import shlex
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

__all__ = [
    "ALPHA",
    "REQUIRED_COUNTS",
    "SHELL_READERS",
    "TASKS_TOTAL",
    "Arm",
    "ArmReport",
    "Catalog",
    "CatalogError",
    "ControlGuard",
    "Corpus",
    "Expect",
    "Paired",
    "Rate",
    "SourceKind",
    "Task",
    "TaskClass",
    "TaskOutcome",
    "ToolCall",
    "Transcript",
    "indexed_sources",
    "load_catalog",
    "mcnemar_worse",
    "outcome",
    "report",
    "wilson",
]


# =============================================================================================
# 1. The vocabularies
# =============================================================================================


class TaskClass(StrEnum):
    """13:1365-1370's four task classes, in the table's order."""

    CITATION = "citation"
    RETRIEVAL = "retrieval"
    ABSENCE = "absence"
    DAMAGED = "damaged"


REQUIRED_COUNTS: Final[Mapping[TaskClass, int]] = {
    TaskClass.CITATION: 8,
    TaskClass.RETRIEVAL: 8,
    TaskClass.ABSENCE: 6,
    TaskClass.DAMAGED: 8,
}
"""13:1365-1370's `n` column. Their sum is the plan's thirty."""

TASKS_TOTAL: Final[int] = sum(REQUIRED_COUNTS.values())


class Corpus(StrEnum):
    """F20's three reference corpora (13:1361-1362)."""

    LEGAL_MATTER = "legal_matter"
    DATA_ROOM = "data_room"
    PERSONAL_ARCHIVE = "personal_archive"


class SourceKind(StrEnum):
    """13:1399's slice: a scanned source is where an agent SHOULD re-read, so it is never pooled."""

    BORN_DIGITAL = "born_digital"
    SCANNED = "scanned"


class Arm(StrEnum):
    """13:1389-1390: the same tasks, once with the MCP server present and once with it absent."""

    OMNIWEAVE = "omniweave"
    CONTROL = "control"


OW_TOOLS: Final[frozenset[str]] = frozenset({"ow_query", "ow_open"})
"""The two listed tools a re-read is counted after. `ow_corpora` and `ow_add` answer no question."""

HOST_READ: Final[str] = "Read"
HOST_GREP: Final[str] = "Grep"
HOST_SHELL: Final[str] = "Bash"

SHELL_READERS: Final[frozenset[str]] = frozenset(
    {"cat", "head", "tail", "less", "more", "type", "get-content", "gc", "sed", "awk", "grep", "rg"}
)
"""Shell commands that read a file's bytes. `cat` is 13:1373's; the rest are the same act (D601)."""


# =============================================================================================
# 2. The catalogue
# =============================================================================================


class CatalogError(ValueError):
    """A catalogue that does not parse or breaks a rule below. Never a partial catalogue."""


@dataclass(frozen=True, slots=True)
class Expect:
    """How a final answer is graded: every `contains` present, no `forbids` present, casefolded.

    Substrings and not a model judge, because a judge is a second model whose drift would move
    `task_accuracy` with nothing in the harness changing -- and the Cassette rule (13:1402) exists
    so that a moved number is a reviewable diff.
    """

    contains: tuple[str, ...] = ()
    forbids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contains and not self.forbids:
            raise CatalogError("an expectation that nothing can fail grades every answer correct")

    def grades(self, answer: str) -> bool:
        folded = answer.casefold()
        return all(one.casefold() in folded for one in self.contains) and not any(
            one.casefold() in folded for one in self.forbids
        )


@dataclass(frozen=True, slots=True)
class Task:
    """One scripted task: a question, the corpus it is asked of, and how its answer is graded."""

    id: str
    task_class: TaskClass
    corpus: Corpus
    source_kind: SourceKind
    prompt: str
    expect: Expect
    injector: str | None = None
    """13:1370: a damaged-corpus task names the one `Injector` applied to its corpus."""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.id):
            raise CatalogError(f"task id {self.id!r} is not [a-z0-9][a-z0-9_-]{{0,63}}")
        if not self.prompt.strip():
            raise CatalogError(f"task {self.id} has no prompt")
        if (self.task_class is TaskClass.DAMAGED) != (self.injector is not None):
            raise CatalogError(
                f"task {self.id}: an injector is required on a damaged-corpus task and "
                f"meaningless on any other (13:1370)"
            )


@dataclass(frozen=True, slots=True)
class Catalog:
    """The tasks, in file order. `missing()` is how far the catalogue is from the plan's thirty."""

    tasks: tuple[Task, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for task in self.tasks:
            if task.id in seen:
                raise CatalogError(f"task id {task.id} appears twice")
            seen.add(task.id)
        for task_class, wanted in REQUIRED_COUNTS.items():
            have = sum(1 for one in self.tasks if one.task_class is task_class)
            if have > wanted:
                raise CatalogError(
                    f"{have} {task_class} tasks against 13:1365-1370's {wanted}; the class sizes "
                    f"are the design, not a floor"
                )

    def missing(self) -> Mapping[TaskClass, int]:
        """Per class, how many tasks the catalogue still owes. Empty when it is complete."""
        return {
            task_class: wanted - sum(1 for one in self.tasks if one.task_class is task_class)
            for task_class, wanted in REQUIRED_COUNTS.items()
            if sum(1 for one in self.tasks if one.task_class is task_class) < wanted
        }

    @property
    def complete(self) -> bool:
        return not self.missing()

    def by_id(self) -> Mapping[str, Task]:
        return {task.id: task for task in self.tasks}


def load_catalog(text: str) -> Catalog:
    """`tasks.toml` as a `Catalog`: one `[[task]]` per task, every key required but `injector`."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"tasks.toml does not parse: {exc}") from exc
    unknown = sorted(set(document) - {"catalog", "task"})
    if unknown:
        raise CatalogError(f"tasks.toml has unknown top-level keys {unknown}")
    tasks: list[Task] = []
    for raw in document.get("task", []):
        extra = sorted(
            set(raw) - {"id", "class", "corpus", "source", "prompt", "expect", "injector"}
        )
        if extra:
            raise CatalogError(f"task {raw.get('id')!r} has unknown keys {extra}")
        try:
            expect = raw["expect"]
            tasks.append(
                Task(
                    id=str(raw["id"]),
                    task_class=TaskClass(raw["class"]),
                    corpus=Corpus(raw["corpus"]),
                    source_kind=SourceKind(raw["source"]),
                    prompt=str(raw["prompt"]),
                    expect=Expect(
                        contains=tuple(str(one) for one in expect.get("contains", ())),
                        forbids=tuple(str(one) for one in expect.get("forbids", ())),
                    ),
                    injector=None if raw.get("injector") is None else str(raw["injector"]),
                )
            )
        except (KeyError, ValueError) as exc:
            if isinstance(exc, CatalogError):
                raise
            raise CatalogError(f"task {raw.get('id')!r}: {exc!r}") from exc
    return Catalog(tasks=tuple(tasks))


# =============================================================================================
# 3. The transcript, and what one task did
# =============================================================================================


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One host tool call, as the scripted agent's transcript records it: the name and its args."""

    tool: str
    args: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Transcript:
    """One task on one arm: the calls in order, and the final answer the agent gave."""

    task_id: str
    arm: Arm
    calls: tuple[ToolCall, ...]
    answer: str


def indexed_sources(receipt_text: str, source_root: str) -> frozenset[str]:
    """The indexed source files, from `omniweave.index.lock`, as absolute POSIX paths.

    The receipt is the corpus a query sees (W7.3aa, D594), so "indexed" is read off it rather than
    off the walk: a file the walk found and nothing parsed is not a source omniweave could have
    answered from, and re-reading it is not distrust. Uris are relative to the source root (D591);
    the last of a row's seven columns, split on the receipt's two-space separator.
    """
    root = _posix(source_root).rstrip("/")
    found: set[str] = set()
    for line in receipt_text.splitlines():
        if not line or line.startswith("#"):
            continue
        uri = line.split("  ")[-1]
        found.add(uri if uri.startswith("/") or re.match(r"[a-z]:/", uri) else f"{root}/{uri}")
    return frozenset(_posix(one) for one in found)


def _posix(path: str) -> str:
    """One spelling for a path on either OS: forward slashes, a lower-case drive letter."""
    spelled = path.replace("\\", "/")
    if re.match(r"[A-Za-z]:/", spelled):
        spelled = spelled[0].lower() + spelled[1:]
    return str(PurePosixPath(spelled))


def _touches(path: str, indexed: frozenset[str]) -> bool:
    """A path that IS an indexed file, or a directory holding one -- a grep over it reads them."""
    spelled = _posix(path).rstrip("/")
    return spelled in indexed or any(one.startswith(spelled + "/") for one in indexed)


def reads_source(call: ToolCall, indexed: frozenset[str]) -> bool:
    """Whether a host call reads an indexed source's bytes. 13:1373's three tools (D601)."""
    if call.tool == HOST_READ:
        return _touches(call.args.get("file_path", ""), indexed)
    if call.tool == HOST_GREP:
        return _touches(call.args.get("path", ""), indexed)
    if call.tool == HOST_SHELL:
        try:
            words = shlex.split(call.args.get("command", ""), posix=True)
        except ValueError:
            words = call.args.get("command", "").split()
        readers = any(word.casefold() in SHELL_READERS for word in words)
        return readers and any(
            _touches(word, indexed) for word in words if "/" in word or "\\" in word
        )
    return False


def _expected_tool(task_class: TaskClass) -> str:
    """F19's right first pick: `ow_open` for a citation-shaped lookup, `ow_query` for the rest."""
    return "ow_open" if task_class is TaskClass.CITATION else "ow_query"


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """The three facts one transcript yields, plus the two slice keys it is reported under."""

    task_id: str
    arm: Arm
    task_class: TaskClass
    source_kind: SourceKind
    reread: bool
    correct: bool
    mis_pick: bool | None
    """`None` when the task made no omniweave call: F19 asks which tool was picked, and none was."""


def outcome(task: Task, transcript: Transcript, indexed: frozenset[str]) -> TaskOutcome:
    """One task's facts. `reread` is D601's one rule; `correct` is `Expect.grades`."""
    if transcript.task_id != task.id:
        raise CatalogError(f"transcript for {transcript.task_id} graded against task {task.id}")
    first = next((i for i, call in enumerate(transcript.calls) if call.tool in OW_TOOLS), -1)
    reread = any(reads_source(call, indexed) for call in transcript.calls[first + 1 :])
    mis_pick = (
        None if first < 0 else transcript.calls[first].tool != _expected_tool(task.task_class)
    )
    return TaskOutcome(
        task_id=task.id,
        arm=transcript.arm,
        task_class=task.task_class,
        source_kind=task.source_kind,
        reread=reread,
        correct=task.expect.grades(transcript.answer),
        mis_pick=mis_pick,
    )


# =============================================================================================
# 4. Rates, the pairing, and the report
# =============================================================================================

Z95: Final[float] = 1.959963984540054
"""The two-sided 95% normal quantile Wilson's interval is built on (13:401)."""


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson's score interval for `k` of `n`. 13:401: *"never the normal approximation, which is
    wrong at the p->1 end where our gates live"*. `(0.0, 1.0)` for `n == 0`: nothing is known."""
    if not 0 <= k <= n:
        raise ValueError(f"{k} of {n} is not a count")
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True, slots=True)
class Rate:
    """`k` of `n`, with its Wilson interval. A rate is never rendered without its `n`."""

    k: int
    n: int

    @property
    def value(self) -> float | None:
        return None if self.n == 0 else self.k / self.n

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.k, self.n)

    def render(self) -> str:
        lo, hi = self.interval
        shown = "n/a" if self.value is None else f"{self.value:.3f}"
        return f"{shown} ({self.k}/{self.n}, 95% [{lo:.3f}, {hi:.3f}])"


def _rate(flags: Iterable[bool]) -> Rate:
    values = list(flags)
    return Rate(k=sum(values), n=len(values))


@dataclass(frozen=True, slots=True)
class Paired:
    """`source_reread_rate` and `task_accuracy`, over one population. **`Q-G21` as a type.**

    13:1385-1387: `source_reread_rate` may not ship without `task_accuracy`. There is no field,
    method or constructor here that yields one without the other, so a report that shows the
    adoption number shows the number that says whether it was bought with wrong answers.
    """

    source_reread_rate: Rate
    task_accuracy: Rate

    @classmethod
    def of(cls, outcomes: Sequence[TaskOutcome]) -> Paired:
        return cls(
            source_reread_rate=_rate(one.reread for one in outcomes),
            task_accuracy=_rate(one.correct for one in outcomes),
        )

    def render(self) -> str:
        return (
            f"source_reread_rate {self.source_reread_rate.render()}  "
            f"task_accuracy {self.task_accuracy.render()}"
        )


@dataclass(frozen=True, slots=True)
class ArmReport:
    """One arm: the pair over everything, the pair per slice, and F19's mis-pick rate.

    Slices are by source kind and by task class, 13:1399-1401's *"reported as a distribution,
    sliced, never as a bare mean"*; `lines()` prints the slices beside the total, so the total is
    never read alone.
    """

    arm: Arm
    total: Paired
    by_source: Mapping[SourceKind, Paired]
    by_class: Mapping[TaskClass, Paired]
    mis_pick: Rate

    def lines(self) -> tuple[str, ...]:
        out = [f"{self.arm}  all             {self.total.render()}"]
        out += [f"{self.arm}  {kind:<15} {pair.render()}" for kind, pair in self.by_source.items()]
        out += [f"{self.arm}  {cls:<15} {pair.render()}" for cls, pair in self.by_class.items()]
        out.append(f"{self.arm}  mis_pick (F19)  {self.mis_pick.render()}")
        return tuple(out)


def report(arm: Arm, outcomes: Sequence[TaskOutcome]) -> ArmReport:
    """The arm's report. Every outcome must be of this arm: pooling arms is what it prevents."""
    stray = sorted({one.task_id for one in outcomes if one.arm is not arm})
    if stray:
        raise CatalogError(f"outcomes {stray} are not from the {arm} arm")
    return ArmReport(
        arm=arm,
        total=Paired.of(outcomes),
        by_source={
            kind: Paired.of([one for one in outcomes if one.source_kind is kind])
            for kind in SourceKind
            if any(one.source_kind is kind for one in outcomes)
        },
        by_class={
            cls: Paired.of([one for one in outcomes if one.task_class is cls])
            for cls in TaskClass
            if any(one.task_class is cls for one in outcomes)
        },
        mis_pick=_rate(one.mis_pick for one in outcomes if one.mis_pick is not None),
    )


# =============================================================================================
# 5. The Control guard
# =============================================================================================

ALPHA: Final[float] = 0.01
"""13:1391's *"paired `p < 0.01`"*."""


def mcnemar_worse(omniweave: Sequence[bool], control: Sequence[bool]) -> float:
    """One-sided exact McNemar: the chance of the omniweave arm being this much worse by luck.

    Paired by task. Only the discordant pairs carry information: `worse` tasks the control arm got
    right and omniweave got wrong, `better` the reverse. Under the null each discordant pair is a
    fair coin, so `p = P(X >= worse)` for `X ~ Binomial(worse + better, 1/2)`. Exact rather than
    chi-squared, because thirty tasks give a handful of discordant pairs and the asymptotic test is
    wrong exactly there -- 13:401's argument against the normal approximation, one statistic over.
    """
    if len(omniweave) != len(control):
        raise ValueError("a paired test needs one control outcome per omniweave outcome")
    worse = sum(1 for o, c in zip(omniweave, control, strict=True) if c and not o)
    better = sum(1 for o, c in zip(omniweave, control, strict=True) if o and not c)
    n = worse + better
    if n == 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(worse, n + 1)) / 2**n


@dataclass(frozen=True, slots=True)
class ControlGuard:
    """13:1388-1391's `Control guard`, and 13:1382's pairing rule across two runs.

    `ok` is false when either holds:

    * **the paired test fails** -- the omniweave arm's accuracy is below the control arm's at
      one-sided `p < ALPHA`, task by task, in the SAME run (13:1389);
    * **the number was bought** -- given the previous run's omniweave report, `source_reread_rate`
      fell AND `task_accuracy` fell with it (13:1382): the agent was talked out of checking and was
      wrong more often for it. That is a failing run whatever the paired test says.
    """

    omniweave: ArmReport
    control: ArmReport
    p_worse: float
    gamed: bool

    @property
    def ok(self) -> bool:
        return self.p_worse >= ALPHA and not self.gamed

    def lines(self) -> tuple[str, ...]:
        verdict = "ok" if self.ok else "FAIL"
        why = []
        if self.p_worse < ALPHA:
            why.append(f"omniweave accuracy below control at p={self.p_worse:.4f} < {ALPHA}")
        if self.gamed:
            why.append("source_reread_rate fell and task_accuracy fell with it (13:1382)")
        return (
            *self.omniweave.lines(),
            *self.control.lines(),
            f"control guard  p_worse={self.p_worse:.4f}  {verdict}"
            + (f": {'; '.join(why)}" if why else ""),
        )

    @classmethod
    def judge(
        cls,
        omniweave: Sequence[TaskOutcome],
        control: Sequence[TaskOutcome],
        *,
        previous: ArmReport | None = None,
    ) -> ControlGuard:
        """Pair the arms by task id -- both must hold the same tasks -- and decide."""
        mine = {one.task_id: one for one in omniweave}
        theirs = {one.task_id: one for one in control}
        if set(mine) != set(theirs):
            raise CatalogError(
                f"the arms hold different tasks: {sorted(set(mine) ^ set(theirs))}; a paired "
                f"test pairs each task with itself"
            )
        order = sorted(mine)
        now = report(Arm.OMNIWEAVE, [mine[i] for i in order])
        gamed = False
        if previous is not None:
            before, after = previous.total, now.total
            gamed = _fell(before.source_reread_rate, after.source_reread_rate) and _fell(
                before.task_accuracy, after.task_accuracy
            )
        return cls(
            omniweave=now,
            control=report(Arm.CONTROL, [theirs[i] for i in order]),
            p_worse=mcnemar_worse(
                [mine[i].correct for i in order], [theirs[i].correct for i in order]
            ),
            gamed=gamed,
        )


def _fell(before: Rate, after: Rate) -> bool:
    return before.value is not None and after.value is not None and after.value < before.value
