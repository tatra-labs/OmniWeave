"""Artefact 5: `llms.txt`, the file G25 is named after. 10 section 11; 10:212; 00:851.

Three properties carry this module, and the first is the one the gate is named for.

**The manifest declares exactly the Actions the registry gives an `mcp_name`.** Not fewer, which is
LEANN's file -- two tools declared against a server defining four, *"two of them state-changing and
undeclared"* (00:587) -- and not more, which would send an agent at a tool that does not dispatch.
Both directions are asserted here and `_manifest_failures()` raises on either at import.

**Every mechanical fact is artefact 1's, not a second transcription.** The types, bounds, choice
sets and defaults come through `mcp_tools.INPUT_SCHEMAS`, so the manifest and `tools/list` cannot
disagree about what `max_chars` accepts; the tests below walk the published schema and demand each
bound in the corresponding line rather than trusting the renderer to have copied it.

**Every constant that could not be derived is bound to whatever else knows the same fact.** A pure
generator may not read `pyproject.toml`, `codes.toml` or an enum module (10:229), so the release
number, the eight section markers, the four verdict states and the five quote tiers are spelled in
the generator and pinned here -- `mcp_tools.MAX_RUNG_MEMBERS`'s pattern from W7.2b. The exit table
was the one with nothing to bind to and is no longer: W7.2f moved it to
`omniweave_core.errors.EXIT_CODES`, which is the home 18:996 gives it and which artefact 6 reads
too, so the test at the bottom that was a strict xfail is now an ordinary one. D329, then D332.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import fields
from pathlib import Path

import omniweave.gen.llms as llms_module
import pytest
from omniweave.gen.cli_tree import commands
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.instructions import SV2_MAX_CHARS
from omniweave.gen.llms import (
    RELEASE,
    SECTION_MARKERS,
    TYPES,
    VERDICTS,
    WIDTH,
    _manifest_failures,
    declared,
    render,
    unbounded,
)
from omniweave.gen.mcp_tools import INPUT_SCHEMAS, OUTPUT_SCHEMAS, unpublished
from omniweave.surface.inputs import HARD_CEILING
from omniweave.surface.registry import (
    ACTIONS,
    CLI_ROSTER,
    HUMAN_ONLY,
    PROFILES,
    ActionSpec,
    listed,
)
from omniweave_core.answer.render import SECTIONS
from omniweave_core.config import KEYS
from omniweave_core.errors import EXIT_CODES
from omniweave_core.model.enums import Quote
from omniweave_core.retrieve.verdict import VerdictState

MANIFEST = REPO_ROOT / "llms.txt"
PYPROJECT = REPO_ROOT / "packages" / "omniweave" / "pyproject.toml"


def _text() -> str:
    return render().decode("utf-8")


def _entries() -> dict[str, str]:
    """The manifest parsed back, which is 10:2431's claim made executable.

    *"flat, greppable, no parser needed -- one `example.<verb>` per lifecycle step."* A line that
    begins in column one and contains a colon opens an entry; a line that begins with two spaces
    continues the one before it. That is the whole grammar, and this is the whole parser.

    `note` appears four times under one key and the last wins here; `_notes()` reads them all.
    """
    out: dict[str, str] = {}
    key = ""
    for line in _text().splitlines():
        if not line or line.startswith("#"):
            key = ""
        elif line.startswith("  "):
            assert key, f"a continuation line with nothing to continue: {line!r}"
            out[key] = f"{out[key]} {line[2:]}"
        else:
            key, _, value = line.partition(": ")
            out[key] = value
    return out


def _notes() -> list[str]:
    return [line.partition(": ")[2] for line in _text().splitlines() if line.startswith("note: ")]


def _by_mcp_name() -> dict[str, ActionSpec]:
    return {spec.mcp_name: spec for spec in ACTIONS.values() if spec.mcp_name is not None}


# ---------------------------------------------------------------------------------------------
# The grammar, and the encoding a byte-diff gate rests on
# ---------------------------------------------------------------------------------------------


def test_the_committed_file_is_what_the_generator_produces() -> None:
    """G25's byte diff for artefact 5, CRLF-normalised on both sides as 11:490 requires."""
    assert MANIFEST.read_bytes().replace(b"\r\n", b"\n") == render()


