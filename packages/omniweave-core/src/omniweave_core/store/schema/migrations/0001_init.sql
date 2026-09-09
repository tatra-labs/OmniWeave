-- schema/migrations/0001_init.sql -- L2, the document model.
--
-- Specified by 03-document-model.md section 13.1 (the golden DDL: meta, enum_val, block and its
-- nine indexes, ow_block_head, block_history, rel, mark, part, block_fts and its three sync
-- triggers), plus the four sections 03:2464-2466 names as also shipping here -- section 2.8
-- (doc, page, producer, rel), section 10.1 (table_meta, cell, grid_slot), section 11 (asset,
-- block_asset, page_render) and section 9 (diag). The per-file object assignment is
-- 07-store-and-retrieval.md section 3's table at :237; the file is written in P2 W2.2
-- (16-roadmap.md section 3.3). charter.md:928-1224 carries the DDL for the ten objects 03 prints
-- in prose sections rather than in section 13.1, and every statement below is its transcription.
--
-- WHAT IS NOT HERE, AND WHY, because each absence is a decision a reader will want to check:
--
--   * NO `PRAGMA`. 03:2296-2303 and charter.md:924-933 print the pragma list at the head of the
--     `.owstore` DDL as documentation OF THE FILE, not as migration statements.
--     07-store-and-retrieval.md section 2.1 splits it three ways and gives each a different
--     lifetime: CONN_PRAGMAS is per connection and `store/sqlite.py` applies it at every open,
--     INIT_PRAGMAS is persistent per file, and CREATE_PRAGMAS (`page_size`, `auto_vacuum`) is
--     "CREATE time only" and must run BEFORE the first table exists. Re-issuing them here would
--     be a second home for one setting (charter section 8 rejection criterion 19), and two of
--     them could not be honoured from inside a migration anyway: `page_size` is a no-op once a
--     page has been written, and `foreign_keys` is a documented no-op inside a transaction --
--     which is what 03 section 15.3 says every migration runs in.
--
--   * NO `INSERT INTO meta`. 03:2306-2307's key list is container_version, model_version,
--     min_reader, digest_recipe, segment_recipe, corpus_id, writer_version and
--     graph.resolve_signature. `corpus_id` and `writer_version` are per-store and per-build and
--     cannot be literals in a byte-diff-gated file at all; `segment_recipe` and
--     `graph.resolve_signature` are L3's, hence 0002_graph.sql's; and the remaining four have no
--     code home to hold parity against -- `omniweave_core.contract` holds CONTRACT,
--     CONTRACTS_SUPPORTED, RELEASE, SCHEMA, SCHEMA_MINOR and SCHEMA_STRING and nothing else -- so
--     a literal here would be a version-bearing site outside 11-repo-layout.md section 4.2's
--     forty, with nothing to compare it against. Contrast `enum_val` below, which HAS a single
--     code home and an explicit two-way parity instruction (charter.md:939). ADR-9 already
--     measured that the neighbouring assertion ("both are present after 0001_init.sql") cannot
--     run, and ST23/ST24 (07:3262-3263) put the only version stamp anyone checks in
--     `index_state`, which 0003_index.sql creates.
--
--   * NO `INSERT INTO migration`. The `migration` table is 07 section 3.8's and ships in
--     0003_index.sql, two files after this one, so the loader writes that row, not this file.
--
--   * NO `MAX_TRUST_BY_METHOD` clamp trigger. 03:1626-1628 and 06-structure-extraction.md:82-83
--     put the generated BEFORE INSERT mirrors on entity / mention / edge / claim, all four of
--     which are 0002_graph.sql's.
--
-- STATEMENT ORDER. charter.md prints `page` before `producer`; this file hoists `producer` above
-- `page`, because 07-store-and-retrieval.md:264 states that "the one forward foreign key in the
-- shipped order is `block.decision_id -> route_decision`". `page.producer_id` would be a second
-- one, and while section 3's own table says a forward FK survives (SQLite resolves a parent at the
-- first DML on the child row, never at CREATE TABLE), a sentence that counts the exceptions at one
-- is the more normative reading of what the shipped order is.
--
-- Everything else follows charter.md's print order, so that the byte-diff gate over this file has
-- exactly one right answer (03:2453-2456).

-- ---------------------------------------------------------------------------
-- meta -- the store's own scalar facts. Written by the store, not by a migration; see the header.
-- 03:2305-2307, charter.md:935-937.
-- ---------------------------------------------------------------------------

CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- container_version . model_version . min_reader . digest_recipe . segment_recipe . corpus_id
-- . writer_version . graph.resolve_signature
-- `meta` NEVER gains a `schema` key: the sole disk home for SCHEMA is `index_state.schema`
-- (ADR-9 decision 3, ST23 at 07:3262). A migration fixture that writes one is asserted to FAIL
-- `ow store verify`.

-- ---------------------------------------------------------------------------
-- enum_val -- the CLOSED enum domains. 03:2309-2316, charter.md:939-952.
--
-- `ord` IS THE STORED VALUE and is APPEND-ONLY (03 section 2.1). For an ordered IntEnum it is the
-- member's own integer, so the SQL ordinal and the Python ordinal are one number and MIN() / >=
-- mean what they say; for a StrEnum it is declaration order and carries no ordering meaning.
--
-- NINE domains are seeded here, not fifteen. charter.md:4834 -- settled law -- says
-- 0002_graph.sql is where "enum_val gains the CLOSED domains: 'lane', 'akind', 'alias_kind',
-- 'claim_status', 'taint', 'precision'", and none of those six names a column on any table in
-- this file. The nine below are exactly the domains L2's own columns read: block.kind,
-- block.layer, block.trust / rel.trust, block.method / page.method, block.quote, page.page_kind,
-- table_meta.kind, rel.kind, block.os_kind.
--
-- `format` is NOT a domain, here or in 0002. 03:2311-2312, charter.md:7948, charter.md:8746
-- erratum D26 and adr/0012:197 all exclude it; a format token is free text over a COMPUTED
-- domain, and a domain a third-party card can extend cannot live in a table whose `ord` is an
-- append-only stored value -- enabling a driver would mint an ord, and two installs would then
-- disagree about enum_val. 05-ingest-and-routing.md:633 and :2074 say otherwise and are the two
-- defective sentences (_notes/build-defects.md D10 rules for 03).
--
-- The rows below are RENDERED from `omniweave_core.model.enums.enum_val_rows()`, the one site that
-- applies section 2.1's ordinal rule; test_migration_0001.py compares the two in both directions
-- (charter.md:939, "CI asserts parity in both directions").
-- ---------------------------------------------------------------------------

CREATE TABLE enum_val (domain TEXT NOT NULL, ord INTEGER NOT NULL, name TEXT NOT NULL,
                       PRIMARY KEY (domain, ord)) WITHOUT ROWID;

INSERT INTO enum_val (domain, ord, name) VALUES
  ('kind', 0, 'document'), ('kind', 1, 'section'), ('kind', 2, 'title'), ('kind', 3, 'heading'),
  ('kind', 4, 'paragraph'), ('kind', 5, 'list'), ('kind', 6, 'list_item'),
  ('kind', 7, 'blockquote'), ('kind', 8, 'code'), ('kind', 9, 'table'),
  ('kind', 10, 'table_cell'), ('kind', 11, 'figure'), ('kind', 12, 'picture'),
  ('kind', 13, 'caption'), ('kind', 14, 'formula'), ('kind', 15, 'rule'),
  ('kind', 16, 'page_header'), ('kind', 17, 'page_footer'), ('kind', 18, 'footnote'),
  ('kind', 19, 'endnote'), ('kind', 20, 'speaker_note'), ('kind', 21, 'comment'),
  ('kind', 22, 'form'), ('kind', 23, 'form_field'), ('kind', 24, 'checkbox'),
  ('kind', 25, 'key_value'), ('kind', 26, 'toc'), ('kind', 27, 'toc_entry'),
  ('kind', 28, 'reference'), ('kind', 29, 'bibliography'), ('kind', 30, 'handwriting'),
  ('kind', 31, 'chemical'), ('kind', 32, 'diagram'), ('kind', 33, 'container'),
  ('kind', 34, 'unknown');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('layer', 0, 'body'), ('layer', 1, 'furniture'), ('layer', 2, 'note'),
  ('layer', 3, 'annotation'), ('layer', 4, 'hidden');
-- trust and quote are ordered IntEnums: the ord IS the member's integer, and MIN() over a set is
-- the set's WEAKEST member. That reading is what makes `segment.quote_min` a gate (03:128-134).
INSERT INTO enum_val (domain, ord, name) VALUES
  ('trust', 0, 'ambiguous'), ('trust', 1, 'inferred'), ('trust', 2, 'extracted');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('method', 0, 'native'), ('method', 1, 'text_layer'), ('method', 2, 'native_xml'),
  ('method', 3, 'ocr_page'), ('method', 4, 'ocr_block'), ('method', 5, 'vlm_page'),
  ('method', 6, 'llm'), ('method', 7, 'heuristic'), ('method', 8, 'roundtrip'),
  ('method', 9, 'user');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('quote', 0, 'synthetic'), ('quote', 1, 'reconstructed'), ('quote', 2, 'reflowed'),
  ('quote', 3, 'normalized'), ('quote', 4, 'verbatim');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('page_kind', 0, 'page'), ('page_kind', 1, 'slide'), ('page_kind', 2, 'sheet'),
  ('page_kind', 3, 'frame'), ('page_kind', 4, 'stream');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('table_kind', 0, 'data'), ('table_kind', 1, 'layout');
