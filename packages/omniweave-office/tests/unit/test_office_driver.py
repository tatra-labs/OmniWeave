"""`AnydocParser` against the Port contract: one call, five refusals, and an honest `achieved`.

The conform kit runs the twelve suites over this driver and is the authority on the contract; what
is here is what the kit cannot ask, because it does not know anydoc:

* **one FFI call per document.** 02-architecture.md:149 fixes it as the S1 contract and nothing
  else in the tree checks it, because the kit counts blob reads rather than decoder calls.
* **each of anydoc's five error classes lands on the `FailureClass` that means it**, with a
  fixture for each rather than a mock -- a mocked `EncryptedError` proves the mapping and not that
  anydoc raises it for a document an operator would call encrypted.
* **`achieved` is computed per document.** A CSV honestly reports `math = []` and
  `assets = "none"` while the card keeps the higher declaration routing filters on, which is
  03 section 2.9's rollup applied driver-side.

Specified in 16-roadmap.md W3.4; 04-driver-system.md sections 1.3 and 1.4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anydoc
import pytest
from omniweave_conform.harness import Fixture, run_parse
from omniweave_office.driver import MEDIA_TYPES, PART, AnydocParser
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.detect import StreamHint

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def run(name: str, tmp_path: Path, **kwargs: Any) -> Any:
    return run_parse(AnydocParser(), Fixture.of(FIXTURES / name), tmp_path, **kwargs)


def hint(name: str) -> StreamHint:
    return StreamHint(
        filename=name, extension=Path(name).suffix, declared_media_type=None, byte_len=None
    )


# ---------------------------------------------------------------------------
# probe and sniff
# ---------------------------------------------------------------------------


def test_probe_names_the_version_rather_than_saying_ok() -> None:
    """The version IS the decoder: its constants are compile-time and its `Block` set is what
    `origin_span = "none"` is honest about, so "which anydoc" is the first thing a reader needs."""
    verdict = AnydocParser.probe(env=None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.OK
    assert "0.2.4" in verdict.detail


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("rich.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("sheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("sheet.xls", "application/vnd.ms-excel"),
        ("memo.doc", "application/msword"),
        ("deck.ppt", "application/vnd.ms-powerpoint"),
        ("notes.odt", "application/vnd.oasis.opendocument.text"),
        ("sheet.ods", "application/vnd.oasis.opendocument.spreadsheet"),
        ("deck.odp", "application/vnd.oasis.opendocument.presentation"),
        ("book.epub", "application/epub+zip"),
        ("memo.rtf", "application/rtf"),
        ("rows.csv", "text/csv"),
    ],
)
def test_sniff_identifies_every_declared_media_type(name: str, media_type: str) -> None:
    """All twelve, including the two the content detector alone cannot answer.

    `xls` versus `xlsx` is decided by the CONTAINER signature, because anydoc's `xlsx` is a parser
    family covering three container generations. CSV is decided by the filename, because it has no
    signature for anyone to read -- which is why its confidence is deliberately the lowest here.
    """
    data = (FIXTURES / name).read_bytes()
    guesses = AnydocParser().sniff(data[:65_536], hint(name))
    assert len(guesses) == 1, name
    assert guesses[0].media_type == media_type
    assert guesses[0].format_token == MEDIA_TYPES[media_type][1]
    assert 0.0 < guesses[0].confidence <= 0.95


def test_sniff_returns_nothing_for_bytes_that_are_not_a_document() -> None:
    """`()` is a legitimate "not mine", and it is the honest answer rather than a low score."""
    data = (FIXTURES / "not_a_document.bin").read_bytes()
    assert AnydocParser().sniff(data, hint("not_a_document.bin")) == ()


def test_sniff_declines_a_pdf_even_though_anydoc_decodes_one() -> None:
    """`parse.pdf.pdfium` owns that path (04:2564) and the exclusion is enforced at both ends."""
    assert AnydocParser().sniff(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", hint("a.pdf")) == ()


def test_a_csv_without_the_extension_is_not_claimed() -> None:
    """A driver that sniffed CSV from content would claim every comma-separated log in a corpus."""
    data = (FIXTURES / "rows.csv").read_bytes()
    assert AnydocParser().sniff(data, hint("access.log")) == ()


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def test_parse_makes_exactly_one_ffi_call_per_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """02-architecture.md:149's S1 contract, counted.

    "omniweave-office only, one call per document, py.detach for the decode." Two calls would
    double the marshal that `py.detach` does not cover -- F2's whole subject -- and nothing else
    in the tree would notice.
    """
    calls: list[tuple[int, str | None]] = []
    original = anydoc.to_document

    def counted(data: Any, fmt: Any = None) -> Any:
        calls.append((len(data), fmt))
        return original(data, fmt)

    monkeypatch.setattr(anydoc, "to_document", counted)
    run("rich.docx", tmp_path)
    assert len(calls) == 1
    assert calls[0][1] == "docx"


def test_the_fragment_opens_with_doc_part_page_and_ends_with_end(tmp_path: Path) -> None:
    """The record order a host reading line by line depends on (03:2575)."""
    records = run("rich.docx", tmp_path).fragment.records
    assert [r["t"] for r in records[:3]] == ["doc", "part", "page"]
    assert records[-1]["t"] == "end"
    assert records[-1]["status"] == "ok"


def test_the_page_record_is_a_stream_with_no_geometry(tmp_path: Path) -> None:
    """`PageKind.STREAM` exists for exactly this: `w_mpt`/`h_mpt` are NULL.

    An office document has no page box -- pagination is a rendering performed by a layout engine
    this framework does not run -- and anydoc flattens a deck's slides into one block stream. A
    made-up box would be a claim that geometry exists; no page record at all would be a claim that
    the blocks belong to nothing.
    """
    page = run("rich.docx", tmp_path).fragment.pages[0]
    assert page["page_kind"] == "stream"
    assert page["w_mpt"] is None
    assert page["h_mpt"] is None
    assert page["quad_origin"] is None
    assert page["quad_unit"] is None
    assert page["quad_dpi"] is None


def test_the_part_is_not_retained(tmp_path: Path) -> None:
    """`retain = False` because `origin_span = "none"`: there is nothing to re-prove from it.

    `[store] retain_parts = "when_citable"` retains a part so a citation can be re-proved. On this
    path no citation ever can be, so retaining would roughly double corpus storage on a claim
    nothing backs -- F32's own question, answered in the direction the card already implies.
    """
    part = run("rich.docx", tmp_path).fragment.parts[0]
    assert part["path"] == PART
    assert part["retain"] is False
    assert part["byte_len"] == (FIXTURES / "rich.docx").stat().st_size


def test_an_embedded_image_leaves_as_its_own_artifact_ref(tmp_path: Path) -> None:
    """Asset bytes travel through `ArtifactRef.of`, the single metered site (04 section 6.5).

    A record carrying base64 would evade `max_output_bytes` entirely, which is the reason the
    ceiling has one enforcement point rather than one per producer.
    """
    result = run("rich.docx", tmp_path).result
    kinds = [ref.kind for ref in result.produced]
    assert kinds == ["doc_fragment", "asset"]
    assert result.produced[1].byte_len == 70


def test_an_oversized_asset_is_dropped_with_a_diag_and_the_document_survives(
    tmp_path: Path,
) -> None:
    """One oversized logo must not cost a whole deck.

    Dropping silently would leave a `picture` block pointing at bytes that never arrive; refusing
    the document would make the driver's own comfort the operator's problem. The `diag` names the
    part, the byte count and the knob.
    """
    driver = AnydocParser(max_asset_bytes=8)
    fixture = Fixture.of(FIXTURES / "rich.docx")
    result = run_parse(driver, fixture, tmp_path)
    assert [ref.kind for ref in result.result.produced] == ["doc_fragment"]
    diags = [r for r in result.fragment.records if r.get("t") == "diag"]
    assert len(diags) == 1
    assert diags[0]["code"] == "OW_OFFICE_ASSET_DROPPED"
    assert diags[0]["detail"]["limit"] == "max_asset_bytes"
    assert diags[0]["fatal"] is False
    picture = next(b for b in result.fragment.blocks if b["kind"] == "picture")
    assert picture["label"] == "a single grey dot"
    assert picture["assets"] is None
    assert not [r for r in result.fragment.records if r.get("t") == "asset"]


# ---------------------------------------------------------------------------
# the five refusals, one fixture each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "failure"),
    [
        ("deepxml.docx", FailureClass.RESOURCE_LIMIT),
        ("encrypted.odt", FailureClass.ENCRYPTED),
        ("truncated.docx", FailureClass.CORRUPT_INPUT),
        ("memo.doc", FailureClass.CORRUPT_INPUT),
        ("not_a_document.bin", FailureClass.UNSUPPORTED_FORMAT),
    ],
)
def test_each_refusal_lands_on_the_failure_class_that_means_it(
    name: str, failure: FailureClass, tmp_path: Path
) -> None:
    """A fixture per class rather than a mock: a mocked error proves the mapping and nothing else.

    `truncated.docx` and `not_a_document.bin` are deliberately different classes even though both
    are unreadable: anydoc reports the first as `MalformedError` (the ZIP opened far enough to be
    a damaged document) and the second as `UnsupportedError` (nothing recognised it at all).
    Collapsing them would invent a distinction the decoder did not make, or lose one it did.
    """
    with pytest.raises(DriverError) as caught:
        run(name, tmp_path)
    assert caught.value.cls is failure


def test_a_resource_limit_carries_anydocs_own_name_and_a_cooldown(tmp_path: Path) -> None:
    """14:503: the typed error carries anydoc's own limit name so a user reads one vocabulary.

    `retry_after_ms` is required because `RESOURCE_LIMIT` is transient in `omniweave_ports`
    (08-runtime.md:568); 02-architecture.md:1017 says the opposite for the same class and
    `_plan/_notes/build-defects.md` D125 records the contradiction. The cooldown is 08's own
    number and it is a cooldown, not a prediction.
    """
    with pytest.raises(DriverError) as caught:
        run("deepxml.docx", tmp_path)
    assert caught.value.limit == "max_xml_depth"
    assert caught.value.retry_after_ms == 60_000


def test_an_unknown_limit_name_becomes_a_code_and_never_passes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14:505: a name anydoc adds that omniweave has no row for is `OW_SCHEMA_UNKNOWN_KIND`.

    Monkeypatched, because the only way to produce this from a fixture is a future anydoc. The
    boundary is the thing under test and it is reachable no other way.
    """

    def raiser(_data: Any, _fmt: Any = None) -> Any:
        error = anydoc.ResourceLimitError("a limit from the future")
        error.limit = "max_something_nobody_has_seen"
        raise error

    monkeypatch.setattr(anydoc, "to_document", raiser)
    with pytest.raises(DriverError) as caught:
        run("rich.docx", tmp_path)
    assert caught.value.limit == "OW_SCHEMA_UNKNOWN_KIND"


