"""ONE Action declaration, SEVEN generated surfaces. 11:247; 18:851; 02-architecture.md row 30.

10:10 closes the opening paragraph that states it: *"Every capability omniweave has is one Action, declared exactly once as an `ActionSpec` in
`omniweave.surface.registry`, from which seven agent-facing artefacts are generated and byte-diff
gated (INV-20, gate G25)"*. This module is that one declaration. It generates nothing --
`omniweave/gen/` is W7.2's -- and it opens nothing: it is imported by every CLI and server entry
point, so an import that read a file or probed a distribution would charge every `ow query` for it
(10:300).

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

## THE CHECK THAT IS NOT AMONG THE ELEVEN

Nothing asserts that a `HUMAN_ONLY` member is an `ACTIONS` key at all. Check 4 is an implication
over rows -- `name in HUMAN_ONLY` implies `mcp_name is None` -- so a typo in the frozenset
(`corpus.rm` written `corpora.rm`) satisfies it vacuously and silently disarms the guard on the
Action it was meant to protect. D291 is the entry, and `_unrostered_human_only()` below reports it
without failing, because failing would make the four-row cell unimportable for a roster gap that is
schedule rather than defect.
"""

from __future__ import annotations

import re
from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Final, Literal, get_args

from omniweave_core.answer import Answer
from omniweave_core.errors import SurfaceError, UsageError
from omniweave_ports import CostClass

from omniweave.sdk.reports import AddReport, CorporaReport
from omniweave.surface.inputs import AddIn, CorporaIn, OpenIn, QueryIn

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from omniweave_ports import Scalar

__all__ = [
    "ACTIONS",
    "DECISION_MAX",
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


# =============================================================================================
# 5. `ACTIONS`
# =============================================================================================

_LISTED: Final[frozenset[Profile]] = frozenset(PROFILES)
"""Both profiles. The four front-door Actions are listed everywhere, which check 6 requires anyway:
`default` implies `full`, because a profile that is not a superset of the one below it would make
`profile = "full"` a narrowing."""

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
