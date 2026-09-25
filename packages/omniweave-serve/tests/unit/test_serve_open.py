"""`ow_open` over `tools/call`: the arguments refused before any read, and the Answer after one.

Every store is migrated by the shipped migrations and seeded with SQL. The resolver's own ladder
is `omniweave_core`'s `test_store_resolve.py`; this file is the server's half -- what reaches the
wire, the corpus a ref chooses, and the ledger an opened block is recorded in.

**10:920's one rule is asserted on every outcome**: nothing here is `isError: true`.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the fixtures seed a REAL store, as core's reader tests do.
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

import pytest
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_serve import opening
from omniweave_serve.dispatch import TOOLS_CALL, McpDispatcher, Surface
from omniweave_serve.emission import StdioSession
from omniweave_serve.query import QueryCaller
from omniweave_serve.stdio import Request

REPO = Path(__file__).resolve().parents[4]
NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
T = TypeVar("T")
LONG = "Fees are payable monthly in arrears, in the currency of the invoice. " * 9
TEXTS = {2: "Clause one sets the term.", 3: LONG, 4: "Clause three sets the notice period."}


class Store(NamedTuple):
    path: Path
    writer: sqlite3.Connection


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, declared, "
        "                achieved) "
        "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', 1, 1, "
        "       'ok', '1.1', '{}', '{}')",
        (b"\x01" * 16, DIGEST),
    )
    conn.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(1, 1, 1, ?, ?, 1)",
        (_code(conn, "page_kind", "page"), _code(conn, "method", "native")),
    )
    rows = [(1, None, "section", None), *((i, 1, "paragraph", text) for i, text in TEXTS.items())]
    for block_id, parent, kind, text in rows:
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind, "
            "                  layer, text, content_digest, os_kind, producer_id, method, trust, "
            "                  quote, origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 2, 4, 'op.parse', 'drv', 1, 0, 0)",
            (
                block_id,
                f"p1/{block_id}",
                f"d1#{block_id}",
                parent,
                block_id,
                _code(conn, "kind", kind),
                _code(conn, "layer", "body"),
                text,
                DIGEST,
                _code(conn, "origin_span_kind", "none"),
                _code(conn, "method", "native"),
            ),
        )
    conn.execute(
        "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
        "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
        (NOW_NS,),
    )
    conn.execute("COMMIT")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    path = tmp_path / "index.owstore"
    writer = ow.connect(path)
    migrate.apply_pending(writer, now_ns=NOW_NS)
    _seed(writer)
    try:
        yield Store(path=path, writer=writer)
    finally:
        writer.close()


def _caller(store: Store, **kw: Any) -> QueryCaller:
    fields: dict[str, Any] = {"corpora": {"handbook": store.path}, "default": "handbook"}
    fields.update(kw)
    return QueryCaller(wall_ns=lambda: NOW_NS, **fields)


def _text(result: dict[str, Any]) -> str:
    assert result["isError"] is False, "10:920: isError is reserved for security refusals"
    (content,) = result["content"]
    return str(content["text"])


def _open(caller: QueryCaller, **arguments: Any) -> str:
    return _text(caller.respond_open(arguments)[0])


def _drive(coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    coroutine.close()
    pytest.fail("the coroutine suspended; nothing on this path may wait")


# ---------------------------------------------------------------------------------------------
# the answer
# ---------------------------------------------------------------------------------------------


def test_a_cite_is_answered_with_its_block_and_its_context(store: Store) -> None:
    text = _open(_caller(store), ref="d1#3")
    assert text.startswith("ow/1 ok corpus=handbook@0 fresh blocks=3/3")
    assert LONG.strip() in text
    assert "paragraph ctx" in text, "10:463: context blocks are marked `ctx` in ow:provenance"


def test_context_zero_is_the_block_alone(store: Store) -> None:
    text = _open(_caller(store), ref="d1#3", context=0)
    assert "blocks=1/1" in text
    assert "Clause one" not in text


def test_a_list_of_refs_answers_each_and_a_miss_does_not_sink_the_rest(store: Store) -> None:
    text = _open(_caller(store), ref=["d1#4", "contract.pdf#p1/99"], context=0)
    assert text.startswith("ow/1 degraded ")
    assert "Clause three" in text
    assert "[OW-M-032]" in text


def test_a_qualified_cite_chooses_its_corpus_when_none_is_the_default(store: Store) -> None:
    text = _open(_caller(store, default=None), ref="handbook:d1#4", context=0)
    assert "Clause three" in text


def test_with_no_corpus_at_all_the_answer_is_ow_a_001(store: Store) -> None:
    assert "[OW-A-001]" in _open(_caller(store, default=None), ref="d1#4")


def test_a_ref_qualified_with_another_corpus_is_ow_a_015(store: Store) -> None:
    """18:335: *"One `Corpus` addresses one corpus."*"""
    text = _open(_caller(store), ref="legal:d1#4", corpus="handbook")
    assert text.startswith("ow: OW-A-015: ")
    assert text.count("\n") == 0


# ---------------------------------------------------------------------------------------------
# refused before any store read
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"ref": "d1#4", "want_impact": True}, "takes no argument want_impact"),
        ({}, "needs ref"),
        ({"ref": ""}, "needs ref"),
        ({"ref": ["d1#4", 7]}, "needs ref"),
        ({"ref": ["d1#4"] * 65}, "OW-A-008"),
        ({"ref": "d1#4", "context": 9}, "context must be"),
        ({"ref": "d1#4", "context": True}, "context must be"),
        ({"ref": "d1#4", "layers": ["margin"]}, "body, furniture, note, annotation, hidden"),
        ({"ref": "d1#4", "max_chars": 999}, "max_chars must be"),
        ({"ref": "d1#4", "corpus": 3}, "corpus must be a string"),
    ],
)
def test_an_argument_problem_is_a_one_line_refusal_before_the_store_is_opened(
    tmp_path: Path, arguments: dict[str, Any], needle: str
) -> None:
    """10:946: *"Input caps are enforced before any store read"*. The corpus points at a file that
    does not exist, so reaching the store would answer `OW-A-002` instead."""
    caller = QueryCaller(corpora={"handbook": tmp_path / "absent.owstore"}, default="handbook")
    text = _text(caller.respond_open(arguments)[0])
    assert text.startswith("ow: ")
    assert needle in text
    assert "Fix: " in text
    assert text.count("\n") == 0


def test_the_arguments_are_the_published_schemas_properties() -> None:
    catalogue = json.loads((REPO / "schema" / "mcp-tools-v1.json").read_text(encoding="utf-8"))
    (tool,) = [one for one in catalogue if one["name"] == opening.OPEN_TOOL]
    schema = tool["inputSchema"]
    assert set(schema["properties"]) == opening._ARGUMENTS
    assert schema["properties"]["ref"]["oneOf"][1]["maxItems"] == 64
    assert schema["properties"]["context"]["maximum"] == 8
    assert schema["properties"]["context"]["default"] == opening._DEFAULT_CONTEXT
    assert (
        schema["properties"]["max_chars"]["minimum"],
        schema["properties"]["max_chars"]["maximum"],
    ) == opening._MAX_CHARS


# ---------------------------------------------------------------------------------------------
# through the dispatcher, and the ledger an opened block is recorded in
# ---------------------------------------------------------------------------------------------


def _call(caller: QueryCaller, ident: int, name: str, arguments: dict[str, Any]) -> tuple[str, Any]:
    surface = Surface(profile="default", compact=True, corpus_resolves=True)
    dispatcher = McpDispatcher.create(surface, caller=caller)
    request = Request(ident=ident, method=TOOLS_CALL, params={"name": name, "arguments": arguments})
    reply = _drive(dispatcher.dispatch(request))
    assert reply is not None
    return _text(reply.body["result"]), reply.after_send


def test_an_opened_block_is_never_withheld_and_is_recorded_after_the_send(store: Store) -> None:
    """D542. Opening the same block twice returns it twice -- the one thing an agent told *"already
    sent"* can do is `ow_open` -- and what it opened is committed, so `ow_query` then points."""
    session = StdioSession.open(sessions=None, pid=1, started_ns=NOW_NS)
    caller = _caller(store, session=session)
    first, commit = _call(caller, 1, "ow_open", {"ref": "d1#3", "context": 0})
    assert LONG.strip() in first
    assert commit is not None
    commit()
    second, commit = _call(caller, 2, "ow_open", {"ref": "d1#3", "context": 0})
    assert LONG.strip() in second
    assert "**ow:sent-earlier**" not in second
    commit()
    third, _ = _call(caller, 3, "ow_query", {"query": "fees payable"})
    assert "**ow:sent-earlier**" in third
    assert "call 3 of" in third
