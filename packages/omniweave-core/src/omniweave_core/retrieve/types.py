"""The query path's shapes -- the five §16 left here, and the vocabulary the ceiling branches on.

07-store-and-retrieval.md §16 prints eleven types and sends five of them to this package by name.
`store/types.py`'s own docstring states the split it drew and why -- Section 16's other five,
`FusionSpec`, `PackSpec`, `QueryBudget`, `RetrievalPolicy` and `VecManifest`, appear in no protocol
signature, so they are the retrieval module's and are deliberately absent there. Four of those five
are here; `VecManifest` is the vector sidecar's and arrives with the semantic Channel (W6.2).

Beside them are the four shapes the query path owns outright -- `Query` (07:2339), `QueryPlan`
(07:1534), `ChannelResult` (07:1226) and the two enums at 07:1203 -- and the five scoring constants
07:1382 homes here in as many words: *"`RRF_K = 60 ; SCORER_VERSION = 1` -- ONE constant, in
`omniweave_core.retrieve`"*. `retrieve/__init__.py` re-exports them so that sentence is literally
true of the package and not only of a module inside it.

## `OffReason` is closed at four, `ceiling()` branches on it, and the document prints three more

07:1215 is unambiguous -- *"`OffReason` is closed at four members, and this is its sole
home"* -- and gives the reason: *"it is closed because `ceiling()` branches on it (§5.3): exactly
one member, `QUERY_DEADLINE`, is ceiling-bearing, so a free-form string decides a published
`confidence` number and a misspelling changes that number with no error anywhere."*

Three reasons appear in the document outside that enum and two of them are in normative text, not
in an illustration: `OFF(short_circuit)` and `OFF(narrowing_empty)` are the effects column of
§6.5's early-exit table, and `OFF(vectors_disabled)` is worked plan 1's spelling of `VECTORS`. This
module ships the enum closed exactly as 07:1215 declares it and D236 records the gap, because the
missing ruling is arithmetic rather than spelling: every Channel at `OFF(narrowing_empty)` makes
the ceiling a sum over nothing, and `confidence = best_score / 0.0`.

`CEILING_BEARING` is a frozenset of one and is stated separately from the enum, because the
membership is the branch. A reader of `ceiling()` should not have to infer which member is special
from a comment on the enum.

## No field defaults to `...`

07:1237: *"No field defaults to `...` anywhere in a shipped shape. `x = ...` is legal Python that
binds `Ellipsis`, so the field is neither required nor defaulted and every consumer type-checks
against `EllipsisType`. A default is a real value or the field is required; those are the only two
options."* `tools/gate_no_ellipsis_default.py` is P6's exit criterion for it and is not yet
written.

Stdlib only (INV-2 / G1), inside one of the nine LAZY subpackages, so `import omniweave_core` does
not reach it (G17).

Specified in 07-store-and-retrieval.md sections 5.1, 5.3, 6, 7.3 and 16; scheduled by
16-roadmap.md:657.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from omniweave_core.operator import SpendVector
from omniweave_core.store.types import ChannelSpec, Expand, Filters

# RUNTIME imports, not `if TYPE_CHECKING:` ones, for `store/types.py`'s two stated reasons and a
# third of this file's own: `Query.filters` defaults to `NO_FILTERS` and `Rule.channels` to
# `CHANNELS`, so the names have to be real objects at class-creation time; `get_type_hints()`
# raises `NameError` on a name that exists only under `TYPE_CHECKING`, and the store package's
# neighbouring module is already read that way by `ow schema emit`'s reflector; and
# `ChannelResult.counts_in_ceiling` is the one predicate `ceiling()` may call, so a type-checker
# fiction behind it would be a fiction behind a published `confidence`.

__all__ = [
    "ABSENCE_GATES",
    "CEILING_BEARING",
    "CHANNELS",
    "DEFAULT_WEIGHTS",
    "NO_FILTERS",
    "RRF_K",
    "SCORER_VERSION",
    "ChannelResult",
    "ChannelStatus",
    "FusedHit",
    "FusionSpec",
    "OffReason",
    "PackSpec",
    "Query",
    "QueryBudget",
    "QueryPlan",
    "RetrievalPolicy",
    "Rule",
]

NO_FILTERS: Final[Filters] = Filters()
"""The empty `Filters`, as one shared instance.

