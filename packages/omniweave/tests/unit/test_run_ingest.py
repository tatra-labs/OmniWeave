"""`ow ingest`: 02 section 4.1's hops 1-4 over real files, a real store and the real Supervisor.

Every configuration is a real `omniweave.toml` under `tmp_path` resolved by the real loader, every
store is created by the shipped migrations, and every walk is over real files. The loop is the
real `Supervisor` with `op.identify` as its dispatcher; `sweep_ms` is small for `bench.SWEEP_MS`'s
reason -- two quiet polls end a drain, and at the shipped 5,000 ms that is ten seconds a test would
spend waiting for nothing (D564).
"""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import time
from pathlib import Path

import pytest
from omniweave.run import discover
from omniweave.run import ingest as ingest_module
from omniweave.run.ingest import IDENTIFIED, STOPPED_AT, TRIGGER, IngestReport, ingest
from omniweave.surface import ingest as cli
from omniweave_core import acquire
from omniweave_core.config import Config, load
from omniweave_core.errors import StoreError
from omniweave_core.locks import store_write_lock

HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
SWEEP_MS = 20


def _project(tmp_path: Path, *names: str) -> tuple[Path, Config]:
    (tmp_path / "omniweave.toml").write_text(HANDBOOK, encoding="utf-8")
    for name in names:
        path = tmp_path / "docs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"body of {name}", encoding="utf-8")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    return tmp_path / ".omniweave" / "index.owstore", config


def _run(
    tmp_path: Path,
    store: Path,
    config: Config,
    *,
    paths: tuple[Path, ...] = (),
    scope: str | None = None,
) -> IngestReport:
    return ingest(
        store,
        config=config,
        source_root=tmp_path,
        output_root=tmp_path / ".omniweave" / "out",
        cache_root=tmp_path / ".omniweave" / "cache",
        argv=["ingest", *map(str, paths)],
        paths=paths,
        scope=scope,
        sweep_ms=SWEEP_MS,
    )


