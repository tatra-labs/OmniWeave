-- 0003_index.sql -- L4: the occurrence tables, `embed_space`, the retrieval indexes. SCHEMA = 1.
--
-- WHAT THIS FILE IS. The third of the reserved migration numbers, and the one file whose contents
-- 07-store-and-retrieval.md section 3 prints itself rather than delegating: its row in section 3's
-- table reads "L4: this section". Every statement below is transcribed from sections 3.2 through
-- 3.8 of that document, which is normative for all of them. Applied forward-only, in numeric
-- order, one transaction per file, by the migration runner (11-repo-layout.md section 5.1).
--
-- WHY THIS FILE IS 0003. 11-repo-layout.md:1188: "0002_graph.sql precedes 0003_index.sql because
-- L4 indexes and foreign keys reference L3 tables, and the reverse ordering was a real defect --
-- an index on a table a later file creates aborts the migration and NEITHER FILE APPLIES."
-- L4 reads exactly three L3 objects and adds no second representation of anything (INV-1):
--   `segment`        three indexes plus the `ow_segment_head` projection (section 3.2)
--   `anchor`         the two reference views join it by equality (section 3.5)
--   `relation_vocab` `block_link.relation` is a foreign key into it (section 3.6)
-- All three are BACKWARD references into 0002_graph.sql, so section 3's forward-reference table
-- does not come into play in this file at all. It also reads 0001_init.sql's `block`, `doc` and
-- `producer`. NOTHING HERE MAY NAME AN OBJECT 0004_runtime.sql OR 0005_out.sql CREATES.
--
-- WHAT DOES *NOT* BELONG HERE, and each omission is a recorded failure rather than an oversight:
--   * `block_fts`'s three sync triggers. They ship in 0001_init.sql beside the table
--     (03-document-model.md section 13.1 is normative for their text). 07 section 3.3 states the
--     consequence of printing them twice: "a trigger name is global in sqlite_master and the
--     shipped DDL uses no IF NOT EXISTS, so printing `block_fts_ai` a second time in
--     `0003_index.sql` would abort G27(b) ... at `trigger block_fts_ai already exists`, and by the
--     same forward-reference rule that governs the migration order above, NEITHER FILE WOULD
--     APPLY." charter.md:3148-3160 re-prints them inside its L4 fence; 07 section 3.3 is the
--     later and normative site and it forbids the repetition.
--   * `ow_block_head`. 03-document-model.md section 13.1 declares it in 0001_init.sql beside
--     `block`; charter.md:3310 re-prints it here, and the same name-collision rule applies.
--   * The `vec` and `events` sidecars (07 sections 3.9 and 3.10). Those are separate database
--     FILES -- `index.vec.owstore`, ATTACHed as `vec`, and `events.owstore` -- not tables in
--     `main`, and section 3.13's register gives their objects the owner "events" rather than 0003.
--   * `asset`, `block_asset`, `part`, `page_render` (section 3.11) and the five `cache_index`
--     objects (section 3.12), which are 0001_init.sql's and 0004_runtime.sql's respectively.
--     Section 3 discusses their storage consequences without owning their DDL.
--   * `index_state`'s and `migration`'s ROWS. The tables are created empty here; the runner writes
--     `index_state.schema` and one `migration` row per applied file. G27(b) asserts, "at the end
--     of the run and not after 0001_init.sql", that `index_state` holds exactly one `schema` row
--     equal to f"{SCHEMA}.{SCHEMA_MINOR}" from `omniweave_core.contract` and that `meta` holds no
--     `schema` key at all -- anchored at the end of the run precisely because `index_state` is
--     created by THIS file (11-repo-layout.md:1196-1200, ADR-9).
--
-- ENCODING. ASCII only, LF, UTF-8, one trailing newline. The pragmas are per connection and per
-- file-create (07 section 2.1) and the transaction is the runner's, so this file opens no BEGIN.
--
-- LEGEND (07 section 3, restated because every object below carries a tag and the tag decides
-- what a minor migration may do to it, per section 3.1):
--   [SOR] system of record, part of the published read contract at this SCHEMA major. A minor
--         migration may NOT drop and re-create it.
--   [DER] derived and rebuildable by one command (`ow store rebuild <object>`), not a read
--         contract, droppable.
--
-- CONDITIONAL STATEMENTS. Section 3.4's trigram set is created ONLY when [retrieval] trigram =
-- true, which a static SQL file cannot decide. The set is delimited below by
--   -- @ow:optional-begin <name>   ... -- @ow:optional-end <name>
-- and the contract is: the runner applies every statement outside an optional region always, and
-- the statements inside one only when that region's named condition holds. G27(b) applies the
-- whole file, conditional region included, which is the desired reading -- it proves the
-- conditional DDL is valid without deciding whether a given store wants it. `tools/indexes.toml`
-- marks the whole set conditional (section 3.13), so a store built with trigram = false neither
-- creates the statements nor is faulted for their absence.

