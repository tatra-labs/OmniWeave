"""`tools/p2_stub_parse.py` -- the P2 stub `parse/1` driver, proved against bytes it was not told.

16-roadmap.md:442 asks for *"a stub `parse/1` driver"* to carry the P2 demo, and the word "stub"
is a licence to assume ONE grammar. It is not a licence to be handed the answer. So this file
builds a PDF to that frozen grammar **here**, independently of both the driver and
`fixtures/gen/gen_5000p_pdf.py`, and then asserts that the driver recovers from the bytes alone
what the builder put in.

THE ASSERTION THAT MATTERS MOST, and why it is written the way it is.
`data[byte_start : byte_start + byte_len] == <the literal as written>` is checked for the first
run, the last run, and a run that needed escaping. A driver that returned plausible offsets --
into the decoded stream rather than the file, or off by the opening parenthesis -- would satisfy
every count and every text comparison in this file and fail only that one. The offsets are the
whole reason a text Block can carry a real `OriginBytes`, which is what lets `ow store verify`
re-derive content from stored bytes (16-roadmap.md:435), so they are checked against the file
that was actually written and not against the driver's own arithmetic.

THE SECOND ONE IS THE QUOTE LADDER. Every block kind's `Quote` is pinned to a literal here, with
the reason beside it, because 03 section 8.5's ladder exists exactly to stop a driver claiming
that text it ASSEMBLED is quotable. A coalesced paragraph is not byte-equal to any single source
range, and `test_a_coalesced_paragraph_is_normalized_because_its_span_is_not_its_text` proves the
inequality rather than asserting the label.

THE THIRD IS THE CARD, AND IT DOES NOT PROVE ITSELF. `doc.achieved` is computed by the host from
the committed rows and never reported by the driver (INV-7 at the capability grain, 03:534-536),
so `achieved == STUB_CAPABILITIES` catches an over-declaration of any field a committed row
witnesses -- thirteen of the fifteen, measured field by field. It catches NEITHER `reading_order`
NOR `round_trip`: no row witnesses either, so `achieved` hands the declaration straight back and
that equality holds against any value at all. All fifteen are therefore pinned to literals in
`test_the_fifteen_capability_fields_are_pinned_here_and_not_read_off_the_card`, because an
equality whose two sides come out of the same store pins agreement and not value. `forfeits` is
`{spatial, round_trip}` and not empty: those are the two absences `_forfeited` derives from a
generation with no `quad` and no round trip, and 03:1575 wants them said out loud. An
over-declared field is worse than an under-declared one because a floor is a filter and never a
ranking key (16-roadmap.md:481).

ON THE INLINE BUILDER. `fixtures/gen/gen_5000p_pdf.py` is built by another agent against the same
frozen contract and may not exist. `_build_pdf` below is a second, independent writer of that
grammar, which is the arrangement the parser deserves: a driver tested only against the generator
that fed it is testing an agreement, not a format. When the generator IS present,
`test_the_driver_reads_the_shipped_generators_own_output` runs the same parse over its bytes, so
the two implementations are cross-checked rather than merely coexisting.

Specified by 16-roadmap.md:434-445, 03-document-model.md sections 2.9, 2.10, 6.2, 7.2 and 8.5,
and 07-store-and-retrieval.md:1005-1030.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import json
import sqlite3  # noqa: TID251 -- this file reads the rows the sink wrote, as the store tests do.
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.model import Capabilities, Kind, Method, PageKind, Quote, Trust
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink

NOW_NS = 1_757_400_000_000_000_000
"""A fixed timestamp. `time.time()` is banned in library code and injected everywhere in the
store, so a test reading the ambient clock would assert against a value production cannot make."""


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "p2_stub_parse.py"
GENERATOR_PATH = REPO_ROOT / "fixtures" / "gen" / "gen_5000p_pdf.py"


def _load(name: str, path: Path) -> ModuleType:
    """Load a `tools/` or `fixtures/` script by path.

    The same mechanism `test_gate_crash.py` uses and for the same reasons: not
    `importlib.import_module`, which is banned outside `host/`, and not a `sys.path` mutation,
    which would leak into every later test in the session.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is in this repository.
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stub = _load("omniweave_p2_stub_parse", TOOL_PATH)


# ---------------------------------------------------------------------------------------------
# The fixture grammar, written here so the parser is not tested against its own assumptions
# ---------------------------------------------------------------------------------------------

PAGE_W_PT = 595.276
PAGE_H_PT = 841.890
HEADING_SIZE_PT = 18.0
BODY_SIZE_PT = 10.0
CELL_SIZE_PT = 8.0
LEADING_PT = 12.0
PARAGRAPHS_PER_PAGE = 8
LINES_PER_PARAGRAPH = 4
TABLE_ROWS = 9
TABLE_COLS = 6
RUNS_PER_PAGE = 1 + PARAGRAPHS_PER_PAGE * LINES_PER_PARAGRAPH + TABLE_ROWS * TABLE_COLS

HEADING_Y = 800.0
PARAGRAPH_TOP_Y = 760.0
PARAGRAPH_PITCH = LINES_PER_PARAGRAPH * LEADING_PT + 18.0
"""Strictly greater than the leading, which is the ONLY signal the coalescer has for a boundary."""

TABLE_TOP_Y = 230.0
TABLE_ROW_PITCH = 20.0
"""Also strictly greater than the leading, so a table row can never merge into a paragraph."""

TABLE_LEFT_X = 60.0
TABLE_COL_PITCH = 80.0
BODY_LINE_CHARS = 75

ESCAPED_BODY = r"a run with parens (like this) and a backslash \ in it, sixty-nine chars"
"""One body literal that must be escaped in the file. It lands in paragraph 0 of page 1."""

ESCAPED_CELL = r"(x)\y"
"""One CELL literal that must be escaped. A cell is a single uncoalesced run, so it is the case
that separates "needed unescaping" from "was coalesced" in the `Quote` ladder."""

ESCAPED_CELL_RAW = rb"\(x\)\\y"
"""Exactly what the file holds for that cell: eight bytes for five characters."""