def _rows(store: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(store)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------
# the four hops, in order
# ---------------------------------------------------------------------------------------------


def test_a_directory_is_walked_read_and_identified_and_the_run_says_where_it_stopped(
    tmp_path: Path,
) -> None:
    """02:472-474's hops 2-4, and the first `Supervisor` run over a real operator."""
    store, config = _project(tmp_path, "a.txt", "sub/b.csv")
    report = _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    assert (report.scopes, report.files, report.discovered) == (1, 0, 2)
    assert (report.acquired.acquired, report.acquired.failed) == (2, 0)
    assert report.acquired.bytes_read == len("body of a.txt") + len("body of sub/b.csv")
    assert report.drained is not None
    assert (report.drained.status, report.drained.completed) == ("done", 2)
    assert report.states == {IDENTIFIED: 2}
    assert report.parts == 2, "05:3186: a document-granularity unit is one part"
    assert report.status == "partial"
    assert report.lines()[-2].endswith(STOPPED_AT)
    assert _rows(store, "SELECT operator, status, unit_part FROM work") == [
        ("op.identify", "done", ""),
        ("op.identify", "done", ""),
    ]
    units = _rows(store, "SELECT state, part_count, content_sha256 IS NOT NULL FROM unit")
    assert units == [(IDENTIFIED, 1, 1), (IDENTIFIED, 1, 1)]


def test_the_run_row_carries_its_generation_and_the_three_empty_columns(tmp_path: Path) -> None:
    """Hop 1, and D562: three `NOT NULL` columns with no producer in this run are empty."""
    store, config = _project(tmp_path, "a.txt")
    report = _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    ((run_id, generation, trigger, argv, status, digest, semantic, policy, empties, ended),) = (
        _rows(
            store,
            "SELECT run_id, generation, trigger, argv, status, config_digest, semantic_digest, "
            "length(policy_digest), pricebook_digest || lock_digest || manifest_path, "
            "ended_ns >= started_ns FROM run",
        )
    )
    assert (run_id, generation, trigger, status) == (report.run_id, 1, TRIGGER, "partial")
    assert json.loads(str(argv)) == ["ingest", str(tmp_path / "docs")]
    assert (digest, semantic) == (config.config_digest, config.semantic_digest)
    assert (policy, empties, ended) == (64, "", 1)


def test_a_second_run_mints_the_next_generation_and_reads_nothing_it_read(tmp_path: Path) -> None:
    """08:1622's `old.generation + 1`, and 08:1623: `index_state.generation` is not bumped by a run
    whose rows no query can see."""
    store, config = _project(tmp_path, "a.txt", "b.txt")
    _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    again = _run(tmp_path, store, config)
    assert again.generation == 2
    assert (again.scopes, again.discovered, again.acquired.acquired) == (1, 2, 0)
    assert again.enqueued == 0
    assert again.drained is None
    assert again.states == {IDENTIFIED: 2}
    assert _rows(store, "SELECT generation FROM run ORDER BY generation") == [(1,), (2,)]
    assert _rows(store, "SELECT v FROM index_state WHERE k = 'generation'") == [("0",)]


def test_with_no_store_and_nothing_to_walk_the_ingest_is_refused_and_creates_nothing(
    tmp_path: Path,
) -> None:
    store, config = _project(tmp_path)
    with pytest.raises(StoreError, match="nothing rostered"):
        _run(tmp_path, store, config)
    assert not store.exists()


def test_a_failed_run_closes_its_row_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, config = _project(tmp_path, "a.txt")

    def boom(*_args: object, **_kw: object) -> object:
        raise RuntimeError("the acquisition pass failed")

    monkeypatch.setattr(discover, "acquire_pending", boom)
    with pytest.raises(RuntimeError):
        _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    assert _rows(store, "SELECT status, ended_ns IS NOT NULL FROM run") == [("failed", 1)]


# ---------------------------------------------------------------------------------------------
# what ow_add leaves, drained by a bare `ow ingest`
# ---------------------------------------------------------------------------------------------


def test_what_ow_add_rostered_is_drained_by_an_ingest_with_no_argument(tmp_path: Path) -> None:
    """D559. `add_sources()` rostered units without the walked path, so `expand.salt_for()` refused
    every one and not one `ow_add` unit could ever be identified. `posttool.command()`'s spawn is
    `ow ingest` and nothing else, so this is the drain it would start."""
    store, config = _project(tmp_path, "a.txt", "b.txt")
    added = acquire.add_sources(store, [tmp_path / "docs"], now_ns=time.time_ns())
    assert len(added.queued) == 2
    derived = [json.loads(str(row[0])) for row in _rows(store, "SELECT derived FROM unit")]
    assert all(acquire.WALKED_PATH_KEY in one for one in derived)
    report = _run(tmp_path, store, config)
    assert report.unsalted == 0
    assert report.states == {IDENTIFIED: 2}


def test_a_file_added_alone_is_walked_again_and_its_parent_scope_row_is_untouched(
    tmp_path: Path,
) -> None:
    """D556 on the drain's side: a file source has no scope row, so a bare ingest finds it by its
    `scope_rule = 'explicit'` and walks it as `add_sources()` did."""
    store, config = _project(tmp_path, "a.txt", "b.txt")
    acquire.add_sources(store, [tmp_path / "docs" / "a.txt"], now_ns=time.time_ns())
    report = _run(tmp_path, store, config)
    assert (report.scopes, report.files, report.discovered) == (0, 1, 1)
    assert report.states == {IDENTIFIED: 1}
    assert _rows(store, "SELECT count(*) FROM ingest_scope") == [(0,)]
    assert _rows(store, "SELECT scope_rule FROM unit") == [("explicit",)]


def test_a_scope_names_one_stored_walk_and_an_unknown_one_is_refused(tmp_path: Path) -> None:
    store, config = _project(tmp_path, "one/a.txt", "two/b.txt")
    acquire.add_sources(
        store, [tmp_path / "docs" / "one", tmp_path / "docs" / "two"], now_ns=time.time_ns()
    )
    report = _run(tmp_path, store, config, scope=str(tmp_path / "docs" / "one"))
    assert (report.scopes, report.discovered) == (1, 1)
    assert report.states == {IDENTIFIED: 1}
    with pytest.raises(StoreError, match="no ingest_scope row"):
        _run(tmp_path, store, config, scope=str(tmp_path / "docs"))


def test_a_unit_with_no_walked_path_is_counted_and_not_raised(tmp_path: Path) -> None:
    """The one kind of unit `_enqueue()` cannot key -- a W7.3v roster row -- ends no corpus."""
    store, config = _project(tmp_path, "a.txt", "b.txt")
    acquire.add_sources(store, [tmp_path / "docs"], now_ns=time.time_ns())
    conn = sqlite3.connect(store)
    conn.execute("UPDATE unit SET derived = '{}' WHERE unit_uri LIKE '%a.txt'")
    conn.commit()
    conn.close()
    report = _run(tmp_path, store, config)
    assert report.unsalted == 1
    assert report.states == {IDENTIFIED: 1, discover.ACQUIRED: 1}
    assert any("D559" in line for line in report.lines())


def test_a_file_deleted_after_a_complete_scan_is_marked_unseen(tmp_path: Path) -> None:
    """05:368-373's sweep, run only after a scan that completed in one call."""
    store, config = _project(tmp_path, "a.txt", "b.txt")
    _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    (tmp_path / "docs" / "b.txt").unlink()
    again = _run(tmp_path, store, config)
    assert again.unseen == 1
    rows = _rows(store, "SELECT state, acq_failure_class FROM unit WHERE unit_uri LIKE '%b.txt'")
    assert rows == [("out_of_scope", "unseen")]


def test_the_lock_is_the_one_beside_the_store_and_is_released(tmp_path: Path) -> None:
    """D560. Every unit takes `store.write` beside its store, and nothing is left behind."""
    store, config = _project(tmp_path, "a.txt")
    _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    lock = store_write_lock(store, now_ns=time.time_ns)
    assert lock.path == store.parent / "store.write-index.owstore.lock"
    assert not lock.path.exists()


def test_the_report_is_ascii_and_says_what_stopped_it(tmp_path: Path) -> None:
    store, config = _project(tmp_path, "a.txt")
    lines = _run(tmp_path, store, config, paths=(tmp_path / "docs",)).lines()
    assert all(line.isascii() for line in lines)
    assert lines[-1] == "partial  0 failed"
    assert "02:452-461" in lines[-2]


def test_an_empty_run_is_ok_and_not_partial(tmp_path: Path) -> None:
    """Nothing identified and nothing left is a run that did all there was: `ok`."""
    store, config = _project(tmp_path)
    (tmp_path / "docs").mkdir()
    report = _run(tmp_path, store, config, paths=(tmp_path / "docs",))
    assert (report.status, report.states, report.drained) == ("ok", {}, None)


# ---------------------------------------------------------------------------------------------
# `ow ingest` on the command line
# ---------------------------------------------------------------------------------------------


def _cli(tmp_path: Path, argv: list[str], *, body: str = HANDBOOK) -> tuple[int, str, str]:
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        argv,
        env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")},
        cwd=tmp_path,
        stdout=out,
        stderr=err,
        sweep_ms=SWEEP_MS,
    )
    return code, out.getvalue(), err.getvalue()


