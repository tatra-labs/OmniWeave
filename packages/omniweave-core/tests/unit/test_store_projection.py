"""`canonical_projection()`: GR8's comparison, with every surrogate id taken out. **D675.**

06:2410-2415's six members over real migrated stores, written by hand so a test can put the same
graph behind DIFFERENT surrogates -- other `doc_ord`s, other `block_id`s, other insertion orders --
and require the two projections equal, and put a retired row beside a live one and require it gone.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- this file drives a REAL store.
from collections.abc import Iterator
from pathlib import Path

import pytest
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.projection import CanonicalProjection, canonical_projection

NOW_NS = 1_700_000_000_000_000_000
KEY_A = bytes.fromhex("aa" * 16)
KEY_B = bytes.fromhex("bb" * 16)


def _store(path: Path) -> sqlite3.Connection:
    conn = ow.connect(path)
    migrate.apply_pending(conn, now_ns=NOW_NS)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, "
        "options_digest) VALUES(1, 'op.parse', 1, 'fp', X'00')"
    )
    conn.execute(
        "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, granularity, "
        "card_sha256, schema_version) VALUES('derive.anchor.defterm', 'derive/1', 'free', 0, 30, "
        "'[\"anchor\"]', 'document', 'sha', 1)"
    )
    conn.execute(
        "INSERT INTO derive_run(run_id, segment_id, pass_id, at_gen, producer_id, method, "
        "origin_operator, origin_driver, driver_schema_v, cost_class, input_digest, cache_key, "
        "status) VALUES(1, NULL, 'derive.anchor.defterm', 1, 1, 0, 'derive.anchor.defterm', "
        "'derive.anchor.defterm', 1, 'free', X'00', 'k', 'ok')"
    )
    return conn


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    one, two = _store(tmp_path / "one.owstore"), _store(tmp_path / "two.owstore")
    try:
        yield one, two
    finally:
        one.close()
        two.close()


def _doc(conn: sqlite3.Connection, doc_ord: int, key: bytes, *, gen: int = 1) -> None:
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
        "VALUES(?, ?, X'00', ?, 'text/plain', 'text', '{}', 1, ?, 'ok', '1.1', '{}', '{}')",
        (doc_ord, key, f"c:/docs/{doc_ord}.txt", gen),
    )


def _block(conn: sqlite3.Connection, block_id: int, doc_ord: int, addr: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(?, 1, 0, 0, 0, 1)",
        (doc_ord,),
    )
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
        "content_digest, os_kind, producer_id, method, trust, quote, origin_operator, "
        "origin_driver, driver_schema_v) VALUES(?, ?, 1, 0, ?, ?, 0, 1, 0, 'text', X'00', 4, 1, "
        "0, 2, 4, 'op.parse', 'drv', 1)",
        (block_id, doc_ord, addr, f"d{doc_ord}#{block_id}"),
    )


def _entity(
    conn: sqlite3.Connection, entity_id: int, scope: int, key: str, *, state: int = 0
) -> None:
    conn.execute(
        "INSERT INTO entity(entity_id, cite, scope, etype, key, title, canonical_id, "
        "resolution_method, trust, mention_digest, state) "
        "VALUES(?, ?, ?, 'defined_term', ?, ?, ?, 0, 2, X'00', ?)",
        (entity_id, f"e{entity_id}", scope, key, key, entity_id, state),
    )


def _anchor(conn: sqlite3.Connection, doc_ord: int, gen: int, name: str, block_id: int) -> None:
    conn.execute(
        "INSERT INTO anchor(doc_ord, gen, name_norm, akind, surface, block_id, scope, run_id) "
        "VALUES(?, ?, ?, 'section', ?, ?, 'document', 1)",
        (doc_ord, gen, name, name, block_id),
    )


def _site(conn: sqlite3.Connection, doc_ord: int, name: str, block_id: int) -> None:
    conn.execute(
        "INSERT INTO ref_site(name_norm, akind, doc_ord, block_id, ts_a, ts_b, surface, scope, "
        "origin_operator) VALUES(?, 'identifier', ?, ?, 0, 4, ?, 'document', 'x')",
        (name, doc_ord, block_id, name),
    )


def _graph(conn: sqlite3.Connection, ords: tuple[int, int], blocks: tuple[int, int]) -> None:
    """One graph: two documents, each a block, a defined term, a section and an occurrence."""
    (a, b), (block_a, block_b) = ords, blocks
    _doc(conn, a, KEY_A)
    _doc(conn, b, KEY_B)
    _block(conn, block_a, a, "p0/0")
    _block(conn, block_b, b, "p0/0")
    _entity(conn, block_a, a, "lender")
    _entity(conn, block_b, b, "notice")
    _entity(conn, block_a + block_b, 0, "acme")
    _anchor(conn, a, 1, "1", block_a)
    _anchor(conn, b, 1, "1", block_b)
    _site(conn, b, "gl_4471", block_b)


def test_the_same_graph_behind_other_surrogates_projects_equal(
    stores: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """Documents 1 and 2 in one store are 7 and 3 in the other, with other block ids: equal."""
    one, two = stores
    _graph(one, (1, 2), (10, 20))
    _graph(two, (7, 3), (71, 32))
    left, right = canonical_projection(one), canonical_projection(two)
    assert left == right
    assert left.differences(right) == {}
    assert left.entities == (
        ("aa" * 16, "defined_term", "lender"),
        ("bb" * 16, "defined_term", "notice"),
        ("corpus", "defined_term", "acme"),
    )
    assert left.anchors == (("aa" * 16, "1", "section"), ("bb" * 16, "1", "section"))
    assert left.unresolved == ("gl_4471",)
    assert (left.edges, left.claims, left.communities) == ((), (), ())


def test_a_retired_entity_and_a_non_head_anchor_are_not_projected(
    stores: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """A full rebuild of the current corpus holds neither, so neither may be compared."""
    one, two = stores
    _graph(one, (1, 2), (10, 20))
    _graph(two, (1, 2), (10, 20))
    _entity(two, 99, 1, "borrower", state=2)
    _anchor(two, 1, 0, "9", 10)
    assert canonical_projection(one) == canonical_projection(two)


def test_differences_names_each_member_and_what_only_each_side_holds(
    stores: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    one, two = stores
    _graph(one, (1, 2), (10, 20))
    _graph(two, (1, 2), (10, 20))
    _entity(two, 99, 1, "borrower")
    _site(one, 1, "cve_2026", 10)
    found = canonical_projection(one).differences(canonical_projection(two))
    assert found == {
        "entities": ([], [("aa" * 16, "defined_term", "borrower")]),
        "unresolved": (["cve_2026"], []),
    }


def test_two_occurrences_of_one_unresolved_name_project_twice(
    stores: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """06:2414 prints a `name_norm` MULTISET: a name referenced twice and defined nowhere is two."""
    one, _two = stores
    _graph(one, (1, 2), (10, 20))
    _site(one, 1, "gl_4471", 10)
    assert canonical_projection(one).unresolved == ("gl_4471", "gl_4471")


def test_a_multiset_keeps_its_duplicates() -> None:
    """Two occurrences of one unresolved name are two, not one: `ref_unresolved` is a multiset."""
    left = CanonicalProjection((), (), (), (), ("x", "x"), ())
    right = CanonicalProjection((), (), (), (), ("x",), ())
    assert left != right
    assert left.differences(right) == {"unresolved": (["x"], [])}
