"""A resolved reference is a `block_link`, and `relation_vocab` carries the thirteen. **D672.**

06:1099-1101: the sink *"looks `name_norm` up in `anchor` under the scope rule and writes either an
`edge(relation='refers_to', bound_by=name_norm)` plus a `block_link` row, or a bare `ref_site`
occurrence"*. These tests drive `SqliteGraphSink` against a real migrated store with three
documents, so the scope rule, the head-generation rule and the arrival order are all exercised the
way a corpus exercises them: a definition in one document, references in the others, and Passes that
run in either order.

`import sqlite3` below, as in `test_store_graph.py`: this file drives a REAL store.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- this file drives a REAL store.
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest
from omniweave_core.answer.untrusted import SANITIZE_MAX, sanitize_label
from omniweave_core.errors import ResourceLimit
from omniweave_core.model.block import Cite
from omniweave_core.model.enums import MAX_TRUST_BY_METHOD, AnchorKind, Method, Trust
from omniweave_core.store import graph as graph_module
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.graph import (
    BUILTIN_RELATIONS,
    AnchorDraft,
    PassIdentity,
    SegmentRef,
    SqliteGraphSink,
    XrefDraft,
)

NOW_NS = 1_757_400_000_000_000_000
GEN = 1

ANCHORS = "derive.anchor.native"
XREFS = "derive.xref.pattern"
ANCHOR_PRODUCER = 1
XREF_PRODUCER = 2

DOCS: dict[int, tuple[tuple[int, str], ...]] = {
    1: ((11, "1. Definitions"), (12, "See Section 1 and Section 1 again.")),
    2: ((21, "Glossary and GL-4471"), (22, "Section 1 applies, as does GL-4471.")),
    3: ((31, "Exhibit table GL-4471"), (32, "Account GL-4471 is closed.")),
}
"""Three documents, two blocks each. A block id is `10 x doc + n`, so a link reads as its route."""

LINK_COLUMNS = (
    "src_block, dst_block, relation, site_block, via_entity, bound_by, weight, ambiguous, "
    "producer_id, trust, score, score_kind, origin_operator, origin_driver, driver_schema_v, "
    "restriction_bits"
)


class _Spend:
    """The eight attributes `SpendVector` declares; `test_store_graph.py` says why that suffices."""

    wall_ms = cpu_ms = gpu_ms = tokens_in = tokens_out = calls = bytes_egress = 0
    provider = ""


def _seed(connection: sqlite3.Connection) -> None:
    """Two producers, two registered Passes, three documents with one Segment each."""
    for producer_id, operator in ((ANCHOR_PRODUCER, ANCHORS), (XREF_PRODUCER, XREFS)):
        connection.execute(
            "INSERT INTO producer (producer_id, operator, op_version, code_fingerprint, "
            "options_digest) VALUES (?, ?, 1, 'abc', X'00')",
            (producer_id, operator),
        )
    for pass_id, lane in ((ANCHORS, "anchor"), (XREFS, "xref")):
        connection.execute(
            "INSERT INTO derive_pass (pass_id, port, cost_class, cost_rank, phase, lanes, "
            "granularity, card_sha256, schema_version) "
            "VALUES (?, 'derive/1', 'free', 0, 20, ?, 'document', 'sha', 1)",
            (pass_id, f'["{lane}"]'),
        )
    connection.execute(
        "INSERT INTO segmenter (segmenter_id, driver_id, driver_schema_v, params_digest) "
        "VALUES (1, 'derive.segment.spine', 1, X'00')"
    )
    for doc_ord, blocks in DOCS.items():
        connection.execute(
            "INSERT INTO doc (doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
            "VALUES (?, ?, X'02', ?, 'text/plain', 'text', '{}', 1, ?, 'ok', '1.1', '{}', '{}')",
            (doc_ord, bytes([doc_ord]), f"file:///{doc_ord}.txt", GEN),
        )
        connection.execute(
            "INSERT INTO page (doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES (?, ?, 0, 0, 0, 1)",
            (doc_ord, GEN),
        )
        connection.execute(
            "INSERT INTO segment (segment_id, doc_ord, gen, ord, segmenter_id, layer, "
            "heading_path, n_blocks, n_tokens, n_chars, tokenizer_id, first_page, last_page, "
            "trust, quote_min, kind_mask, content_digest, origin_operator, origin_driver, "
            "driver_schema_v) VALUES (?, ?, ?, 0, 1, 0, '[]', ?, 10, 50, 'tok', 0, 0, 2, 4, 1, "
            "X'04', 'op.segment', 'derive.segment.spine', 1)",
            (doc_ord, doc_ord, GEN, len(blocks)),
        )
        for index, (block_id, text) in enumerate(blocks):
            connection.execute(
                "INSERT INTO block (block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
                "text, content_digest, os_kind, producer_id, method, trust, quote, "
                "origin_operator, origin_driver, driver_schema_v) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, 1, 0, ?, X'03', 4, 1, 0, 2, 4, 'op.parse', "
                "'parse.native', 1)",
                (block_id, doc_ord, GEN, f"p0/{index}", _cite(block_id), index, text),
            )
            connection.execute(
                "INSERT INTO segment_block (block_id, segment_id, ord) VALUES (?, ?, ?)",
                (block_id, doc_ord, index),
            )


def _cite(block_id: int) -> str:
    return f"d{block_id // 10}#{block_id % 10}"


def _store(path: Path) -> sqlite3.Connection:
    conn = ow.connect(path)
    migrate.apply_pending(conn, now_ns=NOW_NS)
    conn.execute("BEGIN IMMEDIATE")
    _seed(conn)
    return conn


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated store with the three documents seeded, inside one open write transaction."""
    conn = _store(tmp_path / "index.owstore")
    try:
        yield conn
        conn.execute("COMMIT")
    finally:
        conn.close()


