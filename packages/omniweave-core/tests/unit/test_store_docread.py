"""`store.docread.StoreDocReader`: `Doc` over a real `.owstore`. D864.

Every test writes its document through `DocSink`, L2's only writer, using `test_store_doc.py`'s
two-page happy path (a heading with two marks, a paragraph, a table crossing the page break, one
`heading_of` rel), and reads it back through `model.doc.Doc`. The expected value is always read
some other way: `portable.read_block()`, `store.doc.read_grid()`, `read_doc_record()`, or SQL.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.errors import NotFoundError, StoreError, UsageError
from omniweave_core.model.block import Addr, BlockId, Cite
from omniweave_core.model.doc import Doc
from omniweave_core.model.enums import Kind, Layer, RelKind, TableKind, Trust
from omniweave_core.model.serialize import TableFacts, ViewScope, serialize
from omniweave_core.store import docread
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import read_doc_record, read_grid
from omniweave_core.store.docread import StoreDocReader
from omniweave_core.store.portable import BlockDecoder, read_block

if TYPE_CHECKING:
    import sqlite3  # noqa: TID251 -- an annotation only
    from collections.abc import Iterator


def _load_store_doc() -> Any:
    path = Path(__file__).with_name("test_store_doc.py")
    spec = importlib.util.spec_from_file_location("_test_store_doc_for_docread", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_sd = _load_store_doc()
harness = _sd.harness


@pytest.fixture
def written(harness: Any) -> Iterator[tuple[Any, sqlite3.Connection]]:
    """The happy path's document, a second document beside it, and a connection to the file."""
    first = _sd.write_happy_path(harness, key=1)
    _sd.write_happy_path(harness, key=2)
    connection = ow.connect(harness.path)
    try:
        yield first, connection
    finally:
        connection.close()


def _doc(written: tuple[Any, sqlite3.Connection]) -> Doc:
    first, connection = written
    return Doc(StoreDocReader(connection), first.record.doc_ord, first.record.gen)


def _ids(connection: sqlite3.Connection, where: str, params: tuple[Any, ...]) -> list[int]:
    return [
        int(row[0])
        for row in connection.execute(
            f"SELECT block_id FROM block WHERE state = 0 AND {where} ORDER BY page, ord, addr",  # noqa: S608
            params,
        )
    ]


