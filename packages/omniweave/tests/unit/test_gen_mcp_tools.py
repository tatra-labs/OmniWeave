"""Artefact 1: `schema/mcp-tools-v1.json`. 10 section 2.3 row 1; 18 section 3.

Eight of the assertions here are the plan's own measurements -- 608, 334, 481 and 303 description
characters and 411, 258, 189 and 173 full tokens, 10:336 -- and they are exact rather than bounded,
because the table prints them as figures. Six of the eight are reproduced by what ships; the two
that are not both belong to `ow_corpora`, whose printed object omits the annotation key 10:216
requires of every tool, and they carry a **strict xfail** with the arithmetic in the reason. That is
D1's standing treatment in this repository: transcribe the plan's number, fail where it fails, and
let `xfail_strict` turn the amendment into an XPASS that breaks the build.

The token assertions need `tiktoken`, which is a dev dependency and never a runtime one (10:2585),
and its encoding table is fetched on first use. Both conditions are handled by `_encoding()` rather
than by a module-level import, so a checkout without the table runs every other test in this file.
"""

from __future__ import annotations

import ast
import json
import subprocess  # noqa: TID251 -- an import set is observable only from a fresh interpreter.
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

import omniweave.gen.mcp_tools as mcp_tools_module
import pytest
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.mcp_tools import (
    ANNOTATIONS,
    DESCRIPTIONS,
    INPUT_SCHEMAS,
    MAX_RUNG_MEMBERS,
    OUTPUT_SCHEMAS,
    PUBLISHED,
    STEERING,
    _published_failures,
    description,
    hints,
    render,
    tool,
    tools,
)
from omniweave.route.decision import RouteHints
from omniweave.route.rung import Rung
from omniweave.surface import ACTIONS, listed
from omniweave.surface.inputs import (
    CONTEXT_DEFAULT,
    CONTEXT_MAX,
    CONTEXT_MIN,
    CORPORA_DETAILS,
    HARD_CEILING,
    MAX_CHARS_MIN,
    QUERY_MAX_CHARS,
    REF_MAX,
    SOURCE_MAX,
    WANTS,
)
from omniweave.surface.schema import CORPUS_SCOPED, compact, with_required_corpus
from omniweave_core.answer.budget import HARD_CEILING as PACKER_CEILING

PLAN_DESCRIPTION_CHARS = {"ow_query": 608, "ow_open": 334, "ow_corpora": 481, "ow_add": 303}
"""10:336's `description chars` column, and its 1,726 total."""

PLAN_FULL_TOKENS = {"ow_query": 411, "ow_open": 258, "ow_corpora": 189, "ow_add": 173}
PLAN_COMPACT_TOKENS = {"ow_query": 289, "ow_open": 210, "ow_corpora": 189, "ow_add": 162}
"""10:336's two token columns. `ow_corpora`'s two figures are the ones D316 moves."""

SHIPPED_FULL_TOKENS = {"ow_query": 411, "ow_open": 258, "ow_corpora": 195, "ow_add": 173}
SHIPPED_COMPACT_TOKENS = {"ow_query": 289, "ow_open": 210, "ow_corpora": 195, "ow_add": 162}
"""What the generator emits, with `destructiveHint` present on all four tools as 10:216 requires."""

LADDER = ("ow_query", "ow_open", "ow_corpora", "ow_add")
"""The decision ladder, which is artefact 2's order and is deliberately NOT this artefact's."""


def _payload() -> list[dict[str, Any]]:
    return json.loads(render().decode("utf-8"))


def _by_name() -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in _payload()}


def _encoding() -> Any:
    """10:321's tokenizer, or a skip. `tiktoken` is a dev dependency and fetches its table."""
    tiktoken = pytest.importorskip("tiktoken")
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # any failure here means "no table", which is not a defect
        pytest.skip(f"cl100k_base is unavailable offline: {exc}")


def _tokens(obj: dict[str, Any]) -> int:
    """10:321's recipe, verbatim.

    `len(enc.encode(json.dumps(tool, separators=(",",":"), ensure_ascii=False)))`.
    """
    return len(_encoding().encode(json.dumps(obj, separators=(",", ":"), ensure_ascii=False)))


# ---------------------------------------------------------------------------------------------
# The roster: who is published, and in what order
# ---------------------------------------------------------------------------------------------