def test_the_output_is_newline_terminated_utf8_with_no_bom() -> None:
    """10:232, which every renderer here honours and only the renderer can."""
    payload = render()
    assert payload.endswith(b"\n")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    payload.decode("utf-8")


def test_no_line_is_wider_than_the_file_it_is_modelled_on() -> None:
    assert max(len(line) for line in _text().splitlines()) <= WIDTH


def test_every_line_opens_an_entry_continues_one_or_is_a_comment() -> None:
    """The grammar 10:2431 calls *"no parser needed"*, asserted line by line.

    A third shape would not be a cosmetic defect: a reader that split on the first colon of a
    column-one line and appended every two-space line would silently mis-attribute it.
    """
    for line in _text().splitlines():
        if not line or line.startswith(("#", "  ")):
            continue
        assert ": " in line, line
        assert not line[0].isspace(), line


def test_rendering_twice_gives_the_same_bytes() -> None:
    assert render() == render()


def test_the_renderer_reads_no_clock_no_environment_and_no_path() -> None:
    """10:224's ban, over the module that renders artefact 5.

    Read with `ast` for `mcp_tools.py`'s reason: the property is about what the SOURCE may contain,
    and one `time.time()` in a branch no test reaches would still make the byte diff fail on the
    second run. `pathlib` is in the banned set even though a test module three lines up uses it --
    the ban is over the generator, not over its tests.
    """
    source = Path(llms_module.__file__).read_text(encoding="utf-8")
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert not roots & banned, roots & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module


# ---------------------------------------------------------------------------------------------
# LEANN's defect, in both directions
# ---------------------------------------------------------------------------------------------


def test_every_action_with_an_mcp_name_has_a_block() -> None:
    """The half LEANN's file gets wrong. 00:851 makes it G25's named defect."""
    entries = _entries()
    for name in _by_mcp_name():
        assert f"mcp.tool.{name}.action" in entries, name


def test_every_block_names_an_action_the_registry_declares() -> None:
    """The other half. A manifest naming a tool nothing dispatches is the same lie inverted."""
    blocks = {line.split(".")[2] for line in _text().splitlines() if line.startswith("mcp.tool.")}
    assert blocks == set(_by_mcp_name())


def test_the_roster_is_every_named_action_and_not_only_the_listed_four() -> None:
    """10:212's source column is *"every Action with an `mcp_name`"*, which is fourteen, not four.

    The four in `default` are what an MCP client sees in `tools/list`; the file exists for an agent
    that has no MCP client at all, and `mcp.listed_note`'s *"READ THIS BEFORE ASSUMING A TOOL DOES
    NOT EXIST"* is only true of a file that lists the ones a profile does not.
    """
    entries = _entries()
    assert entries["mcp.tools"].split(", ") == list(declared())
    assert len(declared()) == 14
    assert set(entries["mcp.profile.default"].split(", ")) < set(declared())


def test_a_manifest_that_omitted_a_tool_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """LEANN's file, built on purpose, refused by the check that would have caught it."""
    monkeypatch.setattr(llms_module, "declared", lambda: ("ow_query", "ow_open"))
    findings = _manifest_failures()
    assert any("no block is rendered for it" in line for line in findings)
    assert any(line.startswith("ow_add:") for line in findings)


def test_a_manifest_that_invented_a_tool_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llms_module, "declared", lambda: (*declared(), "ow_nonesuch"))
    assert any("no Action declares this mcp_name" in line for line in _manifest_failures())


