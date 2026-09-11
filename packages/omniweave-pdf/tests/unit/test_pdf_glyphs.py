"""The glyph index space, and the three-way identity everything in it rests on.

`glyphs.py`'s whole contract is that a glyph index is a position in the document-global
concatenation of pdfium's per-page character sequences. Three claims make that usable and this file
checks each of them against a real PDF rather than against a mock:

1. **`FPDFText_CountChars(p) == len(get_text_range(0, n)) == len(chr(GetUnicode(i)) for i)`.** A
   slice of the index space is a slice of the text only if the count and the string agree. If they
   ever disagree, every address this driver records is off by the difference and `verbatim` is a
   lie -- so it is asserted rather than assumed, per the module docstring's own promise.
2. **`extract(pdf, a, n) == nfc(document_text(pdf)[a : a+n])`.** The streaming reader and the
   materialised definition give the same answer, including across a page boundary, which is the
   case a per-page implementation gets wrong.
3. **`verify()` distinguishes three answers.** A different extractor is not a mismatch, an
   unresolvable address is not a mismatch, and only a resolved address whose text differs is a
   finding about the driver. Collapsing those into a bool would make a verifier on another machine
   report dishonesty.

Specified in 03-document-model.md sections 7.2 and 8.3; INV-10.
"""

from __future__ import annotations

