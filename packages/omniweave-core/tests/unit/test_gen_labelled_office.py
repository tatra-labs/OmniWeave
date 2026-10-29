"""`fixtures/gen/gen_labelled_office.py`: the labelled office corpus and its references. **D1004.**

The growth corpus `structure_f1` needs, under the user ruling of 2026-10-28 that made the slice
`office/labelled`. Every document is generated from one `Outline`, and so is its
`.structure.jsonl`, so these tests ask three things: that the committed bytes, sidecars and
references are this script's output and nothing else; that the outline rules hold over every
committed outline and bite when one breaks them; and that each sidecar joins both slices.

There is no `EXPECTED.sha256` here on purpose -- that file belongs to `gen_office_fixtures.py`,
and `omniweave_conform.harness.NOT_INPUTS` names exactly it, so a second manifest beside it would
reach the conformance harness as a document. The pin is each sidecar's own `sha256`, which Q-G1
checks against the bytes, and the first test below, which holds the sidecar to the generator.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from omniweave_core.drivers.card import MIN_SLICE_N
from omniweave_core.model import Kind, Layer

REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "packages" / "omniweave-office" / "fixtures"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load(REPO / "fixtures" / "gen" / "gen_labelled_office.py", "_owgen_gen_labelled_office")


def _names() -> list[str]:
    return sorted(GEN.OUTLINES)


# --- the committed tree is this script's output ------------------------------------------------


@pytest.mark.parametrize("name", _names())
def test_each_document_is_the_generators_output(name: str) -> None:
    assert (FIXTURES / name).read_bytes() == GEN.build(name)


@pytest.mark.parametrize("name", _names())
def test_each_sidecar_is_the_generators_output(name: str) -> None:
    """The sidecar is the pin: this plus Q-G1's digest check is `EXPECTED.sha256`'s job done in
    the place the gate already looks."""
    data = GEN.build(name)
    wanted = GEN.sidecar(name, GEN.OUTLINES[name], data)
    assert (FIXTURES / f"{name}.meta.toml").read_bytes() == wanted.encode("utf-8")


@pytest.mark.parametrize("name", _names())
def test_each_reference_is_the_outline_it_was_written_from(name: str) -> None:
    assert (FIXTURES / f"{name}.structure.jsonl").read_bytes() == GEN.reference(
        GEN.OUTLINES[name]
    ).encode("utf-8")


def test_a_build_is_a_function_of_the_outline_alone() -> None:
    """13-quality.md section 4.2's determinism rule: the bytes depend on this file and nothing
    else, so `EXPECTED.sha256` elsewhere and the sidecars here are real checks rather than a
    snapshot of whichever machine ran last."""
    for name in _names():
        assert GEN.build(name) == GEN.build(name)


# --- the reference the outline declares ---------------------------------------------------------


def _rows(name: str) -> list[dict[str, object]]:
    lines = GEN.reference(GEN.OUTLINES[name]).splitlines()
    return [json.loads(line) for line in lines[1:]]


def test_the_reference_opens_with_the_schema_header() -> None:
    """`structure` ruling 1: a JSONL file with no version is a file whose shape cannot change."""
    first = GEN.reference(GEN.OUTLINES["minutes.odt"]).splitlines()[0]
    assert json.loads(first) == {"schema": "omniweave.structure/1"}


@pytest.mark.parametrize("name", _names())
def test_every_row_is_the_outlines_row_in_order(name: str) -> None:
    outline = GEN.OUTLINES[name]
    assert [
        (row["id"], row["kind"], row["layer"], row["parent_kind"], row["text"])
        for row in _rows(name)
    ] == [
        (f"s{at:02d}", one.kind, one.layer, one.parent_kind, one.text)
        for at, one in enumerate(outline.rows, start=1)
    ]


@pytest.mark.parametrize("name", _names())
def test_no_row_carries_a_reviewers_signature(name: str) -> None:
    """D913 stands: Claude drafts, the user verifies, and a reference signs whole through
    `tools/label_review.py --page`. Nothing here is signed."""
    assert all("checked" not in row for row in _rows(name))


@pytest.mark.parametrize("name", _names())
def test_every_kind_and_layer_is_a_real_member(name: str) -> None:
    """`structure` ruling 2: a value outside `Kind` or `Layer` is a `QualityError` naming the row,
    so a typo here would land as a corpus that cannot be loaded at all."""
    for row in _rows(name):
        assert Kind(row["kind"]) is not None
        assert Layer(row["layer"]) is not None


# --- the outline rules --------------------------------------------------------------------------


@pytest.mark.parametrize("name", _names())
def test_every_committed_outline_has_distinct_text(name: str) -> None:
    GEN.unique(GEN.OUTLINES[name])


def test_a_repeated_text_is_refused() -> None:
    """Four of the first eleven outlines had one, and every one read as a disagreement against the
    bytes until the text was made distinct. The rule is enforced rather than remembered."""
    outline = GEN.Outline(
        "rtf",
        "two paragraphs that say the same thing",
        (
            GEN.Row("paragraph", "document", "the same line"),
            GEN.Row("paragraph", "document", "the same line"),
        ),
    )
    with pytest.raises(ValueError, match=r"s02 repeats the text of s01"):
        GEN.unique(outline)


def test_a_table_without_a_column_count_is_refused() -> None:
    """A run of cells with no `cols` has no shape, and chunking it by one would emit a table of
    single-cell rows that no reference row says anything about."""
    outline = GEN.Outline(
        "csv",
        "two cells and no width",
        (
            GEN.Row("paragraph", "table_cell", "left"),
            GEN.Row("paragraph", "table_cell", "right"),
        ),
    )
    with pytest.raises(ValueError, match=r"needs an Outline.cols"):
        GEN.WRITERS["csv"](outline)


def test_a_note_layer_row_is_last_in_its_outline() -> None:
    """A footnote lives in its own part and a byte reader finds it after the body whatever the
    outline says, which is where `rich.docx`'s `s13` sits. So the row goes last or the order check
    in `tools/label_review.py` reports it, as it did for `policy.docx` on the first run."""
    for name, outline in GEN.OUTLINES.items():
        notes = [at for at, row in enumerate(outline.rows) if row.layer == "note"]
        assert notes in ([], [len(outline.rows) - 1]), name


# --- the slices -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", _names())
def test_each_sidecar_joins_its_extension_and_the_coarse_slice(name: str) -> None:
    """D1002: the per-extension key comes from the format, so a new document in an existing
    format joins that slice with no table to update, and the coarse key is what can reach
    `min_slice_n`. Q-G1 ruling 14 holds the pair together from the other side."""
    outline = GEN.OUTLINES[name]
    sidecar = tomllib.loads((FIXTURES / f"{name}.meta.toml").read_text(encoding="utf-8"))
    declared = sidecar["fixture"]["tests"]["slices"]
    facet = [f"office/{outline.fmt}/has_merges=1"] if GEN.merges(outline) else []
    assert declared == [*facet, f"office/{outline.fmt}", "office/labelled"]
    assert bool(facet) == any(row.span > 1 for row in outline.rows), (
        "D1005: the facet is derived from the spans, in both directions"
    )


def test_the_coarse_slice_holds_every_labelled_office_document() -> None:
    """The count the ruling is about, read off the committed index rather than typed: the ten
    `gen_office_fixtures.py` cases plus these, all on one key, against `min_slice_n = 30`."""
    rows = tomllib.loads((REPO / "fixtures" / "index.toml").read_text(encoding="utf-8"))["fixture"]
    on_key = [
        row["path"] for row in rows if "office/labelled" in row.get("tests", {}).get("slices", ())
    ]
    assert len(on_key) == 10 + len(GEN.OUTLINES)
    assert all((REPO / (path + ".structure.jsonl")).is_file() for path in on_key)


# --- the command ------------------------------------------------------------------------------


def test_check_is_clean_over_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert GEN.main(["--check", "--out", str(FIXTURES)]) == 0
    assert "STALE" not in capsys.readouterr().out


def test_check_names_a_stale_file_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GEN.main(["--out", str(tmp_path)]) == 0
    name = _names()[0]
    (tmp_path / f"{name}.structure.jsonl").write_bytes(b"{}\n")
    assert GEN.main(["--check", "--out", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert f"STALE  {name}.structure.jsonl" in out
    assert "1 stale file(s)" in out


def test_writing_into_an_empty_tree_lands_every_file_the_script_owns(tmp_path: Path) -> None:
    """Three files a document, and a fourth -- the labels -- for every document but the three
    whose labels another author owns (D1020). The arithmetic is spelled out rather than derived
    from `labels()`, so a document silently losing its labels file fails here."""
    assert GEN.main(["--out", str(tmp_path)]) == 0
    written = sorted(path.name for path in tmp_path.iterdir())
    assert len(written) == 3 * len(GEN.OUTLINES) + (len(GEN.OUTLINES) - len(GEN.DRAFTED))
    for name in _names():
        assert {name, f"{name}.meta.toml", f"{name}.structure.jsonl"} <= set(written)
        has_labels = f"{name}.assertions.toml" in set(written)
        assert has_labels is (name not in GEN.DRAFTED), name


# --- the labels the outline declares (D1020, D1021) ---------------------------------------------


def _labelled() -> list[str]:
    return [one for one in _names() if one not in GEN.DRAFTED]


@pytest.mark.parametrize("name", _labelled())
def test_each_labels_file_is_the_generators_output(name: str) -> None:
    wanted = GEN.labels(name, GEN.OUTLINES[name])
    assert wanted is not None
    assert (FIXTURES / f"{name}.assertions.toml").read_bytes() == wanted.encode("utf-8")


@pytest.mark.parametrize("name", sorted(GEN.DRAFTED))
def test_the_drafted_three_are_not_this_scripts_to_write(name: str) -> None:
    """The exception, checked in BOTH directions. `labels()` declines to write these, and the file
    beside the fixture exists anyway -- it carries D1005's `table` and `cell_rel` rows, which are
    grid geometry an `Outline` does not declare. A name added to `DRAFTED` without a drafted file
    fails the second assertion; one removed from it fails `test_each_labels_file_is_...`."""
    assert name in GEN.OUTLINES
    assert GEN.labels(name, GEN.OUTLINES[name]) is None
    committed = FIXTURES / f"{name}.assertions.toml"
    assert committed.is_file(), "a DRAFTED name owes a hand-drafted labels file"
    assert "GENERATED by" not in committed.read_text(encoding="utf-8")


def _office_assertions() -> list[tuple[str, dict[str, object]]]:
    out: list[tuple[str, dict[str, object]]] = []
    for path in sorted(FIXTURES.glob("*.assertions.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        out.extend((path.name, one) for one in data["assertion"])
    return out


def test_the_coarse_slice_leads_every_office_order_assertion() -> None:
    """D1021, a user ruling of 2026-10-29. A verdict takes its assertion's FIRST slice and only
    that one (`judge` ruling 5), so the coarse key has to LEAD -- appending it would change
    nothing at all, which is the mistake this test exists to catch."""
    wrong = [
        (where, one["id"], one.get("slices"))
        for where, one in _office_assertions()
        if one["type"] == "order" and (one.get("slices") or ["*"])[0] != GEN.COARSE
    ]
    assert not wrong, f"an order assertion whose verdict lands outside {GEN.COARSE}: {wrong}"


def test_the_coarse_order_slice_reaches_min_slice_n() -> None:
    """The point of D1020, as a number. 15 drafted order assertions over six per-format slices of
    3, 4, 1, 3, 2 and 2 could never admit one; 20 one-per-document claims take the coarse slice to
    35. `release-check` reports exactly this population as "35 unverified assertion(s)"."""
    n = sum(
        1
        for _, one in _office_assertions()
        if one["type"] == "order" and (one.get("slices") or ["*"])[0] == GEN.COARSE
    )
    assert n >= MIN_SLICE_N, f"{n} order assertion(s) in {GEN.COARSE}, under {MIN_SLICE_N}"
    assert n == 35, f"{n} order assertion(s); the ruling's arithmetic was 15 + 20"


def test_the_gated_merge_slice_still_leads_its_own_assertions() -> None:
    """The regression D1021 could have caused. `table_rel_acc`'s register row is `*/has_merges=1`,
    so putting the coarse key first on a `table` or `cell_rel` row would have emptied the one
    office slice that already clears `min_slice_n` -- 33 `table` and 18 `cell_rel`, 51 verdicts."""
    merged = [
        one
        for _, one in _office_assertions()
        if one["type"] in {"table", "cell_rel"}
        and GEN.COARSE in (one.get("slices") or [])
        and (one.get("slices") or [""])[0] != "office/has_merges=1"
    ]
    assert not merged, f"a merge-slice assertion no longer leads with its gated key: {merged}"
    n = sum(
        1
        for _, one in _office_assertions()
        if one["type"] in {"table", "cell_rel"}
        and (one.get("slices") or ["*"])[0] == "office/has_merges=1"
    )
    assert n == 51, f"{n} verdicts in office/has_merges=1, not the 33 + 18 D1005 landed"


@pytest.mark.parametrize("name", _labelled())
def test_no_generated_assertion_carries_a_signature(name: str) -> None:
    """D913 again, on the other label kind: Claude drafts, the user verifies."""
    data = tomllib.loads((FIXTURES / f"{name}.assertions.toml").read_text(encoding="utf-8"))
    assert all("checked" not in one for one in data["assertion"])


def test_order_pair_takes_the_first_structural_transition() -> None:
    outline = GEN.Outline(
        fmt="docx",
        purpose="three rows, the change at the second",
        rows=(
            GEN.Row("paragraph", "document", "one"),
            GEN.Row("paragraph", "list_item", "two"),
            GEN.Row("paragraph", "list_item", "three"),
        ),
    )
    assert GEN.order_pair(outline) == 0


def test_order_pair_takes_a_later_transition_when_the_first_rows_match() -> None:
    """Driven separately from the test above, because returning 0 unconditionally passes that one
    and this is what says the search actually walks the rows."""
    outline = GEN.Outline(
        fmt="docx",
        purpose="the change at the third row",
        rows=(
            GEN.Row("paragraph", "document", "one"),
            GEN.Row("paragraph", "document", "two"),
            GEN.Row("heading", "document", "three"),
        ),
    )
    assert GEN.order_pair(outline) == 1


def test_order_pair_falls_back_to_the_first_pair_with_no_transition() -> None:
    """The nine spreadsheets here: every row a `table_cell`, and the pair is the reading order a
    cell parser inverts."""
    outline = GEN.Outline(
        fmt="xlsx",
        purpose="two cells of one row",
        rows=(
            GEN.Row("paragraph", "table_cell", "Line"),
            GEN.Row("paragraph", "table_cell", "Budgeted"),
        ),
        cols=2,
    )
    assert GEN.order_pair(outline) == 0


def test_order_pair_declines_a_document_with_one_row() -> None:
    outline = GEN.Outline(
        fmt="rtf", purpose="one row", rows=(GEN.Row("paragraph", "document", "alone"),)
    )
    assert GEN.order_pair(outline) is None
    assert GEN.labels("alone.rtf", outline) is None


@pytest.mark.parametrize(
    ("text", "wanted"),
    [
        ('a "quoted" word', 'a \\"quoted\\" word'),
        ("a back\\slash", "a back\\\\slash"),
        ("neither", "neither"),
    ],
)
def test_esc_toml_escapes_a_basic_strings_two(text: str, wanted: str) -> None:
    assert GEN.esc_toml(text) == wanted


@pytest.mark.parametrize("name", _labelled())
def test_every_generated_claim_round_trips_to_the_outlines_exact_text(name: str) -> None:
    """The guarantee that matters, and the one that catches a missing escape for any row.

    An earlier version of this test asserted that NO committed row carries a quote or a backslash,
    and `receipt.rtf` does: its `s03` reads `Reference: NA\\2026\\114`. So `esc_toml` is not
    decorative -- it is one outline edit away from being the only thing keeping a generated file
    parseable -- and the claim worth holding is this: whatever the text, what `tomllib` reads back
    is the outline's row, byte for byte.
    """
    outline = GEN.OUTLINES[name]
    at = GEN.order_pair(outline)
    assert at is not None
    data = tomllib.loads((FIXTURES / f"{name}.assertions.toml").read_text(encoding="utf-8"))
    (one,) = data["assertion"]
    assert one["before"] == outline.rows[at].text
    assert one["after"] == outline.rows[at + 1].text


def test_a_row_needing_an_escape_still_writes_a_parseable_file() -> None:
    """Driven, not assumed: an outline whose asserted pair carries both escapes."""
    outline = GEN.Outline(
        fmt="rtf",
        purpose="a quote and a backslash in the asserted pair",
        rows=(
            GEN.Row("heading", "document", 'He said "NA\\2026\\114"'),
            GEN.Row("paragraph", "document", 'a \\ and a " again'),
        ),
    )
    text = GEN.labels("escapes.rtf", outline)
    assert text is not None
    (one,) = tomllib.loads(text)["assertion"]
    assert one["before"] == 'He said "NA\\2026\\114"'
    assert one["after"] == 'a \\ and a " again'


def _formats() -> list[str]:
    return sorted({outline.fmt for outline in GEN.OUTLINES.values()})


@pytest.mark.parametrize("fmt", _formats())
def test_every_declared_format_has_a_writer_and_a_media_type(fmt: str) -> None:
    assert fmt in GEN.WRITERS
    assert fmt in GEN.MEDIA_TYPES
