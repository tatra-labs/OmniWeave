"""`ow_open`'s resolver and packer over a REAL store: the five-form ladder, retired cites, context.

The store is migrated by the shipped migrations and seeded with SQL, as `test_retrieve_execute.py`
seeds one, and every read goes through `SqliteReader.resolve_refs()` on a read-only connection.

The tree seeded here is the smallest one that makes every rule move:
- a `section` container (`d1#1`, no text) holding five paragraphs, three on page 1 and two on 2;
- a page-1 footer on the `furniture` layer, and a `hidden` paragraph inside the section;
- `d1#9`, retired with a successor (`d1#3`), and `d1#10`, retired with none.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the fixtures seed a REAL store, as test_store_reader.py's do.
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from omniweave_core.answer import render
from omniweave_core.answer.pack import emitted, pack_open
from omniweave_core.answer.render import cites_of
from omniweave_core.model.enums import Layer
from omniweave_core.store import migrate, resolve
from omniweave_core.store import reader as rd
from omniweave_core.store import sqlite as ow

NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
BODY = frozenset({Layer.BODY})
PARAS = {
    2: (1, 1, "Clause one sets the term of the agreement."),
    3: (1, 2, "Clause two sets the fees, payable monthly in arrears."),
    4: (1, 3, "Clause three sets the notice period at thirty days."),
    5: (2, 4, "Clause four governs termination for convenience."),
    6: (2, 5, "Clause five governs the law and the venue."),
}


class Built(NamedTuple):
    path: Path
    writer: sqlite3.Connection


@pytest.fixture
def built(tmp_path: Path) -> Iterator[Built]:
    path = tmp_path / "index.owstore"
    writer = ow.connect(path)
    migrate.apply_pending(writer, now_ns=NOW_NS)
    _seed(writer)
    try:
        yield Built(path=path, writer=writer)
    finally:
        writer.close()


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _doc(conn: sqlite3.Connection, doc_ord: int, uri: str) -> None:
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, declared, "
        "                achieved) "
        "VALUES(?, ?, ?, ?, 'application/pdf', 'pdf', '{}', 1, 1, 'ok', '1.1', '{}', '{}')",
        (doc_ord, bytes([doc_ord]) * 16, DIGEST, uri),
    )
    for page in (1, 2):
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES(?, 1, ?, ?, ?, 1)",
            (doc_ord, page, _code(conn, "page_kind", "page"), _code(conn, "method", "native")),
        )


def _block(
    conn: sqlite3.Connection,
    block_id: int,
    *,
    page: int,
    ord_: int,
    kind: str,
    text: str | None,
    parent: int | None = 1,
    layer: str = "body",
    state: int = 0,
    addr: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind, layer, "
        "                  text, content_digest, os_kind, producer_id, method, trust, quote, "
        "                  origin_operator, origin_driver, driver_schema_v, restriction_bits, "
        "                  state) "
        "VALUES(?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 2, 4, 'op.parse', 'drv', 1, 0, ?)",
        (
            block_id,
            page,
            addr or f"p{page}/{block_id}",
            f"d1#{block_id}",
            parent,
            ord_,
            _code(conn, "kind", kind),
            _code(conn, "layer", layer),
            text,
            DIGEST,
            _code(conn, "origin_span_kind", "none"),
            _code(conn, "method", "native"),
            state,
        ),
    )


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    _doc(conn, 1, "file:///corpus/contract.pdf")
    _block(conn, 1, page=1, ord_=1, kind="section", text=None, parent=None, addr="p1/1")
    for block_id, (page, order, text) in PARAS.items():
        _block(conn, block_id, page=page, ord_=order, kind="paragraph", text=text)
    _block(
        conn, 7, page=1, ord_=9, kind="page_footer", text="Page 1", parent=None, layer="furniture"
    )
    _block(conn, 8, page=2, ord_=6, kind="paragraph", text="Hidden drafting note.", layer="hidden")
    _block(conn, 9, page=1, ord_=7, kind="paragraph", text="old clause", state=1)
    _block(conn, 10, page=1, ord_=8, kind="paragraph", text="deleted clause", state=1)
    conn.execute(
        "INSERT INTO block_history(block_id, doc_ord, retired_gen, superseded_by, reason) "
        "VALUES (9, 1, 1, 3, 'reparse_resegmented'), (10, 1, 1, NULL, 'source_deleted')"
    )
    conn.execute(
        "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
        "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
        (NOW_NS,),
    )
    conn.execute("COMMIT")


def _reader(built: Built) -> rd.SqliteReader:
    return rd.SqliteReader(ow.connect_readonly(built.path), now_ns=NOW_NS)


def _open(
    built: Built, *refs: str, context: int = 0, layers: frozenset[Layer] = BODY
) -> tuple[resolve.Located | resolve.Missed, ...]:
    reader = _reader(built)
    with reader.snapshot() as s:
        return reader.resolve_refs(s, refs, context=context, layers=layers)


def _one(built: Built, ref: str, **kw: object) -> resolve.Located | resolve.Missed:
    (found,) = _open(built, ref, **kw)  # type: ignore[arg-type]
    return found


def _ids(found: resolve.Located | resolve.Missed) -> tuple[int, ...]:
    assert isinstance(found, resolve.Located), found
    return found.block_ids


def _document(built: Built, *refs: str, **kw: object) -> str:
    opening = resolve.fetch(_reader(built), refs, context=0, layers=BODY)
    packed = pack_open(opening, corpus="handbook", **kw)  # type: ignore[arg-type]
    return render(packed.answer, max_chars=packed.max_chars)


# ---------------------------------------------------------------------------------------------
# parsing: every form a string parses as, in ladder order
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "forms"),
    [
        ("d7#412", ("cite", "document")),
        ("handbook:d7#412", ("cite", "document")),
        ("e118", ("entity", "document")),
        ("policy.pdf#p14/3", ("addr", "document")),
        ("policy.pdf#p12-18", ("pages", "document")),
        ("policy.pdf#p14", ("pages", "document")),
        ("policy.pdf", ("document",)),
    ],
)
def test_a_ref_parses_as_every_form_it_could_be_in_ladder_order(
    ref: str, forms: tuple[str, ...]
) -> None:
    """10:439: *"first form that resolves in the store winning"* -- so a cite that does not resolve
    must still be tried as the last form, and the refusal names both."""
    assert tuple(parsed.form for parsed in resolve.parse(ref)) == forms


def test_the_corpus_prefix_is_taken_off_a_qualified_cite() -> None:
    (cite, _) = resolve.parse("handbook:d7#412")
    assert (cite.corpus, cite.cite) == ("handbook", "d7#412")


def test_an_empty_ref_parses_as_nothing_and_is_ow_a_016(built: Built) -> None:
    found = _one(built, "   ")
    assert isinstance(found, resolve.Missed)
    assert found.error.numeric() == "OW-A-016"
    for example in resolve.EXAMPLES.values():
        assert example in str(found.error), "10:452 lists the five forms with one example each"


# ---------------------------------------------------------------------------------------------
# the five forms against the store
# ---------------------------------------------------------------------------------------------


def test_a_live_cite_resolves_to_its_one_block(built: Built) -> None:
    assert _ids(_one(built, "d1#4")) == (4,)


def test_a_retired_cite_is_followed_to_its_successor_and_says_so(built: Built) -> None:
    """03:1159: *"A retired cite still resolves ... and says so in the response."*"""
    found = _one(built, "d1#9")
    assert _ids(found) == (3,)
    assert isinstance(found, resolve.Located)
    assert "retired at generation 1 (reparse_resegmented)" in found.superseded
    assert "d1#3" in found.superseded


def test_a_retired_cite_with_no_successor_is_ow_m_030_and_never_a_neighbour(built: Built) -> None:
    """03:1161: *"never a silent miss and never a nearby block"*."""
    found = _one(built, "d1#10")
    assert isinstance(found, resolve.Missed)
    assert found.error.numeric() == "OW-M-030"
    assert "source_deleted" in str(found.error)


def test_an_addr_resolves_against_the_named_documents_head(built: Built) -> None:
    assert _ids(_one(built, "contract.pdf#p1/4")) == (4,)
    assert _ids(_one(built, "file:///corpus/contract.pdf#p1/4")) == (4,)


def test_an_addr_the_head_does_not_hold_is_ow_m_032(built: Built) -> None:
    found = _one(built, "contract.pdf#p1/99")
    assert isinstance(found, resolve.Missed)
    assert found.error.numeric() == "OW-M-032"


def test_a_page_range_is_its_text_blocks_in_page_and_ord_order(built: Built) -> None:
    """Containers carry no text and do not come back; the footer is furniture and does not."""
    assert _ids(_one(built, "contract.pdf#p1-2")) == (2, 3, 4, 5, 6)
    assert _ids(_one(built, "contract.pdf#p2")) == (5, 6), "D539: `#p<n>` is a one-page range"


def test_a_whole_document_is_every_text_block_in_the_requested_layers(built: Built) -> None:
    assert _ids(_one(built, "contract.pdf")) == (2, 3, 4, 5, 6)
    both = frozenset({Layer.BODY, Layer.FURNITURE})
    assert _ids(_one(built, "contract.pdf", layers=both)) == (2, 3, 4, 7, 5, 6)


def test_the_hidden_layer_is_reached_only_by_naming_it(built: Built) -> None:
    """10:471: `layers` is *"the **only** path to `Layer.HIDDEN`"*."""
    refused = _one(built, "d1#8")
    assert isinstance(refused, resolve.Missed)
    assert 'layers=["hidden"]' in refused.error.fix
    assert _ids(_one(built, "d1#8", layers=frozenset({Layer.HIDDEN}))) == (8,)
    assert 8 not in _ids(_one(built, "contract.pdf"))


def test_an_addressed_block_on_another_visible_layer_is_returned(built: Built) -> None:
    assert _ids(_one(built, "d1#7")) == (7,)


def test_a_file_name_two_documents_share_is_refused_listing_both(built: Built) -> None:
    """D537: a bare name is resolved only when exactly one document has it."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    _doc(conn, 2, "file:///archive/contract.pdf")
    conn.execute("COMMIT")
    found = _one(built, "contract.pdf#p1-2")
    assert isinstance(found, resolve.Missed)
    assert "file:///corpus/contract.pdf" in str(found.error)
    assert "file:///archive/contract.pdf" in str(found.error)
    assert _ids(_one(built, "file:///corpus/contract.pdf#p1-2")) == (2, 3, 4, 5, 6)


