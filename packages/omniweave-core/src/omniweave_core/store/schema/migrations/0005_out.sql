-- 0005_out.sql -- OUT: the compiled artefact, its units, its assets, its citations, its elements.
--
-- Object assignment: 07-store-and-retrieval.md section 3's migration table, whose 0005 row reads
-- "OUT: artifact, artifact_unit, artifact_asset, artifact_cite, artifact_el -- the DDL is
-- generation's". The DDL is transcribed from charter.md:6071-6155 (the "#### OUT DDL" block) in
-- that block's order; 09-generation.md section 5.4 (artifact_pure), section 5.5 (artifact_unit's
-- reason CHECK), section 7 (artifact_asset) and section 10 (artifact_cite) print the same tables.
-- Naming and order are 11-repo-layout.md:1188: NNNN_<slug>.sql, applied forward-only in numeric
-- order, one transaction each, the transaction the runner's and never this file's.
--
-- 16-roadmap.md section 4's freeze: "P9's artefact tables arrive as one appended file
-- (0005_out.sql), so the v0.1 -> v1.0 upgrade is additive DDL plus passes and never a re-parse".
-- This file adds tables and no column to any earlier table, so it is no SCHEMA minor.
--
-- EVERY REFERENCE IS BACKWARD: producer, doc, block and asset are 0001_init.sql's, and every
-- artifact_* child names artifact, created first below.
--
-- NO PRAGMA BLOCK HERE and NO `migration` ROW: the pragma sequence is 0001_init.sql's, and the
-- migration row is the applier's for every file (0004_runtime.sql states both rules). For this
-- file: cost_class = 'ddl', resumable = 0, unbackfilled_means = "not applicable: 0005 is pure DDL
-- and writes no rows".
--
-- HOUSE STYLE: ASCII only, LF, `--` never an em-dash; the charter's comments kept and cited.

-- [SOR] One compiled artefact generation. OUT24: an edit is ALWAYS a new artifact_gen and a
-- sealed row is never patched. Named artifact_gen, not gen: bare `gen` is the per-document parse
-- generation everywhere in this framework.
CREATE TABLE artifact (
  artifact_id   INTEGER PRIMARY KEY,
  slug          TEXT NOT NULL,
  artifact_gen  INTEGER NOT NULL,
  parent_artifact_gen INTEGER,
  origin        TEXT NOT NULL CHECK(origin IN ('authored','feedback','read_back','rebase')),
  target        TEXT NOT NULL,
  compile_driver TEXT NOT NULL,
  media_type    TEXT NOT NULL,
  path          TEXT NOT NULL,
  sha256        BLOB NOT NULL,
  byte_len      INTEGER NOT NULL,
  part_digest   BLOB NOT NULL,                       -- the `part` determinism digest
  il_digest     BLOB NOT NULL,
  il_store_ref  TEXT NOT NULL,                       -- cas:// THE RETAINED IL BUNDLE
  constructs_digest BLOB NOT NULL,
  ledger_digest BLOB NOT NULL,
  brief_digest  BLOB,
  card_sha256   BLOB NOT NULL,
  toolchain_digest BLOB,
  determinism   TEXT NOT NULL,                       -- the JSON set, as compiled
  gate_status   TEXT NOT NULL,
  delivery      TEXT NOT NULL CHECK(delivery IN ('release','draft')),
  report_sha256 BLOB NOT NULL,
  receipt_sha256 BLOB NOT NULL,
  restriction_bits INTEGER NOT NULL DEFAULT 0,       -- runner-set (INV-16)
  producer_id   INTEGER NOT NULL REFERENCES producer(producer_id),
  degradations  TEXT NOT NULL DEFAULT '[]',
  read_back_doc_ord INTEGER REFERENCES doc(doc_ord), -- THE LOOP IS A FOREIGN KEY
  sealed_at_ns  INTEGER NOT NULL,
  UNIQUE (slug, artifact_gen)
);

