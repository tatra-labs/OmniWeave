"""`ow corpora`: the four modes over real stores, the documents `ow_corpora` returns, and the exits.

Each store is `conftest.py`'s `seeded_store`, and the card is written by `store.card.build_card()`
and `write_card()`, the real builder, because nothing in the ingest path writes one yet (D550). The
store-reading documents are core's (W7.8j), so every assertion that the CLI prints what the server
returns is an assertion against `omniweave_serve`'s own handler, called in-process.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from jsonschema import Draft202012Validator
from omniweave.surface import corpora as verb
from omniweave_core.store import card as store_card
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:
    from collections.abc import Sequence

NOW_NS = 1_757_400_000_000_000_000
ACHIEVED = {
    "spatial": "line_bbox",
    "origin_span": "normalized",
    "text_span": True,
    "marks": False,
    "reading_order": "char_stream",
    "sections": "typed_levels",
    "tables": "cells",
    "math": [],
    "assets": "refs",
    "asset_origin": False,
    "notes": "linked",
    "confidence": "page",
    "furniture": "flagged",
    "round_trip": "none",
    "forfeits": [],
}
PROJECT = (
    '[corpora.handbook]\npath = ".omniweave/handbook.owstore"\n'
    '[corpora.legal]\npath = ".omniweave/legal.owstore"\n'
    '[corpora.broken]\npath = ".omniweave/broken.owstore"\n'
    '[serve]\ndefault_corpus = "legal"\n'
)


def _card(path: Path, *, gen: int) -> None:
    conn = ow.connect(path)
    try:
        conn.execute("UPDATE doc SET achieved = ?", (json.dumps(ACHIEVED),))
        row = store_card.build_card(
            conn,
            name=path.stem,
            root="/corpus",
            card_gen=gen,
            built_at_ns=NOW_NS,
            writer_version="0.1.0",
        )
        store_card.write_card(conn, row)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any) -> Path:
    """Three corpora: `handbook` with a card at gen 2, `legal` (the default) with a card at gen 1,
    and `broken`, whose declared store is not a database."""
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    stores = tmp_path / ".omniweave"
    _card(seeded_store(stores / "handbook.owstore"), gen=2)
    _card(seeded_store(stores / "legal.owstore"), gen=1)
    (stores / "broken.owstore").write_bytes(b"not a database")
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["corpora", *argv], env={}, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str], cwd: Path) -> dict[str, Any]:
    code, out, err = _run([*argv, "--render", "json"], cwd)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    return document


def _server(project: Path, **arguments: Any) -> dict[str, Any]:
    """`ow_corpora`'s own answer over the same stores: the handler, in-process."""
    from omniweave_serve.query import QueryCaller  # noqa: PLC0415 -- a test may cross the layer

    stores = project / ".omniweave"
    caller = QueryCaller(
        corpora={name: stores / f"{name}.owstore" for name in ("handbook", "legal", "broken")},
        default="legal",
        wall_ns=lambda: NOW_NS,
    )
    (content,) = caller.respond_corpora(arguments)["content"]
    document: dict[str, Any] = json.loads(content["text"])
    return document


def _entry_schema() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    schema = json.loads((root / "schema" / "corpora-out-v1.json").read_text(encoding="utf-8"))
    return {**schema["$defs"]["CorpusCard"], "$defs": schema["$defs"]}


# ---------------------------------------------------------------------------------------------
# The documents, and that they are the server's
# ---------------------------------------------------------------------------------------------


def test_list_is_the_document_ow_corpora_returns_with_schema_first(project: Path) -> None:
    document = _json([], project)
    assert next(iter(document)) == "schema"
    assert document == {"schema": 1, **_server(project)}
    names = [row["name"] for row in document["corpora"]]
    assert names == ["legal", "handbook", "broken"], "10:1023: default, then card_gen desc"
    broken = document["corpora"][2]
    assert (broken["readable"], bool(broken["reason"])) == (False, True), "10:1031: never omitted"


def test_card_is_one_whole_entry_the_schema_validates(project: Path) -> None:
    document = _json(["handbook", "--detail", "card"], project)
    assert document == {"schema": 1, **_server(project, corpus="handbook", detail="card")}
    (entry,) = document["corpora"]
    Draft202012Validator(_entry_schema()).validate(entry)
    assert (entry["name"], entry["card_gen"], entry["default"]) == ("handbook", 2, False)