def test_the_five_human_only_actions_are_named_and_marked_unreachable() -> None:
    """`mcp_name = None` is a structural marker, not a denylist (10:66), and the file says so."""
    entries = _entries()
    assert entries["mcp.human_only"].split(", ") == sorted(HUMAN_ONLY)
    assert "unreachable from any agent surface" in entries["mcp.human_only_note"]
    assert not set(HUMAN_ONLY) & {str(spec.name) for spec in _by_mcp_name().values()}


# ---------------------------------------------------------------------------------------------
# Agreement with artefact 1
# ---------------------------------------------------------------------------------------------


def test_every_published_bound_reaches_the_manifest() -> None:
    """The property that makes one registry worth having: two artefacts, one set of numbers.

    Walked from `INPUT_SCHEMAS` rather than from a list written here, so a bound added to artefact
    1 and not published here fails without anyone remembering to add a case.
    """
    entries = _entries()
    for mcp_name, schema in INPUT_SCHEMAS.items():
        for field_name, published in schema["properties"].items():
            line = entries[f"mcp.tool.{mcp_name}.input.{field_name}"]
            for branch in (published, *published.get("oneOf", ())):
                for key, word in (
                    ("minimum", "min"),
                    ("maximum", "max"),
                    ("maxLength", "max_length"),
                    ("maxItems", "max_items"),
                ):
                    if key in branch:
                        assert f"{word}={branch[key]}" in line, (mcp_name, field_name, key)
            if "enum" in published:
                assert "enum=" + "|".join(published["enum"]) in line


def test_the_three_route_hints_bounds_are_published_one_level_down() -> None:
    """A nested bound an agent cannot see is a refusal it cannot anticipate."""
    entries = _entries()
    nested = INPUT_SCHEMAS["ow_query"]["properties"]["route_hints"]["properties"]
    for field_name in nested:
        assert f"mcp.tool.ow_query.input.route_hints.{field_name}" in entries
    assert "min=100, max=120000" in entries["mcp.tool.ow_query.input.route_hints.deadline_ms"]


def test_the_two_output_schemas_are_the_two_artefact_1_declares() -> None:
    entries = _entries()
    for mcp_name, path in OUTPUT_SCHEMAS.items():
        assert entries[f"mcp.tool.{mcp_name}.output"] == path
    for mcp_name in ("ow_query", "ow_open"):
        assert entries[f"mcp.tool.{mcp_name}.output"] == (
            f"text/markdown, one content block, <= {HARD_CEILING} chars, no outputSchema"
        )


def test_the_input_fields_are_the_dataclass_fields_in_declaration_order() -> None:
    """10:226 makes the order load-bearing, and `dataclasses.fields` is the order that fixes
    it."""
    lines = _text().splitlines()
    for mcp_name, spec in _by_mcp_name().items():
        prefix = f"mcp.tool.{mcp_name}.input."
        published = [
            line[len(prefix) :].partition(":")[0]
            for line in lines
            if line.startswith(prefix) and line[len(prefix) :].partition(":")[0].count(".") == 0
        ]
        assert published == [field.name for field in fields(spec.inp)], mcp_name


def test_the_five_tools_without_a_published_schema_are_named_as_such() -> None:
    """`unbounded()` is a scheduling distance, reported rather than raised. D300's thirteen."""
    assert unbounded() == unpublished()
    assert _entries()["mcp.tools.unbounded"].startswith(", ".join(unbounded()))
    assert "no bounds" in _entries()["mcp.tools.unbounded"]


def test_the_state_changing_bit_is_not_read_only_for_every_tool() -> None:
    """10:2573's first of four assertions, which is the one LEANN's file cannot make."""
    entries = _entries()
    for mcp_name, spec in _by_mcp_name().items():
        want = "false" if spec.read_only else "true"
        assert entries[f"mcp.tool.{mcp_name}.state_changing"] == want, mcp_name
    assert entries["mcp.tool.ow_add.state_changing"] == "true"


