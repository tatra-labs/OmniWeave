"""Artefact 3: the CLI argparse tree. 10 section 2.3 row 3; 18 section 2; G25's grammar clauses.

The assertions here fall into three groups, and the middle one is the reason this artefact is worth
generating at all.

**The grammar** -- `ow <group> <verb>`, lower case, three verbs before a group exists, and no two
groups differing only by a trailing `s`. 10:238 puts those in G25 by name; `_grammar_failures()`
raises on the first three and `unrostered_groups()` reports the fourth, and the tests below build a
registry that breaks each one.

**The parser it actually produces**, exercised by parsing argv rather than by reading the table. A
test that only compared `COMMANDS` against `ACTIONS` would pass on a tree argparse cannot build.

**The bytes**, which have one property no other generated artefact here has: they are Python source
that `ruff format` and `ruff check` run over like any other file, so a generator that emitted
`repr()`'s single quotes would fail G25 on the first `ruff format` rather than on a real change.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import subprocess  # noqa: TID251 -- an import set is observable only from a fresh interpreter.
import sys
from dataclasses import fields, replace
from pathlib import Path

import omniweave.gen.cli_tree as cli_tree_module
import pytest
from omniweave.cli import ACTION_DEST as EMITTED_ACTION_DEST
from omniweave.cli import COMMANDS, GLOBAL_FLAGS, GROUP_HELP, PROG, Argument, build_parser
from omniweave.gen.cli_tree import (
    ACTION_DEST,
    CLI_ONLY,
    MIN_GROUP_VERBS,
    RENDER_MODES,
    _grammar_failures,
    arguments_for,
    commands,
    group_help,
    render,
    unrostered_groups,
)
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.mcp_tools import INPUT_SCHEMAS
from omniweave.surface import ACTIONS
from omniweave.surface.inputs import CORPORA_DETAILS, WANTS
from omniweave_core.errors import SurfaceError

TREE = REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "cli"

GLOBAL_SPELLINGS = (
    ("--config",),
    ("--corpus",),
    ("--render",),
    ("--quiet", "-q"),
    ("--verbose", "-v"),
    ("--no-color",),
    ("--offline",),
    ("--json-errors",),
)
"""18:889's eight rows, in that table's order, transcribed a second time so the generator's table is
compared against the document rather than against itself."""


def _help(argv: list[str]) -> str:
    """`ow <argv> --help`, captured. argparse writes help to stdout and exits 0."""
    buffer = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buffer):
        build_parser().parse_args([*argv, "--help"])
    return buffer.getvalue()


def _spec(name: str) -> object:
    return ACTIONS[name]


# ---------------------------------------------------------------------------------------------
# The grammar G25 asserts
# ---------------------------------------------------------------------------------------------


def test_the_shipped_registry_breaks_no_grammar_clause() -> None:
    assert _grammar_failures() == ()


def test_a_three_word_cli_tuple_fails() -> None:
    """18:875's grammar is `ow <group> <verb>` and nothing deeper."""
    broken = {**ACTIONS, "doc.grid": replace(ACTIONS["doc.grid"], cli=("doc", "table", "grid"))}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli_tree_module, "ACTIONS", broken)
        assert any("the grammar is `ow <group> <verb>`" in line for line in _grammar_failures())


def test_a_cli_root_that_is_not_a_registered_group_fails() -> None:
    broken = {**ACTIONS, "explain": replace(ACTIONS["explain"], cli=("explainer",))}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli_tree_module, "ACTIONS", broken)
        assert any("is not a registered group" in line for line in _grammar_failures())


def test_an_upper_case_verb_fails() -> None:
    """18:875: *"`ow <group> <verb>`, both lower case"*."""
    broken = {**ACTIONS, "doc.grid": replace(ACTIONS["doc.grid"], cli=("doc", "Grid"))}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli_tree_module, "ACTIONS", broken)
        assert any("is not lower case" in line for line in _grammar_failures())


def test_two_groups_differing_only_by_a_trailing_s_fail() -> None:
    """10:238's named pair: *"a singular `ow driver` group and the locked `ow drivers` group cannot
    both be generated from one `cli` tuple, and one of them would silently win."*"""
    broken = {
        **ACTIONS,
        "doc.grid": replace(ACTIONS["doc.grid"], cli=("drivers", "grid")),
        "doc.diff": replace(ACTIONS["doc.diff"], cli=("driver", "diff")),
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli_tree_module, "ACTIONS", broken)
        assert any("differ only by a trailing `s`" in line for line in _grammar_failures())