-- =========================================================================================
-- 07 section 3.2 -- what L4 adds over the SEGMENT, which is L3's and gets no second segmenter
-- =========================================================================================

CREATE INDEX segment_digest_ix  ON segment(content_digest) WHERE state = 0;              -- [DER]
--   serves: the semantic Channel's inner join from a `vseg` digest back to a live segment, and
--   the corpus-wide embedding dedup (identical text is embedded once).
CREATE INDEX segment_doc        ON segment(doc_ord, gen, first_page) WHERE state = 0;    -- [DER]
--   serves: `Filters.pages` and `Filters.doc_keys` narrowing on the segment side, and
--   `ow index segments`.
CREATE INDEX segment_restricted ON segment(restriction_bits) WHERE restriction_bits <> 0; -- [DER]
--   serves: absence gate 10 (`restricted_withheld`) counting, without scanning live segments.
--   PARTIAL because on a corpus with no restrictions this index holds zero rows and costs zero
--   bytes and zero write amplification.

-- The head-generation projection of the SEGMENT, the exact parallel of `ow_block_head`
-- (03-document-model.md section 13.1). A staged generation's segments are durable and INVISIBLE;
-- this view is the mechanism, not a convenience. 07 section 3.2: "ow_segment_head is declared
-- here, and this is its only home" -- it ships with the three indexes above rather than in
-- 0002_graph.sql, and `segment` is one file earlier so the reference is backward.
-- The join is spelled out clause for clause to match `ow_block_head`; charter.md:3312 prints the
-- same statement with USING (doc_ord), and the two forms are identical in SQLite because
-- SELECT s.* is unaffected by USING's column coalescing.
CREATE VIEW ow_segment_head AS                                                           -- [SOR]
  SELECT s.* FROM segment s JOIN doc d ON d.doc_ord = s.doc_ord
   WHERE s.gen = d.gen AND s.state = 0;

-- =========================================================================================
-- 07 section 3.3 -- lexical. `block_fts` is 0001's; `head_fts` is this section's, table and
-- trigger set together, and every trigger is named explicitly because sqlite_master has ONE
-- namespace for all of them.
-- =========================================================================================

