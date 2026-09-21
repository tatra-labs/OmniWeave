"""Artefact 6, `docs/AGENTS.md`: the file an agent asked to work ON omniweave reads. 10:213.

10:206's sixth row is three cells and no printed block: *"`docs/AGENTS.md` | all Actions, `summary`
inline | an agent asked to work *on* omniweave"*. 18:997 adds the only other requirement any
document makes of it -- *"`ow surface emit` generates it into `docs/AGENTS.md`"*, of the twelve-row
exit table. Nothing else anywhere prints a line of this artefact.

So this is the first renderer that is a DESIGN cell rather than a transcription cell, and the
discipline that replaces a printed block is stated here rather than left to the reader: **every
section is derived from a declaration site, and the four that are not are counted at the bottom of
this docstring.** D328's closing measurement is the reason -- `llms.txt` shipped 165 entries of
which 128 are derived, and the twenty-six that are neither derived nor test-bound are the part of
that file a second author wrote. A file with no printed block can be all second author if nobody
counts.

## WHAT THIS ARTEFACT IS FOR, AND HOW THAT DECIDES WHAT IS IN IT

Its consumer is not an agent USING omniweave -- that is artefact 5's reader, who has a shell and no
MCP client, and artefact 1's, who has a client. This one's reader is *"an agent asked to work **on**
omniweave"*: it is editing this repository. Three things follow, and each is a section:

* **The one rule it can break without noticing is INV-20.** A coding agent's most natural act is to
  edit the file in front of it, and seven files in this tree are generated and byte-diff gated. So
  the artefact register is the FIRST section, it names every path, and it says what `PENDING` means
  -- that nothing may be committed at that path at all, which is the LEANN shape (00:851) and is
  not a rule anyone would guess.
* **The Action table is the capability roster.** 10:213's `generated from` cell is *"all Actions"*,
  which is a wider row set than artefact 5's *"every Action with an `mcp_name`"* and than artefact
  7's *"Actions with an `mcp_name`, grouped by `cli[0]`"*. All three differ, and this one is the
  only one that shows a reader an Action no agent surface can reach.
* **`summary` and NOT `decision`.** The source cell names one prose field. `decision` is the
  pick-time disambiguator two agent surfaces already publish (artefacts 1 and 5), and a reader
  editing the registry does not pick between tools -- so publishing it here would be a fourth copy
  bought for nothing. D328's ratio is the argument.

## THE SOURCE COLUMN IS A CONSTRAINT, AND THIS ROW HAS TWO SOURCES

`gen/artefacts.py` states the rule: *"a renderer that read a field its row does not name would make
the register wrong about what changes force a re-bless."* This row's cell says *"all Actions,
`summary` inline"*, and 18:997 puts the exit table in the same file. Two documents, one artefact,
and the register carries one source. D333 is the entry.

The reading applied here is the one `llms.py` already ships under: the `source` cell selects the
ROWS and names the prose field, and a fact another document puts in the artefact arrives through
the module that declares it, with the binding stated. So `mcp_name`, `cli`, `listed_in` and
`cost_class` are read from the same rows, and the exit table comes from
`omniweave_core.errors.EXIT_CODES` -- which W7.2f moved out of `gen/llms.py` for this artefact's
sake and which `check_register()` now holds `codes.toml` to. D329 was the entry; D332 is the move.

## A PIPE IS ESCAPED AND A NEWLINE IS REFUSED

Every cell here goes into a Markdown table, and two characters can break one. They are treated
differently on purpose. A `|` has a legitimate use in a `summary` -- `--render text|json|jsonl` is
how the CLI's own help spells a choice set -- so it is escaped, which renders as the character the
writer meant. A newline has no legitimate use in a 160-character one-line summary, and a renderer
that silently joined one would publish a cell nobody wrote; `_table_failures()` raises at import
instead, which is `_manifest_failures()`'s shape one artefact over.

## THE COUNT

Five sections, and four of them are a table derived whole: the artefact register from
`gen.artefacts.ARTEFACTS`, the Action table and the human-only roster from `ACTIONS` and
`HUMAN_ONLY`, the exit table from `omniweave_core.errors.EXIT_CODES`. Every row of all four moves
when a declaration moves, and none of them can be edited into agreement with anything.

The fifth is not derived. The CLI grammar's three rules are 10:236's and 16:716's sentences, and
`MIN_GROUP_VERBS` is the only numeral in them -- imported, because it is the one fact in the
section that `cli_tree.py` already enforces. The five paragraphs that introduce the tables and the
header are the rest of the prose; the product sentence is `llms.SUMMARY`, which is one home and
two artefacts rather than a second transcription.

**No section prints a count of its own table.** 10:1457 refuses a verb count for `ow store` --
*"a numeral is a second copy of an enumeration and drifts from it in silence"* -- so *"seven
artefacts"*, *"eleven checks"* and *"twelve exit codes"* are all absent from the output, and the
reader counts rows. D293 is where that rule comes from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.errors import EXIT_CODES, SurfaceError

from omniweave.gen.artefacts import ARTEFACTS, Shape, State
from omniweave.gen.cli_tree import MIN_GROUP_VERBS
from omniweave.gen.llms import PRODUCT, SUMMARY
from omniweave.gen.wrap import wrapped
from omniweave.surface.registry import ACTIONS, HUMAN_ONLY

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from omniweave.gen.artefacts import Artefact
    from omniweave.surface.registry import ActionSpec

__all__ = [
    "ABSENT",
    "REGISTRY_PATH",
    "WIDTH",
    "action_rows",
    "artefact_rows",
    "exit_rows",
    "render",
]


WIDTH: Final[int] = 96
"""The column prose wraps at. The plan documents' own measure, and not a table's.

