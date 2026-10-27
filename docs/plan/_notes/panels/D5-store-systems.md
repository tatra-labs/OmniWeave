# D5-store — Storage, indexing, retrieval and query planning
### the systems-purist proposal

## Headline

**SQLite is the implementation and never the interface: the normative artifact is
`schema/store-v1.sql` plus four Python protocols, the public read surface is a set of versioned
`v1_*` views, and every acceleration structure — FTS5, the ANN sidecar, the CSR adjacency — is a
*derived, rebuildable, epoch-immutable* artifact whose only system of record is a transactional
table in the `.owstore`. Retrieval fuses four channels at one key, the `Chunk`, with weighted RRF
and a computed ceiling; the query planner is a closed set of six plan shapes chosen by a printed
decision table over stored statistics, not a search; and a zero result is `absent` only after
eleven gates, one of which is an indexed join against D2's `diag` table.**

---

## 0. Scope, and what is already settled

I own: the physical schema below D2's model, the index structures, the retrieval contract, the
query planner, concurrency/durability of the store, incremental index maintenance, and the
T1→T2→T3 path. I do **not** re-open the document model (D2), the driver contract (D3), or routing
(D4). Where those rulings name a type or a column I use their spelling verbatim.

Inherited and used unchanged:

| From | Binding thing I build on |
|---|---|
| D1 | `omniweave_core.store` is the **only** module that may call `sqlite3.connect`; core is stdlib-only (gate G1); pragma order `busy_timeout` first; jcodemunch's `connect_readonly` ladder; the `UPDATE … RETURNING`-free claim fallback; `SCHEMA` as the third version axis, "owned by D2/D5"; `omniweave query, warm store ≤ 250 ms` (gate G10). |
| D2 | The `.owstore` tables verbatim — `doc`, `page`, `producer`, `block`, `block_history`, `rel`, `mark`, `table_meta`, `cell`, `grid_slot`, `part`, `asset`, `block_asset`, `page_render`, `diag`, `block_fts`. `block_id` is the only FK target. `content_digest` is blake3-128, merkle, geometry-free. `trust` is an ordered INTEGER so `MIN()` is meaningful. `diag.code` is the input to the absence contract. One writer per `.owstore`. |
| D3 | `origin_driver`, `driver_schema_v`, `restriction_bits` on every produced item plus `CREATE INDEX block_restricted`; `driver_card_cache`, `driver_observation`, `resolution_report`; "**Backend** := a store implementation (SQLite, Postgres). D5's contract. Not a Port, not carded."; the `embed/1` Port. |
| D4 | `route_decision`, `route_unit_decision`, `route_evidence`, `route_signal`, `route_spend`, `route_verdict`, `route_pin`, the `route_scoreboard` view, and `work.decision_id NOT NULL`. **I invent no second decision log.** D5 owns only their physical placement (the same `.owstore`), their retention sweep, and their index set — which are exactly as D4 wrote them. |
| mine-runtime §7 | The `work` table, the claim/lease protocol, `OperatorIdentity`, `StepResult`, `origin_operator`, cache-key groups, invariants I1–I18. |

Two clarifications I state now so nothing downstream guesses (§12 explains why neither is a
conflict): `.owstore` is the *SQLite materialisation* of a schema that also has a Postgres
materialisation, and the normative thing is the schema; and D2's "L4 never adds a second
representation of a block" is honoured literally — **no structure I add stores a second copy of
block text.**

---

## 1. The one structural decision: the retrieval unit is not the Block

D2 makes cells Blocks. A merge-free 4M-cell spreadsheet is 4M Blocks (D2 §6). Embedding, ranking,
or returning 4M cells is not a tuning problem, it is a category error — and every design in the
mine that fuses "nodes" or "passages" quietly assumes one granularity. omniweave has four:

| channel | what it naturally returns |
|---|---|
| lexical (FTS5) | a Block |
| identity | a Block or a Document |
| semantic | an embedded span of text |
| structural | an Entity or a Block reached by traversal |

Fusing four differently-shaped result sets by pretending they share a key is the bug that makes
RRF weights uninterpretable. So:

> **The fusion key is the `Chunk`. The citation key is the `block_id` / `cite`. Retrieval is two
> stages: fuse to chunks, then select blocks within the winning chunks using the per-block evidence
> the lexical and identity channels already produced.**

A Chunk is a contiguous run of live Blocks in `(page, ord)` order under one spine ancestor,
produced by a named, versioned chunker, never crossing a `kind=TABLE` boundary, and bounded in
both blocks and characters. Every channel declares a **lift** to the chunk key:

```
lexical    : block  → chunk   rank = best member rank        (never rank-per-member: a 40-block
                                                              chunk must not occupy 40 slots)
identity   : block  → chunk   rank = best member rank
             doc    → chunk   rank = the doc's first chunk, and only under Plan P0
semantic   : chunk  → chunk   identity
structural : block  → chunk   rank = best reached member rank
```

This single decision is what makes the ceiling meaningful, makes `k` mean something, makes the
absence contract countable, and makes a 4M-cell sheet cost 4M cheap FTS rows and ~0 embeddings
instead of 4M embeddings.

**It also settles D2's open question** *"Do embedding rows key on `block_id` or on
`content_digest`?"* — **neither.** Chunks are positional (`UNIQUE(doc_ord, gen, chunker_id, ord)`)
so provenance survives; embeddings are content-addressed (`PRIMARY KEY (space_id, chunk_digest)`)
so identical text is embedded once corpus-wide and a re-parse that carries a Block's `block_id`
*and* its `content_digest` re-uses the embedding for free. That is LEANN's
`passage_id_scheme ∈ {sequential, content_hash}` fork answered by taking **both**, on the two
different objects that actually want them.

---

## 2. Physical schema

`schema/store-v1.sql` is generated-then-committed and byte-diff gated exactly like D1's
`schema/document-v1.json` (gate G6 extended). It is the specification both backends are diffed
against. It is **not** an API — §3.

