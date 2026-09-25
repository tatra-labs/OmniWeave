"""The official MCP client against `python -m omniweave serve --mcp`, run as a host runs it.

`omniweave_serve`'s own T3 test spawns the server with its three values already decided. This one
spawns the CLI, so step 5 runs in the child from a real `omniweave.toml`, and the values cross
the entry-point boundary before the server starts. What the client reads back is therefore the
configuration's decision: variant A and an optional `corpus` when a default corpus is declared,
variant B and a required `corpus` when none is (10:525, 10:871, D381).

**It spawns, so it is T3** (13 section 2.7). The spawn is the SDK's `stdio_client`, so this file
imports no `subprocess`.

**The last test is the first `tools/call` an agent host could make and get an answer from.** A
store is seeded beside a real `omniweave.toml`, the client calls `ow_query`, and what comes back is
the Answer document, rendered in the child from a retrieval over that store (W7.3r).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_serve import listing

pytestmark = pytest.mark.conform

DEADLINE_S = 60
HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'


NOW_NS = 1_757_400_000_000_000_000
PARAGRAPH = "Fees are payable monthly in arrears."


def _seeded(path: Path, text: str = PARAGRAPH) -> None:
    """One document and one paragraph, in a store the shipped migrations built."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = ow.connect(path)
    try:
        migrate.apply_pending(conn, now_ns=NOW_NS)

        def code(domain: str, name: str) -> int:
            row = conn.execute(
                "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
            ).fetchone()
            return int(row[0])

        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('op.parse', 1, 'fp', X'00')"
        )
        conn.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "                format_evidence, source_bytes, gen, status, model_version, "
            "                declared, achieved) "
            "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', 1, "
            "       1, 'ok', '1.1', '{}', '{}')",
            (b"\x01" * 16, b"\x00" * 16),
        )
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES(1, 1, 1, ?, ?, 1)",
            (code("page_kind", "page"), code("method", "native")),
        )
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
            "                  text, content_digest, os_kind, producer_id, method, trust, quote, "
            "                  origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(1, 1, 1, 1, 'p1/1', 'd1#1', 1, ?, ?, ?, ?, ?, 1, ?, 2, 4, 'op.parse', "
            "       'drv', 1, 0, 0)",
            (
                code("kind", "paragraph"),
                code("layer", "body"),
                text,
                b"\x00" * 16,
                code("origin_span_kind", "none"),
                code("method", "native"),
            ),
        )
        conn.execute(
            "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
            "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
            (NOW_NS,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _session(cwd: Path, argv: list[str]) -> dict[str, object]:
    seen: dict[str, object] = {}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "omniweave", "serve", *argv],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
    )

    async def talk() -> None:
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                init = await client.initialize()
                seen["instructions"] = init.instructions
                listed = await client.list_tools()
                seen["tools"] = [tool.model_dump(exclude_none=True) for tool in listed.tools]
                called = await client.call_tool("ow_query", {"query": "fees payable"})
                seen["called"] = called

    anyio.run(talk)
    return seen


@pytest.mark.parametrize("declared", [True, False])
def test_step_5_in_the_child_decides_what_the_client_reads(
    tmp_path: Path, *, declared: bool
) -> None:
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n' if declared else ""
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    seen = _session(tmp_path, ["--mcp"])
    assert seen["instructions"] == listing.instructions("default", corpus_resolves=declared)
    expected = listing.tools_list("default", compact=True, corpus_resolves=declared)
    assert seen["tools"] == list(expected)
    query = next(tool for tool in expected if tool["name"] == "ow_query")
    assert ("corpus" in query["inputSchema"]["required"]) is not declared


