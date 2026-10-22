"""The absence suite's removal half: its populations, its removed corpora, its counts. D933.

13-quality.md section 8.6, Construction 1. The documents are generated and nothing here builds a
store: `packages/omniweave/tests/conform/test_absence_removal.py` asks the questions for real.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_conform import removal
from omniweave_conform.absence import generator
from omniweave_conform.removal import (
    ABSENT,
    ANSWERABLE,
    REMOVED,
    SHARED,
    Asked,
    Question,
    Removal,
    questions,
    removed,
)

REPO = Path(__file__).resolve().parents[4]


def _catalog() -> list[dict[str, object]]:
    return tomllib.loads((REPO / "bench" / "serve" / "tasks.toml").read_text(encoding="utf-8"))[
        "task"
    ]


def test_each_catalogue_class_lands_in_its_population() -> None:
    """Ruling 2: answerable is citation and retrieval, asked as generated and as removed; an
    absence task is genuinely absent as generated; a damaged task is the damage half's."""
    rows = _catalog()
    asked = questions(REPO)
    by_population = {
        p: [q.task_id for q in asked if q.population == p] for p in (ANSWERABLE, REMOVED, ABSENT)
    }
    answerable = [str(r["id"]) for r in rows if r["class"] in {"citation", "retrieval"}]
    assert by_population[ANSWERABLE] == answerable
    assert by_population[REMOVED] == [task for task in answerable if task not in SHARED]
    assert by_population[ABSENT] == [str(r["id"]) for r in rows if r["class"] == "absence"]
    damaged = {str(r["id"]) for r in rows if r["class"] == "damaged"}
    assert damaged
    assert not damaged & {q.task_id for q in asked}
    assert (
        len(by_population[ANSWERABLE]),
        len(by_population[REMOVED]),
        len(by_population[ABSENT]),
    ) == (13, 12, 5)
    assert all(q.genuinely_absent == (q.population != ANSWERABLE) for q in asked)


def test_the_shared_task_stays_answerable_with_its_section_removed() -> None:
    """Ruling 3: why `data-ret-indexed-cap` is never asked of a removed corpus. Its own sentence
    gone, two other suppliers' agreements still carry an indexed price cap."""
    gen = generator(REPO)
    planted = gen.PLANTED["data-ret-indexed-cap"]
    others = [
        doc.path
        for doc in gen.documents("data_room", "quick")
        if doc.path != planted.path and any("indexed price cap" in line for line in doc.lines)
    ]
    assert sorted(others) == sorted(path for path, _name in gen.EXTRA_SUPPLIERS)
    assert set(SHARED) == {"data-ret-indexed-cap"}


@pytest.mark.parametrize("corpus", ["legal_matter", "data_room", "personal_archive"])
def test_a_removed_corpus_loses_exactly_its_planted_sentences(corpus: str) -> None:
    """Ruling 4: each removed task's line, and nothing else. Every other document is byte for
    byte the generated one, and the removed documents hold none of their sentences."""
    gen = generator(REPO)
    tasks = [q.task_id for q in questions(REPO) if q.corpus == corpus and q.population == REMOVED]
    assert tasks
    cut = removed(REPO, corpus, tasks)
    pristine = {doc.path: doc for doc in gen.documents(corpus, "quick")}
    assert set(cut) == set(pristine)
    touched = {gen.PLANTED[task].path for task in tasks}
    for path, doc in pristine.items():
        if path in touched:
            assert cut[path] != doc.to_bytes(), path
        else:
            assert cut[path] == doc.to_bytes(), path
    for task in tasks:
        planted = gen.PLANTED[task]
        assert pristine[planted.path].lines.count(planted.text) == 1, task


def test_a_task_that_plants_nothing_in_the_corpus_is_refused() -> None:
    with pytest.raises(RuntimeError, match="plants no sentence in personal_archive"):
        removed(REPO, "personal_archive", ["legal-cite-termination"])
    with pytest.raises(RuntimeError, match="plants no sentence in data_room"):
        removed(REPO, "data_room", ["no-such-task"])


