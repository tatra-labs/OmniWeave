"""The Action registry: eleven checks, three orthogonal bits, and SV1. 10-interfaces.md section 2.

Every red case below builds its own `ActionSpec` and runs `_validate` over a mapping of its own.
None of them mutates `ACTIONS`, which is a `Mapping` built once at import (10:176) -- a test that
edited the shipped registry would be testing a state no process can reach.

The green assertions are over the shipped rows, because the property that matters is not that the
checker CAN fail but that the shipped registry passes every one of the eleven, today, at import.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.surface.registry as registry_module
import pytest
from omniweave.sdk import Gap as SdkGap
from omniweave.sdk.reports import AddReport, CorporaReport, CorpusCard
from omniweave.surface import ACTIONS, GROUPS, HUMAN_ONLY, PROFILES, ActionSpec, assert_sv1, listed
from omniweave.surface import inputs as inputs_module
from omniweave.surface.inputs import (
    CORPORA_DETAILS,
    QUERY_MAX_CHARS,
    REF_MAX,
    SOURCE_MAX,
    WANTS,
    AddIn,
    CorporaIn,
    OpenIn,
    QueryIn,
)
from omniweave.surface.registry import (
    DECISION_MAX,
    MCP_NAME_RE,
    SUMMARY_MAX,
    _index,
    _unrostered_human_only,
    _validate,
)
from omniweave_core.answer import Answer
from omniweave_core.answer.budget import HARD_CEILING
from omniweave_core.errors import SurfaceError
from omniweave_core.store.card import CorpusCardRow
from omniweave_core.store.card import Gap as StoreGap
from omniweave_ports import CostClass

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[4]

LISTED_NAMES = ("add", "corpora", "open", "query")
"""The four of 10:311, sorted. A fifth is rejected in advance (10:265) and the rejection is L1/L2
rather than budget: the default surface is measured at 850 tokens of a 1,900 ceiling."""

MCP_NAMES = ("ow_add", "ow_corpora", "ow_open", "ow_query")


def _spec(**over: Any) -> ActionSpec:
    """A minimal legal row, so a red case differs from green by exactly one field."""
    base: dict[str, Any] = {
        "name": "probe",
        "mcp_name": "ow_probe",
        "listed_in": frozenset(),
        "read_only": True,
        "idempotent": True,
        "open_world": False,
        "destructive": False,
        "cost_class": CostClass.FREE,
        "summary": "a probe row that exists only inside this test module",
        "decision": "you are testing the checker",
        "example": {"detail": "card"},
        "inp": CorporaIn,
        "out": CorporaReport,
        "advanced": frozenset(),
        "cli": ("corpora",),
    }
    base.update(over)
    return ActionSpec(**base)


def _mapping(*specs: ActionSpec) -> Mapping[str, ActionSpec]:
    return {spec.name: spec for spec in specs}


# ---------------------------------------------------------------------------------------------
# The shipped registry
# ---------------------------------------------------------------------------------------------


def test_the_shipped_registry_passes_all_eleven_checks_at_import() -> None:
    """If this fails the module would not have imported, which is the point of running at import."""
    assert _validate(ACTIONS) == ()


def test_the_four_listed_actions_are_the_front_door() -> None:
    assert tuple(sorted(ACTIONS)) == LISTED_NAMES
    assert tuple(sorted(spec.mcp_name or "" for spec in ACTIONS.values())) == MCP_NAMES


def test_every_profile_lists_all_four_and_full_is_a_superset_of_default() -> None:
    for profile in PROFILES:
        assert listed(profile) == LISTED_NAMES
    assert set(listed("default")) <= set(listed("full"))


def test_listed_refuses_a_profile_that_is_not_one_of_the_two() -> None:
    with pytest.raises(SurfaceError) as caught:
        listed("verbose")
    assert "verbose" in str(caught.value)
    assert "default" in caught.value.fix


def test_listed_is_sorted_because_the_generator_must_be_deterministic() -> None:
    """10:229: no iteration over an unsorted set, or the byte-diff gates a shape nobody wrote."""
    assert listed("full") == tuple(sorted(listed("full")))


def test_add_is_the_one_writer_and_the_only_open_world_action() -> None:
    """10:158: `open_world` is true *"only where the Action touches something outside the
    store"* -- `ow_add` alone, because it walks a filesystem or fetches a URL."""
    writers = [spec.name for spec in ACTIONS.values() if not spec.read_only]
    open_world = [spec.name for spec in ACTIONS.values() if spec.open_world]
    assert writers == ["add"]
    assert open_world == ["add"]


