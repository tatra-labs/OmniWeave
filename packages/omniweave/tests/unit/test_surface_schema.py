"""`compact_schemas`: the strip, the demotion, the promotion, and the snapshot. 10 section 3.3.

The fixture is `ow_query`'s published `inputSchema`, transcribed from 18:1258 field for field and
in its published order. A synthetic object would test the functions; this one tests them against
the shape the plan says goes on the wire, which is the only version of the question that matters --
`want`, `route_hints` and `max_chars` are the three parameters 18:1307 names as stripped, and they
are in this fixture because they are in that document.

Every assertion about not mutating the input is made twice: once on the result and once on the
argument. 10:513's *"a COPY; the shared array is never touched"* is a promise about the SECOND, and
a test that only read the first would pass on a function that returned a correct value after
corrupting the tool array every other caller shares.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import Any

import pytest
from omniweave.surface import ACTIONS
from omniweave.surface import schema as schema_module
from omniweave.surface.inputs import HARD_CEILING, MAX_CHARS_MIN, QUERY_MAX_CHARS, WANTS
from omniweave.surface.schema import (
    CORPUS_PARAM,
    CORPUS_SCOPED,
    ENUM_DEMOTE_MAX,
    KNOWN_TOOLS,
    advanced_args,
    compact,
    declared_arg_keys,
    unknown_args,
    with_required_corpus,
)


def query_tool() -> dict[str, Any]:
    """18:1258's published object for `ow_query`, in its published order."""
    return {
        "name": "ow_query",
        "description": "Answer a question from indexed documents; returns the passages themselves.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": QUERY_MAX_CHARS},
                "corpus": {"type": "string", "description": "From ow_corpora."},
                "scope": {"type": "string", "description": "'policy.pdf' | 'd7'"},
                "want": {"type": "string", "enum": list(WANTS), "default": WANTS[0]},
                "route_hints": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "RouteHints. Cannot widen budget, egress or licence policy.",
                    "properties": {
                        "lane": {"type": "string"},
                        "max_rung": {
                            "type": "string",
                            "enum": ["gate", "decode", "repair", "page", "regen", "degrade"],
                        },
                        "deadline_ms": {"type": "integer", "minimum": 100, "maximum": 120000},
                    },
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": MAX_CHARS_MIN,
                    "maximum": HARD_CEILING,
                },
            },
        },
    }


# ---------------------------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------------------------


def test_the_snapshot_carries_every_agent_reachable_tool() -> None:
    reachable = {spec.mcp_name for spec in ACTIONS.values() if spec.mcp_name}
    assert reachable == KNOWN_TOOLS


def test_the_snapshot_is_the_declaration_and_not_a_schema() -> None:
    """10:500's `_snapshot_before_strip(ACTIONS)`: `inp`'s fields, not a document's properties."""
    for spec in ACTIONS.values():
        if spec.mcp_name is None:
            continue
        assert declared_arg_keys(spec.mcp_name) == {f.name for f in fields(spec.inp)}, spec.name


def test_every_advanced_parameter_is_still_declared() -> None:
    """The property that makes the strip safe: what is hidden is never what is unknown."""
    for tool in KNOWN_TOOLS:
        assert advanced_args(tool) <= declared_arg_keys(tool), tool


def test_an_advanced_parameter_is_never_reported_unknown() -> None:
    """10:505, stated as the bug it fixes: *"a hidden-but-honoured parameter must never be
    reported as an unknown argument"*."""
    for tool in sorted(KNOWN_TOOLS):
        assert unknown_args(tool, advanced_args(tool)) == (), tool


def test_unknown_args_names_only_what_is_not_declared_and_sorts_it() -> None:
    assert unknown_args("ow_query", ["zzz", "query", "aaa", "route_hints"]) == ("aaa", "zzz")


def test_unknown_args_on_a_tool_this_registry_does_not_carry_declares_nothing() -> None:
    """`ow_nonesuch` has no parameters, so every key supplied to it is unknown."""
    assert declared_arg_keys("ow_nonesuch") == frozenset()
    assert unknown_args("ow_nonesuch", ["a", "b"]) == ("a", "b")


def test_the_five_human_only_actions_have_no_argument_set() -> None:
    """`mcp_name is None` is structural (10:1540), so there is no agent to tell about them."""
    for name in ("uninstall", "corpus.rm", "route.promote", "skills.remove", "targets.remove"):
        assert name not in KNOWN_TOOLS


def test_advanced_is_derived_and_omits_the_tool_that_declares_none() -> None:
    """10:356: `ow_corpora` is the one listed tool compaction does not change."""
    assert advanced_args("ow_query") == ACTIONS["query"].advanced
    assert advanced_args("ow_open") == ACTIONS["open"].advanced
    assert advanced_args("ow_add") == ACTIONS["add"].advanced
    assert advanced_args("ow_corpora") == frozenset()
    assert "ow_corpora" not in schema_module._ADVANCED


