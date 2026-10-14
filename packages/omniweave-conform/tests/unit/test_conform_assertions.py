"""`omniweave_conform.assertions`: the text evaluator for `present`, `absent` and `order`. D825."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from omniweave_conform.assertions import (
    OWDOC_ONLY,
    TEXT_TYPES,
    Match,
    evaluate_text,
    find,
    nearest,
)
from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import Assertion


def _assertion(
    kind: str, spec: dict[str, Any], *, max_diffs: int = 0, evaluable: str = "both"
) -> Assertion:
    return Assertion(
        assertion_id="a1",
        corpus_id="golden",
        corpus_version="2026.09",
        doc="d",
        page=1,
        type=kind,
        spec=spec,
        addr=None,
        evaluable_in=evaluable,
        checked="verified",
        derived_from_sha256="sha256:" + "cd" * 32,
        max_diffs=max_diffs,
    )


def _levenshtein(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def _brute(needle: str, text: str) -> int:
    """The least distance between `needle` and any substring of `text`, the empty one included."""
    best = len(needle)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            best = min(best, _levenshtein(needle, text[i:j]))
    return best


def _strings(seed: str, n: int) -> str:
    raw = hashlib.blake2b(seed.encode()).digest()
    return "".join("abc"[b % 3] for b in raw[:n])


# --- the types -------------------------------------------------------------------------------


def test_the_three_types_and_the_owdoc_rows() -> None:
    assert {"present", "absent", "order"} == TEXT_TYPES
    assert {"footnote", "cell_rel", "span", "cite", "roundtrip"} == OWDOC_ONLY


# --- find ------------------------------------------------------------------------------------


def test_an_exact_budget_finds_every_occurrence() -> None:
    assert find("ab", "abcab", 0) == (Match(0, 0, 2), Match(0, 3, 5))
    assert find("zz", "abcab", 0) == ()


def test_an_empty_needle_is_refused() -> None:
    with pytest.raises(QualityError, match="empty"):
        find("", "text", 0)


def test_a_budget_admits_that_many_edits_and_no_more() -> None:
    text = "the Net revnue rose"
    assert find("Net revenue", text, 0) == ()
    one = find("Net revenue", text, 1)
    assert one
    assert min(m.distance for m in one) == 1
    assert text[one[0].start : one[0].end].startswith("Net rev")


@pytest.mark.parametrize("seed", ["a", "b", "c", "d", "e", "f"])
def test_the_nearest_distance_is_the_brute_forces(seed: str) -> None:
    needle, text = _strings(seed + "n", 4), _strings(seed + "t", 9)
    best = nearest(needle, text)
    assert best is not None
    assert best.distance == _brute(needle, text)
    assert _levenshtein(needle, text[best.start : best.end]) == best.distance


def test_each_kind_of_edit_costs_one() -> None:
    """An extra character in the text, a missing one, and a changed one."""
    for text in ("Net revXenue", "Net revnue", "Net revXnue"):
        found = find("Net revenue", text, 1)
        assert found, text
        assert min(m.distance for m in found) == 1, text


def test_on_a_tie_the_nearest_is_the_earliest() -> None:
    best = nearest("ab", "ax xb")
    assert best is not None
    assert (best.distance, best.start) == (1, 0)


def test_nothing_is_near_in_no_text() -> None:
    assert nearest("abc", "") is None


# --- present and absent ----------------------------------------------------------------------


def test_present_passes_with_no_explanation() -> None:
    got = evaluate_text(_assertion("present", {"text": "Net revenue"}), "Q3 Net revenue rose")
    assert (got.passed, got.explanation) == (True, "")


def test_the_asserted_string_is_normalised_too() -> None:
    """An assertion authored with curly quotes matches a candidate that printed straight ones."""
    spec = {"text": "the " + chr(0x2018) + "Annual" + chr(0x2019) + " Report"}
    assert evaluate_text(_assertion("present", spec), "the 'Annual' Report").passed


def test_both_sides_are_normalised_but_not_casefolded() -> None:
    """Section 8.2: markdown and curly quotes fold; case does not."""
    spec = {"text": "the 'Annual' Report"}
    assert evaluate_text(
        _assertion("present", spec), "**the " + chr(0x2018) + "Annual" + chr(0x2019) + " Report**"
    ).passed
    assert not evaluate_text(_assertion("present", spec), "THE 'ANNUAL' REPORT").passed


def test_a_fabricated_quote_fails_and_prints_both_strings() -> None:
    """13:1263's planted defect: a near miss at edit distance 4, `max_diffs = 0`."""
    asserted = "termination for convenience"
    candidate = "Section 9 allows termination for conveniences only"
    assert _levenshtein("convenience", "conveniences") == 1
    fabricated = "Section 9 allows terminatoin fro convenience only"
    assert _levenshtein(asserted, "terminatoin fro convenience") == 4
    got = evaluate_text(_assertion("present", {"text": asserted}), fabricated)
    assert not got.passed
    assert repr(asserted) in got.explanation
    assert "at distance 4" in got.explanation
    assert evaluate_text(_assertion("present", {"text": asserted}), candidate).passed


