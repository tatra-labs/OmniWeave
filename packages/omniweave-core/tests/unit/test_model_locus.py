"""`omniweave_core.model.locus`: INV-9's biconditional as a type, and the Block half of `locate()`.

V01-6 (00-vision.md:707): *"`Locus.reason` is non-`None` iff `quad is None`, over every fixture"*.
The type is where it holds, so these tests build `Locus` values directly and through `locate()`.
The fixtures half, every block of three real stores, is `test_owdoc_roundtrip.py` section 7.
"""

from __future__ import annotations

import dataclasses

import pytest
from omniweave_core.model.block import Block
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.locus import NO_SPATIAL, Locus, LocusPrecision, locate
from omniweave_core.model.spans import OriginGlyphs, OriginNone, Quad, TextSpan

QUAD = Quad(10_000, 20_000, 90_000, 20_000, 90_000, 44_000, 10_000, 44_000)
DRIVER = "parse.office.anydoc"


def _block(**changes: object) -> Block:
    fields: dict[str, object] = {
        "id": 918_324,
        "addr": "p13/7",
        "cite": "d7#412",
        "doc_ord": 7,
        "gen": 3,
        "page": 13,
        "parent": None,
        "ord": 7,
        "kind": Kind.PARAGRAPH,
        "raw_kind": None,
        "layer": Layer.BODY,
        "label": None,
        "text": "Acme Holdings Ltd is the Buyer",
        "content_digest": b"\x00" * 16,
        "layout_digest": None,
        "revision": 0,
        "quad": None,
        "origin": OriginNone(),
        "span": None,
        "producer_id": 1,
        "method": Method.NATIVE,
        "trust": Trust.EXTRACTED,
        "quote": Quote.NORMALIZED,
        "origin_driver": DRIVER,
    }
    fields.update(changes)
    return Block(**fields)  # type: ignore[arg-type]


def _locus(**changes: object) -> Locus:
    fields: dict[str, object] = {
        "cite": "d7#412",
        "doc_ord": 7,
        "gen": 3,
        "page": 13,
        "addr": "p13/7",
        "span": TextSpan(0, 4),
        "quad": QUAD,
        "precision": LocusPrecision.BLOCK,
        "origin": OriginNone(),
        "reason": None,
    }
    fields.update(changes)
    return Locus(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. The type: INV-9's biconditional cannot be broken by construction
# ---------------------------------------------------------------------------


def test_a_quad_and_no_reason_is_a_locus() -> None:
    assert _locus().reason is None


def test_no_quad_and_a_reason_is_a_locus() -> None:
    assert _locus(quad=None, reason="parse.office.anydoc declares spatial=none").quad is None


@pytest.mark.parametrize(
    ("quad", "reason"),
    [(None, None), (QUAD, "a reason beside a quad")],
)
def test_neither_or_both_is_refused(quad: Quad | None, reason: str | None) -> None:
    """ "Where on the page" is never a blank and never an invented box (06:2107)."""
    with pytest.raises(ValueError, match="iff quad is None"):
        _locus(quad=quad, reason=reason)


def test_a_blank_reason_is_no_reason() -> None:
    with pytest.raises(ValueError, match="not be blank"):
        _locus(quad=None, reason="   ")


def test_the_fields_are_the_ten_the_plan_prints_in_its_order() -> None:
    """06:2091-2100's `Locus(...)`, with the glossary's `reason` last, as the example writes it."""
    assert [field.name for field in dataclasses.fields(Locus)] == [
        "cite",
        "doc_ord",
        "gen",
        "page",
        "addr",
        "span",
        "quad",
        "precision",
        "origin",
        "reason",
    ]


def test_precision_is_the_five_member_vocabulary_tightest_first() -> None:
    """06:2103-2106, and not `enum_val`'s `precision` domain, which is `TimePrecision`'s."""
    assert [member.value for member in LocusPrecision] == ["char", "line", "block", "page", "none"]


# ---------------------------------------------------------------------------
# 2. `locate(block)`
# ---------------------------------------------------------------------------


def test_a_block_with_a_quad_locates_to_it_with_no_reason() -> None:
    origin = OriginGlyphs(part="file", extractor="pdfium@6045", start=15_221, length=812)
    locus = locate(_block(quad=QUAD, origin=origin), declared_spatial="block_bbox")
    assert (locus.quad, locus.reason, locus.origin) == (QUAD, None, origin)
    assert (locus.cite, locus.doc_ord, locus.gen, locus.page, locus.addr) == (
        "d7#412",
        7,
        3,
        13,
        "p13/7",
    )
    assert locus.precision is LocusPrecision.BLOCK


def test_a_block_with_no_quad_names_its_driver_and_the_declared_spatial() -> None:
    """06:2109's own sentence for an anydoc DOCX."""
    locus = locate(_block(), declared_spatial=NO_SPATIAL)
    assert locus.quad is None
    assert locus.reason == "parse.office.anydoc declares spatial=none"
    assert locus.precision is LocusPrecision.BLOCK


def test_a_driver_that_declares_geometry_and_stored_none_here_says_which_block() -> None:
    locus = locate(_block(kind=Kind.DOCUMENT, text=None), declared_spatial="block_bbox")
    assert locus.reason == (
        "parse.office.anydoc declares spatial=block_bbox and stored no quad for this document block"
    )


def test_an_unnamed_driver_is_named_as_such() -> None:
    locus = locate(_block(origin_driver=""), declared_spatial=NO_SPATIAL)
    assert locus.reason == "an unnamed driver declares spatial=none"


def test_the_span_defaults_to_the_whole_text_and_a_given_one_is_kept() -> None:
    block = _block()
    assert locate(block, declared_spatial=NO_SPATIAL).span == TextSpan(0, len(block.text or ""))
    narrowed = locate(block, declared_spatial=NO_SPATIAL, span=TextSpan(0, 17))
    assert narrowed.span == TextSpan(0, 17)
    assert narrowed.precision is LocusPrecision.BLOCK, "a sub-block span is not narrowed here"


def test_a_span_past_the_text_is_refused() -> None:
    """P8's third inequality, `ts_b <= len(text)` (03:2992), checked by `TextSpan.slice_of`."""
    with pytest.raises(ValueError, match="outside a text"):
        locate(_block(), declared_spatial=NO_SPATIAL, span=TextSpan(0, 999))


def test_a_textless_block_has_the_empty_span() -> None:
    locus = locate(_block(kind=Kind.TABLE, text=None), declared_spatial=NO_SPATIAL)
    assert locus.span == TextSpan(0, 0)
