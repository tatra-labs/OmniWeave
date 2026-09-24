"""Artefact 7: the router skill's catalog. 10:214; 10:1154; gate G25.

The last of the seven, and the one whose reader is the always-resident router. Three properties
carry it, and the first is the one the file exists for.

**A capability the front door does not list is still here.** 10:2465's note is the artefact's whole
argument: *"an unlisted tool is DEFINED and DISPATCHABLE when enabled, never refused for being
unlisted."* A router that concluded otherwise would decline work the server would have done, which
is LEANN's defect reached from the routing side, so the listing section precedes every Action and
the five `full`-only tools are in the file with the four listed ones.

**The roster is artefact 5's roster.** 10:212 and 10:214 select the same rows in different words --
every Action with an `mcp_name` -- and a test binds `skill_catalog.declared()` to
`llms.declared()`. Two generated files disagreeing about which tools exist is the defect both are
generated to prevent.

**The label grammar holds.** A value is laid out in a twelve-column field and a continuation line
is indented to it, so a line starting in column one is always a new label. `_blocks()` parses the
file back on that rule and the tests read fields rather than substrings.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import omniweave.gen.skill_catalog as catalog_module
import pytest
from omniweave.gen.agents import ABSENT
from omniweave.gen.artefacts import ARTEFACTS, State
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.llms import LISTED_NOTE
from omniweave.gen.llms import declared as llms_declared
from omniweave.gen.skill_catalog import (
    LABEL,
    WIDTH,
    _catalog_failures,
    declared,
    groups,
    render,
    tool_block,
)
from omniweave.gen.wrap import tokens
from omniweave.surface.registry import ACTIONS, HUMAN_ONLY, PROFILES, listed
from omniweave_core.config import KEYS

COMMITTED = REPO_ROOT / "skills" / "omniweave" / "references" / "actions.md"


def _text() -> str:
    return render().decode("utf-8")


def _blocks() -> dict[str, dict[str, str]]:
    """Every `### <tool>` block, parsed back into its labels. The file's own grammar.

    A `### ` line opens a block; a line whose first `LABEL` characters end in a space is a label
    and the rest is its value; a line indented by exactly `LABEL` spaces continues the label
    before it. That is the whole parser, and it is the claim the twelve-column field makes.
    """
    out: dict[str, dict[str, str]] = {}
    tool = ""
    label = ""
    for line in _text().splitlines():
        if line.startswith("### "):
            tool = line[4:].strip()
            out[tool] = {}
            label = ""
        elif not tool or not line:
            continue
        elif line.startswith(" " * LABEL):
            assert label, f"a continuation with nothing to continue: {line!r}"
            out[tool][label] = f"{out[tool][label]} {line[LABEL:]}"
        elif line.startswith("#"):
            tool = ""
        else:
            label = line[:LABEL].strip()
            out[tool][label] = line[LABEL:]
    return out


# ---------------------------------------------------------------------------------------------
# The file that ships
# ---------------------------------------------------------------------------------------------


def test_the_committed_file_is_what_the_generator_produces() -> None:
    """G25's byte diff for this artefact alone. `emit.check()` asserts it across all seven."""
    assert COMMITTED.is_file(), "ow surface emit has not been run"
    assert COMMITTED.read_bytes().replace(b"\r\n", b"\n") == render()


def test_the_register_row_is_live_and_this_closes_the_seven() -> None:
    row = next(a for a in ARTEFACTS if a.number == 7)
    assert row.path == "skills/omniweave/references/actions.md"
    assert row.state is State.LIVE
    assert row.lands_with == "W7.2g"
    assert all(a.state is State.LIVE for a in ARTEFACTS), "W7.2 closes with no PENDING row"


def test_the_output_is_newline_terminated_utf8_with_no_bom() -> None:
    """10:232, and it is the one encoding claim every renderer here has to make itself."""
    payload = render()
    assert payload.endswith(b"\n")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert payload.decode("utf-8")


def test_the_file_says_it_is_generated_in_a_comment_the_reader_does_not_render() -> None:
    """A Markdown reference read by a model: the banner is an HTML comment, which is 10:1280's
    own form for the route stub beside it (`<!-- skills/.../routes/pptx.md - GENERATED ... -->`)."""
    text = _text()
    assert text.startswith("<!-- skills/omniweave/references/actions.md — GENERATED")
    assert "Do not edit. -->" in text
    assert "`ow surface emit`" in text


# ---------------------------------------------------------------------------------------------
# The roster: every Action with an mcp_name, and nothing else
# ---------------------------------------------------------------------------------------------


