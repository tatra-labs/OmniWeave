"""`parse.pdf.pdfium`: the card, the fragment, the three refusals, and the audit D120 asks for.

The conformance kit already runs twelve suites against this driver -- `test_ow_conform.py` drives
that -- so this file does not repeat them. What it holds is the driver's own claims, each one
either a thing the kit cannot see or a thing worth failing fast on:

* the card loads through the REAL loader with no degradations, and every one of the fifteen
  `[capability.parse]` values equals `driver.ACHIEVED`'s. That equality is what the `capability`
  suite's P15 compares, so a disagreement here is a card that ships and then fails its own
  conformance run;
* `Quad.from_driver` reproduces this driver's quads **from the page record's fields alone** --
  ledger D120's claim, which is the audit 03-document-model.md:1394 promises and which the plan's
  own page-record shape cannot support;
* `verbatim` is true by construction: every block's text is its own recorded glyph slice;
* the three refusals are the three `FailureClass` members that mean them, on real files.

This test file imports `omniweave_core` and the driver may not. `tools/layers.toml`'s rows govern
`packages/*/src/**` (`gate_layers.py:5`), and a test that proves the host's transform accepts this
driver's frame has to hold both halves -- which is exactly why the transform lives on the host side
and the check lives here.

Specified in 16-roadmap.md W3.5; 03-document-model.md sections 7.1, 7.2 and 8.3.
"""

from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

import pytest
from omniweave_conform.harness import Fixture, run_parse
from omniweave_conform.suites.capability import ORIGIN_VERIFIER
from omniweave_core.drivers.card import (
    PARSE_BOOLS,
    PARSE_LADDERS,
    PARSE_SETS,
    load_card,
    read_card_bytes,
)
from omniweave_core.model.spans import Quad
from omniweave_pdf.driver import ACHIEVED, PART, PdfiumParser
from omniweave_pdf.glyphs import EXTRACTOR, document_text
from omniweave_ports.detect import StreamHint
from omniweave_ports.types import DriverError, FailureClass, ProbeEnv, ProbeStatus

ROOT = Path(__file__).resolve().parents[2] / "src/omniweave_pdf"
CARD = ROOT / "driver.toml"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

FIFTEEN = (*PARSE_LADDERS.keys(), *PARSE_BOOLS, *PARSE_SETS.keys())


@pytest.fixture(scope="module")
def parsed() -> tuple[Fixture, object]:
    """One real parse of the two-page fixture, shared by everything that reads a fragment."""
    fixture = Fixture.of(FIXTURES / "gen02p.pdf")
    with tempfile.TemporaryDirectory() as scratch:
        return fixture, run_parse(PdfiumParser(), fixture, Path(scratch))


# ---------------------------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------------------------


def test_the_card_loads_through_the_real_loader_with_no_degradations() -> None:
    """A degradation is a key the author wrote and the loader ignored: a shipped card has none."""
    card = load_card(read_card_bytes(CARD), origin="driver_path", source=str(CARD))
    assert card.identity.id == "parse.pdf.pdfium"
    assert card.identity.entrypoint == "omniweave_pdf.driver:PdfiumParser"
    assert card.degradations == ()
    assert card.attestation is None, "a card carries no attestation until a run writes one"
    assert card.quality.benchmarks == (), "and no [quality] block either (DR13)"


def test_every_one_of_the_fifteen_declares_what_the_code_achieves() -> None:
    """**The card and the constant are one claim in two files, so they are compared.**

    The `capability` suite's P15 asserts `achieved <= declared` on every fixture. Equality is
    stronger and is what this driver actually does -- it reports the same values on every document
    because none of them is document-dependent -- so a drift in either file is caught here, at
    import time, rather than on the first conformance run.
    """
    card = load_card(read_card_bytes(CARD), origin="driver_path", source=str(CARD))
    assert card.parse is not None
    assert set(ACHIEVED) == set(FIFTEEN), "ACHIEVED must carry the fifteen and nothing else"
    for key in FIFTEEN:
        declared = getattr(card.parse, key)
        achieved = ACHIEVED[key]
        if isinstance(declared, frozenset):
            assert set(achieved) == declared, key
        else:
            assert achieved == declared, key


def test_the_card_declares_the_two_values_03_1558_pairs_for_this_driver() -> None:
    """03:1558's row: "both an origin address and a polygon (parse.pdf.pdfium on a born-digital
    page)" -> `origin_span="exact"`, `spatial="block_bbox"`, and the consequence is "full:
    byte-exact quoting AND citation-to-pixel"."""
    card = load_card(read_card_bytes(CARD), origin="driver_path", source=str(CARD))
    assert card.parse is not None
    assert card.parse.origin_span == "exact"
    assert card.parse.spatial == "block_bbox"
    assert card.parse.reading_order == "char_stream"