```sql
-- ============================================================================
-- D5 additions to the .owstore.  SCHEMA = 1.  Every table below is either
-- (a) a system of record, or (b) derived-and-rebuildable and marked DERIVED.
-- No table here stores a second copy of block.text  (D2 consequence 1).
-- ============================================================================

-- ---------- corpus / shard identity -------------------------------------------------
CREATE TABLE corpus (
  corpus_id     BLOB PRIMARY KEY,        -- 16B random, minted once, NEVER derived from a path
  shard_ord     INTEGER NOT NULL,        -- this store's slot in the routing table; 0 when standalone
  vshard_lo     INTEGER NOT NULL,        -- inclusive  \ the virtual-shard range this store owns
  vshard_hi     INTEGER NOT NULL,        -- inclusive  / of 4096.  Standalone: 0..4095
  schema_v      INTEGER NOT NULL,
  created_ns    INTEGER NOT NULL
) WITHOUT ROWID;
-- INVARIANT S14: there is no foreign key in this schema whose target may live in another store.
-- Cross-shard identity is doc_key / content_digest / chunk_digest / entity_key — content, not ids.

-- ---------- the retrieval unit ------------------------------------------------------
CREATE TABLE chunker (
  chunker_id    INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,           -- 'spine/1'  |  'table/1'  |  'fixed/1'
  version       INTEGER NOT NULL,        -- bumped when the SEGMENTATION changes
  params_digest BLOB NOT NULL,           -- sha256_canonical of the flat Scalar params
  UNIQUE (name, version, params_digest)
);

CREATE TABLE chunk (
  chunk_id      INTEGER PRIMARY KEY,     -- store-local, dense, cheap varint  (see §9)
  doc_ord       INTEGER NOT NULL,
  gen           INTEGER NOT NULL,
  chunker_id    INTEGER NOT NULL REFERENCES chunker(chunker_id),
  ord           INTEGER NOT NULL,        -- position of this chunk within (doc_ord, gen, chunker)
  chunk_digest  BLOB NOT NULL,           -- §2.1 recipe.  The join key to `embedding`.
  lo_block      INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  hi_block      INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  n_blocks      INTEGER NOT NULL,
  n_chars       INTEGER NOT NULL,
  head_path     TEXT NOT NULL,           -- 'Introduction / 2.1 Scope'  — headings, NOT body text
  head_addr     TEXT NOT NULL,           -- D2 addr of the first member; what a citation displays
  page_lo       INTEGER NOT NULL, page_hi INTEGER NOT NULL,
  trust_min     INTEGER NOT NULL,        -- MIN(block.trust) over members  (D2 §8: MIN() is useful)
  quote_min     INTEGER NOT NULL,        -- MIN(block.quote): gates serve's byte-exactness claim
  restriction_bits INTEGER NOT NULL DEFAULT 0,  -- OR over members            (D3-17)
  kind_mask     INTEGER NOT NULL,        -- bitmask over D2 Kind: pre-filter without a join
  state         INTEGER NOT NULL DEFAULT 0,     -- 0 live, 1 retired
  UNIQUE (doc_ord, gen, chunker_id, ord)
);
CREATE INDEX chunk_digest_ix ON chunk(chunk_digest);            -- → embedding
CREATE INDEX chunk_doc       ON chunk(doc_ord, gen, page_lo) WHERE state = 0;
CREATE INDEX chunk_restricted ON chunk(restriction_bits) WHERE restriction_bits <> 0;

CREATE TABLE chunk_block (        -- DERIVED from (lo_block, hi_block); materialised only when the
  chunk_id INTEGER NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,   -- run is non-contiguous
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,   -- (furniture skipped)
  PRIMARY KEY (chunk_id, block_id)
) WITHOUT ROWID;
CREATE INDEX chunk_block_rev ON chunk_block(block_id);
-- Contiguous chunks store ZERO rows here and membership is `block_id BETWEEN lo_block AND hi_block`
-- restricted to state=0 — the same "derived and lazily materialised" trick D2 used for grid_slot.

-- ---------- the semantic channel ----------------------------------------------------
CREATE TABLE embed_space (
  space_id        INTEGER PRIMARY KEY,
  model_id        TEXT NOT NULL,
  model_rev       TEXT NOT NULL,        -- EXACT sha. 'main' is refused at insert (S5) and lint-gated
  driver          TEXT NOT NULL,        -- D3 DriverId, e.g. 'embed.text.bge_m3'
  driver_schema_v INTEGER NOT NULL,
  dim             INTEGER NOT NULL,
  metric          TEXT NOT NULL CHECK (metric IN ('cosine','ip','l2')),
  normalize       INTEGER NOT NULL,
  pooling         TEXT NOT NULL,
  tokenizer_digest    BLOB NOT NULL,
  doc_prompt_digest   BLOB NOT NULL,    -- applied ONCE, client side, at build   (anti-LEANN)
  query_prompt_digest BLOB NOT NULL,    -- applied ONCE, client side, at query
  quant           TEXT NOT NULL CHECK (quant IN ('f32','i8','b1')),
  created_ns      INTEGER NOT NULL,
  UNIQUE (model_id, model_rev, driver, driver_schema_v, dim, metric, normalize, pooling,
          tokenizer_digest, doc_prompt_digest, query_prompt_digest, quant)
);
-- LEANN's meta.json, as a table with a UNIQUE constraint instead of a JSON file with a README rule.

CREATE TABLE embedding (          -- SYSTEM OF RECORD.  The ANN sidecar is derived from this.
  space_id     INTEGER NOT NULL REFERENCES embed_space(space_id) ON DELETE CASCADE,
  chunk_digest BLOB NOT NULL,
  vec          BLOB NOT NULL,     -- dim bytes (i8) | dim/8 bytes (b1) | 4*dim (f32, dim<=256 only)
  vnorm        REAL,              -- pre-normalisation L2, kept so a metric change is a re-quantise
  PRIMARY KEY (space_id, chunk_digest)
) WITHOUT ROWID;
-- Content-addressed: one embedding per distinct chunk text per space, corpus-wide, forever.

-- ---------- the cross-document graph (D7 owns the SEMANTICS; D5 owns the STORAGE) ----
CREATE TABLE entity (
  entity_id   INTEGER PRIMARY KEY,
  entity_key  TEXT NOT NULL,      -- graphify ids.py recipe: bounded NFKC/casefold fixpoint,
                                  -- re.UNICODE charset filter. SHARD-INDEPENDENT by construction.
  kind        INTEGER NOT NULL,
  title       TEXT NOT NULL,
  frequency   INTEGER NOT NULL DEFAULT 0,   -- corpus salience  (graphrag: len(text_unit_ids))
  degree      INTEGER NOT NULL DEFAULT 0,   -- graph salience — RECOMPUTED on merge, never "first"
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL,
  origin_operator TEXT NOT NULL,
  UNIQUE (entity_key, kind)
);
CREATE TABLE entity_alias (entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                           alias_key TEXT NOT NULL, PRIMARY KEY (alias_key, entity_id)) WITHOUT ROWID;
CREATE TABLE entity_mention (entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                             block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
                             ts_a INTEGER, ts_b INTEGER,    -- D2 TextSpan inside block.text
                             PRIMARY KEY (entity_id, block_id, IFNULL(ts_a,-1)));

CREATE TABLE edge (               -- ONE edge table. Producer is a column, not a table. (§7.2)
  edge_id     INTEGER PRIMARY KEY,
  src_kind    INTEGER NOT NULL,   -- 0=block 1=entity   (closed, 2 values, CHECK-ed)
  src_id      INTEGER NOT NULL,
  dst_kind    INTEGER NOT NULL,
  dst_id      INTEGER NOT NULL,
  relation    INTEGER NOT NULL,   -- D7's closed vocabulary; direction rule documented per relation
  site_block  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,  -- WHERE it was observed
  weight      REAL NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL,
  origin_operator TEXT NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  CHECK (src_kind IN (0,1) AND dst_kind IN (0,1))
);
-- Identity in the SCHEMA, IFNULL-folded, or INSERT OR IGNORE is a plain INSERT (codegraph #1034).
CREATE UNIQUE INDEX edge_identity ON edge(
    src_kind, src_id, dst_kind, dst_id, relation, producer_id, IFNULL(site_block,-1));
CREATE INDEX edge_out ON edge(src_kind, src_id, relation);   -- left-prefix covers src-only lookups
CREATE INDEX edge_in  ON edge(dst_kind, dst_id, relation);   -- codegraph drops the narrow ones
-- DELIBERATELY ABSENT: idx_edge_src, idx_edge_dst. The composites cover them by left-prefix scan
-- and the narrow indexes are dead weight on the write path (codegraph schema.sql:157-167).

-- ---------- the residue is data  (codegraph's biggest idea, ported) -----------------
CREATE TABLE unresolved_ref (
  ref_id      INTEGER PRIMARY KEY,
  from_block  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ref_kind    INTEGER NOT NULL,   -- section_number | figure_label | table_label | citation_key
                                  -- | defined_term | cross_doc_uri | anchor
  ref_text    TEXT NOT NULL,      -- '§4.2'  'Figure 7'  '[Smith2019]'  'the Agreement'
  retry_key   TEXT NOT NULL,      -- normalised tail: '4.2' | '7' | 'smith2019'
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','failed')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_seen_gen INTEGER NOT NULL
);
CREATE INDEX unresolved_failed ON unresolved_ref(retry_key) WHERE status = 'failed';
-- resolved ⇒ the row is DELETED and an `edge` row is written. On a healthy index the pending set
-- is empty, so only the failed set is worth indexing (codegraph migrations.ts v8).

CREATE TABLE anchor (             -- the resolvable target namespace of a corpus
  anchor_key  TEXT NOT NULL,      -- '§4.2' normalised; scoped by doc unless global_scope=1
  doc_ord     INTEGER NOT NULL,   -- -1 for a corpus-global anchor (a defined term, a citation key)
  block_id    INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  kind        INTEGER NOT NULL,
  PRIMARY KEY (anchor_key, doc_ord, block_id)
) WITHOUT ROWID;

-- ---------- the identity channel's tokenizer escape hatch ---------------------------
CREATE TABLE term_vocab (         -- DERIVED. Rows are PROPOSALS, re-verified at read time,
  segment  TEXT NOT NULL,         -- so there is NO delete path and no consistency bug class.
  block_id INTEGER NOT NULL,      -- (codegraph name_segment_vocab, exact discipline)
  PRIMARY KEY (segment, block_id)
) WITHOUT ROWID;

-- ---------- the lexical channel: TWO external-content FTS tables, ZERO text copies ---
--   block_fts(text) is D2's, verbatim, unchanged.
CREATE VIRTUAL TABLE head_fts USING fts5(
  title, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');
-- + the three AFTER INSERT/DELETE/UPDATE sync triggers, same idiom as block_fts.
-- `block.title` is NULL on text blocks (D2), so head_fts indexes only headings, captions, figure
-- and table titles: a few percent of rows. This is where D5's BM25 weighting lives (§5.1) and it
-- is what a five-column FTS would have cost a second copy of body text to buy.

-- ---------- derived-structure epochs: the snapshot-isolation mechanism (§6.3) --------
CREATE TABLE index_epoch (
  kind        TEXT NOT NULL CHECK (kind IN ('ann','csr')),
  space_id    INTEGER,             -- NULL for csr
  epoch       INTEGER NOT NULL,
  rel_path    TEXT NOT NULL,       -- 'vec/3/epoch-000042'   — relative to the store dir, always
  state       TEXT NOT NULL CHECK (state IN ('building','live','retiring')),
  n_base      INTEGER NOT NULL DEFAULT 0,
  n_delta     INTEGER NOT NULL DEFAULT 0,
  n_tombstone INTEGER NOT NULL DEFAULT 0,
  built_at_ns INTEGER NOT NULL,
  manifest_sha256 BLOB NOT NULL,
  PRIMARY KEY (kind, IFNULL(space_id,-1), epoch)
) WITHOUT ROWID;
CREATE UNIQUE INDEX index_epoch_live ON index_epoch(kind, IFNULL(space_id,-1)) WHERE state = 'live';
--                                    ^ AT MOST ONE LIVE EPOCH PER (kind, space). Enforced, not agreed.

CREATE TABLE epoch_lease (        -- a reader's claim on a derived file it has mmap'd
  kind TEXT NOT NULL, space_id INTEGER, epoch INTEGER NOT NULL,
  holder TEXT NOT NULL,           -- "<host>:<pid>:<create_time>"  (never a bare pid)
  expires_ns INTEGER NOT NULL,
  PRIMARY KEY (kind, IFNULL(space_id,-1), epoch, holder)
) WITHOUT ROWID;

-- ---------- statistics for the planner (§4.3) ---------------------------------------
CREATE TABLE stat (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, computed_ns INTEGER NOT NULL, n_sampled INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE stat_hist (          -- equi-width histograms for the four pushable filter columns
  col TEXT NOT NULL,              -- 'doc.format' | 'block.kind' | 'block.layer' | 'chunk.page_lo'
  bucket TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (col, bucket)
) WITHOUT ROWID;

-- ---------- retrieval telemetry (NOT a second routing log — D4 owns routing) ---------
CREATE TABLE retrieval_event (
  event_id INTEGER PRIMARY KEY,
  ts_ns INTEGER NOT NULL,
  query_digest BLOB NOT NULL,     -- sha256_canonical(text, filter, k, scope) — the text is NOT stored
  plan_shape TEXT NOT NULL,       -- 'P0'..'P5'
  scorer_version INTEGER NOT NULL,
  weights_digest BLOB NOT NULL,
  space_id INTEGER, ann_epoch INTEGER, csr_epoch INTEGER,
  channels_ran TEXT NOT NULL,     -- JSON {channel: ok|off|unavailable|starved}
  card_est INTEGER NOT NULL, card_actual INTEGER NOT NULL,   -- planner honesty: est vs actual
  overfetch_factor REAL NOT NULL,
  n_returned INTEGER NOT NULL, matches_before_packing INTEGER NOT NULL,
  best_score REAL, score_ceiling REAL,
  verdict TEXT NOT NULL, degraded_because TEXT NOT NULL DEFAULT '[]',
  wall_ms INTEGER NOT NULL, read_txn_ms INTEGER NOT NULL,
  producer_version TEXT NOT NULL  -- so a future bug fix never needs a ledger_trust.py
);
CREATE INDEX retrieval_event_ts ON retrieval_event(ts_ns);
CREATE INDEX retrieval_event_bad ON retrieval_event(ts_ns) WHERE verdict <> 'ok';

-- ---------- the public compatibility surface (§3) -----------------------------------
CREATE VIEW v1_block  AS SELECT block_id, doc_ord, gen, page, addr, cite, parent_id, ord, kind,
                                layer, title, text, trust, quote, origin_driver, restriction_bits
                         FROM block WHERE state = 0;
CREATE VIEW v1_chunk  AS SELECT chunk_id, doc_ord, gen, ord, head_path, head_addr, page_lo, page_hi,
                                n_blocks, n_chars, trust_min, quote_min, restriction_bits
                         FROM chunk WHERE state = 0;
CREATE VIEW v1_doc    AS SELECT doc_ord, hex(doc_key) AS doc_key, uri, media_type, format,
                                page_count, status, gen FROM doc;
CREATE VIEW v1_diag   AS SELECT doc_ord, gen, page, block_id, code, severity, message FROM diag;
-- These four views ARE the SQL contract. The base tables are not (S18).
```

