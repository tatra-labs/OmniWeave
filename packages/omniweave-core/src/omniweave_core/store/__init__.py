"""The store boundary: four Protocols, 33 methods, and nothing else crosses.

Implements 07-store-and-retrieval.md section 1.1 (:49-70), which is the primary source and prints
`Store` and `Reader` verbatim; 03-document-model.md section 2.10 (:547-565), which owns `DocSink`'s
eleven; and 06-structure-extraction.md section 1.7 (:355-373), which owns `GraphSink`'s twelve.
02-architecture.md:702 prices the same surface from the architecture side -- "the port is `Store`
(4 methods) + `Reader` (6) + `DocSink` (11) + `GraphSink` (12) -- **33 methods, not four**".

**4 + 6 + 11 + 12 = 33, and the arithmetic is a gate.** `test_store_protocols.py` counts the methods
off the Protocol classes themselves, not off a transcribed list, so a twelfth `DocSink` method fails
the build. 03:568-572 is why: "Eleven, and the count is fixed ... A twelfth re-prices 07 section
1.2's T3 Postgres swap and widens the only boundary a second backend has to reimplement, so adding
one is an ADR, not a patch." 16-roadmap.md:428 restates it for all four at P2's freeze: "The four
store protocols -- `Store` is never widened, and neither is any of the other three."

**Nothing here connects to anything.** There is no `import sqlite3` in this file or in `types.py`,
and the absence is deliberate rather than incidental: ruff's TID251 per-file-ignore covers
`store/*.py` (pyproject.toml), so this file is one of the five places in the repository where the
import is legal, and it declines it. 07:2721 fixes the reason -- "`sqlite3.connect` appears in
exactly one module (ST1)" -- and 07:72-78 makes it structural by typing `Snapshot.token` as an
opaque `object` so a Postgres `Reader` can construct a `Snapshot` at all. A boundary declaration
that imported a backend would forfeit that by example. `store/sqlite.py` is the only module that
connects, and it is another wave's.

**Not ABCs: Protocols.** 18-api-sketch.md:1779 states the house rule in exactly those words
("NOT an ABC: a Protocol"), and it matters twice over here. A `DocSink` implementation is host-side
and a `Reader` implementation may live in a distribution that does not import `omniweave_core` at
all, so structural typing is what makes a third-party backend possible without an inheritance edge
that `tools/layers.toml` would have to permit.

**`@runtime_checkable` is deliberately OFF on all four.** The decorator appears at exactly two sites
in the whole plan -- 04-driver-system.md:108 and 18-api-sketch.md:1780, both `DriverBase`, where
`activate()` really does `isinstance`-check a class it loaded from an entry point. No plan document
`isinstance`-checks a `Store`, a `Reader`, a `DocSink` or a `GraphSink`. Adding it would be worse
than useless: `isinstance` against a `runtime_checkable` Protocol checks only that the ATTRIBUTES
exist, never their signatures, so any object carrying four callables would pass as a `Store` -- and
the thing a backend must actually get right is the signatures. `omniweave-conform`'s job is to run
the contract, not to ask `isinstance`.

## The P2/P6 boundary line, method by method

P2's non-goals (16-roadmap.md:468) exclude "lexical scoring beyond the FTS5 table existing -- no
`W_HEAD`, no `SPINE_DECAY`, no sanitiser ... No `Verdict`, no `Answer`", while 16-roadmap.md:1034
schedules P6 to start "P2 week 9, after W2.3 and W2.8" and bounds it to "retrieval reads `Reader`,
`block_fts` and `block_sec`, and nothing else". Both hold at once: the `Reader` PROTOCOL is frozen
and complete at P2 (16-roadmap.md:428), and some of its IMPLEMENTATION is P6's. A Protocol has no
body, so all six are declared here and there is nothing to defer.

Six rows, one per `Reader` method. "P2" means the body is a pure store read; "P6" means it
depends on scoring or planning P2 explicitly does not build.

1. **`snapshot()` -- P2.** Pure store mechanism: `BEGIN DEFERRED` plus one
   `SELECT v FROM index_state WHERE k='generation'` issued inside it, 07:2777-2782. `index_state`
   carries exactly one `schema` stamp at the end of the shipped migrations by ST24 (07:3263), so
   the table it reads exists at P2. No score, no plan, no fusion.
2. **`capabilities()` -- P2.** Reads `schema`, `stat`, FTS presence and the `vec` attach state --
   every one a P2 table (07:3272-3280). `IndexCaps.channels` is "which of the five CAN run at all
   in this store", which is a store fact and not a plan. `IndexCaps.scorer_version` is the single
   field whose MEANING arrives with P6, since 16-roadmap.md:468 bans the scoring constants from
   P2; the store reports it regardless.
3. **`narrow()` -- P2.** The interesting row, argued in full below. The three-way tag is MEASURED
   by a `LIMIT PREFILTER_MAX + 1` probe, not chosen by a planner.
4. **`channel()` -- P6.** This is where scoring lives. P2's non-goals name its constituents one by
   one: "no `W_HEAD`, no `SPINE_DECAY`, no sanitiser" (16-roadmap.md:468). The structural and
   semantic Channels additionally need `segment` rows and L3, and at P2 "the tables exist and are
   empty" (16-roadmap.md:468). W2.8 builds `block_fts` as an FTS5 external-content table; nothing
   at P2 scores over it.
5. **`hydrate()` -- P2 for the row, P6 for four of `Hit`'s fields.** The read is a `SELECT` over
   `block` by id: `cite`, `addr`, `text`, `span`, `segment_id`, `trust`, `quote` and
   `restriction_bits` are columns or column-derived, and `byte_exact` is 07 section 8.2's single
   predicate evaluated at one call site. But `Hit.score` is "the fused RRF score" and
   `channel_contributions`, `channel_ranks` and `identity_grade` are fusion outputs (07:2250-2265),
   so the shape cannot be filled without a fused ranking. 07:3348 homes `Hit` itself with the query
   path for that reason.
6. **`coverage()` -- P2 for the counts, P6 for `gaps`.** `discovered`, `indexed`, `partial`,
   `failed`, `skipped` and `scope_rows` are counts over `ingest_scope` and `doc`. `pending_work`,
   `stale_units` and `unreadable_units` read `work` and `unit`, which P2 creates and leaves empty
   and P4 fills -- a store read either way, with nothing to count yet. `Coverage.gaps` is
   `tuple[DegradeCause, ...]`, and `DegradeCause` is 07 section 6.7's, with the gate ladder
   (07:1989, and 07:3348-3351 sends it there) that 16-roadmap.md:468 excludes from P2. At P2 a
   backend returns `gaps=()`.

**`narrow()` is a store mechanism, not a planner decision, and four things settle it.** 07 section
6.1 is titled "Decision 1 -- narrowing, a closed three-way choice" and sits under section 6, "the
planner", which is the reading that would make it P6's. It does not survive the section's own body.

1. **Its signature takes a `Snapshot`, and `plan()` runs before `snapshot()`** (07:2795: "`plan()`
   runs before `snapshot()`; the Answer is rendered after it closes"). A method that needs the read
   view cannot be part of a pure, memoised plan; `narrow` is on `Reader` and not on `plan()` for
   that reason.
2. **The plan explicitly puts the work inside `retrieve()`, not `plan()`** (07:1657-1660): the
   `Method` enum codes "are resolved on the read connection when the narrowing statement is
   prepared -- inside `retrieve()`, never inside `plan()`, whose memo key carries the filter FIELD
   set and no filter values."
3. **The three-way tag is observed, not chosen.** `kind` is `set` when the `LIMIT PREFILTER_MAX + 1`
   probe returns at most `PREFILTER_MAX` rows, `empty` when it returns none, and `all` when it hits
   the cap -- so the tag is a function of the data. 07:1592-1597 forecloses the alternative reading
   in as many words: "**No histogram, no independence assumption, no cost-based optimiser.**"
   07:1555 says the same of the section as a whole: "There is **no cost-based optimiser and no
   join-order search**."
4. **The one genuinely P6 quantity is not in the return type.** Above `PREFILTER_MAX`, narrowing
   "becomes an over-fetch factor `clamp(1/selectivity, 1, 64)`" (07:1682-1684) -- and `Narrowing`
   has no field for it, because the factor is consumed by the Channels. What the planner decides is
   the `Filters` VALUE, upstream of this call and P6's; what `narrow()` does with it is SQL over
   `block` and `doc` with a `LIMIT`.

## The types, and where each one lives

Every type these 33 signatures name, with its definition site and its owner. "Here" means
`omniweave_core.store.types`, re-exported below.

* `Snapshot` -- 07:2766-2769. Here.
* `Filters`, `Narrowing` -- 07:1563-1582. Here.
* `IndexCaps`, `ChannelInput`, `ChannelSpec`, `Coverage` -- 07:3271-3337. Here.
* `Expand` -- 07:1342-1351. Here, because `ChannelInput.expand` names it.
* `BlockId`, `BlockDraft`, `Mark`, `Cite`, `Trust`, `RelKind` -- 03 sections 2.2, 2.5, 2.6.
  `omniweave_core.model`, and imported below: they exist.
* `DocRecord`, `PageRecord`, `AssetDraft` -- 03:404, :415, :426. `omniweave_core.model`, still owed
  by W2.1 (see that package's docstring, "Still owed by P2").
* `Grid`, `Diag` -- 03:1880, :1800. `omniweave_core.model`, still owed by W2.1. The plan prints
  both UNQUOTED in `DocSink` (03:557, :563), so both become real imports the moment they land.
* `WorkRow` -- NEVER PRINTED anywhere in the plan; see the defect note on `Store`.
  02-architecture.md:246 homes it in `omniweave_core.work` and 08-runtime.md:2841 gives its one
  load-bearing field.
* `StepResult` -- 08-runtime.md:209-231. The runtime's, P4.
* `ChannelResult`, `Hit` -- 07:1225-1235, :2250-2265. The retrieval module's, P6; 07:3348 says so.
* `SegmentRef`, `PassIdentity`, `RunStatus`, `RunReport`, `RunId`, `EntityId`, `MentionId`,
  `EdgeId`, `ClaimId` and the seven Drafts -- 06:337-384. `omniweave_core/store/graph.py`, which
  06:381-384 names as their home. NOT this file, and not this wave.
* `Spend` -- 05-ingest-and-routing.md:2370. P4's.
* `DegradeCause` -- 07:1989. P6's (07:3348-3351).

**`# ruff: noqa: F821` below, and why it is a directive and not twenty-six comments.** Twenty-six of
those names have no module yet, and the plan quotes most of them at their use sites for the same
reason. A Protocol method has no body, so a signature naming an unhomed type costs nothing at import
time -- what it costs is `typing.get_type_hints()`, which raises `NameError` here rather than
lying. Every statement in this file is a `class`, an `import`, or a `...`, so F821 can only ever
fire on an annotation; and `test_store_protocols.py` pins the EXACT set of unresolved names, so a
typo shows up as a new member of that set and a name that later gets a home shows up as a stale one.
That test is the gate the suppression would otherwise remove.

Stdlib only (INV-2 / G1). One of the nine LAZY names (11-repo-layout.md section 1.3): G17 asserts a
bare `import omniweave_core` does not reach this package, which holds because
`omniweave_core/__init__.py` imports none of the nine and exposes them through `__getattr__`.
Importing `omniweave_core.store` is what a caller does ON PURPOSE.

Tier T-SCHEMA: 02-architecture.md section 2 row 26.
"""
# ruff: noqa: F821 -- the unhomed types are enumerated in the docstring and pinned by
# test_store_protocols.py::test_the_unresolved_forward_references_are_exactly_the_expected_set.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, BinaryIO, Protocol