def test_no_listed_tool_is_destructive_including_the_writer() -> None:
    """10:161: ingest appends and never removes indexed content, so a host should not prompt."""
    assert [spec.name for spec in ACTIONS.values() if spec.destructive] == []


def test_every_listed_action_is_idempotent() -> None:
    """`ow_add`'s idempotency is the store's and not the surface's (18:1364), which is what
    makes an `idempotentHint: true` on a writer honest."""
    assert all(spec.idempotent for spec in ACTIONS.values())


def test_corpora_is_the_one_tool_compaction_does_not_change() -> None:
    """10:356, and it is still the second-cheapest tool at 189 tokens including its outputSchema."""
    assert ACTIONS["corpora"].advanced == frozenset()
    assert all(spec.advanced for name, spec in ACTIONS.items() if name != "corpora")


def test_the_advanced_sets_are_the_ones_the_strip_table_names() -> None:
    """10:495's `_ADVANCED`, which `ActionSpec.advanced` is stated to equal."""
    assert ACTIONS["query"].advanced == frozenset({"want", "route_hints", "max_chars"})
    assert ACTIONS["open"].advanced == frozenset({"context", "layers", "max_chars"})
    assert ACTIONS["add"].advanced == frozenset({"dry_run"})


def test_only_add_can_reach_a_billed_driver() -> None:
    """`cost_class` is the worst case over reachable drivers, and it is what the dispatcher reads
    to decide whether a call needs a cost deferral before it starts (10:166)."""
    billed = [s.name for s in ACTIONS.values() if s.cost_class is CostClass.BILLED_API]
    assert billed == ["add"]


def test_the_two_retrievers_return_an_answer_and_the_two_row_shaped_tools_do_not() -> None:
    """18:1316: no `outputSchema` on `ow_query` or `ow_open`, because declaring one obliges
    structured content that DOUBLES a 22,000-character answer in hosts that also emit the text."""
    assert ACTIONS["query"].out is Answer
    assert ACTIONS["open"].out is Answer
    assert ACTIONS["corpora"].out is CorporaReport
    assert ACTIONS["add"].out is AddReport


def test_no_action_is_human_only_yet_and_none_of_the_four_could_be() -> None:
    assert [spec.name for spec in ACTIONS.values() if spec.human_only] == []
    assert set(ACTIONS) & HUMAN_ONLY == set()


# ---------------------------------------------------------------------------------------------
# The eleven checks, one red case each
# ---------------------------------------------------------------------------------------------


def test_check_1_a_row_keyed_under_another_name_is_caught() -> None:
    bad = {"corpora": _spec(name="query")}
    assert any("names itself" in line for line in _validate(bad))


def test_check_1_a_duplicate_name_raises_at_build_rather_than_winning_the_dict() -> None:
    with pytest.raises(SurfaceError) as caught:
        _index((_spec(), _spec(mcp_name="ow_other")))
    assert "two Actions are named" in str(caught.value)
    assert caught.value.code() == "OW_SURFACE_REGISTRY_INVALID"


def test_check_2_two_actions_on_one_mcp_name_is_caught() -> None:
    """10:197's own example: the dispatcher would resolve to whichever won the dict."""
    bad = _mapping(_spec(), _spec(name="probe2", mcp_name="ow_probe"))
    assert any("is already probe's" in line for line in _validate(bad))


