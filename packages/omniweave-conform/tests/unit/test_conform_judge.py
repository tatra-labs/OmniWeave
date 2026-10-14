"""`omniweave_conform.judge`, and Q-G23: the harness scores deliberately wrong outputs. D827.

13-quality.md section 8.5 item 8: *"Three planted defects with the exact expected numbers
asserted, because `omniweave-conform` is dev-tier and is therefore tested less rigorously than
runtime code"*. The plan's fixtures are a 12-page `sec-exhibit-scan` and `xlsx-merged-4m-cells`;
neither is in the tree, so each defect is planted here into a synthetic candidate with the plan's
shape and the plan's numbers.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from omniweave_conform import rollup as rollup_module
from omniweave_conform import staging
from omniweave_conform.judge import UNSLICED, judge
from omniweave_conform.rollup import RATES, rollup
from omniweave_conform.stats import rate
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.store.oweval import Assertion, Run


def _assertion(
    assertion_id: str,
    kind: str,
    spec: dict[str, Any],
    *,
    page: int | None = 1,
    doc: str = "sec-exhibit-scan",
    slices: tuple[str, ...] = ("pdf/scan",),
    checked: str | None = "verified",
    max_diffs: int = 0,
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        corpus_id="golden",
        corpus_version="2026.09",
        doc=doc,
        page=page,
        type=kind,
        spec=spec,
        addr=None,
        evaluable_in="both",
        checked=checked,
        derived_from_sha256="sha256:" + "cd" * 32,
        max_diffs=max_diffs,
        slices=slices,
    )


def _exhibit() -> tuple[list[Assertion], dict[tuple[str, int], str]]:
    """Twelve pages and forty `present` assertions: six on page 7, the rest spread over the
    other eleven, each asserting a line its page carries."""
    pages = {("sec-exhibit-scan", p): f"Exhibit page {p}." for p in range(1, 13)}
    assertions = []
    on_other = [p for p in range(1, 13) if p != 7]
    for n in range(40):
        page = 7 if n < 6 else on_other[(n - 6) % len(on_other)]
        token = hashlib.blake2b(str(n).encode()).hexdigest()[:12]
        line = f"clause {token} of page {page}"
        pages["sec-exhibit-scan", page] += f"\n{line}"
        assertions.append(_assertion(f"a{n:02d}", "present", {"text": line}, page=page))
    return assertions, pages


# --- Q-G23's three planted defects -----------------------------------------------------------


def test_a_dropped_page_fails_exactly_its_assertions() -> None:
    """*"page 7 removed from the candidate output: exactly the 6 assertions anchored on page 7
    fail; `34/40 = 0.850`; the six ids are named in the report"*."""
    assertions, pages = _exhibit()
    whole = judge(assertions, pages, run_id="r")
    assert (whole.passed, len(whole.verdicts)) == (40, 40)
    dropped = {key: text for key, text in pages.items() if key[1] != 7}
    got = judge(assertions, dropped, run_id="r")
    assert (got.passed, len(got.verdicts)) == (34, 40)
    assert rate(got.passed, len(got.verdicts)).value == 0.850
    assert got.failed == tuple(f"a{n:02d}" for n in range(6))
    lost = {v.explanation for v in got.verdicts if not v.passed}
    assert lost == {"page 7 of doc sec-exhibit-scan is missing from the candidate"}


def test_a_transposed_table_fails_every_relation_while_every_string_passes() -> None:
    """*"every `table` and `cell_rel` assertion fails (`0/18`) while every `present` assertion
    still passes"*. The text evaluator judges `table`; `cell_rel` is owdoc-only and is named as
    not run rather than counted."""
    header = ["Item", *[f"Q{q}" for q in range(1, 4)]]
    body = [[f"r{r}", *[f"{r}.{q}" for q in range(1, 4)]] for r in range(1, 7)]
    grid = [header, *body]

    def markdown(rows: list[list[str]]) -> str:
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        return "\n".join([*lines, *("| " + " | ".join(row) + " |" for row in rows[1:])])

    original = markdown(grid)
    swapped = markdown([list(col) for col in zip(*grid, strict=True)])
    tables = [
        _assertion(
            f"t{r}{q}",
            "table",
            {"cell": f"{r}.{q}", "left_heading": f"r{r}", "top_heading": f"Q{q}"},
        )
        for r in range(1, 7)
        for q in range(1, 4)
    ]
    strings = [_assertion(f"p{r}", "present", {"text": f"r{r}"}) for r in range(1, 7)]
    cell_rel = [_assertion("c1", "cell_rel", {"cell": "1.1"})]
    batch = [*tables, *strings, *cell_rel]
    assert len(tables) == 18
    before = judge(batch, {("sec-exhibit-scan", 1): original}, run_id="r")
    after = judge(batch, {("sec-exhibit-scan", 1): swapped}, run_id="r")
    by_kind_before = {v.assertion_id[0]: [] for v in before.verdicts}
    for v in before.verdicts:
        by_kind_before[v.assertion_id[0]].append(v.passed)
    assert all(by_kind_before["t"]) and all(by_kind_before["p"])
    table_passes = sum(v.passed for v in after.verdicts if v.assertion_id.startswith("t"))
    present_passes = sum(v.passed for v in after.verdicts if v.assertion_id.startswith("p"))
    assert (table_passes, present_passes) == (0, 6)
    assert [aid for aid, _ in after.not_run] == ["c1"]
    assert "c1" not in {v.assertion_id for v in after.verdicts}
    assert len(after.verdicts) == 24


