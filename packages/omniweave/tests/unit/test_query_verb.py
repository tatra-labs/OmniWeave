"""`ow query`: the verb over a real seeded store, its exits, and `--render json` against the schema.

The store is `conftest.py`'s `seeded_store`, which seeds the way `omniweave-serve`'s
`test_serve_query.py` seeds one: one document, three blocks, a finished `ingest_scope`. So the CLI
and `ow_query` answer over the same shape of store, and a difference between them is a
difference in the verb, not in the fixture.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from jsonschema import Draft202012Validator
from omniweave.surface import query as verb
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any) -> Path:
    """A project whose `handbook` corpus has a seeded store at the declared path."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    seeded_store(tmp_path / ".omniweave" / "index.owstore")
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["query", *argv], env={}, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _schema(name: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    return json.loads((root / "schema" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------------------------


def test_a_hit_is_rendered_with_its_cite_and_exits_0(project: Path) -> None:
    code, out, err = _run(["terminate"], project)
    assert (code, err) == (0, "")
    assert "d1#2" in out
    assert "terminate this agreement" in out


def test_render_json_is_the_answer_the_schema_publishes(project: Path) -> None:
    """10:1530 and `schema/answer-v1.json`, which is strict: every key is declared (D614)."""
    code, out, _ = _run(["terminate", "--render", "json"], project)
    assert code == 0
    document = json.loads(out)
    Draft202012Validator(_schema("answer-v1.json")).validate(document)
    #  One weak hit over a three-block store is `low_confidence`, and that is exit 0 (10:1482).
    assert document["state"] == "low_confidence"
    assert document["corpus"] == "handbook"
    assert [block["cite"] for block in document["evidence"]][:1] == ["d1#2"]


def test_with_two_corpora_declared_every_cite_is_qualified(project: Path) -> None:
    """`ow_query`'s `qualify=len(self.corpora) > 1`, which W7.8g's verb did not pass (D616)."""
    (project / "omniweave.toml").write_text(
        PROJECT + '[corpora.legal]\npath = ".omniweave/legal.owstore"\n', encoding="utf-8"
    )
    code, out, _ = _run(["terminate", "--corpus", "handbook", "--render", "json"], project)
    assert code == 0
    assert json.loads(out)["evidence"][0]["cite"] == "handbook:d1#2"


def test_quiet_prints_the_verdict_state_and_nothing_else(project: Path) -> None:
    assert _run(["terminate", "--quiet"], project)[:2] == (0, "low_confidence\n")


def test_a_question_with_no_hit_is_absent_and_exits_0_by_default(project: Path) -> None:
    """10:1482: absent is an answer, not a failure, unless --fail-on names it."""
    assert _run(["unicorn", "--quiet"], project)[:2] == (0, "absent\n")


def test_fail_on_absent_is_exit_3(project: Path) -> None:
    assert _run(["unicorn", "--quiet", "--fail-on", "absent,degraded"], project)[0] == 3


def test_fail_on_degraded_is_exit_4_and_absent_is_not_named(project: Path) -> None:
    """A corrupt `block_fts` is degraded (W7.8b): 4 under --fail-on degraded, 0 without."""
    store = project / ".omniweave" / "index.owstore"
    writer = ow.connect(store)
    try:
        writer.execute("UPDATE block_fts_data SET block = X'DEADBEEFDEADBEEF' WHERE id = 10")
        writer.commit()
    finally:
        writer.close()
    assert _run(["unicorn", "--quiet"], project)[:2] == (0, "degraded\n")
    assert _run(["unicorn", "--fail-on", "degraded"], project)[0] == 4
    assert _run(["unicorn", "--fail-on", "absent"], project)[0] == 0


def test_k_and_mode_reach_the_query(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from omniweave_core.retrieve import execute as execute_module  # noqa: PLC0415

    seen: list[Any] = []
    real = execute_module.execute

    def spy(reader: Any, query: Any, policy: Any, **kwargs: Any) -> Any:
        seen.append(query)
        return real(reader, query, policy, **kwargs)

    monkeypatch.setattr(execute_module, "execute", spy)
    _run(["terminate", "--k", "3", "--mode", "cite"], project)
    assert (seen[0].k, seen[0].mode, seen[0].text) == (3, "cite", "terminate")


# ---------------------------------------------------------------------------------------------
# Not found, and usage
# ---------------------------------------------------------------------------------------------


def test_an_undeclared_corpus_is_exit_2(project: Path) -> None:
    code, _, err = _run(["x", "--corpus", "nope"], project)
    assert code == 2
    assert "OW-A-002" in err


def test_a_declared_corpus_with_no_store_is_exit_2_naming_the_add(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    code, _, err = _run(["x"], tmp_path)
    assert code == 2
    assert "ow add --corpus handbook" in err


def test_a_store_that_is_not_a_database_is_one_line_not_a_traceback(tmp_path: Path) -> None:
    """D617: `connect_readonly()` raised a bare `DatabaseError`, which no verb catches."""
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    (tmp_path / ".omniweave").mkdir()
    (tmp_path / ".omniweave" / "index.owstore").write_bytes(b"not a database" * 16)
    code, out, err = _run(["x"], tmp_path)
    assert (code, out) == (70, "")
    assert "is not a readable store" in err
    assert len(err.splitlines()) == 2, "the message and its fix"


def test_an_error_under_render_json_is_the_error_object_on_stdout(project: Path) -> None:
    """10:1539-1540: `{"schema":1,"error":{...}}`, never a traceback, and nothing on stderr."""
    code, out, err = _run(["x", "--corpus", "nope", "--render", "json"], project)
    assert (code, err) == (2, "")
    document = json.loads(out)
    assert list(document) == ["schema", "error"]
    #  Charter section 5 C9: `code` is the symbol on the wire, `numeric` the human form (ADR-13).
    assert document["error"]["code"] == "OW_CORPUS_NOT_FOUND"
    assert document["error"]["numeric"] == "OW-A-002"
    assert document["error"]["fix"]


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--scope", "sec:3"], "--scope"),
        (["--want", "table"], "--want table"),
        (["--max-rung", "page"], "--max-rung"),
        (["--explain"], "--explain"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
        (["--corpus", "a,b"], "a comma list in --corpus"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(["terminate", *flags], project)
    assert (code, out) == (1, "")
    assert named in err


@pytest.mark.parametrize(
    "flags",
    [
        ["--quiet", "--render", "json"],
        ["--fail-on", "sometimes"],
        ["--max-chars", "10"],
    ],
)
def test_usage_errors_exit_1(project: Path, flags: list[str]) -> None:
    assert _run(["terminate", *flags], project)[0] == 1


def test_an_empty_or_over_long_question_is_usage(project: Path) -> None:
    assert _run(["   "], project)[0] == 1
    assert _run(["x" * 5000], project)[0] == 1


def test_a_parse_error_is_1_and_help_is_0(project: Path) -> None:
    assert _run(["--k", "notanumber", "x"], project)[0] == 1
    assert _run(["--help"], project)[0] == 0


def test_python_m_omniweave_dispatches_query(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "query" in launcher.DISPATCHED
    monkeypatch.chdir(project)
    monkeypatch.setattr("os.environ", {})
    assert launcher.main(["query", "terminate", "--quiet"]) == 0
    assert capsys.readouterr().out == "low_confidence\n"
