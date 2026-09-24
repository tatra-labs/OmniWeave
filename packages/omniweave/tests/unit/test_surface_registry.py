"""The Action registry: eleven checks, three orthogonal bits, and SV1. 10-interfaces.md section 2.

Every red case below builds its own `ActionSpec` and runs `_validate` over a mapping of its own.
None of them mutates `ACTIONS`, which is a `Mapping` built once at import (10:176) -- a test that
edited the shipped registry would be testing a state no process can reach.

The green assertions are over the shipped rows, because the property that matters is not that the
checker CAN fail but that the shipped registry passes every one of the eleven, today, at import.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess  # noqa: TID251 -- D298 is observable only from a fresh interpreter.
import sys
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.sdk as sdk_root
import omniweave.surface.registry as registry_module
import pytest
from omniweave.sdk import Gap as SdkGap
from omniweave.sdk.reports import (
    DOCTOR_SEVERITIES,
    SEVERITIES,
    AddReport,
    CodeRow,
    CorporaReport,
    CorpusCard,
    DoctorFinding,
    DoctorReport,
)
from omniweave.surface import (
    ACTIONS,
    CLI_ABSENT,
    CLI_FREE,
    CLI_ROSTER,
    CLI_UNROSTERED,
    FULL_ROSTER,
    GROUPS,
    HUMAN_ONLY,
    PROFILES,
    ActionSpec,
    assert_sv1,
    listed,
    resolve_cli,
)
from omniweave.surface import inputs as inputs_module
from omniweave.surface.inputs import (
    CORPORA_DETAILS,
    QUERY_MAX_CHARS,
    REF_MAX,
    SOURCE_MAX,
    WANTS,
    AddIn,
    CorporaIn,
    CoverageIn,
    DiffIn,
    DoctorIn,
    ExplainIn,
    GridIn,
    OpenIn,
    QueryIn,
)
from omniweave.surface.registry import (
    DECISION_MAX,
    MCP_NAME_RE,
    SUMMARY_MAX,
    _cli_roster_failures,
    _duplicate_cli,
    _index,
    _roster_failures,
    _unrostered_cli,
    _unrostered_full,
    _unrostered_human_only,
    _validate,
)
from omniweave_core.answer import Answer
from omniweave_core.answer.budget import HARD_CEILING
from omniweave_core.errors import SurfaceError
from omniweave_core.model import Grid
from omniweave_core.model.rebind import RebindReport
from omniweave_core.retrieve.verdict import Coverage
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

NARROW_NAMES = ("corpus.coverage", "doc.diff", "doc.grid", "doctor", "explain")
"""The five of 10:807's eighteen that have rows, sorted as `listed()` returns them.

Five and not eighteen because `ActionSpec.out` is a `type` and thirteen output types have no home
in this process yet -- seven in P8, two in P9, three forward-referenced by their own document, and
`route.explain`'s deferred for a measured import cost (D298). `_unrostered_full()` names them."""

FULL_ROSTER_NAMES = (
    "doc.outline",
    "doc.grid",
    "extract.fields",
    "graph.entities",
    "graph.locate",
    "graph.neighbors",
    "graph.report",
    "graph.claims",
    "doc.xrefs",
    "route.explain",
    "doc.verify_quote",
    "corpus.coverage",
    "doc.diff",
    "out.list",
    "out.targets",
    "cost.report",
    "doctor",
    "explain",
)
"""10:807-822's Action column, transcribed here a second time and on purpose.

`FULL_ROSTER` is the shipped copy and this is the test's own, typed from the table rather than
imported from the module, so the assertion below compares two independent transcriptions. Importing
the constant and asserting it equals itself would test nothing.
"""


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
    """The front door is a PROFILE and not the mapping: `ACTIONS` also carries narrow rows."""
    assert listed("default") == LISTED_NAMES
    assert tuple(sorted(ACTIONS[name].mcp_name or "" for name in LISTED_NAMES)) == MCP_NAMES