from omniweave_core.model.block import BlockDraft, BlockId, Cite, Mark
from omniweave_core.model.enums import RelKind, Trust
from omniweave_core.store.types import (
    ChannelInput,
    ChannelSpec,
    Coverage,
    Expand,
    Filters,
    IndexCaps,
    Narrowing,
    Snapshot,
)

# `AbstractContextManager`, not `typing.ContextManager`. 07:63 prints
# `def snapshot(self) -> ContextManager["Snapshot"]`, and `typing.ContextManager` has been a
# deprecated alias since 3.9 -- ruff UP035 rejects the import outright. The two spell the same
# protocol, so this is a spelling change and not a semantic one; recorded because a reader
# comparing this file to 07:63 word for word will notice.

__all__ = [
    "ChannelInput",
    "ChannelSpec",
    "Coverage",
    "DocSink",
    "Expand",
    "Filters",
    "GraphSink",
    "IndexCaps",
    "Narrowing",
    "Reader",
    "Snapshot",
    "Store",
]


class Store(Protocol):
    """The QUEUE boundary. Four methods. Never widened.

    Transcribed from 07:56-60, which is also charter.md:3393-3397 word for word. 08-runtime.md
    section 9.2 calls it "THE ONLY THING THAT CHANGES BETWEEN T1, T2 AND T3" and prints a WIDER
    variant of two of the four; the divergence and the ruling are in the defect note at the bottom
    of this class's docstring.

    `complete()` is the only mutation entry point on the queue, and one call is one transaction:
    "one unit's derived rows, its `work` transition, its `dep` rows, its reservation commit and its
    spend row commit **together or not at all**" (07:2731-2733).

    **The `bool` return means exactly one thing.** `False` is SUPERSEDED and nothing else; every
    other refusal raises, "because a boolean that means both 'someone else won' and 'your driver is
    wrong' turns a bug into a no-op" (08:2489-2494). `gen` is what the commit predicate compares
    against the row's `claimed_gen`, which is what makes a superseded result write nothing
    (08:2841).

    **DEFECT -- `Store` is printed twice, and the two prints disagree.** Two definition sites carry
    the four-method form transcribed here (07:56-60 and charter.md:3393-3397); one carries a wider
    form (08-runtime.md:2478-2485):

        def claim(self, cost_class: CostClass, batch: int, gen: int,
                  worker: str, lease_ms: int) -> Sequence["WorkRow"]: ...
        def complete(self, row_id: int, gen: int, result: StepResult,
                     *, deps: Sequence["Dep"], rows: "DerivedRows") -> bool: ...

    Two definition sites against one, and the charter is law, so the four-parameter `claim` and the
    three-parameter `complete` are what ship. Two further facts point the same way: 07 section 1.1
    is the section the roadmap sends W2.3 to, and 08's extra parameters are typed `CostClass`, `Dep`
    and `DerivedRows`, which are P4's runtime types and do not exist at P2's freeze. The method
    COUNT is four either way, so 02:702's arithmetic is unaffected. Widening either signature to
    08's is an ADR, not a patch (16-roadmap.md:428); reported.
    """

    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]: ...

    def complete(self, row_id: int, gen: int, result: StepResult) -> bool: ...

    def reap_expired_leases(self, now_ms: int) -> int: ...

    def counts_by_status(self) -> Mapping[str, int]: ...


