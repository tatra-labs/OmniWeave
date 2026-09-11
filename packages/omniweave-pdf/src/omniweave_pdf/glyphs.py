"""INV-10's `glyphs` branch: the index space, and the re-extraction that proves a quote.

03-document-model.md:1419 gives the variant and its predicate in one row:

| `glyphs` | `part, extractor, start, length` | a PDF text layer | re-extracting `[a, a+len)` from
  `part` with the recorded `extractor` reproduces `block.text` under NFC |

:1468-1474 says why it exists at all: "A PDF paragraph has no byte range in the content stream.
Without a glyph-run address, `parse.pdf.pdfium` could never produce a `VERBATIM` block, and with
`parse.office.anydoc` honestly declaring `origin_span = "none"` the `VERBATIM` tier would ship with
**no producer at all**." This module is that producer's half of the bargain.

## The index space, stated precisely, because the whole branch rests on it

**A glyph index is a position in the document-global concatenation of pdfium's per-page character
sequences, taken in page order, starting at zero.**

Three properties follow, and each one is load-bearing:

* **It is pdfium's, not the PDF's.** 03:1471: "`extractor` is an exact identity like `pdftext@0.6`,
  because the glyph index space is the extractor's, not the PDF's". `FPDFText_CountChars` counts
  what pdfium's text layer produced, which includes the `\\r\\n` pairs pdfium *synthesises* at line
  ends and which exist nowhere in the content stream. A different extractor counts differently, so
  the identity is recorded and a verifier holding a different one must report that rather than a
  mismatch.
* **It is document-global, not per-page.** The predicate re-extracts "from `part`", and the
  `glyphs` variant carries `part, extractor, start, length` and no page (03:1419, and :1432's
  column map gives `os_path` NULL). An index that needed a page to resolve would not be
  re-extractable from what the union carries.
* **It is the unicode sequence exactly.** `FPDFText_CountChars(p)` equals
  `len(get_text_range(0, n))` equals `len("".join(chr(FPDFText_GetUnicode(p, i)) for i in
  range(n)))`, so a slice of the index space IS a slice of the text. `test_pdf_glyphs.py` asserts
  that three-way equality against a real fixture rather than assuming it, because everything here
  is wrong if it does not hold.

## Why `extract()` does not materialise the document

`document_text()` exists and the driver does not call it. 03-document-model.md:2572-2581 is the
constraint -- "the 5,000-page document never exists in memory" -- so `extract()` walks pages
accumulating counts, materialises only the pages the requested range actually touches, and stops.
A verifier checking one block on page 4,000 of a 5,000-page PDF pays for one page.

## What `EXTRACTOR` names

`pypdfium2@<version>`, matching 03:740's pattern `^[a-z0-9_.-]+@[0-9A-Za-z.+-]+$`, and it names the
**wrapper** rather than the bundled pdfium build. The wrapper version is what a lockfile pins and
what `[deps] pins` records, it determines the pdfium build by construction (one wheel, one binary),
and it is the direct analogue of the `pdftext@0.6` the plan prints. `pdfium_build()` reports the
binary's own version for a report that wants it; it is deliberately not the identity, because a
value nobody can pin is a value nobody can reproduce.

Specified in 03-document-model.md sections 7.2 and 8.3; INV-10; 16-roadmap.md W3.5.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Final

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from pypdfium2.version import PDFIUM_INFO, PYPDFIUM_INFO

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "EXTRACTOR",
    "PageText",
    "document_text",
    "extract",
    "page_texts",
    "pdfium_build",
]

EXTRACTOR: Final = f"pypdfium2@{PYPDFIUM_INFO}"
"""The recorded `os_extractor`. An EXACT identity, matching 03:740's pattern.

