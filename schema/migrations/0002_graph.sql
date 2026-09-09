-- 0002_graph.sql -- L3: segments, anchors, entities, edges, claims. SCHEMA = 1.
--
-- WHAT THIS FILE IS. The second of the reserved migration numbers. The per-file object assignment
-- is 07-store-and-retrieval.md section 3's table; the DDL itself is charter.md's "The owgraph DDL"
-- (charter.md:4830-5250), transcribed statement for statement, with 06-structure-extraction.md
-- sections 1.3-1.6 normative for the census, the identities and the vocabularies. Applied
-- forward-only, in numeric order, one transaction per file, by the migration runner
-- (11-repo-layout.md section 5.1: migrations ship in the wheel as package data and are read
-- through importlib.resources, never as a tool).
--
-- WHY THIS FILE IS 0002 AND THE INDEX LAYER IS 0003. 11-repo-layout.md:1188 states it and states
-- the failure: "0002_graph.sql precedes 0003_index.sql because L4 indexes and foreign keys
-- reference L3 tables, and the reverse ordering was a real defect -- an index on a table a later
-- file creates aborts the migration and NEITHER FILE APPLIES." L4 reads three objects declared
-- here -- `segment` (three indexes), `anchor` (the two reference views) and `relation_vocab` (a
-- foreign key from `block_link`) -- so nothing in this file may name an object 0003 creates.
-- 07 section 3's three-way rule is why the direction is asymmetric: a VIEW resolves its names at
-- first use and survives a forward reference lazily, a FOREIGN KEY resolves at the first DML on
-- the child row and also survives, but a CREATE INDEX resolves its table at CREATE time and
-- ABORTS. G27(b) applies every migration in numeric order to an empty file on the declared
-- MIN_SQLITE = (3, 42, 0) and is the only test that catches it.
--
-- THE ONE FORWARD FOREIGN KEY IN THIS FILE is `derive_run.decision_id -> route_decision`
-- (charter.md:4950). `route_decision` ships in 0004_runtime.sql (05-ingest-and-routing.md
-- section 7.1), so the parent does not exist when this file applies -- which is legal, because
-- SQLite performs no DDL-time parent lookup and a migration writes no rows. NOTE FOR THE PLAN'S
-- OWNER: 07-store-and-retrieval.md:249 says "The one forward foreign key in the shipped order is
-- `block.decision_id -> route_decision`". Counted from definition sites, there are TWO: that one
-- (charter.md:1062, in 0001_init.sql) and this one. The rule is unaffected; the count is wrong.
--
-- WHAT THIS FILE DOES NOT DO. It creates every L3 table EMPTY and P8 fills them
-- (16-roadmap.md section 3.3, and P2's non-goals at 16-roadmap.md:466: "No `segment` rows and no
-- L3 rows: the tables exist and are empty"). Three consequences, each deliberate:
--   1. `etype_vocab`'s fifteen builtin rows and `relation_vocab`'s thirteen
--      (06-structure-extraction.md section 1.6) are NOT seeded here.
--   2. No `INSERT INTO enum_val`. 03-document-model.md section 15.3 assigns the write to the
--      migration STEP, not to the file: "Each runs in one transaction, updates its `meta` rows,
--      and regenerates `enum_val` from the Python enums with CI asserting parity in both
--      directions and the append-only assertion of section 2.1." A literal INSERT cannot make
--      that assertion and would be a second writer of the table. The six closed domains this
--      layer brings into use -- lane, akind, alias_kind, claim_status, taint, precision
--      (charter.md:4834) -- are `omniweave_core.model.enums.enum_val_rows()`'s rows for those
--      domains and nothing else.
--   3. No `CREATE TRIGGER` mirroring `MAX_TRUST_BY_METHOD` onto entity/mention/edge/claim.
--      06-structure-extraction.md:83 and 03-document-model.md:1628 require those triggers to be
--      "generated ... at migration time with CI parity in both directions: two enforcers, one
--      truth", and 16-roadmap.md:415 lists them as a W2.2 deliverable separate from
--      `schema/migrations/0001-0004`. Writing them as literal SQL here would create the second
--      truth the parity requirement exists to forbid, because the ceiling lives in Python.
--      Contrast `route_decision_monotone` (charter.md:2851), which IS printed as literal SQL in
--      its own file: it mirrors no Python mapping, only a predicate over its own table.
--
-- ENCODING. ASCII only, LF, UTF-8, one trailing newline. `--` never an em dash, "section" never
-- U+00A7. The pragmas are per CONNECTION and per FILE-CREATE, never per migration
-- (07-store-and-retrieval.md section 2.1's CONN_PRAGMAS / INIT_PRAGMAS / CREATE_PRAGMAS), and the
-- transaction is the runner's, so this file opens no BEGIN and closes no COMMIT.
--
-- L3 MAY NOT put containment or intra-document references in its own tables: containment is
-- `block.parent_id` and the seven `rel` kinds are L2's, both in 0001_init.sql.

-- =========================================================================================
-- vocabularies: DATA, not code
--
-- Three vocabularies are OPEN and therefore tables rather than `enum_val` rows
-- (06-structure-extraction.md section 1.6, charter section 5 X2): an enum generated from a Python
-- enum at migration time cannot express "a driver may declare a new relation". The third is
-- `claim.claim_type`, an open COLUMN with no table at all.
-- =========================================================================================

CREATE TABLE etype_vocab (            -- entity classes, corpus-tuned. NEVER a four-item config
  etype        TEXT PRIMARY KEY,      -- list: graphrag's DEFAULT_ENTITY_TYPES is four news-corpus
  scope        TEXT NOT NULL CHECK(scope IN ('document','corpus')),   -- values (defaults.py:41),
  resolution   TEXT NOT NULL CHECK(resolution IN ('exact_only','fuzzy','none')),  -- which is most
  source       TEXT NOT NULL CHECK(source IN ('builtin','proposed','user')),      -- of why it does
  compatible   TEXT NOT NULL DEFAULT '[]',   -- a JSON array of etypes that MAY merge across
  n_entities   INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
-- The fifteen builtin rows are 06-structure-extraction.md section 1.6's and are NOT seeded here:
--   anchor, defined_term, section, figure, table (document); citation, person, org, place, date,
--   money, quantity, product, group, unknown (corpus).
-- `proposed` comes from `ow graph types --propose` and is not first-class until an operator
-- promotes it to `user`.

CREATE TABLE relation_vocab (         -- THE DIRECTION RULE AS DATA; the prompt is GENERATED from
  relation   TEXT PRIMARY KEY,        -- it, so prompt and schema cannot drift.
  symmetric  INTEGER NOT NULL DEFAULT 0,      -- symmetric => stored with src < dst
  actor_rule TEXT NOT NULL,           -- "source is the CITING entity; target is the CITED entity."
  source     TEXT NOT NULL CHECK(source IN ('builtin','driver','user'))
) WITHOUT ROWID;
-- The thirteen builtin rows (refers_to cites defines part_of member_of party_to supersedes amends
-- located_in attributed_to depends_on co_occurs_with related_to) are not seeded here. A driver
-- card MAY declare relations = [{relation, symmetric, actor_rule}], admitted at activation with
-- source='driver'; a relation with no actor_rule is CARD_INVALID.
-- `block_link.relation` in 0003_index.sql references THIS TABLE and not `enum_val`. That is the
-- backward reference 11-repo-layout.md:1188 names, and it is why this file cannot be 0003.

CREATE TABLE derive_pass (            -- THE PASS REGISTRY. DATA. There is no pipeline array.
  pass_id     TEXT PRIMARY KEY,       -- == a DriverId, or 'op.<name>' for a core-side pass
  port        TEXT NOT NULL CHECK(port IN ('derive/1','op')),
  --   'op' is NOT a Port -- there are exactly five and `host` was never one of them. A core-side
  --   pass is an `op.<name>` OPERATOR, a vocabulary `work.operator` already admits.
  cost_class  TEXT NOT NULL CHECK(cost_class IN ('free','local_compute','billed_api')),
  cost_rank   INTEGER NOT NULL,       -- 0|1|2, derived from cost_class. THE PRIMARY ORDERING.
  phase       INTEGER NOT NULL DEFAULT 50,   -- THE SECONDARY ORDERING, WITHIN ONE cost_rank ONLY.
  --   `(cost_rank, phase)` IS THE ORDERING. `cost_rank` alone could not express `op.lexicon`
  --   before `op.resolve`, or the precise `derive.entity.table` before the fuzzy
  --   `derive.entity.gazetteer` -- both pairs are free, and the shipped ladder ordered them
  --   anyway with a `phase` column the schema could not store. `phase` is CARD-DECLARED
  --   ([capability.derive] phase, default 50) and orders only within a rank, so a third party's
  --   FREE pass still preempts every PAID pass whatever its phase. That property is the whole of
  --   "deterministic before LLM" and it is untouched.
  lanes       TEXT NOT NULL,          -- a JSON array over the `lane` domain: the six derive lanes
                                      --   anchor|xref|entity|claim|community|summary. TEXT, not
                                      --   an ord: an `enum_val.ord` addresses one value and this
                                      --   column holds a set.
  granularity TEXT NOT NULL CHECK(granularity IN ('document','part','corpus')),
  card_sha256 TEXT NOT NULL, schema_version INTEGER NOT NULL,
  enabled     INTEGER NOT NULL DEFAULT 1
) WITHOUT ROWID;

-- =========================================================================================
-- THE SEGMENT. Defined ONCE, here (charter section 5 X23). 0003_index.sql READS it and adds no
-- second chunking: three indexes and the `ow_segment_head` projection, all backward references.
-- =========================================================================================

CREATE TABLE segmenter (
  segmenter_id    INTEGER PRIMARY KEY,
  driver_id       TEXT NOT NULL,          -- e.g. 'derive.segment.spine'
  driver_schema_v INTEGER NOT NULL,
  params_digest   BLOB NOT NULL,          -- sha256_canonical of the flat Scalar params
  UNIQUE (driver_id, driver_schema_v, params_digest)
);

CREATE TABLE segment (
  segment_id  INTEGER PRIMARY KEY,
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, ord INTEGER NOT NULL,
  segmenter_id INTEGER NOT NULL REFERENCES segmenter(segmenter_id),
  layer       INTEGER NOT NULL,       -- Layer ord: body/furniture/note segments are SEPARATE
  atom        TEXT,                   -- 'table'|'list'|NULL: an unsplittable atom
  heading_path TEXT NOT NULL,         -- a JSON array of ancestor heading texts. A DIGEST INPUT.
                                      --   Derived from `block_sec` (0003), which is why that
                                      --   table is "computed once and read twice".
  n_blocks INTEGER NOT NULL, n_tokens INTEGER NOT NULL, n_chars INTEGER NOT NULL,
  tokenizer_id TEXT NOT NULL,
  first_page INTEGER NOT NULL, last_page INTEGER NOT NULL,
  trust       INTEGER NOT NULL,       -- MIN(block.trust) over members -- why AMBIGUOUS = 0 matters
  quote_min   INTEGER NOT NULL,       -- MIN(block.quote) over members: gates the byte-exactness
                                      --   claim, and it works BECAUSE `Quote` is an ordered
                                      --   IntEnum with synthetic = 0 and verbatim = 4, so the
                                      --   ord IS the member's integer (03 section 2.1).
  kind_mask   INTEGER NOT NULL,       -- a bitmask over Kind ords: pre-filter without a join
  restriction_bits INTEGER NOT NULL DEFAULT 0,   -- OR over members
  content_digest BLOB NOT NULL,       -- ow128(b'ow.segment.1', [segmenter identity, heading_path,
                                      --                         member content_digests in ord])
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  state       INTEGER NOT NULL DEFAULT 0,        -- 0 live, 1 retired
  synopsis_of INTEGER REFERENCES block(block_id), -- non-NULL => a table synopsis segment
  UNIQUE (doc_ord, gen, ord)
);

CREATE TABLE segment_block (
  block_id   INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  ord        INTEGER NOT NULL        -- position WITHIN the segment; the cover_bits bit index
) WITHOUT ROWID;                     -- EXACTLY ONE SEGMENT PER BLOCK. OVERLAP IS UNREPRESENTABLE.
CREATE INDEX segment_block_seg ON segment_block(segment_id, ord);
--   serves: the semantic lift, ord-ordered members (07-store-and-retrieval.md section 3.13).

-- =========================================================================================
-- the run: provenance interned ONCE per (segment, pass)
-- =========================================================================================

CREATE TABLE derive_run (
  run_id     INTEGER PRIMARY KEY,
  segment_id INTEGER REFERENCES segment(segment_id) ON DELETE CASCADE,  -- NULL => a corpus pass
  pass_id    TEXT NOT NULL REFERENCES derive_pass(pass_id),
  at_gen     INTEGER NOT NULL,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),   -- `producer` is 0001's
  method      INTEGER NOT NULL,      -- Method ord. ONE METHOD PER PASS; two methods is two
                                     --   passes. This is the column the generated
                                     --   MAX_TRUST_BY_METHOD triggers on mention/edge/claim
                                     --   reach through, since none of those carries a method of
                                     --   its own -- which is also why the clamp has to be a
                                     --   trigger and cannot be a CHECK (SQLite forbids a
                                     --   subquery in a CHECK).
  origin_operator TEXT NOT NULL,     -- OWNERSHIP, not trust. THE REPLACEMENT KEY.
  origin_driver   TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  cost_class  TEXT NOT NULL, decision_id TEXT REFERENCES route_decision(decision_id),
  --   ^ THE FORWARD FOREIGN KEY. `route_decision` is 0004_runtime.sql's. Legal: SQLite resolves a
  --     foreign-key parent at the first DML on the child row, not at CREATE TABLE, and this file
  --     writes no rows (07-store-and-retrieval.md section 3's three-way rule).
  input_digest BLOB NOT NULL,        -- segment.content_digest at derive time (an ow128 BLOB)
  cache_key    TEXT NOT NULL,        -- THE SAME TYPE AND THE SAME FUNCTION AS EVERY OTHER
  --   cache_key in the framework: a 64-char `sha256_canonical` hex string from the ONE
  --   `cache_key()` in `omniweave_core.cache`. `derive_run` sits in the same store as `work`, so a
  --   16-byte BLOB here under the same column name meant a reader could not tell whether a derive
  --   pass's cache identity was the key `with_cache` looks up. It is.
  status TEXT NOT NULL CHECK(status IN ('ok','partial','empty','failed','quarantined')),
  --   ^ `derive_run.status` is a SECOND closed vocabulary spelled `status` and is deliberately NOT
  --     an `enum_val` domain. `claim.status` below is the one that is, under the domain name
  --     `claim_status` (charter.md:942), precisely so these two cannot be confused.
  n_items INTEGER NOT NULL DEFAULT 0, n_quarantined INTEGER NOT NULL DEFAULT 0,
  spend  TEXT NOT NULL DEFAULT '{}'  -- canonical JSON of Spend. NO DOLLARS HERE.
);
CREATE UNIQUE INDEX derive_run_identity ON derive_run(pass_id, IFNULL(segment_id,-1), at_gen);
--   serves: INSERT OR IGNORE. An identity containing an IFNULL sentinel is ALWAYS a separate
--   CREATE UNIQUE INDEX and never an inline UNIQUE/PRIMARY KEY: SQLite prohibits an expression in
--   a table-level constraint, so the inline form does not merely fail review, it fails
--   CREATE TABLE (ST10, verified on 3.45.1). The installing migration MUST GROUP BY the IDENTICAL
--   expression, sentinels included.
CREATE INDEX derive_run_seg ON derive_run(segment_id, pass_id);

CREATE TABLE derive_cover (          -- THE deterministic-first mechanism
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE,
  lane       TEXT    NOT NULL,       -- the `lane` domain, stored as the LOWER-CASE MEMBER NAME.
                                     --   TEXT and not an ord because the join partners
                                     --   (`route_decision.lane`, `work.lane`) are TEXT; the
                                     --   `enum_val` row remains the name-to-ord registry.
  run_id     INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  cover_bits BLOB    NOT NULL,       -- 1 bit per block in segment_block.ord order. EXACTLY
                                     --   ceil(MAX_SEGMENT_BLOCKS/8) = 64 B, and the segmenter
                                     --   emits BEFORE the 513th block, so a segment can never
                                     --   overflow the bitmap. A 513-block segment is a REFUSAL,
                                     --   never a truncation -- "zero billed items on covered
                                     --   ground" rests on this bitmap being complete.
  n_covered  INTEGER NOT NULL,
  empty_reason TEXT,                 -- NOT NULL => covered with ZERO items. doctor reports the
                                     --   rate.
  PRIMARY KEY (segment_id, lane, run_id)
) WITHOUT ROWID;
CREATE INDEX derive_cover_lane ON derive_cover(lane, segment_id);

-- =========================================================================================
-- the graph proper
-- =========================================================================================

CREATE TABLE entity (
  entity_id  INTEGER PRIMARY KEY,    -- a DURABLE surrogate. Assigned once for a (scope,etype,key).
  cite       TEXT NOT NULL,          -- 'e412' -- prompts ONLY (INV-8)
  scope      INTEGER NOT NULL,       -- 0 = corpus-wide, else the owning doc_ord
  etype      TEXT NOT NULL REFERENCES etype_vocab(etype),
  key        TEXT NOT NULL,          -- normalize_key(canonical surface). A BLOCKING key, NOT an id.
  title      TEXT NOT NULL,          -- the display surface (the highest-trust mention's)
  raw_etype  TEXT,                   -- the producer's own label, KEPT
  canonical_id INTEGER NOT NULL REFERENCES entity(entity_id),   -- DERIVED from entity_merge
  resolution_trust  INTEGER NOT NULL DEFAULT 0,   -- Trust ord, REUSED. No new enum.
  resolution_method INTEGER NOT NULL,             -- Method ord, REUSED.
  trust      INTEGER NOT NULL,       -- MIN over live mentions. No default: absent => AMBIGUOUS.
  taint      INTEGER NOT NULL DEFAULT 0,          -- OR over live mentions. A BITMASK: the `taint`
                                     --   domain's ord IS the member's bit, so
                                     --   `taint & TAINT_UNTRUSTED_SOURCE` is the shipped
                                     --   predicate and the ords are NOT dense from 0.
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  frequency  INTEGER NOT NULL DEFAULT 0,   -- COUNT(DISTINCT mention.segment_id) -- CORPUS salience
  degree     INTEGER NOT NULL DEFAULT 0,   -- edge degree -- GRAPH salience. BOTH, always recomputed
  doc_count  INTEGER NOT NULL DEFAULT 0,   -- corpus SPREAD; 400 mentions in one contract is not
                                           --   400 documents
  mention_digest BLOB NOT NULL,      -- a merkle over live mention digests: the `summary` cache key
  description TEXT,                  -- DERIVED: the highest-trust mention's context sentence
  summary     TEXT,                  -- LLM, OPTIONAL, a separate column, keyed on mention_digest
  state      INTEGER NOT NULL DEFAULT 0,   -- 0 live, 1 overloaded, 2 retired
  x          TEXT NOT NULL DEFAULT '{}',
  UNIQUE (scope, etype, key)
);
CREATE UNIQUE INDEX entity_cite  ON entity(cite);
--   serves: cite resolution over the BASE table, so a merged-away 'e997' still resolves and the
--   resolver returns the canonical row with Diag(OW_GRAPH_ENTITY_MERGED) naming 'e412'. Silence
--   would make a shipped answer look wrong (06-structure-extraction.md section 1.5).
CREATE INDEX entity_canon  ON entity(canonical_id)              WHERE state = 0;
CREATE INDEX entity_rank   ON entity(etype, degree DESC, frequency DESC) WHERE state = 0;
CREATE INDEX entity_review ON entity(resolution_trust, taint) WHERE resolution_trust<2 OR taint<>0;
--   serves: the human review surface. One of the three consumers that keeps `trust` and `taint`
--   from rotting into decoration (06-structure-extraction.md section 1.2).
CREATE INDEX entity_restricted ON entity(restriction_bits)      WHERE restriction_bits <> 0;

-- The canonical-cluster projection. EXTENDS THE CHARTER: 06-structure-extraction.md section 1.5
-- declares it and is its only home. Every ranking, embedding and prompt-rendering consumer reads
-- this rather than `entity`, so a merged cluster is ranked once and not once per fragment.
-- Named `ow_entity_head` to parallel the locked `ow_block_head` (03-document-model.md section
-- 13.1) and deliberately NOT `ow_entity_canon`, which would differ from the `entity_canon` index
-- above by an `ow_` prefix. Placed in this file, immediately after its base table's indexes,
-- exactly as `ow_block_head` follows `block`'s in 0001_init.sql; 07 section 3's file table names
-- only tables, so the file is this cluster's choice and the reference is backward either way.
CREATE VIEW ow_entity_head AS
  SELECT * FROM entity WHERE state = 0 AND entity_id = canonical_id;

CREATE TABLE entity_alias (          -- the fix for graphrag's title keying
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  name_norm TEXT NOT NULL,           -- normalize_key(surface). ONE SPELLING for a normalised name
                                     --   across `anchor`, `ref_site` (0003) and here.
  surface TEXT NOT NULL,
  alias_kind TEXT NOT NULL CHECK(alias_kind IN ('canonical','variant','abbrev','expansion',
                                                'translit','llm','user')),
  --   `alias_kind`, NOT `akind`: `akind` is the anchor/reference vocabulary and these two sets are
  --   disjoint, so one `enum_val` domain name could not have held both -- PRIMARY KEY
  --   (domain, ord) has room for one vocabulary per domain. The seven members above are the
  --   `alias_kind` domain in declaration order (ord 0..6).
  run_id  INTEGER NOT NULL REFERENCES derive_run(run_id),
  trust   INTEGER NOT NULL, taint INTEGER NOT NULL DEFAULT 0,
  doc_count INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (entity_id, name_norm, alias_kind)
) WITHOUT ROWID;
CREATE INDEX entity_alias_name ON entity_alias(name_norm);   -- the lexicon automaton's source
-- RULE (injection layer 6): an alias with (taint & TAINT_UNTRUSTED_SOURCE) AND doc_count = 1 is
-- NEVER a blocking key for cross-document resolution. Enforced in resolve/block.py plus a test --
-- it is a predicate over two columns and not a constraint, because a legal row may still be an
-- illegal blocking key.

CREATE TABLE mention (               -- THE BRIDGE: the only table referencing both spaces
  mention_id INTEGER PRIMARY KEY,    --   (06-structure-extraction.md:232 GR15), enforced by a
  entity_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,   -- schema lint
  block_id   INTEGER NOT NULL REFERENCES block(block_id)   ON DELETE CASCADE,   -- classifying
  segment_id INTEGER NOT NULL REFERENCES segment(segment_id) ON DELETE CASCADE, -- every FK target
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,   -- a TextSpan, half-open [ts_a, ts_b) in
                                     --   CHARACTERS of block.text. NOT NULL: a mention HAS a span.
                                     --   `ts_*` and never `a`/`b`: the terminology lock reserves
                                     --   `os_*` for an OriginSpan, whose `os_b` is a LENGTH.
  surface TEXT NOT NULL,
  run_id  INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust   INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint   INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  digest  BLOB NOT NULL,             -- ow128(b'ow.mention.1', [entity.key, block_id, ts_a, ts_b])
  state   INTEGER NOT NULL DEFAULT 0,-- 0 live, 1 orphaned (the block retired, no successor)
  CHECK (ts_a <= ts_b),
  CHECK ((score IS NULL) = (score_kind IS NULL)),   -- an unnamed 0.7 is not a measurement
  UNIQUE (block_id, ts_a, ts_b, entity_id, run_id)  -- identity IN THE SCHEMA
);
CREATE INDEX mention_entity  ON mention(entity_id, block_id) WHERE state = 0;
CREATE INDEX mention_block   ON mention(block_id, ts_a);
--   serves: 07-store-and-retrieval.md section 7.4's graph impact
--   (SELECT COUNT(*) FROM mention WHERE block_id = ? AND state = 0) and span-ordered hydration
--   within one block. NOTE FOR THE PLAN'S OWNER: 07 section 3.13's register row prints this index
--   as "(block_id) partial state = 0", which is a different index. The charter's DDL
--   (charter.md:5047) is the shape implemented, because it is the DDL home and because `ts_a` in
--   the key is what makes hydration a covering range scan; the register row's predicate is served
--   by the left prefix.
CREATE INDEX mention_segment ON mention(segment_id);
CREATE INDEX mention_review  ON mention(trust, taint) WHERE trust < 2 OR taint <> 0;
-- THERE IS NO `quad` COLUMN AND THERE NEVER WILL BE. Geometry is L2's (INV-9).

CREATE TABLE edge (                  -- entity->entity. Weighted. Clustered. Traversed.
  edge_id    INTEGER PRIMARY KEY,    -- `block_link` (0003) is the block->block table.
  src_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  dst_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  relation   TEXT NOT NULL REFERENCES relation_vocab(relation),
  role       TEXT,                   -- a participation role: reifies an n-ary event on member_of
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  --   ^ WHERE THE RELATIONSHIP WAS OBSERVED. graphify requires source_file on EDGES, not just on
  --     nodes: that one field is what makes "where does this document assert that" answerable.
  ts_a INTEGER, ts_b INTEGER,
  bound_by   TEXT,                   -- the anchor name_norm that RESOLVED this edge; drives
                                     --   unbind. NULL => NEVER UNBOUND ("never delete what we
                                     --   cannot restore").
  weight     REAL NOT NULL DEFAULT 1.0,
  combined_degree INTEGER NOT NULL DEFAULT 0,   -- src.degree + dst.degree; the edge prior
  corroborations  INTEGER NOT NULL DEFAULT 1,   -- CORROBORATION IS NOT PROMOTION
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust  INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint  INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  x      TEXT NOT NULL DEFAULT '{}',
  CHECK (src_entity <> dst_entity),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX edge_identity ON edge(
  src_entity, dst_entity, relation, observed_block, IFNULL(ts_a,-1), run_id);   -- ST10
CREATE INDEX edge_src    ON edge(src_entity, relation, weight DESC);
CREATE INDEX edge_dst    ON edge(dst_entity, relation, weight DESC);
CREATE INDEX edge_obs    ON edge(observed_block);
CREATE INDEX edge_bound  ON edge(bound_by) WHERE bound_by IS NOT NULL;
CREATE INDEX edge_review ON edge(trust, taint) WHERE trust < 2 OR taint <> 0;

CREATE TABLE edge_evidence (         -- which mentions witnessed this edge; drives locate()
  edge_id    INTEGER NOT NULL REFERENCES edge(edge_id) ON DELETE CASCADE,
  mention_id INTEGER NOT NULL REFERENCES mention(mention_id) ON DELETE CASCADE,
  slot TEXT NOT NULL CHECK(slot IN ('src','dst','predicate')),
  PRIMARY KEY (edge_id, mention_id, slot)
) WITHOUT ROWID;

CREATE TABLE claim (                 -- graphrag's covariates. A DIFFERENT TABLE FROM `edge`
  claim_id   INTEGER PRIMARY KEY,    --   because it has different consumers: the clusterer reads
  cite       TEXT NOT NULL,          --   edge, never claim, and weight/combined_degree are
                                     --   meaningless here.
  subject_entity INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  object_entity  INTEGER          REFERENCES entity(entity_id) ON DELETE CASCADE,  -- BIPARTITE
  object_literal TEXT, object_datatype TEXT,   -- 'xsd:date'|'xsd:decimal'|'money:USD'|'string'
  claim_type TEXT NOT NULL,          -- an OPEN vocabulary, corpus-tuned: the third of
                                     --   06-structure-extraction.md section 1.6's three, and the
                                     --   one with no table at all. An unrecognised value is
                                     --   KEPT, not rejected -- hence no CHECK.
  predicate  TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('asserted','denied','suspected','superseded')),
  --   ^ THE `claim_status` DOMAIN, four members in declaration order (ord 0..3). The domain name
  --     carries the table because `derive_run.status` above is a second vocabulary spelled
  --     `status` and is not an `enum_val` domain at all.
  t_start TEXT, t_end TEXT,          -- ISO-8601, partial permitted ('2026', '2026-06')
  t_precision TEXT CHECK(t_precision IN ('year','month','day','datetime')),
  --   ^ THE `precision` DOMAIN, four members in declaration order (ord 0..3). This column and not
  --     `Locus.precision`, whose five values are computed by the query and never stored
  --     (06-structure-extraction.md:2106) while an `enum_val.ord` is by definition a stored value.
  --     charter.md:4835 puts the `precision` domain in this file, and `t_precision` is the only
  --     precision COLUMN in it.
  observed_block INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  --   ^ graphrag stores `source_text`, A COPY, which drifts on any re-parse. We store the
  --     reference and a tier, never the text (INV-1).
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,
  quote_tier INTEGER NOT NULL,       -- the source block's Quote ord, copied at write time. THE ONE
                                     --   DELIBERATE DENORMALISATION IN L3: a four-value ordinal,
                                     --   not text, structure or geometry, so INV-1 is untouched,
                                     --   and it makes `quote_tier >= 4` an index range scan
                                     --   instead of a join through observed_block per candidate.
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  trust  INTEGER NOT NULL, score REAL, score_kind TEXT,
  taint  INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  x      TEXT NOT NULL DEFAULT '{}',
  CHECK ((object_entity IS NULL) <> (object_literal IS NULL)),   -- bipartite
  CHECK ((object_literal IS NULL) = (object_datatype IS NULL)),  -- a literal HAS a datatype
  CHECK ((t_start IS NOT NULL OR t_end IS NOT NULL) = (t_precision IS NOT NULL))
);
CREATE UNIQUE INDEX claim_identity ON claim(
  subject_entity, IFNULL(object_entity,-1), IFNULL(object_literal,''), claim_type,
  observed_block, ts_a, run_id);                                               -- ST10
CREATE UNIQUE INDEX claim_cite ON claim(cite);
CREATE INDEX claim_subject ON claim(subject_entity, claim_type);
CREATE INDEX claim_time    ON claim(t_start, t_end) WHERE t_precision IS NOT NULL;

-- =========================================================================================
-- resolution: append-only, order-independent, reversible
-- =========================================================================================

CREATE TABLE entity_merge (
  merge_id  INTEGER PRIMARY KEY,
  loser_id  INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  winner_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  polarity  INTEGER NOT NULL CHECK(polarity IN (-1, 1)),  -- -1 = MUST NOT merge (a user split),
                                     --   the only construct that makes a human split survive a
                                     --   later automatic merge attempt.
  stage TEXT NOT NULL CHECK(stage IN ('exact','lsh_jw','community_boost','abbrev','llm_band',
                                      'user')),
  method INTEGER NOT NULL, trust INTEGER NOT NULL,
  score REAL, score_kind TEXT,       -- 'jaro_winkler'|'lsh_jaccard'|'llm_logprob'
  guards TEXT NOT NULL DEFAULT '[]', -- the guards that PASSED: a rule change is auditable
  reason TEXT,                       -- REQUIRED when stage='user'. Not a CHECK: the requirement
                                     --   is on the writer, and charter.md:5133 prints none.
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id),
  decided_at_gen INTEGER NOT NULL, retired_at_gen INTEGER,
  CHECK (loser_id <> winner_id),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX entity_merge_pair ON entity_merge(loser_id, winner_id, polarity)
  WHERE retired_at_gen IS NULL;
-- entity.canonical_id = the path-compressed union-find closure over polarity=+1 rows, honouring
-- polarity=-1 as a blocking pair, with stage='user' applied LAST and NEVER overwritten by a pass.

CREATE TABLE entity_band (           -- PERSISTED MinHash bands. NEVER an in-memory index:
  band     INTEGER NOT NULL,         -- 128-perm signatures for 1.5M entities is ~1.3 GB of RAM.
  bucket   BLOB    NOT NULL,
  etype    TEXT    NOT NULL,
  entity_id INTEGER NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (band, bucket, entity_id)
) WITHOUT ROWID;
-- Rebuilt whenever meta['graph.resolve_signature'] changes (the normalize_key version, perms,
-- threshold, shingle size). A FORGOTTEN BUMP IS SILENT RECALL LOSS, so the signature is CHECKED at
-- the top of every resolve pass and a mismatch REBUILDS rather than warns.

-- =========================================================================================
-- anchors and the durable residue
-- =========================================================================================

CREATE TABLE anchor (                -- WHAT A DOCUMENT DEFINES. The anchor_delta substrate.
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  name_norm TEXT NOT NULL,
  akind TEXT NOT NULL,               -- the `akind` domain: AnchorKind's fourteen members, stored
                                     --   as the LOWER-CASE MEMBER NAME. `ref_site.akind` (0003)
                                     --   IS THE SAME VOCABULARY AND THE SAME COLUMN NAME, because
                                     --   `ref_unresolved` and `ow_ref_resolved` join them by
                                     --   EQUALITY: `citation_key` here against `citekey` there
                                     --   made every citation-key reference permanently
                                     --   unresolved, permanently visible in `ref_unresolved` and
                                     --   permanently absent from `ow_ref_resolved`, with nothing
                                     --   anywhere reporting it. `citekey` won.
  surface   TEXT NOT NULL,           -- as written. DISPLAYED, never matched.
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  entity_id INTEGER REFERENCES entity(entity_id) ON DELETE SET NULL,
  scope TEXT NOT NULL CHECK(scope IN ('document','corpus')),
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  PRIMARY KEY (doc_ord, gen, name_norm, akind)
) WITHOUT ROWID;
CREATE INDEX anchor_corpus ON anchor(name_norm, akind) WHERE scope = 'corpus';
CREATE INDEX anchor_name   ON anchor(name_norm, akind, scope, doc_ord);
--   serves: the `ref_unresolved` anti-join, WITH `scope` and `doc_ord` in the key, because both
--   views filter on them -- a document-scoped anchor must not resolve another document's
--   reference. The occurrence side (`ref_site`) and both views are 0003_index.sql's: a view cannot
--   go stale, so there is no status column to get wrong.

CREATE TABLE quarantine (            -- graphrag DELETES these (filter_orphan_relationships).
  q_id INTEGER PRIMARY KEY,          -- A HALLUCINATED NAME IS VERY OFTEN A REAL ENTITY THE
  code TEXT NOT NULL,                -- EXTRACTOR FAILED TO EMIT A ROW FOR. KEEP IT.
     -- OW_GRAPH_UNGROUNDED | OW_GRAPH_DANGLING_CITE | OW_GRAPH_DANGLING_TMP
     -- | OW_GRAPH_OUT_OF_SCOPE_BLOCK | OW_GRAPH_COVERED_GROUND | OW_GRAPH_ITEM_BUDGET
     -- | OW_GRAPH_TRUST_CLAMPED | OW_GRAPH_LABEL_TOO_LONG | OW_GRAPH_INJECTION_SUSPECT
     -- | OW_GRAPH_ETYPE_OUT_OF_VOCAB | OW_GRAPH_UNPARSED_ITEM | OW_GRAPH_GUARD_BLOCKED
     -- | OW_GRAPH_COHESION_SPLIT | OW_GRAPH_ENTITY_OVERLOADED
     -- No CHECK: `code` resolves against append-only `codes.toml`, which a schema constraint
     -- would freeze into this migration.
  run_id INTEGER NOT NULL REFERENCES derive_run(run_id) ON DELETE CASCADE,
  row_kind TEXT NOT NULL CHECK(row_kind IN ('entity','alias','mention','edge','claim','anchor',
                                            'xref','merge')),
  payload TEXT NOT NULL,             -- THE REJECTED DRAFT, canonical JSON, VERBATIM
  block_id INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  detail TEXT NOT NULL DEFAULT '{}', at_gen INTEGER NOT NULL
);
CREATE INDEX quarantine_code ON quarantine(code, run_id);

CREATE TABLE graph_history (         -- RETIREMENT, not deletion. One table for every kind.
  kind TEXT NOT NULL CHECK(kind IN ('entity','mention','edge','claim','community')),
  row_id INTEGER NOT NULL, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER, reason TEXT NOT NULL,   -- reparse|resolver_split|resolver_merge|
  payload TEXT NOT NULL,                         -- source_deleted|pass_replaced|compacted
  PRIMARY KEY (kind, row_id, retired_gen)
) WITHOUT ROWID;
-- `row_id` is polymorphic over `kind` and therefore carries NO foreign key: a retirement row must
-- outlive the row it retires, which is the whole point of the table.

-- =========================================================================================
-- communities and reports
-- =========================================================================================

CREATE TABLE community (
  community_id INTEGER PRIMARY KEY,  -- durable; carried across re-clusters by member_digest match
  cite   TEXT NOT NULL,              -- 'c412' -- prompts ONLY. FLAT, not level.ordinal: a level is
  level  INTEGER NOT NULL,           -- not stable across re-clusters. INTEGER, not graphrag's str
  parent INTEGER REFERENCES community(community_id),   -- that update/communities.py:52 astype()s.
  component_ord INTEGER NOT NULL,    -- A root's parent is NULL, NEVER -1.
  cluster_run INTEGER NOT NULL,
  size INTEGER NOT NULL, cohesion REAL,
  member_digest BLOB NOT NULL,       -- ow128(b'ow.community.1', sorted canonical member ids)
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
  coverage REAL,                     -- the fraction of member evidence that FIT the context window
  run_id INTEGER REFERENCES derive_run(run_id),
  trust INTEGER CHECK(trust IS NULL OR trust <= 1),   -- A REPORT IS NEVER `EXTRACTED`. The CHECK
                                     --   is expressible as a literal only because Trust's ord IS
                                     --   the member's integer (03 section 2.1); 1 is INFERRED.
  taint INTEGER NOT NULL DEFAULT 0, restriction_bits INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0, written_at_ns INTEGER
);
CREATE INDEX community_report_todo ON community_report(report_state) WHERE report_state <> 'fresh';
CREATE VIEW community_report_fresh AS
  SELECT r.* FROM community_report r JOIN community c USING (community_id)
  WHERE r.report_state = 'fresh' AND r.member_digest = c.member_digest;
-- RETRIEVAL READS THE VIEW. A stale report is INVISIBLE, never silently served as current.

CREATE TABLE graph_observation (     -- symmetric with driver_observation (0004_runtime.sql)
  run TEXT NOT NULL, pass_id TEXT NOT NULL, lane TEXT NOT NULL,
  segments_in INTEGER NOT NULL DEFAULT 0, segments_cached INTEGER NOT NULL DEFAULT 0,
  blocks_in INTEGER NOT NULL DEFAULT 0, items_out INTEGER NOT NULL DEFAULT 0,
  covered INTEGER NOT NULL DEFAULT 0, cover_empty INTEGER NOT NULL DEFAULT 0,
  quarantined INTEGER NOT NULL DEFAULT 0, grounded_frac REAL,
  calls INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
  wall_ms INTEGER NOT NULL DEFAULT 0,
  -- graphify's FIVE MISS SHAPES. A cache that silently serves a partial never self-heals.
  miss_corrupt INTEGER NOT NULL DEFAULT 0, miss_partial INTEGER NOT NULL DEFAULT 0,
  miss_empty INTEGER NOT NULL DEFAULT 0, miss_mismatch INTEGER NOT NULL DEFAULT 0,
  miss_vintage INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run, pass_id, lane)
) STRICT;
-- STRICT needs SQLite 3.37 and MIN_SQLITE is (3, 42, 0), so the floor covers it three features
-- deep (07-store-and-retrieval.md section 2.1). `pass_id` carries no FK to `derive_pass`
-- deliberately: an observation of a pass that has since been disabled and deleted from the
-- registry is exactly the row an operator needs.

-- =========================================================================================
-- enum_val: the six closed domains L3 brings into use
-- =========================================================================================
-- charter.md:4834, describing THIS FILE: "enum_val gains the CLOSED domains: 'lane', 'akind',
-- 'alias_kind', 'claim_status', 'taint', 'precision'. The OPEN vocabularies get their own
-- tables." That is settled law assigning these six domains to 0002, and it is why they are here
-- and not left to a later step.
--
-- WHY LITERAL SQL, against the reading recorded in this file's header. That reading was that
-- 03-document-model.md section 15.3 assigns the write to the migration STEP -- "Each runs in one
-- transaction, updates its `meta` rows, and regenerates `enum_val` from the Python enums" -- so a
-- literal INSERT would be a second writer. The reading is defensible about the MECHANISM and does
-- not settle the OUTCOME: section 15.3 fixes where the truth lives (the Python enums), while
-- charter.md:4834 fixes which file the six domains belong to, and the two are not in conflict.
-- What no reading permits is the state abstaining produced -- 0001_init.sql seeding L2's nine
-- domains literally, nothing seeding L3's six, and enum_val holding NINE of the fifteen closed
-- domains after all four migrations apply. Consistency with the sibling file settles the form.
--
-- The truth remains `omniweave_core.model.enums.enum_val_rows()`, which is the only site that
-- knows an ordinal. These rows are GENERATED from it, and
-- packages/omniweave-core/tests/unit/test_enum_val_parity.py asserts the two agree in both
-- directions -- so this is a second enforcer, never a second truth. When the migration runner
-- lands in P2 stage B and regenerates enum_val at migration time, it becomes the third enforcer
-- of the same one truth and these literals are what it is checked against.
--
-- THE ORDINAL IS THE STORED VALUE AND IS APPEND-ONLY (03 section 2.1). For `taint` -- an IntFlag
-- -- `ord` is the member's own flag bit and the sequence is therefore NOT dense: 0, 1, 2, 4, 8,
-- 16. A reader must not infer position from it, and renumbering it densely would silently
-- reinterpret every stored taint column. For the five StrEnums it is declaration order.
-- lane <- Lane: 11 members, ord dense from 0.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('lane', 0, 'text'), ('lane', 1, 'table'), ('lane', 2, 'math'), ('lane', 3, 'fields'),
  ('lane', 4, 'caption'), ('lane', 5, 'anchor'), ('lane', 6, 'xref'), ('lane', 7, 'entity'),
  ('lane', 8, 'claim'), ('lane', 9, 'community'), ('lane', 10, 'summary');
-- akind <- AnchorKind: 14 members, ord dense from 0.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('akind', 0, 'section'), ('akind', 1, 'clause'), ('akind', 2, 'figure'), ('akind', 3,
  'table'), ('akind', 4, 'equation'), ('akind', 5, 'citekey'), ('akind', 6, 'identifier'),
  ('akind', 7, 'defined_term'), ('akind', 8, 'footnote'), ('akind', 9, 'exhibit'), ('akind', 10,
  'slide'), ('akind', 11, 'sheet'), ('akind', 12, 'glossary'), ('akind', 13, 'bookmark');
-- alias_kind <- AliasKind: 7 members, ord dense from 0.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('alias_kind', 0, 'canonical'), ('alias_kind', 1, 'variant'), ('alias_kind', 2, 'abbrev'),
  ('alias_kind', 3, 'expansion'), ('alias_kind', 4, 'translit'), ('alias_kind', 5, 'llm'),
  ('alias_kind', 6, 'user');
-- claim_status <- ClaimStatus: 4 members, ord dense from 0.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('claim_status', 0, 'asserted'), ('claim_status', 1, 'denied'), ('claim_status', 2,
  'suspected'), ('claim_status', 3, 'superseded');
-- taint <- Taint: 6 members, ord IS the flag bit -- NOT dense.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('taint', 0, 'none'), ('taint', 1, 'untrusted_source'), ('taint', 2, 'sentinel'), ('taint', 4,
  'hidden_text'), ('taint', 8, 'offscreen'), ('taint', 16, 'single_witness_xdoc');
-- precision <- TimePrecision: 4 members, ord dense from 0.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('precision', 0, 'year'), ('precision', 1, 'month'), ('precision', 2, 'day'), ('precision', 3,
  'datetime');
