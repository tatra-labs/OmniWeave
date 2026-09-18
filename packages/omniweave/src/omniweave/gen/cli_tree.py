"""Artefact 3: the CLI argparse tree. 10 section 2.3 row 3; 18 section 2; 11:246.

10:210's row: generated from *"`cli` tuples plus `inp` fields"*, consumed by *"`ow --help`, shell
completion"*. 10:1453 says the same from the other end and is the sentence that makes the tree
mechanical rather than a layout decision: every CLI verb *"is an `ActionSpec` row, so the argparse
tree is generated and the same `--render`/exit-code contract applies"*.

16:716 calls this the largest of the seven generators and gives three reasons, all of which are
grammar rather than volume: *"a verb is an imperative, a group is created only at three or more
verbs, and there are no aliases"*. `_grammar_failures()` below is those three plus G25's fourth --
no two groups differing only by a trailing `s` -- and it raises at import, because each describes a
`cli` tuple that is wrong in shipped source rather than a roster that is merely incomplete.

## WHAT THIS EMITS, AND WHY IT IS DATA WITH A BUILDER RATHER THAN A SCRIPT OF `add_argument` CALLS

`omniweave/cli/__init__.py`, whole. 11:246 marks the directory `T-GENERATED` and 02:35 draws it
inside G25's box, so there is no hand-written module beside the generated one; the package is one
file and this renderer writes all of it.

What it writes is a `COMMANDS` table and a fixed `build_parser()` that walks it. The alternative --
emitting one `add_parser`/`add_argument` statement per row -- produces the same parser and a worse
diff: a reviewer approving a new flag would read a rewritten function instead of an added row, and
G25's byte diff exists precisely so that a change to the agent-facing surface is legible. It also
keeps the generated code constant, so the only thing that can move between releases is data.

## THE BOUNDS AND THE CHOICES COME FROM ARTEFACT 1, NOT FROM A SECOND SPELLING

`--want`'s five values, `--detail`'s four and `--max-rung`'s seven are read out of
`gen/mcp_tools.INPUT_SCHEMAS`, which reads them from `surface/inputs.py`'s `Final`s. So the chain is
one deep and has one home: a member added to `WANTS` reaches the MCP schema and the CLI in the same
commit, and neither artefact carries a copy. That is also why artefact 1 lands before artefact 3
rather than beside it -- 10:206's numbering turns out to be a dependency order for two of the seven.

Per-argument help is the published `description` from the same place, where there is one. Nothing
in the plan writes CLI help text, and `summary` is the only per-Action prose 10:210's source column
could reach; D321 records that the column names neither.

## THE FIELD-TO-ARGUMENT RULE, AND THE FOUR PLACES IT DOES NOT REACH

A field with no default is a positional; a field with a default is `--kebab-case`. `str |
tuple[str, ...]` takes `nargs="+"`, `bool` becomes a switch, `int` carries `type=int`. `_KINDS` is
the closed map of the eight annotation spellings `surface/inputs.py` actually uses, and an
unrecognised one raises rather than defaulting to a string -- schemagen's `_HANDLERS` discipline,
for schemagen's reason: a silent fallback publishes a parameter the handler cannot read.

Four things that rule cannot produce, all recorded in D321 and D322:

1. **`--corpus` is global** (18:892), so a `corpus` field is not published per verb -- except on
   `ow corpora`, which 18:912 prints as `ow corpora [<name>]`, a positional.
2. **`route_hints` is an object.** 18:910's `ow query` row publishes exactly one of its three
   fields, `--max-rung`, and no rule in any document says which of a nested object's fields become
   flags.
3. **Eleven published flags have no `inp` field at all** -- `--k`, `--mode`, `--fail-on`,
   `--explain`, `--raw`, `--want-impact`, `--summarize`, `--schema`, `--allow-cost`,
   `--allow-egress`, `--wait`. `surface/inputs.py` says so of the first three by name. They are
   transcribed in `CLI_ONLY` below.
4. **`ow open` declares `max_chars` and 18:911 does not print `--max-chars` for it**, although
   18:910 prints it for `ow query` and the two fields are the same parameter with the same bounds.
   The rule wins here and the table is the defect, because the handler honours the parameter either
   way and a CLI that could not pass it would be narrower than the MCP tool.

## WHAT IS NOT HERE: A DISPATCHER

`build_parser()` parses and `set_defaults` records which Action each command resolves to. Nothing
calls one. 02:719's step 1 is *"parse argv against the generated argparse tree, look the verb up in
`ACTIONS`"* and steps 2-9 are config, limits, digests, surface, store, catalog, lock and loop --
none of which exists yet. A `[project.scripts]` entry pointing at a `main()` that could parse
`ow query` and then do nothing would be a front door that lies, which is the defect INV-20 names.
D323 is the entry, and `ow` becomes a console script in the cell that lands the dispatch sequence.
"""

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import SurfaceError