def test_the_catalog_declares_every_tool_the_registry_defines_and_no_other() -> None:
    """Both directions. One of them is LEANN's file and the other sends a router at nothing."""
    named = sorted(spec.mcp_name for spec in ACTIONS.values() if spec.mcp_name is not None)
    assert list(declared()) == named
    assert sorted(_blocks()) == named


def test_this_roster_is_artefact_5s_roster() -> None:
    """10:212 and 10:214 select the same rows in different words, so the two files carry the
    same tools. A test rather than an import, because the equality is the property -- binding
    one function to the other would make it true by construction and check nothing."""
    assert declared() == llms_declared()


def test_the_narrow_actions_are_here_and_not_only_the_listed_four() -> None:
    """D336. 10:1154 calls this *the narrow-capability catalog* and 10:214's source cell says
    every Action with an `mcp_name`. The cell wins, so the file holds both sets and marks which
    is which -- a catalog of five would omit `ow_query` from the file a router picks with."""
    blocks = _blocks()
    front_door = {str(ACTIONS[name].mcp_name) for name in listed(PROFILES[0])}
    narrow = {str(ACTIONS[name].mcp_name) for name in listed(PROFILES[1])} - front_door
    assert front_door <= set(blocks)
    assert narrow <= set(blocks)
    assert narrow, "the full profile lists more than the default, or this test proves nothing"


def test_no_human_only_action_reaches_the_catalog() -> None:
    """A router cannot route to a capability no agent surface can dispatch. 10:214 excludes them
    by selecting on `mcp_name`, and `docs/AGENTS.md` is where they are published instead."""
    text = _text()
    for name in HUMAN_ONLY:
        assert f"### {name}" not in text
        assert f"action      {name}" not in text


# ---------------------------------------------------------------------------------------------
# The grouping
# ---------------------------------------------------------------------------------------------


def test_the_groups_are_cli_roots_sorted_and_their_members_sorted_by_name() -> None:
    roots = [root for root, _ in groups()]
    assert roots == sorted(roots)
    for _root, members in groups():
        assert [spec.name for spec in members] == sorted(spec.name for spec in members)


def test_every_group_heading_is_a_cli_root_and_every_action_sits_under_its_own() -> None:
    """10:214's *"grouped by `cli[0]`"*, read off the file rather than off the function."""
    heading = ""
    seen: dict[str, str] = {}
    for line in _text().splitlines():
        if line.startswith("## ow "):
            heading = line[len("## ow ") :].strip()
        elif line.startswith("### "):
            seen[line[4:].strip()] = heading
    for _root, members in groups():
        for spec in members:
            assert seen[str(spec.mcp_name)] == spec.cli[0]


def test_two_actions_sharing_a_root_share_a_group() -> None:
    """`corpora` and `corpus.coverage` both spell `ow corpora` (10:1424, D299), and the dotted
    prefix `corpus` is not a CLI root at all -- so the grouping key is the root, not the name."""
    corpora = dict(groups())["corpora"]
    assert [spec.name for spec in corpora] == ["corpora", "corpus.coverage"]
    assert "## ow corpus\n" not in _text()


# ---------------------------------------------------------------------------------------------
# The blocks
# ---------------------------------------------------------------------------------------------


def test_every_block_publishes_six_fields_from_the_registry() -> None:
    blocks = _blocks()
    for _root, members in groups():
        for spec in members:
            block = blocks[str(spec.mcp_name)]
            assert block["action"] == spec.name
            assert block["cli"] == f"ow {' '.join(spec.cli)}"
            assert block["listed"] == (", ".join(sorted(spec.listed_in)) or ABSENT)
            assert block["cost"] == spec.cost_class.value
            assert block["pick it"] == spec.decision
            assert block["it does"] == spec.summary


def test_the_decision_clause_is_published_here_and_not_in_artefact_6() -> None:
    """10:192 makes `decision` the disambiguator *an agent reads at pick time*, and a router is
    the reader that picks. `docs/AGENTS.md`'s reader edits the registry, so W7.2f left it out."""
    agents_md = (REPO_ROOT / "docs" / "AGENTS.md").read_text(encoding="utf-8")
    for spec in ACTIONS.values():
        if spec.mcp_name is not None:
            assert spec.decision in _text()
            assert spec.decision not in agents_md


def test_the_action_name_is_published_beside_the_tool_name() -> None:
    """10:790: both environment variables accept *the bare Action name and the MCP name*, so a
    router widening a listing to reach a capability needs the pair this block carries."""
    for tool, block in _blocks().items():
        assert ACTIONS[block["action"]].mcp_name == tool


def test_cost_is_printed_for_every_block_and_never_dropped_where_it_is_free() -> None:
    """10:216's rule one artefact over: a key present for some rows and absent for others makes
    its presence mean something the register does not declare."""
    costs = {block["cost"] for block in _blocks().values()}
    assert "free" in costs and len(costs) > 1
    assert all("cost" in block for block in _blocks().values())


