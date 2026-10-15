"""`omniweave_conform.churn`: the decomposition table, the shape delta and the churn class. D819."""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_conform.churn import (
    CHURN_SYMBOL,
    Decomposition,
    Delta,
    Reductions,
    Row,
    classify,
    explain,
    load_decomposition,
    refuse_unexplained,
    shape_delta,
)
from omniweave_conform.reduce import SHAPE_FAMILIES
from omniweave_core.errors import QualityError

REPO = Path(__file__).resolve().parents[4]
TABLE = REPO / "fixtures" / "goldens" / "DECOMPOSITION.toml"

SHAPE_HEAD = "owshape/1  corpus=c  doc=k  driver=d@1  schema_v=1"
PAGES_HEAD = "owpages/1  corpus=c  doc=k  driver=d@1  schema_v=1"
OUTLINE_HEAD = "owoutline/1  corpus=c  doc=k  driver=d@1  schema_v=1"


def _text(head: str, *lines: str) -> str:
    return "".join(f"{line}\n" for line in (head, *lines))


def _shape(**counters: str) -> str:
    base = {
        "blocks.kind.paragraph": "3",
        "blocks.layer.body": "3",
        "blocks.total": "3",
        "pages.total": "1",
        "quote.normalized": "3",
        "trust.extracted": "3",
    }
    base.update({k.replace("__", "."): v for k, v in counters.items()})
    return _text(SHAPE_HEAD, *(f"{k} {v}" for k, v in sorted(base.items())))


def _page(
    *,
    n: int = 3,
    kind: str = "paragraph:3",
    layer: str = "body:3",
    trust: str = "extracted:3",
    quote: str = "normalized:3",
    cdig: str = "aaaaaaaa",
    diag: str = "",
) -> str:
    return (
        f"p0000 n={n} kind{{{kind}}} layer{{{layer}}} trust{{{trust}}} quote{{{quote}}}"
        f" cdig={cdig} ldig=bbbbbbbb diag{{{diag}}}"
    )


def _outline(*extra: str, first: str = "00000000 - Net revenue rose") -> str:
    return _text(
        OUTLINE_HEAD,
        f"p0/0 paragraph body extracted normalized {first}",
        "p0/1 paragraph body extracted normalized 11111111 - Operating costs fell",
        "p0/2 paragraph body extracted normalized 22222222 -",
        *extra,
    )


BASE = Reductions(_shape(), _text(PAGES_HEAD, _page()), _outline())


@pytest.fixture(scope="module")
def table() -> Decomposition:
    return load_decomposition(TABLE)


# --- the table -------------------------------------------------------------------------------


def test_the_committed_table_is_the_reducers_families(table: Decomposition) -> None:
    table.verify()
    assert sorted(row.id for row in table.rows) == sorted(SHAPE_FAMILIES)


def test_the_committed_table_keeps_the_plans_rows(table: Decomposition) -> None:
    """13:752-781's nine rows, as printed, but `diag.*` (D818's finding, ruling 2 of D819)."""
    wise = {row.id: row.page_wise for row in table.rows}
    assert wise["blocks.total"] and wise["blocks.kind.*"] and wise["trust.*"]
    assert wise["quote.*"] and wise["marks.kind.*"]
    assert not wise["grid.tables_with_merges"]
    assert not wise["rel.kind.*"]
    assert not wise["quad.present_frac"]
    assert not wise["diag.*"]
    assert all(row.reason for row in table.rows if not row.page_wise)


def test_a_table_short_of_a_family_or_long_of_one_is_refused() -> None:
    rows = tuple(Row(id=f, page_wise=False, reason="r") for f in SHAPE_FAMILIES)
    with pytest.raises(QualityError, match=r"no row for \['trust\.\*'\]"):
        Decomposition(rows=tuple(r for r in rows if r.id != "trust.*")).verify()
    with pytest.raises(QualityError, match=r"rows for no family \['zzz\.\*'\]"):
        Decomposition(rows=(*rows, Row(id="zzz.*", page_wise=True))).verify()