CREATE VIRTUAL TABLE head_fts USING fts5(          -- block.label: NULL on most rows => tiny [DER]
  label, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2', detail='full', columnsize=1);
-- The FTS5 column is named `label` because the `block` column is: 03-document-model.md section
-- 13.1 declares `label TEXT`, and ADR-1 decision 7 renamed it from `title` so that `Kind.TITLE`
-- keeps the word. An external-content FTS5 table resolves its column names against
-- content='block', so `head_fts(title ...)` over a table with no `title` column raises
-- `no such column: title` WHEN THIS FILE APPLIES -- which, by the forward-reference rule, takes
-- G27(b)'s whole run with it. charter.md:3161 still prints `title`; 03 section 13.1's DDL is the
-- one home for the name and 07 section 3.3 prints the corrected statement.
-- The option set is 07 section 3.3's and a change to any of it is a SCHEMA major bump:
-- detail='full' supplies the instance offsets `ChannelResult.spans` carries, columnsize=1 the
-- per-row length bm25() normalises by, and there is deliberately no `prefix` index and never a
-- persistent `rank` (a stored rank would put part of the scorer outside SCORER_VERSION).

-- The same two guards as `block_fts`'s set and the same 'delete'-carries-OLD rule, with `label`
-- substituted for `text`: skip rows where state <> 0, skip rows where the column IS NULL, and make
-- the 'delete' command row carry the OLD values EXACTLY as indexed -- an external-content table
-- stores no text of its own, so a 'delete' whose value differs from what was indexed corrupts the
-- index silently. `block_fts`'s set and this one both fire on `block` and maintain disjoint
-- indexes, so their relative firing order is irrelevant and neither reads the other's table.
CREATE TRIGGER head_fts_ai AFTER INSERT ON block
  WHEN NEW.state = 0 AND NEW.label IS NOT NULL
  BEGIN INSERT INTO head_fts(rowid, label) VALUES (NEW.block_id, NEW.label); END;
CREATE TRIGGER head_fts_ad AFTER DELETE ON block
  WHEN OLD.state = 0 AND OLD.label IS NOT NULL
  BEGIN INSERT INTO head_fts(head_fts, rowid, label)
        VALUES ('delete', OLD.block_id, OLD.label); END;
CREATE TRIGGER head_fts_au AFTER UPDATE ON block BEGIN
  INSERT INTO head_fts(head_fts, rowid, label)
    SELECT 'delete', OLD.block_id, OLD.label WHERE OLD.state = 0 AND OLD.label IS NOT NULL;
  INSERT INTO head_fts(rowid, label)
    SELECT NEW.block_id, NEW.label        WHERE NEW.state = 0 AND NEW.label IS NOT NULL;
END;
-- Retiring a generation sets its blocks state = 1 in the SAME transaction that advances doc.gen,
-- so `block_fts_au` and `head_fts_au` remove them from both FTS tables and re-add nothing. THE
-- INDEX LAYER NEVER HOLDS TWO GENERATIONS -- which is what makes `ow_block_head` a filter rather
-- than a deduplication. No FTS-bearing table is ever emptied by a cascade: whether an
-- ON DELETE CASCADE fires row triggers is governed by PRAGMA recursive_triggers, which
-- CONN_PRAGMAS does not set, so deleting a document is `DELETE FROM block WHERE doc_ord = ?`
-- FIRST and `DELETE FROM doc WHERE doc_ord = ?` second, in one transaction (07 section 3.3).

-- @ow:optional-begin trigram   -- applied only when [retrieval] trigram = true (07 section 3.4)
-- Trigram is off by default and is ONE LADDER RUNG INSIDE THE `exact` CHANNEL at tier 35, never a
-- sixth Channel: CHANNELS is a closed five-tuple. It contributes MEMBERSHIP, never a score -- a
-- trigram hit is a substring match and a bm25() over trigrams is a number with no interpretation.
-- `IndexCaps.has_trigram` tells the planner whether the rung exists; MIN_TRIGRAM_CHARS = 3 is
-- refused below with a usage error, because a trigram index cannot match a two-character needle.
-- Its cost is UNVERIFIED for the trigram tokenizer -- the rejected ~2.6x figure measures a
-- `prefix='2 3'` index -- which is the honest reason it ships opt-in.
CREATE VIRTUAL TABLE block_tri USING fts5(                                               -- [DER]
  text, content='block', content_rowid='block_id',
  tokenize='trigram');
-- DEFECT, MEASURED, AND THE ONE STATEMENT IN THIS FILE THAT IS NOT ITS SOURCE VERBATIM.
-- 07 section 3.4 prints `tokenize='trigram remove_diacritics 1'`. The FTS5 TRIGRAM tokenizer
-- gained a `remove_diacritics` option only in SQLite 3.45.0; before that its only option is
-- `case_sensitive`. Measured on 3.43.1 in this workspace:
--     tokenize='trigram'                  -> OK
--     tokenize='trigram case_sensitive 0' -> OK
--     tokenize='trigram remove_diacritics 1' -> sqlite3.OperationalError:
--                                               error in tokenizer constructor
-- MIN_SQLITE is (3, 42, 0) at five sites -- 02-architecture.md section 2 row 7 and section 6 row
-- 6, 07 section 2.1, charter.md:430 and :8518 -- it is already a shipped constant in
-- `omniweave_core.limits`, and it is G27(b)'s own flag (`--min-sqlite 3.42`, 16-roadmap.md's P2
-- exit line). 07 section 2.1 justifies the floor exhaustively as "three features deep" (STRICT
-- 3.37, unixepoch() 3.38, unixepoch('subsec') 3.42); a fourth feature at 3.45 would have been
-- named there. So the printed option string, and not the floor, is the defective side, and the
-- bare `trigram` tokenizer is shipped instead: it applies identically on every SQLite at or above
-- the floor, whereas the printed form makes G27(b) fail outright wherever [retrieval]
-- trigram = true below 3.45.0. Two corroborating details: `remove_diacritics 1` is the value 07
-- section 3.3's own option table calls defective ("version 1 mishandles multi-codepoint diacritic
-- sequences", which is why `block_fts` and `head_fts` use 2), and 1 is not a legal trigram value
-- at any version. The consequence is disclosed rather than hidden: a trigram substring probe does
-- not fold diacritics. It contributes MEMBERSHIP ONLY inside a ladder rung of an opt-in Channel,
-- so the effect is confined to whether an accented needle matches an unaccented haystack; the
-- table is [DER] and `ow store rebuild block_tri` re-creates it if the option is ever restored.
-- The three triggers are 03 section 13.1's `block_fts` trigger bodies with `block_tri` substituted
-- for `block_fts`, and they ship in this file so no name collides with 0001's. "The same three
-- triggers" is not a legal instruction: a trigger name is global in sqlite_master and
-- CREATE TRIGGER is not idempotent, so the set is written out.
CREATE TRIGGER block_tri_ai AFTER INSERT ON block
  WHEN NEW.state = 0 AND NEW.text IS NOT NULL
  BEGIN INSERT INTO block_tri(rowid, text) VALUES (NEW.block_id, NEW.text); END;
