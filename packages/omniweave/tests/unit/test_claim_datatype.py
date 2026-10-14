"""06 section 3.6's datatype rules, held to one answer in their two homes. **D722.**

`omniweave_graph.table.rules.datatype` (D681) types a table cell under its header, and
`omniweave_llm.claim.datatype` (D722) types a claim's literal under its predicate. Each package
imports `omniweave_ports` alone, so neither can import the other's copy; this test can import both.
"""

from __future__ import annotations

import pytest
from omniweave_graph.table.rules import datatype as table_datatype
from omniweave_llm.claim import datatype as claim_datatype

CASES = [
    ("2026-06-30", "due"),
    ("2026-02-30", "due"),
    ("30 June 2026", "signed"),
    ("June 30, 2026", "signed"),
    ("30/06/2026", "signed"),
    ("4,000 EUR", "pays"),
    ("£ 12", "pays"),
    ("€ 1,250.50", "price"),
    ("12", "fee in CHF"),
    ("$ 12", "pays"),
    ("¥ 12", "pays"),
    ("ABC 12", "pays"),
    ("1,250", "amount"),
    ("-12.5", "Rate"),
    ("1,250", "pays"),
    ("1250", "units sold"),
    ("Seller", "role"),
    ("", "role"),
    ("12 EUR", ""),
]


@pytest.mark.parametrize(("literal", "header"), CASES)
def test_a_claims_literal_is_typed_as_a_table_cell_under_the_same_header(
    literal: str, header: str
) -> None:
    assert claim_datatype(literal, header) == table_datatype(literal, header)


def test_the_cases_reach_every_answer_the_rules_give() -> None:
    answers = {table_datatype(literal, header) for literal, header in CASES}
    assert answers == {"xsd:date", "money:EUR", "money:GBP", "money:CHF", "xsd:decimal", "string"}