def test_the_description_is_the_registrys_summary_and_the_decision_is_its_decision() -> None:
    """D328. `summary` is the one prose field all nine Actions carry and the only one this
    artefact's source column can reach; the plan prints a third string per tool and no field holds
    it."""
    entries = _entries()
    for mcp_name, spec in _by_mcp_name().items():
        assert entries[f"mcp.tool.{mcp_name}.description"] == spec.summary
        assert entries[f"mcp.tool.{mcp_name}.decision"] == spec.decision


def test_the_profiles_are_rosters_and_not_counts() -> None:
    """D293: *"a numeral is a second copy of an enumeration and drifts from it in silence"*.

    10:2464 prints *"default + 18 narrow Actions"*; the registry holds five of those eighteen, so a
    transcribed 18 would be a manifest over-declaring a server -- LEANN's defect arrived at through
    a number instead of a name.
    """
    entries = _entries()
    assert entries["mcp.profiles"] == ", ".join(PROFILES)
    for profile in PROFILES:
        want = sorted(str(ACTIONS[name].mcp_name) for name in listed(profile))
        assert entries[f"mcp.profile.{profile}"].split(", ") == want
    assert "18" not in entries["mcp.profile.full"]


# ---------------------------------------------------------------------------------------------
# The constants, and what each is bound to
# ---------------------------------------------------------------------------------------------


def test_the_release_is_the_one_the_distribution_ships() -> None:
    """G5's number. The generator may not read this file (10:229); this test may."""
    version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert version == RELEASE
    entries = _entries()
    assert entries["version"] == version
    assert entries["generated_from"].endswith(f"@ release {version}")


def test_the_two_environment_variables_are_the_ones_the_loader_reads() -> None:
    """D327, and the reason this line is a slot rather than a transcription.

    The plan names `OMNIWEAVE_MCP_ENABLED` in five places; until W7.2e `ENV_OVERRIDES` carried one
    row and `serve.enabled`'s twin was the mechanical `OMNIWEAVE_SERVE_ENABLED`, so a transcribed
    manifest would have told an agent to set a variable the loader never read.
    """
    note = _entries()["mcp.listed_note"]
    assert KEYS["serve.listed"].env in note
    assert KEYS["serve.enabled"].env in note
    assert "OMNIWEAVE_MCP_ENABLED" in note


def test_the_shipped_defaults_come_from_the_config_registry() -> None:
    entries = _entries()
    assert entries["mcp.enabled_default"] == KEYS["serve.enabled"].default
    assert str(KEYS["serve.add_deadline_ms"].default) in entries["mcp.tool.ow_add.note"]


def test_the_instructions_cap_is_sv2s_number_and_not_a_second_copy() -> None:
    assert f"<= {SV2_MAX_CHARS} chars" in _entries()["mcp.instructions"]


def test_the_eight_section_markers_are_the_answer_renderers_own() -> None:
    """`SECTIONS` has nine rows; the status line has no marker, so eight is the whole list."""
    assert tuple(f"ow:{spec.name}" for spec in SECTIONS if spec.marker) == SECTION_MARKERS
    assert _entries()["answer.sections"].startswith(" ".join(SECTION_MARKERS))


def test_the_four_verdict_keys_are_verdictstates_members() -> None:
    named = [name for name, _ in VERDICTS if name != "none"]
    assert named == [member.value for member in VerdictState]
    assert VERDICTS[-1][0] == "none", "the fifth key is the negative space and belongs to no enum"


def test_the_five_quote_tiers_are_the_quote_enums_members() -> None:
    entries = _entries()
    keys = [key.removeprefix("quote.") for key in entries if key.startswith("quote.")]
    spelled = {tier for key in keys for tier in key.split("|")}
    assert spelled == {member.name.lower() for member in Quote}


