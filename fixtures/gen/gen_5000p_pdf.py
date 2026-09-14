"""`gen_5000p_pdf.py` -- the 5,000-page PDF fixture, synthesised byte by byte.

**No work item in the plan is assigned to build this file.** W4.10 builds `fixtures/incremental/`
and W9.8 builds `fixtures/out/`; 13-quality.md section 4.6 (:586-589) owns the *regime* every
generator under `fixtures/gen/` obeys but assigns it to no phase. P2 needs the corpus anyway --
16-roadmap.md:442 makes "ingest `fixtures/gen/gen_5000p_pdf.py`'s output through a stub `parse/1`
driver" the P2 demo, and 16-roadmap.md:459-460 makes `store.bytes_per_block` and
`rss.gen5000p_peak_bytes` two of its eight exit commands -- so it is built here, at P2 stage C,
and this paragraph is the record that it was built outside a work item rather than under one.

## What it is for

Three consumers, and they want three different things out of the same bytes:

* **The P2 demo** (16-roadmap.md:442-448) wants a document big enough that "the 5,000-page
  document never exists in memory" (03-document-model.md:2572-2581) is a claim under test rather
  than an aspiration, and a `SIGKILL` at page 3,000 has 2,000 pages left to converge over.
* **`store.bytes_per_block`** (12-performance.md:244, 660 B +/- 10%, nightly, RATCHET) wants a
  corpus whose prose/cell mix is REAL, because 07-store-and-retrieval.md:1012 makes the dominant
  term corpus-dependent in as many words: *"A prose paragraph is ~300 B; a table cell is ~10 B.
  The 60-120 blocks/page envelope is that wide because cells are Blocks."* A fixture of headings
  only would measure a number 07 section 4.1 is not talking about, so every page carries both.
* **The stub `parse/1` driver** (`tools/p2_stub_parse.py`) wants a file it can parse with no PDF
  library at all, and wants every text run's literal to be findable at a byte offset IN THE FILE,
  because that offset becomes each text Block's `OriginBytes` and is what lets `ow store verify`
  re-derive `content_sha256` from stored bytes (INV-10's bytes branch, 16-roadmap.md:442-443).

That third consumer is why this module writes PDF by hand instead of reaching for a library. Every
object is uncompressed, every content stream carries an explicit `/Length` and no `/Filter`, and
the cross-reference section is a CLASSIC xref TABLE rather than an xref stream -- so a literal in
the file is a literal in the stream, at an offset arithmetic can reach.

## The regime, which is 13-quality.md:586-589 and is not decoration

*"`fixtures/gen/*.py`, each deterministic under `SOURCE_DATE_EPOCH=0` with `random`, `secrets`,
`uuid4`, `time.time` and `datetime.now` monkeypatched to raise... Output lands in
`fixtures/generated/`, which is `.gitignore`d; `fixtures/gen/EXPECTED.sha256` pins each
generator's output so a generator change is a one-line visible diff rather than a silent corpus
change."*

All five of those names are absent from this module, and `test_fixture_gen.py` installs the five
patches and runs the generator under them rather than trusting the absence: a generator that
happens not to call `time.time` today is not the same artefact as one that provably cannot. The
content of page `i` is a pure function of `i` -- not of the page count, not of the output path,
not of the clock -- so `--pages 8` emits byte-for-byte the first eight pages that `--pages 5000`
does, which is what makes the small pin in `EXPECTED.sha256` a real check on the large one.

Every date in the file is the literal `D:19800101000000Z`. `SOURCE_DATE_EPOCH` is therefore not
read at all: there is no timestamp here for it to override, which is the strongest form of
compliance with the setting rather than a way around it.

## Why these constants, and the one number this file must NOT be tuned to

`store.bytes_per_block = 660` is a MEASUREMENT of the store, taken over this corpus. Choosing
`PARAGRAPHS_PER_PAGE` or the run length to make 660 come out true would make the nightly ratchet
measure its own input, so the constants below are chosen for one reason only: they put a page in
the plan-stated **60-120 blocks/page** envelope (00-vision.md:474, 07-store-and-retrieval.md:1095)
with a prose/cell mix that resembles a paginated document, and the bytes-per-block figure is then
whatever the store reports.

What the constants imply, arithmetically, is `BLOCKS_PER_PAGE_FIXTURE = 64` -- 1 heading + 8
paragraphs + 1 table + 54 cells, excluding the page-root Block the sink mints. That number is **a
property of this fixture and not a measurement of the world** (ruling D27, this session): F1's
blocks-per-page envelope closes only against ten real 200-page documents
(03-document-model.md:3086), which need W3.4/W3.5 drivers and are P3. Anything that prints 64 must
label it. What P2 does close off this corpus is the *store* variable, `store.bytes_per_block`.

## The shape of the file, stated once because the stub driver depends on all of it

```
%PDF-1.4                       header
%<four bytes >= 0x80>          the binary comment, so every tool treats the file as binary
1 0 obj  /Catalog              -> 2 0 R
2 0 obj  /Pages                /Count <pages> /Kids [5 0 R 7 0 R ...]
3 0 obj  /Font  /Helvetica     the one font, shared by every page as /F1
4 0 obj  the Info dictionary   both dates the frozen literal
5 0 obj  page 1                /MediaBox [0 0 595.276 841.890], /Contents 6 0 R
6 0 obj  page 1 content        << /Length n >> stream ... endstream, NO /Filter
...      page p is object 5 + 2*(p-1); its content stream is the next object
xref                           a classic table, <objects>+1 entries of exactly 20 bytes
trailer  /Size /Root /Info /ID
startxref <offset of "xref">
%%EOF
```

Every byte written is ASCII except the four in the binary comment, and **no byte in the file is a
carriage return**: a CRLF translation on a Windows checkout would shift every literal's offset and
rot every `OriginBytes` the stub emits, so the file is opened `"wb"` and the EOL is a bare newline
everywhere, including inside the fixed-width xref entries (the spec allows a trailing space there
exactly so that a table stays 20 bytes per entry without a CR).

One number format is used for every real number in the file: three decimal places, always. That is
why `/MediaBox` reads `[0 0 595.276 841.890]` with its trailing zero intact, and why a size reads
`/F1 18.000 Tf`. `float()` round-trips all of them, and a single format means the stub has one
rule rather than four.

Specified against: 13-quality.md:586-589 (the regime), 16-roadmap.md:442-460 (the demo and the
exit criteria), 12-performance.md:244-245 and :1514 (what measures off it),
07-store-and-retrieval.md:1005-1030 (why the prose/cell mix is load-bearing),
00-vision.md:474 and 07-store-and-retrieval.md:1095 (the 60-120 blocks/page envelope),
03-document-model.md:3086 (what actually closes F1, and why it is not this file alone).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO, Final

# --------------------------------------------------------------------------------------------
# The frozen contract. Every one of these is read by `tools/p2_stub_parse.py`.
# --------------------------------------------------------------------------------------------

DEFAULT_PAGES: Final = 5_000
"""16-roadmap.md:442. The demo document, and the corpus `store.bytes_per_block` is taken over."""

PAGE_W_PT: Final = 595.276
"""A4 width in points (210 mm). Emitted as `595.276`."""

PAGE_H_PT: Final = 841.890
"""A4 height in points (297 mm). Emitted as `841.890`, trailing zero intact."""

HEADING_SIZE_PT: Final = 18.0
BODY_SIZE_PT: Final = 10.0
CELL_SIZE_PT: Final = 8.0

LEADING_PT: Final = 12.0
"""The EXACT y-decrement between two runs of one paragraph.