def test_the_payload_is_the_four_front_door_tools() -> None:
    assert set(_by_name()) == {ACTIONS[name].mcp_name for name in listed("default")}
    assert set(_by_name()) == PUBLISHED


def test_the_rendered_bytes_are_the_tool_objects_the_builder_returns() -> None:
    """`render()` serializes `tools()` and adds nothing: JSON is the only transform between
    them."""
    assert _payload() == list(tools())


def test_the_payload_is_sorted_by_action_name_and_not_by_the_ladder() -> None:
    """D312's question asked of the other artefact, and answered the other way.

    10:225 sorts Actions by `name`; artefact 2 prints the decision ladder because 10:874 prints
    that artefact whole and five sites repeat its order. Nothing prints this one whole, so the rule
    applies unamended -- and the test asserts the two orders differ, so a future reconciliation
    cannot quietly make both true by reordering one of them.
    """
    emitted = [entry["name"] for entry in _payload()]
    assert emitted == ["ow_add", "ow_corpora", "ow_open", "ow_query"]
    assert emitted == sorted(emitted)
    assert tuple(emitted) != LADDER


def test_the_five_narrow_rows_that_landed_are_not_published_yet() -> None:
    """W7.1b's `full`-profile Actions have an `mcp_name`, an `inp` and no published `inputSchema`.

    No document prints one: 10:807's roster gives each row one line of prose and 18 section 3
    prints objects for the front door only. Reported by `unpublished()` and pinned here, so the
    distance to a complete artefact is a number rather than a memory.
    """
    assert mcp_tools_module.unpublished() == (
        "ow_coverage",
        "ow_diff",
        "ow_doctor",
        "ow_explain",
        "ow_grid",
        "ow_hooks_check",
        "ow_skills_check",
        "ow_skills_hash",
        "ow_skills_ls",
        "ow_skills_verify",
    )


def test_a_front_door_tool_with_nothing_published_fails_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clause 5. A fifth listed tool is a build failure, not a three-tool file."""
    spec = ACTIONS["doctor"]
    listed_everywhere = frozenset({"default", "full"})
    widened = {
        **ACTIONS,
        "doctor": type(spec)(**{**vars_of(spec), "listed_in": listed_everywhere}),
    }
    monkeypatch.setattr(mcp_tools_module, "ACTIONS", widened)
    failures = _published_failures()
    assert any("ow_doctor" in line and "nothing is published" in line for line in failures)


def vars_of(spec: Any) -> dict[str, Any]:
    """`dataclasses.asdict` recurses into the `inp`/`out` types; this does not."""
    return {field.name: getattr(spec, field.name) for field in fields(spec)}


def test_prose_for_a_tool_no_action_declares_fails_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clause 1: LEANN's manifest defect written the other way round."""
    monkeypatch.setattr(mcp_tools_module, "DESCRIPTIONS", {**DESCRIPTIONS, "ow_invented": "prose"})
    assert any("no Action declares that mcp_name" in line for line in _published_failures())


def test_tool_refuses_an_action_with_nothing_published() -> None:
    with pytest.raises(KeyError, match="nothing is published"):
        tool(ACTIONS["doctor"])


# ---------------------------------------------------------------------------------------------
# The descriptions, and the eight figures 10:336 prints
# ---------------------------------------------------------------------------------------------


def test_each_description_is_the_length_the_plan_measured() -> None:
    for name, expected in PLAN_DESCRIPTION_CHARS.items():
        assert len(DESCRIPTIONS[name]) == expected, name


def test_the_descriptions_total_the_1726_characters_the_plan_counted() -> None:
    assert sum(len(body) for body in DESCRIPTIONS.values()) == 1726


def test_no_description_is_derivable_from_the_catalog_row_it_is_said_to_come_from() -> None:
    """D317. 10:208 names `summary`, `decision` and `example` and no `description` field exists.

    Check 7 caps `summary` at 160 characters and `decision` at 90, so the two together cannot
    reach 608 -- the gap is not a matter of formatting. Asserted as an inequality rather than as
    prose so the day `ActionSpec` grows a `description` field, this test is what a reader is sent
    to.
    """
    for name in PUBLISHED:
        spec = next(s for s in ACTIONS.values() if s.mcp_name == name)
        assert len(DESCRIPTIONS[name]) > len(spec.summary) + len(spec.decision)
        assert spec.summary not in DESCRIPTIONS[name]
        assert spec.decision not in DESCRIPTIONS[name]


