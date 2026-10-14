"""`omniweave_core.out.provenance`: the embedded channel's grammars, body and receipt row. D802.

`cited()` and `addresses()` read carrier trees and a Plan, and run in the docx and pptx lowering
tests over real tables; the pure pieces are read here.
"""

from __future__ import annotations

import json

import pytest
from omniweave_core.out.provenance import SCHEMA, body, citations, kind, span


@pytest.mark.parametrize("value", ["quote", "paraphrase", "derived", "data"])
def test_a_kind_is_one_of_the_four(value: str) -> None:
    assert kind(value) == value


@pytest.mark.parametrize("value", ["rumour", "", "Quote"])
def test_any_other_kind_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="is not one of"):
        kind(value)


@pytest.mark.parametrize(("value", "found"), [("0:3", (0, 3)), ("12:40", (12, 40))])
def test_a_span_is_a_colon_b_with_a_below_b(value: str, found: tuple[int, int]) -> None:
    assert span(value) == found


@pytest.mark.parametrize("value", ["3:3", "5:2", "03", "a:b", "-1:2", "1:", ":4", "1:2:3"])
def test_any_other_span_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="is not a:b with a < b"):
        span(value)


def test_the_body_is_canonical_json_with_its_addresses_sorted() -> None:
    data = body(
        [{"el": "u01/e2", "cite": "d7#1", "doc_gen": 3, "kind": None, "span": None}],
        {"u01/e3": "text.text", "u01/e2": "shape.rect"},
        corpus="acme",
        slug="deck",
        artifact_gen=2,
    )
    found = json.loads(data)
    assert found == {
        "schema": SCHEMA,
        "corpus": "acme",
        "slug": "deck",
        "artifact_gen": 2,
        "cites": [{"el": "u01/e2", "cite": "d7#1", "doc_gen": 3, "kind": None, "span": None}],
        "els": {"u01/e2": "shape.rect", "u01/e3": "text.text"},
    }
    assert list(found["els"]) == ["u01/e2", "u01/e3"]
    assert data == body(found["cites"], found["els"], corpus="acme", slug="deck", artifact_gen=2), (
        "one body for one input"
    )


def test_the_receipt_row_counts_the_parts_rows_or_fails_without_it() -> None:
    raw = body([{"el": "e", "cite": "c"}] * 2, {}, corpus="a", slug="s", artifact_gen=1)
    passed = citations({"customXml/p.json": raw}, "customXml/p.json")
    failed = citations({}, "customXml/p.json")
    assert (passed.value, passed.detail) == ("passed", "embedded: 2 cite row(s)")
    assert (failed.value, failed.detail) == ("failed", "no customXml/p.json in the package")