def _num(value: float) -> str:
    """A PDF number: no exponent, no trailing zeros, ASCII."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _escape(text: str) -> str:
    """Backslash, then the two parentheses. The three escapes the grammar permits, in order."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _body_text(page: int, paragraph: int, line: int) -> str:
    if page == 1 and paragraph == 0 and line == 0:
        return ESCAPED_BODY
    stem = f"p{page} par{paragraph} line{line} "
    filler = "omniweave deterministic prose sample for the P2 bytes-per-block measurement"
    return (stem + filler)[:BODY_LINE_CHARS]


def _cell_text(page: int, row: int, column: int) -> str:
    if page == 1 and row == 0 and column == 0:
        return ESCAPED_CELL
    return f"r{row}c{column}p{page}"


def _content(page: int) -> bytes:
    """One page's content stream, in the emission order the contract fixes.

    Heading, then `PARAGRAPHS_PER_PAGE` paragraphs of `LINES_PER_PARAGRAPH` runs each with `y`
    falling by exactly `LEADING_PT` inside a paragraph and by more between them, then the table's
    cells row-major on a grid whose row pitch is also greater than the leading.
    """
    lines = ["BT", f"/F1 {_num(HEADING_SIZE_PT)} Tf"]
    lines.append(f"1 0 0 1 {_num(72.0)} {_num(HEADING_Y)} Tm")
    lines.append(f"({_escape(f'Heading of page {page}')}) Tj")
    lines.append(f"/F1 {_num(BODY_SIZE_PT)} Tf")
    for paragraph in range(PARAGRAPHS_PER_PAGE):
        top = PARAGRAPH_TOP_Y - paragraph * PARAGRAPH_PITCH
        for line in range(LINES_PER_PARAGRAPH):
            y = top - line * LEADING_PT
            lines.append(f"1 0 0 1 {_num(72.0)} {_num(y)} Tm")
            lines.append(f"({_escape(_body_text(page, paragraph, line))}) Tj")
    lines.append(f"/F1 {_num(CELL_SIZE_PT)} Tf")
    for row in range(TABLE_ROWS):
        y = TABLE_TOP_Y - row * TABLE_ROW_PITCH
        for column in range(TABLE_COLS):
            x = TABLE_LEFT_X + column * TABLE_COL_PITCH
            lines.append(f"1 0 0 1 {_num(x)} {_num(y)} Tm")
            lines.append(f"({_escape(_cell_text(page, row, column))}) Tj")
    lines.append("ET")
    return ("\n".join(lines) + "\n").encode("ascii")


def _build_pdf(pages: int = 2, *, filtered: bool = False) -> bytes:
    """A whole PDF: header, uncompressed objects, a classic xref TABLE, trailer, `%%EOF`.

    `filtered` writes a `/Filter` the bytes do not honour, which is only useful because the whole
    file is rebuilt around it: a `/Filter` spliced into finished bytes would shift every xref
    offset, and the parser would then fail on the cross-reference table instead of on the thing
    the test is about.
    """
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: b"<< /CreationDate (D:19800101000000Z) /ModDate (D:19800101000000Z) >>",
    }
    kids: list[int] = []
    for index in range(pages):
        content_num = 5 + 2 * index
        page_num = content_num + 1
        kids.append(page_num)
        stream = _content(index + 1)
        head = b"<< /Filter /FlateDecode /Length %d >>" if filtered else b"<< /Length %d >>"
        objects[content_num] = head % len(stream) + b"\nstream\n" + stream + b"endstream"
        objects[page_num] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (
                _num(PAGE_W_PT).encode("ascii"),
                _num(PAGE_H_PT).encode("ascii"),
                content_num,
            )
        )
    kid_refs = b" ".join(b"%d 0 R" % num for num in kids)
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kid_refs, pages)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
    xref_at = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n" % size
    out += b"0000000000 65535 f \n"
    for num in range(1, size):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 4 0 R >>\n" % size
    out += b"startxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


PDF = _build_pdf()
PAGES = stub.parse_pdf(PDF)


# ---------------------------------------------------------------------------------------------
# 1. It parses. From the bytes, and from nothing else.
# ---------------------------------------------------------------------------------------------


def test_the_page_tree_and_the_page_box_come_out_of_the_cross_reference_table() -> None:
    """`startxref` -> `xref` -> `/Root` -> `/Pages` -> `/Kids`, with `/MediaBox` inherited or not.

    Nothing here is told how many pages the file holds; the count is what the walk found.
    """
    assert len(PAGES) == 2
    assert [page.page for page in PAGES] == [1, 2], "pages are numbered 1-based by the driver"
    for page in PAGES:
        assert page.w_pt == pytest.approx(PAGE_W_PT)
        assert page.h_pt == pytest.approx(PAGE_H_PT)


def test_a_page_holds_one_heading_thirty_two_prose_runs_and_fifty_four_cells() -> None:
    """1 + 32 + 54 = 87, and the arithmetic is asserted per class rather than as one total.

    A total alone passes when a heading is miscounted as prose, which is the exact confusion that
    moves the prose/cell mix 07:1012 makes bytes-per-block depend on.
    """
    for page in PAGES:
        assert len(page.runs) == RUNS_PER_PAGE == 87
        sizes = [run.size_pt for run in page.runs]
        assert sizes.count(HEADING_SIZE_PT) == 1
        assert sizes.count(BODY_SIZE_PT) == PARAGRAPHS_PER_PAGE * LINES_PER_PARAGRAPH == 32
        assert sizes.count(CELL_SIZE_PT) == TABLE_ROWS * TABLE_COLS == 54
        assert page.runs[0].size_pt == HEADING_SIZE_PT, "the heading is emitted first"