CREATE TRIGGER block_tri_ad AFTER DELETE ON block
  WHEN OLD.state = 0 AND OLD.text IS NOT NULL
  BEGIN INSERT INTO block_tri(block_tri, rowid, text)
        VALUES ('delete', OLD.block_id, OLD.text); END;
CREATE TRIGGER block_tri_au AFTER UPDATE ON block BEGIN
  INSERT INTO block_tri(block_tri, rowid, text)
    SELECT 'delete', OLD.block_id, OLD.text WHERE OLD.state = 0 AND OLD.text IS NOT NULL;
  INSERT INTO block_tri(rowid, text)
    SELECT NEW.block_id, NEW.text        WHERE NEW.state = 0 AND NEW.text IS NOT NULL;
END;
-- @ow:optional-end trigram

-- =========================================================================================
-- 07 section 3.5 -- exact: the occurrence side of `anchor`. The Channel exists because unicode61
-- destroys exactly the tokens a document query needs: 'section 4.2(b)' becomes 4 . 2 . b,
-- 'ISO-8601' becomes iso . 8601. `anchor` (what a document DEFINES) is 0002_graph.sql's.
--
-- ONE CONCEPT, ONE COLUMN NAME, ONE VOCABULARY. The definition side and the occurrence side are
-- joined by equality in the two views below, so they must agree on both: the column is `name_norm`
-- on both tables and `akind` on both tables, and the vocabulary is the single Python enum
-- `AnchorKind`. Previously `anchor.akind` said `citation_key` where `ref_site.kind` said
-- `citekey`, and `citation_key` never equals `citekey` -- so EVERY citation-key reference was
-- permanently unresolved, permanently visible in `ref_unresolved`, permanently absent from
-- `ow_ref_resolved`, with nothing anywhere reporting it.
-- =========================================================================================

CREATE TABLE ref_site (               -- EVERY reference occurrence. NO status column, EVER. [SOR]
  name_norm TEXT NOT NULL,            -- normalize_key of the resolvable name. Same NAME as
                                      --   anchor's, and the same normaliser.
  akind     TEXT NOT NULL,            -- AnchorKind, the SAME closed vocabulary as anchor.akind,
                                      --   stored as the lower-case member name.
  doc_ord   INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  --   ^ DENORMALISED onto this table so the document-scope predicate is an index lookup and not a
  --     correlated subquery. That is the difference between a 2 ms and a 400 ms `exact` Channel on
  --     a 17-document corpus, and the gap widens linearly.
  block_id  INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, ts_b INTEGER NOT NULL,   -- a half-open TextSpan into block.text
  --   ^ `ts_a`/`ts_b`, not `a`/`b`: the terminology lock reserves that pair for a TextSpan and
  --     `os_*` for an OriginSpan, and this table's span is a TextSpan -- half-open [ts_a, ts_b) in
  --     CHARACTERS of block.text, whereas an OriginSpan's `os_a` is an OFFSET and `os_b` is a
  --     LENGTH in whatever unit `os_kind` names. The asymmetry is deliberate (a glyph run has no
  --     meaningful end offset in the byte stream) and a semgrep rule rejects `os_a:os_b` slicing
  --     and `text[ts_a:ts_a+ts_b]`. charter.md:3182 still prints `a`/`b`; 07 section 3.5 renames
  --     them and is normative for this table.
  surface  TEXT NOT NULL,             -- 'section 4.2(b)' as written. DISPLAYED, never matched.
  scope    TEXT NOT NULL CHECK (scope IN ('document','corpus')),
  origin_operator TEXT NOT NULL, run_id INTEGER,
  PRIMARY KEY (name_norm, akind, block_id, ts_a)
) WITHOUT ROWID;
CREATE INDEX ref_site_block ON ref_site(block_id);
--   serves: hydration ("which references does this hit contain") and cascade locality.
CREATE INDEX ref_site_name  ON ref_site(name_norm, akind);
--   serves: the `exact` Channel's probe, and the `anchor_delta` join that retries the unresolved
--   set when a document's defined names change.
-- MAX_REF_SITES_PER_BLOCK = 32; a breach emits Diag(OW_REFSITE_TRUNCATED) and is COUNTED.

