"""`omniweave_conform.pdfcrypt`, the `encrypt` Injector's transform, checked by its reader.

Here and not in the kit's own tests because the proof that an encryption is an encryption is that
pdfium refuses the file without the password and reads the same text with it, and pypdfium2 is
this package's dependency, not the kit's (ADR-15 D15.6).
"""

from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from omniweave_conform.pdfcrypt import PERMISSIONS, encrypt_pdf

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
USER, OWNER = "s3cret", "owner"


def _text(raw: bytes, password: str | None = None) -> str:
    document = pdfium.PdfDocument(raw, password=password)
    try:
        return "".join(
            document[index].get_textpage().get_text_range() for index in range(len(document))
        )
    finally:
        document.close()


@pytest.mark.parametrize("name", ["gen01p.pdf", "gen02p.pdf", "gen08p.pdf"])
def test_a_user_password_makes_the_file_unreadable_without_it_and_the_same_with_it(
    name: str,
) -> None:
    raw = (FIXTURES / name).read_bytes()
    locked = encrypt_pdf(raw, user_password=USER, owner_password=OWNER)
    with pytest.raises(pdfium.PdfiumError, match="password"):
        pdfium.PdfDocument(locked)
    assert _text(locked, USER) == _text(raw)
    assert _text(locked, OWNER) == _text(raw)


def test_an_empty_user_password_is_an_owner_only_file_that_opens_with_none() -> None:
    """ADR-15 D15.2's case: `/Encrypt` present, and readable with no password at all."""
    raw = (FIXTURES / "gen02p.pdf").read_bytes()
    restricted = encrypt_pdf(raw, user_password="", owner_password=OWNER)
    assert b"/Encrypt" in restricted
    assert _text(restricted) == _text(raw)


def test_every_string_is_encrypted_and_decrypts_back() -> None:
    """ISO 32000-1 7.6.2: strings as well as streams. The fixture's Info dictionary names its
    producer in clear, and the encrypted file does not, yet pdfium reads the value back."""
    raw = (FIXTURES / "gen02p.pdf").read_bytes()
    with pdfium.PdfDocument(raw) as document:
        metadata = document.get_metadata_dict()
    locked = encrypt_pdf(raw, user_password=USER, owner_password=OWNER)
    shown = [value for value in metadata.values() if value]
    assert shown
    for value in shown:
        assert value.encode("latin-1") not in locked
    with pdfium.PdfDocument(locked, password=USER) as document:
        assert document.get_metadata_dict() == metadata


def test_the_handler_is_revision_3_rc4_128_with_the_stated_permissions() -> None:
    locked = encrypt_pdf(
        (FIXTURES / "gen01p.pdf").read_bytes(), user_password=USER, owner_password=OWNER
    )
    handler = re.search(rb"<< /Filter /Standard (.*?) >>", locked)
    assert handler is not None
    assert b"/V 2 /R 3 /Length 128" in handler.group(1)
    assert f"/P {PERMISSIONS}".encode() in handler.group(1)


def test_every_xref_offset_names_its_object_and_the_output_is_deterministic() -> None:
    raw = (FIXTURES / "gen04p.pdf").read_bytes()
    locked = encrypt_pdf(raw, user_password=USER, owner_password=OWNER)
    assert locked == encrypt_pdf(raw, user_password=USER, owner_password=OWNER)
    table = locked[locked.rindex(b"\nxref\n") :]
    entries = re.findall(rb"(\d{10}) (\d{5}) n ", table)
    assert entries
    for number, (offset, _generation) in enumerate(entries, start=1):
        assert locked[int(offset) :].startswith(f"{number} ".encode())


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"%PDF-1.7\n1 0 obj\n<< /Type /ObjStm >>\nendobj\n", "an object stream"),
        (b"%PDF-1.7\n1 0 obj\n<< /Type /XRef >>\nendobj\n", "a cross-reference stream"),
        (b"%PDF-1.7\ntrailer << /Encrypt 5 0 R >>", "an encryption dictionary already"),
        (b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\n%%EOF\n", "classic xref"),
    ],
)
def test_a_pdf_it_does_not_write_is_refused_by_name(data: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        encrypt_pdf(data, user_password=USER, owner_password=OWNER)