def test_default_is_the_four_and_full_is_a_superset_of_it() -> None:
    assert listed("default") == LISTED_NAMES
    assert set(listed("default")) < set(listed("full"))
    assert set(listed("full")) - set(listed("default")) == set(NARROW_NAMES)


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
    store"* -- `ow_add` alone, because it walks a filesystem or fetches a URL.

    `add` is the one writer an agent can reach. `install`, `uninstall` and the two `ow skills`
    verbs write too -- an agent host's configuration -- and have no `mcp_name` (10:53's row 1,
    D469, D489), so no agent reaches them over MCP.
    """
    writers = [spec.name for spec in ACTIONS.values() if not spec.read_only]
    open_world = [spec.name for spec in ACTIONS.values() if spec.open_world]
    assert writers == ["add", "install", "uninstall", "skills.install", "skills.remove"]
    assert [name for name in writers if ACTIONS[name].mcp_name is not None] == ["add"]
    #  `hooks.check` runs the installed commands, which are outside the store (10:157-158); it
    #  reads and writes nothing of the deployment, so it is open-world and read-only.
    assert open_world == ["add", "hooks.check"]


def test_no_listed_tool_is_destructive_including_the_writer() -> None:
    """10:161: ingest appends and never removes indexed content, so a host should not prompt.

    `uninstall` and `skills.remove` are destructive -- they remove configuration a user has -- and
    both are human-only.
    """
    destructive = [spec.name for spec in ACTIONS.values() if spec.destructive]
    assert destructive == ["uninstall", "skills.remove"]
    assert [name for name in LISTED_NAMES if ACTIONS[name].destructive] == []


def test_every_listed_action_is_idempotent() -> None:
    """`ow_add`'s idempotency is the store's and not the surface's (18:1364), which is what
    makes an `idempotentHint: true` on a writer honest."""
    assert all(spec.idempotent for spec in ACTIONS.values())


def test_corpora_is_the_one_tool_compaction_does_not_change() -> None:
    """10:356, and it is still the second-cheapest tool at 189 tokens including its outputSchema."""
    assert ACTIONS["corpora"].advanced == frozenset()
    assert all(ACTIONS[name].advanced for name in LISTED_NAMES if name != "corpora")


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


def test_the_human_only_actions_are_the_install_and_skills_verbs_and_none_of_the_four() -> None:
    """`install` and `uninstall` are the first rows with `mcp_name = None`, and the `ow skills`
    pair the next. `uninstall` and `skills.remove` are in `HUMAN_ONLY`, the roster 10:143
    transcribes: 10:53's row 1 also matches `install` and `skills.install`, and the roster leaves
    both out (D469, D489)."""
    unreachable = [spec.name for spec in ACTIONS.values() if spec.human_only]
    assert unreachable == ["install", "uninstall", "skills.install", "skills.remove"]
    assert set(ACTIONS) & HUMAN_ONLY == {"uninstall", "skills.remove"}
    assert not any(ACTIONS[name].human_only for name in LISTED_NAMES)


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
    """10:802: the `full` roster is defined and dispatchable always, listed only under `full`.

    The probe borrows a rostered identity, because a `full`-only listing is legal exactly when
    `FULL_ROSTER` carries the Action -- which is `_roster_failures`' fourth clause and is what
    stops a nineteenth narrow tool arriving without a line in 10:807's table.
    """
    rostered = _spec(name="doc.outline", mcp_name="ow_outline", listed_in=frozenset({"full"}))
    assert _validate(_mapping(rostered)) == ()


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
    assert _unrostered_human_only(ACTIONS) == ("corpus.rm", "route.promote", "targets.remove")
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
        "doc.grid": {"ref"},
        "corpus.coverage": set(),
        "doc.diff": {"ref"},
        "doctor": set(),
        "explain": {"code"},
        "install": set(),
        "uninstall": set(),
        "skills.install": {"name"},
        "skills.remove": {"name"},
        "skills.ls": set(),
        "skills.verify": set(),
        "skills.check": set(),
        "skills.hash": set(),
        "hooks.check": set(),
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


WRITING_CALLS: frozenset[str] = frozenset(
    {"open", "write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace"}
)
"""Every way a module could put bytes on disk, as an attribute or a builtin name."""


def test_this_package_can_write_no_file_at_all() -> None:
    """02:254's forbidden column: this package declares, and row 31's `omniweave/gen/` emits.

    Stated over the package's SOURCE rather than over two artefact paths, because those paths
    stopped being evidence when W7.2b landed `schema/mcp-tools-v1.json`: the file exists now and
    `omniweave.gen.mcp_tools` wrote it, which is row 31 doing its job rather than row 30 exceeding
    it. What must stay true is that nothing HERE can write one, and that is also 10:300's claim --
    this module is imported by every CLI and server entry point, so an `open` on any path in it
    would be charged to every `ow query`.

    `omniweave.gen.check()`'s third clause carries the other half, over all six artefact paths.
    """
    package = REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "surface"
    sources = sorted(package.glob("*.py"))
    assert [path.name for path in sources] == [
        "__init__.py",
        "authority.py",
        "inputs.py",
        "registry.py",
        "schema.py",
        "startup.py",
    ]
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            assert called not in WRITING_CALLS, f"{path.name}: {called}()"


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


# ---------------------------------------------------------------------------------------------
# The `full` roster
# ---------------------------------------------------------------------------------------------


def test_the_roster_is_10_807s_eighteen_in_that_tables_order() -> None:
    """Two independent transcriptions of one table, compared. Eighteen rows, that order."""
    assert len(FULL_ROSTER) == 18
    assert tuple(name for _, name in FULL_ROSTER) == FULL_ROSTER_NAMES


def test_every_rostered_tool_name_satisfies_the_name_grammar() -> None:
    """Check 3's pattern applies to a roster entry before any row exists to carry it."""
    for mcp_name, name in FULL_ROSTER:
        assert MCP_NAME_RE.match(mcp_name), f"{name} is rostered as {mcp_name!r}"