def _run(
    conn: sqlite3.Connection,
    doc_ord: int,
    drafts: Iterable[AnchorDraft | XrefDraft],
    *,
    method: Method | None = None,
) -> None:
    """One run of the anchor Pass or the xref Pass over one document's Segment."""
    drafts = list(drafts)
    is_anchor = isinstance(drafts[0], AnchorDraft)
    pass_id = ANCHORS if is_anchor else XREFS
    sink = SqliteGraphSink(conn)
    sink.begin_run(
        SegmentRef(
            segment_id=doc_ord,
            doc_ord=doc_ord,
            gen=GEN,
            content_digest=b"\x04",
            uncovered=bytes(64),
        ),
        PassIdentity(
            pass_id=pass_id,
            producer_id=ANCHOR_PRODUCER if is_anchor else XREF_PRODUCER,
            method=method or (Method.NATIVE_XML if is_anchor else Method.HEURISTIC),
            origin_operator=pass_id,
            origin_driver=pass_id,
            driver_schema_v=1,
            cost_class="free",
        ),
        frozenset(Cite(_cite(block_id)) for block_id, _ in DOCS[doc_ord]),
    )
    for draft in drafts:
        if isinstance(draft, AnchorDraft):
            sink.anchor(draft)
        else:
            sink.xref(draft)
    sink.end_run("ok", _Spend())


def _anchor(
    block_id: int,
    quote: str,
    name: str,
    *,
    akind: AnchorKind = AnchorKind.SECTION,
    scope: str = "document",
) -> AnchorDraft:
    return AnchorDraft(
        name=name,
        akind=akind,
        at=(Cite(_cite(block_id)), quote),
        scope=scope,  # type: ignore[arg-type]
        surface=quote,
    )


def _xref(
    block_id: int, quote: str, name: str, *, akind: AnchorKind = AnchorKind.SECTION
) -> XrefDraft:
    return XrefDraft(name=name, akind=akind, at=(Cite(_cite(block_id)), quote), surface=quote)


def _links(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            f"SELECT {LINK_COLUMNS} FROM block_link ORDER BY src_block, dst_block"  # noqa: S608
        )
    ]


def _pairs(conn: sqlite3.Connection) -> list[tuple[int, int, int]]:
    return [
        (int(src), int(dst), int(ambiguous))
        for src, dst, ambiguous in conn.execute(
            "SELECT src_block, dst_block, ambiguous FROM block_link ORDER BY src_block, dst_block"
        )
    ]


SECTION_ONE = _anchor(11, "1. Definitions", "1")
SEE_SECTION_ONE = _xref(12, "Section 1 and", "1")


