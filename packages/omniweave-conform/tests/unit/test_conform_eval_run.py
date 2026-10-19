"""`omniweave_conform.eval_run`: the parse suite as `.oweval` rows. D868.

The suite runs over the repository's own register, `eval/gates.toml`, and its two `[[subject]]`
rows: `parse.pdf.pdfium`, whose fixtures claim verbatimness, and `parse.office.anydoc`, whose do
not (13:661). The parse runs once per module; each test reads the batch it produced.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave_conform import absence as absence_harness
from omniweave_conform import eval_run
from omniweave_conform import retrieval as cite_harness
from omniweave_conform.damage import INJECTORS, TABLE, Assessment, Clause
from omniweave_conform.entry import run as entry_run
from omniweave_conform.release import check_release
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Batch, open_oweval, scoreboard, write

REPO = Path(__file__).resolve().parents[4]
REGISTER: dict[str, Any] = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
PDFIUM, OFFICE = "parse.pdf.pdfium", "parse.office.anydoc"


def _clock(start: int = 1_000) -> Any:
    ticks = count(start, 7)
    return lambda: next(ticks)


def _parse(register: dict[str, Any] = REGISTER, **kw: Any) -> tuple[Batch, tuple[Any, ...]]:
    options: dict[str, Any] = {"subject": None, "witness": "self", "cassette": "off"} | kw
    return eval_run.parse(register, root=REPO, now_ns=_clock(), **options)


@pytest.fixture(scope="module")
def parsed() -> tuple[Batch, tuple[Any, ...]]:
    return _parse()


def test_each_subject_is_one_run_over_its_own_tier_a_corpus(parsed: Any) -> None:
    batch, done = parsed
    assert [run.subject for run in batch.runs] == [PDFIUM, OFFICE]
    assert [row.subject for row in done] == [PDFIUM, OFFICE]
    for run, row in zip(batch.runs, REGISTER["subject"], strict=True):
        (corpus,) = [c for c in batch.corpora if c.corpus_id == run.corpus_id]
        assert corpus.corpus_id == row["fixtures"]
        assert (corpus.tier, corpus.publishable, corpus.n_assertions) == ("A", False, 0)
        assert corpus.version == corpus.corpus_digest[:16] == run.corpus_version
        assert run.measured_on.corpus == f"{corpus.corpus_id}@{corpus.version}"
        assert (run.suite, run.status, run.timing_basis) == ("parse", "ok", "in_process")
        assert (run.witness, run.cassette) == ("self", "off")
        assert run.started_ns < run.ended_ns  # type: ignore[operator]
        assert len(run.code_fingerprint) == 64
        assert eval_run.PARSE_UNMEASURED[0] in run.not_measured
        assert run.confounders[0] == "the fixtures are the driver's own, written by its authors"


def test_a_measured_rate_is_one_native_run_metric_on_its_slice(parsed: Any) -> None:
    batch, done = parsed
    (metric,) = batch.metrics
    assert metric.run_id == batch.runs[0].run_id
    assert (metric.metric, metric.slice_key) == ("span_exact_rate", "pdf/born_digital")
    assert (metric.value, metric.truth_kind, metric.method, metric.state) == (
        1.0,
        "native_run",
        "closed_form",
        "ok",
    )
    assert metric.n == done[0].n > 0
    assert metric.ci_lo is not None
    assert metric.ci_lo < 1.0 == metric.ci_hi
    assert done[0].refused == tuple(
        name for name in done[0].refused if name.endswith(")")
    )  # each refusal carries its class


def test_a_vacuous_rate_writes_no_metric_and_says_why(parsed: Any) -> None:
    batch, done = parsed
    office = batch.runs[1]
    assert not [m for m in batch.metrics if m.run_id == office.run_id]
    assert done[1].value is None
    assert office.not_measured[0].startswith("span_exact_rate: vacuous, no block claims")


def test_the_corpus_digest_frames_each_path_and_its_bytes(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"one")
    (tmp_path / "b").write_bytes(b"two")
    files = [tmp_path / "b", tmp_path / "a"]
    first = eval_run.corpus_digest(tmp_path, files)
    assert first == eval_run.corpus_digest(tmp_path, list(reversed(files)))
    (tmp_path / "b").write_bytes(b"twO")
    assert eval_run.corpus_digest(tmp_path, files) != first
    (tmp_path / "b").write_bytes(b"two")
    (tmp_path / "b").rename(tmp_path / "c")
    assert eval_run.corpus_digest(tmp_path, [tmp_path / "a", tmp_path / "c"]) != first


def test_subject_narrows_and_a_subject_the_register_lacks_is_refused() -> None:
    batch, _ = _parse(subject=PDFIUM)
    assert [run.subject for run in batch.runs] == [PDFIUM]
    with pytest.raises(QualityError, match="no \\[\\[subject\\]\\] in the metric register"):
        _parse(subject="parse.nothing")


def test_a_register_with_no_subject_is_refused() -> None:
    with pytest.raises(QualityError, match="names no \\[\\[subject\\]\\]"):
        _parse({"gate": REGISTER["gate"]})


def test_a_parse_gate_this_build_cannot_compute_is_named() -> None:
    register = REGISTER | {
        "gate": [*REGISTER["gate"], {"metric": "structure_f1", "suite": "parse"}],
    }
    batch, _ = _parse(register, subject=PDFIUM)
    assert "structure_f1: this build does not compute it" in batch.runs[0].not_measured


def test_the_run_id_is_a_digest_of_what_ran_and_when() -> None:
    first, _ = _parse(subject=PDFIUM)
    again, _ = _parse(subject=PDFIUM)
    later = eval_run.parse(
        REGISTER, root=REPO, subject=PDFIUM, witness="self", cassette="off", now_ns=_clock(9_999)
    )[0]
    assert first.runs[0].run_id == again.runs[0].run_id != later.runs[0].run_id
    assert len(first.runs[0].run_id) == 32


def test_the_batch_writes_and_release_check_wants_the_other_two_gates(
    parsed: Any, tmp_path: Path
) -> None:
    batch, _ = parsed
    connection = open_oweval(tmp_path / "x.oweval")
    try:
        write(connection, batch)
        assert [row.standing for row in scoreboard(connection)] == ["WITHHELD"]
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert [(f.kind, f.names) for f in judged.findings] == [
        ("unmeasured", "hard gate degradation_detection@*"),
        ("unmeasured", "hard gate citability_violations@*"),
    ]


def test_the_entry_point_writes_the_store_and_returns_builtins(tmp_path: Path) -> None:
    store = tmp_path / "eval.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["parse"],
        subject=PDFIUM,
        witness="ci",
        cassette="required",
        admit=lambda _argv: None,
    )
    assert done["suites"] == ["parse"]
    [row] = done["runs"]  # type: ignore[misc]
    assert (row["subject"], row["metric"], row["value"]) == (PDFIUM, "span_exact_rate", 1.0)
    connection = open_oweval(store)
    try:
        stored = connection.execute("SELECT run_id, witness, cassette FROM eval_run").fetchall()
    finally:
        connection.close()
    assert stored == [(row["run_id"], "ci", "required")]
    with pytest.raises(QualityError, match="no file at"):
        entry_run(
            oweval=str(store),
            gates=str(tmp_path / "missing.toml"),
            root=str(REPO),
            suites=["parse"],
            subject=None,
            witness="self",
            cassette="off",
            admit=lambda _argv: None,
        )


# --- the absence suite's deterministic half (D869) ----------------------------------------------


def _suite(*oks: bool) -> absence_harness.Suite:
    return absence_harness.Suite(
        assessments=tuple(
            Assessment(
                injector=f"inj{index}",
                fixture="personal_archive/medical/lab-results-2024.pdf",
                clauses=(Clause("counterfactual", ok, "why"),),
            )
            for index, ok in enumerate(oks)
        ),
        documents={"personal_archive/a.pdf": b"one", "data_room/b.xlsx": b"two"},
    )


def _absence(monkeypatch: pytest.MonkeyPatch, suite: Any, register: Any = REGISTER) -> Any:
    seen: dict[str, Any] = {}

    def fake(chosen: Any, **kw: Any) -> Any:
        seen.update(chosen=list(chosen), **kw)
        if isinstance(suite, Exception):
            raise suite
        return suite

    monkeypatch.setattr(absence_harness, "run_suite", fake)
    batch, done = eval_run.absence(
        register,
        root=REPO,
        witness="ci",
        cassette="off",
        now_ns=_clock(),
        admit=lambda _argv: None,
    )
    return batch, done, seen


def test_the_absence_half_is_one_run_of_omniweave_over_every_built_injector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch, (done,), seen = _absence(monkeypatch, _suite(True, True, True))
    assert seen["chosen"] == list(INJECTORS)
    assert seen["root"] == REPO
    assert seen["admit"](("ow", "x")) is None
    (run,) = batch.runs
    (corpus,) = batch.corpora
    assert (run.suite, run.subject, run.timing_basis, run.status) == (
        "absence",
        "omniweave",
        "spawn_inclusive",
        "ok",
    )
    assert run.started_ns < run.ended_ns  # type: ignore[operator]
    assert corpus.corpus_id == run.corpus_id == "reference_corpora/quick"
    assert corpus.version == corpus.corpus_digest[:16]
    assert corpus.corpus_digest == absence_harness.documents_digest(_suite().documents)
    assert (corpus.n_docs, corpus.tier, corpus.publishable) == (2, "A", False)
    assert run.not_measured[0].startswith(f"{len(TABLE) - len(INJECTORS)} of {len(TABLE)}")
    assert eval_run.ABSENCE_UNMEASURED[0] in run.not_measured
    assert run.confounders[1] == "0 pair(s) failed"
    (metric,) = batch.metrics
    assert (metric.metric, metric.slice_key, metric.value, metric.n) == (
        "degradation_detection",
        "deterministic_half",
        1.0,
        3,
    )
    assert (metric.truth_kind, metric.method) == ("rendered", "closed_form")
    assert (done.suite, done.parsed, done.refused) == ("absence", 3, ())


def test_a_failed_pair_lowers_the_rate_and_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    batch, (done,), _ = _absence(monkeypatch, _suite(True, False))
    (metric,) = batch.metrics
    assert metric.value == 0.5
    assert done.refused == ("inj1 x personal_archive/medical/lab-results-2024.pdf",)
    assert batch.runs[0].confounders[1].startswith("1 pair(s) failed: inj1 x ")


def test_a_suite_that_could_not_run_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(QualityError, match="the absence suite could not run: RuntimeError: boom"):
        _absence(monkeypatch, RuntimeError("boom"))


def test_the_register_row_and_its_truth_kind_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    no_row = {"gate": [row for row in REGISTER["gate"] if row["suite"] != "absence"]}
    with pytest.raises(QualityError, match="no absence degradation_detection row"):
        _absence(monkeypatch, _suite(True), no_row)
    bad = {
        "gate": [
            {**row, "truth_kind": "self_verifying"} if row["suite"] == "absence" else row
            for row in REGISTER["gate"]
        ]
    }
    with pytest.raises(QualityError, match="truth_kind 'self_verifying' is not one of"):
        _absence(monkeypatch, _suite(True), bad)


def test_the_entry_point_runs_every_suite_in_one_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(absence_harness, "run_suite", lambda *_a, **_k: _suite(True, True))
    monkeypatch.setattr(cite_harness, "run_suite", lambda *_a, **_k: _checked(()))
    store = tmp_path / "both.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["parse", "absence", "retrieve"],
        subject=None,
        witness="self",
        cassette="off",
        admit=lambda _argv: None,
    )
    assert done["suites"] == ["parse", "absence", "retrieve"]
    rows: Any = done["runs"]
    assert [row["suite"] for row in rows] == ["parse", "parse", "absence", "retrieve"]
    connection = open_oweval(store)
    try:
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert (judged.ok, judged.runs) == (True, 4)


@pytest.mark.parametrize(
    ("suites", "subject", "says"),
    [
        (["extract"], None, "measures parse, absence, retrieve in this build, not extract"),
        (["retrieve"], PDFIUM, "the retrieve suite's subject is omniweave itself"),
        ([], None, "not nothing"),
        (["absence"], PDFIUM, "the absence suite's subject is omniweave itself"),
    ],
)
def test_the_entry_point_refuses_what_it_cannot_run(
    tmp_path: Path, suites: list[str], subject: str | None, says: str
) -> None:
    with pytest.raises(QualityError, match=says):
        entry_run(
            oweval=str(tmp_path / "x.oweval"),
            gates=str(REPO / "eval" / "gates.toml"),
            root=str(REPO),
            suites=suites,
            subject=subject,
            witness="self",
            cassette="off",
            admit=lambda _argv: None,
        )
    assert not (tmp_path / "x.oweval").exists()


def test_the_generated_documents_digest_is_their_names_and_bytes() -> None:
    one = absence_harness.documents_digest({"a": b"1", "b": b"2"})
    assert one == absence_harness.documents_digest({"b": b"2", "a": b"1"})
    assert one != absence_harness.documents_digest({"a": b"1", "c": b"2"})
    assert one != absence_harness.documents_digest({"a": b"1", "b": b"3"})


# --- the retrieve suite's self-verifying half (D870) --------------------------------------------


def _checked(unsound: tuple[tuple[str, ...], ...]) -> cite_harness.Checked:
    """Three Answers of two cites each; `unsound[i]` names the cites of Answer i that failed."""
    rows = list(unsound) + [()] * (3 - len(unsound))
    return cite_harness.Checked(
        asked=tuple(
            cite_harness.Asked(f"task-{index}", ("d1#1", "d1#2"), bad)
            for index, bad in enumerate(rows)
        ),
        documents={"legal_matter/msa.pdf": b"one", "data_room/x.xlsx": b"two"},
        skipped=6,
    )


def _retrieve(monkeypatch: pytest.MonkeyPatch, checked: Any, register: Any = REGISTER) -> Any:
    def fake(root: Path, **kw: Any) -> Any:
        assert root == REPO
        assert kw["work"].is_dir()
        if isinstance(checked, Exception):
            raise checked
        return checked

    monkeypatch.setattr(cite_harness, "run_suite", fake)
    return eval_run.retrieve(register, root=REPO, witness="self", cassette="off", now_ns=_clock())


def test_the_retrieve_half_counts_violations_and_rates_soundness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch, (done,) = _retrieve(monkeypatch, _checked((("d1#2",),)))
    (run,) = batch.runs
    assert (run.suite, run.subject, run.timing_basis) == (
        "retrieve",
        "omniweave",
        "spawn_inclusive",
    )
    assert batch.corpora[0].corpus_id == run.corpus_id == "reference_corpora/quick"
    assert run.not_measured[0].startswith("6 damaged task(s)")
    assert eval_run.RETRIEVE_UNMEASURED[0] in run.not_measured
    assert run.confounders[1] == "1 cite(s) did not resolve: task-0: d1#2"
    violations, soundness = batch.metrics
    assert (violations.metric, violations.value, violations.n, violations.method) == (
        "citability_violations",
        1.0,
        3,
        "exact",
    )
    assert (violations.ci_lo, violations.ci_hi, violations.truth_kind) == (None, None, "native_run")
    assert (soundness.metric, soundness.value, soundness.n, soundness.method) == (
        "citation_soundness",
        5 / 6,
        6,
        "closed_form",
    )
    assert {m.slice_key for m in batch.metrics} == {"born_digital"}
    assert (done.suite, done.value, done.n, done.parsed, done.refused) == (
        "retrieve",
        1.0,
        3,
        5,
        ("task-0: d1#2",),
    )


def test_a_clean_retrieve_run_meets_the_hard_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    batch, _ = _retrieve(monkeypatch, _checked(()))
    assert [m.value for m in batch.metrics] == [0.0, 1.0]
    assert batch.runs[0].confounders[1] == "0 cite(s) did not resolve"


def test_the_retrieve_rows_must_be_in_the_register(monkeypatch: pytest.MonkeyPatch) -> None:
    without = {"gate": [row for row in REGISTER["gate"] if row["suite"] != "retrieve"]}
    with pytest.raises(QualityError, match="no retrieve citability_violations, citation_soundness"):
        _retrieve(monkeypatch, _checked(()), without)
    renamed = {
        "gate": [
            {**row, "truth_kind": "oracle"} if row["suite"] == "retrieve" else row
            for row in REGISTER["gate"]
        ]
    }
    with pytest.raises(QualityError, match="truth_kind 'oracle' is not one of"):
        _retrieve(monkeypatch, _checked(()), renamed)


def test_a_retrieve_suite_that_could_not_run_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(QualityError, match="the retrieve suite could not run: OSError: disk"):
        _retrieve(monkeypatch, OSError("disk"))


def test_the_catalogue_asks_every_task_but_the_damaged() -> None:
    tasks, skipped = cite_harness.load_tasks(REPO)
    rows = tomllib.loads((REPO / cite_harness.CATALOG).read_text(encoding="utf-8"))["task"]
    assert len(tasks) + skipped == len(rows)
    assert skipped == sum(1 for row in rows if row["class"] == "damaged") > 0
    assert {task.corpus for task in tasks} == {"legal_matter", "data_room", "personal_archive"}
    with pytest.raises(RuntimeError, match="no adoption catalogue"):
        cite_harness.load_tasks(REPO / "nowhere")


def _load_store_doc() -> Any:
    path = REPO / "packages" / "omniweave-core" / "tests" / "unit" / "test_store_doc.py"
    spec = importlib.util.spec_from_file_location("_test_store_doc_for_retrieval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_sd = _load_store_doc()
harness = _sd.harness


def test_a_cite_is_sound_when_it_resolves_to_a_placed_live_block(harness: Any) -> None:
    from omniweave_core.store import sqlite as ow  # noqa: PLC0415

    written = _sd.write_happy_path(harness)
    connection = ow.connect(harness.path)
    try:
        cite = connection.execute(
            "SELECT cite FROM block WHERE block_id = ?", (int(written.paragraph),)
        ).fetchone()[0]
        plain = SimpleNamespace(evidence=(SimpleNamespace(cite=cite, byte_exact=False),))
        exact = SimpleNamespace(evidence=(SimpleNamespace(cite=cite, byte_exact=True),))
        assert cite_harness.check(connection, cite, plain)  # type: ignore[arg-type]
        assert not cite_harness.check(connection, "d999#1", plain)  # type: ignore[arg-type]
        assert not cite_harness.check(connection, cite, exact)  # type: ignore[arg-type]
        connection.execute("UPDATE block SET state = 1 WHERE cite = ?", (cite,))
        assert not cite_harness.check(connection, cite, plain)  # type: ignore[arg-type]
    finally:
        connection.close()


def test_an_answer_s_cites_are_its_headers_then_its_pointers_once_each() -> None:
    answer = SimpleNamespace(
        pointers=(SimpleNamespace(cites=("d1#3", "d1#1")),),
        withheld=(SimpleNamespace(cites=("d2#1",)),),
    )
    assert cite_harness._cites(answer, ("d1#1", "d1#2")) == ("d1#1", "d1#2", "d1#3", "d2#1")  # type: ignore[arg-type]
