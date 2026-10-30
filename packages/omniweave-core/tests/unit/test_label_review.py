"""Ruling 1's review page, tested as a program: `tools/label_review.py`. **D980.**

Three things are worth holding here.

1. **The committed labels agree with the committed bytes.** D913 drafted all 110 from the
   generators' text functions, and this file reads them back off the fixtures through readers that
   import no omniweave driver. A drafted claim that the file contradicts is a defect to mend before
   a reviewer ever sees it, so it fails here rather than waiting for the review.
2. **`agrees` is not `checked`.** Nothing in the tool writes a signature. `apply_verdicts` takes a
   reviewer's file, refuses any value but section 8.1's two, refuses an id the sidecar does not
   carry, and stages every write so a refusal leaves the tree untouched.
3. **A signature does not reformat the sidecar.** The files are hand-written and commented, and
   `autocrlf=true` leaves them CRLF in the working tree, so `_stamp` edits the signed row's lines
   and leaves every other byte -- line ending included -- where it was.
4. **The structure references are the second population, and their unit is the DOCUMENT** (D1001).
   The same three things hold, with one more: what this tool can judge about a reference row is
   its TEXT and its POSITION, never its `(kind, layer, parent_kind)` triple, and the two rows it
   cannot judge at all are named rather than guessed. The first run of the structure half reported
   five of fifty-nine rows disagreeing with the bytes; three were the readers being narrower than
   the formats (a DOCX footnote, a PPTX speaker note, an EPUB title in `content.opf`) and two were
   OMML formulas whose transcription no byte reader can confirm. The readers were widened and the
   transcription tier bounded to paragraphs that carry OMML, and the tests below hold both: a row
   that is wrong is still wrong, in a formula paragraph and outside one.

Loaded by file path under a private name at module scope, as `test_gate_measured_on.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "label_review.py"
    spec = importlib.util.spec_from_file_location("_owtool_label_review", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load()

SIDECAR = """# a sidecar, with the comments a reviewer reads.
schema = "omniweave.assertions/1"

[[assertion]]
id = "first"
type = "present"
page = 1
text = "Hello"
slices = ["x/y"]

