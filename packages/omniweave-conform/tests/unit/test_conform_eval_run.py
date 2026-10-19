"""`omniweave_conform.eval_run`: the parse suite as `.oweval` rows. D868.

The suite runs over the repository's own register, `eval/gates.toml`, and its two `[[subject]]`
rows: `parse.pdf.pdfium`, whose fixtures claim verbatimness, and `parse.office.anydoc`, whose do
not (13:661). The parse runs once per module; each test reads the batch it produced.
"""

from __future__ import annotations

import tomllib
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import absence as absence_harness
from omniweave_conform import eval_run
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


def test_the_batch_writes_and_release_check_wants_only_the_absence_gate(
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
        ("unmeasured", "hard gate degradation_detection@*")
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


def test_the_entry_point_runs_both_suites_in_one_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(absence_harness, "run_suite", lambda *_a, **_k: _suite(True, True))
    store = tmp_path / "both.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["parse", "absence"],
        subject=None,
        witness="self",
        cassette="off",
        admit=lambda _argv: None,
    )
    assert done["suites"] == ["parse", "absence"]
    rows: Any = done["runs"]
    assert [row["suite"] for row in rows] == ["parse", "parse", "absence"]
    connection = open_oweval(store)
    try:
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert (judged.ok, judged.runs) == (True, 3)


@pytest.mark.parametrize(
    ("suites", "subject", "says"),
    [
        (["extract"], None, "measures parse, absence in this build, not extract"),
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