This is the single fact the stub's coalescing rule turns on: consecutive runs at the same
`size_pt` whose baseline drops by exactly `LEADING_PT` are one paragraph, and any other gap ends
it. Every other vertical step in the page is strictly greater than this, which is how a boundary
is detectable without a layout engine.
"""

PARAGRAPHS_PER_PAGE: Final = 8
LINES_PER_PARAGRAPH: Final = 4
TABLE_ROWS: Final = 9
TABLE_COLS: Final = 6

RUNS_PER_PAGE: Final = 1 + PARAGRAPHS_PER_PAGE * LINES_PER_PARAGRAPH + TABLE_ROWS * TABLE_COLS
"""87 text runs: one heading, thirty-two body lines, fifty-four cells."""

BLOCKS_PER_PAGE_FIXTURE: Final = 1 + PARAGRAPHS_PER_PAGE + 1 + TABLE_ROWS * TABLE_COLS
"""64 = 1 heading + 8 paragraphs + 1 table + 54 cells, EXCLUDING the page-root Block.

**A property of this fixture, never a measurement of a corpus** (ruling D27). It sits inside the
plan's 60-120 blocks/page envelope (00-vision.md:474) by construction, which is the only claim
made for it; F1 closes against ten real 200-page documents in P3 (03-document-model.md:3086).
Anything that prints this number must print that caveat with it.
"""

# --------------------------------------------------------------------------------------------
# Geometry. Every gap below is strictly greater than LEADING_PT, on purpose.
# --------------------------------------------------------------------------------------------

MARGIN_LEFT_PT: Final = 56.693
"""20 mm. Body and heading runs share this x; cells step right from it."""

MARGIN_TOP_PT: Final = 56.693
"""20 mm, so the heading baseline is at 785.197."""

HEADING_Y_PT: Final = PAGE_H_PT - MARGIN_TOP_PT
"""785.197 -- the heading baseline, and the highest run on every page."""

HEADING_GAP_PT: Final = 24.0
"""Heading baseline to the first body line. > LEADING_PT, so the heading never coalesces."""

PARAGRAPH_GAP_PT: Final = 18.0
"""Last line of one paragraph to the first line of the next. > LEADING_PT: this IS the boundary."""

TABLE_GAP_PT: Final = 24.0
"""Last body line to the first table row. > LEADING_PT."""

TABLE_ROW_STEP_PT: Final = 14.0
"""Row to row. > LEADING_PT, so two rows of cells never read as one paragraph."""

TABLE_COL_W_PT: Final = 80.0
"""Six columns from `MARGIN_LEFT_PT` end at x=456.693, inside the right margin."""

NUM_DECIMALS: Final = 3
"""One number format for the whole file. See the module docstring."""

BODY_CHARS: Final = 75
"""The soft target for a body run, in unescaped characters.