[[assertion]]
id = "second"
type = "absent"
text = "Nowhere"
slices = ["x/y"]
"""


def _claim(**body: object) -> object:
    return TOOL.Claim(Path("s.toml"), Path("f.txt"), 1, body)


def _evidence(*runs: str, grid: tuple[tuple[str, ...], ...] = ()) -> object:
    return TOOL.Evidence("a test", runs=runs, pages=(runs,), grid=grid)


# 1 -- the committed labels, against the committed bytes.


def test_every_drafted_label_has_evidence_and_agrees() -> None:
    """Every label but a `cell_rel` is confirmed against the bytes here.

    A `cell_rel` is DECLARED unjudgeable by this reader (D1005): its relation is asked of the
    parsed `Grid`'s spans and header chains, and a flat cell grid read off the bytes answers
    `right` of a span-2 cell with `''` rather than its last column's neighbour -- judging it here
    would call a correct row wrong. `test_conform_table_assertions.py` judges every one of them
    on the real `Grid`, so none is taken on trust; what is declined is only this file's reading.
    """
    rows = TOOL.review(REPO)
    assert rows, "no *.assertions.toml found -- the glob or the tree moved"
    blind = [row.claim.id for row in rows if row.agrees is None]
    typed = {row.claim.type for row in rows if row.agrees is None}
    assert typed <= {"cell_rel"}, f"no evidence for {blind}: a reviewer would take those on trust"
    assert blind, "D1005 committed cell_rel labels; an empty list means the tier stopped firing"
    declined = [row for row in rows if row.claim.type == "cell_rel"]
    for row in declined:
        assert "claim about the parsed Grid" in row.why, row.why
        assert "test_conform_table_assertions.py" in row.why, (
            "a declined row that does not say where the real check lives is a row taken on trust"
        )
        assert row.excerpt, f"{row.claim.id} declines without showing the table it read"
    wrong = [
        f"{row.claim.fixture.name}:{row.claim.id} -- {row.why}"
        for row in rows
        if row.agrees is False
    ]
    assert wrong == [], "drafted labels the fixture bytes contradict:\n" + "\n".join(wrong)


def test_every_fixture_with_labels_has_an_independent_reader() -> None:
    rows = TOOL.review(REPO)
    suffixes = {row.claim.fixture.suffix for row in rows}
    unreadable = {row.claim.fixture.suffix for row in rows if row.evidence.unreadable is not None}
    assert unreadable == set(), (
        f"no independent reader for {sorted(unreadable)} of {sorted(suffixes)}"
    )


def test_nothing_in_the_tree_is_signed_yet_or_is_signed_only_the_two_ways() -> None:
    """A signature is the user's. This test does not demand there be none -- only that each is one
    of the two values section 8.1 allows, so a typo cannot quietly become a third state."""
    for claim in TOOL.claims(REPO):
        assert claim.checked in (None, *TOOL.VERDICTS), f"{claim.id}: {claim.checked!r}"


# 2 -- the arithmetic, on its own terms.


def test_present_finds_and_misses() -> None:
    evidence = _evidence("a heading", "some body text")
    assert TOOL.judge(_claim(id="a", type="present", page=1, text="body"), evidence).agrees is True
    missed = TOOL.judge(_claim(id="a", type="present", page=1, text="absent"), evidence)
    assert missed.agrees is False
    assert "no run on that page" in missed.why


def test_order_holds_only_in_the_drawn_direction() -> None:
    evidence = _evidence("first", "second")
    assert TOOL.judge(
        _claim(id="a", type="order", page=1, before="first", after="second"), evidence
    ).agrees
    backwards = TOOL.judge(
        _claim(id="a", type="order", page=1, before="second", after="first"), evidence
    )
    assert backwards.agrees is False
    assert "does NOT precede" in backwards.why


def test_order_with_a_missing_side_names_the_side() -> None:
    row = TOOL.judge(
        _claim(id="a", type="order", page=1, before="first", after="gone"), _evidence("first")
    )
    assert row.agrees is False
    assert "'gone'" in row.why


def test_absent_is_over_the_whole_document_not_one_page() -> None:
    evidence = TOOL.Evidence(
        "a test", runs=("page one", "page two"), pages=(("page one",), ("page two",))
    )
    assert TOOL.judge(_claim(id="a", type="absent", text="page three"), evidence).agrees is True
    assert (
        TOOL.judge(_claim(id="a", type="absent", page=1, text="page two"), evidence).agrees is False
    )


def test_table_walks_the_grid_in_four_directions() -> None:
    grid = (("Region", "Units"), ("north", "17"))
    evidence = _evidence("Region", "Units", "north", "17", grid=grid)
    assert TOOL.judge(
        _claim(id="a", type="table", page=1, cell="north", right="17", up="Region"), evidence
    ).agrees
    assert TOOL.judge(
        _claim(id="a", type="table", page=1, cell="17", left="north", up="Units"), evidence
    ).agrees
    wrong = TOOL.judge(_claim(id="a", type="table", page=1, cell="north", right="99"), evidence)
    assert wrong.agrees is False
    assert "is '17', not '99'" in wrong.why


def test_table_off_the_edge_disagrees_rather_than_raising() -> None:
    evidence = _evidence("only", grid=(("only",),))
    row = TOOL.judge(_claim(id="a", type="table", page=1, cell="only", right="anything"), evidence)
    assert row.agrees is False


def test_a_row_with_no_evidence_is_neither_true_nor_false() -> None:
    row = TOOL.judge(
        _claim(id="a", type="present", page=1, text="x"), TOOL.Evidence("x", unreadable="no reader")
    )
    assert row.agrees is None
    assert "no evidence" in row.why


def test_a_table_claim_without_a_grid_is_unknown_not_false() -> None:
    row = TOOL.judge(_claim(id="a", type="table", page=1, cell="x", right="y"), _evidence("x", "y"))
    assert row.agrees is None


# 3 -- the readers, on the fixtures' own escapes.


def test_pdf_literals_come_back_unescaped() -> None:
    assert TOOL.unescape(rb"(a \(b\) c)") == "a (b) c"
    assert TOOL.unescape(rb"(a \\ b)") == "a \\ b"


def test_the_pdf_reader_finds_one_page_per_kid() -> None:
    fixture = REPO / "packages" / "omniweave-pdf" / "fixtures" / "gen04p.pdf"
    pages = TOOL.pdf_pages(fixture)
    assert len(pages) == 4, "gen04p.pdf draws four pages"
    assert pages[0][0].startswith("Article 1."), pages[0][:2]


# 4 -- the signature: the user's, written where it belongs and nowhere else.


def test_stamp_appends_to_the_right_row_only() -> None:
    signed = TOOL._stamp(SIDECAR, "first", "verified")
    assert 'id = "first"' in signed
    assert signed.count("checked") == 1
    head, _, tail = signed.partition('[[assertion]]\nid = "second"')
    assert 'checked = "verified"' in head
    assert "checked" not in tail


def test_stamp_replaces_an_existing_signature() -> None:
    once = TOOL._stamp(SIDECAR, "second", "rejected")
    twice = TOOL._stamp(once, "second", "verified")
    assert twice.count("checked") == 1
    assert 'checked = "verified"' in twice


def test_stamp_keeps_crlf_where_the_file_has_it() -> None:
    """`autocrlf=true` leaves these files CRLF in the working tree (D>=CRLF ruling): a signature
    that wrote a bare LF into a CRLF file would show up as a whole-file diff."""
    signed = TOOL._stamp(SIDECAR.replace("\n", "\r\n"), "first", "verified")
    assert 'checked = "verified"\r\n' in signed
    assert "\n\n" not in signed.replace("\r\n", "\n").replace("\n\n", "")


def test_apply_writes_only_the_reviewers_two_values(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.txt.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    relative = "packages/p/fixtures/f.txt.assertions.toml"
    written = TOOL.apply_verdicts(tmp_path, {relative: {"first": "verified", "second": "rejected"}})
    assert written == [f"{Path(relative)}: 2 signed"]
    rows = {row["id"]: row.get("checked") for row in _rows(sidecar)}
    assert rows == {"first": "verified", "second": "rejected"}


@pytest.mark.parametrize(
    ("verdicts", "message"),
    [
        ({"first": "approved"}, "is not one of"),
        ({"first": True}, "is not one of"),
        ({"third": "verified"}, "no such assertion id"),
    ],
)
def test_apply_refuses_and_leaves_the_file_byte_identical(
    tmp_path: Path, verdicts: dict[str, object], message: str
) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.txt.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    before = sidecar.read_bytes()
    with pytest.raises(SystemExit, match=message):
        TOOL.apply_verdicts(tmp_path, {"packages/p/fixtures/f.txt.assertions.toml": verdicts})
    assert sidecar.read_bytes() == before


def test_apply_refuses_an_unknown_sidecar(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no such sidecar"):
        TOOL.apply_verdicts(tmp_path, {"nowhere.assertions.toml": {"first": "verified"}})


def test_one_bad_sidecar_stops_the_whole_write(tmp_path: Path) -> None:
    """Two sidecars, the second unsignable: the first must not be written either."""
    first = tmp_path / "packages" / "a" / "fixtures" / "f.txt.assertions.toml"
    second = tmp_path / "packages" / "b" / "fixtures" / "g.txt.assertions.toml"
    for path in (first, second):
        path.parent.mkdir(parents=True)
        path.write_bytes(SIDECAR.encode("utf-8"))
    before = first.read_bytes()
    with pytest.raises(SystemExit, match="no such assertion id"):
        TOOL.apply_verdicts(
            tmp_path,
            {
                "packages/a/fixtures/f.txt.assertions.toml": {"first": "verified"},
                "packages/b/fixtures/g.txt.assertions.toml": {"nope": "verified"},
            },
        )
    assert first.read_bytes() == before


def _rows(sidecar: Path) -> list[dict[str, object]]:
    return tomllib.loads(sidecar.read_text(encoding="utf-8"))["assertion"]


# 5 -- the bundle and the page.


def test_the_bundle_carries_every_label_and_says_what_agrees_means() -> None:
    data = TOOL.bundle(TOOL.review(REPO))
    assert data["schema"] == "omniweave.label-review/1"
    assert "not a reviewer's verdict" in data["note"]
    counted = sum(len(group["labels"]) for group in data["fixtures"])
    assert counted == len(TOOL.claims(REPO))


def test_the_page_names_every_label_and_disclaims_the_arithmetic() -> None:
    data = TOOL.bundle(TOOL.review(REPO))
    page = TOOL.page_html(data)
    assert "<title>" in page
    assert "not a verdict" in page
    for group in data["fixtures"]:
        for label in group["labels"]:
            assert label["id"] in page


def test_the_page_escapes_what_a_fixture_wrote() -> None:
    data = {
        "fixtures": [
            {
                "fixture": "f.txt",
                "sidecar": "f.txt.assertions.toml",
                "origin": "a test",
                "labels": [
                    {
                        "id": "x",
                        "type": "present",
                        "page": 1,
                        "claim": '<script>alert("x")</script>',
                        "toml": {},
                        "slices": [],
                        "checked": None,
                        "agrees": True,
                        "why": "ok",
                        "excerpt": ["<b>not markup</b>"],
                    }
                ],
            }
        ]
    }
    page = TOOL.page_html(data)
    #  The page has a script of its OWN since D1001 -- the one that collects verdicts -- so the
    #  assertion is that a fixture's text never becomes a second one, not that there are none.
    assert page.count("<script>") == 1
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "&lt;b&gt;not markup" in page


# 6 -- the program's exits.


def test_main_exits_clean_over_the_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "bundle.json"
    page = tmp_path / "review.html"
    assert (
        TOOL.main(["--root", str(REPO), "--json", str(out), "--page", str(page)]) == TOOL.EXIT_CLEAN
    )
    printed = capsys.readouterr().out
    assert "carry a reviewer's signature" in printed
    assert json.loads(out.read_text(encoding="utf-8"))["fixtures"]
    assert page.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_main_exits_two_when_a_row_has_no_evidence(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.unknownext.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    (sidecar.parent / "f.unknownext").write_bytes(b"")
    assert TOOL.main(["--root", str(tmp_path)]) == TOOL.EXIT_NO_EVIDENCE


def test_main_exits_one_when_a_claim_contradicts_the_bytes(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "rows.csv.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(
        b'schema = "omniweave.assertions/1"\n\n[[assertion]]\nid = "wrong"\n'
        b'type = "present"\npage = 1\ntext = "not in the file"\nslices = ["x"]\n'
    )
    (sidecar.parent / "rows.csv").write_bytes(b"a,b\n1,2\n")
    assert TOOL.main(["--root", str(tmp_path)]) == TOOL.EXIT_DISAGREES


# 4 -- the structure references: the second population, whose unit is the document.


STRUCTURE = (
    '{"schema": "omniweave.structure/1"}\n'
    '{"id": "s01", "page": 1, "kind": "heading", "layer": "body", '
    '"parent_kind": "document", "text": "Alpha"}\n'
    '{"id": "s02", "page": 1, "kind": "paragraph", "layer": "body", '
    '"parent_kind": "document", "text": "Beta"}\n'
)


def _reference(**over: object) -> object:
    body: dict[str, object] = {
        "sidecar": Path("f.docx.structure.jsonl"),
        "fixture": Path("f.docx"),
        "id": "s01",
        "page": 1,
        "kind": "paragraph",
        "layer": "body",
        "parent_kind": "document",
        "text": "Hello",
        "checked": None,
    }
    return TOOL.Reference(**{**body, **over})


def test_every_committed_reference_row_agrees_with_the_bytes_or_is_named_unconfirmable() -> None:
    """The committed references, read back off the fixtures. **Zero may disagree.**

    A row the file contradicts is a defect to mend before a reviewer sees it, exactly as a drafted
    assertion is. A row this tool cannot confirm is allowed and is counted: it is the formula
    transcription case, and naming it is the alternative to calling the reference wrong.
    """
    readings = TOOL.read_structure(REPO)
    disagree = [one for one in readings if one.agrees is False]
    assert disagree == [], [one.why for one in disagree]
    unknown = [one.reference.id for one in readings if one.agrees is None]
    assert len(readings) == 277, "the committed population; a new reference belongs in this count"
    assert unknown == ["s04", "s05"], "the two OMML rows of rich.docx and nothing else"


def test_the_signature_unit_is_the_document_and_every_one_is_signed_whole() -> None:
    """`structure` ruling 3: a document scores only when EVERY row of its reference is verified.

    This asserted `{None}` -- "this repository has signed no reference row" -- until the reviewer
    signed on 2026-10-30. The ruling it tests is about the UNIT, not about the count, so what it
    says now is that no document is part-signed: a reference with some rows verified and some not
    has no precision denominator, which is the defect ruling 3 exists to prevent.
    """
    grouped = TOOL.documents(TOOL.read_structure(REPO))
    assert len(grouped) == 33
    for name, group in grouped.items():
        signed = {one.reference.checked for one in group}
        assert len(signed) == 1, f"{name} is part-signed: {sorted(signed, key=str)}"
        assert signed == {"verified"}, name


def test_a_reference_row_the_bytes_do_not_carry_disagrees() -> None:
    evidence = TOOL.Evidence("a test", runs=("Alpha", "Beta"), pages=(("Alpha", "Beta"),))
    reading = TOOL._unmatched(_reference(text="Gamma"), evidence, evidence.runs, ["Alpha", "Beta"])
    assert reading.agrees is False
    assert "carries no text folding to 'Gamma'" in reading.why


def test_a_transcription_is_unconfirmable_only_where_the_document_carries_a_formula() -> None:
    """The tier's bound, which is the whole of why it is not an excuse.

    `x2+1` and `x^{2}+1` are the same letters and digits with different notation. At a paragraph
    the reader saw carry OMML that is a transcription it cannot confirm; at any other paragraph it
    is a row that disagrees with the bytes, and the only difference is `Evidence.derived`.
    """
    runs = ("x2+1",)
    row = _reference(text="x^{2}+1")
    with_math = TOOL.Evidence("a test", runs=runs, pages=(runs,), derived=(0,))
    without = TOOL.Evidence("a test", runs=runs, pages=(runs,))
    assert TOOL._unmatched(row, with_math, runs, list(runs)).agrees is None
    assert TOOL._unmatched(row, without, runs, list(runs)).agrees is False


def test_a_formula_paragraph_does_not_excuse_a_row_that_invents_content() -> None:
    """The subsequence is of the BYTES' letters, so a row may add notation and never content."""
    runs = ("x2+1",)
    evidence = TOOL.Evidence("a test", runs=runs, pages=(runs,), derived=(0,))
    assert TOOL._unmatched(_reference(text="y^{3}+2"), evidence, runs, list(runs)).agrees is False
    assert TOOL._transcribes("x2+1", TOOL.letters("x^{2}+1")) is True
    assert TOOL._transcribes("x2+1", TOOL.letters("x^{3}+1")) is False


