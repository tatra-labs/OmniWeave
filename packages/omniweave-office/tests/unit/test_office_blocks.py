"""The mapping from anydoc's model to `owdoc-fragment/1`, asserted against real documents.

`blocks.py` translates between two document models, and every claim it makes is checkable against
a fixture rather than against a comment. What is checked here is what a reviewer would otherwise
have to take on trust:

* all eight `Block` variants land on the `Kind` member the plan names, across the corpus;
* the exactly-once grid survives the crossing -- one `table_cell` per ORIGIN slot, none for a
  covered position, in row-major order, with the span on the origin;
* mark ranges are half-open offsets into the block's own text, `0 <= a <= b <= len(text)`, and a
  zero-width `anchor` is legal;
* a footnote body sits at `layer = "note"` and the reference site names it, which is what makes
  `achieved.notes` report `linked` rather than `inline`;
* an image becomes a `picture` BLOCK with a `block_asset` link, never a mark, because a mark is a
  range over text and an image occupies none.

Specified in 03-document-model.md sections 2.6, 2.7 and 10; 16-roadmap.md W3.4.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import anydoc
import pytest
from omniweave_office.blocks import BLOCK_KINDS, NOTE_LAYER, Walk, nfc

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PART = "office/source"


def walk(name: str, fmt: str | None = None) -> tuple[list[dict[str, Any]], Walk]:
    document = anydoc.to_document((FIXTURES / name).read_bytes(), fmt)
    engine = Walk(PART)
    return list(engine.records(document)), engine


def blocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("t") == "block"]


def by_tmp(records: list[dict[str, Any]], tmp: str) -> dict[str, Any]:
    return next(record for record in blocks(records) if record["tmp"] == tmp)


# ---------------------------------------------------------------------------
# the eight variants
# ---------------------------------------------------------------------------


def test_every_anydoc_variant_maps_to_a_kind_the_plan_names() -> None:
    """`BLOCK_KINDS` covers exactly the wheel's eight, with the plan's two renames."""
    from anydoc import _anydoc  # noqa: PLC0415

    stub = Path(_anydoc.__file__).with_suffix(".pyi").read_text(encoding="utf-8")
    section = stub.split("class Block:", 1)[1]
    literal = section.split("Literal[", 1)[1].split("]", 1)[0]
    variants = {piece.strip().strip('"') for piece in literal.split(",") if piece.strip()}
    assert variants == set(BLOCK_KINDS)
    assert BLOCK_KINDS["block_quote"] == "blockquote"  # Kind was renamed off QUOTE (03:823)
    assert BLOCK_KINDS["math"] == "formula"  # 05:3224's worked trace


def test_the_corpus_reaches_all_eight_variants() -> None:
    """Eight variants, two fixtures. A mapping nothing exercises is a mapping nobody checked."""
    seen: set[str] = set()
    for name in ("rich.docx", "book.epub"):
        seen.update(block["kind"] for block in blocks(walk(name)[0]))
    assert {"heading", "paragraph", "list", "table", "formula"} <= seen
    assert {"blockquote", "code", "rule"} <= seen


def test_every_block_carries_the_same_four_constants() -> None:
    """`os = {"k": "none"}`, `quad = None`, `quote = "normalized"`, `method = "native_xml"`.

    Not "usually" and not "on this fixture": the eight variants carry no source address, so there
    is no document for which this driver could write anything else. The conform `capability`
    suite's P14 clause for `origin_span = "none"` fails the whole run if one block dissents.
    """
    for name in ("rich.docx", "book.epub", "sheet.xlsx"):
        for block in blocks(walk(name)[0]):
            assert block["os"] == {"k": "none"}, block["tmp"]
            assert block["quad"] is None
            assert block["quote"] == "normalized"
            assert block["method"] == "native_xml"
            assert block["page"] == 0


# ---------------------------------------------------------------------------
# the grid
# ---------------------------------------------------------------------------


def test_the_merged_cell_produces_one_origin_and_no_covered_slot() -> None:
    """03:1897's exactly-once invariant, crossing the wire.

    `rich.docx`'s table is 3x2 with the last row merged across both columns: five cells, not six.
    The sixth position is `covered`, `build_grid` derives it from the origin's span (03:1935), and
    emitting it here would hand the host a second copy of a derivation it owns.
    """
    records, engine = walk("rich.docx")
    table = next(b for b in blocks(records) if b["kind"] == "table")
    cells = [
        b for b in blocks(records) if b["kind"] == "table_cell" and b["parent"] == table["tmp"]
    ]
    positions = [(c["cell"]["r"], c["cell"]["c"]) for c in cells]
    assert positions == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)]
    assert positions == sorted(positions), "cells arrive in row-major origin order (03:1941)"
    merged = cells[-1]["cell"]
    assert (merged["row_span"], merged["col_span"]) == (1, 2)
    assert table["payload"] == {"header_rows": 1, "header_cols": 0, "kind": "data"}
    assert engine.has_spans is True


def test_a_table_without_merges_reports_no_spans() -> None:
    """`achieved.tables` is `cells` rather than `cells_with_spans` for a flat grid (03:527)."""
    _records, engine = walk("rows.csv", "csv")
    assert engine.tables == 1
    assert engine.has_spans is False


@pytest.mark.parametrize("name", ["sheet.xlsx", "sheet.ods", "sheet.xls"])
def test_three_spreadsheet_encodings_produce_one_grid_shape(name: str) -> None:
    """OOXML `mergeCell`, ODF `covered-table-cell` and BIFF8 are three spellings, one model."""
    records, engine = walk(name)
    assert engine.tables == 1
    cells = [b for b in blocks(records) if b["kind"] == "table_cell"]
    assert cells, name
    for cell in cells:
        assert cell["cell"]["row_span"] >= 1
        assert cell["cell"]["col_span"] >= 1
        assert cell["parent"] is not None


# ---------------------------------------------------------------------------
# marks
# ---------------------------------------------------------------------------


def test_mark_ranges_are_half_open_offsets_into_the_blocks_own_text() -> None:
    """`0 <= a <= b <= len(text)` (03:373), on every mark of every block of the corpus."""
    for name in ("rich.docx", "book.epub"):
        for block in blocks(walk(name)[0]):
            text = block["text"]
            for mark in block["marks"]:
                assert 0 <= mark["a"] <= mark["b"] <= len(text), (block["tmp"], mark)


def test_a_styled_run_becomes_one_mark_per_attribute_over_the_same_range() -> None:
    """Four booleans, up to four marks -- never one combined record.

    03:369: overlapping ranges are representable here, which marker's one
    `formats: List[Literal[...]]` per span cannot express ("bold ending mid-italic"). A combined
    record would re-introduce exactly that collapse at the wire.
    """
    records, _ = walk("rich.docx")
    paragraph = next(b for b in blocks(records) if b["kind"] == "paragraph" and "bold" in b["text"])
    kinds = {mark["kind"] for mark in paragraph["marks"]}
    assert {"bold", "italic", "strike", "link", "note_ref"} <= kinds
    bold = next(m for m in paragraph["marks"] if m["kind"] == "bold")
    assert paragraph["text"][bold["a"] : bold["b"]] == "bold"
    italic = next(m for m in paragraph["marks"] if m["kind"] == "italic")
    assert paragraph["text"][italic["a"] : italic["b"]] == "italic"


def test_a_link_mark_carries_a_non_empty_target_and_a_resolved_kind() -> None:
    """The conform `capability` suite checks the target; the kind is this mapping's own claim."""
    records, _ = walk("rich.docx")
    link = next(
        mark for block in blocks(records) for mark in block["marks"] if mark["kind"] == "link"
    )
    assert link["target"] == "https://example.invalid/report"
    assert link["target_kind"] == "external"


