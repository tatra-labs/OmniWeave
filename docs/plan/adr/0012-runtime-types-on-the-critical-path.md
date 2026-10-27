# ADR-12 — `Outcome` is eight members in `08` §1.3, `RunContext` stays in `omniweave_core/operator.py`, the exit-code table gains no row, and a bake asset hangs off a synthetic job document

**Status:** Accepted · **Priority:** 4 of 12 · **Price:** 3 ed
**Discharges:** `08#D2`, `18#3` (defect); `09#Q9` (adjacent)
**Charter errata claimed:** `E90` (block `E90`-`E95`, five unused)
**Supersedes:** none
**Blocks / unblocks:** `Store.complete(row_id, gen, result: "StepResult") -> bool` is one of P2's four protocols ([16](../16-roadmap.md) §3 — P2 freezes at week 16) and cannot be typed while `StepResult` has no single home. The `09#Q9` half carries its own harder anchor — "**Must be made before `bake` ships, not with it**" — and is vacuous while `K-5` holds ([17](../17-risks.md):386). Unblocks [18](../18-api-sketch.md) §5's three signatures, and ADR-1's bulk lock pass, which needs the field sets before it can write `08#D1`'s sixteen rows.

## Context

**All three types are printed. The register rows were written against a plan that no longer exists.**
`18#3` ([17](../17-risks.md):728) reads, verbatim:

> `Outcome` and `StepResult` are named in six places and defined in none, and
> `Store.complete(row_id, gen, result: "StepResult") -> bool` depends on the shape — defect —
> `runtime` — [08](../08-runtime.md) writing both field sets. If the `Outcome` member set is larger
> than the seven implied, the exit-code table needs one more row, because exit 5 is the only code
> mapped from an `Outcome` rather than from an `OwError` — v0.1; ADR-12

[08](../08-runtime.md) §1.3 (lines 175-233) now prints `Outcome` as an eight-member `StrEnum`,
`StepMetrics` as seven fields, and `StepResult` as eleven with a `__post_init__` that raises on four
outcome-specific required-field sets; §1.4 (lines 246-336) prints `Roots`, `RunContext`,
`CancelReason`, `Cancellation` and `CancelToken`. The row's closer is discharged in text, and what
remains is a **decision about the consequence the row itself makes conditional**: the member set
landed at **eight**, not the seven the row assumed, so the exit-code clause fires.

**The charter names `Outcome` four times and defines it nowhere** — `charter.md`:2024 (a
`DriverResult` docstring), :2981 (RT10), :4329 (the decorator stack), :8473 — while §D6's
`work.status` `CHECK` fixes six *statuses* and no outcomes. [08](../08-runtime.md) §"Extends the
charter" item 3 (line 2619) nevertheless asserts "The charter fixes the six statuses, **the eight
outcomes** and `attempts_total < 5`". The first and third clauses hold; the second does not, and it
is the only sentence in the plan crediting the charter with a definition it never wrote.

**`08#D2` is a contradiction inside the charter, not between documents.** `charter.md`:3892 — "one
`asyncio` Supervisor living in the `omniweave` distribution — **never in `omniweave-core`**" —
against `charter.md`:3951-3953, whose `omniweave-core` package layout places `RunContext` in
`operator.py` beside `StepResult`. The same pair appears in the ruling at
[`D6-runtime.md`](../_notes/rulings/D6-runtime.md):950 and :117. [08](../08-runtime.md):2765-2774
already records the reading that makes both true — in a **New terms preamble**, an aside, where no
gate and no reviewer checklist will find it.

**`09#Q9`'s recommended option names a column that does not exist.** The row
([17](../17-risks.md):658) recommends "(a) a synthetic `doc` per compile job with
`origin = 'authored'`". `doc` has no `origin` column: `charter.md`:954-975 lists twenty and
[03](../03-document-model.md):404-411's `DocRecord` mirrors them exactly. Option (a) is unbuildable
as written, and adding a column to `doc` is a P2 DDL change inside the one strictly-ordered migration
sequence ninety-one tables share.

That is why this is an ADR and not a repair: two questions are answered by choosing between printed
statements, and the third's own recommendation cannot be built.

## Decision

### 1. `Outcome` has eight members and [08](../08-runtime.md) §1.3 is its sole home