# ---------------------------------------------------------------------------------------------
# The link a resolved reference makes
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_first", [True, False], ids=["anchor-first", "reference-first"])
def test_a_resolved_reference_is_a_refers_to_link_from_its_block_to_the_anchors(
    connection: sqlite3.Connection, anchor_first: bool
) -> None:
    """Every column, and the provenance is the run that OBSERVED the reference (D672 reading 1).

    The xref run is an `llm` one here, so its ceiling (`INFERRED`) differs from the anchor run's
    (`native_xml`, `EXTRACTED`): a sink stamping whichever run completed the binding writes a
    different `trust` and `producer_id` in one of the two orders.
    """
    if anchor_first:
        _run(connection, 1, [SECTION_ONE])
    _run(connection, 1, [SEE_SECTION_ONE], method=Method.LLM)
    if not anchor_first:
        _run(connection, 1, [SECTION_ONE])
    assert _links(connection) == [
        (
            12,
            11,
            "refers_to",
            12,
            None,
            "1",
            1.0,
            0,
            XREF_PRODUCER,
            int(MAX_TRUST_BY_METHOD[Method.LLM]),
            None,
            None,
            XREFS,
            XREFS,
            1,
            0,
        )
    ]
    assert int(MAX_TRUST_BY_METHOD[Method.LLM]) == int(Trust.INFERRED)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_link_is_the_same_whichever_write_lands_first(tmp_path: Path) -> None:
    """*"at write time and again on `anchor_delta`"* (06:1099): order cannot change the rows.

    Anchor first, the reference binds itself; reference first, the anchor binds it. Both stores
    end with the identical row -- attributed to the xref run either way.
    """
    rows = []
    for order, name in (
        ((SECTION_ONE, SEE_SECTION_ONE), "a"),
        ((SEE_SECTION_ONE, SECTION_ONE), "b"),
    ):
        conn = _store(tmp_path / f"{name}.owstore")
        try:
            for draft in order:
                _run(conn, 1, [draft])
            rows.append(_links(conn))
            conn.execute("COMMIT")
        finally:
            conn.close()
    assert rows[0] == rows[1]
    assert len(rows[0]) == 1
    assert rows[0][0][8] == XREF_PRODUCER


def test_two_occurrences_in_one_block_make_one_link_and_two_ref_sites(
    connection: sqlite3.Connection,
) -> None:
    """`block_link_identity` has no span in it: the occurrence is `ref_site`'s, the link is one."""
    _run(connection, 1, [SECTION_ONE])
    _run(connection, 1, [SEE_SECTION_ONE, _xref(12, "Section 1 again", "1")])
    assert connection.execute("SELECT COUNT(*) FROM ref_site").fetchone()[0] == 2
    assert _pairs(connection) == [(12, 11, 0)]


def test_an_unresolved_reference_makes_no_link_and_stays_in_the_residue(
    connection: sqlite3.Connection,
) -> None:
    _run(connection, 1, [SECTION_ONE])
    _run(connection, 1, [_xref(12, "Section 1 and", "1", akind=AnchorKind.EXHIBIT)])
    assert _links(connection) == []
    assert connection.execute("SELECT COUNT(*) FROM ref_unresolved").fetchone()[0] == 1


# ---------------------------------------------------------------------------------------------
# The two predicates both reference views carry, and the live-source rule
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_first", [True, False], ids=["anchor-first", "reference-first"])
def test_a_document_scoped_anchor_links_no_other_documents_reference(
    connection: sqlite3.Connection, anchor_first: bool
) -> None:
    """*"'Figure 3' in one contract binding 'Figure 3' in another"* (07:528) -- in either order.

    Anchor first, document 2's reference binds itself at its own write (the `xref` arm); reference
    first, document 1's anchor is the write that would bind it (the `anchor` arm).
    """
    other = _xref(22, "Section 1 applies", "1")
    for doc_ord, draft in [(1, SECTION_ONE), (2, other)][:: 1 if anchor_first else -1]:
        _run(connection, doc_ord, [draft])
    _run(connection, 1, [SEE_SECTION_ONE])
    assert _pairs(connection) == [(12, 11, 0)]


