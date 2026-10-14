"""`omniweave_core.store.oweval`: the `.oweval` file's schema, open, write and view. D814."""

from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

import pytest
from omniweave_core.canonical import canonical
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import StoreError
from omniweave_core.store import oweval
from omniweave_core.store.oweval import (
    EVAL_SCHEMA,
    EVAL_TABLES,
    Assertion,
    Batch,
    Calibration,
    Corpus,
    Counter,
    Flake,
    Metric,
    Perf,
    Run,
    Verdict,
    open_oweval,
    scoreboard,
    user_version,
    write,
)
from omniweave_core.store.sqlite import connect

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


def _corpus(**over: object) -> Corpus:
    row = Corpus(
        corpus_id="omniweave-golden",
        version="2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        tier="A",
        n_docs=2,
        n_assertions=3,
        n_checked=3,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=True,
    )
    return replace(row, **over)


def _run(run_id: str = "run-1", **over: object) -> Run:
    row = Run(
        run_id=run_id,
        suite="parse",
        corpus_id="omniweave-golden",
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
        started_ns=1_000,
        ended_ns=2_000,
        status="ok",
    )
    return replace(row, **over)


def _assertion(assertion_id: str, **over: object) -> Assertion:
    row = Assertion(
        assertion_id=assertion_id,
        corpus_id="omniweave-golden",
        corpus_version="2026.09",
        doc="sec-10k",
        page=3,
        type="present",
        spec={"text": "Net revenue", "case": "fold"},
        addr=None,
        evaluable_in="both",
        checked="verified",
        derived_from_sha256="sha256:" + "cd" * 32,
        slices=("office/docx",),
    )
    return replace(row, **over)


def _verdict(assertion_id: str, *, run_id: str = "run-1", **over: object) -> Verdict:
    row = Verdict(
        run_id=run_id,
        assertion_id=assertion_id,
        evaluator="owdoc",
        passed=True,
        score=None,
        slice_key="office/docx",
    )
    return replace(row, **over)


def _metric(run_id: str = "run-1", **over: object) -> Metric:
    row = Metric(
        run_id=run_id,
        metric="span_exact_rate",
        value=1.0,
        n=40,
        ci_lo=0.912,
        ci_hi=1.0,
        method="closed_form",
        truth_kind="rendered",
        state="ok",
    )
    return replace(row, **over)


def _batch() -> Batch:
    ids = ("a1", "a2", "a3")
    return Batch(
        corpora=(_corpus(),),
        assertions=tuple(_assertion(i) for i in ids),
        runs=(_run(not_measured=("handwriting", "math"), confounders=("one embedder",)),),
        verdicts=tuple(
            _verdict(i, passed=i != "a2", explanation="" if i != "a2" else "absent") for i in ids
        ),
        metrics=(_metric(),),
        counters=(Counter(run_id="run-1", counter="renders", scope="corpus", value=7),),
        perf=(
            Perf(
                run_id="run-1",
                budget_id="parse.p50_ms",
                pacer_before_ns=100,
                pacer_after_ns=110,
                work_ns=420,
                time_ratio=4.0,
                peak_rss_bytes=None,
                peak_wal_bytes=None,
                status="pass",
            ),
        ),
        calibration=(
            Calibration(
                eval_set_id="parse-cal@2026.09",
                score_kind="block.trust",
                producer_id=41,
                slice_key="office/docx",
                bucket=0,
                bucket_lo=0.0,
                bucket_hi=1.0,
                n=212,
                n_correct=74,
                p_hat=74 / 212,
                wilson_lo=0.288,
                wilson_hi=0.415,
                ece=None,
                brier=None,
                label_sources=("human",),
                measured_at_ns=5,
                harness_version="0.1.0",
            ),
        ),
        flake=(Flake(test_id="t::x", day="2026-10-14", runs=4, fails=1, reran_green=1),),
    )


def _reversed(batch: Batch) -> Batch:
    names = Batch.__dataclass_fields__
    return replace(batch, **{name: tuple(reversed(getattr(batch, name))) for name in names})


# --- open --------------------------------------------------------------------------------------