A Markdown table row cannot be wrapped -- a break inside one ends the row -- so only the prose
paragraphs pass through `_wrapped()`. The table lines are as long as their widest cell, which for
the Action table is a 160-character `summary` plus five short cells, and that is correct output
rather than a line this module failed to fold.
"""

ABSENT: Final[str] = "—"
"""The em dash that fills a cell with no value. One spelling, because a table that used `-` in one
column and `none` in another would be publishing this renderer's mood."""

REGISTRY_PATH: Final[str] = "packages/omniweave/src/omniweave/surface/registry.py"
"""Where an editor goes to change any of it. The one path this artefact names that no register
holds: 11:247 homes the module and `ARTEFACTS` carries the paths of the seven OUTPUTS, not of the
declaration they are generated from. `test_gen_agents.py` asserts the file is there."""


# =============================================================================================
# 1. Cells
# =============================================================================================


def _cell(text: str) -> str:
    """One table cell. A pipe is escaped; the caller has already refused a newline.

    `str.replace` and not a regex: there is exactly one character to escape and a pattern would
    be a second place to look when a third one appears.
    """
    return text.replace("|", "\\|")


def _row(cells: Iterable[str]) -> str:
    """One Markdown table row, pipe-delimited and padded by one space on each side."""
    return "| " + " | ".join(cells) + " |"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    """A whole Markdown table: the header, the rule, the rows. No column alignment.

    Unaligned because padding a column to its widest cell would make every row of the Action
    table move when one `summary` grows by a character, and G25's diff is what a reviewer reads.
    """
    return [
        _row(headers),
        _row("---" for _ in headers),
        *(_row(row) for row in rows),
    ]


def _wrapped(text: str, indent: str = "") -> list[str]:
    """One paragraph, wrapped at `WIDTH`. Pure, and the only text here that is not a table.

    `gen.wrap` holds the mechanism, because artefact 7 wraps prose to the same contract and a
    second copy is the one that stops matching the first. What stays here is the column: `WIDTH`
    is this artefact's choice and not the wrapper's.
    """
    return wrapped(text, width=WIDTH, indent=indent)


def _item(marker: str, text: str) -> list[str]:
    """One list item, wrapped, with its continuation lines under the text rather than the marker.

    The indent is the marker's own width, which is how a Markdown list nests: a continuation
    line indented less than the marker ends the item, and one indented more opens a code block.
    """
    return _wrapped(f"{marker} {text}", indent=" " * (len(marker) + 1))


# =============================================================================================
# 2. The rows, each from one declaration site
# =============================================================================================


def _artefact_path(artefact: Artefact) -> str:
    """An artefact's path as this file publishes it: a directory carries its slash.

    Artefact 3 is a `TREE` (11:246 homes the argparse tree at a package) and artefact 2 has no
    path at all, which is D314. Both facts are the register's and neither is restated here.
    """
    if artefact.path is None:
        return ABSENT
    suffix = "/" if artefact.shape is Shape.TREE else ""
    return f"`{artefact.path}{suffix}`"


def _artefact_state(artefact: Artefact) -> str:
    """What `ow surface emit --check` does with this row today.

    The `PENDING` half is the sentence this artefact exists to carry. 00:851 makes LEANN's
    hand-written `llms.txt` G25's named defect, and `emit.check()`'s third clause is the guard:
    a file committed at a `PENDING` row's path fails the build. A reader who did not know that
    would create the file, see no renderer, and assume it was theirs to write.
    """
    if artefact.state is State.LIVE:
        return "generated"
    return f"**pending {artefact.lands_with}** — nothing may be committed at this path"