def test_the_arity_rule_is_reported_and_not_raised() -> None:
    """`ow doc` carries two Actions against `CLI_ROSTER`'s four. D306 records the roster half.

    Raising would make `omniweave.gen` unimportable for a scheduling state, which is the argument
    `_unrostered_full()` makes one package over: a roster gap is not a defect in shipped source.
    """
    assert MIN_GROUP_VERBS == 3
    assert unrostered_groups() == ("doc (2)",)
    assert _grammar_failures() == ()


def test_an_unknown_annotation_raises_rather_than_defaulting_to_a_string() -> None:
    """schemagen's `_HANDLERS` discipline: a silent fallback publishes a parameter nothing reads."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli_tree_module, "_KINDS", {})
        with pytest.raises(SurfaceError, match="no CLI rule for the annotation"):
            arguments_for(ACTIONS["explain"])


# ---------------------------------------------------------------------------------------------
# The global flags
# ---------------------------------------------------------------------------------------------


def test_the_global_flags_are_18_884s_eight_in_that_order() -> None:
    assert tuple(flag.spelling for flag in GLOBAL_FLAGS) == GLOBAL_SPELLINGS


def test_every_global_flag_is_accepted_before_and_after_the_verb() -> None:
    """18:887: *"Accepted before or after the verb, on every command."* That is why they are a
    parent parser and not root-only: argparse accepts an option after a subcommand only when the
    subparser declares it too, and a flag a user may write in one position and not the other is
    two contracts."""
    parser = build_parser()
    before = parser.parse_args(["--render", "json", "query", "hello"])
    after = parser.parse_args(["query", "hello", "--render", "json"])
    assert before.render == after.render == "json"
    assert before.query == after.query == "hello"


def test_render_carries_18_1050s_four_modes_and_defaults_to_text() -> None:
    assert RENDER_MODES == ("text", "json", "jsonl", "rows")
    assert build_parser().parse_args(["doctor"]).render == "text"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["doctor", "--render", "yaml"])


def test_verbose_counts_and_quiet_switches() -> None:
    """18:895: *"`-v` adds phase timings; `-vv` adds the event stream at debug"*."""
    parsed = build_parser().parse_args(["doctor", "-vv", "-q"])
    assert parsed.verbose == 2
    assert parsed.quiet is True


def test_every_global_flag_reaches_every_command() -> None:
    declared = {flag.spelling[0].lstrip("-").replace("-", "_") for flag in GLOBAL_FLAGS}
    for command in COMMANDS:
        parsed = vars(build_parser().parse_args([*command.words, *_minimal(command)]))
        assert declared <= set(parsed), command.words


def _minimal(command: object) -> list[str]:
    """The positional arguments one command needs to parse at all."""
    supplied: list[str] = []
    for argument in command.arguments:  # type: ignore[attr-defined]
        if argument.spelling[0].startswith("-") or argument.nargs == "?":
            continue
        supplied.append("x")
    return supplied


# ---------------------------------------------------------------------------------------------
# One Action's arguments
# ---------------------------------------------------------------------------------------------


def test_a_required_field_is_a_positional_and_a_defaulted_one_is_a_flag() -> None:
    parsed = build_parser().parse_args(["explain", "OW-A-013"])
    assert parsed.code == "OW-A-013"
    assert build_parser().parse_args(["doctor"]).runtime is False
    assert build_parser().parse_args(["doctor", "--runtime"]).runtime is True


def test_the_batch_forms_take_many_words() -> None:
    """18:1336's `oneOf` of a string and an array is one argv shape on a shell."""
    assert build_parser().parse_args(["open", "d7#412"]).ref == ["d7#412"]
    assert build_parser().parse_args(["add", "a.pdf", "b.pdf"]).source == ["a.pdf", "b.pdf"]


def test_an_underscore_becomes_a_hyphen() -> None:
    """18:913 prints `--dry-run` for `AddIn.dry_run`."""
    assert build_parser().parse_args(["add", "x", "--dry-run"]).dry_run is True
    assert build_parser().parse_args(["doc", "diff", "d7", "--from-gen", "40"]).from_gen == 40


def test_an_int_field_parses_as_an_int() -> None:
    assert build_parser().parse_args(["query", "q", "--max-chars", "8000"]).max_chars == 8000
    assert build_parser().parse_args(["open", "d7", "--context", "3"]).context == 3


def test_corpus_is_global_everywhere_and_positional_on_ow_corpora_alone() -> None:
    """18:892 makes `--corpus` global; 18:912 prints `ow corpora [<name>]`."""
    for command in COMMANDS:
        published = {flag.spelling[0] for flag in command.arguments}
        assert "--corpus" not in published, command.words
        if command.words != ("corpora",):
            assert "corpus" not in published, command.words
    assert build_parser().parse_args(["corpora", "handbook"]).corpus == "handbook"
    assert build_parser().parse_args(["corpora"]).corpus is None


