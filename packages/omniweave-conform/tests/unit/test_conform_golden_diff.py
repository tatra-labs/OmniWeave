"""`omniweave_conform.golden_diff`: the three-part PR-comment diff. D821."""

from __future__ import annotations

from omniweave_conform.churn import Reductions
from omniweave_conform.golden_diff import COMMENT_LINES, OUTLINE_LINES, comment, render
from omniweave_core.out.finding import EXAMPLES_MAX

SHAPE_HEAD = "owshape/1  corpus=c  doc=k  driver=d@1  schema_v=1"
PAGES_HEAD = "owpages/1  corpus=c  doc=k  driver=d@1  schema_v=1"
OUTLINE_HEAD = "owoutline/1  corpus=c  doc=k  driver=d@1  schema_v=1"


def _text(head: str, lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in (head, *lines))


def _page(page: int, *, n: int = 3, cdig: str = "aaaaaaaa", kind: str = "paragraph:3") -> str:
    return (
        f"p{page:04d} n={n} kind{{{kind}}} layer{{body:{n}}} trust{{extracted:{n}}}"
        f" quote{{normalized:{n}}} cdig={cdig} ldig=bbbbbbbb diag{{}}"
    )


def _outline(count: int, *, digest: str = "00000000") -> str:
    return _text(
        OUTLINE_HEAD,
        [f"p0/{i} paragraph body extracted normalized {digest} - line {i}" for i in range(count)],
    )


SHAPE = _text(SHAPE_HEAD, ["blocks.total 30", "quad.present_frac 0.5000", "trust.extracted 30"])
PAGES = _text(PAGES_HEAD, [_page(p) for p in range(10)])
BASE = Reductions(SHAPE, PAGES, _outline(3))


def test_no_change_no_comment() -> None:
    assert render(BASE, BASE) == ""


def test_the_shape_delta_leads_with_old_new_and_sign() -> None:
    new = BASE._replace(
        shape=_text(
            SHAPE_HEAD,
            [
                "blocks.kind.table 6",
                "blocks.total 36",
                "quad.present_frac 0.2500",
                "trust.extracted 30",
            ],
        )
    )
    assert render(BASE, new).splitlines() == [
        "shape delta (3 counters):",
        "  blocks.kind.table - -> 6 (+6)",
        "  blocks.total 30 -> 36 (+6)",
        "  quad.present_frac 0.5000 -> 0.2500",
    ]


def test_pages_fold_by_changed_fields_with_three_examples() -> None:
    lines = [_page(p) for p in range(10)]
    for p in range(5):
        lines[p] = _page(p, cdig="cccccccc")
    lines[7] = _page(7, n=4, kind="heading:1,paragraph:3")
    new = BASE._replace(pages=_text(PAGES_HEAD, [*lines[:9], _page(12)]))
    assert render(BASE, new).splitlines() == [
        "pages (8 lines changed in 4 groups):",
        "  cdig x5 p0000 p0001 p0002",
        "  +page x1 p0012",
        "  -page x1 p0009",
        "  kind,layer,n,quote,trust x1 p0007",
    ]
    assert EXAMPLES_MAX == 3


def test_pages_examples_run_in_page_order_past_four_digits() -> None:
    old = _text(PAGES_HEAD, [_page(9999), _page(10000)])
    new = _text(PAGES_HEAD, [_page(9999, cdig="c"), _page(10000, cdig="c")])
    got = render(BASE._replace(pages=old), BASE._replace(pages=new))
    assert got.splitlines()[1] == "  cdig x2 p9999 p10000"


def test_the_outline_is_a_context_free_unified_diff() -> None:
    new = BASE._replace(outline=_outline(3).replace("line 1", "line one"))
    assert render(BASE, new).splitlines() == [
        f"outline (first {OUTLINE_LINES} changed lines):",
        "--- outline",
        "+++ outline",
        "@@ -3 +3 @@",
        "-p0/1 paragraph body extracted normalized 00000000 - line 1",
        "+p0/1 paragraph body extracted normalized 00000000 - line one",
    ]


def test_the_outline_stops_at_forty_changed_lines() -> None:
    old, new = _outline(30), _outline(30, digest="11111111")
    lines = render(BASE._replace(outline=old), BASE._replace(outline=new)).splitlines()
    changed = [line for line in lines[3:] if line.startswith(("+", "-"))]
    assert len(changed) == OUTLINE_LINES == 40
    assert lines[-1] == "... 20 more changed outline lines"


def test_a_suppressed_file_diffs_as_its_one_line() -> None:
    old = BASE._replace(pages="owpages/1 SUPPRESSED reason=bytes pages=9 would_be_bytes=300000\n")
    new = old._replace(pages=old.pages.replace("pages=9", "pages=10"))
    assert render(old, new).splitlines() == [
        "pages:",
        "  -owpages/1 SUPPRESSED reason=bytes pages=9 would_be_bytes=300000",
        "  +owpages/1 SUPPRESSED reason=bytes pages=10 would_be_bytes=300000",
    ]