def test_a_corpus_scoped_anchor_links_every_document_and_a_second_target_is_ambiguous(
    connection: sqlite3.Connection,
) -> None:
    """`ambiguous` is >1 target, KEPT, ranked down (0003:319); a later target re-marks the first."""
    _run(connection, 3, [_xref(32, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER)])
    _run(
        connection,
        1,
        [_anchor(11, "Definitions", "GL-4471", akind=AnchorKind.IDENTIFIER, scope="corpus")],
    )
    assert _pairs(connection) == [(32, 11, 0)]
    _run(
        connection,
        2,
        [_anchor(21, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER, scope="corpus")],
    )
    assert _pairs(connection) == [(32, 11, 1), (32, 21, 1)]


def test_an_anchor_of_a_retired_generation_links_nothing(connection: sqlite3.Connection) -> None:
    """HEAD GENERATION ONLY (07:520): document 1 re-ingested, its old anchor no longer resolves."""
    _run(
        connection,
        1,
        [_anchor(11, "Definitions", "GL-4471", akind=AnchorKind.IDENTIFIER, scope="corpus")],
    )
    connection.execute("UPDATE doc SET gen = 2 WHERE doc_ord = 1")
    _run(connection, 3, [_xref(32, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER)])
    assert _links(connection) == []


def test_a_retired_source_block_is_not_linked_when_its_anchor_arrives_later(
    connection: sqlite3.Connection,
) -> None:
    """A tombstoned block's occurrence is history, not a live reference to bind."""
    _run(connection, 3, [_xref(32, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER)])
    connection.execute("UPDATE block SET state = 1 WHERE block_id = 32")
    _run(
        connection,
        1,
        [_anchor(11, "Definitions", "GL-4471", akind=AnchorKind.IDENTIFIER, scope="corpus")],
    )
    assert _links(connection) == []


def test_restriction_bits_are_both_ends_or(connection: sqlite3.Connection) -> None:
    """A link discloses both blocks it joins (D672 reading 4)."""
    connection.execute("UPDATE block SET restriction_bits = 4 WHERE block_id = 11")
    connection.execute("UPDATE block SET restriction_bits = 1 WHERE block_id = 12")
    _run(connection, 1, [SECTION_ONE])
    _run(connection, 1, [SEE_SECTION_ONE])
    (bits,) = connection.execute("SELECT restriction_bits FROM block_link").fetchone()
    assert bits == 5


# ---------------------------------------------------------------------------------------------
# MAX_LINKS_PER_BLOCK
# ---------------------------------------------------------------------------------------------