def _tree(tmp_path: Path, *texts: str) -> Path:
    """A one-fixture tree: a CSV of three cells, and a reference naming `texts` in that order."""
    where = tmp_path / "packages" / "p" / "fixtures"
    where.mkdir(parents=True)
    (where / "f.csv").write_text("Alpha,Beta,Gamma\n", encoding="utf-8", newline="")
    rows = ['{"schema": "omniweave.structure/1"}']
    rows += [
        json.dumps(
            {
                "id": f"s{index:02d}",
                "page": 1,
                "kind": "paragraph",
                "layer": "body",
                "parent_kind": "table_cell",
                "text": text,
            }
        )
        for index, text in enumerate(texts, start=1)
    ]
    (where / "f.csv.structure.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8", newline=""
    )
    return tmp_path


def test_a_reference_in_the_documents_own_order_agrees(tmp_path: Path) -> None:
    readings = TOOL.read_structure(_tree(tmp_path, "Alpha", "Beta", "Gamma"))
    assert [one.agrees for one in readings] == [True, True, True]
    assert [one.at for one in readings] == [0, 1, 2]


def test_a_reference_out_of_the_documents_own_order_is_a_finding(tmp_path: Path) -> None:
    """The defect a reviewer reading row by row would never see: every row is in the file, and
    the rows are not in the order the file carries them."""
    readings = TOOL.read_structure(_tree(tmp_path, "Alpha", "Gamma", "Beta"))
    assert [one.agrees for one in readings] == [True, True, False]
    assert "BEFORE the previous row's 2" in readings[2].why