`Query.filters` defaults to it rather than to `Filters()` written in the field, which ruff's RUF009
refuses on the general rule that a call in a default is evaluated once. Here that is exactly what
is wanted -- `Filters` is frozen, so one instance is every caller's -- and naming it also gives
`plan._filter_fields()` the baseline it compares a query's filters against, so "which fields did
this query set" has one answer and not two."""

CHANNELS: Final[tuple[str, ...]] = ("identity", "exact", "lexical", "structural", "semantic")
"""07:1202, and the order is the canonical run order of §6.2 -- cheapest first.

Five and not jcodemunch's four: `identity` splits into `identity` and `exact` because a document
corpus has two different exact things, *this block* and *this named thing inside a block*, with
different sources, different ladders and different weights; 07:1188 says folding them *"would
make the `exact` weight unreachable"*. `similarity` is renamed `semantic` because the Channel is a
segment-level embedding hit projected onto blocks rather than a similarity score."""

DEFAULT_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {"identity": 2.0, "exact": 1.2, "lexical": 1.0, "semantic": 0.8, "structural": 0.4}
)
"""07:1380. A `MappingProxyType` because it is a module-level default that ends up as a dataclass
field default, and a bare dict there is one `.update()` away from changing every plan in the
process."""

RRF_K: Final[int] = 60
"""The RRF smoothing constant (07:1382), jcodemunch's `DEFAULT_SMOOTHING` unchanged."""

SCORER_VERSION: Final[int] = 1
"""07:1382's *"ONE constant"*. It is on `QueryPlan` and on `eval_run`, and a second spelling of it
anywhere is how two runs claim the same scorer while computing different numbers."""

CEILING_WEIGHT_DENOMINATOR: Final[int] = RRF_K + 1
"""`_weight / (k + 1)`, named because 07:1401 forbids writing it out: *"Never hardcode
`1/(k+1)`."* The weights are not normalised to sum to 1, so the ceiling genuinely depends on which
Channels ran -- which is the point, and the named constant is the reminder."""

ABSENCE_GATES: Final[tuple[str, ...]] = (
    "timed_out",
    "channel_unavailable",
    "store_changed_mid_query",
    "coverage_incomplete",
    "pending_work_in_scope",
    "source_edited_unindexed",
    "freshness_unknown",
    "inputs_unreadable",
    "parse_gap_in_scope",
    "restricted_withheld",
    "filter_starved",
    "truncated_by_packing",
    "space_mismatch",
    "shard_unreachable",
    "similarity_only",
)
"""The fifteen, in the order of 07:2166, which says that order *"is the precedence order"*.

07:2169: it *"runs outward: gates 1-3 ask whether the search itself happened, gates 4-9 ask whether
the corpus the search ran over is whole, gates 10-12 ask whether the answer that came back is
whole, and gates 13-15 ask whether the machinery that produced it was the machinery the caller
configured."* The names are here rather than in `verdict.py` because `QueryPlan.gates` is a subset
of them and W6.1
produces that subset; the fifteen predicates are `build_verdict()`'s and are W6.5's."""


class ChannelStatus(StrEnum):
    """07:1204. `ok`/`empty` contribute weight to the ceiling; `off` is an operator choice and is
    disclosed; `unavailable` contributes nothing **and forces `degraded`**."""

    OK = "ok"
    EMPTY = "empty"
    OFF = "off"
    UNAVAILABLE = "unavailable"