@pytest.mark.parametrize("bad_name", ["query", "OW_QUERY", "ow_", "ow_1query", "ow_q", "ow-query"])
def test_check_3_a_name_a_host_cannot_address_is_caught(bad_name: str) -> None:
    assert not MCP_NAME_RE.match(bad_name)
    assert any("is not ow_" in line for line in _validate(_mapping(_spec(mcp_name=bad_name))))


def test_check_3_accepts_all_four_shipped_names() -> None:
    assert all(MCP_NAME_RE.match(name) for name in MCP_NAMES)


def test_check_4_a_human_only_action_that_is_reachable_is_caught() -> None:
    bad = _mapping(_spec(name="uninstall", mcp_name="ow_uninstall", cli=("uninstall",)))
    assert any("HUMAN_ONLY" in line for line in _validate(bad))


def test_check_4_a_human_only_action_that_is_listed_is_caught() -> None:
    bad = _mapping(
        _spec(name="corpus.rm", mcp_name=None, listed_in=frozenset(PROFILES), cli=("corpora",))
    )
    failures = _validate(bad)
    assert any("HUMAN_ONLY" in line for line in failures)


def test_check_5_a_listing_that_can_never_take_effect_is_caught() -> None:
    bad = _mapping(_spec(mcp_name=None, listed_in=frozenset(PROFILES)))
    assert any("can never take effect" in line for line in _validate(bad))


def test_check_6_an_unknown_profile_is_caught() -> None:
    bad = _mapping(_spec(listed_in=frozenset({"default", "full", "verbose"})))
    assert any("not a subset" in line for line in _validate(bad))


def test_check_6_default_without_full_is_not_a_superset_of_the_profile_below_it() -> None:
    bad = _mapping(_spec(listed_in=frozenset({"default"})))
    assert any("but not in 'full'" in line for line in _validate(bad))


def test_check_6_full_alone_is_legal_which_is_the_whole_eighteen_row_roster() -> None:
    """10:802: the `full` roster is defined and dispatchable always, listed only under `full`."""
    assert _validate(_mapping(_spec(listed_in=frozenset({"full"})))) == ()


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("summary", "", "summary is empty"),
        ("decision", "", "decision is empty"),
        ("summary", "x" * (SUMMARY_MAX + 1), "over 160"),
        ("decision", "x" * (DECISION_MAX + 1), "over 90"),
        ("summary", "ends in a stop.", "full stop"),
        ("decision", "ends in a stop.", "full stop"),
    ],
)
def test_check_7_the_catalog_row_cannot_wrap_a_table(field: str, value: str, fragment: str) -> None:
    assert any(fragment in line for line in _validate(_mapping(_spec(**{field: value}))))


def test_check_7_holds_over_every_shipped_row() -> None:
    for spec in ACTIONS.values():
        assert 0 < len(spec.summary) <= SUMMARY_MAX, spec.name
        assert 0 < len(spec.decision) <= DECISION_MAX, spec.name
        assert not spec.summary.endswith(".")
        assert not spec.decision.endswith(".")


def test_check_8_an_example_naming_a_parameter_that_does_not_exist_is_caught() -> None:
    bad = _mapping(_spec(example={"detail": "card", "verbosity": 3}))
    assert any("is not a field" in line for line in _validate(bad))


def test_check_8_an_example_of_the_wrong_type_is_caught() -> None:
    bad = _mapping(_spec(example={"detail": 4}))
    assert any("does not satisfy" in line for line in _validate(bad))


def test_check_8_an_example_omitting_a_required_parameter_is_caught() -> None:
    bad = _mapping(_spec(inp=QueryIn, out=Answer, example={"corpus": "handbook"}))
    assert any("omits required field 'query'" in line for line in _validate(bad))