def test_the_runs_come_back_in_content_stream_order_with_the_positions_tm_set() -> None:
    """`Tm` is ABSOLUTE (there is no `Td` and no `TL`), so a driver that accumulated would drift."""
    page = PAGES[0]
    assert page.runs[0].y_pt == pytest.approx(HEADING_Y)
    first_paragraph = page.runs[1 : 1 + LINES_PER_PARAGRAPH]
    for index, run in enumerate(first_paragraph):
        assert run.y_pt == pytest.approx(PARAGRAPH_TOP_Y - index * LEADING_PT)
        assert run.x_pt == pytest.approx(72.0)
    second_paragraph_first = page.runs[1 + LINES_PER_PARAGRAPH]
    gap = first_paragraph[-1].y_pt - second_paragraph_first.y_pt
    assert gap > LEADING_PT, "the paragraph boundary is a gap LARGER than the leading, or nothing"


def test_the_driver_never_reads_the_generator() -> None:
    """A stub may assume a grammar. It may not import the thing that wrote the file.

    An `ast` walk over the IMPORT STATEMENTS and not a substring scan, for the reason this
    project keeps relearning: the driver's docstring cites `fixtures/gen/gen_5000p_pdf.py` by
    name because 16-roadmap.md:442 does, and a naive grep counts that citation as a dependency.
    A docstring is not a definition site.
    """
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    assert imported, "the ast walk found no imports at all, so it is not reading the file"
    for module in imported:
        assert "gen_5000p" not in module and "fixtures" not in module, (
            f"the driver imports {module!r}: a stub may assume a grammar, never learn the answer"
        )


# ---------------------------------------------------------------------------------------------
# 2. The offsets. The load-bearing part, checked against the file rather than against the driver
# ---------------------------------------------------------------------------------------------


def _written(text: str) -> bytes:
    """The literal AS WRITTEN in the file: escaped, ASCII."""
    return _escape(text).encode("ascii")


def test_every_sampled_runs_byte_range_slices_back_to_its_literal_as_written() -> None:
    """`data[start : start + length]` IS the literal's content, for first, last and escaped.

    This is the assertion the whole driver exists to support. `byte_start` is an offset into the
    FILE, so a slice taken by a third party holding only these bytes reproduces the literal --
    which is what makes `OriginBytes` re-derivable at `ow store verify` (16-roadmap.md:435).
    """
    first = PAGES[0].runs[0]
    last = PAGES[-1].runs[-1]
    escaped = next(run for run in PAGES[0].runs if run.text == ESCAPED_CELL)
    for run, expected in (
        (first, _written("Heading of page 1")),
        (last, _written(_cell_text(2, TABLE_ROWS - 1, TABLE_COLS - 1))),
        (escaped, ESCAPED_CELL_RAW),
    ):
        assert run.byte_len == len(expected)
        assert PDF[run.byte_start : run.byte_start + run.byte_len] == expected


def test_the_escaped_literal_is_unescaped_in_text_and_not_in_the_bytes() -> None:
    """The two halves of `TextRun` disagree here on purpose, and that disagreement IS the ladder.

    Without a run in the sample whose written form differs from its text, the offset assertion
    above would pass against a driver that returned `text.encode()` and a fabricated offset.
    """
    escaped = next(run for run in PAGES[0].runs if run.text == ESCAPED_CELL)
    assert escaped.text == ESCAPED_CELL
    assert escaped.byte_len == len(ESCAPED_CELL_RAW) > len(ESCAPED_CELL.encode("utf-8"))
    assert PDF[escaped.byte_start : escaped.byte_start + escaped.byte_len] != ESCAPED_CELL.encode()


def test_no_two_runs_of_a_document_share_a_byte_range() -> None:
    """Distinctness is the cheapest proof that the offsets are read and not derived from an index.

    A driver that returned, say, the stream start for every run would satisfy the text
    assertions, the counts and the ordering, and fail only here.
    """
    ranges = [(run.byte_start, run.byte_len) for page in PAGES for run in page.runs]
    assert len(set(ranges)) == len(ranges) == 2 * RUNS_PER_PAGE


# ---------------------------------------------------------------------------------------------
# 3. Refusals. A stub that guesses outside its grammar measures the wrong document
# ---------------------------------------------------------------------------------------------


def test_a_file_that_is_not_a_pdf_is_refused() -> None:
    with pytest.raises(stub.StubParseError, match="%PDF-"):
        stub.parse_pdf(b"not a pdf at all")


def test_a_filtered_content_stream_is_refused_rather_than_skipped() -> None:
    """A decoded stream has no file offsets to hand an `OriginBytes`, so it cannot be read here."""
    with pytest.raises(stub.StubParseError, match="Filter"):
        stub.parse_pdf(_build_pdf(1, filtered=True))


def test_a_literal_with_an_escape_outside_the_grammar_is_refused() -> None:
    r"""`\n` is legal PDF and outside this stub, and it says so instead of decoding it two ways."""
    poisoned = PDF.replace(rb"\(x\)\\y", rb"\(x\)\ny", 1)
    with pytest.raises(stub.StubParseError, match="backslash"):
        stub.parse_pdf(poisoned)


def test_a_run_at_an_unrecognised_size_is_refused_by_the_classifier() -> None:
    """Classifying an unknown size as prose would silently move the prose/cell mix (07:1012)."""
    poisoned = PDF.replace(b"/F1 18 Tf", b"/F1 17 Tf", 1)
    pages = stub.parse_pdf(poisoned)
    with pytest.raises(stub.StubParseError, match="17"):
        stub._classify(pages[0])


def test_a_startxref_that_points_at_no_xref_keyword_is_refused() -> None:
    """The cross-reference TABLE is the only entry point; a cross-reference STREAM is not."""
    poisoned = PDF.replace(b"\nxref\n", b"\nXREF\n", 1)
    with pytest.raises(stub.StubParseError, match="xref"):
        stub.parse_pdf(poisoned)


# ---------------------------------------------------------------------------------------------
# 4. Coalescing, and the Quote each kind therefore earns
# ---------------------------------------------------------------------------------------------


