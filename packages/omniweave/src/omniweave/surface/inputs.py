"""The input type of every listed Action -- one dataclass per published `inputSchema`.

`ActionSpec.inp` is a `type` (10:137), and four of the seven generated artefacts read it: the MCP
tool schema (10:208), the CLI argparse tree (10:210 -- *"`cli` tuples plus `inp` fields"*), the SDK
stubs (10:211) and `_DECLARED_ARG_KEYS` (10:500). A surface that declared its parameters in seven
places would be the defect INV-20 exists to prevent, arrived at from the inside, so the parameters
are declared once, here, as ordinary frozen dataclasses.

## DECLARATION ORDER IS THE PUBLISHED ORDER

10:231 fixes it: *"schema properties in declaration order (which is `dataclasses.fields` order,
itself stable)"*. Every class below is therefore written in the order 18:1258's published
`inputSchema` prints its properties, and reordering a field is a wire change that G25's byte-diff
will show. That is the whole reason the order is stated rather than left to a sort: a sorted schema
would put `corpus` before `query` and bury the one required parameter under an optional one.

## WHAT IS NOT HERE, AND WHY EACH ABSENCE IS DELIBERATE

- **No `refs` and no `schema` on `QueryIn`** (18:1322). Reference-shaped tokens are lifted into
  `Query.refs` by 07 section 5.2's sanitisation before the residue reaches FTS5, so an agent that
  pastes `d7#412` inside a question already has the identity channel; and a JSON Schema is an
  ingest-time fact, which is why `--schema` is a flag on `ow add`. 18:980 records that an earlier
  draft put it on `query` and calls that *"the single most consequential error a caller could
  inherit from an API reference"*.
- **No `corpora` list anywhere.** 10:388: *"One query addresses one corpus"*. The cross-corpus
  fan-out is the CLI's `--corpus a,b` and the SDK's `omniweave.corpora([...])`, and it is not
  reachable from `ow_query`, *"because a listed tool that silently fans out hides the
  incomparability of cross-corpus BM25 scores"*.
- **No `want_impact` on `OpenIn`** (18:1365). The MCP handler sets it by default when the ref is a
  single block, so one citation gets `ow:impact` without a knob and a 64-ref batch does not pay 192
  joins. A parameter would be a knob for a decision the arity already makes.
- **No `k`, `mode` or `fail_on`.** Those are `ow query` CLI flags (18:910). `want` is a packing
  preset on the surface and *"never changes `Query.mode`"* (10:420), which the planner owns.

## THE LISTED FOUR FIRST, THEN THE NARROW ROWS THAT HAVE LANDED

The first four classes are the `default` profile's, in 10:311's order. The rest are `full`-profile
Actions and arrive one at a time, because `ActionSpec` needs an `inp` AND an `out` and 10:807's
roster has thirteen rows whose output type has no home yet (`registry.py`'s `_unrostered_full()`
names them). An input type written ahead of its row would be a published parameter list nothing
publishes -- dead weight that a reader would reasonably mistake for a shipped surface -- so a class
appears here in the cell that adds its row and not before.

**No narrow input declares `max_chars`.** The two retrievers pack prose into an Answer against
`HARD_CEILING`; every narrow Action here returns rows, and a row set truncated at a character count
would cut a row in half. Where a narrow Action needs a bound it is a row count, and where it needs
none it has none.

## THE BOUNDS ARE CONSTANTS, AND ONE OF THEM IS IMPORTED

Every numeric bound the published schema prints is a `Final` here, so the generator reads the same
integer the handler enforces -- except `HARD_CEILING`, which already has a home in
`omniweave_core.answer.budget` (18:1729, *"one ceiling for every tool"*). `max_chars`' published
`maximum` is that constant and not a copy of it: INV-21 gives a name one home, and a surface that
re-spelled `24_000` would be a second one that drifts silently the day the packing ceiling moves.

A dataclass field carries no bound -- `context: int` does not say 0..8. The bounds live beside the
fields as constants because two consumers need them as values rather than as annotations: the schema
generator prints them, and the handler enforces them *"before any store read"* (10:379). A
validating type would satisfy neither; it would raise at construction, which is after the point
10:453 requires the check to happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.answer.budget import HARD_CEILING as _HARD_CEILING

if TYPE_CHECKING:
    from omniweave.route import RouteHints

__all__ = [
    "CONTEXT_DEFAULT",
    "CONTEXT_MAX",
    "CONTEXT_MIN",
    "CORPORA_DETAILS",
    "HARD_CEILING",
    "MAX_CHARS_MIN",
    "QUERY_MAX_CHARS",
    "REF_MAX",
    "SOURCE_MAX",
    "WANTS",
    "AddIn",
    "CorporaIn",
    "CoverageIn",
    "DiffIn",
    "DoctorIn",
    "ExplainIn",
    "GridIn",
    "HooksCheckIn",
    "InstallIn",
    "OpenIn",
    "QueryIn",
    "SkillsInstallIn",
    "SkillsRemoveIn",
    "UninstallIn",
]


QUERY_MAX_CHARS: Final[int] = 4096
"""`ow_query`'s `query`, 10:374, enforced BEFORE any store read.