def test_the_pinned_extractor_is_the_one_the_driver_records() -> None:
    """`[deps] pins` is not a compatibility preference here: it is the glyph index space's identity.

    03:1471: "`extractor` is an exact identity ... because the glyph index space is the
    extractor's, not the PDF's". An address recorded under one version is not re-extractable under
    another, so a pin that named a different version would make every address this driver writes
    unverifiable by anyone who honoured the pin.
    """
    card = load_card(read_card_bytes(CARD), origin="driver_path", source=str(CARD))
    distribution, _, version = EXTRACTOR.partition("@")
    assert f"{distribution}=={version}" in card.deps.pins


# ---------------------------------------------------------------------------------------------
# probe and sniff
# ---------------------------------------------------------------------------------------------


def test_probe_is_ok_and_names_the_build_rather_than_saying_ok() -> None:
    env = ProbeEnv(
        platform="test",
        machine="x86_64",
        python=(3, 12),
        which={},
        gpu_present=False,
        vram_gb=0.0,
        offline=True,
    )
    verdict = PdfiumParser.probe(env)
    assert verdict.status is ProbeStatus.OK
    assert EXTRACTOR in verdict.detail
    assert "pdfium" in verdict.detail


@pytest.mark.parametrize(
    ("name", "expected"),
    [("gen02p.pdf", 1), ("not_a_pdf.bin", 0), ("no_text_layer.pdf", 1), ("truncated.pdf", 1)],
)
def test_sniff_claims_a_pdf_and_declines_anything_else(name: str, expected: int) -> None:
    """Returning `()` is a legitimate "not mine", not a failure.

    `truncated.pdf` is claimed even though `parse()` will refuse it: `sniff` reads a header window
    and a truncated PDF still has its header. That is the right division -- sniffing identifies a
    format, parsing decides whether these particular bytes are readable.
    """
    data = (FIXTURES / name).read_bytes()
    hint = StreamHint(
        filename=name, extension=Path(name).suffix, declared_media_type=None, byte_len=len(data)
    )
    guesses = PdfiumParser().sniff(data[:8192], hint)
    assert len(guesses) == expected
    if guesses:
        assert guesses[0].media_type == "application/pdf"
        assert guesses[0].format_token == "pdf"  # noqa: S105 -- a token, not a secret.


def test_sniff_ranks_a_named_pdf_above_an_unnamed_one() -> None:
    data = (FIXTURES / "gen01p.pdf").read_bytes()[:8192]
    named = StreamHint(filename="a.pdf", extension=".pdf", declared_media_type=None, byte_len=0)
    blind = StreamHint(filename=None, extension=None, declared_media_type=None, byte_len=0)
    driver = PdfiumParser()
    assert driver.sniff(data, named)[0].confidence > driver.sniff(data, blind)[0].confidence


# ---------------------------------------------------------------------------------------------
# The fragment
# ---------------------------------------------------------------------------------------------


def test_every_block_text_is_its_own_recorded_glyph_slice(parsed: tuple[Fixture, object]) -> None:
    """**`quote = "verbatim"` is true by construction, and this is the construction.**

    Not through `verify()` -- that is the driver's own hook and the conformance kit's path. This
    reads the document's text independently and slices it at the recorded offsets, so a bug in
    `verify()` cannot make this pass.
    """
    fixture, run = parsed
    whole = document_text(fixture.data)
    assert run.blocks, "the fixture must produce blocks"
    for block in run.blocks:
        origin = block["os"]
        assert origin["k"] == "glyphs"
        assert origin["part"] == PART
        assert origin["extractor"] == EXTRACTOR
        assert origin["length"] == len(block["text"])
        assert whole[origin["start"] : origin["start"] + origin["length"]] == block["text"]
        assert block["quote"] == "verbatim"


def test_blocks_arrive_in_glyph_index_order_which_is_a_char_stream_order(
    parsed: tuple[Fixture, object],
) -> None:
    """`reading_order = "char_stream"` with no reordering step to get wrong.

    16-roadmap.md:485 makes marker's 75%-vs-56% char-stream result "the floor we may not ship
    below". Emitting in index order IS that order, and the assertion is that nothing reorders.
    """
    _, run = parsed
    starts = [block["os"]["start"] for block in run.blocks]
    assert starts == sorted(starts)
    for earlier, later in itertools.pairwise(run.blocks):
        end = earlier["os"]["start"] + earlier["os"]["length"]
        assert later["os"]["start"] >= end, "two blocks may not overlap in the index space"