class OffReason(StrEnum):
    """07:1206. CLOSED, and the only legal `reason` when status is `OFF`.

    `VECTORS`, `NOT_IN_PLAN` and `NOT_BUILT` are operator choices, and 07:1413 prices the
    difference: *"the Channel was never going to look, so its weight has no business in a
    denominator that measures 'we looked there'"*. `QUERY_DEADLINE` is a runtime shortfall -- the
    Channel was in the plan, the query ran out of time -- and exempting it *"shrinks the
    denominator and makes a worse answer report higher confidence, which is the exact inversion
    `ceiling()` exists to prevent"*.
    """

    VECTORS = "vectors"
    NOT_IN_PLAN = "not_in_plan"
    NOT_BUILT = "not_built"
    QUERY_DEADLINE = "query_deadline"


CEILING_BEARING: Final[frozenset[OffReason]] = frozenset({OffReason.QUERY_DEADLINE})
"""The one member of `OffReason` whose weight stays in the ceiling (07:1414).

A frozenset of one, stated here rather than as a comment on the enum, because this membership IS
`ceiling()`'s branch and a reader should not have to infer an arithmetic rule from prose. W6.3
reads
it; nothing else may re-derive it."""


@dataclass(frozen=True, slots=True)
class ChannelResult:
    """One Channel's output (07:1226). The record the two-deadline split writes its difference into.

    `store/types.py` carries this name as one of three deliberately unresolved forward
    references -- `Reader.channel()` returns it and 07:3348 sends it to the query path -- and
    homing it here does not resolve that annotation: the store would have to import the query path
    to do that, which inverts 02's row 26/27 boundary. The forward reference stays one.

    `rank_of` is 07:1240's addition to the charter's shape and the reason is the semantic Channel:
    *"a segment hit at rank r yields its member blocks at rank r"*, so up to 64 blocks share one
    rank. A positional derivation would spread them across 64 distinct ranks and destroy exactly
    the region-level property the rule preserves. It is empty for every Channel but `semantic`.
    """

    name: str
    status: ChannelStatus
    ranked: tuple[int, ...] = ()
    rank_of: Mapping[int, int] = field(default_factory=lambda: MappingProxyType({}))
    spans: Mapping[int, object] = field(default_factory=lambda: MappingProxyType({}))
    grades: Mapping[int, str] = field(default_factory=lambda: MappingProxyType({}))
    weight: float | None = None
    reason: str = ""
    truncated_at_limit: bool = False
    ran_ms: int = 0
    cost: SpendVector | None = None

    @property
    def counts_in_ceiling(self) -> bool:
        """07:1396's `OR` clause, as a predicate rather than as three comparisons at each call site.

        `OK` and `EMPTY` count; `OFF` counts only for `CEILING_BEARING`; `UNAVAILABLE` never does.
        An `OFF` whose reason is outside `OffReason` counts as NOT bearing and that is D236's
        subject -- three such reasons are printed in the document and none has a ruling.
        """
        if self.status in (ChannelStatus.OK, ChannelStatus.EMPTY):
            return True
        if self.status != ChannelStatus.OFF:
            return False
        return any(self.reason == member.value for member in CEILING_BEARING)


def _weight(result: ChannelResult, weights: Mapping[str, float]) -> float:
    """07:1385's three-level resolution, in the one place ST6 requires it to have.

    07:1484 states the precedence and names the sentinel. `ChannelResult.weight` is *"an explicit
    float, **including `0.0`**"*; `0.0` *"is a value, not "unset", and `_weight()`'s three-level
    resolution (explicit -> named default -> 1.0) with `None` as the sentinel is what makes the
    distinction representable"*. So the first branch tests `is not None` and never truthiness, and
    the fall-through to `1.0` is for a Channel name `DEFAULT_WEIGHTS` does not carry -- which is
    every future sixth Channel, weighted like an unweighted one rather than like a silent zero.

    **It lives here and not in `fuse.py` or `ceiling.py`.** ST6 (07:3240) is the claim that the two
    functions *"share `_weight()`"*, and 07:1428 prices a breach: *"A ceiling that drifts from the
    scorer silently rescales every confidence number in the product."* A rule homed inside either
    function makes the other an importer of its sibling's private name, and the import direction
    would then declare one of the two authoritative when neither is. Here it sits beside the field
    it resolves and beside `counts_in_ceiling`, the other rule the ceiling reads, and the two
    callers are peers.

    D258: nothing bounds the returned float below. `0.0` is blessed by 07:1484 and it is also the
    denominator's only zero.
    """
    if result.weight is not None:
        return result.weight
    return weights.get(result.name, 1.0)