-- Identical inputs => identical bytes. slug and delivery are in the key because three cases are
-- "the same six digests, a second row": --accept-manual's draft, a recompile after the gate
-- clears, and one IL compiled under two slugs (09-generation.md section 5.4).
CREATE UNIQUE INDEX artifact_pure ON artifact(
  target, slug, delivery, il_digest, constructs_digest, ledger_digest, card_sha256,
  IFNULL(toolchain_digest, x''));

-- OUT24 made structural: sealed_at_ns is NOT NULL, so every row is sealed the moment it exists,
-- and a sealed row is neither updated nor deleted. gate_status advances on a NEW artifact_gen.
CREATE TRIGGER artifact_sealed_no_update BEFORE UPDATE ON artifact
  WHEN OLD.sealed_at_ns IS NOT NULL
  BEGIN SELECT RAISE(ABORT,'OW-T-511 a sealed artifact row is never patched'); END;
CREATE TRIGGER artifact_sealed_no_delete BEFORE DELETE ON artifact
  WHEN OLD.sealed_at_ns IS NOT NULL
  BEGIN SELECT RAISE(ABORT,'OW-T-511 a sealed artifact row is never deleted'); END;

-- [SOR] One output unit and its outcome. The two outcomes that need an explanation cannot be
-- written without one (09-generation.md section 5.5).
CREATE TABLE artifact_unit (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit        TEXT NOT NULL,
  ord         INTEGER NOT NULL,
  outcome     TEXT NOT NULL CHECK(outcome IN ('native','baked','passthrough','cloned_passthrough',
                                              'patched','rebuilt','manual_required')),
  il_path     TEXT NOT NULL,
  il_sha256   BLOB NOT NULL,                         -- the PER-UNIT retained IL
  nsig        TEXT NOT NULL,                         -- the canonicalized-subtree content anchor
  reason      TEXT,
  CHECK (outcome NOT IN ('manual_required','baked') OR reason IS NOT NULL),
  PRIMARY KEY (artifact_id, unit)
) WITHOUT ROWID;

-- [SOR] THE LEDGER JOIN. L2's asset is unchanged and is the single source of truth.
CREATE TABLE artifact_asset (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  asset_id    INTEGER NOT NULL REFERENCES asset(asset_id),
  slot        TEXT NOT NULL,                         -- 'asset-slot:<sha256>' as in the IL
  role        TEXT NOT NULL,                         -- image|bake|font|video|audio|ole|thumbnail
  units       TEXT NOT NULL,                         -- a JSON array of unit ids
  ratio_variants TEXT NOT NULL DEFAULT '[]',         -- two ratios => THE DECK IS STRETCHING IT
  PRIMARY KEY (artifact_id, asset_id, slot, role)
) WITHOUT ROWID;

-- [SOR] The authoritative citation ledger: which element of which unit cites which block, at the
-- doc_gen the Plan pinned. verbatim is PROVED by OW-T-102, never claimed.
CREATE TABLE artifact_cite (
  artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
  unit        TEXT NOT NULL,
  el          TEXT NOT NULL,
  cite        TEXT NOT NULL,                         -- 'd7#412' (canonical, unqualified)
  block_id    INTEGER REFERENCES block(block_id),    -- NULL => unresolved at build time
  doc_gen     INTEGER NOT NULL,                      -- PINNED: a re-parse cannot re-point a ship
  kind        TEXT NOT NULL CHECK(kind IN ('quote','paraphrase','derived','data')),
  span_a      INTEGER,
  span_b      INTEGER,
  verbatim    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (artifact_id, unit, el, cite)
) WITHOUT ROWID;
-- "which decks quote page 14 of this contract?" -- one indexed query (07 section 3.13).
CREATE INDEX artifact_cite_block ON artifact_cite(block_id);

-- [DER] Written by the host from read_back's x.ow.el values: the IL element address a read_back
-- Block came from.
CREATE TABLE artifact_el (
  artifact_id INTEGER NOT NULL,
  unit        TEXT NOT NULL,
  el          TEXT NOT NULL,
  block_id    INTEGER NOT NULL REFERENCES block(block_id),
  PRIMARY KEY (artifact_id, el)
) WITHOUT ROWID;