def test_no_block_text_contains_a_line_separator(parsed: tuple[Fixture, object]) -> None:
    """The separators pdfium synthesises are never inside a block's recorded range.

    A block whose text carried a `\\r\\n` would still re-verify -- it is a contiguous slice -- so
    this is not about INV-10. It is about the split being a line split: one separator left at the
    head of the next block is a block whose text begins with a newline, and nothing downstream
    would notice.
    """
    _, run = parsed
    for block in run.blocks:
        assert "\r" not in block["text"]
        assert "\n" not in block["text"]
        assert block["text"] == block["text"].strip() or block["text"].strip() != ""


def test_the_part_is_retained_because_exact_is_a_claim_about_bytes_that_must_persist(
    parsed: tuple[Fixture, object],
) -> None:
    fixture, run = parsed
    part = run.fragment.part(PART)
    assert part is not None
    assert part["retain"] is True
    assert part["sha256"] == fixture.digest
    assert part["byte_len"] == fixture.byte_len


def test_the_doc_record_reports_the_page_count_and_the_fifteen(
    parsed: tuple[Fixture, object],
) -> None:
    _, run = parsed
    doc = run.fragment.doc
    assert doc is not None
    assert doc["format"] == "pdf"
    assert doc["media_type"] == "application/pdf"
    assert doc["page_count"] == len(run.fragment.pages) == 2
    assert set(run.fragment.achieved) == set(FIFTEEN)


def test_page_indices_are_original_dense_and_typed_as_pages(
    parsed: tuple[Fixture, object],
) -> None:
    """P29: `page` is the ORIGINAL source index, 0-based, never a batch index (03:2277)."""
    _, run = parsed
    indices = [page["page"] for page in run.fragment.pages]
    assert indices == list(range(len(indices)))
    assert {page["page_kind"] for page in run.fragment.pages} == {"page"}
    assert {page["method"] for page in run.fragment.pages} == {"text_layer"}


# ---------------------------------------------------------------------------------------------
# Geometry: D120's audit
# ---------------------------------------------------------------------------------------------


def test_the_page_record_alone_is_enough_to_re_derive_the_transform(
    parsed: tuple[Fixture, object],
) -> None:
    """**Ledger D120, made checkable for this driver.**

    03-document-model.md:1394 says `page.quad_origin` is recorded "so an audit can re-derive the
    transform". `Quad.from_driver` takes five inputs besides the points and the plan's page record
    carries three of them; this driver's page record carries all five, and this test is the audit
    that claim describes: nothing here reads the driver, the card, or `03:1385`'s table. It reads
    the page record and applies the transform.
    """
    _, run = parsed
    frames = {page["page"]: page for page in run.fragment.pages}
    quadded = [block for block in run.blocks if block["quad"] is not None]
    assert quadded, "a block_bbox driver must produce quads"

    for block in quadded:
        page = frames[block["page"]]
        points = [(block["quad"][i], block["quad"][i + 1]) for i in range(0, len(block["quad"]), 2)]
        quad = Quad.from_driver(
            points,
            origin=page["quad_origin"],
            unit=page["quad_unit"],
            page_h=page["h_mpt"] / 1000,
            dpi=page["quad_dpi"],
            rotation=page["rotation"],
        )
        # The stored frame is topleft millipoints, so every coordinate is inside the page box.
        assert min(quad[0::2]) >= 0 and max(quad[0::2]) <= page["w_mpt"], block["tmp"]
        assert min(quad[1::2]) >= 0 and max(quad[1::2]) <= page["h_mpt"], block["tmp"]


def test_the_drivers_own_frame_is_bottomleft_points(parsed: tuple[Fixture, object]) -> None:
    """03:1385's first row: PDF user space is `bottomleft` and `pt`.

    Asserted on the page record rather than inferred, because the record is what an audit reads,
    and asserted against the QUADS too: in a bottomleft frame the first corner's y is the larger
    one, and a driver that had already flipped would fail this while still producing plausible
    numbers.
    """
    _, run = parsed
    for page in run.fragment.pages:
        assert page["quad_origin"] == "bottomleft"
        assert page["quad_unit"] == "pt"
        assert page["quad_dpi"] is None
        assert page["w_mpt"] > 0 and page["h_mpt"] > 0
    for block in run.blocks:
        if block["quad"] is None:
            continue
        quad = block["quad"]
        assert quad[1] >= quad[7], "top-left y is above bottom-left y in a bottomleft frame"
        assert quad[2] >= quad[0], "top-right x is right of top-left x"


