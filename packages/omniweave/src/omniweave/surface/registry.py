"""ONE Action declaration, SEVEN generated surfaces. 11:247; 18:851; 02-architecture.md row 30.

10:10 closes the opening paragraph that states it: *"Every capability omniweave has is one Action,
declared exactly once as an `ActionSpec` in `omniweave.surface.registry`, from which seven
agent-facing artefacts are generated and byte-diff gated (INV-20, gate G25)"*. This module is that
one declaration. It generates nothing -- `omniweave/gen/` is W7.2's -- and it opens nothing: it is
imported by every CLI and server entry point, so an import that read a file or probed a
distribution would charge every `ow query` for it (10:300).

## WHY THIS FILE EXISTS BEFORE ANY SURFACE DOES

FE5 (16:32) forbids the obvious order. *"Ship a hand-written CLI first and the registry's arrival is
a reconciliation between two surfaces that already disagree -- which is LEANN's defect (`llms.txt`
declaring two tools against a four-tool server, G6's cited catch) arrived at from the inside."* Both
failures this architecture prevents are measured rather than imagined (10:108): LEANN's manifest
declares two tools against a server defining four, two of them state-changing and undeclared; and
jcodemunch's always-on policy block enumerates ~25 tools its own front door never offers, flagged in
its own `cli/init.py` as bug #397. *"A machine-readable manifest a human maintains by hand is a lie
with a schema."*

## THE THREE BITS ARE NOT ONE BIT

10:36 is the section this module exists to make unrepresentable-in-the-wrong-combination, and it is
worth restating because conflating any two of them is the mistake:

| decision | field | owner | question |
|---|---|---|---|
| reachability | `mcp_name: str \\| None` | the architecture | may an agent ever dispatch this? |
| listing | `listed_in` | the token budget | does it cost `tools/list` context every turn? |
| authority | `enabled`, in `[serve]` | the operator | may this caller dispatch it NOW? |

They are independent, and 10:43 gives three worked cases: `route.explain` is reachable, unlisted and
has no route stub; `make.deck` is unreachable, unlisted and HAS one; `query` is reachable, listed
and has none, because a question is one call.

`enabled` is deliberately not a field. It is the operator's, resolved from `[serve] enabled` and
`OMNIWEAVE_MCP_ENABLED` at startup, and `assert_sv1()` below is where the two meet. A field would
make a deployment decision a source-code decision.

## WHAT IS IN `ACTIONS` TODAY, AND WHAT IS NOT

The four listed Actions. That is W7.1's first cell and not its last: 10:857 puts *"roughly 110
further Actions"* behind them and the eighteen-row `full` roster at 10:805 between. Every check
below is written over the whole mapping and not over four rows, so a later cell adds data and no
logic -- which is the property that makes a registry worth having.

**A roster is not a numeral, and this file is where that bites.** 10:1457 refuses to print a verb
count for `ow store` and `ow index` because *"a numeral is a second copy of an enumeration and
drifts from it in silence"*; 16:715's estimation basis for this very work item says `~45 Actions`
while 10:857 and 10:2519 say ~130. D293 is the entry. The mapping is the roster; nothing here
carries a count.

## THE ELEVEN CHECKS RUN AT IMPORT, NOT AT REVIEW

10:176: `_validate(ACTIONS)` *"raises `OwError(OW_SURFACE_REGISTRY_INVALID)` naming every failing
row"*. Every row, not the first -- a registry with three defects should cost one edit cycle. The
charter states one of the eleven (a duplicate `name`); the other ten are 10's, and each is a defect
*"that is otherwise invisible until a user hits it"*.

Check 2 is the one 10:184 names out loud: `ACTIONS` is keyed on `name`, so two Actions sharing an
`mcp_name` are structurally possible and *"the dispatcher would resolve to whichever won the dict"*.

`SurfaceError` carries it rather than a bare `OwError`, although 10:179 writes `OwError`: the symbol
is an `OW-A-*` and `codes.toml`'s area A maps to `SurfaceError`, so raising the base class would put
an area-A code on a class the register says belongs to another.

It keeps that class's exit floor of **70**, and the contrast with `assert_sv1()` below is the point.
An invalid registry is a defect in shipped source that no configuration can cause and no user can
clear, which is 10:1489's *"internal error"*; a breach of SV1 is two config keys that disagree,
which is exit **1**, *"usage or configuration error"*. Two failures, two audiences, two numbers.

## `out` IS A TYPE, AND A TYPE IS AN IMPORT

10:137 makes `inp` and `out` `type` objects, which is what lets one declaration generate a schema, a
parser, an SDK stub and a `.pyi` without a second vocabulary. The cost arrives with the roster: an
object cannot be named without importing the module that defines it, this module is imported by
every CLI and server entry point (10:300), and 10:857 puts roughly 110 further Actions behind the
eighteen. At the end of that road `import omniweave.surface` transitively imports every distribution
that defines an output type, on the path of every `ow query`.

It is already measurable. `RouteDecision` is the honest `out` for `route.explain` -- 10:816 asks for
*"which driver produced a block, at what rung, and what it cost"* and that is four of its fields --
and naming it here adds **72 modules** to this import, among them `email`, `csv`, `decimal` and
`_socket`, because `omniweave.route` reaches the pricebook parser. A socket module on the front
door's import path is not a cost this row is worth, so `route.explain` is the one rostered Action
deferred for a measured reason rather than a missing type. D298 is the entry and W7.2 owns the
answer, because a generator that reads `out` for its schema and a dispatcher that needs the class
itself do not need it at the same moment.

## THE THREE CHECKS THAT ARE NOT AMONG THE ELEVEN

Nothing asserts that a `HUMAN_ONLY` member is an `ACTIONS` key at all. Check 4 is an implication
over rows -- `name in HUMAN_ONLY` implies `mcp_name is None` -- so a typo in the frozenset
(`corpus.rm` written `corpora.rm`) satisfies it vacuously and silently disarms the guard on the
Action it was meant to protect. D291 is the entry, and `_unrostered_human_only()` below reports it
without failing, because failing would make the four-row cell unimportable for a roster gap that is
schedule rather than defect.

`_unrostered_full()` is the same shape over `FULL_ROSTER` and reports thirteen; `_duplicate_cli()`
is the shape check 9 does not have, and it already names a real pair. `_roster_failures()` is the
one of the three that RAISES, because its four clauses are all about declarations this file
carries -- a roster and a row that disagree is a defect in shipped source, which is the line
`SurfaceError`'s floor of 70 draws.
"""