def test_the_choice_sets_are_artefact_1s_and_not_a_second_spelling() -> None:
    """`--want`, `--detail` and `--max-rung` read `INPUT_SCHEMAS`, which reads `inputs.py`."""
    published = {
        flag.spelling[0]: flag.choices for flag in _flags_of(("query",)) + _flags_of(("corpora",))
    }
    assert published["--want"] == WANTS
    assert published["--detail"] == CORPORA_DETAILS
    rungs = INPUT_SCHEMAS["ow_query"]["properties"]["route_hints"]["properties"]["max_rung"]
    assert published["--max-rung"] == tuple(rungs["enum"])


def _flags_of(words: tuple[str, ...]) -> tuple[Argument, ...]:
    return next(command.arguments for command in COMMANDS if command.words == words)


def test_a_choice_set_shows_its_values_in_help_rather_than_a_metavar() -> None:
    """18:910 prints `--want passages|table|fields|outline|related`; a metavar would hide them."""
    text = _help(["query"])
    assert "{passages,table,fields,outline,related}" in text
    assert "--want WANT" not in text


def test_route_hints_publishes_only_max_rung() -> None:
    """D322. 18:910's `ow query` row prints `--max-rung` and neither `--lane` nor `--deadline-ms`,
    and no document gives the rule for turning a nested object into flags."""
    published = {flag.spelling[0] for flag in _flags_of(("query",))}
    assert "--max-rung" in published
    assert published.isdisjoint({"--lane", "--deadline-ms", "--route-hints"})


def test_the_eleven_cli_only_flags_are_published_and_have_no_input_field() -> None:
    """D321. 10:210 says the tree comes from `cli` tuples plus `inp` fields; eleven flags 18:910
    prints come from neither."""
    spellings = {flag.spelling[0] for flags in CLI_ONLY.values() for flag in flags}
    assert spellings == {
        "--k",
        "--mode",
        "--fail-on",
        "--explain",
        "--raw",
        "--want-impact",
        "--summarize",
        "--schema",
        "--allow-cost",
        "--allow-egress",
        "--wait",
    }
    for words, flags in CLI_ONLY.items():
        names = {
            name for spec in ACTIONS.values() if spec.cli == words for name in _field_names(spec)
        }
        for flag in flags:
            assert flag.spelling[0].lstrip("-").replace("-", "_") not in names, flag.spelling


def _field_names(spec: object) -> set[str]:
    return {field.name for field in fields(spec.inp)}  # type: ignore[attr-defined]


def test_the_cli_only_flags_parse() -> None:
    parsed = build_parser().parse_args(
        ["query", "q", "--k", "20", "--mode", "cite", "--fail-on", "absent,degraded", "--explain"]
    )
    assert (parsed.k, parsed.mode, parsed.fail_on, parsed.explain) == (
        20,
        "cite",
        "absent,degraded",
        True,
    )
    assert build_parser().parse_args(["add", "x", "--allow-cost", "500"]).allow_cost == 500


# ---------------------------------------------------------------------------------------------
# The command table, and the collision two Actions make
# ---------------------------------------------------------------------------------------------


def test_every_action_with_a_cli_tuple_reaches_a_command() -> None:
    spelled = {command.words for command in COMMANDS}
    assert spelled == {spec.cli for spec in ACTIONS.values() if spec.cli}


def test_the_commands_are_sorted_by_their_words() -> None:
    """10:225's sort, through the one projection this artefact has: two Actions can share a
    spelling, so the spelling is the key."""
    words = [command.words for command in COMMANDS]
    assert words == sorted(words)


def test_ow_corpora_is_one_subparser_carrying_two_actions() -> None:
    """D299, and 10:1424's resolution: `corpus.coverage`'s CLI twin is `ow corpora --detail
    coverage`, a FLAG VALUE on the first, so the two Actions share one subparser and their
    arguments are unioned."""
    corpora = next(command for command in COMMANDS if command.words == ("corpora",))
    assert corpora.actions == ("corpora", "corpus.coverage")
    published = {flag.spelling[0] for flag in corpora.arguments}
    assert {"corpus", "--detail", "--scope", "--summarize"} == published
    parsed = build_parser().parse_args(["corpora", "--detail", "coverage", "--scope", "policy.pdf"])
    assert (parsed.detail, parsed.scope) == ("coverage", "policy.pdf")


def test_a_shared_spelling_resolves_to_one_action_and_the_other_needs_the_flag() -> None:
    """The half the union does not settle: `set_defaults` can carry one name, and the dispatcher
    reads `--detail` to tell the pair apart. D322 records that no document states the rule."""
    assert build_parser().parse_args(["corpora"]).ow_action == "corpora"
    assert build_parser().parse_args(["corpora", "--detail", "coverage"]).ow_action == "corpora"