-- Resolution is BY STRING, so there is no lifecycle and nothing to go stale. Both predicates in
-- both views are load-bearing and both failed silently without them:
--   1. `n.gen = dd.gen` -- without it a RETIRED generation's anchor still satisfies the anti-join,
--      so a reference "resolves" against text that is no longer the head.
--   2. the scope clause -- without it a scope='document' anchor in document A resolves a
--      `ref_site` in document B: "Figure 3" in one contract binding "Figure 3" in another. That is
--      the single most common false merge in a document corpus, guarded for entities and, before
--      this, wide open on the reference path.
-- `ref_unresolved` is a member of canonical_projection(), so a full build and an incremental build
-- agreed on the SAME WRONG ANSWER and gate G19 could never see it. A view over the right
-- predicates is the fix; a status column would only have recorded the wrong answer durably.
CREATE VIEW ref_unresolved AS                                                            -- [SOR]
  SELECT s.name_norm, s.akind, s.doc_ord, s.block_id, s.ts_a, s.ts_b, s.surface, s.scope
  FROM ref_site s
  WHERE NOT EXISTS (
    SELECT 1 FROM anchor n JOIN doc dd ON dd.doc_ord = n.doc_ord
    WHERE n.name_norm = s.name_norm AND n.akind = s.akind
      AND n.gen = dd.gen                                     -- HEAD GENERATION ONLY
      AND (n.scope = 'corpus' OR n.doc_ord = s.doc_ord));    -- SCOPE IS HONOURED

CREATE VIEW ow_ref_resolved AS                                                           -- [SOR]
  SELECT s.block_id AS src_block, n.block_id AS dst_block, s.name_norm, s.akind, s.ts_a, s.ts_b
  FROM ref_site s
  JOIN anchor n ON n.name_norm = s.name_norm AND n.akind = s.akind
  JOIN doc dd   ON dd.doc_ord = n.doc_ord AND n.gen = dd.gen      -- HEAD GENERATION ONLY
  WHERE n.scope = 'corpus' OR n.doc_ord = s.doc_ord;              -- SCOPE IS HONOURED

CREATE TABLE ref_attempt (            -- the FAILED TAIL only: written after a first failure. [DER]
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  ts_a INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 1, last_tried_gen INTEGER,
  candidates TEXT NOT NULL DEFAULT '[]',   -- JSON array of near-miss cites
  PRIMARY KEY (block_id, ts_a)
) WITHOUT ROWID;
-- `ref_attempt` gives the hot retry set an index without introducing a status column that can
-- lie. `ow store residue` prints `ref_unresolved` grouped by `name_norm`: THE RESIDUE IS DATA,
-- not a log line.

-- =========================================================================================
-- 07 section 3.6 -- structural: the section prefix index and the block->block link table
-- =========================================================================================