def test_the_docx_reader_reaches_the_footnote_part() -> None:
    """D1001: `word/footnotes.xml` is a separate part, and `rich.docx`'s last row is in it."""
    evidence = TOOL.read_evidence(REPO / "packages/omniweave-office/fixtures/rich.docx")
    assert "Unaudited figures." in evidence.runs
    assert "footnotes.xml" in evidence.origin


def test_the_pptx_reader_reaches_the_speaker_note_part() -> None:
    """D1001: a row carrying `layer = "note"` is a claim about `ppt/notesSlides/`."""
    evidence = TOOL.read_evidence(REPO / "packages/omniweave-office/fixtures/deck.pptx")
    assert "Mention the backlog only if asked." in evidence.runs
    assert "notesSlides" in evidence.origin


def test_the_epub_reader_reaches_the_package_title() -> None:
    """D1001: an EPUB's title is `content.opf` metadata; the XHTML does not carry it."""
    evidence = TOOL.read_evidence(REPO / "packages/omniweave-office/fixtures/book.epub")
    assert evidence.runs[0] == "A very short book"
    assert "dc:title" in evidence.origin


def test_the_math_index_counts_the_paragraphs_the_text_walk_counts() -> None:
    """Off by one here and the tier excuses the wrong paragraph, which is worse than not having
    it: a blank paragraph is dropped by `_paragraphs` and must be dropped by this too."""
    document = TOOL._members(
        REPO / "packages/omniweave-office/fixtures/rich.docx",
        TOOL.re.compile(r"^word/document\.xml$"),
    )[0]
    runs = TOOL._paragraphs(document)
    for index in TOOL._math_paragraphs(document):
        assert index < len(runs)
        assert runs[index] in {"x2+1", "The ratio ab"}