# ---------------------------------------------------------------------------
# achieved, computed per document
# ---------------------------------------------------------------------------


def achieved(name: str, tmp_path: Path) -> dict[str, Any]:
    return dict(run(name, tmp_path).fragment.achieved)


def test_achieved_reports_what_this_document_produced_and_not_what_the_card_allows(
    tmp_path: Path,
) -> None:
    """A CSV is a table and nothing else, so seven of the fifteen differ from the declaration."""
    csv = achieved("rows.csv", tmp_path / "csv")
    assert csv["math"] == []
    assert csv["assets"] == "none"
    assert csv["asset_origin"] is False
    assert csv["notes"] == "none"
    assert csv["sections"] == "none"
    assert csv["tables"] == "cells"

    docx = achieved("rich.docx", tmp_path / "docx")
    assert docx["math"] == ["latex"]
    assert docx["assets"] == "bytes"
    assert docx["asset_origin"] is True
    assert docx["notes"] == "linked"
    assert docx["sections"] == "outline_from_source"
    assert docx["tables"] == "cells_with_spans"
    assert docx["marks"] is True


def test_the_constant_eight_never_vary(tmp_path: Path) -> None:
    """`spatial`, `origin_span`, `text_span`, `reading_order`, `confidence`, `furniture`,
    `round_trip` and `forfeits` are properties of this code rather than of a document."""
    for index, name in enumerate(("rich.docx", "rows.csv", "book.epub")):
        report = achieved(name, tmp_path / str(index))
        assert report["spatial"] == "none"
        assert report["origin_span"] == "none"
        assert report["text_span"] is False
        assert report["reading_order"] == "source"
        assert report["confidence"] == "none"
        assert report["furniture"] == "destroyed"
        assert report["round_trip"] == "structure"
        assert report["forfeits"] == []


def test_an_empty_presentation_is_a_success_the_host_will_not_cache(tmp_path: Path) -> None:
    """`deck.ppt` is a valid PowerPoint 97 stream with nothing in it.

    The driver returns `ok` -- it decoded the document correctly and the document is empty -- and
    `is_valid_nonempty()` is what turns that into `FAILED_PERMANENT(EMPTY_RESULT)` host-side, so
    an empty success is never memoised and never served from cache forever.
    """
    result = run("deck.ppt", tmp_path)
    assert result.result.outcome == "ok"
    assert result.fragment.blocks == ()
    assert AnydocParser().is_valid_nonempty(result.result.produced[0]) is False
    assert AnydocParser().is_valid_nonempty(run("rich.docx", tmp_path).result.produced[0]) is True


def test_the_fragment_is_one_json_object_per_line(tmp_path: Path) -> None:
    """`owdoc-fragment/1` is NDJSON, and a host reads it line by line rather than loading it."""
    body = run("rich.docx", tmp_path).body
    lines = body.decode("utf-8").splitlines()
    assert lines
    for line in lines:
        assert isinstance(json.loads(line), dict)