class Reader(Protocol):
    """The RETRIEVAL boundary. A Postgres T3 implements this.

    Transcribed from 07:63-68, which is also charter.md:3399-3404 word for word -- one definition
    site per document and no disagreement between them. The P2/P6 ruling for each of the six bodies
    is the table in this module's docstring.

    **One `Snapshot` threads through five of the six**, and that is ST2: "One `BEGIN DEFERRED` for
    the whole query -- every Channel, hydration and the coverage scan. Without it, a 6-12 statement
    retrieval sees up to twelve snapshots and fusion mixes generations" (07:2758-2762). The test the
    plan names is explicit: a full re-index is committed between Channel 1 and Channel 5 and the
    results must be identical. `capabilities()` is the one method that takes no `Snapshot`, because
    it is "read once, at open" (07:3272) and memoises `plan()` through `IndexCaps.caps_digest`.

    **The snapshot must not be held open indefinitely** (07:2789-2793). A held read transaction pins
    the WAL, `MAX_SNAPSHOT_MS = 5_000` is the ceiling in `limits.py`, and exceeding it aborts with
    `OW-S-010` and `verdict = degraded`. That deadline "is a WAL-valve safety parameter, not a UX
    parameter", which is also why the query embedding runs in phase 2, outside the snapshot (ST22)
    -- and why `ChannelInput` carries `q_sig` rather than a `Reader` method computing it.
    """

    def snapshot(self) -> AbstractContextManager[Snapshot]: ...

    def capabilities(self) -> IndexCaps: ...

    def narrow(self, s: Snapshot, f: Filters) -> Narrowing: ...

    def channel(self, s: Snapshot, spec: ChannelSpec, n: Narrowing) -> ChannelResult: ...

    def hydrate(self, s: Snapshot, ids: Sequence[int]) -> Sequence[Hit]: ...

    def coverage(self, s: Snapshot, f: Filters) -> Coverage: ...