def test_signing_a_document_writes_one_verdict_into_every_row(tmp_path: Path) -> None:
    sidecar = tmp_path / "f.docx.structure.jsonl"
    sidecar.write_text(STRUCTURE, encoding="utf-8", newline="")
    blob, count = TOOL.signed_document(sidecar, "verified")
    assert count == 2
    rows = [json.loads(line) for line in blob.decode("utf-8").splitlines()[1:]]
    assert [row["checked"] for row in rows] == ["verified", "verified"]
    assert [row["id"] for row in rows] == ["s01", "s02"]


def test_signing_does_not_reach_disk_and_keeps_the_header(tmp_path: Path) -> None:
    sidecar = tmp_path / "f.docx.structure.jsonl"
    sidecar.write_text(STRUCTURE, encoding="utf-8", newline="")
    blob, _count = TOOL.signed_document(sidecar, "rejected")
    assert sidecar.read_text(encoding="utf-8") == STRUCTURE, "staged, never written here"
    assert blob.decode("utf-8").splitlines()[0] == '{"schema": "omniweave.structure/1"}'


def test_a_row_the_verdict_does_not_change_round_trips_byte_for_byte(tmp_path: Path) -> None:
    """`json.dumps`' default separators are the ones these files use, so signing a file twice is
    the same bytes -- which is what makes a diff of a review readable."""
    sidecar = tmp_path / "f.docx.structure.jsonl"
    sidecar.write_text(STRUCTURE, encoding="utf-8", newline="")
    once, _ = TOOL.signed_document(sidecar, "verified")
    sidecar.write_bytes(once)
    twice, _ = TOOL.signed_document(sidecar, "verified")
    assert twice == once


