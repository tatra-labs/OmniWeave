# D7-structure — Structure extraction: deterministic-first graph building and the knowledge model

## Decision

omniweave's knowledge layer is **`owgraph`**: one set of tables inside D2's `.owstore`, written only
by the host through a single **`GraphSink`**, in which the graphify/graphrag distinction is not a mode
but three columns D2 already defines (`method`, `producer_id`, `trust`) plus D3's `origin_driver`. The
extraction unit is the **Segment** — a heading-scoped, table-atomic, zero-overlap, block-aligned run of
~1,200 tokens that is simultaneously the extraction unit, the embedding unit and the cache unit.
Deterministic-before-LLM is enforced by a **coverage ledger** whose ordering key is D3's `cost_class`,
so a third party's free extractor preempts the paid one with no core change, and by a CI query
asserting zero billed items on covered ground. An LLM is never asked for a character offset: it returns
a block **`cite`** and a verbatim **`quote`**, and the host locates the quote itself — one `str.find`
that is simultaneously the citation, the polygon, the hallucination gate and the injection containment.
**No L3 table stores geometry**; `locate()` walks `mention → block.quad` and returns a `Locus` whose
`quad` may be `None` with a stated reason rather than a synthesized rectangle. Entity resolution is
**append-only and reversible**: `entity` is keyed on `(scope, etype, key)` and is durable, `entity_merge`
is a log of `polarity = ±1` decisions, and `entity.canonical_id` is a derived path-compressed closure, so
`ow graph split` is a re-closure rather than a re-index. Communities are **re-clustered always,
re-reported only when `member_digest` changes**, with reports lazy, leaf communities capped at 512
members rather than graphrag's 10, and `use_lcc` permanently off. Incremental correctness rests on
**`anchor_delta`** — codegraph's `definitionDelta` for documents — plus owner-scoped replacement and a
blocking CI gate asserting incremental equals full. `omniweave-graph`'s third-party dependency set is
**empty**.

## Spec

**1. One model, no mode switch, and the mechanism is a ledger.** graphrag ships two pipelines over one
schema (`index/workflows/factory.py:52-96`); graphify ships two tiers in one JSON blob and needs
`_is_ast_tier` plus a written COEXIST rule to stop a semantic re-extract deleting the file's AST nodes
(`build.py:1668-1674`, #2333/#2336). Both encode structurally what D2 encodes as a column. An
AST-derived mention is `(method=native_xml, trust=EXTRACTED, origin_driver='derive.anchor.native')`; an
LLM one is `(method=llm, trust=INFERRED, origin_driver='derive.entity.llm')`. Same row, same table, same
query. graphify's tier predicate becomes `derive_pass.cost_rank`, a card field the host reads without
importing anything (D3-1).

Ordering is `cost_rank` (`free=0 < local_compute=1 < billed_api=2`) and nothing else. A pass records
what it **covered** — "I looked at this (Segment, lane) and my answer is complete" — into
`derive_cover`, as a per-Segment bitmap over the Segment's blocks. A billed pass's input selector is
`covered_frac(segment, lane, cheaper passes) < llm_coverage_floor` (0.60); its per-item gate is a bit
test, and an item whose `observed_block` is covered by a cheaper pass for the same lane is quarantined,
never written. Gate **G7-2** runs that join on the fixture corpus and asserts zero. The honesty guard is
that `cover` requires at least one emitted item or an explicit `cover_empty` with a reason; `ow graph
doctor` reports the `cover_empty` rate per (pass, lane) and warns above 0.98, because a pass that finds
nothing and claims coverage is silent recall loss shaped exactly like absence.

**2. The Segment.** `segment` + `segment_block` with `PRIMARY KEY (block_id)`, so a block belongs to
exactly one Segment and overlap is unrepresentable. The segmenter walks D2's `block_read` index in
`(page, ord)` order, never splits a Block, never splits a table or list (`atom`), prefers a heading
boundary, partitions by `Layer` so a footnote's entities do not pollute body context, and carries
`heading_path` (docling's `contextualize()` for free). `content_digest = blake3_128(canonical(
[heading_path, member content_digests]))` — a merkle over D2's digests, so an unchanged Segment survives
a re-parse free, and `heading_path` **is** a digest input because the prompt contains it. There is
**one** chunking: D5 reads `segment` and does not define a second, because a zero-overlap block-aligned
Segment is exactly as citable as any retrieval chunk and neighbour expansion is D2's `parent_id`/`ord`.

**3. Grounding by quote.** The extraction schema asks for `cite` + `quote` (3–300 chars, claimed
verbatim) and never for offsets, a `bbox`, a `page` or an `id`. The host checks the `cite` is one the
prompt supplied (else `quarantine(OWG_DANGLING_CITE)`), computes `i = normalize_k(block.text).find(
normalize_k(quote))` (else `OWG_UNGROUNDED`), and writes `mention(block_id, ts_a=i, ts_b=i+len)`.
`normalize_k` strips Unicode `Cf`, so the wrapper's zero-width defanging is invisible to grounding and
no `ShiftMap` is needed. Every leaf is nullable before constrained decoding (lift's
`make_properties_nullable`); every array carries `minItems`/`maxItems` (surya disabled guided table-rec
because an under-specified grammar lets greedy decoding legally close an array after one element);
`more_available: bool` replaces graphrag's `LOOP_PROMPT` and its `response.content != "Y"` compare
(`graph_extractor.py:118`), and a glean is `attempt = 2` on the same D4 decision, capped, charged to the
same budget. Deterministic drivers may emit a `span` when their card declares `grounding = "span"`.

**4. Provenance, five axes, no new vocabulary.** The reproduction tuple is interned once per
`(Segment, pass)` into `derive_run`: `producer_id`, `method`, `origin_driver`, `driver_schema_v`,
`origin_operator`, `cost_class`, `decision_id`, `cache_key`. Each item row carries `run_id`, `trust`
(no default; absent ⇒ `AMBIGUOUS`, fixing graphify's `default="EXTRACTED"` at `callflow_html.py:210`),
`score`/`score_kind` nullable together, `restriction_bits` (D3-17, with a partial index) and `taint`.
`MAX_TRUST_BY_METHOD` clamps `llm`/`vlm_page`/`ocr_*`/`roundtrip` to `INFERRED`; the clamp is applied by
the runner after the driver returns, writes an `OWG_TRUST_CLAMPED` quarantine row carrying the original
claim, and is mirrored by a `BEFORE INSERT` trigger generated from the same mapping with CI parity —
D2's `enum_val` pattern. A migration may only downgrade `trust` and may never clear `taint`.

**5. Where a graph edge meets a polygon.** `edge → edge_evidence → mention → block`, then `block.quad`,
`block.page`, `block.os_*`. `locate()` returns a `Locus` with `quad: Quad | None`, `precision ∈
{char, line, block, page, none}` and, when `quad is None`, a `reason` naming the parse driver's declared
`spatial`. Sub-block precision is a query (narrow to covering line-child Blocks), never a stored column.

**6. Entity resolution.** `entity` is `UNIQUE(scope, etype, key)` where `key = normalize_key(canonical
surface)` — a **blocking** key, never an identity, because graphrag's identity *is* its uppercased title
(`clean_str(x.upper())`, `graph_extractor.py:146-158`) and spelling drift splits a node. `normalize_key`
is graphify's `ids.py` verbatim (bounded NFKC/casefold fixpoint, `re.UNICODE` filter), vendored at a
pinned SHA with its NOTICE, and the extraction prompt restates the recipe so model-minted keys collide
with deterministic ones on purpose. The funnel: exact key → type gate → entropy ≥ 2.5 bits/char →
MinHash/LSH (128 perms, 32 bands, 0.7, 3-gram shingles with spaces stripped, persisted in
`entity_band`) → Jaro-Winkler ≥ 92.0 (plain Jaro cross-document at ≥ 12 chars) → community boost +5.0 →
nine negative guards re-applied before the LLM band `[75, 92)` → union-find with a deterministic
survivor → cohesion re-check splitting members below `threshold − 10`. `entity_merge` is append-only
with `polarity ∈ {+1, −1}`; `canonical_id` is the derived closure; `ow graph split` writes a `−1` row.
The two document-specific guards nothing in the collection has: `scoped_label_crossdoc` (two
`scope='document'` entities in different documents never merge — *Figure 3* in doc A is not *Figure 3*
in doc B) and `cross_trust_class` (an entity witnessed only by an untrusted-external document is never
auto-merged into an internal one).

**7. Incremental.** D2's `rebind` runs first; if it quarantines, D7 does nothing. `S` = Segments whose
`content_digest` moved. Replacement is owner-scoped, `DELETE … WHERE run_id IN (… segment_id IN S AND
pass_id = :p)`, so a free re-extraction cannot delete billable rows. Retired blocks move their items to
`graph_history`, never `DELETE`. `anchor_delta` is the per-document symmetric difference of
`(name_norm, akind)` pairs across the store phase: **added** names retry `unresolved_ref WHERE
status='failed' AND retry_key IN (:added)` on the partial index; **removed** names unbind every edge
whose `bound_by` names them, deleting it and re-writing an `unresolved_ref` — codegraph's inbound
re-bind, whose absence it measured at 4.3% of distinct edges wrong in both directions
(`docs/benchmarks/index-drift-cg33.md:5,25`). Only edges carrying `bound_by` participate: "never delete
what we cannot restore" (`src/extraction/index.ts:2663`). Resolution rescope includes `entity_band`
probes of new entities, not just their clusters. Clustering is always full; reports go stale only on a
`member_digest` change. Gate **G7-8** builds a 60-document corpus once and again in 20 shuffled steps
and asserts equality on a canonical projection modulo surrogate ids.

**8. Cost.** Every billed pass is D4's `Rung.ENRICH`; `evaluate()` picks, `admit()` reserves,
`budget.exhausted` fires DEGRADE to the free graph with a `Diag`. Cache keys are cost-tiered (graphify
`cache.py`): free artifacts carry a producer-version namespace so an upgrade invalidates them, paid
artifacts do not, so a bug-fix release never re-bills. Five miss shapes are counted per run. Reports are
lazy, leaves ≤ 512 members, `report_levels = 2`. `ow graph plan` prints Segments, calls, tokens and
micros before a cent is spent; billed passes are absent from the default `enable` list, so
`pip install omniweave && ow graph build` costs $0 and needs no key.

## Concrete shape

```sql
-- ═════ owgraph — added to D2's .owstore, model_version 1.1 (MINOR ⇒ additive only) ═════
-- Same file, same connection, D2's pragma order (busy_timeout FIRST — codegraph #238).
-- D2 binds: "L3 may not put containment or intra-document references in its own tables."
--           Containment is D2's `block.parent_id`; the seven `rel` kinds are D2's.
-- enum_val gains domains: 'lane', 'akind', 'ref_kind', 'claim_status', 'taint', 'precision'.