def test_a_paragraph_is_the_runs_whose_y_falls_by_exactly_the_leading() -> None:
    """The rule, in isolation: same size, `dy == LEADING_PT`. Any other gap ends the paragraph."""
    _heading, paragraphs, cells = stub._classify(PAGES[0])
    assert len(paragraphs) == PARAGRAPHS_PER_PAGE
    assert {len(group) for group in paragraphs} == {LINES_PER_PARAGRAPH}
    assert len(cells) == TABLE_ROWS * TABLE_COLS


def test_the_cell_grid_is_derived_from_geometry_and_not_from_a_constant() -> None:
    """`y` descending is the row, `x` ascending is the column. Nine by six, read off the page."""
    _heading, _paragraphs, cells = stub._classify(PAGES[0])
    positions = stub._cell_positions(cells)
    assert positions[0] == (0, 0)
    assert positions[-1] == (TABLE_ROWS - 1, TABLE_COLS - 1)
    assert len({row for row, _ in positions}) == TABLE_ROWS
    assert len({column for _, column in positions}) == TABLE_COLS
    assert sorted(positions) == list(positions), (
        "_cell_positions answers row-major because the runs arrive in content-stream order. That "
        "the cells then REACH add_block in that order is a different claim about _write_table, "
        "proved by test_the_cells_reach_add_block_in_row_major_order over the sibling ordinals"
    )


# ---------------------------------------------------------------------------------------------
# 5. The store. One real `.owstore`, driven through `DocSink` by `ingest`
# ---------------------------------------------------------------------------------------------


def _producer(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES(?, ?, 'p2stub', X'00')",
        (stub.OPERATOR, stub.OP_VERSION),
    )
    connection.commit()
    return int(cursor.lastrowid or 0)


@pytest.fixture
def ingested(tmp_path: Path) -> dict[str, Any]:
    """A migrated store with `_build_pdf()`'s two pages ingested through the stub driver."""
    pdf_path = tmp_path / "gen_2p.pdf"
    pdf_path.write_bytes(PDF)
    store = tmp_path / "index.owstore"
    cas = tmp_path / "cas"
    cas.mkdir()
    connection = ow.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        producer_id = _producer(connection)
    finally:
        connection.close()

    with ow.StoreThread(lambda: ow.connect(store)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator=stub.OPERATOR,
            origin_driver=stub.DRIVER_ID,
            driver_schema_v=stub.DRIVER_SCHEMA_V,
            blobs=BlobStore(cas),
        )
        record = stub.ingest(
            sink,
            pdf=pdf_path,
            uri=pdf_path.as_uri(),
            doc_ord=0,
            doc_key=bytes(range(16)),
        )
    return {"store": store, "record": record, "pdf": pdf_path}