def test_check_8_widens_an_int_to_a_float_but_never_a_bool_to_an_int() -> None:
    """JSON widens an integer to a number; it does not widen a boolean to an integer."""
    assert _validate(_mapping(_spec(inp=OpenIn, example={"ref": "d7#412", "context": 2}))) == ()
    bad = _mapping(_spec(inp=OpenIn, example={"ref": "d7#412", "context": True}))
    assert any("does not satisfy" in line for line in _validate(bad))


def test_check_8_every_shipped_example_would_work_if_an_agent_copied_it() -> None:
    """10:193 is the whole reason the check exists: *"an example an agent copies and gets an
    argument error from"*. Constructing the input type is the strongest available form."""
    for spec in ACTIONS.values():
        spec.inp(**dict(spec.example))


def test_check_9_an_empty_cli_tuple_is_caught() -> None:
    assert any("cli must be non-empty" in line for line in _validate(_mapping(_spec(cli=()))))


def test_check_9_an_undeclared_cli_root_is_caught() -> None:
    bad = _mapping(_spec(cli=("corpuses", "ls")))
    assert any("is not a declared root" in line for line in _validate(bad))


def test_check_9_two_roots_differing_only_by_a_trailing_s_are_caught() -> None:
    """10:238's `ow driver` / `ow drivers` collision, which one `cli` tuple cannot generate both
    halves of -- *"and one of them would silently win"*."""
    bad = _mapping(
        _spec(name="a", mcp_name="ow_a", cli=("hook",)),
        _spec(name="b", mcp_name="ow_b", cli=("hooks",)),
    )
    assert any("trailing s" in line for line in _validate(bad))


def test_check_10_destructive_still_has_no_default_so_omission_is_a_type_error() -> None:
    """10:169: MCP's own default is `true`, so a defaulted `false` would silently invert the most
    alarming annotation the protocol has."""
    declared = {field.name: field for field in fields(ActionSpec)}
    assert declared["destructive"].default is not False
    with pytest.raises(TypeError):
        ActionSpec(  # type: ignore[call-arg]
            name="probe",
            mcp_name=None,
            listed_in=frozenset(),
            read_only=False,
            idempotent=True,
            open_world=False,
            cost_class=CostClass.FREE,
            summary="a writer that forgot to declare destructiveness",
            decision="this construction never completes",
            example={},
            inp=CorporaIn,
            out=CorporaReport,
        )


def test_check_11_an_advanced_member_that_is_not_a_parameter_is_caught() -> None:
    bad = _mapping(_spec(advanced=frozenset({"verbosity"})))
    assert any("not a field of the input" in line for line in _validate(bad))


def test_check_11_holds_over_every_shipped_row() -> None:
    for spec in ACTIONS.values():
        declared = {field.name for field in fields(spec.inp)}
        assert spec.advanced <= declared, spec.name


def test_validate_reports_every_failing_row_rather_than_the_first() -> None:
    """10:179: *"naming every failing row"*. A registry with three defects costs one cycle."""
    bad = _mapping(
        _spec(name="a", mcp_name="nope", cli=()),
        _spec(name="b", mcp_name="ow_b", summary=""),
        _spec(name="c", mcp_name="ow_c", advanced=frozenset({"nothing"})),
    )
    failures = _validate(bad)
    assert len({line.split(":")[0] for line in failures}) == 3


# ---------------------------------------------------------------------------------------------
# `HUMAN_ONLY`, and the check that is not among the eleven
# ---------------------------------------------------------------------------------------------


def test_human_only_is_the_charters_five() -> None:
    assert (
        frozenset({"uninstall", "corpus.rm", "route.promote", "skills.remove", "targets.remove"})
        == HUMAN_ONLY
    )