def test_the_em_dash_survives_into_the_committed_bytes() -> None:
    """10:332: `ensure_ascii=True` would emit `—` as a six-character escape, *"inflating the count
    by an artefact of the serializer rather than of the wire."*"""
    raw = render()
    assert raw.count("—".encode()) > 0
    assert raw.count(b"\\u2014") == 0
    assert raw.count("·".encode()) > 0


def test_an_unlisted_tools_description_is_its_summary_plus_the_steering_clause() -> None:
    """10:851, *"generated, not written"*; 18:1373, *"so steering survives re-listing"*."""
    spec = ACTIONS["doctor"]
    built = description(spec)
    assert built == f"{spec.summary}. {STEERING}"
    assert built.endswith(STEERING)


def test_no_front_door_description_carries_the_steering_clause() -> None:
    """The clause points at `ow_query`; appending it to `ow_query` would be a tool citing itself."""
    for name in PUBLISHED:
        assert STEERING not in DESCRIPTIONS[name], name


# ---------------------------------------------------------------------------------------------
# The annotations: four keys, always
# ---------------------------------------------------------------------------------------------


def test_every_tool_carries_all_four_annotation_keys() -> None:
    """10:216. A missing key would mean the generator branched."""
    for entry in _payload():
        assert list(entry["annotations"]) == [key for key, _ in ANNOTATIONS], entry["name"]


def test_the_annotations_are_the_registry_booleans_and_nothing_else() -> None:
    for spec in ACTIONS.values():
        if spec.mcp_name not in PUBLISHED:
            continue
        assert hints(spec) == {
            "readOnlyHint": spec.read_only,
            "destructiveHint": spec.destructive,
            "idempotentHint": spec.idempotent,
            "openWorldHint": spec.open_world,
        }


def test_destructive_hint_is_false_for_all_four_listed_tools() -> None:
    """10:161, `ow_add` included: *"its writes append documents and index rows and never remove
    indexed content, so a host that reads `destructiveHint` to decide whether to prompt should not
    prompt for an ingest."*"""
    assert [entry["annotations"]["destructiveHint"] for entry in _payload()] == [False] * 4


def test_ow_corpora_carries_the_key_the_plans_printed_object_omits() -> None:
    """D316. 18:1345 prints three annotation keys for `ow_corpora`; 10:216 requires four, and
    10:221 says why it is `destructiveHint` in particular: *"MCP reads an absent `destructiveHint`
    as `true`"*, which would publish the protocol's most alarming annotation on the safest tool in
    the set."""
    assert _by_name()["ow_corpora"]["annotations"]["destructiveHint"] is False


def test_the_annotation_order_is_the_one_three_of_the_four_printed_objects_use() -> None:
    assert [key for key, _ in ANNOTATIONS] == [
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
    ]


# ---------------------------------------------------------------------------------------------
# The input schemas, bound to the declarations rather than beside them
# ---------------------------------------------------------------------------------------------


def test_every_published_property_list_is_its_input_types_field_order() -> None:
    """10:226, *"schema properties in declaration order (which is `dataclasses.fields` order)"*."""
    for name, schema in INPUT_SCHEMAS.items():
        spec = next(s for s in ACTIONS.values() if s.mcp_name == name)
        assert tuple(schema["properties"]) == tuple(f.name for f in fields(spec.inp)), name


def test_a_field_added_to_an_input_type_without_publishing_it_fails_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trimmed = dict(INPUT_SCHEMAS["ow_corpora"])
    trimmed["properties"] = {"corpus": {"type": "string"}}
    monkeypatch.setattr(mcp_tools_module, "INPUT_SCHEMAS", {**INPUT_SCHEMAS, "ow_corpora": trimmed})
    assert any("in declaration order" in line for line in _published_failures())


