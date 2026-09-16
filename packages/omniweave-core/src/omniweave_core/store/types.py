"""The values that CROSS the store boundary, as distinct from the boundary itself.

Implements 07-store-and-retrieval.md section 10.4 (`Snapshot`, at :2766-2769), section 6.1
(`Filters` and `Narrowing`, at :1563-1582), section 6.3's `Expand` (:1342-1351) and section 16,
"Types this document defines" (`IndexCaps` at :3271-3280, `ChannelInput` at :3282-3290,
`ChannelSpec` at :3292-3300, `Coverage` at :3331-3337).

**Why this file exists at all, when `__init__.py` could hold it.** 07:49-52 prices the boundary at
"four Protocols in `omniweave_core.store`, 33 methods in total", and 02-architecture.md:702 restates
it as "**33 methods, not four**" -- the number an ADR sizing a Postgres T3 backend reads. That claim
is only checkable by READING the file that makes it, so `__init__.py` holds four class bodies and
nothing else, and the eight value types they mention live here. The split is the same one the plan
itself draws: section 1.1 prints the Protocols, section 16 prints the shapes, and 07:3348 sends
`Hit`, `Response`, `Verdict` and `DegradeCause` away to the sections that own them.

**Only the types a `Store` or `Reader` signature names are here**, and the boundary is drawn by that
rule rather than by convenience. `Reader.narrow`, `Reader.channel` and `Reader.coverage` name
`Filters`, `ChannelSpec`, `Narrowing` and `Coverage` (07:65-68), so those four are P2's;
`ChannelSpec` names `ChannelInput` (07:3300) which names `Expand` (07:3290), so those follow it by
necessity. Section 16's other five -- `FusionSpec`, `PackSpec`, `QueryBudget`, `RetrievalPolicy`,
`VecManifest` -- appear in NO protocol signature, and `FusionSpec` and `RetrievalPolicy` need
`RRF_K`, `DEFAULT_WEIGHTS` and `Rule`, which 16-roadmap.md:468 lists among P2's non-goals. They are
the retrieval module's and are deliberately absent.

**Three names here are unresolvable forward references, and that is the honest state of the tree.**
`ChannelResult` (07:1225-1235), `Hit` (07:2250-2265) and `DegradeCause` (07:1989) belong to the
query path -- 07:3348 says so in as many words -- and `ChannelResult.cost` is a `Spend`
(05-ingest-and-routing.md:2370), which P4 owns. The plan quotes them at their use sites for the same
reason. A Protocol method has no body, so declaring a signature that names them costs nothing at
import time; what it costs is `typing.get_type_hints()`, which raises `NameError` here rather than
lying. `test_store_protocols.py` asserts the ANNOTATION TEXT against the plan instead, and asserts
which names are unresolved, so a later phase that homes them cannot do so silently.

`Grid` and `Diag` (03-document-model.md:1880, :1800) are likewise quoted rather than imported: they
are `omniweave_core.model`'s and are still owed by W2.1 (see that package's docstring, "Still owed
by P2"). The plan prints `Grid` and `Diag` UNQUOTED in `DocSink` (03:557, :563), so those two become
real imports the moment the model lands; reported.

**No `sqlite3`, deliberately.** ruff's TID251 per-file-ignore covers `store/*.py`, so this file
COULD take the import and nothing would complain. It does not, and neither does `__init__.py`:
07:75-78 makes `Snapshot.token` an opaque `object` precisely so "a Postgres `Reader` can construct a
`Snapshot` at all", and a backend-agnostic declaration that imported a backend would forfeit that by
example. `test_store_protocols.py` asserts the absence from a fresh interpreter.

Stdlib only (INV-2 / G1). Inside one of the nine LAZY subpackages (11-repo-layout.md section 1.3),
so `import omniweave_core` must not reach it -- G17.

Tier T-SCHEMA: 02-architecture.md section 2 row 26.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple

from omniweave_core.config import Scalar
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust

# `Mapping`, `Scalar`, `Kind`, `Layer`, `Method`, `Quote` and `Trust` are RUNTIME imports, not
# `if TYPE_CHECKING:` ones. Two independent reasons, and either alone would settle it:
#
# 1. `Filters.layers` defaults to `frozenset({Layer.BODY})` (07:1569) and `Expand.min_trust` to
#    `Trust.INFERRED` (07:1347) -- a default is evaluated at class-creation time, so the enum has
#    to be a real object, not a type-checker fiction.
# 2. `IndexCaps.caps_digest` is "sha256_canonical of every field above" (07:3280) and
#    `ow schema emit`'s reflector walks these annotations, both through
#    `typing.get_type_hints()`, which raises `NameError` on a name that exists only under
#    `TYPE_CHECKING`. `model/block.py` records the same decision for the same call.
#
# `omniweave_core.config` and `omniweave_core.model.enums` are stdlib-only and already resident
# whenever anything opens a store.

__all__ = [
    "ChannelInput",
    "ChannelSpec",
    "Coverage",
    "Expand",
    "Filters",
    "IndexCaps",
    "Narrowing",
    "Snapshot",
]


# ---------------------------------------------------------------------------
# The snapshot -- 07 section 10.4
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One `BEGIN DEFERRED` read view, held for the WHOLE query (ST2, 07:2760-2763).

    Transcribed from 07:2766-2769. `frozen=True, slots=True` is the plan's own decoration, and
    both halves earn their place: a query that could rebind `generation` mid-flight would defeat
    gate 3's cross-boundary comparison (07:2795-2799), and a `__dict__` on the one object every
    Channel, the hydration and the coverage scan all carry is per-query allocation for nothing.

    **`token` is typed `object`, and the annotation is load-bearing** (07:72-78). The SQLite
    backend stores its `sqlite3.Connection` there and is the only code that unwraps it, so INV-17
    ("`sqlite3.connect` appears in exactly one module") holds BY CONSTRUCTION rather than by
    review. Typing the field `sqlite3.Connection` "would make T3 unrepresentable in the type
    system -- which is the premise the whole scale-out section rests on" (07:77-78), and
    02-architecture.md:702 makes the same point from the architecture side: the token is "an
    opaque backend-owned `token: object`, never a `sqlite3.Connection`, so INV-17 holds by
    construction in a backend that has no SQLite at all". `test_store_protocols.py` reads the
    annotation off `__annotations__` and fails on anything narrower.

    `generation` is populated from INSIDE the snapshot: `snapshot()` issues `BEGIN DEFERRED`
    followed immediately by `SELECT v FROM index_state WHERE k='generation'`, because a deferred
    transaction does not acquire the read view until its first statement, and "without that first
    read, two Channels could still straddle a commit" (07:2777-2782). `schema` is an `int` here
    while `IndexCaps.schema` is a `'<major>.<minor>'` string (07:3273) -- two fields, two shapes,
    both transcribed as printed.

    `opened_ns` is what `MAX_SNAPSHOT_MS` is measured against (07:2789-2793), and the deadline it
    feeds "is a WAL-valve safety parameter, not a UX parameter": a held read pins the WAL.
    """

    token: object
    generation: int
    corpus_id: str
    schema: int
    vec_attached: bool
    opened_ns: int