def test_the_parts_run_shape_pages_outline() -> None:
    new = Reductions(
        SHAPE.replace("blocks.total 30", "blocks.total 31"),
        _text(PAGES_HEAD, [_page(0, cdig="c"), *(_page(p) for p in range(1, 10))]),
        _outline(4),
    )
    heads = [
        line for line in render(BASE, new).splitlines() if not line.startswith((" ", "+", "-", "@"))
    ]
    assert heads == [
        "shape delta (1 counters):",
        "pages (1 lines changed in 1 groups):",
        f"outline (first {OUTLINE_LINES} changed lines):",
    ]


def _with_counters(n: int) -> Reductions:
    """`BASE`'s shape plus `n` new diag counters: a header and exactly `n` delta rows."""
    counters = [f"diag.OW_C{i:04d} 1" for i in range(n)]
    kept = ["blocks.total 30", "quad.present_frac 0.5000", "trust.extracted 30"]
    return BASE._replace(shape=_text(SHAPE_HEAD, sorted([*kept, *counters])))


def test_the_comment_is_cut_at_four_hundred_lines() -> None:
    lines = render(BASE, _with_counters(500)).splitlines()
    assert len(lines) == COMMENT_LINES == 400
    assert lines[-1] == f"... {501 - 399} more lines past the 400-line cap"


def test_a_comment_at_the_cap_is_not_cut() -> None:
    lines = render(BASE, _with_counters(399)).splitlines()
    assert len(lines) == 400
    assert lines[-1] == "  diag.OW_C0398 - -> 1 (+1)"
    assert len(render(BASE, _with_counters(400)).splitlines()) == 400


# ---------------------------------------------------------------------------
# comment(): every changed document, one cap. D850.
# ---------------------------------------------------------------------------

NOTHING = Reductions("", "", "")
SUPPRESSED_PAGES = "owpages/1 SUPPRESSED reason=bytes pages=9 would_be_bytes=300000\n"


def test_a_comment_is_render_under_a_header() -> None:
    new = _with_counters(2)
    assert comment([("c/d@1/k.pdf", BASE, new)]) == "document c/d@1/k.pdf:\n" + render(BASE, new)


def test_a_comment_heads_each_changed_document_in_the_order_given() -> None:
    heads = [
        line
        for line in comment(
            [("b", BASE, _with_counters(1)), ("a", BASE, BASE), ("c", BASE, _with_counters(2))]
        ).splitlines()
        if line.startswith("document ")
    ]
    assert heads == ["document b:", "document c:"]


def test_no_changed_document_no_comment() -> None:
    assert comment([("a", BASE, BASE)]) == ""
    assert comment([]) == ""


def test_one_cap_bounds_the_whole_comment() -> None:
    """Ruling 7: two documents of 252 lines each are 504, cut at 399 and a count."""
    one = render(BASE, _with_counters(250)).splitlines()
    assert len(one) == 251
    lines = comment([("a", BASE, _with_counters(250)), ("b", BASE, _with_counters(250))])
    assert len(lines.splitlines()) == COMMENT_LINES
    assert lines.splitlines()[-1] == f"... {504 - 399} more lines past the 400-line cap"
    assert len(comment([("a", BASE, _with_counters(250))], max_lines=10).splitlines()) == 10


def test_a_new_document_is_diffed_against_nothing() -> None:
    lines = comment([("k", NOTHING, BASE)]).splitlines()
    assert lines[:6] == [
        "document k:",
        "shape delta (3 counters):",
        "  blocks.total - -> 30 (+30)",
        "  quad.present_frac - -> 0.5000",
        "  trust.extracted - -> 30 (+30)",
        "pages (10 lines changed in 1 groups):",
    ]
    assert lines[6] == f"  +page x10 {' '.join(f'p{p:04d}' for p in range(EXAMPLES_MAX))}"
    assert lines[7:10] == [
        f"outline (first {OUTLINE_LINES} changed lines):",
        "--- outline",
        "+++ outline",
    ]
    assert lines[-1] == "+p0/2 paragraph body extracted normalized 00000000 - line 2"


def test_a_lost_document_reads_every_counter_as_gone() -> None:
    lines = comment([("k", BASE, NOTHING)]).splitlines()
    assert lines[2] == "  blocks.total 30 -> - (-30)"
    assert f"  -page x10 {' '.join(f'p{p:04d}' for p in range(EXAMPLES_MAX))}" in lines


def test_a_suppressed_side_against_nothing_is_its_one_line() -> None:
    """Ruling 4: the side that does not exist has no line, rather than an index error."""
    suppressed = Reductions("", SUPPRESSED_PAGES, "")
    assert render(NOTHING, suppressed).splitlines() == ["pages:", f"  +{SUPPRESSED_PAGES.strip()}"]
    assert render(suppressed, NOTHING).splitlines() == ["pages:", f"  -{SUPPRESSED_PAGES.strip()}"]
