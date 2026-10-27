# D5-store — Storage, indexing, retrieval and query planning

## Decision

SQLite is the **published read interface and the swappable write implementation**: one
`.owstore` per corpus holding D2's model, D5's index layer, and D3/D4/D6's operational tables, with
exactly two derived, separately-deletable SQLite sidecars (`*.vec.owstore` for vectors,
`events.owstore` for the query ledger) so that no query process ever needs a write handle on the
index. Retrieval is **five channels — `identity · exact · lexical · structural · semantic` — fused
by weighted RRF at one key, `block_id`**, with a computed `ceiling()` that shares one weight
function with `fuse()`; the **Chunk** exists as a first-class stored object because it is the
embedding unit, the `derive/1` unit and the packing unit, but it is *not* the fusion key — the
semantic channel projects each chunk's rank onto its member blocks. The planner is a pure
`plan(Query, IndexCaps, RetrievalPolicy) -> QueryPlan` whose **narrowing strategy is a closed
three-way choice decided by an exact `LIMIT PREFILTER_MAX+1` probe** (no histograms, no independence
assumption, no cost-based optimiser) and whose channel selection, weights and short-circuits are
authored in **D4's rule grammar verbatim** in `retrieval.toml`. One writer per store; one
`BEGIN DEFERRED` snapshot per query, hard-capped at 5 s because a pinned reader is a WAL-valve
safety parameter; codegraph's eight-property WAL valve and bulk-index windows ported whole with a
`bulk_window` marker that refuses to serve after a crash. Embeddings are an operator (D3's `embed/1`
Driver) and the ANN index is a **Backend** behind an `omniweave.backends` entry point; the shipped
stdlib backend is a binary-signature segment scan that **refuses above 250,000 chunks** — a ceiling
I measured, not estimated. Vectors key on `chunk_digest`, chunks key positionally on
`(doc_ord, gen, chunker_id, ord)`, so a re-parse that changes provenance but not text costs zero
embeddings. The graph is **one block→block `edge` table** with schema-enforced identity and a
bounded frontier BFS — no CSR, no materialised closure, no graph engine. `block_id` is
`(minting_shard_ord << 48) | sequence` with shard 0 for every single-store corpus, so a laptop's ids
are 1,2,3… and a fabric never rewrites an FK. A zero result is `absent` only after twelve gates, one
of which is an indexed join against D2's `diag`. The index is a cache, is `.gitignore`d, and the one
committed artefact is `omniweave.index.lock`.

## Spec