class DocSink(Protocol):
    """HOST-SIDE. Never handed to a driver, never reachable from `DriverIO` (charter section 5 X1).

    A `parse/1` driver emits `owdoc-fragment/1` addressing blocks by a per-invocation `tmp` id; the
    host decodes it and drives this. That is what makes INV-6 and INV-7 structural rather than
    reviewed, and what makes a fragment portable between stores. -- 03:548-551, quoted because the
    plan writes this class's own docstring.

    The eleven methods are transcribed from 03:553-565, in the printed order. 03:574-597 is the
    table of what each one mints, stamps or enforces, and it is not restated here: one concept, one
    home. Four properties of the SHAPE, though, are properties of these signatures and belong with
    them:

    * **Eleven is fixed.** 03:568-572: "`BlockDraft.cell` exists precisely so a cell's grid position
      can reach `add_block` without a twelfth method. A twelfth re-prices 07 section 1.2's T3
      Postgres swap ... so adding one is an ADR, not a patch."
    * **The method is spelled `diag`, not `add_diag`** -- "the charter's spelling and section 1.1's,
      kept because one concept gets one name in every document" (03:571-572).
    * **`add_asset` takes a `BinaryIO` and never bytes**, and hashes the stream itself, raising
      `OW_ASSET_DIGEST_MISMATCH` on disagreement with `AssetDraft.sha256` (03:589, charter.md:1481).
    * **`add_part`'s `blob` is nullable, and that nullability IS the retention policy in the
      signature** (03:614-619). `[store] retain_parts` decides whether the bytes reach CAS;
      `blob=None` records `path`, `sha256` and `byte_len` with `store_ref` NULL. The digest and the
      length are required either way, so INV-10's `glyphs` branch and `VERBATIM`'s re-verification
      can name WHICH part they could not read. `add_part` is also "the sole inserter of an L2 `part`
      row" (03:601): `op.identify` writes `unit.part_count` and the per-part `work` rows and never a
      `part` row -- erratum E53.

    `end_page()` COMMITS ONE TRANSACTION (03:594), so "rows are durable and invisible while
    `g_t > doc.gen`", and a `diag` about page 3,000 survives a crash at page 3,001 because
    `diag()` writes inside the current page's transaction (03:593).

    **DEFECT -- `begin_doc`'s return type and `add_rel`'s arity differ between the charter and 03.**
    charter.md:1474 prints `def begin_doc(self, rec: "DocRecord") -> None` and charter.md:1479-1480
    gives `add_rel` no `score_kind`. 03:553 returns `"DocRecord"` and 03:558-559 adds
    `score_kind: str | None = None`. 03 section 2.10 is where 07:542-543 delegates these eleven
    ("every type they take is defined above and every rule they enforce is a rule of this
    document"), 03:584 requires `score_kind` to be "resolved against the `score_kind` register" at
    write, and `end_doc` returns a `DocRecord` in both prints -- so a `begin_doc` that returns one
    is the consistent shape. 03 is followed; reported.
    """

    def begin_doc(self, rec: DocRecord) -> DocRecord: ...

    def begin_page(self, page: PageRecord) -> None: ...

    def add_block(self, b: BlockDraft) -> BlockId: ...

    def add_marks(self, b: BlockId, marks: Sequence[Mark]) -> None: ...

    def add_grid(self, b: BlockId, g: Grid) -> None: ...

    def add_rel(
        self,
        src: BlockId,
        dst: BlockId,
        kind: RelKind,
        *,
        trust: Trust,
        score: float | None = None,
        score_kind: str | None = None,
    ) -> None: ...

    def add_asset(self, a: AssetDraft, blob: BinaryIO) -> int: ...

    def add_part(self, path: str, blob: BinaryIO | None, sha256: bytes, byte_len: int) -> None: ...

    def diag(self, d: Diag) -> None: ...

    def end_page(self, stats: Mapping[str, Any]) -> None: ...

    def end_doc(self, status: str) -> DocRecord: ...