def test_10_495s_three_literal_rows_are_the_three_the_registry_derives() -> None:
    """The mapping 10:495 writes by hand, reproduced from `ActionSpec.advanced`. D308."""
    assert schema_module._ADVANCED["ow_query"] == frozenset({"want", "route_hints", "max_chars"})
    assert schema_module._ADVANCED["ow_open"] == frozenset({"context", "layers", "max_chars"})
    assert schema_module._ADVANCED["ow_add"] == frozenset({"dry_run"})


# ---------------------------------------------------------------------------------------------
# The strip
# ---------------------------------------------------------------------------------------------


def test_compact_removes_exactly_the_three_parameters_18_1307_names() -> None:
    tool = query_tool()
    result = compact(tool)
    assert list(result["inputSchema"]["properties"]) == ["query", "corpus", "scope"]


def test_compact_keeps_the_surviving_properties_in_declaration_order() -> None:
    """10:231: schema properties in declaration order, so a strip may not re-sort what it keeps."""
    tool = query_tool()
    hidden = advanced_args("ow_query")
    kept = [key for key in tool["inputSchema"]["properties"] if key not in hidden]
    assert list(compact(tool)["inputSchema"]["properties"]) == kept


def test_compact_does_not_touch_the_tool_it_was_given() -> None:
    tool = query_tool()
    before = copy.deepcopy(tool)
    compact(tool)
    assert tool == before


def test_additional_properties_false_survives_compaction() -> None:
    """10:516, and it reads like a contradiction until the two channels are separated."""
    result = compact(query_tool())
    assert result["inputSchema"]["additionalProperties"] is False


def test_compact_touches_neither_required_nor_the_prose() -> None:
    """The budget is cut by removing a parameter, *never* by shortening a description (10:352)."""
    tool = query_tool()
    result = compact(tool)
    assert result["inputSchema"]["required"] == ["query"]
    assert result["description"] == tool["description"]
    assert result["annotations"] == tool["annotations"]


def test_compacting_ow_corpora_returns_an_equal_copy() -> None:
    tool = {
        "name": "ow_corpora",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"corpus": {"type": "string"}, "detail": {"type": "string"}},
        },
    }
    result = compact(tool)
    assert result == tool
    assert result is not tool
    assert result["inputSchema"] is not tool["inputSchema"]


def test_a_tool_with_no_input_schema_is_returned_as_a_copy() -> None:
    tool = {"name": "ow_query", "description": "no schema here"}
    result = compact(tool)
    assert result == tool
    assert result is not tool


def test_a_tool_name_the_registry_does_not_carry_compacts_to_itself() -> None:
    """Not a hole: the tool array is generated from `ACTIONS` and byte-diff gated by G25."""
    tool = query_tool()
    tool["name"] = "ow_nonesuch"
    assert compact(tool)["inputSchema"]["properties"].keys() == (
        tool["inputSchema"]["properties"].keys()
    )


# ---------------------------------------------------------------------------------------------
# The demotion
# ---------------------------------------------------------------------------------------------


def _enum_tool(members: int, *, description: str | None = None) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "string", "enum": [f"m{i}" for i in range(members)]}
    if description is not None:
        prop["description"] = description
    return {"name": "ow_corpora", "inputSchema": {"type": "object", "properties": {"p": prop}}}


def test_an_enum_of_exactly_the_ceiling_keeps_its_enum() -> None:
    """10:507 says *exceeds* 12, so twelve members are still validated client-side."""
    result = compact(_enum_tool(ENUM_DEMOTE_MAX))
    assert len(result["inputSchema"]["properties"]["p"]["enum"]) == ENUM_DEMOTE_MAX


def test_an_enum_one_member_over_the_ceiling_is_demoted_and_not_deleted() -> None:
    """*"It becomes a free-form string with the members named in the description"*, and the
    parameter stays fully usable -- which is the difference between demotion and deletion."""
    result = compact(_enum_tool(ENUM_DEMOTE_MAX + 1))
    prop = result["inputSchema"]["properties"]["p"]
    assert "enum" not in prop
    assert prop["type"] == "string"
    assert prop["description"] == "one of: " + ", ".join(f"m{i}" for i in range(13))


def test_a_demoted_enum_keeps_the_description_it_already_had() -> None:
    result = compact(_enum_tool(ENUM_DEMOTE_MAX + 1, description="The language."))
    prop = result["inputSchema"]["properties"]["p"]
    assert prop["description"].startswith("The language. one of: ")


