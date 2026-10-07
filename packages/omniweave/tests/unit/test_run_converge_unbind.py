"""`converge.unbind_document`: a retired document leaves the reference graph. **D673.**

06 section 10.2's *"a whole document deleted"* row -- *"every d7 anchor removed -> unbind"* -- over
a real migrated store, with the rows written by hand so each test names exactly the graph it starts
from: documents of one block each (`block_id = 10 x doc_ord`), anchors, occurrences and links.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from omniweave.run.converge import Unbound, unbind_document
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow

NOW_NS = 1_700_000_000_000_000_000


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[Any]:
    """A migrated store inside one open write transaction. `Any`: TID251 bans naming `sqlite3`."""
    conn = ow.connect(tmp_path / "index.owstore")
    try:
        migrate.apply_pending(conn, now_ns=NOW_NS)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, "
            "options_digest) VALUES(1, 'op.parse', 1, 'fp', X'00')"
        )
        conn.execute(
            "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
            "granularity, card_sha256, schema_version) VALUES('derive.anchor.native', 'derive/1', "
            "'free', 0, 20, '[\"anchor\"]', 'document', 'sha', 1)"
        )
        conn.execute(
            "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
            "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, cache_key, "
            "status) VALUES(1, NULL, 'derive.anchor.native', 1, 1, 0, 'derive.anchor.native', "
            "'derive.anchor.native', 1, 'free', X'00', 'k', 'ok')"
        )
        yield conn
        conn.execute("COMMIT")
    finally:
        conn.close()


def _doc(conn: Any, doc_ord: int) -> int:
    """One document at generation 1 with one live block, `10 x doc_ord`. Returns the block id."""
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
        "VALUES(?, ?, X'00', ?, 'text/plain', 'text', '{}', 1, 1, 'ok', '1.1', '{}', '{}')",
        (doc_ord, bytes([doc_ord]) * 16, f"c:/docs/{doc_ord}.txt"),
    )
    conn.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(?, 1, 0, 0, 0, 1)",
        (doc_ord,),
    )
    block_id = doc_ord * 10
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
        "content_digest, os_kind, producer_id, method, trust, quote, origin_operator, "
        "origin_driver, driver_schema_v) VALUES(?, ?, 1, 0, 'p0/0', ?, 0, 1, 0, 'text', X'00', "
        "4, 1, 0, 2, 4, 'op.parse', 'drv', 1)",
        (block_id, doc_ord, f"d{doc_ord}#1"),
    )
    return block_id


def _anchor(conn: Any, doc_ord: int, name: str, akind: str, scope: str = "document") -> None:
    conn.execute(
        "INSERT INTO anchor(doc_ord, gen, name_norm, akind, surface, block_id, scope, run_id) "
        "VALUES(?, 1, ?, ?, ?, ?, ?, 1)",
        (doc_ord, name, akind, name, doc_ord * 10, scope),
    )


def _site(conn: Any, doc_ord: int, name: str, akind: str) -> None:
    conn.execute(
        "INSERT INTO ref_site(name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, scope, "
        "origin_operator) VALUES(?, ?, ?, ?, 0, 4, ?, 'document', 'derive.xref.pattern')",
        (name, akind, doc_ord, doc_ord * 10, name),
    )


def _link(conn: Any, src: int, dst: int, bound_by: str | None, *, ambiguous: int = 0) -> None:
    conn.execute(
        "INSERT INTO block_link(src_block, dst_block, relation, site_block, bound_by, ambiguous, "
        "producer_id, trust, origin_operator, origin_driver, driver_schema_v) "
        "VALUES(?, ?, 'refers_to', ?, ?, ?, 1, 2, 'derive.xref.pattern', 'derive.xref.pattern', 1)",
        (src, dst, src, bound_by, ambiguous),
    )


def _links(conn: Any) -> list[tuple[int, int, str | None, int]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT src_block, dst_block, bound_by, ambiguous FROM block_link "
            "ORDER BY src_block, dst_block"
        )
    ]


def test_a_retired_documents_anchors_occurrences_and_bound_links_all_leave(
    connection: Any,
) -> None:
    """Links INTO it (bound by its anchors) and OUT of it (made by its occurrences) both go.

    Document 1 defines `section 1` and references document 2's corpus identifier, so it holds one
    link of each direction. Its anchor and its occurrence leave with them, and document 2's rows
    are untouched: its anchor stays, and its own occurrence still resolves.
    """
    one, two = _doc(connection, 1), _doc(connection, 2)
    _anchor(connection, 1, "1", "section")
    _anchor(connection, 2, "gl_4471", "identifier", scope="corpus")
    _site(connection, 1, "gl_4471", "identifier")
    _site(connection, 2, "gl_4471", "identifier")
    _link(connection, one, two, "gl_4471")
    _link(connection, two, one, "1")
    report = unbind_document(connection, 1)
    assert report == Unbound(doc_ord=1, anchors=1, occurrences=1, links=2, disambiguated=0)
    assert connection.execute("SELECT doc_ord FROM anchor").fetchall() == [(2,)]
    assert connection.execute("SELECT doc_ord FROM ref_site").fetchall() == [(2,)]
    assert _links(connection) == []
    assert connection.execute("SELECT COUNT(*) FROM ref_unresolved").fetchone() == (0,)


def test_a_link_with_no_binding_anchor_is_never_unbound(connection: Any) -> None:
    """06:1249: *"Only rows carrying it participate in `unbind` ... never delete what we cannot
    restore"*. A link another writer made without `bound_by` stays, retired endpoint or not."""
    one, two = _doc(connection, 1), _doc(connection, 2)
    _link(connection, two, one, None)
    assert unbind_document(connection, 1).links == 0
    assert _links(connection) == [(two, one, None, 0)]