INSERT INTO enum_val (domain, ord, name) VALUES
  ('rel_kind', 0, 'caption_of'), ('rel_kind', 1, 'note_ref'), ('rel_kind', 2, 'continues'),
  ('rel_kind', 3, 'anchor_ref'), ('rel_kind', 4, 'heading_of'), ('rel_kind', 5, 'derived_from'),
  ('rel_kind', 6, 'supersedes');
-- origin_span_kind's ordinals are load-bearing IN SQL: block's last two CHECKs interpolate
-- `pixels` = 3 and `bytes` = 0 as literals (03:1447-1451). Renumbering here silently retypes
-- those two constraints as well as every stored row.
INSERT INTO enum_val (domain, ord, name) VALUES
  ('origin_span_kind', 0, 'bytes'), ('origin_span_kind', 1, 'nodepath'),
  ('origin_span_kind', 2, 'glyphs'), ('origin_span_kind', 3, 'pixels'),
  ('origin_span_kind', 4, 'none');

-- ---------------------------------------------------------------------------
-- doc -- one row per source document. charter.md:954-977; the value type is 03 section 2.8's
-- `DocRecord`. Historical generations survive as block/page rows keyed (doc_ord, gen), and
-- `doc.gen` is the head.
-- ---------------------------------------------------------------------------

CREATE TABLE doc (
  doc_ord         INTEGER PRIMARY KEY,      -- corpus-local; the number inside a `cite`
  doc_key         BLOB    NOT NULL UNIQUE,  -- sha256(NORMALIZED source bytes)[:16]
  source_sha256   BLOB    NOT NULL,         -- sha256 of the RAW bytes, as delivered
  normalizer      TEXT,                     -- NULL => raw bytes were hashed (OW_NORMALIZER_FAILED)
  uri             TEXT    NOT NULL,
  media_type      TEXT    NOT NULL,
  format          TEXT    NOT NULL,
  format_evidence TEXT    NOT NULL,         -- JSON: magic bytes, content probe, OPC root element
  source_bytes    INTEGER NOT NULL,
  gen             INTEGER NOT NULL DEFAULT 1,   -- THE HEAD GENERATION. One doc row per doc_key.
  next_cite_n     INTEGER NOT NULL DEFAULT 1,   -- THE CITE COUNTER: monotonic per doc_key, never
                                                --   reset, never reused. See `block.cite`.
  status          TEXT    NOT NULL CHECK(status IN ('ok','partial','failed','skipped')),
  page_count      INTEGER,
  model_version   TEXT    NOT NULL,         -- "1.1"
  declared        TEXT    NOT NULL,         -- Capabilities the driver's card claims   (JSON)
  achieved        TEXT    NOT NULL,         -- Capabilities actually delivered HERE    (JSON)
  confidence      TEXT    NOT NULL DEFAULT '{}',
  timings_ms      TEXT    NOT NULL DEFAULT '{}',
  x               TEXT    NOT NULL DEFAULT '{}'
);
-- D2's UNIQUE(doc_key, gen) is STRUCK: under it doc_ord moved on every re-parse and `cite` stopped
-- resolving, contradicting D2's own "yesterday's citation still resolves" (section 5 X12).
-- `doc.format` is NOT NULL, which is what makes 07 section 3.8's NO_JOB_DOCS predicate
-- (`doc.format <> 'owjob'`) total and index-free.

-- ---------------------------------------------------------------------------
-- producer -- the reproduction tuple as a row, not a string. ONE TYPE, TWO LAYERS: `Producer` IS
-- L5's OperatorIdentity. charter.md:998-1016, 03 section 2.8.
-- ---------------------------------------------------------------------------