def test_a_row_without_its_reason_or_twice_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "D.toml"
    path.write_text('[[counter]]\nid = "x.*"\npage_wise = false\n', encoding="utf-8")
    with pytest.raises(QualityError, match="says no reason"):
        load_decomposition(path)
    twice = '[[counter]]\nid = "x"\npage_wise = true\n' * 2
    path.write_text(twice, encoding="utf-8")
    with pytest.raises(QualityError, match="repeats an id"):
        load_decomposition(path)


def test_a_shape_counter_with_no_row_is_refused(table: Decomposition) -> None:
    new = BASE._replace(shape=_shape(novel__counter="1"))
    with pytest.raises(
        QualityError, match=r"'novel\.counter' has no DECOMPOSITION\.toml row"
    ) as got:
        classify(BASE, new, table)
    assert got.value.code() == CHURN_SYMBOL


# --- the delta -------------------------------------------------------------------------------


def test_the_shape_delta_signs_counts_and_not_values() -> None:
    old = _shape(quad__present_frac="0.5000")
    new = _shape(blocks__total="4", blocks__kind__heading="1", quad__present_frac="0.2500")
    assert shape_delta(old, new) == (
        Delta("blocks.kind.heading", None, "1", 1),
        Delta("blocks.total", "3", "4", 1),
        Delta("quad.present_frac", "0.5000", "0.2500", None),
    )
    assert shape_delta(old, old) == ()


# --- the classes -----------------------------------------------------------------------------


def test_nothing_moved_is_unchanged(table: Decomposition) -> None:
    assert classify(BASE, BASE, table).cls == "unchanged"


def test_a_text_fix_is_incidental(table: Decomposition) -> None:
    new = Reductions(
        BASE.shape,
        _text(PAGES_HEAD, _page(cdig="cccccccc")),
        _outline(first="0a0a0a0a - Net revenue grew"),
    )
    got = classify(BASE, new, table)
    assert (got.cls, got.delta) == ("incidental", ())


def test_a_histogram_moving_under_a_still_shape_is_unexplained(table: Decomposition) -> None:
    new = BASE._replace(pages=_text(PAGES_HEAD, _page(kind="heading:1,paragraph:2")))
    got = classify(BASE, new, table)
    assert got.cls == "unexplained"
    with pytest.raises(QualityError, match=r"unexplained golden churn in g\.shape") as raised:
        refuse_unexplained(got, "g.shape")
    assert raised.value.code() == CHURN_SYMBOL
    assert raised.value.fix == "ow eval golden --explain g.shape"


def test_an_outline_line_arriving_under_a_still_shape_is_unexplained(
    table: Decomposition,
) -> None:
    new = BASE._replace(outline=_outline("p0/3 table body extracted normalized 33333333 -"))
    assert classify(BASE, new, table).cls == "unexplained"


def test_an_outline_kind_change_is_beyond_a_digest(table: Decomposition) -> None:
    new = BASE._replace(
        outline=_outline(first="00000000 - Net revenue rose").replace(
            "p0/1 paragraph", "p0/1 heading"
        )
    )
    assert classify(BASE, new, table).cls == "unexplained"


def test_an_added_block_with_a_consistent_delta_is_structural(table: Decomposition) -> None:
    new = Reductions(
        _shape(
            blocks__total="4",
            blocks__kind__heading="1",
            blocks__layer__body="4",
            quote__normalized="4",
            trust__extracted="4",
        ),
        _text(
            PAGES_HEAD,
            _page(
                n=4,
                kind="heading:1,paragraph:3",
                layer="body:4",
                trust="extracted:4",
                quote="normalized:4",
            ),
        ),
        _outline("p0/3 heading body extracted normalized 33333333 - Results"),
    )
    got = classify(BASE, new, table)
    assert got.cls == "structural"
    assert [d.key for d in got.delta] == [
        "blocks.kind.heading",
        "blocks.layer.body",
        "blocks.total",
        "quote.normalized",
        "trust.extracted",
    ]
    refuse_unexplained(got, "g.shape")