def test_a_block_at_the_link_ceiling_gets_no_more_links_and_one_fatal_diag(
    connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """07:1058's ceiling, at 1 here: the breach is recorded once, the occurrence kept.

    One occurrence with three targets -- two corpus-scoped anchors in other documents and its own
    document's -- so the first link is written, the next two are refused, and one `Diag` says so,
    against the SOURCE's document.
    """
    monkeypatch.setattr(graph_module, "MAX_LINKS_PER_BLOCK", 1)
    for doc_ord, block_id, quote, scope in (
        (1, 11, "Definitions", "corpus"),
        (2, 21, "GL-4471", "corpus"),
        (3, 31, "GL-4471", "document"),
    ):
        _run(
            connection,
            doc_ord,
            [_anchor(block_id, quote, "GL-4471", akind=AnchorKind.IDENTIFIER, scope=scope)],
        )
    assert connection.execute("SELECT COUNT(*) FROM anchor").fetchone()[0] == 3
    _run(connection, 3, [_xref(32, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER)])
    assert _pairs(connection) == [(32, 11, 1)]
    assert connection.execute("SELECT COUNT(*) FROM ref_site").fetchone()[0] == 1
    diags = connection.execute(
        "SELECT doc_ord, gen, block_id, code, fatal FROM diag WHERE code = ?",
        (ResourceLimit.SYMBOL,),
    ).fetchall()
    assert [tuple(row) for row in diags] == [(3, GEN, 32, ResourceLimit.SYMBOL, 1)]


def test_a_ceiling_reached_by_a_later_anchor_is_recorded_on_the_sources_document(
    connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `anchor` arm can bind another document's occurrence: the diag belongs to THAT document.

    Document 3's reference is written first; document 1's corpus anchor links it, and document 2's
    finds the block at the ceiling. The run is document 2's, the refused link is document 3's.
    """
    monkeypatch.setattr(graph_module, "MAX_LINKS_PER_BLOCK", 1)
    _run(connection, 3, [_xref(32, "GL-4471", "GL-4471", akind=AnchorKind.IDENTIFIER)])
    for doc_ord, block_id, quote in ((1, 11, "Definitions"), (2, 21, "GL-4471")):
        _run(
            connection,
            doc_ord,
            [_anchor(block_id, quote, "GL-4471", akind=AnchorKind.IDENTIFIER, scope="corpus")],
        )
    assert _pairs(connection) == [(32, 11, 1)], "kept, and marked: it now has two targets"
    diags = connection.execute(
        "SELECT doc_ord, block_id, fatal FROM diag WHERE code = ?", (ResourceLimit.SYMBOL,)
    ).fetchall()
    assert [tuple(row) for row in diags] == [(3, 32, 1)]


def test_a_reference_to_an_anchor_in_its_own_block_is_resolved_and_not_a_self_link(
    connection: sqlite3.Connection,
) -> None:
    """A loop from a block to itself traverses nowhere (D672 reading 7); the view still binds it."""
    _run(connection, 2, [_anchor(22, "Section 1 applies", "1")])
    _run(connection, 2, [_xref(22, "Section 1", "1")])
    assert _links(connection) == []
    assert connection.execute("SELECT COUNT(*) FROM ow_ref_resolved").fetchone()[0] == 1


# ---------------------------------------------------------------------------------------------
# relation_vocab's thirteen
# ---------------------------------------------------------------------------------------------


def test_the_migration_seeds_relation_vocabs_thirteen_builtins(
    connection: sqlite3.Connection,
) -> None:
    """06:293's thirteen, in its order, and `cites` carrying the one `actor_rule` 06:304 prints."""
    rows = {
        str(relation): (int(symmetric), str(rule), str(source))
        for relation, symmetric, rule, source in connection.execute(
            "SELECT relation, symmetric, actor_rule, source FROM relation_vocab"
        )
    }
    assert list(rows) == sorted(rows)
    assert [relation for relation, _, _ in BUILTIN_RELATIONS] == [
        "refers_to",
        "cites",
        "defines",
        "part_of",
        "member_of",
        "party_to",
        "supersedes",
        "amends",
        "located_in",
        "attributed_to",
        "depends_on",
        "co_occurs_with",
        "related_to",
    ]
    assert set(rows) == {relation for relation, _, _ in BUILTIN_RELATIONS}
    assert rows["cites"][1] == "source is the CITING entity; target is the CITED entity."
    assert {r for r, (symmetric, _, _) in rows.items() if symmetric} == {
        "co_occurs_with",
        "related_to",
    }
    assert {source for _, _, source in rows.values()} == {"builtin"}


@pytest.mark.parametrize("relation", [relation for relation, _, _ in BUILTIN_RELATIONS])
def test_every_actor_rule_is_a_fixed_point_of_sanitize_label_under_the_ceiling(
    relation: str,
) -> None:
    """06:320: *"at most 200 characters and passes `sanitize_label()`"*: it goes into a prompt."""
    (rule,) = [rule for name, _, rule in BUILTIN_RELATIONS if name == relation]
    assert 0 < len(rule) <= SANITIZE_MAX
    assert sanitize_label(rule) == rule


def test_a_missing_builtin_relation_returns_and_an_operators_wording_survives(
    tmp_path: Path,
) -> None:
    """The seed runs on every `apply_pending` and only fills gaps (D667's rule, D672's table)."""
    conn = ow.connect(tmp_path / "index.owstore")
    try:
        migrate.apply_pending(conn, now_ns=NOW_NS)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM relation_vocab WHERE relation = 'amends'")
        conn.execute(
            "UPDATE relation_vocab SET actor_rule = 'source amends target', source = 'user' "
            "WHERE relation = 'supersedes'"
        )
        conn.execute("COMMIT")
        assert migrate.apply_pending(conn, now_ns=NOW_NS) == ()
        rows = dict(conn.execute("SELECT relation, actor_rule FROM relation_vocab").fetchall())
        assert len(rows) == len(BUILTIN_RELATIONS)
        assert rows["amends"] == {r: a for r, _, a in BUILTIN_RELATIONS}["amends"]
        assert rows["supersedes"] == "source amends target"
    finally:
        conn.close()