### 2.1 The chunk digest recipe (`chunk_recipe = 1`)

```
chunk_digest = blake3_128(canonical([
    chunker.name, chunker.version, chunker.params_digest,
    head_path,                                   -- contextualisation is PART of what was embedded
    [b.content_digest for b in members in (page, ord) order],
]))
```

`head_path` is in the digest because contextualised text is what the embedder saw; leaving it out
would let a heading rename silently serve a stale vector. `block_id`, `addr`, `cite`, `page`,
geometry, `producer_id`, `trust` and `origin_operator` are **not** inputs — a driver upgrade that
changes provenance without changing text must not re-bill an embedding. Every input is a stored
field, so a `chunk_recipe` bump is a re-digest pass, never a re-parse (D2's constraint, restated).

### 2.2 The chunker, and the input that breaks naive chunking

```
spine/1 :  walk blocks in (page, ord) order under one nearest ancestor of kind
           {SECTION, TITLE, HEADING, DOCUMENT}; emit when
             n_chars >= TARGET_CHARS (1600)  or  n_blocks >= MAX_CHUNK_BLOCKS (64)
             or the ancestor changes  or  the next block has kind TABLE
           overlap: OVERLAP_BLOCKS = 1 whole block, never a character window
           layers: {BODY} by default; furniture/notes/annotation are separately chunked and
                   carry a lane tag, never merged into body chunks (D2's `layer` column)

table/1 :  a TABLE block becomes chunks of whole rows with the header rows REPEATED in each,
           bounded by TABLE_CHUNK_CHARS (1600) and TABLE_MAX_CHUNKS (32).
           Above TABLE_SYNOPSIS_CELLS = 20_000 the table yields exactly ONE synopsis chunk
             (header rows + n_rows/n_cols + 8 sampled rows + per-column type/range stats)
           and emits Diag(code='OW_TABLE_SYNOPSIS_ONLY', detail={cells}).
           The cells stay fully lexically indexed and fully citable; they are simply not embedded.
```

That last rule is the priced answer to the 4M-cell sheet: **4,000,000 FTS rows and 1 embedding.**
It is a real capability loss (semantic search cannot find a cell by paraphrase in a huge sheet), it
is visible in `diag`, it forces `degraded` in the absence contract when a query's scope touches
such a table, and it is a `[chunkers]` policy an operator can widen at a stated cost.

---

## 3. SQLite is the implementation. The interface is four protocols plus four views.

```python
# omniweave_core/store/__init__.py  — stdlib only (gate G1)

# ---- D1's four-method Store protocol, KEPT VERBATIM. I do not widen it. ----
class Store(Protocol):                       # the T1→T2→T3 distribution seam (mine-runtime §7.10.2)
    def claim(self, batch: int, gen: int, worker: str, lease_ms: int) -> Sequence[WorkRow]: ...
    def complete(self, row_id: int, gen: int, result: StepResult) -> bool: ...
    def reap_expired_leases(self, now_ms: int) -> int: ...
    def counts_by_status(self) -> Mapping[str, int]: ...

# ---- three SIBLING protocols in the same module. Separate, deliberately. ----
class Corpus(Protocol):
    """Transactional read/write of the model. One implementation per Backend."""
    def open_snapshot(self) -> "Snapshot": ...          # BEGIN DEFERRED + epoch pin
    def writer(self) -> "WriteLane": ...                # exclusive; at most one per process
    def sink(self, doc: DocRecord) -> DocSink: ...      # D2's DocSink, one txn per end_page()
    def migrate(self, to: int) -> MigrationReport: ...

class Lexicon(Protocol):
    """The lexical channel. FTS5 on SQLite; tsvector+GIN on Postgres; the CONTRACT is ranks."""
    def search(self, q: "LexQuery", cand: "Candidates", limit: int) -> "ChannelResult": ...

class VectorIndex(Protocol):
    """A Backend, not a Port (D3 terminology). Derived from `embedding`, always rebuildable."""
    def search(self, space_id: int, qv: bytes, k: int, cand: "Candidates") -> "ChannelResult": ...
    def build(self, space_id: int, src: Iterable[tuple[bytes, bytes]], out: Path) -> "EpochManifest": ...
    def open_epoch(self, path: Path) -> "OpenEpoch": ...
    def capabilities(self) -> "VectorCaps": ...   # (max_n, quants, supports_prefilter, mmap)
```

**Why SQL is not the API.** The moment a user's tool selects from `block`, the physical schema is
frozen: I cannot add a covering column, split a hot table, or change an index without breaking
somebody. But people genuinely want `sqlite3 index.db`. So the answer is the ordinary database
answer, and it costs nothing: **the base tables are private; `v1_block`, `v1_chunk`, `v1_doc` and
`v1_diag` are the compatibility surface**, `ow sql --readonly '<SELECT…>'` refuses any statement
naming a non-`v1_` object, and `SCHEMA` versions the views, not the tables. Analytics goes through
`ow export parquet` (which D2 already ships) and `ow export duckdb`.

**Why the DDL is still normative.** It is the only artifact a SQLite backend and a Postgres backend
can be diffed against, and it is the thing a reviewer reads. `tools/schemagen.py --check` is
extended to emit and byte-diff `schema/store-v1.sql`, so a physical-schema change shows up in a PR
as a diff even though it is not a public API.

---

## 4. The query planner

### 4.1 The IR

```python
Candidates = Literal["ALL"] | frozenset[int]     # a SUM TYPE, not Optional[frozenset]
# jcodemunch's measured bug — an empty candidate set was falsy, skipped the filter, and returned
# "the whole repository ranked by centrality" on a nonsense query, which ALSO made `absent`
# unreachable. Here "ALL" and frozenset() are different values of different shape; the falsy
# collapse is unrepresentable, not merely discouraged.

@dataclass(frozen=True, slots=True)
class Filter:                       # composes into D2's `Scope`; closed, pushable, no expressions
    doc_keys:   frozenset[bytes] | None = None
    uri_prefix: str | None = None
    formats:    frozenset[str] | None = None
    kinds:      frozenset[Kind] | None = None
    layers:     frozenset[Layer] = frozenset({Layer.BODY})
    pages:      range | None = None
    min_trust:  Trust | None = None
    min_quote:  Quote | None = None
    gen:        Literal["current"] | int = "current"
    deny_restriction_bits: int = 0        # set by policy, never by the caller (D3-17)

@dataclass(frozen=True, slots=True)
class Query:
    text: str = ""
    anchors: tuple[str, ...] = ()        # explicit cite/addr/§/label tokens the caller supplies
    filter: Filter = Filter()
    channels: frozenset[Channel] = frozenset({LEXICAL, IDENTITY, SEMANTIC, STRUCTURAL})
    space_id: int | None = None          # None ⇒ the corpus default space
    k: int = 20
    max_blocks_returned: int = 200
    deadline_ms: int = 2000
    expand: "Expand | None" = None       # structural traversal budget, §7.3
```

### 4.2 Six plan shapes. A closed set, chosen by a printed decision table.

I reject a general cost-based optimiser. Join-order search over an embedded store is a decade of
work, is untestable, and produces plan flips that look like outages. A closed plan space is
auditable, has a finite test matrix, and is still right in five years.

| shape | when | what it does |
|---|---|---|
| **P0 `IDENTITY_EXACT`** | `anchors` resolves, or `text` parses as a `cite`/`addr`/`doc_key`/uri | one index seek; no fusion; `ceiling` is not reported because no ranking occurred |
| **P1 `NARROW_PREFILTER`** | `card_est(filter) ≤ PREFILTER_MAX (200_000)` | materialise `Candidates` as a `frozenset[chunk_id]`, run every requested channel restricted to it, fuse. **Exact filtering; no over-fetch; no recall loss.** |
| **P2 `LEXICAL_LEAD`** | semantic not requested, or no live epoch for `space_id` | FTS5 over-fetch `5×k` (min 100), identity + structural rescore over that candidate set, fuse |
| **P3 `HYBRID_FUSE`** | the default | lexical `5×k`, semantic `k × overfetch_factor`, identity, fuse to `m = 4×k`, then structural expansion seeded from the top-`m`, refuse |
| **P4 `STRUCTURAL_SEED`** | `expand` is set and seeds resolve | resolve seeds → bounded beam traversal → score within the reached set |
| **P5 `REFUSE`** | a *requested* channel has no live implementation | zero results, `verdict.state = degraded`, `degraded_because = ["channel_unavailable:<c>"]`, and the exact command that fixes it. **Never a silent fallback to the channels that do work.** |

`overfetch_factor = clamp(1 / max(sel_est, 1e-4), 1.0, OVERFETCH_MAX = 64.0)`. If post-filtering
the over-fetched ANN result yields `< k` survivors, the plan sets `filter_starved` and the verdict
goes `degraded`. That is LEANN's unmitigated post-filter trap — *"silent recall loss shaped exactly
like absence"* — converted into a named, countable, user-visible condition.

**One rule above all others, and it is codegraph's:** *filters narrow; channels score within the
narrowed set.* Every channel takes `Candidates`. No channel post-filters on its own.

### 4.3 Statistics, and honesty about them

`stat` / `stat_hist` are refreshed by `ow index analyze` (also run automatically at the end of any
write lane that touched > 1% of rows, off-thread, like codegraph's `PRAGMA optimize`). Selectivity
is a product of per-predicate selectivities under an independence assumption — which is **wrong**,
and the mitigation is measurement, not a smarter model: every `retrieval_event` records
`card_est` and `card_actual`, and `ow index tune --estimates` fails CI when the 7-day median ratio
leaves `[0.25, 4.0]`. That is D4's `--estimates` gate applied to the planner, deliberately.

### 4.4 `ow query explain`

```
$ ow query explain "obligations of the Supplier under §4.2" --kind paragraph --format pdf

plan P1 NARROW_PREFILTER   scorer v1  weights sha256:9c1e…  space 3 (bge-m3@a1b2c3, i8)
                           ann epoch 42 (live, base 1_204_881 + delta 9_113 - tomb 402)
filter        doc.format='pdf' ∧ block.kind=paragraph ∧ layer=body ∧ gen=current
  card_est    18_402   (hist doc.format 0.61 × block.kind 0.34 × layer 0.97, independence)
  card_actual 17_991   (ratio 0.98)
candidates    frozenset[17_991]  → PREFILTER (≤ 200_000)
channels      identity  ok    2 hits   tier=anchor_exact(50)  '§4.2' → p14/3 via anchor
              lexical   ok  100 hits   bm25(block_fts)×1.0 + bm25(head_fts)×6.0
              semantic  ok   64 hits   overfetch 1.0 (prefiltered, exact)
              structural ok  31 hits   beam 64 × 2 hops from top-80, relations {defines,refers_to}
fuse          RRF k=60  ceiling 4.2/61 = 0.06885   best 0.05902 (86% of ceiling)
verdict       ok         scanned 17_991 chunks / 412 documents
budget        wall 84 ms   read_txn 84 ms / 5000 ms   0 billed calls
```

---

## 5. The four channels

### 5.1 Lexical — two external-content FTS tables, and D5's two weights

Query sanitisation is a **semantic transform**, not escaping (codegraph `queries.ts:1476-1495`,
adapted to documents):

```
§ ¶ † ‡ · —  →  space          (a section sign must not glue to its number)
strip FTS5 specials  ' " * ( ) : ^ -
drop bare AND OR NOT NEAR      (a user may not inject FTS5 syntax)
cap at MAX_QUERY_TERMS = 64    (a 10k-term paste is a DoS, not a query)
de-hyphenate line-break artifacts: 'inter- national' → try {internationa l, inter national}
unknown 'foo:bar' passes through as plain text  ← so searching 'TODO:' returns results
field DSL: kind: page: doc: format: lang: trust: — validated against the closed vocabularies
```

Scoring, and this is where "D5 owns the BM25 weights" (D2 §11) is discharged:

```
block_score(b) = 1.0 × |bm25(block_fts)|
               + 6.0 × max over ancestors a of b in the heading spine of |bm25(head_fts, a)|
                       decayed by 0.6^(spine distance)
chunk_rank      = rank over  Σ of the top-3 member block_scores, divided by (n_chars/1600)^0.25
```

Two weights, not five, because there are exactly two indexed fields and both are justified: a
heading match is evidence about the whole chunk, a body match is evidence about one block. The
`0.6^distance` decay and the top-3 cap are fitted parameters with a golden-set CI gate, shipped
as `calibration: bootstrap` until an eval set is registered — D4's discipline, applied here.

**Over-fetch 5× before re-rank** (codegraph, verbatim reasoning): a re-ranker that only sees the
base scorer's top-k cannot promote anything the base scorer buried.

**No `catch { return []; }`.** codegraph's FTS failure path turns a malformed query into a
confident zero; here a channel failure returns `ChannelResult(status=FAILED, detail=…)` and the
verdict goes `degraded`. That is a one-line difference with an enormous behavioural one.

### 5.2 Identity — a graded ladder with the normalisation distance named

```
anchor_exact      50   '§4.2' | 'Table 3.2' | 'Figure 7'  resolving through `anchor`
cite_exact        50   'd7#412'
addr_exact        50   'p14/3'
doc_uri_exact     50
doc_key_prefix    48   ≥ 8 hex chars
title_exact       45   case-folded only
title_normalised  40   needed MORE than case: punctuation, separators, NFKC
title_prefix      30
term_segment      20   via term_vocab, RE-VERIFIED against `block` at read time
none               0
```

The 40 tier exists for the reason jcodemunch measured: collapsing it into 50 let a
punctuation-different match tie with a literal one and the tie fell through to BM25 — *a test
fixture outranking the symbol it tests by 0.355 points out of ~58.* The document analogue is a
figure caption "Table 3.2 (revised)" tying with the actual "Table 3.2". `identity_tier` is
reported and must name the grade actually measured.

### 5.3 Semantic — two backends, one contract, and no daemon in the default path

**The embedder is a D3 `embed/1` Driver. The vector index is a D5 Backend. The `embedding` rows are
core store tables.** Those three sentences are the whole answer to "are embeddings core or an
operator".

Two backends ship:

| backend | where | mechanism | envelope |
|---|---|---|---|
| `exact/b1` | **`omniweave-core`, stdlib only** | 1-bit-per-dim binary quantisation; Hamming via `int.bit_count()` (3.10+, and D1's floor is 3.11); full scan; then re-rank the top `RERANK_N=1000` against the `i8` vectors in `embedding` | measured against D1's `omniweave query, warm store ≤ 250 ms` gate; the CI benchmark sets the published ceiling, estimated at **~10⁵ chunks** |
| `ann/usearch` | `omniweave-vector` (a **twelfth** distribution — §12) | mmap'd HNSW over `i8`, per-epoch immutable, base + delta + tombstone bitmap | 10⁸ chunks per shard |

The exact backend is not a toy. A 100k-chunk laptop corpus — the overwhelming majority of first
runs — gets semantic search with **zero third-party dependencies, zero daemons, zero index build,
and exact recall**. That is worth a great deal and it is the only reason `pip install omniweave`
can offer vectors at all under gate G1.

**LEANN's selective recomputation is rejected as the default and kept as a mode.** D3 permits an
embedding Service over a 0600 UDS, so it is *implementable*; I decline it as the default on three
grounds: recompute-on-read makes p99 latency depend on a daemon's liveness; it makes retrieval
non-reproducible the moment the model file changes underneath (there is no digest to check because
nothing was stored); and D1 §S3 plus the security digest's ZMQ finding make a long-lived local
embedding listener the single surface I least want on by default. What I **do** take whole is
LEANN's discipline: the storage/compute trade is a **validated flag pair stamped in the index
metadata**, so `embed_space.quant` is a column, the illegal combination is a CHECK, and a searcher
discovers the mode from the store instead of a README sentence.

**Double-templating is made unrepresentable.** `doc_prompt_digest` and `query_prompt_digest` are
separate columns of `embed_space`; the searcher asserts the query embedder's template digest equals
`query_prompt_digest` before the search runs. LEANN filters templates out of the server options at
runtime and documents why; here it is a schema constraint.

### 5.4 Structural — an edge table plus a per-epoch CSR, never a graph engine

Multi-hop over SQLite is a recursive CTE with one index seek per frontier node per hop. At fan-out
30 and 3 hops that is ~27k seeks ≈ tens of milliseconds — fine. At fan-out 300 it is 27M seeks —
not fine. So:

```
edge_count ≤ CSR_THRESHOLD (2_000_000)   → recursive CTE over edge_out / edge_in
edge_count >  CSR_THRESHOLD              → the CSR sidecar, an EPOCH artifact:
    csr/epoch-NNNNNN/{manifest.json, offsets.i64, neighbours.i64, relation.u8, weight.f32}
    mmap'd, read-only, built by the same builder that builds an ANN epoch, from the SAME
    transactional `edge` table, and therefore rebuildable at any time (S2).
```

Both are behind one `Traverser` protocol and both are **bounded by construction**:

```python
@dataclass(frozen=True, slots=True)
class Expand:
    max_hops: int = 2                 # HARD CAP 4
    beam: int = 64                    # per hop, ordered by (weight × trust) / log1p(combined_degree)
    relations: frozenset[int] = ...   # NEVER "all relations"
    min_trust: Trust = Trust.INFERRED
    hub_cap: int = 4096               # an entity with more edges than this contributes at most
                                      # hub_cap neighbours, sampled by weight, and sets
                                      # degradations += ["hub_capped:<entity>"]
```

`hub_cap` is the thing that keeps a 10B-block corpus queryable: a hub entity with 50M edges is not
a traversal, it is an outage, and the honest response is a capped expansion that *says* it capped.

### 5.5 Fusion — `fuse()` and `ceiling()` as one artifact

```python
RRF_K = 60
DEFAULT_WEIGHTS = {"identity": 2.0, "lexical": 1.0, "semantic": 0.8, "structural": 0.4}

def _weight(ch: ChannelResult, w: Mapping[str, float]) -> float:
    return ch.weight if ch.weight is not None else w.get(ch.name, 1.0)   # 0.0 is a VALUE, not absent

def fuse(chs, *, k=RRF_K, weights=None) -> list[FusedChunk]: ...
def ceiling(chs, *, k=RRF_K, weights=None) -> float: ...    # Σ_weight / (k+1); SAME _weight()

# INVARIANT S9: a property test builds a perfect-consensus set and asserts fuse()[0].score ==
# ceiling(). Weights resolve through ONE function or the ceiling silently rescales every
# confidence. With the defaults the all-channel ceiling is 4.2/61 = 0.06885 and the
# lexical+identity ceiling is 3.0/61 = 0.04918 — NEVER hardcode 1/(k+1).

@dataclass(frozen=True, slots=True)
class FusedChunk:
    chunk_id: int
    chunk_digest: bytes                        # the cross-shard tiebreak key
    score: float
    channel_contributions: Mapping[str, float]
    channel_ranks: Mapping[str, int]
# Total order: sorted by (-score, chunk_digest). chunk_digest, NOT chunk_id, because chunk_id is
# store-local and a federated query must be deterministic regardless of which shard answers first.
```

**Stage two — within-chunk block selection.** For each surviving chunk, return the members ordered
by `block_score` (already computed by the lexical channel) with identity hits promoted, capped at
`max_blocks_returned`. The chunk is the unit of *ranking*; the block is the unit of *citation*.

---

## 6. Concurrency, durability, snapshot isolation

### 6.1 The write side

- **One writer per `.owstore`** (D2). Cross-process: mine-runtime's `process_locks`-shaped scoped
  lock, `scope="store.write"`, `(host, pid, process_create_time)` liveness, `INTERACTIVE_WAIT = 2 s`
  / `BATCH_WAIT = 60 s` passed per call, never a constant. **Enqueue before attempting the lock** —
  the trigger writes its `work` rows first, then tries the lock, and returns immediately if held,
  because the holder's next `claim()` is a superset.
- **One `WriteLane` thread inside the writer.** All producers push `WriteOp` batches; the lane owns
  the only read-write connection. This is what makes the pragma set, the valve, and the bulk window
  reasonable about state instead of hopeful.
- **Group commit**, `COMMIT_WINDOW_MS = 25` or 512 ops, whichever first. Under a watcher, 40 tiny
  page commits become ~2 WAL flushes. With `synchronous=NORMAL` this is about WAL frame churn, not
  fsync count, and WAL frame churn is what the valve exists to bound.
- **Bulk windows.** For a backfill > 100k blocks: write `meta.bulk_window = <op-id>`, drop the
  non-identity indexes and the three FTS sync triggers, load, `INSERT INTO block_fts(block_fts)
  VALUES('rebuild')`, recreate triggers and indexes, clear `meta.bulk_window`. codegraph measured
  2.8 s → 1.1 s inserting a 224k-edge set with recreation at ~0.3 s. **A UNIQUE identity index is
  never dropped** — dropping it would admit duplicates mid-load, which is the one thing a reload
  cannot repair. A `bulk_window` row present at open ⇒ the store **refuses to serve** and names
  `ow index repair`. (Invariant S12: a crash inside a bulk window must be *visible*, not silently
  served with missing indexes and missing FTS rows.)

### 6.2 Durability, stated precisely

`journal_mode=WAL` + `synchronous=NORMAL` means a power loss may lose the last committed
transactions and never corrupts the file. That is acceptable **because the checkpoint and the data
are in one transaction**: a lost commit reverts the `work` row to `pending` and the unit is
re-derived. It is *not* acceptable for billed output, so:

> **S15 — a transaction that commits the output of a `BILLED_API` operator runs with
> `PRAGMA synchronous = FULL`,** set on the write connection before `BEGIN` and restored after.
> One fsync against a VLM call is free; re-billing a page because a laptop lid closed is not.

### 6.3 Snapshot isolation for a query running while a re-index commits

This is the question with the sharpest answer, and nothing in the mine addresses it.

SQLite WAL gives a reader a consistent snapshot **for the life of one read transaction** — but the
ANN graph and the CSR adjacency are *files outside the database*, so they are outside the snapshot.
A reader that resolves "use `vec/3/epoch-000042`" and then reads a file being rewritten in place
gets torn data with no error. Therefore:

1. **Every derived structure is epoch-immutable.** A builder writes `vec/<space>/epoch-<N+1>/`
   complete, fsyncs it, inserts `index_epoch(state='building')`, verifies `manifest_sha256`, then
   in **one transaction** flips `N+1` to `live` and `N` to `retiring`. There is no in-place mutation
   of a live epoch, ever.
2. **A query opens one `BEGIN DEFERRED` read transaction and resolves every epoch pointer inside
   it,** then takes an `epoch_lease` row (also inside it) before mmap'ing. The snapshot therefore
   covers the pointer *and* the lease.
3. **The reaper unlinks a `retiring` epoch only when** `now > retired_at + EPOCH_GRACE_MS` **and**
   no live `epoch_lease` row exists for it. `EPOCH_GRACE_MS = 2 × MAX_READ_TXN_MS`. On Windows an
   open mmap makes unlink fail; the reaper tolerates the failure, leaves the row `retiring`, and
   retries — it never force-closes a reader.
4. **`MAX_READ_TXN_MS = 5000`, hard.** A read transaction pins the WAL and prevents checkpointing;
   an unbounded reader is exactly the "pinned reader" that turned codegraph's WAL valve into a
   22 GB WAL and an exit-137 OOM. A query that exceeds it is aborted and returns
   `verdict=degraded, degraded_because=["deadline"]` — never a partial result presented as complete.
   This is the connection between two mined facts that neither repo makes: **the reader's deadline
   is a WAL-valve safety parameter, not a UX parameter.**

Consequence, stated: `epoch` is monotone and appears in every `retrieval_event`, so "why did this
query return something different an hour later" is answerable from the ledger.

### 6.4 The WAL valve

Ported whole from codegraph with all eight properties and its measured constants, because every one
of them has a named failure behind it. Restated only for the numbers the implementer needs:

```
soft   = clamp(dbSize/4, 256 MB, 2 GB)     trigger on GROWTH beyond sizeAtLastFullBackfill,
                                            never on absolute size (a WAL file never shrinks)
hard   = 2 × soft   → park the writer at a between-transactions boundary until a FULL backfill
file   = 4 × soft   → the barrier also wal_checkpoint(TRUNCATE)
futility latch: 2 consecutive give-ups ⇒ disable writer pauses for 60 s and degrade to
                un-valved behaviour   (invariant I9)
journal_size_limit = 64 MB; heal-on-open above it (25.6 GB leak observed)
PASSIVE checkpoints on a worker thread with its own connection, never the write lane's
```

### 6.5 Readers

Every reader — hook, CLI, MCP server, second process — uses D1's `connect_readonly` ladder:
`mode=ro` when a WAL sidecar exists, `mode=ro&immutable=1` when it does not. **A read must not
change the freshness answer** (I10): opening a WAL database `mode=ro` creates the `-wal`/`-shm`
sidecars and moves the mtime a naive freshness check reads, and `immutable=1` against a live WAL
raises "no such table", which a caller mapping to "no embeddings" turns into a *false absence about
a corpus that was just embedded.*

---

## 7. Incremental update

### 7.1 The index delta falls out of D2's `rebind`

`ow rebind` already produces the block-level answer. D5 consumes it:

```
carried, content_digest unchanged  → block keeps its FTS rows, its chunk membership, its embeddings
carried, content_digest changed    → the block's chunk(s) are invalidated: chunk_digest recomputed,
                                     embedding looked up by the NEW digest (often a hit, corpus-wide)
created                            → new chunk, new digest, embed on miss
retired                            → chunk re-segmented; the old chunk row goes state=1
```

Because `chunk_digest` is content-addressed and `embedding` is keyed on it, **a re-parse that
changes provenance but not text costs zero embeddings**, and two documents sharing boilerplate share
one embedding. graphrag's `_copy_previous_output` copies a 50 GB index to add one document and
re-embeds the whole corpus; this is the inversion.

### 7.2 `anchor_delta` — codegraph's `definitionDelta`, ported

The correctness idea nobody outside codegraph has: incremental is not "re-derive the changed thing",
it is "re-derive everything whose answer depended on what changed". codegraph measured **4.3% of
distinct edges wrong, in both directions, silently, forever** without it.

```
anchor_delta = symmetric difference, across the write, of the set of
               (doc_ord, anchor_key, kind) pairs in `anchor`
```

sampled **before** blocks are replaced and diffed after. For each key in `anchor_delta`, re-run the
resolution pass over `unresolved_ref WHERE retry_key = ?` (partial index) **and** over already-
resolved `edge` rows whose relation is anchor-bound and whose `retry_key` matches — the inbound
re-bind. A body-only edit leaves `anchor_delta` empty, which is the common case and free.

Document anchors are: section numbers, figure and table labels, defined terms ("the Agreement"),
citation keys, slide titles, sheet names, and cross-document URIs. omniweave will mint unresolved
references constantly — a citation to a document not yet ingested, a cross-reference to a figure in
another PDF — and *the residue is data*: it is a row with a retry key, not a log line.

### 7.3 Tier-scoped replacement, and the ownership rule

Replacement is keyed on `(doc_ord, origin_operator)` — graphify's `build_merge`, per tier. **An
operator's re-run may replace only rows whose `origin_operator` is its own** (I4). Without it a free
structure re-extraction after one keystroke silently deletes every LLM-derived row for that
document: a free operation destroying billable output. Every eviction statement in the store is
filtered on `origin_operator`; a semgrep rule bans a `DELETE FROM` against a derived table without
it.

Deletion is an explicit list (`prune_docs`), never inferred — graphrag's `deleted_inputs` is
computed and consumed nowhere, and inference is how that happens.

### 7.4 The gate that makes all of this true

> **S13 — a CI job runs the fixture corpus incrementally (parse → edit 12 documents → update) and
> from scratch, then diffs *every* table with a canonical dump ordered by natural key, excluding
> only `retrieval_event`, `driver_observation`, and timestamp columns. A non-empty diff fails the
> build.**

This gate goes in **before** the watcher, deliberately, because the watcher is what will break it
silently.

---

## 8. Freshness, coverage, and the absence contract

### 8.1 Freshness is derived from durable state

`stale = EXISTS(claimable work row in scope)`, `refreshing = EXISTS(claimed with a live lease)`,
per-corpus plus a per-unit pending list filtered to the units this answer cites. Never a module
global (three repos got this wrong the same way), never a file mtime, never in-process state.
Four-valued per unit: `fresh | edited_uncommitted | stale_index | unknown`.

### 8.2 The eleven gates

`result_count == 0` becomes `ABSENT` only after failing all eleven, in precedence order. Each
failure forces `DEGRADED`. **One gate — `state == ABSENT` — governs citability**, so a new hazard is
always expressed by forcing `degraded`, never by adding a second rule.

| # | gate | why a zero result cannot prove absence |
|---|---|---|
| 1 | `deadline` | the read-transaction or query budget expired; part of the corpus was not scanned |
| 2 | `channel_unavailable` | a requested channel had no live implementation (plan P5) |
| 3 | `shard_unreachable` | a federated shard did not answer within the fan-out deadline |
| 4 | `coverage_incomplete` | `corpus.documents_discovered > documents_indexed`; a corpus that dropped files at index time reports the same digest as the source and served confident zeros over ~1,975 unindexed files in the one measured case |
| 5 | `pending_work_in_scope` | a `work` row is pending or claimed for a unit inside the query scope |
| 6 | `freshness_unknown` | a unit in scope could not be stat-checked; the absence claim rests entirely on this |
| 7 | **`parse_degraded_in_scope`** | an **indexed join** against D2's `diag`: `EXISTS(SELECT 1 FROM diag WHERE doc_ord IN scope AND (severity='error' OR code IN (OW_NEEDS_OCR, OW_TIMEOUT, OW_ENCRYPTED, OW_TRUNCATED_BY_BUDGET, OW_MALFORMED, OW_MISSING_PART, OW_INTEGRITY_UNCHECKED, OW_TABLE_SYNOPSIS_ONLY)))`. *OCR failed on pages 12–40* is a silent zero in every RAG system that exists. Here it is an index seek on `diag_code`. |
| 8 | `filter_starved` | the ANN over-fetch bound was hit and post-filtering left fewer than `k` survivors |
| 9 | **`restriction_withheld`** | a hit was withheld by `deny_restriction_bits` policy (D3-17). Withheld results are **counted**, never silently dropped — nobody in the mine has this because nobody carries licence restrictions into retrieval |
| 10 | `matches_before_packing > 0` | the `k` cap or the block budget emptied a non-empty result. **An empty response is not an empty search.** |
| 11 | `absence_unprovable` (last) | the only channel that ran was semantic. A cosine zero is a statement about the model, not about the corpus, and it must not be citable as one. Checked last because every gate above names something the caller can fix. |

### 8.3 The response envelope

```python
@dataclass(frozen=True, slots=True)
class Verdict:
    state: Literal["ok","low_confidence","absent","degraded"]
    degraded_because: tuple[str, ...]
    scanned: Mapping[str, int]              # {"chunks": …, "documents": …}
    best_score: float | None
    score_ceiling: float | None             # meaningless without it (§5.5)
    scorer_version: int
    weights_digest: str
    channels: Mapping[str, Literal["ok","off","unavailable","failed","starved"]]
    space: Mapping[str, str] | None         # model_id, model_rev, dim, metric, quant, epoch
    freshness: Literal["fresh","stale","unknown","not_tracked"]
    coverage: Mapping[str, int]
    withheld: int                           # restriction_bits
    did_you_mean: tuple[str, ...]
```

---

## 9. From a 10k-block laptop to a 10B-block cluster

### 9.1 Four tiers, one schema, one operator contract

| tier | blocks | shape |
|---|---|---|
| **T0 laptop** | ≤ 10⁶ | one `.owstore`, `exact/b1` vectors, recursive-CTE traversal, no epochs materialised beyond the trivial one. Zero third-party dependencies. |
| **T1 workstation** | ≤ 10⁸ | one `.owstore` (10⁸ blocks ≈ 33 GB by D2's measured 338 B/block), `omniweave-vector` ANN epochs, CSR sidecar, WAL valve fully engaged |
| **T2 host** | ≤ 10⁹ | N `.owstore` shards on one host, one writer per shard, a scatter-gather reader; or Postgres with `SELECT … FOR UPDATE SKIP LOCKED` replacing the claim `UPDATE` |
| **T3 cluster** | 10¹⁰ | 4096 virtual shards over M physical stores + one replicated **registry** shard |

### 9.2 The sharding key, and the one invariant that makes it work

> **Shard on `doc_key`.** A document never spans a shard.

That single invariant keeps `block.parent_id`, `rel`, `mark`, `cell`, `grid_slot`, `chunk`,
`chunk_block`, `part`, `asset` and `page_render` **all shard-local**, which means D2's entire FK
graph survives sharding untouched. `vshard = crc32c(doc_key) mod 4096`; a committed
`routing.toml` maps virtual-shard ranges to physical stores, so rebalancing moves ranges, never
rows-by-hash.

### 9.3 `block_id` allocation — D2's open question, settled

D2 asks: *"Does a T3 (Postgres) tier need a different `block_id` allocation scheme? … if T3 is in
scope for v1, `block_id` becomes a 64-bit composite (shard, sequence) and that must be decided
before any FK ships."*

**No. `block_id` stays a dense, store-local `INTEGER PRIMARY KEY` exactly as D2 wrote it. I reject
the composite.** Reasons, in order:

1. A composite puts the shard number in the high bits, so every rowid is a 9-byte varint instead of
   a 1–4 byte one. At 10⁸ blocks with ~8 indexed references each that is roughly **4–6 GB of pure
   key-width overhead per shard**, paid forever, to solve a problem that does not exist.
2. The problem does not exist because **there are no cross-shard foreign keys** (S14). A document
   never spans a shard, so no FK ever needs to point across one.
3. Everything that legitimately crosses a shard is already content-addressed and therefore
   shard-independent: `doc_key`, `content_digest`, `chunk_digest`, `cite`, `entity_key`.
4. A global reference, where one is genuinely needed (an entity mention, a cross-document citation),
   is the explicit pair `GlobalRef = (corpus_id: bytes16, block_id: int)` — a value type, never a
   column that pretends to be a local FK.

D6 should not contradict this. If it does, the amendment is one line in D2, not a re-key.

### 9.4 Federation

`ow query` against a routing table is scatter-gather:

```
1. narrow by filter → the set of vshards that can contain a match
     (doc_keys → exact vshards;  uri_prefix → a vshard set from the `doc_route` registry;
      otherwise → all)
2. fan out with a per-shard deadline = 0.6 × query deadline; MAX_INFLIGHT_SHARDS = 32
3. each shard returns its per-channel ranked lists (NOT fused) plus its scanned counts
4. the coordinator concatenates per channel, re-ranks each channel globally on its own raw score,
   then fuses ONCE with the global ceiling
5. a shard that missed its deadline sets degraded_because += ["shard_unreachable:<n>"]
```

Fusing once at the coordinator, over globally re-ranked channels, is the only correct order:
fusing per shard and merging fused scores is wrong because RRF ranks are shard-relative.

**The registry shard** holds `entity`, `entity_alias`, `anchor` with `doc_ord = -1`, and the
routing table. It is small relative to blocks (entities are 1–2 orders fewer), it is
read-mostly, and it is replicated. It is also the single point of contention at 10¹⁰, and
`hub_cap` is what stops one hot entity from making it the bottleneck.

### 9.5 Numbers

Using D2's measured 338 B/block and ~200 MB per 300–600k blocks with FTS5:

| | 10⁴ blocks | 10⁷ | 10¹⁰ |
|---|---|---|---|
| model + FTS5 | ~4 MB | ~3.3 GB | ~3.4 TB (≈ 830 MB / vshard) |
| chunks @ 8 blocks each | 1,250 | 1.25 M | 1.25 B |
| embeddings i8 @ 768 dim | ~1 MB | ~1 GB | ~1 TB |
| ANN graph @ degree 32 | — | 160 MB | 160 GB |
| CSR @ 2 edges/block | — | 160 MB | 160 GB |
| `retrieval_event` | negligible | ~1 KB/query | ~1 KB/query |
| shape | one file, no deps | one file + epochs | 4096 vshards / 32–128 hosts |

---

## 10. The index is a cache. The committed artifact is a lock file.

graphify's merge driver is the only "commit your graph" implementation in the collection, and its
own constants state the ceiling: **typical < 5 MB / < 50k nodes, hard caps 50 MB / 100k nodes** —
two to three orders short of 10⁷ blocks, let alone 10¹⁰. Worse, the driver is `nx.compose`, a pure
union that ignores the merge base, so **a node deleted on one branch and untouched on the other
comes back.** That is the right trade for a derived artifact and a silent corruption for anything
treated as source.

So: **the `.owstore` is a cache and is `.gitignore`d.** What is committed is:

```
omniweave.index.lock      sorted, plain text, one line per document, deterministic
# schema=1 corpus=<none>  chunker=spine/1@3:9c1e  space=bge-m3@a1b2c3/768/cosine/i8
<doc_key hex>  <gen>  <status>  <n_blocks>  <n_chunks>  <root content_digest>  <producer_id tuple>  <uri>
```

- `ow index lock` writes it; `ow index verify` proves a locally built store matches it and exits
  non-zero with the first differing line otherwise.
- A merge driver is registered **for this file only**: sort-merge by `doc_key`; identical lines
  union; a *conflicting* line for the same `doc_key` is a **real conflict** the human resolves.
  Deletion is a deleted line and stays deleted. That is precisely the property graphify's union
  driver throws away, and it is affordable because the file is text with a total order on its key.
- `ow index diff <a.lock> <b.lock>` gives graphify's `graph_diff` at the right granularity:
  *"12 documents re-parsed, 3 added, 1 removed, 402 chunks changed, 0 embeddings re-billed."*

At 10⁷ blocks over ~20k documents the lock file is ~3 MB of text — reviewable, diffable, and it
carries the one property people actually want from committing an index: *did re-indexing change
anything, and can I reproduce it?*

---

## 11. Invariants, and how each is enforced

| # | Invariant | Enforced by |
|---|---|---|
| **S1** | Exactly one writer per `.owstore`; readers never block it. | Cross-process scoped lock `store.write` with `(host,pid,create_time)` liveness; a single in-process `WriteLane`; a test spawns two writers and asserts the second waits and then succeeds, and that neither corrupts. |
| **S2** | Every ANN and CSR structure is derived and rebuildable from transactional tables. | A CI job deletes `vec/` and `csr/`, runs `ow index rebuild --derived`, and asserts byte-identical epoch manifests **and** identical top-50 over 1,000 golden queries. |
| **S3** | A query reads exactly one snapshot of the model *and* of every derived structure. | One `BEGIN DEFERRED`; epoch pointers and `epoch_lease` rows are read/written **inside** it; a fault-injection test commits a new epoch mid-query and asserts the reader's results are unchanged. |
| **S4** | A derived file is never unlinked while a reader holds its lease. | `epoch_lease` + `EPOCH_GRACE_MS`; the reaper's SQL is `NOT EXISTS(live lease)`; a test mmaps an epoch, retires it, and asserts the file survives until the lease expires. |
| **S5** | An `embedding` row cannot exist without a fully-specified space. | FK to `embed_space`; a trigger rejects `model_rev IN ('','main')`; gate G8's semgrep rule bans `revision="main"`. |
| **S6** | A search never mixes embedding spaces. | `space_id` is a required plan field; `embedding` is `PRIMARY KEY (space_id, chunk_digest)`; the ANN epoch's manifest carries `space_id` and the opener asserts it. |
| **S7** | Filters narrow; channels score within the narrowed set; "no restriction" and "restrict to nothing" are different values. | `Candidates = Literal["ALL"] | frozenset[int]` — a sum type. The falsy collapse that returned a whole repository on a nonsense query is unrepresentable, not merely discouraged. A test issues a filter matching nothing and asserts zero results with `verdict=absent` (all gates passing). |
| **S8** | Every channel is totally ordered on `(-score, chunk_digest)`. | A shared `total_order()` helper is the only sort site; a property test shuffles each channel's input 100× and asserts identical output; `chunk_digest` (not `chunk_id`) makes it federation-stable. |
| **S9** | `fuse()` and `ceiling()` resolve weights through one function. | Both call `_weight()`; a perfect-consensus property test asserts `fuse()[0].score == ceiling()`. |
| **S10** | A zero result is `absent` only after eleven gates; `state == absent` is the sole citability rule. | `build_verdict()` is the only constructor of `Verdict`; a table-driven test with one fixture per gate; a test asserts adding a hazard requires no second citability rule. |
| **S11** | Every UNIQUE natural key folds NULLs with `IFNULL`. | A schema test parses `store-v1.sql`, finds every UNIQUE index over a nullable column, and fails if it lacks `IFNULL`. codegraph #1034 is the regression fixture. |
| **S12** | A crash inside a bulk window is visible, never silently served. | `meta.bulk_window` written before the first DDL and cleared after the last; open-time check refuses to serve and names `ow index repair`; a test SIGKILLs mid-bulk and asserts the refusal. |
| **S13** | An incremental run converges to the same state as a full rebuild. | The CI incremental-vs-full table diff (§7.4). codegraph measured 4.3% of distinct edges wrong without the equivalent pass. |
| **S14** | No foreign key targets another store. | A schema test resolves every FK to a table in the same file; the federation client has no API that takes a bare `block_id`; `GlobalRef` is the only cross-store reference type. |
| **S15** | A `BILLED_API` commit is durable. | The `WriteLane` sets `synchronous=FULL` for that transaction; a test asserts the pragma value at commit time for a billed operator and `NORMAL` for a free one. |
| **S16** | A governor cannot make things worse than not running. | The WAL valve's futility latch (2 give-ups ⇒ 60 s cooldown ⇒ degrade); an `armed` log line and a heartbeat. |
| **S17** | A reader cannot pin the WAL indefinitely. | `MAX_READ_TXN_MS = 5000` enforced by the snapshot context manager; exceeding it aborts with `degraded:["deadline"]`; a test holds a query against a bulk write and asserts the abort. |
| **S18** | The physical schema is not a compatibility surface. | `ow sql --readonly` rejects any statement naming a non-`v1_` object; a test renames a base column and asserts the `v1_*` views and every conformance query still pass. |
| **S19** | Every retrieval response is replayable. | `scorer_version`, `weights_digest`, `space`, `ann_epoch`, `csr_epoch`, `plan_shape` on the envelope **and** in `retrieval_event`; `ow query replay <event_id>` returns `IDENTICAL` / `DIVERGED` / `REPLAY_DRIFT`. |
| **S20** | Restricted content never leaves the store. | `deny_restriction_bits` is applied inside the channel SQL (`chunk_restricted` partial index), not by the caller; withheld hits are counted into `Verdict.withheld`; a test parses with a synthetic restricted driver and asserts the withholding survives lexical, semantic and structural paths. |
| **S21** | Every store migration declares its cost class and what an un-backfilled row means. | A migration registry with required `{ddl_only: bool, backfills: bool, unbackfilled_meaning: str}`; CI fails a migration missing any field; a test runs every migration against a fixture at every prior `SCHEMA`. |
| **S22** | A channel failure is never a confident zero. | `ChannelResult.status` is a required field; semgrep bans a bare `except` returning an empty list inside `store/channels/`; a fault-injection test corrupts the FTS index and asserts `verdict=degraded`, not `absent`. |

---

## 12. Two clarifications, and one flagged tension

**(a) `.owstore` and Postgres.** D2: *"whose canonical form is the SQLite corpus file
(`.owstore`)"*; D1: `backend = "sqlite" # sqlite (shipped) | postgres (D5, later)`. Read literally,
a Postgres T3 has no canonical form. **My reading, which I believe is the intended one:** the
normative object is the *schema* at a given `SCHEMA` version; `.owstore` is its SQLite
materialisation and `.owdoc` is its interchange projection. A Postgres backend is the same schema
in a different materialisation, held to the same `import(export(store)) == store` gate. **Minimum
amendment if the judge disagrees with my reading:** change D2's Decision sentence to *"whose
canonical **local** form is the SQLite corpus file (`.owstore`)"*. Nothing else moves. I am not
re-litigating; I am naming the ambiguity so no downstream document guesses.

**(b) "L4 never adds a second representation of a block."** I honour it literally. `head_fts` is
external-content over `block.title` (no text copy); `block_fts` is D2's, untouched; `chunk` stores
offsets and a heading path, never body text; `chunk_block` is materialised only for
non-contiguous runs; `term_vocab` stores segments, not text. The only place block text is
duplicated anywhere in omniweave is D2's own optional `part` retention, which is D2's call.

**(c) The one real tension I want on the record: D1 §S3 versus D3's Service.** D1 states *"A
long-lived local IPC daemon for parsing, embedding or indexing is banned; if a later decision needs
one it is a unix socket or named pipe at 0600, never a loopback port"*, and reserves attach-or-spawn
HTTP for *"GPU VLMs only"*. D3 then defines *"**Service** := a host-managed shared resource a Driver
requests by name through `io.service(name)` — a vLLM engine, an ONNX session, **an embedding
server**"*. D3's escape route satisfies D1's own escape clause (UDS/named pipe at 0600), so I read
these as consistent and I have designed accordingly: an embedding Service is permitted, and I
decline it as the *default* on engineering grounds (§5.3), not on legal ones. **This is not a
conflict and needs no amendment.** I record it because a later panel reading only D1 would
reasonably conclude that no embedding server may exist, and that conclusion would be wrong.

**(d) One distribution beyond D1's eleven.** `omniweave-vector` (ANN backend, depends on a
third-party `usearch`/`hnswlib` wheel — a *consumed* compiled wheel, exactly like `pypdfium2` in
`omniweave-pdf`, so it is still `py3-none-any` and violates nothing in D1's CI shape). D1 says
"eleven first-party distributions"; this makes twelve. If the judge prefers to hold the line at
eleven, the fallback is to land the ANN backend inside `omniweave-graph`, at the cost of pulling
`tree-sitter` and `graphrag-chunking` onto the vector path and inheriting its `<3.14` ceiling — a
worse outcome, priced here so the choice is deliberate. The licence of the chosen ANN library must
clear gate G3 / D3-18 before it ships; I have not verified it against a checkout because it is not
in `_collections/`.

---

## 13. Build order

| phase | weeks | ships | invariants |
|---|---:|---|---|
| **B1 store core** | 6 | `store-v1.sql`, migrations with cost classes, pragma ladder, `connect_readonly`, WriteLane + group commit, bulk window, WAL valve, heal-on-open, epoch manager + leases + reaper, `ow index status/repair` | S1, S3, S4, S11, S12, S15, S16, S17, S21 |
| **B2 chunk + lexical + identity** | 4 | chunker `spine/1` + `table/1`, `chunk`/`chunk_block`, `head_fts`, sanitiser, `term_vocab`, `anchor`, identity ladder, `ow query` with plans P0/P1/P2, fusion + ceiling, `Verdict` with all eleven gates, `retrieval_event` | S7, S8, S9, S10, S18, S19, S20, S22 |
| **B3 semantic** | 4 | `embed_space`, `embedding`, the stdlib `exact/b1` backend + i8 re-rank, `omniweave-vector` ANN epochs with base/delta/tombstone and compaction, plan P3, `filter_starved` | S2, S5, S6 |
| **B4 graph + incremental** | 5 | `edge` + identity index, recursive-CTE traversal, CSR epoch above 2M edges, `Expand` with `hub_cap`, plan P4, `unresolved_ref`, `anchor_delta`, tier-scoped replacement, the incremental-vs-full CI gate, `ow index lock/verify/diff` | S13, S14 |
| **B5 planner honesty** | 3 | `stat`/`stat_hist`, `ow query explain`, `ow query replay`, `ow index tune --estimates`, the golden-set weight calibration gate | — |
| **B6 federation** | 5 | routing table, scatter-gather coordinator, registry shard, `shard_unreachable`, Postgres backend behind the same four protocols | S14 at scale |

**≈27 engineer-weeks to B5** (a complete single-store product) for two engineers ≈ 14 calendar
weeks; **+5 for federation**, which nothing should build until a real corpus asks for it.

Runtime and space costs, stated: FTS5 adds 40–60% of indexed text; `chunk` ~120 B/row plus
`head_path`; `embedding` `dim` bytes/chunk at i8; CSR 8 B/edge; `retrieval_event` ~1 KB/query
(sampled at 100% below 10⁴ queries/day, then at 10%). Page cache 64 MB + mmap 256 MB per
connection (D2's pragmas). Core gains **zero** third-party dependencies.

---

## 14. Failure modes I own

1. **The 4M-cell spreadsheet becomes semantically invisible.** `TABLE_SYNOPSIS_ONLY` is a real
   capability loss: "find the row where margin fell below 12%" will not be answered by the semantic
   channel. It *is* answered by lexical + a numeric filter, it is visible in `diag`, and it forces
   `degraded`. The alternative — 4M embeddings — is worse, and pretending otherwise is how a
   framework ships a $40,000 ingest.
2. **The independence assumption in selectivity estimation is wrong.** `format='pdf' ∧ lang='de'`
   are correlated in every real corpus. The planner will over- or under-estimate, P1 will be chosen
   when P3 was right, and the only defence is the est-vs-actual ratio in `retrieval_event` and a CI
   gate. A multi-column histogram is the fix and it is not in v1.
3. **A long analytical query starves the writer.** `MAX_READ_TXN_MS = 5000` bounds it, which means
   an honest analytical query over 10⁸ blocks simply cannot run against a live store — it must go
   through `ow export duckdb`. Someone will find this infuriating, and the alternative is codegraph's
   22 GB WAL.
4. **Epoch compaction is unbounded work with no incremental path.** Rebuilding an ANN base over
   10⁸ vectors is hours. The delta segment bounds *query* correctness, not *build* cost; a corpus
   ingesting faster than compaction completes grows its delta until `MAX_DELTA_VECTORS` forces the
   writer to wait. The pause is honest and it is still a pause.
5. **`chunk_digest` dedup is a covert channel across tenants in a shared store.** If two tenants
   share a `.owstore` and one embeds a document, the other's identical document is embedded for free
   — observable as a timing difference. In a multi-tenant deployment, `space_id` must be
   tenant-scoped, which forfeits the dedup. Multi-tenancy is not solved here and I am not pretending
   it is.
6. **The registry shard is the T3 bottleneck and a hot entity is its worst input.** `hub_cap`
   truncates rather than fails, so a query about a hub entity silently sees a sampled neighbourhood
   (it says so in `degradations`, which nobody reads).
7. **Binary quantisation loses recall on short chunks.** 1-bit-per-dim over a 20-token chunk is
   noisy; the i8 re-rank recovers precision only among the top 1,000 the b1 scan surfaced. A corpus
   of very short chunks (a glossary, a chat log) is the input where the stdlib backend is
   measurably worse than the ANN one, and the CI benchmark must include one.
8. **`anchor_delta` is only as good as the anchor extractor.** A corpus whose cross-references are
   prose ("as described above") produces no anchors, so incremental convergence is trivially true
   and retrieval quality is unaffected — but a corpus with *idiosyncratic* numbering the extractor
   half-recognises produces a partially-populated `anchor` table and therefore a
   partially-correct convergence, which is worse than none and is invisible.
9. **The lock file diverges from the store and nobody notices** until `ow index verify` runs. It is
   not verified on every open (that would cost a full scan), so a stale lock file is a lie until CI
   catches it.
10. **Every fitted number here — the two BM25 weights, the 0.6 spine decay, the four RRF weights,
    `PREFILTER_MAX`, `CSR_THRESHOLD`, `TABLE_SYNOPSIS_CELLS` — is a guess seeded from another
    domain's tuning.** jcodemunch's weights were tuned for code search; codegraph's 20× name weight
    was tuned for symbol names. They ship as `calibration: bootstrap` and the golden-set gate is the
    only thing that will ever make them true.

---

## 15. Why I reject the alternatives

- **A pluggable vector-store abstraction (graphrag's).** graphrag's pluggability buys portability
  across five hosted stores and pays for it with an index whose metadata lives in five places and an
  update path that copies the whole index. omniweave's index is *derived from* a transactional
  system of record; making the derived thing pluggable is fine (it is `VectorIndex`, four methods),
  but making the *storage of embeddings* pluggable would put the system of record outside the
  transaction that produced it, and then a crash between "embedding written to Pinecone" and
  "`work` row completed" is unrecoverable. The system of record is in the store. Full stop.
- **graphify's deliberate no-vectors.** Defensible, and its benchmark (0.497 recall@10 on LOCOMO,
  76% LongMemEval-S at zero LLM build cost) proves deterministic extraction is competitive *where
  structure exists*. It does not cover the thematic query over prose, which is a real omniweave
  workload. The synthesis is not "no vectors" but "vectors are one weighted channel with a declared
  ceiling, off by default at T0, and never the sole basis for an absence claim" (gate 11).
- **LEANN's selective recomputation as the default.** Its numbers are real (201 GB → 6 GB at 60M
  chunks) and the trade is right for a cold personal corpus. It is wrong as a default for a served
  framework: it makes p99 depend on a daemon, it makes retrieval unreproducible because nothing was
  stored to compare against, and its own incremental story does not survive (full-corpus re-hash,
  a two-layer Merkle tree whose own TODO says so, and HNSW's *"limited incremental support"* — which
  is why LEANN's own MCP tool defaults to `ivf`). Kept as a stamped flag-pair mode; not the default.
- **jcodemunch's per-producer edge tables.** Genuinely good where the *columns* differ per producer
  (`p50_ms` means nothing outside runtime). In omniweave the columns do not differ: every edge has a
  producer, a trust, a site and a weight. One `edge` table with `producer_id` as a column, a UNIQUE
  identity index including `producer_id`, and codegraph's composite indexes is strictly simpler and
  admits the same `WHERE producer_id IN (…)` queries. I take the `*_unmapped` idea whole as
  `unresolved_ref` and reject the table split.
- **A real graph engine (Neo4j, KùzuDB, DuckDB-PGQ).** A second storage engine means a second
  durability story, a second snapshot story, a second migration story and a second failure domain,
  in exchange for multi-hop traversal that a per-epoch CSR delivers in a few hundred lines with the
  same snapshot semantics as everything else. The moment traversal is unbounded, no engine saves
  you; the moment it is beam-bounded, no engine is needed.
- **`ord_path` / gap keys, adjacency-list-in-JSON, and a materialised transitive closure.** The
  first is D2's rejection and I agree. The second forfeits the UNIQUE identity index that codegraph
  measured as necessary. The third is O(n²) on a document graph and re-materialises on every edit.
- **Committing the store to git with a union merge driver.** graphify's own caps (50 MB /
  100k nodes) and its base-ignoring `nx.compose` — a deleted node returns — make it wrong for
  anything above a toy. The lock file gets the property people want at 1/1000 the size and with
  correct deletion semantics.
- **A general cost-based optimiser.** Untestable, produces plan flips that present as outages, and
  every real gain it would find is already in the six shapes. The finite plan space is the feature.
- **Postgres from day one.** It solves T3 and it costs the property that makes omniweave installable:
  `pip install omniweave && ow parse report.docx && ow query "…"` with no server. Postgres is the
  same schema behind the same four protocols, shipped when a workload demands it.
- **Raw SQL as the public API.** The most requested and the most expensive. Four `v1_*` views give
  95% of it at zero compatibility cost.

---

## 16. Open questions

- **What is the real chunks-per-block ratio and characters-per-chunk distribution on a mixed
  corpus?** Every storage projection above scales off "8 blocks per chunk". Settle it by running
  `spine/1` over D2's `fixtures/docs/` plus ten real 200-page documents and plotting the
  distribution; the answer retunes `TARGET_CHARS`, `MAX_CHUNK_BLOCKS` and every table in §9.5.
- **Where exactly does the stdlib `exact/b1` backend cross D1's 250 ms warm-query budget?** My
  estimate is ~10⁵ chunks and it is an estimate, not a measurement. Settle it with a CI benchmark on
  the three CI OSes; the measured number becomes the published switch-over point and the trigger for
  `ow doctor` to recommend `omniweave-vector`.
- **Does binary quantisation plus an i8 re-rank hold recall on document chunks?** Measure
  recall@10 of `b1 → top-1000 → i8 re-rank` against exact i8 on a 100k-chunk corpus. If it is below
  0.95, the stdlib backend ships i8-only with a smaller envelope.
- **Which ANN library clears the licence gate and ships pure wheels for the CI matrix?** usearch and
  hnswlib both declare permissive licences; neither is in `_collections/`, so the claim is
  unverified. Settle it with gate G3 over a resolved graph plus an import-graph scan, and by checking
  wheel availability for {ubuntu, macos, windows} × {3.11, 3.12, 3.13}.
- **Is one `edge` table right once D7 defines its relation vocabulary?** If D7 introduces a relation
  whose *columns* genuinely differ (a temporal claim with `start_date`/`end_date` — graphrag's
  covariate shape), that is a sibling table, not a column on `edge`. Settle it in D7; the
  `edge_identity` index shape is what must not change.
- **Do the eleven absence gates hold at federation scale?** Gate 4 (`coverage_incomplete`) requires
  a global count of discovered-versus-indexed documents, which is a scatter of its own. Settle it by
  measuring whether a cached, per-shard coverage row refreshed on every write is accurate enough to
  gate a citability claim, or whether coverage must be recomputed per query.
- **Multi-tenancy.** §14.5 names a real leak and mine-runtime §7.12 lists the store shape as
  unresolved. Settle it with a decision between store-per-tenant (LDR's `tenants × 60 × 3` FD
  multiplier) and row-level tenancy with tenant-scoped `space_id`; nothing in `_collections/` has
  evidence for the middle ground.