def test_every_command_records_the_action_it_resolves_to() -> None:
    """02:719's step 1: *"parse argv against the generated argparse tree, look the verb up in
    `ACTIONS`"*. `ACTION_DEST` is the key that lookup reads."""
    assert ACTION_DEST == EMITTED_ACTION_DEST == "ow_action"
    for command in COMMANDS:
        parsed = build_parser().parse_args([*command.words, *_minimal(command)])
        assert getattr(parsed, ACTION_DEST) in ACTIONS, command.words


def test_a_group_advertises_the_verbs_it_has_and_not_the_ones_it_is_owed() -> None:
    """`CLI_ROSTER["doc"]` carries four; two have landed. A `--help` naming `show` and `verify`
    against a parser with neither is LEANN's `llms.txt` in one line, and G25 is named after it."""
    assert GROUP_HELP == {"doc": "diff · grid"}
    assert group_help() == GROUP_HELP
    text = _help(["doc"])
    assert "diff" in text
    assert "verify" not in text


def test_an_unknown_verb_is_a_usage_error() -> None:
    """02:719's step 1: *"an unknown verb or flag: usage error, exit 1, no config read"*."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["doc", "invent"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["query", "q", "--invented"])


def test_the_command_help_is_its_actions_summary() -> None:
    for command in COMMANDS:
        assert command.help == ACTIONS[command.actions[0]].summary


# ---------------------------------------------------------------------------------------------
# The bytes, which are also Python
# ---------------------------------------------------------------------------------------------


def test_the_committed_module_is_byte_for_byte_what_the_generator_produces() -> None:
    committed = (TREE / "__init__.py").read_bytes()
    assert committed.replace(b"\r\n", b"\n") == render()


def test_the_package_holds_exactly_the_one_generated_module() -> None:
    """`check()`'s fifth clause is over this set; asserting it here says what the set is."""
    tracked = sorted(
        path.relative_to(TREE).as_posix()
        for path in TREE.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(TREE).parts
    )
    assert tracked == ["__init__.py"]


def test_the_render_is_utf8_with_no_bom_and_one_trailing_newline() -> None:
    raw = render()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    raw.decode("utf-8")


def test_rendering_twice_gives_the_same_bytes() -> None:
    assert render() == render()


def test_the_emitted_source_parses_and_declares_what_it_exports() -> None:
    tree = ast.parse(render().decode("utf-8"))
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        for target in [node.target]
    }
    assert {"PROG", "ACTION_DEST", "GLOBAL_FLAGS", "COMMANDS", "GROUP_HELP"} <= assigned
    assert PROG == "ow"


def test_the_emitted_source_carries_no_single_quoted_string() -> None:
    """`ruff format` normalises quotes, so a generator that reached for `repr()` would emit a
    module the formatter rewrites -- and G25 would then fail on the first `ruff format` run rather
    than on a change anyone made."""
    text = render().decode("utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            segment = ast.get_source_segment(text, node)
            assert segment is None or not segment.startswith("'"), segment


def test_no_emitted_line_is_longer_than_the_lint_allows() -> None:
    lines = render().decode("utf-8").splitlines()
    assert max(len(line) for line in lines) <= 100


def test_the_generator_reads_no_clock_no_environment_and_no_path() -> None:
    """10:224's ban, over the module that renders artefact 3."""
    source = Path(cli_tree_module.__file__).read_text(encoding="utf-8")
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert not {alias.name.split(".")[0] for alias in node.names} & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module


def _modules_loaded_by(statement: str) -> set[str]:
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_the_generated_tree_opens_no_path_to_the_router_or_a_socket() -> None:
    """`ow --help` has a 190 ms cold budget (12:238) and a breach there is *"usually G25's surface
    generator growing"*. The tree imports `argparse` and `typing` and nothing of omniweave's."""
    loaded = _modules_loaded_by("import omniweave.cli")
    assert "omniweave.route" not in loaded
    assert loaded.isdisjoint({"_socket", "socket", "email"})


def test_building_the_parser_touches_no_registry() -> None:
    """The emitted module is data plus argparse: `ACTIONS` is the generator's input, not the
    parser's, so `ow --help` pays for neither the registry nor its output types."""
    source = (TREE / "__init__.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("omniweave"), node.module
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith("omniweave") for alias in node.names)


def test_the_parser_argparse_builds_is_the_one_the_table_describes() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    assert parser.prog == PROG
    assert len(commands()) == len(COMMANDS)
