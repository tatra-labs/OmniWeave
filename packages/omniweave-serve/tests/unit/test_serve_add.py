"""`ow_add` over `tools/call`: the roots it may read, the refusals before it reads, and the report.

The walks are over real directories under `tmp_path`, and the store is created by the first add,
as 10:541-542's first `ow add` creates it. The roster step itself is core's `test_acquire_add.py`;
this file is what reaches the wire.

**One outcome here is `isError: true`**, and it is the one 10:486 names: a path outside every
`[roots]` source. Every other outcome is `isError: false` (10:920).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from omniweave_serve import adding
from omniweave_serve.query import QueryCaller

REPO = Path(__file__).resolve().parents[4]


def _now() -> int:
    """Ten seconds past the wall clock, taken per call: a module-level value goes stale under
    `-n auto`, where a test can run long after collection and its files' `mtime` then falls inside
    the settling window of a "now" that is already in the past."""
    return time.time_ns() + 10_000_000_000


def _tree(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"body of {name}", encoding="utf-8")
    return root


def _caller(tmp_path: Path, **kw: Any) -> QueryCaller:
    fields: dict[str, Any] = {
        "corpora": {"handbook": tmp_path / ".omniweave" / "index.owstore"},
        "default": "handbook",
        "sources": {"handbook": tmp_path / "corpus"},
    }
    fields.update(kw)
    return QueryCaller(wall_ns=_now, **fields)


def _call(caller: QueryCaller, **arguments: Any) -> dict[str, Any]:
    return caller.respond_add(arguments)


def _text(result: dict[str, Any]) -> str:
    (content,) = result["content"]
    return str(content["text"])


def _report(caller: QueryCaller, **arguments: Any) -> dict[str, Any]:
    result = _call(caller, **arguments)
    assert result["isError"] is False
    document: dict[str, Any] = json.loads(_text(result))
    return document


# ---------------------------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------------------------


def test_a_directory_is_rostered_and_reported_in_add_out_v1s_shape(tmp_path: Path) -> None:
    _tree(tmp_path / "corpus" / "docs", "a.pdf", "b.pdf")
    report = _report(_caller(tmp_path), source="docs")
    schema = json.loads((REPO / "schema" / "add-out-v1.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(report)
    assert (report["discovered"], report["queued"], report["unchanged"]) == (2, 2, 0)
    assert report["corpus"] == "handbook"
    assert str(report["scope_id"]).endswith("/docs/"), "D555: the store's text prefix"
    assert report["completed"] == []
    assert report["deadline_reached"] is False
    assert report["schema"] == 1
    assert (tmp_path / ".omniweave" / "index.owstore").is_file()


def test_every_queued_unit_is_pending_and_says_nothing_drains_it(tmp_path: Path) -> None:
    """D554: no `ow ingest` child is spawned, so the report says so rather than polling."""
    _tree(tmp_path / "corpus" / "docs", "a.pdf")
    (row,) = _report(_caller(tmp_path), source="docs")["pending"]
    assert row["uri"].endswith("/docs/a.pdf")
    assert "nothing drains it" in row["reason"]
    assert row["approve"] == "ow ingest"


def test_a_dry_run_queues_nothing_and_still_lists_what_would_queue(tmp_path: Path) -> None:
    """10:488: *"the same `add-out-v1` shape with `queued = 0` and a populated `pending`"*."""
    _tree(tmp_path / "corpus" / "docs", "a.pdf")
    report = _report(_caller(tmp_path), source="docs", dry_run=True)
    assert report["queued"] == 0
    (row,) = report["pending"]
    assert row["reason"] == "would be rostered; dry_run wrote nothing", "not 'rostered'"
    assert not (tmp_path / ".omniweave" / "index.owstore").exists()


def test_pending_is_capped_and_counts_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D557. The cap is patched down so the test writes three files and not thirty-three."""
    monkeypatch.setattr(adding, "PENDING_MAX", 2)
    _tree(tmp_path / "corpus" / "docs", "a.pdf", "b.pdf", "c.pdf")
    report = _report(_caller(tmp_path), source="docs")
    assert len(report["pending"]) == 2
    assert report["pending_more"] == 1
    assert report["queued"] == 3