CREATE TABLE producer (
  producer_id INTEGER PRIMARY KEY,
  operator TEXT NOT NULL, op_version INTEGER NOT NULL, code_fingerprint TEXT NOT NULL,
  --                      ^^^^^^^ AN INTEGER AT EVERY SITE: here, on `Producer`, and on
  --                      `work`/`work_done`. There is no str() round-trip anywhere, so "07" and 7
  --                      can never disagree between this key and `work_identity`.
  model_id TEXT, model_rev TEXT,          -- model_rev = an exact commit sha; "main" is a lint error
  runtime TEXT, runtime_version TEXT, prompt_fp TEXT, options_digest BLOB NOT NULL
);
-- SQL NULLs are each distinct, so a nullable natural key needs IFNULL sentinels or INSERT OR
-- IGNORE degenerates to a plain INSERT (codegraph #1034: byte-identical duplicates that inflated
-- counts and flowed into callers). SQLite PROHIBITS an expression inside a table-level UNIQUE or
-- PRIMARY KEY, verified on 3.45.1, so an identity containing an IFNULL sentinel is ALWAYS a
-- separate UNIQUE INDEX -- never an inline constraint (ST10, charter.md:1008-1013).
CREATE UNIQUE INDEX producer_identity ON producer(
  operator, op_version, code_fingerprint, IFNULL(model_id,''), IFNULL(model_rev,''),
  IFNULL(runtime,''), IFNULL(runtime_version,''), IFNULL(prompt_fp,''), options_digest);

-- ---------------------------------------------------------------------------
-- page -- one row per ORIGINAL source page, per generation. charter.md:980-996, 03 section 2.8's
-- `PageRecord`. `page.method` is the branch that ran on THAT page, which is what makes per-page
-- escalation (INV-13) auditable: a 400-page PDF with three OCR'd pages has three rows at
-- method='ocr_page' and 397 at method='text_layer'.
-- ---------------------------------------------------------------------------

CREATE TABLE page (
  doc_ord     INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen         INTEGER NOT NULL,
  page        INTEGER NOT NULL,          -- ORIGINAL source index, 0-based. NEVER a batch index.
  page_kind   INTEGER NOT NULL,          -- page|slide|sheet|frame|stream
  label       TEXT,                      -- printed label: "iv", "A-3"
  w_mpt       INTEGER, h_mpt INTEGER,    -- 1/1000 pt; NULL when page_kind='stream'
  rotation    INTEGER NOT NULL DEFAULT 0,
  quad_origin TEXT CHECK(quad_origin IN ('topleft','bottomleft')),  -- what the DRIVER handed us
  method      INTEGER NOT NULL,          -- the branch that ran on THIS page
  status      TEXT    NOT NULL DEFAULT 'ok',
  ocr_error_score REAL,                  -- the SCORE, not the label (surya)
  parse_score REAL, layout_score REAL, table_score REAL, ocr_score REAL,
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),   -- page segmentation owner
  stats       TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (doc_ord, gen, page)
) WITHOUT ROWID;
-- page.table_score is computed from THIS page's table_meta.recon_score values, or it is NULL and
-- excluded from the mean: docling declares the field per page and never assigns it, so its
-- published grade is a three-component mean wearing four (03:1789-1794).

-- ---------------------------------------------------------------------------
-- block -- the single node type. 03:2318-2364 is the golden statement and this is its
-- transcription; charter.md:1018-1078 prints the same forty columns with `title` where 03 has
-- `label`. ADR-1 decision 7 (adr/0001:103) renamed the column to `label` so that `Kind.TITLE`
-- keeps the word, and 07 section 3.3 (:391-397) makes the name load-bearing: `head_fts` is an
-- external-content FTS5 table over this column, so a stale `title` would raise
-- `no such column: title` when 0003_index.sql applies and take G27(b)'s whole run with it.
-- ---------------------------------------------------------------------------