CREATE TABLE block_sec (              -- a section PREFIX index. Not an identity, not an     [DER]
  block_id  INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,  -- ordering
  sec_id    INTEGER NOT NULL,         -- the nearest heading/section block         authority.
  sec_depth INTEGER NOT NULL,
  sec_path  TEXT    NOT NULL          -- '/0001/0004/0002' -- "everything under 4.2" is a prefix
) WITHOUT ROWID;                      --   range
CREATE INDEX block_sec_path ON block_sec(sec_path, block_id);
--   serves: `Filters.sec_path_prefix` as a range scan (sec_path >= '/0001/0004/0002' AND sec_path
--   < '/0001/0004/0003'), and the lexical scorer's spine term. `block_id` is in the key so the
--   scan is covering and never touches `block`.
-- `sec_path` components are ZERO-PADDED TO FOUR DIGITS, because a plain integer path makes
-- '/1/10' < '/1/2' lexicographically and the range scan silently returns the wrong set. The prefix
-- upper bound is the path with its last component incremented, and a section with more than 9,999
-- siblings emits Diag(OW_RESOURCE_LIMIT, {limit: "SEC_PATH_FANOUT"}) and truncates the path at
-- that depth rather than producing an unsortable key.
-- `block_sec` is computed once and read twice: as an indexed prefix for retrieval, and by the
-- segmenter, which reads it to produce `segment.heading_path`. One computation, two shapes.
-- NOTE FOR THE PLAN'S OWNER: 03-document-model.md:2477 calls `block_sec` "L3's" in its read-
-- contract paragraph. 07 section 3.6 declares it here and section 3.13's register gives it the
-- owner 0003, so this file is its home; only the aside in 03 disagrees.