def test_apply_refuses_a_per_row_verdict_for_a_structure_reference(tmp_path: Path) -> None:
    """The shape chooses the population, so the wrong shape is refused by name."""
    sidecar = tmp_path / "f.docx.structure.jsonl"
    sidecar.write_text(STRUCTURE, encoding="utf-8", newline="")
    with pytest.raises(SystemExit, match="ONE verdict for the document"):
        TOOL.apply_verdicts(tmp_path, {"f.docx.structure.jsonl": {"s01": "verified"}})
    assert sidecar.read_text(encoding="utf-8") == STRUCTURE


def test_apply_refuses_a_document_verdict_for_an_assertions_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "f.assertions.toml"
    sidecar.write_text(SIDECAR, encoding="utf-8", newline="")
    with pytest.raises(SystemExit, match="one verdict per row"):
        TOOL.apply_verdicts(tmp_path, {"f.assertions.toml": "verified"})
    assert sidecar.read_text(encoding="utf-8") == SIDECAR


def test_apply_refuses_a_document_verdict_outside_the_two(tmp_path: Path) -> None:
    sidecar = tmp_path / "f.docx.structure.jsonl"
    sidecar.write_text(STRUCTURE, encoding="utf-8", newline="")
    with pytest.raises(SystemExit, match="'approved' is not one of"):
        TOOL.apply_verdicts(tmp_path, {"f.docx.structure.jsonl": "approved"})
    assert sidecar.read_text(encoding="utf-8") == STRUCTURE