A line is filled with whole words up to this bound, so runs land in the high sixties to
seventy-five -- the "~75 ASCII characters" the stub driver's contract states -- without ever
splitting a word, because a word split at a fixed column would make the text a function of the
column rather than of the page.
"""

# --------------------------------------------------------------------------------------------
# PDF object numbering. Fixed arithmetic, because the /Kids array must name page objects that
# have not been written yet.
# --------------------------------------------------------------------------------------------

OBJ_CATALOG: Final = 1
OBJ_PAGES: Final = 2
OBJ_FONT: Final = 3
OBJ_INFO: Final = 4
FIRST_PAGE_OBJ: Final = 5

FIXED_DATE: Final = "D:19800101000000Z"
"""Every date in the file. 13-quality.md:586-589 forbids a clock; this is what replaces it."""

PDF_HEADER: Final = b"%PDF-1.4\n"
BINARY_COMMENT: Final = b"%\xe2\xe3\xcf\xd3\n"
"""Four bytes >= 0x80 on a comment line, per PDF 1.7 section 7.5.2, so that every downstream tool
treats the file as binary. None of the four is 0x0D."""

XREF_FREE_ENTRY: Final = b"0000000000 65535 f \n"
"""Exactly 20 bytes, like every other entry. The trailing space before the EOL is what keeps the
width fixed without a carriage return."""

# --------------------------------------------------------------------------------------------
# The word pool. A fixed list, indexed by arithmetic -- never sampled.
# --------------------------------------------------------------------------------------------

WORDS: Final = (
    "agreement",
    "party",
    "clause",
    "schedule",
    "annex",
    "term",
    "notice",
    "consent",
    "warranty",
    "indemnity",
    "liability",
    "remedy",
    "breach",
    "waiver",
    "assignment",
    "novation",
    "counterpart",
    "governing",
    "jurisdiction",
    "arbitration",
    "confidential",
    "disclosure",
    "obligation",
    "covenant",
    "representation",
    "condition",
    "precedent",
    "termination",
    "renewal",
    "escalation",
    "milestone",
    "deliverable",
    "acceptance",
    "inspection",
    "audit",
    "record",
    "retention",
    "invoice",
    "payment",
    "interest",
    "adjustment",
    "allocation",
    "threshold",
    "aggregate",
    "quarterly",
    "annual",
    "effective",
    "commencement",
    "expiry",
    "survival",
    "severance",
    "amendment",
    "variation",
    "supplement",
    "appendix",
    "exhibit",
    "definition",
    "interpretation",
    "construction",
    "priority",
    "conflict",
    "resolution",
    "escrow",
    "custody",
)

WORD_STEP: Final = 7_919
"""A prime stride through `WORDS`, so consecutive words in a line differ. Not a random source: the
whole sequence is a closed form in the page, paragraph, line and word index."""

ESCAPED_CELL_PAGE_STRIDE: Final = 5
ESCAPED_CELL_ROW: Final = 4
ESCAPED_CELL_COL: Final = 2
"""Which cell carries parentheses, and how often.