from omniweave.gen.mcp_tools import INPUT_SCHEMAS
from omniweave.surface.registry import ACTIONS, GROUPS, ROOT_AND_VERB, ActionSpec

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CLI_ONLY",
    "GLOBAL_FLAGS",
    "MIN_GROUP_VERBS",
    "RENDER_MODES",
    "Flag",
    "arguments_for",
    "commands",
    "group_help",
    "render",
    "unrostered_groups",
]


MIN_GROUP_VERBS: Final[int] = 3
"""18:875: *"a group exists only at three or more verbs"*, and G25 checks it (10:238)."""

RENDER_MODES: Final[tuple[str, ...]] = ("text", "json", "jsonl", "rows")
"""18:1042's four output modes, in that table's order. `text` is the default (18:893).

Spelled here rather than imported, because `--render` has no home in the packages yet: the modes
are an output-side contract (`owrows/1` is 07 section 7.5's) and nothing under `packages/` declares
them. When a renderer lands, this tuple becomes an import the way `WANTS` already is.
"""

ACTION_DEST: Final[str] = "ow_action"
"""The `set_defaults` key carrying the `ACTIONS` name a parsed command resolves to.

Not `action`, which argparse already uses for the behaviour of an argument, and not `name`, which a
future `--name` flag would shadow. 02:719's step 1 reads this key.
"""


@dataclass(frozen=True, slots=True)
class Flag:
    """One published positional or option, in the form the generated table carries it."""

    spelling: tuple[str, ...]
    kind: str = "str"
    nargs: str | None = None
    metavar: str | None = None
    choices: tuple[str, ...] | None = None
    default: object = None
    help: str = ""


_KINDS: Final[Mapping[str, str]] = {
    "str": "str",
    "int": "int",
    "bool": "switch",
    "str | None": "str",
    "int | None": "int",
    "str | tuple[str, ...]": "str",
    "tuple[str, ...] | None": "csv",
    "RouteHints | None": "object",
}
"""Every annotation `surface/inputs.py` uses, mapped to how the CLI publishes it.

Read as the strings they are: `from __future__ import annotations` makes every field's `type` a
string, and resolving them would import `omniweave.route` for `RouteHints` -- 47 modules and a
socket, which is D298's charge and the same one `mcp_tools.py` refuses. A closed map over the
spellings needs no resolution, and an unknown spelling raises.
"""

GLOBAL_FLAGS: Final[tuple[Flag, ...]] = (
    Flag(
        ("--config",),
        metavar="PATH",
        help="the highest-precedence config source; skips the upward walk",
    ),
    Flag(
        ("--corpus",),
        metavar="NAME",
        help="resolves through [corpora]; ow query is the one verb accepting a comma list",
    ),
    Flag(
        ("--render",),
        choices=RENDER_MODES,
        default=RENDER_MODES[0],
        help="output mode",
    ),
    Flag(
        ("--quiet", "-q"),
        kind="switch",
        help="suppress the progress stream; diagnostics still print",
    ),
    Flag(
        ("--verbose", "-v"),
        kind="count",
        default=0,
        help="-v adds phase timings; -vv adds the event stream at debug",
    ),
    Flag(
        ("--no-color",),
        kind="switch",
        help="ANSI only when stdout is a TTY; also honours NO_COLOR",
    ),
    Flag(
        ("--offline",),
        kind="switch",
        help="refuse every fetch, a toolchain install included",
    ),
    Flag(
        ("--json-errors",),
        kind="switch",
        help="print an OwError as one JSON object on stderr instead of prose",
    ),
)
"""18:889's eight global flags, in that table's order, *"accepted before or after the verb, on every
command"*.

That last clause is why they are published as an `add_help=False` parent parser rather than on the
root alone: argparse only accepts an option after the subcommand if the subparser also declares it,
and a global flag a user may write in one position and not the other is two contracts.

18:900 names `--json-errors` the load-bearing one: *"without it a CI consumer has to parse prose to
recover the `OW-*` code, which is exactly the fragility `codes.toml` exists to remove."*
"""

