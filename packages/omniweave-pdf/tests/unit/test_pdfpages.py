"""`omniweave_conform.pdfpages`, the `inflate` Injector's transform, checked by its reader. D644.

Here and not in the kit's own tests for `test_pdfcrypt.py`'s reason: the proof that a padded file
has the pages it claims is that pdfium counts them and reads each one's text, and pypdfium2 is this
package's dependency, not the kit's.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from omniweave_conform.pdfcrypt import encrypt_pdf
from omniweave_conform.pdfpages import pad_pages, page_count

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
USER, OWNER = "s3cret", "owner"


def _pages(raw: bytes) -> list[str]:
    document = pdfium.PdfDocument(raw)
    try:
        return [document[i].get_textpage().get_text_range() for i in range(len(document))]
    finally:
        document.close()


@pytest.mark.parametrize(("name", "pages"), [("gen01p.pdf", 1), ("gen02p.pdf", 2)])
def test_a_padded_pdf_has_the_pages_it_was_given_each_with_the_last_page_s_text(
    name: str, pages: int
) -> None:
    raw = (FIXTURES / name).read_bytes()
    assert page_count(raw) == pages
    padded = pad_pages(raw, to_pages=pages + 3)
    assert page_count(padded) == pages + 3
    read = _pages(padded)
    assert read[:pages] == _pages(raw)
    assert read[pages:] == [_pages(raw)[-1]] * 3
    assert pad_pages(raw, to_pages=pages + 3) == padded, "deterministic, one set of bytes"


def test_the_pristine_bytes_are_the_padded_file_s_first_bytes() -> None:
    """An incremental update (ISO 32000-1 §7.5.6): the original is untouched, the new trailer
    names the old one, and the last `startxref` names the new xref table, which is what detection's
    trailer check reads (D641)."""
    raw = (FIXTURES / "gen01p.pdf").read_bytes()
    padded = pad_pages(raw, to_pages=2)
    assert padded.startswith(raw)
    assert b"/Prev " in padded[len(raw) :]
    assert padded.endswith(b"%%EOF\n")
    offset = int(padded.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    assert padded[offset:].startswith(b"xref\n")
    assert offset > len(raw)


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b"not a pdf at all", "classic xref table"),
        (
            encrypt_pdf(
                (FIXTURES / "gen01p.pdf").read_bytes(), user_password=USER, owner_password=OWNER
            ),
            "an encryption dictionary",
        ),
    ],
)
def test_a_pdf_it_cannot_pad_is_refused_by_name(raw: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        pad_pages(raw, to_pages=9)


def test_a_pdf_already_that_long_is_not_one_row_above_anything() -> None:
    raw = (FIXTURES / "gen02p.pdf").read_bytes()
    with pytest.raises(ValueError, match="has 2 already"):
        pad_pages(raw, to_pages=2)