def test_the_roster_names_each_action_once_and_each_tool_once() -> None:
    assert len({name for _, name in FULL_ROSTER}) == len(FULL_ROSTER)
    assert len({mcp for mcp, _ in FULL_ROSTER}) == len(FULL_ROSTER)


def test_thirteen_of_the_eighteen_are_still_waiting_on_an_output_type() -> None:
    """`_unrostered_full()` is schedule, not defect, and reports in the table's order.

    The day this becomes `()` is the day 10:833's `ow surface budget --bless` has its condition:
    the `full_*` baseline rows are written *"on the first run after the eighteen `ActionSpec`s
    exist"*, and this tuple is the distance from that run.
    """
    assert _unrostered_full(ACTIONS) == (
        "doc.outline",
        "extract.fields",
        "graph.entities",
        "graph.locate",
        "graph.neighbors",
        "graph.report",
        "graph.claims",
        "doc.xrefs",
        "route.explain",
        "doc.verify_quote",
        "out.list",
        "out.targets",
        "cost.report",
    )


def test_the_landed_five_are_the_roster_minus_the_thirteen() -> None:
    waiting = set(_unrostered_full(ACTIONS))
    landed = tuple(sorted(name for _, name in FULL_ROSTER if name not in waiting))
    assert landed == NARROW_NAMES


def test_every_narrow_row_is_read_only_free_and_not_destructive() -> None:
    """10:823: forced by SV1 rather than chosen.

    `listed` must be a subset of `enabled`, the shipped `[serve] enabled = "read_only+add"` grants
    the read-only Actions plus `add`, so a writer listed in `full` would make the default
    configuration fail its own startup check. `ow_ingest` is the named casualty.
    """
    for name in NARROW_NAMES:
        spec = ACTIONS[name]
        assert spec.read_only, name
        assert spec.idempotent, name
        assert not spec.destructive, name
        assert not spec.open_world, name
        assert spec.cost_class is CostClass.FREE, name


def test_the_shipped_enabled_preset_grants_every_listed_action_in_both_profiles() -> None:
    """SV1 over the configuration that ships, which is the check 10:823 argues from."""
    read_only_plus_add = {name for name, spec in ACTIONS.items() if spec.read_only} | {"add"}
    for profile in PROFILES:
        assert_sv1(listed(profile), read_only_plus_add)


def test_each_narrow_row_declares_the_out_type_its_own_home_owns() -> None:
    """`out` is imported, never redefined: 18 section 1.6's rule, applied row by row.

    `Grid`, `Coverage` and `RebindReport` are `omniweave_core`'s and arrive through it; only
    `DoctorReport` and `CodeRow` are this distribution's, and those two because 18 section 1.4
    prints them field for field the way it prints `CorpusCard`.
    """
    assert ACTIONS["doc.grid"].out is Grid
    assert ACTIONS["corpus.coverage"].out is Coverage
    assert ACTIONS["doc.diff"].out is RebindReport
    assert ACTIONS["doctor"].out is DoctorReport
    assert ACTIONS["explain"].out is CodeRow


