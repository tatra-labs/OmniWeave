"""`ow add`: the roster step, the in-process drain, the report, and every exit it can give.

Every project is a real `omniweave.toml` under `tmp_path`, every store is created by `ow add`
itself through the shipped migrations, and every drain is the real `run.ingest.ingest()` over real
files. The files are `.txt`, which the drain reads, identifies and routes to no driver
(`parse.text.builtin` is not installed), so nothing here starts the S4 worker. The parse, the
`completed` row and the `ow query` after it are `conform/test_add_process.py`'s. `sweep_ms` is
small for `test_run_ingest.py`'s reason (D564).
"""

from __future__ import annotations

import io
import json
import os
import sqlite3  # noqa: TID251 -- the assertions read the store the verb wrote.
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from jsonschema import Draft202012Validator
from omniweave.surface import add as verb
from omniweave_core.locks import store_write_lock

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
SWEEP_MS = 20
PAST_NS = 1_700_000_000_000_000_000
"""An mtime far enough behind the add that `stat_fresh()`'s granularity clause holds (05:344)."""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project declaring `handbook`, with two `.txt` files under `docs/` and no store yet."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, body in (("a.txt", "Fees are payable monthly."), ("b.txt", "Notice is 30 days.")):
        (docs / name).write_text(body, encoding="utf-8")
        os.utime(docs / name, ns=(PAST_NS, PAST_NS))
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(
        ["add", *argv],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
        stdout=out,
        stderr=err,
        sweep_ms=SWEEP_MS,
    )
    return code, out.getvalue(), err.getvalue()


def _store(project: Path) -> Path:
    return project / ".omniweave" / "index.owstore"