def test_a_sentence_on_no_line_or_surviving_the_cut_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 4: the ground truth is checked, never assumed.

    The generator writes `PLANTED[task].text` into its document when it builds it, so a patched
    entry moves the sentence into the dental receipt; its `path` says where the cut looks."""
    gen = generator(REPO)
    real = gen.PLANTED["home-ret-dental"]
    misplaced = gen.Planted(real.corpus, "insurance/car-policy-2024.pdf", real.text)
    monkeypatch.setitem(gen.PLANTED, "home-ret-dental", misplaced)
    with pytest.raises(RuntimeError, match=r"on 0 line\(s\), not one: 'Amount due: \$285.40'"):
        removed(REPO, "personal_archive", ["home-ret-dental"])
    #  The car policy's title line, now also written into the receipt: cut from one, kept in one.
    twice = gen.Planted(real.corpus, "insurance/car-policy-2024.pdf", "Car insurance policy 2024")
    monkeypatch.setitem(gen.PLANTED, "home-ret-dental", twice)
    with pytest.raises(
        RuntimeError, match="removed corpus still holds 'Car insurance policy 2024'"
    ):
        removed(REPO, "personal_archive", ["home-ret-dental"])


def _asked(population: str, state: str, task: str = "t") -> Asked:
    return Asked(Question(task, "c", "q", population), state)


def test_the_populations_and_the_answered_absent_are_counted_apart() -> None:
    run = Removal(
        asked=(
            _asked(ANSWERABLE, "ok", "a"),
            _asked(ANSWERABLE, "absent", "b"),
            _asked(REMOVED, "absent", "a"),
            _asked(REMOVED, "low_confidence", "b"),
            _asked(ABSENT, "degraded", "c"),
        ),
        shared=(),
        documents={},
    )
    assert [one.question.task_id for one in run.answerable] == ["a", "b"]
    assert [one.question.population for one in run.genuinely_absent] == [REMOVED, REMOVED, ABSENT]
    assert [(one.question.population, one.question.task_id) for one in run.called_absent] == [
        (ANSWERABLE, "b"),
        (REMOVED, "a"),
    ]
    assert removal.ABSENT_STATE == "absent"


def test_each_question_is_asked_of_the_corpus_its_population_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rulings 4 and 5, with the builds and the reads faked: six stores, each built from the
    documents it should hold, and a removed question read only from a removed corpus."""
    built: dict[str, dict[str, bytes]] = {}
    read: list[tuple[str, str]] = []

    def build(work: Path, documents: dict[str, bytes]) -> None:
        built[work.name] = dict(documents)

    def ask(work: Path, question: str, **_clock: object) -> object:
        read.append((work.name, question))
        return type("Seen", (), {"state": "low_confidence"})()

    monkeypatch.setattr(removal, "build", build)
    monkeypatch.setattr(removal, "ask", ask)
    done = removal.run_suite(REPO, work=tmp_path, now_ns=lambda: 0)
    corpora = ("legal_matter", "data_room", "personal_archive")
    assert sorted(built) == sorted((*corpora, *(f"{c}-removed" for c in corpora)))
    gen = generator(REPO)
    for corpus in corpora:
        assert built[corpus] == {d.path: d.to_bytes() for d in gen.documents(corpus, "quick")}
    asked = questions(REPO)
    assert [one.question for one in done.asked] == list(asked)
    assert read == [
        (f"{q.corpus}-removed" if q.population == REMOVED else q.corpus, q.prompt) for q in asked
    ]
    cut = {q.task_id for q in asked if q.population == REMOVED}
    for task in cut:
        planted = gen.PLANTED[task]
        assert (
            built[f"{planted.corpus}-removed"][planted.path] != built[planted.corpus][planted.path]
        )
    assert done.shared == ("data-ret-indexed-cap",)
    assert set(done.documents) == {
        f"{store}/{path}" for store, documents in built.items() for path in documents
    }