def _rows(store: Path, sql: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    connection = ow.connect_readonly(store)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _quotes_by_kind(store: Path) -> dict[str, set[int]]:
    rows = _rows(
        store,
        "SELECT e.name, b.quote FROM block b JOIN enum_val e ON e.domain='kind' AND e.ord=b.kind",
    )
    out: dict[str, set[int]] = {}
    for kind, quote in rows:
        out.setdefault(str(kind), set()).add(int(quote))
    return out


def test_the_generation_commits_and_every_page_and_block_is_visible(
    ingested: dict[str, Any],
) -> None:
    """`end_doc` returns the post-commit record, so `gen` moving is the commit's own evidence."""
    record = ingested["record"]
    assert record.status == "ok"
    assert record.page_count == 2
    assert record.gen == 1, "gen 0 is reserved and means 'no committed generation' (03:82)"
    store = ingested["store"]
    assert _rows(store, "SELECT count(*) FROM page")[0][0] == 2
    # 1 document root + per page (1 page root + 1 heading + 8 paragraphs + 1 table + 54 cells).
    assert _rows(store, "SELECT count(*) FROM block")[0][0] == 1 + 2 * (1 + 1 + 8 + 1 + 54)


def test_the_pages_are_written_at_the_stores_own_zero_based_index(
    ingested: dict[str, Any],
) -> None:
    """`TextRun.page` is 1-based by the driver contract; `page.page` is 0-based by 03:277.

    The conversion happens exactly once, at `_page_record`, and this pins which side is which --
    an off-by-one here renumbers every `addr` in the document.
    """
    store = ingested["store"]
    assert [row[0] for row in _rows(store, "SELECT page FROM page ORDER BY page")] == [0, 1]
    addrs = [row[0] for row in _rows(store, "SELECT addr FROM block ORDER BY block_id")]
    assert addrs[0] == "doc", "03:816 -- the document root's addr is the literal `doc`"
    assert addrs[1] == "p0/0", "the first page root is page 0's ordinal 0"
    assert "p1/0" in addrs, "the second page root addresses page 1 and not page 2"
    assert "p0/0/9/r0c0" in addrs, "a cell's addr step is r<r>c<c> (03:1105)"
    assert "p0/0/9/r8c5" in addrs


def test_the_part_row_names_the_whole_file_and_its_digest(ingested: dict[str, Any]) -> None:
    """`add_part` runs BEFORE any block whose origin cites it, and there is exactly one part."""
    data = ingested["pdf"].read_bytes()
    rows = _rows(ingested["store"], "SELECT path, sha256, byte_len FROM part")
    assert len(rows) == 1
    path, digest, byte_len = rows[0]
    assert path == "file"
    assert bytes(digest) == hashlib.sha256(data).digest()
    assert byte_len == len(data)


def test_each_block_kind_carries_exactly_the_quote_it_earned(ingested: dict[str, Any]) -> None:
    """The ladder, pinned kind by kind, with the reason for each.

    * `document`, `container` and `table` are SYNTHETIC: this driver assembled them, they carry
      no text of their own, and a container quotes nothing (03 section 8.5).
    * a `heading` is one run whose literal needed no unescaping, so its span decodes to exactly
      its text -- VERBATIM, and it is the only kind here that is.
    * a `paragraph` is ALWAYS NORMALIZED: it coalesces four runs joined with a space, so it is
      byte-equal to no single source range.
    * a `table_cell` is VERBATIM unless its literal needed unescaping, which is why the fixture
      plants exactly one escaped cell -- both rungs of the same kind, in one document.
    """
    quotes = _quotes_by_kind(ingested["store"])
    assert quotes[Kind.DOCUMENT.value] == {int(Quote.SYNTHETIC)}
    assert quotes[Kind.CONTAINER.value] == {int(Quote.SYNTHETIC)}
    assert quotes[Kind.TABLE.value] == {int(Quote.SYNTHETIC)}
    assert quotes[Kind.HEADING.value] == {int(Quote.VERBATIM)}
    assert quotes[Kind.PARAGRAPH.value] == {int(Quote.NORMALIZED)}
    assert quotes[Kind.TABLE_CELL.value] == {int(Quote.VERBATIM), int(Quote.NORMALIZED)}

    escaped = _rows(
        ingested["store"],
        "SELECT quote FROM block WHERE kind = (SELECT ord FROM enum_val WHERE domain='kind' "
        "AND name='table_cell') AND text = ?",
        (ESCAPED_CELL,),
    )
    assert [row[0] for row in escaped] == [int(Quote.NORMALIZED)], (
        "the one cell whose literal needed unescaping must not claim VERBATIM: its recorded "
        "bytes do not decode to its text, which is the lie the ladder exists to prevent"
    )


def test_a_verbatim_blocks_origin_bytes_re_derive_its_text_from_the_file(
    ingested: dict[str, Any],
) -> None:
    """INV-10's `bytes` branch, run for real over every VERBATIM row.

    `nfc(part_bytes[os_a : os_a + os_b].decode(os_codec)) == block.text` (03:1470-1476). This is
    the clause `ow store verify` will run at P2's exit, evaluated here against the file on disk
    rather than against anything the sink remembered.

    THE CODEC IS PINNED TO A LITERAL, AND THE DECODE USES THE LITERAL. An earlier form of this
    test split `os_codec` out of the row and decoded with whatever it found there, which is both
    sides of one equality coming out of the same store: a driver recording `latin-1/strict` was
    then decoded as latin-1 and agreed with itself. Every byte this fixture addresses is ASCII,
    so that agreement held for every wrong codec in the Latin family and the test could not fail.
    `utf-8/strict` is the policy 03:1440 says the `bytes` branch READS, so the test states it.
    """
    data = ingested["pdf"].read_bytes()
    rows = _rows(
        ingested["store"],
        "SELECT text, os_a, os_b, os_codec FROM block WHERE quote = ? AND text IS NOT NULL",
        (int(Quote.VERBATIM),),
    )
    assert len(rows) > 100, f"only {len(rows)} VERBATIM rows; the sample is too thin to mean much"
    for text, start, length, codec in rows:
        assert codec == "utf-8/strict", f"os_codec is {codec!r}, not the policy this driver states"
        decoded = data[start : start + length].decode("utf-8", "strict")
        assert unicodedata.normalize("NFC", decoded) == text


def test_a_coalesced_paragraph_is_normalized_because_its_span_is_not_its_text(
    ingested: dict[str, Any],
) -> None:
    """The inequality itself, not the label.

    A paragraph's `OriginBytes` can only honestly cover the whole run region, which necessarily
    includes the `) Tj` and `Tm` operator bytes between its four runs. Decoding it therefore does
    NOT yield `block.text` -- and that is exactly why the quote is NORMALIZED and why
    `STUB_CAPABILITIES.origin_span` is `normalized` rather than `exact` (03:512).
    """
    data = ingested["pdf"].read_bytes()
    rows = _rows(
        ingested["store"],
        "SELECT text, os_a, os_b FROM block WHERE kind = "
        "(SELECT ord FROM enum_val WHERE domain='kind' AND name='paragraph') LIMIT 1",
    )
    text, start, length = rows[0]
    covered = data[start : start + length]
    assert covered.decode("utf-8") != text
    assert b") Tj" in covered, "the span covers the operator bytes between the coalesced runs"
    for word in text.split(" ")[:2]:
        assert word.encode("utf-8") in covered, "yet it does contain every run it coalesced"


def test_the_table_reaches_the_store_as_a_real_grid_with_fifty_four_cells(
    ingested: dict[str, Any],
) -> None:
    """`add_grid` wrote `table_meta` and `cell`; a merge-free grid writes no `grid_slot` row.

    The cells are not decoration: 07:1012-1020 makes bytes-per-block depend on the prose/cell mix
    (*"a prose paragraph is ~300 B; a table cell is ~10 B"*), so a fixture ingested without them
    measures a number the plan is not talking about.
    """
    store = ingested["store"]
    meta = _rows(store, "SELECT n_rows, n_cols, row_len, has_merges FROM table_meta")
    assert len(meta) == 2, "one table per page"
    for n_rows, n_cols, row_len, has_merges in meta:
        assert (n_rows, n_cols) == (TABLE_ROWS, TABLE_COLS)
        assert row_len == "[" + ",".join([str(TABLE_COLS)] * TABLE_ROWS) + "]"
        assert has_merges == 0
    assert _rows(store, "SELECT count(*) FROM cell")[0][0] == 2 * TABLE_ROWS * TABLE_COLS
    assert _rows(store, "SELECT count(*) FROM grid_slot")[0][0] == 0


def test_the_card_this_stub_declares_is_what_the_store_says_it_achieved(
    ingested: dict[str, Any],
) -> None:
    """`achieved` is computed by the HOST from the committed rows (INV-7, 03:534-536).

    So this equality separates a declaration from a wish for every field some committed row
    witnesses -- thirteen of the fifteen, established by over-declaring each in turn and watching
    which ones this assertion caught. `reading_order` and `round_trip` have no witness among the
    rows: `achieved` returns the declaration unchanged for those two, and this equality is silent
    about them. They are pinned by literal in
    `test_the_fifteen_capability_fields_are_pinned_here_and_not_read_off_the_card`.

    `forfeits` is the two absences `_forfeited` (03:528) derives from a generation with no `quad`
    and no round trip, stated on the card rather than discovered. A stub that over-declares is
    worse than one that under-declares, because a capability floor is a FILTER and never a
    ranking key (16-roadmap.md:481).
    """
    record = ingested["record"]
    assert record.declared == stub.STUB_CAPABILITIES
    assert record.achieved == stub.STUB_CAPABILITIES, (
        f"declared and achieved diverge: {record.achieved}"
    )
    assert record.achieved.forfeits == frozenset({"spatial", "round_trip"}), (
        "`_forfeited` (03:528) derives exactly these two from a generation with no `quad` and no "
        "round trip, so the card states them rather than being caught out by them"
    )


def test_the_document_records_the_raw_digest_and_no_normaliser(
    ingested: dict[str, Any],
) -> None:
    """05:261 -- NULL `normalizer` means the raw bytes were hashed, which is what happened.

    `pdf_trailer_v1` (05:264) belongs to an ingest stage that does not exist at P2, and naming it
    would claim a normalisation nothing performed.
    """
    record = ingested["record"]
    assert record.normalizer is None
    assert record.source_sha256 == hashlib.sha256(PDF).digest()
    assert record.source_bytes == len(PDF)
    assert record.format == "pdf"
    assert record.format_evidence["header"] == "%PDF-1.4"


def test_every_text_block_is_native_and_extracted_with_a_bytes_origin(
    ingested: dict[str, Any],
) -> None:
    """Method, Trust and `os_kind` on every row, because a single wrong ordinal is invisible.

    `Method.NATIVE` caps trust at `EXTRACTED` (03:1616-1622) and `os_kind = bytes` caps quote at
    `VERBATIM` (03:1675-1681), so both ceilings have to be right for any of the assertions above
    to mean what they say -- a clamp would have silently lowered them instead of failing.

    THE PAIR IS NAMED AND NOT MERELY COUNTED. An earlier form of this test asserted only that
    exactly one `(method, trust)` pair reached the store, which a document written entirely at
    `heuristic`/`inferred` satisfies just as well: uniformly wrong is still one pair. Both
    ceilings above are stated in terms of WHICH method and WHICH trust, so a test that declines
    to say which is checking neither of them.
    """
    store = ingested["store"]
    distinct = _rows(
        store,
        "SELECT DISTINCT e.name, b.trust FROM block b "
        "JOIN enum_val e ON e.domain='method' AND e.ord=b.method",
    )
    assert distinct == [(Method.NATIVE.value, int(Trust.EXTRACTED))], (
        f"every block is native/extracted, and exactly one pair may reach the store: {distinct}"
    )
    none_kind = _rows(
        store,
        "SELECT count(*) FROM block WHERE os_kind = "
        "(SELECT ord FROM enum_val WHERE domain='origin_span_kind' AND name='none')",
    )[0][0]
    assert none_kind == 0, (
        "a body block with os_kind='none' drags doc.achieved.origin_span to 'none' (03:512), "
        "which is why the containers carry real byte spans too"
    )


def test_the_heading_payload_carries_a_level_the_schema_accepts(
    ingested: dict[str, Any],
) -> None:
    """03:977 -- `heading.level` is an integer 1..9, validated inside `DocSink.add_block`."""
    rows = _rows(
        ingested["store"],
        "SELECT payload FROM block WHERE kind = "
        "(SELECT ord FROM enum_val WHERE domain='kind' AND name='heading')",
    )
    assert len(rows) == 2
    assert {row[0] for row in rows} == {'{"level":1}'}


# ---------------------------------------------------------------------------------------------
# 6. The cross-check against the shipped generator, when it exists
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(
    not GENERATOR_PATH.is_file(), reason="fixtures/gen/gen_5000p_pdf.py has not landed yet"
)
def test_the_driver_reads_the_shipped_generators_own_output(tmp_path: Path) -> None:
    """The same parse over a file this test did not write.

    Two independent writers of one frozen grammar is the arrangement that makes the parser a
    reader of a FORMAT rather than a partner in an agreement. If this fails and everything above
    passes, the generator and this file disagree about the contract -- which is a finding about
    the contract, not a bug in either.
    """
    generator = _load("omniweave_gen_5000p_pdf", GENERATOR_PATH)
    out = generator.generate(tmp_path / "gen_3p.pdf", pages=3)
    pages = stub.parse_pdf(Path(out).read_bytes())
    assert len(pages) == 3
    for page in pages:
        assert len(page.runs) == RUNS_PER_PAGE
        _heading, paragraphs, cells = stub._classify(page)
        assert len(paragraphs) == PARAGRAPHS_PER_PAGE
        assert {len(group) for group in paragraphs} == {LINES_PER_PARAGRAPH}
        assert len(cells) == TABLE_ROWS * TABLE_COLS
        first = page.runs[0]
        raw = Path(out).read_bytes()[first.byte_start : first.byte_start + first.byte_len]
        assert raw.decode("ascii") == first.text or "\\" in raw.decode("ascii")


# ---------------------------------------------------------------------------------------------
# 7. The values themselves.
#
# Every assertion below pins a LITERAL. Each one exists because a mutation of the driver went
# unnoticed by sections 1-6: the driver was broken on purpose, this file stayed green, and a real
# defect of that shape would therefore have shipped. Two recurring reasons, both named in the
# docstrings: an equality whose two sides come out of the same store pins agreement and not
# value, and a field nothing ever reads back is a field nothing checks.
# ---------------------------------------------------------------------------------------------

DECLARED_CARD: dict[str, object] = {
    "spatial": "none",
    "origin_span": "normalized",
    "text_span": False,
    "marks": False,
    "reading_order": "char_stream",
    "sections": "none",
    "tables": "cells",
    "math": frozenset(),
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "none",
    "forfeits": frozenset({"spatial", "round_trip"}),
}
"""The card this driver is permitted to publish, transcribed field by field on the TEST side.

Not `stub.STUB_CAPABILITIES`, and that difference is the point. `doc.achieved` catches an
over-declaration only where a committed row witnesses the field; `reading_order` and `round_trip`
have no witness, so comparing the record to the driver's own constant proves only that those two
agree with themselves. Fifteen literals cost fifteen lines and cannot do that.
"""


def test_the_fifteen_capability_fields_are_pinned_here_and_not_read_off_the_card() -> None:
    """Each field against a literal, and the field SET against the dataclass.

    Measured rather than assumed: over-declaring each of the fifteen in turn and re-running this
    file showed `achieved == STUB_CAPABILITIES` catching thirteen. `reading_order`
    (`char_stream` -> `source`) and `round_trip` (`none` -> `passthrough`) both survived it,
    because no committed row contradicts either -- `achieved` carries the declaration back and
    the equality holds. Those two are exactly the fields an over-claiming driver would keep.

    The field-set assertion guards against a SIXTEENTH field. `Capabilities` is one field set
    with three homes (`model/block.py`:278-279), so a field added there and omitted here would be
    an unpinned capability that nothing in this file mentions.
    """
    names = {field.name for field in dataclasses.fields(Capabilities)}
    assert names == set(DECLARED_CARD), "the card and `Capabilities` disagree about the field set"
    assert len(DECLARED_CARD) == 15, "03 section 2.9 declares fifteen capability fields"
    for field, expected in DECLARED_CARD.items():
        assert getattr(stub.STUB_CAPABILITIES, field) == expected, (
            f"STUB_CAPABILITIES.{field} is {getattr(stub.STUB_CAPABILITIES, field)!r} and not "
            f"{expected!r}: a capability floor is a FILTER, so an over-declared field admits this "
            f"driver to work it cannot do (16-roadmap.md:481)"
        )


def test_every_block_row_names_this_driver_this_operator_and_this_schema_version(
    ingested: dict[str, Any],
) -> None:
    """D3's three ownership columns, against literals and not against the module constants.

    `DocSink` is CONSTRUCTED with `stub.DRIVER_ID`, `stub.OPERATOR` and `stub.DRIVER_SCHEMA_V`,
    by this fixture and by `ingest`'s eventual runner alike, so `origin_driver == stub.DRIVER_ID`
    is a tautology: rename the constant and both sides move together. Renaming `DRIVER_ID` to
    `parse.pdf.pdfium` -- W3.5's name, which the driver's own docstring says it is deliberately
    NOT -- left this whole file green. Two drivers that disagree about what they can do must
    never share an id, because `achieved` is stored per document and read back by serve (charter
    section 5 X9), so the id is pinned here as text.

    The `parse.` prefix on the operator is load-bearing for a second reason: `_clamp_quote` caps
    a block at `SYNTHETIC` when the operator is not a parse (03:1683-1686), so every `VERBATIM`
    asserted above rests on it.
    """
    assert stub.DRIVER_ID == "parse.pdf.stub"
    assert stub.OPERATOR == "parse.pdf"
    assert stub.DRIVER_SCHEMA_V == 1
    assert stub.PORT == "parse/1", "16-roadmap.md:442's own name for the port"
    rows = _rows(
        ingested["store"],
        "SELECT DISTINCT origin_operator, origin_driver, driver_schema_v, os_part FROM block",
    )
    assert rows == [("parse.pdf", "parse.pdf.stub", 1, "file")]


def test_the_page_box_reaches_the_store_in_millipoints_the_right_way_up(
    ingested: dict[str, Any],
) -> None:
    """`w_mpt`, `h_mpt`, `page_kind`, `rotation` and `quad_origin` -- none of them read back.

    The page box was parsed and asserted in POINTS by
    `test_the_page_tree_and_the_page_box_come_out_of_the_cross_reference_table`, and then nothing
    checked what `_page_record` did with it. Scaling by 100 rather than 1000, and swapping width
    for height, each left this file green -- and the fixture's page is portrait, so the swap is a
    visible error no assertion reached.

    The `1000` below is this test's own transcription of 03:2225's millipoint grain, not the
    driver's `_MPT_PER_POINT`, which is the thing under test.
    """
    assert round(PAGE_W_PT * 1000) != round(PAGE_H_PT * 1000), "portrait, so a swap is visible"
    rows = _rows(
        ingested["store"],
        "SELECT p.page, e.name, p.w_mpt, p.h_mpt, p.rotation, p.quad_origin, p.status "
        "FROM page p JOIN enum_val e ON e.domain='page_kind' AND e.ord=p.page_kind "
        "ORDER BY p.page",
    )
    assert rows == [
        (
            index,
            PageKind.PAGE.value,
            round(PAGE_W_PT * 1000),
            round(PAGE_H_PT * 1000),
            0,
            None,
            "ok",
        )
        for index in (0, 1)
    ]


def test_the_doc_row_keeps_the_uri_the_media_type_and_the_key_it_was_handed(
    ingested: dict[str, Any],
) -> None:
    """Three `doc` columns that `_doc_record` fills and that nothing read back.

    `uri`, `media_type` and `doc_key` were each replaced with a wrong constant inside
    `_doc_record` and this file stayed green. `doc_key` is `sha256(normalized source)[:16]` and
    UNIQUE on the table (0001_init.sql), so a driver that ignored its argument would collide the
    second document it ever ingested with the first; `uri` is what a `cite` eventually resolves
    through. The expected values are the fixture's own inputs to `ingest`.
    """
    record = ingested["record"]
    expected_uri = ingested["pdf"].as_uri()
    assert record.uri == expected_uri
    assert record.media_type == "application/pdf"
    assert record.doc_key == bytes(range(16)), "the key the fixture handed `ingest`, unchanged"
    rows = _rows(ingested["store"], "SELECT uri, media_type, doc_key, format, normalizer FROM doc")
    assert rows == [(expected_uri, "application/pdf", bytes(range(16)), "pdf", None)]


def test_the_pre_commit_doc_record_is_the_claim_before_the_host_recomputes_it() -> None:
    """`_doc_record` alone, with no sink, because `end_doc` overwrites two of these fields.

    `gen` and `page_count` on the RETURNED record are the host's: `end_doc` bumps the generation
    and counts the committed pages. So seeding `gen=1` instead of `0`, or `page_count` as
    `len(pages) + 1`, changed nothing any assertion in this file could see -- the record handed
    back had already been corrected. 03:82 makes `gen = 0` mean "no committed generation", which
    is the only honest value on a row that has not been committed, and this is the one place it
    can be checked at all.
    """
    record = stub._doc_record(PDF, PAGES, uri="file:///x.pdf", doc_ord=3, doc_key=bytes(range(16)))
    assert record.gen == 0, "03:82 -- gen 0 is reserved and means 'no committed generation'"
    assert record.page_count == 2, "the pages the parse found, before the commit counts rows"
    assert record.doc_ord == 3
    assert record.uri == "file:///x.pdf"
    assert record.source_sha256 == hashlib.sha256(PDF).digest()
    assert record.source_bytes == len(PDF)
    assert record.normalizer is None
    assert record.status == "ok"
    assert record.declared == stub.STUB_CAPABILITIES
    assert record.achieved == stub.STUB_CAPABILITIES, (
        "seeded equal to `declared`, so a reader before the commit sees a claim rather than a "
        "floor of absences; `end_doc` replaces it from the committed rows"
    )


def test_a_coalesced_paragraph_is_its_four_runs_joined_by_one_space(
    ingested: dict[str, Any],
) -> None:
    """The paragraph's TEXT, built independently here, against the text the store holds.

    Nothing in this file read a paragraph's text. `_text_block` joins its runs with `" "`, and
    joining with `""` instead -- which welds `...chars` straight onto `p1` and changes every
    prose block in the document -- passed every assertion, the NORMALIZED one included: that test
    splits the text it was handed on `" "` and looks the pieces up in the covered bytes, so a
    text with no separators at all still yields pieces that are present.

    The expected strings come from `_body_text`, this file's own writer, so the two sides are
    independent. Paragraph 0 of page 1 is the one carrying `ESCAPED_BODY`, which is also the one
    run whose text differs from its bytes.
    """
    expected = [
        " ".join(_body_text(1, paragraph, line) for line in range(LINES_PER_PARAGRAPH))
        for paragraph in range(PARAGRAPHS_PER_PAGE)
    ]
    rows = _rows(
        ingested["store"],
        "SELECT b.text FROM block b WHERE b.page = 0 AND b.kind = "
        "(SELECT ord FROM enum_val WHERE domain='kind' AND name='paragraph') ORDER BY b.ord",
    )
    assert [row[0] for row in rows] == expected
    assert expected[0].startswith(ESCAPED_BODY), "paragraph 0 of page 1 carries the escaped run"
    assert " " in expected[0], "a separator that the wrong join would have dropped"


def test_the_document_root_addresses_the_whole_file_byte_for_byte(
    ingested: dict[str, Any],
) -> None:
    """`doc`'s `OriginBytes` is the entire part, `(0, len(file))`, and it was never checked.

    Shrinking it to `(0, 1)` kept this file green: `os_kind` stayed `bytes`, so the one assertion
    that touched the document root -- that no block carries `os_kind = 'none'`, which would drag
    `doc.achieved.origin_span` to `none` (03:512) -- was satisfied by a span naming one byte. A
    root that carries a byte range is claiming that range holds the document.
    """
    rows = _rows(ingested["store"], "SELECT addr, os_part, os_a, os_b FROM block WHERE addr='doc'")
    assert rows == [("doc", "file", 0, len(PDF))]
    assert _rows(ingested["store"], "SELECT byte_len FROM part")[0][0] == len(PDF), (
        "and the part it names is that same whole file"
    )


def test_each_pages_stats_count_the_runs_read_and_the_blocks_written(
    ingested: dict[str, Any],
) -> None:
    """`end_page`'s stats reach `page.stats`, and until now nothing read them back.

    Passing `{"runs": 0, "blocks": 0}` -- a page reporting that it read nothing and wrote nothing
    -- left every assertion in this file green. The pair is the cheapest per-page witness that a
    page's content arrived at all, which is what a bytes-per-block measurement over 5000 pages
    has to be able to trust (07:1005-1030).

    `blocks` counts the page root as well as the content beneath it: 1 page root + 1 heading +
    8 paragraphs + 1 table + 54 cells.
    """
    expected_blocks = 1 + 1 + PARAGRAPHS_PER_PAGE + 1 + TABLE_ROWS * TABLE_COLS
    assert expected_blocks == 65
    rows = _rows(ingested["store"], "SELECT page, stats FROM page ORDER BY page")
    assert [row[0] for row in rows] == [0, 1]
    for _page, stats in rows:
        assert json.loads(stats) == {"runs": RUNS_PER_PAGE, "blocks": expected_blocks}


def test_the_cells_reach_add_block_in_row_major_order(ingested: dict[str, Any]) -> None:
    """The sibling ordinals under the table, which is where the WRITE order becomes visible.

    `test_the_cell_grid_is_derived_from_geometry_and_not_from_a_constant` checks that
    `_cell_positions` ANSWERS row-major, which follows from the runs arriving in content-stream
    order. It says nothing about the order `_write_table` then hands them to `add_block`: sorting
    the cells column-major inside `_write_table` left that assertion passing. `DocSink.add_grid`
    does catch it (03:1937), but as a fixture error naming no claim of this file's, so the claim
    is stated here -- read off `addr`, whose last step is `r<r>c<c>` (03:1105), ordered by
    `block.ord`, which IS reading order (0001_init.sql on the column).
    """
    rows = _rows(
        ingested["store"],
        "SELECT b.addr FROM block b WHERE b.page = 0 AND b.kind = "
        "(SELECT ord FROM enum_val WHERE domain='kind' AND name='table_cell') ORDER BY b.ord",
    )
    assert len(rows) == TABLE_ROWS * TABLE_COLS
    positions = [
        tuple(int(part) for part in str(addr).rsplit("/", 1)[1][1:].split("c")) for (addr,) in rows
    ]
    assert positions == [(row, col) for row in range(TABLE_ROWS) for col in range(TABLE_COLS)]