def test_one_refused_document_stops_every_write(tmp_path: Path) -> None:
    good = tmp_path / "a.docx.structure.jsonl"
    bad = tmp_path / "b.docx.structure.jsonl"
    for path in (good, bad):
        path.write_text(STRUCTURE, encoding="utf-8", newline="")
    with pytest.raises(SystemExit):
        TOOL.apply_verdicts(
            tmp_path,
            {"a.docx.structure.jsonl": "verified", "b.docx.structure.jsonl": "approved"},
        )
    assert good.read_text(encoding="utf-8") == STRUCTURE


def test_the_structure_bundle_is_keyed_by_document_and_says_what_it_does_not_judge() -> None:
    data = TOOL.structure_bundle(TOOL.read_structure(REPO), REPO)
    assert data["schema"] == "omniweave.structure-review/1"
    assert len(data["documents"]) == 33
    assert "per DOCUMENT" in data["note"]
    assert "kind, layer, parent_kind) is the reviewer's judgement" in data["note"]
    first = data["documents"][0]
    assert first["reference"].endswith(".structure.jsonl")
    assert all("claim" in row and "why" in row for row in first["rows"])


def test_the_page_carries_both_populations_and_says_which_unit_each_signs() -> None:
    rows = TOOL.review(REPO)
    page = TOOL.page_html(
        TOOL.bundle(rows, REPO), TOOL.structure_bundle(TOOL.read_structure(REPO), REPO)
    )
    assert "Structure references" in page
    assert "per document, not per row" in page
    assert "packages/omniweave-office/fixtures/rich.docx" in page
    for one in TOOL.read_structure(REPO):
        assert TOOL._esc(one.reference.text) in page


def test_the_page_without_a_structure_bundle_is_the_assertions_page() -> None:
    """The second argument is optional, so the first population's page is unchanged by D1001."""
    page = TOOL.page_html(TOOL.bundle(TOOL.review(REPO), REPO))
    assert "Structure references" not in page


def _page() -> str:
    return TOOL.page_html(
        TOOL.bundle(TOOL.review(REPO), REPO),
        TOOL.structure_bundle(TOOL.read_structure(REPO), REPO),
    )


def test_the_page_carries_one_control_per_assertion_and_one_per_document() -> None:
    """D1001: a page with no way to record a verdict is not a page that prepares a signature.

    110 assertions sign one at a time and 10 references sign whole, which is `structure` ruling
    3's unit, and the count of controls is the two populations added rather than a number typed
    here: a drafted label or a new reference moves it.
    """
    page = _page()
    labels = len(TOOL.review(REPO))
    files = len(TOOL.documents(TOOL.read_structure(REPO)))
    assert page.count("class=verdict data-key=") == labels + files
    assert page.count("value=verified") == labels + files