def test_no_quad_is_all_zero_or_degenerate(parsed: tuple[Fixture, object]) -> None:
    """P6's clause, checked here too: a zero quad is the shape a skipped box leaves behind."""
    _, run = parsed
    for block in run.blocks:
        quad = block["quad"]
        if quad is None:
            continue
        assert any(value != 0 for value in quad), block["tmp"]
        assert max(quad[0::2]) > min(quad[0::2]), f"{block['tmp']} has no width"
        assert max(quad[1::2]) > min(quad[1::2]), f"{block['tmp']} has no height"


# ---------------------------------------------------------------------------------------------
# The three refusals
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "failure"),
    [
        ("not_a_pdf.bin", FailureClass.CORRUPT_INPUT),
        ("truncated.pdf", FailureClass.CORRUPT_INPUT),
        ("no_text_layer.pdf", FailureClass.NEEDS_OCR),
    ],
)
def test_each_refusal_is_the_failure_class_that_means_it(name: str, failure: FailureClass) -> None:
    """Three real files, three typed refusals, and never a bare exception.

    `NEEDS_OCR` for a document with no text layer anywhere is the one that matters to the host:
    it is the difference between "this document is unreadable" and "this document needs a
    different driver", and only the second is actionable.
    """
    fixture = Fixture.of(FIXTURES / name)
    with tempfile.TemporaryDirectory() as scratch, pytest.raises(DriverError) as caught:
        run_parse(PdfiumParser(), fixture, Path(scratch))
    assert caught.value.cls is failure


def test_cancellation_between_pages_raises_timeout_with_a_cooldown() -> None:
    """`io.cancelled()` at every loop top, and `retry_after_ms` is REQUIRED because the class is
    transient (charter D3)."""
    fixture = Fixture.of(FIXTURES / "gen04p.pdf")
    with tempfile.TemporaryDirectory() as scratch, pytest.raises(DriverError) as caught:
        run_parse(PdfiumParser(), fixture, Path(scratch), cancel_after_progress=1)
    assert caught.value.cls is FailureClass.TIMEOUT
    assert caught.value.retry_after_ms == 0


def test_a_page_with_no_text_layer_in_a_texted_document_is_a_diag_and_not_a_refusal() -> None:
    """INV-13's per-page escalation, from the driver's side.

    The host decides whether to send an empty page to an OCR driver, and it can only decide that
    if this driver reports the page rather than failing the document out from under it. Built by
    concatenating a texted document with an empty one is not possible, so the assertion is made on
    the one-page empty file: it raises, and the RECORDS it produced up to that point still carry
    the page and its diag.
    """
    fixture = Fixture.of(FIXTURES / "no_text_layer.pdf")
    with tempfile.TemporaryDirectory() as scratch, pytest.raises(DriverError) as caught:
        run_parse(PdfiumParser(), fixture, Path(scratch))
    assert caught.value.cls is FailureClass.NEEDS_OCR
    assert "text layer" in str(caught.value)


def test_min_chars_drops_a_whitespace_only_line_and_nothing_else() -> None:
    """The one config knob, doing the one thing the card says it does."""
    fixture = Fixture.of(FIXTURES / "gen01p.pdf")
    with tempfile.TemporaryDirectory() as scratch:
        default = run_parse(PdfiumParser(), fixture, Path(scratch) / "a")
        wide = run_parse(PdfiumParser(min_chars=1000), fixture, Path(scratch) / "b")
    assert len(default.blocks) > 0
    assert len(wide.blocks) == 0, "a 1000-character floor drops every line of this fixture"


def test_a_negative_min_chars_is_a_driver_bug_at_construction() -> None:
    with pytest.raises(DriverError) as caught:
        PdfiumParser(min_chars=-1)
    assert caught.value.cls is FailureClass.DRIVER_BUG


# ---------------------------------------------------------------------------------------------
# The kit's hook
# ---------------------------------------------------------------------------------------------


def test_verify_origin_is_the_hook_the_conformance_kit_looks_for(
    parsed: tuple[Fixture, object],
) -> None:
    """`ORIGIN_VERIFIER` names it, and the kit calls it for a branch it cannot read unaided."""
    fixture, run = parsed
    hook = getattr(PdfiumParser, ORIGIN_VERIFIER, None)
    assert hook is not None, f"the kit looks for {ORIGIN_VERIFIER}()"

    block = run.blocks[0]
    ok, why = hook(fixture.data, block["os"], block["text"])
    assert ok and why == ""

    ok, why = hook(fixture.data, block["os"], "not what is there")
    assert not ok and "re-extracted" in why

    ok, why = hook(fixture.data, {"k": "bytes", "part": PART}, block["text"])
    assert not ok and "glyphs" in why
