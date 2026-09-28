"""`omniweave_pdf.signals`: the `pdfium` provider's computer, over real files.

Three keys, each checked against the thing it claims to count: `decode.char_count` against the
glyph index space `glyphs.document_text` defines, `unit.part_count` against the generated page
count, and `corpus.is_form` against a PDF built here with and without an `/AcroForm`. Every key is
also a row of this package's `signals.toml`, and an asked key the module does not compute is absent
from the answer rather than guessed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from omniweave_pdf import signals
from omniweave_pdf.glyphs import document_text

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SIGNALS_TOML = Path(__file__).resolve().parents[2] / "src/omniweave_pdf/signals.toml"
KEYS = ("unit.part_count", "corpus.is_form", "decode.char_count")


def _pdf(catalog_extra: bytes = b"") -> bytes:
    """One blank 200 pt page, uncompressed, with a classic xref: the smallest file pdfium opens."""
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R " + catalog_extra + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    )
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


@pytest.mark.parametrize(
    ("name", "pages"), [("gen01p.pdf", 1), ("gen02p.pdf", 2), ("gen08p.pdf", 8)]
)
def test_the_char_count_is_the_glyph_index_space_and_the_part_count_the_pages(
    name: str, pages: int
) -> None:
    raw = (FIXTURES / name).read_bytes()
    found = signals.compute(raw, KEYS)
    assert found == {
        "unit.part_count": pages,
        "corpus.is_form": False,
        "decode.char_count": len(document_text(raw)),
    }
    count = found["decode.char_count"]
    assert isinstance(count, int)
    assert count > 0


def test_a_page_with_no_text_layer_counts_zero_which_is_what_the_scanned_rule_reads() -> None:
    """`decode.no-text-layer` is `decode.char_count = 0`, so zero is a value, never UNKNOWN."""
    found = signals.compute((FIXTURES / "no_text_layer.pdf").read_bytes(), KEYS)
    assert found["decode.char_count"] == 0
    assert found["unit.part_count"] == 1


def test_a_catalog_with_an_acroform_is_a_form_and_one_without_is_not() -> None:
    assert signals.compute(_pdf(b"/AcroForm << /Fields [] >>"), ("corpus.is_form",)) == {
        "corpus.is_form": True
    }
    assert signals.compute(_pdf(), ("corpus.is_form",)) == {"corpus.is_form": False}


def test_only_the_asked_keys_are_answered_and_an_unknown_one_is_absent() -> None:
    raw = (FIXTURES / "gen01p.pdf").read_bytes()
    assert signals.compute(raw, ("unit.part_count", "ink.tiles")) == {"unit.part_count": 1}


def test_asked_for_nothing_it_computes_it_does_not_open_the_bytes() -> None:
    """`ink.tiles` alone on bytes pdfium would refuse: nothing opened, so nothing raised."""
    assert signals.compute(b"not a pdf", ("ink.tiles",)) == {}


def test_bytes_pdfium_will_not_open_raise_pdfium_s_own_error() -> None:
    """The child turns the raise into every asked key's reason (`host.signals.answer`)."""
    with pytest.raises(pdfium.PdfiumError):
        signals.compute((FIXTURES / "truncated.pdf").read_bytes(), KEYS)


def test_every_computed_key_is_a_pdfium_row_of_this_package_s_signals_toml() -> None:
    rows = tomllib.loads(SIGNALS_TOML.read_text(encoding="utf-8"))["signal"]
    for key in signals.COMPUTES:
        assert key in rows, key
        assert rows[key]["serves"] == ["pdf"]
        assert rows[key]["cost_class"] == "free", "a computer here answers the FREE group only"