def artefact_rows() -> tuple[tuple[str, ...], ...]:
    """10:206's seven rows, in that table's order, as cells.

    Whole from `gen.artefacts.ARTEFACTS`, which is that table transcribed once. A second
    transcription here would be a register describing a register.
    """
    return tuple(
        (
            str(artefact.number),
            _cell(artefact.name),
            _artefact_path(artefact),
            _cell(artefact.source),
            _cell(artefact.consumer),
            _artefact_state(artefact),
        )
        for artefact in ARTEFACTS
    )


def _spelling(spec: ActionSpec) -> str:
    """The Action's CLI command. Check 9 makes `cli` non-empty, so there is always one."""
    return f"`ow {' '.join(spec.cli)}`" if spec.cli else ABSENT


def action_rows() -> tuple[tuple[str, ...], ...]:
    """Every Action, sorted by `name`, with `summary` inline. 10:213's cell.

    Sorted rather than declaration-ordered: 10:225 fixes it -- *"Actions by `name`"* -- and this
    artefact has no second projection to sort under, unlike `cli_tree.commands()`, whose key is
    the SPELLING because two Actions can share one.

    `mcp_name` is `—` for an Action no agent surface can reach, and that is the structural claim
    10:1540 makes: *"`mcp_name = None` is structural, not a denylist"*. `listed_in` is then empty
    by check 5, so the two columns read as one fact rather than as two coincidences.
    """
    return tuple(
        (
            f"`{name}`",
            f"`{spec.mcp_name}`" if spec.mcp_name else ABSENT,
            _spelling(spec),
            ", ".join(sorted(spec.listed_in)) if spec.listed_in else ABSENT,
            f"`{spec.cost_class.value}`",
            _cell(spec.summary),
        )
        for name, spec in sorted(ACTIONS.items())
    )


def human_only_rows() -> tuple[tuple[str, ...], ...]:
    """`HUMAN_ONLY`'s five, sorted, each with its row's summary or the fact that it has none.

    The second column is a roster DISTANCE and it is published rather than hidden: `ACTIONS`
    carries no human-only row today, so all five read *"no ActionSpec row yet"*, and the day one
    lands this artefact's diff is where a reviewer sees it. `registry._unrostered_human_only()`
    reports the same gap one package over and a test asserts the two agree.
    """
    return tuple(
        (
            f"`{name}`",
            _cell(ACTIONS[name].summary) if name in ACTIONS else "no `ActionSpec` row yet",
        )
        for name in sorted(HUMAN_ONLY)
    )


def exit_rows() -> tuple[tuple[str, ...], ...]:
    """18:997's twelve rows, three columns, from `omniweave_core.errors.EXIT_CODES`.

    Not a constant in this module, and that is the whole of D332: the table's home is
    `codes.toml` (18:996), a generator may not read a file (10:229), so the form code reads is a
    tuple in the module that owns the exit map and `check_register()` holds the register to it.
    `derived_from()` is that module's own join of the two halves of the third column.
    """
    return tuple(
        (str(row.code), _cell(row.meaning), _cell(row.derived_from())) for row in EXIT_CODES
    )


# =============================================================================================
# 3. What cannot be rendered
# =============================================================================================


def _table_failures() -> tuple[str, ...]:
    """Every reason this artefact could not be rendered honestly. Raised at import.

    Two clauses, and neither is checked anywhere else:

    1. **An empty registry.** `ACTIONS` is a `Mapping` and nothing requires it to be non-empty;
       a file published under this name saying omniweave has no capabilities is LEANN's defect
       at full strength, and it would render as a table with a header and no rows -- which reads
       as a document rather than as a failure.
    2. **A cell with a line break.** Check 7 caps `summary` at 160 characters and forbids a
       trailing full stop; it says nothing about a newline, and a newline in any published cell
       ends the table row early and turns the rest of the summary into a paragraph. Refused
       rather than joined, because joining publishes a sentence nobody wrote.
    """
    findings: list[str] = []
    if not ACTIONS:
        findings.append(
            "the Action registry is empty, so this artefact would publish a capability table "
            "with no capabilities in it"
        )
    for name, spec in sorted(ACTIONS.items()):
        published = (("summary", spec.summary), ("mcp_name", spec.mcp_name or ""))
        findings.extend(
            f"{name}: {field} contains a line break, which ends a Markdown table row"
            for field, text in published
            if "\n" in text or "\r" in text
        )
    return tuple(findings)