10:379 gives two reasons and only the first is jcodemunch's: an unbounded string forces a full FTS5
scan, and *"a 4,096-character question is not a question, it is a pasted document, and the right
answer to it is `ow_add`"*. Over the cap is `OW-A-008`, a success-shaped Answer whose `ow:blocking`
says so -- not a protocol error, because the caller asked a legible question badly rather than
issuing an illegible call.
"""

REF_MAX: Final[int] = 64
"""`ow_open`'s `ref` array bound, 18:1337's `maxItems`, enforced before any store read (10:453)."""

SOURCE_MAX: Final[int] = 256
"""`ow_add`'s `source` array bound, 10:485 and 18:1359's `maxItems`."""

CONTEXT_MIN: Final[int] = 0
CONTEXT_MAX: Final[int] = 8
CONTEXT_DEFAULT: Final[int] = 1
"""`ow_open`'s sibling window, 10:461. Zero is a legal request and means *"no siblings"*."""

MAX_CHARS_MIN: Final[int] = 1000
"""The published `minimum` on both retrievers' `max_chars`, 18:1290.

There is no `MAX_CHARS_MAX` constant beside it. The published `maximum` is `HARD_CEILING`, bound
below, and the effective value is `min(requested, tier.max_chars, HARD_CEILING)` (10:478) -- a
request above the tier is honoured at the tier and disclosed, never refused.
"""

HARD_CEILING: Final[int] = _HARD_CEILING
"""The published `maximum`, re-exported rather than re-spelled. 18:1729, *"one ceiling for every
tool"*.

It is the same object `omniweave_core.answer.budget` defines, bound here so the schema generator
reads the published bounds from one module without importing the packer. `omniweave_core.retrieve`
re-exports `RRF_K` and `SCORER_VERSION` on the same terms and for the same reason (07:1382): a
binding is not a second home, and `24_000` written twice would be."""

WANTS: Final[tuple[str, ...]] = ("passages", "table", "fields", "outline", "related")
"""`want`'s five members in 18:1275's published order, which is 10:424's table order.

10:434: an unknown value is a validation error naming the five, *"never a silent fall-back to
`passages`, because a caller who asked for `table` and got prose has been lied to"*. The default is
the first member, which is why the tuple is ordered rather than a frozenset.
"""

CORPORA_DETAILS: Final[tuple[str, ...]] = ("list", "card", "coverage", "actions")
"""`ow_corpora`'s `detail`, 18:1352. `actions` is how an agent discovers the narrow-Action catalog
(18:1367), which is what makes an unlisted Action reachable without listing it."""


@dataclass(frozen=True, slots=True)
class QueryIn:
    """`ow_query` / `ow query`. 18:1258's published `inputSchema`, in its published order.

    `route_hints` is the one non-scalar field and it is `omniweave.route.RouteHints` rather than a
    surface type of its own. 05:2019 makes that type a RESTRICTION -- it has no `budget`, no
    `egress` and no `licence` field -- which is *"what makes it safe to accept from an agent over
    MCP or the SDK"*. A second, surface-local hint shape would be a rival home for a type whose
    safety property is exactly its field list.

    The published object exposes three of `RouteHints`' five fields (`lane`, `max_rung`,
    `deadline_ms`) under `additionalProperties: false`. That is a narrowing the schema generator
    performs, not a different type: 18:1322 strikes `schema` from this surface by name, and
    `prefer_capability` is a driver-selection hint with no agent-facing meaning.
    """

    query: str
    corpus: str | None = None
    scope: str | None = None
    want: str = WANTS[0]
    route_hints: RouteHints | None = None
    max_chars: int | None = None