One cell in fifty-four, on every fifth page. Enough that the stub driver's unescaper is exercised
on the cell branch in any run of five pages or more; few enough that the ~10 B cell text figure
07-store-and-retrieval.md:1012 depends on is untouched.
"""

PAGE_MIX: Final = 1_000_003
PARA_MIX: Final = 10_007
LINE_MIX: Final = 101
"""Three primes, so `(page, paragraph, line)` triples do not collide into the same word run within
any plausible page count. Nothing here needs to be unpredictable -- only distinct and
reproducible."""


# --------------------------------------------------------------------------------------------
# Text, as a pure function of the page index
# --------------------------------------------------------------------------------------------


def _num(value: float) -> str:
    """The one number format: three decimals, always. `595.276`, `841.890`, `18.000`."""
    return f"{value:.{NUM_DECIMALS}f}"


def _word(index: int) -> str:
    """`WORDS`, indexed. The modulo lives here rather than at each call site."""
    return WORDS[index % len(WORDS)]


def heading_text(page: int) -> str:
    """The heading run of page `page` (1-based). ~40 ASCII characters.

    A pure function of the page number and of nothing else -- not of the total page count -- which
    is what makes `--pages 8` a genuine prefix of `--pages 5000` and therefore makes the small pin
    in `EXPECTED.sha256` a real check on the large one.
    """
    seed = page * PAGE_MIX
    first = _word(seed).capitalize()
    second = _word(seed + WORD_STEP)
    return f"Article {page}. {first} and {second}"


def body_text(page: int, paragraph: int, line: int) -> str:
    r"""One body run: whole words up to `BODY_CHARS`, all ASCII, never word-split.

    Every third `(page + paragraph)` puts a parenthesised, backslash-bearing token at the head of
    line 1. That is deliberate, and it is the only reason those characters appear anywhere in the
    corpus: the literal must be written escaped (`\(`, `\)`, `\\`) and read back unescaped, so a
    run whose escaped length differs from its text length exists on most pages. Without it the
    stub driver's `Quote.VERBATIM` / `Quote.NORMALIZED` distinction would never be exercised by
    the fixture, and an unexercised ladder rung is an unproven one.
    """
    seed = page * PAGE_MIX + paragraph * PARA_MIX + line * LINE_MIX
    parts: list[str] = []
    length = 0
    if line == 1 and (page + paragraph) % 3 == 0:
        token = f"(see \\ {_word(seed)})"
        parts.append(token)
        length = len(token)
    index = 0
    while True:
        word = _word(seed + index * WORD_STEP)
        extra = len(word) + (1 if parts else 0)
        if length + extra > BODY_CHARS:
            break
        parts.append(word)
        length += extra
        index += 1
    return " ".join(parts)


def cell_text(page: int, row: int, col: int) -> str:
    """One table cell: nine or ten ASCII characters, `R3C4-0271`.

    07-store-and-retrieval.md:1012 puts a table cell at ~10 B of text against a prose paragraph's
    ~300 B, and that ratio is the whole reason the bytes-per-block decomposition has an error bar.
    A cell that carried a sentence would quietly move the number this corpus exists to measure.

    Every fifth page parenthesises one cell, so the escape path is exercised in the cell branch
    and not only in prose.
    """
    value = (page * 31 + row * 7 + col) % 10_000
    if page % ESCAPED_CELL_PAGE_STRIDE == 0 and row == ESCAPED_CELL_ROW and col == ESCAPED_CELL_COL:
        return f"R{row}C{col}({value:04d})"
    return f"R{row}C{col}-{value:04d}"


# --------------------------------------------------------------------------------------------
# Content streams
# --------------------------------------------------------------------------------------------


def _escape(text: str) -> bytes:
    r"""A PDF literal string body. Only `\`, `(` and `)` are escaped -- in that order.

    The backslash must go first, or an escape introduced for a parenthesis would itself be
    escaped. Nothing else is escaped because nothing else needs to be: every character this
    generator emits is printable ASCII, so there is no octal escape, no newline inside a literal
    and no line continuation anywhere in the corpus. The stub driver's unescaper is therefore
    three replacements long.
    """
    raw = text.encode("ascii")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _tm(x_pt: float, y_pt: float) -> bytes:
    """`1 0 0 1 x y Tm` -- an ABSOLUTE text position.

    There is no `Td`, no `TL` and no `T*` in this file, so a parser never has to track a text-line
    matrix to know where a run sits.
    """
    return f"1 0 0 1 {_num(x_pt)} {_num(y_pt)} Tm".encode("ascii")


def _tj(text: str) -> bytes:
    """`(literal) Tj`. One run, one line, one operator."""
    return b"(" + _escape(text) + b") Tj"


def _tf(size_pt: float) -> bytes:
    """`/F1 size Tf`. Emitted only where the size CHANGES -- three times per page."""
    return f"/F1 {_num(size_pt)} Tf".encode("ascii")


def page_content(page: int) -> bytes:
    """The content stream of page `page` (1-based), exactly as it appears in the file.

    Emission order is the contract's: the heading, then `PARAGRAPHS_PER_PAGE` paragraphs of
    `LINES_PER_PARAGRAPH` runs each, then `TABLE_ROWS` x `TABLE_COLS` cells in row-major order.
    The y-arithmetic is the load-bearing part -- inside a paragraph the baseline drops by exactly
    `LEADING_PT` and at every other boundary by strictly more -- so the coalescing rule in the stub
    driver is reading a fact this function wrote, not guessing at a layout. Within one table row
    the baseline does not move at all, which is also not a drop of exactly `LEADING_PT`, so six
    cells never read as one paragraph either.

    No trailing newline: `_content_object` supplies the EOL that precedes `endstream`, and that
    EOL is not counted in `/Length`.
    """
    lines: list[bytes] = [b"BT", _tf(HEADING_SIZE_PT)]

    y = HEADING_Y_PT
    lines.append(_tm(MARGIN_LEFT_PT, y))
    lines.append(_tj(heading_text(page)))

    lines.append(_tf(BODY_SIZE_PT))
    for paragraph in range(PARAGRAPHS_PER_PAGE):
        y -= HEADING_GAP_PT if paragraph == 0 else PARAGRAPH_GAP_PT
        for line in range(LINES_PER_PARAGRAPH):
            if line:
                y -= LEADING_PT
            lines.append(_tm(MARGIN_LEFT_PT, y))
            lines.append(_tj(body_text(page, paragraph, line)))

    lines.append(_tf(CELL_SIZE_PT))
    top = y - TABLE_GAP_PT
    for row in range(TABLE_ROWS):
        row_y = top - row * TABLE_ROW_STEP_PT
        for col in range(TABLE_COLS):
            lines.append(_tm(MARGIN_LEFT_PT + col * TABLE_COL_W_PT, row_y))
            lines.append(_tj(cell_text(page, row, col)))

    lines.append(b"ET")
    return b"\n".join(lines)


# --------------------------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------------------------


def page_object_number(page: int) -> int:
    """Object number of page `page` (1-based). Its content stream is the next object."""
    return FIRST_PAGE_OBJ + 2 * (page - 1)


def object_count(pages: int) -> int:
    """Catalog, Pages, Font, Info, then two objects per page.

    `/Size` is one MORE than this, because entry 0 of a cross-reference table is the head of the
    free list and is an object number too.
    """
    return 4 + 2 * pages


def _obj(number: int, body: bytes) -> bytes:
    return f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"


def _catalog_object() -> bytes:
    return _obj(OBJ_CATALOG, f"<< /Type /Catalog /Pages {OBJ_PAGES} 0 R >>".encode("ascii"))


def _pages_object(pages: int) -> bytes:
    kids = " ".join(f"{page_object_number(p)} 0 R" for p in range(1, pages + 1))
    return _obj(OBJ_PAGES, f"<< /Type /Pages /Count {pages} /Kids [{kids}] >>".encode("ascii"))


def _font_object() -> bytes:
    """One Helvetica, shared by every page as `/F1`.

    A base-14 font needs no descriptor and no embedded programme, which keeps the file free of any
    binary object at all -- the four bytes of the header comment are the only non-ASCII in it.
    """
    return _obj(
        OBJ_FONT,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )


def _info_object(title: str) -> bytes:
    """`/Info`, whose `/Title` is the caller's. Every date is `FIXED_DATE` and nothing is read.

    The title is a parameter rather than derived from the page count because `write_pdf` serves
    two corpora now: this generator's own N-page fixture, whose title is
    `"omniweave gen_5000p_pdf {pages}p"`, and `gen_incremental.py`'s 300 documents, each of which
    needs a title of its own. Deriving it here would have made the second corpus either untitled
    or mis-titled, and `/Title` is in the bytes the digest covers.
    """
    body = (
        f"<< /Title ({title})"
        " /Producer (omniweave fixtures/gen/gen_5000p_pdf.py)"
        f" /CreationDate ({FIXED_DATE}) /ModDate ({FIXED_DATE}) >>"
    )
    return _obj(OBJ_INFO, body.encode("ascii"))


def _page_object(page: int) -> bytes:
    number = page_object_number(page)
    body = (
        f"<< /Type /Page /Parent {OBJ_PAGES} 0 R"
        f" /MediaBox [0 0 {_num(PAGE_W_PT)} {_num(PAGE_H_PT)}]"
        f" /Resources << /Font << /F1 {OBJ_FONT} 0 R >> >>"
        f" /Contents {number + 1} 0 R >>"
    )
    return _obj(number, body.encode("ascii"))


def _content_object(number: int, content: bytes) -> bytes:
    """`<< /Length n >> stream ... endstream`, with `n` the true byte count of the stream data.

    No `/Filter`. The EOL after `stream` and the one before `endstream` are structure, not data,
    and only the bytes between them are counted -- which is what makes a literal's file offset
    computable by a parser that never decodes anything.
    """
    head = f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
    return _obj(number, head + content + b"\nendstream")


def _file_id(seed: str) -> str:
    """A deterministic `/ID`, 32 hex digits, over a seed the caller chooses.

    A PDF `/ID` is conventionally random, and random is exactly what 13-quality.md:586-589
    forbids. A digest over the one input that changes the file content is the honest substitute:
    it is stable across runs and machines, and it still differs between two files that differ.

    The seed is the caller's for `_info_object`'s reason: two documents of the same page count in
    `gen_incremental.py`'s corpus are different files and must not share an `/ID`.
    """
    return hashlib.sha256(seed.encode("ascii")).hexdigest()[:32].upper()


# --------------------------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------------------------


class _Sink:
    """A binary stream that knows its own offset.

    `BufferedWriter.tell()` would answer the same question, but only for a seekable stream, and
    the offset is the one thing this generator cannot get wrong: it is written into the xref table
    and read back as a file offset by the stub driver. Counting what was written is independent of
    the stream's own bookkeeping, so a disagreement between the two surfaces as a broken xref in
    the test rather than as silence.
    """

    __slots__ = ("_out", "pos")

    def __init__(self, out: BinaryIO) -> None:
        self._out = out
        self.pos = 0

    def write(self, data: bytes) -> None:
        self._out.write(data)
        self.pos += len(data)


def write_pdf(out: BinaryIO, contents: Sequence[int], *, title: str, id_seed: str) -> None:
    """Write one PDF whose pages carry `page_content(i)` for each `i` in `contents`, in order.

    **The public entry to this file's byte format, and the reason it is public.** 16-roadmap.md:550
    gives W4.10 a 300-document corpus, `tools/p2_stub_parse.py` reads exactly one grammar, and a
    second generator emitting that grammar would be a second home for a byte layout whose whole
    value is that a literal in the file is a literal at a computable offset. So
    `fixtures/gen/gen_incremental.py` composes its documents out of THIS function, and the two
    corpora share one xref writer, one object numbering and one escape rule.

    **Position and content are different indices, and keeping them apart is the whole change.**
    The object numbering follows a page's POSITION in this file -- `page_object_number(1)` is the
    first page object wherever its content came from -- and the content follows the INDEX into
    this module's frozen content space. `_emit` passes `range(1, pages + 1)`, so the two coincide
    for the N-page fixture and its bytes are unchanged; `gen_incremental.py` passes a scattered
    tuple, and a document's content is then a function of the indices it names rather than of how
    many pages it happens to have.

    `contents` must be `Sized`: `/Count` and the xref table are both written from its length
    before any page is emitted, so a bare iterator would need a materialised copy anyway.
    """
    sink = _Sink(out)
    pages = len(contents)
    count = object_count(pages)
    offsets: list[int] = [0] * (count + 1)

    sink.write(PDF_HEADER)
    sink.write(BINARY_COMMENT)

    offsets[OBJ_CATALOG] = sink.pos
    sink.write(_catalog_object())
    offsets[OBJ_PAGES] = sink.pos
    sink.write(_pages_object(pages))
    offsets[OBJ_FONT] = sink.pos
    sink.write(_font_object())
    offsets[OBJ_INFO] = sink.pos
    sink.write(_info_object(title))

    for position, index in enumerate(contents, start=1):
        number = page_object_number(position)
        offsets[number] = sink.pos
        sink.write(_page_object(position))
        offsets[number + 1] = sink.pos
        sink.write(_content_object(number + 1, page_content(index)))

    startxref = sink.pos
    sink.write(f"xref\n0 {count + 1}\n".encode("ascii"))
    sink.write(XREF_FREE_ENTRY)
    for number in range(1, count + 1):
        sink.write(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))

    file_id = _file_id(id_seed)
    trailer = (
        f"trailer\n<< /Size {count + 1} /Root {OBJ_CATALOG} 0 R /Info {OBJ_INFO} 0 R"
        f" /ID [<{file_id}> <{file_id}>] >>\n"
    )
    sink.write(trailer.encode("ascii"))
    sink.write(f"startxref\n{startxref}\n".encode("ascii"))
    sink.write(b"%%EOF\n")


def repo_root() -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {here}"
    raise RuntimeError(message)


def default_out(pages: int) -> Path:
    """`<repo>/fixtures/generated/gen_{pages}p.pdf`.

    `fixtures/generated/` is `.gitignore`d (13-quality.md:588): the corpus is regenerated, never
    committed, and `EXPECTED.sha256` is the only thing about it that lives in git.
    """
    return repo_root() / "fixtures" / "generated" / f"gen_{pages}p.pdf"


def generate(out: Path, *, pages: int = DEFAULT_PAGES) -> Path:
    """Write the fixture to `out` and return `out`.

    Streamed a page at a time: the 5,000-page file is tens of megabytes and this generator is the
    input to `rss.gen5000p_peak_bytes` (12-performance.md:245), so it would be a poor joke for the
    generator itself to be the process that needs 1.5 GiB. Only one page's content stream and the
    xref offset table are ever resident, and the offset table is one machine int per object.
    """
    if pages < 1:
        message = f"pages must be >= 1, got {pages}"
        raise ValueError(message)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        write_pdf(
            handle,
            range(1, pages + 1),
            title=f"omniweave gen_5000p_pdf {pages}p",
            id_seed=f"omniweave/gen_5000p_pdf/1/{pages}",
        )
    return out


def sha256_of(path: Path) -> str:
    """The digest `EXPECTED.sha256` pins, read back in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """`python fixtures/gen/gen_5000p_pdf.py [--pages N] [--out PATH] [--print-sha256]`.

    Always reports the path, the size, the digest and the page count, because a fixture whose
    digest is one flag away from being unreported is a fixture nobody checks. `--print-sha256`
    adds one further line in `sha256sum` format -- digest, two spaces, the repo-relative path --
    which is the exact line `EXPECTED.sha256` wants pasted into it.

    `print` is banned by ruff's T20 across this repository, so the report is written to
    `sys.stdout` directly; that is the same escape the `tools/gate_*.py` runners take.
    """
    parser = argparse.ArgumentParser(
        prog="gen_5000p_pdf.py",
        description="Generate the deterministic N-page PDF fixture (13-quality.md:586-589).",
    )
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="page count")
    parser.add_argument("--out", type=Path, default=None, help="output path")
    parser.add_argument(
        "--print-sha256",
        action="store_true",
        help="also print one EXPECTED.sha256 line for this output",
    )
    args = parser.parse_args(argv)

    if args.pages < 1:
        sys.stderr.write(f"gen_5000p_pdf.py: --pages must be >= 1, got {args.pages}\n")
        return 2

    out: Path = args.out if args.out is not None else default_out(args.pages)
    generate(out, pages=args.pages)
    digest = sha256_of(out)
    size = out.stat().st_size

    sys.stdout.write(f"path    {out}\n")
    sys.stdout.write(f"bytes   {size}\n")
    sys.stdout.write(f"sha256  {digest}\n")
    sys.stdout.write(f"pages   {args.pages}\n")
    if args.print_sha256:
        try:
            rel = out.resolve().relative_to(repo_root()).as_posix()
        except ValueError:
            rel = out.name
        sys.stdout.write(f"{digest}  {rel}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