def test_every_published_bound_is_the_constant_and_not_a_copy_of_it() -> None:
    """INV-21 over eight numbers: the generator prints what the handler enforces, by identity."""
    query = INPUT_SCHEMAS["ow_query"]["properties"]
    open_ = INPUT_SCHEMAS["ow_open"]["properties"]
    add = INPUT_SCHEMAS["ow_add"]["properties"]
    assert query["query"]["maxLength"] == QUERY_MAX_CHARS
    assert query["max_chars"]["minimum"] == MAX_CHARS_MIN
    assert query["max_chars"]["maximum"] == HARD_CEILING
    assert query["want"]["enum"] == list(WANTS)
    assert query["want"]["default"] == WANTS[0]
    assert open_["ref"]["oneOf"][1]["maxItems"] == REF_MAX
    assert open_["context"]["minimum"] == CONTEXT_MIN
    assert open_["context"]["maximum"] == CONTEXT_MAX
    assert open_["context"]["default"] == CONTEXT_DEFAULT
    assert add["source"]["oneOf"][1]["maxItems"] == SOURCE_MAX
    detail = INPUT_SCHEMAS["ow_corpora"]["properties"]["detail"]
    assert detail["enum"] == list(CORPORA_DETAILS)
    assert detail["default"] == CORPORA_DETAILS[0]


def test_the_published_ceiling_is_the_packers_own_object() -> None:
    """18:1729, *"one ceiling for every tool"*, reaching the schema without being re-spelled."""
    assert INPUT_SCHEMAS["ow_query"]["properties"]["max_chars"]["maximum"] is PACKER_CEILING
    assert INPUT_SCHEMAS["ow_open"]["properties"]["max_chars"]["maximum"] is PACKER_CEILING


def test_max_rung_is_the_rung_ladders_member_names_lower_cased() -> None:
    """The one name this module copies, bound by a test rather than by an import.

    18:1300: *"the wire value is the lower-case member name and one byte-diff-gated generator
    cannot emit two casing conventions without a special case nobody declared."* Importing `Rung`
    costs the generator 47 modules and a socket, which is D298's charge one package over.
    """
    assert tuple(member.name.lower() for member in Rung) == MAX_RUNG_MEMBERS
    published = INPUT_SCHEMAS["ow_query"]["properties"]["route_hints"]["properties"]["max_rung"]
    assert published["enum"] == list(MAX_RUNG_MEMBERS)


def test_route_hints_publishes_three_of_route_hints_five_fields_in_order() -> None:
    """18:1276's narrowing, which the generator performs and the type does not declare.

    `prefer_capability` is a driver-selection hint with no agent-facing meaning and `schema` is
    struck from this surface by name (18:1322), so the published object is a restriction of a type
    whose safety property is already its field list (05:2019).
    """
    declared = [field.name for field in fields(RouteHints)]
    published = list(INPUT_SCHEMAS["ow_query"]["properties"]["route_hints"]["properties"])
    assert published == ["lane", "max_rung", "deadline_ms"]
    assert [name for name in declared if name in published] == published
    assert set(declared) - set(published) == {"prefer_capability", "schema"}


def test_ow_corpora_declares_no_required_key_at_all() -> None:
    """Both of its parameters are optional, and an empty `required: []` is a different document."""
    assert "required" not in INPUT_SCHEMAS["ow_corpora"]
    assert "required" not in _by_name()["ow_corpora"]["inputSchema"]


def test_every_published_object_is_closed() -> None:
    """10:516: `additionalProperties: false` is the declaration, and it survives compaction."""
    for name, schema in INPUT_SCHEMAS.items():
        assert schema["additionalProperties"] is False, name


def test_the_shared_input_schemas_are_not_handed_out_by_reference() -> None:
    """`with_required_corpus` is documented as never mutating the shared array; neither does this.
    A caller that edited a tool object would otherwise edit the next render."""
    first = tool(ACTIONS["query"])
    first["inputSchema"]["properties"].pop("query")
    assert "query" in INPUT_SCHEMAS["ow_query"]["properties"]
    assert "query" in tool(ACTIONS["query"])["inputSchema"]["properties"]


# ---------------------------------------------------------------------------------------------
# `outputSchema`: declared for the row-shaped two, absent for the two that pack prose
# ---------------------------------------------------------------------------------------------


def test_the_two_prose_retrievers_declare_no_output_schema() -> None:
    """18:1315, and it is a measurement: a conforming structured result *"DOUBLES a 22,000-character
    answer"* in a host that also emits the serialized-JSON text block."""
    assert "outputSchema" not in _by_name()["ow_query"]
    assert "outputSchema" not in _by_name()["ow_open"]


def test_the_two_row_shaped_tools_ref_a_schema_file_that_exists() -> None:
    for name, target in OUTPUT_SCHEMAS.items():
        assert _by_name()[name]["outputSchema"] == {"$ref": target}
        assert (REPO_ROOT / target).is_file(), target