**Containers.** `.omniweave/index.owstore` is the store: D2's tables, D5's index layer, D3's
`driver_card_cache`/`driver_observation`/`resolution_report`, D4's seven `route_*` tables and the
`route_scoreboard` view, and D6's `work`. D1's `[store] path` key is kept; its default value becomes
`.omniweave/index.owstore` (D1's example said `index.db`; D2 named the format `.owstore`). Two
sidecars are derived and separately deletable: `index.vec.owstore`, ATTACHed as `vec`, and
`events.owstore`. `rm -rf .omniweave` is a supported, documented, lossless operation and every rule
below is subordinate to keeping that sentence true.

Both sidecars are SQLite, not raw files. A flat mmap array would add a second on-disk format with
its own torn-write, truncation and portability semantics for a benefit the segment-BLOB layout
already delivers. The `vec` sidecar exists because 3 KB/chunk of float32 must not churn the writer's
B-tree, WAL, backup and `VACUUM`; `events.owstore` exists because a query process opens the index
`mode=ro` and **cannot** write it at all, and a read-write telemetry connection would take the index
write lock on every query. **No transaction ever spans `main` and `vec`** — atomic commit across
attached databases does not hold in WAL mode — which is affordable because a vector row is only ever
surfaced through an inner join to a live chunk in the *main* snapshot, so a stale vector is
invisible, never wrong.

**The retrieval unit.** Three of five channels are natively block-shaped, `block_id` is D2's only FK
target and the citation unit, and `restriction_bits`, `matches_before_packing` and `withheld` are
per-block concepts. So fusion is at `block_id`. The Chunk is nevertheless a stored object with a
`chunker_id`, a positional identity and a `chunk_digest`, because D3 makes chunks a `derive/1`
output and an embedder cannot be handed 4,000,000 spreadsheet cells. The semantic channel scores
chunks and lifts each hit to its member blocks **at the chunk's own rank** — every member gets the
same rank, so RRF says "this region is relevant" and the other channels break the tie. A table above
`TABLE_SYNOPSIS_CELLS = 20_000` yields exactly one synopsis chunk (header rows, dimensions, eight
sampled rows, per-column type/range) and emits `OW_TABLE_SYNOPSIS_ONLY`; its cells stay fully
lexically indexed and fully citable. That is the priced answer to the 4M-cell sheet: 4,000,000 FTS
rows and one embedding.

**Lexical, and D2's delegation.** D2 wrote `block_fts` as a single-column external-content table and
delegated: *"D5 owns the BM25 weights."* Verified here (SQLite 3.45.1): a single-column
`bm25(t, w)` accepts a weight, but the weight enters the tf-saturation term rather than acting as a
field weight, and it cannot express "a heading match outranks a body match" — so the pragmatist
panel's diagnosis is right. Its remedy is not needed. D2 says L4 *adds indexes on these tables*, so
D5 adds a second external-content FTS5 table, **`head_fts` over `block.title`** (NULL on most rows,
therefore a tiny index), and scores with **heading-spine propagation**: a block earns
`W_BODY · bm25n(block_fts, b)` plus `W_HEAD · max over its heading spine of
bm25n(head, a) · SPINE_DECAY^depth`. That is strictly better for documents than a title column
would be, because it lifts the paragraphs *under* a matching heading and not merely the heading.
**D2's `block_fts` DDL is unchanged.**

**The planner.** Pure, memoised, printable. Its one genuinely hard decision is narrowing, and it is
answered exactly rather than estimated: run the narrowing `SELECT … LIMIT PREFILTER_MAX + 1` into a
TEMP table (verified to work on a `mode=ro` main connection). At or below `PREFILTER_MAX = 200_000`
you hold the exact candidate set and every channel — including the ANN one — filters exactly, with
no recall loss. Above it, narrowing becomes an over-fetch factor `clamp(1/selectivity, 1, 64)` from a
handful of scalar counts in `stat`, and if post-filtering leaves fewer than `k`, `filter_starved`
fires. Everything else — which channels run, their weights, budgets and short-circuits — is
`retrieval.toml` in D4's grammar, with D4's loader, Kleene `on_unknown`, `@thresholds` substitution,
subsumption linter and isotonic threshold fitter reused unchanged. Six named plan shapes and
equi-width histograms are rejected: five of six shapes are just "which channels ran", and an
independence-assumption estimate is wrong on exactly the correlated predicates real corpora have.

**Concurrency.** One writer, cross-process scoped lock `store.write`, holder identity
`(host, pid, process_create_time)`, `INTERACTIVE_WAIT_MS = 2_000` / `BATCH_WAIT_MS = 60_000` passed
per call, **enqueue before attempting the lock**. Pragmas in codegraph's order with `busy_timeout`
first. The WAL valve is ported with all eight properties and its verified constants
(`DEFAULT_WAL_VALVE_MB = 256`, hard cap ×2, file cap ×4, 20 passes then a futility latch,
`min(2048, max(256, db_bytes/4/MiB))`). Bulk windows drop only non-UNIQUE secondary indexes, read
their DDL from `schema/` by name with a hard raise on a miss, yield at the top of each loop body, and
write `index_state.bulk_window` before the first DDL — an open marker at open **refuses to serve**
and names `ow store repair`. `synchronous = NORMAL`, except that a transaction committing the output
of a `BILLED_API` operator runs at `synchronous = FULL`, set before `BEGIN`: one fsync against a VLM
call is free and re-billing a page because a laptop lid closed is not.

**Incremental.** D2's `rebind` produces the block-level delta and D5 consumes it: a carried
`block_id` with an unchanged `content_digest` keeps its FTS rows, chunk membership and embedding;
a changed digest re-chunks and looks the embedding up by the *new* `chunk_digest`, corpus-wide, often
a hit. Cross-reference convergence is `ResolutionDelta` — the set of `ref_name.norm` values whose row
set changed across the write — and every `ref_site` with a norm in the delta is re-resolved
**including in documents this run never touched**. Without it, codegraph measured 4.3% of distinct
edges wrong, in both directions, silently. `ref_unresolved` is a **VIEW**, not a table with a status
lifecycle: document resolution is by normalised string, so the anti-join is always correct and there
is no status column to get wrong; `ResolutionDelta` is what keeps it from ever running corpus-wide.
Replacement is tier-scoped on `origin_operator` and deletion is an explicit list, never inferred.

**Scale.** T1 one store; T2 one store with the full valve plus an ANN Backend; T3 Postgres behind
the same protocols; T4 a fabric of shards. Placement is jump consistent hash over `doc_key` (twelve
lines of stdlib, moves 1/n on resize, no committed routing table); **minting is separate from
placement**, so a document may migrate and its `block_id`s keep their prefix forever. A document
never spans a shard, so D2's entire FK graph stays shard-local and erasure is one `DELETE`. There
are no cross-shard foreign keys; everything that crosses is content — `doc_key`, `content_digest`,
`chunk_digest`, `cite`, `ref_name.norm` — and the one cross-store reference type is the value
`GlobalRef = (corpus_id, block_id)`. Federation broadcasts the query and **fuses on ranks**, because
two BM25 indexes with different corpus statistics produce incomparable scores; the bias toward small
shards is disclosed as `fusion_kind` and `shards_contributed`, never fixed by a global `term_df`
table nobody can keep consistent.

## Concrete shape

```
.omniweave/                              cache_root (D1). NEVER inside source_root.
├── index.owstore                        D2 model + D5 index + D3/D4/D6 ops.  THE file.
├── index.owstore-wal / -shm             healed at open above 64 MB
├── index.vec.owstore                    ATTACHed as `vec`. DERIVED. Deletable.
├── events.owstore                       retrieval_event. Per-user. DERIVED. Deletable.
├── cas/ab/cd/<sha256>                   retained `part` bytes, assets, page renders
└── jobs/<run_id>/…                      D1's toolchain job directories
omniweave.index.lock                     THE committed artefact (text, sorted, merge-driven)
retrieval.toml                           D4's rule grammar. builtin<site<project<profile<request
```

```sql
-- ═════ 0002_index.sql — the L4 layer. SCHEMA = 1. Additive to D2's .owstore. ═════
-- LEGEND:  [SOR] system of record, part of the published read contract at this SCHEMA major.
--          [DER] derived + rebuildable by one command; NOT a read contract; droppable.
-- D3's origin_driver / driver_schema_v / restriction_bits and D4's decision_id ship inside
-- 0001_init.sql's base `block` and `work` definitions, NOT as ALTER TABLE. (See Risks.)

-- ───── chunks: the embedding / derive / packing unit. NOT the fusion key. ─────────── [SOR]
CREATE TABLE chunker (
  chunker_id    INTEGER PRIMARY KEY,
  driver_id     TEXT    NOT NULL,          -- D3 DriverId, e.g. 'derive.chunk.spine'
  driver_schema_v INTEGER NOT NULL,
  params_digest BLOB    NOT NULL,          -- sha256_canonical of the flat Scalar params
  UNIQUE (driver_id, driver_schema_v, params_digest)
);
CREATE TABLE chunk (
  chunk_id      INTEGER PRIMARY KEY,
  doc_ord       INTEGER NOT NULL,
  gen           INTEGER NOT NULL,
  chunker_id    INTEGER NOT NULL REFERENCES chunker(chunker_id),
  ord           INTEGER NOT NULL,          -- position within (doc_ord, gen, chunker_id)
  chunk_digest  BLOB    NOT NULL,          -- recipe below; the join key to `vec`
  lo_block      INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  hi_block      INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  n_blocks      INTEGER NOT NULL, n_chars INTEGER NOT NULL,
  head_path     TEXT    NOT NULL,          -- 'Introduction / 2.1 Scope' — HEADINGS, not body text
  page_lo       INTEGER NOT NULL, page_hi INTEGER NOT NULL,
  trust_min     INTEGER NOT NULL,          -- MIN(block.trust) over members
  quote_min     INTEGER NOT NULL,          -- MIN(block.quote): gates serve's byte-exactness claim
  kind_mask     INTEGER NOT NULL,          -- bitmask over D2 Kind: pre-filter without a join
  restriction_bits INTEGER NOT NULL DEFAULT 0,   -- OR over members (D3-17)
  origin_operator  TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  state         INTEGER NOT NULL DEFAULT 0,      -- 0 live, 1 retired
  UNIQUE (doc_ord, gen, chunker_id, ord)
);
CREATE INDEX chunk_digest_ix  ON chunk(chunk_digest) WHERE state = 0;
CREATE INDEX chunk_doc        ON chunk(doc_ord, gen, page_lo) WHERE state = 0;
CREATE INDEX chunk_restricted ON chunk(restriction_bits) WHERE restriction_bits <> 0;

CREATE TABLE chunk_block (            -- [DER] materialised ONLY for a non-contiguous run.
  chunk_id INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  PRIMARY KEY (chunk_id, block_id)
) WITHOUT ROWID;
CREATE INDEX chunk_block_rev ON chunk_block(block_id);
-- A contiguous chunk stores ZERO rows: membership is `block_id BETWEEN lo_block AND hi_block`
-- AND state = 0. Same derived-and-lazily-materialised trick D2 used for grid_slot.

-- ───── lexical: D2's block_fts UNCHANGED, plus head_fts. NO second copy of any text. ── [DER]
-- D2's block_fts stands exactly as written. Its three triggers get the two guards D2's sketch
-- omits (state and NULL text), and the 'delete' command row carries the OLD values:
CREATE TRIGGER block_fts_ai AFTER INSERT ON block
  WHEN NEW.state = 0 AND NEW.text IS NOT NULL
  BEGIN INSERT INTO block_fts(rowid, text) VALUES (NEW.block_id, NEW.text); END;
CREATE TRIGGER block_fts_ad AFTER DELETE ON block
  WHEN OLD.state = 0 AND OLD.text IS NOT NULL
  BEGIN INSERT INTO block_fts(block_fts, rowid, text)
        VALUES ('delete', OLD.block_id, OLD.text); END;
CREATE TRIGGER block_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, text)
    SELECT 'delete', OLD.block_id, OLD.text WHERE OLD.state = 0 AND OLD.text IS NOT NULL;
  INSERT INTO block_fts(rowid, text)
    SELECT NEW.block_id, NEW.text        WHERE NEW.state = 0 AND NEW.text IS NOT NULL;
END;
CREATE VIRTUAL TABLE head_fts USING fts5(          -- block.title: NULL on most rows ⇒ tiny
  title, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');       -- + the same three guarded triggers
-- Retiring a generation sets its blocks state=1 IN THE SAME TRANSACTION that advances doc.gen,
-- so the FTS update trigger removes them. The index layer NEVER holds two generations.

-- ───── exact: the tokens unicode61 destroys. '§4.2(b)'→4·2·b, 'ISO-8601'→iso·8601 ──── [SOR]
CREATE TABLE ref_name (               -- a resolvable name DEFINED at a block
  norm     TEXT NOT NULL,             -- NFKC + casefold + punctuation-class collapse
  kind     TEXT NOT NULL,             -- section|clause|figure|table|equation|citekey|
                                      -- identifier|defined_term|footnote|exhibit|slide|sheet
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  doc_ord  INTEGER NOT NULL,
  surface  TEXT NOT NULL,             -- '§ 4.2(b)' as written. Displayed, never matched.
  origin_operator TEXT NOT NULL,
  PRIMARY KEY (norm, kind, block_id)
) WITHOUT ROWID;
CREATE INDEX ref_name_lookup ON ref_name(norm, kind, doc_ord);
CREATE TABLE ref_site (               -- a reference OCCURRENCE
  norm     TEXT NOT NULL, kind TEXT NOT NULL,
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  a INTEGER NOT NULL, b INTEGER NOT NULL,        -- D2 TextSpan into block.text
  surface  TEXT NOT NULL, origin_operator TEXT NOT NULL,
  PRIMARY KEY (norm, kind, block_id, a)
) WITHOUT ROWID;
CREATE INDEX ref_site_block ON ref_site(block_id);
-- MAX_REF_SITES_PER_BLOCK = 32; a breach emits Diag(OW_REFSITE_TRUNCATED) and is counted.
CREATE VIEW ref_unresolved AS         -- NO status column, NO lifecycle: resolution is by string,
  SELECT s.norm, s.kind, s.block_id, s.a, s.b, s.surface       -- so the retry is always correct.
  FROM ref_site s
  WHERE NOT EXISTS (SELECT 1 FROM ref_name n WHERE n.norm = s.norm AND n.kind = s.kind);
-- `ow store residue` prints it grouped by norm. The residue is data, not a log line.

-- ───── structural: one block→block edge table. FK-enforced. CASCADE works. ────────── [SOR]
CREATE TABLE block_sec (              -- [DER] section prefix index; NOT D2's rejected ord_path:
  block_id  INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,  -- no identity,
  sec_id    INTEGER NOT NULL,         -- nearest heading/section block           no ordering
  sec_depth INTEGER NOT NULL,         --                                         authority
  sec_path  TEXT    NOT NULL          -- '/1/4/2' — "everything under §4.2" is a prefix range
) WITHOUT ROWID;
CREATE INDEX block_sec_path ON block_sec(sec_path, block_id);
CREATE INDEX rel_src ON rel(src_id, kind);        -- D2 shipped only rel_dst; this is the other half

CREATE TABLE edge (
  edge_id     INTEGER PRIMARY KEY,
  src_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  relation    INTEGER NOT NULL,       -- FK into D2's enum_val; D7 OWNS THE VOCABULARY
  site_block  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,  -- WHERE it was observed
  via_entity  INTEGER,                -- D7's entity_id when the relation is entity-mediated.
                                      -- Deliberately no FK: D7 creates `entity`, and SQLite
                                      -- cannot add one by ALTER. `ow store verify` checks it.
  weight      REAL    NOT NULL DEFAULT 1.0,
  ambiguous   INTEGER NOT NULL DEFAULT 0,   -- >1 target matched: KEPT, ranked down, never dropped
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL,       -- D2 Trust ordinal. Absent ⇒ 0. Migrations only downgrade.
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
-- Identity in the SCHEMA with IFNULL sentinels, or INSERT OR IGNORE is a plain INSERT with
-- nothing to conflict on (codegraph #1034: byte-identical duplicates that inflated counts).
-- The migration installing this index MUST GROUP BY the identical expression.
CREATE UNIQUE INDEX edge_identity ON edge(
  src_block, dst_block, relation, producer_id, IFNULL(site_block,-1), IFNULL(via_entity,-1));
CREATE INDEX edge_out ON edge(src_block, relation);   -- left-prefix covers src-only lookups
CREATE INDEX edge_in  ON edge(dst_block, relation);
CREATE INDEX edge_restricted ON edge(restriction_bits) WHERE restriction_bits <> 0;
-- DELIBERATELY ABSENT: single-column edge_src / edge_dst. codegraph migration v4 DROPS the
-- equivalents as dead weight on the write path. MAX_EDGES_PER_BLOCK = 4096, enforced at write.

-- ───── the semantic channel's write-time contract (payload lives in `vec`) ────────── [SOR]
CREATE TABLE embed_space (            -- LEANN's meta.json as a table with a UNIQUE constraint
  space_id        INTEGER PRIMARY KEY,
  model_key       TEXT    NOT NULL UNIQUE,   -- sha256_canonical(the nine fields below)[:16]
  driver_id       TEXT    NOT NULL,          -- D3 embed/1 DriverId, e.g. 'embed.text.bge_m3'
  driver_schema_v INTEGER NOT NULL,
  model_id        TEXT    NOT NULL,
  model_rev       TEXT    NOT NULL,          -- EXACT sha. '' or 'main' is refused (D4-R14)
  dim             INTEGER NOT NULL,
  metric          TEXT    NOT NULL CHECK (metric IN ('cosine','ip','l2')),
  normalize       INTEGER NOT NULL,
  pooling         TEXT    NOT NULL,
  doc_prompt_digest   BLOB NOT NULL,         -- applied ONCE, client side, at build
  query_prompt_digest BLOB NOT NULL,         -- applied ONCE, client side, at query
  sig_bits        INTEGER NOT NULL,          -- binary signature width; 0 = none
  storage         TEXT    NOT NULL CHECK (storage IN ('sig_only','sig_full')),
  backend         TEXT    NOT NULL,          -- an `omniweave.backends` entry-point name
  created_ns      INTEGER NOT NULL
);
-- THE nine identity fields are model_id, model_rev, dim, metric, normalize, pooling,
-- doc_prompt_digest, query_prompt_digest, driver_id+driver_schema_v. A search whose embed
-- driver does not reproduce model_key is REFUSED with OW-S-020 printing BOTH tuples.
-- This SETTLES D3's open question: capability.embed keeps only dim, max_tokens and languages.

-- ───── freshness, coverage, state, stats, migrations ──────────────────────────────── [SOR]
CREATE TABLE unit_stat (              -- D5 owns the table; D6 owns the predicate and the writer
  unit_uri TEXT NOT NULL, salt TEXT NOT NULL,     -- keyed by SALT, never by absolute path (#1989)
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  indexed_at_ns INTEGER NOT NULL,     -- ★ captured BEFORE the content read
  content_digest BLOB NOT NULL, derived TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (unit_uri, salt)
) WITHOUT ROWID;
-- stat_fresh := size == st_size AND mtime_ns == st_mtime_ns
--                             AND st_mtime_ns + MTIME_GRANULARITY_NS(2e9) <= indexed_at_ns
CREATE TABLE ingest_scope (           -- written by the enumerator / an acquire driver (D3 duty)
  scope_id TEXT PRIMARY KEY, discovered INTEGER NOT NULL, indexed INTEGER NOT NULL,
  skipped INTEGER NOT NULL, skipped_why TEXT NOT NULL DEFAULT '{}',
  scanned_at_ns INTEGER NOT NULL, complete INTEGER NOT NULL
);
-- An ABSENT row means "coverage unknown", NEVER "nothing was excluded".
CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- corpus_id · shard_ord · schema · scorer_version · generation · fts_state{ok,building,stale}
-- · bulk_window · wal_baseline_bytes · last_full_index_ns · default_space_id
CREATE TABLE stat (k TEXT PRIMARY KEY, v INTEGER NOT NULL, computed_ns INTEGER NOT NULL);
-- ONLY scalar counts, for the over-fetch factor: live_blocks, live_chunks, docs, per-kind counts.
-- NO histograms: the narrowing decision is EXACT (LIMIT PREFILTER_MAX+1), not estimated.
CREATE TABLE migration (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_ns INTEGER NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('ddl','backfill','rebuild')),
  resumable INTEGER NOT NULL, backfill_done INTEGER NOT NULL DEFAULT 0, backfill_total INTEGER,
  unbackfilled_means TEXT NOT NULL    -- REQUIRED PROSE. `ow doctor` prints it verbatim.
) STRICT;
-- A migration whose estimated row-touch exceeds WATCHDOG_MS/2 MUST set resumable=1 and run
-- through `work` (codegraph: 79 s of CREATE INDEX against a 60 s watchdog ⇒ SIGKILL after
-- doing the work). Every ADD COLUMN is guarded with PRAGMA table_info; every dedup DELETE
-- before a UNIQUE index GROUP BYs the identical expression, IFNULL sentinels included.

-- ───── views: the compositions that are painful in raw SQL (part of the read contract) ─────
CREATE VIEW ow_block_head AS SELECT b.* FROM block b JOIN doc d USING (doc_ord)
  WHERE b.gen = d.gen AND b.state = 0;
CREATE VIEW ow_chunk_head AS SELECT c.* FROM chunk c JOIN doc d USING (doc_ord)
  WHERE c.gen = d.gen AND c.state = 0;
CREATE VIEW ow_ref_resolved AS
  SELECT s.block_id AS src_block, n.block_id AS dst_block, s.norm, s.kind, s.a, s.b
  FROM ref_site s JOIN ref_name n ON n.norm = s.norm AND n.kind = s.kind;
```

```sql
-- ═════ index.vec.owstore — ATTACHed as `vec`. [DER] Optional. Deletable. ═════
CREATE TABLE vec_manifest (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- corpus_id (≠ main.index_state.corpus_id ⇒ the sidecar is IGNORED, not read) · schema
-- · model_key · backend · backend_version · storage · sig_bits · dim · built_at_ns · rows
CREATE TABLE vseg (                   -- CONTIGUOUS SEGMENTS, never a row per vector.
  model_key TEXT NOT NULL, seg_no INTEGER NOT NULL, n INTEGER NOT NULL,
  digests BLOB NOT NULL,              -- n * 16 B chunk_digest, sorted
  sigs    BLOB NOT NULL,              -- n * (sig_bits/8) B, same order
  live    BLOB NOT NULL,              -- ceil(n/8) B bitmap; a swept row clears its bit
  PRIMARY KEY (model_key, seg_no)
);
CREATE TABLE vfull (                  -- storage='sig_full' only: exact rerank of the top RERANK_N
  model_key TEXT NOT NULL, chunk_digest BLOB NOT NULL, v BLOB NOT NULL,   -- dim*4 B f32 LE
  PRIMARY KEY (model_key, chunk_digest)
) WITHOUT ROWID;
CREATE TABLE vpending (               -- the re-embed set, MATERIALISED so it is a scan
  model_key TEXT NOT NULL, chunk_digest BLOB NOT NULL, chars INTEGER NOT NULL,
  PRIMARY KEY (model_key, chunk_digest)
) WITHOUT ROWID;
-- SEGMENT_SIZE = 4096. RERANK_N = 1000. Measured here (CPython 3.11, 96-byte signatures,
-- XOR + int.bit_count() + a 512-entry heap):
--   200,000 signatures scanned in 81 ms  ⇒  ~406 ms extrapolated to 1,000,000.
-- Therefore VEC_BRUTE_MAX_BLOCKS = 250_000 (~100 ms), inside D1's 250 ms warm-query gate
-- alongside the lexical channel. Above it the stdlib backend REFUSES with OW-S-022.
```

```sql
-- ═════ events.owstore — per-user, derived, deletable. Written by mode=ro query processes. ═════
CREATE TABLE retrieval_event (
  event_id INTEGER PRIMARY KEY, ts_ns INTEGER NOT NULL,
  corpus_id TEXT NOT NULL, surface TEXT NOT NULL,          -- cli | mcp | hook
  query_hash TEXT NOT NULL, query TEXT,
  plan_digest TEXT NOT NULL, policy_digest TEXT NOT NULL,
  scorer_version INTEGER NOT NULL, producer_version TEXT NOT NULL,
  narrowing_kind TEXT NOT NULL CHECK (narrowing_kind IN ('all','set','empty')),
  narrowing_n INTEGER NOT NULL, prefilter_exact INTEGER NOT NULL,
  channels TEXT NOT NULL, channel_ms TEXT NOT NULL DEFAULT '{}',
  space_id INTEGER, backend TEXT, overfetch REAL,
  returned_n INTEGER NOT NULL, matches_before_packing INTEGER NOT NULL,
  best_score REAL, score_ceiling REAL, confidence REAL, gap REAL,
  verdict_state TEXT NOT NULL, degraded_because TEXT NOT NULL DEFAULT '[]',
  freshness TEXT NOT NULL, snapshot_gen INTEGER NOT NULL, shards_contributed TEXT,
  spend TEXT NOT NULL, micros INTEGER NOT NULL DEFAULT 0,   -- D4's Spend vector + PriceBook
  latency_ms INTEGER NOT NULL
) STRICT;
CREATE INDEX retrieval_event_ts  ON retrieval_event(ts_ns);
CREATE INDEX retrieval_event_bad ON retrieval_event(ts_ns) WHERE verdict_state <> 'ok';
-- Written through a bounded in-memory queue (cap 4096, drop-oldest with a counter), flushed
-- on a 2 s timer and at exit — NEVER inside the read snapshot, NEVER on the response path.
-- Retention 90 days, swept by `ow store gc`. THIS IS A QUERY LEDGER, NOT A SECOND DECISION LOG:
-- query-time work that persists nothing creates no `work` row and no `route_decision`.
```

```python
# ═════ omniweave_core/store/ — THE ONLY module that calls sqlite3.connect (D1 lint) ═════
CONN_PRAGMAS = (                     # per connection, IN THIS ORDER
    "busy_timeout = 5000",           # FIRST. journal_mode before this crashes a contended open.
    "foreign_keys = ON", "journal_mode = WAL", "synchronous = NORMAL",
    "cache_size = -64000", "temp_store = MEMORY", "mmap_size = 268435456")
INIT_PRAGMAS = ("journal_size_limit = 67108864",)     # persistent per FILE; heal threshold
CREATE_PRAGMAS = ("page_size = 8192", "auto_vacuum = INCREMENTAL")   # CREATE time only

class Store(Protocol):               # D1's four methods. VERBATIM. Never widened.
    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]: ...
    def complete(self, row_id: int, gen: int, result: StepResult) -> bool: ...
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...

class Reader(Protocol):              # the RETRIEVAL boundary. A Postgres T3 implements this.
    def snapshot(self) -> ContextManager["Snapshot"]: ...
    def capabilities(self) -> "IndexCaps": ...
    def narrow(self, s: "Snapshot", f: "Filters") -> "Narrowing": ...
    def channel(self, s: "Snapshot", spec: "ChannelSpec", n: "Narrowing") -> "ChannelResult": ...
    def hydrate(self, s: "Snapshot", ids: Sequence[int]) -> Sequence["Hit"]: ...
    def coverage(self, s: "Snapshot", f: "Filters") -> "Coverage": ...

class VectorBackend(Protocol):       # THE Backend seam. Not a Port, not a DriverCard (D3).
    def manifest(self) -> "VecManifest": ...
    def upsert(self, model_key: str,
               rows: Iterable[tuple[bytes, bytes, bytes | None]]) -> int: ...  # digest, sig, full
    def search(self, model_key: str, q_sig: bytes, q_full: bytes | None, *, k: int,
               candidates: frozenset[bytes] | None) -> Sequence[tuple[bytes, float]]: ...
    def sweep(self, live: Callable[[], Iterable[bytes]]) -> int: ...
# Declared by an `omniweave.backends` entry point plus a `backend.toml` read by D3's
# import-free loader. It is NOT a DriverCard: no capability floors, never in resolve(),
# selected by NAME in config only. CONTRACT OBLIGATIONS, verified by omniweave-conform:
#   (1) filter pushdown is real — `candidates` narrows BEFORE ranking, tested at 0.01 selectivity;
#   (2) either epoch-immutable (search() reads the version resolved at open) OR it returns
#       unavailable(rebuilding) — the afternoon-implementable floor;
#   (3) it declares a ceiling and REFUSES above it rather than serving a slow query;
#   (4) recall@10 against exhaustive f32 on a fixed 50k fixture, with a committed floor.
# D2's DocSink is the write protocol, unchanged. There is no fifth protocol.

@dataclass(frozen=True, slots=True)
class Snapshot:
    conn: "sqlite3.Connection"       # the only place a Connection is visible outside store/
    generation: int; corpus_id: str; schema: int; vec_attached: bool; opened_ns: int
# ONE `BEGIN DEFERRED` for the WHOLE query — every channel, hydration and the coverage scan.
# Without it a 6–12 statement retrieval sees up to twelve snapshots and fusion mixes generations.
# MAX_SNAPSHOT_MS = 5_000 is a CEILING in limits.py; [retrieval] snapshot_ms clamps BELOW it
# (default 2_000). Exceeding it aborts with OW-S-010 and verdict=degraded — because a held read
# transaction PINS THE WAL, which is exactly the futility-latch condition. The reader's deadline
# is a WAL-valve safety parameter, not a UX parameter.

class Narrowing(NamedTuple):         # a TAGGED type. `if candidates:` is unrepresentable.
    kind: Literal["all", "set", "empty"]
    table: str | None                # 'tmp_narrow' iff kind == 'set'
    n: int                           # exact when kind == 'set'
# PREFILTER_MAX = 200_000. `SELECT … LIMIT PREFILTER_MAX+1` into a TEMP table (verified to work
# on a mode=ro main connection) gives an EXACT candidate set or proves it is too big. No
# histogram, no independence assumption, no cost-based optimiser.
#   CREATE TEMP TABLE tmp_narrow(block_id INTEGER PRIMARY KEY) WITHOUT ROWID;
#   INSERT INTO tmp_narrow SELECT b.block_id FROM block b JOIN doc d USING (doc_ord)
#     WHERE b.state=0 AND b.gen=d.gen AND b.layer IN (…) AND b.kind IN (…)
#       AND (b.restriction_bits & :deny)=0 AND b.trust >= :trust LIMIT :cap;

@dataclass(frozen=True, slots=True)
class Filters:                       # FILTERS NARROW. CHANNELS SCORE WITHIN THE NARROWED SET.
    doc_keys: frozenset[bytes] | None = None; uri_prefix: str | None = None
    formats: frozenset[str] | None = None; kinds: frozenset[Kind] | None = None
    layers: frozenset[Layer] = frozenset({Layer.BODY})
    pages: range | None = None; sec_path_prefix: str | None = None; lang: str | None = None
    min_trust: Trust | None = None; min_quote: Quote | None = None
    deny_restriction_bits: int = 0   # set by POLICY, never by the caller (D3-17)
    gen: Literal["head"] | int = "head"

@dataclass(frozen=True, slots=True)
class Query:
    text: str = ""; refs: tuple[str, ...] = (); filters: Filters = Filters()
    mode: Literal["find","cite","explore","prove_absent"] = "find"
    k: int = 20; max_blocks: int = 60; max_chars: int = 24_000
    space_id: int | None = None; corpora: tuple[str, ...] = ()
    expand: "Expand | None" = None; budget: "QueryBudget" = ...

CHANNELS = ("identity", "exact", "lexical", "structural", "semantic")
class ChannelStatus(StrEnum):
    OK="ok"; EMPTY="empty"; OFF="off"; UNAVAILABLE="unavailable"
# OK/EMPTY contribute weight to the ceiling. OFF is an OPERATOR CHOICE and is disclosed.
# UNAVAILABLE contributes nothing AND forces degraded — and a channel that RAISED reports
# UNAVAILABLE with a reason. There is no `except: return []` under retrieve/ (semgrep).

@dataclass(frozen=True, slots=True)
class ChannelResult:
    name: str; status: ChannelStatus
    ranked: tuple[int, ...]                       # block_ids, totally ordered, duplicate-free
    spans: Mapping[int, TextSpan] = ...           # FTS5 offsets: a hit is sub-block addressed
    grades: Mapping[int, str] = ...               # identity: the tier ACTUALLY measured
    weight: float | None = None                   # explicit (INCLUDING 0.0) wins; 0.0 is a value
    reason: str = ""                              # REQUIRED when status != OK
    truncated_at_limit: bool = False              # feeds gates 8 and 9
    ran_ms: int = 0; cost: "Spend" = ...

DEFAULT_WEIGHTS = {"identity": 2.0, "exact": 1.2, "lexical": 1.0,
                   "semantic": 0.8, "structural": 0.4}
RRF_K = 60 ; SCORER_VERSION = 1
# ceiling, five channels = 5.4/61 = 0.08852 ; four (no semantic) = 4.6/61 = 0.07541
# ; lexical+identity only = 3.0/61 = 0.04918.  NEVER hardcode 1/(k+1).
def _weight(ch, w) -> float: return ch.weight if ch.weight is not None else w.get(ch.name, 1.0)
def fuse(chs, *, k=RRF_K, weights=DEFAULT_WEIGHTS) -> list["FusedHit"]: ...
def ceiling(chs, *, k=RRF_K, weights=DEFAULT_WEIGHTS) -> float: ...
#   score(b) = Σ_c _weight(c)/(k + rank(c,b)) over c.status == OK
#   ceiling  = Σ_c _weight(c)/(k + 1)        over c.status in (OK, EMPTY)
#   confidence = best_score / ceiling.  low_confidence < 0.35.
#   Both resolve weights through _weight(). A perfect-consensus property test asserts
#   fuse()[0].score == ceiling() to 1e-12. A ceiling that drifts from the scorer silently
#   rescales every confidence number in the product.
@dataclass(frozen=True, slots=True)
class FusedHit:
    block_id: int; score: float
    channel_contributions: Mapping[str, float]; channel_ranks: Mapping[str, int]
# Total order on (-score, block_id). Ties broken by storage order are nondeterministic across
# a VACUUM or an FTS5 'optimize'. A fusion returning only a score is one you cannot tune.
# THE SEMANTIC CHANNEL'S LIFT: a chunk hit at rank r yields ALL its member blocks AT RANK r
# (capped at SEM_BLOCKS_PER_CHUNK = 64), so a region-level signal stays region-level and the
# block-level channels break the tie.

# ── the lexical scorer: this is where "D5 owns the BM25 weights" is discharged ──────────
W_BODY = 1.0 ; W_HEAD = 6.0 ; SPINE_DECAY = 0.6 ; LEX_OVERFETCH = 5
# lex(b) = W_BODY * bm25n(block_fts, b)
#        + W_HEAD * max over a in spine(b) of ( bm25n(head_fts, a) * SPINE_DECAY**depth(b,a) )
# spine(b) comes from block_sec. b is its own depth-0 ancestor. Over-fetch 5x BEFORE re-rank
# (codegraph): a re-ranker that only sees the base scorer's top-k cannot promote what it buried.
# Query sanitisation is a SEMANTIC TRANSFORM, not escaping: § ¶ † ‡ · — → space; soft hyphen
# and '-\n' folded; FTS5 specials '"*():^- and bare AND|OR|NOT|NEAR stripped so a user cannot
# inject FTS syntax; reference-shaped tokens ('§4.2(b)', 'Fig. 3a', 'GL-4471', 'd7#412') LIFTED
# OUT to Query.refs before the residue reaches FTS; CJK runs bigrammed; MAX_QUERY_TERMS = 64;
# an unknown 'foo:bar' prefix passes through AS PLAIN TEXT so `TODO:` returns results.
# Field DSL: kind: page: doc: layer: trust: quote: sec: lang:  — validated against D2's enums.

# ── the identity ladder. The 40 tier is the first thing a "simplification" deletes. ─────
IDENTITY_LADDER = {                  # the reported grade is the one ACTUALLY measured
    "cite_exact": 50, "addr_exact": 50, "doc_uri_exact": 50, "doc_key_prefix": 48,
    "title_exact": 45,               # casefold only
    "title_normalised": 40,          # needed MORE than case: NFKC, punctuation, separators
    "title_prefix": 30, "spine_segment": 20, "none": 0}
# Collapsing 40 into 50 let a punctuation-different match tie a literal one and fall through to
# BM25 — a fixture outranking the symbol it tests by 0.355 of ~58. Document analogue:
# "Table 3.2 (revised)" tying with "Table 3.2".

@dataclass(frozen=True, slots=True)
class Expand:                        # structural traversal, bounded BY CONSTRUCTION
    max_hops: int = 2                # HARD CAP 4
    beam: int = 64                   # per hop, ordered by (weight * trust) / log1p(degree)
    relations: frozenset[int] = ...  # NEVER "all relations"
    min_trust: Trust = Trust.INFERRED
    max_visited: int = 4096
    hub_cap: int = 4096              # a block with more edges contributes at most hub_cap
                                     # neighbours, sampled by weight, and sets
                                     # degradations += ["hub_capped:<block_id>"]
# A Python frontier BFS over batched `WHERE src_block IN (…)`, with an explicit visited set,
# cancellable at the top of each hop, joining tmp_narrow. NOT a recursive CTE (SQLite has no
# built-in visited set and no per-hop fan-out bound). NO CSR sidecar, NO materialised closure,
# NO graph engine at v1.

# ── the planner ─────────────────────────────────────────────────────────────────────────
def plan(q: Query, caps: "IndexCaps", pol: "RetrievalPolicy") -> "QueryPlan": ...
# PURE: no clock, no RNG, no env, no I/O, no store read. Memoised on
# (mode, channel set, filter-field set, policy_digest, caps_digest). Same semgrep bans as
# D4's evaluate(). Channels run CHEAPEST FIRST inside one Snapshot, each with its own
# budget_ms; a channel over budget returns UNAVAILABLE(timeout) with what it has.
# retrieval.toml is D4's rule grammar VERBATIM — first-match-wins [[rule]] blocks, closed
# comparison clauses, @thresholds.<name> substitution, required on_unknown, and D4's loader,
# subsumption linter and isotonic threshold fitter reused unchanged.
@dataclass(frozen=True, slots=True)
class QueryPlan:
    channels: tuple["ChannelSpec", ...]          # ordered; the order IS the run order
    filters: Filters; fusion: "FusionSpec"; pack: "PackSpec"
    gates: tuple[str, ...]                       # which absence gates apply to THIS plan
    short_circuit: str | None                    # 'identity>=50 and mode=cite'
    scorer_version: int; plan_digest: str; policy_digest: str

# ── the verdict: TWELVE gates, ONE citability rule ──────────────────────────────────────
class VerdictState(StrEnum):
    OK="ok"; LOW_CONFIDENCE="low_confidence"; ABSENT="absent"; DEGRADED="degraded"
ABSENCE_GATES = (                    # precedence order; ANY failure forces DEGRADED
  "timed_out",              #  1 snapshot or a channel budget expired
  "channel_unavailable",    #  2 a requested channel is unavailable, or a channel RAISED
  "coverage_incomplete",    #  3 ingest_scope.discovered > indexed, complete=0, or NO ROW
  "pending_work_in_scope",  #  4 work rows pending/claimed for units inside the scope
  "freshness_unknown",      #  5 a unit in scope could not be stat-checked
  "parse_incomplete",       #  6 ★ THE DOCUMENT GATE. An indexed join on diag_code:
                            #    doc.status IN ('partial','failed','skipped') OR a diag row in
                            #    scope with OW_NEEDS_OCR, OW_ENCRYPTED, OW_TIMEOUT,
                            #    OW_TRUNCATED_BY_BUDGET, OW_RESOURCE_LIMIT, OW_MALFORMED,
                            #    OW_MISSING_PART, OW_INTEGRITY_UNCHECKED, OW_TABLE_SYNOPSIS_ONLY.
  "restricted_withheld",    #  7 ★ rows removed by deny_restriction_bits. COUNTED, never silent.
  "truncated_by_packing",   #  8 matches_before_packing > 0 and returned 0
  "filter_starved",         #  9 ★ the ANN over-fetch cap was hit and post-filtering left < k
  "shard_unreachable",      # 10 federated only
  "space_mismatch",         # 11 vec_manifest.model_key or corpus_id disagrees
  "similarity_only")        # 12 ★ LAST: the only channel that ran was semantic. A cosine zero
                            #    is a statement about the MODEL, not about the corpus.
@dataclass(frozen=True, slots=True)
class DegradeCause:
    gate: str; detail: str
    diag_codes: tuple[str, ...] = (); where: tuple[tuple[int,int,int], ...] = ()  # doc,pg_lo,pg_hi
    fix: str = ""                    # THE EXACT COMMAND that clears it (D1's error-message rule)
@dataclass(frozen=True, slots=True)
class Verdict:
    state: VerdictState; degraded_because: tuple[DegradeCause, ...]
    scanned: Mapping[str,int]; best_score: float|None; score_ceiling: float
    confidence: float|None; scorer_version: int; plan_digest: str
    channels: Mapping[str, ChannelStatus]
    freshness: Literal["fresh","stale","unknown","not_tracked"]
    coverage: "Coverage"; withheld: Mapping[str,int]; matches_before_packing: int
    space: Mapping[str,str]|None; snapshot_gen: int
    federated: bool; shards_contributed: str|None
    fusion_kind: Literal["exact","rank_merge"]; did_you_mean: tuple[str,...]
    def citable_as_absence(self) -> bool: return self.state is VerdictState.ABSENT
def build_verdict(**kw) -> Verdict: ...   # the ONLY constructor. A new hazard forces DEGRADED;
                                          # nothing ever adds a second citability rule.
def retrieve(r: Reader, q: Query, pol: "RetrievalPolicy") -> "Response": ...
#   Response = {hits: tuple[Hit,...], verdict: Verdict, cost: Spend}
#   Hit = {block_id, cite, addr, score, span, channel_contributions, channel_ranks,
#          identity_grade, chunk_id, trust, quote, restriction_bits}
```

```
# ═════ the chunk digest recipe (chunk_recipe = 1) ═════
chunk_digest = blake3_128(canonical([
    chunker.driver_id, chunker.driver_schema_v, chunker.params_digest,
    head_path,                                  # contextualisation IS part of what was embedded
    [b.content_digest for b in members in (page, ord) order]]))
chunk_text(c) = c.head_path + "\n\n" + "\n\n".join(member texts)
NOT inputs: chunk_id, block_id, addr, cite, page, geometry, producer_id, trust, origin_operator.
Every input is a STORED field, so a chunk_recipe bump is a re-digest pass, never a re-parse.

# ═════ the shipped chunker: derive.chunk.spine ═════
TARGET_CHARS 1600 · MAX_CHUNK_BLOCKS 64 · OVERLAP_BLOCKS 1 (a WHOLE block, never a char window)
emit on: n_chars >= TARGET_CHARS | n_blocks >= MAX_CHUNK_BLOCKS | the heading ancestor changes
         | the next block is kind TABLE
layers: {BODY} by default; furniture/note/annotation are chunked separately and never merged in
TABLE: whole rows with header rows REPEATED, bounded by TABLE_CHUNK_CHARS 1600 / TABLE_MAX_CHUNKS 32
       above TABLE_SYNOPSIS_CELLS = 20_000 → ONE synopsis chunk + Diag(OW_TABLE_SYNOPSIS_ONLY)
       ⇒ a merge-free 4M-cell sheet is 4,000,000 FTS rows, 4,000,000 citable blocks, 1 embedding.

# ═════ block_id ═════
block_id := (minting_shard_ord << 48) | sequence          # 16 bits / 48 bits, 63-bit total
  single store  shard_ord = 0 ⇒ ids are literally 1, 2, 3 …  zero bytes, human-readable
  fabric        65,536 shards x 2.81e14 blocks each
  CHECK ((block_id >> 48) = :shard_ord) on every shard's block table, asserted at open
  placement     jump_consistent_hash(int.from_bytes(doc_key[:8],'big'), n_shards)  ~12 lines
  MINTING IS NOT PLACEMENT: a document may migrate; its block_ids keep their prefix FOREVER.
  A document never spans a shard. There are NO cross-shard foreign keys.
  GlobalRef = (corpus_id: bytes16, block_id: int)          the ONLY cross-store reference type.

# ═════ omniweave.index.lock — THE committed artefact ═════
# schema=1 scorer=1 chunker=derive.chunk.spine@3:9c1e space=bge-m3@a1b2c3/768/cosine/i8
<doc_key hex>  <gen>  <status>  <n_blocks>  <n_chunks>  <root content_digest>  <uri>
# Sorted by doc_key, byte-stable, no timestamps, ~200 B/document (≈3 MB at 20k documents).
# A merge driver is registered FOR THIS PATH ONLY: sort-merge by doc_key; identical lines
# union; a CONFLICTING line for one doc_key is a real conflict a human resolves; a deleted
# line STAYS DELETED. That last property is exactly what graphify's `nx.compose` union driver
# throws away (verified: graphify/graphify/cli.py:2572, caps _MERGE_MAX_BYTES = 50 MB /
# _MERGE_MAX_NODES = 100_000 at :2547-2548).
# `ow store lock | verify --lock | diff`. The .owstore is .gitignore'd; a tracked store is
# OW-S-060 and `ow doctor` fails. `ow store export --portable` writes one .owdoc per document
# (D2's codec, D2's CI gate) as a TRANSPORT artefact — not a git artefact.
```

```toml
# omniweave.toml — additive to D1's [store]
[store]
backend      = "sqlite"              # sqlite (shipped) | postgres (T3) | fabric (T4)
path         = ".omniweave/index.owstore"
wal_valve_mb = 0                     # 0 = clamp(db_bytes/4, 256 MB, 2 GB) — codegraph's formula
wal_heal_mb  = 64
bulk_windows = true

[retrieval]
vectors     = "off"                  # off | on.  THE DEFAULT IS OFF.
scorer      = 1
fusion_k    = 60
snapshot_ms = 2000                   # clamped below MAX_SNAPSHOT_MS = 5000
trigram     = false                  # a THIRD lexical channel. Opt-in, no default. See Rejected.
policy      = "retrieval.toml"
event_log   = true                   # events.owstore, 90-day retention
[retrieval.weights]  identity = 2.0 ; exact = 1.2 ; lexical = 1.0 ; semantic = 0.8 ; structural = 0.4
[retrieval.lex]      w_body = 1.0 ; w_head = 6.0 ; spine_decay = 0.6 ; overfetch = 5
[retrieval.budget]   query_ms = 250
  channel_ms = { identity = 20, exact = 40, lexical = 60, structural = 60, semantic = 120 }
[retrieval.vectors]
model_key   = ""                     # empty ⇒ adopt vec_manifest's. A MISMATCH is gate 11.
backend     = "vector.brute"         # an `omniweave.backends` entry-point name
storage     = "auto"                 # auto | sig_only | sig_full — STAMPED, validated at open
max_blocks  = 250000                 # the stdlib backend's MEASURED ceiling. Above it: REFUSE.
[store.shard]  count = 1 ; target_blocks = 32000000
```

```
# ═════ CLI ═════
ow query <text> [--k 20] [--mode find|cite|explore|prove_absent] [--json]
ow query explain <text>          filters, narrowing (exact n), channels, fusion, ceiling, gates
ow query replay <event_id>       IDENTICAL | DIVERGED | REPLAY_DRIFT
ow get <cite|addr|uri>           the short-circuit path: one index seek
ow store doctor | stats | verify [--deep] | repair --fts|--sec|--refs | gc | vacuum [--into]
ow store backup <path>           sqlite3 online backup API: consistent, no writer pause
ow store analyze                 refresh `stat`; also auto-run after a write touching >1% of rows
ow store explain --golden        EXPLAIN QUERY PLAN for every shipped statement, byte-diff gated
ow store residue                 ref_unresolved grouped by norm — the residue is data
ow store migrate [--resume] | reshard | sql --readonly '<SELECT …>' | export --portable
ow store lock | verify --lock | diff <a.lock> <b.lock>
ow index [--rebuild] | update | chunks [--rebuild] | vectors [--rebuild] | drop --channel <name>

# ═════ codes.toml — OW-S-nnn, append-only, every message ends in the command that clears it ═════
OW-S-001 STORE_NOT_FOUND             OW-S-020 VECTOR_SPACE_MISMATCH (prints BOTH tuples)
OW-S-002 STORE_LOCKED (names holder) OW-S-021 VECTOR_SIDECAR_FOREIGN (corpus_id ⇒ ignored)
OW-S-003 SCHEMA_AHEAD                OW-S-022 VECTOR_BACKEND_CEILING
OW-S-004 MIGRATION_REQUIRED          OW-S-023 VECTOR_BACKEND_REBUILDING
OW-S-005 FTS5_UNAVAILABLE            OW-S-030 OVERFETCH_EXHAUSTED
OW-S-006 SQLITE_TOO_OLD (<3.35)      OW-S-031 QUERY_BUDGET_EXHAUSTED
OW-S-007 WAL_HEALED                  OW-S-032 CHANNEL_FAILED
OW-S-008 WAL_WRITER_PAUSED           OW-S-040 SHARD_UNREACHABLE
OW-S-009 BULK_WINDOW_OPEN            OW-S-041 CROSS_SHARD_FUSION_APPROXIMATE
OW-S-010 SNAPSHOT_EXPIRED            OW-S-050 UNEXPLAINED_LOSS
OW-S-011 FTS_GHOSTS                  OW-S-051 COVERAGE_UNKNOWN
OW-S-012 QUERY_PLAN_REGRESSION       OW-S-060 STORE_TRACKED_BY_GIT   OW-S-061 LOCKFILE_DRIFT
```

```
# ═════ INVARIANTS S1–S20, each with its enforcer ═════
S1  sqlite3.connect appears in exactly one module.            D1's lint rule + a monkeypatch test.
S2  One query = one snapshot.  Channel fns take Snapshot, never Store/Connection (pyright); a
    test commits a full re-index between channel 1 and channel 5 and asserts identical results.
S3  No transaction spans main and vec.  A grep gate over BEGIN-scoped statement groups.
S4  A stale vector is invisible, never wrong.  The semantic channel's only exit is an inner join
    vseg.digests[i] = chunk.chunk_digest inside the main snapshot. Sweeps are an optimisation.
S5  "no restriction" != "restrict to nothing".  Narrowing is TAGGED; semgrep bans `if narrowing:`;
    a nonsense-query fixture asserts 0 hits and `absent`, never the corpus ranked by centrality.
S6  fuse() and ceiling() share _weight().  Perfect-consensus property test to 1e-12.
S7  Every channel is totally ordered on (-score, block_id).  A property test shuffles SQL row
    order 100x and VACUUMs, asserting an identical ranking.
S8  A channel failure is never a confident zero.  No bare except under retrieve/ (semgrep);
    a fault-injection test corrupts block_fts and asserts degraded, not absent.
S9  `absent` requires all twelve gates.  build_verdict is the sole constructor; one fixture per
    gate; a test asserts adding a hazard requires no second citability rule.
S10 Every derived row's identity is a schema constraint.  UNIQUE with IFNULL sentinels; the
    installing migration GROUP BYs the identical expression; a double-insert test.
S11 An operator's re-run replaces only rows whose origin_operator is its own.  NOT NULL on every
    derived row; a grep gate over every DELETE FROM under store/ for the predicate.
S12 Incremental converges with a full rebuild.  gate_incremental.py indexes a 200-document
    fixture in 40 batches and fully into a second store and diffs EVERY table modulo timestamps.
    codegraph measured 4.3% of distinct edges wrong, both directions, silently, without it.
S13 A crash inside a bulk window is visible, never silently served.  index_state.bulk_window
    written before the first DDL; open refuses and names `ow store repair`; a SIGKILL test.
S14 A BILLED_API commit is durable.  synchronous=FULL set before BEGIN for that transaction;
    a test asserts the pragma value at commit time for a billed operator and NORMAL for a free one.
S15 A reader cannot pin the WAL indefinitely.  MAX_SNAPSHOT_MS in the snapshot context manager.
S16 A governor that cannot help gets out of the way.  The valve's futility latch: 2 give-ups ⇒
    60 s cooldown ⇒ degrade to un-valved, with an armed log line and a heartbeat.
S17 Every shipped index is used and every hot query's plan is reviewed.  tools/indexes.toml names
    each index and its statement; `ow store explain --golden` byte-diff gated like D1's G6.
S18 Every migration declares cost class, resumability and what an un-backfilled row means.
    NOT NULL in a STRICT table; the loader refuses a >WATCHDOG_MS/2 migration that is not resumable.
S19 The store is never committed.  Shipped .gitignore; `ow doctor` fails with OW-S-060.
S20 block_id carries its minting shard forever.  CHECK ((block_id >> 48) = :shard_ord) on every
    shard, asserted at open against index_state.shard_ord; an append-only shard registry.
```

```
# ═════ BUILD ORDER — every phase ships a command a user runs ═════
P1  4 wk  store core: pragmas, connect_readonly ladder, 0001+0002, migrations, WAL valve,
          heal-on-open, bulk windows, Store's four methods incl. the no-RETURNING fallback,
          unit_stat, ingest_scope, index_state.        `ow index . && ow store stats`
P2  3 wk  Snapshot, Filters/Narrowing, the lexical + identity channels, head_fts and the spine
          scorer, sanitisation, fuse/ceiling, build_verdict with all twelve gates,
          retrieval_event.                             `ow query` that can honestly say "not found"
P3  3 wk  ref_name/ref_site/ref_unresolved, block_sec, edge + the frontier BFS, the exact and
          structural channels, plan() + retrieval.toml, `ow query explain`.
P4  3 wk  chunk + chunker + chunk_digest, derive.chunk.spine, ResolutionDelta, gate_incremental,
          the attribution guard, `ow store lock/verify/diff`, watcher integration.
P5  3 wk  embed_space, the vec sidecar, vector.brute + the 250k refusal, VectorBackend +
          omniweave.backends + backend.toml + the conformance suite, vpending, recall gate.
P6  —     Postgres behind the same protocols; shard prefix + jump hash + reshard; the fabric
          coordinator with rank fusion and the degraded roll-up. Scoped by the first 50M-block user.
≈16 engineer-weeks to P5 for two people, plus ~1.5 weeks of Windows parity. Zero new runtime
dependencies in omniweave-core beyond what D1/D2 already resolve: sqlite3, json, hashlib, heapq,
array, struct, unicodedata, re, tomllib.
```

## Rationale

**The fusion key is the block, and this is the one place I overrule the systems purist.** His
observation is right — four channels return four shapes and pretending they share a key makes RRF
weights uninterpretable — but his fix costs more than the disease. D2 spent its whole identity
section establishing that `block_id` is the single durable FK target and `cite` the single
citable token; introducing a second ranking key means D7, D8 and D9 each learn a key and a
projection, and `restriction_bits`, `withheld` and `matches_before_packing` are all per-block
quantities that would have to be lifted twice. His own stage two — "select blocks within the
winning chunks using the per-block evidence the lexical and identity channels already produced" —
is a second fusion at block level with the ceiling computed one level up, which is precisely the
drift `ceiling()` exists to prevent. The real problem he identified, that a 4M-cell sheet must not
become 4M embeddings, is solved by his *other* idea — the table synopsis rule in the chunker — and
I take that whole. Chunks stay, as the embedding unit and the `derive/1` unit that D3 already
mandates; the semantic channel projects a chunk's rank onto its members so a region-level signal
stays region-level and the block-level channels break the tie.

**Where the systems purist was straightforwardly right and both others were not**: the sum-typed
`Narrowing`, the `hub_cap`, the `bulk_window` crash marker, `synchronous = FULL` for billed
commits, and the reader deadline as a WAL-valve safety parameter rather than a UX parameter. All
five are taken verbatim. His epoch/lease machinery is right in principle and in the wrong place:
with both sidecars being SQLite, nothing the framework ships mutates a derived file in place, so
two tables and a reaper leave the core schema and become a *contract obligation on a Backend*,
verified by the conformance suite — with "refuse to search while rebuilding" as the
afternoon-implementable floor. That is the ecosystem architect's instinct applied to the systems
architect's mechanism, and it is a strictly smaller core.

**The narrowing decision is the planner, and it should be exact rather than estimated.** All three
panels reached for a selectivity model; the systems purist went furthest, with equi-width
histograms, an independence assumption he correctly labels wrong, and a CI gate on the est-vs-actual
ratio to contain the damage. But `SELECT … LIMIT PREFILTER_MAX + 1` answers the only question that
matters — *is the candidate set small enough to filter exactly* — with an exact answer, in one
statement, for the cost of the work you were going to do anyway. That deletes `stat_hist`, the
independence assumption, the est-vs-actual gate, and five of six named plan shapes. What remains
of the planner is channel selection and weights, and there the ecosystem architect is right that
reusing D4's grammar is worth more than a bespoke config: one policy language, one linter, one
threshold fitter, and an operator who learned `route.toml` can read `retrieval.toml`.

**The ecosystem architect won the two questions where operability is the whole answer.**
`ref_unresolved` as a *view* rather than codegraph's status-lifecycle table is a genuine
improvement over the source: codegraph needs the status column because its resolution is
scope-aware, ours is by normalised string, so the anti-join is always correct and there is no
lifecycle to get wrong — and `ResolutionDelta` keeps it from ever running corpus-wide. And the
three-valued `ok | off | unavailable` capability, which makes "we deliberately have no vectors"
and "the vector channel broke" different facts, is what lets `vectors = "off"` ship as a default
without lying. Its measured brute-force numbers are the only measurements in the panel that
survived my own check: I reproduced 200,000 96-byte signature comparisons at 81 ms in CPython
3.11, within 15% of its 466 ms/1M, so the 250,000-chunk refusal is a measured ceiling and not a
guess. An honest refusal beats a five-second query nobody warned you about.

**The pragmatist won the two mechanical arguments.** A query process opens the index `mode=ro` and
therefore *cannot* write it; the ecosystem's "second write connection" for `retrieval_event` would
take the index write lock on every query, against the indexer, which is the exact contention the
whole design exists to avoid. So the query ledger is its own file. And the pragmatist is the only
architect who noticed that D2's delegation of the BM25 weights is unsatisfiable as written — which
I verified — though I decline the D2 amendment, because L4 is allowed to add index objects and
`head_fts` plus heading-spine propagation is both additive and better: it lifts the paragraphs
under a matching heading, which a title column would not.

**Three things I rejected from everyone.** A materialised transitive closure in any form
(`edge_closure`, `reach`, the CSR sidecar): each is a cache with an invalidation story and an
allowlist policy, serving a query that has no first user. LEANN's selective recomputation as a
shipped *mode*: legal under D1 and D3, declined by all three panels as a default, and I go one step
further — a mode with zero implementations at v1 is an abstraction with no user, and the
`VectorBackend` seam is where it belongs if someone wants it. And a global cross-shard `term_df`
table: a distributed statistic whose drift is silent, in exchange for making an approximation look
exact. Rank fusion plus `fusion_kind = "rank_merge"` and `shards_contributed` is the honest answer.

**Claims I checked and found wrong.** (1) The ecosystem panel states that three binding
`ALTER TABLE … ADD COLUMN … NOT NULL` statements "cannot execute" and that "each raises". Verified
on SQLite 3.45.1: they raise only against a **non-empty** table; on an empty table
`ALTER TABLE t ADD COLUMN x TEXT NOT NULL` succeeds. Its remedy — ship the columns in the base
`0001_init.sql` — is right and I adopt it, but downstream authors must not repeat the stated rule
as universal. (2) The ecosystem panel justifies `vectors = "off"` with graphify's
"0.497 recall@10 on LOCOMO … at zero embedding cost". `graphify/BENCHMARKS.md` fairness rules read
*"One shared local embedder where the system allows it: BGE-m3 (1024-d, multilingual)"* and its
LOCOMO table lists the primary `graph-expand` configuration at **~$1.40 ingest cost**, against
`$0 (shared index)` for the dense-RAG and BM25 baselines. The pragmatist caught this; the
conclusion survives, the evidence for it does not. (3) The pragmatist calls a single-column FTS5
`bm25()` weight "a no-op scalar". Verified: the weight is accepted and enters the tf-saturation
term, so it is a saturation knob, not a no-op — but it still cannot express field weighting, so
the diagnosis holds and the phrasing does not. (4) The pragmatist prices `block_tri` at "~2.6× the
primary index size"; that figure is the ecosystem panel's measurement of a `prefix='2 3'` index
(770 MB vs 290 MB at 1M blocks), not of the trigram tokenizer, and is unverified for trigram —
which is one reason trigram ships opt-in with no default. (5) The systems panel's ANN-library
licence claim is self-admittedly unverified, and its "~10⁵ chunks" brute-force ceiling is
conservative by about 2.5× against my measurement.

## Rejected

- **Chunk as the fusion key (systems)** — three of five channels are natively block-shaped, D2 makes `block_id` the only FK target and the citation unit, and its own stage two re-fuses per-block evidence with the ceiling computed one level up. The 4M-cell problem it was invented to solve is solved by the chunker's synopsis rule, which I take instead.
- **Six named plan shapes P0–P5 and `stat_hist` equi-width histograms with an independence assumption (systems)** — five of six shapes are just "which channels ran" and the sixth is a verdict; the estimate is wrong on exactly the correlated predicates real corpora have. An exact `LIMIT PREFILTER_MAX+1` probe answers the only question the planner has and deletes the whole apparatus.
- **`index_epoch` + `epoch_lease` + a reaper in the core schema (systems)** — no structure the framework ships is mutated in place outside SQLite. Epoch immutability moves behind the `VectorBackend` contract, with "return `unavailable(rebuilding)`" as the floor a third party can implement in an afternoon.
- **A per-epoch CSR adjacency above 2M edges (systems), `edge_closure` for three tree-shaped relations (pragmatist), and `reach` as a capped 2-hop closure (ecosystem)** — three shapes of the same thing: a cache with an invalidation pass and an allowlist policy, for a traversal that has no first user. codegraph does 6.4M relationships in SQLite with sub-millisecond reads; the bounded frontier BFS covers what documents need, and the moment traversal is unbounded no structure saves you.
- **`block_id` as a dense store-local integer with no shard prefix (systems)** — the asymmetry decides it: reserving 16 bits costs zero bytes at shard 0 (a laptop's ids are literally 1, 2, 3…), while adding the prefix later rewrites every FK in every deployed store. Its correct half — that cross-shard identity is content, never an id, and that `GlobalRef` is the only cross-store reference type — is adopted whole.
- **`omniweave-vector` as a twelfth first-party distribution (systems)** — the ANN backend ships from its own repository as the reference Backend, exactly as a third-party driver does under D1, so D1's eleven distributions and its one-runner `py3-none-any` CI shape are untouched. Putting it inside `omniweave-graph` (pragmatist) is worse: it would force `tree-sitter`, `graphrag-chunking` and a `<3.14` CPython ceiling onto anyone who wants vectors.
- **Amending D2's `block_fts` to two columns (pragmatist)** — the diagnosis is correct and the remedy is unnecessary. D2 says L4 adds indexes on these tables; `head_fts` plus heading-spine propagation is additive, contradicts nothing, and is better for documents because it lifts the paragraphs under a matching heading rather than only the heading.
- **`block_tri` (trigram FTS5) on by default below 5M blocks (pragmatist)** — the `exact` channel over `ref_site`/`ref_name` already covers `§12.4(b)`, `ISO27001`, `GL-4471` and `Fig. 3a`, which is most of the motivation; the 2.6× cost figure is transferred from a prefix-index measurement; and a third lexical channel dilutes the ceiling on every query that does not need it. It ships as `[retrieval] trigram = false`.
- **A global `term_df` table for cross-shard BM25 re-ranking (pragmatist)** — a distributed statistic maintained incrementally, whose staleness biases ranking silently, and whose repair is a full scan. It buys the appearance of exactness. Rank fusion with `fusion_kind` and `shards_contributed` disclosed is the honest v1.
- **`[store.vector] mode = "recompute"` (pragmatist's LEANN mode)** — a second correctness surface, a query path whose p99 depends on a model load, and retrieval that is unreproducible because nothing was stored to compare against, for a corpus size we cannot test. Zero implementations at v1 makes it an abstraction with no user; the `VectorBackend` seam is where it belongs.
- **`plan()` as a D4 rule policy for the narrowing decision too (ecosystem)** — narrowing is a closed three-way choice on an exact count, not a rule. The grammar is taken for channel selection, weights, budgets and short-circuits, where it earns the linter and the fitter.
- **`MAX_SNAPSHOT_MS = 30_000` (ecosystem)** — 30 seconds of pinned WAL is the precise condition codegraph's futility latch exists for, and the outcome it produced was 22 GB of WAL and exit 137. Five seconds is the ceiling, two the default.
- **`retrieval_event` in the main store on a second write connection (ecosystem)** — a `mode=ro` reader cannot write the main store, and a read-write telemetry connection contends with the indexer for the write lock on every query.
- **The `store_readonly` rule that a read requiring a TEMP table fails CI (ecosystem)** — verified: TEMP tables work on a `mode=ro` main connection, and materialising the narrowing set is exactly what makes exact prefiltering possible.
- **A vector database, a graph engine, or any second storage system (Qdrant, pgvector-as-a-prerequisite, Neo4j, Kùzu, DuckDB-PGQ)** — a second durability story, a second snapshot story, a second migration story and a second failure domain, before a user has parsed one document; Neo4j Community is GPLv3 into a stack D1 keeps clean with a fail-not-warn denylist. Each arrives as a `Backend` if a workload ever demands it.
- **Committing the `.owstore`, with or without graphify's merge driver** — verified in source: `nx.compose` at `graphify/graphify/cli.py:2572` is a pure union that ignores the merge base, so a node deleted on one branch and untouched on the other returns; the caps at `:2547-2548` are 50 MB / 100k nodes, two to three orders below a real corpus. `omniweave.index.lock` is line-oriented with a total order on `doc_key`, so deletion works and the merge is a sort-merge.
- **`v1_*` views as the *only* public read surface (systems)** — D2 already published the base tables in a binding ruling, and two names for one concept is worse than a published table. Instead: system-of-record tables are the contract at a `SCHEMA` major; objects marked `[DER]` are explicitly not, and `ow store sql --readonly` reads anything and writes nothing.
- **A cost-based optimiser, and a learned ranker at v1** — join-order search over an embedded store is untestable and produces plan flips that present as outages; a learned ranker has no labels on day one, cannot be linted, diffed or explained to a customer whose bill doubled, and destroys replay. Learning enters as a fitted threshold in `retrieval.toml`, never as the decider.
- **Storing float vectors as BLOBs in the main `.owstore`, and one row per vector anywhere** — 3 KB/chunk churns the writer's B-tree, WAL, backup and `VACUUM`; and a row-per-vector layout costs 2.3× a segment layout in pure SQLite cursor overhead (1072 ms vs 466 ms per million, the ecosystem panel's measurement, corroborated by mine at 81 ms/200k).
- **LEANN's linear hybrid blend, and any score blending across channels** — it adds a raw `bm25()` in the tens to a cosine, so whichever channel has the larger numeric range wins, a single-channel hit scores on the same additive scale as a consensus hit, and ties break on dict insertion order. Rank fusion is scale-free and federates; score blending does neither.

## Consequences

- **D2's open question on embedding keys is settled: both, on two different objects.** The Chunk is positional (`UNIQUE(doc_ord, gen, chunker_id, ord)`) so provenance survives; the embedding is content-addressed (`chunk_digest`) so identical text is embedded once corpus-wide and a re-parse that carries a block's `content_digest` re-uses it for free. That is LEANN's `passage_id_scheme` fork answered by taking both halves on the objects that want them.
- **D2's open question on `block_id` allocation is settled before any FK ships**: 16-bit minting shard, 48-bit sequence, shard 0 everywhere until a fabric exists. D2 asked for this decision explicitly; downstream authors must use this layout in every FK and every embedding row.
- **D3's open question on `capability.embed` is settled**: `embed_space` pins the full nine-field identity and refuses a mismatch on **both** the build and the search path, so the card keeps only `dim`, `max_tokens` and `languages` for routing.
- **D3 acquires one new obligation**: the `acquire` conformance suite must assert that a connector writes its `ingest_scope` row. Absence gate 3 is unreachable otherwise, and the failure mode is a confident zero over an incomplete corpus — the exact incident the gate exists for.
- **D3 acquires one new artefact class**: `backend.toml` plus the `omniweave.backends` entry-point group, read by D3's existing import-free loader. It is not a DriverCard, never enters `resolve()`, and is selected by name in config only.
- **D6 inherits the writer discipline**: one writer per store holding the `store.write` scoped lock, enqueue-before-lock, one transaction per `DocSink.end_page()`, and `synchronous = FULL` on any transaction committing `BILLED_API` output. Every other process is `mode=ro` on the index. D6 owns `unit_stat`'s predicate and writer; D5 owns the table.
- **D6 also inherits a generation rule**: advancing `doc.gen` must set the prior generation's blocks to `state = 1` **in the same transaction**, or the index layer holds two generations and every query double-counts.
- **D7 gets exactly one traversable edge table and it is block→block.** Entity, claim, community and report tables are D7's; they key on `block_id`, carry `origin_operator`/`origin_driver`/`driver_schema_v`/`restriction_bits`, declare identity as a UNIQUE IFNULL-folded expression index, and cascade from `block`. An entity-mediated relation reaches the traverser only by materialising `edge` rows at the mention sites with `via_entity` set, bounded by `MAX_EDGES_PER_BLOCK`. D7 also owns the `relation` vocabulary in `enum_val` and must write `ref_site` rows rather than log lines for references it cannot resolve.
- **D8 and D9 consume `FusedHit` + `Verdict` and must render `degraded_because` verbatim.** `FusedHit.span` exists so a hit can be packed sub-block. `Verdict.citable_as_absence()` is the single predicate that licenses "not found"; a `degraded` answer is success-shaped with a banner, never `isError`.
- **D10 gets `retrieval_event`, `SCORER_VERSION`, `fixtures/store/golden-queries.jsonl` and the rule that `UNKNOWN` is the zero value.** Every weight and threshold here ships as `calibration: bootstrap` and a change requires a `SCORER_VERSION` bump plus a golden-set win of ≥2 nDCG@10 points over ≥50 queries.
- **`vectors = "off"` is the shipped default**, so most first runs get four channels and a verdict that says `semantic: off`. That is a visible product limitation and the correct one; the alternative is a five-second query or numpy in core.
- **Twelve gates means many real answers are `degraded`.** On any corpus with a scanned PDF, gate 6 fires constantly. That is the truth and it will read as noise until operators learn that `degraded` means "usable, but I could not prove absence".
- **The published read schema is a public constraint.** Every `[SOR]` object above is something an outside dashboard may depend on, and breaking it is a `SCHEMA` major with a two-release deprecation window announced like a `CONTRACT` bump. `[DER]` objects are explicitly outside that promise.
- **Three files instead of one.** `rm -rf .omniweave` stays lossless, but `ow store backup` must cover all three, and a store copied without its sidecars loses vectors and query history rather than failing.
- **Zero new runtime dependencies from D5.** FTS5 ships inside CPython's SQLite, RRF is arithmetic, the brute vector backend is `int.bit_count()`, and jump consistent hash is twelve lines. Nothing here moves D1's weight gate.

## Risks

- **UPSTREAM CONFLICT: D1 §Spec *Core purity* vs D2 §Spec ¶1 and D3 §Consequences.** D1 states `omniweave-core` "depends on nothing outside the standard library, enforced by a gate that resolves it in a clean environment and asserts exactly one distribution", and its concrete `pyproject.toml` says `dependencies = []   # ENFORCED BY GATE G1. Amending this amends D1.` D2 states the opposite — "`omniweave-core` depends on `pydantic`, `zstandard` and stdlib `sqlite3`" — and additionally specifies `content_digest = blake3_128(...)`, and `blake3` is not in the standard library. D3 adds "Core's new dependency surface is `tomllib` (stdlib), a JSON Schema validator and a MessagePack codec". Three rulings, three incompatible dependency floors for one distribution. **This is not D5's call**; the minimum amendment is for the charter to pick one and re-render the other two rulings' dependency lines. D5 is written to be correct under either reading: every line of `omniweave_core/store/` and `omniweave_core/retrieve/` uses only `sqlite3`, `json`, `hashlib`, `heapq`, `array`, `struct`, `unicodedata`, `re` and `tomllib`, and `content_digest`/`chunk_digest` are consumed as opaque 16-byte BLOBs and never recomputed here. D5's only ask is that `sqlite3` remain importable from core, which holds under every reading.
- **D2 AMBIGUITY, resolved here, with the minimum amendment named.** D2's `doc` table has `doc_ord INTEGER PRIMARY KEY` alongside both a `gen` column and `UNIQUE(doc_key, gen)`, while `block` and `page` key on `(doc_ord, gen, …)`. Read as "one `doc` row per `(doc_key, gen)`", `doc_ord` changes on every re-parse and `cite = d{doc_ord}#{n}` stops resolving — contradicting D2's own "yesterday's citation still resolves". **D5 adopts the only self-consistent reading: `doc` holds one row per `doc_key`, whose `gen` is the head generation, and historical generations survive as `block`/`page` rows keyed `(doc_ord, gen)`.** Under that reading `doc.gen` *is* the head and no `doc_head` table is needed. If the charter intends the other reading, the minimum amendment is to add `doc_head(doc_key PRIMARY KEY, doc_ord, gen)` and re-key `cite` off `doc_key`, and every `ow_*_head` view here changes.
- **The block-count and bytes-per-block envelope is unresolved by 3–10×** and every size threshold above scales off it. D2 projects ~338 B/block; the ecosystem panel measured 912 B/block including FTS on a pessimistic synthetic corpus; codegraph's kernel numbers extrapolate to 10–40 GB at 10M blocks. If the real figure is 40 GB, `mmap_size = 256 MB` and `cache_size = 64 MB` become binding and T2 arrives at 5M blocks rather than 50M. A `G-SIZE` gate recording bytes-per-block per table on ten real 200-page documents, per release, is the only thing that settles it.
- **The input that breaks this design is one document with millions of blocks.** A 4M-cell spreadsheet is one `doc_key`, therefore one shard; D2's `DocSink.end_page()` commits a page at a time, so it is one enormous transaction and one enormous WAL spike, and **the valve cannot help mid-transaction** because its release condition is a full backfill and there is no commit boundary to park at. `block_sec` gets 4M rows under one section and narrowing by `doc_keys` becomes useless. The honest behaviour today is `MAX_BLOCKS_PER_DOC` with `OW_RESOURCE_LIMIT` naming the knob; the real fix is a sub-page commit boundary that D2 lists as its own open question.
- **Every fitted number here is a guess seeded from another domain.** The five RRF weights, `W_HEAD = 6.0`, `SPINE_DECAY = 0.6`, `PREFILTER_MAX`, the identity ladder's tiers and `confidence < 0.35` are transferred from code-search tuning. They ship as `calibration: bootstrap`, and the golden-set gate is the only thing that will ever make them true.
- **A pinned reader plus a bulk index still degrades.** `MAX_SNAPSHOT_MS` bounds one query; it does not bound a client that opens a fresh snapshot every twenty seconds forever. The valve escalates, fails, latches and degrades to un-valved growth, which is by design (I9) and still means the WAL grows until the client stops.
- **FTS5 ghosts are silent.** External content plus a trigger path that misses one case yields dead `block_id`s returned forever, and the `'delete'` command row must carry the OLD values exactly as indexed. `ow store verify` and the `ow doctor` count check catch it after the fact, not before.
- **`ref_site` explodes on the wrong corpus.** A patent portfolio or a statute is nearly all reference tokens; at 32 sites/block the table dwarfs everything else and the truncation `Diag` becomes 40,000 warnings nobody opens. The cap makes it bounded, not cheap.
- **The `ref_unresolved` view is only cheap because of `ResolutionDelta`.** If the delta is routinely large — a corpus where every edit renumbers headings — the anti-join runs near-corpus-wide and the resolution pass needs its own budget and a keyset cursor, at which point "the corpus grew and now this resolves" can take several runs.
- **`chunk_digest` dedup is a covert channel in a shared store.** Two tenants sharing one `.owstore` observe each other's embeddings as a timing difference. Multi-tenancy requires tenant-scoped `space_id`, which forfeits the dedup, and is not solved here.
- **A third-party `VectorBackend` that lies about filter pushdown** produces recall loss shaped like absence, and gate 9 only catches the total-wipeout case. The conformance suite tests pushdown at 0.01 selectivity; a backend that passes and later regresses is undetected.
- **Rank fusion across shards is biased toward small shards**, disclosed rather than fixed, and cross-shard `ref_name` resolution requires a broadcast, so a cross-shard citation resolves only through a periodic catalog build.
- **A Postgres T3 migration resets every quality number.** `ts_rank_cd` is not `bm25()`, `scorer_version` changes, and every scoreboard cell goes `UNKNOWN`. Documented, and it will still surprise the first operator who does it on a Friday.
- **`ow store vacuum` is a cliff.** A 40 GB store needs 40 GB free and a writer pause; `DELETE` frees pages without shrinking the file, which is a compliance-relevant fact that belongs in the docs and not in a support ticket.
- **Two writers via two `.owstore` paths for one corpus** is undetectable. `corpus_id` catches a mismatched sidecar, not a duplicated store. `ow doctor` warns; it cannot prevent.

## Terminology

- `.owstore` := the SQLite file holding one corpus — D2's model, D5's index layer, and D3/D4/D6's operational tables. The canonical local form of the model and the published read interface at a `SCHEMA` major.
- Sidecar := a derived, separately-deletable SQLite database beside the `.owstore`. Exactly two: `index.vec.owstore` (ATTACHed as `vec`) and `events.owstore`. Never part of a transaction with `main`.
- Chunk := a contiguous run of live Blocks in `(page, ord)` order under one heading ancestor, produced by a named `derive/1` chunker, bounded in blocks and characters, never crossing a `kind = TABLE` boundary. The embedding unit, the `derive/1` unit and the packing unit. **Not** the fusion key.
- chunk_digest := blake3-128 over the chunker identity, the chunk's `head_path` and its members' `content_digest`s in order. The key of an embedding row; identical contextualised text is embedded once corpus-wide.
- Channel := one named retrieval mechanism producing a totally ordered list of `block_id`s. Exactly five: `identity`, `exact`, `lexical`, `structural`, `semantic`.
- ChannelStatus := `ok | empty | off | unavailable`. `off` is an operator choice and is disclosed; `unavailable` is a degradation and forces `degraded`; a channel that raised reports `unavailable` with a reason.
- Narrowing := the tagged result of applying `Filters` — `all`, `set` (a TEMP table plus its exact row count), or `empty`. "No restriction" and "restrict to nothing" are different values of different shape.
- PREFILTER_MAX := 200,000. At or below it the narrowing set is materialised exactly and every channel, including the ANN one, filters exactly; above it, narrowing becomes an over-fetch factor.
- Heading-spine propagation := the lexical scorer's second term — a block earns a decayed share of the best BM25 score achieved by any heading on its spine, from `head_fts` over `block.title` and `block_sec`. This is what discharges D2's "D5 owns the BM25 weights".
- ceiling := `Σ weights of channels that ran / (k + 1)`, computed by the same `_weight()` as `fuse()`. `confidence = best_score / ceiling`. Never `1/(k+1)`.
- Verdict := the four-state answer (`ok | low_confidence | absent | degraded`) plus `degraded_because`, coverage, freshness, channels, scanned counts and the space identity. `state == absent` is the single rule that licenses an absence claim.
- Absence gate := one of the twelve precedence-ordered checks a zero result must pass before it may be called `absent`. A new hazard forces `degraded`; it never adds a second citability rule.
- ref_name := a row asserting that a normalised reference name (a section number, figure label, defined term, citation key) is **defined** at a Block.
- ref_site := a row recording an **occurrence** of a normalised reference name at a Block and TextSpan. `ref_unresolved` is the view of sites with no matching name.
- ResolutionDelta := the set of `ref_name.norm` values whose row set changed across a write. Every `ref_site` with a norm in the delta is re-resolved, including in documents this run never touched. This is what makes an incremental index converge with a full rebuild.
- edge := the single traversable relation table, block→block, with an optional observation site and an optional `via_entity`. Identity is a UNIQUE IFNULL-folded expression index. D7 owns the vocabulary; D5 owns the table and the traversal bounds.
- Expand := the bounded traversal request — max hops (hard cap 4), per-hop beam, total visited cap, an explicit relation allowlist, a minimum trust, and a `hub_cap` that truncates a hot node's neighbourhood and says so.
- Backend := an implementation of a store or index seam selected by name in config. Two kinds exist: a store backend (`sqlite`, `postgres`, `fabric`) and a `VectorBackend` behind the `omniweave.backends` entry-point group with a `backend.toml`. A Backend is never a Port, never a DriverCard, and never enters `resolve()`.
- embed_space := the row pinning the nine-field embedding identity (model, revision, dim, metric, normalisation, pooling, the two prompt digests, driver + schema version). A search whose embedder does not reproduce its `model_key` is refused on the search path, not only the build path.
- model_key := `sha256_canonical` of those nine fields, truncated to 16 bytes. The name a vector sidecar and a query agree on.
- Snapshot := one `BEGIN DEFERRED` read transaction held for a whole retrieval call — every channel, hydration and the coverage scan. Bounded by `MAX_SNAPSHOT_MS = 5000`, because a held read transaction pins the WAL.
- Bulk window := a marked interval during which non-UNIQUE secondary indexes and FTS triggers are dropped for a bulk load. An open marker at store open refuses to serve. The UNIQUE identity index is never dropped.
- Minting shard := the 16-bit prefix of a `block_id`, assigned once when the Block is created and never reused or rewritten. Distinct from the **placement shard**, which is `jump_consistent_hash(doc_key)` and may change on a reshard.
- GlobalRef := `(corpus_id: bytes16, block_id: int)`. The only reference type that may cross a store boundary. There are no cross-shard foreign keys.
- omniweave.index.lock := the one committed artefact — sorted plain text, one line per document, byte-stable, with a merge driver registered for that path only. The index's receipt, not the index.

## Open questions

- **What is the real chunks-per-block ratio and characters-per-chunk distribution on a mixed corpus?** Every storage projection scales off "eight blocks per chunk". Settled by running `derive.chunk.spine` over D2's `fixtures/docs/` plus ten real 200-page documents (a 10-K, a court filing, a scientific review, a spreadsheet-heavy report) and plotting the distribution; the answer retunes `TARGET_CHARS`, `MAX_CHUNK_BLOCKS` and every size table here.
- **Does binary quantisation plus an exact rerank of the top 1,000 hold recall on document chunks?** Settled by `gate_vec_recall.py`: recall@10 of `sig → top-1000 → f32 rerank` against exhaustive f32 on a fixed 50k-chunk fixture. Below 0.95 the stdlib backend ships `sig_full` only, with a smaller ceiling.
- **Is `W_HEAD = 6.0` with `SPINE_DECAY = 0.6` right, or does heading propagation promote tables of contents above the sections they name?** Settled by nDCG@10 over `golden-queries.jsonl` with `W_HEAD` swept across {1, 2, 4, 6, 12} and the `toc_entry` kind included and excluded. If the curve is flat, `head_fts` should be dropped and the lexical channel is one term.
- **Does `ResolutionDelta` actually stay empty on real edits?** codegraph's `definitionDelta` is empty for body-only code edits, but a document edit that renumbers one heading changes every downstream cross-reference key. Settled by instrumenting `|ResolutionDelta|` over 200 real edits on a 5,000-page corpus; if it is routinely large, the re-bind pass needs its own budget and a keyset cursor.
- **Which ANN library clears D1's gate G3 and ships pure wheels for {ubuntu, macos, windows} × {3.11, 3.12, 3.13}?** `usearch` and `hnswlib` both declare permissive licences and neither is in `_collections/`, so the claim is unverified. Settled by running G3's three scans (resolved graph, import graph, unpacked artifacts) against the candidate and checking wheel availability, before P5 starts. Pre-committed fallback: `vector.brute` plus the 250k refusal.
- **Does the twelve-gate verdict hold at federation scale?** Gate 3 (`coverage_incomplete`) needs a global discovered-versus-indexed count, which is a scatter of its own. Settled by measuring whether a cached per-shard coverage row refreshed on every write is accurate enough to gate a citability claim, or whether coverage must be recomputed per query.
- **Is one `edge` table right once D7 defines its relation vocabulary?** If D7 introduces a relation whose *columns* genuinely differ — a temporal claim with `start_date`/`end_date`, graphrag's covariate shape — that is a sibling table, not a column on `edge`. Settled in D7; the `edge_identity` index shape is what must not change.
- **Multi-tenancy.** The `chunk_digest` dedup leak is real and `mine-runtime.md` §7.12 lists the store shape as unresolved. Settled by a decision between store-per-tenant (LDR's `tenants × 60 × 3` file-descriptor multiplier) and row-level tenancy with tenant-scoped `space_id`; nothing in `_collections/` has evidence for the middle ground.