def test_every_control_is_keyed_the_way_apply_reads_it() -> None:
    """The export is `--apply`'s own grammar, so the keys are the paths that file names: a row of
    an assertions sidecar as `<path>::<id>`, a whole reference as `<path>`."""
    page = _page()
    for row in TOOL.review(REPO):
        key = f"{TOOL._posix(row.claim.sidecar, REPO)}::{row.claim.id}"
        assert f'data-key="{key}"' in page
    for sidecar in TOOL.documents(TOOL.read_structure(REPO)):
        key = TOOL._posix(sidecar, REPO)
        assert f'data-key="{key}"' in page
        assert f'data-key="{key}::' not in page, "a reference signs whole, never row by row"


def test_the_page_is_a_whole_document_that_scales_on_a_phone() -> None:
    page = _page()
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert 'name="viewport"' in page


def test_the_page_says_nothing_is_written_until_the_command_runs() -> None:
    """The tool's own rule, on the page that collects: this file never writes a signature."""
    page = _page()
    assert "--apply" in page
    assert "Nothing is written until you run that command." in page


def test_a_reference_whose_header_is_not_the_schema_stops_the_read(tmp_path: Path) -> None:
    """Ruling 1's header, enforced: a reference with no version is one nothing else will read."""
    (tmp_path / "packages" / "p" / "fixtures").mkdir(parents=True)
    bad = tmp_path / "packages" / "p" / "fixtures" / "f.docx.structure.jsonl"
    bad.write_text('{"schema": "something/9"}\n', encoding="utf-8", newline="")
    with pytest.raises(SystemExit, match="first line is not"):
        TOOL.references(tmp_path)


# 5 -- TRANSCRIBED: the two rows no byte reader can confirm, declared and checked both ways.


def test_the_declaration_matches_the_tree_exactly() -> None:
    """Both directions over the real tree, which is the only statement that matters here."""
    assert TOOL.transcription_findings(TOOL.read_structure(REPO), REPO) == []
    assert len(TOOL.TRANSCRIBED) == 2


def test_an_undeclared_transcription_is_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise a second one arrives silently and the exit code keeps saying clean."""
    monkeypatch.setattr(TOOL, "TRANSCRIBED", ())
    findings = TOOL.transcription_findings(TOOL.read_structure(REPO), REPO)
    assert len(findings) == 2
    assert all("not in TRANSCRIBED" in one for one in findings)


def test_a_declaration_for_a_row_that_now_reads_cleanly_is_a_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declaration that stopped being true is a comment, so the stale direction fails too."""
    monkeypatch.setattr(
        TOOL,
        "TRANSCRIBED",
        (
            *TOOL.TRANSCRIBED,
            (
                "packages/omniweave-office/fixtures/rows.csv.structure.jsonl",
                "s01",
                "region",
                "region",
            ),
        ),
    )
    findings = TOOL.transcription_findings(TOOL.read_structure(REPO), REPO)
    assert len(findings) == 1
    assert "declared a transcription and now reads True" in findings[0]


def test_a_declaration_whose_recorded_strings_drifted_is_a_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declaration records WHAT the bytes say, so a fixture edit that changes it fails here
    rather than leaving a reviewer reading a sentence about a file that moved."""
    path, label, _said, says = TOOL.TRANSCRIBED[0]
    monkeypatch.setattr(
        TOOL, "TRANSCRIBED", ((path, label, "something else", says), TOOL.TRANSCRIBED[1])
    )
    findings = TOOL.transcription_findings(TOOL.read_structure(REPO), REPO)
    assert len(findings) == 1
    assert "TRANSCRIBED records 'something else'" in findings[0]


def test_main_exits_clean_with_the_declaration_and_two_without_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reason the declaration exists: a permanent exit 2 is an exit code that says nothing."""
    assert TOOL.main([]) == TOOL.EXIT_CLEAN
    monkeypatch.setattr(TOOL, "TRANSCRIBED", ())
    assert TOOL.main([]) == TOOL.EXIT_NO_EVIDENCE
    assert "TRANSCRIBED:" in capsys.readouterr().out