# ---------------------------------------------------------------------------
# Narrowing -- 07 section 6.1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Filters:
    """FILTERS NARROW. CHANNELS SCORE WITHIN THE NARROWED SET (07:1564).

    Thirteen fields, transcribed from 07:1565-1577 in the printed order. Every default is a real
    value: 07:1237-1239 refuses `x = ...` as a field default anywhere in a shipped shape, because
    `Ellipsis` is neither required nor defaulted and every consumer then type-checks against
    `EllipsisType`.

    Four fields carry a rule the type alone does not say, and each is recorded where the plan puts
    it rather than in a validator this phase does not own:

    * `doc_keys` above `MAX_FILTER_DOC_KEYS = 1024` goes into a second TEMP table (`tmp_docs`)
      joined in, never an `IN (...)` list -- SQLite's parameter and expression-tree limits make a
      100k-element list a parse-time failure rather than a slow query (07:1608-1612).
    * `formats` containing `'owjob'` is a usage error, not an empty result (07:1567).
    * `pages` must be a `range` of step 1; any other step is a usage error, "because a strided page
      filter has no index expression and would silently become a full scan" (07:1613-1615).
    * `deny_methods` is `frozenset[Method]` and NOT `frozenset[Method] | None`, because empty means
      "no restriction" and there is no third state to represent (ST5, 07:1637-1640). `Filters()`
      and `Filters(deny_methods=frozenset())` are the same query. `deny_restriction_bits` is the
      asymmetric twin: policy sets it, never the caller (DR17, 07:1576).

    `layers` defaults to `frozenset({Layer.BODY})` rather than to everything -- furniture is
    excluded unless asked for, which is the one default in this shape that changes what a query
    returns.
    """

    doc_keys: frozenset[bytes] | None = None
    uri_prefix: str | None = None
    formats: frozenset[str] | None = None
    kinds: frozenset[Kind] | None = None
    layers: frozenset[Layer] = frozenset({Layer.BODY})
    pages: range | None = None
    sec_path_prefix: str | None = None
    lang: str | None = None
    min_trust: Trust | None = None
    min_quote: Quote | None = None
    deny_methods: frozenset[Method] = frozenset()
    deny_restriction_bits: int = 0
    gen: Literal["head"] | int = "head"