-- ─────────────────────────── vocabularies (data, not code) ───────────────────────────
CREATE TABLE etype_vocab (            -- entity classes, corpus-tuned. NEVER a four-item config list.
  etype        TEXT PRIMARY KEY,      -- graphrag: DEFAULT_ENTITY_TYPES = [organization,person,geo,
  scope        TEXT NOT NULL CHECK(scope IN ('document','corpus')),  --  event] (defaults.py:42) is
  resolution   TEXT NOT NULL CHECK(resolution IN ('exact_only','fuzzy','none')),  -- why "graphrag
  source       TEXT NOT NULL CHECK(source IN ('builtin','proposed','user')),      --  doesn't work
  compatible   TEXT NOT NULL DEFAULT '[]',   -- JSON array of etypes that MAY merge across
  n_entities   INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
-- builtin: anchor(document) defined_term(document) section(document) figure(document)
--          table(document) citation(corpus) person org place date money quantity product
--          group unknown.  'proposed' comes from `ow graph types --propose` and is not
--          first-class until an operator promotes it.

CREATE TABLE relation_vocab (         -- the DIRECTION RULE as data; the prompt is GENERATED from it,
  relation   TEXT PRIMARY KEY,        -- so prompt and schema cannot drift.  (graphify llm.py:500-504)
  symmetric  INTEGER NOT NULL DEFAULT 0,      -- symmetric ⇒ stored with src_entity < dst_entity
  actor_rule TEXT NOT NULL,           -- "source is the CITING entity; target is the CITED entity."
  source     TEXT NOT NULL CHECK(source IN ('builtin','driver','user'))
) WITHOUT ROWID;
-- builtin (12): refers_to cites defines part_of member_of party_to supersedes amends
--               located_in attributed_to depends_on co_occurs_with related_to
-- A driver card MAY declare relations = [{relation, symmetric, actor_rule}]; admitted at
-- activation with source='driver'. A relation with no actor_rule is CARD_INVALID.

CREATE TABLE derive_pass (            -- the pass registry. DATA. There is no pipeline array.
  pass_id     TEXT PRIMARY KEY,       -- == the D3 driver id, or 'host.<name>' for host passes
  port        TEXT NOT NULL,          -- 'derive/1' | 'host'
  cost_class  TEXT NOT NULL CHECK(cost_class IN ('free','local_compute','billed_api')),
  cost_rank   INTEGER NOT NULL,       -- 0|1|2. THE ORDERING. Nothing else orders passes.
  lanes       TEXT NOT NULL,          -- JSON array: anchor|xref|entity|claim|community|summary
  granularity TEXT NOT NULL CHECK(granularity IN ('document','part','corpus')),
  card_sha256 TEXT NOT NULL, schema_version INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1
) WITHOUT ROWID;

-- ─────────────────────────── the Segment ───────────────────────────
CREATE TABLE segment (
  segment_id  INTEGER PRIMARY KEY,
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, ord INTEGER NOT NULL,
  layer       INTEGER NOT NULL,       -- D2 Layer: body/furniture/note segments are separate
  atom        TEXT,                   -- 'table'|'list'|NULL: an unsplittable atom
  heading_path TEXT NOT NULL,         -- JSON array of ancestor heading texts. A DIGEST INPUT.
  n_blocks INTEGER NOT NULL, n_tokens INTEGER NOT NULL, tokenizer_id TEXT NOT NULL,
  first_page INTEGER NOT NULL, last_page INTEGER NOT NULL,
  trust       INTEGER NOT NULL,       -- MIN(block.trust) over members — why AMBIGUOUS=0 matters
  content_digest BLOB NOT NULL,       -- blake3_128([heading_path, member content_digests in ord])
  UNIQUE (doc_ord, gen, ord)
);
CREATE INDEX segment_digest ON segment(content_digest);
CREATE TABLE segment_block (
  block_id   INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  ord        INTEGER NOT NULL        -- position WITHIN the segment; the cover_bits bit index
) WITHOUT ROWID;                     -- EXACTLY ONE segment per block. Overlap is unrepresentable.
CREATE INDEX segment_block_seg ON segment_block(segment_id, ord);

-- ─────────────── the run: provenance interned once per (segment, pass) ───────────────
CREATE TABLE derive_run (
  run_id     INTEGER PRIMARY KEY,
  segment_id INTEGER REFERENCES segment(segment_id) ON DELETE CASCADE,  -- NULL ⇒ corpus pass
  pass_id    TEXT NOT NULL REFERENCES derive_pass(pass_id),
  at_gen     INTEGER NOT NULL,
  -- provenance, verbatim from D2/D3/D4. No parallel names are invented.
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method      INTEGER NOT NULL,      -- D2 Method. One method per pass; two methods is two passes.
  origin_operator TEXT NOT NULL,     -- D2 §8: OWNERSHIP, not trust. The replacement key.
  origin_driver   TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,      -- D3
  cost_class  TEXT NOT NULL, decision_id TEXT,                          -- D3 / D4
  -- cache
  input_digest BLOB NOT NULL,        -- segment.content_digest at derive time
  cache_key    BLOB NOT NULL,        -- free_key | paid_key, below
  status TEXT NOT NULL CHECK(status IN ('ok','partial','empty','failed','quarantined')),
  n_items INTEGER NOT NULL DEFAULT 0, n_quarantined INTEGER NOT NULL DEFAULT 0,
  spend  TEXT NOT NULL DEFAULT '{}', -- canonical JSON of D4's Spend. No dollars here.
  UNIQUE (pass_id, IFNULL(segment_id,-1), at_gen)
);
CREATE INDEX derive_run_seg ON derive_run(segment_id, pass_id);

CREATE TABLE derive_cover (          -- THE deterministic-first mechanism
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  lane       TEXT    NOT NULL,
  run_id     INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  cover_bits BLOB    NOT NULL,       -- 1 bit per block in segment_block.ord order; ≤64 B at 512
  n_covered  INTEGER NOT NULL,
  empty_reason TEXT,                 -- NOT NULL ⇒ covered with zero items. doctor reports the rate.
  PRIMARY KEY (segment_id, lane, run_id)
) WITHOUT ROWID;
CREATE INDEX derive_cover_lane ON derive_cover(lane, segment_id);

-- ─────────────────────────── the graph proper ───────────────────────────
CREATE TABLE entity (
  entity_id  INTEGER PRIMARY KEY,    -- DURABLE surrogate. Assigned once for a (scope,etype,key).
  cite       TEXT NOT NULL,          -- 'e412' — prompts ONLY. See UPSTREAM CONFLICT 2.
  scope      INTEGER NOT NULL,       -- 0 = corpus-wide, else the owning doc_ord
  etype      TEXT NOT NULL REFERENCES etype_vocab(etype),
  key        TEXT NOT NULL,          -- normalize_key(canonical surface). A BLOCKING key, not an id.
  title      TEXT NOT NULL,          -- display surface (the highest-trust mention's)
  raw_etype  TEXT,                   -- the producer's own label, kept (D2's raw_kind rule)
  canonical_id INTEGER NOT NULL REFERENCES entity(entity_id),   -- DERIVED from entity_merge
  resolution_trust  INTEGER NOT NULL DEFAULT 0,   -- D2 Trust, reused. No new enum.
  resolution_method INTEGER NOT NULL,             -- D2 Method, reused.
  trust      INTEGER NOT NULL,       -- MIN over live mentions. No default: absent ⇒ AMBIGUOUS.
  taint      INTEGER NOT NULL DEFAULT 0,          -- OR over live mentions
  restriction_bits INTEGER NOT NULL DEFAULT 0,    -- D3-17
  frequency  INTEGER NOT NULL DEFAULT 0,   -- COUNT(DISTINCT mention.segment) — CORPUS salience
  degree     INTEGER NOT NULL DEFAULT 0,   -- edge degree — GRAPH salience.  BOTH, always recomputed
  doc_count  INTEGER NOT NULL DEFAULT 0,   -- corpus SPREAD; 400 mentions in one contract ≠ 400 docs
  mention_digest BLOB NOT NULL,      -- merkle over live mention digests: the `summary` cache key
  description TEXT,                  -- DERIVED: the highest-trust mention's context sentence
  summary     TEXT,                  -- LLM, OPTIONAL, a separate column, keyed on mention_digest
  state      INTEGER NOT NULL DEFAULT 0,   -- 0 live, 1 overloaded, 2 retired
  x          TEXT NOT NULL DEFAULT '{}',   -- keys MUST be 'x.<vendor>.<key>'
  UNIQUE (scope, etype, key)
);
CREATE UNIQUE INDEX entity_cite  ON entity(cite);
CREATE INDEX entity_canon  ON entity(canonical_id)              WHERE state = 0;
CREATE INDEX entity_rank   ON entity(etype, degree DESC, frequency DESC) WHERE state = 0;
CREATE INDEX entity_review ON entity(resolution_trust, taint)   WHERE resolution_trust < 2 OR taint<>0;
CREATE INDEX entity_restricted ON entity(restriction_bits)      WHERE restriction_bits <> 0;

CREATE TABLE entity_alias (          -- the fix for graphrag's title keying
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  norm    TEXT NOT NULL,             -- normalize_key(surface)
  surface TEXT NOT NULL,
  akind   TEXT NOT NULL CHECK(akind IN ('canonical','variant','abbrev','expansion','translit',
                                        'llm','user')),
  run_id  INTEGER NOT NULL REFERENCES derive_run(run_id),
  trust   INTEGER NOT NULL, taint INTEGER NOT NULL DEFAULT 0,
  doc_count INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (entity_id, norm, akind)
) WITHOUT ROWID;
CREATE INDEX entity_alias_norm ON entity_alias(norm);   -- the lexicon automaton's source
-- RULE (injection layer 6): an alias with (taint & TAINT_UNTRUSTED_SOURCE) AND doc_count = 1 is
-- NEVER a blocking key for cross-document resolution. Enforced in resolve/block.py + a test.

CREATE TABLE mention (               -- THE BRIDGE: the only table referencing both spaces. (G7-15)
  mention_id INTEGER PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  block_id   INTEGER NOT NULL REFERENCES block(block_id)   ON DELETE CASCADE,
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,   -- D2 TextSpan. NOT NULL: a mention has a span.
  surface TEXT NOT NULL,
  run_id  INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust   INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint   INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  digest  BLOB NOT NULL,             -- blake3_128([entity.key, block_id, ts_a, ts_b])
  state   INTEGER NOT NULL DEFAULT 0,-- 0 live, 1 orphaned (block retired, no successor)
  CHECK (ts_a <= ts_b),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  UNIQUE (block_id, ts_a, ts_b, entity_id, run_id)   -- identity IN THE SCHEMA (codegraph #1034)
);
CREATE INDEX mention_entity  ON mention(entity_id, block_id) WHERE state = 0;
CREATE INDEX mention_block   ON mention(block_id, ts_a);
CREATE INDEX mention_segment ON mention(segment_id);
CREATE INDEX mention_review  ON mention(trust, taint) WHERE trust < 2 OR taint <> 0;
-- THERE IS NO `quad` COLUMN AND THERE NEVER WILL BE. Geometry is D2's. (G7-1)

CREATE TABLE edge (                  -- entity→entity. Weighted. Clustered. Traversed.
  edge_id    INTEGER PRIMARY KEY,
  src_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  dst_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  relation   TEXT NOT NULL REFERENCES relation_vocab(relation),
  role       TEXT,                   -- participation role: reifies an n-ary event on member_of
  -- WHERE THE RELATIONSHIP WAS OBSERVED. graphify requires source_file on EDGES, not just nodes:
  -- that one field is what makes "where does this document assert that" answerable.
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER, ts_b INTEGER,
  bound_by   TEXT,                   -- the anchor name_norm that RESOLVED this edge; drives unbind.
                                     -- NULL ⇒ never unbound ("never delete what we cannot restore")
  weight     REAL NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,   -- src.degree + dst.degree; the edge prior
  corroborations  INTEGER NOT NULL DEFAULT 1,   -- corroboration is NOT promotion
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust  INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint  INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  x      TEXT NOT NULL DEFAULT '{}',
  CHECK (src_entity <> dst_entity),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  UNIQUE (src_entity, dst_entity, relation, observed_block, IFNULL(ts_a,-1), run_id)
);
CREATE INDEX edge_src     ON edge(src_entity, relation, weight DESC);
CREATE INDEX edge_dst     ON edge(dst_entity, relation, weight DESC);
CREATE INDEX edge_obs     ON edge(observed_block);
CREATE INDEX edge_bound   ON edge(bound_by) WHERE bound_by IS NOT NULL;
CREATE INDEX edge_review  ON edge(trust, taint) WHERE trust < 2 OR taint <> 0;

CREATE TABLE edge_evidence (         -- which mentions witnessed this edge; drives locate()
  edge_id    INTEGER NOT NULL REFERENCES edge(edge_id) ON DELETE CASCADE,
  mention_id INTEGER NOT NULL REFERENCES mention(mention_id) ON DELETE CASCADE,
  slot TEXT NOT NULL CHECK(slot IN ('src','dst','predicate')),
  PRIMARY KEY (edge_id, mention_id, slot)
) WITHOUT ROWID;

CREATE TABLE claim (                 -- graphrag's covariates. A DIFFERENT table from `edge` because
  claim_id   INTEGER PRIMARY KEY,    -- it has different consumers: the clusterer reads edge, never
  cite       TEXT NOT NULL,          -- claim, and weight/combined_degree are meaningless here.
  subject_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  object_entity  INTEGER          REFERENCES entity(entity_id) ON DELETE CASCADE,  -- BIPARTITE
  object_literal TEXT, object_datatype TEXT,   -- 'xsd:date'|'xsd:decimal'|'money:USD'|'string'
  claim_type TEXT NOT NULL,          -- OPEN vocabulary, corpus-tuned (graphrag: covariate_type)
  predicate  TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('asserted','denied','suspected','superseded')),
  t_start TEXT, t_end TEXT,          -- ISO-8601, partial permitted ('2026', '2026-06')
  t_precision TEXT CHECK(t_precision IN ('year','month','day','datetime')),
  -- graphrag stores `source_text`, a COPY. A copy drifts on any re-parse. We store the reference.
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  quote_tier INTEGER NOT NULL,       -- D2's Quote of the source block, copied at write time
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust  INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint  INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  x      TEXT NOT NULL DEFAULT '{}',
  CHECK ((object_entity IS NULL) <> (object_literal IS NULL)),
  CHECK ((object_literal IS NULL) = (object_datatype IS NULL)),
  CHECK ((t_start IS NOT NULL OR t_end IS NOT NULL) = (t_precision IS NOT NULL)),
  UNIQUE (subject_entity, IFNULL(object_entity,-1), IFNULL(object_literal,''), claim_type,
          observed_block, ts_a, run_id)
);
CREATE UNIQUE INDEX claim_cite ON claim(cite);
CREATE INDEX claim_subject ON claim(subject_entity, claim_type);
CREATE INDEX claim_time    ON claim(t_start, t_end) WHERE t_precision IS NOT NULL;

-- ───────────── resolution: append-only, order-independent, reversible ─────────────
CREATE TABLE entity_merge (
  merge_id  INTEGER PRIMARY KEY,
  loser_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  winner_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  polarity  INTEGER NOT NULL CHECK(polarity IN (-1, 1)),  -- -1 = MUST NOT merge (a user split)
  stage  TEXT NOT NULL CHECK(stage IN ('exact','lsh_jw','community_boost','abbrev','llm_band','user')),
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  score REAL, score_kind TEXT,       -- 'jaro_winkler'|'lsh_jaccard'|'llm_logprob'
  guards TEXT NOT NULL DEFAULT '[]', -- the guards that PASSED: a rule change is auditable
  reason TEXT,                       -- REQUIRED when stage='user'
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id),
  decided_at_gen INTEGER NOT NULL, retired_at_gen INTEGER,
  CHECK (loser_id <> winner_id),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX entity_merge_pair ON entity_merge(loser_id, winner_id, polarity)
  WHERE retired_at_gen IS NULL;
-- entity.canonical_id = the path-compressed union-find closure over polarity=+1 rows, honouring
-- polarity=-1 as a blocking pair, with stage='user' applied LAST and never overwritten by a pass.

CREATE TABLE entity_band (           -- persisted MinHash bands. NEVER an in-memory index:
  band     INTEGER NOT NULL,         -- 128-perm signatures for 1.5M entities is ~1.3 GB of RAM.
  bucket   BLOB    NOT NULL,
  etype    TEXT    NOT NULL,
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (band, bucket, entity_id)
) WITHOUT ROWID;
-- Rebuilt whenever meta['graph.resolve_signature'] changes (normalize_key version, perms,
-- threshold, shingle size). A forgotten bump is silent recall loss, so the signature is CHECKED
-- at the top of every resolve pass and a mismatch REBUILDS rather than warns.

-- ───────────── anchors, references, and the durable residue ─────────────
CREATE TABLE anchor (                -- what a document DEFINES. The anchor_delta substrate.
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  name_norm TEXT NOT NULL,
  akind TEXT NOT NULL,               -- section|figure|table|exhibit|defined_term|citation_key|
                                     -- glossary|bookmark
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  entity_id INTEGER REFERENCES entity(entity_id) ON DELETE SET NULL,
  scope TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  PRIMARY KEY (doc_ord, gen, name_norm, akind)
) WITHOUT ROWID;
CREATE INDEX anchor_corpus ON anchor(name_norm, akind) WHERE scope = 'corpus';

CREATE TABLE unresolved_ref (        -- codegraph's biggest idea, for documents. Residue is DATA.
  ref_id     INTEGER PRIMARY KEY,
  from_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  ref_text TEXT NOT NULL,
  ref_kind TEXT NOT NULL,            -- section|figure|table|exhibit|citation|defined_term|
                                     -- anchor|doc_link
  retry_key TEXT NOT NULL,           -- normalize_key of the resolvable name — the anchor_delta join
  scope TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  candidates TEXT NOT NULL DEFAULT '[]',   -- JSON array of near-miss entity cites
  status TEXT NOT NULL CHECK(status IN ('pending','failed')),   -- resolved ⇒ ROW DELETED
  attempts INTEGER NOT NULL DEFAULT 0, last_tried_gen INTEGER,
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE
);
-- PARTIAL: on a healthy corpus the pending set is empty and the failed set is the only population
-- worth indexing (codegraph migrations.ts v8, idx_unresolved_failed_tail).
CREATE INDEX unresolved_retry ON unresolved_ref(retry_key) WHERE status = 'failed';

CREATE TABLE quarantine (            -- graphrag DELETES these (filter_orphan_relationships).
  q_id INTEGER PRIMARY KEY,          -- A hallucinated name is very often a REAL entity the
  code TEXT NOT NULL,                -- extractor failed to emit a row for. KEEP IT.
     -- OWG_UNGROUNDED | OWG_DANGLING_CITE | OWG_DANGLING_TMP | OWG_OUT_OF_SCOPE_BLOCK
     -- | OWG_COVERED_GROUND | OWG_ITEM_BUDGET | OWG_TRUST_CLAMPED | OWG_LABEL_TOO_LONG
     -- | OWG_INJECTION_SUSPECT | OWG_ETYPE_OUT_OF_VOCAB | OWG_UNPARSED_ITEM
     -- | OWG_GUARD_BLOCKED | OWG_COHESION_SPLIT | OWG_ENTITY_OVERLOADED
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  row_kind TEXT NOT NULL CHECK(row_kind IN ('entity','alias','mention','edge','claim','anchor',
                                            'xref','merge')),
  payload TEXT NOT NULL,             -- the rejected draft, canonical JSON, verbatim
  block_id INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  detail TEXT NOT NULL DEFAULT '{}', at_gen INTEGER NOT NULL
);
CREATE INDEX quarantine_code ON quarantine(code, run_id);

CREATE TABLE graph_history (         -- retirement, not deletion. One table for every kind.
  kind TEXT NOT NULL CHECK(kind IN ('entity','mention','edge','claim','community')),
  row_id INTEGER NOT NULL, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER, reason TEXT NOT NULL,   -- reparse|resolver_split|resolver_merge|
  payload TEXT NOT NULL,                         -- source_deleted|pass_replaced|compacted
  PRIMARY KEY (kind, row_id, retired_gen)
) WITHOUT ROWID;

-- ─────────────────────────── communities and reports ───────────────────────────
CREATE TABLE community (
  community_id INTEGER PRIMARY KEY,  -- durable; carried across re-clusters by member_digest match
  cite   TEXT NOT NULL,              -- 'c412' — prompts ONLY. Flat, not level.ordinal: a level
  level  INTEGER NOT NULL,           -- is not stable across re-clusters. INTEGER, not graphrag's
  parent INTEGER REFERENCES community(community_id),   -- str that update/communities.py:52
  component_ord INTEGER NOT NULL,    -- astype(int)s. Root parent is NULL, NEVER -1.
  cluster_run INTEGER NOT NULL,
  size INTEGER NOT NULL, cohesion REAL,
  member_digest BLOB NOT NULL,       -- blake3_128(canonical(sorted canonical member ids))
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id),
  trust INTEGER NOT NULL, taint INTEGER NOT NULL DEFAULT 0,
  state INTEGER NOT NULL DEFAULT 0,
  UNIQUE (cluster_run, level, component_ord, member_digest)
);
CREATE UNIQUE INDEX community_cite  ON community(cite);
CREATE INDEX community_level ON community(level, size DESC) WHERE state = 0;
CREATE TABLE community_member (
  community_id INTEGER NOT NULL REFERENCES community(community_id) ON DELETE CASCADE,
  entity_id    INTEGER NOT NULL REFERENCES entity(entity_id)       ON DELETE CASCADE,
  PRIMARY KEY (community_id, entity_id)
) WITHOUT ROWID;
CREATE INDEX community_member_e ON community_member(entity_id);

