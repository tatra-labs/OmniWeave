"""The absence suite's removal half: ground truth by removal, over the generated corpora. D933.

13-quality.md section 8.6, Construction 1: *"Take a Tier-B document, delete a section, re-ingest,
and ask a question whose only answer was in the deleted section. Metrics: `absent_precision`,
`absent_recall`, and `false_confident_zero <= 0.01` -- the fraction of genuinely answerable
questions answered `absent`. Removal gives exact ground truth at zero labelling cost, and the
deleted span is retained so the counterfactual is one query away."* All three read
`Verdict.state` and nothing else, so no judge runs and the half is deterministic; `qa_accuracy`,
the judge-graded one, is not this module's.

## Rulings

1. **The documents are the reference corpora, and a section is a planted sentence.** The
   adoption catalogue (`retrieval.CATALOG`) asks its questions of the three corpora
   `fixtures/gen/gen_reference_corpora.py` generates at `quick` scale, and that generator writes
   every answer as one line of one named document, its `PLANTED` table. Deleting that line is
   deleting the section the question's only answer was in. They are Tier A, not Tier B, which the
   run's confounders say.
2. **Three populations, each by construction.** A `citation` or `retrieval` task asked of its
   corpus as generated is **answerable**: its answer is planted there, which
   `bench/serve/test_corpora.py` holds. The same task asked of the corpus with its sentence
   removed is **genuinely absent**, and so is an `absence` task asked of the corpus as generated:
   the generator's `ABSENT` table names terms no document holds. A `damaged` task is the
   paired-damage half's.
3. **A task whose answer is in several documents is not removed.** `SHARED` names it and why:
   deleting one section leaves it answerable, so its removed question is not genuinely absent.
4. **One removed corpus per catalogue corpus**, every removable sentence of it deleted at once:
   each removed question's answer is gone whichever others are, and three builds stand for
   thirteen. `run_suite()` refuses a sentence that is not exactly one line of its document, or
   that survives the removal anywhere in the corpus, because either would make the ground truth
   an assertion.
5. **The questions are asked as `absence.ask()` asks them**: one read-only `execute()` over a
   store a real `ow add` built (`absence.build()`), reading the `Verdict`, never the prose.

Specified in 13-quality.md sections 8.3 and 8.6.
"""

from __future__ import annotations

import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_conform.absence import ask, build, generator
from omniweave_conform.retrieval import CATALOG

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "ABSENT",
    "ANSWERABLE",
    "REMOVED",
    "SHARED",
    "Asked",
    "Question",
    "Removal",
    "questions",
    "removed",
    "run_suite",
]

ANSWERABLE: Final = "answerable"
REMOVED: Final = "removed"
ABSENT: Final = "absent"

ANSWERABLE_CLASSES: Final = frozenset({"citation", "retrieval"})
"""Ruling 2: the catalogue classes whose answer is planted in their corpus."""
ABSENCE_CLASS: Final = "absence"

SHARED: Final[Mapping[str, str]] = MappingProxyType(
    {
        "data-ret-indexed-cap": (
            "its answer names three suppliers, each in its own agreement "
            "(the generator's EXTRA_SUPPLIERS), so removing one section leaves it answerable"
        ),
    }
)
"""Ruling 3: the answerable tasks whose removed question would not be genuinely absent."""

ABSENT_STATE: Final = "absent"
"""`VerdictState.ABSENT`'s value: the one state a question can be *answered absent* with."""


@dataclass(frozen=True, slots=True)
class Question:
    """One question asked: the task, its corpus, and which population it is in (ruling 2)."""

    task_id: str
    corpus: str
    prompt: str
    population: str

    @property
    def genuinely_absent(self) -> bool:
        return self.population != ANSWERABLE


@dataclass(frozen=True, slots=True)
class Asked:
    """One question and the state its `Verdict` read."""

    question: Question
    state: str

    @property
    def answered_absent(self) -> bool:
        return self.state == ABSENT_STATE


@dataclass(frozen=True, slots=True)
class Removal:
    """The half's run: every question asked, what was not removed, and the documents read."""

    asked: tuple[Asked, ...]
    shared: tuple[str, ...]
    documents: Mapping[str, bytes]
    """Every document either corpus held, keyed `<corpus>/<path>` and `<corpus>-removed/<path>`."""

    def of(self, population: str) -> tuple[Asked, ...]:
        return tuple(one for one in self.asked if one.question.population == population)

    @property
    def answerable(self) -> tuple[Asked, ...]:
        return self.of(ANSWERABLE)

    @property
    def genuinely_absent(self) -> tuple[Asked, ...]:
        return tuple(one for one in self.asked if one.question.genuinely_absent)

    @property
    def called_absent(self) -> tuple[Asked, ...]:
        return tuple(one for one in self.asked if one.answered_absent)


