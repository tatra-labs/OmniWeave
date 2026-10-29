"""`omniweave_conform.structure`: the reference, the F1 and the drafted corpus. **D982.**

The Doc is a hand-built one, as `test_conform_cells.py`'s is, so a scoring test depends on the
tuples under test and not on a driver. The last three tests are over the committed references
themselves: they load, they are unsigned, and every fixture that should carry one does.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import structure
from omniweave_core.drivers.card import MeasuredOn, load_card
from omniweave_core.errors import QualityError
from omniweave_core.model.block import Addr, Block, BlockId, Cite
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.spans import OriginNone
from omniweave_core.store.oweval import Run

REPO = Path(__file__).resolve().parents[4]
OFFICE_FIXTURES = REPO / "packages" / "omniweave-office" / "fixtures"
OFFICE_CARD = REPO / "packages" / "omniweave-office" / "src" / "omniweave_office" / "driver.toml"
PDF_CARD = REPO / "packages" / "omniweave-pdf" / "src" / "omniweave_pdf" / "driver.toml"
DOC_ORD, GEN = 3, 1
HEADER = json.dumps({"schema": structure.SCHEMA})
MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="cpython",
    runtime_version="3.12.0",
    sampling="n/a",
    prompt_version="n/a",
    hardware="test",
    corpus="packages/omniweave-office/fixtures@" + "0" * 16,
    corpus_digest="sha256:" + "0" * 64,
    harness_version="0.1.0",
)


def _block(
    block: int,
    text: str,
    *,
    kind: Kind = Kind.PARAGRAPH,
    layer: Layer = Layer.BODY,
    parent: int | None = None,
    page: int = 0,
    order: int = 0,
) -> Block:
    return Block(
        id=BlockId(block),
        addr=Addr(f"p{page}/b{block}"),
        cite=Cite(f"d{DOC_ORD}#{block}"),
        doc_ord=DOC_ORD,
        gen=GEN,
        page=page,
        parent=None if parent is None else BlockId(parent),
        ord=order,
        kind=kind,
        raw_kind=None,
        layer=layer,
        label=None,
        text=text,
        content_digest=bytes(16),
        layout_digest=None,
        revision=1,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.TEXT_LAYER,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


@dataclass
class _Doc:
    """Just enough `Doc` for `score()`: `blocks(pages=, layers=)` and `block(id)`."""

    rows: list[Block] = field(default_factory=list)

    def add(self, block: Block) -> Block:
        self.rows.append(block)
        return block

    def blocks(
        self,
        *,
        pages: range | None = None,
        kinds: Iterable[Kind] | None = None,
        layers: Iterable[Layer] = (Layer.BODY,),
        under: BlockId | None = None,
    ) -> Iterator[Block]:
        del kinds, under
        wanted = set(layers)
        for block in self.rows:
            if pages is not None and block.page not in pages:
                continue
            if block.layer in wanted:
                yield block

    def block(self, id: BlockId) -> Block:  # noqa: A002 -- Doc.block's own name.
        return next(block for block in self.rows if block.id == id)


def _reference(path: Path, *rows: dict[str, Any], header: str = HEADER) -> Path:
    lines = [header, *(json.dumps(row) for row in rows)]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "s01",
        "page": 1,
        "kind": "paragraph",
        "layer": "body",
        "parent_kind": "document",
        "text": "a line",
    }
    row.update(over)
    return row


def _triple(**over: Any) -> structure.Triple:
    base = structure.Triple(
        id="s01",
        page=1,
        kind="paragraph",
        layer="body",
        parent_kind=None,
        text="a line",
        checked="verified",
    )
    return replace(base, **over)


def _run(status: str = "ok") -> Run:
    return Run(
        run_id="r" * 32,
        suite="parse",
        corpus_id="packages/omniweave-office/fixtures",
        corpus_version="0" * 16,
        corpus_digest="0" * 64,
        subject="parse.office.anydoc",
        subject_version="0.1.0",
        producer_id=None,
        measured_on=MEASURED,
        timing_basis="in_process",
        witness="self",
        cassette="off",
        policy_digest=None,
        pricebook_digest=None,
        harness_version="0.1.0",
        code_fingerprint="0" * 64,
        hardware="test",
        started_ns=1,
        ended_ns=2,
        status=status,
    )


# ---------------------------------------------------------------------------
# The reference file (rulings 1 and 2)
# ---------------------------------------------------------------------------


def test_a_fixture_with_no_reference_file_has_no_tuples(tmp_path: Path) -> None:
    assert structure.load(tmp_path / "doc.docx") == ()


def test_the_header_names_the_schema_or_the_file_is_refused(tmp_path: Path) -> None:
    fixture = tmp_path / "doc.docx"
    _reference(fixture.with_name("doc.docx.structure.jsonl"), _row(), header="{}")
    with pytest.raises(QualityError, match="schema is None"):
        structure.load(fixture)


def test_an_empty_reference_is_refused(tmp_path: Path) -> None:
    fixture = tmp_path / "doc.docx"
    structure.reference_of(fixture).write_bytes(b"\n\n")
    with pytest.raises(QualityError, match="is empty"):
        structure.load(fixture)


def test_a_header_with_a_second_key_is_refused(tmp_path: Path) -> None:
    fixture = tmp_path / "doc.docx"
    _reference(
        structure.reference_of(fixture),
        _row(),
        header=json.dumps({"schema": structure.SCHEMA, "note": "no"}),
    )
    with pytest.raises(QualityError, match="schema and nothing else"):
        structure.load(fixture)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"id": ""}, "is a non-empty string"),
        ({"page": 0}, "1-based page number"),
        ({"page": True}, "1-based page number"),
        ({"kind": "stanza"}, "is not a Kind member"),
        ({"layer": "footer"}, "is not a Layer member"),
        ({"parent_kind": "stanza"}, "is not a Kind member"),
        ({"text": "  "}, "non-empty string"),
        ({"checked": "maybe"}, "verified or rejected"),
        ({"max_diffs": -1}, "an int >= 0"),
        ({"slices": "office"}, "a list of slice names"),
        ({"colour": "red"}, "unknown key"),
    ],
)
def test_every_field_is_closed_against_its_vocabulary(
    tmp_path: Path, over: dict[str, Any], message: str
) -> None:
    fixture = tmp_path / "doc.docx"
    _reference(structure.reference_of(fixture), _row(**over))
    with pytest.raises(QualityError, match=message):
        structure.load(fixture)


def test_a_repeated_id_is_refused(tmp_path: Path) -> None:
    fixture = tmp_path / "doc.docx"
    _reference(structure.reference_of(fixture), _row(), _row(text="another line"))
    with pytest.raises(QualityError, match="repeats"):
        structure.load(fixture)


def test_a_row_inherits_the_fixtures_slices_and_keeps_its_own(tmp_path: Path) -> None:
    fixture = tmp_path / "doc.docx"
    _reference(
        structure.reference_of(fixture),
        _row(),
        _row(id="s02", text="its own", slices=["office/docx/has_merges=1"]),
    )
    inherited, own = structure.load(fixture, slices=("office/docx",))
    assert inherited.slices == ("office/docx",)
    assert own.slices == ("office/docx/has_merges=1",)
    assert inherited.checked is None, "ruling 3: a drafted row is unsigned"
    assert inherited.max_diffs == 0


# ---------------------------------------------------------------------------
# The F1 (rulings 3 to 6)
# ---------------------------------------------------------------------------


def test_an_unsigned_reference_does_not_score_and_says_how_many() -> None:
    doc = _Doc([_block(1, "a line")])
    scored = structure.score("doc.docx", doc, (_triple(checked=None), _triple(id="s02")))
    assert (scored.f1, scored.scored) == (None, False)
    assert scored.why == "1 of 2 reference row(s) unsigned (ruling 3)"


def test_a_document_with_no_reference_does_not_score() -> None:
    scored = structure.score("doc.docx", _Doc([_block(1, "a line")]), ())
    assert (scored.f1, scored.why) == (None, "carries no structure.jsonl reference")


def test_a_tree_the_parse_reproduces_scores_one() -> None:
    doc = _Doc(
        [
            _block(1, "", kind=Kind.DOCUMENT),
            _block(2, "Quarterly report", kind=Kind.HEADING, parent=1),
            _block(3, "Quarter", parent=4),
            _block(4, "", kind=Kind.TABLE_CELL, parent=1),
        ]
    )
    reference = (
        _triple(id="s01", kind="heading", parent_kind="document", text="Quarterly report"),
        _triple(id="s02", parent_kind="table_cell", text="Quarter"),
    )
    scored = structure.score("doc.docx", doc, reference)
    assert (scored.tp, scored.predicted, scored.reference) == (2, 2, 2)
    assert scored.f1 == 1.0


def test_a_text_less_block_is_outside_both_denominators() -> None:
    """Ruling 6: the `table`, its `table_cell` and the `list` carry no text of their own."""
    doc = _Doc(
        [
            _block(1, "", kind=Kind.TABLE),
            _block(2, "", kind=Kind.TABLE_CELL, parent=1),
            _block(3, "Quarter", parent=2),
        ]
    )
    scored = structure.score("doc.docx", doc, (_triple(parent_kind="table_cell", text="Quarter"),))
    assert (scored.predicted, scored.reference, scored.f1) == (1, 1, 1.0)


def test_a_wrong_kind_costs_precision_and_recall() -> None:
    doc = _Doc([_block(1, "Quarterly report", kind=Kind.PARAGRAPH)])
    scored = structure.score(
        "doc.docx", _Doc(doc.rows), (_triple(kind="heading", text="Quarterly report"),)
    )
    assert (scored.tp, scored.predicted, scored.reference, scored.f1) == (0, 1, 1, 0.0)


def test_a_wrong_parent_kind_fails_the_triple_the_text_alone_would_pass() -> None:
    doc = _Doc([_block(1, "", kind=Kind.BLOCKQUOTE), _block(2, "a note", parent=1)])
    reference = (_triple(layer="note", parent_kind="speaker_note", text="a note"),)
    scored = structure.score("doc.docx", doc, reference)
    assert scored.predicted == 0, "the reference names the note layer and the Block is in body"
    assert (scored.tp, scored.f1) == (0, 0.0)


def test_an_unmatched_prediction_costs_precision_only() -> None:
    doc = _Doc([_block(1, "a line"), _block(2, "a stray line", order=1)])
    scored = structure.score("doc.docx", doc, (_triple(),))
    assert (scored.tp, scored.predicted, scored.reference) == (1, 2, 1)
    assert scored.f1 == pytest.approx(2 * 0.5 * 1.0 / 1.5)


def test_max_diffs_is_the_rows_own_edit_budget() -> None:
    doc = _Doc([_block(1, "a line.")])
    assert structure.score("doc.docx", doc, (_triple(),)).f1 == 0.0
    assert structure.score("doc.docx", doc, (_triple(max_diffs=1),)).f1 == 1.0


def test_a_block_matches_at_most_one_reference_row() -> None:
    """Ruling 4: two rows naming the same text cannot both claim the one Block."""
    doc = _Doc([_block(1, "a line")])
    scored = structure.score("doc.docx", doc, (_triple(), _triple(id="s02")))
    assert (scored.tp, scored.predicted, scored.reference) == (1, 1, 2)
    assert scored.f1 == pytest.approx(2 * 1.0 * 0.5 / 1.5)


def test_only_the_referenced_pages_are_predicted() -> None:
    doc = _Doc([_block(1, "a line"), _block(2, "page two", page=1)])
    scored = structure.score("doc.docx", doc, (_triple(),))
    assert (scored.predicted, scored.f1) == (1, 1.0)


# ---------------------------------------------------------------------------
# The rows (ruling 7) and the card (ruling 8)
# ---------------------------------------------------------------------------


def test_no_scored_document_is_one_unknown_macro_row() -> None:
    rows = structure.metrics(
        _run(), (structure.Scored("doc.docx", ("office/docx",), 0, 0, 2, None),)
    )
    assert [(row.metric, row.slice_key, row.state, row.value) for row in rows] == [
        (structure.METRIC, "__macro__", "unknown", None)
    ]


def test_a_slice_under_min_slice_n_is_unknown_with_its_n() -> None:
    scored = [structure.Scored(f"d{i}.docx", ("office/docx",), 1, 1, 1, 1.0) for i in range(3)]
    rows = {row.slice_key: row for row in structure.metrics(_run(), scored)}
    assert (rows["office/docx"].state, rows["office/docx"].n) == ("unknown", 3)
    assert rows["__macro__"].state == "unknown"


def test_a_slice_at_min_slice_n_carries_its_mean_and_its_interval() -> None:
    scored = [
        structure.Scored(f"d{i}.docx", ("office/docx",), 1, 1, 1, 1.0 if i else 0.5)
        for i in range(30)
    ]
    rows = {row.slice_key: row for row in structure.metrics(_run(), scored)}
    one = rows["office/docx"]
    assert (one.state, one.n, one.method, one.truth_kind) == ("ok", 30, "closed_form", "rendered")
    assert one.value == pytest.approx((29 + 0.5) / 30)
    assert rows["__macro__"].value == pytest.approx(one.value)
    assert one.ci_lo is not None and one.ci_lo < one.value < one.ci_hi  # type: ignore[operator]


def test_an_unknown_run_yields_unknown_rows() -> None:
    scored = [structure.Scored(f"d{i}.docx", ("office/docx",), 1, 1, 1, 1.0) for i in range(30)]
    rows = structure.metrics(_run(status="unknown"), scored)
    assert {row.state for row in rows} == {"unknown"}
    assert {row.value for row in rows} == {None}


def test_a_document_without_slices_lands_on_the_unsliced_key() -> None:
    scored = [structure.Scored("doc.docx", (), 1, 1, 1, 1.0)]
    assert {row.slice_key for row in structure.metrics(_run(), scored)} == {"*", "__macro__"}


def test_the_pdf_card_declares_no_structure_and_the_office_card_does() -> None:
    """Ruling 8: the two shipped parse cards, read from disk."""
    pdf = load_card(PDF_CARD.read_bytes(), origin="driver_path", source=str(PDF_CARD))
    office = load_card(OFFICE_CARD.read_bytes(), origin="driver_path", source=str(OFFICE_CARD))
    why = structure.inapplicable(pdf)  # type: ignore[arg-type]
    assert "parse.pdf.pdfium" in why
    assert 'sections = "none"' in why and 'tables = "none"' in why
    assert structure.inapplicable(office) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The committed references (D982's drafted corpus)
# ---------------------------------------------------------------------------


def test_every_committed_reference_loads_and_is_unsigned() -> None:
    files = sorted(OFFICE_FIXTURES.glob(f"*{structure.SUFFIX}"))
    assert len(files) == 30, (
        "D982 drafted a reference for each of the ten labelled office fixtures and D1004 added"
        " twenty more, which is `min_slice_n = 30` met exactly"
    )
    rows = [
        row
        for path in files
        for row in structure.load(path.with_name(path.name.removesuffix(structure.SUFFIX)))
    ]
    assert len(rows) == 227
    assert [row for row in rows if row.checked is not None] == [], (
        "ruling 3: only the reviewer writes checked"
    )


def test_every_labelled_office_fixture_carries_a_reference() -> None:
    labelled = sorted(OFFICE_FIXTURES.glob("*.assertions.toml"))
    missing = [
        path.name
        for path in labelled
        if not structure.reference_of(
            path.with_name(path.name.removesuffix(".assertions.toml"))
        ).is_file()
    ]
    assert missing == []