CREATE TABLE community_report (      -- DEMAND-MATERIALISED. Written on first descent.
  community_id INTEGER PRIMARY KEY REFERENCES community(community_id) ON DELETE CASCADE,
  report_state TEXT NOT NULL CHECK(report_state IN ('absent','stale','fresh')),
  member_digest BLOB,                -- the digest the CURRENT text was written against
  title TEXT, summary TEXT, full_content TEXT, findings TEXT,
  rank REAL, rating_explanation TEXT,
  coverage REAL,                     -- fraction of member evidence that FIT the context window
  run_id INTEGER REFERENCES derive_run(run_id),
  trust INTEGER CHECK(trust IS NULL OR trust <= 1),   -- a report is NEVER EXTRACTED
  taint INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0, written_at_ns INTEGER
);
CREATE INDEX community_report_todo ON community_report(report_state) WHERE report_state <> 'fresh';
CREATE VIEW community_report_fresh AS
  SELECT r.* FROM community_report r JOIN community c USING (community_id)
  WHERE r.report_state = 'fresh' AND r.member_digest = c.member_digest;
-- Retrieval reads the VIEW. A stale report is INVISIBLE, never silently served as current.

-- ─────────────── operability: the artefact an on-call engineer reads ───────────────
CREATE TABLE graph_observation (     -- symmetric with D3's driver_observation
  run TEXT NOT NULL, pass_id TEXT NOT NULL, lane TEXT NOT NULL,
  segments_in INTEGER NOT NULL DEFAULT 0, segments_cached INTEGER NOT NULL DEFAULT 0,
  blocks_in INTEGER NOT NULL DEFAULT 0, items_out INTEGER NOT NULL DEFAULT 0,
  covered INTEGER NOT NULL DEFAULT 0, cover_empty INTEGER NOT NULL DEFAULT 0,
  quarantined INTEGER NOT NULL DEFAULT 0, grounded_frac REAL,
  calls INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
  wall_ms INTEGER NOT NULL DEFAULT 0,
  -- graphify's five miss shapes. A cache that silently serves a partial never self-heals.
  miss_corrupt INTEGER NOT NULL DEFAULT 0, miss_partial INTEGER NOT NULL DEFAULT 0,
  miss_empty INTEGER NOT NULL DEFAULT 0, miss_mismatch INTEGER NOT NULL DEFAULT 0,
  miss_vintage INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run, pass_id, lane)
) STRICT;
```

```python
# ══════════ omniweave-graph — THIRD-PARTY DEPENDENCIES: NONE. Ceiling 5 MB. ══════════
# Settles D1's open question: graphrag-chunking is DROPPED (388 lines; sentence_chunker.py:9
# `import nltk` with nltk absent from pyproject.toml:32-35; bootstrap_nltk.py runs EIGHT
# nltk.download() calls from SentenceChunker.__init__, failing D1 G15 and D3 needs_network=false;
# create_chunk_results.py:19-30 advances start_char as if chunks did not overlap while
# split_text_on_tokens advances by chunk_size - chunk_overlap, so every provenance offset after
# the first is wrong and the error accumulates; requires-python ">=3.11,<3.14").
# tree-sitter moves to `omniweave-driver-code` (P5); grammars are their own distributions
# (codegraph ships 27 grammars, 66 MB, with 3 LICENSE files — the outcome to avoid).
# networkx / datasketch / rapidfuzz / numpy are all REJECTED — see Rejected.

# omniweave_graph/ident.py — ONE implementation. graphify/ids.py (Apache-2.0) vendored at a
# pinned SHA under vendor/graphify-ids/ with LICENSE + NOTICE + .sha256, per D1's four-part rule.
def normalize_key(s: str) -> str:
    """Invariants, one property test each (graphify's three):
         idempotent · charset-closed (\\w and _ only) · caseless-stable
       The bounded fixpoint loop is load-bearing: casefold and NFKC do not commute and neither is
       a fixpoint of the other (Turkish dotted I -> i + U+0307, which NFKC recomposes; #2614).
       re.UNICODE on the filter, or every CJK/Cyrillic/Arabic corpus collapses to one node per
       document (#811)."""
    cur = s
    for _ in range(6):
        nxt = unicodedata.normalize("NFKC", cur.casefold())
        if nxt == cur: break
        cur = nxt
    cur = re.sub(r"[^\w]+", "_", cur, flags=re.UNICODE)
    return re.sub(r"_+", "_", cur).strip("_")

def normalize_k(s: str) -> str:
    """The GROUNDING normaliser — a DIFFERENT function from normalize_key, deliberately.
       NFKC · casefold · strip Unicode category Cf (so the wrapper's zero-width defanging AND a
       zero-width-joiner obfuscation attack are both invisible here, which is why no ShiftMap is
       needed) · map soft hyphen and U+2010..2015 to '-' · collapse whitespace runs to ' ' · strip.
       Grounding always runs against the UNDEFANGED block text."""

# omniweave_graph/model/taint.py — bits 5..31 RESERVED; a 33rd bit is a migration.
class Taint(IntFlag):
    NONE=0; UNTRUSTED_SOURCE=1<<0; SENTINEL=1<<1; HIDDEN_TEXT=1<<2
    OFFSCREEN=1<<3; SINGLE_WITNESS_XDOC=1<<4
GENERATION_BLOCKED = Taint.SENTINEL | Taint.HIDDEN_TEXT | Taint.OFFSCREEN
# Taint ORs UPWARD (mention -> entity/edge/claim -> community_report) and NEVER ACROSS EDGES:
# neighbourhood propagation poisons a whole subgraph from one bad PDF and makes the bit useless.