def _channel_set(results: Iterable[ChannelResult]) -> tuple[ChannelResult, ...]:
    """The argument both functions are stated over: materialised once, and unique by `name`.

    Two jobs, shared rather than done twice. It **materialises**, because 07:1387-1388 print both
    signatures over one `chs` and a caller holding a generator would hand `ceiling()` an iterator
    `fuse()` had already drained -- a denominator of `0.0` under a real numerator, with nothing
    raised.

    And it refuses a **repeated name**, because the two functions disagree about a duplicate in
    exactly the direction 07:1428 forbids: `ceiling()` sums over rows, so a Channel named twice
    counts twice, while `fuse()` keys its contributions by name, so the second occurrence silently
    replaces the first. One caller mistake, a confidence halved, and no error anywhere. A
    name-keyed channel set is what the record downstream is shaped for in any case -- 07:2014 makes
    `Verdict.channels` a mapping with *"ALL FIVE members of CHANNELS, ALWAYS present"*.
    """
    unique: dict[str, ChannelResult] = {}
    for result in results:
        if result.name in unique:
            msg = (
                f"two ChannelResults named {result.name!r} were handed to one fusion: "
                f"ceiling() would count that weight twice and fuse() would keep only the second "
                f"contribution, so the pair disagrees by construction -- fix: pass one result per "
                f"Channel name, which is what QueryPlan.channels and Verdict.channels both are"
            )
            raise ValueError(msg)
        unique[result.name] = result
    return tuple(unique.values())


@dataclass(frozen=True, slots=True)
class FusedHit:
    """07:1450. One fused result, and the two mappings that make a fusion tunable.

    07:1458: *"**A fusion returning only a score is one you cannot tune**: the per-Channel
    contributions and ranks are what make `ow query --explain` and weight fitting possible at
    all."* Neither mapping therefore has a default -- a `FusedHit` carrying a score and nothing
    else is the shape this one exists to refuse, and 07:1237 leaves exactly two options, a real
    default or a required field.

    **`__post_init__` refuses a rank below 1.** 07:1425: *"`rank` being 1-based matters because
    `ceiling` hardcodes `k + 1` as the best attainable term: a 0-based implementation silently
    yields `confidence > 1`."* The check is on the SHAPE and not only inside `fuse()`, because
    `--explain` and the offline weight fitter read `channel_ranks` off hits they did not build.
    The other check is that the two mappings carry the same keys: a contribution with no rank is a
    number nobody can re-derive, and a rank with no contribution is a Channel that scored nothing
    while claiming to have ranked something.

    The order is `(-score, block_id)` and it is TOTAL (ST7, 07:1455). `fuse()` sorts on it; a
    consumer that re-sorts on anything else re-introduces the tie the total order exists to remove,
    and 07:1455 names when it bites -- *"Ties broken by storage order are nondeterministic across a
    `VACUUM` or an FTS5 `'optimize'`"*, both of which section 2.2 schedules.
    """

    block_id: int
    score: float
    channel_contributions: Mapping[str, float]
    channel_ranks: Mapping[str, int]

    def __post_init__(self) -> None:
        if set(self.channel_ranks) != set(self.channel_contributions):
            msg = (
                f"block {self.block_id} carries contributions from "
                f"{sorted(self.channel_contributions)} and ranks from "
                f"{sorted(self.channel_ranks)}: 07:1452 gives a FusedHit one Channel set and both "
                f"mappings are keyed by it -- fix: emit both keys from the same loop over the "
                f"Channels that ranked this block"
            )
            raise ValueError(msg)
        for name, rank in self.channel_ranks.items():
            if rank < 1:
                msg = (
                    f"channel {name!r} reports rank {rank} for block {self.block_id}: 07:1392 "
                    f"makes rank 1-BASED and in [1, len(ranked)], and 07:1425 says why -- "
                    f"`ceiling` hardcodes k + 1 as the best attainable term, so a 0-based rank "
                    f"silently yields confidence > 1 -- fix: 1 + the position, never the position"
                )
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class QueryBudget:
    """07:3313. `query_ms` bounds the SNAPSHOT-HELD phase only. `embed_ms` is outside it.

    `hydration_reserve_ms` is *"hydration + the coverage scan. NOT a Channel, NOT schedulable"*,
    and it is what `ow route lint` check 3 adds to `sum(channel_ms)` before comparing against
    `query_ms` -- `15 + 25 + 50 + 40 + 80 = 210, + 40 reserved = 250`, exactly equal and therefore
    passing a `<=`. `snapshot_ms` is a WAL-valve safety parameter clamped below `MAX_SNAPSHOT_MS`,
    never a UX one: 07:1822 records 30 s of pinned WAL producing 22 GB of WAL and exit 137.
    """

    query_ms: int = 250
    hydration_reserve_ms: int = 40
    embed_ms: int = 120
    snapshot_ms: int = 2_000
    federate_ms: int = 40
    channel_ms: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType(
            {"identity": 15, "exact": 25, "lexical": 50, "structural": 40, "semantic": 80}
        )
    )
    max_micros: int = 0

    @property
    def schedulable_ms(self) -> int:
        """`query_ms - hydration_reserve_ms` -- what the Channels may spend between them."""
        return self.query_ms - self.hydration_reserve_ms