def _states(project: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(_store(project))
    try:
        return conn.execute("SELECT state, count(*) FROM unit GROUP BY state").fetchall()
    finally:
        conn.close()


def _schema() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    return json.loads((root / "schema" / "add-out-v1.json").read_text(encoding="utf-8"))


def _validate(document: dict[str, Any]) -> None:
    """`add-out-v1.json`, with D555's one deviation put back: `scope_id` is the store's prefix."""
    assert document["scope_id"] is None or isinstance(document["scope_id"], str)
    Draft202012Validator(_schema()).validate({**document, "scope_id": 0})


# ---------------------------------------------------------------------------------------------
# (a), (b) and (c): roster, drain, report
# ---------------------------------------------------------------------------------------------


def test_a_directory_is_rostered_drained_and_reported(project: Path) -> None:
    code, out, err = _run(["docs"], project)
    assert code == 0
    first, second, *rest = out.splitlines()
    assert first.startswith("scope ") and first.endswith(
        "/docs/  ·  discovered 2  ·  unchanged 0  ·  queued 2  ·  skipped 0"
    )
    assert second == "completed 0   pending 2 (2 no_driver)   deadline_reached false"
    assert [line.split()[-1] for line in rest[:2]] == ["no_driver", "no_driver"]
    assert rest[-1] == "  ow ingest --corpus handbook"
    #  (b) ran: the drain read and identified both, and its report is stderr's (10:1565).
    assert _states(project) == [("identified", 2)]
    assert err.startswith("ow ingest  run ")
    assert "  detect    txt 2" in err.splitlines()


def test_render_json_is_add_out_v1_with_schema_first(project: Path) -> None:
    """10:1530's `schema` first; `add-out-v1.json` but for D555's `scope_id`."""
    code, out, _ = _run(["docs", "--render", "json"], project)
    assert code == 0
    document = json.loads(out)
    _validate(document)
    assert next(iter(document)) == "schema"
    assert (document["discovered"], document["queued"], document["unchanged"]) == (2, 2, 0)
    assert document["scope_id"].endswith("/docs/")
    assert document["completed"] == []
    assert {row["reason"] for row in document["pending"]} == {"no_driver"}
    assert {row["approve"] for row in document["pending"]} == {"ow ingest --corpus handbook"}
    assert document["deadline_reached"] is False


def test_quiet_prints_the_count_queued_and_nothing_else(project: Path) -> None:
    """10:1543: *"`ow add --quiet` prints the count queued"*."""
    assert _run(["docs", "--quiet"], project) == (0, "2\n", "")


def test_a_file_source_has_no_scope_and_is_drained_on_its_own(project: Path) -> None:
    """D556: one file rosters no `ingest_scope` row, so the report names no scope."""
    code, out, _ = _run(["docs/a.txt", "--render", "json"], project)
    assert code == 0
    document = json.loads(out)
    _validate(document)
    assert (document["scope_id"], document["discovered"], document["queued"]) == (None, 1, 1)
    assert _states(project) == [("identified", 1)]


def test_a_second_add_of_unchanged_files_queues_nothing_and_drains_nothing(project: Path) -> None:
    assert _run(["docs", "--quiet"], project)[0] == 0
    code, out, err = _run(["docs"], project)
    assert (code, err) == (0, ""), "nothing queued, so no drain ran and printed nothing"
    assert "unchanged 2  ·  queued 0" in out.splitlines()[0]
    assert out.splitlines()[1] == "completed 0   pending 0   deadline_reached false"


def test_a_dry_run_writes_nothing_and_names_the_command_it_priced(project: Path) -> None:
    """18:1152-1158: a dry run exits 0, queues nothing and prints the approving command."""
    code, out, err = _run(["docs", "--dry-run", "--corpus", "handbook"], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert "queued 0" in lines[0]
    assert lines[1] == "NOT RUN (dry run). 2 units would be queued."
    assert lines[-1] == "  ow add docs --corpus handbook"
    assert not _store(project).exists(), "a dry run writes nothing, the store included"


def test_a_dry_run_under_render_json_lists_what_would_queue(project: Path) -> None:
    document = json.loads(_run(["docs", "--dry-run", "--render", "json"], project)[1])
    _validate(document)
    assert document["queued"] == 0
    assert [row["reason"] for row in document["pending"]] == ["dry_run", "dry_run"]


def test_a_settled_unit_is_a_completed_row_in_add_out_v1s_shape(
    tmp_path: Path, seeded_store: Any
) -> None:
    """`AddCompleted` read from the store: the head document, its pages, blocks and span."""
    store = seeded_store(tmp_path / "index.owstore")
    (row,) = verb._completed(store, ["file:///corpus/contract.pdf", "file:///nothing"])
    assert row == {
        "uri": "file:///corpus/contract.pdf",
        "doc_ord": 1,
        "gen": 1,
        "pages": 0,
        "blocks": 3,
        "achieved_origin_span": "none",
    }
    Draft202012Validator(_schema()["$defs"]["AddCompleted"]).validate(row)


def test_the_text_render_lists_at_most_its_cap_and_counts_the_rest() -> None:
    pending = [
        {"uri": f"u{i}", "reason": "no_driver", "approve": "ow ingest --corpus c"}
        for i in range(verb.TEXT_PENDING_MAX + 3)
    ]
    report = {
        "scope_id": None,
        "discovered": 35,
        "unchanged": 0,
        "queued": 35,
        "skipped": 0,
        "completed": [],
        "pending": pending,
    }
    lines = verb._text(report, dry_run=False)
    assert lines[1] == "completed 0   pending 35 (35 no_driver)   deadline_reached false"
    assert lines[-2:] == ["  ... and 3 more", "  ow ingest --corpus c"]
    assert len(lines) == 2 + verb.TEXT_PENDING_MAX + 2


# ---------------------------------------------------------------------------------------------
# refusals, and their exits
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--allow-cost", "40000"], "--allow-cost"),
        (["--schema", "po.schema.json"], "--schema"),
        (["--allow-egress", "g1"], "--allow-egress"),
        (["--wait", "20"], "--wait"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(["docs", *flags], project)
    assert (code, out) == (1, "")
    assert named in err
    assert not _store(project).exists(), "refused before anything is read"


def test_a_url_source_is_refused_by_name(project: Path) -> None:
    code, _, err = _run(["https://example.com/a.pdf"], project)
    assert code == 1
    assert "is a URL" in err


def test_quiet_and_render_are_exclusive(project: Path) -> None:
    assert _run(["docs", "--quiet", "--render", "json"], project)[0] == 1


def test_a_source_outside_the_corpus_root_is_exit_6_and_writes_nothing(tmp_path: Path) -> None:
    """10:1425's 6: `OW-A-007`, the refusal `ow ingest` makes, before anything is walked."""
    inner = tmp_path / "project"
    inner.mkdir()
    (inner / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    code, out, err = _run(["../elsewhere"], inner)
    assert (code, out) == (6, "")
    assert "OW-A-007" in err
    assert "ow add will not walk it" in err
    assert not (inner / ".omniweave").exists()


def test_a_missing_source_is_usage(project: Path) -> None:
    code, _, err = _run(["nope"], project)
    assert code == 1
    assert "does not exist" in err


def test_an_undeclared_corpus_is_exit_2_naming_the_declaration(project: Path) -> None:
    """D615: 10:1469's *"`ow add` creates a corpus"* is not built; the fix is the declaration."""
    code, _, err = _run(["docs", "--corpus", "legal"], project)
    assert code == 2
    assert "OW-A-002" in err
    assert "[corpora.legal]" in err


def test_no_resolvable_corpus_is_exit_2(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    code, _, err = _run(["docs"], tmp_path)
    assert code == 2
    assert "none resolves" in err


def test_an_error_under_render_json_is_the_error_object_on_stdout(project: Path) -> None:
    code, out, err = _run(["docs", "--corpus", "legal", "--render", "json"], project)
    assert (code, err) == (2, "")
    document = json.loads(out)
    assert list(document) == ["schema", "error"]
    assert document["error"]["symbol"] == "OW_CORPUS_NOT_FOUND"


def test_a_held_store_write_lock_is_exit_7(project: Path) -> None:
    """10:1425's 7: `store.write` held past `INTERACTIVE_WAIT_MS` is `StoreBusy` (02:757-758)."""
    assert _run(["docs/a.txt", "--quiet"], project)[0] == 0
    held = store_write_lock(_store(project), now_ns=time.time_ns)
    held.acquire(wait_ms=0)
    try:
        code, out, err = _run(["docs/b.txt"], project)
    finally:
        held.release()
    assert (code, out) == (7, "")
    assert "fix:" in err


def test_a_parse_error_is_1_and_help_is_0(project: Path) -> None:
    assert _run([], project)[0] == 1, "SOURCE is nargs='+'"
    assert _run(["--help"], project)[0] == 0


def test_python_m_omniweave_dispatches_add(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "add" in launcher.DISPATCHED
    monkeypatch.chdir(project)
    monkeypatch.setattr("os.environ", {"OMNIWEAVE_HOME": str(project / "owhome")})
    assert launcher.main(["add", "docs", "--dry-run", "--quiet"]) == 0
    assert capsys.readouterr().out == "0\n"