`ok`, `ok_partial`, `skipped_cached`, `skipped_unchanged`, `failed_transient`, `failed_permanent`,
`deferred_budget`, `cancelled`. `StepMetrics` and `StepResult` are the dataclasses printed beside
them, verbatim, including `StepResult.__post_init__`. Every other document cites §1.3 and prints no
field list of its own; [glossary.md](../glossary.md):988-989 already points there. §"Extends the
charter" item 3's opening clause is corrected to *the six statuses and `attempts_total < 5`*, and
the item's subject becomes the mapping **and** the enum. The charter names `Outcome` and never
defines it, so **no erratum is owed for the definition** — there is nothing to supersede.

### 2. The exit-code table gains no row, and that is the answer to `18#3`'s condition

The member set is larger than seven, so the row's condition fires. The ruling is still **no new
code**, because the eighth member's dispositions are already allocated in full by
[08](../08-runtime.md) §1.4's four-cause table (lines 338-345):

| `CancelReason` | process exit today | why no code is owed |
|---|---|---|
| `interrupt` | `130` | the shell's `128 + signal`. [10](../10-interfaces.md) §6.2's fifth rule keeps it out of the table on purpose; claiming it would create a second register |
| `shed` | `0`, with `run.status = 'partial'` | a partial run is a result. Its `degradations[]` route it to exit 4 under `--fail-on degraded`, which is the existing mechanism |
| `deadline` | none — request scope, no `run` row | `retrieve()` discards the partial ranking and rolls back the snapshot; no process is exiting |
| `client` | none — the MCP handler returns no response | ditto |

[10](../10-interfaces.md) §6.2 stays at **twelve** codes and `codes.toml` stays byte-identical.
`Outcome.CANCELLED` is the one member with no exit code of its own, and that is correct rather than
missing.

**Erratum `E90`.** Charter `:6851`-`:6862` prints the exit table at eleven rows and has no exit 8;
[10](../10-interfaces.md) §6.2 prints twelve. The charter's block is retired law and
[10](../10-interfaces.md) §6.2 plus `codes.toml` are the sole home. It is written here because a
ruling that the table gains no row is meaningless against a table with two homes that already
disagree by one.

### 3. `RunContext` lives in `omniweave_core/operator.py`, and the reason becomes normative

Both charter sentences hold as written and neither is superseded, so **no erratum is claimed for
`08#D2`**. `RunContext` is a frozen value object with no loop, no store handle and no `async def`;
the Supervisor is `omniweave/run/supervisor.py` and is not `RunContext`. The resolution moves out of
[08](../08-runtime.md)'s New-terms preamble into §1.4 as normative text: `ServiceRegistry.handle()`
performs **blocking** attach-or-spawn and the async part is the Supervisor's `service_refill` task in
`omniweave/run/`, never the registry; `BudgetLedger` computes headroom in SQL on a synchronous
connection; neither field makes `omniweave-core` asyncio-dependent, which is why `RunContext` may be
defined there under G23.

**`G23` gains one clause**: no `async def`, no `await`, and no `asyncio` or `selectors` import
anywhere under `packages/omniweave-core/src/`, asserted by an AST walk rather than by
`-X importtime` alone — which catches a coroutine defined in a module that is never imported at
start-up and is therefore invisible to the import-time probe `V01-2` runs. This ADR **coins no new
`G` number**: the G-series cardinality is ADR-2's question ([17](../17-risks.md):675), and a clause
on an existing gate needs no allocation.

### 4. A compile-produced asset hangs off a synthetic **job document**, with no new column

Option (a), re-specified so it is implementable. One `doc` row per compile job, written by
`omniweave_core.out`'s job runner before `bake` produces its first byte, using columns that exist:

| column | value |
|---|---|
| `uri` | `ow-job://<corpus>/<artifact_slug>/<job_digest>` |
| `media_type` | `application/vnd.omniweave.job+json` |
| `format` | `owjob` |
| `format_evidence` | `{"synthetic":"compile-job","run_id":…,"artifact_slug":…,"unit_count":…}` |
| `doc_key` | `sha256(canonical job record)[:16]`, so an identical re-run is the same document |
| `source_sha256` | `sha256` of the same canonical bytes |
| `normalizer` | `"canonical/1"` — the bytes were canonical when produced, so normalising them is the identity. **Not** `NULL`, which means the normaliser threw and records `OW-C-041` ([08](../08-runtime.md):1306) |
| `status` | `'ok'`; `page_count` `NULL`; `next_cite_n` 1 |