def test_the_record_is_the_doc_row_and_only_at_the_head_generation(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    assert doc.rec == read_doc_record(connection, first.record.doc_ord)
    assert doc.declared == doc.rec.declared
    assert doc.achieved == doc.rec.achieved
    with pytest.raises(NotFoundError, match="generation"):
        _ = Doc(StoreDocReader(connection), first.record.doc_ord, first.record.gen + 1).rec
    with pytest.raises(NotFoundError, match="no document d999"):
        _ = Doc(StoreDocReader(connection), 999, 1).rec


def test_one_block_by_id_addr_and_cite_is_read_blocks_own_decode(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    for block_id in (first.root, first.heading, first.paragraph, first.table, *first.cells):
        expected = read_block(connection, int(block_id))
        assert expected is not None
        assert doc.block(block_id) == expected
        assert doc.by_addr(expected.addr) == expected
        assert doc.by_cite(expected.cite) == expected
    heading = doc.block(first.heading)
    assert [mark.kind for mark in heading.marks] == ["anchor", "bold"]


def test_a_miss_is_none_and_another_documents_block_is_a_miss(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    other = [
        int(row[0])
        for row in connection.execute(
            "SELECT block_id FROM block WHERE doc_ord <> ?", (first.record.doc_ord,)
        )
    ]
    assert other
    assert doc.by_addr(Addr("p99/1")) is None
    assert doc.by_cite(Cite("d999#1")) is None
    with pytest.raises(NotFoundError, match="no block"):
        doc.block(BlockId(other[0]))
    assert doc.by_cite(read_block(connection, other[0]).cite) is None  # type: ignore[union-attr]


def test_a_retired_block_is_a_miss(written: Any) -> None:
    first, connection = written
    connection.execute("UPDATE block SET state = 1 WHERE block_id = ?", (int(first.paragraph),))
    doc = _doc(written)
    assert doc.by_cite(read_block(connection, int(first.paragraph)).cite) is None  # type: ignore[union-attr]
    assert int(first.paragraph) not in [int(block.id) for block in doc.blocks()]


def test_blocks_is_every_live_body_block_in_page_ord_addr_order(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    got = list(doc.blocks())
    assert [int(block.id) for block in got] == _ids(
        connection, "doc_ord = ? AND gen = ?", (first.record.doc_ord, first.record.gen)
    )
    assert got == [read_block(connection, int(block.id)) for block in got]


def test_each_filter_narrows_as_its_sql_does(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    key = (first.record.doc_ord, first.record.gen)
    cell = BlockDecoder(connection).ordinal("kind", Kind.TABLE_CELL.value)

    def ids(**kw: Any) -> list[int]:
        return [int(block.id) for block in doc.blocks(**kw)]

    assert ids(pages=range(1, 2)) == _ids(connection, "doc_ord = ? AND gen = ? AND page = 1", key)
    assert ids(pages=range(0, 1)) == _ids(connection, "doc_ord = ? AND gen = ? AND page = 0", key)
    assert ids(kinds=[Kind.TABLE_CELL]) == _ids(
        connection, "doc_ord = ? AND gen = ? AND kind = ?", (*key, cell)
    )
    assert ids(kinds=[Kind.TABLE_CELL]) == [int(block) for block in first.cells]
    assert ids(kinds=[]) == []
    assert ids(layers=[Layer.FURNITURE]) == []
    assert ids(trust_below=Trust.EXTRACTED) == _ids(
        connection, "doc_ord = ? AND gen = ? AND trust < 2", key
    )
    assert ids(trust_below=Trust.AMBIGUOUS) == []


def test_under_is_the_subtree_rooted_at_the_block(written: Any) -> None:
    first, _connection = written
    doc = _doc(written)
    assert sorted(int(block.id) for block in doc.blocks(under=first.table)) == sorted(
        [int(first.table), *(int(cell) for cell in first.cells)]
    )
    assert [int(block.id) for block in doc.blocks(under=first.heading)] == [int(first.heading)]
    under_root = [int(block.id) for block in doc.blocks(under=first.root)]
    assert under_root == [int(block.id) for block in doc.blocks()]
    assert [int(b.id) for b in doc.blocks(under=first.table, pages=range(1, 2))] == [
        int(first.cells[2])
    ]


def test_marks_are_read_one_statement_per_window(
    written: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, connection = written
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    whole = list(_doc(written).blocks())
    monkeypatch.setattr(docread, "MARK_WINDOW", 2)
    statements.clear()
    windowed = list(_doc(written).blocks())
    assert windowed == whole
    marks = [sql for sql in statements if "FROM mark WHERE block_id IN" in sql]
    assert len(marks) == -(-len(whole) // 2)
    assert next(b for b in windowed if b.id == first.heading).marks


def test_the_cursor_reads_one_snapshot_and_keeps_a_callers_own(written: Any) -> None:
    _first, connection = written
    assert not connection.in_transaction
    cursor = _doc(written).blocks()
    next(cursor)
    assert connection.in_transaction
    list(cursor)
    assert not connection.in_transaction
    closed = _doc(written).blocks()
    next(closed)
    assert isinstance(closed, Generator)
    closed.close()
    assert not connection.in_transaction
    connection.execute("BEGIN DEFERRED")
    list(_doc(written).blocks())
    assert connection.in_transaction
    connection.execute("COMMIT")


def test_payload_is_the_column_and_a_missing_block_is_not_found(written: Any) -> None:
    first, _connection = written
    doc = _doc(written)
    assert dict(doc.payload(first.heading)) == {"level": 1}
    assert dict(doc.payload(first.root)) == {}
    with pytest.raises(NotFoundError, match="no live block"):
        doc.payload(BlockId(10**9))


def test_rels_read_both_directions_and_filter_by_kind(written: Any) -> None:
    first, _connection = written
    doc = _doc(written)
    [out] = doc.rels(first.heading)
    assert (out.src, out.dst, out.kind) == (first.heading, first.paragraph, RelKind.HEADING_OF)
    assert out.trust is Trust.INFERRED
    assert list(doc.rels(first.paragraph, inbound=True)) == [out]
    assert list(doc.rels(first.paragraph)) == []
    assert list(doc.rels(first.heading, RelKind.CAPTION_OF)) == []
    assert list(doc.rels(first.heading, RelKind.HEADING_OF)) == [out]


def test_grid_is_read_grids_from_the_table_or_a_cell(written: Any) -> None:
    first, connection = written
    doc = _doc(written)
    expected = read_grid(connection, int(first.table))
    assert expected is not None
    assert doc.grid(first.table) == expected[1]
    assert doc.grid(first.cells[2]) == expected[1]
    with pytest.raises(NotFoundError, match="neither a table"):
        doc.grid(first.paragraph)
    with pytest.raises(NotFoundError, match="no live block"):
        doc.grid(BlockId(10**9))


@pytest.mark.parametrize(
    ("call", "read"),
    [
        (lambda doc: doc.frames(), "frames()"),
        (lambda doc: doc.page_render(0, 72), "page_render()"),
        (lambda doc: doc.asset(object()), "asset()"),
        (lambda doc: doc.verify_quote(BlockId(1)), "verify_quote()"),
    ],
)
def test_the_four_unbuilt_reads_are_refused_by_name(written: Any, call: Any, read: str) -> None:
    with pytest.raises(UsageError, match=re.escape(f"Doc.{read} is not built")):
        call(_doc(written))


def test_a_member_the_store_does_not_name_is_refused(written: Any) -> None:
    _first, connection = written
    decoder = BlockDecoder(connection)
    with pytest.raises(StoreError, match="no kind member 'sonnet'"):
        decoder.ordinal("kind", "sonnet")
    with pytest.raises(StoreError, match="kind code 999"):
        decoder.member("kind", 999)


# --- resolve_scope: Doc.serialize()'s one read (ruling 7) -----------------------------------------


def _scope(written: Any, **kw: Any) -> ViewScope:
    first, connection = written
    return StoreDocReader(connection).resolve_scope(
        first.record.doc_ord, first.record.gen, pages=kw.get("pages"), under=kw.get("under")
    )


def test_the_scope_is_the_generation_in_pre_order(written: Any) -> None:
    first, _connection = written
    scope = _scope(written)
    assert [int(block.id) for block in scope.blocks] == [
        int(first.root),
        int(first.heading),
        int(first.table),
        *(int(cell) for cell in first.cells),
        int(first.paragraph),
    ]
    assert (scope.kind, scope.gen) == ("document", first.record.gen)


def test_the_scope_carries_every_satellite_serialize_reads(written: Any) -> None:
    first, connection = written
    scope = _scope(written)
    assert dict(scope.payload(first.heading)) == {"level": 1}
    assert first.root not in scope.payloads
    assert scope.table(first.table) == TableFacts(TableKind.DATA, header_rows=1, header_cols=0)
    assert [scope.cells[cell] for cell in first.cells] == list(_sd.POSITIONS)
    assert scope.continues == {}
    assert scope.heading_paths[first.paragraph] == ("Master Services Agreement",)
    assert first.heading not in scope.heading_paths
    assert first.root not in scope.heading_paths
    connection.execute("INSERT INTO meta(k, v) VALUES('corpus_id', 'handbook-7')")
    assert _scope(written).corpus_id == "handbook-7"


def test_a_continues_rel_reaches_the_scope(written: Any) -> None:
    first, connection = written
    code = BlockDecoder(connection).ordinal("rel_kind", RelKind.CONTINUES.value)
    connection.execute(
        "INSERT INTO rel(doc_ord, gen, src_id, dst_id, kind, producer_id, trust, origin_operator) "
        "SELECT doc_ord, gen, ?, ?, ?, producer_id, 2, 'parse.pdf' FROM block WHERE block_id = ?",
        (int(first.cells[1]), int(first.cells[2]), code, int(first.cells[1])),
    )
    assert _scope(written).continues == {first.cells[1]: first.cells[2]}


def test_a_page_range_and_a_subtree_are_their_blocks_in_pre_order(written: Any) -> None:
    first, _connection = written
    pages = _scope(written, pages=range(1, 2))
    assert [int(b.id) for b in pages.blocks] == [int(first.cells[2]), int(first.paragraph)]
    assert pages.kind == "pages"
    assert first.heading not in pages.payloads
    assert first.table not in pages.tables
    subtree = _scope(written, under=first.table)
    assert [int(b.id) for b in subtree.blocks] == [
        int(first.table),
        *(int(cell) for cell in first.cells),
    ]
    assert subtree.kind == "subtree"


def test_a_retired_block_leaves_the_scope(written: Any) -> None:
    first, connection = written
    connection.execute("UPDATE block SET state = 1 WHERE block_id = ?", (int(first.paragraph),))
    scope = _scope(written)
    assert int(first.paragraph) not in [int(block.id) for block in scope.blocks]
    assert first.paragraph not in scope.heading_paths


def test_serialize_renders_the_stored_document(written: Any) -> None:
    _first, connection = written
    text, spans = _doc(written).serialize("md")
    assert text == serialize(_scope(written), "md")[0]
    assert text.startswith("# **Master** Services Agreement\n")
    assert "| Region | FY2024 |" in text
    assert text.endswith("Fees are payable within 30 days.")
    assert spans.is_synthetic(0)
    assert not connection.in_transaction


def test_contextualize_prefixes_each_top_level_unit_with_its_heading_path(written: Any) -> None:
    text, _spans = _doc(written).serialize("md", pages=range(1, 2), contextualize=True)
    assert text.count("Master Services Agreement\n") == 2
    assert text.endswith("Master Services Agreement\nFees are payable within 30 days.")