def test_no_eleventh_check_asserts_a_human_only_name_has_a_row_at_all() -> None:
    """D291. Check 4 is an implication, so a typo in the frozenset satisfies it vacuously.

    All five are unrostered today, which is schedule and not defect -- W7.1's first cell carries the
    four listed Actions. When the roster closes, this assertion is the one line that changes.
    """
    assert _unrostered_human_only(ACTIONS) == (
        "corpus.rm",
        "route.promote",
        "skills.remove",
        "targets.remove",
        "uninstall",
    )
    assert _validate(ACTIONS) == (), "and the eleven checks say nothing about it"


def test_a_typo_in_human_only_disarms_check_4_without_failing_anything() -> None:
    """The failure mode D291 names, reproduced: the guarded Action is reachable and legal."""
    typo = _mapping(_spec(name="corpora.rm", mcp_name="ow_corpora_rm", cli=("corpora",)))
    assert "corpora.rm" not in HUMAN_ONLY
    assert _validate(typo) == ()


# ---------------------------------------------------------------------------------------------
# The CLI root registry
# ---------------------------------------------------------------------------------------------


def test_every_shipped_cli_root_is_declared() -> None:
    assert {spec.cli[0] for spec in ACTIONS.values()} <= GROUPS


def test_the_declared_roster_already_contains_one_trailing_s_collision() -> None:
    """D295. `ow hook <event>` and `ow hooks check` are both in 18:918's command surface.

    10:238 gives the rule's motivating example as `ow driver` / `ow drivers`, which does not occur.
    The pair that does occur is named nowhere in the plan.
    """
    collisions = sorted(root for root in GROUPS if root + "s" in GROUPS)
    assert collisions == ["hook"]


def test_there_is_no_top_level_export_init_or_resume_root() -> None:
    """18:975, 10:1464, 10:1468 -- each absence is load-bearing and each has a stated reason."""
    assert {"export", "init", "resume"} & GROUPS == set()


def test_store_and_index_are_roots_although_neither_prints_a_verb_count() -> None:
    """18:947: a numeral is a second copy of an enumeration and drifts from it in silence."""
    assert {"store", "index"} <= GROUPS


# ---------------------------------------------------------------------------------------------
# SV1
# ---------------------------------------------------------------------------------------------


def test_sv1_passes_when_listed_is_a_subset_of_enabled() -> None:
    assert assert_sv1(listed("default"), ("query", "open", "corpora", "add", "doctor")) is None


def test_sv1_refuses_a_listed_action_the_operator_did_not_enable() -> None:
    with pytest.raises(SurfaceError) as caught:
        assert_sv1(("query", "add"), ("query",))
    assert "add" in str(caught.value)
    assert caught.value.code() == "OW_ACTION_NOT_ENABLED"
    assert "OMNIWEAVE_MCP_ENABLED" in caught.value.fix


def test_sv1_refuses_a_human_only_action_in_enabled_even_when_nothing_lists_it() -> None:
    """10:792: naming one in either variable is a startup error, not a warning."""
    with pytest.raises(SurfaceError) as caught:
        assert_sv1((), ("query", "uninstall"))
    assert "uninstall" in str(caught.value)
    assert caught.value.code() == "OW_HUMAN_ONLY_ACTION"


def test_sv1_exits_1_before_the_transport_opens() -> None:
    """02:723 fixes the number, and it is the same one for both clauses."""
    for listed_now, enabled_now in ((("add",), ()), ((), ("corpus.rm",))):
        with pytest.raises(SurfaceError) as caught:
            assert_sv1(listed_now, enabled_now)
        assert caught.value.EXIT == 1


def test_the_shipped_default_enabled_preset_would_grant_exactly_the_listed_set() -> None:
    """10:846: `read_only+add` grants the read-only Actions plus `add`, and every `full` tool is
    read-only *"forced by SV1, not by taste"* -- listing a writer would fail the default config."""
    read_only_plus_add = {s.name for s in ACTIONS.values() if s.read_only} | {"add"}
    assert assert_sv1(listed("full"), read_only_plus_add) is None