def test_absent_is_the_inverse_and_names_what_it_found() -> None:
    spec = {"text": "DRAFT"}
    assert evaluate_text(_assertion("absent", spec), "Final report").passed
    got = evaluate_text(_assertion("absent", spec), "a DRAFT report")
    assert not got.passed
    assert "'DRAFT' occurs as 'DRAFT' at distance 0" in got.explanation
    fuzzy = evaluate_text(_assertion("absent", spec, max_diffs=1), "a DRAFF report")
    assert not fuzzy.passed


# --- order -----------------------------------------------------------------------------------


def test_order_passes_when_before_ends_before_after_starts() -> None:
    spec = {"before": "Introduction", "after": "Conclusion"}
    assert evaluate_text(_assertion("order", spec), "Introduction ... Conclusion").passed
    got = evaluate_text(_assertion("order", spec), "Conclusion ... Introduction")
    assert not got.passed
    assert "first ends at" in got.explanation


def test_order_reads_the_earliest_before_and_the_latest_after() -> None:
    spec = {"before": "A1", "after": "B2"}
    assert evaluate_text(_assertion("order", spec), "B2 A1 B2").passed
    assert not evaluate_text(_assertion("order", spec), "B2 A1").passed


def test_order_names_the_string_that_is_missing() -> None:
    spec = {"before": "Preface", "after": "Index"}
    got = evaluate_text(_assertion("order", spec), "Index only")
    assert not got.passed
    assert got.explanation.startswith("order: before 'Preface' not found")
    got = evaluate_text(_assertion("order", spec), "Preface only")
    assert got.explanation.startswith("order: after 'Index' not found")


def test_order_admits_before_ending_where_after_starts() -> None:
    assert evaluate_text(_assertion("order", {"before": "A1", "after": "B2"}), "A1B2").passed


def test_order_honours_the_budget() -> None:
    spec = {"before": "Introduction", "after": "Conclusion"}
    text = "Intrduction then Conclusoon"
    assert not evaluate_text(_assertion("order", spec), text).passed
    assert evaluate_text(_assertion("order", spec, max_diffs=1), text).passed


# --- what it does not judge ------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["table", "math", "baseline", "format"])
def test_a_type_not_yet_judged_is_refused_by_name(kind: str) -> None:
    with pytest.raises(QualityError, match=f"does not judge '{kind}' yet"):
        evaluate_text(_assertion(kind, {}), "text")


@pytest.mark.parametrize("kind", sorted(OWDOC_ONLY))
def test_an_owdoc_type_is_refused(kind: str) -> None:
    with pytest.raises(QualityError, match="owdoc-only"):
        evaluate_text(_assertion(kind, {}), "text")


def test_an_owdoc_assertion_is_refused_whatever_its_type() -> None:
    with pytest.raises(QualityError, match="owdoc-only"):
        evaluate_text(_assertion("present", {"text": "x"}, evaluable="owdoc"), "x")