class Narrowing(NamedTuple):
    """A TAGGED three-way outcome. `if candidates:` is UNREPRESENTABLE (07:1579).

    Transcribed from 07:1579-1582. A `NamedTuple` and not a frozen dataclass, because that is what
    the plan prints -- and the choice is not arbitrary: the tag is field zero, so the first thing
    any positional read of the value yields is the tag rather than a payload.

    **The counter-example is measured, and it is why the type is tagged.** In jcodemunch's
    `build_structural_channel` (`signal_fusion.py:203-224`) `candidate_ids` was falsy-checked, so a
    query matching nothing produced an empty candidate set that SKIPPED the filter and let every
    symbol with nonzero PageRank into the Channel: the whole repository returned, ranked by
    centrality, labelled "Confident matches returned", with `absent` unreachable on both fusion
    paths (07:1670-1680). `kind="empty"` and `kind="all"` mean opposite things and no structural
    truth-test of the value can tell them apart, so semgrep bans `if narrowing:` and the tag is
    read.

    `table` is `'tmp_narrow'` iff `kind == "set"`, and `n` is EXACT in that case -- the
    `LIMIT PREFILTER_MAX + 1` probe either returns the candidate set or PROVES it too big, with no
    histogram, no independence assumption and no cost-based optimiser (07:1592-1597).
    """

    kind: Literal["all", "set", "empty"]
    table: str | None
    n: int


# ---------------------------------------------------------------------------
# What plan() may know, and what a Channel is handed -- 07 sections 6.3 and 16
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexCaps:
    """What `plan()` may know about the store. Read once, at open (07:3272).

    Seventeen fields, transcribed from 07:3273-3280. `schema` is the `'<major>.<minor>'` string of
    07 section 3.1, which `Snapshot.schema` is not -- see that class.

    `caps_digest` is "sha256_canonical of every field above; memoises plan()" (07:3280), so this
    shape's field ORDER is an input to a cache key and reordering it is a behaviour change, not a
    tidy-up. `channels` is "which of the five CAN run at all in this store" -- a store fact
    (does `block_fts` exist, is `vec` attached), never a policy or a plan.

    `stat_age_ns` above `STAT_MAX_AGE_NS` forces the over-fetch factor to its maximum of 64
    (07:3278, 07 section 3.8): a stale `stat` is treated as no information rather than as
    information, which is the only reading under which a wrong selectivity estimate cannot become
    silent recall loss.

    `scorer_version` is the one field whose MEANING this phase does not supply. P2's non-goals
    (16-roadmap.md:468) exclude every lexical scoring constant, so at P2 a backend reports it and
    nothing reads it; 16-roadmap.md:1034 hands that to P6.
    """

    schema: str
    scorer_version: int
    channels: frozenset[str]
    has_head_fts: bool
    has_trigram: bool
    fts_state: str
    space_id: int | None
    vec_backend: str | None
    vec_ceiling: int
    vec_pushdown: bool
    live_blocks: int
    live_segments: int
    docs: int
    stat_age_ns: int
    shard_ord: int
    federated: bool
    caps_digest: str


