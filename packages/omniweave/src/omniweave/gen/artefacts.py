"""The seven agent-facing artefacts, as a register. 10 section 2.3; 02-architecture.md row 31.

10:202 is the sentence this file makes checkable: *"`ow surface emit` writes all seven;
`ow surface emit --check` byte-diffs them, CRLF-normalised, and fails CI (gate G25)."* Seven rows,
each carrying what it is generated from, who consumes it, where it lands and whether a renderer for
it exists yet.

## WHY A REGISTER AND NOT SEVEN FUNCTIONS

`tools/schemagen.py` already proved the shape one gate over: an inventory of thirteen `SchemaSource`
rows, each resolving to `live`, `pending`, `deferred` or `unresolved`, and a `--check` that refuses
a committed file for a row nothing can produce. That refusal is the half most emitters leave out,
and it is the half that matters before the renderers exist -- without it, a hand-written `llms.txt`
committed today would sit in the tree looking generated until the day something tried to generate
it. LEANN's `llms.txt` is G25's named defect (00:851) and it is precisely a hand-written file that
looked generated.

So the register ships before six of the seven renderers do, and `check()` is already a gate: it
fails on a committed file for a `PENDING` row.

## TWO OF THE SEVEN HAVE NO PATH, AND ONE OF THEM HAS NO FILE AT ALL

Artefact 3 is *"the CLI argparse tree"*, which 11:246 homes at `omniweave/cli/` -- a package, not a
file, so its byte-diff is over a tree and its renderer is W7.2's largest.

Artefact 2 is *"the MCP `instructions` string, two variants"*, and **no document gives it a path**.
It is delivered on `initialize` rather than written, and what the plan gates it with is a
measurement: `benchmarks/serve_schema_baseline.json` freezes
`"instructions_chars": {"default": 977, "no_corpus": 996}` (10:2596) and 10:909 puts the cap in
`tests/test_instructions.py`. So 10:202's *"writes all seven"* is six, and the `path`
column below says which one it is not, per row rather than in prose. D314 is the entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "ARTEFACTS",
    "Artefact",
    "State",
    "by_number",
    "path_carrying",
]


class State(StrEnum):
    """Whether a renderer for this artefact exists in this build.

    Two members and not `tools/schemagen.py`'s four. Its `deferred` and `unresolved` both describe a
    declaration site that may or may not have landed, which is a question about `schema/*.json`'s
    thirteen Python symbols; an agent-facing artefact has no declaration site to resolve -- it has a
    renderer or it does not.
    """

    LIVE = "live"
    """A renderer exists. `check()` byte-diffs it, or measures it where there is no path."""

    PENDING = "pending"
    """No renderer yet. `check()` asserts that no file is committed at its path, which is the
    clause that makes a hand-written artefact a build failure rather than a surprise."""


@dataclass(frozen=True, slots=True)
class Artefact:
    """One row of 10:206's table, plus where it lands and whether it can be produced."""

    number: int
    """1-7, 10:206's own numbering. Kept because every other document cites the artefacts by it."""

    name: str
    """10:206's `artefact` cell, verbatim."""

    path: str | None
    """Repository-relative, or `None` for an artefact that is not a file. See the docstring."""

    source: str
    """10:206's `generated from` cell: the `ActionSpec` fields a renderer may read, and no more."""

    consumer: str
    """10:206's `consumed by` cell. It is here because it is the argument for the artefact's
    existence, and a renderer that cannot name its reader is a renderer nobody asked for."""

    state: State

    lands_with: str
    """The work item that makes `state` `LIVE`. 16:716 schedules all seven under W7.2."""


ARTEFACTS: Final[tuple[Artefact, ...]] = (
    Artefact(
        number=1,
        name="schema/mcp-tools-v1.json",
        path="schema/mcp-tools-v1.json",
        source="mcp_name, listed_in, the four booleans, inp, summary, decision, example, advanced",
        consumer="the MCP server's tools/list",
        state=State.LIVE,
        lands_with="W7.2b",
    ),
    Artefact(
        number=2,
        name="the MCP instructions string, two variants",
        path=None,
        source="the listed set plus decision clauses",
        consumer="initialize, on a track that survives tool deferral",
        state=State.LIVE,
        lands_with="W7.2a",
    ),
    Artefact(
        number=3,
        name="the CLI argparse tree",
        path="packages/omniweave/src/omniweave/cli",
        source="cli tuples plus inp fields",
        consumer="ow --help, shell completion",
        state=State.PENDING,
        lands_with="W7.2c",
    ),
    Artefact(
        number=4,
        name="omniweave/sdk/_generated.pyi",
        path="packages/omniweave/src/omniweave/sdk/_generated.pyi",
        source="inp, out, name",
        consumer="mypy, IDEs, ow surface typescript",
        state=State.PENDING,
        lands_with="W7.2d",
    ),
    Artefact(
        number=5,
        name="llms.txt",
        path="llms.txt",
        source="every Action with an mcp_name",
        consumer="an agent with a shell and no MCP client",
        state=State.PENDING,
        lands_with="W7.2e",
    ),
    Artefact(
        number=6,
        name="docs/AGENTS.md",
        path="docs/AGENTS.md",
        source="all Actions, summary inline",
        consumer="an agent asked to work on omniweave",
        state=State.PENDING,
        lands_with="W7.2e",
    ),
    Artefact(
        number=7,
        name="skills/omniweave/references/actions.md",
        path="skills/omniweave/references/actions.md",
        source="Actions with an mcp_name, grouped by cli[0]",
        consumer="the router skill's catalog",
        state=State.PENDING,
        lands_with="W7.2f",
    ),
)
"""10:206's seven rows, in that table's order.

The `source` column is a constraint and not a comment. 10:216 forbids the renderer for artefact 1
from branching on a boolean's VALUE -- *"a missing key would mean the generator branched, and G25's
byte-diff would be gating a shape nobody declared"* -- and the same discipline reads sideways: a
renderer that read a field its row does not name would make the register wrong about what changes
force a re-bless.

`lands_with` splits W7.2 into cells rather than restating 16:716's single row, because seven
generators at ~0.6 ew are not one commit and a register that claimed they were would be a schedule
nobody could check against.
"""


def by_number(number: int) -> Artefact:
    """One artefact by 10:206's numbering, which is how every other document cites them."""
    for artefact in ARTEFACTS:
        if artefact.number == number:
            return artefact
    raise KeyError(f"there are seven artefacts, numbered 1-7; {number} is not one of them")


def path_carrying() -> tuple[Artefact, ...]:
    """The artefacts `check()` can reach on disk: the six with a path.

    Named as a function rather than as a second tuple so there is one roster and one derivation of
    it. The count is six, 10:202 says seven, and the module docstring says which one is missing.
    """
    return tuple(artefact for artefact in ARTEFACTS if artefact.path is not None)