def test_a_fabricated_quote_fails_alone_and_prints_both_strings() -> None:
    """*"a `present` assertion's string replaced by a plausible near-miss at edit distance 4 with
    `max_diffs = 0`: that one assertion fails ... the explanation prints both strings"*."""
    assertions, pages = _exhibit()
    target = assertions[10]
    key = ("sec-exhibit-scan", target.page or 0)
    asserted = str(target.spec["text"])
    token = asserted.split()[1]
    shifted = "".join(format((int(ch, 16) + 1) % 16, "x") for ch in token[:4])
    near = asserted.replace(token, shifted + token[4:])
    pages[key] = pages[key].replace(asserted, near)
    got = judge(assertions, pages, run_id="r")
    assert got.failed == (target.assertion_id,)
    explanation = next(v.explanation for v in got.verdicts if not v.passed)
    assert repr(asserted) in explanation
    assert repr(near) in explanation
    assert "at distance 4" in explanation


# --- the rest of the rulings -----------------------------------------------------------------


def test_a_rejected_assertion_does_not_run_and_an_unchecked_one_does() -> None:
    pages = {("d", 1): "alpha beta"}
    got = judge(
        [
            _assertion("a", "present", {"text": "alpha"}, doc="d", checked="rejected"),
            _assertion("b", "present", {"text": "beta"}, doc="d", checked=None),
        ],
        pages,
        run_id="r",
    )
    assert [v.assertion_id for v in got.verdicts] == ["b"]


def test_a_pageless_assertion_reads_the_whole_document() -> None:
    pages = {("d", 2): "Conclusion", ("d", 1): "Introduction", ("e", 1): "Other"}
    order = _assertion(
        "o", "order", {"before": "Introduction", "after": "Conclusion"}, doc="d", page=None
    )
    alone = _assertion("x", "absent", {"text": "Other"}, doc="d", page=None)
    got = judge([order, alone], pages, run_id="r")
    assert [v.passed for v in got.verdicts] == [True, True]


def test_slice_key_explanation_and_order() -> None:
    pages = {("d", 1): "alpha"}
    batch = [
        _assertion("z", "present", {"text": "omega"}, doc="d", slices=()),
        _assertion("a", "present", {"text": "alpha"}, doc="d", slices=("office/docx", "x")),
    ]
    assert UNSLICED == staging.UNSLICED == rollup_module.UNSLICED == "*"
    got = judge(batch, pages, run_id="run-9")
    assert [(v.assertion_id, v.slice_key, v.run_id, v.evaluator) for v in got.verdicts] == [
        ("a", "office/docx", "run-9", "text"),
        ("z", UNSLICED, "run-9", "text"),
    ]
    assert got.verdicts[0].explanation == ""
    assert got.verdicts[1].explanation.startswith("present 'omega' not found")
    assert judge(list(reversed(batch)), pages, run_id="run-9") == got


def test_judged_verdicts_roll_up() -> None:
    """D816's rollup reads what this writes: thirty-one `order` assertions over one page, one
    of them out of order, is 30/31 at `order_acc`."""
    text = " ".join(f"w{i:02d}" for i in range(40))
    batch = [
        _assertion(f"o{i:02d}", "order", {"before": f"w{i:02d}", "after": f"w{i + 1:02d}"}, doc="d")
        for i in range(30)
    ]
    batch.append(_assertion("o99", "order", {"before": "w09", "after": "w02"}, doc="d"))
    got = judge(batch, {("d", 1): text}, run_id="run-1")
    measured = MeasuredOn(
        weights="n/a",
        weights_revision="n/a",
        runtime="pdfium",
        runtime_version="6721",
        sampling="{}",
        prompt_version="n/a",
        hardware="x",
        corpus="golden@2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        harness_version="0.1.0",
    )
    run = Run(
        run_id="run-1",
        suite="parse",
        corpus_id="golden",
        corpus_version="2026.09",
        corpus_digest="sha256:" + "ab" * 32,
        subject="s",
        subject_version="1",
        producer_id=None,
        measured_on=measured,
        timing_basis="in_process",
        witness="ci",
        cassette="off",
        policy_digest=None,
        pricebook_digest=None,
        harness_version="0.1.0",
        code_fingerprint="c",
        hardware="x",
        started_ns=1,
        ended_ns=2,
        status="ok",
    )
    rows = rollup(run, RATES["order_acc"], got.verdicts, batch, evaluator="text").metrics
    head = next(r for r in rows if r.slice_key == "__macro__")
    assert (head.n, head.value) == (31, 30 / 31)
    assert replace(head, value=None).metric == "order_acc"