@dataclass(frozen=True, slots=True)
class OpenIn:
    """`ow_open` / `ow open`. 18:1335's published `inputSchema`.

    `ref` is `str | tuple[str, ...]` because the schema is a `oneOf` of a string and an array, and
    the singular form is the common one: an agent resolving one citation should not have to wrap it.
    The five ref forms and their resolution order are 10:437's and are enforced by the handler, not
    by this type -- a form that parses but does not resolve continues down the ladder, which is a
    store fact and cannot be decided at construction.

    `layers` is the only path to `Layer.HIDDEN` (10:468), whose `WORTH_LAYER` weight is `0.0`, so no
    other route can pack it into an Answer. It is `advanced` and therefore stripped from the compact
    schema, which 10:471 argues is correct rather than merely cheap: *"an agent that needs hidden
    layers knows it does"*.
    """

    ref: str | tuple[str, ...]
    corpus: str | None = None
    context: int = CONTEXT_DEFAULT
    layers: tuple[str, ...] | None = None
    max_chars: int | None = None


@dataclass(frozen=True, slots=True)
class CorporaIn:
    """`ow_corpora` / `ow corpora`. 18:1349's published `inputSchema`.

    Two optional parameters and no `advanced` member, which is why 10:356 records that this tool is
    *"unchanged by compaction"* -- and why it is still the second-cheapest of the four at 189 tokens
    despite carrying the longest description in the set. Prose compresses at ~3.2 chars/token and
    JSON Schema does not.

    `summarize` is absent by construction and not by omission. 10:90 works the decision: the
    abstract is returned by this tool's own payload, so *"an agent that could write it could write
    the prose its own next call reads"*. It is the CLI's `ow corpora --summarize`, one flag on the
    human surface, and `abstract_producer` records which model wrote it when one did.
    """

    corpus: str | None = None
    detail: str = CORPORA_DETAILS[0]


@dataclass(frozen=True, slots=True)
class AddIn:
    """`ow_add` / `ow add`. 18:1356's published `inputSchema`.

    The one listed writer, and the parameter that is NOT here is why it survives 10:54's row 2:
    there is no `allow_cost`. 10:1131 states it -- *"`ow add --allow-cost <micros>` is the approval
    path and is CLI-only, because `RouteHints` correctly has no budget field"*. Billable work
    defers rather than spends, and the response carries the pending cost with the exact command that
    approves it, which is the `Degradation`-shaped deferral row 2 asks for.

    `dry_run` is `advanced` and returns the same `add-out-v1` shape with `queued = 0` and a
    populated `pending` (10:487), *"so a caller can price an ingest without starting one"*.
    """

    source: str | tuple[str, ...]
    corpus: str | None = None
    dry_run: bool = False


# =============================================================================================
# The `full` profile's inputs. One class per landed row; 10:807's table order.
# =============================================================================================


@dataclass(frozen=True, slots=True)
class GridIn:
    """`ow_grid` / `ow doc grid`. 10:808.

    `ref` addresses a table, and the resolution ladder is `ow_open`'s (10:437) rather than a second
    one: a `d7#412` cite, a `p14/3` address or a path all reach a block, and a block that is not a
    table is `OW-A-002`, naming the `Kind` it actually is. The alternative -- a `doc` plus a table
    ordinal -- was not taken because an agent reading an Answer holds a cite and has never seen an
    ordinal, and a parameter nothing in the payload supplies is a parameter that cannot be filled.

    There is no `max_rows`. `Grid.slot(r, c)` is O(1) over a cover that was built at ingest
    (03 section 9), so the cost of the whole table is the cost of the rows the caller reads, and a
    truncation knob would have to cut either a row or a column -- both of which change what the
    exactly-once cover MEANS. The bound that exists is the packer's, one layer up.
    """

    ref: str
    corpus: str | None = None


@dataclass(frozen=True, slots=True)
class DiffIn:
    """`ow_diff` / `ow doc diff`. 10:819.

    Two optional generations, and the default pair is the one an operator wants: `to_gen` defaults
    to the head and `from_gen` to the generation before it, because 03:1302 puts this Action's whole
    reason in the quarantine path -- a `rebind()` below threshold leaves a generation *"durable and
    invisible for inspection by `ow doc diff`"*, and the generation a reader wants to inspect is the
    one that was just refused.

    Both are `advanced`, so the compact schema publishes a document and nothing else. That is the
    §3.3 strip working as designed rather than a narrowing: the handler honours a `from_gen` a host
    forwards unvalidated, and `_DECLARED_ARG_KEYS` is snapshotted before the strip so neither is
    ever reported unknown.
    """

    ref: str
    corpus: str | None = None
    from_gen: int | None = None
    to_gen: int | None = None