def test_a_delta_the_pages_contradict_is_unexplained(table: Decomposition) -> None:
    """`shape` says one heading arrived; the pages say two did."""
    new = Reductions(
        _shape(blocks__kind__heading="1", blocks__kind__paragraph="2"),
        _text(PAGES_HEAD, _page(kind="heading:2,paragraph:1")),
        BASE.outline,
    )
    got = classify(BASE, new, table)
    assert got.cls == "unexplained"
    assert got.reasons[-1] == "blocks.kind.heading moved +1 in shape and +2 over pages"


def test_a_non_page_wise_counter_may_move_alone(table: Decomposition) -> None:
    for counter in (
        {"rel__kind__note_ref": "1"},
        {"grid__tables_with_merges": "1"},
        {"diag__OW_X": "1"},
        {"marks__kind__bold": "2"},
    ):
        got = classify(BASE, BASE._replace(shape=_shape(**counter)), table)
        assert got.cls == "structural", counter


def test_a_paged_diag_still_cross_checks_where_pages_print_it(table: Decomposition) -> None:
    """`diag.*` is not page-wise, so a document-level diag is not `unexplained` -- and a paged
    diag that moved on its page line alone, with a still `shape`, still is."""
    new = BASE._replace(pages=_text(PAGES_HEAD, _page(diag="OW_X:1")))
    assert classify(BASE, new, table).cls == "unexplained"


# --- suppressed files ------------------------------------------------------------------------


def test_a_suppressed_file_compares_by_its_count(table: Decomposition) -> None:
    old = BASE._replace(outline="owoutline/1 SUPPRESSED reason=bytes blocks=3 would_be_bytes=900\n")
    grown = old._replace(outline=old.outline.replace("900", "901"))
    assert classify(old, grown, table).cls == "incidental"
    more = old._replace(outline=old.outline.replace("blocks=3", "blocks=4"))
    assert classify(old, more, table).cls == "unexplained"
    assert classify(old, BASE, table).cls == "unexplained"


def test_suppressed_pages_skip_the_cross_check(table: Decomposition) -> None:
    old = BASE._replace(pages="owpages/1 SUPPRESSED reason=bytes pages=1 would_be_bytes=300000\n")
    new = old._replace(shape=_shape(blocks__kind__heading="1"))
    got = classify(old, new, table)
    assert got.cls == "structural"


# ---------------------------------------------------------------------------
# explain(): ruling 6 written out, key by key. D851.
# ---------------------------------------------------------------------------

NOTHING = Reductions("", "", "")


def test_explain_names_each_key_the_pages_contradict(table: Decomposition) -> None:
    new = Reductions(
        _shape(blocks__kind__heading="1", blocks__kind__paragraph="2"),
        _text(PAGES_HEAD, _page(kind="heading:2,paragraph:1")),
        BASE.outline,
    )
    assert explain(BASE, new, table) == (
        "blocks.kind.heading shape 0 -> 1 (+1), pages 0 -> 2 (+2): DISAGREES by +1",
        "blocks.kind.paragraph shape 3 -> 2 (-1), pages 3 -> 1 (-2): DISAGREES by -1",
        "2 page-wise counter(s) disagree between shape and pages",
    )


def test_explain_shows_a_histogram_moving_under_a_still_shape(table: Decomposition) -> None:
    new = BASE._replace(pages=_text(PAGES_HEAD, _page(kind="heading:1,paragraph:2")))
    assert explain(BASE, new, table) == (
        "blocks.kind.heading shape 0 -> 0 (+0), pages 0 -> 1 (+1): DISAGREES by +1",
        "blocks.kind.paragraph shape 3 -> 3 (+0), pages 3 -> 2 (-1): DISAGREES by -1",
        "2 page-wise counter(s) disagree between shape and pages",
    )