@dataclass(frozen=True, slots=True)
class FusionSpec:
    """07:3305. The fusion constants as the plan fixed them, so a run records what it scored
    with."""

    k: int = RRF_K
    weights: Mapping[str, float] = DEFAULT_WEIGHTS
    low_confidence: float = 0.35


@dataclass(frozen=True, slots=True)
class PackSpec:
    """07:3310 -- *"what RETRIEVAL bounds. The Answer allocator is D9's."*"""

    k: int = 20
    max_blocks: int = 60
    max_chars: int = 24_000
    hydrate_text: bool = True
    with_spans: bool = True


@dataclass(frozen=True, slots=True)
class Query:
    """07:2339. The caller's whole request, and a bound on work rather than on prose.

    07:2346: *"`k = 20` bounds fusion output; `max_blocks = 60` bounds hydration; `max_chars =
    24_000` bounds the text hydration reads, applied per response, in `hits` order, so the drop is
    deterministic and the cut is at a block boundary."*

    There is no `corpora` field and 07:2361 states the reason: *"`retrieve()` takes one `Reader`, a
    `Reader` is one store, and a store is one corpus."* Cross-corpus BM25 scores are incomparable
    for the same reason cross-shard ones are, and a surface spanning corpora issues N calls and
    discloses `fusion_kind = "rank_merge"`.
    """

    text: str = ""
    refs: tuple[str, ...] = ()
    filters: Filters = NO_FILTERS
    mode: Literal["find", "cite", "explore", "prove_absent"] = "find"
    k: int = 20
    max_blocks: int = 60
    max_chars: int = 24_000
    space_id: int | None = None
    expand: Expand | None = None
    budget: QueryBudget | None = None

    @property
    def text_terms(self) -> int:
        """The `query.text_terms` a rule reads, as a whitespace count and nothing cleverer.

        The sanitiser of 07 §5.2 is the lexical Channel's and lifts reference-shaped tokens out to
        `Query.refs` before FTS5 sees the residue; it runs at bind time, inside `retrieve()`, and
        `plan()` may not reach it -- the planner's memo key excludes the query text, so a count
        that depended on the sanitiser's output would make two plans of the same shape differ. A
        rule comparing `text_terms` against `0` or `4` (07:1717, :1725) is answered identically
        either way, which is why the cheap count is the honest one here.
        """
        return len(self.text.split())

    @property
    def has_refs(self) -> bool:
        """`query.has_refs`, the second of the four keys the shipped retrieval rules read."""
        return bool(self.refs)