# ---------------------------------------------------------------------------------------------
# The listing section, which is why the file exists
# ---------------------------------------------------------------------------------------------


def test_the_listing_section_precedes_every_action() -> None:
    text = _text()
    assert text.index("## Before deciding a capability is missing") < text.index("### ow_")


def test_each_profile_publishes_its_roster_and_not_a_count() -> None:
    """D293: a numeral is a second copy of an enumeration. The rosters are the names."""
    text = _text()
    for profile in PROFILES:
        tools = sorted(str(ACTIONS[name].mcp_name) for name in listed(profile))
        line = next(row for row in text.splitlines() if row.startswith(profile))
        joined = line
        for row in text.splitlines()[text.splitlines().index(line) + 1 :]:
            if not row.startswith(" " * LABEL):
                break
            joined = f"{joined} {row[LABEL:]}"
        for tool in tools:
            assert tool in joined


def test_the_listing_note_is_artefact_5s_string_with_the_live_variable_names() -> None:
    """D327's lesson: the manifest once published an environment variable nothing read, so the
    two names are filled from `KEYS` rather than typed. The sentence itself is imported."""
    filled = LISTED_NOTE.format(listed=KEYS["serve.listed"].env, enabled=KEYS["serve.enabled"].env)
    assert " ".join(filled.split()) in " ".join(_text().split())
    assert KEYS["serve.listed"].env in _text()
    assert KEYS["serve.enabled"].env in _text()


def test_the_file_says_a_cli_twin_runs_whatever_the_listing_says() -> None:
    """10:2519, and the reason every block carries a `cli` line."""
    assert "CLI twin" in _text()


# ---------------------------------------------------------------------------------------------
# What cannot be rendered
# ---------------------------------------------------------------------------------------------


def test_the_shipped_registry_renders() -> None:
    assert _catalog_failures() == ()


def test_a_newline_in_a_published_field_is_refused_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A line break inside a value starts a line in column one, which this file's grammar reads
    as a new label. Check 7 caps both strings and says nothing about a newline."""
    first = next(name for name, spec in ACTIONS.items() if spec.mcp_name is not None)
    broken = dict(ACTIONS) | {first: replace(ACTIONS[first], decision="two\nlines")}
    monkeypatch.setattr(catalog_module, "ACTIONS", broken)
    assert any("line break" in line for line in _catalog_failures())


def test_a_tool_the_registry_does_not_define_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half a one-directional check misses: a block naming a tool nothing dispatches."""
    monkeypatch.setattr(
        catalog_module,
        "groups",
        lambda: (("ghost", (replace(next(iter(ACTIONS.values())), mcp_name="ow_ghost"),)),),
    )
    findings = _catalog_failures()
    assert any("ow_ghost" in line and "no Action declares" in line for line in findings)


# ---------------------------------------------------------------------------------------------
# Grammar, purity, determinism
# ---------------------------------------------------------------------------------------------


def test_a_code_span_is_never_broken_across_two_lines() -> None:
    for line in _text().splitlines():
        assert line.count("`") % 2 == 0, line


def test_no_value_line_runs_past_the_column_unless_one_token_does() -> None:
    for line in _text().splitlines():
        if len(line) > WIDTH:
            assert max(len(token) for token in tokens(line)) > WIDTH // 2, line


def test_a_continuation_line_lands_on_the_label_column() -> None:
    """The grammar's whole claim: column one is always a new label."""
    for block in _blocks().values():
        assert set(block) == {"action", "cli", "listed", "cost", "pick it", "it does"}


def test_an_unlisted_reachable_action_would_print_the_em_dash() -> None:
    """Check 5 forbids `listed_in` on an Action with no `mcp_name` and says nothing about the
    reverse, so a reachable-but-unlisted Action is legal -- 10:43's `route.explain` is the one
    the plan names. The block prints artefact 6's em dash rather than an empty field."""
    first = next(name for name, spec in ACTIONS.items() if spec.mcp_name is not None)
    unlisted = replace(ACTIONS[first], listed_in=frozenset())
    assert f"listed      {ABSENT}" in "\n".join(tool_block(unlisted))


def test_the_renderer_reads_no_clock_no_environment_and_no_file() -> None:
    """10:229's ban, `pathlib` included: this module is not the one that writes."""
    tree = ast.parse(Path(catalog_module.__file__).read_text(encoding="utf-8"))
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module


def test_rendering_twice_produces_the_same_bytes() -> None:
    """Determinism, which is what G25's byte diff gates. A set iterated unsorted fails here."""
    assert render() == render()