def test_the_narrow_rows_carry_the_cli_spellings_their_documents_print() -> None:
    assert ACTIONS["doc.grid"].cli == ("doc", "grid")
    assert ACTIONS["doc.diff"].cli == ("doc", "diff")
    assert ACTIONS["doctor"].cli == ("doctor",)
    assert ACTIONS["explain"].cli == ("explain",)
    assert ACTIONS["corpus.coverage"].cli == ("corpora",)


def test_no_narrow_row_is_human_only() -> None:
    """A `full` listing and `mcp_name = None` contradict by check 4; this is the other end."""
    assert not set(NARROW_NAMES) & HUMAN_ONLY
    assert all(ACTIONS[name].mcp_name is not None for name in NARROW_NAMES)


# ---------------------------------------------------------------------------------------------
# `_roster_failures`: the reconciliation that is not one of the eleven
# ---------------------------------------------------------------------------------------------


def test_roster_clause_1_a_tool_name_rostered_twice_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure a mapping literal answers by discarding a line."""
    monkeypatch.setattr(
        registry_module,
        "FULL_ROSTER",
        (("ow_twin", "first.thing"), ("ow_twin", "second.thing")),
    )
    failures = _roster_failures({})
    assert any("'ow_twin' is first.thing's and second.thing's" in line for line in failures)


def test_roster_clause_1_an_action_rostered_twice_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module,
        "FULL_ROSTER",
        (("ow_one", "same.thing"), ("ow_two", "same.thing")),
    )
    assert any("is rostered twice" in line for line in _roster_failures({}))


def test_roster_clause_2_a_row_that_renamed_its_tool_is_reported() -> None:
    """The two columns of 10:807 are one fact written twice, so they may not drift apart."""
    renamed = _spec(name="doc.outline", mcp_name="ow_spine", listed_in=frozenset({"full"}))
    failures = _roster_failures(_mapping(renamed))
    assert any("rostered as 'ow_outline' but declares mcp_name 'ow_spine'" in x for x in failures)


def test_roster_clause_3_a_rostered_row_that_widened_into_default_is_reported() -> None:
    """10:265 rejects a fifth listed tool in advance; this is the door it would arrive through."""
    widened = _spec(
        name="doc.outline", mcp_name="ow_outline", listed_in=frozenset({"default", "full"})
    )
    failures = _roster_failures(_mapping(widened))
    assert any("not ['full']" in line for line in failures)


def test_roster_clause_4_a_full_listing_absent_from_the_roster_is_reported() -> None:
    """Without this clause the roster is documentation rather than a register."""
    stranger = _spec(name="new.thing", mcp_name="ow_new_thing", listed_in=frozenset({"full"}))
    failures = _roster_failures(_mapping(stranger))
    assert any("absent from FULL_ROSTER" in line for line in failures)


def test_an_unlisted_row_is_not_a_roster_concern() -> None:
    """10:857's ~110: an `mcp_name`, an empty `listed_in`, and no line in any profile's table."""
    assert _roster_failures(_mapping(_spec(name="store.export"))) == ()


def test_the_shipped_registry_reconciles_with_its_own_roster() -> None:
    assert _roster_failures(ACTIONS) == ()


# ---------------------------------------------------------------------------------------------
# `_duplicate_cli`: the clause check 9 does not have
# ---------------------------------------------------------------------------------------------


def test_duplicate_cli_names_the_corpora_pair_and_nothing_else() -> None:
    """D299. `ow corpora` is two Actions, and the second is a FLAG VALUE on the first (10:1424).

    Reported rather than raised, for D295's reason: the pair surfaces on the day both rows land,
    which is the day the generator has to decide how a flag-valued twin is emitted.
    """
    assert _duplicate_cli(ACTIONS) == (("corpora",),)
    sharing = sorted(n for n, s in ACTIONS.items() if s.cli == ("corpora",))
    assert sharing == ["corpora", "corpus.coverage"]


def test_duplicate_cli_is_empty_when_every_tuple_differs() -> None:
    a = _spec(name="a", mcp_name="ow_a", cli=("doc", "grid"))
    b = _spec(name="b", mcp_name="ow_b", cli=("doc", "diff"))
    assert _duplicate_cli(_mapping(a, b)) == ()


def test_duplicate_cli_ignores_the_unreachable_empty_tuple() -> None:
    """Check 9 already forbids an empty `cli`; a second reporter must not double-count it."""
    assert _duplicate_cli(_mapping(_spec(name="a", mcp_name="ow_a", cli=()))) == ()


def test_the_shipped_roots_still_contain_no_trailing_s_collision() -> None:
    """Check 9's third clause over the roots the registry now uses. `hook`/`hooks` is not here
    yet -- both are declared in `GROUPS` and neither has a row (D295)."""
    roots = {spec.cli[0] for spec in ACTIONS.values() if spec.cli}
    assert roots == {
        "query", "open", "corpora", "add", "doc", "doctor", "explain", "install", "uninstall",
        "hooks", "skills",
    }  # fmt: skip
    assert not {root for root in roots if root + "s" in roots}
    assert roots <= GROUPS


# ---------------------------------------------------------------------------------------------
# D298: `out` is a type, and a type is an import
# ---------------------------------------------------------------------------------------------


def _modules_loaded_by(statement: str) -> set[str]:
    """`sys.modules` after `statement` runs in a fresh interpreter.

    The same instrument `test_core_eager_surface.py` uses and for the same reason: once this
    process has imported `omniweave.route` for its own purposes, `sys.modules` can no longer say
    whether the surface pulled it in.
    """
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_importing_the_surface_does_not_load_the_router() -> None:
    """D298. `RouteDecision` is `route.explain`'s honest `out`, and naming it costs 72 modules.

    `QueryIn.route_hints` is already `RouteHints` under `TYPE_CHECKING` for this reason; an `out`
    has no such escape, because `ActionSpec.out` is an object rather than an annotation. This test
    is what makes the next writer notice before the cost ships.
    """
    loaded = _modules_loaded_by("import omniweave.surface")
    assert "omniweave.route" not in loaded


def test_importing_the_surface_opens_no_path_to_a_socket() -> None:
    """The concrete shape of the same cost: `omniweave.route` reaches the pricebook parser, which
    reaches `email`, which reaches `_socket`. A socket module on `ow query`'s import path is what
    this guard names, because a module count on its own reads as bookkeeping."""
    loaded = _modules_loaded_by("import omniweave.surface")
    assert loaded.isdisjoint({"_socket", "socket", "email", "csv", "decimal"})


def test_the_registry_still_probes_no_distribution() -> None:
    """10:300, asserted the only way it can be: nothing in the import asks what is installed."""
    loaded = _modules_loaded_by("import omniweave.surface")
    assert "importlib.metadata" not in loaded


# ---------------------------------------------------------------------------------------------
# The narrow inputs
# ---------------------------------------------------------------------------------------------


def test_the_field_order_of_each_narrow_input_is_the_published_order() -> None:
    """10:231: schema properties in declaration order, so reordering a field is a wire change."""
    assert [f.name for f in fields(GridIn)] == ["ref", "corpus"]
    assert [f.name for f in fields(CoverageIn)] == ["corpus", "scope"]
    assert [f.name for f in fields(DiffIn)] == ["ref", "corpus", "from_gen", "to_gen"]
    assert [f.name for f in fields(DoctorIn)] == ["runtime"]
    assert [f.name for f in fields(ExplainIn)] == ["code"]


def test_no_narrow_input_declares_max_chars() -> None:
    """A character ceiling packs prose. Every narrow Action returns rows, and a row set cut at a
    character count would cut a row in half."""
    for name in NARROW_NAMES:
        assert "max_chars" not in {f.name for f in fields(ACTIONS[name].inp)}, name


def test_the_narrow_advanced_sets_are_the_fields_the_strip_may_hide() -> None:
    assert ACTIONS["doc.diff"].advanced == frozenset({"from_gen", "to_gen"})
    assert ACTIONS["doctor"].advanced == frozenset({"runtime"})
    assert ACTIONS["doc.grid"].advanced == frozenset()
    assert ACTIONS["corpus.coverage"].advanced == frozenset()
    assert ACTIONS["explain"].advanced == frozenset()


def test_every_narrow_input_is_a_frozen_slotted_dataclass() -> None:
    for name in NARROW_NAMES:
        inp = ACTIONS[name].inp
        assert inp.__dataclass_params__.frozen, name  # type: ignore[attr-defined]
        assert getattr(inp, "__slots__", None) is not None, name


def test_two_actions_need_no_corpus_and_both_reasons_are_stated() -> None:
    """`ow explain` reads `codes.toml`, which is repository data; `ow doctor` reads the
    deployment. Neither opens a store, so both answer before the first `ow add`. `install` and
    `uninstall` wire agent hosts and open no store either (10:1469: two verbs, two receipts), and
    nor do the two `ow skills` verbs, which copy bundles between directories."""
    without_corpus = sorted(
        name for name, spec in ACTIONS.items() if "corpus" not in {f.name for f in fields(spec.inp)}
    )
    assert without_corpus == [
        "doctor", "explain", "hooks.check", "install", "skills.check", "skills.hash",
        "skills.install", "skills.ls", "skills.remove", "skills.verify", "uninstall",
    ]  # fmt: skip


# ---------------------------------------------------------------------------------------------
# The three report types 18 section 1.4 specifies
# ---------------------------------------------------------------------------------------------


def test_doctor_report_is_18_737s_fields_in_order() -> None:
    assert [f.name for f in fields(DoctorReport)] == [
        "ok",
        "warned",
        "failed",
        "config_sources",
        "config_digest",
        "semantic_digest",
    ]


def test_doctor_finding_is_18_745s_fields_in_order() -> None:
    assert [f.name for f in fields(DoctorFinding)] == ["check", "detail", "severity", "fix"]


def test_code_row_is_18_751s_fields_in_order() -> None:
    assert [f.name for f in fields(CodeRow)] == [
        "numeric",
        "symbol",
        "meaning",
        "fix",
        "owner_doc",
    ]


def test_a_doctor_report_carries_three_disjoint_tuples() -> None:
    """Three and not one with a severity filter: `failed` being non-empty IS the exit code."""
    warn = DoctorFinding(check="pdfium", detail="not importable", severity="warning", fix="uv sync")
    report = DoctorReport(
        ok=(),
        warned=(warn,),
        failed=(),
        config_sources={"serve.profile": "omniweave.toml"},
        config_digest="0" * 64,
        semantic_digest="1" * 64,
    )
    assert report.warned == (warn,)
    assert report.failed == ()
    assert report.config_sources["serve.profile"] == "omniweave.toml"


def test_doctor_severities_is_not_gap_severities() -> None:
    """D297. Two closed vocabularies that differ in one member, and the member is the weakest one:
    a `Gap` rolls up facts that were recorded (`info`), a `DoctorFinding` is a probe that returned
    nothing to do (`ok`). Folding them would make one member unspellable on each side."""
    assert SEVERITIES == ("info", "warning", "error")
    assert DOCTOR_SEVERITIES == ("ok", "warning", "error")
    assert set(SEVERITIES) ^ set(DOCTOR_SEVERITIES) == {"info", "ok"}


def test_a_code_row_carries_both_spellings_of_one_register_entry() -> None:
    """10:1438: `ow explain` accepts either, so the row it returns names both."""
    row = CodeRow(
        numeric="OW-A-028",
        symbol="OW_SURFACE_REGISTRY_INVALID",
        meaning="the Action registry failed its own checks at import",
        fix="fix every row named in the message",
        owner_doc="10-interfaces.md",
    )
    assert row.numeric.startswith("OW-")
    assert row.symbol.startswith("OW_")
    assert row.owner_doc.endswith(".md")


def test_the_three_new_report_types_are_reachable_from_the_sdk_root() -> None:
    """18:149: `omniweave.sdk` is the module, so a caller never imports `reports` by name."""
    assert sdk_root.DoctorReport is DoctorReport
    assert sdk_root.DoctorFinding is DoctorFinding
    assert sdk_root.CodeRow is CodeRow
    assert {"CodeRow", "DoctorFinding", "DoctorReport"} <= set(sdk_root.__all__)


# ---------------------------------------------------------------------------------------------
# The CLI roster
# ---------------------------------------------------------------------------------------------


def test_the_roster_carries_exactly_the_declared_roots() -> None:
    """A root with no entry validates nothing; an entry under no root is a command nobody types."""
    assert set(CLI_ROSTER) == GROUPS
    assert len(CLI_ROSTER) == 43


def test_every_entry_is_sorted_and_free_of_duplicates() -> None:
    """10:229 makes the generator pure -- no unsorted iteration -- and this is an input."""
    for root, verbs in CLI_ROSTER.items():
        assert list(verbs) == sorted(set(verbs)), root


def test_cli_free_names_only_rostered_roots() -> None:
    assert set(CLI_ROSTER) >= CLI_FREE


def test_the_two_exception_registers_are_disjoint() -> None:
    """`absent` and `unrostered` are opposite claims about one spelling."""
    assert not set(CLI_ABSENT) & set(CLI_UNROSTERED)


def test_no_exception_row_is_also_a_rostered_spelling() -> None:
    """A spelling registered as missing and carried as a verb is the register describing a surface
    that moved out from under it."""
    for spelling in (*CLI_ABSENT, *CLI_UNROSTERED):
        assert resolve_cli(spelling) in {"absent", "unrostered"}, spelling


def test_the_shipped_registers_reconcile() -> None:
    assert _cli_roster_failures(ACTIONS) == ()


@pytest.mark.parametrize(
    ("spelling", "status"),
    [
        (("query",), "bare"),
        (("doctor",), "bare"),
        (("doc", "grid"), "verb"),
        (("store", "export"), "verb"),
        (("store", "export", "parquet"), "verb"),
        (("graph", "merge", "e412", "e997"), "verb"),
        (("open", "d7"), "argument"),
        (("hook", "prompt"), "argument"),
        (("store", "rebalance"), "absent"),
        (("export",), "absent"),
        (("search",), "absent"),
        (("resume",), "unrostered"),
        (("plan", "lint"), "unrostered"),
        (("bench", "answer"), "unrostered"),
        (("frobnicate",), "no-such-root"),
        (("store", "reshard"), "no-such-verb"),
        (("doctor", "deeply"), "no-such-verb"),
        (("drivers", "check", "omniweave-pdf"), "no-such-verb"),
        ((), "no-such-root"),
    ],
)
def test_resolve_cli_answers_the_grammar(spelling: tuple[str, ...], status: str) -> None:
    """10:1413's grammar, one row per shape it admits and one per shape it refuses.

    `ow drivers check omniweave-pdf` is the row worth reading: `check` IS a `drivers` verb, and the
    spelling still fails because `drivers` is not in `CLI_FREE`. A root that takes a third word has
    to say so, or the roster cannot tell an argument from a verb somebody invented.
    """
    assert resolve_cli(spelling) == status


def test_the_registers_are_consulted_longest_first() -> None:
    """The one ordering bug this resolver can have, pinned.

    `store` is in `CLI_FREE` and has a non-empty roster, so a lookup that tried the root before the
    spelling would read `rebalance` as an argument -- and 18:3319 requires that exact name never to
    resolve, because 11 section 8.6 uses it as the worked example of one that does not.
    """
    assert resolve_cli(("store", "rebalance")) == "absent"
    assert "rebalance" not in CLI_ROSTER["store"]
    assert "store" in CLI_FREE


def test_resolve_cli_is_the_only_reader_of_the_two_word_width() -> None:
    """`ROOT_AND_VERB` is two facts that happen to be one integer, so it is named once."""
    assert registry_module.ROOT_AND_VERB == 2
    assert max(len(spelling) for spelling in (*CLI_ABSENT, *CLI_UNROSTERED)) <= 2


def test_every_shipped_row_resolves_to_a_spelling_the_generator_can_emit() -> None:
    for name, spec in ACTIONS.items():
        assert resolve_cli(spec.cli) in {"verb", "bare"}, name


def test_the_unrostered_cli_count_is_the_distance_to_the_registry() -> None:
    """10:857's *"roughly 110 further Actions"*, minus what has landed, plus what it undercounts.

    140 rather than 110, and the gap is D293's: the roster is transcribed from the plan's own
    tables and usage rather than from a numeral, and a numeral is a second copy of an enumeration.
    """
    waiting = _unrostered_cli(ACTIONS)
    assert len(waiting) == 140
    have = {spec.cli for spec in ACTIONS.values()}
    assert not set(waiting) & have
    assert len(waiting) + len(have) == sum(max(1, len(v)) for v in CLI_ROSTER.values())


def test_a_root_with_no_verbs_contributes_exactly_one_spelling() -> None:
    """`ow doctor` is a command; `ow doctor <verb>` is not a shape this grammar has."""
    waiting = set(_unrostered_cli(ACTIONS))
    assert ("top",) in waiting
    assert not any(spelling[0] == "top" and len(spelling) > 1 for spelling in waiting)


def test_five_rostered_roots_are_below_the_arity_the_grammar_requires() -> None:
    """D306. 10:1413: *"a group only at three or more verbs"*, and 18:918 prints five that are not.

    Reported by a test rather than by a check, because every one of the five is printed with
    exactly those verbs by the command surface -- so the grammar and the roster disagree in the
    plan, and a raise here would make the disagreement unimportable rather than visible.
    """
    thin = sorted(root for root, verbs in CLI_ROSTER.items() if 0 < len(verbs) < 3)
    assert thin == ["cache", "hooks", "schema", "targets", "test"]


def test_the_store_roster_is_the_one_open_question_5_asks_for() -> None:
    """18:948's *"at least twenty-six distinct `ow store <verb>` spellings"*, against 20."""
    assert len(CLI_ROSTER["store"]) == 24
    assert {"export", "repair", "verify", "redact", "rekey", "gc"} <= set(CLI_ROSTER["store"])
    assert "rebalance" not in CLI_ROSTER["store"]