def test_an_entity_ref_is_refused_by_name_rather_than_read_as_a_uri(built: Built) -> None:
    found = _one(built, "e118")
    assert isinstance(found, resolve.Missed)
    assert "entity" in str(found.error)


def test_a_ref_that_parses_and_resolves_nowhere_names_its_forms(built: Built) -> None:
    found = _one(built, "nothing-like-it.pdf")
    assert isinstance(found, resolve.Missed)
    assert found.forms == ("document",)
    assert "document" in str(found.error)


# ---------------------------------------------------------------------------------------------
# context: +-K siblings, same parent, same layer
# ---------------------------------------------------------------------------------------------


def test_context_is_k_siblings_either_side_under_the_same_parent(built: Built) -> None:
    found = _one(built, "d1#4", context=1)
    assert _ids(found) == (3, 4, 5)
    assert isinstance(found, resolve.Located)
    assert found.context_ids == frozenset({3, 5})


def test_context_never_crosses_into_another_layer(built: Built) -> None:
    """Block 8 is a sibling of 6 on the hidden layer, and block 7 has no parent at all."""
    assert _ids(_one(built, "d1#6", context=8)) == (2, 3, 4, 5, 6)
    assert _ids(_one(built, "d1#7", context=8)) == (7,)


# ---------------------------------------------------------------------------------------------
# pack_open: request order, reading order, and nothing cut silently
# ---------------------------------------------------------------------------------------------