def test_explain_agrees_with_a_consistent_structural_change(table: Decomposition) -> None:
    new = Reductions(
        _shape(
            blocks__total="4",
            blocks__kind__heading="1",
            blocks__layer__body="4",
            quote__normalized="4",
            trust__extracted="4",
        ),
        _text(
            PAGES_HEAD,
            _page(
                n=4,
                kind="heading:1,paragraph:3",
                layer="body:4",
                trust="extracted:4",
                quote="normalized:4",
            ),
        ),
        BASE.outline,
    )
    got = explain(BASE, new, table)
    assert [line.split(" ", 1)[0] for line in got[:-1]] == [
        "blocks.kind.heading",
        "blocks.layer.body",
        "blocks.total",
        "quote.normalized",
        "trust.extracted",
    ]
    assert all(line.endswith(": agrees") for line in got[:-1])
    assert got[2] == "blocks.total shape 3 -> 4 (+1), pages 3 -> 4 (+1): agrees"
    assert got[-1] == "every page-wise counter that moved agrees between shape and pages"


def test_explain_says_when_nothing_page_wise_moved(table: Decomposition) -> None:
    """The `outline`-only case, an unchanged document, and a counter that is not page-wise."""
    outline_only = BASE._replace(outline=_outline("p0/3 table body extracted normalized 3 -"))
    for new in (outline_only, BASE):
        assert explain(BASE, new, table) == ("no page-wise counter moved in shape or over pages",)


@pytest.mark.parametrize(
    "new",
    [
        BASE._replace(shape=_shape(grid__tables_with_merges="1")),
        BASE._replace(shape=_shape(diag__OW_X="1")),
        BASE._replace(pages=_text(PAGES_HEAD, _page(diag="OW_X:1"))),
        BASE._replace(shape=_shape(marks__kind__bold="2")),
    ],
    ids=["unprinted-not-page-wise", "diag-in-shape", "diag-over-pages", "marks-not-printed"],
)
def test_explain_reads_only_page_wise_keys_pages_prints(
    table: Decomposition, new: Reductions
) -> None:
    """Ruling 2: `diag` is printed and not page-wise; `marks.kind` is page-wise and not printed."""
    assert explain(BASE, new, table) == ("no page-wise counter moved in shape or over pages",)


def test_explain_compares_moves_not_totals(table: Decomposition) -> None:
    """Two blocks on no page: the totals never agree, and the moves still do."""
    old = BASE._replace(shape=_shape(blocks__total="5"))
    new = Reductions(_shape(blocks__total="6"), _text(PAGES_HEAD, _page(n=4)), BASE.outline)
    assert explain(old, new, table) == (
        "blocks.total shape 5 -> 6 (+1), pages 3 -> 4 (+1): agrees",
        "every page-wise counter that moved agrees between shape and pages",
    )


def test_explain_sums_over_every_page(table: Decomposition) -> None:
    two = _text(PAGES_HEAD, _page(), _page().replace("p0000", "p0001"))
    moved = _text(PAGES_HEAD, _page(), _page(n=5).replace("p0000", "p0001"))
    old = BASE._replace(shape=_shape(blocks__total="6"), pages=two)
    new = BASE._replace(shape=_shape(blocks__total="8"), pages=moved)
    assert explain(old, new, table)[0] == (
        "blocks.total shape 6 -> 8 (+2), pages 6 -> 8 (+2): agrees"
    )


def test_explain_of_a_new_document_sums_from_nothing(table: Decomposition) -> None:
    got = explain(NOTHING, BASE, table)
    assert "blocks.total shape 0 -> 3 (+3), pages 0 -> 3 (+3): agrees" in got
    assert got[-1] == "every page-wise counter that moved agrees between shape and pages"


def test_explain_of_a_suppressed_pages_has_nothing_to_sum(table: Decomposition) -> None:
    gone = BASE._replace(pages="owpages/1 SUPPRESSED reason=bytes pages=9 would_be_bytes=300000\n")
    expected = ("pages is SUPPRESSED on a side, so no counter sums over its pages",)
    assert explain(BASE, gone, table) == expected
    assert explain(gone, BASE, table) == expected