# omniweave_graph/model/trust.py — the security clamp, applied BY THE RUNNER after the driver
# returns; a driver cannot opt out (D3-8). A clamp writes OWG_TRUST_CLAMPED carrying the driver's
# original claim, so over-claiming is MEASURABLE in `ow graph doctor`, not silently corrected.
MAX_TRUST_BY_METHOD: Mapping[Method, Trust] = {
    Method.NATIVE: EXTRACTED, Method.NATIVE_XML: EXTRACTED, Method.TEXT_LAYER: EXTRACTED,
    Method.HEURISTIC: EXTRACTED, Method.USER: EXTRACTED,
    Method.OCR_PAGE: INFERRED, Method.OCR_BLOCK: INFERRED, Method.VLM_PAGE: INFERRED,
    Method.LLM: INFERRED, Method.ROUNDTRIP: INFERRED,   # <- the ones a document can talk back on
}
# Mirrored by BEFORE INSERT triggers on entity/mention/edge/claim GENERATED from this mapping at
# migration time, with CI parity in both directions — D2's enum_val pattern. Two enforcers, one truth.

# omniweave_graph/locate.py — "where on the page". Absence is a VALUE.
@dataclass(frozen=True, slots=True)
class Locus:
    cite: Cite; doc_ord: int; gen: int; page: int; addr: Addr
    span: TextSpan
    quad: Quad | None                                  # D2's frame: topleft, 1/1000 pt, unrotated
    precision: Literal["char","line","block","page","none"]
    origin: OriginSpan                                 # the answer when there is no polygon
    reason: str | None                                 # non-None IFF quad is None, e.g.
                                                       # "parse.doc.anydoc declares spatial=none"
def locate(store, kind: Literal["mention","edge","claim","entity"], row_id: int
           ) -> tuple[Locus, ...]: ...
# NO SYNTHESIZED BOX, EVER. D1: "bounding boxes are optional in L2, and their absence must be
# representable rather than faked." precision='line' means the span narrowed to covering
# line-child Blocks; precision='block' means the whole Block. Say which.

# omniweave_graph/segment.py
MAX_SEGMENT_TOKENS = 1200; MAX_SEGMENT_BLOCKS = 512    # min(tenant_cap, MAX_*); never widened
def segment(doc: "Doc", sink: "GraphSink") -> Iterator["SegmentDraft"]: ...
# Block-aligned · zero overlap · table- and list-atomic · layer-partitioned · heading-scoped.
# A table over MAX_SEGMENT_BLOCKS is its own Segment, routed to derive.entity.table and NEVER
# to an LLM entity pass. token_est = ceil(utf8_len/4) with tokenizer_id stamped unless a driver
# supplies a real tokenizer; the estimate only SIZES a Segment — D4 bills actuals — so an
# estimate error never becomes a wrong bill.

# omniweave_graph/resolve/ — constants are graphify's measured ones (dedup.py:244-248)
ENTROPY_MIN=2.5; LSH_THRESHOLD=0.7; NUM_PERM=128; BANDS=32; SHINGLE_K=3
MERGE_THRESHOLD=92.0; COMMUNITY_BOOST=5.0; LLM_BAND=(75.0,92.0); LLM_BATCH=30
COHESION_SPLIT_DELTA=10.0; MAX_ENTITY_DEGREE=4096; MAX_CANDIDATE_PAIRS=5_000_000
GUARDS = ("prefix_containment","numeric_tokens_differ","content_token_swap","variant_suffix",
          "short_label_substitution","file_anchored_crossdoc","scoped_label_crossdoc",
          "cross_trust_class","cooccurrence_in_segment")
# The last three are ours. `scoped_label_crossdoc`: two scope='document' entities in different
# documents never merge — "Figure 3" in doc A is not "Figure 3" in doc B, the single most common
# false merge in a document corpus and one no code-oriented deduper needs.
# `cooccurrence_in_segment`: two entities mentioned distinctly in one Segment are LESS likely the
# same thing — a document saying "X and Y" is asserting they differ. Blocks below JW 97.
# `cross_trust_class`: an entity witnessed only by an untrusted_external document is never
# auto-merged into an internal one (cross_trust_class_merge = never|llm_band_only|allow).
def resolve(store, *, scope: frozenset[EntityId] | None, admission) -> "ResolveReport": ...
# PURE over (entity, entity_alias, live entity_merge, community_member). Writes entity_merge rows
# and recomputes canonical_id as a path-compressed closure. Idempotent. Order-independent (G7-6):
# candidate pairs are processed in the total order (-score, min(key), max(key)) and the survivor is
# min on (merge_hops, -len(alias_set), key). Never mutates or deletes an entity.

# omniweave_graph/cluster/louvain.py — PURE PYTHON over an array('i') CSR from ONE SQL scan.
CLUSTER_SEED = 0xDEADBEEF; MAX_COMMUNITY_SIZE = 512; COHESION_SPLIT = 0.05
COHESION_SPLIT_MIN = 50; REPORT_LEVELS = 2; MAX_CLUSTER_EDGES = 8_000_000
# Determinism engineered three ways, all graphrag's (cluster_graph.py:57-97): direction-normalized
# (lo=min, hi=max), duplicate-dropped, sorted edge list, fixed seed.
# PER CONNECTED COMPONENT. use_lcc is REJECTED PERMANENTLY (graphrag defaults.py:72 use_lcc=True
# silently discards everything outside the largest component; on a folder of unrelated PDFs —
# omniweave's premise — that is most of the graph).
# Above MAX_CLUSTER_EDGES: refuse with OWG_GRAPH_TOO_LARGE naming the cap AND the driver seam
# `omniweave-driver-leiden` (graspologic_native, called DIRECTLY — graphify cluster.py:22-40
# measured 7-19 s of graspologic package import for a layout algorithm it never calls).
```

```jsonc
// ══ owgraph-segment/1 — what a derive driver RECEIVES, as a blob ref in D3's INVOKE frame ══
{"t":"segment","seg":"seg:9f2c1d4a77b03e51","heading_path":["Part II","7. Risk Factors"],
 "n_blocks":184,"n_tokens":1174,"layer":"body","atom":null,
 "doc":{"format":"pdf","media_type":"application/pdf","lang":"en",
        "trust_class":"untrusted_external","outline":[/* … */]},
 "etypes":["defined_term","person","org","money","date","unknown"],   // the corpus vocabulary
 "relations":[{"relation":"cites","actor_rule":"source is the CITING entity; target is the CITED."}]}
{"t":"block","cite":"d7#412","kind":"paragraph","layer":"body","page":13,"ord":7,
 "text":"…","marks":[[12,19,"bold",null]],"quote":"normalized","trust":2,
 "table":{"table_cite":"d7#400","r":0,"c":3,"header_rows":1,"row_span":1,"col_span":1}}
// NO block_id. A driver addresses blocks by `cite` only, so it CANNOT forge a block_id and its
// output is portable between stores. The host maps cite -> block_id on ingest.

// ══ owgraph-items/1 — what a derive driver RETURNS. `tmp` ids are LOCAL to one invocation. ══
{"t":"entity","tmp":"e1","key":"indemnified_party","etype":"defined_term",
 "title":"Indemnified Party","trust":"extracted","score":null}
{"t":"alias","tmp_entity":"e1","surface":"Indemnitee","akind":"abbrev","trust":"extracted"}
{"t":"mention","tmp_entity":"e1","cite":"d7#412","span":[12,29],"surface":"Indemnified Party"}
{"t":"mention","tmp_entity":"e1","cite":"d7#480","quote":"the Indemnified Party shall",
 "surface":"Indemnified Party"}                       // `quote` XOR `span`, never both
{"t":"edge","tmp_src":"e1","tmp_dst":"e7","relation":"defines","cite":"d7#410","quote":"…",
 "trust":"inferred","score":0.81,"score_kind":"model_logprob"}
{"t":"claim","tmp_subject":"e1","object_literal":"1250000","object_datatype":"money:USD",
 "claim_type":"attribute","predicate":"cap_on_liability","status":"asserted",
 "t_start":"2026-01-01","t_precision":"day","cite":"d7#412","quote":"…","trust":"inferred"}
{"t":"anchor","name":"Exhibit C","akind":"exhibit","cite":"d7#500","scope":"document"}
{"t":"xref","name":"Exhibit C","ref_kind":"exhibit","cite":"d7#88","quote":"see Exhibit C"}
{"t":"cover","lane":"anchor","cites":["d7#412","d7#413"]}
{"t":"cover_empty","lane":"anchor","cites":["d7#414"],"reason":"no definition pattern"}
{"t":"more","value":false}          // replaces graphrag's LOOP_PROMPT + `response != "Y"` compare
{"t":"diag","code":"OWG_LANGUAGE_UNSUPPORTED","severity":"warning","detail":{"lang":"ja"}}
// A `tmp` referenced but never defined quarantines the WHOLE SEGMENT with OWG_DANGLING_TMP:
// graphrag's filter_orphan_relationships as a hard gate with a counter, keeping the rows.
```

```python
# ══════ GraphSink — the ONLY writer of L3 tables. Drivers never see it. (mirrors D2's DocSink) ══════
class GraphSink(Protocol):
    def begin_run(self, seg: "SegmentRef", p: "PassIdentity",
                  allowed_cites: frozenset[Cite]) -> RunId: ...
    # `allowed_cites` is THE cache-poisoning / injection control, lifted from graphify's
    # cache.put(entries, allowed_units=frozenset(batch_units)) and D-runtime I13. A draft naming a
    # cite outside the set is quarantined OWG_OUT_OF_SCOPE_BLOCK. Enforced by the SIGNATURE.
    def entity(self, d: "EntityDraft") -> EntityId: ...
    def alias(self,  d: "AliasDraft")  -> None: ...
    def mention(self, d: "MentionDraft") -> MentionId: ...    # grounds a `quote`, else quarantines
    def edge(self,  d: "EdgeDraft")  -> EdgeId: ...
    def claim(self, d: "ClaimDraft") -> ClaimId: ...
    def anchor(self, d: "AnchorDraft") -> None: ...
    def xref(self,  d: "XrefDraft")  -> None: ...   # -> edge(bound_by=…) | unresolved_ref
    def cover(self, lane: str, cites: Sequence[Cite], *, empty_reason: str | None = None) -> None: ...
    def quarantine(self, row_kind: str, code: str, payload: Mapping[str, Any], **d: Any) -> None: ...
    def diag(self, d: Diag) -> None: ...
    def end_run(self, status: str, spend: Spend) -> "RunReport": ...   # COMMITS ONE TRANSACTION
# The sink is the ONLY place trust is written, the ONLY place ids are minted, and the ONLY place
# restriction_bits / origin_driver / producer_id are stamped. A draft PROPOSES; the runner DECIDES.
# It has no drop(): quarantine is the only disposal path. (G7-10)

@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: int; pass_id: str; status: str
    inputs: int; emitted: int; quarantined: int
    covered: int; cover_empty: int
    coverage_frac: float          # the deterministic-first metric, printed by `ow graph plan`
    grounded_frac: float | None   # LLM passes -> D4's day-one signal verify.grounded_field_frac
    spend: Spend                  # D4's seven-unit physical vector. No dollars here.
```

```toml
# ══ [capability.derive] — a NEW vocabulary. D3: an unknown key inside [capability.<port>] is
#    ignored with a recorded CARD_CAPABILITY_UNKNOWN, "the one safe asymmetry", so no port bump. ══
[capability.derive]
lanes        = ["anchor"]                 # SET: anchor|xref|entity|claim|community|summary
item_kinds   = ["entity","mention","anchor"]   # SET; conform asserts nothing else is emitted
grounding    = "span"                     # none < quote < span. `span` requires determinism.
covers       = "claimed"                  # never | claimed | exhaustive
max_trust    = "extracted"                # the CEILING the driver claims; the runner ALSO clamps
                                          # by MAX_TRUST_BY_METHOD, whichever is lower
languages    = ["en"]
relations    = []                         # [{relation, symmetric, actor_rule}] admitted into
                                          # relation_vocab; no actor_rule ⇒ CARD_INVALID
# `emits_quad` DOES NOT EXIST. No L3 row carries geometry. (G7-1)