CLI_ONLY: Final[Mapping[tuple[str, ...], tuple[Flag, ...]]] = {
    ("query",): (
        Flag(("--k",), kind="int", metavar="N", help="candidates per channel before fusion"),
        Flag(
            ("--mode",),
            choices=("find", "cite", "explore", "prove_absent"),
            help="the planner's mode; never set by --want",
        ),
        Flag(
            ("--fail-on",),
            metavar="STATE[,STATE]",
            help="exit 3 on absent, 4 on degraded, instead of 0",
        ),
        Flag(("--explain",), kind="switch", help="print the routing decision with the answer"),
    ),
    ("open",): (
        Flag(("--raw",), kind="switch", help="the retained bytes, without the packer's rendering"),
        Flag(
            ("--want-impact",),
            kind="switch",
            help="ow:impact for a batch; a single-block ref gets it anyway",
        ),
    ),
    ("corpora",): (
        Flag(
            ("--summarize",),
            kind="switch",
            help="write the corpus abstract, recording a producer",
        ),
    ),
    ("add",): (
        Flag(("--schema",), metavar="PATH", help="a JSON Schema; sets unit.schema_requested"),
        Flag(
            ("--allow-cost",),
            kind="int",
            metavar="MICROS",
            help="approve billable work up to this many micros",
        ),
        Flag(("--allow-egress",), metavar="GRANT", help="the grant id that permits a fetch"),
        Flag(("--wait",), kind="int", metavar="S", help="seconds to wait before reporting pending"),
    ),
}
"""Published flags with no `inp` field, transcribed from 18:910-913's command table.

Eleven of them, and they are not an oversight in `surface/inputs.py`: that module states three by
name -- *"**No `k`, `mode` or `fail_on`.** Those are `ow query` CLI flags (18:910)"* -- and the
reason generalises. `--want-impact` is absent from `OpenIn` because 18:1365 has the MCP handler set
it by default for a single-block ref; `--allow-cost` is absent from `AddIn` because 10:1131 makes
cost approval CLI-only, *"because `RouteHints` correctly has no budget field"*; `--summarize` is
absent from `CorporaIn` because 10:90 puts the abstract on the human surface.

So the asymmetry is the design, and what is wrong is 10:210's source column claiming the tree comes
from `cli` tuples plus `inp` fields. D321 is the entry. Their types and value names are the table's
own notation -- `N` and `<micros>` are integers, a bare flag is a switch, `a|b|c` is a choice set.
"""

CORPUS_PARAM: Final[str] = "corpus"
"""18:892 makes `--corpus` global, so a `corpus` field is never published per verb -- except one."""

CORPUS_POSITIONAL: Final[tuple[str, ...]] = ("corpora",)
"""The one command that publishes `corpus` as a positional: 18:912's `ow corpora [<name>]`.

Named as a constant rather than written into a branch, because it is a fact about one printed row
and a reader should be able to find every place this generator departs from its own rule.
"""

ROUTE_HINTS_FIELD: Final[str] = "route_hints"
ROUTE_HINTS_PUBLISHED: Final[tuple[str, ...]] = ("max_rung",)
"""Which of `route_hints`' three published sub-fields become CLI flags: 18:910 prints `--max-rung`
and neither `--lane` nor `--deadline-ms`. D322 records that no document gives the rule."""


