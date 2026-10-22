"""`ow bench query` (D915): the golden query set, the harness's pieces and the runner's report.

A real build spawns `ow add`'s parse workers, so the end-to-end run over a small store is the
conform tier's (`tests/conform/test_bench_query_process.py`). Here the set is held to its
generator, the timing loop to an injected clock, and the report to a stand-in result.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave.run import bench, benchquery

REPO = Path(__file__).resolve().parents[4]


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load(REPO / "fixtures" / "gen" / "gen_golden_queries.py", "_owgen_golden_queries")
PDF = sys.modules["gen_5000p_pdf"]
RUNNER = _load(REPO / "tools" / "ow_bench.py", "_owtool_ow_bench_query")


# ---------------------------------------------------------------------------------------------
# The golden set
# ---------------------------------------------------------------------------------------------


def test_the_committed_set_is_the_generator_s_output() -> None:
    assert (REPO / benchquery.QUERIES).read_bytes() == GEN.render()


def test_forty_queries_eight_of_each_kind_every_page_in_the_smallest_store() -> None:
    queries = benchquery.load_queries(REPO)
    assert len(queries) == 40
    kinds = [one.kind for one in queries]
    assert {kind: kinds.count(kind) for kind in set(kinds)} == dict.fromkeys(
        ("heading", "phrase", "cell", "words", "absent"), 8
    )
    rows = [
        json.loads(line) for line in (REPO / benchquery.QUERIES).read_text("utf-8").splitlines()
    ]
    pages = [row["page"] for row in rows[1:] if row["page"] is not None]
    assert max(pages) <= GEN.MAX_PAGE == 200
    assert len({one.id for one in queries}) == 40


def test_a_query_is_written_from_the_generator_s_text_and_absent_words_are_not_in_it() -> None:
    queries = {one.id: one for one in benchquery.load_queries(REPO)}
    assert queries["heading-0"].text == PDF.heading_text(1)
    vocabulary = set(PDF.WORDS)
    for one in queries.values():
        if one.kind == "absent":
            assert not set(one.text.split()) & vocabulary, one.text


def test_a_set_of_another_schema_is_refused(tmp_path: Path) -> None:
    (tmp_path / benchquery.QUERIES).parent.mkdir(parents=True)
    (tmp_path / benchquery.QUERIES).write_text('{"schema": "x/2"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"is not omniweave\.golden-queries/1"):
        benchquery.load_queries(tmp_path)


# ---------------------------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------------------------


def test_query_is_runnable_and_names_what_it_does_not_measure() -> None:
    assert bench.SUBJECTS["query"].runnable
    assert "query" in bench.runnable()


class _Corpus:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def query(self, text: str) -> None:
        self.asked.append(text)


class _Clock:
    """Each read 2 ms after the last, so every timed query takes exactly 2 ms."""

    def __init__(self) -> None:
        self._ticks = count(0, 2_000_000)

    def monotonic_ns(self) -> int:
        return next(self._ticks)

    def wall_ns(self) -> int:
        return 0


def test_each_query_is_asked_once_untimed_then_timed_every_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corpus = _Corpus()
    monkeypatch.setattr("omniweave.corpus", lambda *_a, **_k: corpus)
    monkeypatch.setattr(benchquery, "_blocks", lambda _store: 8_401)
    queries = (
        benchquery.Query("a", "heading", "Article 1."),
        benchquery.Query("b", "absent", "quantum entanglement"),
    )
    result = benchquery.query(tmp_path, queries, pages=200, runs=3, merged=True, clock=_Clock())
    assert corpus.asked == ["Article 1.", "quantum entanglement"] * 4
    assert (result.total.n, result.total.p50, result.total.worst) == (6, 2.0, 2.0)
    assert [(s.name, s.n) for s in result.by_kind] == [("heading", 3), ("absent", 3)]
    assert (result.blocks, result.merged, result.narrowing_all) == (8_401, True, False)
    assert any("per-Channel" in gap for gap in result.not_measured)


def test_a_store_past_prefilter_max_says_its_narrowing_is_the_whole_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("omniweave.corpus", lambda *_a, **_k: _Corpus())
    monkeypatch.setattr(benchquery, "_blocks", lambda _store: benchquery.PREFILTER_MAX + 1)
    queries = (benchquery.Query("a", "heading", "x"),)
    assert benchquery.query(tmp_path, queries, pages=1, runs=1, merged=False).narrowing_all


def test_no_timed_pass_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one timed pass"):
        benchquery.query(tmp_path, (), pages=1, runs=0, merged=True)


# ---------------------------------------------------------------------------------------------
# The runner's report
# ---------------------------------------------------------------------------------------------


def _result(p50: float) -> Any:
    series = bench.Series.of("end-to-end", [p50] * 5)
    return SimpleNamespace(
        pages=5_000,
        blocks=210_001,
        runs=5,
        merged=True,
        total=series,
        by_kind=(bench.Series.of("heading", [p50]),),
        narrowing_all=True,
        not_measured=("vectors on: no encoder is installed by default",),
    )


def test_the_report_prints_b27_as_an_indication_naming_the_machine() -> None:
    out = StringIO()
    RUNNER.report_query(_result(168.0), out, runner="github-hosted ubuntu-latest")
    text = out.getvalue()
    assert "5,000 pages, 210,001 live blocks, 5 warm pass(es), FTS merged" in text
    assert "F50: 210,001 blocks; the default narrowing exceeds PREFILTER_MAX" in text
    assert (
        "query.warm_p50_ms = 180 +/- 20%: p50 168.0 ms is within it -- INDICATION, measured on "
        "github-hosted ubuntu-latest, not the pinned ow-bench-1"
    ) in text
    assert "not measured: vectors on" in text


def test_a_p50_past_the_band_is_outside_it() -> None:
    out = StringIO()
    RUNNER.report_query(_result(230.0), out, runner="an unpinned machine")
    assert "p50 230.0 ms is OUTSIDE it -- INDICATION" in out.getvalue()


def test_a_page_count_below_one_does_not_run(tmp_path: Path) -> None:
    out = StringIO()
    code = RUNNER.main(
        ["query", "--pages", "0", "--root", str(tmp_path / "r"), "--home", str(tmp_path)], out=out
    )
    assert code == RUNNER.EXIT_NOT_RUN
    assert "DID NOT RUN: --pages 0" in out.getvalue()


# ---------------------------------------------------------------------------------------------
# D916: the run kept as .oweval rows
# ---------------------------------------------------------------------------------------------


def _measured(*, before: int = 1_000_000_000, after: int = 1_010_000_000) -> Any:
    return benchquery.QueryResult(
        pages=5_000,
        blocks=210_001,
        runs=5,
        total=bench.Series.of("end-to-end", [95.0, 95.1, 96.0]),
        by_kind=(),
        merged=True,
        narrowing_all=True,
        not_measured=("vectors on: no encoder is installed by default",),
        pacer_before_ns=before,
        pacer_after_ns=after,
    )


def test_a_kept_run_is_one_corpus_one_perf_run_and_its_budget_row() -> None:
    kept = benchquery.batch_of(
        REPO, _measured(), machine="github-hosted ubuntu-latest", started_ns=1, ended_ns=2
    )
    (corpus,) = kept.corpora
    (run,) = kept.runs
    (row,) = kept.perf
    assert corpus.corpus_id == "fixtures/store/golden-queries.jsonl"
    assert corpus.version == corpus.corpus_digest[:16]
    assert (run.suite, run.subject, run.timing_basis, run.status) == (
        "perf",
        "omniweave",
        "in_process",
        "ok",
    )
    assert run.hardware.startswith("github-hosted ubuntu-latest (")
    assert run.measured_on.hardware == run.hardware
    assert any("seven-run rolling median on ow-bench-1" in gap for gap in run.not_measured)
    assert (row.budget_id, row.work_ns, row.status) == ("query.warm_p50_ms", 95_100_000, "unknown")
    assert row.run_id == run.run_id
    assert row.time_ratio == pytest.approx(95_100_000 / 1_005_000_000)


def test_pacer_readings_that_disagree_make_the_row_unstable_never_a_pass() -> None:
    kept = benchquery.batch_of(
        REPO, _measured(after=2_000_000_000), machine="m", started_ns=1, ended_ns=2
    )
    assert kept.perf[0].status == "unstable"


def test_a_run_whose_pacer_was_not_read_is_not_kept() -> None:
    with pytest.raises(ValueError, match="needs the Pacer read before and after"):
        benchquery.batch_of(REPO, _measured(before=0), machine="m", started_ns=1, ended_ns=2)


def test_the_runner_keeps_the_run_and_release_check_refuses_its_unknown_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from omniweave_core.store.oweval import open_oweval  # noqa: PLC0415

    monkeypatch.setattr(RUNNER.bench, "query", lambda *_a, **_k: _measured())
    monkeypatch.setenv("OMNIWEAVE_RUNNER", "github-hosted ubuntu-latest")
    store = tmp_path / "bench.oweval"
    out = StringIO()
    code = RUNNER.main(
        ["query", "--oweval", str(store), "--root", str(tmp_path / "r"), "--home", str(tmp_path)],
        out=out,
    )
    assert code == RUNNER.EXIT_CLEAN
    assert "kept: query.warm_p50_ms in" in out.getvalue()
    assert "measured on github-hosted ubuntu-latest, not the pinned ow-bench-1" in out.getvalue()
    connection = open_oweval(store)
    try:
        rows = connection.execute("SELECT budget_id, status FROM eval_perf").fetchall()
    finally:
        connection.close()
    assert rows == [("query.warm_p50_ms", "unknown")]