def test_open_out_v1_is_deliberately_not_an_output_schema() -> None:
    """18:1320: it is `ow open --render json`'s shape, not an MCP `outputSchema`."""
    assert (REPO_ROOT / "schema" / "open-out-v1.json").is_file()
    assert "schema/open-out-v1.json" not in OUTPUT_SCHEMAS.values()


def test_declaring_an_output_schema_for_a_prose_retriever_fails_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_tools_module,
        "OUTPUT_SCHEMAS",
        {**OUTPUT_SCHEMAS, "ow_query": "schema/answer-v1.json"},
    )
    assert any("18:1315 pairs them" in line for line in _published_failures())


def test_the_key_order_puts_output_schema_before_input_schema() -> None:
    """18:1348's order. It changes no count worth measuring and every byte of a reviewer's diff."""
    assert list(_by_name()["ow_corpora"]) == [
        "name",
        "description",
        "annotations",
        "outputSchema",
        "inputSchema",
    ]
    assert list(_by_name()["ow_query"]) == ["name", "description", "annotations", "inputSchema"]


# ---------------------------------------------------------------------------------------------
# The measured payload: 10:336, recounted with 10:321's recipe
# ---------------------------------------------------------------------------------------------


def test_the_full_schema_column_is_what_the_generator_emits() -> None:
    assert {entry["name"]: _tokens(entry) for entry in _payload()} == SHIPPED_FULL_TOKENS


def test_the_compact_schema_column_is_what_the_generator_emits() -> None:
    assert {
        entry["name"]: _tokens(compact(entry)) for entry in _payload()
    } == SHIPPED_COMPACT_TOKENS


def test_the_two_profile_totals_are_the_ones_the_arithmetic_gives() -> None:
    """The measurement behind the xfails, asserted positively so the numbers are pinned."""
    payload = _payload()
    assert sum(_tokens(entry) for entry in payload) == 1037
    assert sum(_tokens(compact(entry)) for entry in payload) == 856


def test_the_promotion_still_costs_the_fifteen_tokens_the_plan_measured() -> None:
    """10:538's *"+15 tokens on the compact payload"* -- a delta, so D316's six do not touch it."""
    payload = _payload()
    base = sum(_tokens(compact(entry)) for entry in payload)
    promoted = sum(
        _tokens(
            with_required_corpus(compact(entry))
            if entry["name"] in CORPUS_SCOPED
            else compact(entry)
        )
        for entry in payload
    )
    assert promoted - base == 15


def test_three_of_the_four_tools_cost_exactly_what_the_plan_counted() -> None:
    """The transcription's strongest evidence: six of 10:336's eight figures, reproduced."""
    got_full = {entry["name"]: _tokens(entry) for entry in _payload()}
    got_compact = {entry["name"]: _tokens(compact(entry)) for entry in _payload()}
    for name in ("ow_query", "ow_open", "ow_add"):
        assert got_full[name] == PLAN_FULL_TOKENS[name], name
        assert got_compact[name] == PLAN_COMPACT_TOKENS[name], name


D316_REASON = (
    "D316. 18:1345 prints `ow_corpora` with three annotation keys and 10:216 requires four of "
    "every tool. Emitting `destructiveHint: false` costs 6 tokens, so `ow_corpora` is 195 in both "
    "columns rather than 189, and 10:2596's frozen `default_compact` 850, `default_full` 1031 and "
    "`default_compact_corpus_required` 865 become 856, 1037 and 871. These xfails land when "
    "10 section 3.1's table and the baseline are re-derived together."
)


@pytest.mark.xfail(strict=True, reason=D316_REASON)
def test_ow_corpora_costs_the_189_tokens_the_plan_counted() -> None:
    corpora = _by_name()["ow_corpora"]
    assert _tokens(corpora) == PLAN_FULL_TOKENS["ow_corpora"]


@pytest.mark.xfail(strict=True, reason=D316_REASON)
def test_the_default_profile_costs_the_850_tokens_the_baseline_freezes() -> None:
    assert sum(_tokens(compact(entry)) for entry in _payload()) == 850


@pytest.mark.xfail(strict=True, reason=D316_REASON)
def test_the_full_form_costs_the_1031_tokens_the_baseline_freezes() -> None:
    assert sum(_tokens(entry) for entry in _payload()) == 1031


