"""`omniweave_conform.golden_diff`: the three-part PR-comment diff. D821."""

from __future__ import annotations

from omniweave_conform.churn import Reductions
from omniweave_conform.golden_diff import COMMENT_LINES, OUTLINE_LINES, render
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