# =============================================================================================
# 1. The grammar G25 asserts, at import
# =============================================================================================


def _spellings() -> Mapping[tuple[str, ...], tuple[str, ...]]:
    """Every `cli` tuple in `ACTIONS`, mapped to the Action names that claim it, sorted."""
    claimed: dict[tuple[str, ...], list[str]] = {}
    for name, spec in ACTIONS.items():
        if spec.cli:
            claimed.setdefault(spec.cli, []).append(name)
    return {words: tuple(sorted(names)) for words, names in sorted(claimed.items())}


def _grammar_failures() -> tuple[str, ...]:
    """G25's CLI grammar, over the `cli` tuples that have landed. 10:238; 18:875.

    Four clauses, three of them 16:716's own reasons for calling this the largest generator:

    1. **at most two words.** 18:875's grammar is `ow <group> <verb>` and nothing deeper; a
       three-word `cli` tuple would need a second level of subparsers no document describes.
    2. **`cli[0]` is a registered group.** Check 9 of 10:193 already asserts it over `ACTIONS`;
       repeated here because this generator would otherwise build a subparser for a root the roster
       does not know, and `ow --help` is where that becomes visible.
    3. **no two groups differ only by a trailing `s`.** 10:238 names the pair it exists for: *"a
       singular `ow driver` group and the locked `ow drivers` group cannot both be generated from
       one `cli` tuple, and one of them would silently win."*
    4. **a lower-case spelling throughout**, which is 18:875's *"both lower case"*.

    The three-or-more-verbs rule is NOT here, and that is deliberate: it is a property of the
    ROSTER rather than of what has landed, `ow doc` carries two Actions today against `CLI_ROSTER`'s
    four, and raising on it would make a registry unimportable for a scheduling state. D306 already
    records the five rostered groups that breach it. `unrostered_groups()` reports this half.
    """
    out: list[str] = []
    for words, names in _spellings().items():
        who = ", ".join(names)
        if not words:  # pragma: no cover -- check 9 of 10:193 refuses an empty `cli` first
            out.append(f"{who}: cli is empty; check 9 of 10:193 requires a spelling")
            continue
        if len(words) > ROOT_AND_VERB:
            out.append(
                f"{who}: cli={words} is {len(words)} words; the grammar is `ow <group> <verb>`"
            )
        if words[0] not in GROUPS:
            out.append(f"{who}: cli[0]={words[0]!r} is not a registered group")
        if any(word != word.lower() for word in words):
            out.append(f"{who}: cli={words} is not lower case (18:875)")
    roots = {words[0] for words in _spellings()}
    out.extend(
        f"{root!r} and {root + 's'!r} differ only by a trailing `s` (G25)"
        for root in sorted(roots)
        if root + "s" in roots
    )
    return tuple(out)


_GRAMMAR: Final[tuple[str, ...]] = _grammar_failures()
if (
    _GRAMMAR
):  # pragma: no cover -- the shipped registry is well-formed; a test builds one that is not
    raise SurfaceError(
        "the CLI grammar G25 asserts is broken by a `cli` tuple: " + "; ".join(_GRAMMAR),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="correct the `cli` tuple in surface/registry.py; `ow <group> <verb>`, both lower case",
    )


def unrostered_groups() -> tuple[str, ...]:
    """Groups whose landed verb count is below 18:875's three. Reported, never raised.

    `ow doc` has two Actions today and four rostered spellings, so the arity rule is satisfied by
    the plan and not yet by this build. Raising would make the registry unimportable for a
    scheduling state, which is `_unrostered_full()`'s argument in the package next door; D306
    records the five groups that breach the rule against the ROSTER, which is the half a reviewer
    has to fix in a document rather than in code.
    """
    counts: dict[str, int] = {}
    for words in _spellings():
        if len(words) > 1:
            counts[words[0]] = counts.get(words[0], 0) + 1
    return tuple(
        sorted(f"{root} ({count})" for root, count in counts.items() if count < MIN_GROUP_VERBS)
    )


# =============================================================================================
# 2. One Action's arguments
# =============================================================================================