from __future__ import annotations

import re
from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Final, Literal, get_args

from omniweave_core.answer import Answer
from omniweave_core.errors import SurfaceError, UsageError
from omniweave_core.model import Grid
from omniweave_core.model.rebind import RebindReport
from omniweave_core.retrieve.verdict import Coverage
from omniweave_ports import CostClass

from omniweave.sdk.reports import AddReport, CodeRow, CorporaReport, DoctorReport
from omniweave.surface.inputs import (
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

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from omniweave_ports import Scalar

__all__ = [
    "ACTIONS",
    "DECISION_MAX",
    "FULL_ROSTER",
    "GROUPS",
    "HUMAN_ONLY",
    "MCP_NAME_RE",
    "PROFILES",
    "SUMMARY_MAX",
    "ActionSpec",
    "Profile",
    "assert_sv1",
    "listed",
]


# =============================================================================================
# 1. The profiles, the name grammar and the two length caps
# =============================================================================================

Profile = Literal["default", "full"]
"""10:120. Two named listed-sets, and `full` is a superset of `default` by check 6."""

PROFILES: Final[tuple[Profile, ...]] = get_args(Profile)
DEFAULT_PROFILE: Final[Profile] = PROFILES[0]
FULL_PROFILE: Final[Profile] = PROFILES[1]

MCP_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^ow_[a-z][a-z0-9_]{1,30}$")
"""Check 3's grammar (10:188), which catches *"a name a host cannot address"*.

The lower bound is three characters after `ow_` at minimum and the upper is 34 in total. Both come
from the pattern as 10 prints it; neither is restated as a numeral here, because the pattern is the
statement and a second copy would be a second thing to keep true.
"""

SUMMARY_MAX: Final[int] = 160
DECISION_MAX: Final[int] = 90
"""Check 7's caps (10:192), which catch *"a catalog row that wraps in a table"*.

The `decision` clause is the shorter of the two on purpose: it is a disambiguator between tools that
an agent reads at pick time, and 10:79 measures a skill's threshold against exactly this pair --
instructions *"exceed what a tool `description` can carry"* means more than `SUMMARY_MAX` plus
`DECISION_MAX` characters can express. A cap that moved would move that test with it.
"""


# =============================================================================================
# 2. `ActionSpec`
# =============================================================================================


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """One capability, declared once. 10:124's field list in 10:124's order.

    **`destructive` carries no default, and its position is the argument.** It sits with the other
    three booleans ahead of `cost_class` rather than among the defaulted tail. 10:164: *"MCP's own
    default for `destructiveHint` is `true`, so an omitted declaration would silently ship the most
    alarming annotation the protocol has"*. A dataclass field with no default already makes
    omission a `TypeError` at the construction site; check 10 catches the other case, where a writer
    declares it by copying a neighbouring row.

    **Each of the four booleans has exactly one consumer** (10:154), which is why they are four
    fields and not one flags int:

    - `read_only` generates `annotations.readOnlyHint` AND is the predicate the `read_only` and
      `read_only+add` `enabled` presets resolve against -- the only one with two consumers, and the
      second is authority rather than annotation;
    - `idempotent` generates `idempotentHint` and licenses the CLI's retry advice on exit 7;
    - `open_world` generates `openWorldHint` and is true *"only where the Action touches something
      outside the store -- `ow_add` alone, because it walks a filesystem or fetches a URL"*;
    - `destructive` generates `destructiveHint` and nothing else: it feeds no preset and licenses no
      advice.

    **`cost_class` is rendered into no schema.** It is the Action's worst-case class over the
    drivers it can reach, read by the dispatcher (10:171) *"to decide whether a call needs a cost
    deferral before it starts"*, and printed by `ow_corpora detail="actions"` (10:172) *"so an
    agent can see that `ow_ingest` may bill and `ow_outline` cannot"*.

    **`cli` defaults to the empty tuple and check 9 forbids it.** The default is therefore
    unreachable, and it is written as 10:139 writes it: every capability always has a CLI verb
    (10:32), so an empty `cli` is a row someone stopped writing halfway rather than a legal state.
    """

    name: str
    mcp_name: str | None
    listed_in: frozenset[Profile]
    read_only: bool
    idempotent: bool
    open_world: bool
    destructive: bool
    cost_class: CostClass
    summary: str
    decision: str
    example: Mapping[str, Scalar]
    inp: type
    out: type
    advanced: frozenset[str] = frozenset()
    cli: tuple[str, ...] = ()

    @property
    def human_only(self) -> bool:
        """Whether no agent surface can reach this Action, by construction rather than by policy.

        10:1540: `mcp_name = None` is *"structural, not a denylist"*. The property reads the field
        rather than `HUMAN_ONLY`, so it stays true for an Action that is unreachable without being
        one of the charter's five -- `make.deck` is the shipped example (10:43), unreachable under
        row 3 and not in the frozenset.
        """
        return self.mcp_name is None


# =============================================================================================
# 3. `HUMAN_ONLY`, and the CLI group registry
# =============================================================================================

HUMAN_ONLY: Final[frozenset[str]] = frozenset(
    {"uninstall", "corpus.rm", "route.promote", "skills.remove", "targets.remove"}
)
"""The five the charter names, produced by rows 1-3 of 10:51's first-match-wins table.

10:66 is why this is a frozenset of names and not a decorator or a deny list in config. Naming one
of these in `OMNIWEAVE_MCP_ENABLED` is a startup error rather than a warning, which
`assert_sv1()` enforces, because (10:791) *"the whole point of `mcp_name = None` is that no key
grants it"*.

`ow_add` is the one listed writer and it survives row 2, 10:60, *"precisely because its billable
half defers rather than spends -- the response carries the pending cost and the CLI command that
approves it, which is the deferral shape row 2 asks for"*.
"""

GROUPS: Final[frozenset[str]] = frozenset(
    {
        "add",
        "audit-config",
        "bench",
        "cache",
        "check",
        "conform",
        "corpora",
        "cost",
        "deps",
        "doc",
        "doctor",
        "drivers",
        "eval",
        "explain",
        "graph",
        "hook",
        "hooks",
        "index",
        "ingest",
        "install",
        "make",
        "open",
        "out",
        "parse",
        "query",
        "queue",
        "rebind",
        "replay",
        "route",
        "schema",
        "serve",
        "services",
        "session",
        "show-config",
        "skills",
        "store",
        "surface",
        "targets",
        "test",
        "top",
        "trace",
        "uninstall",
        "why",
    }
)
"""Every legal `cli[0]`, transcribed from 18:908's complete command surface and 10:1414's table.

A root here is not necessarily a GROUP. 10:1413's grammar is `ow <group> <verb>` with *"a group only
at three or more verbs"*, so `query`, `open`, `corpora` and `add` are top-level verbs while `store`,
`graph` and `out` are groups. Check 9 asks only that `cli[0]` be a declared root; the arity rule is
G25's (10:236) and belongs with the generator that has the whole tree in front of it.

**This registry already contains the collision the trailing-`s` rule exists to forbid.** `ow hook
<event>` (hidden, reads stdin JSON, always exits 0) and `ow hooks check` (resolves and executes the
installed command) are both in 18:918's surface and differ by one character. 10:238 gives the rule's
motivating example as the `ow driver` / `ow drivers` pair, which does not occur; the pair that does
occur is not named anywhere. D295 is the entry. The check below runs over the roots `ACTIONS` uses
rather than over this frozenset, which is the reading check 9's placement among the row checks
forces -- and it means the collision surfaces on the day both rows land, which is the day the
decision has to be made.

`ow export` is deliberately absent: 10:1467 makes the single spelling `ow store export`, *"so d2
resolves against exactly one name"*. So are `ow init` and `ow resume` (10:1464, 10:1468), each for a
stated reason -- two operations with different receipts, and a second recovery protocol AP-5 forbids
by name.
"""


FULL_ROSTER: Final[tuple[tuple[str, str], ...]] = (
    ("ow_outline", "doc.outline"),
    ("ow_grid", "doc.grid"),
    ("ow_fields", "extract.fields"),
    ("ow_entities", "graph.entities"),
    ("ow_locate", "graph.locate"),
    ("ow_neighbors", "graph.neighbors"),
    ("ow_community", "graph.report"),
    ("ow_claims", "graph.claims"),
    ("ow_xrefs", "doc.xrefs"),
    ("ow_why", "route.explain"),
    ("ow_verify", "doc.verify_quote"),
    ("ow_coverage", "corpus.coverage"),
    ("ow_diff", "doc.diff"),
    ("ow_artifacts", "out.list"),
    ("ow_targets", "out.targets"),
    ("ow_cost", "cost.report"),
    ("ow_doctor", "doctor"),
    ("ow_explain", "explain"),
)
"""The eighteen `listed_in = {"full"}` Actions, transcribed from 10:807-822 in that table's order.

**Pairs and not a mapping literal**, for the reason `_index` states one section down: a `dict`
silently keeps the last of two rows sharing a key, so a roster written as `{...}` could lose a line
to a copy-paste and still import. `_roster_failures()` checks both columns for duplicates over the
pairs, which is a check a dict cannot be asked to perform on itself.

**Eighteen is a roster and not a count, and here the count is load-bearing anyway.** 10:829 prices
the `full` profile at `18 x 150.5 ~ 2,709` tokens against a `full_compact` ceiling of 4,200, and
10:833 says those baseline rows are written by `ow surface budget --bless` *"on the first run after
the eighteen `ActionSpec`s exist, not typed by hand"*. So this tuple is what tells that command when
its day has come: `len(FULL_ROSTER) == len(listed("full")) - len(listed("default"))` is the
condition, and `_unrostered_full()` is the distance from it.

**Five have rows today and thirteen do not**, and the reason is never that the Action is unclear. It
is that `ActionSpec.out` is a `type` -- an OBJECT, evaluated at import -- so a row cannot be written
before something in this process can name what it returns. Seven of the thirteen wait on P8's L3
types and two on P9's OUT framework (16:190-191), both of which exit after v0.1 ships at week 42;
three -- `ow_verify`, `ow_fields` and `ow_cost` -- wait on a shape no module defines, and one of
those three is `QuoteVerdict` (03:1706), which `omniweave_core/model/doc.py` already
forward-references twice under `noqa: F821`. The thirteenth, `route.explain`, waits on nothing but
the cost of naming `RouteDecision` here. D298 is that entry and it is the one worth reading, because
it is a property of this mechanism rather than of the schedule; D300 is the other twelve.
"""


# =============================================================================================
# 4. The eleven checks
# =============================================================================================

_SCALAR_NAMES: Final[frozenset[str]] = frozenset({"str", "int", "float", "bool", "None"})
"""The annotation spellings a `Mapping[str, Scalar]` example can satisfy.

Check 8 asks whether an example validates against `inp`, and an example is scalars only (10:136), so
the matcher is total without importing anything an input module deferred: a field annotated with a
non-scalar type cannot be satisfied by a scalar, whatever that type is. That is why this reads
annotation TEXT rather than calling `typing.get_type_hints` -- `QueryIn.route_hints` is
`RouteHints | None` under `TYPE_CHECKING`, and resolving it at import would pull
`omniweave.route`'s policy loader into every `ow query`.
"""


def _members(annotation: str) -> tuple[str, ...]:
    """The top-level union members of an annotation, as written.

    Splits on `|` at bracket depth zero, so `str | tuple[str, ...]` yields two members and
    `Mapping[str, int]` yields one. No `typing` machinery and no evaluation.
    """
    out: list[str] = []
    depth = 0
    current = ""
    for char in annotation:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "|" and depth == 0:
            out.append(current.strip())
            current = ""
        else:
            current += char
    out.append(current.strip())
    return tuple(member for member in out if member)


def _accepts(annotation: str, value: object) -> bool:
    """Whether a scalar example value is assignable to a field annotated `annotation`.

    An `int` is accepted where `float` is declared, which is JSON's own widening and the shape every
    published `"type": "number"` takes. A `bool` is NOT accepted where `int` is declared, although
    Python's type tree allows it: `dry_run` and `context` are different kinds of parameter and an
    example that confused them would generate a schema nobody meant.
    """
    written = type(value).__name__ if value is not None else "None"
    members = _members(annotation)
    if written in members:
        return True
    return written == "int" and "float" in members


def _example_failures(spec: ActionSpec) -> tuple[str, ...]:
    """Check 8, 10:190: *"an example an agent copies and gets an argument error from"*."""
    declared = {field.name: field for field in fields(spec.inp)}
    out: list[str] = []
    for key, value in spec.example.items():
        field = declared.get(key)
        if field is None:
            out.append(f"{spec.name}: example key {key!r} is not a field of {spec.inp.__name__}")
        elif not _accepts(str(field.type), value):
            out.append(
                f"{spec.name}: example {key}={value!r} does not satisfy {field.type} "
                f"on {spec.inp.__name__}"
            )
    required = {
        field.name
        for field in fields(spec.inp)
        if field.default is MISSING and field.default_factory is MISSING
    }
    for missing in sorted(required - set(spec.example)):
        out.append(f"{spec.name}: example omits required field {missing!r}")
    return tuple(out)


def _row_failures(spec: ActionSpec, key: str) -> tuple[str, ...]:
    """Checks 1 and 3 through 11, for one row. Check 2 is cross-row and lives in `_validate`."""
    out: list[str] = []
    if key != spec.name:
        out.append(f"{key}: keyed on {key!r} but names itself {spec.name!r}")  # check 1
    if spec.mcp_name is not None and not MCP_NAME_RE.match(spec.mcp_name):  # check 3
        out.append(f"{spec.name}: mcp_name {spec.mcp_name!r} is not ow_[a-z][a-z0-9_]{{1,30}}")
    if spec.name in HUMAN_ONLY and (spec.mcp_name is not None or spec.listed_in):  # check 4
        out.append(f"{spec.name}: HUMAN_ONLY, so mcp_name must be None and listed_in empty")
    if spec.mcp_name is None and spec.listed_in:  # check 5
        out.append(f"{spec.name}: listed_in on an Action no agent can reach can never take effect")
    if not set(spec.listed_in) <= set(PROFILES):  # check 6
        out.append(f"{spec.name}: listed_in {sorted(spec.listed_in)} is not a subset of {PROFILES}")
    elif DEFAULT_PROFILE in spec.listed_in and FULL_PROFILE not in spec.listed_in:
        out.append(f"{spec.name}: listed in {DEFAULT_PROFILE!r} but not in {FULL_PROFILE!r}")
    out.extend(_prose_failures(spec))  # check 7
    out.extend(_example_failures(spec))  # check 8
    if not spec.cli:  # check 9, first clause
        out.append(f"{spec.name}: every capability has a CLI verb, so cli must be non-empty")
    elif spec.cli[0] not in GROUPS:
        out.append(f"{spec.name}: cli root {spec.cli[0]!r} is not a declared root")
    declared = {field.name for field in fields(spec.inp)}
    for member in sorted(spec.advanced - declared):  # check 11
        out.append(f"{spec.name}: advanced names {member!r}, which is not a field of the input")
    return tuple(out)


def _prose_failures(spec: ActionSpec) -> tuple[str, ...]:
    """Check 7, split out because it is four assertions about two strings."""
    out: list[str] = []
    for label, text, cap in (
        ("summary", spec.summary, SUMMARY_MAX),
        ("decision", spec.decision, DECISION_MAX),
    ):
        if not text:
            out.append(f"{spec.name}: {label} is empty")
        elif len(text) > cap:
            out.append(f"{spec.name}: {label} is {len(text)} characters, over {cap}")
        elif text.endswith("."):
            out.append(f"{spec.name}: {label} ends in a full stop, which wraps in a catalog table")
    return tuple(out)


def _trailing_s_failures(roots: Collection[str]) -> tuple[str, ...]:
    """Check 9's third clause, over the roots `ACTIONS` uses.

    10:238: a singular `ow driver` group and the locked `ow drivers` group *"cannot both be
    generated from one `cli` tuple, and one of them would silently win"*.
    """
    collisions = sorted({root for root in roots if root + "s" in roots})
    return tuple(f"{root!r} and {root}s differ only by a trailing s" for root in collisions)


def _roster_failures(actions: Mapping[str, ActionSpec]) -> tuple[str, ...]:
    """The reconciliation between `FULL_ROSTER` and the rows, and it is not one of the eleven.

    The eleven are checks on a ROW (10:176). This is a check between two declarations in this file,
    which is the same shape check 1's other half takes in `_index` and check 10 takes on
    `ActionSpec`: where the evidence is not inside a row, the check is not inside `_row_failures`.

    Four clauses, and the fourth is the one that earns the function:

    1. `FULL_ROSTER` names each `mcp_name` once and each Action once. Written as pairs precisely so
       this can be asked; a mapping literal would have answered it by discarding a line.
    2. A rostered Action that HAS a row carries the roster's `mcp_name`. The two columns of 10:807
       are the same fact written twice, so a row that renamed its tool without editing the roster
       would leave the published table describing a tool no server serves.
    3. A rostered Action that has a row is listed in `full` and NOT in `default`. 10:805 defines the
       roster as the Actions *"listed only under `profile = "full"` or an explicit override"*, so a
       row that widened itself into the front door would be a fifth listed tool arriving through a
       table about narrow ones -- and 10:265 rejects a fifth in advance.
    4. **Every `full`-listed row is IN the roster.** Without it the roster is documentation: a new
       Action could be listed in `full`, cost its share of the 4,200-token ceiling, appear in
       `tools/list` and never be added to 10:807's table -- which is precisely the LEANN defect
       (10:108) this module exists to prevent, arrived at from the direction the other three clauses
       leave open.
    """
    out: list[str] = []
    seen_mcp: dict[str, str] = {}
    seen_name: set[str] = set()
    for mcp_name, name in FULL_ROSTER:
        if mcp_name in seen_mcp:
            out.append(f"FULL_ROSTER: mcp_name {mcp_name!r} is {seen_mcp[mcp_name]}'s and {name}'s")
        if name in seen_name:
            out.append(f"FULL_ROSTER: {name!r} is rostered twice")
        seen_mcp[mcp_name] = name
        seen_name.add(name)
        spec = actions.get(name)
        if spec is None:
            continue
        if spec.mcp_name != mcp_name:
            out.append(f"{name}: rostered as {mcp_name!r} but declares mcp_name {spec.mcp_name!r}")
        if set(spec.listed_in) != {FULL_PROFILE}:
            out.append(
                f"{name}: rostered in the full profile but listed_in is "
                f"{sorted(spec.listed_in)}, not [{FULL_PROFILE!r}]"
            )
    for name, spec in actions.items():
        narrow = FULL_PROFILE in spec.listed_in and DEFAULT_PROFILE not in spec.listed_in
        if narrow and name not in seen_name:
            out.append(f"{name}: listed in {FULL_PROFILE!r} but absent from FULL_ROSTER")
    return tuple(out)


def _validate(actions: Mapping[str, ActionSpec]) -> tuple[str, ...]:
    """The eleven checks. Returns EVERY failure, so one edit cycle clears a registry with three."""
    out: list[str] = []
    seen_mcp: dict[str, str] = {}
    for key, spec in actions.items():
        out.extend(_row_failures(spec, key))
        if spec.mcp_name is not None:  # check 2
            first = seen_mcp.setdefault(spec.mcp_name, spec.name)
            if first != spec.name:
                out.append(f"{spec.name}: mcp_name {spec.mcp_name!r} is already {first}'s")
    out.extend(_trailing_s_failures({spec.cli[0] for spec in actions.values() if spec.cli}))
    out.extend(_undefaulted_failures())  # check 10
    out.extend(_roster_failures(actions))  # not one of the eleven; see the function
    return tuple(out)


def _undefaulted_failures() -> tuple[str, ...]:
    """Check 10, and it is a check on the TYPE rather than on a row.

    10:190 states it as an implication over rows -- `read_only is False` implies `destructive` is
    *"explicitly declared, never defaulted"* -- but a row cannot carry the evidence. By the time an
    `ActionSpec` exists, `destructive` holds a `bool` and nothing records whether a writer typed it
    or inherited it, and 10:171 says why that distinction is the whole point: MCP reads an absent
    `destructiveHint` as `true`, so a defaulted `false` would be the protocol's most alarming
    annotation silently inverted.

    The evidence lives one level up. A field with no default makes omission a `TypeError` at the
    construction site, which is a stronger enforcement than any per-row test -- so what this asserts
    is that the field still has no default. A future edit adding `destructive: bool = False` would
    pass every row check and fail here.
    """
    for field in fields(ActionSpec):
        if field.name == "destructive" and (
            field.default is not MISSING or field.default_factory is not MISSING
        ):  # pragma: no cover -- the shipped type has no default; the test builds its own
            return ("ActionSpec.destructive has a default, so a writer can omit it",)
    return ()


def _index(specs: Iterable[ActionSpec]) -> Mapping[str, ActionSpec]:
    """Check 1's other half: *"a duplicate name => raise"* (10:141), at build rather than after.

    A mapping literal would silently keep the last of two rows sharing a name, which is the one
    failure mode a dict cannot report on its own.
    """
    out: dict[str, ActionSpec] = {}
    for spec in specs:
        if spec.name in out:
            raise SurfaceError(
                f"two Actions are named {spec.name!r}",
                symbol="OW_SURFACE_REGISTRY_INVALID",
                fix="give one of them a different `name` in omniweave/surface/registry.py",
            )
        out[spec.name] = spec
    return out


def _unrostered_human_only(actions: Mapping[str, ActionSpec]) -> tuple[str, ...]:
    """The check that is not among the eleven: a `HUMAN_ONLY` name with no row. D291.

    Reported rather than raised, because today every one of the five is schedule rather than defect
    -- `ACTIONS` carries four rows and none of them is human-only. A test asserts this function's
    answer, so the day the roster closes the assertion changes from *"these five are pending"* to
    *"these five are rostered"* in one place.
    """
    return tuple(sorted(HUMAN_ONLY - set(actions)))


def _unrostered_full(actions: Mapping[str, ActionSpec]) -> tuple[str, ...]:
    """Which of `FULL_ROSTER`'s eighteen have no row yet, in the roster's published order.

    The companion to `_unrostered_human_only()` and reported on the same terms: a missing row here
    is schedule, not defect, and raising would make the registry unimportable for an Action whose
    output type ships two phases from now. A test asserts this function's exact answer, so the day
    the thirteenth lands the assertion becomes `()` in one place and `ow surface budget --bless`
    (10:833) has its condition.

    Order is `FULL_ROSTER`'s rather than sorted, because the thing a reader wants from this tuple is
    its position in 10:807's table.
    """
    return tuple(name for _, name in FULL_ROSTER if name not in actions)


def _duplicate_cli(actions: Mapping[str, ActionSpec]) -> tuple[tuple[str, ...], ...]:
    """CLI tuples two or more Actions declare, sorted. D299, and it is not among the eleven either.

    Check 9 asks that `cli` be non-empty and that `cli[0]` be a declared root, and its third clause
    forbids two roots differing only by a trailing `s`. None of the three asks whether two rows
    declare the SAME tuple -- which is the collision the trailing-`s` clause is a special case of,
    in its most direct form, and the one check 2 has a counterpart for on the MCP side (*"the
    dispatcher would resolve to whichever won the dict"*, 10:184).

    It already fires. `corpora` and `corpus.coverage` both spell `ow corpora`, because 10:1424 gives
    the second no verb of its own: its CLI twin is `ow corpora --detail coverage`, a FLAG VALUE on
    the first. Two Actions, one command, distinguished by an argument -- so the generated argparse
    tree has one subparser to build and two rows asking for it.

    Reported and not raised, for D295's reason and with D295's benefit: the pair surfaces on the day
    both rows land, which is the day the decision has to be made rather than the day someone
    notices. Raising would instead mean the roster could not be assembled until W7.2 had settled
    how a flag-valued twin is generated, which is the wrong order: the generator needs the
    collision in front of it.
    """
    seen: dict[tuple[str, ...], list[str]] = {}
    for name, spec in actions.items():
        if spec.cli:
            seen.setdefault(spec.cli, []).append(name)
    return tuple(sorted(cli for cli, names in seen.items() if len(names) > 1))


# =============================================================================================
# 5. `ACTIONS`
# =============================================================================================

_LISTED: Final[frozenset[Profile]] = frozenset(PROFILES)
"""Both profiles. The four front-door Actions are listed everywhere, which check 6 requires anyway:
`default` implies `full`, because a profile that is not a superset of the one below it would make
`profile = "full"` a narrowing."""

_FULL_ONLY: Final[frozenset[Profile]] = frozenset({FULL_PROFILE})
"""The narrow roster's listing: `full` and not `default`, which is `_roster_failures`' clause 3.

Not the complement of `_LISTED`, and the distinction is check 6's: `listed_in` is a SET of profiles
a row appears in, so widening `full` never narrows `default` and the two constants are two legal
values rather than two halves of one. A row that wanted both writes `_LISTED`; there is no third."""

ACTIONS: Final[Mapping[str, ActionSpec]] = _index(
    (
        ActionSpec(
            name="query",
            mcp_name="ow_query",
            listed_in=_LISTED,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            # The worst case over the drivers retrieval can reach, and that is the semantic
            # channel's embedder. It is not BILLED_API: `Query` (07 section 5.1) carries no rung
            # ceiling and no deadline, so nothing documented carries this Action's `route_hints`
            # into the rung ladder where billed work lives -- which is D294, not a licence.
            cost_class=CostClass.LOCAL_COMPUTE,
            summary=(
                "Ask an indexed corpus a question and get cited passages, a verdict, and the "
                "gaps that could be hiding an answer"
            ),
            decision="you have a question, not an id",
            example={
                "query": "how much parental leave accrues per month",
                "corpus": "handbook",
                "scope": "policy.pdf",
                "max_chars": 8000,
            },
            inp=QueryIn,
            out=Answer,
            advanced=frozenset({"want", "route_hints", "max_chars"}),
            cli=("query",),
        ),
        ActionSpec(
            name="open",
            mcp_name="ow_open",
            listed_in=_LISTED,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Fetch the exact passages behind an address you already hold: a cite, a page "
                "range, or a whole document"
            ),
            decision="you have an id, not a question",
            example={"ref": "d7#412", "corpus": "handbook"},
            inp=OpenIn,
            out=Answer,
            advanced=frozenset({"context", "layers", "max_chars"}),
            cli=("open",),
        ),
        ActionSpec(
            name="corpora",
            mcp_name="ow_corpora",
            listed_in=_LISTED,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "List what this server can read and what is in each corpus: counts, formats, "
                "known gaps, freshness and the capability floor"
            ),
            decision="you do not know what exists yet",
            example={"detail": "card"},
            inp=CorporaIn,
            out=CorporaReport,
            # 10:356: the one listed tool compaction does not change, because it declares none.
            advanced=frozenset(),
            cli=("corpora",),
        ),
        ActionSpec(
            name="add",
            mcp_name="ow_add",
            listed_in=_LISTED,
            read_only=False,
            idempotent=True,
            open_world=True,
            # 10:161: false for all four listed tools, `ow_add` included, because its writes append
            # documents and index rows and never remove indexed content -- so a host that reads
            # `destructiveHint` to decide whether to prompt should not prompt for an ingest.
            destructive=False,
            # The worst case, and the reason the Action is still listable: row 2 of 10:51 asks
            # whether it spends money WITHOUT a per-call human act, and this one defers instead.
            cost_class=CostClass.BILLED_API,
            summary=(
                "Index files, directories or URLs into a corpus so ow_query can cite them; "
                "billable work defers with the command that approves it"
            ),
            decision="the answer is not indexed yet",
            example={"source": "policy-2025.pdf", "corpus": "handbook"},
            inp=AddIn,
            out=AddReport,
            advanced=frozenset({"dry_run"}),
            cli=("add",),
        ),
        # -- the `full` profile, in FULL_ROSTER's order. Every one of them is read-only, and 10:823
        #    says that is FORCED rather than chosen: `listed` must be a subset of `enabled`, the
        #    shipped `enabled = "read_only+add"` grants the read-only Actions plus `add`, so listing
        #    a writer in `full` would make the default configuration fail its own startup check. --
        ActionSpec(
            name="doc.grid",
            mcp_name="ow_grid",
            listed_in=_FULL_ONLY,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Read one table as an exactly-once grid: every cell at its slot, the header row "
                "and column, and the merges that would otherwise be counted twice"
            ),
            decision="you hold a table cite and need cells, not prose",
            example={"ref": "d7#412", "corpus": "handbook"},
            inp=GridIn,
            out=Grid,
            advanced=frozenset(),
            cli=("doc", "grid"),
        ),
        ActionSpec(
            name="corpus.coverage",
            mcp_name="ow_coverage",
            listed_in=_FULL_ONLY,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "What a scope holds and what is missing from it: discovered against indexed, the "
                "gap list behind a low or absent verdict, and the command that clears each gap"
            ),
            decision="ow_query said absent and you need to know why",
            example={"corpus": "handbook", "scope": "policy.pdf"},
            inp=CoverageIn,
            out=Coverage,
            advanced=frozenset(),
            # 10:1424 gives this Action no verb of its own: the CLI twin is a flag VALUE on
            # `ow corpora`. `_duplicate_cli()` reports the pair; D299 is the entry.
            cli=("corpora",),
        ),
        ActionSpec(
            name="doc.diff",
            mcp_name="ow_diff",
            listed_in=_FULL_ONLY,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Compare two generations of one document: what carried, what was revised, what is "
                "new, and whether the newer generation was quarantined rather than committed"
            ),
            decision="the document was re-indexed and you need what moved",
            example={"ref": "policy.pdf", "corpus": "handbook"},
            inp=DiffIn,
            out=RebindReport,
            advanced=frozenset({"from_gen", "to_gen"}),
            cli=("doc", "diff"),
        ),
        ActionSpec(
            name="doctor",
            mcp_name="ow_doctor",
            listed_in=_FULL_ONLY,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Check this deployment: every resolved configuration value with its source, the "
                "driver and toolchain probes, and a fix command for every warning"
            ),
            decision="something is misconfigured and you need the command",
            example={"runtime": False},
            inp=DoctorIn,
            out=DoctorReport,
            advanced=frozenset({"runtime"}),
            cli=("doctor",),
        ),
        ActionSpec(
            name="explain",
            mcp_name="ow_explain",
            listed_in=_FULL_ONLY,
            read_only=True,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Resolve an OW-* code or symbol to what it means and the exact command that "
                "clears it; reads no corpus, so it answers on a machine with no store at all"
            ),
            decision="you have a code from an error and need what clears it",
            example={"code": "OW-A-013"},
            inp=ExplainIn,
            out=CodeRow,
            advanced=frozenset(),
            cli=("explain",),
        ),
    )
)

