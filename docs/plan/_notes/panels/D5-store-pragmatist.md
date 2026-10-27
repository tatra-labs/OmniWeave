# D5-store — Storage, indexing, retrieval and query planning (SHIPPING PRAGMATIST)

## Headline

**One SQLite file per corpus is the implementation and the SQL is the interface; the four retrieval
channels are ordinary tables and ordinary queries fused by a 120-line weighted-RRF function with a
computed ceiling; the query planner is a pure compiler that runs the free channels first and pays for
a vector only when the free channels fail a stated confidence gate; and the index is a cache — never a
committed artifact — that scales from a laptop to a cluster by sharding whole documents on `doc_key`
and federating by corpus, with the honesty layer (a four-state verdict behind ten gates over D2's
`diag` table) as the thing that makes any of it citable.**

Ship order: week 4 a user runs `ow index . && ow query "…"` on a laptop and gets cited blocks with a
verdict. Week 14 the same command runs against 500M blocks. Nothing in phase 1 is thrown away.

---

## 1. What is already settled, and the one clause I contest

I am bound by, and use verbatim:

- **D1**: `omniweave_core.store` is *the only* module permitted to call `sqlite3.connect` (lint rule);
  codegraph's pragma ordering (`busy_timeout` **before** `journal_mode`, #238); heal-on-open for an
  oversized WAL; the proportional WAL valve with its futility latch; jcodemunch's `connect_readonly`
  ladder; FTS5 absence and `sqlite_version < 3.35` as **named capability probes** with the
  `omniweave[sqlite]` remedy; a claim protocol that works without `UPDATE … RETURNING`; SQLite the
  only shipped backend, Postgres as T3 behind the four-method `Store` protocol; error codes
  `OW-S-nnn` in the append-only `codes.toml`; the 250 MB aggregate weight gate; `omniweave query,
  warm store ≤ 250 ms` as gate G10.
- **D2**: the `.owstore` **is** the model — "L4 adds indexes and edge tables ON THESE TABLES; it never
  adds a second representation of a block." `block_id` is the only FK target. `addr`/`cite`/`doc_key`,
  `content_digest`/`layout_digest`, `gen`, `state`, `trust`, `quote`, `origin_operator`, `diag.code`,
  `part.store_ref = cas://…`, `page_render` as an evictable cache, `rebind`/`RebindReport`. "D5
  inherits `block_id` as the join key and `diag.code` as the input to the absence contract."
- **D3**: `block.origin_driver`, `block.driver_schema_v`, `block.restriction_bits` + the partial index;
  `driver_card_cache`, `driver_observation`, `resolution_report`; `embed/1` is a **Port**, so an
  embedder is a Driver, not a store feature; the `subproc` host's long-lived worker per
  `(driver_id, config_digest)` over a **0600 UDS**; "`store` becomes D5's Backend".
- **D4**: `route_decision`/`route_unit_decision`/`route_evidence`/`route_signal`/`route_spend`/
  `route_verdict`/`route_pin` + `route_scoreboard`; `work.decision_id NOT NULL`; the seven-unit
  physical `Spend` vector and the operator-owned `PriceBook`; "D5 … must not invent a second decision
  log."
