"""`omniweave_conform.eval_run`: the parse suite as `.oweval` rows. D868.

The suite runs over the repository's own register, `eval/gates.toml`, and its two `[[subject]]`
rows: `parse.pdf.pdfium`, whose fixtures claim verbatimness, and `parse.office.anydoc`, whose do
not (13:661). The parse runs once per module; each test reads the batch it produced.
"""

from __future__ import annotations

import hashlib
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
from omniweave_conform import portability as cell_harness
from omniweave_conform import retrieval as cite_harness
from omniweave_conform import roundtrip as r2_harness
from omniweave_conform.damage import INJECTORS, TABLE, Assessment, Clause
from omniweave_conform.entry import run as entry_run
from omniweave_conform.release import SUITES as SUITES_SEVEN
from omniweave_conform.release import check_release
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Batch, open_oweval, scoreboard, write

REPO = Path(__file__).resolve().parents[4]
REGISTER: dict[str, Any] = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
PDFIUM, OFFICE = "parse.pdf.pdfium", "parse.office.anydoc"
SPAN = "span_exact_rate"
DRAFTED = (
    ("metric", "order_acc@__macro__ in parse/parse.office.anydoc"),
    ("metric", "order_acc@__macro__ in parse/parse.pdf.pdfium"),
    ("metric", "table_rel_acc@__macro__ in parse/parse.office.anydoc"),
)
"""D913: the drafted labels' rates, `unknown` until a reviewer verifies 30 in a slice, and each
one a refusal, run id aside."""


def _labels(fixtures: str) -> int:
    """D913: the `[[assertion]]` rows the subject's committed labels files hold."""
    return sum(
        len(tomllib.loads(path.read_text(encoding="utf-8")).get("assertion", []))
        for path in (REPO / fixtures).glob("*.assertions.toml")
    )


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
        assert (corpus.tier, corpus.publishable) == ("A", False)
        assert (corpus.n_assertions, corpus.n_checked) == (_labels(row["fixtures"]), 0)
        assert corpus.n_assertions > 0, "D913 drafted labels for both fixture sets"
        judged = [v for v in batch.verdicts if v.run_id == run.run_id]
        assert len(judged) == corpus.n_assertions
        assert [v.assertion_id for v in judged if not v.passed] == [], "every drafted label holds"
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
    (metric,) = [m for m in batch.metrics if m.metric == SPAN]
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
    assert not [m for m in batch.metrics if m.run_id == office.run_id and m.metric == SPAN]
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


def test_the_batch_writes_and_release_check_wants_the_other_four_gates(
    parsed: Any, tmp_path: Path
) -> None:
    batch, _ = parsed
    connection = open_oweval(tmp_path / "x.oweval")
    try:
        write(connection, batch)
        standing = {(row.metric, row.standing) for row in scoreboard(connection)}
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert standing == {(SPAN, "WITHHELD"), ("order_acc", "UNKNOWN"), ("table_rel_acc", "UNKNOWN")}
    drafted = judged.findings[: len(DRAFTED)]
    assert all(f.fix.startswith('verify its labels: write checked = "verified"') for f in drafted)
    assert all("unverified assertion(s) ran and were not scored" in f.why for f in drafted)
    assert [(f.kind, f.names.split(" run ")[0]) for f in judged.findings] == [
        *DRAFTED,
        ("unmeasured", "hard gate degradation_detection@*"),
        ("unmeasured", "hard gate citability_violations@*"),
        ("unmeasured", "hard gate address_survival@*"),
        ("unmeasured", "hard gate cell_identity@*"),
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
    survived = r2_harness.Element("u01/e1", "heading", True, "")
    monkeypatch.setattr(r2_harness, "judge", lambda target: _judged(target, survived))
    _fake_cells(monkeypatch)
    store = tmp_path / "both.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["parse", "absence", "retrieve", "roundtrip", "portability"],
        subject=None,
        witness="self",
        cassette="off",
        admit=lambda _argv: None,
    )
    assert done["suites"] == ["parse", "absence", "retrieve", "roundtrip", "portability"]
    rows: Any = done["runs"]
    assert [row["suite"] for row in rows] == [
        "parse",
        "parse",
        "absence",
        "retrieve",
        "roundtrip",
        "roundtrip",
        "portability",
        "portability",
        "portability",
    ]
    connection = open_oweval(store)
    try:
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert judged.runs == 9
    assert [(f.kind, f.names.split(" run ")[0]) for f in judged.findings] == list(DRAFTED), (
        "D913: every suite's hard gate holds; only the drafted labels' unverified rates refuse"
    )