_FAILURES: Final[tuple[str, ...]] = _validate(ACTIONS)
if _FAILURES:  # pragma: no cover -- a shipped registry that fails its own checks is unimportable
    raise SurfaceError(
        "the Action registry is invalid: " + "; ".join(_FAILURES),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="fix every row named above in omniweave/surface/registry.py",
    )


# =============================================================================================
# 6. Listing, and SV1
# =============================================================================================


def listed(profile: str = DEFAULT_PROFILE) -> tuple[str, ...]:
    """The Action names a profile lists, sorted. 10:802's roster, derived rather than written.

    Sorted because the generator is pure and deterministic (10:229): *"no iteration over an unsorted
    set"*, or G25's byte-diff would gate a shape nobody declared.
    """
    if profile not in PROFILES:
        raise UsageError(
            f"{profile!r} is not a profile; the two are {', '.join(PROFILES)}",
            symbol="OW_TOOL_NOT_LISTED",
            fix=f"set [serve] profile to one of: {', '.join(PROFILES)}",
        )
    return tuple(sorted(name for name, spec in ACTIONS.items() if profile in spec.listed_in))


def assert_sv1(listed_now: Collection[str], enabled_now: Collection[str]) -> None:
    """SV1, checked ONCE at startup and never per request. 02:723; 10:784.

    Two clauses, two symbols, and both name the key and the Action rather than merely refusing:

    - `listed` must be a subset of `enabled`. A server that quietly narrowed its own listing *"would
      disagree with the `llms.txt` it ships"* (10:788), so there is no repair-and-continue path.
    - `HUMAN_ONLY` must not intersect `enabled`. 10:792: naming one *"in either variable is a
      startup error, not a warning -- the whole point of `mcp_name = None` is that no key grants
      it"*.

    Both collections are Action names, already normalised: 10:790 has the resolver accept either the
    bare name or the `mcp_name` and normalise before this runs, so this function never has to guess
    which spelling it was handed.

    Raises `UsageError`, which is `SurfaceError`'s exit-1 leaf. 02:723 fixes the number --
    *"`SurfaceError` (`OW-A-*`), exit 1, before the transport opens"* -- and 10:1482's exit table
    reads 1 as *"usage or configuration error"*, which is what a breach of SV1 is: two config keys
    that disagree. The base class's floor is 70, the internal-error code, and a deployment that
    listed more than it enabled is not a bug in omniweave.
    """
    unauthorised = sorted(set(listed_now) - set(enabled_now))
    if unauthorised:
        raise UsageError(
            "SV1: [serve] listed names "
            + ", ".join(unauthorised)
            + ", which [serve] enabled does not grant",
            symbol="OW_ACTION_NOT_ENABLED",
            fix=(
                "widen [serve] enabled (or OMNIWEAVE_MCP_ENABLED) to cover them, "
                "or drop them from [serve] listed"
            ),
        )
    granted = sorted(HUMAN_ONLY & set(enabled_now))
    if granted:
        raise UsageError(
            "SV1: [serve] enabled names the human-only Action(s) " + ", ".join(granted),
            symbol="OW_HUMAN_ONLY_ACTION",
            fix=(
                "remove them from [serve] enabled and OMNIWEAVE_MCP_ENABLED; "
                "they are unreachable from any agent surface by construction"
            ),
        )