import ctypes
import itertools
import re
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import pytest
from omniweave_pdf.glyphs import (
    EXTRACTOR,
    document_text,
    extract,
    page_texts,
    pdfium_build,
    verify,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
GEN02 = FIXTURES / "gen02p.pdf"
GEN04 = FIXTURES / "gen04p.pdf"


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return GEN02.read_bytes()


def test_the_count_the_range_and_the_characters_all_agree(pdf: bytes) -> None:
    """Claim 1, per page, on a real document.

    Three ways of asking pdfium how long a page's text is, which must give one answer. The
    per-character loop is the slow, literal reading of "the character sequence"; `get_text_range`
    is what `page_text()` actually calls; `FPDFText_CountChars` is what the offsets are computed
    from. A disagreement between any two of them shifts every address on that page.
    """
    with pdfium.PdfDocument(pdf) as document:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                count = pdfium_raw.FPDFText_CountChars(textpage.raw)
                by_range = textpage.get_text_range(0, count)
                by_char = "".join(
                    chr(pdfium_raw.FPDFText_GetUnicode(textpage.raw, i)) for i in range(count)
                )
            finally:
                textpage.close()
                page.close()
            assert count > 0, f"page {index} of the fixture must carry a text layer"
            assert len(by_range) == count
            assert by_char == by_range


def test_page_offsets_are_the_running_total_and_tile_the_document(pdf: bytes) -> None:
    """Every page starts where the previous one ended, and together they are the whole space."""
    whole = document_text(pdf)
    with pdfium.PdfDocument(pdf) as document:
        parts = list(page_texts(document))
    assert [part.index for part in parts] == list(range(len(parts)))
    assert parts[0].start == 0
    for earlier, later in itertools.pairwise(parts):
        assert later.start == earlier.end
    assert sum(part.length for part in parts) == len(whole)
    assert "".join(part.text for part in parts) == whole


@pytest.mark.parametrize("offset", [0, 1, 33, 500])
@pytest.mark.parametrize("length", [1, 7, 40])
def test_extract_agrees_with_the_materialised_definition(
    pdf: bytes, offset: int, length: int
) -> None:
    """Claim 2: the streaming reader and the definition give one answer."""
    whole = document_text(pdf)
    assert extract(pdf, offset, length) == unicodedata.normalize(
        "NFC", whole[offset : offset + length]
    )


def test_extract_spans_a_page_boundary(pdf: bytes) -> None:
    """The case a per-page implementation gets wrong, asked directly.

    A range that starts on page 0 and ends on page 1 has to be stitched from two pages' text, and
    an implementation that resolved an index to one page would return a short string or the wrong
    one. The fixture's first page boundary is where the assertion is aimed.
    """
    whole = document_text(pdf)
    with pdfium.PdfDocument(pdf) as document:
        boundary = next(page_texts(document)).length
    span = 20
    start = boundary - span // 2
    got = extract(pdf, start, span)
    assert got == unicodedata.normalize("NFC", whole[start : start + span])
    assert got is not None
    assert len(got) == span


def test_a_range_past_the_end_is_none_rather_than_a_short_string(pdf: bytes) -> None:
    """`None` rather than truncation: a suite must tell "not here" from "differs"."""
    whole = document_text(pdf)
    assert extract(pdf, len(whole) - 3, 10) is None
    assert extract(pdf, len(whole) + 1, 1) is None
    assert extract(pdf, -1, 5) is None
    assert extract(pdf, 0, -5) is None


def test_a_zero_length_range_is_the_empty_string_and_not_none(pdf: bytes) -> None:
    """An empty block is a driver bug, not an unresolvable address; the reader says which."""
    assert extract(pdf, 0, 0) == ""


def test_the_extractor_identity_matches_the_cards_grammar() -> None:
    """03:740's pattern for `os.extractor`: `^[a-z0-9_.-]+@[0-9A-Za-z.+-]+$`."""
    assert re.fullmatch(r"[a-z0-9_.-]+@[0-9A-Za-z.+-]+", EXTRACTOR), EXTRACTOR
    assert EXTRACTOR.startswith("pypdfium2@")
    assert pdfium_build() and pdfium_build() != EXTRACTOR


def test_verify_returns_three_distinguishable_answers(pdf: bytes) -> None:
    """Claim 3. A verifier that collapsed these would accuse a driver of dishonesty for
    running on a different machine, which is the one thing an attestation mechanism may not do."""
    whole = document_text(pdf)
    text = whole[0:33]

    ok, why = verify(pdf, 0, 33, text, EXTRACTOR)
    assert ok and why == ""

    ok, why = verify(pdf, 0, 33, "something else entirely", EXTRACTOR)
    assert not ok
    assert "re-extracted" in why, why

    ok, why = verify(pdf, len(whole) + 10, 33, text, EXTRACTOR)
    assert not ok
    assert "not in this document" in why, why

    ok, why = verify(pdf, 0, 33, text, "pdftext@0.6")
    assert not ok
    assert "recorded extractor" in why, why
    assert "re-extracted" not in why, "a different extractor is not a mismatch"


def test_verification_is_nfc_and_not_a_casefold(pdf: bytes) -> None:
    """03:1491: `glyphs` re-extracts under NFC. Never `normalize_k`, which casefolds.

    The plan states the consequence directly for the `bytes` branch (03:2991: "a fixture whose
    retained part reads `ABC` and whose `text` is `abc` **must fail**") and all three branches now
    agree on `nfc()`. This is that assertion for the `glyphs` branch: a driver that lower-cased its
    text would be claiming `verbatim` against a page that does not say that.
    """
    text = document_text(pdf)[0:33]
    assert text != text.lower(), "the fixture must contain a capital for this test to mean anything"
    ok, _ = verify(pdf, 0, 33, text.lower(), EXTRACTOR)
    assert not ok


def test_the_index_space_is_stable_across_two_reads(pdf: bytes) -> None:
    """`replay_class = "byte_exact"` is a promise about the addresses too, not only the text."""
    assert document_text(pdf) == document_text(pdf)
    assert extract(pdf, 100, 50) == extract(pdf, 100, 50)


def test_a_longer_document_addresses_its_later_pages_correctly() -> None:
    """Four pages, so a page-3 address is past three earlier pages' worth of offset.

    A one- or two-page fixture cannot distinguish "the running total works" from "the second page
    happens to start where a bug would put it".
    """
    pdf = GEN04.read_bytes()
    whole = document_text(pdf)
    with pdfium.PdfDocument(pdf) as document:
        parts = list(page_texts(document))
    assert len(parts) == 4
    last = parts[-1]
    assert extract(pdf, last.start, 25) == unicodedata.normalize(
        "NFC", whole[last.start : last.start + 25]
    )
    assert last.start > parts[0].length, "the last page must start after the first"


def test_a_char_box_exists_for_every_character_the_count_reports(pdf: bytes) -> None:
    """The geometry half of the same index space: a quad is built from these boxes.

    A character the count reports but `GetCharBox` refuses would leave a hole in a block's quad,
    and the driver's `_quad` skips a refused box -- so this asserts the skip is for degenerate
    boxes rather than for missing ones.
    """
    with pdfium.PdfDocument(pdf) as document:
        page = document[0]
        textpage = page.get_textpage()
        try:
            count = pdfium_raw.FPDFText_CountChars(textpage.raw)
            left, right, bottom, top = (ctypes.c_double() for _ in range(4))
            refused = 0
            for index in range(count):
                if not pdfium_raw.FPDFText_GetCharBox(
                    textpage.raw, index, left, right, bottom, top
                ):
                    refused += 1
        finally:
            textpage.close()
            page.close()
    assert refused == 0, f"{refused} of {count} characters have no box"