@pytest.mark.parametrize(
    ("suites", "subject", "says"),
    [
        (["chemistry"], None, "roundtrip, portability, extract, perf, not chemistry"),
        (["portability"], PDFIUM, "the portability suite's subjects are its own"),
        (["retrieve"], PDFIUM, "the retrieve suite's subjects are its own"),
        (["roundtrip"], PDFIUM, "the roundtrip suite's subjects are its own"),
        ([], None, "not nothing"),
        (["absence"], PDFIUM, "the absence suite's subjects are its own"),
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
    """`test_store_doc.py`, by path, with omniweave-core's `conftest` as the one it imports.

    That file does `from conftest import PlanDocs`, and which `conftest` a bare import finds
    depends on which test pytest collected first: run alone, this file collected
    `packages/conftest.py` under that name and the import failed (D875).
    """
    tests = REPO / "packages" / "omniweave-core" / "tests"
    own = importlib.util.spec_from_file_location("_core_tests_conftest", tests / "conftest.py")
    assert own is not None and own.loader is not None
    conftest = importlib.util.module_from_spec(own)
    sys.modules[own.name] = conftest
    own.loader.exec_module(conftest)
    path = tests / "unit" / "test_store_doc.py"
    spec = importlib.util.spec_from_file_location("_test_store_doc_for_retrieval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = sys.modules.get("conftest")
    sys.modules["conftest"] = conftest
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is not None:
            sys.modules["conftest"] = previous
        else:
            del sys.modules["conftest"]
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


# --- the roundtrip suite (D871) -----------------------------------------------------------------


def test_a_target_row_resolves_its_paths_and_its_path_valued_config() -> None:
    docx, pptx = r2_harness.targets(REGISTER, REPO)
    assert (docx.target, pptx.target) == ("docx", "pptx")
    assert docx.card == REPO / REGISTER["target"][0]["card"]
    assert docx.golden == REPO / "fixtures" / "out" / "golden" / "docx"
    assert docx.config == {}
    assert pptx.config == {"font_dir": str(REPO / "fixtures" / "out" / "golden" / "pptx" / "fonts")}
    assert r2_harness.targets({}, REPO) == ()


def test_the_docx_golden_compiles_reads_back_and_every_address_survives() -> None:
    docx = r2_harness.targets(REGISTER, REPO)[0]
    judged = r2_harness.judge(docx)
    assert (judged.driver, judged.gate, judged.unknown) == (
        "compile.docx.native",
        "manual-required",
        None,
    )
    assert judged.elements
    assert all(element.passed for element in judged.elements)
    assert {element.el.split("/", 1)[0] for element in judged.elements} == {"u01", "u02"}
    assert len(judged.fingerprint) == 64
    assert [path.name for path in judged.il_units] == ["il.toml", "u01.html", "u02.html"]


def _judged(target: Any, *elements: Any, unknown: str | None = None) -> r2_harness.Judged:
    return r2_harness.Judged(
        target=target,
        driver=f"compile.{target.target}.native",
        version="0.1.0",
        gate="manual-required",
        elements=tuple(elements),
        unknown=unknown,
        il_units=(target.golden / "il" / ("u01.svg" if target.target == "pptx" else "u01.html"),),
        fingerprint="f" * 64,
    )


def _roundtrip(monkeypatch: pytest.MonkeyPatch, judge: Any) -> Any:
    monkeypatch.setattr(r2_harness, "judge", judge)
    return eval_run.roundtrip(REGISTER, root=REPO, witness="self", cassette="off", now_ns=_clock())


def test_each_element_is_one_roundtrip_assertion_and_one_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def judge(target: Any) -> Any:
        if target.target == "pptx":
            return _judged(target, unknown="the gate is unverified; lower() is unreachable")
        return _judged(
            target,
            r2_harness.Element("u01/e1", "heading", True, ""),
            r2_harness.Element("u01/e2", "para", False, "missing: no read-back Block carries it"),
        )

    batch, done = _roundtrip(monkeypatch, judge)
    docx_run, pptx_run = batch.runs
    assert (docx_run.suite, docx_run.subject, docx_run.status) == (
        "roundtrip",
        "compile.docx.native",
        "ok",
    )
    assert docx_run.code_fingerprint == "f" * 64
    assert eval_run.ROUNDTRIP_CONFOUNDER in docx_run.confounders
    assert docx_run.confounders[2].startswith("1 element(s) failed R2: u01/e2 (missing:")
    assert pptx_run.status == "unknown"
    assert pptx_run.not_measured[0] == "R2: the gate is unverified; lower() is unreachable"
    docx_corpus = next(c for c in batch.corpora if c.corpus_id == docx_run.corpus_id)
    assert docx_run.corpus_id == "fixtures/out/golden/docx"
    assert (docx_corpus.n_assertions, docx_corpus.n_checked, docx_corpus.publishable) == (
        2,
        0,
        False,
    )
    ids = [a.assertion_id for a in batch.assertions]
    assert ids == [
        f"roundtrip/docx@{docx_corpus.version}/u01/e1",
        f"roundtrip/docx@{docx_corpus.version}/u01/e2",
    ]
    first = batch.assertions[0]
    assert (first.type, first.addr, first.doc, first.evaluable_in, first.checked) == (
        "roundtrip",
        "u01/e1",
        "il/u01.html",
        "owdoc",
        None,
    )
    unit = REPO / "fixtures" / "out" / "golden" / "docx" / "il" / "u01.html"
    assert first.derived_from_sha256 == hashlib.sha256(unit.read_bytes()).hexdigest()
    assert dict(first.spec) == {"law": "r2", "construct": "heading"}
    assert [(v.assertion_id, v.passed, v.slice_key) for v in batch.verdicts] == [
        (ids[0], True, "docx"),
        (ids[1], False, "docx"),
    ]
    assert batch.verdicts[1].explanation == "missing: no read-back Block carries it"
    (metric,) = batch.metrics  # the unjudged pptx run writes none (D902)
    assert (metric.run_id, metric.metric, metric.slice_key, metric.value, metric.n) == (
        docx_run.run_id,
        "address_survival",
        "docx",
        0.5,
        2,
    )
    assert (metric.truth_kind, metric.state) == ("native_run", "ok")
    assert [(d.value, d.n, d.parsed) for d in done] == [(0.5, 2, 1), (None, 0, 0)]
    assert {d.metric for d in done} == {"address_survival"}
    assert done[1].refused == ("unknown: the gate is unverified; lower() is unreachable",)


def test_an_unjudged_target_is_an_unknown_run_release_check_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    batch, _ = _roundtrip(monkeypatch, lambda target: _judged(target, unknown="no reader"))
    connection = open_oweval(tmp_path / "r.oweval")
    try:
        write(connection, batch)
        judged = check_release(connection, {"gate": []}, strict=False)
    finally:
        connection.close()
    assert [f.kind for f in judged.findings] == ["run", "run"]
    assert "R2: no reader" in judged.findings[0].why


def test_a_roundtrip_suite_with_no_target_or_a_failing_target_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(QualityError, match="names no \\[\\[target\\]\\]"):
        eval_run.roundtrip({"gate": []}, root=REPO, witness="self", cassette="off", now_ns=_clock())

    def broken(_target: Any) -> Any:
        raise TypeError("not a driver card")

    with pytest.raises(QualityError, match="could not run docx: TypeError: not a driver card"):
        _roundtrip(monkeypatch, broken)


def test_the_entry_point_writes_a_roundtrip_run_s_assertions_and_verdicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        r2_harness,
        "judge",
        lambda target: _judged(target, r2_harness.Element("u01/e1", "heading", True, "")),
    )
    store = tmp_path / "rt.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["roundtrip"],
        subject=None,
        witness="self",
        cassette="off",
        admit=lambda _argv: None,
    )
    rows: Any = done["runs"]
    assert [(row["suite"], row["slice"], row["value"]) for row in rows] == [
        ("roundtrip", "docx", 1.0),
        ("roundtrip", "pptx", 1.0),
    ]
    connection = open_oweval(store)
    try:
        counts = [
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("eval_assertion", "eval_verdict", "eval_run")
        ]
    finally:
        connection.close()
    assert counts == [2, 2, 2]


# --- the suites this build cannot measure (D872) ------------------------------------------------


@pytest.mark.parametrize("suite", ["extract", "perf"])
def test_an_unmeasurable_suite_writes_one_unknown_run_naming_why(suite: str) -> None:
    batch, (done,) = eval_run.unknown(suite, witness="self", cassette="off", now_ns=_clock())
    (run,) = batch.runs
    assert (run.suite, run.subject, run.status, run.corpus_id) == (
        suite,
        "omniweave",
        "unknown",
        "none",
    )
    assert run.not_measured == (eval_run.UNMEASURABLE[suite],)
    assert run.confounders[0].startswith("nothing was measured")
    assert (batch.corpora, batch.metrics, batch.perf, batch.verdicts) == ((), (), (), ())
    assert (done.metric, done.value, done.refused) == (
        "none",
        None,
        (eval_run.UNMEASURABLE[suite],),
    )


def test_every_suite_is_measured_or_says_why_it_cannot_be() -> None:
    assert set(eval_run.SUITES) == set(SUITES_SEVEN)
    assert set(eval_run.BUILT).isdisjoint(eval_run.UNMEASURABLE)
    with pytest.raises(QualityError, match="'parse' is a suite this build measures"):
        eval_run.unknown("parse", witness="self", cassette="off", now_ns=_clock())


def test_release_check_refuses_an_unknown_run_by_its_reason(tmp_path: Path) -> None:
    store = tmp_path / "u.oweval"
    done = entry_run(
        oweval=str(store),
        gates=str(REPO / "eval" / "gates.toml"),
        root=str(REPO),
        suites=["perf"],
        subject=None,
        witness="self",
        cassette="off",
        admit=lambda _argv: None,
    )
    assert done["suites"] == ["perf"]
    connection = open_oweval(store)
    try:
        judged = check_release(connection, {"gate": []}, strict=False)
    finally:
        connection.close()
    [finding] = judged.findings
    assert finding.kind == "run"
    assert finding.why == "status unknown; not measured: " + eval_run.UNMEASURABLE["perf"]
    assert finding.fix == "fix what stopped the run, then ow eval run --suite perf"


def test_a_register_without_the_address_survival_row_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 16: the roundtrip suite measures against its hard row, as absence does its own."""
    monkeypatch.setattr(r2_harness, "judge", _judged)
    without = {**REGISTER, "gate": [g for g in REGISTER["gate"] if g["suite"] != "roundtrip"]}
    with pytest.raises(QualityError, match="no roundtrip address_survival row"):
        eval_run.roundtrip(without, root=REPO, witness="self", cassette="off", now_ns=_clock())


# --- the portability suite (D903) ---------------------------------------------------------------

_FROZEN_PARTS = cell_harness.read_parts(REPO)


def _fake_cells(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shapes: tuple[dict[str, str], dict[str, str]] = ({"a.shape": "1"}, {"a.shape": "1"}),
    parts: dict[str, dict[str, str]] | None = None,
) -> None:
    """The two halves, faked: the shapes as given, each target's parts its frozen ones or these."""
    produced = parts if parts is not None else _FROZEN_PARTS
    monkeypatch.setattr(cell_harness, "shapes", lambda _root: shapes)
    monkeypatch.setattr(
        cell_harness,
        "parts",
        lambda target: (
            f"compile.{target.target}.native",
            "0.1.0",
            "f" * 64,
            produced[target.target],
        ),
    )


def _portability(register: dict[str, Any] = REGISTER) -> tuple[Batch, tuple[Any, ...]]:
    return eval_run.portability(
        register, root=REPO, witness="self", cassette="off", now_ns=_clock()
    )


def test_portability_is_a_shape_run_then_one_run_per_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_cells(monkeypatch)
    batch, done = _portability()
    assert [(r.subject, r.timing_basis, r.status) for r in batch.runs] == [
        ("omniweave", "spawn_inclusive", "ok"),
        ("compile.docx.native", "in_process", "ok"),
        ("compile.pptx.native", "in_process", "ok"),
    ]
    assert [run.corpus_id for run in batch.runs] == [
        "fixtures/index.toml",
        "fixtures/out/golden/docx",
        "fixtures/out/golden/pptx",
    ]
    assert {c.corpus_id: (c.tier, c.publishable) for c in batch.corpora} == {
        run.corpus_id: ("A", False) for run in batch.runs
    }
    assert [(m.metric, m.slice_key, m.value, m.truth_kind) for m in batch.metrics] == [
        ("cell_identity", "shape", 1.0, "native_run"),
        ("cell_identity", "docx", 1.0, "native_run"),
        ("cell_identity", "pptx", 1.0, "native_run"),
    ]
    assert [m.n for m in batch.metrics] == [1, *(len(p) for p in _FROZEN_PARTS.values())]
    assert all(run.confounders[0] == eval_run.CELL_CONFOUNDER for run in batch.runs)
    assert [(row.slice_key, row.refused) for row in done] == [
        ("shape", ()),
        ("docx", ()),
        ("pptx", ()),
    ]
    connection = open_oweval(tmp_path / "p.oweval")
    try:
        write(connection, batch)
        judged = check_release(connection, REGISTER, strict=False)
    finally:
        connection.close()
    assert "hard gate cell_identity@*" not in [f.names for f in judged.findings]


def test_a_shape_or_part_that_moved_lowers_the_rate_and_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx = dict(_FROZEN_PARTS["docx"])
    docx.pop("word/document.xml")
    _fake_cells(
        monkeypatch,
        shapes=({"a.shape": "1", "b.shape": "2"}, {"a.shape": "1", "b.shape": "3", "c.shape": "4"}),
        parts={**_FROZEN_PARTS, "docx": docx},
    )
    batch, done = _portability()
    shape, word = batch.metrics[0], batch.metrics[1]
    assert (shape.value, shape.n) == (pytest.approx(1 / 3), 3)
    assert done[0].refused == ("b.shape: differs", "c.shape: not frozen")
    assert word.n == len(_FROZEN_PARTS["docx"])
    assert word.value == pytest.approx((word.n - 1) / word.n)
    assert done[1].refused == ("word/document.xml: missing",)
    assert batch.runs[1].confounders[1] == (f"1 of {word.n} differ: word/document.xml: missing")


def test_no_frozen_shape_is_an_unknown_run_with_no_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_cells(monkeypatch, shapes=({}, {}))
    batch, done = _portability()
    assert batch.runs[0].status == "unknown"
    assert batch.runs[0].not_measured[0].startswith("nothing frozen to compare")
    assert [m.slice_key for m in batch.metrics] == ["docx", "pptx"]
    assert done[0].value is None


def test_a_target_the_parts_table_lacks_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(_root: Path) -> Any:
        raise AssertionError("ingested before the refusal")

    monkeypatch.setattr(cell_harness, "read_parts", lambda _root: {"docx": {"x": "y"}})
    monkeypatch.setattr(cell_harness, "shapes", never)
    with pytest.raises(QualityError, match=r"eval/portability.toml has no row for pptx") as raised:
        _portability()
    assert "tools/ow_portability.py --write" in raised.value.fix


def test_an_ingest_or_a_compile_that_fails_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def fails(_root: Path) -> Any:
        raise OSError("ow add exited 70: boom")

    _fake_cells(monkeypatch)
    monkeypatch.setattr(cell_harness, "shapes", fails)
    with pytest.raises(QualityError, match="could not ingest the Tier-A fixtures: ow add exited"):
        _portability()

    def broken(_target: Any) -> Any:
        raise RuntimeError("no compiler")

    _fake_cells(monkeypatch)
    monkeypatch.setattr(cell_harness, "parts", broken)
    with pytest.raises(QualityError, match="could not compile docx: RuntimeError: no compiler"):
        _portability()


def test_a_register_without_the_cell_identity_row_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_cells(monkeypatch)
    without = {**REGISTER, "gate": [g for g in REGISTER["gate"] if g["suite"] != "portability"]}
    with pytest.raises(QualityError, match="no portability cell_identity row"):
        _portability(without)