CREATE TABLE block (
  block_id   INTEGER PRIMARY KEY,            -- DURABLE surrogate; the only FK target FOR A BLOCK
  doc_ord    INTEGER NOT NULL,
  gen        INTEGER NOT NULL,
  page       INTEGER NOT NULL,
  addr       TEXT    NOT NULL,               -- 'doc' | 'p14/3' | 'p14/3/r2c5'  -- TYPE-FREE
  cite       TEXT    NOT NULL,               -- 'd7#412'  -- prompts ONLY (INV-8)
  parent_id  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  ord        INTEGER NOT NULL,               -- position among siblings == READING ORDER
  kind       INTEGER NOT NULL,               -- closed vocab, FK into enum_val
  raw_kind   TEXT,                           -- the producer's own label, KEPT
  layer      INTEGER NOT NULL,               -- inherited from the parent unless a page root
  label      TEXT,                           -- a human label for a CONTAINER; NOT Kind.TITLE
  text       TEXT,                           -- PLAIN text, fully resolved, NFC. NULL on containers.
  content_digest BLOB NOT NULL,              -- ow128, merkle. GEOMETRY IS NOT AN INPUT.
  layout_digest  BLOB,                       -- NULL when the block has no geometry
  revision   INTEGER NOT NULL DEFAULT 0,
  quad       BLOB,                           -- 8 x i32 LE, or NULL
  os_kind    INTEGER NOT NULL,               -- bytes|nodepath|glyphs|pixels|none
  os_part    TEXT, os_a INTEGER, os_b INTEGER, os_path TEXT,
  os_extractor TEXT, os_codec TEXT,          -- os_b is a LENGTH (section 7.2)
  ts_a       INTEGER, ts_b INTEGER,          -- a half-open RANGE
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method     INTEGER NOT NULL,
  trust      INTEGER NOT NULL,               -- 0=ambiguous 1=inferred 2=extracted
  score      REAL, score_kind TEXT,
  quote      INTEGER NOT NULL,               -- 0=synthetic ... 4=verbatim. ORDERED.
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  decision_id TEXT REFERENCES route_decision(decision_id),
  payload    TEXT,                           -- JSON, kind-discriminated, schema-validated
  state      INTEGER NOT NULL DEFAULT 0,     -- 0=live 1=tombstone. There is no DELETE.
  x          TEXT    NOT NULL DEFAULT '{}',
  FOREIGN KEY (doc_ord, gen, page) REFERENCES page(doc_ord, gen, page) ON DELETE CASCADE,
  CHECK (parent_id IS NULL OR parent_id <> block_id),
  CHECK ((os_a IS NULL) = (os_b IS NULL)),
  CHECK ((ts_a IS NULL) = (ts_b IS NULL)),
  CHECK ((score IS NULL) = (score_kind IS NULL)),
  CHECK (os_b IS NULL OR os_b >= 0),                      -- a LENGTH
  CHECK (ts_a IS NULL OR ts_a <= ts_b),                   -- a RANGE
  CHECK (length(addr) <= 512),
  CHECK (raw_kind IS NULL OR length(raw_kind) <= 128),
  CHECK ((os_path IS NOT NULL) <= (os_part IS NOT NULL)),
  CHECK ((os_extractor IS NOT NULL) <= (os_part IS NOT NULL)),
  CHECK (os_kind <> 3 OR quad IS NOT NULL),               -- 3 == OsKind.PIXELS, interpolated
  CHECK (os_kind <> 0 OR os_codec IS NOT NULL),           -- 0 == OsKind.BYTES; the branch decodes
  CHECK ((block_id >> 48) = 0)                            -- shard ordinal, interpolated
);
-- THREE LITERALS IN THIS STATEMENT ARE INTERPOLATED, and each is interpolated because SQLite
-- refuses the general form. `3` and `0` are OsKind.PIXELS's and OsKind.BYTES's ordinals: 03:1438
-- and :1443 write the two constraints with a `(SELECT ord FROM enum_val ...)` subquery and :1447
-- then says a subquery inside a CHECK is prohibited, so "the generator emits
-- CHECK (os_kind <> 3 OR quad IS NOT NULL)" and CI asserts each literal against the enum in both
-- directions -- which test_migration_0001.py does, against `OsKind`. `48` carries the shard
-- ordinal, `0` for every single-store corpus (ST20, charter.md:1070-1076): a bind parameter is
-- prohibited in a CHECK body, so `:shard_ord` cannot appear, and the value is re-asserted at
-- every open against `index_state.shard_ord`.
--
-- The two `<=` clauses are IMPLICATIONS over 0/1, which SQLite evaluates arithmetically (03:1452).
--
-- D3's three ownership columns (origin_operator, origin_driver, driver_schema_v) and D4's
-- decision_id are in the INITIAL DDL, never an ALTER TABLE: verified on SQLite 3.45.1,
-- `ALTER TABLE t ADD COLUMN x TEXT NOT NULL` succeeds only against an EMPTY table (03:2465-2469).
--
-- `decision_id -> route_decision` is THE ONE FORWARD FOREIGN KEY in the shipped order
-- (07:264-273). `route_decision` is 0004_runtime.sql's, and this CREATE TABLE still succeeds under
-- `PRAGMA foreign_keys = ON` because SQLite resolves a parent at the first DML on the child row,
-- not at DDL time -- and a migration writes no rows. The exception is CHECKED, not assumed: G27(b)
-- applies 0001 -> 0005 in numeric order to an empty file, and `ow store repair` step 3 runs
-- `PRAGMA foreign_key_check` against the completed schema.
CREATE UNIQUE INDEX block_addr ON block(doc_ord, gen, addr);   -- addr is POSITIONAL: gen-keyed
CREATE UNIQUE INDEX block_cite ON block(doc_ord, cite);        -- cite is DURABLE: GEN-FREE
-- One cite can NEVER name two rows. `addr` legitimately repeats across generations (`p14/3` is a
-- position); `cite` legitimately does not, and a gen in this key is what would let `d7#412` mean a
-- different row at gen 41 and gen 42.
CREATE UNIQUE INDEX block_sib  ON block(doc_ord, gen, IFNULL(parent_id,-1), ord);
CREATE INDEX block_read   ON block(doc_ord, gen, page, ord) WHERE state = 0;  -- full render = scan
CREATE INDEX block_parent ON block(parent_id, ord)          WHERE state = 0;
CREATE INDEX block_kind   ON block(doc_ord, gen, kind, page, ord) WHERE state = 0;
CREATE INDEX block_cdig   ON block(doc_ord, content_digest);                  -- rebind
CREATE INDEX block_review ON block(doc_ord, gen, page) WHERE trust < 2 AND state = 0;
CREATE INDEX block_restricted ON block(restriction_bits) WHERE restriction_bits <> 0;