# ---------------------------------------------------------------------------------------------
# The input types
# ---------------------------------------------------------------------------------------------


def test_declaration_order_is_the_published_property_order() -> None:
    """10:231: schema properties in `dataclasses.fields` order. Reordering a field is a wire change.

    The orders here are 18:1258, 18:1335, 18:1349 and 18:1356 as those objects print them.
    """
    assert [f.name for f in fields(QueryIn)] == [
        "query",
        "corpus",
        "scope",
        "want",
        "route_hints",
        "max_chars",
    ]
    assert [f.name for f in fields(OpenIn)] == ["ref", "corpus", "context", "layers", "max_chars"]
    assert [f.name for f in fields(CorporaIn)] == ["corpus", "detail"]
    assert [f.name for f in fields(AddIn)] == ["source", "corpus", "dry_run"]


def test_the_required_parameter_of_each_tool_is_the_one_the_schema_requires() -> None:
    """`required` in the published inputSchema is exactly the fields with no default."""
    required = {
        name: {f.name for f in fields(spec.inp) if f.default is f.default_factory}
        for name, spec in ACTIONS.items()
    }
    assert required == {
        "query": {"query"},
        "open": {"ref"},
        "corpora": set(),
        "add": {"source"},
    }


def test_the_published_bounds_are_the_plans_numbers() -> None:
    assert QUERY_MAX_CHARS == 4096
    assert REF_MAX == 64
    assert SOURCE_MAX == 256


def test_max_chars_has_no_second_ceiling_constant() -> None:
    """INV-21: `HARD_CEILING` already has a home in `omniweave_core.answer.budget`."""
    assert HARD_CEILING == 24_000
    assert not [n for n in vars(inputs_module) if n.endswith("MAX_CHARS_MAX")]


def test_the_two_closed_enums_keep_their_members_and_their_order() -> None:
    """10:516: `want` (5) and `max_rung` (7) are closed and small and keep their enums; only an
    enum over 12 members is demoted to a described free string."""
    assert WANTS == ("passages", "table", "fields", "outline", "related")
    assert CORPORA_DETAILS == ("list", "card", "coverage", "actions")
    assert QueryIn("q").want == WANTS[0]
    assert CorporaIn().detail == CORPORA_DETAILS[0]
    assert len(WANTS) <= 12


def test_no_query_input_carries_a_schema_or_a_refs_parameter() -> None:
    """18:1322, and 18:980 calls putting `--schema` on `query` *"the single most consequential
    error a caller could inherit from an API reference"*."""
    names = {f.name for f in fields(QueryIn)}
    assert {"schema", "refs", "corpora", "k", "mode"} & names == set()


def test_open_carries_no_want_impact_knob() -> None:
    """18:1365: the handler sets it by default when the ref is a single block, so a 64-ref batch
    does not pay 192 joins."""
    assert "want_impact" not in {f.name for f in fields(OpenIn)}


def test_add_carries_no_allow_cost_parameter_which_is_why_it_survives_row_2() -> None:
    """10:1131: the approval path is CLI-only, *"because `RouteHints` correctly has no budget
    field"*."""
    assert "allow_cost" not in {f.name for f in fields(AddIn)}
    assert ACTIONS["add"].mcp_name == "ow_add"


# ---------------------------------------------------------------------------------------------
# The report types
# ---------------------------------------------------------------------------------------------


def test_truncated_is_top_level_and_appears_on_no_card() -> None:
    """D292. 10:1097 makes it *"a top-level boolean rather than a count"*; 18:687 puts it on the
    row. The listing's flag belongs to the listing."""
    assert "truncated" in {f.name for f in fields(CorporaReport)}
    assert "truncated" not in {f.name for f in fields(CorpusCard)}


