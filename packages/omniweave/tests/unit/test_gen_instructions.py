"""Artefact 2: the MCP `instructions` string. 10 section 3.9.

Two of the assertions here are the plan's own measurements — 977 characters for variant A and 996
for variant B — and they are exact rather than bounded, because 10:872 and 10:892 print them as
figures. A test that asserted `< 1000` would pass on a string the plan never measured.

The other two combinations do not meet SV2's cap and carry a **strict xfail** with the arithmetic in
the reason, which is D1's standing treatment in this repository: transcribe the plan's number, fail
where it fails, and let `xfail_strict` turn the amendment into an XPASS that breaks the build.
"""

from __future__ import annotations

import ast
from pathlib import Path

import omniweave.gen.instructions as instructions_module
import pytest
from omniweave.gen.instructions import (
    DEFERRAL_PREFIX,
    FRONT_DOOR,
    NO_DEFAULT_CORPUS,
    SKILL_SENTENCE,
    SV2_MAX_CHARS,
    TOOL_PREFIX,
    VARIANT_A,
    WITH_DEFAULT_CORPUS,
    catalog_names,
    deferral_line,
    instructions,
)
from omniweave.surface import ACTIONS, listed
from omniweave_core.errors import UsageError

VARIANT_A_CHARS = 977
"""10:872: *"Variant A, the default corpus case — measured at 977 characters, 271 tokens."*"""

VARIANT_B_CHARS = 996
"""10:892: *"996 characters, 277 tokens"*, the second sentence swapped."""

TOOLSEARCH_FRAGMENT_CHARS = 118
"""10:898: *"The line costs 118 characters — `ToolSearch "select:"` plus four
`mcp__omniweave__`-prefixed names"*. The fragment's figure is right; the LINE's is not. D313."""


# ---------------------------------------------------------------------------------------------
# The two measurements the plan prints
# ---------------------------------------------------------------------------------------------


def test_variant_a_is_the_977_characters_the_plan_measured() -> None:
    assert len(VARIANT_A) == VARIANT_A_CHARS
    assert instructions() == VARIANT_A


def test_variant_b_is_996_and_differs_by_exactly_one_sentence() -> None:
    """10:892's swap, and the delta is the whole of it: +19 characters, nothing else moves."""
    variant_b = instructions(default_corpus=False)
    assert len(variant_b) == VARIANT_B_CHARS
    assert variant_b == VARIANT_A.replace(WITH_DEFAULT_CORPUS, NO_DEFAULT_CORPUS, 1)
    assert len(NO_DEFAULT_CORPUS) - len(WITH_DEFAULT_CORPUS) == VARIANT_B_CHARS - VARIANT_A_CHARS


def test_the_body_does_not_end_in_a_newline() -> None:
    """978 would be the count with one, and the plan's figure is 977."""
    assert not VARIANT_A.endswith("\n")
    assert VARIANT_A.endswith("generate.")


# ---------------------------------------------------------------------------------------------
# The catalog binding
# ---------------------------------------------------------------------------------------------


def test_the_body_advertises_exactly_the_tools_the_default_profile_lists() -> None:
    """10:866: *"bound to the live catalog by a test so it cannot advertise a tool omniweave does
    not serve"*. A fifth listed tool fails here rather than going unmentioned."""
    advertised = set(catalog_names())
    served = {ACTIONS[name].mcp_name for name in listed("default")}
    assert advertised == served


def test_the_names_are_read_back_out_of_the_prose_and_not_restated() -> None:
    """A binding that compared two tuples in this package would never look at the string that
    ships. `catalog_names()` parses the body."""
    assert catalog_names() == tuple(ACTIONS[name].mcp_name for name in FRONT_DOOR)
    for name in catalog_names():
        assert f"\n{name} " in VARIANT_A or VARIANT_A.startswith(f"{name} "), name


def test_the_front_door_order_is_the_ladder_and_not_the_sort() -> None:
    """D312. 10:229 would sort these by `name`; 10:878 prints the decision ladder."""
    assert FRONT_DOOR == ("query", "open", "corpora", "add")
    assert set(FRONT_DOOR) == set(listed("default"))
    assert tuple(sorted(FRONT_DOOR)) != FRONT_DOOR


def test_no_line_of_the_body_is_its_actions_decision_clause() -> None:
    """D311. 10:209 says the artefact is generated from *the listed set plus `decision` clauses*,
    and not one of the four printed lines is one -- so a generator that substituted them would
    emit a string the plan never measured."""
    for name in FRONT_DOOR:
        assert ACTIONS[name].decision not in VARIANT_A, name