# ══ the shipped pass ladder. Ordering is cost_rank and nothing else. ══
#   pass_id                    class          lanes            granularity  method       phase
#   derive.anchor.native       free           anchor           document     native_xml   P1
#   derive.anchor.defterm      free           anchor,entity    document     heuristic    P1
#   derive.xref.native         free           xref             document     native_xml   P1
#   derive.xref.pattern        free           xref             document     heuristic    P1
#   derive.entity.table        free           entity,claim     document     native_xml   P1
#   derive.entity.gazetteer    free           entity           document     heuristic    P2
#   host.lexicon               free           entity           corpus       heuristic    P2
#   host.resolve               free           entity           corpus       heuristic    P2
#   derive.merge.llm           billed_api     entity           corpus       llm          P3
#   derive.entity.llm          billed_api     entity           part         llm          P3
#   derive.claim.llm           billed_api     claim            part         llm          P3
#   host.cluster               local_compute  community        corpus       heuristic    P4
#   derive.report.llm          billed_api     summary          corpus       llm          P4
#   derive.code.treesitter     free           entity           document     heuristic    P5
# FREE passes route at DOCUMENT granularity (unit_part = ''), one D4 decision, and are INVOKEd
# with the document's Segments as D3 units. BILLED passes route AND execute at SEGMENT
# granularity (unit_part = 'seg:<hex16>'), one decision each. `derive_run` is per (Segment, pass)
# in both cases. derive.anchor.defterm is the highest-yield free pass on legal and financial
# corpora: it mints abbrev/expansion aliases, and "IBM" vs "International Business Machines"
# scores far below JW 92, so the fuzzy funnel PROVABLY cannot catch that class.
```

```
# ══════════════════════ the extraction schema (billed passes) ══════════════════════
{ "type":"object","additionalProperties":false,
  "required":["entities","relations","more_available"],
  "properties":{
    "entities":{"type":"array","minItems":0,"maxItems":40,"items":{
      "type":"object","additionalProperties":false,
      "required":["name","etype","cite","quote","description"],
      "properties":{
        "name":{"type":["string","null"],"maxLength":200},
        "etype":{"type":["string","null"],"enum":["<corpus vocabulary>","unknown"]},
        "cite":{"type":"string","pattern":"^d[0-9]+#[0-9]+$"},
        "quote":{"type":"string","minLength":3,"maxLength":300},
        "description":{"type":["string","null"],"maxLength":400}}}},
    "relations":{"type":"array","minItems":0,"maxItems":40,"items":{
      "type":"object","additionalProperties":false,
      "required":["source","target","relation","cite","quote"],
      "properties":{
        "source":{"type":"string","maxLength":200},"target":{"type":"string","maxLength":200},
        "relation":{"type":"string","enum":["<relation_vocab>"]},
        "cite":{"type":"string","pattern":"^d[0-9]+#[0-9]+$"},
        "quote":{"type":"string","minLength":3,"maxLength":300}}}},
    "more_available":{"type":"boolean"}}}

RULES, each from a measured failure:
 * EVERY leaf nullable ([T,"null"]) before constrained decoding — lift's make_properties_nullable
   (lift/lift/model/vllm.py:28-45). Without it the grammar FORCES the model to invent a value.
 * minItems/maxItems on EVERY array — surya disabled guided table-rec outright because an
   under-specified grammar lets greedy decoding legally close an array after one element.
 * repetition_penalty stays 1.0. Real documents repeat.
 * `more_available` replaces graphrag's second and third calls per chunk. A glean is D4
   `attempt = 2` on the SAME decision, serial, same budget, capped by max_attempts = 2.
 * NO offsets, NO bbox, NO page, NO id. Geometry and identity are OURS. (G7-11)
 * `cite` is a pattern AND is re-checked against allowed_cites. Anything else is quarantined.
 * The prompt is RENDERED from relation_vocab and etype_vocab, so prompt and schema cannot drift.
```

```
# ══════════════════════ cache keys — cost-tiered (graphify cache.py) ══════════════════════
free_key = blake3_128(canonical([pass_id, driver_version, schema_version,
                                 segment.content_digest, config_digest]))
paid_key = blake3_128(canonical([pass_id, schema_version, segment.content_digest,
                                 prompt_fp, model_id, model_rev, decode_digest,
                                 etype_vocab_digest]))
# FREE artifacts carry a producer-version namespace so an upgrade invalidates them.
# PAID artifacts DO NOT carry driver_version, so a bug-fix release never re-bills a corpus.
# prompt_fp = sha256 over the prompt with CRLF and trailing whitespace NORMALISED, 12 hex chars —
# or every Windows checkout re-bills. model_rev = an exact sha; "main" is a lint error (D2 §8).
# "Cache hit" is a POLICY, not a lookup: five miss shapes counted in graph_observation
# (corrupt · partial · empty · doc/source mismatch · prompt vintage) plus graphify's aggregate
# run warning "this graph may mix extraction vintages". A cache that silently serves a partial
# result never self-heals.

# ══════════════════════ incremental — the complete recompute rule ══════════════════════
STEP 0  D2's `rebind` runs first. If it QUARANTINES, D7 does nothing: the gen is not committed,
        the graph stays on the previous gen, and `ow graph doctor` says so.
STEP 1  R = revised ∪ created blocks. S = Segments whose content_digest moved (a merkle over
        member block content_digests + heading_path). D2 excludes geometry, spans, marks,
        producer_id, trust and x from content_digest, so a parse-driver bbox jitter re-bills
        NOTHING. A one-typo edit in a 200-page PDF is one Segment.