def test_a_list_of_sources_is_one_report(tmp_path: Path) -> None:
    corpus = _tree(tmp_path / "corpus", "one/a.pdf", "two/b.pdf", "c.pdf")
    report = _report(_caller(tmp_path), source=["one", "two", str(corpus / "c.pdf")])
    assert report["discovered"] == 3
    assert report["scope_id"] is None, "two directory scopes, so no one scope_id (D555)"


# ---------------------------------------------------------------------------------------------
# the roots
# ---------------------------------------------------------------------------------------------


def test_a_path_outside_every_root_is_ow_a_007_and_the_one_is_error(tmp_path: Path) -> None:
    """10:486: *"`isError: true` and **no retry guidance**"*."""
    elsewhere = _tree(tmp_path / "elsewhere", "secret.pdf")
    result = _call(_caller(tmp_path), source=str(elsewhere / "secret.pdf"))
    assert result["isError"] is True
    text = _text(result)
    assert text.startswith("ow: OW-A-007: ")
    assert "Fix" not in text
    assert not (tmp_path / ".omniweave" / "index.owstore").exists()


def test_a_relative_path_that_climbs_out_of_the_root_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path / "corpus", "a.pdf")
    _tree(tmp_path / "outside", "b.pdf")
    result = _call(_caller(tmp_path), source="../outside/b.pdf")
    assert result["isError"] is True


def test_any_declared_corpus_source_is_a_root(tmp_path: Path) -> None:
    """10:486's *"every configured root"*: a path under another corpus's source is inside one."""
    _tree(tmp_path / "corpus", "a.pdf")
    legal = _tree(tmp_path / "legal", "b.pdf")
    caller = _caller(
        tmp_path, sources={"handbook": tmp_path / "corpus", "legal": tmp_path / "legal"}
    )
    assert _report(caller, source=str(legal / "b.pdf"))["discovered"] == 1


def test_a_missing_path_inside_the_root_is_a_plain_refusal(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    result = _call(_caller(tmp_path), source="nope.pdf")
    assert result["isError"] is False
    assert "does not exist" in _text(result)


def test_a_corpus_with_no_source_root_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path / "corpus", "a.pdf")
    text = _text(_call(_caller(tmp_path, sources={}), source="a.pdf"))
    assert "no source root" in text


# ---------------------------------------------------------------------------------------------
# refused before anything is read
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"source": "a.pdf", "allow_cost": 5}, "takes no argument allow_cost"),
        ({}, "needs source"),
        ({"source": []}, "needs source"),
        ({"source": ["a.pdf"] * 257}, "OW-A-008"),
        ({"source": ["a.pdf", ""]}, "non-empty string"),
        ({"source": "x" * 4097}, "at most 4096 bytes"),
        ({"source": "https://example.org/a.pdf"}, "no acquire connector for URLs"),
        ({"source": "a.pdf", "dry_run": "yes"}, "dry_run is a boolean"),
        ({"source": "a.pdf", "corpus": 3}, "corpus must be a string"),
    ],
)
def test_an_argument_problem_is_a_one_line_refusal(
    tmp_path: Path, arguments: dict[str, Any], needle: str
) -> None:
    result = _caller(tmp_path).respond_add(arguments)
    assert result["isError"] is False
    text = _text(result)
    assert text.startswith("ow: ")
    assert needle in text
    assert text.count("\n") == 0
    assert not (tmp_path / ".omniweave").exists(), "nothing is read or written"


def test_the_arguments_are_the_published_schemas_properties() -> None:
    catalogue = json.loads((REPO / "schema" / "mcp-tools-v1.json").read_text(encoding="utf-8"))
    (tool,) = [one for one in catalogue if one["name"] == adding.ADD_TOOL]
    schema = tool["inputSchema"]
    assert set(schema["properties"]) == adding._ARGUMENTS
    assert schema["properties"]["source"]["oneOf"][1]["maxItems"] == adding.MAX_SOURCES