def test_the_type_vocabulary_covers_every_annotation_any_input_uses() -> None:
    used = {str(field.type) for spec in _by_mcp_name().values() for field in fields(spec.inp)}
    assert used <= set(TYPES)


def test_an_annotation_with_no_manifest_type_does_not_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llms_module, "TYPES", {"str": "string"})
    assert any("no entry in TYPES" in line for line in _manifest_failures())


def test_a_schema_default_that_contradicts_the_dataclass_does_not_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing else binds the VALUES. `mcp_tools._published_failures()` binds the names and the
    order; two agent-facing files disagreeing about what `--context` does when omitted is the same
    class of defect one field down."""
    bent = {
        "ow_open": {
            "properties": {
                "ref": {},
                "corpus": {},
                "context": {"type": "integer", "default": 99},
                "layers": {},
                "max_chars": {},
            }
        }
    }
    monkeypatch.setattr(llms_module, "INPUT_SCHEMAS", bent)
    findings = _manifest_failures()
    assert any("inputSchema publishes default 99" in line for line in findings)


# ---------------------------------------------------------------------------------------------
# The CLI block, and the prose that has no home but this module
# ---------------------------------------------------------------------------------------------


def test_every_published_command_has_a_usage_line_and_names_its_actions() -> None:
    """Keyed by the command's WORDS, because `ow corpora` dispatches two Actions (D299, D322)."""
    entries = _entries()
    for words, actions, _help, _flags in commands():
        key = ".".join(words)
        assert entries[f"cli.{key}"].startswith("ow " + " ".join(words))
        assert entries[f"cli.{key}.actions"] == ", ".join(actions)
    assert entries["cli.corpora.actions"] == "corpora, corpus.coverage"


def test_the_cli_block_publishes_a_group_roster_and_not_a_verb_count() -> None:
    assert _entries()["cli.groups"].split(" ") == sorted(CLI_ROSTER)
    assert "~130" not in _text()


def test_the_twelve_exit_codes_are_published_in_numeric_order() -> None:
    """The manifest publishes the short form of every row the register carries.

    `EXIT_CODES` is `omniweave_core.errors`' now rather than this module's: W7.2f moved it to
    the home 18:996 gives it so artefact 6 could print the same table without a second
    transcription, and `check_register()` holds `codes.toml` to it. D329 was the defect; D332 is
    the move.
    """
    codes = [row.code for row in EXIT_CODES]
    assert codes == sorted(codes)
    line = _entries()["cli.exit_codes"]
    for row in EXIT_CODES:
        assert f"{row.code} {row.slug}" in line


def test_the_four_notes_share_one_key() -> None:
    """LEANN's grammar: a reader greps `^note:` and gets all of them."""
    assert len(_notes()) == 4
    assert any("no egress by default" in note for note in _notes())


def test_the_lifecycle_examples_keep_their_alignment() -> None:
    """`_wrapped()` splits on single spaces and keeps empty tokens, so a run survives."""
    assert "ow install --check          # exit 0 configured" in _text()


def test_the_exit_code_table_lives_in_codes_toml() -> None:
    """D329, closed by D332. This was a strict xfail from W7.2e until the table landed.

    18:996 puts it *"in `codes.toml` beside the `OW-*` register, so `ow explain` prints it and
    `ow surface emit` generates it into `docs/AGENTS.md`"*, and while `codes.toml` carried no
    exit table the twelve pairs had one home in this repository -- a tuple in this generator,
    which is agent-facing text written by hand inside the module that enforces INV-20. W7.2f
    appended the rows, moved the constant to `omniweave_core.errors` where both generators can
    import it, and `check_register()` is the binding this test now only samples.
    """
    register = tomllib.loads((REPO_ROOT / "codes.toml").read_text(encoding="utf-8"))
    published = [(row["code"], row["slug"]) for row in register["exit"]]
    assert published == [(row.code, row.slug) for row in EXIT_CODES]