def test_a_relative_link_is_reported_as_internal() -> None:
    """anydoc's `relative` -> the mark vocabulary's `internal`, and the value is preserved.

    The only judgement in `_LINK_TARGET_KINDS`. A host that later disagrees can re-decide from the
    target string, which is kept exactly as anydoc gives it.
    """
    records, _ = walk("book.epub")
    targets = [
        mark for block in blocks(records) for mark in block["marks"] if mark["kind"] == "link"
    ]
    assert targets
    assert all(mark["target"] for mark in targets)
    assert {mark["target_kind"] for mark in targets} <= {"external", "internal", "anchor"}


def test_an_anchor_mark_is_zero_width_and_names_an_anchor_kind() -> None:
    """`a == b` is legal and meaningful for `anchor` (03:372)."""
    records, _ = walk("rich.docx")
    anchors = [
        mark for block in blocks(records) for mark in block["marks"] if mark["kind"] == "anchor"
    ]
    assert anchors
    for mark in anchors:
        assert mark["a"] == mark["b"]
        assert mark["name"]
        assert mark["akind"] in {"section", "bookmark"}


def test_inline_math_occupies_its_own_range_and_carries_the_notation() -> None:
    """The LaTeX source IS the text at that range, so the mark says what the range is."""
    records, engine = walk("rich.docx")
    block = next(b for b in blocks(records) if any(m["kind"] == "math" for m in b["marks"]))
    mark = next(m for m in block["marks"] if m["kind"] == "math")
    assert block["text"][mark["a"] : mark["b"]] == mark["src"]
    assert mark["notation"] == "latex"
    assert engine.notations == {"latex"}