@dataclass(frozen=True, slots=True)
class Rule:
    """One `[[rule]]` block at `surface = "retrieval"` -- the `then` half, plus its `when`.

    **This is not `omniweave.route.policy.Rule` and it cannot be.** D4 gives both surfaces one
    grammar, and 07:3456 says so: *"Same grammar, same loader, same subsumption linter, same
    isotonic fitter as the routing surface."* But the routing `Rule` carries a `rung` and a `Then`
    of driver/escalate_to/render, and this one carries a channel list, weights, a short-circuit
    expression and a gate modifier list -- the `when` half is shared and the `then` half is not.
    Worse, the loader that compiles either lives in the `omniweave` distribution, which
    `tools/layers.toml` forbids this one from importing. D235 is that inversion.

    `when` is a mapping from an evidence key to a clause, and `plan.py` evaluates exactly the
    clause forms the four shipped rules use and REFUSES every other one. A partial grammar that
    refused loudly was preferred to a second full implementation of D4's, which is the thing
    13:1072 names as the failure to avoid: *"two normalisers drift and a comparison starts
    depending on which one ran"*, said of a fold table and true of a rule grammar.
    """

    rule_id: str
    when: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    channels: tuple[str, ...] = CHANNELS
    weights: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    short_circuit: str = ""
    gates: tuple[str, ...] = ()
    on_unknown: str = "skip"


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """07:3327 verbatim: D4's loaded policy at `surface = "retrieval"`.

    `thresholds` is carried and never read by `plan()`: `@thresholds.<name>` is a **compile-time
    substitution** (07:1766), so a compiled rule holds the number and not the name. The mapping is
    here because `policy_digest` is a digest over it and an operator reading `--explain` wants the
    value that was substituted.
    """

    rules: tuple[Rule, ...] = ()
    thresholds: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    policy_name: str = "builtin:balanced"
    policy_digest: str = ""
    budget: QueryBudget | None = None
    """**Not in 07:3327's printed shape**, and D238 is why it is here anyway. 07:2343 makes
    `Query.budget = None` mean *"the retrieval policy's default budget"*, and the printed
    `RetrievalPolicy` has no budget to default to. `None` here falls through to
    `QueryBudget()`'s own defaults, which are §16's printed numbers and the shipped
    `retrieval.toml`'s."""


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """07:1534. A template; execution binds it.

    07:1545: *"The memo key excludes the query text, so `QueryPlan.channels` holds `ChannelSpec`s
    with `bind = None`, and `retrieve()` produces the executed specs with
    `dataclasses.replace(spec, bind=ChannelInput(...))` after phase 2. `plan_digest` is computed
    over the unbound specs, so two different queries of the same shape share a plan digest and the
    scoreboard can slice by plan -- which is the whole reason the planner is pure."*

    `channels` is ordered and **the order is the run order**. There is no second, executed-order
    field and no runtime re-ordering (07:1688).
    """

    channels: tuple[ChannelSpec, ...]
    filters: Filters
    fusion: FusionSpec
    pack: PackSpec
    gates: tuple[str, ...]
    short_circuit: str | None
    scorer_version: int
    plan_digest: str
    policy_digest: str
    rule_id: str = ""
    """Which rule selected this channel set. Not in 07:1534's printed shape and not a second
    `plan_digest`: `--explain` prints *"the rule that matched"* for the routing surface (05:1949's
    `rule_origin` is a column for exactly that), and a retrieval plan an operator cannot trace to a
    rule is one they have to diff channel lists to understand."""

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.channels)

    @property
    def budget_ms(self) -> int:
        """What the Channels may spend between them, summed. Check 3's left-hand side."""
        return sum(spec.budget_ms for spec in self.channels)