def test_coverage_reads_the_default_when_no_corpus_is_named(project: Path) -> None:
    document = _json(["--detail", "coverage"], project)
    (row,) = document["corpora"]
    assert (row["name"], row["default"]) == ("legal", True)
    assert row["coverage"]["indexed"] == row["coverage"]["discovered"]
    server = _server(project, detail="coverage")
    assert document == {"schema": 1, **server}


def test_a_prefix_narrows_the_list_and_a_prefix_matching_nothing_is_empty(project: Path) -> None:
    assert [row["name"] for row in _json(["hand*"], project)["corpora"]] == ["handbook"]
    assert _json(["zzz*"], project)["corpora"] == []


def test_actions_is_the_catalog_of_every_action_with_an_mcp_name(project: Path) -> None:
    """10:1012. The server refuses this mode (D551); the CLI owns the registry it reads."""
    from omniweave.surface.registry import ACTIONS  # noqa: PLC0415

    document = _json(["--detail", "actions"], project)
    published = [spec for spec in ACTIONS.values() if spec.mcp_name]
    assert [row["mcp_name"] for row in document["actions"]] == [s.mcp_name for s in published]
    assert all(row["summary"] and row["decision"] for row in document["actions"])


def test_the_text_render_is_a_line_per_corpus_with_its_state(project: Path) -> None:
    code, out, err = _run([], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("legal (default)")
    assert "readable" in lines[0]
    assert "card_gen=1" in lines[0]
    assert "verbatim_fraction" in lines[0]
    assert lines[2].startswith("broken") and "unreadable: " in lines[2]


def test_the_text_card_prints_one_line_per_field(project: Path) -> None:
    code, out, _ = _run(["handbook", "--detail", "card"], project)
    assert code == 0
    fields = {line.split()[0] for line in out.splitlines()[1:] if line.startswith("  ")}
    assert {"formats", "achieved", "verbatim_fraction", "gaps"} <= fields


# ---------------------------------------------------------------------------------------------
# Not found, and usage
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["nope"], ["nope", "--detail", "card"], ["nope", "--detail", "coverage"]],
)
def test_an_undeclared_corpus_is_exit_2(project: Path, argv: list[str]) -> None:
    code, out, err = _run(argv, project)
    assert (code, out) == (2, "")
    assert "OW-A-002" in err


def test_card_with_no_corpus_and_no_default_is_exit_2(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.a]\npath = "a.owstore"\n[corpora.b]\npath = "b.owstore"\n', encoding="utf-8"
    )
    code, _, err = _run(["--detail", "card"], tmp_path)
    assert code == 2
    assert "none was named or is the default" in err


def test_card_refuses_a_wildcard(project: Path) -> None:
    code, _, err = _run(["hand*", "--detail", "card"], project)
    assert code == 1
    assert "refuses a wildcard" in err


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--corpus", "handbook"], "--corpus"),
        (["--corpus=handbook"], "--corpus"),
        (["--summarize"], "--summarize"),
        (["--scope", "d7"], "--scope"),
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(flags, project)
    assert (code, out) == (1, "")
    assert named in err


def test_the_corpus_flag_would_otherwise_be_lost_to_the_positional() -> None:
    """D617: why `--corpus` is refused. The generated parser drops it, measured here."""
    from omniweave.cli import build_parser  # noqa: PLC0415

    assert build_parser().parse_args(["corpora", "--corpus", "handbook"]).corpus is None


def test_an_error_under_render_json_is_the_error_object_on_stdout(project: Path) -> None:
    code, out, err = _run(["nope", "--render", "json"], project)
    assert (code, err) == (2, "")
    assert list(json.loads(out)) == ["schema", "error"]


def test_a_parse_error_is_1_and_help_is_0(project: Path) -> None:
    assert _run(["--detail", "everything"], project)[0] == 1
    assert _run(["--help"], project)[0] == 0


def test_python_m_omniweave_dispatches_corpora(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "corpora" in launcher.DISPATCHED
    monkeypatch.chdir(project)
    monkeypatch.setattr("os.environ", {})
    assert launcher.main(["corpora"]) == 0
    assert capsys.readouterr().out.startswith("legal (default)")