@dataclass(frozen=True, slots=True)
class Expand:
    """Structural traversal, BOUNDED BY CONSTRUCTION (07:1343).

    Transcribed from 07:1344-1351. Present in this module only because `ChannelInput.expand` names
    it (07:3290) and `ChannelSpec.bind` names `ChannelInput` (07:3300); the traversal itself is
    07 section 6.3's and its L3 half is 16-roadmap.md W8.9's.

    **`relations` has no default, and the absence is the specification** (07:1344, :1360-1362):
    "all relations" on a document graph reaches every block in the corpus within three hops, and a
    relation absent from `relation_vocab` is a usage error naming the vocabulary, "because silently
    traversing nothing is indistinguishable from a corpus with no links".

    The four ceilings exist because the alternative is a recursive CTE, and SQLite has "no built-in
    visited set and no per-hop fan-out bound, so a recursive CTE over a cyclic reference graph is
    unbounded by construction" (07:1355-1358). `max_hops` carries a HARD CAP of 4 that this shape
    does not enforce -- it is a clamp at the traversal, not a field constraint, and 07:1345 states
    it as a comment for exactly that reason.
    """

    relations: frozenset[str]
    max_hops: int = 2
    beam: int = 64
    min_trust: Trust = Trust.INFERRED
    max_visited: int = 4096
    hub_cap: int = 4096


@dataclass(frozen=True, slots=True)
class ChannelInput:
    """The QUERY material, bound AFTER `plan()` (07:3283).

    Transcribed from 07:3284-3290. Seven fields, every one defaulted, because a plan carries this
    shape's ABSENCE: `ChannelSpec.bind` is `None` in a `QueryPlan` and is set by `retrieve()`
    (07:3300), which is what lets `plan()` stay pure and memoised on query SHAPE.

    **`q_sig` and `q_full` come from phase 2 and are NEVER computed inside the snapshot** (07:3288,
    ST22). The query embedding is a Driver call, and a Driver call inside a held read transaction
    pins the WAL -- which is the futility-latch condition, so the phase split is "the only way to
    obey both" (07 Extends-the-charter row 6). Carrying the signature on the INPUT side of the
    boundary is what makes that structural: a `Reader` receives a value it could not have computed.

    **`seeds` is an EIGHTH field, added by P6 W6.2b's successor, and it is the same argument as
    `ChannelSpec.bind`'s.** The `structural` Channel is *"seeded from the union of the `identity`
    and `exact` ranked sets; when both of those are empty, from the ranked set of whichever scoring
    Channels **precede it in this plan** ... and when no scoring Channel precedes it, from
    `tmp_narrow` itself"* (07:1327-1332). Choosing the seed is 07:1333's *"runtime step"*, which
    means `retrieve()` chooses it -- and `Reader.channel(s, spec, n)` is the frozen signature
    (07:63-68), so with no field for the chosen seed the signature cannot carry it. The last rung of
    the ladder needs no field, because `tmp_narrow` is already in the `Narrowing`; the first three
    do. Defaulted to `()` like every other field here, and an empty `seeds` means "fall through to
    `tmp_narrow`", never "traverse nothing". D246.
    """

    terms: tuple[str, ...] = ()
    refs: tuple[tuple[str, str], ...] = ()
    idents: tuple[str, ...] = ()
    scope_doc: int | None = None
    q_sig: bytes | None = None
    q_full: bytes | None = None
    expand: Expand | None = None
    seeds: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """One row of `QueryPlan.channels`; THE ORDER IS THE RUN ORDER (07:3293).

    Transcribed from 07:3294-3300. There is no second, executed-order field and no runtime
    re-ordering (07:1704-1707), so a plan's channel tuple is the whole schedule.

    `weight` is `float | None` and "explicit (0.0 included) wins over `[retrieval.weights]`"
    (07:3298) -- the `None` is what distinguishes "unset, take the configured weight" from the real
    value `0.0`, and 07:1232 restates it: "0.0 IS A VALUE". A plain `float` defaulting to `0.0`
    would make a Channel deliberately weighted out indistinguishable from one nobody configured.

    `params` is `Mapping[str, Scalar]` -- flat scalars only, e.g. `{"expand_hops": 2}`. `Scalar` is
    `omniweave_core.config`'s (02-architecture.md:1303, 18-api-sketch.md:51), imported rather than
    redeclared: one name, one home (INV-21).

    `bind` is excluded from `plan_digest`, which is the whole reason it may be a field at all --
    07's Extends-the-charter row 3: `Reader.channel(s, spec, n)` is the charter's signature and
    `plan()` is pure and memoised on query shape, so with no field for query material "the
    signature cannot be implemented".
    """

    name: str
    budget_ms: int
    limit: int
    overfetch: int
    weight: float | None
    params: Mapping[str, Scalar]
    bind: ChannelInput | None = None