def test_the_graph_roster_is_18s_sixteen_and_four_of_them_are_charter_only() -> None:
    """18's Open question 6: `cluster`, `converge`, `diff`, `report` are nowhere else."""
    assert len(CLI_ROSTER["graph"]) == 16
    assert {"cluster", "converge", "diff", "report"} <= set(CLI_ROSTER["graph"])
    assert {"merge", "merges"} <= set(CLI_ROSTER["graph"])


def test_out_carries_the_full_profile_action_and_not_the_verb_nothing_writes() -> None:
    """`list` is 10:820's `out.list`; `project` is printed by 18:918 and invoked nowhere; `preview`
    is invoked twice and printed nowhere, which is why it is unrostered rather than rostered."""
    assert "list" in CLI_ROSTER["out"]
    assert "project" in CLI_ROSTER["out"]
    assert "preview" not in CLI_ROSTER["out"]
    assert ("out", "preview") in CLI_UNROSTERED


def test_the_human_only_five_all_have_a_rostered_cli_spelling() -> None:
    """D291's five are CLI-only, so the roster is where they have to be reachable."""
    assert "remove" in CLI_ROSTER["skills"]
    assert "remove" in CLI_ROSTER["targets"]
    assert "promote" in CLI_ROSTER["route"]
    assert "rm" in CLI_ROSTER["store"]
    assert CLI_ROSTER["uninstall"] == ()