_FAILURES: Final[tuple[str, ...]] = _table_failures()
if _FAILURES:  # pragma: no cover -- the shipped registry agrees with itself; a test builds one
    raise SurfaceError(
        "docs/AGENTS.md cannot be rendered from this registry: " + "; ".join(_FAILURES),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix=f"fix every row named above in {REGISTRY_PATH}",
    )


# =============================================================================================
# 4. The bytes
# =============================================================================================


def render() -> bytes:
    """`docs/AGENTS.md`, whole. Pure: the artefact register, `ACTIONS`, the exit table.

    10:232 fixes the encoding -- *"Output is `\\n`-terminated UTF-8 with no BOM"* -- and the
    final newline is added here so no section has to remember it.

    **No section prints a count.** 10:1457 refuses a verb count for `ow store` because *"a
    numeral is a second copy of an enumeration and drifts from it in silence"*, and every
    enumeration this file publishes is a table directly under the sentence that introduces it --
    so *"seven artefacts"*, *"eleven checks"* and *"twelve exit codes"* are all absent, and the
    reader counts rows. D293 is the entry that rule comes from.
    """
    lines: list[str] = [
        f"# AGENTS.md — {PRODUCT}",
        "",
        *_wrapped(
            "**GENERATED** by `ow surface emit` from `omniweave.surface.registry`, and "
            "byte-diff gated by G25. Do not edit this file: `ow surface emit --check` fails on "
            "a hand edit and the next `ow surface emit` overwrites it. Change "
            f"`{REGISTRY_PATH}` and re-emit."
        ),
        "",
        *_wrapped(f"**{PRODUCT}** — {SUMMARY}"),
        "",
        "## Nothing agent-facing is written by hand",
        "",
        *_wrapped(
            "INV-20, gate G25. The artefacts below are generated from the one `ActionSpec` set "
            "and byte-diff gated, so a capability is declared once and every surface that "
            "publishes it is rendered from that declaration. To add or change one:"
        ),
        "",
        *_item(
            "1.",
            f"edit the `ActionSpec` in `{REGISTRY_PATH}`. Its checks run at import and "
            "name every failing row at once.",
        ),
        *_item(
            "2.",
            "run `ow surface emit`, which rewrites every artefact below and leaves the "
            "diff for review.",
        ),
        *_item(
            "3.",
            "`ow surface emit --check` is G25. It fails CI on any artefact whose bytes "
            "differ from what the generator produces.",
        ),
        "",
        *_table(
            ("#", "artefact", "path", "generated from", "consumed by", "state"),
            artefact_rows(),
        ),
        "",
        *_wrapped(
            "The `state` column has two values, and the second carries the rule that is not "
            "guessable: a **pending** artefact is one no renderer produces yet, and nothing may "
            "be committed at its path at all. A hand-written file sitting where a generator has "
            "not landed is the defect G25 is named after, and `--check` fails on it."
        ),
        "",
        "## Actions",
        "",
        *_wrapped(
            "Every Action this build declares, with its `summary` inline. An Action with no MCP "
            "tool name is unreachable from every agent surface by construction rather than by "
            "policy, and no configuration key can grant one."
        ),
        "",
        *_table(
            ("Action", "MCP tool", "CLI", "listed in", "cost", "summary"),
            action_rows(),
        ),
        "",
        "## Human-only Actions",
        "",
        *_wrapped(
            "These names are declared human-only. Each must carry `mcp_name = None` and an "
            "empty `listed_in`, and naming one in the `enabled` configuration key is a startup "
            "error rather than a warning — the point of an absent MCP name is that no key "
            "grants it."
        ),
        "",
        *_table(("Action", "summary"), human_only_rows()),
        "",
        "## Exit codes",
        "",
        *_wrapped(
            "Every non-zero exit prints the code, the message and the fix command — never "
            "a traceback. The exit code is a pure function of the exception class, which is why "
            "the rows below that name no class name what they are instead: a verdict, a gate "
            "status or a detection result is not raised."
        ),
        "",
        *_table(("code", "meaning", "derived from"), exit_rows()),
        "",
        "## The CLI grammar",
        "",
        *_item(
            "-", f"`ow <group> <verb>`, and a group exists only at {MIN_GROUP_VERBS} or more verbs."
        ),
        *_item(
            "-",
            "No two groups differ only by a trailing `s`. G25 asserts it, because one "
            "of the two would silently win.",
        ),
        *_item(
            "-",
            "There are no aliases. A capability has one name, and a rejected spelling "
            "is registered as rejected rather than left out.",
        ),
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