def questions(root: Path) -> tuple[Question, ...]:
    """The catalogue's questions in its order, each in its population (rulings 2 and 3)."""
    path = root / CATALOG
    if not path.is_file():
        msg = f"no adoption catalogue at {path}"
        raise RuntimeError(msg)
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("task", [])
    out: list[Question] = []
    for row in rows:
        task, corpus, prompt = str(row["id"]), str(row["corpus"]), str(row["prompt"])
        kind = row.get("class")
        if kind in ANSWERABLE_CLASSES:
            out.append(Question(task, corpus, prompt, ANSWERABLE))
            if task not in SHARED:
                out.append(Question(task, corpus, prompt, REMOVED))
        elif kind == ABSENCE_CLASS:
            out.append(Question(task, corpus, prompt, ABSENT))
    return tuple(out)


def removed(root: Path, corpus: str, tasks: Sequence[str]) -> dict[str, bytes]:
    """`corpus` at `quick` scale with each of `tasks`' planted sentence deleted (rulings 1, 4).

    Raises `RuntimeError` when a task plants nothing, when its sentence is not exactly one line
    of its document, or when the sentence survives anywhere in the corpus.
    """
    gen = generator(root)
    cut: dict[str, set[str]] = {}
    for task in tasks:
        planted = gen.PLANTED.get(task)
        if planted is None or planted.corpus != corpus:
            msg = f"{task} plants no sentence in {corpus}, so there is no section to remove"
            raise RuntimeError(msg)
        cut.setdefault(planted.path, set()).add(planted.text)
    out: dict[str, bytes] = {}
    kept_text: list[str] = []
    for doc in gen.documents(corpus, "quick"):
        lines = doc.lines
        for text in sorted(cut.get(doc.path, ())):
            if lines.count(text) != 1:
                msg = (
                    f"{corpus}/{doc.path} holds its planted sentence on {lines.count(text)} "
                    f"line(s), not one: {text!r}"
                )
                raise RuntimeError(msg)
        gone = cut.get(doc.path, set())
        pages = tuple(tuple(line for line in page if line not in gone) for page in doc.pages)
        kept = gen.Document(doc.path, pages)
        kept_text.extend(kept.lines)
        out[doc.path] = kept.to_bytes()
    whole = "\n".join(kept_text)
    for texts in cut.values():
        for text in sorted(texts):
            if text in whole:
                msg = f"{corpus}'s removed corpus still holds {text!r}"
                raise RuntimeError(msg)
    return out


def run_suite(root: Path, *, work: Path, now_ns: Callable[[], int], workers: int = 4) -> Removal:
    """Each catalogue corpus built as generated and as removed, then every question asked of the
    corpus its population names (rulings 2-5)."""
    asking = questions(root)
    corpora = list(dict.fromkeys(question.corpus for question in asking))
    gen = generator(root)
    sets: dict[tuple[str, bool], dict[str, bytes]] = {}
    for corpus in corpora:
        sets[corpus, False] = {doc.path: doc.to_bytes() for doc in gen.documents(corpus, "quick")}
        cut = [q.task_id for q in asking if q.corpus == corpus and q.population == REMOVED]
        sets[corpus, True] = removed(root, corpus, cut)

    def place(corpus: str, *, cut: bool) -> Path:
        return work / (f"{corpus}-removed" if cut else corpus)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        built = [
            pool.submit(build, place(corpus, cut=cut), documents)
            for (corpus, cut), documents in sets.items()
        ]
        for future in built:
            future.result()
    asked = tuple(
        Asked(
            question,
            ask(
                place(question.corpus, cut=question.population == REMOVED),
                question.prompt,
                now_ns=now_ns,
            ).state,
        )
        for question in asking
    )
    read = {
        f"{corpus}{'-removed' if cut else ''}/{path}": data
        for (corpus, cut), documents in sets.items()
        for path, data in documents.items()
    }
    shared = tuple(
        task
        for task in SHARED
        if any(q.task_id == task for q in asking if q.population == ANSWERABLE)
    )
    return Removal(asked=asked, shared=shared, documents=read)