def test_the_card_carries_the_three_read_time_degradations_on_the_row() -> None:
    """10:1092: *"so a client that iterates `corpora` cannot miss them"*."""
    assert {"readable", "reason", "card_stale"} <= {f.name for f in fields(CorpusCard)}


def test_the_card_is_not_the_stored_row() -> None:
    """`CorpusCardRow` is the table's shape; the three degradations are properties of a read."""
    stored = {f.name for f in fields(CorpusCardRow)}
    assert {"readable", "reason", "card_stale"} & stored == set()


def test_gap_has_one_home_and_the_sdk_imports_it() -> None:
    """INV-21. Absence gate 9 reads it in the store, which may not import this distribution."""
    assert SdkGap is StoreGap


def test_the_add_report_has_no_verdict_field() -> None:
    """18:1520: `ow_add` writes the roster, not the queue, so it has no verdict to report."""
    assert "verdict" not in {f.name for f in fields(AddReport)}


def test_plan_is_an_alias_rather_than_a_second_field() -> None:
    """18:715: one field, two names, so the two spellings cannot disagree."""
    report = AddReport(
        scope_id=92,
        corpus="handbook",
        discovered=6,
        unchanged=4,
        queued=2,
        skipped=0,
        completed=(),
        pending=(),
        degradations=(),
        deadline_reached=False,
    )
    assert report.plan is report.pending
    assert "plan" not in {f.name for f in fields(AddReport)}


def test_the_wire_forms_field_lists_are_the_plans() -> None:
    """10:1040 and 10:1112, transcribed. A field added here is an MCP output change (11:1101)."""
    assert [f.name for f in fields(CorporaReport)] == [
        "corpora",
        "truncated",
        "degradations",
        "schema",
    ]
    assert [f.name for f in fields(AddReport)] == [
        "scope_id",
        "corpus",
        "discovered",
        "unchanged",
        "queued",
        "skipped",
        "completed",
        "pending",
        "degradations",
        "deadline_reached",
        "schema",
    ]


# ---------------------------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------------------------


def test_the_registry_invalid_symbol_resolves_through_ow_explain() -> None:
    register = tomllib.loads((REPO_ROOT / "codes.toml").read_text(encoding="utf-8"))
    rows = {row["symbol"]: row for row in register["code"]}
    assert rows["OW_SURFACE_REGISTRY_INVALID"]["numeric"] == "OW-A-028"
    assert rows["OW_SURFACE_REGISTRY_INVALID"]["raised_by"] == "SurfaceError"


def test_the_two_sv1_symbols_are_already_registered() -> None:
    register = tomllib.loads((REPO_ROOT / "codes.toml").read_text(encoding="utf-8"))
    symbols = {row["symbol"] for row in register["code"]}
    assert {"OW_ACTION_NOT_ENABLED", "OW_HUMAN_ONLY_ACTION"} <= symbols


def test_no_generated_artefact_has_been_written_yet() -> None:
    """02:254 forbids this package from emitting them; row 31 is `omniweave/gen/`, W7.2's."""
    assert not (REPO_ROOT / "llms.txt").exists()
    assert not (REPO_ROOT / "schema" / "mcp-tools-v1.json").exists()


def test_the_repo_root_this_module_computed_is_the_repo_root() -> None:
    assert (REPO_ROOT / "codes.toml").is_file()
    assert json.loads((REPO_ROOT / "schema" / "answer-v1.json").read_text(encoding="utf-8"))


def test_the_module_docstring_carries_the_ordering_constraint_that_put_it_first() -> None:
    """FE5 (16:32): `surface/registry.py` precedes the SECOND agent-facing surface.

    There is no gate for a build order, so the argument lives where the next writer reads it --
    ship a hand-written CLI first and the registry's arrival is a reconciliation between two
    surfaces that already disagree.
    """
    doc = registry_module.__doc__ or ""
    assert "FE5 (16:32)" in doc
    assert re.search(r"\b10:10\b", doc), "the paragraph that homes ACTIONS here"