def _published(spec: ActionSpec) -> Mapping[str, Any]:
    """The Action's published `inputSchema` properties, or an empty mapping.

    Artefact 1 publishes four; the narrow rows have none yet and declare no enum-valued or
    prose-carrying parameter, so an empty mapping is a complete answer for them rather than a
    silent loss. `mcp_tools.unpublished()` is the roster of the five that are waiting.
    """
    if spec.mcp_name is None or spec.mcp_name not in INPUT_SCHEMAS:
        return {}
    properties = INPUT_SCHEMAS[spec.mcp_name]["properties"]
    return properties if isinstance(properties, dict) else {}


def _nargs(annotation: str, *, required: bool) -> str | None:
    """A positional's `nargs`: `"+"` for the batch forms, `"?"` for the one optional positional.

    `str | tuple[str, ...]` is 18:1336's `oneOf` of a string and an array read on the shell, where
    the singular and plural forms are the same argv either way -- `ow open d7#412` and
    `ow open d7#412 d7#998` differ only in length. `"?"` is `ow corpora [<name>]` and nothing else.
    """
    if annotation == "str | tuple[str, ...]":
        return "+"
    return None if required else "?"


def _flag_name(field_name: str) -> str:
    """`dry_run` -> `--dry-run`. 18:913 prints `--dry-run` for `AddIn.dry_run`."""
    return "--" + field_name.replace("_", "-")


def group_help() -> Mapping[str, str]:
    """Each group's help line: the verbs it actually has, in 18:910's own notation.

    18:932 writes `ow doc` as *"`show` \u00b7 `verify` \u00b7 `grid`"* -- a group's help in that
    table IS its verb list -- so the notation is transcribed and the content is derived. Derived
    from the LANDED verbs and not from `CLI_ROSTER`, which carries four for `ow doc`: a `--help`
    that advertised `show` and `verify` against a parser with neither is LEANN's `llms.txt` in one
    line, and G25 is named after that defect.
    """
    verbs: dict[str, list[str]] = {}
    for words in _spellings():
        if len(words) > 1:
            verbs.setdefault(words[0], []).append(words[1])
    return {root: " \u00b7 ".join(sorted(found)) for root, found in sorted(verbs.items())}


def _from_object(spec: ActionSpec, field_name: str) -> tuple[Flag, ...]:
    """A nested object field's flags: `route_hints` -> `--max-rung`, and nothing else. D322."""
    nested = _published(spec).get(field_name, {}).get("properties", {})
    out: list[Flag] = []
    for name in ROUTE_HINTS_PUBLISHED:
        published = nested.get(name, {})
        enum = published.get("enum")
        out.append(
            Flag(
                (_flag_name(name),),
                choices=tuple(enum) if enum else None,
                help=published.get("description", ""),
            )
        )
    return tuple(out)


def arguments_for(spec: ActionSpec) -> tuple[Flag, ...]:
    """One Action's published arguments: its `inp` fields, then 18:910's CLI-only flags.

    Declaration order throughout, for 10:226's reason one artefact over -- it is
    `dataclasses.fields` order, it is what the MCP schema publishes, and a CLI whose `--help`
    listed the same parameters in a different order would be a second opinion about the surface.
    """
    published = _published(spec)
    out: list[Flag] = []
    for field in fields(spec.inp):
        kind = _KINDS.get(str(field.type))
        if kind is None:
            raise SurfaceError(
                f"{spec.inp.__name__}.{field.name}: no CLI rule for the annotation {field.type!r}",
                symbol="OW_SURFACE_REGISTRY_INVALID",
                fix="add the annotation to _KINDS in gen/cli_tree.py, with its argparse shape",
            )
        if kind == "object":
            out.extend(_from_object(spec, field.name))
            continue
        required = field.default is MISSING and field.default_factory is MISSING
        declared = published.get(field.name, {})
        text = declared.get("description", "")
        if field.name == CORPUS_PARAM and spec.cli != CORPUS_POSITIONAL:
            continue
        if required or field.name == CORPUS_PARAM:
            out.append(
                Flag(
                    (field.name,),
                    kind="str" if kind == "csv" else kind,
                    nargs=_nargs(str(field.type), required=required),
                    metavar=field.name.upper(),
                    help=text,
                )
            )
            continue
        enum = declared.get("enum")
        hidden = kind in {"switch", "count"} or bool(enum)
        out.append(
            Flag(
                (_flag_name(field.name),),
                kind=kind,
                metavar=None if hidden else field.name.upper(),
                choices=tuple(enum) if enum else None,
                default=field.default if field.default is not MISSING else None,
                help=text,
            )
        )
    out.extend(CLI_ONLY.get(spec.cli, ()))
    return tuple(out)