def test_the_surviving_target_of_an_ambiguous_reference_is_no_longer_ambiguous(
    connection: Any,
) -> None:
    """Two documents defined the corpus identifier; one is retired; the other is now the target."""
    one, two, three = _doc(connection, 1), _doc(connection, 2), _doc(connection, 3)
    for doc_ord in (1, 2):
        _anchor(connection, doc_ord, "gl_4471", "identifier", scope="corpus")
    _site(connection, 3, "gl_4471", "identifier")
    _link(connection, three, one, "gl_4471", ambiguous=1)
    _link(connection, three, two, "gl_4471", ambiguous=1)
    report = unbind_document(connection, 1)
    assert (report.links, report.disambiguated) == (1, 1)
    assert _links(connection) == [(three, two, "gl_4471", 0)]


def test_a_reference_still_with_two_targets_stays_ambiguous(connection: Any) -> None:
    """Three definitions, one retired: two remain, so the occurrence is still ambiguous."""
    blocks = [_doc(connection, doc_ord) for doc_ord in (1, 2, 3, 4)]
    for doc_ord in (1, 2, 4):
        _anchor(connection, doc_ord, "gl_4471", "identifier", scope="corpus")
    _site(connection, 3, "gl_4471", "identifier")
    for dst in (blocks[0], blocks[1], blocks[3]):
        _link(connection, blocks[2], dst, "gl_4471", ambiguous=1)
    assert unbind_document(connection, 1).disambiguated == 0
    assert _links(connection) == [(30, 20, "gl_4471", 1), (30, 40, "gl_4471", 1)]


def test_another_documents_link_bound_by_the_same_name_is_left_alone(connection: Any) -> None:
    """`bound_by` is a NAME, and every contract has a `Section 1`: the unbind is keyed on the
    retired document's blocks, never on the name alone, so document 2's own link survives."""
    _doc(connection, 1)
    _doc(connection, 2)
    connection.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
        "content_digest, os_kind, producer_id, method, trust, quote, origin_operator, "
        "origin_driver, driver_schema_v) VALUES(21, 2, 1, 0, 'p0/1', 'd2#2', 1, 1, 0, 'text', "
        "X'00', 4, 1, 0, 2, 4, 'op.parse', 'drv', 1)"
    )
    _anchor(connection, 1, "1", "section")
    _anchor(connection, 2, "1", "section")
    _link(connection, 21, 20, "1")
    unbind_document(connection, 1)
    assert _links(connection) == [(21, 20, "1", 0)]
    assert connection.execute("SELECT doc_ord FROM anchor").fetchall() == [(2,)]