@dataclass(frozen=True, slots=True)
class CoverageIn:
    """`ow_coverage`. 10:818, and its CLI twin is `ow corpora --detail coverage` (10:1424).

    The two parameters are `ow_query`'s first two, and deliberately the same two spellings: this is
    the Action an agent reaches for when `ow_query` returned `absent`, and a scope that had to be
    re-spelled to ask *"what is missing from what I just searched?"* would be a second scope grammar
    to get wrong. 10:388's one-query-one-corpus rule applies here for the same reason -- a coverage
    report over two corpora would sum counts nothing can join.

    Everything it returns is derived, which is why it has no `detail` knob: the gap list IS the
    `diag` roll-up (10:1085) and the counts ARE `ingest_scope`'s, so there is no cheaper form to ask
    for. `Coverage.scope_rows == 0` means coverage is UNKNOWN rather than clean, and that is the
    field this Action exists to put in front of a caller.
    """

    corpus: str | None = None
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorIn:
    """`ow_doctor` / `ow doctor`. 10:1436, where the one flag is `--runtime`.

    `runtime` is `advanced` because the two probes answer different questions at different prices.
    The default pass reads configuration, resolves the driver catalog and checks toolchain digests
    -- all of it local and free. `--runtime` additionally EXERCISES what it found: it opens the
    model-server seam, resolves a subprocess host and prints the vision driver's installed size
    (02:267, which makes that print `ow doctor`'s job). An agent that wanted a fix command should
    not pay for a probe that starts processes to get one.

    It is a bool and not a `depth` enum, because there are two behaviours and a two-member enum is
    a bool that also needs a default spelled out.
    """

    runtime: bool = False


@dataclass(frozen=True, slots=True)
class HooksCheckIn:
    """`ow hooks check`. 10:1432's one flag is `--render`, which is global, so there is no field.

    Which commands to check is not an argument: they are the ones the install receipt says were
    installed, read back out of the files the receipt names (10:2078, *"resolves the installed
    command string"*). A command given on argv would be a command that was not installed.
    """


@dataclass(frozen=True, slots=True)
class InstallIn:
    """`ow install`. 10:1427's flags, every one an option: a field with a default is `--kebab`.

    `hooks`, `skills` and `location` default to `None`, and `None` is not a choice. 10:1427 gives
    `--hooks` and `--skills` no default and 18:2973 passes both, so the verb refuses an install
    that names neither rather than choosing what an unqualified `ow install` does to a host
    (D447). `location` is asked for when there is a terminal to ask, as `ow uninstall`'s step 1
    asks it (10:1754), and refused when there is not. `check` and `print_config` are the two
    read-only modes 10:1427 folds into the same verb.
    """

    target: str = "auto"
    location: str | None = None
    hooks: str | None = None
    skills: str | None = None
    allow_cli: bool = False
    check: bool = False
    print_config: str | None = None
    dry_run: bool = False
    yes: bool = False


@dataclass(frozen=True, slots=True)
class UninstallIn:
    """`ow uninstall`. 10:1428: `--target all --location ... --keep-cli --yes`.

    `target` defaults to `all` and not `auto` -- 10:1751, *"so a user need not remember where they
    installed it"*. `location` is asked first when omitted (10:1754).
    """

    target: str = "all"
    location: str | None = None
    keep_cli: bool = False
    yes: bool = False


@dataclass(frozen=True, slots=True)
class SkillsInstallIn:
    """`ow skills install <name>...`. 10:1429 prints the positional and no flag.

    `name` is `str | tuple[str, ...]`, `OpenIn.ref`'s shape, so the generated tree gives it
    `nargs="+"`: `ow skills install omniweave-pptx omniweave-authoring` is one argv whichever form
    a caller holds. There is no `--location`: 10:1393 writes *"into every discovered
    `<host>/skills` directory"*, and 10:1398's containment rule says which scope each one is.
    """

    name: str | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillsRemoveIn:
    """`ow skills remove <name>...`, the human-only fifth of 10:59's five (`skills.remove`).

    10:1429 gives `remove` no cell, only the note *"`remove` is human-only"*, so its one flag is
    `ow uninstall`'s: `--yes`, because a verb that deletes prints its plan and asks first
    (10:1620-1621) and a pipe has no one to ask.
    """

    name: str | tuple[str, ...]
    yes: bool = False


@dataclass(frozen=True, slots=True)
class ExplainIn:
    """`ow_explain` / `ow explain <CODE>`. 10:1438.

    One required string, and it accepts BOTH spellings of a register entry -- `OW-A-013` or
    `OW_PARSE_GAP_IN_SCOPE`. The parameter is therefore `code` and not `numeric`: a name that
    promised the numeric form would be wrong half the time it is used, and the resolver's job is
    precisely that it does not care which one it was handed.

    There is no `corpus`, which makes this the only Action in either profile that reads no store at
    all. `codes.toml` is repository data, so `ow explain` answers with no corpus configured, on a
    machine that has never run `ow add`, and while a store is locked by another writer -- which is
    most of the situations in which someone has an `OW-*` code and needs to know what it means.
    """

    code: str
