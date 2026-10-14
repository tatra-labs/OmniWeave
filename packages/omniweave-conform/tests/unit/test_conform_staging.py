"""`omniweave_conform.staging`: per-worker NDJSON and the one-transaction import. D815."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from omniweave_conform.staging import (
    Imported,
    StagingError,
    StagingWriter,
    import_staging,
    read_staging,
    staging_path,
)
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import StoreError
from omniweave_core.store.oweval import (
    Assertion,
    Corpus,
    Counter,
    Perf,
    Run,
    Verdict,
    open_oweval,
)

if TYPE_CHECKING:
    from pathlib import Path

_MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="pdfium",
    runtime_version="6721",
    sampling="{}",
    prompt_version="n/a",
    hardware="x86_64-windows 8c/16GiB",
    corpus="omniweave-golden@2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    harness_version="0.1.0",
)

_CORPUS = Corpus(
    corpus_id="golden",
    version="2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    tier="A",
    n_docs=1,
    n_assertions=4,
    n_checked=4,
    document_redistributable=True,
    assertions_redistributable=True,
    publishable=True,
)


def _run(run_id: str = "run-1", **over: object) -> Run:
    row = Run(
        run_id=run_id,
        suite="parse",
        corpus_id="golden",
        corpus_version="2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        subject="parse.pdf.pdfium",
        subject_version="0.1.0",
        producer_id=None,
        measured_on=_MEASURED,
        timing_basis="in_process",
        witness="ci",
        cassette="required",
        policy_digest=None,
        pricebook_digest=None,
        harness_version="0.1.0",
        code_fingerprint="c0ffee",
        hardware="x86_64-windows 8c/16GiB",
        started_ns=1,
        ended_ns=2,
        status="ok",
    )
    return replace(row, **over)


def _assertion(assertion_id: str, *slices: str, checked: str | None = "verified") -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        corpus_id="golden",
        corpus_version="2026.09",
        doc="d",
        page=1,
        type="present",
        spec={"text": assertion_id},
        addr=None,
        evaluable_in="both",
        checked=checked,
        derived_from_sha256="sha256:" + "cd" * 32,
        slices=slices,
    )


_ASSERTIONS = (
    _assertion("a1", "office/docx"),
    _assertion("a2", "office/docx"),
    _assertion("a3", "pdf/scan"),
    _assertion("a4"),
)


def _verdict(assertion_id: str, run_id: str = "run-1", **over: object) -> Verdict:
    row = Verdict(
        run_id=run_id,
        assertion_id=assertion_id,
        evaluator="owdoc",
        passed=True,
        score=None,
        slice_key="office/docx",
    )
    return replace(row, **over)


def _stage_all(root: Path) -> None:
    """Two workers, every assertion answered, a counter and a perf reading."""
    with StagingWriter(root, "run-1", "gw0") as one:
        one.add(_verdict("a1"))
        one.add(_verdict("a2", passed=False, explanation="absent"))
        one.add(Counter(run_id="run-1", counter="renders", scope="corpus", value=3))
    with StagingWriter(root, "run-1", "gw1") as two:
        two.add(_verdict("a3", slice_key="pdf/scan"))
        two.add(_verdict("a4", slice_key="*"))
        two.add(
            Perf(
                run_id="run-1",
                budget_id="parse.p50_ms",
                pacer_before_ns=1,
                pacer_after_ns=1,
                work_ns=4,
                time_ratio=4.0,
                peak_rss_bytes=None,
                peak_wal_bytes=None,
                status="pass",
            )
        )


def _import(tmp_path: Path, runs: tuple[Run, ...] = (_run(),)) -> Imported:
    return import_staging(
        tmp_path / "e.oweval",
        tmp_path / "staging",
        corpora=(_CORPUS,),
        assertions=_ASSERTIONS,
        runs=runs,
    )


def _run_row(tmp_path: Path, run_id: str = "run-1") -> tuple[str, str]:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        row = connection.execute(
            "SELECT status, not_measured FROM eval_run WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        connection.close()
    return row[0], row[1]


# --- the file name and the writer --------------------------------------------------------------


def test_the_name_is_run_then_worker(tmp_path: Path) -> None:
    assert staging_path(tmp_path, "nightly-2026.10.14", "gw3").name == (
        "nightly-2026.10.14.gw3.ndjson"
    )


@pytest.mark.parametrize(
    ("run_id", "worker_id"), [("r", "g.w"), ("r/x", "gw0"), ("r", "a\\b"), ("", "gw0"), ("r", "")]
)
def test_a_name_that_cannot_parse_back_is_refused(
    tmp_path: Path, run_id: str, worker_id: str
) -> None:
    with pytest.raises(StagingError):
        staging_path(tmp_path, run_id, worker_id)


def test_a_writer_owns_its_file(tmp_path: Path) -> None:
    with StagingWriter(tmp_path, "run-1", "gw0"), pytest.raises(FileExistsError):
        StagingWriter(tmp_path, "run-1", "gw0")


def test_each_row_is_one_sorted_line(tmp_path: Path) -> None:
    with StagingWriter(tmp_path, "run-1", "gw0") as writer:
        writer.add(_verdict("a1"))
        writer.add(Counter(run_id="run-1", counter="c", scope="s", value=1))
    lines = writer.path.read_bytes().split(b"\n")
    assert lines[-1] == b""
    first = json.loads(lines[0])
    assert first["t"] == "eval_verdict"
    assert list(first) == sorted(first)
    assert json.loads(lines[1]) == {
        "t": "eval_counter",
        "run_id": "run-1",
        "counter": "c",
        "scope": "s",
        "value": 1,
    }


def test_a_writer_refuses_another_runs_row(tmp_path: Path) -> None:
    with (
        StagingWriter(tmp_path, "run-1", "gw0") as writer,
        pytest.raises(StagingError, match="cannot be staged"),
    ):
        writer.add(_verdict("a1", run_id="run-2"))


# --- reading ---------------------------------------------------------------------------------


def test_reading_returns_every_row(tmp_path: Path) -> None:
    _stage_all(tmp_path / "staging")
    staged = read_staging(tmp_path / "staging")
    assert [v.assertion_id for v in staged.verdicts] == ["a1", "a2", "a3", "a4"]
    assert len(staged.counters) == 1
    assert len(staged.perf) == 1
    assert staged.truncated == ()


def test_a_truncated_final_line_is_dropped_and_named(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    _stage_all(root)
    path = staging_path(root, "run-1", "gw1")
    data = path.read_bytes()
    path.write_bytes(data[: data.rindex(b"\n", 0, len(data) - 1) + 1] + b'{"t":"eval_pe')
    staged = read_staging(root)
    assert staged.perf == ()
    assert staged.truncated == (("run-1", "run-1.gw1.ndjson"),)


def test_a_tail_cut_inside_a_character_is_dropped_undecoded(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    with StagingWriter(root, "run-1", "gw0") as writer:
        writer.add(_verdict("a1"))
    path = staging_path(root, "run-1", "gw0")
    path.write_bytes(path.read_bytes() + '{"explanation":"café'.encode()[:-1])
    staged = read_staging(root)
    assert len(staged.verdicts) == 1
    assert staged.truncated == (("run-1", "run-1.gw0.ndjson"),)


def test_a_bad_line_before_the_last_is_corruption(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    _stage_all(root)
    path = staging_path(root, "run-1", "gw0")
    lines = path.read_bytes().split(b"\n")
    lines[1] = b'{"t":"eval_verdict","nonsense":1}'
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(StagingError, match=r"run-1\.gw0\.ndjson:2 is not a staging row"):
        read_staging(root)


def test_a_row_of_another_run_in_a_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    line = json.dumps(
        {"t": "eval_counter", "run_id": "run-2", "counter": "c", "scope": "s", "value": 1}
    )
    staging_path(root, "run-1", "gw0").write_text(line + "\n", encoding="utf-8")
    with pytest.raises(StagingError, match="is a row of 'run-2'"):
        read_staging(root)


# --- importing -------------------------------------------------------------------------------


def test_a_whole_staging_imports_as_ok(tmp_path: Path) -> None:
    _stage_all(tmp_path / "staging")
    got = _import(tmp_path)
    assert got.status == {"run-1": "ok"}
    assert (got.verdicts, got.counters, got.perf, got.dropped) == (4, 1, 1, 0)
    assert _run_row(tmp_path) == ("ok", "[]")
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        assert connection.execute("SELECT count(*) FROM eval_verdict").fetchone() == (4,)
    finally:
        connection.close()


def test_a_truncated_line_makes_the_run_partial(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    _stage_all(root)
    path = staging_path(root, "run-1", "gw1")
    path.write_bytes(path.read_bytes() + b'{"t":"eval_coun')
    got = _import(tmp_path)
    assert got.status == {"run-1": "partial"}
    status, scope = _run_row(tmp_path)
    assert status == "partial"
    assert json.loads(scope) == ["run-1.gw1.ndjson: a truncated final line, dropped"]


def test_a_missing_verdict_names_its_slices(tmp_path: Path) -> None:
    """a2 (office/docx) and a4 (no slices) never answered: two slices named, each with its
    count against the slice's total, after the caller's own entries."""
    root = tmp_path / "staging"
    with StagingWriter(root, "run-1", "gw0") as writer:
        writer.add(_verdict("a1"))
        writer.add(_verdict("a3", slice_key="pdf/scan"))
    _import(tmp_path, runs=(_run(not_measured=("handwriting",)),))
    status, scope = _run_row(tmp_path)
    assert status == "partial"
    assert json.loads(scope) == [
        "handwriting",
        "*: 1 of 1 assertions produced no verdict",
        "office/docx: 1 of 2 assertions produced no verdict",
    ]


def test_a_rejected_assertion_is_not_expected_to_answer(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    with StagingWriter(root, "run-1", "gw0") as writer:
        writer.add(_verdict("a1"))
    got = import_staging(
        tmp_path / "e.oweval",
        root,
        corpora=(_CORPUS,),
        assertions=(_assertion("a1", "x"), _assertion("a9", "x", checked="rejected")),
        runs=(_run(),),
    )
    assert got.status == {"run-1": "ok"}


def test_an_unchecked_assertion_is_expected_to_answer(tmp_path: Path) -> None:
    """13:1022: `checked IS NULL` runs and never scores, so its silence is a loss."""
    root = tmp_path / "staging"
    with StagingWriter(root, "run-1", "gw0") as writer:
        writer.add(_verdict("a1"))
    got = import_staging(
        tmp_path / "e.oweval",
        root,
        corpora=(_CORPUS,),
        assertions=(_assertion("a1", "x"), _assertion("a9", "x", checked=None)),
        runs=(_run(),),
    )
    assert got.status == {"run-1": "partial"}


def test_an_unknown_run_stays_unknown(tmp_path: Path) -> None:
    (tmp_path / "staging").mkdir()
    got = _import(tmp_path, runs=(_run(status="unknown"),))
    assert got.status == {"run-1": "unknown"}
    status, scope = _run_row(tmp_path)
    assert status == "unknown"
    assert len(json.loads(scope)) == 3


def test_a_run_only_answers_for_its_own_corpus(tmp_path: Path) -> None:
    """Another corpus's assertions are no run's loss but their own runs'."""
    root = tmp_path / "staging"
    _stage_all(root)
    other = replace(_assertion("b1", "x"), corpus_version="2026.10")
    got = import_staging(
        tmp_path / "e.oweval",
        root,
        corpora=(_CORPUS, replace(_CORPUS, version="2026.10")),
        assertions=(*_ASSERTIONS, other),
        runs=(_run(),),
    )
    assert got.status == {"run-1": "ok"}