# ---------------------------------------------------------------------------
# VecManifest -- 07 section 16, read at attach
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VecManifest:
    """The `vec` sidecar's identity, read at attach (07:3339-3348). Eleven fields.

    **`corpus_id` is the field that makes the sidecar deletable.** 07:790 and 07:3190: a
    `vec_manifest.corpus_id` that differs from `main.index_state.corpus_id` means the sidecar is
    *"IGNORED, not read"* -- not an error, not a partial read, not a rebuild. The vectors are
    derived and the store is authoritative, so a sidecar that belongs to another corpus is
    indistinguishable from no sidecar at all, and absence gate 13 (`space_mismatch`) is what makes
    the difference visible to a caller.

    **`storage` is a `Literal` of two values because the two are different indexes**, not two
    settings of one. `sig_only` is the signature scan alone; `sig_full` additionally holds `dim*4`
    byte f32 vectors in `vfull` for an exact rerank of the top `RERANK_N`, and 07:2698 prices the
    choice -- at 1M blocks the whole `sig_only` sidecar is 3.7 MB.

    **`pushdown` is contract obligation (1)** (07:104-107): *"`candidates` narrows BEFORE ranking,
    tested at 0.01 selectivity. LEANN post-filters metadata after ANN retrieval with no over-fetch,
    which is silent recall loss that presents as absence."* A backend that declares `False` gets
    the over-fetch clamp and a `pushdown_unavailable` Degradation, and absence gate 11
    (`filter_starved`) reads this field by name (07:2191).

    Home: `omniweave_core.store`, beside the other boundary value types and with the `Reader` that
    reports two of its fields through `IndexCaps`. 18-api-sketch.md:840 lists it in a row whose
    home is `omniweave_core.retrieve.verdict`, in the same breath as `Coverage` -- which P2 homed
    here, for the same reason: the thing that reads it is a `Reader`, and `IndexCaps.vec_backend`
    and `IndexCaps.vec_pushdown` are copied straight out of it at open.
    """

    corpus_id: str
    schema: int
    model_key: str
    backend: str
    backend_version: str
    storage: Literal["sig_only", "sig_full"]
    sig_bits: int
    dim: int
    built_at_ns: int
    rows: int
    pushdown: bool


# ---------------------------------------------------------------------------
# Coverage -- 07 section 16
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """What `Reader.coverage()` returns; feeds absence gates 4-9 (07:3332).

    Eleven fields, transcribed from 07:3333-3337.

    **`scope_rows == 0` means coverage is UNKNOWN, not clean** (07:3335): no `ingest_scope` row is
    in view, which is gate 4 firing. That is the field that stops "we found nothing" being read as
    "there is nothing", and 18-api-sketch.md:466-469 repeats the warning verbatim on the public
    handle -- "that is gate 4 firing, not a clean bill of health".

    `gaps` is typed `tuple["DegradeCause", ...]`, and `DegradeCause` is 07 section 6.7's (07:1989),
    with the gate ladder it belongs to; 07:3348-3351 sends it there explicitly. It is therefore an
    UNRESOLVED forward reference in this module -- see the module docstring. P2's non-goals name no
    `Verdict` and no gate ladder (16-roadmap.md:468), so at P2 a backend returns `gaps=()` and the
    counts are the whole of what it can honestly report.

    `pending_work`, `stale_units` and `unreadable_units` read `work` and `unit`, which P2 creates
    and leaves EMPTY (16-roadmap.md:406, :468) and P4 fills. The read is a store read either way;
    what changes is whether it has anything to count.
    """

    discovered: int
    indexed: int
    partial: int
    failed: int
    skipped: int
    complete: bool
    scope_rows: int
    pending_work: int
    stale_units: int
    unreadable_units: int
    gaps: tuple[DegradeCause, ...]  # noqa: F821 -- 07 section 6.7's; see the module docstring.