def commands() -> tuple[tuple[tuple[str, ...], tuple[str, ...], str, tuple[Flag, ...]], ...]:
    """Every published command: its words, the Actions it dispatches, its help and its arguments.

    Sorted by the command's words, which is 10:225's *"Actions by `name`"* read through the one
    projection this artefact has -- two Actions can share a spelling, so the spelling is the key.

    `ow corpora` is that case and it is 10:1424's: `corpora` and `corpus.coverage` both spell it,
    because the second's CLI twin is `ow corpora --detail coverage`, a FLAG VALUE on the first.
    The subparser therefore carries the UNION of the two Actions' arguments in roster order, and
    the pair is named in `_duplicate_cli()` one package over. No document states the union rule;
    D322 records that, and the alternative -- one subparser per Action -- is not available, because
    argparse resolves a command by its words.
    """
    out: list[tuple[tuple[str, ...], tuple[str, ...], str, tuple[Flag, ...]]] = []
    for words, names in _spellings().items():
        merged: list[Flag] = []
        for name in names:
            for flag in arguments_for(ACTIONS[name]):
                if flag.spelling not in {seen.spelling for seen in merged}:
                    merged.append(flag)
        out.append((words, names, ACTIONS[names[0]].summary, tuple(merged)))
    return tuple(out)


# =============================================================================================
# 3. The bytes
# =============================================================================================

_WIDTH: Final[int] = 96
"""The column a wrapped string literal stops at, leaving room for the closing quote inside 100."""


def _wrap(body: str, indent: str) -> list[str]:
    """`body` as one or more adjacent string literals, each fitting the line length.

    Implicit concatenation rather than a backslash or a textwrap call, because the result has to
    survive `ruff format` unchanged -- a generated module is linted and formatted like any other
    file here, and a byte-diff gate over source that the formatter would rewrite is a gate that
    fails on the first `ruff format` run.
    """
    budget = _WIDTH - len(indent) - 2
    pieces: list[str] = []
    rest = body
    while rest:
        if len(rest) <= budget:
            pieces.append(rest)
            break
        cut = rest.rfind(" ", 0, budget)
        cut = budget if cut <= 0 else cut + 1
        pieces.append(rest[:cut])
        rest = rest[cut:]
    return [f"{indent}{_literal(piece)}" for piece in pieces or [""]]