# ---------------------------------------------------------------------------------------------
# `_cli_roster_failures`: the six clauses
# ---------------------------------------------------------------------------------------------


def test_cli_clause_1_a_root_with_no_entry_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    short = {root: verbs for root, verbs in CLI_ROSTER.items() if root != "top"}
    monkeypatch.setattr(registry_module, "CLI_ROSTER", short)
    assert any("no entry for the declared root 'top'" in x for x in _cli_roster_failures({}))


def test_cli_clause_1_an_entry_under_no_root_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "CLI_ROSTER", {**CLI_ROSTER, "frobnicate": ()})
    assert any("'frobnicate' is not a declared root" in x for x in _cli_roster_failures({}))


def test_cli_clause_2_an_unsorted_entry_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "CLI_ROSTER", {**CLI_ROSTER, "queue": ("status", "retry")})
    assert any("is not sorted and unique" in x for x in _cli_roster_failures({}))


def test_cli_clause_3_a_free_root_that_is_not_rostered_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_module, "CLI_FREE", CLI_FREE | {"frobnicate"})
    assert any("CLI_FREE names 'frobnicate'" in x for x in _cli_roster_failures({}))


def test_cli_clause_4_an_exception_row_that_became_a_verb_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure both exception registers exist to make impossible."""
    monkeypatch.setattr(
        registry_module, "CLI_ABSENT", {("store", "verify"): "a row that is also a rostered verb"}
    )
    assert any("which CLI_ROSTER also carries" in x for x in _cli_roster_failures({}))


def test_cli_clause_5_a_spelling_in_both_registers_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_module, "CLI_ABSENT", {("resume",): "absent"})
    monkeypatch.setattr(registry_module, "CLI_UNROSTERED", {("resume",): "unrostered"})
    assert any("both absent and unrostered" in x for x in _cli_roster_failures({}))


def test_cli_clause_6_a_row_whose_cli_is_data_is_reported() -> None:
    """An Action spelled `ow open <something>` would be a row the generator cannot subparse."""
    bad = _spec(name="a", mcp_name="ow_a", cli=("open", "d7"))
    assert any("resolves argument" in line for line in _cli_roster_failures(_mapping(bad)))