**`format = 'owjob'` is the origin discriminator.** No `doc.origin` column is added: `WHERE format =
'owjob'` is the exhaustive selector and costs nothing, because `format` is already `NOT NULL`.
`asset.doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord)` is unchanged
([03](../03-document-model.md):1987-1996), and so is the `asset_identity` unique index. **A job
document carries zero `block` rows**, so it is invisible to every Channel by construction — a Channel
ranks Blocks — and cannot be cited. `artifact.read_back_doc_ord` ([09](../09-generation.md):2056)
later points at the `read_back` document, never at the job document; the job document is where a
bake's provenance (which unit, which construct, which DPI) lives, in `format_evidence` and `x`.

## Alternatives rejected

### Fold `CANCELLED` into `FAILED_TRANSIENT` and keep `Outcome` at seven

At its best this is the smaller type, it matches the register row's own assumption, and a cancelled
row *is* re-claimable exactly as a transient failure is. Rejected on the `attempts_total` arithmetic
[08](../08-runtime.md) §1.2 spells out: `CANCELLED` **decrements** `attempts_total` where
`FAILED_TRANSIENT` keeps it, because the claim predicate carries `attempts_total < 5` and five
Ctrl-Cs would otherwise leave a document permanently unclaimable without one attempt having run.
Folding the two also loses `work.status` (a cancelled row goes to `pending`) and `retry_after`
(`NULL`, not the ladder).

### Give `Outcome.CANCELLED` its own exit code (a new 10, or `130` promoted into the table)

Genuinely close, and worth arguing at full strength because a future reader will re-propose it: a
script that wants to distinguish "the operator stopped it" from "it finished" must read `run.status`
today, and *one scalar a shell can test* is [10](../10-interfaces.md) §6.3's own rule. Rejected
because the four causes exit **four different ways on purpose** — `130`, `0`, and twice no process
exit at all — so a single code would have to lie about three of them. Promoting `130` creates exactly
the second register [10](../10-interfaces.md) §6.2 refuses, and a new code 10 would be the first exit
value backed by neither an `OwError` nor a `Verdict`.

### Move `RunContext` into `omniweave/run/` so `omniweave-core` references no live subsystem

The strongest form of this is not about asyncio at all: `RunContext.services` is a `ServiceRegistry`
and `ServiceRegistry.handle()` **starts a process** ([08](../08-runtime.md):952-958). A type in the
distribution whose whole claim is zero third-party imports, no sockets and no processes, that
transitively reaches `subprocess`, is a real smell, and `V01-2` exists to catch that shape.
Rejected because the move breaks `OperatorABC.run(self, batch, ctx: RunContext) ->
Sequence[StepResult]` ([08](../08-runtime.md):1891): the Protocol is `T-CONTRACT` in
`omniweave_core/operator.py` ([11](../11-repo-layout.md):192), so an out-of-tree Operator would have
to import `omniweave` to type its own `run()` — inverting the dependency direction `charter.md`:185
exists to enforce. The field is a *reference*: core defines the shape, `omniweave` constructs the
value, and G23's new clause is the cheaper guard against the real hazard.

### `09#Q9` option (b) — nullable `doc_ord` plus `CHECK (doc_ord IS NOT NULL OR store_ref LIKE 'cas://%')`

At its best this is one DDL line instead of a synthetic-document mechanism plus a job runner, and it
invents no documents nobody asked for. Rejected on three counts, any one sufficient. **The `CHECK`
enforces nothing**: every `asset.store_ref` is `cas://…` already
([03](../03-document-model.md):1993, "NO INLINE BYTES, EVER"), so the predicate is vacuously true.
**The unique index breaks**: `asset_identity` is `(doc_ord, sha256, IFNULL(origin_part,''))` and
SQLite treats every `NULL` as distinct, so identical bake output produces unbounded duplicate rows.
**The licence story breaks**: `restriction_bits` and the six licence columns live on `asset`
*per document* precisely so the same bytes can be barred in one document and free in another
([09](../09-generation.md) §7.2), and a row owned by no document has no answer for the compile-time
restriction aggregate (OUT11, DR17, INV-16).