An exact identity rather than a floor, because the index space is the extractor's: a verifier
running a different version is not entitled to conclude "mismatch" from a disagreement, only
"different extractor". `verify()` returns that distinction rather than a bare bool."""


def pdfium_build() -> str:
    """The bundled pdfium binary's own version, for a report. **Never the recorded identity.**

    04-driver-system.md:1586's example tombstone -- "pdfium 6.x changes glyph run grouping; the
    successor declares char_bbox" -- is about this number, so a report that names it is more useful
    than one that does not. It is not `EXTRACTOR` because it is not what a lockfile pins.
    """
    return str(PDFIUM_INFO)


class PageText:
    """One page's character sequence and the document-global offset it starts at.

    `start` is the running total of every earlier page's character count, which is the definition
    of the index space and the only thing that makes a per-page API produce a document-global
    address.
    """

    __slots__ = ("index", "start", "text")

    def __init__(self, index: int, start: int, text: str) -> None:
        self.index = index
        self.start = start
        self.text = text

    @property
    def length(self) -> int:
        return len(self.text)

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    def __repr__(self) -> str:  # pragma: no cover -- diagnostics only.
        return f"PageText(index={self.index}, start={self.start}, length={self.length})"


def page_text(document: pdfium.PdfDocument, index: int) -> str:
    """One page's characters, as the index space defines them.

    `get_text_range(0, n)` rather than a per-character loop: they are equal (the module docstring's
    three-way identity, asserted in `test_pdf_glyphs.py`) and the range call is one FFI crossing
    instead of `n`. On a 2,891-character page that is the difference between a millisecond and a
    hundred, against 05-ingest-and-routing.md:839's 8 ms/page target.
    """
    page = document[index]
    textpage = page.get_textpage()
    try:
        count = pdfium_raw.FPDFText_CountChars(textpage.raw)
        return textpage.get_text_range(0, count) if count > 0 else ""
    finally:
        textpage.close()
        page.close()


def page_texts(document: pdfium.PdfDocument) -> Iterator[PageText]:
    """Every page in order, each carrying its document-global start offset.

    A generator, so a caller that wants page 3 of 5,000 pays for three pages rather than 5,000.
    """
    cursor = 0
    for index in range(len(document)):
        text = page_text(document, index)
        yield PageText(index, cursor, text)
        cursor += len(text)


def document_text(pdf: bytes) -> str:
    """The whole index space, materialised. **The driver does not call this.**

    Here because it is the definition -- `extract(pdf, a, n) == nfc(document_text(pdf)[a : a + n])`
    is the property `test_pdf_glyphs.py` checks `extract()` against -- and because a verifier with
    a small document and no memory concern is entitled to the simple form. On anything the size of
    `fixtures/gen`'s 5,000-page output it is the wrong function, which is why the driver uses
    `page_texts()` and why this docstring says so.
    """
    with pdfium.PdfDocument(pdf) as document:
        return "".join(part.text for part in page_texts(document))


def extract(pdf: bytes, start: int, length: int) -> str | None:
    """INV-10's `glyphs` branch, right-hand side: `[start, start+length)` under NFC.

    Args:
        pdf: the retained part's bytes. The whole PDF, because the glyph index space is the
            document's and a page in isolation would renumber from zero.
        start: a document-global glyph index.
        length: a LENGTH, never an end offset (03:1445, "`os_b` is a LENGTH, never an end offset" --
            one quantity, one spelling, three places).

    Returns:
        The NFC-normalised slice, or `None` when the range falls outside the document. `None`
        rather than a raise or a truncated string: a suite comparing this against `block.text`
        needs to distinguish "the text differs" from "the address is not in this document", and a
        short string would report the first when the truth is the second.

    **NFC and nothing else.** 03:1491: "`glyphs` re-extracts under NFC". Not `normalize_k`, which
    casefolds and would let a block reading `abc` prove `VERBATIM` against a page reading `ABC`;
    not `normalize_eval`, which folds quote families and is the evaluator's.

    Materialises only the pages the range touches.
    """
    if start < 0 or length < 0:
        return None
    stop = start + length
    pieces: list[str] = []
    with pdfium.PdfDocument(pdf) as document:
        for part in page_texts(document):
            if part.end <= start:
                continue
            if part.start >= stop:
                break
            lo = max(0, start - part.start)
            hi = min(part.length, stop - part.start)
            pieces.append(part.text[lo:hi])
    gathered = "".join(pieces)
    # A short gather means the range ran off the end of the document. Length rather than a
    # separate bound check, because the pages were walked anyway and the count is the answer.
    if len(gathered) != length:
        return None
    return unicodedata.normalize("NFC", gathered)


def verify(pdf: bytes, start: int, length: int, text: str, extractor: str) -> tuple[bool, str]:
    """Re-extract and compare, and say which of the three answers it is.

    Returns `(ok, reason)`. `reason` is empty when `ok`; otherwise it names one of exactly three
    things, and the distinction is the point:

    * **a different extractor** -- the index space is not ours to read, so this is neither a pass
      nor a mismatch. A verifier that reported "mismatch" here would be accusing a driver of
      dishonesty for running on a different machine.
    * **an unresolvable address** -- the range is not in this document.
    * **a mismatch** -- the address resolved and the text differs. This is the only one that is a
      finding about the driver, and it is what INV-10 exists to catch.
    """
    if extractor != EXTRACTOR:
        return False, f"recorded extractor {extractor!r}, this one is {EXTRACTOR!r}"
    got = extract(pdf, start, length)
    if got is None:
        return False, f"glyph range [{start}, {start + length}) is not in this document"
    if got != unicodedata.normalize("NFC", text):
        return False, f"re-extracted {got[:80]!r}, block text is {text[:80]!r}"
    return True, ""