def _literal(text: str) -> str:
    """One Python string literal for `text`, double-quoted, with the four escapes JSON needs."""
    escaped = (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _value(value: object) -> str:
    """One Python expression for a table cell, double-quoted throughout.

    `repr()` is not usable here and the reason is mechanical: it single-quotes strings and this
    repository formats with `ruff format`, which normalises them back to double quotes -- so a
    generator that reached for `repr` would emit a module the formatter rewrites, and G25 would
    fail on the first `ruff format` run rather than on a real change.
    """
    if isinstance(value, str):
        return _literal(value)
    if isinstance(value, tuple):
        inner = ", ".join(_value(member) for member in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    return repr(value)


def _field_lines(name: str, value: object, indent: str) -> list[str]:
    """One `name=value,` line, or several when the value is a string that does not fit."""
    rendered = _value(value)
    if len(indent) + len(name) + len(rendered) + 2 <= _WIDTH:
        return [f"{indent}{name}={rendered},"]
    if isinstance(value, str):
        return [f"{indent}{name}=(", *_wrap(value, indent + "    "), f"{indent}),"]
    if isinstance(value, tuple):
        lines = [f"{indent}{name}=("]
        lines.extend(f"{indent}    {_value(member)}," for member in value)
        lines.append(f"{indent}),")
        return lines
    return [f"{indent}{name}={rendered},"]


def _flag_lines(flag: Flag, indent: str) -> list[str]:
    """One `Argument(...)` call, always exploded, so `ruff format` leaves it alone.

    A magic trailing comma keeps a call exploded under every formatter setting this repository
    uses, which makes the emitted text a fixed point of `ruff format` without the generator having
    to model the formatter's line-fitting rules.
    """
    lines = [f"{indent}Argument("]
    inner = indent + "    "
    lines.extend(_field_lines("spelling", flag.spelling, inner))
    for name in ("kind", "nargs", "metavar", "choices", "default"):
        value = getattr(flag, name)
        if value is None or (name == "kind" and value == "str"):
            continue
        lines.extend(_field_lines(name, value, inner))
    if flag.help:
        lines.extend(_field_lines("help", flag.help, inner))
    lines.append(f"{indent}),")
    return lines


_HEADER: Final[str] = '''"""`ow`'s argparse tree. GENERATED by `ow surface emit`; do not edit.

Artefact 3 of the seven (10 section 2.3), generated from `omniweave.surface.registry.ACTIONS` by
`omniweave.gen.cli_tree` and byte-diff gated by G25. A hand edit here is a build failure, and the
change you want belongs in `ACTIONS` or in the generator.

`build_parser()` walks `COMMANDS` and returns the parser `ow --help` renders. It parses and does
not dispatch: `set_defaults` records the `ACTIONS` name each command resolves to under
`{action_dest}`, which is 02:719's step 1, and steps 2-9 belong to the runtime.
"""

from __future__ import annotations

import argparse
from typing import Any, Final, NamedTuple

__all__ = [
    "ACTION_DEST",
    "COMMANDS",
    "GLOBAL_FLAGS",
    "GROUP_HELP",
    "PROG",
    "Argument",
    "Command",
    "build_parser",
]

PROG: Final[str] = "ow"
"""18:874: *"`ow` and `omniweave` are the same console script; there is no other alias."*"""

ACTION_DEST: Final[str] = "{action_dest}"
"""The parsed-namespace key carrying the `ACTIONS` name this command resolves to."""

GROUP_DEST: Final[str] = "ow_group"
VERB_DEST: Final[str] = "ow_verb"


class Argument(NamedTuple):
    """One positional or option, as `build_parser` hands it to argparse."""

    spelling: tuple[str, ...]
    kind: str = "str"
    nargs: str | None = None
    metavar: str | None = None
    choices: tuple[str, ...] | None = None
    default: object = None
    help: str = ""


class Command(NamedTuple):
    """One `ow` command: its words, the Actions it dispatches, and its published arguments."""

    words: tuple[str, ...]
    actions: tuple[str, ...]
    help: str
    arguments: tuple[Argument, ...]
'''

_BUILDER: Final[str] = '''

def _add(parser: argparse.ArgumentParser, argument: Argument, *, suppress: bool = False) -> None:
    """Add one `Argument` to one parser, translating `kind` into argparse's vocabulary."""
    options: dict[str, Any] = {}
    if argument.kind == "switch":
        options["action"] = "store_true"
    elif argument.kind == "count":
        options["action"] = "count"
    else:
        if argument.kind == "int":
            options["type"] = int
        if argument.nargs is not None:
            options["nargs"] = argument.nargs
        if argument.metavar is not None:
            options["metavar"] = argument.metavar
        if argument.choices is not None:
            options["choices"] = list(argument.choices)
    if suppress:
        options["default"] = argparse.SUPPRESS
    elif argument.default is not None:
        options["default"] = argument.default
    if argument.help:
        options["help"] = argument.help
    parser.add_argument(*argument.spelling, **options)


def _common(*, defaults: bool) -> argparse.ArgumentParser:
    """The global flags as a parent parser. Built twice, and the second time with no defaults.

    18:887 says the eight are *"accepted before or after the verb, on every command"*, and argparse
    makes the second half a trap rather than a setting: a subparser applies its OWN defaults after
    the root has parsed, so `ow --render json query "..."` is silently overwritten by the
    subparser's `text` unless the subparser declines to have a default at all. `argparse.SUPPRESS`
    is that declining -- the attribute is set only when the flag is actually written -- and the
    root's copy carries the real defaults.
    """
    common = argparse.ArgumentParser(add_help=False)
    for flag in GLOBAL_FLAGS:
        _add(common, flag, suppress=not defaults)
    return common


def build_parser() -> argparse.ArgumentParser:
    """The parser `ow --help` renders. Pure: it reads `COMMANDS` and touches nothing else."""
    root = argparse.ArgumentParser(
        prog=PROG, parents=[_common(defaults=True)], description=DESCRIPTION
    )
    inherited = _common(defaults=False)
    nodes: dict[tuple[str, ...], argparse.ArgumentParser] = {(): root}
    holders: dict[tuple[str, ...], Any] = {}
    for command in COMMANDS:
        for depth in range(1, len(command.words)):
            branch = command.words[:depth]
            if branch not in nodes:
                _open(nodes, holders, branch, GROUP_HELP.get(branch[-1], ""), inherited)
        node = _open(nodes, holders, command.words, command.help, inherited)
        for argument in command.arguments:
            _add(node, argument)
        node.set_defaults(**{ACTION_DEST: command.actions[0]})
    return root


def _open(
    nodes: dict[tuple[str, ...], argparse.ArgumentParser],
    holders: dict[tuple[str, ...], Any],
    words: tuple[str, ...],
    help_text: str,
    inherited: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """The parser for `words`, creating its parent's subparser group on first use."""
    parent_words = words[:-1]
    holder = holders.get(parent_words)
    if holder is None:
        holder = nodes[parent_words].add_subparsers(
            dest=VERB_DEST if parent_words else GROUP_DEST,
            metavar="<verb>" if parent_words else "<group>",
        )
        holders[parent_words] = holder
    node = holder.add_parser(
        words[-1],
        parents=[inherited],
        help=help_text,
        description=help_text,
    )
    nodes[words] = node
    return node
'''


def render() -> bytes:
    """`omniweave/cli/__init__.py`'s committed bytes. Artefact 3's entry in `emit.RENDERERS`.

    Pure: `ACTIONS`, `INPUT_SCHEMAS` and the tables above, and no clock, path or environment.
    10:228 fixes the encoding -- *"`\\n`-terminated UTF-8 with no BOM"* -- and the last line ends
    the builder, so the trailing newline is the one this function adds.
    """
    lines: list[str] = [_HEADER.format(action_dest=ACTION_DEST).rstrip("\n"), ""]
    lines.append("")
    lines.extend(
        [
            "DESCRIPTION: Final[str] = (",
            *_wrap(
                "omniweave -- ask indexed documents a question and get cited passages back.",
                "    ",
            ),
            ")",
            "",
            "GLOBAL_FLAGS: Final[tuple[Argument, ...]] = (",
        ]
    )
    for flag in GLOBAL_FLAGS:
        lines.extend(_flag_lines(flag, "    "))
    lines.extend([")", "", "GROUP_HELP: Final[dict[str, str]] = {"])
    for root, verbs in group_help().items():
        lines.append(f"    {_literal(root)}: {_literal(verbs)},")
    lines.extend(["}", "", "COMMANDS: Final[tuple[Command, ...]] = ("])
    for words, names, summary, flags in commands():
        lines.append("    Command(")
        lines.extend(_field_lines("words", words, "        "))
        lines.extend(_field_lines("actions", names, "        "))
        lines.extend(_field_lines("help", summary, "        "))
        if not flags:
            lines.append("        arguments=(),")
        else:
            lines.append("        arguments=(")
            for flag in flags:
                lines.extend(_flag_lines(flag, "            "))
            lines.append("        ),")
        lines.append("    ),")
    lines.append(")")
    lines.append(_BUILDER.rstrip("\n"))
    text = "\n".join(lines)
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8") + b"\n"