def test_the_command_ingests_a_path_and_exits_0_on_a_partial_run(tmp_path: Path) -> None:
    """08:911: *"a partial run is a result and not an error"*."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("x", encoding="utf-8")
    code, out, err = _cli(tmp_path, ["docs", "--corpus", "handbook"])
    assert (code, err) == (0, "")
    assert out.splitlines()[-1] == "partial  0 failed"


def test_the_default_corpus_is_used_when_none_is_named(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("x", encoding="utf-8")
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    code, _out, err = _cli(tmp_path, ["docs"], body=body)
    assert (code, err) == (0, "")


@pytest.mark.parametrize(
    ("argv", "body", "exit_code", "needle"),
    [
        (["docs", "--scope", "x"], HANDBOOK, 1, "paths or --scope"),
        (["--corpus", "legal"], HANDBOOK, 1, "OW_CORPUS_NOT_FOUND"),
        ([], "", 1, "none resolves"),
        (["missing"], HANDBOOK, 1, "does not exist"),
        (["--corpus", "handbook"], HANDBOOK, StoreError.EXIT, "nothing rostered"),
        (["--no-such-flag"], HANDBOOK, 1, ""),
    ],
)
def test_each_refusal_is_one_line_on_stderr_with_its_exit(
    tmp_path: Path, argv: list[str], body: str, exit_code: int, needle: str
) -> None:
    (tmp_path / "docs").mkdir()
    code, out, err = _cli(tmp_path, argv, body=body)
    assert code == exit_code
    assert out == ""
    assert needle in err
    assert err.isascii()


def test_a_path_outside_the_source_root_is_refused_before_anything_is_walked(
    tmp_path: Path,
) -> None:
    """05:78: *"a refusal, not a warning"*. `OW-A-007`, exit 6, and no store is created."""
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "elsewhere").mkdir()
    code, out, err = _cli(project, ["../elsewhere", "--corpus", "handbook"])
    assert (code, out) == (6, "")
    assert "OW_PATH_OUTSIDE_ROOTS" in err
    assert not (project / ".omniweave").exists()


def test_the_module_is_what_python_m_omniweave_ingest_runs() -> None:
    import omniweave.__main__ as launcher  # noqa: PLC0415

    assert "ingest" in launcher.DISPATCHED
    assert ingest_module.TRIGGER == "cli"


def test_the_queue_forgets_an_identification_only_when_its_commit_stuck() -> None:
    """`IdentifyLedger`: *"`forget()` is the caller's acknowledgement that the commit stuck"* -- and
    a superseded commit rolled back, so its entry is what a retry would need."""

    class Inner:
        def __init__(self) -> None:
            self.answers = [True, False]

        def complete(self, _row_id: int, _gen: int, _result: object) -> bool:
            return self.answers.pop(0)

    ledger = ingest_module.expand.IdentifyLedger()
    ledger.record(1, "a", None)
    ledger.record(2, "b", None)
    queue = ingest_module._Forgetting(Inner(), ledger)  # type: ignore[arg-type]
    assert queue.complete(1, 1, object()) is True  # type: ignore[arg-type]
    assert queue.complete(2, 1, object()) is False  # type: ignore[arg-type]
    assert len(ledger) == 1