CREATE TABLE block_link (             -- block->block. `edge` is L3's entity->entity table.  [SOR]
  link_id     INTEGER PRIMARY KEY,
  src_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_block   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  relation    TEXT    NOT NULL REFERENCES relation_vocab(relation),  -- OPEN vocabulary
  --   ^ a BACKWARD reference into 0002_graph.sql. It references that table and not `enum_val`
  --     because an enum generated from a Python enum cannot express "a driver may declare a new
  --     relation". This foreign key is one of the three reasons L3 must precede L4.
  site_block  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,  -- WHERE it was observed
  via_entity  INTEGER,                -- an entity_id when the relation is entity-mediated.
                                      -- DELIBERATELY NO FOREIGN KEY; `ow store verify` checks it
                                      -- instead. NOTE FOR THE PLAN'S OWNER: 07 section 3.6 and
                                      -- charter.md:3238 both justify the absence with "L3 creates
                                      -- `entity` in a later migration and SQLite cannot add an FK
                                      -- by ALTER", which is STALE under the numbering this file
                                      -- ships with -- `entity` is created one file EARLIER. The
                                      -- decision stands and is implemented as printed; only the
                                      -- reason needs rewriting.
  bound_by    TEXT,                   -- the anchor name_norm that RESOLVED this link; drives
                                      -- unbind. NULL => never unbound.
  weight      REAL    NOT NULL DEFAULT 1.0,
  ambiguous   INTEGER NOT NULL DEFAULT 0,   -- >1 target matched: KEPT, ranked down, never dropped
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust       INTEGER NOT NULL,       -- Trust ord. Absent => 0. Migrations only DOWNGRADE.
  score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL, origin_driver TEXT NOT NULL, driver_schema_v INTEGER NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX block_link_identity ON block_link(
  src_block, dst_block, relation, producer_id, IFNULL(site_block,-1), IFNULL(via_entity,-1));
--   serves: INSERT OR IGNORE. Without the IFNULL sentinels there is nothing to conflict on and
--   INSERT OR IGNORE degenerates to a plain INSERT (codegraph #1034: byte-identical duplicates
--   that inflated counts and flowed into callers). The installing migration MUST GROUP BY the
--   IDENTICAL expression, sentinels included. An identity containing an IFNULL sentinel is ALWAYS
--   a separate CREATE UNIQUE INDEX, never an inline UNIQUE/PRIMARY KEY: SQLite prohibits an
--   expression in a table-level constraint, so the inline form does not merely fail review, it
--   fails CREATE TABLE (ST10, verified on 3.45.1).
CREATE INDEX block_link_out ON block_link(src_block, relation);
--   serves: the forward hop of Expand's frontier BFS. The left prefix covers src-only lookups,
--   which is why there is no separate single-column index.
CREATE INDEX block_link_in  ON block_link(dst_block, relation);
--   serves: the reverse hop, and `ow open`'s back-references ("what points at this block").
CREATE INDEX block_link_bound ON block_link(bound_by) WHERE bound_by IS NOT NULL;
--   serves: anchor_delta unbinding. PARTIAL because most links have no binding anchor.
CREATE INDEX block_link_restricted ON block_link(restriction_bits) WHERE restriction_bits <> 0;
--   serves: absence gate 10 on the traversal path.
-- DELIBERATELY ABSENT: single-column src/dst indexes. codegraph's migration v4 DROPS the
-- equivalents as dead weight on the write path; the two-column indexes cover them by left prefix.
-- In the same repository, dropping the four non-unique edge indexes for a bulk load measured
-- 2.8 s -> 1.1 s on a 224k-edge insert with ~0.3 s to re-create -- the measured basis for
-- 07 section 10.6's bulk windows, and the reason the UNIQUE identity index is never dropped.
-- MAX_LINKS_PER_BLOCK = 4096, enforced at write.

-- =========================================================================================
-- 07 section 3.7 -- the semantic Channel's write-time contract. The payload lives in the `vec`
-- sidecar, which is a separate file and not this migration's.
-- =========================================================================================

CREATE TABLE embed_space (            -- a meta.json as a table WITH A UNIQUE CONSTRAINT   [SOR]
  space_id        INTEGER PRIMARY KEY,
  model_key       TEXT    NOT NULL UNIQUE,   -- sha256_canonical(the nine fields below)[:16]
  driver_id       TEXT    NOT NULL,          -- an embed/1 DriverId, e.g. 'embed.text.bge_m3'
  driver_schema_v INTEGER NOT NULL,
  model_id        TEXT    NOT NULL,
  model_rev       TEXT    NOT NULL,          -- an EXACT sha. '' or 'main' is REFUSED
  dim             INTEGER NOT NULL,
  metric          TEXT    NOT NULL CHECK (metric IN ('cosine','ip','l2')),
  normalize       INTEGER NOT NULL,
  pooling         TEXT    NOT NULL,
  doc_prompt_digest   BLOB NOT NULL,         -- applied ONCE, client side, at build
  query_prompt_digest BLOB NOT NULL,         -- applied ONCE, client side, at query
  sig_bits        INTEGER NOT NULL,          -- the binary signature WIDTH IN BITS; 0 = none
  storage         TEXT    NOT NULL CHECK (storage IN ('sig_only','sig_full')),
  backend         TEXT    NOT NULL,          -- an `omniweave.backends` entry-point name
  created_ns      INTEGER NOT NULL
);
-- THE NINE IDENTITY FIELDS are model_id, model_rev, dim, metric, normalize, pooling,
-- doc_prompt_digest, query_prompt_digest, and driver_id + driver_schema_v. A search whose embed
-- Driver does not reproduce `model_key` is REFUSED with OW-S-020 printing BOTH tuples -- on the
-- SEARCH path, not only the build path. Making `model_key` a UNIQUE column is what turns "the
-- query embedder drifted" from a silent recall collapse into a refusal.
-- `sig_bits` DEFAULTS TO `dim` (one sign bit per dimension is what binary quantisation of a
-- normalised vector produces), so the shipped bge-m3 space at dim = 768 has sig_bits = 768 and a
-- 96-byte signature. sig_bits = 0 means the space is sig_full with no signature stage and
-- VEC_BRUTE_MAX does not apply to it; the stdlib backend refuses such a space outright.
-- [retrieval.vec] storage = "auto" resolves ONCE, AT BUILD TIME, and the resolved value is
-- written here and to `vec_manifest` and never re-derived at query time.
-- [capability.embed] on a driver card therefore keeps only dim, max_tokens and languages: the
-- identity lives here, once (INV-21).

-- =========================================================================================
-- 07 section 3.8 -- freshness, coverage, state, statistics, migrations
-- =========================================================================================

CREATE TABLE ingest_scope (           -- written by the enumerator / an acquire driver     [SOR]
  scope_id TEXT PRIMARY KEY,          -- the canonical URI PREFIX of the enumerated root
  discovered INTEGER NOT NULL, indexed INTEGER NOT NULL,
  skipped INTEGER NOT NULL, skipped_why TEXT NOT NULL DEFAULT '{}',
  scanned_at_ns INTEGER NOT NULL, complete INTEGER NOT NULL
);
-- AN ABSENT ROW MEANS "COVERAGE UNKNOWN", NEVER "NOTHING WAS EXCLUDED". Absence gate 4 reads this
-- and fires when any scope row in view has discovered > indexed, complete = 0, OR DOES NOT EXIST.
-- `scope_id` is a URI PREFIX and that is what makes gate 4 implementable: there is no
-- `doc.scope_id` column and there must not be one, because a document can be reached by two scans.
-- The containment test is `doc.uri GLOB scope_id || '*'` over `doc` (thousands of rows, not
-- millions, so an unindexed scan is the right implementation) and NO INDEX IS ADDED FOR IT.

CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);                          -- [SOR]
-- corpus_id . shard_ord . schema . scorer_version . generation . fts_state{ok,building,stale}
-- . bulk_window . wal_baseline_bytes . last_full_index_ns . default_space_id . unicode_version
-- `index_state.schema` holds <major>.<minor> and is THE ONLY PLACE ON DISK that holds it -- `meta`
-- never gains a `schema` key (07 section 3.1, ADR-9). The reader's own pair is `SCHEMA` and
-- `SCHEMA_MINOR` in `omniweave_core.contract`, formatted at exactly one site, in `contract`
-- itself; `omniweave_core.limits` holds no version constant, now or ever.
-- `fts_state` is a THREE-STATE MACHINE the lexical Channel reads: `ok` runs normally, `building`
-- returns UNAVAILABLE(fts_building) with OW-S-032 and FORCES `degraded`, `stale` returns
-- UNAVAILABLE(fts_stale) and `ow doctor` names `ow store repair`. It is written in the same
-- transaction as the DDL that invalidates it, so a crash leaves the pessimistic value: an FTS
-- index of unknown completeness must degrade the Verdict, because a missing posting is
-- indistinguishable from an absent phrase.