-- The head-generation projection every reader goes through. Staged rows (gen > doc.gen) are
-- durable and INVISIBLE (03 section 1.1); this view is the mechanism, not a convenience. [DER]
-- Printed at 03:2376-2380, inside section 13.1's golden DDL, which 03:2465 says ships here, and
-- named in section 13.1's own [DER] list at :2473. charter.md:3310 prints the same view in its
-- 0003_index.sql block with `USING (doc_ord)`; the join is spelled out because 03 section 13.1 is
-- the site 07 section 3.2 names as its home, and the two forms are identical in SQLite because
-- `SELECT b.*` is unaffected by USING's column coalescing.
-- Retiring a generation sets its blocks state = 1 in the same transaction that advances doc.gen,
-- so the index layer never holds two generations -- which is what makes this a FILTER rather than
-- a deduplication (07 section 3.3).
CREATE VIEW ow_block_head AS
  SELECT b.* FROM block b JOIN doc d ON d.doc_ord = b.doc_ord
   WHERE b.gen = d.gen AND b.state = 0;

CREATE TABLE block_history (       -- retirement, instead of tombstones that outlive a generation
  block_id INTEGER PRIMARY KEY, doc_ord INTEGER NOT NULL, retired_gen INTEGER NOT NULL,
  superseded_by INTEGER,           -- NULL = retired with no defensible successor
  reason TEXT NOT NULL             -- reparse_resegmented|driver_upgrade|source_deleted|compacted
);

CREATE TABLE rel (                 -- the CLOSED intra-document DAG. Containment is NOT here.
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL,
  src_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  kind INTEGER NOT NULL,           -- caption_of|note_ref|continues|anchor_ref|heading_of|
                                   -- derived_from|supersedes  -- SEVEN, and only seven
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, x TEXT NOT NULL DEFAULT '{}',
  UNIQUE (src_id, dst_id, kind, producer_id)   -- identity IN THE SCHEMA, or INSERT OR IGNORE is
);                                             -- a no-op with nothing to conflict on
CREATE INDEX rel_dst ON rel(dst_id, kind);
CREATE INDEX rel_src ON rel(src_id, kind);     -- D5 supplies the half D2 omitted

CREATE TABLE mark (                -- sparse inline formatting over block.text
  mark_id INTEGER PRIMARY KEY,     -- a SURROGATE: two links may cover the same range
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  a INTEGER NOT NULL, b INTEGER NOT NULL,
  kind TEXT NOT NULL, value TEXT,
  CHECK (a >= 0 AND b >= a)
);
CREATE INDEX mark_block ON mark(block_id, a, b);
-- Overlaps are representable, so marker's bold+italic collapse is UNEXPRESSIBLE here and
-- hyphenation is recoverable. `mark.kind` is deliberately TEXT and OPEN: an unknown kind is kept,
-- rendered as no formatting, and reported as OW_MARK_KIND_UNKNOWN (03:2727) -- which is why it is
-- not an enum_val domain.

-- ---------------------------------------------------------------------------
-- table_meta / cell / grid_slot -- 03 section 10.1 (:1846-1871), charter.md:1129-1157.
-- A cell IS an ordinary Block; grid_slot is the DERIVED cover map and is TOTAL when it exists.
-- ---------------------------------------------------------------------------