# ---------------------------------------------------------------------------------------------
# The deferral line
# ---------------------------------------------------------------------------------------------


def test_the_toolsearch_fragment_is_the_118_characters_the_plan_counted() -> None:
    line = deferral_line()
    fragment = line[len(DEFERRAL_PREFIX) : -1]
    assert len(fragment) == TOOLSEARCH_FRAGMENT_CHARS
    assert fragment.startswith('ToolSearch "select:')


def test_the_line_costs_more_than_the_fragment_and_the_difference_is_the_prefix() -> None:
    """D313's arithmetic: 13 characters of `If deferred: ` plus the closing stop."""
    assert len(deferral_line()) == TOOLSEARCH_FRAGMENT_CHARS + len(DEFERRAL_PREFIX) + 1
    assert len(deferral_line()) == 132


def test_the_line_names_the_four_front_door_tools_in_order_and_prefixed() -> None:
    line = deferral_line()
    for name in FRONT_DOOR:
        assert TOOL_PREFIX + str(ACTIONS[name].mcp_name) in line
    positions = [line.index(TOOL_PREFIX + str(ACTIONS[n].mcp_name)) for n in FRONT_DOOR]
    assert positions == sorted(positions), "the ladder's order, not the sort's"


def test_the_deferral_line_is_absent_under_the_default_profile() -> None:
    """10:897: four tools at 850 tokens, and no host defers that. The line would be 12% of the cap
    spent insuring against a condition the profile cannot reach."""
    assert DEFERRAL_PREFIX not in instructions(profile="default")
    assert DEFERRAL_PREFIX in instructions(profile="full")


def test_the_skill_sentence_is_dropped_only_under_full() -> None:
    """10:907, *"where the router skill's own description covers it"*."""
    assert SKILL_SENTENCE in instructions(profile="default")
    assert SKILL_SENTENCE not in instructions(profile="full")
    assert instructions(profile="full").count("never instruction.") == 1


# ---------------------------------------------------------------------------------------------
# SV2's cap, and the two combinations that miss it
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("default_corpus", [True, False])
def test_the_default_profile_meets_sv2(*, default_corpus: bool) -> None:
    assert len(instructions(profile="default", default_corpus=default_corpus)) <= SV2_MAX_CHARS


@pytest.mark.xfail(
    strict=True,
    reason=(
        "D313. 10:909 asserts len(s) <= 1000 for all four variant x profile combinations. Under "
        "`full` the generator appends a 132-character deferral line (10:898 counts 118, which is "
        "the ToolSearch fragment without the 13-character `If deferred: ` prefix and the closing "
        "stop) and drops the 79-character skill sentence, leaving 1,031 and 1,050. 10:907 states "
        "1,113 before the drop; the arithmetic gives 1,110. This xfail lands when 3.9 is amended."
    ),
)
@pytest.mark.parametrize("default_corpus", [True, False])
def test_the_full_profile_meets_sv2(*, default_corpus: bool) -> None:
    assert len(instructions(profile="full", default_corpus=default_corpus)) <= SV2_MAX_CHARS


def test_the_full_profile_lengths_are_the_ones_the_arithmetic_gives() -> None:
    """The measurement behind the xfail, asserted positively so the numbers are pinned."""
    assert len(instructions(profile="full")) == 1031
    assert len(instructions(profile="full", default_corpus=False)) == 1050


def test_generating_does_not_enforce_the_cap() -> None:
    """10:909 puts SV2 in a test. A raise here would make `profile = "full"` unserveable over an
    arithmetic error in a document rather than a defect in a deployment."""
    assert len(instructions(profile="full")) > SV2_MAX_CHARS


# ---------------------------------------------------------------------------------------------
# Refusals and purity
# ---------------------------------------------------------------------------------------------


def test_an_unknown_profile_raises_through_the_one_refusal_that_already_exists() -> None:
    with pytest.raises(UsageError) as caught:
        instructions(profile="verbose")
    assert "verbose" in str(caught.value)
    assert "default" in caught.value.fix


def test_the_renderer_reads_no_clock_no_environment_and_no_path() -> None:
    """10:229's ban, over the module that renders artefact 2.

    Read with `ast` rather than by importing and probing, because the property is about what the
    SOURCE may contain: a renderer that called `time.time()` once, in a branch no test reaches,
    would still make G25's byte-diff fail on the second run.
    """
    source = Path(instructions_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert not roots & banned, roots & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module