CREATE TABLE stat (k TEXT PRIMARY KEY, v INTEGER NOT NULL, computed_ns INTEGER NOT NULL); -- [DER]
-- ONLY SCALAR COUNTS, for the over-fetch factor: live_blocks, live_segments, docs, per-kind
-- counts. NO HISTOGRAMS: the narrowing decision is EXACT, not estimated, and a histogram would be
-- a second, wrong answer to a question that already has an exact one.
-- `docs` is  SELECT count(*) FROM doc WHERE format <> 'owjob'  -- the NO_JOB_DOCS predicate, whose
-- one spelling lives in `omniweave_core.store` and which every site appends verbatim. A job
-- document (one `doc` row per compile job, format = 'owjob') is not a document a user ingested and
-- must never be counted as one. `format` is NOT NULL on `doc`, so the predicate is total and needs
-- no IFNULL, and no index is added for it.
-- ONE WRITER AND A STALENESS RULE: re-derived by the run-final converge pass (`op.converge`) and
-- by `ow index stats`, one transaction per key. STAT_MAX_AGE_NS = 86_400e9; past it, or with a key
-- missing, the over-fetch factor takes its MAXIMUM CLAMP of 64 and records
-- Degradation(kind="stat_stale", fix_command="ow index stats") on the Verdict. A wrong over-fetch
-- factor is a silent recall loss, so staleness fails expensive.

CREATE TABLE migration (                                                                 -- [SOR]
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_ns INTEGER NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('ddl','backfill','rebuild')),
  resumable INTEGER NOT NULL, backfill_done INTEGER NOT NULL DEFAULT 0, backfill_total INTEGER,
  unbackfilled_means TEXT NOT NULL    -- REQUIRED PROSE. `ow doctor` prints it VERBATIM, because a
                                      --   half-backfilled column is a correctness question an
                                      --   operator must answer without reading the migration.
) STRICT;
-- `version INTEGER PRIMARY KEY` is half of why G27(b) asserts the numeric prefixes of
-- schema/migrations/*.sql are exactly 1..N with no duplicate and no gap BEFORE applying them: two
-- branches each adding a 0004 would both insert version 4, and the second raises on every store in
-- the fleet after the first has already committed its DDL. A GAP raises nothing at all, which is
-- why density is asserted separately (11-repo-layout.md section 5.2).
-- A migration whose estimated row-touch exceeds WATCHDOG_MS / 2 MUST set resumable = 1 and run
-- through the `work` queue: codegraph's scar is 79 s of CREATE INDEX against a 60 s watchdog,
-- SIGKILLed AFTER DOING THE WORK, so the next start redid it. Every ADD COLUMN is guarded with
-- PRAGMA table_info, and a NOT NULL column with a default belongs in 0001_init.sql -- verified on
-- 3.45.1, `ALTER TABLE ... ADD COLUMN ... NOT NULL` raises only against a NON-EMPTY table, which
-- is the worst possible distribution of outcomes for a later migration.