def test_the_profile_flag_reaches_the_server(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    seen = _session(tmp_path, ["--mcp", "--profile", "full"])
    assert seen["instructions"] == listing.instructions("full", corpus_resolves=False)


def test_the_client_calls_ow_query_and_reads_the_answer_document(tmp_path: Path) -> None:
    """The whole path: the host's `tools/call` -> step 5 in the child -> `QueryCaller` ->
    `retrieve()` over the seeded store -> `pack()` -> `render()` -> one text content block."""
    _seeded(tmp_path / ".omniweave" / "index.owstore")
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    called = _session(tmp_path, ["--mcp"])["called"]
    assert isinstance(called, CallToolResult)
    assert called.isError is False
    (content,) = called.content
    assert isinstance(content, TextContent)
    document = content.text
    assert document.startswith("ow/1 ")
    assert "corpus=handbook@0" in document
    assert "d1#1" in document
    assert PARAGRAPH in document


def test_with_no_corpus_declared_the_call_is_answered_with_ow_a_001(tmp_path: Path) -> None:
    """10:540: the tool is listed and callable before the first `ow add`, and the answer says what
    is missing rather than the call failing."""
    (tmp_path / "omniweave.toml").write_text("", encoding="utf-8")
    called = _session(tmp_path, ["--mcp"])["called"]
    assert isinstance(called, CallToolResult)
    assert called.isError is False
    (content,) = called.content
    assert isinstance(content, TextContent)
    assert "[OW-A-001]" in content.text


LONG = "Fees are payable monthly in arrears, in the currency of the invoice. " * 9
"""A paragraph worth withholding: above 18:486's 400 characters net of the row that replaces it."""


def _conversation(cwd: Path, calls: int, before: dict[int, Callable[[], None]]) -> list[str]:
    """`calls` `ow_query` calls in ONE child, and so one session; `before[i]` runs before call i."""
    texts: list[str] = []
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "omniweave", "serve", "--mcp"],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
    )

    async def talk() -> None:
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                await client.initialize()
                for index in range(calls):
                    if index in before:
                        before[index]()
                    called = await client.call_tool("ow_query", {"query": "fees payable"})
                    assert isinstance(called, CallToolResult)
                    assert called.isError is False
                    (content,) = called.content
                    assert isinstance(content, TextContent)
                    texts.append(content.text)

    anyio.run(talk)
    return texts


def test_the_second_call_in_a_session_points_at_what_the_first_sent(tmp_path: Path) -> None:
    """D525 closed, across a real process boundary: the child commits the first Answer's blocks
    after it wrote them, and the second Answer withholds them behind an `ow:sent-earlier` row."""
    _seeded(tmp_path / ".omniweave" / "index.owstore", LONG)
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    first, second = _conversation(tmp_path, 2, {})
    assert LONG in first
    assert "dedup saved 0 chars" in first
    assert "**ow:sent-earlier**" in second
    assert LONG not in second
    assert "call 2 of" in second
    assert "dedup saved 0 chars" not in second


def test_a_compaction_marker_between_calls_brings_the_content_back(tmp_path: Path) -> None:
    """10:1948: the `PreCompact` hook's marker, written where the hook writes it, clears the
    child's ledger, and the next Answer re-sends and says why (D534)."""
    _seeded(tmp_path / ".omniweave" / "index.owstore", LONG)
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    sessions = tmp_path / ".omniweave" / "sessions"

    def compact() -> None:
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "0123456789abcdef.compacted").write_text("{}", encoding="utf-8")

    _, second, third = _conversation(tmp_path, 3, {1: compact})
    assert LONG in second
    assert "ledger_reset_by_compaction" in second
    assert "**ow:sent-earlier**" in third


def _tools(cwd: Path, calls: list[tuple[str, dict[str, object]]]) -> list[str]:
    """Each `(tool, arguments)` in ONE child, in order; the text of each result."""
    texts: list[str] = []
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "omniweave", "serve", "--mcp"],
        env={"OMNIWEAVE_HOME": str(cwd / "owhome")},
        cwd=cwd,
    )

    async def talk() -> None:
        with anyio.fail_after(DEADLINE_S):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                await client.initialize()
                for name, arguments in calls:
                    called = await client.call_tool(name, arguments)
                    assert isinstance(called, CallToolResult)
                    assert called.isError is False
                    (content,) = called.content
                    assert isinstance(content, TextContent)
                    texts.append(content.text)

    anyio.run(talk)
    return texts


def test_the_client_opens_a_cite_a_document_and_a_stale_address(tmp_path: Path) -> None:
    """`ow_open`, the other half of the front door, across a real process boundary: the cite the
    first `ow_query` returned resolves exactly, a file name resolves to its document, and an
    address the store does not hold is an Answer saying so rather than a failed call."""
    _seeded(tmp_path / ".omniweave" / "index.owstore", LONG)
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    cite, document, stale = _tools(
        tmp_path,
        [
            ("ow_open", {"ref": "d1#1"}),
            ("ow_open", {"ref": "contract.pdf"}),
            ("ow_open", {"ref": "contract.pdf#p1/99"}),
        ],
    )
    assert cite.startswith("ow/1 ok corpus=handbook@0 ")
    assert LONG.strip() in cite
    assert "resolved           = 1 of 1 refs" in cite
    assert LONG.strip() in document
    assert stale.startswith("ow/1 degraded ")
    assert "[OW-M-032]" in stale