def test_rows_for_a_run_not_given_refuse_the_import(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    _stage_all(root)
    with StagingWriter(root, "run-9", "gw0") as writer:
        writer.add(_verdict("a1", run_id="run-9"))
    with pytest.raises(StagingError, match=r"\['run-9'\]"):
        _import(tmp_path)
    assert not (tmp_path / "e.oweval").exists()


def test_a_truncated_file_of_a_run_not_given_refuses_the_import(tmp_path: Path) -> None:
    """Its only line was cut, so it stages no row; the loss still names a run nobody gave."""
    root = tmp_path / "staging"
    _stage_all(root)
    root.joinpath("run-9.gw0.ndjson").write_bytes(b'{"t":"eval_ver')
    with pytest.raises(StagingError, match=r"\['run-9'\]"):
        _import(tmp_path)


def test_a_status_outside_the_check_is_refused(tmp_path: Path) -> None:
    (tmp_path / "staging").mkdir()
    with pytest.raises(StagingError, match="status outside"):
        _import(tmp_path, runs=(_run(status="skip"),))


def test_an_import_is_one_transaction(tmp_path: Path) -> None:
    """A staged row the store refuses takes every other row with it."""
    root = tmp_path / "staging"
    _stage_all(root)
    with StagingWriter(root, "run-1", "gw2") as writer:
        writer.add(_verdict("a1", evaluator="human"))
    with pytest.raises(StoreError, match="eval_verdict"):
        _import(tmp_path)
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        for table in ("eval_run", "eval_verdict", "eval_corpus", "eval_counter"):
            sql = f"SELECT count(*) FROM {table}"  # noqa: S608 -- a literal table name
            assert connection.execute(sql).fetchone() == (0,), table
    finally:
        connection.close()


def test_a_second_import_of_the_same_staging_is_refused_whole(tmp_path: Path) -> None:
    _stage_all(tmp_path / "staging")
    _import(tmp_path)
    before = (tmp_path / "e.oweval").read_bytes()
    with pytest.raises(StoreError, match=r"eval_run \(run_id='run-1'\) refused"):
        _import(tmp_path)
    assert (tmp_path / "e.oweval").read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == [
        "run-1.gw0.ndjson",
        "run-1.gw1.ndjson",
    ]