def test_an_opened_block_renders_on_the_open_surface_with_its_provenance(built: Built) -> None:
    document = _document(built, "d1#4")
    assert document.startswith("ow/1 ok corpus=handbook@0 fresh blocks=1/1")
    assert PARAS[4][2] in document
    assert "resolved           = 1 of 1 refs" in document
    assert "**ow:related**" not in document


def test_refs_pack_in_the_order_they_were_asked_for(built: Built) -> None:
    assert cites_of(_document(built, "d1#6", "d1#2")) == ("d1#6", "d1#2")


def test_a_retired_cite_says_so_in_blocking_beside_its_successor(built: Built) -> None:
    document = _document(built, "d1#9")
    assert "> d1#9 was retired at generation 1" in document
    assert cites_of(document) == ("d1#3",)


def test_a_miss_in_a_batch_is_a_blocking_line_and_the_rest_still_answer(built: Built) -> None:
    document = _document(built, "d1#2", "d1#10")
    assert document.startswith("ow/1 degraded ")
    assert "[OW-M-030]" in document
    assert cites_of(document) == ("d1#2",)
    assert "resolved           = 1 of 2 refs" in document


def _lengthen(built: Built) -> None:
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE block SET text = text || ? WHERE block_id IN (2,3,4,5,6)", (" x" * 300,))
    conn.execute("COMMIT")


def test_a_document_over_the_envelope_names_what_it_cut_in_a_section_never_dropped(
    built: Built,
) -> None:
    """10:459: *"It never truncates mid-document silently."* At the 1,000-character floor
    `ow:notseen` itself does not survive (D546), so the trailer carries `OW-A-010` and the fetch."""
    _lengthen(built)
    document = _document(built, "contract.pdf", max_chars=1_000)
    assert 1 <= len(cites_of(document)) < 5
    trailer = document.split("**ow:trailer**", 1)[1]
    assert "OW-A-010 OW_RESPONSE_TRUNCATED" in trailer
    assert '`ow_open ref="contract.pdf#p' in trailer


def test_with_room_every_cut_block_is_named_by_an_ow_notseen_row(built: Built) -> None:
    _lengthen(built)
    document = _document(built, "contract.pdf", max_chars=2_500)
    shown = cites_of(document)
    assert 1 <= len(shown) < 5
    notseen = document.split("**ow:notseen**", 1)[1].split("**ow:trailer**", 1)[0]
    assert "not shown: the budget ran out first." in notseen
    for block_id in (2, 3, 4, 5, 6):
        cite = f"d1#{block_id}"
        assert (cite in shown) != (cite in notseen), cite


def test_what_an_opened_answer_records_is_what_it_rendered(built: Built) -> None:
    opening = resolve.fetch(_reader(built), ("contract.pdf",), context=0, layers=BODY)
    packed = pack_open(opening, corpus="handbook")
    document = render(packed.answer, max_chars=packed.max_chars)
    assert [e.cite for e in emitted(packed, document)] == ["d1#2", "d1#3", "d1#4", "d1#5", "d1#6"]
