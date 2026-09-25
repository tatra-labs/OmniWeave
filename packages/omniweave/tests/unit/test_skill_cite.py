"""`references/cite.md`: rendered, shipped as rendered, and every table bound to its source.

**The sharpest test is `test_every_rule_cites_lines_that_say_what_the_rule_says`.** The nine "when
not to quote" rules are the one part of the page this build wrote rather than transcribed (D504),
so each carries its plan lines, and the test resolves every one and requires a word from the rule
on the line it cites. A rule whose citation drifts to a blank line or a neighbouring paragraph
fails.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave.gen.llms import CITE_RULES, VERDICTS
from omniweave.skills import cite
from omniweave_core.answer.render import BYTE_EXACT_ADVISORY, RECONSTRUCTED_ADVISORY
from omniweave_core.model.enums import Quote
from omniweave_core.retrieve.verdict import VerdictState

if TYPE_CHECKING:
    from conftest import PlanDocs

SKILLS = Path(__file__).resolve().parents[4] / "skills"
_CITATION = re.compile(r"(glossary\.md|\d{2}):(\d+)(?:-(\d+))?")
#  One distinctive word per rule that its cited lines must contain, in `DONT`'s order.
_WITNESS = (
    "verbatim", "returnable", "source_ahead", "untrusted", "notseen", "Read",
    "absence", "defanged", "cite",
)  # fmt: skip


def test_the_shipped_page_is_the_render() -> None:
    assert cite.check(SKILLS) == ()


def test_a_hand_edit_is_named_and_emit_restores_it(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    page = root / cite.SHIPPED
    page.write_bytes(page.read_bytes() + b"\nmy note\n")
    assert cite.check(root) == ("skills/omniweave/references/cite.md differs from the render",)
    assert cite.emit(root)
    assert not cite.emit(root)
    assert cite.check(root) == ()
    page.unlink()
    assert cite.check(root) == ("skills/omniweave/references/cite.md is missing",)


def test_the_sections_are_10_1155s_four_subjects_in_its_order() -> None:
    """*"cite vs addr; quote tiers; verdicts; WHEN NOT TO QUOTE"*."""
    headings = [line for line in cite.render().split("\n") if line.startswith("## ")]
    assert headings == [
        "## cite vs addr",
        "## Quote tiers, strongest first",
        "## Verdicts",
        "## When NOT to quote",
    ]


def test_every_quote_tier_has_a_meaning_and_they_print_strongest_first() -> None:
    assert set(cite.MEANINGS) == set(Quote)
    text = cite.render()
    at = [text.index(f"| `{tier.name.lower()}` |") for tier in sorted(Quote, reverse=True)]
    assert at == sorted(at)


def test_the_page_prints_the_advisories_an_answer_carries_byte_for_byte() -> None:
    """07:2585: the advisory is keyed on `byte_exact`, so the line is what an agent must read."""
    text = cite.render()
    assert BYTE_EXACT_ADVISORY in text
    assert RECONSTRUCTED_ADVISORY in text


def test_the_verdict_and_cite_tables_are_llms_txts_own_rows() -> None:
    text = cite.render()
    for state, meaning in VERDICTS:
        assert f"| `{state}` | {meaning} |" in text
    assert {state for state, _ in VERDICTS} >= {one.value for one in VerdictState}
    for key, value in CITE_RULES:
        assert f"- **{key}**: {value}" in text


def test_the_identifier_table_is_the_glossarys(plan: PlanDocs) -> None:
    """glossary.md:182-187, cell for cell once the glossary's bold markup is removed."""
    plan.require()
    rows = plan.lines("glossary.md")[183:187]
    for row, (name, *cells) in zip(rows, cite.IDENTIFIERS, strict=True):
        found = [cell.strip().replace("**", "") for cell in row.strip("|").split(" | ")]
        assert found == [f"`{name}`", *cells], row


def _document(plan: PlanDocs, label: str) -> str:
    if label == "glossary.md":
        return label
    (name,) = [one for one in plan.documents() if one.startswith(f"{label}-") and "/" not in one]
    return name


def test_every_rule_cites_lines_that_say_what_the_rule_says(plan: PlanDocs) -> None:
    plan.require()
    assert len(_WITNESS) == len(cite.DONT)
    for (rule, where), witness in zip(cite.DONT, _WITNESS, strict=True):
        assert witness.lower() in rule.lower(), (witness, rule)
        cited: list[str] = []
        for label, first, last in _CITATION.findall(where):
            lines = plan.lines(_document(plan, label))
            span = lines[int(first) - 1 : int(last or first)]
            assert all(line.strip() for line in span[:1]), (where, span)
            cited.extend(span)
        assert cited, where
        assert witness.lower() in " ".join(cited).lower(), (witness, where)


def test_no_two_rules_open_the_same_way() -> None:
    openings = [rule.split(":")[0].split(".")[0] for rule, _ in cite.DONT]
    assert len(set(openings)) == len(openings)