- **mine-runtime §7 (D6's material)**: the `work` table, `origin_operator` ownership (I4), the
  per-unit attribution guard, the racily-clean stat rule, the three-group cache key.

### The one flagged conflict (narrow, and I state the minimum amendment)

**D2 §Concrete shape, `.owstore` DDL:**

> ```sql
> CREATE VIRTUAL TABLE block_fts USING fts5(
>   text, content='block', content_rowid='block_id',
>   tokenize='unicode61 remove_diacritics 2');
> -- + the three standard AFTER INSERT/DELETE/UPDATE sync triggers. D5 owns the BM25 weights.
> ```

**The clause "D5 owns the BM25 weights" is unsatisfiable against a one-column FTS5 table.** SQLite's
`bm25()` takes one weight per column; with a single `text` column there is exactly one weight and it
is a no-op scalar. codegraph's entire lexical result — `bm25(nodes_fts, 0, 20, 5, 1, 2)`, a 20× name
weight over docstring, verified at `codegraph/src/db/queries.ts:1508` — is a *column-weight* result and
is unreproducible here. Every document corpus needs it: a heading that matches the query is stronger
evidence than the same words buried in a 900-word paragraph, and `block.title` already exists as a
column of `block` (D2's `block` DDL, `title TEXT`).

**Minimum amendment (two tokens of DDL, no new table, no new column on `block`):**

```sql
CREATE VIRTUAL TABLE block_fts USING fts5(
  title, text,                                  -- both are EXISTING columns of `block`
  content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');    -- tokenizer UNCHANGED
```

External-content FTS5 requires its column names to be columns of the content table; `title` and `text`
both are, so this costs nothing but the triggers naming two columns instead of one. Nothing else in D2
moves. If the judge refuses the amendment, the fallback is jcodemunch's `_FIELD_REPS` trick — repeat
the title tokens 3× inside the single `text` column at index time — which works, costs ~2% index size,
and makes `block_fts.text` no longer equal to `block.text`, which is strictly worse for a model whose
whole point is that there is one representation of a block. Take the two tokens.

Everything else below is additive to D2's schema and contradicts nothing.

---

## 2. Design

### 2.1 The container: one file, two sibling directories, one telemetry sidecar

```
<cache_root>/                                   # D1's three roots; cache_root ∉ source_root
├── index.owstore                 SQLite. D2's tables + D5's indexes + D7's graph + D3/D4/D6 ops.
├── index.owstore-wal / -shm      transient
├── cas/ab/cd/<sha256>            content-addressed blobs: retained parts, assets, page renders
├── vec/<space_id>/               ONE vector space per dir: vectors.f16 + index.usearch + meta.json
├── index.lock.json               GENERATED, byte-stable, COMMITTABLE. Not the index — its receipt.
└── telemetry.db                  SQLite. query_event + retrieval tuning. SEPARATE FILE, see §2.6.
```

**Why the vectors are not in the SQLite file.** A 768-dim float16 vector is 1,536 B. At 10M blocks that
is 15 GB of BLOBs churning the same B-tree the lexical channel and the writer are using, and every
`VACUUM`, backup and WAL frame carries it. Outside the file they are an mmap-able flat array indexed by
a dense `vec_ord`, deletable without touching the store, and rebuildable from `content_digest` alone.
The store keeps only the join row. This is the same reasoning D2 already applied to assets
(`store_ref = cas://…`, "NO INLINE BYTES, EVER").

**Why telemetry is not in the SQLite file.** The serve process opens the store `mode=ro` and must never
take the write lock (§2.7). A query ledger is a write on every query. Putting it in `index.owstore`
would make every MCP call contend with the indexer for the writer lock, which is the exact contention
this design is built to avoid. `telemetry.db` is per-user, derived, deletable, and its loss costs
nothing but tuning data.

### 2.2 SQLite is the implementation; the SQL is the interface

I reject a storage-abstraction layer. There is one shipped backend and one dialect, and the *portable*
thing is not a Python `Backend` protocol with one implementation — it is **DDL and queries written in
the SQLite ∩ Postgres intersection**, with exactly four named divergences behind a 60-line `Dialect`
shim. D4 already committed to this ("identical DDL on Postgres for T3"). The four:

| # | Divergence | SQLite | Postgres (T3) |
|---|---|---|---|
| 1 | claim | `UPDATE … WHERE id IN (SELECT … LIMIT n) RETURNING *`, with D1's mandated `BEGIN IMMEDIATE`+`UPDATE`+`SELECT` fallback for `sqlite_version < 3.35` | `SELECT … FOR UPDATE SKIP LOCKED` |
| 2 | lexical | `block_fts` (FTS5) | `tsvector` GIN column + `ts_rank_cd` |
| 3 | upsert | `INSERT … ON CONFLICT DO UPDATE` | identical |
| 4 | nullable natural keys | `IFNULL(x,-1)` inside the UNIQUE index | `COALESCE(x,-1)` inside the UNIQUE index |

Everything else — every table, every index, every filter, every traversal — is one string. The
`Dialect` shim is four methods and is allowed to exist precisely because it has two implementations on
the roadmap, not one. That is the whole "is SQLite the interface or the implementation" question
answered: **the implementation, with a dialect-portable SQL surface, and no ORM.**

The Python surface is two Protocols, both small. D1 fixed the writer side at four methods; I add a
reader.

### 2.3 The four channels, and how they coexist

They coexist because **all four are the same shape** — an ordered list of `block_id` plus a raw score —
and because **filters narrow while channels score within the narrowed set** (codegraph's composition
rule, `src/search/query-parser.ts`, stated in one sentence and worth more than the parser). No channel
ever sees a global corpus; every channel sees `tmp_narrow` or `NULL`.

| Channel | Cost | Mechanism | Store objects |
|---|---|---|---|
| **lexical** | FREE | FTS5 `MATCH` + `bm25(block_fts, 8.0, 1.0)` over the narrowed set, over-fetched 5× | `block_fts` (+ optional `block_tri`) |
| **identity** | FREE | a graded ladder over `cite`, `addr`, `doc_key`, `block.title`, and a materialized `term_vocab` of proposals re-verified at read time | `block_cite`, `block_addr`, `term_vocab` |
| **structural** | FREE | bounded BFS from the free channels' seeds over containment (`parent_id`), D2's seven `rel` kinds, and D7's `kedge` | `block_parent`, `rel_dst`, `kedge_*` |
| **semantic** | LOCAL_COMPUTE / BILLED_API | one `embed/1` call for the query + ANN over `vec/<space_id>/` | `vector_space`, `block_vec` |

**Identity for documents is not identity for code, and the ladder is re-graded accordingly.** codegraph
and jcodemunch weight identity highest because a symbol name is a coined token. A document heading is
prose; `"Revenue"` as a heading is not the same class of evidence as `getUserById` as a function name.
So my ladder tops out at exact `cite`/`addr`/`doc_key` (a token the model was *given*), and title
matches sit below the lexical channel's ceiling contribution. jcodemunch's 40-vs-50 lesson is kept in
full: a match that needed *more* than case folding grades lower, and the reported grade is the one
actually measured (`retrieval/scoring.py:192-252`; the 0.355-out-of-58 fixture-outranks-the-class bug).

The ladder, stated:

```
exact cite / addr / doc_key                        50   the model was HANDED this token
exact doc-scoped title, case-folded only           42
tokenized title match (needed more than case)      34   ← the tier that must not be collapsed
title prefix                                       26
term_vocab segment hit, re-verified against block  18
figure / table / section label exact               44   ("Fig. 3a", "Table 2", "§12.4(b)")
no match                                            0
```

**Two lexical channels, not one, when the tokenizer is the constraint.** `unicode61` is right for prose
and wrong for CJK, for `§12.4(b)`, for hyphenated line-break artifacts, and for a query typed as
`ISO27001` against text reading `ISO 27001`. codegraph reached this with a `LIKE` ladder beside FTS5
("when the tokenizer is the constraint, add a channel; do not fight the tokenizer"); LEANN reached FTS5
from the other side. My version is a second external-content FTS5 table with `tokenize='trigram'`
(SQLite ≥ 3.34; D1's floor is already 3.35). It costs ~2.6× the primary index size, so it is **on by
default below 5M blocks and opt-in above**, and it is a *channel*, fused, never a fallback — because a
fallback makes the two answers incomparable and a fusion makes them additive.

**Query sanitization is a semantic transform, not escaping** (codegraph `queries.ts:1476-1495`). The
document rewrites: `§`/`¶` → whitespace; `Fig. 3a` / `Table 2` / `§12.4(b)` lifted out as *identity*
probes before the residue reaches FTS; soft-hyphen `U+00AD` and `-\n` stripped; FTS5 specials and bare
`AND|OR|NOT|NEAR` removed so a user cannot inject FTS syntax; **unknown `foo:bar` prefixes pass through
as plain text**, so someone searching `TODO:` gets results instead of a parse error.

### 2.4 Fusion: `fuse()` and `ceiling()` shipped as a pair, one weight function

Weighted RRF, `k = 60`, weights **not** normalized to sum to 1, resolved for both functions through one
`_weight()`, pinned by a perfect-consensus test. This is jcodemunch's design (`signal_fusion.py`),
reimplemented from `mine-graph.md §4.3` — **not vendored**, because its Dual-Use Licence v1.1 bars use
"within a for-profit organization to support revenue-generating activities" and bars publishing any
derivative to a package registry.

Starting weights, and they are a *policy* with a stated justification, not a constant:

```
identity 1.6 · lexical 1.4 · lexical_tri 0.7 · semantic 0.9 · structural 0.5     k = 60
ceiling(all five ran)      = 5.1 / 61 = 0.0836
ceiling(lexical+identity)  = 3.0 / 61 = 0.0492
```

Lower identity and higher lexical than jcodemunch's code-tuned `{identity 2.0, lexical 1.0,
similarity 0.8, structural 0.4}`, for the reason above. The ceiling depends on **which channels
actually ran**, so a two-channel perfect result reports `normalized = 1.0`, not "0.049, low
confidence". Never hardcode `1/(k+1)`.

Four properties, each with a failure behind it:

1. `FusedHit` carries `channel_contributions` and `channel_ranks`. A fusion function returning only a
   score is one you cannot tune, and it is what feeds `query_event` and the offline tuner.
2. Every channel is totally ordered on `(-score, block_id)`. Ties broken by storage order make the
   whole ranking nondeterministic across a `VACUUM` or an FTS5 `'optimize'`.
3. `ChannelResult.status ∈ {ran, empty, off, unavailable}`. `ran`/`empty` contribute their weight to
   the ceiling; `off` does not; `unavailable` does not **and forces `degraded`**. LEANN's linear blend
   of raw `bm25()` tens against a cosine (`api.py:1453-1468`) is the anti-pattern: whichever channel
   has the larger numeric range wins, and a single-channel hit scores like a consensus hit.
4. `Narrowing` is a **tagged** type, never a falsy check. jcodemunch's v1.108.185 bug — an empty
   candidate set read as falsy, letting every symbol with nonzero PageRank into the structural channel,
   so a nonsense query returned the whole repository "confidently" and the absence contract became
   unreachable — is reproduced as a regression fixture in our own test suite.

### 2.5 The query planner: a pure compiler with a demand plan, not a cost optimizer

`compile_plan(Query, StoreCaps, Policy) -> Plan` is pure: no clock, no network, no store read. It
returns an ordered list of stages grouped by `cost_class`, a narrowing spec, a fusion spec and a
`plan_digest`. The runner executes stages in cost order and **re-tests a gate between groups** — D4's
demand-plan idea applied to retrieval, where it is even cheaper because the free channels are index
scans.

```
FREE group        identity · lexical · lexical_tri · structural
     └─ gate: sufficient(free)  ==  n_hits >= k
                                AND normalized_top1 >= 0.35
                                AND (top1 - top2)/ceiling >= 0.05
                                AND channels_ran >= 2
LOCAL_COMPUTE     semantic, local embed driver
BILLED_API        semantic, hosted embed driver · LLM rerank (D10's, if it ever exists)
```

Thresholds are jcodemunch's measured regret constants restated (low confidence 0.30, thin top-1 0.10,
ambiguous gap 0.05, `regret.py`), nudged up because a document corpus has more near-duplicates than a
code corpus. `mode="exhaustive"` skips the gate and runs everything — that is the eval mode and the
mode the tuner replays.

**Why a demand plan and not "always run everything":** on a warm 1M-block store the four free channels
plus fusion is a low-single-digit-millisecond query. One local embed call is 8–30 ms on CPU and is the
*entire* latency budget of G10's 250 ms once you add a cold model load. On a hosted embedder it is a
network round trip and a bill. Most queries against a document corpus are keyword-shaped and clear the
gate. **Why not sampling shortcuts:** none, for D4's stated reason — an approximation that is wrong on
precisely the query that motivated the feature is worse than the cost it saves.

**Why not a cost-based optimizer.** There are four channels and one join order. A CBO here is an
abstraction with one plan shape and a statistics table nobody maintains. SQLite's own planner handles
the SQL; the only decision above it is "did the free tier answer", and that is one function with four
named thresholds and a recorded verdict.

### 2.6 The verdict: four states, ten gates, over D2's `diag` table

This is the highest-value thing in the whole decision and it is almost free, because D2 already built
the input. Reimplemented from `mine-graph.md §4.6`.

`result_count == 0` becomes `absent` only after failing ten gates in precedence order; each gate forces
`degraded` instead. One gate (`state == absent`) governs citability, so every new hazard is expressed
by forcing `degraded` and never by adding a second rule.

| # | Gate | Document instantiation | Source of truth |
|---|---|---|---|
| 1 | `timed_out` | the query budget expired mid-scan | `QueryBudget` |
| 2 | `channel_unavailable` | semantic requested, no `vector_space` for this corpus or the `embed/1` probe is red; trigram requested, `block_tri` absent | `vector_space`, D3 `ProbeVerdict` |
| 3 | `snapshot_changed` | a federated leg read a different `PRAGMA data_version`, or the read txn was retried | §2.7 |
| 4 | `coverage_incomplete` | `doc.status IN ('failed','skipped')` or `page.status <> 'ok'` **inside the filtered scope** | D2 `doc`/`page` |
| 5 | `source_ahead` | a source in scope has a newer sha/mtime than `doc.source_sha256` | D2 `QuoteVerdict` |
| 6 | `freshness_unknown` | `work` rows in scope are `pending`/`claimed`, or the racily-clean stat rule failed | D6 `work` |
| 7 | `moved_during_scan` | a shard became unreachable mid-query | §2.10 |
| 8 | `inputs_incomplete` | `diag.fatal = 1` in scope, or D3 quarantined a driver this run | D2 `diag`, D3 `driver_observation` |
| 9 | `truncated_by_packing` | `matches_before_packing > 0` and `len(hits) == 0` | D9's packer |
| 10 | `absence_unprovable` | **the only channel that ran is `semantic`** | `ChannelResult.status` |

Gate 10 is checked last and deliberately: every gate above it names something the caller can fix
(re-index, widen scope, raise the budget). A cosine zero is a statement about the embedding model, not
about the corpus, and must not be citable as one.

`degraded_because` is not a boolean — it names the `diag.code`s and the `(doc_ord, page)` ranges. The
product sentence this buys, which no RAG system in existence emits:

> `absent` — except pages 12–40 of `d7` failed OCR (`OW_NEEDS_OCR`) and `d11` is encrypted
> (`OW_ENCRYPTED`); 2 of 214 documents in scope were not searched.

`SCORER_VERSION` is an integer bumped on any change to weights, `k`, the identity ladder or the gate
thresholds, and it is in every `query_event` row and every verdict, so "0.8 confidence" is a
measurable statement rather than a number.

### 2.7 Concurrency, durability and snapshot isolation

**One writer. WAL. Readers never block. Everything else is a degrade path.** codegraph's answer, and
the measurements behind it are the best in the collection.

- Pragmas exactly as D1 mandates, `busy_timeout = 5000` **first** (before `journal_mode`, or a
  contended open throws instead of waiting — codegraph #238), then `foreign_keys=ON`,
  `journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`,
  `mmap_size=268435456`, `journal_size_limit=67108864`. Split into `_INIT_PRAGMAS` (persistent, per
  file) and `_PRAGMAS` (per connection) — jcodemunch's refinement.
- **Heal-on-open** at 64 MB: a SIGKILLed process leaves an arbitrarily large WAL and nothing shrinks it
  (25.6 GB observed in codegraph). `OW-S-002`, logged, not silent.
- **The full eight-property WAL valve**, ported to Python from `codegraph/src/db/wal-valve.ts`
  (constants verified in-tree: `DEFAULT_WAL_VALVE_MB = 256` at `:50`, `HARD_CAP_MULTIPLIER = 2` at
  `:52`, `FILE_CAP_MULTIPLIER = 4` at `:54`, `MAX_PAUSED_BACKFILL_PASSES = 20` at `:56`, threshold
  `min(2048, max(256, dbSize/4/MiB))` at `:75`). Each of the eight has a measured failure behind it and
  none is optional: deferred autocheckpoint (default autocheckpointing was ~95% of all disk I/O — 45 s
  vs 19+ min at 150 IOPS); a **growth-relative** trigger baselined on the last full backfill; off-thread
  PASSIVE checkpoints on a separate connection; writer backpressure at 2× with a *full* backfill as the
  release condition; TRUNCATE at 4×; the futility latch; `journal_size_limit`; at-open heal.
  The load-bearing subtlety: **a WAL file's size never shrinks**, so an absolute-size trigger
  degenerates into pausing the writer forever (guava: ~9 min per 160 files). The futility latch exists
  because 20 checkpoint passes per over-cap boundary against a pinned reader is what turned a slow index
  into **22 GB WAL, exit 137**.
- **Bulk-index windows.** Drop the non-unique secondary indexes on `block`, `rel` and `kedge` for a bulk
  load and rebuild after, with a **cooperative yield between each `CREATE INDEX`** — codegraph measured
  2.8 s → 1.1 s on a 224k-edge insert with ~0.3 s of recreate, and 79 s of back-to-back index builds
  against a 60 s watchdog means "SIGKILLed right after doing the work." The DDL is extracted from
  `schema/` by index name and a miss is a hard raise, never a skip: a bulk window that silently fails to
  recreate an index leaves a permanently slow database. FTS5 is handled the same way —
  `INSERT INTO block_fts(block_fts) VALUES('rebuild')` after a bulk import instead of per-row triggers.
  Crash-safe by construction: the next open re-applies `CREATE INDEX IF NOT EXISTS`. The one index kept
  inside every window is the UNIQUE identity index, because `INSERT OR IGNORE` conflicts on it.

**Snapshot isolation for a query running while a re-index commits — the mechanism, stated exactly.**
A retrieval call issues 6–12 statements (narrowing, four channels, hydration, `diag` scan for the
verdict). If they run as autocommit statements they see up to twelve different snapshots, and fusion
then mixes generations: a `block_id` from the lexical channel can be tombstoned by the time the
structural channel expands from it, and the verdict's coverage count can disagree with the hits it is
describing. **Therefore: every retrieval call runs inside exactly one `BEGIN DEFERRED` read
transaction, established by the narrowing statement and held to the end of hydration.** In WAL mode
that is a genuine repeatable-read snapshot with zero locking cost and zero writer interference. Gate 3
of the verdict becomes structurally satisfiable rather than best-effort on the single-file path, and
remains a real gate on the federated path.

The cost of that, stated: **a held read transaction pins the WAL**, which is exactly the condition the
valve's futility latch was written for. So the read transaction is bounded by
`[store] query_txn_ms = 2000`; past it the reader commits, emits `OW-S-006 SNAPSHOT_EXPIRED`, and the
verdict is `degraded{snapshot_expired}`. A 2-second cap is 8× the G10 budget and ~30× a warm query, so
in practice only a pathological hydration hits it — and when it does, degrading is strictly better than
stalling the indexer.

**Write contention under a watcher.** The rule is that *the set of writers is one process, by
construction, not by lock discipline*:

| Process | Store handle | Writes |
|---|---|---|
| indexer / watcher (D6) | read-write, holds the `store.write` scoped lock | everything |
| `omniweave-serve` MCP | `mode=ro` (or `mode=ro&immutable=1` when no `-wal` sidecar exists) | `telemetry.db` only |
| `ow query` CLI | `mode=ro` | `telemetry.db` only |
| `ow index` (second invocation) | attempts the lock, **enqueue-before-lock** | via the lock holder |

D1's `connect_readonly` ladder is applied by every reader. Interactive lock wait 2 s, batch 60 s, named
per call site, never a constant; the holder is named in the WARNING past 1 s, and `(host, pid,
create_time)` is the holder identity, never a bare pid (jcodemunch #450: "two-week-old rows resolving
to a Chrome renderer"). Enqueue-before-lock (graphify's ordering, which everyone gets backwards): a
trigger writes its `work` rows first, then tries the lock; if the lock is held it returns immediately
having lost nothing, because the holder's next `claim()` is a superset. That removes the drain
protocol, the pending-changes file and the 20-pass ceiling entirely.

The residual contention is indexer-vs-indexer, and it is a 5 s `busy_timeout` plus a scoped lock. A
reader is never in that path. **A query never waits on a write.**

The watcher tier itself is codegraph's, restated with its own numbers: ≤2 pending units → 300 ms
debounce; 3–500 → the full debounce with a scoped sync; >500 → a full scan-diff, which is also the
repair mechanism. `MAX_DIR_WATCHES = 50_000` against an inotify budget commonly 8k–128k, which is why
**at tier M live watching is unavailable and the watcher is an optional freshness tier, not a
guarantee** — and `freshness = "not_tracked"` is the honest answer there, disclosed rather than
refused.

### 2.8 Embeddings: an operator, and vectors keyed by content

Embeddings are **not core**. D3 already made `embed/1` a Port, so an embedder is a Driver with a card,
a licence tier, a cost class and a probe. What D5 owns is the *space*, the *join*, and the *refusal*.

**A `vector_space` row is LEANN's `meta.json` as a table, and it is a write-time contract.** LEANN's
best idea is not the pruned graph; it is that the index metadata records everything needed to answer a
query the same way it was built — model id, embedding mode, provider options **including prompt
templates**, dimensions, distance metric, storage-mode flags, id scheme, and where the payload lives
(`api.py:648-684`). Its worst is that the illegal *build* combination is corrected in code
(`api.py:449-458`) while the illegal *search* combination is a README sentence — a footgun that returns
silently wrong results. So: **every flag pair is validated from the stamped metadata on both paths**,
and a query whose embed driver's `(model_id, model_rev, dim, metric, normalization, prompt_fp)` does
not match the space is refused with `OW-S-007 VECTOR_SPACE_MISMATCH`, naming both tuples. Never a silent
mismatch, never a coerced dimension. Prompt templates are applied exactly once, client-side, and
stripped from anything handed to the driver — LEANN's double-templating fix, which is the vector-store
analogue of decode symmetry.

**D2's open question — "Do embedding rows key on `block_id` or on `content_digest`?" — is answered:
both, at different levels, and that is not a fudge.**

```
vec payload   keyed on (space_id, content_digest)   -> vec_ord      content-addressed
join row      block_vec(block_id, space_id, vec_ord)                block-addressed
```

Consequences, which is why this is the right answer:

- A `rebind` that **carries `block_id` and changes `content_digest`** (D2 rule 2, "equal `addr` and
  `kind`, digest changed") correctly re-embeds — one new payload, one updated join row.
- A `rebind` that **carries `content_digest` under a new `block_id`** (a re-parse that re-segments
  around an unchanged paragraph) is **free** — new join row, zero embed calls.
- Two identical running footers across 5,000 pages share **one** vector. On a real 10-K corpus this is a
  measurable fraction of all blocks, and it is the same dedupe LEANN gets from `passage_id_scheme =
  content_hash`.
- A `digest_recipe` bump (D2 prices it as at most annual) re-embeds everything. Named, budgeted, and
  the reason D2 restricted digest inputs to stored fields.

This is LEANN's `passage_id_scheme ∈ {sequential, content_hash}` fork resolved by taking content-hash
for the payload and keeping a durable surrogate for the join — the pair LEANN cannot have, because it
has no `block_id`.

**On LEANN's selective recomputation, which the brief asks me to engage.** It is available to us —
D1 bans a framework daemon but explicitly permits "a unix socket or named pipe at 0600", and D3's
`subproc` host already runs a long-lived worker per `(driver_id, config_digest)` over exactly that, with
LEANN's own unauthenticated ZMQ-on-a-dynamic-loopback-port (`api.py:133`) named as the anti-pattern it
replaces. So the mechanism is legal. **I still reject it as the v1 default, on arithmetic.** LEANN's
headline is 201 GB → 6 GB at 60M chunks (97%, and 91% at 2.1M); the saving improves with corpus size and
is decisive there. At our S/M range it is not: 768-dim **float16** is 1.5 KB/block, so 1M blocks is
1.5 GB and 10M is 15 GB. A fitted PCA to 256 dims plus int8 quantization gives **256 B/block** — a 6×
reduction on float16, 12× on float32 — putting 10M blocks at 2.5 GB with **zero query-time model
calls**, against LEANN's 64–200 chunk embeddings recomputed *per query*. Under a 250 ms warm-query
budget, paying 64 forward passes per query to save 12 GB of disk is the wrong trade at every scale we
ship at. So:

```
[store.vector] mode = "stored"     # stored (default) | recompute
```

`recompute` exists, is stamped in the space metadata, is validated on both build and search, and
becomes the recommendation above ~50M vectors where LEANN's numbers start to dominate. Its illegal
combinations are refused, not warned about. **That is LEANN's real contribution taken whole — the
flag pair stamped in metadata — with its default inverted for our scale.**

**ANN backend.** Below 50,000 vectors, brute force over the mmapped `vectors.f16` is correct and needs
no library — but pure Python cannot do it in 250 ms, so `flat` is honest about its ceiling and refuses
above it. Above that, `usearch` (Apache-2.0, ~4 MB wheel, no torch, not on D1's denylist) inside
**`omniweave-graph`**, which D1 already sizes at 150 MB. This adds a dependency line to an existing
distribution; it does **not** add a twelfth distribution and does not touch D1's extra→sibling rule.
Price it as one line in `tools/weights.toml`.

**Post-filter over-fetch, because this is the classic silent recall bug.** LEANN applies
`metadata_filters` *after* the ANN search with no over-fetch (`api.py:259-290`), so a restrictive filter
over `top_k=5` returns zero rows while matching documents exist — recall loss shaped exactly like
absence. Ours: the narrowing set is known before the ANN call, so we compute selectivity
`|narrow| / n_live_blocks` and over-fetch `ceil(k / max(selectivity, 0.001)) * 1.5`, capped at
`k * 64`; if the cap is reached with fewer than `k` survivors we retry once at the cap and then emit
`OW-S-013 OVERFETCH_EXHAUSTED` and `degraded{filter_overfetch_exhausted}`. Never a quiet short list.

### 2.9 The graph: an edge table, and traversal that is bounded by construction

**No graph engine, no adjacency pickle, no NetworkX-as-primary.** The evidence is one-sided:

- codegraph indexed **70,000 files / 2,000,000 symbols / 6,400,000 relationships in under 12 minutes on
  a 2-core 6 GB VPS**, in SQLite, "where RAM-first designs run out of memory before reaching 1%".
- graphify's NetworkX + committed `graph.json` design states its own ceiling in a constant:
  **`_MERGE_MAX_BYTES = 50 MB`, `_MERGE_MAX_NODES = 100_000`**, with typical graphs "< 5 MB / < 50k
  nodes". That is two to three orders of magnitude short of 10M blocks.

So: an edge table, with codegraph's three hard-won schema rules.

1. **Identity is a UNIQUE expression index with `IFNULL` sentinels, enforced in the schema, never in
   the writer.** `INSERT OR IGNORE` with nothing to conflict on is a plain `INSERT`; codegraph #1034
   produced "byte-identical duplicate rows that inflated counts and flowed into callers/impact." SQL
   NULLs are each distinct, so a nullable natural key needs a sentinel — and the migration that installs
   the index must `GROUP BY` the identical expression.
2. **Narrow single-column indexes are dead weight** when a composite covers them by left-prefix scan;
   codegraph's migration v4 *drops* `idx_edges_source`/`idx_edges_target` because `(source, kind)` and
   `(target, kind)` already serve them. Every index in my DDL carries a comment naming the query it
   serves, and CI runs `EXPLAIN QUERY PLAN` over the eleven hot queries and fails if any of them falls
   to a table scan.
3. **Partial indexes for minority populations** — `unresolved_ref` retry, `restriction_bits <> 0`
   (D3's), `trust < 2` (D2's `block_review`).

**Multi-hop.** Two mechanisms, chosen by depth, and neither is a recursive CTE with unbounded fanout:

- **Depth ≤ 3 (the whole product surface):** a Python-driven frontier BFS over batched
  `WHERE src_block IN (…)` queries, with a **visited set**, a per-hop `MAX_FRONTIER = 512`, a total
  `MAX_VISITED = 4096`, and a relation-kind allowlist supplied by the query. Deterministic, bounded,
  cancellable at the top of each hop, and it composes with `tmp_narrow` because each hop is a join.
  Score is `Σ prior[kind] / (1 + hops)`, total-ordered on `(-score, block_id)`.
- **Unbounded reachability over a *named* relation subset** (`continues`, `supersedes`, `cites`):
  a materialized `edge_closure(src_block, dst_block, relation, depth)` capped at depth 4, rebuilt **per
  document** on that document's re-index, not corpus-wide. Only three kinds qualify and only because
  each is near-tree-shaped, so the closure is O(n), not O(n²). Any other kind is refused, because
  `semantically_similar_to`-shaped relations have a dense closure and materializing it is how you get a
  50 GB index for a 3 GB corpus.

No PageRank at v1. It is a global recomputation with one consumer, it is the channel jcodemunch weights
*lowest* (0.4), and the bug it caused there (an unfiltered structural channel returning the whole
repository) cost more than the signal was worth. A `centrality` column is a phase-5 additive column with
a named consumer or it does not ship.

**Every edge carries where the relationship was observed.** graphify's `source_file` on *edges*, not
just nodes, is what makes "where does this document assert that" answerable and what turns a blast-radius
answer into a citation. Our column is `kedge.observed_at_block`.

**`unresolved_ref` is the table nobody else has and it is the reason an incremental index converges.**
codegraph's status lifecycle, restated for documents: extraction that emits a reference it cannot
resolve **writes a row**, not a log line — a citation to a document not yet ingested, a cross-reference
to a figure in another PDF, a caption naming a section number, a `See §4.2` whose §4.2 is in a different
file. Rows are `pending` on insert; a resolution pass either deletes the row (resolved) or marks it
`failed`, kept, with a `name_tail` retry key and a **partial index `WHERE status='failed'`** because on
a healthy index the pending set is empty and the failed set is the only population worth indexing. "The
corpus grew and now this citation resolves" becomes a bounded query instead of a re-index. This is also
the honest home for jcodemunch's `*_unmapped` idea: **the residue is data.**

### 2.10 Scale: 10k blocks on a laptop to 10B blocks on a cluster

Three tiers. The schema, the channel contract, the fusion function and the verdict are **identical in
all three**. What changes is the number of files and who fuses.

| Tier | Blocks | Shape | Store size | What changes |
|---|---|---|---|---|
| **S** | ≤ 5M | one `index.owstore` | ≤ 3 GB | nothing. This is the laptop, and it is phase 1. |
| **M** | ≤ 500M | N sharded `.owstore` files, one host, `shard_target = 32M` blocks (~18 GB) | ≤ 300 GB | a `catalog.owstore` maps shard → range; queries scatter-gather |
| **L** | > 500M | shards across hosts, or Postgres partitions (D1's T3) | TB | shards are remote; `Dialect` swaps to Postgres if T3 is chosen |

Sizing basis: D2's measured ~338 B/block, 10M blocks ≈ 3.3 GB of block rows; add FTS5 and our secondary
indexes and the working figure is ~550 B/block.

**Sharding key: `blake2b(doc_key) % N`, and a document is never split across shards.** `doc_key` is
D2's content identity of the source, so a re-ingest of the same bytes lands in the same shard, and
insertion order never hot-spots (which `doc_ord` would). The invariant that a document is whole in one
shard is what makes this cheap: containment, `rel`, `cell`/`grid_slot`, `part`, `asset`, `page_render`,
`cite` resolution and every intra-document query are **shard-local**, so the only cross-shard structure
is D7's inter-document `kedge`. Those are **mirrored** — written once into each endpoint's shard with a
`mirror` flag — so 1-hop expansion never leaves the shard and 2-hop costs one extra round.

**`block_id` allocation across shards — D2 filed this as an open question and it must be decided before
any FK ships.** `block_id` is a 64-bit composite: **high 12 bits = shard ordinal, low 52 bits = a
per-shard sequence.** 4,096 shards × 4.5×10¹⁵ blocks each, which is not a ceiling anyone reaches. The
S-tier store is shard 0, so its ids are literally `1..N` and an S→M migration **does not rewrite a
single id** — it copies whole documents into new shards, and only the newly-placed documents get new
ids, which is a `rebind` the model already supports.  `N` is fixed at corpus creation; re-sharding is a
copy, and `ow store reshard` says so.

**Cross-shard fusion is where the honest answer differs from the convenient one.** BM25's idf is
per-index. Ten shards means ten different idfs for the same term, so a raw `bm25()` comparison across
shards is wrong, and rank-fusing per-shard ranks is *also* wrong (rank 1 in a 100-block shard is not
rank 1 in a 32M-block shard). Two mitigations, both stated:

1. **Within one corpus,** shards are large (≥ 8M blocks) and drawn by a hash of `doc_key`, so their term
   distributions converge; the coordinator over-fetches `3k` per shard per channel, merges, and
   **re-ranks the merged candidate set using a global `term_df` table** maintained incrementally in
   `catalog.owstore` (one row per term above a df floor of 8 — for a document corpus that is ~2–5M rows,
   ~120 MB). BM25 over a few thousand candidates with global df and per-block length is a
   coordinator-side computation of a few milliseconds. This is exact enough to be called exact and I
   will not call it exact: the verdict carries `fusion_kind = "global-df-rerank"`.
2. **Across corpora (federation),** there is no shared idf and there should not be. Each corpus fuses
   locally, normalizes by **its own** ceiling into `[0,1]`, and the coordinator merges by normalized
   score with a per-corpus prior. The verdict says `federated: true, fusion_kind:
   "normalized-per-corpus"` and `OW-S-014 CROSS_SHARD_FUSION_APPROXIMATE` appears in `degradations[]`.
   **A cross-corpus ranking that claims to be exact is a lie, and the cheapest fix is to stop claiming
   it.**

Federation unit is the **corpus**, not the shard, because that is the unit a team actually has: a
`corpus` is one `.owstore` (or one shard set) with one `corpus_id`, one retention policy and one set of
`restriction_bits` consequences. `ow query --corpora legal,eng,archive`.

**10B blocks, priced honestly.** At ~550 B/block, 10B blocks is **~5.5 TB** of relational data,
~313 shards at 32M blocks, ~2.5 TB of int8 vectors, and a global `term_df` in the tens of millions of
rows. That is a cluster, it is not v1, and it is not a thing a small team ships before it has a paying
user at tier M. What phase 1 buys is that **nothing in the S-tier design has to be undone to get
there**: same DDL, same channels, same `fuse()`, same verdict, one new coordinator process and a
`term_df` table.

### 2.11 Incremental update

Four mechanisms, three of them already proven in `_collections/`:

1. **Per-unit content hash with the racily-clean rule.** `(size, mtime_ns, indexed_at_ns)` where
   `indexed_at_ns` is captured **before** the content read, and an entry is trusted only when
   `mtime_ns + 2s <= indexed_at_ns`. Entries without the field are untrusted, not trusted. This is
   graphify `cache.py:239-265` and it is the single most important correctness detail in the mine —
   skip it and some fraction of edits serve stale extractions forever with no symptom. The stat memo is
   keyed by the **salt**, not the absolute path (graphify #1989: the same file hashed under two roots
   in one run poisoned the persisted index).
2. **Tier-scoped replacement keyed on `origin_operator`.** Already D6's I4; D5's contribution is that
   every derived row in *my* tables carries it too, and every eviction statement filters on it. A free
   FTS re-index or structure re-extraction after a keystroke must never delete a billable embedding row
   — that is graphify #2334/#1865, and it is the worst failure available to a pipeline that mixes cost
   tiers.
3. **`refdelta` — the document analogue of codegraph's `definitionDelta`, and the thing that makes
   incremental *correct* rather than merely fast.** It is the set of globally-resolvable reference keys
   whose definition set changed in this run: heading numbers, figure and table labels, defined terms,
   citation keys, document ids, `part` paths. Computed as a per-document symmetric difference of
   `doc_key \0 refkey` pairs across the write phase. A body-only edit leaves it empty, which is the
   common case and free. Non-empty means: re-run the resolution pass for `unresolved_ref` rows whose
   `name_tail` is in the delta, **and** re-bind already-resolved `rel`/`kedge` rows in *untouched*
   documents whose target name is in the delta. Without it, incremental and full diverge and nobody
   notices for months — codegraph measured **4.3% of distinct edges wrong, in both directions,
   silently**, from skipping exactly this pass.
4. **Deletion is explicit, never inferred**, and `ON DELETE CASCADE` with `foreign_keys=ON` does the
   work declaratively from `doc` down. graphify hand-rolls 290 lines of eviction because JSON has no
   foreign keys; graphrag computes `deleted_inputs` and consumes it nowhere.

Plus **the per-unit attribution guard** (graphify's `_check_shrink` at the right granularity): an
unaccounted row loss refuses the transaction for *that unit*, marks the work row
`failed_permanent(UNEXPLAINED_LOSS)`, and records it — and **a unit whose derivation failed this run
never accounts for its own losses**, which is the clause that makes the guard sound. Overrides are named
per check (`--allow-unexplained-loss`), never one `--force`.

And the cost-tiered reconciliation split (graphify's two-tier watcher): free reconciliations
(FTS re-index, structural re-extraction, eviction — **deletion is free, which is easy to get wrong**)
run on the debounce; paid reconciliations (re-embed, LLM extraction) set a durable staleness flag that a
human or agent clears. `ow doctor` reports it.

**FTS5 ghosts, named because external content makes them silent.** The sync triggers fire only for
`NEW.state = 0`; a generation retirement issues explicit `('delete', …)` command rows for every retired
`block_id` in a bounded off-hot-path `fts_gc` pass. `ow doctor` compares
`SELECT count(*) FROM block_fts` against `SELECT count(*) FROM block WHERE state=0` at the current
generation and raises `OW-S-010 FTS_GHOSTS` on drift. Get the `'delete'` idiom wrong and the index
accumulates ghosts that return dead `block_id`s forever.

### 2.12 The index is a cache. It is never committed to git.

**Ruling: no committed index, no merge driver, and the reasons are structural rather than aesthetic.**

- The `.owstore` is a binary SQLite file with a WAL. Git has no merge for it and never will.
- **D2 forbids what a committed index would need**: `block_id` is "store-local", "never exported and
  never shown to a model", and the `.owdoc` archive "NEVER contains a `block_id`". A committed index is
  an artifact whose primary keys are meaningless in another checkout.
- graphify's merge driver — the strongest precedent for the idea — is `nx.compose`, a **pure union that
  ignores `%O` (the base)**, so a node deleted on one branch and untouched on the other comes back. The
  repo names it "union merge" honestly, and its caps are **50 MB / 100k nodes**, two to three orders
  below our target.
- codegraph's WAL numbers make the storage case on their own: 5.9 GB of WAL against a 340 MB DB during a
  bulk index. That is not going in a repository.

**What *is* committable, and it gets the real benefit graphify was after — an index whose freshness CI
can assert:**

- `.owdoc` archives (D2's interchange form) for any document a team wants under version control. They
  are ZIPs of zstd NDJSON, contain no `block_id`, and D2 already gates
  `import(export(store)) == store` in CI.
- **`index.lock.json`** — generated, sorted, byte-stable, no timestamps, ~200 B per document. It is the
  index's *receipt*: `{store_schema_version, digest_recipe, scorer_version, corpus_id, shard_count,
  vector_spaces[], documents: [{doc_key, source_sha256, gen, status, block_count,
  content_digest_root}]}`. `ow index verify --manifest` compares it against the live store and against
  the source tree and exits non-zero on drift. That makes "is the index current for this commit" a CI
  gate without committing a gigabyte, and it is the honest version of graphify's idea.

---

## 3. Concrete shape

### 3.1 DDL — additive to D2's `.owstore`

```sql
-- ═══════════ omniweave_core/store/schema/0002_index.sql ═══════════
-- Additive to D2's .owstore. Every index below names the query it serves; CI runs
-- EXPLAIN QUERY PLAN over the eleven hot queries and FAILS on a table scan.
-- Set at CREATE time, before any table exists (cannot be changed later):
--   PRAGMA page_size    = 8192;      -- block rows average ~340 B; 8 KiB fits ~24/page
--   PRAGMA auto_vacuum  = INCREMENTAL;  -- VACUUM on a 35 GB file is an hour; incremental is not

-- ── LEXICAL ───────────────────────────────────────────────────────────────────
-- D5's amendment to D2's block_fts: TWO columns, both existing columns of `block`,
-- so that "D5 owns the BM25 weights" is satisfiable at all. Tokenizer UNCHANGED.
DROP TABLE IF EXISTS block_fts;
CREATE VIRTUAL TABLE block_fts USING fts5(
  title, text,
  content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');
-- BM25 weights: (title 8.0, text 1.0). NOT codegraph's 20x: a heading is prose, and a 20x
-- weight promotes TOC entries above the sections they name. Tuned by the gate in §5.
--   SELECT block_id, -bm25(block_fts, 8.0, 1.0) AS s FROM block_fts
--    WHERE block_fts MATCH ?1 AND rowid IN (SELECT block_id FROM tmp_narrow)
--    ORDER BY s DESC, rowid ASC LIMIT ?2;   -- ?2 = 5 * k (over-fetch before re-rank)

-- Triggers fire ONLY for live blocks. A retired generation is swept by fts_gc().
CREATE TRIGGER block_fts_ai AFTER INSERT ON block WHEN NEW.state = 0 BEGIN
  INSERT INTO block_fts(rowid, title, text) VALUES (NEW.block_id, NEW.title, NEW.text);
END;
CREATE TRIGGER block_fts_ad AFTER DELETE ON block WHEN OLD.state = 0 BEGIN
  INSERT INTO block_fts(block_fts, rowid, title, text)
    VALUES ('delete', OLD.block_id, OLD.title, OLD.text);
END;
CREATE TRIGGER block_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, title, text)
    SELECT 'delete', OLD.block_id, OLD.title, OLD.text WHERE OLD.state = 0;
  INSERT INTO block_fts(rowid, title, text)
    SELECT NEW.block_id, NEW.title, NEW.text WHERE NEW.state = 0;
END;

-- Second lexical channel. ON below 5M blocks, opt-in above. ~2.6x the primary index size.
-- Serves: CJK (unicode61 makes one giant token), "ISO27001" vs "ISO 27001", §12.4(b), hyphen
-- artifacts. A CHANNEL, fused -- never a fallback, because a fallback makes two answers
-- incomparable while a fusion makes them additive. (codegraph reached this with a LIKE ladder.)
CREATE VIRTUAL TABLE block_tri USING fts5(
  text, content='block', content_rowid='block_id', tokenize='trigram');

-- ── IDENTITY ──────────────────────────────────────────────────────────────────
-- Materialized derived index whose rows are PROPOSALS, re-verified against `block` at read
-- time -- so it needs NO delete path, which removes an entire class of consistency bug.
-- (codegraph name_segment_vocab, schema.sql:137-149.) A full re-index clears it.
CREATE TABLE term_vocab (
  segment  TEXT    NOT NULL,   -- lowercased, NFD-stripped: "références" -> "references"
  block_id INTEGER NOT NULL,
  src      INTEGER NOT NULL,   -- 0=title 1=defined_term 2=figure_label 3=citation_key 4=heading_no
  PRIMARY KEY (segment, block_id, src)
) WITHOUT ROWID;
CREATE INDEX term_vocab_block ON term_vocab(block_id);
CREATE INDEX block_title_lower ON block(doc_ord, lower(title))
  WHERE title IS NOT NULL AND state = 0;

-- ── SEMANTIC ──────────────────────────────────────────────────────────────────
-- LEANN's meta.json as a row. A WRITE-TIME CONTRACT: a mismatch is refused, not coerced,
-- on BOTH the build path and the search path (LEANN validates only the build path).
CREATE TABLE vector_space (
  space_id      TEXT PRIMARY KEY,          -- 'e5-small@a1b2c3/cos/256i8'
  driver_id     TEXT    NOT NULL,          -- D3 registry key of the embed/1 driver
  driver_schema_v INTEGER NOT NULL,
  model_id      TEXT    NOT NULL,
  model_rev     TEXT    NOT NULL,          -- EXACT sha. 'main' is a load error (D3/D4 R14).
  dim           INTEGER NOT NULL,
  metric        TEXT    NOT NULL CHECK (metric IN ('cosine','ip','l2')),
  normalized    INTEGER NOT NULL,
  dtype         TEXT    NOT NULL CHECK (dtype IN ('f32','f16','i8')),
  reduction     TEXT,                      -- NULL | 'pca:256@<sha256 of the fitted basis>'
  prompt_fp     TEXT    NOT NULL DEFAULT '',  -- templates applied ONCE, client-side (LEANN)
  mode          TEXT    NOT NULL CHECK (mode IN ('stored','recompute')),
  backend       TEXT    NOT NULL CHECK (backend IN ('flat','usearch')),
  payload_dir   TEXT    NOT NULL,          -- 'vec/<space_id>/' -- resolved METADATA-relative FIRST
  n_vectors     INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL,
  -- Illegal combinations REFUSED at construction AND at search, from this row.
  CHECK (NOT (mode = 'recompute' AND dtype = 'i8')),     -- recompute needs the live model's dtype
  CHECK (NOT (backend = 'flat' AND n_vectors > 50000))   -- flat is honest about its ceiling
);

CREATE TABLE block_vec (
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  space_id TEXT    NOT NULL REFERENCES vector_space(space_id) ON DELETE CASCADE,
  vec_ord  INTEGER NOT NULL,        -- dense row index into vec/<space_id>/vectors.<dtype>
  PRIMARY KEY (block_id, space_id)
) WITHOUT ROWID;
CREATE INDEX block_vec_ord ON block_vec(space_id, vec_ord);

-- The payload is CONTENT-addressed: identical text embeds once, corpus-wide. This is what
-- makes a re-parse that re-segments around unchanged prose FREE, and it dedupes the running
-- footer that appears on all 5,000 pages. (D2 open question, answered.)
CREATE TABLE vec_payload (
  space_id       TEXT NOT NULL REFERENCES vector_space(space_id) ON DELETE CASCADE,
  content_digest BLOB NOT NULL,     -- D2's blake3-128. Geometry deliberately not an input.
  vec_ord        INTEGER NOT NULL,
  refcount       INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (space_id, content_digest)
) WITHOUT ROWID;

-- ── STRUCTURAL (D7 owns the vocabularies; D5 owns the storage and the traversal) ──────────
CREATE TABLE kedge (
  kedge_id   INTEGER PRIMARY KEY,
  src_block  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_block  INTEGER,                       -- NULL while unresolved
  relation   INTEGER NOT NULL,              -- FK into D2's enum_val; D7 owns the vocabulary
  observed_at_block INTEGER,                -- WHERE the relationship was observed (graphify)
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust      INTEGER NOT NULL,              -- D2 Trust. Absent => AMBIGUOUS. Migrations only downgrade.
  score      REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL,            -- D6 I4 ownership axis
  origin_driver   TEXT NOT NULL,            -- D3
  driver_schema_v INTEGER NOT NULL,         -- D3
  restriction_bits INTEGER NOT NULL DEFAULT 0,   -- D3: restrictions travel to derived items
  mirror     INTEGER NOT NULL DEFAULT 0,    -- 1 => a cross-shard copy held at the other endpoint
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
-- Identity in the SCHEMA. INSERT OR IGNORE with nothing to conflict on is a plain INSERT
-- (codegraph #1034: byte-identical duplicates that inflated counts and flowed into callers).
-- SQL NULLs are each distinct, hence the IFNULL sentinels. The installing migration must
-- GROUP BY this exact expression.
CREATE UNIQUE INDEX kedge_identity ON kedge(
  src_block, IFNULL(dst_block,-1), relation, IFNULL(observed_at_block,-1), producer_id);
CREATE INDEX kedge_src ON kedge(src_block, relation);   -- covers src-only by left-prefix scan
CREATE INDEX kedge_dst ON kedge(dst_block, relation) WHERE dst_block IS NOT NULL;
CREATE INDEX kedge_restricted ON kedge(restriction_bits) WHERE restriction_bits <> 0;
-- NO kedge_source / kedge_target single-column indexes: the composites cover them
-- (codegraph migration v4 DROPS the equivalents as dead weight on writes).

-- Materialized ONLY for near-tree relations. Any other kind is REFUSED: a dense closure is how
-- you get a 50 GB index for a 3 GB corpus. Rebuilt per document, not corpus-wide.
CREATE TABLE edge_closure (
  src_block INTEGER NOT NULL, dst_block INTEGER NOT NULL,
  relation  INTEGER NOT NULL, depth INTEGER NOT NULL CHECK (depth BETWEEN 1 AND 4),
  PRIMARY KEY (src_block, relation, dst_block)
) WITHOUT ROWID;

-- ── THE RESIDUE IS DATA (codegraph's biggest architectural idea) ──────────────
CREATE TABLE unresolved_ref (
  ref_id     INTEGER PRIMARY KEY,
  src_block  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ref_kind   TEXT    NOT NULL,      -- citation | figure | table | section | defined_term | uri
  ref_text   TEXT    NOT NULL,      -- as written: "see §4.2", "Smith 2019", "Fig. 3a"
  name_tail  TEXT    NOT NULL DEFAULT '',   -- written when marked failed; the retry key
  candidates TEXT,                  -- JSON array of block_id considered and rejected
  status     TEXT    NOT NULL DEFAULT 'pending',   -- pending | failed  (resolved => row DELETED)
  last_try_gen INTEGER
);
-- PARTIAL: on a healthy index the pending set is empty and the failed set is the only
-- population worth indexing (codegraph migrations.ts v8).
CREATE INDEX unresolved_failed_tail ON unresolved_ref(name_tail) WHERE status = 'failed';

-- Convergence key: reference keys whose DEFINITION set changed this run.
-- Empty on a body-only edit, which is the common case and free.
CREATE TABLE refdelta (
  run_id  TEXT NOT NULL, refkey TEXT NOT NULL, doc_ord INTEGER NOT NULL,
  PRIMARY KEY (run_id, refkey, doc_ord)
) WITHOUT ROWID;

-- ── OPERATIONAL ───────────────────────────────────────────────────────────────
CREATE TABLE store_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- corpus_id · shard_ordinal · shard_count · store_schema_version · scorer_version
-- wal_size_at_last_full_backfill · page_size · df_epoch · created_by

-- Numbered, described, idempotent. EVERY row declares its cost class and what an
-- un-backfilled row means to readers (codegraph migrations.ts discipline).
CREATE TABLE store_migration (
  version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL, description TEXT NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('ddl_only','row_churn','full_reindex')),
  backfilled INTEGER NOT NULL,
  unbackfilled_means TEXT NOT NULL   -- '' iff backfilled=1. A migration that CANNOT backfill
) STRICT;                            -- MUST make its column a monotone hint that UNIONS with
                                     -- the old signal (codegraph files.generated, migration v9).

-- Global term stats. EMPTY and unused at tier S. Maintained incrementally at M/L so a
-- coordinator can re-rank a merged cross-shard candidate set with global idf. df floor 8.
CREATE TABLE term_df (term TEXT PRIMARY KEY, df INTEGER NOT NULL) WITHOUT ROWID;
```

```sql
-- ═══════════ telemetry.db — SEPARATE FILE, per-user, derived, deletable ═══════════
-- Written by READ-ONLY store consumers. This is why it is not in index.owstore:
-- a query must never contend with the indexer for the writer lock.
CREATE TABLE query_event (
  ts INTEGER NOT NULL, corpus_id TEXT NOT NULL, surface TEXT NOT NULL,   -- cli | mcp | hook
  query_hash TEXT NOT NULL, query TEXT NOT NULL,
  plan_digest TEXT NOT NULL, scorer_version INTEGER NOT NULL,
  channels_ran TEXT NOT NULL,          -- JSON {lexical:'ran', semantic:'off', ...}
  narrowing_kind TEXT NOT NULL CHECK (narrowing_kind IN ('unrestricted','set','empty')),
  n_hits INTEGER NOT NULL, matches_before_packing INTEGER NOT NULL,
  top1 REAL, top2 REAL, ceiling REAL, normalized_top1 REAL,
  verdict_state TEXT NOT NULL, degraded_because TEXT NOT NULL DEFAULT '[]',
  returned_ids TEXT NOT NULL,
  spend_wall_ms INTEGER NOT NULL DEFAULT 0, spend_cpu_ms INTEGER NOT NULL DEFAULT 0,
  spend_tokens_in INTEGER NOT NULL DEFAULT 0, spend_calls INTEGER NOT NULL DEFAULT 0,
  spend_micros INTEGER NOT NULL DEFAULT 0,      -- D4's Spend vector and PriceBook, verbatim
  escalated INTEGER NOT NULL DEFAULT 0,         -- did the free-tier gate fail?
  producer_version TEXT NOT NULL                -- so a future bug fix never needs ledger_trust.py
) STRICT;
CREATE INDEX query_event_hash ON query_event(query_hash, ts);
CREATE INDEX query_event_bad  ON query_event(ts) WHERE verdict_state IN ('degraded','low_confidence');
```

### 3.2 Python surface

```python
# ═══ omniweave_core/store/__init__.py — THE ONLY module that calls sqlite3.connect (D1) ═══

# --- writer side: D1 fixed this at four methods. Unchanged. ---
class Store(Protocol):
    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]: ...
    def complete(self, row_id: int, gen: int, result: StepResult) -> bool: ...
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...

# --- reader side: D5 adds exactly this. Five methods, one of them the whole retrieval path. ---
class Reader(Protocol):
    def snapshot(self) -> "Snapshot": ...          # context manager: ONE BEGIN DEFERRED
    def block(self, s: "Snapshot", b: BlockId) -> Block: ...
    def hydrate(self, s: "Snapshot", ids: Sequence[BlockId]) -> Sequence[Block]: ...
    def channel(self, s: "Snapshot", spec: "ChannelSpec") -> "ChannelResult": ...
    def coverage(self, s: "Snapshot", scope: "Filters") -> "Coverage": ...   # feeds gates 4 and 8

class Snapshot(Protocol):
    """ONE `BEGIN DEFERRED` read transaction. Every channel, the hydration and the coverage
    scan run inside it, so fusion can never mix generations and verdict gate 3 is structurally
    satisfiable on the single-file path. Bounded by [store] query_txn_ms (default 2000): past
    it the txn commits, OW-S-006 is emitted and the verdict is degraded -- because a held read
    transaction PINS THE WAL, and that is exactly the futility-latch condition."""
    data_version: int           # PRAGMA data_version, captured at BEGIN
    max_gen: Mapping[int, int]  # doc_ord -> current gen visible in this snapshot
    def __enter__(self) -> "Snapshot": ...
    def __exit__(self, *e) -> None: ...

# ═══ omniweave_core/retrieve/ — STDLIB ONLY. FTS5 + SQL + ~400 lines of pure Python. ═══
# D1's gate G1 (omniweave-core resolves to exactly one distribution) is untouched: FTS5 ships
# inside CPython's sqlite3, and RRF is arithmetic.

Narrowing = Literal["unrestricted"] | frozenset[BlockId]   # TAGGED. Never a falsy check.
# jcodemunch v1.108.185: an empty candidate set read as falsy let every symbol with nonzero
# PageRank into the structural channel, so a nonsense query returned the whole repository
# "confidently" -- AND made the absence contract unreachable on both fusion paths.
# Regression fixture: tests/retrieve/test_narrowing_empty_is_not_unrestricted.py

class ChannelStatus(StrEnum):
    RAN="ran"; EMPTY="empty"; OFF="off"; UNAVAILABLE="unavailable"
# RAN and EMPTY contribute weight to the ceiling. OFF does not. UNAVAILABLE does not and
# FORCES degraded (verdict gate 2).

@dataclass(frozen=True, slots=True)
class ChannelResult:
    name: Literal["lexical","lexical_tri","identity","structural","semantic"]
    status: ChannelStatus
    ranked: tuple[tuple[BlockId, float, TextSpan | None], ...]  # ALWAYS sorted (-score, block_id)
    weight: float | None = None      # explicit (incl. 0.0) wins; else the named default; else 1.0
    unavailable_reason: str | None = None
    cost: "Spend" = ...              # D4's seven-unit physical vector, verbatim

@dataclass(frozen=True, slots=True)
class FusedHit:
    block_id: BlockId
    score: float
    span: TextSpan | None                       # from FTS5 offsets: a hit is sub-block addressed
    channel_contributions: Mapping[str, float]  # a fusion returning only a score cannot be tuned
    channel_ranks: Mapping[str, int]

DEFAULT_WEIGHTS = {"identity": 1.6, "lexical": 1.4, "lexical_tri": 0.7,
                   "semantic": 0.9, "structural": 0.5}
DEFAULT_K = 60
SCORER_VERSION = 1     # bump on ANY change to weights, k, the identity ladder, or the gates

def _weight(ch: ChannelResult, w: Mapping[str, float]) -> float:
    """Explicit weight (INCLUDING 0.0) wins; else the named default; else 1.0.
    Three-level resolution with None as the sentinel, because 0.0 is a meaningful value."""
    return ch.weight if ch.weight is not None else w.get(ch.name, 1.0)

def fuse(channels: Sequence[ChannelResult], *, k: int = DEFAULT_K,
         weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> list[FusedHit]:
    """score(b) = sum(_weight(c) / (k + rank(c, b))) over channels where b appears.
    Total-order tiebreak on block_id: tied fused scores must NEVER fall back to channel
    insertion order or to whatever order SQLite handed rows back."""

def ceiling(channels: Sequence[ChannelResult], *, k: int = DEFAULT_K,
            weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> float:
    """sum(_weight(c) for c in channels if c.status in (RAN, EMPTY)) / (k + 1).
    ⚠ MUST resolve weights through the SAME _weight() as fuse(). A ceiling that drifts from
    the scorer silently rescales every confidence. Pinned by test_perfect_consensus_equals_
    ceiling(), which fuses a rank-1-everywhere set and asserts equality. Weights are NOT
    normalised to sum to 1, so the ceiling DEPENDS ON WHICH CHANNELS ACTUALLY RAN.
    NEVER hardcode 1/(k+1)."""

# ═══ the planner: pure. No clock, no network, no store read. ═══
@dataclass(frozen=True, slots=True)
class Query:
    text: str
    filters: "Filters" = ...
    mode: Literal["auto","exhaustive","lexical","identity","structural","semantic"] = "auto"
    k: int = 20
    corpora: tuple[str, ...] = ()
    budget: "QueryBudget" = ...      # wall_ms=5000, micros=0 (FREE by default), calls=0
    replay: str | None = None        # a recorded plan_digest: replay a query byte-for-byte

@dataclass(frozen=True, slots=True)
class Filters:                       # FILTERS NARROW. CHANNELS SCORE WITHIN THE NARROWED SET.
    doc: tuple[str, ...] = ()        # doc_key prefix | cite prefix | uri glob
    pages: tuple[range, ...] = ()
    kinds: frozenset[Kind] = frozenset()
    layers: frozenset[Layer] = frozenset({Layer.BODY})
    trust_at_least: Trust | None = None
    quote_at_least: Quote | None = None
    restriction_mask: int = 0        # D3: exclude items carrying these bits
    since_gen: int | None = None

@dataclass(frozen=True, slots=True)
class Stage:
    channel: str
    cost_class: Literal["FREE","LOCAL_COMPUTE","BILLED_API"]
    over_fetch: int                  # 5*k lexical; ceil(k/selectivity)*1.5 semantic, cap 64*k

@dataclass(frozen=True, slots=True)
class Plan:
    narrowing: "NarrowSpec"
    stages: tuple[Stage, ...]        # grouped and ordered by cost_class
    gate: "GateSpec"                 # re-tested BETWEEN cost groups (D4's demand plan)
    fusion: "FusionSpec"
    plan_digest: str                 # sha256_canonical(...) -- in every query_event row

def compile_plan(q: Query, caps: "StoreCaps", policy: "RetrievePolicy") -> Plan: ...
    # PURE. A property test shuffles the channel list 100x and asserts an identical Plan.

GATE_DEFAULTS = GateSpec(min_hits_ratio=1.0,       # >= k hits
                         min_normalized_top1=0.35, # jcodemunch regret: low confidence 0.30
                         min_gap_normalized=0.05,  # jcodemunch regret: ambiguous gap 0.05
                         min_channels_ran=2)

# ═══ the verdict: four states, ten gates, ONE citability rule ═══
class VerdictState(StrEnum):
    OK="ok"; LOW_CONFIDENCE="low_confidence"; ABSENT="absent"; DEGRADED="degraded"

@dataclass(frozen=True, slots=True)
class DegradeCause:
    gate: str                              # 'coverage_incomplete'
    diag_codes: tuple[str, ...]            # ('OW_NEEDS_OCR','OW_ENCRYPTED')  -- D2's registry
    where: tuple[tuple[int, int, int], ...]  # (doc_ord, page_lo, page_hi)
    note: str                              # ends with the exact command that clears it (D1)

@dataclass(frozen=True, slots=True)
class Verdict:
    state: VerdictState
    degraded_because: tuple[DegradeCause, ...]
    scanned: Mapping[str, int]                     # {blocks, documents, pages}
    best_score: float | None; score_ceiling: float; normalized_top1: float | None
    scorer_version: int
    channels: Mapping[str, ChannelStatus]
    freshness: Literal["fresh","stale","unknown","not_tracked"]
    coverage: "Coverage"        # documents_in_scope, indexed, failed, skipped, pages_not_ok
    snapshot: Mapping[str, Any] # {data_version, corpus_id, shard_ordinals, max_gen}
    federated: bool
    fusion_kind: Literal["exact","global-df-rerank","normalized-per-corpus"]
    did_you_mean: tuple[str, ...]
    spend: "Spend"              # D4's vector; priced by the same PriceBook
    def citable_as_absence(self) -> bool:
        return self.state is VerdictState.ABSENT
    # THE ONE RULE. Every new hazard forces DEGRADED; nothing ever adds a second rule.

def build_verdict(**kw) -> Verdict: ...   # the ONLY constructor. Ten gates, in precedence order.
```

### 3.3 Config

```toml
# omniweave.toml — additive to D1's [store] block
[store]
backend = "sqlite"                 # sqlite (shipped) | postgres (T3, later)
path    = ".omniweave/index.owstore"
page_size = 8192                   # CREATE-time only
query_txn_ms = 2000                # snapshot bound; past it -> OW-S-006 + degraded
wal_valve_mb = 0                   # 0 = min(2048, max(256, db_size/4)) -- codegraph's formula
wal_heal_mb  = 64                  # at-open heal for a SIGKILL leftover (25.6 GB observed)
bulk_index_windows = true          # drop+rebuild secondary indexes for bulk load, with yields

[store.lex]
bm25 = { title = 8.0, text = 1.0 }
trigram = "auto"                   # auto (on below 5M blocks) | true | false
over_fetch = 5                     # 5x k before re-rank (codegraph)

[store.vector]
enabled = false                    # OFF BY DEFAULT. Turning it on names a driver.
space   = "e5-small@a1b2c3/cos/256i8"
mode    = "stored"                 # stored | recompute -- stamped, validated on BOTH paths
backend = "usearch"                # flat (stdlib, <=50k vectors) | usearch (omniweave-graph)
dtype   = "i8"
reduction = "pca:256"

[store.shard]
count = 1                          # fixed at corpus creation; resharding is a copy
target_blocks = 32_000_000

[retrieve]
k = 20
weights = { identity = 1.6, lexical = 1.4, lexical_tri = 0.7, semantic = 0.9, structural = 0.5 }
smoothing = 60
gate = { min_normalized_top1 = 0.35, min_gap_normalized = 0.05, min_channels_ran = 2 }
max_hops = 3
max_frontier = 512
max_visited = 4096
max_query_terms = 64
# Per-key validation with per-key fallback, never all-or-nothing, and the read can never raise.
```

### 3.4 The query DSL and the narrowing

```
kind:table page:12-40 doc:d7 layer:body trust:>=2 quote:>=normalized "quarterly revenue"

  -> Filters(kinds={TABLE}, pages=(range(12,41),), doc=("d7",), layers={BODY},
             trust_at_least=EXTRACTED, quote_at_least=NORMALIZED)
     text = "quarterly revenue"

Unknown prefixes pass through as plain text, so `TODO:` returns results rather than a parse
error (codegraph's rule). Values are validated against the D2 enums. FILTERS NARROW; CHANNELS
SCORE WITHIN THE NARROWED SET.

Narrowing is materialised as a TEMP table inside the read transaction, never as a Python set --
a frozenset of 10M ids is 400 MB and a JOIN is free:

  CREATE TEMP TABLE tmp_narrow(block_id INTEGER PRIMARY KEY) WITHOUT ROWID;
  INSERT INTO tmp_narrow
    SELECT b.block_id FROM block b JOIN doc d USING (doc_ord)
     WHERE b.state = 0 AND b.gen = d.gen AND b.layer IN (...) AND b.kind IN (...)
       AND (b.restriction_bits & :mask) = 0 AND b.trust >= :trust;

and narrowing_kind ∈ {unrestricted, set, empty} is carried EXPLICITLY, so "restrict to nothing"
can never be read as "no restriction".
```

### 3.5 Package layout and the error register

```
packages/omniweave-core/src/omniweave_core/
├── store/
│   ├── __init__.py        connect(), connect_readonly() -- THE ONLY sqlite3.connect (D1 lint)
│   ├── pragmas.py         _INIT_PRAGMAS (per file) / _PRAGMAS (per conn); busy_timeout FIRST
│   ├── walvalve.py        the eight properties, ported from codegraph/src/db/wal-valve.ts
│   ├── bulk.py            index windows; DDL read from schema/, a miss is a HARD RAISE
│   ├── migrate.py         numbered · described · idempotent · cost-classed · backfill-honest
│   ├── dialect.py         ~60 lines. FOUR named divergences. Two implementations on the roadmap.
│   ├── shard.py           blake2b(doc_key) % N; block_id = (shard << 52) | seq
│   └── schema/            0001_owdoc.sql (D2's) · 0002_index.sql · 0003_graph.sql
├── retrieve/
│   ├── plan.py            compile_plan() -- PURE
│   ├── channels/          lexical.py · trigram.py · identity.py · structural.py · semantic.py
│   ├── fuse.py            fuse() + ceiling() + _weight(). Reimplemented from notes, NOT vendored.
│   ├── sanitize.py        § ¶ soft-hyphen · Fig./Table/§ lifted to identity · FTS5 specials
│   ├── verdict.py         four states · ten gates · SCORER_VERSION · citable_as_absence()
│   └── telemetry.py       query_event writer against telemetry.db
packages/omniweave-graph/src/omniweave_graph/
└── vector/                usearch backend · pca fit/apply · i8 quantise · space validation
tools/
├── gate_query_plan.py     EXPLAIN QUERY PLAN over 11 hot queries; a table scan FAILS the build
├── gate_incremental.py    incremental-then-full on a fixture corpus; diffs EVERY table
└── tune_weights.py        offline nDCG@10 over the golden set; emits a SUGGESTED patch, never applies
fixtures/store/
├── golden-queries.jsonl   120 queries x graded judgments over a 12-document licence-clean corpus
├── ghost-fts.owstore      an .owstore with deliberately orphaned block_fts rows
├── wal-pinned/            a reader pinning the WAL, to exercise the futility latch
├── nonsense-query/        the jcodemunch empty-candidate-set regression
└── shard-4/               a 4-shard corpus with cross-shard kedges, for federation tests

codes.toml (append-only, D1's register)
  OW-S-001  STORE_LOCKED                  the holder is named; try `ow index --wait 60`
  OW-S-002  WAL_OVERSIZE_HEALED           informational; names the reclaimed bytes
  OW-S-003  SCHEMA_AHEAD                  the store was written by a newer omniweave
  OW-S-004  MIGRATION_REQUIRED            names `ow store migrate` and the cost class
  OW-S-005  FTS5_UNAVAILABLE              names `pip install omniweave[sqlite]` (D1's remedy)
  OW-S-006  SNAPSHOT_EXPIRED              query_txn_ms exceeded; the verdict is degraded
  OW-S-007  VECTOR_SPACE_MISMATCH         prints BOTH tuples, field by field
  OW-S-009  SHARD_UNREACHABLE             names the shard and the corpus
  OW-S-010  FTS_GHOSTS                    names the drift count and `ow store fts-gc`
  OW-S-011  UNEXPLAINED_LOSS              names the unit; `--allow-unexplained-loss` is the override
  OW-S-012  QUERY_BUDGET_EXHAUSTED
  OW-S-013  OVERFETCH_EXHAUSTED           the filter is too selective for the ANN top-k
  OW-S-014  CROSS_SHARD_FUSION_APPROXIMATE
```

---

## 4. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| S1 | There is exactly one representation of a block. No table stores block text a second time. | `content='block'` external-content FTS5 on both tables; a CI grep bans a column named `text`/`body`/`html` outside `block`; `ow doctor` compares `block_fts` count against live `block` count |
| S2 | `sqlite3.connect` appears in exactly one module. | D1's lint rule, inherited; `tools/semgrep/omniweave.yaml` |
| S3 | `busy_timeout` is set before any pragma that touches the file. | `pragmas.py` emits an ordered tuple; a unit test asserts index 0; a contended-open test asserts no `SQLITE_BUSY` (codegraph #238) |
| S4 | Every retrieval call sees exactly one snapshot. | `Reader.channel()` requires a `Snapshot`; no store method opens its own connection; a test runs a query while a writer commits between every channel and asserts identical results |
| S5 | A reader never takes the write lock on `index.owstore`. | serve and CLI-query use D1's `connect_readonly` ladder; a test opens the store read-write in one process and asserts a concurrent query succeeds and writes zero bytes to `index.owstore` |
| S6 | `fuse()` and `ceiling()` resolve weights identically. | Both call `_weight()`; `test_perfect_consensus_equals_ceiling` asserts `top.score == ceiling(...)`; a mutation test that changes one and not the other must fail the suite |
| S7 | "Restrict to nothing" is never read as "no restriction". | `Narrowing` is tagged; `narrowing_kind` is recorded per query; the `nonsense-query/` fixture asserts 0 hits and `absent`, never the corpus ranked by centrality |
| S8 | Every channel is totally ordered on `(-score, block_id)`. | `ChannelResult.__post_init__` asserts sortedness under `-O0`; a property test `VACUUM`s the store and asserts an identical ranking |
| S9 | An empty result is `absent` only after ten gates. | `build_verdict()` is the only constructor of `Verdict`; a table-driven test enumerates all ten and asserts each forces `degraded`; `citable_as_absence()` is the single predicate |
| S10 | A vector never answers a query from a different space. | `vector_space` compared field-by-field against the embed driver's `HELLO_ACK`; mismatch is `OW-S-007` naming both tuples; a test mutates `model_rev` and asserts refusal on the SEARCH path, not just the build path |
| S11 | Derived rows carry ownership, driver and restriction. | `origin_operator`, `origin_driver`, `driver_schema_v`, `restriction_bits` `NOT NULL` on `kedge`; CI greps eviction SQL for a missing `origin_operator =` predicate |
| S12 | Every derived row's identity is a schema constraint. | `kedge_identity` UNIQUE with `IFNULL` sentinels; the installing migration `GROUP BY`s the identical expression; a test inserts the same edge twice and asserts one row |
| S13 | Every index earns its keep. | `tools/gate_query_plan.py` runs `EXPLAIN QUERY PLAN` over eleven hot queries and fails on `SCAN`; a second check fails if any declared index is unused by all eleven |
| S14 | Incremental converges with a full rebuild. | `tools/gate_incremental.py` runs incremental-then-full on the fixture corpus and diffs every table. codegraph measured **4.3% of distinct edges wrong** without the equivalent pass |
| S15 | A migration is honest about backfill. | `store_migration.cost_class` and `unbackfilled_means` `NOT NULL` in a `STRICT` table; a column that cannot be backfilled must be a monotone hint that unions with the old signal |
| S16 | A bulk-index window is crash-safe and cannot silently skip a rebuild. | DDL read from `schema/` by index name, a miss raises; the next open re-applies `CREATE INDEX IF NOT EXISTS`; a test SIGKILLs mid-window and asserts the index exists after reopen |
| S17 | No synchronous store stage exceeds half the watchdog. | Cooperative yield between each `CREATE INDEX` and every 1,000 rows, yield at the *top* of the loop body; a CI timing assertion (codegraph: 79 s of builds against a 60 s watchdog) |
| S18 | The index is never a committed artifact. | shipped `.gitignore` covers `*.owstore*`, `cas/`, `vec/`, `telemetry.db`; `ow index verify --manifest` is the CI gate; a repo test fails if an `.owstore` is tracked |
| S19 | A weight or threshold change bumps `SCORER_VERSION`. | CI diffs `DEFAULT_WEIGHTS`/`GATE_DEFAULTS`/the identity ladder against the previous tag and fails if `SCORER_VERSION` did not move |
| S20 | A post-filtered ANN search never silently loses recall. | Over-fetch by measured selectivity, one retry at the cap, then `OW-S-013` + `degraded`; a test at 0.1% selectivity asserts the degrade rather than a short list |
| S21 | A query never blocks on the indexer. | Reader connections are `mode=ro`; the only writes a query performs are to `telemetry.db`; a soak test runs 1,000 queries against a store under continuous bulk index and asserts zero `SQLITE_BUSY` |

---

## 5. Build order, and what it costs

Every phase ships a command a real user runs.

**P1 — the store and the lexical channel (≈4 weeks, 2 people).**
`store/` (connect, pragmas, migrations, WAL valve, heal-on-open, bulk windows, `Dialect`),
`0002_index.sql`, `block_fts` + weights + triggers + `fts_gc`, the identity ladder, sanitization,
`Snapshot`, `Filters`, `ow index` and `ow query`, a **two-channel** `fuse()`+`ceiling()`, and a
**three-gate** verdict (2, 4, 10).
*Deliverable: `ow index ~/docs && ow query "termination for convenience"` returns cited blocks with a
verdict on a laptop.* Invariants S1–S8, S13, S16, S17, S21.

**P2 — structural, the planner, the full verdict (≈3 weeks).**
Containment + `rel` + `kedge` traversal with the frontier caps, `edge_closure` for the three
tree-shaped relations, `compile_plan()`, the free-tier gate, all ten verdict gates over
`diag`/`work`/`doc`/`page`, `query_event`.
*Deliverable: `absent` becomes a trustworthy answer, and the degrade line names the pages that failed
OCR.* S9, S11, S12.

**P3 — incremental (≈3 weeks).**
Racily-clean stat rule, tier-scoped eviction on `origin_operator`, `refdelta`, `unresolved_ref` with
the resolution pass and the partial retry index, the per-unit attribution guard, `index.lock.json`,
`ow index verify`, watcher integration with the three debounce tiers.
*Deliverable: the index is never stale and never re-does work.* S14, S15, S18.

**P4 — vectors (≈4 weeks).**
`vector_space` + `block_vec` + `vec_payload`, the `embed/1` integration through D3's subproc host, PCA
fit + int8 quantization, `flat` and `usearch` backends, selectivity over-fetch, the semantic stage in
the planner.
*Deliverable: thematic queries work, and turning vectors on costs 256 B/block.* S10, S19, S20.

**P5 — scale.**
Sharding (`shard.py`, composite `block_id`, `catalog.owstore`, `term_df`), the scatter-gather
coordinator, federation across corpora, and the Postgres `Dialect`. Not scoped in weeks; scoped by the
first customer who has 50M blocks.

**≈14 engineer-weeks to P4 for two people**, plus ~1.5 weeks of Windows parity (named-pipe read-only,
`mode=ro` URI quirks, `os.path.normcase` in the salt, the `\\?\` prefix).

**Runtime and operational cost, stated.**
- Warm single-channel query on 1M blocks: low single-digit ms. Four free channels + fusion + hydration
  of 20 blocks: target < 60 ms, which fits G10's 250 ms once interpreter start is paid.
- `block_fts` costs ~35–45% of block-text size on disk; `block_tri` costs ~2.6× `block_fts`.
- Vectors at 768→256 int8: 256 B/block, so 10M blocks is 2.5 GB outside the store.
- Store at rest: plan `db_size × 1.2`; during bulk index plan `db_size + 8 GB` for the WAL (codegraph's
  measured envelope).
- Dependency weight added: **zero** in `omniweave-core` (D1's G1 gate untouched — FTS5 ships inside
  CPython's SQLite, the fusion is arithmetic), and **~4 MB** (`usearch`) inside `omniweave-graph`'s
  existing 150 MB ceiling. One line in `tools/weights.toml`. No twelfth distribution.
- Operational burden: one more sidecar file to explain (`telemetry.db`), one WAL valve to tune, one
  golden query set to maintain, and the `SCORER_VERSION` discipline.

---

## 6. Tradeoffs

1. **One writer.** The whole concurrency story is "readers never block, one writer, everything else
   degrades". It is correct for an embedded index and it means a second ingest process gains nothing.
   Multi-writer ingest is a Postgres property, not a SQLite property, and I am not pretending otherwise.
2. **The snapshot bound is a real cliff.** A 2-second read transaction is generous, and a query that
   exceeds it degrades rather than completing consistently. I chose degrading over pinning the WAL
   because a pinned WAL takes the whole system down and a degraded query takes one answer down.
3. **`block_tri` costs 2.6× the primary lexical index.** It buys CJK, `ISO27001`, and `§12.4(b)`. On a
   pure-English corpus it is dead weight, which is why it is `auto`.
4. **Cross-shard BM25 is approximate and the verdict says so.** A global-df re-rank over a merged
   candidate set is close; a per-corpus normalized merge is not. The alternative — a globally consistent
   distributed inverted index — is a different product.
5. **Rejecting LEANN's default mode costs disk.** At 60M+ vectors LEANN wins by ~30×. I pay that in disk
   to buy a query path with no model call, and I ship `recompute` as a validated mode so the trade is
   reversible per corpus rather than per framework.
6. **No PageRank, no learned ranker, no CBO.** The ranking is five channels and five constants. It will
   be beaten on some corpus by something smarter, and the tuner exists to find out — but a hand-tunable
   ranking with `channel_contributions` on every hit is debuggable, and a learned one is not until you
   have the golden set that P1 does not have yet.
7. **The `edge_closure` allowlist is a policy, not a mechanism.** Someone will want it for a fourth
   relation and be refused. That refusal is the design.
8. **Telemetry in a second file** means a store copied to another machine loses its tuning data, and
   `ow query --explain` on a fresh checkout has no history. Correct trade: query latency and lock
   contention beat portable telemetry.
9. **The two-token amendment to D2's `block_fts`.** It is a change to settled law, however small, and I
   would rather flag it than route around it with a field-repetition hack that breaks the
   one-representation invariant.
10. **A ten-gate verdict means many queries report `degraded` on a real corpus.** That is the point and
    it is also a product cost: a user who does not read the degrade line will think the tool is broken.

---

## 7. Failure modes, named honestly

1. **A single page with 4,000,000 cells.** D2's `DocSink.end_page()` commits one transaction per page,
   and D2's own risks section already says "a sub-page commit boundary may be forced later". At 4M cell
   blocks that transaction is on the order of a gigabyte of WAL frames, and **the valve cannot help
   mid-transaction** — its release condition is a full backfill and there is no commit boundary to park
   at. The store's honest behaviour today: the write succeeds on a machine with the disk for it and
   fails with `SQLITE_FULL` on one without. **This is the input that breaks the durability story; it is
   inherited rather than introduced, and the fix is a sub-page commit boundary D2 must own.**
2. **A read transaction held under a watcher storm.** A slow hydration (a 24 MB block, a cold page cache)
   plus a bulk re-index means the reader pins the WAL, the valve's 20 backfill passes all fail, the
   futility latch disarms writer parking, and the WAL grows unbounded until the reader exits.
   `query_txn_ms` is a bound, not a proof — a reader that *dies* holding a transaction still pins until
   its connection is reaped.
3. **A corpus that is one 200 MB block.** Some PDFs extract as a single text run. BM25 length
   normalization means it never ranks, the trigram index balloons, and its vector is meaningless.
   Retrieval still returns a usable `TextSpan` from FTS5 offsets, so the *citation* survives, but ranking
   is effectively broken for that document and nothing in the store detects it. Mitigation is an
   `ow doctor` warning above a p99 `block_text_bytes` threshold: a report, not a fix.
4. **Global `term_df` drift at tier M.** Maintained incrementally; a crashed ingest can leave it behind
   the shards, and a stale df biases cross-shard re-ranking silently. `df_epoch` in `store_meta` plus a
   periodic recount is the mitigation, and the recount is a full scan.
5. **FTS5 ghosts.** External content plus a trigger path that misses one case equals dead `block_id`s
   returned forever. `fts_gc` and the `ow doctor` count check catch it *after* it happens, not before.
6. **The free-tier gate is a recall risk by construction.** A query whose lexical top-1 is a
   near-duplicate boilerplate block can clear `normalized_top1 >= 0.35` and `gap >= 0.05` while the real
   answer needed the semantic channel. `query_event.escalated` plus the offline tuner measures how often
   that happens; it does not prevent it. `mode="exhaustive"` is the escape hatch and a user has to know
   to type it.
7. **`unresolved_ref` retry cost.** After every ingest the resolution pass queries the failed set for
   every `name_tail` in `refdelta`. On an academic corpus citing uningested literature that partial index
   can be millions of rows and the pass is minutes. Bounded by `MAX_RESOLUTION_MS` and a keyset cursor;
   when the budget expires the remainder is deferred, which means "the corpus grew and now this resolves"
   can take several runs.
8. **`PRAGMA optimize` and FTS5 `'merge'` are minutes of synchronous IO** on a large index. Both run
   off-thread on a separate connection and both can be starved indefinitely by a busy writer, at which
   point query plans degrade with no visible symptom until someone reads `ow doctor`.
9. **The identity ladder over-fires on numerically-titled corpora.** A corpus where every section is
   titled `1.1`, `1.2` produces enormous `term_vocab` fanout on a query containing a number. A stoplist
   and `MAX_IDENTITY_CANDIDATES = 256` bound it; both are policy that will be wrong somewhere.
10. **An index built with vectors on, then queried after the embed driver is uninstalled**, yields
    `channel_unavailable` and therefore `degraded` on every query. Correct, and it will read as "the tool
    is broken" to a user who does not read the degrade line.
11. **Adversarial input: a 4,000-term query.** FTS5 with 4,000 OR'd prefix terms is a full posting scan.
    Capped at `MAX_QUERY_TERMS = 64` after sanitization, with the truncation reported — a cap that will
    occasionally clip a legitimate paste of the paragraph the user wanted to find.
12. **An S→M migration under a live watcher.** Copying whole documents into new shards while the watcher
    is enqueuing work rows is the one operation with no clean answer; `ow store reshard` refuses unless
    the watcher is stopped and the `work` table is drained, which is downtime.

---

## 8. Why I reject the alternatives

- **A pluggable vector-store abstraction (graphrag's shape).** graphrag ships LanceDB, Azure AI Search
  and CosmosDB behind one interface, and the cost shows: `IndexSchema`, a per-store id-remap, and an
  embedding path that is **non-incremental** — a chunker or embedder config change re-embeds the whole
  corpus because there is no ownership record to scope the work (`mine-runtime.md §2.7`). Three
  implementations of a store is three ways for the metadata contract to be almost right. I ship one
  vector *layout* (a flat mmapped array plus a `vector_space` row) and two ANN backends behind ~40 lines,
  because the ANN library is genuinely swappable and the storage is not.
- **graphify's "deliberate no-vectors", as the brief frames it.** **That framing does not survive the
  source.** `graphify/BENCHMARKS.md:87` states the fairness rule "One shared local embedder where the
  system allows it: BGE-m3 (1024-d, multilingual)"; the headline configuration at `:102` is called
  `graph-expand`; `semantically_similar_to` is a first-class relation. graphify's zero-LLM claim is about
  **graph construction**, not retrieval. The real, checkable lesson is a better one: graphify ties dense
  RAG at 0.497 recall@10 on LOCOMO and 76% on LongMemEval-S at **zero LLM build cost**, which is exactly
  why my planner runs the free channels first and `[store.vector] enabled` defaults to `false`. What I do
  reject is graphify's *storage*: NetworkX plus a committed `graph.json`, capped by its own authors at
  50 MB / 100k nodes.
- **A real graph engine (Neo4j, Kùzu, SurrealDB, or an in-memory adjacency).** It adds a service or a
  second store to keep in sync with the `.owstore`, and D2's ruling is explicit that a model plus a sync
  layer is the failure it was designed to avoid ("one store, never a model plus a sync layer"). The
  workload does not justify it: codegraph does 6.4M relationships in SQLite on a 2-core VPS in under 12
  minutes, and our traversals are depth ≤ 3 with a visited cap. A graph engine would buy fast unbounded
  traversal, which is precisely the query I refuse to offer because its cost is unbounded.
- **A recursive CTE for multi-hop.** SQLite's `WITH RECURSIVE` has no built-in visited set, so a cyclic
  or dense relation blows up with no cap and no cancel point. The frontier BFS is more code and it is
  bounded, cancellable and instrumented.
- **jcodemunch's code, in any form.** Its Dual-Use Licence v1.1 §3 bars use "within a for-profit
  organization to support revenue-generating activities" and §(c) bars publishing any derivative to a
  package registry. The fusion function, the ceiling, the identity ladder, the absence contract and the
  regret thresholds here are **reimplemented from the design descriptions in `mine-graph.md §4`**, which
  is why that section was written as a specification rather than a pointer.
- **LEANN's linear hybrid blend** (`api.py:1453-1468`): a raw `bm25()` in the tens added to a cosine,
  ties broken on dict insertion order, and a single-channel hit scored on the same additive scale as a
  consensus hit. Three independent defects in six lines; RRF fixes all three.
- **LEANN's selective recomputation as the default.** Engaged in full at §2.8: legal under D1/D3, and
  rejected for v1 on arithmetic — 64–200 forward passes per query to save 12 GB, against a 250 ms
  warm-query budget, when PCA-256 + int8 gets 256 B/block for free at query time. Kept as a stamped,
  both-paths-validated mode for the corpora where LEANN's own numbers dominate.
- **A checkpoint file, a JSON state bag, or a step counter for index progress.** The `work` table's
  pending set is the checkpoint (D6's ruling and codegraph's soundness property). DataFlow's
  `cache_step_{N}` has eight documented failure modes.
- **Committing the index, with or without graphify's merge driver.** §2.12: the merge is `nx.compose`,
  it ignores the base so deletions resurrect, the caps are 50 MB / 100k nodes, and D2 forbids exporting
  `block_id` at all. `index.lock.json` gets the freshness gate without the gigabyte.
- **A cost-based query optimizer, or a learned ranker at v1.** One plan shape, five channels, and no
  labelled data on day one. `tools/tune_weights.py` emits a **suggested-never-applied** patch against the
  golden set — jcodemunch's discipline — and a weight change lands only when it beats the incumbent on
  nDCG@10 by ≥ 2 points over ≥ 50 queries and bumps `SCORER_VERSION`.
- **Parquet or a columnar sidecar as the index.** D2 already priced it: 27% smaller, **~2,000× slower to
  point-read** (42.8 ms vs 20 µs), and immutable — graphrag's `_copy_previous_output` copies a 50 GB
  index to add one document. Retrieval is a point-read workload. `ow export parquet` exists for analytics
  and is not the index.
- **Postgres from day one.** It solves multi-writer and cross-shard idf, and it costs every user a
  service before they have a corpus. D1 already ruled SQLite the only shipped backend; the `Dialect` shim
  is what makes the upgrade a configuration change rather than a rewrite.
- **A `Backend`/ORM abstraction over the store.** An abstraction with one implementation, wrapping a
  surface (SQL) that is already portable, at the cost of hiding `EXPLAIN QUERY PLAN` — which is a CI gate
  here. Four named dialect divergences beat a leaky object model.

---

## 9. Consequences for other decisions

- **D2** must accept the two-token `block_fts` amendment (§1), and it inherits answers to two of its open
  questions: embedding rows key on **`content_digest` for the payload and `block_id` for the join**
  (§2.8), and `block_id` becomes a **12-bit shard ordinal in the high bits plus a 52-bit per-shard
  sequence**, with shard 0 for a single-file store so the S-tier path is byte-identical to today (§2.10).
- **D6** owns `work`; D5 owns `Snapshot`. The rule between them: the indexer is the only writer and holds
  the `store.write` scoped lock; every other process opens read-only. D6's `origin_operator` eviction
  discipline extends to `kedge`, `term_vocab`, `block_vec` and `unresolved_ref`.
- **D7** owns the `kedge.relation` vocabulary, the entity/community model and the extraction; it does
  **not** own the storage, the identity index, the traversal caps or the `edge_closure` allowlist. D7 must
  key on `block_id`, must set `origin_operator`/`origin_driver`/`restriction_bits`, and must write
  `unresolved_ref` rows rather than log lines for references it cannot resolve.
- **D9** consumes `FusedHit` + `Verdict`. `degraded_because` is designed to be rendered verbatim;
  codegraph's ~24,000-char response ceiling and its reserve-then-render budgeting are D9's; and
  `FusedHit.span` exists so a hit can be packed sub-block rather than whole.
- **D10** gets `query_event`, `SCORER_VERSION`, `fixtures/store/golden-queries.jsonl`, and the
  `route_scoreboard`-shaped discipline that `UNKNOWN` is the zero value.
- **D4 is untouched.** Query-time work that is not persisted and is bounded by the query's own
  `QueryBudget` does **not** create a `work` row or a `route_decision`; it is charged against the same
  `Spend` vector and `PriceBook` and recorded in `query_event`. Anything a query *persists* into the store
  — materializing a missing embedding, resolving an `unresolved_ref` — goes through `work` +
  `route_decision` like everything else. **`query_event` is a query ledger, not a second decision log.**
- **D1** gains one dependency line: `omniweave-graph` += `usearch` (~4 MB, Apache-2.0), inside its
  existing 150 MB ceiling. No new distribution, no change to the extra→sibling rule, and
  `omniweave-core`'s G1 zero-dependency gate untouched.

---

## 10. Open questions

- **Is `bm25(title 8.0, text 1.0)` right, or is the whole column-weight idea wrong for prose?** Settled by
  nDCG@10 over `golden-queries.jsonl` with the title weight swept across `{1, 2, 4, 8, 20}`. If the curve
  is flat, the D2 amendment loses its justification and I should withdraw it.
- **Does `refdelta` actually stay empty on real edits?** codegraph's `definitionDelta` is empty for
  body-only code edits, but a document edit that renumbers one heading changes every downstream
  cross-reference key. Settled by instrumenting `|refdelta|` over 200 real edits on a 5,000-page corpus;
  if it is routinely large, the re-bind pass is not incremental and needs its own budget.
- **What is the real block-count-per-page envelope, and therefore every storage number here?** D2 filed
  the same question. My 5M/500M tier boundaries scale directly off 60–120 blocks/page.
- **Does the free-tier gate cost measurable recall?** Settled by running `mode="exhaustive"` in shadow on
  1% of queries and comparing nDCG@10 against the gated plan. If the gap exceeds 3 points, the thresholds
  move or the gate goes away.
- **Is a 12-bit shard ordinal enough, and can `block_id` allocation really be decided before P1 ships
  FKs?** It must be, because every FK in D2 points at `block_id`. 4,096 × 4.5×10¹⁵ is not a real ceiling,
  but the choice is irreversible and deserves a week of scrutiny before P1's first migration.
- **Does the `usearch` dependency survive a licence and supply-chain audit?** Apache-2.0 and not on D1's
  denylist, but gate G3 scans the resolved graph, the import graph *and* unpacked artifacts, and `usearch`
  ships prebuilt binaries. Settled by running G3 against it before P4 starts, with `flat` plus a refusal
  above 50k vectors as the pre-committed fallback.
- **Does PCA-256 + int8 hold retrieval quality?** The 6–12× storage claim is arithmetic; the quality claim
  is not. Settled by nDCG@10 on the golden set at `{f32-768, f16-768, i8-256}` before P4 ships the default.