def test_a_new_file_gets_the_schema_and_its_version(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        assert user_version(connection) == EVAL_SCHEMA == 1
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert names == set(EVAL_TABLES)
        views = connection.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()
        assert views == [("eval_scoreboard",)]
    finally:
        connection.close()


def test_reopening_applies_nothing(tmp_path: Path) -> None:
    path = tmp_path / "e.oweval"
    open_oweval(path).close()
    before = path.read_bytes()
    open_oweval(path).close()
    assert path.read_bytes() == before


def test_a_file_with_a_schema_and_no_version_is_refused(tmp_path: Path) -> None:
    """An `.owstore`, or anything else: it has tables and `user_version = 0`."""
    path = tmp_path / "other.db"
    connection = connect(path)
    connection.execute("CREATE TABLE meta (k TEXT)")
    connection.close()
    with pytest.raises(StoreError, match=r"not an \.oweval"):
        open_oweval(path)


def test_a_newer_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "e.oweval"
    connection = open_oweval(path)
    connection.execute(f"PRAGMA user_version = {EVAL_SCHEMA + 1}")
    connection.close()
    with pytest.raises(StoreError, match="newer than this harness"):
        open_oweval(path)


def test_a_version_without_its_tables_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "e.oweval"
    connection = open_oweval(path)
    connection.execute("DROP VIEW eval_scoreboard")
    connection.execute("DROP TABLE eval_flake")
    connection.close()
    with pytest.raises(StoreError, match="has no eval_flake"):
        open_oweval(path)


def test_the_chain_is_one_file_numbered_one() -> None:
    chain = oweval._chain()
    assert [(number, name) for number, name, _ in chain] == [(1, "0001_eval.sql")]


# --- the DDL against the charter ---------------------------------------------------------------


def _charter_columns(text: str) -> dict[str, list[str]]:
    """The charter's `.oweval` block: each table's column names, comments stripped."""
    start = text.index("#### `.oweval`")
    block = text[start : text.index("CREATE VIEW eval_scoreboard", start)]
    block = "\n".join(line.split("--", 1)[0] for line in block.splitlines())
    out = {}
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\)\s*STRICT", block, re.DOTALL):
        out[match[1]] = _columns(match[2])
    return out


def _columns(body: str) -> list[str]:
    items, depth, current = [], 0, ""
    for char in body:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    items.append(current)
    names = [item.split()[0] for item in items if item.strip()]
    return [name for name in names if name not in ("PRIMARY",)]


def test_every_table_has_the_charters_columns_but_two_rulings(tmp_path: Path, plan: object) -> None:
    """Rulings 3 and 8 are the only differences: 12-performance.md's `peak_wal_bytes` for the
    charter's `wal_peak_bytes` with both peaks NULLable, and `eval_run`'s two published lists."""
    plan.require()  # type: ignore[attr-defined]
    charter = _charter_columns(plan.text("_notes/charter.md"))  # type: ignore[attr-defined]
    assert sorted(charter) == sorted(EVAL_TABLES)
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        for table in EVAL_TABLES:
            info = connection.execute(f"PRAGMA table_info({table})").fetchall()
            shipped = [row[1] for row in info]
            want = charter[table]
            if table == "eval_perf":
                want = [("peak_wal_bytes" if c == "wal_peak_bytes" else c) for c in want]
                notnull = {row[1]: row[3] for row in info}
                assert notnull["peak_rss_bytes"] == 0
                assert notnull["peak_wal_bytes"] == 0
            if table == "eval_run":
                want = [*want, "not_measured", "confounders"]
            assert shipped == want, table
    finally:
        connection.close()


# --- write -------------------------------------------------------------------------------------


def test_a_batch_round_trips(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(connection, _batch())
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in EVAL_TABLES
        }
        assert counts == {
            "eval_corpus": 1,
            "eval_run": 1,
            "eval_assertion": 3,
            "eval_verdict": 3,
            "eval_metric": 1,
            "eval_calibration": 1,
            "eval_counter": 1,
            "eval_perf": 1,
            "eval_flake": 1,
        }
        measured, fairness, degradations, unpinned, scope, confounders = connection.execute(
            "SELECT measured_on, fairness, degradations, unpinned, not_measured, confounders "
            "FROM eval_run"
        ).fetchone()
        assert measured == canonical(asdict(_MEASURED)).decode()
        assert (fairness, degradations, unpinned) == ("{}", "[]", 0)
        assert scope == '["handwriting","math"]'
        assert confounders == '["one embedder"]'
        spec, slices = connection.execute(
            "SELECT spec, slices FROM eval_assertion WHERE assertion_id = 'a1'"
        ).fetchone()
        assert spec == '{"case":"fold","text":"Net revenue"}'
        assert slices == '["office/docx"]'
        assert connection.execute(
            "SELECT passed, explanation FROM eval_verdict ORDER BY assertion_id"
        ).fetchall() == [(1, ""), (0, "absent"), (1, "")]
        assert connection.execute(
            "SELECT peak_rss_bytes, peak_wal_bytes FROM eval_perf"
        ).fetchone() == (None, None)
        assert connection.execute("SELECT label_sources FROM eval_calibration").fetchone() == (
            '["human"]',
        )
    finally:
        connection.close()


def test_the_file_does_not_depend_on_the_order_rows_arrive_in(tmp_path: Path) -> None:
    """Ruling 5: the same rows in another order make the same bytes."""
    one, two = tmp_path / "one.oweval", tmp_path / "two.oweval"
    for path, batch in ((one, _batch()), (two, _reversed(_batch()))):
        connection = open_oweval(path)
        write(connection, batch)
        connection.close()
    assert one.read_bytes() == two.read_bytes()