### Add `doc.origin` as a two-value column (`ingested` / `authored`)

Close, and it is what the register row's recommendation implies. Rejected because it is a P2 DDL
change to `doc` — the table `block`, `page`, `part`, `asset`, `block_cite` and `artifact` all key
against — inside the strictly-ordered migration sequence, in exchange for information `format`
already carries. It is also a second home for one fact, which charter §8 rejection criterion 19 makes
a rejection criterion and which ADR-9 exists because the plan committed it twice already.

## Consequences

| # | obligation | document | price |
|---|---|---|--:|
| 1 | §1.3's block is marked the sole home of `Outcome`/`StepMetrics`/`StepResult`, with the eight-member count stated in prose beside it | [08](../08-runtime.md) §1.3 | 0.2 ed |
| 2 | §"Extends the charter" item 3 loses "the eight outcomes" and gains the enum as its own subject | [08](../08-runtime.md):2619 | 0.1 ed |
| 3 | the `RunContext` resolution moves from the New-terms preamble (:2765-2774) into §1.4 as normative text | [08](../08-runtime.md) §1.4 | 0.3 ed |
| 4 | `G23` gains the AST clause; `tools/gates.toml`'s `G23` row and its script change together | [11](../11-repo-layout.md) §6.4 | 0.5 ed |
| 5 | §6.2 gains one sentence: `Outcome.CANCELLED` maps to no code, citing the four-cause table | [10](../10-interfaces.md) §6.2 | 0.2 ed |
| 6 | erratum `E90` is inserted into charter §9.2 — **by a later stage; no agent in this stage edits the charter** | [charter.md](../_notes/charter.md) §9.2 | 0.2 ed |
| 7 | Q9's two-option paragraph is replaced by the ruling, and §7.1's third consequence bullet gains the row shape | [09](../09-generation.md) §7.1, §Open questions Q9 | 0.8 ed |
| 8 | `owjob` is added to the format-token register; no `enum_val` domain changes, because `format` is free text | [03](../03-document-model.md) §6, [05](../05-ingest-and-routing.md) §2 | 0.3 ed |
| 9 | `corpus_card`'s document count and `ow store stats` exclude `format = 'owjob'`; one predicate, stated once | [07](../07-store-and-retrieval.md) | 0.4 ed |

**What becomes harder.** A job document is a real `doc` row, so `ow store gc`, `rebind()` and the
`doc_key` dedup path all see it. It has no blocks, so `rebind()` is a no-op over it; but
`asset.doc_ord` is `ON DELETE CASCADE` from `doc(doc_ord)`, which means deleting a job document
silently deletes its bake assets. Item 7 owes that sentence and the refusal that goes with it.

**What a future reader must not do.** Do not print a `StepResult` field list in any other document.
Do not add a member to `Outcome` without amending [08](../08-runtime.md) §1.2's transition table in
the same change — that table is the specification, and a cell changed without it is a rejectable PR.
Do not add exit code 10.

**Names this ADR coins**, handed to ADR-1's bulk lock pass rather than written into the lock here
(`02#1`'s closer is "one bulk lock pass **after** the documents land"): `owjob`, `canonical/1`, and
the job-document concept. `Outcome`, `StepMetrics`, `RunContext`, `Roots` and `CancelToken` are
already on `08#D1`'s sixteen-name list and need no second claim.

**Errata:** `E90` claimed. `E91`-`E95` unused, and never reallocated.

## Open

Nothing about the three types. Two adjacencies are recorded and deliberately not decided:

1. **The charter's exit table lacks exit 8** — [18](../18-api-sketch.md) §Open questions item 2, with
   no register row and no ADR. `E90` retires the charter's block wholesale and closes it as a side
   effect; a later stage preferring a narrower erratum changes nothing in §2.
2. **`K-5` may delete §4's question entirely.** `09#Q9` is vacuous while `bake` is `unavailable` on
   all three release-1 targets, and `K-5` ([17](../17-risks.md):386) demotes `bake` to `forbidden` if
   no SVG rasterizer clears G3 by DP5, week 40. If `K-5` fires, §4 costs one unused row shape — the
   price of meeting the anchor `09#Q9` sets: **before `bake` ships, not with it**.