# ---------------------------------------------------------------------------
# notes, assets, and the speaker note that is not one
# ---------------------------------------------------------------------------


def test_a_footnote_body_sits_at_the_note_layer_and_its_reference_names_it() -> None:
    """`achieved.notes = "linked"` is 03:532's rollup: every note body has an inbound reference."""
    records, engine = walk("rich.docx")
    note = next(b for b in blocks(records) if b["kind"] == "footnote")
    assert note["layer"] == NOTE_LAYER
    body = [b for b in blocks(records) if b["parent"] == note["tmp"]]
    assert body and all(b["layer"] == NOTE_LAYER for b in body)
    reference = next(
        mark for block in blocks(records) for mark in block["marks"] if mark["kind"] == "note_ref"
    )
    assert reference["target_tmp"] == note["tmp"]
    assert reference["a"] == reference["b"]
    assert engine.notes_rung == "linked"


def test_the_note_body_comes_after_every_reference_site_in_the_stream() -> None:
    """A host reading line by line (03:2575) never meets a forward reference to a note."""
    records, _ = walk("rich.docx")
    note = next(b for b in blocks(records) if b["kind"] == "footnote")
    order = [r.get("tmp") for r in records]
    referrers = [
        b["tmp"] for b in blocks(records) if any(m["kind"] == "note_ref" for m in b["marks"])
    ]
    assert referrers
    assert max(order.index(tmp) for tmp in referrers) < order.index(note["tmp"])


def test_an_image_becomes_a_picture_block_with_a_block_asset_link() -> None:
    """An image is not a mark: a mark is a range over text and an image occupies none.

    The alt text is the block's `label` rather than its `text`, because alt text is a description
    OF the picture and putting it in `text` would make it quotable as document content.
    """
    records, engine = walk("rich.docx")
    asset = next(r for r in records if r.get("t") == "asset")
    assert asset["media_type"] == "image/png"
    assert asset["origin_part"] == "word/media/dot.png"
    assert asset["role"] == "image"
    picture = next(b for b in blocks(records) if b["kind"] == "picture")
    assert picture["text"] == ""
    assert picture["label"] == "a single grey dot"
    assert picture["assets"] == [{"tmp": asset["tmp"], "role": "image"}]
    assert engine.assets == 1
    assert engine.asset_origins == 1


def test_the_asset_record_precedes_every_block_that_references_it() -> None:
    """Assets first, so a line-by-line reader resolves a link it has already seen."""
    records, _ = walk("rich.docx")
    first_block = next(index for index, r in enumerate(records) if r.get("t") == "block")
    assets = [index for index, r in enumerate(records) if r.get("t") == "asset"]
    assert assets and max(assets) < first_block


def test_a_pptx_speaker_note_arrives_as_a_blockquote_and_the_driver_cannot_tell() -> None:
    """anydoc emits it as `Block::BlockQuote` (`src/formats/pptx/mod.rs:207`).

    So `Kind.SPEAKER_NOTE` has no producer on this path, and nothing downstream can separate a
    presenter's note from a quotation on the slide. That is a real limitation of the office path
    and it is asserted rather than described, because a docstring cannot fail.
    """
    records, _ = walk("deck.pptx")
    kinds = [b["kind"] for b in blocks(records)]
    assert "blockquote" in kinds
    assert "speaker_note" not in kinds


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def test_block_text_is_nfc() -> None:
    """`quote = "normalized"` is a claim about the text, and `nfc()` is what makes it true."""
    for name in ("rich.docx", "book.epub", "notes.odt", "memo.rtf"):
        for block in blocks(walk(name)[0]):
            assert block["text"] == unicodedata.normalize("NFC", block["text"]), block["tmp"]


def test_nfc_is_not_a_casefold() -> None:
    """03:1491 and 13:1041: `nfc()`, never `normalize_k`, which casefolds."""
    assert nfc("ABC") == "ABC"
    assert nfc("Å") == "Å"
    assert nfc("Å") == "Å"


def test_the_walk_mints_a_unique_tmp_for_every_record() -> None:
    """A `tmp` collision makes the host's parent map ambiguous, and it is silent when it happens."""
    for name in ("rich.docx", "book.epub", "sheet.xls"):
        records, _ = walk(name)
        tmps = [r["tmp"] for r in records if "tmp" in r]
        assert len(tmps) == len(set(tmps)), name


def test_every_parent_names_a_block_that_exists() -> None:
    """The fragment is a tree, and a dangling parent is a tree the host cannot rebuild."""
    for name in ("rich.docx", "book.epub"):
        records, _ = walk(name)
        known = {b["tmp"] for b in blocks(records)}
        for block in blocks(records):
            assert block["parent"] is None or block["parent"] in known, block["tmp"]