def test_ow_corpora_is_still_unchanged_by_compaction() -> None:
    """10:353's reading survives D316 even though its numeral does not: the tool declares no
    `advanced` parameters, so the strip has nothing to take."""
    corpora = _by_name()["ow_corpora"]
    assert compact(corpora) == corpora
    assert ACTIONS["corpora"].advanced == frozenset()


def test_every_tool_is_under_the_700_token_per_tool_cap() -> None:
    """10:336's last column, which D316 does not come close to moving."""
    assert all(_tokens(entry) <= 700 for entry in _payload())


def test_the_default_surface_is_under_its_1900_token_ceiling() -> None:
    assert sum(_tokens(compact(entry)) for entry in _payload()) <= 1900


# ---------------------------------------------------------------------------------------------
# Compaction, over the objects that actually ship
# ---------------------------------------------------------------------------------------------


def test_compaction_strips_exactly_the_advanced_parameters() -> None:
    for entry in _payload():
        spec = next(s for s in ACTIONS.values() if s.mcp_name == entry["name"])
        survivors = set(compact(entry)["inputSchema"]["properties"])
        declared = set(entry["inputSchema"]["properties"])
        assert declared - survivors == set(spec.advanced), entry["name"]


def test_no_published_enum_reaches_the_demotion_threshold() -> None:
    """10:509's rule fires above 12 members; the largest published enum has seven."""
    sizes = [len(MAX_RUNG_MEMBERS), len(WANTS), len(CORPORA_DETAILS)]
    assert max(sizes) == 7
    for entry in _payload():
        assert compact(entry)["inputSchema"] == _strip(
            entry["inputSchema"],
            next(s for s in ACTIONS.values() if s.mcp_name == entry["name"]).advanced,
        ), entry["name"]


def _strip(schema: dict[str, Any], advanced: frozenset[str]) -> dict[str, Any]:
    """The strip with no demotion, so the test above compares against a second implementation."""
    out = {key: value for key, value in schema.items() if key != "properties"}
    out["properties"] = {
        key: value for key, value in schema["properties"].items() if key not in advanced
    }
    return {key: out[key] for key in schema}


def test_the_promotion_gives_corpus_a_required_slot_on_every_corpus_scoped_tool() -> None:
    for entry in _payload():
        if entry["name"] not in CORPUS_SCOPED:
            continue
        promoted = with_required_corpus(entry)
        assert "corpus" in promoted["inputSchema"]["required"], entry["name"]
        assert "corpus" not in entry["inputSchema"].get("required", []), entry["name"]


# ---------------------------------------------------------------------------------------------
# The bytes, and the purity that makes a byte diff mean something
# ---------------------------------------------------------------------------------------------


def test_the_committed_file_is_byte_for_byte_what_the_renderer_produces() -> None:
    committed = (REPO_ROOT / "schema" / "mcp-tools-v1.json").read_bytes()
    assert committed.replace(b"\r\n", b"\n") == render()


def test_the_render_is_utf8_with_no_bom_and_one_trailing_newline() -> None:
    """10:228, *"Output is `\\n`-terminated UTF-8 with no BOM"*."""
    raw = render()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"]\n")
    assert not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    raw.decode("utf-8")


def test_rendering_twice_gives_the_same_bytes() -> None:
    """The property a byte-diff gate rests on, asserted rather than assumed."""
    assert render() == render()


def test_the_renderer_reads_no_clock_no_environment_and_no_path() -> None:
    """10:224's ban, over the module that renders artefact 1.

    Read with `ast` rather than by importing and probing, because the property is about what the
    SOURCE may contain: a renderer that called `time.time()` once, in a branch no test reaches,
    would still make G25's byte-diff fail on the second run.
    """
    source = Path(mcp_tools_module.__file__).read_text(encoding="utf-8")
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert not roots & banned, roots & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module


def _modules_loaded_by(statement: str) -> set[str]:
    """`sys.modules` after `statement` runs in a fresh interpreter."""
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_the_generator_does_not_import_the_router_to_read_seven_strings() -> None:
    """D298's charge, one package over. `MAX_RUNG_MEMBERS` is spelled and bound by a test."""
    loaded = _modules_loaded_by("import omniweave.gen.mcp_tools")
    assert "omniweave.route" not in loaded
    assert loaded.isdisjoint({"_socket", "socket", "email"})