@pytest.mark.parametrize(
    ("change", "table"),
    [
        ({"verdicts": (_verdict("a1", evaluator="human"),)}, "eval_verdict"),
        ({"metrics": (_metric(method="bootstrap"),)}, "eval_metric"),
        ({"metrics": (_metric(state="pass"),)}, "eval_metric"),
        ({"metrics": (_metric(truth_kind="vibes"),)}, "eval_metric"),
        ({"runs": (_run(status="skip"),)}, "eval_run"),
        ({"runs": (_run(witness="vendor"),)}, "eval_run"),
        ({"corpora": (_corpus(tier="E"),)}, "eval_corpus"),
        ({"verdicts": (_verdict("a1", run_id="run-9"),)}, "eval_verdict"),
        ({"verdicts": (_verdict("zz"),)}, "eval_verdict"),
    ],
)
def test_a_refused_row_writes_nothing(
    tmp_path: Path, change: dict[str, tuple[object, ...]], table: str
) -> None:
    """A CHECK or a foreign key refuses one row, and the whole batch rolls back (ruling 4)."""
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        bad = replace(_batch(), **change)
        with pytest.raises(StoreError, match=table):
            write(connection, bad)
        assert not connection.in_transaction
        for name in EVAL_TABLES:
            sql = f"SELECT count(*) FROM {name}"  # noqa: S608
            assert connection.execute(sql).fetchone() == (0,), name
    finally:
        connection.close()


def test_eval_perf_refuses_a_status_outside_eval_status(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        perf = replace(_batch().perf[0], status="pass_with_warnings")
        with pytest.raises(StoreError, match="eval_perf"):
            write(connection, replace(_batch(), perf=(perf,)))
    finally:
        connection.close()


def test_a_corpus_repeats_identically_or_not_at_all(tmp_path: Path) -> None:
    """Ruling 6: a second run against the same corpus names the same rows, which are kept."""
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(connection, _batch())
        again = Batch(
            corpora=(_corpus(),),
            assertions=(_assertion("a1"),),
            runs=(_run("run-2"),),
            verdicts=(_verdict("a1", run_id="run-2"),),
        )
        write(connection, again)
        assert connection.execute("SELECT count(*) FROM eval_run").fetchone() == (2,)
        changed = Batch(corpora=(_corpus(n_docs=3),))
        with pytest.raises(StoreError, match="immutable"):
            write(connection, changed)
        moved = Batch(assertions=(_assertion("a1", page=4),))
        with pytest.raises(StoreError, match="immutable"):
            write(connection, moved)
    finally:
        connection.close()


def test_a_run_is_imported_once(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(connection, _batch())
        with pytest.raises(StoreError, match=r"eval_run \(run_id='run-1'\) refused"):
            write(connection, Batch(runs=(_run(),)))
    finally:
        connection.close()


def test_deleting_a_run_cascades_to_its_rows(tmp_path: Path) -> None:
    """13:1720's prune runs through the foreign keys; the corpus and assertions stay."""
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(connection, _batch())
        connection.execute("DELETE FROM eval_run WHERE run_id = 'run-1'")
        for table in ("eval_verdict", "eval_metric", "eval_counter", "eval_perf"):
            sql = f"SELECT count(*) FROM {table}"  # noqa: S608
            assert connection.execute(sql).fetchone() == (0,), table
        assert connection.execute("SELECT count(*) FROM eval_assertion").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM eval_corpus").fetchone() == (1,)
    finally:
        connection.close()


# --- the view ----------------------------------------------------------------------------------


def test_the_scoreboard_computes_each_standing(tmp_path: Path) -> None:
    connection = open_oweval(tmp_path / "e.oweval")
    try:
        write(
            connection,
            Batch(
                corpora=(_corpus(), _corpus(version="2026.10", publishable=False)),
                runs=(
                    _run("ranked"),
                    _run("self", witness="self"),
                    _run("pinless", unpinned=True),
                    _run("biased", entrant_bias=True),
                    _run("withheld", corpus_version="2026.10"),
                    _run("dead", status="unknown"),
                    _run("partial", status="partial"),
                ),
                metrics=(
                    _metric("ranked"),
                    _metric("ranked", metric="agree_rate", truth_kind="agreement"),
                    _metric("ranked", metric="recall", state="unknown", value=None),
                    _metric("self"),
                    _metric("pinless"),
                    _metric("biased"),
                    _metric("withheld"),
                    _metric("dead"),
                    _metric("partial"),
                ),
            ),
        )
        board = scoreboard(connection)
        got = sorted((row.metric, row.subject_version, row.witness, row.standing) for row in board)
        standings = [row.standing for row in board]
        assert len(board) == 8
        assert standings.count("RANKED") == 2
        assert standings.count("UNRANKED") == 4
        assert standings.count("WITHHELD") == 1
        assert standings.count("UNKNOWN") == 1
        assert ("agree_rate", "0.1.0", "ci", "UNRANKED") in got
        assert ("recall", "0.1.0", "ci", "UNKNOWN") in got
        assert all(isinstance(row.publishable, bool) for row in board)
    finally:
        connection.close()