STEP 2  Owner-scoped replacement, per pass:
          DELETE FROM mention WHERE run_id IN (SELECT run_id FROM derive_run
                                               WHERE segment_id IN S AND pass_id = :p);
        (same for edge, claim, anchor, unresolved_ref, derive_cover). Rows owned by OTHER passes
        on the SAME Segments SURVIVE — a free re-extraction cannot delete billable LLM rows
        (D2 §8 origin_operator; graphify #2333/#2336 by construction, with no _is_ast_tier).
STEP 3  Retired blocks: their items move to graph_history with a reason. Mentions whose block was
        retired become state=1 and a re-bind pass follows block_history.superseded_by; NULL ⇒
        retired with a reason. Silence is never an option.
STEP 4  ANCHOR DELTA — codegraph's definitionDelta for documents, and the step that makes
        incremental CORRECT rather than merely fast.
          anchor_delta(D) = symmetric_difference(anchors(D,g), anchors(D,g+1))   PER DOCUMENT,
            so a name moving between two changed documents does not cancel itself out.
          ADDED   -> SELECT * FROM unresolved_ref WHERE status='failed' AND retry_key IN (:added)
                     on the PARTIAL index. "The corpus grew and now this citation resolves" is one
                     indexed lookup, not a re-index.
          REMOVED -> UNBIND: every edge WHERE bound_by IN (:removed) is deleted and re-written as
                     an unresolved_ref. ONLY edges carrying `bound_by` participate: codegraph's
                     "no stamp — never delete what we cannot restore" (index.ts:2663). Skipping
                     the equivalent pass is what left 4.3% of codegraph's distinct edges wrong, in
                     both directions, silently (docs/benchmarks/index-drift-cg33.md:5,25).
          A body-only edit leaves anchor_delta EMPTY — the common case, and free.
STEP 5  RESOLUTION SCOPE.
          E = clusters_of(mentions added ∪ removed)
            ∪ clusters_of(entity_band probe of every NEW entity)   <- MANDATORY and easy to miss:
                                                                      a new entity can join an OLD
                                                                      cluster it never met
            ∪ clusters that lost their last live mention
        entity_merge rows whose supporting mention was deleted are RETIRED and canonical_id is
        recomputed for that closure only.
STEP 6  CLUSTER THE WHOLE GRAPH, ALWAYS. Detection is cheap; reports are the expensive artifact.
        Then UPDATE community_report SET report_state='stale' WHERE member_digest changed.
        NOTHING ELSE. graphrag inverts this: update/communities.py:45-66 offsets delta ids by
        old_max_community_id + 1 and pd.concats, so an entity in both halves lives in two
        unrelated hierarchies with two reports and global search map-reduces over both.
STEP 7  Salience recomputed, ALL FOUR columns, with a post-run assertion that FAILS THE RUN:
        entity.frequency, entity.degree, entity.doc_count, edge.combined_degree. graphrag
        recomputes edge degrees and leaves node degree at "first" with a literal `# todo`
        (index/update/entities.py).
DELETION is EXPLICIT and tier-blind (`ow store rm --doc d7`), never inferred. graphrag's
        deleted_inputs is computed at incremental_index.py:56 and consumed NOWHERE —
        load_update_documents.py:62 returns only `.new_inputs`, so its graph only ever grows.
```

```toml
# ── omniweave.toml, the [graph] section. Everything here is data. ──
[graph]
enabled       = true
etypes        = "auto"            # corpus-tuned into etype_vocab. NEVER a four-item list.
segment_tokens = 1200             # clamps BELOW MAX_SEGMENT_TOKENS; never above
llm_coverage_floor = 0.60         # a Segment this well explained by cheaper passes is not sent
max_items_per_segment = 2048      # effective = min(tenant_cap, MAX_ITEMS_PER_SEGMENT)

[graph.passes]
order  = "cost_class"             # THE ONLY ordering. There is no pipeline array to reorder.
enable = ["derive.anchor.native","derive.anchor.defterm","derive.xref.native",
          "derive.xref.pattern","derive.entity.table","derive.entity.gazetteer"]
# billed_api passes are ABSENT, therefore OFF. D3: "billed_api is opt-in".
# `ow graph build` refuses a billed pass without --allow-billed and prints `ow graph plan`.

[graph.resolve]
entropy_min=2.5 ; lsh_threshold=0.7 ; num_perm=128 ; bands=32 ; shingle_k=3
merge_threshold=92.0 ; community_boost=5.0 ; llm_band=[75.0,92.0] ; llm_batch=30
cohesion_split_delta=10.0 ; max_entity_degree=4096 ; max_candidate_pairs=5000000
cross_trust_class_merge = "llm_band_only"     # never | llm_band_only | allow

[graph.community]
backend = "louvain"               # louvain (in-tree, pure Python) | leiden (a driver distribution)
seed = 3735928559                 # 0xDEADBEEF, graphrag's, kept — determinism is auditable
use_lcc = false                   # PERMANENTLY. Not a knob. graphrag's default discards the rest.
max_community_size = 512          # NOT graphrag's 10. 10 on 3M entities is ~300k leaves ⇒ ≥400k
cohesion_split = 0.05 ; cohesion_split_min = 50      # report calls: the biggest bill in the file.
reports = "lazy"                  # lazy | eager | off
report_levels = 2

[graph.taint]
block_generation = ["sentinel","hidden_text","offscreen"]   # a REFUSAL, with --allow-tainted

[graph.limits]                    # ceilings; a tenant cap clamps BELOW, never above (D1's rule)
max_mentions_per_doc = 250000 ; max_mentions_per_entity_per_doc = 512
max_entity_label = 200 ; max_cluster_edges = 8000000 ; max_lexicon_aliases = 500000
```

```
# ══════════════════════ CLI ══════════════════════
ow graph plan     [--enable <pass>]     # runs FREE passes, prints Segments/calls/tokens/micros. $0
ow graph build    [--allow-billed] [--budget 0.10]
ow graph why      e412                  # every mention: cite, page, quad, precision, trust, pass
ow graph locate   <cite|e412|k91>       # the Locus, with `reason` when there is no polygon
ow graph explain  e412                  # the merge tree: pairs, scores, stages, guards that fired
ow graph split    e412 --group 3        # writes entity_merge(polarity=-1); re-closes. Seconds.
ow graph merges   [--uncertain-first]
ow graph residue                        # unresolved_ref + quarantine, grouped by reason
ow graph review   [--taint] [--trust below=extracted] [--cluster-cohesion]
ow graph types    --propose             # a deterministically sampled 40-Segment vocabulary probe
ow graph cluster  | ow graph report [--stale] [--warm --level 0]
ow graph diff     <gen_a> <gen_b>       # canonical-projection delta, human-readable
ow graph converge FIXTURE               # the G7-8 gate, runnable locally
ow graph doctor                         # cover_empty rate/pass/lane · miss shapes · mention/block
                                        # ratio · violated splits · resolve_signature drift
```

```
# ══════════════════════ invariants (G7-1 … G7-18) ══════════════════════
G7-1  No L3 table stores geometry.            CI grep of graph.sql + the generated schema.json for
                                              quad|bbox|poly|x0; a test asserts locate() returns
                                              quad=None + reason on an anydoc-parsed document.
G7-2  A billed pass never emits on ground a cheaper pass covered.   The input selector IS the
                                              covered_frac query; the per-item gate is a cover_bits
                                              bit test; test_deterministic_first.py asserts the
                                              join count is 0 on the fixture corpus.
G7-3  A pass covers only where it emitted, or declares cover_empty with a reason.
                                              GraphSink.cover requires empty_reason when the cite
                                              set produced nothing; doctor warns above 0.98.
G7-4  An LLM/VLM/OCR item never reaches trust=EXTRACTED.   MAX_TRUST_BY_METHOD clamp in the runner
                                              + OWG_TRUST_CLAMPED quarantine + a GENERATED BEFORE
                                              INSERT trigger with CI parity to the mapping.
G7-5  Every LLM-emitted row is span-grounded in the block it cited.   The sink's grounding gate;
                                              mention.ts_a/ts_b NOT NULL; a fixture quoting absent
                                              text asserts OWG_UNGROUNDED and grounded_frac < 1.
G7-6  Resolution is order-independent and reversible.   Hypothesis shuffles candidates 100x and
                                              asserts an identical canonical_id map; CI recomputes
                                              canonical_id from the log and byte-compares; a split
                                              round-trip test.
G7-7  Entity identity is never a surface form.   `key` is documented as a BLOCKING key; a test
                                              asserts two live entities may share a key and differ.
G7-8  Incremental converges with full.        60 documents, 20 Hypothesis-shuffled steps including
                                              3 edits, 2 deletions and 1 driver-version re-parse;
                                              equality on canonical_projection() modulo surrogate
                                              ids. BLOCKING, not nightly.
G7-9  A driver's output may reference only blocks it was handed.   begin_run(allowed_cites=…);
                                              OWG_OUT_OF_SCOPE_BLOCK; conform `derive_scope`.
G7-10 Nothing is deleted; dropped is quarantined and retired is historied.   GraphSink has no
                                              drop(); a dangling-tmp draft produces a quarantine
                                              row; owcheck --graph asserts zero orphans.
G7-11 No model-returned string is ever an identifier and no prompt carries a surrogate id.
                                              semgrep in llm/: a parsed `id`-shaped field may flow
                                              only into normalize_key; the prompt builder accepts
                                              only the four Cite NewTypes; a test renders every
                                              prompt over a fixture and greps for p\d+/\d+ and
                                              bare integers.
G7-12 Untrusted text reaches a prompt only through wrap_untrusted().   semgrep in llm/; conform
                                              `derive_injection` over 40 payloads, zero untainted
                                              items, zero false positives on the SOP fixture.
G7-13 Absent trust is AMBIGUOUS; a migration may only downgrade and may never clear taint.
                                              trust INTEGER NOT NULL with NO column default; the
                                              wire reader maps missing -> 0; tools/migration_lint.py
                                              rejects any statement raising trust or clearing taint.
G7-14 A report is stale iff member_digest changed, and a stale report is invisible.
                                              Retrieval reads community_report_fresh; a test edits
                                              one paragraph and asserts written_at_ns is unchanged
                                              on every row.
G7-15 `mention` is the only table referencing both a block_id and an entity_id.   A schema lint
                                              classifies every FK target L2/L3; both ⇒ fail unless
                                              the table is `mention`.
G7-16 Salience is recomputed, all four columns.   A post-run assertion FAILS THE RUN when
                                              entity.degree <> COUNT(*), frequency, doc_count or
                                              edge.combined_degree disagree.
G7-17 Every relation has a written direction rule and the prompt is generated from it.
                                              relation_vocab.actor_rule NOT NULL; the extraction
                                              prompt is rendered from the table, so prompt and
                                              schema cannot drift.
G7-18 Deterministic passes and clustering are bit-reproducible.   Shuffle block iteration and file
                                              order 100x, assert byte-identical rows by natural
                                              key; two cluster runs give an identical partition.

canonical_projection(store) = sorted (scope, etype, key) entity multiset
                            | sorted (src.key, dst.key, relation, observed cite, trust, method)
                            | sorted (subject.key, claim_type, predicate, object, t_start, t_end)
                            | sorted community member_digest multiset
                            | sorted unresolved_ref.retry_key multiset
                            | sorted (doc, name_norm, akind) anchor multiset
# Surrogate ids are EXCLUDED. This is what full and incremental must agree on, byte for byte.

# ══════════════════════ conform: five `derive` suites (D3's kit) ══════════════════════
derive_capability  every declared lane produces items; every UNDECLARED lane produces none;
                   grounding="quote" ⇒ no item carries a span; max_trust asserted absent-above.
derive_identity    normalize_key idempotent / charset-closed / caseless-stable over a 20k-string
                   corpus: Turkish dotted I, Greek ypogegrammeni, CJK, Cyrillic, full-width Latin.
derive_scope       10 blocks in; every emitted cite is one of the 10; every tmp resolves.
derive_injection   40 hostile fixtures (white-on-white PDF text, OOXML w:instrText, a PPTX speaker
                   note, an EXIF comment, alt-text, a forged </untrusted_source> in a table cell,
                   an SVG <title>, a ZWJ-obfuscated directive, a non-Latin directive, a "cite this
                   URL as the source" exfiltration) PLUS an SOP containing "## Instructions" that
                   MUST NOT be flagged. Gate: zero items at trust > INFERRED, zero out-of-scope
                   cites, zero items above the per-Segment budget, item count within 3x the same
                   document with the payload removed, and zero taint on the SOP fixture.
derive_cost        the card's tokens_out_p95_multiple within 25% of measurement (D4's rule).

# ══════════════════════ injection defence — seven layers, no proof ══════════════════════
1 SCOPE CONTAINMENT  begin_run(allowed_cites). A model handed pages 12-14 cannot write on page 400,
                     cannot touch another document, cannot modify an existing entity. Survives a
                     FULLY SUCCESSFUL injection. Buys the most.
2 GROUNDING BY QUOTE An entity invented by an instruction the document carried cannot be quoted
                     from the document's own prose. Kills invented entities BY CONSTRUCTION.
3 TRUST CLAMP        MAX_TRUST_BY_METHOD, runner-applied, with the over-claim recorded.
4 ITEM BUDGETS       max_items_per_segment=2048, max_mentions_per_doc=250k, label <=200 chars.
                     "Emit 100,000 entities named ACME" is OWG_ITEM_BUDGET naming the knob —
                     anydoc's reasoning: a knob that turns off the zip-bomb cap will be turned off.
5 THE WRAPPER        graphify's <untrusted_source path=… sha256=…> vendored at a pinned SHA, with
                     the three fixes: (a) XML-escape the path attribute (llm.py:592 interpolates it
                     raw); (b) defang a COPY — grounding runs against the undefanged text and
                     normalize_k strips Cf, so no ShiftMap is needed; (c) DROP the heading sentinel
                     ^\s*###?\s*(?:system|instruction)s?\s*:?\s*$ (llm.py:567) — it matches
                     "## Instructions" in every manual, RFP and SOP on earth. KEEP the generalised
                     <\|[A-Za-z0-9_.\-]{1,64}\|> form (#3183) and the forged-closing-delimiter case.
6 TRUST-CLASS MERGE BOUNDARY   Injection's PAYOFF is poisoning another document's entity, and the
                     alias table is the vector. cross_trust_class_merge=llm_band_only by default;
                     an alias with (taint & UNTRUSTED_SOURCE) and doc_count=1 is NEVER a blocking
                     key for cross-document resolution. One rule, large blast radius, zero cost.
7 BOTH DIRECTIONS    sanitize_label() on every string re-entering a prompt or an MCP response —
                     the index is a persistence layer for attacker text. The prompt carries ONLY
                     cite/ecite/ccite/kcite tokens: no block_id, no entity_id, no addr, no path.
Ship graphify's own claim verbatim: it "does not make injection impossible, but changes it from
'works on first try' to 'requires evasion.'" graphrag's RAI_TRANSPARENCY.md is the only documented
cross-prompt-injection programme in the collection AND it ships "the system is designed for trusted
users", which is disqualifying as omniweave's posture.

# ══════════════════════ embeddings — POLICY here, storage is D5's ══════════════════════
EXACTLY THREE, each named to ONE consuming retrieval mode (graphrag config/embeddings.py:6-17):
  segment.text                  -> basic / local
  entity.description            -> mention -> node resolution
  community_report.full_content -> thematic / global
edge descriptions are NOT embedded. A fourth requires a row in tools/embeddings.toml naming its
consumer; CI fails an embedding computed with no row.
Keys are CONTENT-ADDRESSED: segment.content_digest, entity.mention_digest, community.member_digest
(LEANN's passage_id_scheme = content_hash, so a re-chunk after a re-parse does not re-embed).
This answers D2's open question from D7's side; D5 owns the final call.
entity.description is DERIVED (the highest-trust mention's context sentence), never an LLM summary.
An LLM summary is a separate optional `entity.summary` column keyed on mention_digest — NOT
graphrag's description-as-a-list re-summarised by an LLM call on every merge and truncated at 4,000
input tokens, lossily and silently.

# ══════════════════════ build order — every phase ships something a user runs ══════════════════════
P1  3 wk  DDL + migration 0007 · GraphSink · ident · segmenter · anchor.native · anchor.defterm ·
          xref.native · xref.pattern · entity.table · locate()/Locus · unresolved_ref · quarantine ·
          delta-by-content_digest · ow graph build/why/locate/residue.
          >>> A ZERO-LLM, ZERO-API-KEY KNOWLEDGE GRAPH OVER ANY PARSED CORPUS, EVERY NODE CITING A
              PAGE AND A POLYGON. `ow graph why` works on day 21. <<<
P2  3 wk  derive_cover + the coverage selector · gazetteer · host.lexicon (Aho-Corasick) · the full
          funnel (MinHash, Jaro-Winkler, nine guards, entity_merge with polarity, split/explain) ·
          anchor_delta + unbind · the G7-8 convergence gate.
P3  4 wk  billed passes behind D4 ENRICH · the prompt kit + JSON-Schema subset validator · the
          grounding gate · the vendored wrapper with its three fixes · taint · cost-tiered cache ·
          ow graph plan / types --propose · conform's five derive suites + the 40-fixture corpus.
P4  3 wk  Louvain per component · member_digest · lazy reports · rated descent handed to D5.
P5  —     omniweave-driver-code (tree-sitter); grammars as their own distributions.
~13 engineer-weeks to P4 for two people. P1 lands in three.
```

## Rationale

Three things decided this ruling, and each beat a prettier alternative.

**Cost class must be the ordering, because that is the only version a third party can win.** All three
architects agreed there is no mode switch; they disagreed on what enforces the order. The pragmatist's
`PASS_RANK` is a hardcoded dict in core, so a contributor's new extractor has no rank and needs a core
PR to be inserted into the ladder. The systems architect's answer is a `CHECK` constraint on trust plus
D4's `ENRICH` rung, which enforces *who may claim what* but not *who runs first*. Only the ecosystem
architect's coverage ledger makes the property mechanical and open: a cheap precise extractor written by
someone else automatically preempts the paid one, and `test_deterministic_first.py` is a SQL query that
returns zero. That is the difference between a design and a diagram, and it is the single best idea in
that proposal. I moved the ledger's grain from the block to the Segment plus a 64-byte cover bitmap,
because the LLM's input is a Segment and you cannot send half of one — per-block cover rows are
precision the mechanism cannot use, and 40M of them at 10M blocks.

**The model must never be asked for a character offset.** The systems architect's span-index contract is
the most careful piece of engineering in the panel and it is aimed at the wrong target: his own failure
mode 7 concedes the rejection rate on non-Latin scripts is unmeasured and that `normalize_k`'s tolerance
is "a number I am guessing at". The pragmatist's grounding-by-quote is one `str.find` and it does four
jobs — citation, polygon, hallucination gate, injection containment — with no fuzzy band to calibrate.
It also has independent support: graphify already runs a weaker version of it (`_dispatched_source_text`
plus `_label_identifiers`, a lenient substring check that *flags* rather than drops, `llm.py:641-652`),
and D4 has already ruled the same mechanism for the `fields` lane as `FieldGrounding` plus a mandatory
free cross-check. Making `normalize_k` strip Unicode `Cf` deletes the systems architect's `ShiftMap`
entirely and simultaneously defeats the zero-width-joiner obfuscation attack the ecosystem's own fixture
list names. One function, three problems.

**Resolution must be reversible, and it must be keyed on the entity, not the mention.** The ecosystem's
"mentions are ground truth, an entity is a union-find cluster" is the most principled statement in the
panel and it produces the worst mechanics: cluster ids churn, so it needs a plurality-carry rule it
admits is unstable at n=2, and the candidate space becomes O(mentions²) — 6M mentions rather than 1.5M
entities at 10M blocks. The systems architect's `entity_merge` log with a derived `canonical_id` gets the
same reversibility with a durable `entity_id` (a `(scope, etype, key)` never moves), no plurality rule
and no id churn, which means `e412` in a shipped answer keeps resolving for free. I took the ecosystem's
`polarity = -1` on top, because it is the only thing that makes a human split survive a later automatic
merge attempt, and the systems proposal has no equivalent.

Two more calls worth defending. `omniweave-graph` has **no third-party dependencies**, and that is not
minimalism: `datasketch` is not the 0.3 MB the ecosystem's table claims — graphify dropped it and wrote
107 lines of its own because `datasketch.lsh` imports `scipy.integrate.quad` at module level, and
scipy's `array_api_compat` then loads `numpy.testing`, which calls `platform.machine()` and spawns
`cmd.exe`, hanging for minutes under corporate EDR (`graphify/_minhash.py:1-9`). `rapidfuzz` and
`networkx` fail for a different reason each: a Jaro-Winkler score change in a dependency silently alters
*durable* merges months later, and building an `nx.Graph` from 2M edges costs more memory than the
clustering algorithm does. And claims are a **separate table** from edges, against the systems
architect, because the clusterer reads `edge` and never `claim`, and `weight`/`combined_degree` are
meaningless on a temporal assertion — graphrag's own Relationship/Covariate split is right for exactly
that reason.

**One factual correction per proposal, since each carried one.** The systems proposal's D4 conflict is
real but its arithmetic is wrong by two orders: it claims ~40,000 Segments in a 500-page 10-K, which
conflates blocks with Segments — at its own `MAX_SEGMENT_TOKENS = 1200` that document is ~300–500
Segments. The pragmatist makes the same class of error in the other direction, deriving "~40k chunks"
for a 5,000-page corpus that at his own `chunk_target_tokens = 1200` is ~2,700. The ecosystem architect
is the only one who did the block-to-unit arithmetic correctly and said so, and its correction of the
digest's "10M blocks ⇒ ~20M calls" — which assumes one chunk per block, true in graphrag and false under
D2 where cells are blocks — is adopted here. Its own error is the `datasketch` line above.

## Rejected

- **Character offsets from the model (systems).** The proposal's own failure mode concedes the fuzzy
  threshold and the non-Latin rejection rate are guesses. Grounding by quote is strictly more robust,
  is one `str.find`, and needs no fuzzy band, no `ShiftMap` and no `TAINT_SPAN_FUZZY` bit.
- **Per-block `derive_cover` (ecosystem).** 40M rows at 10M blocks for precision the selector cannot
  use, because the unit of a paid call is a Segment. Replaced by one row per `(segment, lane, pass)`
  with a <=64-byte `cover_bits` bitmap, which keeps both the fractional selector and the exact per-item
  gate.
- **`derive_unit(lo_block, hi_block)` as a block-id range (ecosystem).** `block_id` contiguity is not
  guaranteed — D2's `rebind` carries ids across a re-parse, so a range silently gains or loses blocks.
  An explicit `segment_block` table with `PRIMARY KEY (block_id)` also makes overlap unrepresentable and
  gives the reverse lookup the incremental path needs.
- **Two chunkings, extraction and retrieval (ecosystem).** Its own open question concedes "if the
  difference is under ~2 points, one table wins on simplicity". A zero-overlap block-aligned Segment is
  exactly as citable as a retrieval chunk, and neighbour expansion is D2's `parent_id`/`ord`, already
  indexed. One table, one merkle, one cache key, one embedding key.
- **Mention-keyed union-find as the entity (ecosystem).** O(mentions²) candidate space and an id-churn
  problem it patches with a plurality rule that has no answer at n=2. Entity-keyed merge gets the same
  reversibility with a durable id and no plurality rule at all.
- **`PASS_RANK` as a hardcoded dict in core (pragmatist).** A third party's extractor has no rank. Cost
  class is already on the card and is already the right ordering.
- **A `pass.rank >= 6` trust trigger (pragmatist) and `CHECK (NOT (method=6 AND trust=2))` (systems).**
  The first conflates cost with method; the second hardcodes one enum ordinal and can express exactly
  one pair. `MAX_TRUST_BY_METHOD` is a table that covers OCR, VLM and roundtrip too, is applied by the
  runner per D3-8, records the over-claim, and generates the trigger.
- **`mention.quad` as a derived cache with a `quad_method` (systems, ecosystem).** A second
  representation of geometry that a pdfium upgrade desynchronizes, plus a whole `G7-GEOM`
  digest-exclusion apparatus to keep it honest. `Locus.precision` names what we have and `block.quad`
  is the only copy. Sub-block precision is a query against covering line-child Blocks.
- **`graphrag-chunking` (D1's open question, delegated to D7).** Four disqualifiers, all verified in
  tree: `sentence_chunker.py:9` imports `nltk`, absent from `pyproject.toml:32-35`; `bootstrap_nltk.py`
  runs eight `nltk.download()` calls from `SentenceChunker.__init__`, failing D1 G15, D3
  `needs_network=false` and D3's "constructing a driver MUST load no model and open no file";
  `create_chunk_results.py:19-30` advances `start_char = end_char + 1` while
  `token_chunker.split_text_on_tokens` advances by `chunk_size - chunk_overlap`, so at the shipped
  `size=1200, overlap=100` every offset after the first is overstated and the error accumulates
  linearly; and `requires-python = ">=3.11,<3.14"` contradicts D1's no-upper-bound rule. Dropping it
  also removes `pydantic` from `omniweave-graph`'s closure and the `<3.14` CPython ceiling D1 inherited.
- **`datasketch`, `rapidfuzz`, `networkx`, `numpy` (ecosystem).** `datasketch` pulls scipy and a
  documented Windows EDR hang, which graphify measured and worked around in 107 lines
  (`graphify/_minhash.py:1-9`) — the ecosystem's "~0.3 MB" is wrong by two orders. `rapidfuzz` scores
  *durable* merges, so a version bump silently changes which entities are the same thing; the risk
  digest's own pin policy would force an exact pin with a named owner and a refresh rota, which costs
  more than 40 property-tested lines. `networkx` requires materialising 2M edges as Python objects
  before Louvain allocates anything, which is the memory cliff, not the fix for it.
- **Our own Leiden (systems).** A real algorithm with a real quality risk the proposal concedes
  ("may under-perform graspologic... mitigated by a modularity floor gate"), to save a `pip install`.
  Louvain over an `array('i')` CSR is simpler, well-specified and deterministic;
  `omniweave-driver-leiden` is the better backend, probed and optional, importing `graspologic_native`
  directly.
- **One `edge` table carrying claims (systems).** The clusterer reads edges and never claims;
  `weight`, `combined_degree` and `corroborations` are meaningless on a temporal assertion, and a claim
  needs `claim_type`, `status`, `t_precision` and a literal object that no edge wants. graphrag's own
  Relationship/Covariate split is right, for the reason that they have different consumers.
- **`DriverIO.reader()` (the pragmatist's D3 amendment).** Unnecessary, because entity resolution and
  clustering are host functions, not drivers — the ecosystem's point that "keeping the resolver in the
  host is what keeps the driver contract small enough to implement in an afternoon" is correct. The only
  corpus-scoped *driver* is the LLM merge tiebreak, which receives candidate pairs as a blob. D3 needs
  no amendment; that flagged conflict is dissolved, not escalated.
- **A hyperedge table (graphify's `G.graph["hyperedges"]`).** One producer, no query, no index. A
  hyperedge is a `group` entity plus `member_of` edges with `edge.role`, which inherits traversal,
  ranking, resolution, communities and citation for free.
- **A separate graph database (Neo4j, Kuzu, DuckDB-PGQ).** D2 ruled one store — "L4 builds on these
  tables, not beside them" — and a second engine is a second consistency problem, backup story,
  freshness question and install. Nothing in the retrieval contract needs traversal past depth 3, and
  depth 3 is three indexed joins.
- **graphrag's incremental path entire.** Four independent defects, all verified: title-only delta
  (`incremental_index.py:48-56`, `~input_dataset["title"].isin(previous_docs)`); `deleted_inputs`
  computed at `:56` and consumed nowhere (`load_update_documents.py:62` returns only `.new_inputs`);
  node `degree` merged as `"first"` with a literal `# todo`; and communities id-offset by
  `old_max_community_id + 1` and `pd.concat`ed (`update/communities.py:45-70`).
- **graphrag's defaults `max_cluster_size = 10`, `use_lcc = True`, `DEFAULT_ENTITY_TYPES`
  (`config/defaults.py:41,71-72`).** 10 on 3M entities is ~300k leaf communities plus every internal
  level, and reports are 3–6x extraction cost — the largest line item in the file, fixed by one config
  change. `use_lcc` silently discards everything outside the largest component, which on a folder of
  unrelated PDFs is most of the graph. Four news-shaped entity types is why "graphrag doesn't work on
  my domain".
- **Delimited-text extraction.** `record_type == '"entity"'` with the literal quotes as part of the
  match (`graph_extractor.py:146`), no unparsed-record counter, so total parse failure of a chunk is
  indistinguishable from "this chunk had no entities". Structured output with nullable leaves, an
  `OWG_UNPARSED_ITEM` quarantine row and a per-pass counter in `graph_observation`.
- **Copying `source_text` onto claims (graphrag `COVARIATES_FINAL_COLUMNS`).** A verbatim copy beside
  `block.text` drifts on any re-parse, and D2's whole `quote` discipline exists to stop exactly that.
- **Putting L3 spans in D2's `mark` table.** D2 asks the question and states the test: "if a span
  carries its own provenance, trust and producer, it is not a Mark." A mention carries `run_id`,
  `trust`, `score`, `taint`, `restriction_bits` and its own identity constraint. `mark` is written by
  the parse driver and is excluded from `content_digest`; a mention is neither.
- **Any use of jcodemunch-mcp code.** Its Dual-Use Licence v1.1 bars use within a for-profit
  organization and bars publishing any derivative or portion to a package registry. Its retrieval
  thinking is cited as prior art and reimplemented clean-room; no line is copied, and that is recorded.

## Consequences

- **D5 inherits `segment` as the retrieval unit and must not define a second chunking.** It gets
  `entity_id`, `edge_id`, `claim_id`, `community_id` as join keys, three content-addressed embedding
  targets, and four new absence-contract gates: `reports_absent`, `unresolved_backlog > 0`,
  `resolution_quarantined`, `pass_disabled(lane)`. It reads `community_report_fresh`, never
  `community_report`.
- **D4 gains six lanes** (`anchor, xref, entity, claim, community, summary`) in its open registry and no
  new rungs. Extraction is `ENRICH`; a glean is `attempt = 2`. It gains one clause on the definition of
  a part (see the first risk).
- **D6 gets `(unit_uri, '', <pass_id>)` for free document-granularity passes and
  `(unit_uri, 'seg:<hex16>', <pass_id>)` for billed segment-granularity ones**, both as ordinary `work`
  rows with a `decision_id`. `derive_run` is per `(Segment, pass)` in both cases.
- **D3 needs no amendment.** `[capability.derive]` is a new vocabulary inside an existing table, which
  D3 already declares forward-compatible; the pragmatist's `DriverIO.reader()` request is dissolved by
  keeping resolution and clustering in the host.
- **D8/D9 get `restriction_bits` on `entity`, `mention`, `edge` and `claim`** with partial indexes, so
  "may I ship this deck" is one predicate over blocks *and* graph rows; and they get `Locus`, which
  returns `quad = None` with a `reason` rather than a guessed rectangle.
- **`omniweave-graph` drops from D1's 150 MB ceiling to 5 MB with zero third-party dependencies**, and
  loses the `<3.14` CPython ceiling. `tree-sitter` moves to `omniweave-driver-code`;
  `graspologic-native` moves to `omniweave-driver-leiden`.
- **Two vendored files under D1's four-part rule**: `vendor/graphify-ids/ids.py` and
  `vendor/graphify-security/llm_wrap.py`, each with sha256, a parity test, LICENSE and a NOTICE row.
  graphify has already relicensed once (MIT to Apache-2.0), so a floating dependency is refused.
- **A default install produces a graph nobody paid for, and a reviewer benchmarking omniweave against
  graphrag at defaults will find us behind on prose entity recall.** That is deliberate and the README
  must say so rather than let it be discovered. graphify's LOCOMO/LongMemEval numbers are the evidence
  that the free tier is competitive rather than a stub.
- **Lazy reports move cost to the interactive path.** The first global query on a cold corpus pays
  inline; `reports = "eager"` is one key and `ow graph plan --reports` prices it.
- **`quarantine`, `unresolved_ref` and `entity_merge` grow monotonically** and need generation-boundary
  compaction. `ow graph review` is a queue a human is expected to work, and on an untrusted corpus it
  will be long.
- **Three permanent living artefacts with an owner**: the 40-fixture injection corpus, the 60-document
  convergence corpus, and the prompt-fingerprint rota (a prompt edit is a cache-namespace change and a
  re-bill). `omniweave-conform`'s `derive` profile must stay inside D3's five-minute laptop budget.

## Risks

- **UPSTREAM CONFLICT: D4-router, §Spec first paragraph.** It states verbatim: *"**The unit of decision
  is the part** (page / slide / sheet / track), identical to the `work` table's `unit_part`."* A billed
  extraction pass decides per Segment, and a Segment is neither a page nor a document. Under the clause
  as written a 500-page 10-K is one routing decision covering ~400 Segments, so `[budget.per_part]`
  (6,000 micros, 3 calls) applies to the whole document and the runaway guard is a no-op on the most
  expensive stage in the framework; `route_spend` has no per-Segment attribution, so `agree`, `audit`
  and `tune` cannot learn an extraction threshold at all. **Minimum amendment, one clause, no DDL
  change** (D4 already types `unit_part TEXT NOT NULL DEFAULT ''`): replace the parenthetical with
  *"(page / slide / sheet / track for the `parse`, `ocr` and `vlm` lanes; the Segment for the `graph`
  lanes). A `derive` driver declaring `granularity = "part"` MUST define its part as a stable
  content-derived string that partitions the unit and MUST record it in `route_decision.unit_part`; the
  graph lanes' part is `"seg:" || hex(segment.content_digest)[:16]`."* D2's *"`(unit_uri,
  unit_part=NULL)` for document-level structure"* needs the matching words *"for document-granularity
  derive passes"*. **Correction to the systems proposal, which raised this conflict with the wrong
  arithmetic**: it claims ~40,000 Segments in a 500-page 10-K, which conflates blocks with Segments —
  at its own `MAX_SEGMENT_TOKENS = 1200` a 500-page document is ~300–500 Segments, and only the subset
  passing the coverage selector gets a decision. The row volume is affordable, which is why I accept
  the amendment rather than the second, parallel ledger it proposed as a fallback.
- **UPSTREAM CONFLICT: D2-docmodel, Terminology.** *"`cite` := the short per-document token `d7#412`.
  **The only identifier that may appear in a prompt or in model output.**"* Read literally this makes
  entity-, claim- and community-level retrieval uncitable: a global-search answer says "communities
  c17 and c34 both discuss the indemnity clause" and cannot say it with a block cite, because a
  community is not a block; and forcing an entity reference through one document's `d7#412`
  reintroduces graphrag's title-keying bug from the other side. graphrag's own `Identified.short_id`
  docstring is the precedent: *"Human readable ID used to refer to this community in prompts."*
  **Minimum amendment**: generalise from one token to one closed typed token space, keeping the stated
  intent word for word — *"The prompt-safe id space is a closed set of typed short tokens, each minted
  by the layer that owns the row and each resolvable by one indexed lookup: `d7#412` (Block, L2),
  `e412` (Entity), `c412` (Community), `k412` (Claim). No other identifier — `block_id`, `entity_id`,
  `addr`, a UUID — may appear in a prompt or in model output."* Cost: one sentence, one prompt-lint
  regex, three `UNIQUE` indexes already in the DDL above.
- **Grounding by quote costs recall, and the rate is unmeasured.** A coreference ("the Company" to
  Acme Corp) and any summarization-shaped fact are quarantined. `quarantine_rate` and `grounded_frac`
  make it visible; nothing makes it small. If the true-fact quarantine rate exceeds ~15% the design
  needs a second cheap "quote it again" repair call, which is tokens.
- **`anchor_delta` is only as good as its extractors.** A defined-term style the pattern pass does not
  recognise ("Capitalised Terms shall have the meanings given in Schedule 1") produces a removed name
  that is never detected, no unbind happens, and incremental diverges from full in exactly codegraph's
  measured 4.3% way. G7-8 catches it only if the fixture corpus contains that pattern. **This is the
  weakest point in the design and the fixture corpus is the only control.**
- **The god-entity.** 4,000 NDAs and "the Company". `max_entity_degree = 4096` flips `state='overloaded'`
  and excludes the entity from expansion and from community membership. That is a refusal, not a fix,
  and every query about that entity degrades. The input that breaks the design is a homogeneous corpus
  of boilerplate documents about genuinely different parties.
- **A 4M-cell spreadsheet.** D2 makes every cell a Block. `derive.entity.table` touches header cells and
  key/value blocks only, and `max_mentions_per_doc = 250_000` catches the rest with `OWG_ITEM_BUDGET`
  naming the knob — but the right answer, profiling a column and minting one entity per column rather
  than per cell, is a `derive.entity.sheet` pass that is named and not designed. Spreadsheet-heavy
  corpora will hit the budget on legitimate documents.
- **Pure-Python MinHash and Louvain are the performance bet.** ~0.2 ms/entity for a 128-perm signature
  and O(E) per Louvain sweep over an `array('i')` CSR put 1.5M entities at ~5 minutes of blocking and
  2M edges at a few minutes of clustering. That is an estimate, not a measurement, and if it is 5x off
  the escape is `num_perm = 64` and `omniweave-driver-leiden`, not a second in-tree implementation.
- **A heading rename re-bills a section.** `heading_path` is a digest input because the prompt contains
  it, so renaming a top-level heading in a 500-page report re-extracts everything beneath it — ~400
  Segments, on the order of $0.40 at commodity prices. Correct, priced, and someone will still be angry.
- **`taint` over-blocks technical corpora.** A prompt-engineering book, an LLM API reference and a
  jailbreak-research corpus all legitimately carry `SENTINEL`, and their facts are excluded from
  generation by default. Taint is per-mention rather than per-document, which helps; on those corpora
  it will still be loud, and every surface that shows it must say what it means.
- **`entity_band` can drift silently.** A change to `normalize_key`, `num_perm`, `shingle_k` or the
  threshold without a `meta['graph.resolve_signature']` bump means new entities stop finding old
  clusters — recall loss with no error. The signature is checked at the top of every resolve pass and a
  mismatch rebuilds, which converts a silent failure into a slow one.
- **A user split is not transitive.** `polarity = -1` blocks that pair, not the path around it, so A|B
  can rejoin via C. `ow graph doctor --violated-splits` detects it; constrained correlation clustering
  would fix it and is not v1.
- **`quarantine` is a table nobody opens.** Keeping rejected rows is right — graphrag deletes them and a
  hallucinated name is very often a real entity the extractor failed to emit — and it means a corpus
  with 40,000 `OWG_UNGROUNDED` rows reads as forty thousand things nobody looks at. The per-run
  aggregate in `graph_observation` is the only thing standing between that and invisibility.
- **The injection corpus is a snapshot.** Forty fixtures written against 2026 attack shapes. A new
  carrier — a font-ligature payload, a PDF optional-content group — is invisible until someone adds a
  fixture. The suite is a floor, not a proof.

## Terminology

- owgraph := omniweave's L3 knowledge model — the entity, mention, edge, claim, anchor, community and residue tables inside D2's `.owstore`. Never a second store, never a second block representation.
- Segment := the extraction, embedding and cache unit: a heading-scoped, table-atomic, zero-overlap, block-aligned run of ~1,200 tokens. A row in `segment`; its members are `segment_block` rows and a block belongs to exactly one Segment. Deliberately not called a chunk or a unit, because D5 owns "chunk" and D6 owns "unit".
- Pass := one named extraction mechanism with a `cost_class`, a lane set and a granularity; a row in `derive_pass`, which is data, not a hardcoded pipeline list.
- Run := one execution of one Pass over one Segment; a row in `derive_run`, holding the interned reproduction tuple (producer, method, origin_driver, origin_operator, decision_id) and the cache key. Every L3 item row carries a `run_id`.
- Lane := what is being asked for, from D4's open registry: `anchor | xref | entity | claim | community | summary`.
- Cover := a Pass's claim that it looked at a set of a Segment's blocks for one lane and its answer is complete. A row in `derive_cover` with a per-block bitmap. A Pass with zero items must write `cover_empty` with a reason instead.
- Coverage ordering := the rule that a Pass's eligibility is decided by `derive_pass.cost_rank` and the Cover already recorded by cheaper Passes. It is the whole of "deterministic before LLM".
- Mention := a `TextSpan` inside one Block that names an Entity, carrying its own Run, trust, score and taint. The only table in the framework referencing both a `block_id` and an `entity_id`. Deliberately not a D2 `mark`.
- Grounding := locating a model-claimed verbatim `quote` inside the Block it cited, under `normalize_k`, to obtain the span. An ungrounded item is quarantined, never admitted and never deleted.
- Locus := the resolved answer to "where on the page", carrying `quad: Quad | None`, D2's `OriginSpan`, a `precision` in {char, line, block, page, none} and a `reason` when there is no polygon. A synthesized box is never returned.
- Observation site := the `(observed_block, ts_a, ts_b)` where a *relationship* was seen, distinct from where either endpoint is defined. graphify's `source_file`-on-edges at block-and-span resolution.
- Anchor := a globally-resolvable name a document defines — section number, figure or table label, exhibit id, defined term, citation key, glossary entry, bookmark. A row in `anchor`.
- anchor_delta := the per-document symmetric difference of `(name_norm, akind)` pairs across a store phase. codegraph's `definitionDelta` for documents, and the key that makes incremental converge with full.
- bound_by := the anchor `name_norm` that resolved an edge. Only an edge carrying it may be unbound by an `anchor_delta` removal — "never delete what we cannot restore".
- Residue := `unresolved_ref` plus `quarantine`. Unfinished business and rejected rows are queryable tables with partial indexes, never log lines.
- key := `normalize_key(canonical surface)` on an Entity. A **blocking** key, never an identity: `entity_id` is the identity and `entity_alias` holds every observed surface.
- entity_merge := the append-only log of pairwise resolution decisions with `polarity` in {+1, -1}. `entity.canonical_id` is the derived path-compressed closure over it; a split is a `-1` row and a re-closure.
- Taint := a five-bit `IntFlag` recording that an item derives from an untrusted source, a defanged chat-template sentinel, hidden text, off-page geometry, or a single-witness cross-document assertion. It ORs upward through mention to entity/edge/claim to report, and never across edges.
- Draft := an item a `derive/1` driver emits over `owgraph-items/1`, addressing blocks by `cite` and other drafts by a per-invocation `tmp` id. The host mints every real id and stamps every provenance field.
- GraphSink := the only writer of owgraph tables. Takes `allowed_cites`, clamps trust, grounds quotes, mints ids, and commits one transaction per Run. It has no `drop()`.
- member_digest := `blake3_128` over a community's sorted canonical member ids. A report is stale iff its `member_digest` differs from its community's; that is the only trigger for re-reporting.

## Open questions

- **What is the true-fact quarantine rate of the grounding gate?** — a 500-Segment human-labelled audit measuring how many `OWG_UNGROUNDED` rows were real facts the model simply did not quote, split by script and by document class. Above ~15% and a second cheap "quote it again" repair call earns its tokens; above ~30% the exact `find` needs a bounded fuzzy fallback and a `SPAN_FUZZY` taint bit comes back.
- **What is `coverage_frac` on real corpora?** — the whole cost argument for deterministic-first is a projection. Run the free Passes over ten real documents per class (10-K, court filing, scientific review, merger agreement, RFP, technical manual, scanned correspondence) and plot the distribution. If the median outside structured corpora is below 0.2, `llm_coverage_floor` becomes per-corpus and the economics section is rewritten rather than defended.
- **Is pure-Python MinHash and Louvain fast enough?** — benchmark 1.5M entities through `entity_band` construction and 2M edges through Louvain on a 4-core laptop. Above ~10 minutes for either, drop `num_perm` to 64 and make `omniweave-driver-leiden` the documented default install, but never add a second in-tree implementation.
- **What is the LSH block-miss rate at 0.7 / 128 perms on document entity labels?** — graphify tuned those constants on code identifiers. Sample 1,000 known-identical cross-document pairs from an annotated corpus and measure. Above ~3% and either `shingle_k` or the band count is wrong for prose names.
- **Do current models emit `e412`, `c412` and `k412` as reliably as `d7#412`?** — graphrag's `short_id` premise is untested for a non-block sigil. Measure emission accuracy over 1,000 generations; if `c412` is confused with a figure or section number, change the sigil before anything ships and before the D2 amendment is written.
- **Does the resolution funnel's `[75, 92)` LLM band earn its cost on documents?** — measure band-hit precision on a labelled 1,000-pair document sample. If deterministic precision inside the band is already above ~0.9, the band closes and `derive.merge.llm` is deleted rather than shipped.
- **Does `graspologic-native`'s licence survive an in-tree read?** — it is not vendored in `_collections/`, so its SPDX is unverified here. If it is not permissive, `omniweave-driver-leiden` is probed-red and pruned; there is no substitute algorithm, by the same rule that forbids substituting a codec.
- **Is one Segment table really enough for both extraction and retrieval?** — measure extraction F1 at 1,200-token Segments against D5's preferred retrieval granularity on an annotated corpus. Under ~2 points of difference the single table stands; above it, D5 gets its own chunking and D7 keeps `segment` for extraction only.