class GraphSink(Protocol):
    """The L3 write boundary. Twelve methods, HOST-SIDE like `DocSink`.

    Transcribed from 06-structure-extraction.md:355-373, in the printed order. The sink "is the ONLY
    place trust is written, the ONLY place ids are minted, and the ONLY place `restriction_bits` /
    `origin_driver` / `producer_id` are stamped" (charter.md:5444-5445). A DRAFT PROPOSES; THE
    RUNNER DECIDES (06:378).

    Four properties the signatures carry rather than assert (06:386-392):

    * **`allowed_cites` IS the injection and cache-poisoning control** (GR9), lifted from graphify's
      `cache.put(entries, allowed_units=...)`. A draft naming a cite outside the set is quarantined
      `OW_GRAPH_OUT_OF_SCOPE_BLOCK` and KEPT. "Enforced by the SIGNATURE, not by a later audit"
      (06:358-361).
    * **There is no `drop()`**, so "the rejected draft is kept VERBATIM in `payload`" is a
      type-level fact rather than a convention, and `quarantine()` is the ONLY disposal path.
    * **Every id-returning method mints its id INSIDE the sink**, so no Draft can name one (GR11).
      That is why `entity`, `mention`, `edge` and `claim` return an id and `alias`, `anchor` and
      `xref` return `None`: the last three name their subject by a `TmpRef` the sink resolves.
    * **`cover` is a method on the open run** rather than a separate write, so a cover row commits
      or vanishes with the items it describes (GR3: coverage, or a REASON).

    `end_run()` COMMITS ONE TRANSACTION and returns the `RunReport` that `ow graph plan` and
    `ow graph residue` read (06:373-384).

    **Every Draft, every id and `RunStatus` live in `omniweave_core/store/graph.py`, not here.**
    06:381-384 is explicit: "the seven Drafts live in `omniweave_core/store/graph.py` beside
    `GraphSink`, are frozen and slotted, and are host-side reconstructions of `owgraph-items/1`
    frames -- a driver never imports them, exactly as a `parse/1` driver never imports
    `BlockDraft`." That file is not this wave's, so the twelve signatures below name those types as
    forward references; see this module's docstring.

    **DEFECT -- `end_run`'s status type differs between the charter and 06.** charter.md:5440 prints
    `def end_run(self, status: str, spend: Spend)`; 06:373 prints `status: RunStatus`. 06:391-393
    states the reason and claims the override in as many words -- "`RunStatus` narrows the charter's
    `status: str` to the same five-value domain as the `derive_run` `CHECK`, so a runner cannot
    report a state the store cannot hold". A declared narrowing with a stated reason is a completion
    rather than a contradiction. 06 is followed; recorded for the lock.
    """

    def begin_run(
        self, seg: SegmentRef, p: PassIdentity, allowed_cites: frozenset[Cite]
    ) -> RunId: ...

    def entity(self, d: EntityDraft) -> EntityId: ...

    def alias(self, d: AliasDraft) -> None: ...

    def mention(self, d: MentionDraft) -> MentionId: ...

    def edge(self, d: EdgeDraft) -> EdgeId: ...

    def claim(self, d: ClaimDraft) -> ClaimId: ...

    def anchor(self, d: AnchorDraft) -> None: ...

    def xref(self, d: XrefDraft) -> None: ...

    def cover(
        self, lane: str, cites: Sequence[Cite], *, empty_reason: str | None = None
    ) -> None: ...

    def quarantine(
        self, row_kind: str, code: str, payload: Mapping[str, Any], **d: Any
    ) -> None: ...

    def diag(self, d: Diag) -> None: ...

    def end_run(self, status: RunStatus, spend: Spend) -> RunReport: ...