CREATE TABLE table_meta (
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  n_rows INTEGER NOT NULL, n_cols INTEGER NOT NULL,   -- n_cols = max(row_len); rows may be RAGGED
  row_len TEXT NOT NULL,           -- JSON int array: raggedness is EXPLICIT, never implied
  header_rows INTEGER NOT NULL DEFAULT 0, header_cols INTEGER NOT NULL DEFAULT 0,
  kind INTEGER NOT NULL,           -- data|layout  (a layout table is unwrapped by the SERIALIZER)
  recon_strategy TEXT,             -- native_xml|span_x0|span_center|proj_1|proj_3|proj_10|
                                   -- tableformer|vlm|human
  recon_score REAL,                -- marker's judge score, KEPT (marker computes then discards it)
  has_merges INTEGER NOT NULL DEFAULT 0,   -- 0 => grid_slot is EMPTY and slot(r,c) is arithmetic
  native_part TEXT, native_sha256 BLOB     -- hash-pinned original part => passthrough export
);
CREATE TABLE cell (                -- ORIGIN cells only; a cell IS a Block
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,
  r INTEGER NOT NULL, c INTEGER NOT NULL,
  row_span INTEGER NOT NULL DEFAULT 1, col_span INTEGER NOT NULL DEFAULT 1,
  UNIQUE (table_id, r, c)
);
CREATE TABLE grid_slot (           -- DERIVED cover map. Materialized ONLY when has_merges = 1,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,  -- capped at
  r INTEGER NOT NULL, c INTEGER NOT NULL,                                       -- MAX_GRID_SLOTS
  origin_id INTEGER NOT NULL REFERENCES cell(block_id) ON DELETE CASCADE,
  PRIMARY KEY (table_id, r, c)
) WITHOUT ROWID;
-- "which cell is above this one":
--   has_merges = 0 -> SELECT block_id  FROM cell      WHERE table_id=?1 AND c=?2 AND r=?3-1;
--   has_merges = 1 -> SELECT origin_id FROM grid_slot WHERE table_id=?1 AND c=?2 AND r=?3-1;
-- A merge-free 4M-cell sheet is 4,000,000 ordinary Blocks and ZERO grid_slot rows. The FK on
-- origin_id targets `cell`, not `block`, so "an origin that is not a cell of this table" is
-- unrepresentable rather than merely wrong (03:2062-2065).

CREATE TABLE part (               -- named byte streams of the original container, hash-pinned
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  path TEXT NOT NULL,             -- 'file' | 'word/document.xml' | 'pdf:page=12/content=0'
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL,
  store_ref TEXT,                 -- cas://ab/cd/<sha256>   NULL => bytes were not retained
  PRIMARY KEY (doc_ord, path)
) WITHOUT ROWID;
-- INVARIANT (INV-10): quote='verbatim' requires part.store_ref IS NOT NULL AND ONE OF EXACTLY
-- THREE RE-VERIFIABLE BRANCHES, all three proved the same way, by re-reading the retained part:
--   bytes    : nfc(part_bytes[os_a : os_a+os_b].decode(*os_codec.split('/', 1)))  ==  block.text
--   nodepath : nfc(node_text(part, os_path))                                      ==  block.text
--   glyphs   : re-extracting glyphs [os_a, os_a+os_b) from `part` with the RECORDED os_extractor
--              (e.g. 'pdftext@0.6') reproduces block.text under NFC
-- `pixels` and `none` can NEVER reach verbatim: there is nothing to re-read. The charter writes
-- the bytes branch with `normalize_k`; errata E48-E51 replace it with `nfc()` at all four loci,
-- because normalize_k casefolds and would prove "abc" verbatim against source bytes "ABC"
-- (03:1470-1483).

-- ---------------------------------------------------------------------------
-- asset / block_asset / page_render -- 03 section 11 (:2069-2151), charter.md:1181-1208.
-- NO INLINE BYTES, EVER: bytes live in the CAS at .omniweave/cas/ab/cd/<sha256>.
-- ---------------------------------------------------------------------------

CREATE TABLE asset (
  asset_id INTEGER PRIMARY KEY,
  doc_ord  INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  origin_part TEXT,               -- anydoc's origin_part, unique in the collection
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL, width INTEGER, height INTEGER,
  store_ref TEXT NOT NULL,        -- cas://ab/cd/<sha256>   NO INLINE BYTES, EVER
  licence TEXT, licence_url TEXT, spdx TEXT, source_url TEXT, retrieved_at_ns INTEGER,
  restriction_bits INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX asset_identity ON asset(doc_ord, sha256, IFNULL(origin_part,''));
CREATE TABLE block_asset (
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id) ON DELETE CASCADE,
  role TEXT NOT NULL,             -- image|thumbnail|source_crop|ole|chart_data|bake|font
  PRIMARY KEY (block_id, asset_id, role)
) WITHOUT ROWID;

