"""`omniweave_serve.query.QueryCaller`: `ow_query` answered from a real store, over `tools/call`.

Every store is migrated by the shipped migrations and seeded with SQL, as core's reader tests seed
one, and every call goes through the real `connect_readonly`, `SqliteReader`, `retrieve()`, `pack()`
and `render()`. The dispatcher tests drive `McpDispatcher` with this Caller plugged in, which is the
first time `tools/call` has returned an answer rather than a refusal.

**10:920's one rule is asserted on every outcome**: nothing here is `isError: true`, because none
of these conditions is a security refusal.
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
from omniweave_serve import query as query_module
from omniweave_serve.dispatch import TOOLS_CALL, McpDispatcher, Surface
from omniweave_serve.query import MAX_QUERY_CHARS, QUERY_TOOL, QueryCaller
from omniweave_serve.stdio import METHOD_NOT_FOUND, Request

REPO = Path(__file__).resolve().parents[4]
NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
T = TypeVar("T")
TEXTS = {
    1: "Termination",
    2: "Either party may terminate this agreement with thirty days notice.",
    3: "Fees are payable monthly in arrears.",
}


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
    producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
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
        "VALUES(1, 1, 1, ?, ?, ?)",
        (_code(conn, "page_kind", "page"), _code(conn, "method", "native"), producer),
    )
    for block_id, text in TEXTS.items():
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
            "                  label, text, content_digest, os_kind, producer_id, method, trust, "
            "                  quote, origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, "
            "       0, 0)",
            (
                block_id,
                f"p1/{block_id}",
                f"d1#{block_id}",
                block_id,
                _code(conn, "kind", "heading" if block_id == 1 else "paragraph"),
                _code(conn, "layer", "body"),
                text,
                DIGEST,
                _code(conn, "origin_span_kind", "none"),
                producer,
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
    assert content["type"] == "text"
    return str(content["text"])


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


def test_a_query_is_answered_with_the_rendered_document(store: Store) -> None:
    text = _text(_caller(store).answer({"query": "terminate agreement notice"}))
    assert text.startswith("ow/1 ")
    assert "corpus=handbook@0 fresh" in text
    assert "**« d1#2 · contract.pdf p.1 · verbatim · extracted" in text
    assert TEXTS[2] in text
    assert '<ow:untrusted corpus="handbook" gen="0">' in text


def test_max_chars_is_the_envelope_the_status_line_prints(store: Store) -> None:
    text = _text(_caller(store).answer({"query": "fees", "max_chars": 1000}))
    assert "/1000 calls=" in text.splitlines()[0]


def test_two_corpora_qualify_every_cite(store: Store, tmp_path: Path) -> None:
    caller = _caller(store, corpora={"handbook": store.path, "legal": tmp_path / "x.owstore"})
    assert "**« handbook:d1#3 ·" in _text(caller.answer({"query": "fees payable"}))


def test_a_miss_is_absent_and_says_so(store: Store) -> None:
    assert _text(_caller(store).answer({"query": "unicorn"})).startswith("ow/1 absent ")


# ---------------------------------------------------------------------------------------------
# the corpus: 10:920's three recoverable rows, each an Answer with ow:blocking
# ---------------------------------------------------------------------------------------------


def test_no_corpus_configured_is_ow_a_001(store: Store) -> None:
    text = _text(_caller(store, corpora={}, default=None).answer({"query": "fees"}))
    assert text.startswith("ow/1 degraded ")
    assert "**ow:blocking**" in text
    assert "[OW-A-001]" in text
    assert "Fix: `ow add <path>`" in text


def test_an_undeclared_corpus_is_ow_a_002_listing_the_declared(store: Store) -> None:
    text = _text(_caller(store).answer({"query": "fees", "corpus": "legal"}))
    assert "[OW-A-002]" in text
    assert "declared: handbook" in text


def test_a_declared_store_that_is_not_on_disk_is_ow_a_002(store: Store, tmp_path: Path) -> None:
    caller = _caller(store, corpora={"handbook": tmp_path / "gone.owstore"})
    text = _text(caller.answer({"query": "fees"}))
    assert "[OW-A-002]" in text
    assert "is not readable" in text


# ---------------------------------------------------------------------------------------------
# the arguments: refused before any store read (10:945), each a one-line text refusal
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"query": "x" * (MAX_QUERY_CHARS + 1)}, "OW-A-008"),
        ({"query": "fees", "k": 5}, "takes no argument k"),
        ({"query": ""}, "non-empty query"),
        ({"query": "fees", "scope": "d1"}, "scope is published and not served"),
        ({"query": "fees", "want": "table"}, "want=table is published and not served"),
        ({"query": "fees", "route_hints": {}}, "route_hints is published and not served"),
        ({"query": "fees", "max_chars": 10}, "max_chars must be an integer in 1000-24000"),
        ({"query": "fees kind:novel"}, "kind:novel is not one of"),
    ],
)
def test_an_argument_this_build_cannot_honour_is_refused_by_name(
    store: Store, arguments: dict[str, Any], needle: str
) -> None:
    text = _text(_caller(store).answer(arguments))
    assert text.startswith("ow: ")
    assert needle in text
    assert text.count("\n") == 0
    assert "Fix: " in text


def test_a_query_the_schema_admits_can_still_be_refused_by_the_sanitiser(store: Store) -> None:
    """D529. 10:374 caps `query` at 4,096 characters and 07:1323 caps the text the sanitiser reads
    at 4,000, so a 4,050-character query passes the tool's own check and is refused one layer down
    -- by name, as a text refusal, and never as an exception on the wire."""
    text = _text(_caller(store).answer({"query": "fees " * 810}))
    assert text.startswith("ow: ")
    assert "MAX_QUERY_CHARS is 4000" in text


def test_the_arguments_are_the_published_schemas_properties() -> None:
    catalogue = json.loads((REPO / "schema" / "mcp-tools-v1.json").read_text(encoding="utf-8"))
    (tool,) = [one for one in catalogue if one["name"] == QUERY_TOOL]
    schema = tool["inputSchema"]
    assert set(schema["properties"]) == query_module._ARGUMENTS
    assert schema["properties"]["query"]["maxLength"] == MAX_QUERY_CHARS
    low, high = query_module._MAX_CHARS
    assert (
        schema["properties"]["max_chars"]["minimum"],
        schema["properties"]["max_chars"]["maximum"],
    ) == (low, high)


# ---------------------------------------------------------------------------------------------
# through the dispatcher
# ---------------------------------------------------------------------------------------------


def _dispatcher(store: Store) -> McpDispatcher:
    surface = Surface(profile="default", compact=True, corpus_resolves=True)
    return McpDispatcher.create(surface, caller=_caller(store))


def test_tools_call_for_ow_query_returns_the_answer_and_commits_nothing(store: Store) -> None:
    request = Request(
        ident=9, method=TOOLS_CALL, params={"name": QUERY_TOOL, "arguments": {"query": "fees"}}
    )
    reply = _drive(_dispatcher(store).dispatch(request))
    assert reply is not None
    assert reply.after_send is None, "no emission ledger is held yet (D525)"
    assert reply.body["id"] == 9
    assert _text(reply.body["result"]).startswith("ow/1 ")


def test_a_listed_tool_with_no_caller_yet_says_so(store: Store) -> None:
    request = Request(
        ident=1, method=TOOLS_CALL, params={"name": "ow_open", "arguments": {"ref": "d1#2"}}
    )
    reply = _drive(_dispatcher(store).dispatch(request))
    assert reply is not None
    assert reply.body["error"]["code"] == METHOD_NOT_FOUND
    assert "ow_open" in reply.body["error"]["message"]
