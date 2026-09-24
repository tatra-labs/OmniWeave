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

from omniweave.sdk.reports import (
    AddReport,
    CodeRow,
    CorporaReport,
    DoctorReport,
    HooksCheckReport,
    InstallReport,
    SkillsReport,
)
from omniweave.surface.inputs import (
    AddIn,
    CorporaIn,
    CoverageIn,
    DiffIn,
    DoctorIn,
    ExplainIn,
    GridIn,
    HooksCheckIn,
    InstallIn,
    OpenIn,
    QueryIn,
    SkillsInstallIn,
    SkillsRemoveIn,
    UninstallIn,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from omniweave_ports import Scalar

__all__ = [
    "ACTIONS",
    "CLI_ABSENT",
    "CLI_FREE",
    "CLI_RESOLVED",
    "CLI_ROSTER",
    "CLI_UNROSTERED",
    "DECISION_MAX",
    "FULL_ROSTER",
    "GROUPS",
    "HUMAN_ONLY",
    "MCP_NAME_RE",
    "PROFILES",
    "SUMMARY_MAX",
    "ActionSpec",
    "CliStatus",
    "Profile",
    "assert_sv1",
    "listed",
    "resolve_cli",
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

CLI_ROSTER: Final[Mapping[str, tuple[str, ...]]] = {
    "add": (),
    "audit-config": (),
    # 12:1968 declares this one a CLOSED SET and declares it is not a verb list: *"the second word
    # is a positional subject from a closed set -- one function per subject in
    # `omniweave/run/bench.py`"*. It is rostered here anyway, because the property a roster
    # checks -- may this second word appear after this root? -- is the same property either way,
    # and a closed set left unrostered is a set nothing compares the plan against. `answer` is
    # used three times and is not in it; D303.
    "bench": (
        "cold",
        "compile",
        "embed",
        "encoding",
        "incremental",
        "inproc",
        "pacer",
        "parse",
        "query",
        "route",
        "rss",
        "scheduler",
        "service",
    ),
    "cache": ("prune", "stat"),
    "check": (),
    "conform": (),
    "corpora": (),
    "cost": (),
    "deps": (),
    # 18:918 prints `show` / `verify` / `grid`; `diff` is 03:1302's, where a quarantined generation
    # is *"durable and invisible for inspection by `ow doc diff`"*. Four, from two documents.
    "doc": ("diff", "grid", "show", "verify"),
    "doctor": (),
    # 18:918, *"7 verbs: `list explain add verify ack check scaffold`"*. The one group whose
    # printed count, printed roster and plan usage all agree.
    "drivers": ("ack", "add", "check", "explain", "list", "scaffold", "verify"),
    # No document rosters these. 18:918 prints `ow eval …` with an ellipsis, so the twelve below
    # are the plan's own usage, collected the way 07's `ow store` roster had to be. D302.
    "eval": (
        "bless",
        "calibrate",
        "correlate",
        "explain",
        "fetch",
        "golden",
        "import",
        "prune",
        "publish",
        "record",
        "release-check",
        "run",
    ),
    "explain": (),
    # 18:918's sixteen, in that row's order re-sorted. `merge` and `merges` are two verbs that
    # differ by one character and by write access (18:957), and both are here for that reason.
    # Four of the sixteen -- `cluster`, `converge`, `diff`, `report` -- occur nowhere else in the
    # plan, which is 18's Open question 6 and D304.
    "graph": (
        "build",
        "cluster",
        "converge",
        "diff",
        "doctor",
        "explain",
        "locate",
        "merge",
        "merges",
        "plan",
        "report",
        "residue",
        "review",
        "split",
        "types",
        "why",
    ),
    "hook": (),
    "hooks": ("check",),
    # 18:952 names this roster unpublished and 18's Open question 5 asks 07 to publish it. Six,
    # from usage. D302.
    "index": ("drop", "rebuild", "segments", "stats", "update", "vectors"),
    "ingest": (),
    "install": (),
    # 18:918, `ow make deck|pptx|docx|video <selection>`. `make.deck` is 10:43's Action name.
    "make": ("deck", "docx", "pptx", "video"),
    "open": (),
    # 18:918's eleven plus `list`, which 10:820 rosters as the `full`-profile Action `out.list`
    # and 14:1200 invokes as `ow out list --erased`. `project` is the reverse case: printed here,
    # invoked nowhere. `preview` is the third: invoked twice, printed nowhere. D305.
    "out": (
        "assets",
        "back",
        "check",
        "compile",
        "constructs",
        "list",
        "normalize",
        "project",
        "scaffold",
        "stamp",
        "targets",
        "verify",
    ),
    "parse": (),
    "query": (),
    # 18:918, `status` / `retry` / `reset`. `ow queue explain` is used twice and is not here; D305.
    "queue": ("reset", "retry", "status"),
    "rebind": (),
    "replay": (),
    # 18:918, *"8 verbs: `explain replay simulate lint scoreboard propose promote audit`"*.
    # `audit` is printed and never invoked; `promote` is `route.promote`, one of HUMAN_ONLY's five.
    "route": ("audit", "explain", "lint", "promote", "propose", "replay", "scoreboard", "simulate"),
    "schema": ("emit",),
    "serve": (),
    "services": (),
    # 18:918, `ls` / `show` / `clear`.
    "session": ("clear", "ls", "show"),
    "show-config": (),
    # 18:918's six plus `remove`, which 10:1429 carries as a note rather than a cell --
    # *"`remove` is human-only"* -- and which `HUMAN_ONLY` rosters as `skills.remove`.
    "skills": ("check", "hash", "install", "ls", "remove", "update", "verify"),
    # THE ROSTER 18'S OPEN QUESTION 5 ASKS FOR, and the reason this constant exists at all.
    # 18:948: *"18's own rows said '20 verbs' and '5 verbs' while the plan already used at least
    # twenty-six distinct `ow store <verb>` spellings"*. Twenty-four, collected from the plan's
    # own usage across nine documents, because 07 publishes no table and 10 section 6.1 points at
    # 07 for one -- a pointer to a roster nobody has enumerated. D302.
    "store": (
        "backup",
        "compact",
        "diff",
        "doctor",
        "explain",
        "export",
        "fsck",
        "gc",
        "git-install",
        "import",
        "key-export",
        "key-list",
        "lock",
        "merge-lock",
        "migrate",
        "rebuild",
        "redact",
        "rekey",
        "repair",
        "residue",
        "rm",
        "stats",
        "vacuum",
        "verify",
    ),
    # 18:918, `list` / `emit` / `budget` / `typescript`.
    "surface": ("budget", "emit", "list", "typescript"),
    # `install` is 18:918's; `remove` is `HUMAN_ONLY`'s `targets.remove` and appears in no table.
    "targets": ("install", "remove"),
    "test": ("crash-matrix",),
    "top": (),
    # 15-observability owns these four; 18:918 gives `ow trace` no printed verbs. D302.
    "trace": ("export", "prune", "stat", "tree"),
    "uninstall": (),
    "why": (),
}
"""Every legal second word, per CLI root. 18:948's *"a count is not a roster"*, made a register.

`GROUPS` says what a root may be; this says what may follow one. The two are checked against each
other at import, because a root with no entry is a root nothing can validate a spelling under, and
an entry under no root is a roster for a command that cannot be typed.

**An empty tuple is not an empty roster.** It means the root takes no second WORD from a closed
set -- `ow query "<question>"`, `ow open d7#412`, `ow add policy.pdf`. Those roots are in
`CLI_FREE`, and the resolver reads whatever follows them as data. A root with an empty tuple and no
`CLI_FREE` membership would be a bare verb taking nothing at all, which is a legal shape
(`ow doctor`, `ow top`) and the reason the two facts are two constants rather than one.

**The verbs are transcribed, never invented, and where the plan publishes no table that is said
out loud.** 18:918's command surface prints a roster for eleven of the twenty-two roots that have
one. For `ow store`, `ow index`, `ow eval` and `ow trace` it prints a pointer or an ellipsis
instead, and 18's Open question 5 records that the pointer for the first two *"names a roster
nobody has enumerated"*. Those four entries are collected from the plan's own usage -- every
`ow <root> <word>` spelling that occurs inside backticks in `_plan/*.md` -- which is the only
source available and is exactly what Open question 5 asks 07 to write down. D302 is the entry.

**10:1413's arity rule is violated by five of these roots and the violation is in the plan, not
here.** *"A group only at three or more verbs"*: `cache` has two, `targets` has two, and `hooks`,
`schema` and `test` have one each. Every one of the five is printed by 18:918 with exactly those
verbs, so the grammar and the command surface disagree on five rows. D306.
"""

CLI_FREE: Final[frozenset[str]] = frozenset(
    {
        "add",
        "conform",
        "corpora",
        "doc",
        "eval",
        "explain",
        "graph",
        "hook",
        "open",
        "out",
        "parse",
        "query",
        "route",
        "show-config",
        "skills",
        "store",
        "targets",
        "test",
        "why",
    }
)
"""The roots whose second or later word may be DATA rather than a name this registry knows.

Two kinds are in here and they are not the same kind. A root with an empty `CLI_ROSTER` entry takes
its argument immediately -- `ow open d7#412`, `ow explain OW-A-013`, `ow why absent`. A root with a
non-empty entry takes its argument AFTER the verb -- `ow store export parquet`,
`ow graph merge e412 e997`, `ow doc verify msa-2024` -- and the resolver only ever reads the first
two words, so membership here says what the third word onwards may be.

`why` is the uncomfortable one. `ow why absent` occurs five times and is specified by name at
15:914 (*"the one an agent needs most, because a zero result is the answer most likely to be
wrong"*), which reads much more like a closed subject than like a cite. It is left free because no
document rosters a second member, and a one-member closed set is a set that cannot be wrong.
"""

CLI_ABSENT: Final[Mapping[tuple[str, ...], str]] = {
    ("benchmark",): "12:1968 -- no two groups may differ only by a suffix; the group is `ow bench`",
    ("driver",): "10:237 -- the singular the trailing-`s` rule forbids; `ow drivers` is the group",
    ("export",): "10:1465 -- the one spelling is `ow store export`, so d2 resolves one name",
    ("init",): "10:1469 -- `ow install` wires hosts, `ow add` creates a corpus; two receipts",
    ("watch",): "16:586 -- `op.converge` shipped so a watcher is a scheduler's job, not a verb",
    ("ask",): "terminology.md:967 -- the lock's rejected query verb; one name, no alias",
    ("find",): "terminology.md:968 -- the same row family, and the same one name",
    ("search",): "terminology.md:969 -- the same family; the cold-start gate measures `ow query`",
    ("store", "rebalance"): "18:3319 -- 11 section 8.6's deliberate not-in-registry name",
}
"""Spellings the plan writes down in order to say they do not exist.

Every one is a sentence of the form *"there is no `ow <x>`"*, and every one of those sentences is
the reason a reader would otherwise expect the name. They are registered rather than simply omitted
because a resolver that silently failed on them would be reporting the plan's own prose as a defect,
and because `ow store rebalance` has a stronger claim than the rest: 18:3319 says it *"must stay out
of `ACTIONS` whatever 07 decides"*, since 11 section 8.6 uses it as the worked example of a name
that does NOT resolve. A register with a row for it is how that stays true through an edit.

The last three come from the terminology lock rather than from a plan document, and they are the
only rows here that were never candidates: `ow ask`, `ow find` and `ow search` are three spellings
of `ow query` the lock refuses by name, with one reason for all three -- *"One name, no alias; the
cold-start gate measures it"*. A lock that names a rejected spelling has already done the work a
register does, so the rows are a transcription and not a decision.
"""

CLI_UNROSTERED: Final[Mapping[tuple[str, ...], str]] = {
    ("bench", "answer"): "12:1968's closed set omits it; used at 10:2662, 10:2739, 17:667. D303",
    ("out", "preview"): "printed by no verb table; used at 09:2865 and 17:662. D305",
    ("plan", "lint"): "18:3227 and charter:8762 name the verb; `plan` is not a declared root. D307",
    ("queue", "explain"): "18:918's `ow queue` prints status/retry/reset; used at 08:1991. D305",
    ("resume",): "10:1473 says it does not exist; six sites invoke it, two of them gates. D301",
}
"""Spellings the plan USES that no roster carries. Each value names the defect it belongs to.

This is the ratchet, and it is the half of the register that has to be able to shrink. A spelling
the plan names and nothing rosters is a defect whichever way it is resolved -- the roster gains a
row or the document loses a sentence -- so leaving it unrecorded would mean the resolver either
fails on the plan as it stands or passes by not looking. `plan_lint`'s `cli-verbs` rule fails on a
spelling that is in none of the four registers AND on a row here that no longer occurs, so a fix
lands with its row struck rather than leaving a register that quietly stopped describing anything.

`("resume",)` is the one to read first. 10:1473 states its absence and calls it load-bearing --
*"a second recovery protocol that has to agree with the first, which AP-5 forbids by name"* -- and
then 00:710's acceptance criterion V01-9, 11:1564's G21 row, 02:1137, 16:445 and 16:569 all invoke
it as the command that converges after a kill. An acceptance criterion and a gate row naming a verb
the interfaces document says does not exist is not a spelling mistake; D301 is the entry.
"""
CliStatus = Literal[
    "verb", "argument", "bare", "absent", "unrostered", "no-such-root", "no-such-verb"
]
"""What `resolve_cli()` can say about a spelling. Seven answers, five of them not a finding."""

CLI_RESOLVED: Final[frozenset[CliStatus]] = frozenset(
    {"verb", "argument", "bare", "absent", "unrostered"}
)
"""The five statuses a caller treats as resolved, and the reason there are five rather than three.

`verb`, `argument` and `bare` are the spelling being legal. `absent` and `unrostered` are the
spelling being *known* -- the plan writes it down, a register carries it, and the register says
which. A resolver with three answers would have to report the plan's own *"there is no `ow
export`"* as a defect, and the only cure for that is an exception list nobody can audit; two more
statuses put the exceptions in a mapping with a citation per row instead.

The two outside this set are `no-such-root` and `no-such-verb`, and they are what 11 section 8.6
clause d2 fails on: *"`ow store rebalance` -- not in the ACTIONS registry (nearest:
`ow store reshard`)"*.
"""


ROOT_AND_VERB: Final[int] = 2
"""The number of words in a fully spelled `ow <group> <verb>`, and the widest register key.

Named because it is two different facts that happen to be the same integer: the longest spelling
either exception register holds, and the point past which a root must be in `CLI_FREE` to carry
another word. Writing `2` twice would let one of them move without the other.
"""


def _registered_spelling(words: Sequence[str]) -> CliStatus | None:
    """`absent` or `unrostered` if either exception register holds this spelling, else `None`.

    LONGEST FIRST, and that order is the whole of `resolve_cli`'s subtlety: `ow store rebalance`
    has a rostered root and `store` is in `CLI_FREE`, so a lookup that tried the root first would
    read `rebalance` as an argument and report the one name 18:3319 requires never to resolve as
    perfectly ordinary.
    """
    for width in range(ROOT_AND_VERB, 0, -1):
        key = tuple(words[:width])
        if key in CLI_ABSENT:
            return "absent"
        if key in CLI_UNROSTERED:
            return "unrostered"
    return None


def resolve_cli(words: Sequence[str]) -> CliStatus:
    """Resolve one `ow <...>` spelling against the four CLI registers. 11 section 8.6 clause d2.

    The registers are consulted LONGEST FIRST, and that order is the whole of the function's
    subtlety. `ow store rebalance` has a rostered root, and `store` is in `CLI_FREE`, so a resolver
    that checked the root before the spelling would read `rebalance` as an argument and report the
    one name 18:3319 requires never to resolve as perfectly fine.

    After the registers, the rule is 10:1413's grammar and nothing else:

    - a root with a non-empty `CLI_ROSTER` entry takes a VERB as its second word, and `CLI_FREE`
      then governs the third word onwards (`ow store export parquet`, `ow graph merge e412 e997`);
    - a root with an empty entry takes its argument immediately if it is in `CLI_FREE`
      (`ow open d7#412`) and takes nothing at all if it is not (`ow doctor`, `ow top`).

    Only the first two words decide the status; the rest decide whether the root had to be free to
    carry them. That is why `ow doc verify msa-2024` resolves and `ow doctor --runtime` never
    reaches this function -- a flag is not a word this grammar has an opinion about, and the caller
    strips it.
    """
    if not words:
        return "no-such-root"
    registered = _registered_spelling(words)
    if registered is not None:
        return registered
    verbs = CLI_ROSTER.get(words[0])
    if verbs is None:
        return "no-such-root"
    if len(words) == 1:
        return "bare"
    free = words[0] in CLI_FREE
    if verbs:
        rostered = words[1] in verbs and (len(words) == ROOT_AND_VERB or free)
        return "verb" if rostered else "no-such-verb"
    return "argument" if free else "no-such-verb"


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


def _cli_roster_failures(actions: Mapping[str, ActionSpec]) -> tuple[str, ...]:
    """The reconciliation between the four CLI registers and the rows. Not one of the eleven.

    `_roster_failures()` does this for `FULL_ROSTER` and this is the same shape one surface over,
    with one difference that is worth stating: a `full`-profile listing is a property of a ROW, so
    that function reads `ACTIONS` first and the roster second. A CLI spelling is a property of the
    GRAMMAR, so this one checks the registers against each other before it looks at a row at all --
    a roster with a root `GROUPS` does not carry validates nothing, whether or not a row uses it.

    Six clauses:

    1. `CLI_ROSTER`'s keys are exactly `GROUPS`. A root with no entry is a root under which no
       spelling can be checked; an entry under no root is a roster for a command nobody can type.
    2. Every entry is sorted and free of duplicates. Sorted because 10:229 makes the generator
       pure -- *"no iteration over an unsorted set"* -- and this is one of its inputs; free of
       duplicates because a roster that lists a verb twice is a roster somebody edited twice.
    3. `CLI_FREE` names only rostered roots.
    4. No `CLI_ABSENT` or `CLI_UNROSTERED` key is ALSO rostered. A spelling that is both registered
       as missing and carried as a verb is the register describing a surface that moved out from
       under it, and it is the failure both mappings exist to make impossible.
    5. The two mappings are disjoint, because `absent` and `unrostered` are opposite claims about
       the same spelling -- the plan meant to omit it, or the plan forgot it.
    6. Every row's `cli` resolves to `verb` or `bare`. Not to `argument`: an Action whose CLI
       spelling is data would be a row the generator cannot emit a subparser for.
    """
    out: list[str] = []
    missing = sorted(GROUPS - set(CLI_ROSTER))
    extra = sorted(set(CLI_ROSTER) - GROUPS)
    out.extend(f"CLI_ROSTER: no entry for the declared root {root!r}" for root in missing)
    out.extend(f"CLI_ROSTER: {root!r} is not a declared root" for root in extra)
    for root, verbs in sorted(CLI_ROSTER.items()):
        if list(verbs) != sorted(set(verbs)):
            out.append(f"CLI_ROSTER[{root!r}] is not sorted and unique: {list(verbs)}")
    out.extend(
        f"CLI_FREE names {root!r}, which is not a rostered root"
        for root in sorted(CLI_FREE - set(CLI_ROSTER))
    )
    for label, register in (("CLI_ABSENT", CLI_ABSENT), ("CLI_UNROSTERED", CLI_UNROSTERED)):
        for spelling in register:
            verbs = CLI_ROSTER.get(spelling[0])
            rostered = verbs is not None and (
                (len(spelling) == 1 and not verbs) or (len(spelling) > 1 and spelling[1] in verbs)
            )
            if rostered:
                out.append(f"{label} names {' '.join(spelling)!r}, which CLI_ROSTER also carries")
    for spelling in sorted(set(CLI_ABSENT) & set(CLI_UNROSTERED)):
        out.append(f"{' '.join(spelling)!r} is registered both absent and unrostered")
    for name, spec in actions.items():
        if spec.cli and resolve_cli(spec.cli) not in {"verb", "bare"}:
            out.append(
                f"{name}: cli {' '.join(spec.cli)!r} resolves {resolve_cli(spec.cli)}, "
                f"which is not a spelling the generator can emit"
            )
    return tuple(out)


def _unrostered_cli(actions: Mapping[str, ActionSpec]) -> tuple[tuple[str, ...], ...]:
    """Every `CLI_ROSTER` spelling with no `ActionSpec` row, sorted. The distance to the registry.

    `_unrostered_full()` counts thirteen and `_unrostered_human_only()` counts five; this one
    counts what is left of 10:857's *"roughly 110 further Actions"* after the rows that have
    landed, and it is the number that says how far P7 W7.1 still has to run. It reports rather than
    raises for the same reason both of those do, and for one more: 10:857's roster is blocked on
    output types by D298 and D300, so every row here is waiting on a decision made elsewhere.

    A root with an empty entry contributes ONE spelling -- itself -- because `ow doctor` is a
    command and `ow doctor <verb>` is not a shape the grammar has.
    """
    have = {spec.cli for spec in actions.values() if spec.cli}
    out: list[tuple[str, ...]] = []
    for root, verbs in CLI_ROSTER.items():
        spellings = [(root, verb) for verb in verbs] if verbs else [(root,)]
        out.extend(spelling for spelling in spellings if spelling not in have)
    return tuple(sorted(out))


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
    out.extend(_cli_roster_failures(actions))  # nor is this one
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
        #  10:53's row 1: an Action that modifies omniweave's installed configuration is human-only
        #  and has no `mcp_name`. `install` writes an agent host's MCP entry, its permissions and
        #  its hooks, so row 1 matches it -- though 10:59's five and 10:859's "every other Action
        #  has an mcp_name" leave it out. The first match wins (10:48), the safe one. D469.
        ActionSpec(
            name="install",
            mcp_name=None,
            listed_in=frozenset(),
            read_only=False,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Wire agent hosts to omniweave: the MCP entry, one permission wildcard, the "
                "instruction block, hooks and the core skill, each recorded in a receipt"
            ),
            decision="an agent host should reach omniweave and does not yet",
            example={
                "target": "claude-code",
                "location": "global",
                "hooks": "context",
                "skills": "core",
                "dry_run": True,
            },
            inp=InstallIn,
            out=InstallReport,
            cli=("install",),
        ),
        ActionSpec(
            name="uninstall",
            mcp_name=None,
            listed_in=frozenset(),
            read_only=False,
            idempotent=True,
            open_world=False,
            destructive=True,
            cost_class=CostClass.FREE,
            summary=(
                "Take omniweave out of agent hosts exactly: every path the install receipt names, "
                "on its digest, and never the corpus index"
            ),
            decision="an agent host should stop reaching omniweave",
            example={"target": "all", "location": "global", "yes": True},
            inp=UninstallIn,
            out=InstallReport,
            cli=("uninstall",),
        ),
        #  10:53's row 1 again: a skill is omniweave's steering surface in an agent host, so writing
        #  one is the installed configuration row 1 names, and there is no `mcp_name` -- the rule
        #  `install` follows (D469). The agent still runs it: the router's section 4 says
        #  `ow skills install <name>`, and 10:102 is *"The skills shell out to `ow`"*. A shell is
        #  not an MCP dispatch, and row 1 is about the second. D489.
        ActionSpec(
            name="skills.install",
            mcp_name=None,
            listed_in=frozenset(),
            read_only=False,
            idempotent=True,
            open_world=False,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Copy a shipped skill bundle into every discovered agent-host skills directory, "
                "verified on its whole-bundle digest and recorded in skills-lock.json"
            ),
            decision="a route needs a skill body that is not installed yet",
            example={"name": "omniweave-pptx"},
            inp=SkillsInstallIn,
            out=SkillsReport,
            cli=("skills", "install"),
        ),
        #  One of HUMAN_ONLY's five (10:59), so check 4 already requires what this row declares.
        ActionSpec(
            name="skills.remove",
            mcp_name=None,
            listed_in=frozenset(),
            read_only=False,
            idempotent=True,
            open_world=False,
            destructive=True,
            cost_class=CostClass.FREE,
            summary=(
                "Take a skill out of every directory skills-lock.json says ow skills install put "
                "it in, on its digest; a modified or foreign copy is kept"
            ),
            decision="a skill ow skills install placed should go",
            example={"name": "omniweave-pptx", "yes": True},
            inp=SkillsRemoveIn,
            out=SkillsReport,
            cli=("skills", "remove"),
        ),
        #  10:57's row 5: not irreversible, spends nothing, writes nothing a user opens, and not a
        #  pure function of the corpus -- so an `mcp_name`, unlisted and not enabled. 10:57 spells
        #  it `ow_<verb>`; the verb is `check`, which names nothing alone, so the group is kept.
        #  `open_world`: it runs the installed commands, which are outside the store (10:157-158).
        ActionSpec(
            name="hooks.check",
            mcp_name="ow_hooks_check",
            listed_in=frozenset(),
            read_only=True,
            idempotent=True,
            open_world=True,
            destructive=False,
            cost_class=CostClass.FREE,
            summary=(
                "Run each installed hook command as its host would, with a probe payload in a "
                "scratch project, and say which failed and why"
            ),
            decision="a hook seems silent and you need to know whether it runs",
            example={},
            inp=HooksCheckIn,
            out=HooksCheckReport,
            cli=("hooks", "check"),
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