-- Page renders are a DERIVED, EVICTABLE cache. Not a model field, by construction. [DER]
CREATE TABLE page_render (
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, page INTEGER NOT NULL,
  dpi INTEGER NOT NULL, renderer TEXT NOT NULL, renderer_version TEXT NOT NULL,
  colorspace TEXT NOT NULL, asset_id INTEGER NOT NULL REFERENCES asset(asset_id),
  last_used_ns INTEGER NOT NULL,
  PRIMARY KEY (doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)
) WITHOUT ROWID;
-- Decoded 192-DPI A4 pages are 10.7 MB EACH: 43 MB for a four-page batch, ~53 GB for 5,000.
-- That arithmetic is why rendering FOLLOWS routing and is never a model field.

-- ---------------------------------------------------------------------------
-- diag -- FAILURE IS A FIELD, not an exception. charter.md:1210-1218, 03 section 9.
-- `block_id` is deliberately NOT a foreign key: a diagnostic often concerns a block the parse then
-- refused to write, and an FK would force a choice between losing the diagnostic and writing a
-- block that was rejected (03:1813-1815).
-- ---------------------------------------------------------------------------

CREATE TABLE diag (
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen INTEGER NOT NULL, page INTEGER, block_id INTEGER, part TEXT,
  code TEXT NOT NULL,             -- the SYMBOL from codes.toml; callers branch on this
  severity TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
  component TEXT NOT NULL, message TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
  fatal INTEGER NOT NULL          -- anydoc's is_fatal(): a limit breach is never swallowed
);
CREATE INDEX diag_code ON diag(code);   -- THE ABSENCE CONTRACT READS THIS (gate 9)

-- ---------------------------------------------------------------------------
-- block_fts -- the lexical Channel. External-content: NO second copy of the text (INV-1). [DER]
--
-- The OPTION SET is 07-store-and-retrieval.md section 3.3's and this file may not change one:
-- `detail='full'` supplies the instance offsets `ChannelResult.spans` carries, `columnsize=1` the
-- per-row length bm25() normalises by, `content='block'` is what makes it external-content, and
-- `prefix` is DELIBERATELY ABSENT (a `tok*` query scans a term-index range instead, affordable at
-- MAX_QUERY_TERMS = 64, and identity-tier prefix matching uses B-tree ranges on block_cite and
-- doc(uri)). A persistent `rank` is NEVER set: it would put part of the scorer outside
-- SCORER_VERSION, so a scorer change would not invalidate a cached score. Changing any option is a
-- SCHEMA major bump made in 07 section 3.3, never here.
-- ---------------------------------------------------------------------------

CREATE VIRTUAL TABLE block_fts USING fts5(
  text,
  content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2',
  detail='full',            -- REQUIRED: instance offsets are what ChannelResult.spans carries
  columnsize=1);            -- REQUIRED: bm25() needs per-row length for its normalisation

-- The three sync triggers, WITH the two guards a naive version omits: skip rows where state <> 0,
-- skip rows where text IS NULL, and make the 'delete' command row carry the OLD values EXACTLY as
-- indexed -- an external-content FTS5 table stores no text of its own, so a 'delete' whose text
-- differs from what was indexed corrupts the index silently. 03:2432-2447 is normative for the
-- text; 07 section 3.3 requires the guards.
--
-- A TRIGGER NAME IS GLOBAL IN sqlite_master and the shipped DDL uses no IF NOT EXISTS, so these
-- three names may appear in no other migration: printing block_fts_ai again in 0003_index.sql
-- would abort G27(b) at `trigger block_fts_ai already exists` and, by the forward-reference rule,
-- NEITHER FILE would apply. 0003's head_fts and block_tri sets carry their own names for exactly
-- that reason (07 section 3.3, section 3.4).
--
-- Tombstoning is an UPDATE state 0 -> 1, so block_fts_au removes the row and does not re-add it:
-- there is no separate tombstone trigger. And block_fts indexes EVERY generation, including staged
-- ones, so a lexical search joins ow_block_head (03:2458-2462).
CREATE TRIGGER block_fts_ai AFTER INSERT ON block
WHEN new.state = 0 AND new.text IS NOT NULL BEGIN
  INSERT INTO block_fts(rowid, text) VALUES (new.block_id, new.text);
END;
CREATE TRIGGER block_fts_ad AFTER DELETE ON block
WHEN old.state = 0 AND old.text IS NOT NULL BEGIN
  INSERT INTO block_fts(block_fts, rowid, text) VALUES ('delete', old.block_id, old.text);
END;
CREATE TRIGGER block_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, text)
    SELECT 'delete', old.block_id, old.text
     WHERE old.state = 0 AND old.text IS NOT NULL;
  INSERT INTO block_fts(rowid, text)
    SELECT new.block_id, new.text
     WHERE new.state = 0 AND new.text IS NOT NULL;
END;