def test_the_demotion_reaches_a_nested_object() -> None:
    """A rule that only looked one level deep stops working the first time a parameter grows a
    shape, and `route_hints` is already an object with three properties of its own."""
    tool = {
        "name": "ow_corpora",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hints": {
                    "type": "object",
                    "properties": {
                        "lane": {"type": "string", "enum": [f"l{i}" for i in range(20)]}
                    },
                }
            },
        },
    }
    lane = compact(tool)["inputSchema"]["properties"]["hints"]["properties"]["lane"]
    assert "enum" not in lane
    assert lane["description"].startswith("one of: l0, l1,")


def test_the_demotion_reaches_an_array_items_schema() -> None:
    tool = {
        "name": "ow_corpora",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layers": {
                    "type": "array",
                    "items": {"type": "string", "enum": [f"x{i}" for i in range(13)]},
                }
            },
        },
    }
    items = compact(tool)["inputSchema"]["properties"]["layers"]["items"]
    assert "enum" not in items


def test_no_shipped_parameter_needs_the_demotion_today() -> None:
    """10:510: the only candidate is `route_hints.lane`, already a free string at its declaration.

    `want` has five members and `max_rung` seven; both are closed and small and keep their enums.
    The rule ships ahead of a parameter that needs it because the alternative is discovering the
    ceiling from a budget failure.
    """
    assert len(WANTS) <= ENUM_DEMOTE_MAX
    original = query_tool()["inputSchema"]["properties"]
    hidden = advanced_args("ow_query")
    survivors = {key: value for key, value in original.items() if key not in hidden}
    assert compact(query_tool())["inputSchema"]["properties"] == survivors


# ---------------------------------------------------------------------------------------------
# The promotion
# ---------------------------------------------------------------------------------------------


def test_with_required_corpus_promotes_in_property_order() -> None:
    """10:231 fixes property order; a `required` array ordered by anything else would make G25's
    byte-diff depend on the sequence of calls that produced it."""
    result = with_required_corpus(query_tool())
    assert result["inputSchema"]["required"] == ["query", "corpus"]


def test_with_required_corpus_does_not_touch_the_tool_it_was_given() -> None:
    tool = query_tool()
    before = copy.deepcopy(tool)
    with_required_corpus(tool)
    assert tool == before, "10:530: a COPY; the shared array is never touched"


def test_the_promotion_is_idempotent() -> None:
    once = with_required_corpus(query_tool())
    assert with_required_corpus(once) == once


def test_the_promotion_and_the_strip_commute_on_the_corpus_parameter() -> None:
    """`corpus` is advanced on no tool, so it survives the strip and can still be promoted."""
    assert with_required_corpus(compact(query_tool()))["inputSchema"]["required"] == [
        "query",
        "corpus",
    ]
    assert CORPUS_PARAM not in advanced_args("ow_query")


def test_a_tool_with_no_corpus_property_comes_back_an_equal_copy() -> None:
    """10:525 scopes the promotion to *every corpus-scoped listed tool*, and the property is what
    makes a tool one. `ow_doctor` and `ow_explain` read no store at all."""
    tool = {
        "name": "ow_explain",
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "string"}},
        },
    }
    result = with_required_corpus(tool)
    assert result == tool
    assert result["inputSchema"] is not tool["inputSchema"]


def test_corpus_scoped_is_derived_from_the_parameter_and_not_listed() -> None:
    derived = tuple(sorted(t for t in KNOWN_TOOLS if CORPUS_PARAM in declared_arg_keys(t)))
    assert derived == CORPUS_SCOPED
    assert "ow_doctor" not in CORPUS_SCOPED
    assert "ow_explain" not in CORPUS_SCOPED
    assert {"ow_query", "ow_open", "ow_corpora", "ow_add"} <= set(CORPUS_SCOPED)


# ---------------------------------------------------------------------------------------------
# The import-time refusal
# ---------------------------------------------------------------------------------------------


def test_an_advanced_parameter_that_is_required_would_be_unsatisfiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D309. Nothing in the eleven forbids it: check 11 asks only that an `advanced` member be a
    field of `inp`, and a field with no default is a field. The strip would then remove a property
    the same object declares `required`, under `additionalProperties: false` -- a tool no host can
    call, published by a registry that passed every check.
    """

    @dataclass(frozen=True, slots=True)
    class Needy:
        mandatory: str

    spec = ACTIONS["explain"]
    bad = type(spec)(
        **{
            **{f.name: getattr(spec, f.name) for f in fields(spec)},
            "inp": Needy,
            "advanced": frozenset({"mandatory"}),
            "example": {"mandatory": "x"},
        }
    )
    monkeypatch.setattr(schema_module, "ACTIONS", {"probe": bad})
    assert schema_module._unsatisfiable_rows() == (
        "probe: advanced names the required parameter(s) mandatory",
    )


def test_the_shipped_registry_publishes_no_unsatisfiable_schema() -> None:
    assert schema_module._unsatisfiable_rows() == ()
