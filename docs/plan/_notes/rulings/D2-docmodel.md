# D2-docmodel — The canonical document model (the L2 pivot)

> **Superseded in part — 2026-09-05, by ADR-6 (`_plan/adr/0006-citation-and-retrieval-surface.md`)
> decision 1.** This ruling is a historical record and its decision text stands as written. One
> printed line has since been overtaken and **must not be implemented as printed**: the
> `block_cite` index under [Concrete shape](#concrete-shape), written here as
> `CREATE UNIQUE INDEX block_cite ON block(doc_ord, gen, cite);`. The index is **gen-free** —
> `UNIQUE(doc_ord, cite)`. `cite`'s grammar is `[<corpus>:]d<doc_ord>#<n>` and carries no
> generation, so a gen-keyed index is not resolvable from the token at all; retirement is carried by
> `block_history.superseded_by` (`OW-M-030` / `OW_CITE_RETIRED`) rather than by a generation column.
> Sole home of the index roster: `_plan/07-store-and-retrieval.md` §3.13; the authoritative DDL is
> `_plan/03-document-model.md` §13.1. Charter §6.1's matching spelling is retired by erratum `E54`.
> Nothing else in this ruling is superseded.

## Decision

omniweave defines its own normative model, **`owdoc`**: a flat, append-only **Block** table with one
strict containment spine (`parent_id` + `ord`) plus a small closed intra-document `rel` table, whose
canonical form is the SQLite corpus file (**`.owstore`**) that L4's indexes also live in — one store,
never a model plus a sync layer — and whose interchange form (**`.owdoc`**) is a lossless,
round-trip-tested projection of that store: a plain ZIP of zstd-framed NDJSON block **Frames** with a
`frames.json` seek index and a pretty-printed `manifest.json`. `DoclingDocument` is an importer and an
export target behind an extra, never a base class. Identity is four fields with four written-down
jobs: **`block_id`** (store-local durable int64 surrogate, the only FK target, never exported and
never shown to a model), **`addr`** (type-free path-like address `p14/3`, the archive's internal
reference and the CLI/URL/round-trip address), **`cite`** (`d7#412`, the only id that may enter a
prompt), and the **`content_digest`/`layout_digest`** pair (change detection and round-trip detection
are different questions and get different hashes). Text is addressed in three named coordinate
systems that the type system refuses to mix — **`OriginSpan`** (a tagged union into the original
container, because a PDF paragraph has no byte range and an OOXML paragraph's stable address is a
child-index path, not a byte range), **`TextSpan`** (chars inside one block's own text),
**`RenderSpan`** (offsets into a hash-pinned view, liftable only through a **`SpanMap`**) — and the
per-block **`quote`** tier plus the per-driver `origin_span` capability are what make serve's
"byte-identical, safe to edit from" claim mechanically true rather than aspirational. Geometry is a
four-corner `Quad` in fixed-point 1/1000 pt, normalized to one frame at the driver boundary. Table
cells are ordinary Blocks; the grid cover map is derived and lazily materialized; no type anywhere has
an `html` field. Re-parse identity is carried by an explicit `rebind` pass that emits a
`RebindReport` and quarantines a low-match re-parse instead of silently rebinding. Drivers push into a
`DocSink` one page per transaction, so a 5,000-page document never exists in memory; page images are
an evictable derived cache keyed by DPI and renderer, rendered after routing, never a model field.

## Spec

**1. Not inheriting `DoclingDocument`.** Verified in-tree: `docling/pyproject.toml:47` pins
`docling-core[chunking] (>=2.73.0,<3.0.0)` and `:50-51` list `torch` and `torchvision` as *base*
dependencies; `uv.lock:1347-1377` shows `docling-core` itself hard-requiring `pandas` and `typer`,
with the `[chunking]` extra adding `transformers` and four tree-sitter grammars; `CHANGELOG.md` holds
168 releases from `v0.2.0` (2024-07-16) to `v2.90.0` (2026-04-17), so a `docling-core` minor can
redefine our public type between two installs. `docs/concepts/docling_document.md:23-41` confirms
JSON-pointer identity (`#/texts/1`) into four parallel type-partitioned lists — a position inside an
identity, which is what `rebind` cannot tolerate. `datamodel/document.py:317` names where the stable
surface really is: *"ensure stable schema via export_to_dict"*. We copy docling's designs and none of
its class. `omniweave-core` depends on `pydantic`, `zstandard` and stdlib `sqlite3`, asserted by a CI
test over the *resolved* closure; `omniweave-docling` is a separately versioned two-way adapter with a
published fidelity matrix.

**2. Shape.** Flat Block table; containment is `parent_id` + `ord`, and `ord` *is* the reading order —
one representation, not a scalar plus a redundant `structure` list kept equal by a validator. Marker's
75%-vs-56% result (`builders/line.py:80-82`) says *do not re-infer order from geometry*; a
driver-written `ord` is stored order and satisfies it. `layer ∈ {body, furniture, note, annotation,
hidden}` is a column, so furniture and notes leave the body reading order without a second tree and
are never deleted (D#5). Reject `ord_path`: its only justification is interactive insertion that does
not exist, and `ORDER BY page, ord` is the range scan. A **closed** relation set lives in L2 —
`caption_of · note_ref · continues · anchor_ref · heading_of · derived_from · supersedes` — because
the parser produces it and the serializer consumes it. Everything cross-document or entity-level is
D7's; L2 never depends on L3.

**3. Identity.** `block_id` is a store-local int64 assigned once; every FK — `mark`, `cell`,
`grid_slot`, `block_asset`, `rel`, index rows, embeddings, annotations — points here and nowhere else.
`addr` is `p{page}/{ord}` (`/r{r}c{c}` for cells), **type-free**, because promoting a paragraph to a
heading must not move it. `cite` is `d{doc_ord}#{n}` — graphrag's rule that a citation be short enough
for a model to emit reliably. `doc_key` is `sha256(normalized source bytes)[:16]`, a per-format
normalizer having first stripped PDF `/ModDate`, OOXML `w:rsid*`, frontmatter and EXIF. Two digests
under one `digest_recipe`:
`content_digest` excludes geometry so a driver upgrade's bbox jitter cannot orphan a document;
`layout_digest` adds page and geometry quantized to whole points, ppt-master's canonicalize-then-hash
applied to a different question. Only stored fields are digest inputs, so a recipe bump is a re-digest
pass, never a re-parse.

**4. Re-parse.** `gen` is a per-document monotonic integer; the prior generation survives until the
next successful parse, so yesterday's citation still resolves and reports `superseded_by`. `ow rebind`
matches in three rules — equal `content_digest` under the same parent carries the `block_id`; equal
`addr` and `kind` with a changed digest carries it and bumps `revision`; otherwise a fresh id and a
`block_history` row — and emits a `RebindReport` with per-page match rates. Below threshold the
generation is **quarantined, not committed**. codegraph measured 4.3% of distinct edges wrong, both
directions, silently, from skipping the equivalent pass.

**5. Text addressing.** `OriginSpan` is a tagged union because there is no single answer:
`bytes(part,start,len,codec)` for flat text; `nodepath(part, child-index path)` for OOXML/ODF —
ppt-master's verified `SourceRefRecord.source_path`, which survives edits to other subtrees where a
byte range into `word/document.xml` does not; `glyphs(page,extractor,start,len)`, marker's
`Span.minimum_position` from pdftext's `char_start_idx` (`schema/text/span.py:24`);
`pixels(page,quad)`; `none`. **Correction to the record:** docling's `charspan` is *not* a page-glyph index —
`readingorder_model.py:418-421` computes `(len(new_item.text)+1, …+len(merged_elem.text))`, an
intra-item range, and every other call site passes `(0, len(text))`. That is `TextSpan`, the space the
systems proposal dropped while believing it had it. `RenderSpan` carries a `view_id`; a serializer
returns `(text, SpanMap)` or declares `spanmap:false`, and such output may never be cited. `quote ∈
{verbatim, normalized, reflowed, reconstructed, synthetic}`; `verbatim` requires an `OriginBytes` span
**and** a retained copy of that part, since an offset without retained bytes is unverifiable. Serve
may claim byte-exactness only for `verbatim`.

**6. Tables.** anydoc's exactly-once grid with cells as ordinary Blocks, so citation-to-cell, per-cell
geometry and per-cell provenance come free (the fix for D#2). `build_grid` is the sole constructor and
**clamps** overlapping spans as anydoc deliberately does (`table.rs:182-186`) — overlapping rowspans
are routine in real HTML and raising fails legitimate input — emitting `OW_TABLE_SPAN_CLAMPED` and
dropping the table's `trust` to `inferred`. The cover map is **derived and lazily materialized**: a
merge-free table answers `slot(r,c)` by arithmetic and stores zero
`grid_slot` rows, so a 4M-cell sheet is 4M ordinary blocks needing no second table model, capped at
`MAX_GRID_SLOTS = 4_000_000`. `recon: (strategy, score)` is stored (marker discards it, D#9);
cross-page tables join by `continues`, and the render merges where the model does not.

**7. Inline formatting.** A sparse `mark(block_id, a, b, kind, value)` table over plain `block.text`,
which is what FTS5 indexes and a citation quotes. Overlaps are representable, so marker's bold+italic
collapse (D#8) is unexpressible and hyphenation is recoverable (D#7). A surrogate `mark_id` is
required: two links may cover one range.

**8. Provenance — four axes, never conflated.** `producer_id` interned into a row carrying the full
reproduction tuple (`model_rev` is an exact SHA; `"main"` is a lint error); `method` per block, which
docling lacks (D#10); `trust ∈ ambiguous|inferred|extracted` as an ordered INTEGER with ambiguous
lowest so `MIN()` over a chunk is the chunk's trust, absent ⇒ ambiguous, migrations only downgrade;
`score` + `score_kind` nullable together, since a layout softmax and a token probability are not
comparable. Plus `origin_operator` verbatim from the runtime design, so a free re-extraction cannot
delete billable LLM rows, and `raw_kind` surviving canonicalization (D#16). Confidence keeps docling's
shape with one correction: **`table_score` is computed from the page's `recon` scores or it is NULL
and excluded from the mean** — per-page `table_score` is never assigned anywhere in docling, so
`standard_pdf_pipeline.py:867`'s `nanmean` runs over an all-NaN list and the published grade is a
three-component mean wearing four.

**9. Streaming and budget.** The unit of memory is the **Frame**: a block-count-bounded run in
`(page, ord)` order, target 8,192 blocks, indexed in `frames.json`. A frame is *not* a page range,
which makes a page holding 400,000 blocks harmless. `Doc` is a handle, every traversal returns an
iterator, and `DocSink.end_page()` commits one transaction so the `work` table's pending rows are the
checkpoint. Arithmetic, because two proposals got it wrong: 5,000 A4 pages at 60–120 blocks/page —
that wide *because cells are blocks* — is **300k–600k blocks**, ~200 MB of store with FTS5, ~45 MB
archived; 10M blocks is 3.3 GB and ~750 MB. Decoded 192-DPI A4 pages are **10.7 MB each**: 43 MB for a
four-page batch, **~53 GB** for all 5,000 — why rendering follows routing.

**10. Schema evolution.** `container_version` (bump ⇒ readers refuse, naming the upgrade command),
`model_version` MAJOR.MINOR (minor additive, major refused), `min_reader`, and `x` with
`x.<vendor>.<key>` namespacing written back sorted. Enum values are member names as strings on the
wire — marker's `BlockTypes(str, Enum)` with `auto()` yields `"1"`, `"2"` (`schema/__init__.py:1-12`)
— and INTEGER FKs in SQLite, taking both wins. Unknown members become `unknown` + `raw_kind`; an
unknown non-`unknown` kind fails closed. Wire keys are short and frozen in an append-only registry CI
diffs. Five gates: `write(read(b)) == b` over hand-authored future archives; every released fixture
still loads; a committed generated `schema.json`; new fields optional; and
`import(export(store)) == store`, which stops store and archive from drifting.

**11. Enforcement.** An invariant with no enforcer is a comment. `Quad.from_driver` and `build_grid`
are sole constructors; `serialize` returns `(str, SpanMap)`; no class may declare an `html`,
`markdown` or `md` field. Limits are anydoc's fixed constants at the read boundary, clamped per tenant
as `min(tenant_cap, MAX_*)`, never widened. `owcheck` runs before sealing and on read by default at
~240 ns/block (~2.4 s at 10M), validating the parent/`ord` bijection, grid exactly-once, `rel`
integrity and verbatim-implies-retained-part; `--no-check` stamps `OW_INTEGRITY_UNCHECKED`. A driver
over-declaring fails the shared testkit: `origin_span='exact'` is proved by
`normalize_k(part_bytes[a:a+len]) == block.text`. Failure is a field — `status` plus `Diag` rows from
a closed, unit-tested registry that serve's absence contract reads.

## Concrete shape

```sql
-- ============================ .owstore — the canonical form ============================
-- One SQLite file per corpus. L4 adds indexes and edge tables ON THESE TABLES; it never
-- adds a second representation of a block.
-- Pragma ORDER is load-bearing: busy_timeout FIRST (codegraph #238).
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA cache_size   = -64000;      -- 64 MB
PRAGMA mmap_size    = 268435456;   -- 256 MB

CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- container_version, model_version, min_reader, digest_recipe, corpus_id, writer_version

-- Generated from the Python enums at migration time; CI asserts parity in both directions.
CREATE TABLE enum_val (domain TEXT NOT NULL, ord INTEGER NOT NULL, name TEXT NOT NULL,
                       PRIMARY KEY (domain, ord)) WITHOUT ROWID;
-- domains: kind, layer, trust, method, quote, page_kind, table_kind, rel_kind, origin_span_kind

CREATE TABLE doc (
  doc_ord         INTEGER PRIMARY KEY,      -- corpus-local; the number inside a `cite`
  doc_key         BLOB    NOT NULL,         -- sha256(NORMALIZED source bytes)[:16]
  source_sha256   BLOB    NOT NULL,         -- sha256 of the RAW bytes, as delivered
  normalizer      TEXT,                     -- NULL => raw bytes were hashed (OW_NORMALIZER_FAILED)
  uri             TEXT    NOT NULL,
  media_type      TEXT    NOT NULL,
  format          TEXT    NOT NULL,
  format_evidence TEXT    NOT NULL,         -- JSON: magic bytes, content probe, OPC root element
  source_bytes    INTEGER NOT NULL,
  gen             INTEGER NOT NULL DEFAULT 1,
  status          TEXT    NOT NULL CHECK(status IN ('ok','partial','failed','skipped')),
  page_count      INTEGER,
  model_version   TEXT    NOT NULL,         -- "1.0"
  declared        TEXT    NOT NULL,         -- Capabilities the driver claims   (JSON)
  achieved        TEXT    NOT NULL,         -- Capabilities actually delivered  (JSON)
  confidence      TEXT    NOT NULL DEFAULT '{}',
  timings_ms      TEXT    NOT NULL DEFAULT '{}',
  x               TEXT    NOT NULL DEFAULT '{}',
  UNIQUE(doc_key, gen)
);

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
  stats       TEXT NOT NULL DEFAULT '{}',-- marker page_stats shape
  PRIMARY KEY (doc_ord, gen, page)
) WITHOUT ROWID;

-- The reproduction tuple as a row, not a string. Shared verbatim with L5's OperatorIdentity.
CREATE TABLE producer (
  producer_id INTEGER PRIMARY KEY,
  operator TEXT NOT NULL, op_version TEXT NOT NULL, code_fingerprint TEXT NOT NULL,
  model_id TEXT, model_rev TEXT,          -- model_rev = exact commit sha; "main" is a lint error
  runtime TEXT, runtime_version TEXT, prompt_fp TEXT, options_digest BLOB NOT NULL,
  -- SQL NULLs are each distinct, so a nullable natural key needs IFNULL sentinels or
  -- INSERT OR IGNORE degenerates to a plain INSERT (codegraph #1034).
  UNIQUE (operator, op_version, code_fingerprint, IFNULL(model_id,''), IFNULL(model_rev,''),
          IFNULL(runtime,''), IFNULL(runtime_version,''), IFNULL(prompt_fp,''), options_digest)
);

CREATE TABLE block (
  block_id   INTEGER PRIMARY KEY,            -- DURABLE surrogate. Every FK points here.
  doc_ord    INTEGER NOT NULL,
  gen        INTEGER NOT NULL,
  page       INTEGER NOT NULL,
  addr       TEXT    NOT NULL,               -- 'p14/3' | 'p14/3/r2c5'  -- TYPE-FREE
  cite       TEXT    NOT NULL,               -- 'd7#412'  -- prompts ONLY
  parent_id  INTEGER REFERENCES block(block_id) ON DELETE CASCADE,
  ord        INTEGER NOT NULL,               -- position among siblings == READING ORDER
  kind       INTEGER NOT NULL,               -- closed vocab, FK into enum_val
  raw_kind   TEXT,                           -- the producer's own label, kept (surya raw_label)
  layer      INTEGER NOT NULL,               -- body|furniture|note|annotation|hidden
  title      TEXT,                           -- NULL on text blocks: a chunk is addressed, not named
  text       TEXT,                           -- PLAIN text, fully resolved. NULL for containers.
  content_digest BLOB NOT NULL,              -- blake3-128, merkle. Geometry is NOT an input.
  layout_digest  BLOB,                       -- NULL when the block has no geometry
  revision   INTEGER NOT NULL DEFAULT 0,
  -- geometry: the stored frame is ALWAYS (topleft, 1/1000 pt, unrotated page)
  quad       BLOB,                           -- 8 x i32 LE, or NULL
  -- OriginSpan: a tagged union. NEVER zero-defaulted; nullable as a whole.
  os_kind    INTEGER NOT NULL,               -- bytes|nodepath|glyphs|pixels|none
  os_part    TEXT,                           -- 'file' | 'word/document.xml' | 'xl/.../sheet1.xml'
  os_a       INTEGER, os_b INTEGER,          -- (start, len) for bytes / glyphs
  os_path    TEXT,                           -- '0.3.1.7' child-index path, for nodepath
  os_extractor TEXT,                         -- glyph-stream identity, e.g. 'pdftext@0.6'
  os_codec   TEXT,                           -- decode policy for bytes; symmetry is an invariant
  -- TextSpan: a char range inside THIS block's own text (docling's real charspan)
  ts_a       INTEGER, ts_b INTEGER,
  -- provenance: four axes
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  method     INTEGER NOT NULL,
  trust      INTEGER NOT NULL,               -- 0=ambiguous 1=inferred 2=extracted (MIN() is useful)
  score      REAL, score_kind TEXT,          -- the SCALE is named, or both are NULL
  quote      INTEGER NOT NULL,               -- verbatim|normalized|reflowed|reconstructed|synthetic
  origin_operator TEXT NOT NULL,             -- OWNERSHIP, not trust (mine-runtime §7.6.1)
  payload    TEXT,                           -- JSON, kind-discriminated (list spec, form field, ...)
  state      INTEGER NOT NULL DEFAULT 0,     -- 0=live 1=tombstone. There is no DELETE.
  x          TEXT    NOT NULL DEFAULT '{}',  -- keys MUST be 'x.<vendor>.<key>'
  FOREIGN KEY (doc_ord, gen, page) REFERENCES page(doc_ord, gen, page) ON DELETE CASCADE,
  CHECK (parent_id IS NULL OR parent_id <> block_id),
  CHECK ((os_a IS NULL) = (os_b IS NULL)),
  CHECK ((ts_a IS NULL) = (ts_b IS NULL)),
  CHECK ((score IS NULL) = (score_kind IS NULL))
);
CREATE UNIQUE INDEX block_addr ON block(doc_ord, gen, addr);
-- SUPERSEDED 2026-09-05 by ADR-6 decision 1. The next line is preserved as this panel ruled it and
-- must NOT be implemented as printed: block_cite is GEN-FREE, `ON block(doc_ord, cite)`. A cite
-- carries no generation, so a gen-keyed index is not resolvable from the token.
CREATE UNIQUE INDEX block_cite ON block(doc_ord, gen, cite);
-- IFNULL sentinel is mandatory: a nullable natural key silently admits duplicates.
CREATE UNIQUE INDEX block_sib  ON block(doc_ord, gen, IFNULL(parent_id,-1), ord);
CREATE INDEX block_read   ON block(doc_ord, gen, page, ord) WHERE state = 0;  -- full render = scan
CREATE INDEX block_parent ON block(parent_id, ord)          WHERE state = 0;
CREATE INDEX block_kind   ON block(doc_ord, gen, kind, page, ord) WHERE state = 0;
CREATE INDEX block_cdig   ON block(doc_ord, content_digest);                  -- rebind
CREATE INDEX block_review ON block(doc_ord, gen, page) WHERE trust < 2 AND state = 0;  -- partial

CREATE TABLE block_history (       -- retirement, instead of tombstones that outlive a generation
  block_id      INTEGER PRIMARY KEY,
  doc_ord       INTEGER NOT NULL,
  retired_gen   INTEGER NOT NULL,
  superseded_by INTEGER,           -- NULL = retired with no defensible successor
  reason        TEXT NOT NULL      -- reparse_resegmented|driver_upgrade|source_deleted|compacted
);

CREATE TABLE rel (                 -- the closed intra-document DAG. Containment is NOT here.
  doc_ord  INTEGER NOT NULL, gen INTEGER NOT NULL,
  src_id   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  dst_id   INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  kind     INTEGER NOT NULL,       -- caption_of|note_ref|continues|anchor_ref|heading_of|
                                   -- derived_from|supersedes
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust    INTEGER NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL,
  x        TEXT NOT NULL DEFAULT '{}',
  -- Identity in the SCHEMA, or INSERT OR IGNORE is a no-op with nothing to conflict on.
  UNIQUE (src_id, dst_id, kind, producer_id)
);
CREATE INDEX rel_dst ON rel(dst_id, kind);

CREATE TABLE mark (                -- sparse inline formatting over block.text
  mark_id  INTEGER PRIMARY KEY,    -- surrogate: two links may cover the same range
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  a INTEGER NOT NULL, b INTEGER NOT NULL,   -- char offsets into block.text
  kind  TEXT NOT NULL,             -- bold|italic|code|link|math|anchor|note_ref|dehyphenated|
                                   -- raw_style|lang|redaction|...
  value TEXT                       -- JSON; NULL for valueless marks
);
CREATE INDEX mark_block ON mark(block_id, a, b);

CREATE TABLE table_meta (
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  n_rows INTEGER NOT NULL, n_cols INTEGER NOT NULL,   -- n_cols = max(row_len); rows may be RAGGED
  row_len TEXT NOT NULL,           -- JSON int array: raggedness is EXPLICIT, never implied
  header_rows INTEGER NOT NULL DEFAULT 0, header_cols INTEGER NOT NULL DEFAULT 0,
  kind INTEGER NOT NULL,           -- data|layout   (a layout table is unwrapped by the SERIALIZER)
  recon_strategy TEXT,             -- native_xml|span_x0|span_center|proj_1|proj_3|proj_10|
                                   -- tableformer|vlm|human
  recon_score REAL,                -- marker's judge score, KEPT (marker computes then discards it)
  has_merges INTEGER NOT NULL DEFAULT 0,   -- 0 => grid_slot is EMPTY and slot(r,c) is arithmetic
  native_part TEXT, native_sha256 BLOB     -- hash-pinned original part => passthrough export
);
CREATE TABLE cell (                -- ORIGIN cells only; a cell IS a block
  block_id INTEGER PRIMARY KEY REFERENCES block(block_id) ON DELETE CASCADE,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,
  r INTEGER NOT NULL, c INTEGER NOT NULL,
  row_span INTEGER NOT NULL DEFAULT 1, col_span INTEGER NOT NULL DEFAULT 1,
  UNIQUE (table_id, r, c)
);
CREATE TABLE grid_slot (           -- DERIVED cover map. Materialized ONLY when has_merges = 1,
  table_id INTEGER NOT NULL REFERENCES table_meta(block_id) ON DELETE CASCADE,   -- capped at
  r INTEGER NOT NULL, c INTEGER NOT NULL,                                        -- MAX_GRID_SLOTS
  origin_id INTEGER NOT NULL REFERENCES cell(block_id) ON DELETE CASCADE,
  PRIMARY KEY (table_id, r, c)
) WITHOUT ROWID;
-- "which cell is above this one":
--   has_merges = 0 -> SELECT block_id  FROM cell      WHERE table_id=?1 AND c=?2 AND r=?3-1;
--   has_merges = 1 -> SELECT origin_id FROM grid_slot WHERE table_id=?1 AND c=?2 AND r=?3-1;

CREATE TABLE part (               -- named byte streams of the original container, hash-pinned
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  path TEXT NOT NULL,             -- 'file' | 'word/document.xml' | 'pdf:page=12/content=0'
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL,
  store_ref TEXT,                 -- cas://ab/cd/<sha256>   NULL => bytes were not retained
  PRIMARY KEY (doc_ord, path)
) WITHOUT ROWID;
-- INVARIANT: quote = 'verbatim' requires os_kind = 'bytes' AND part.store_ref IS NOT NULL.

CREATE TABLE asset (
  asset_id INTEGER PRIMARY KEY,
  doc_ord  INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  origin_part TEXT,               -- anydoc's origin_part, unique in the collection (D#15)
  sha256 BLOB NOT NULL, byte_len INTEGER NOT NULL, width INTEGER, height INTEGER,
  store_ref TEXT NOT NULL,        -- cas://ab/cd/<sha256>   NO INLINE BYTES, EVER
  licence TEXT, licence_url TEXT, spdx TEXT, source_url TEXT, retrieved_at_ns INTEGER,
  UNIQUE (doc_ord, sha256, IFNULL(origin_part,''))
);
CREATE TABLE block_asset (
  block_id INTEGER NOT NULL REFERENCES block(block_id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id) ON DELETE CASCADE,
  role TEXT NOT NULL,             -- image|thumbnail|source_crop|ole|chart_data
  PRIMARY KEY (block_id, asset_id, role)
) WITHOUT ROWID;

-- Page renders are a DERIVED, EVICTABLE cache. Not a model field, by construction.
CREATE TABLE page_render (
  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, page INTEGER NOT NULL,
  dpi INTEGER NOT NULL, renderer TEXT NOT NULL, renderer_version TEXT NOT NULL,
  colorspace TEXT NOT NULL, asset_id INTEGER NOT NULL REFERENCES asset(asset_id),
  last_used_ns INTEGER NOT NULL,
  PRIMARY KEY (doc_ord, gen, page, dpi, renderer, renderer_version, colorspace)
) WITHOUT ROWID;

CREATE TABLE diag (               -- failure is a FIELD, not an exception
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen INTEGER NOT NULL, page INTEGER, block_id INTEGER, part TEXT,
  code TEXT NOT NULL,             -- from the CLOSED registry below; callers branch on this
  severity TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
  component TEXT NOT NULL, message TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
  fatal INTEGER NOT NULL          -- anydoc's is_fatal(): a limit breach is never swallowed
);
CREATE INDEX diag_code ON diag(code);   -- the serve layer's absence contract reads this

-- Lexical channel. External-content: NO second copy of the text.
CREATE VIRTUAL TABLE block_fts USING fts5(
  text, content='block', content_rowid='block_id',
  tokenize='unicode61 remove_diacritics 2');
-- + the three standard AFTER INSERT/DELETE/UPDATE sync triggers. D5 owns the BM25 weights.
```

```python
# ===================== omniweave.owdoc — pydantic + zstandard + sqlite3 =====================
# No torch. No numpy. No PIL. No pandas. No pyarrow. Asserted by test_core_closure.py over the
# RESOLVED dependency graph, not over declared manifests.

# ---- enums: MEMBER NAMES as values on the wire, INTEGER in SQLite via enum_val ----
class Kind(StrEnum):     # 34 members + UNKNOWN (mandatory for forward compatibility)
    DOCUMENT="document"; SECTION="section"; TITLE="title"; HEADING="heading"
    PARAGRAPH="paragraph"; LIST="list"; LIST_ITEM="list_item"; QUOTE="quote"; CODE="code"
    TABLE="table"; TABLE_CELL="table_cell"; FIGURE="figure"; PICTURE="picture"
    CAPTION="caption"; FORMULA="formula"; RULE="rule"; PAGE_HEADER="page_header"
    PAGE_FOOTER="page_footer"; FOOTNOTE="footnote"; ENDNOTE="endnote"
    SPEAKER_NOTE="speaker_note"; COMMENT="comment"; FORM="form"; FORM_FIELD="form_field"
    CHECKBOX="checkbox"; KEY_VALUE="key_value"; TOC="toc"; TOC_ENTRY="toc_entry"
    REFERENCE="reference"; BIBLIOGRAPHY="bibliography"; HANDWRITING="handwriting"
    CHEMICAL="chemical"; DIAGRAM="diagram"; CONTAINER="container"; UNKNOWN="unknown"
class Layer(StrEnum):    BODY="body"; FURNITURE="furniture"; NOTE="note"
                         ANNOTATION="annotation"; HIDDEN="hidden"
class Trust(IntEnum):    AMBIGUOUS=0; INFERRED=1; EXTRACTED=2      # MIN() over a chunk works
class Method(StrEnum):   NATIVE="native"; TEXT_LAYER="text_layer"; NATIVE_XML="native_xml"
                         OCR_PAGE="ocr_page"; OCR_BLOCK="ocr_block"; VLM_PAGE="vlm_page"
                         LLM="llm"; HEURISTIC="heuristic"; ROUNDTRIP="roundtrip"; USER="user"
class Quote(StrEnum):    VERBATIM="verbatim"; NORMALIZED="normalized"; REFLOWED="reflowed"
                         RECONSTRUCTED="reconstructed"; SYNTHETIC="synthetic"
class PageKind(StrEnum): PAGE="page"; SLIDE="slide"; SHEET="sheet"; FRAME="frame"; STREAM="stream"
class RelKind(StrEnum):  CAPTION_OF="caption_of"; NOTE_REF="note_ref"; CONTINUES="continues"
                         ANCHOR_REF="anchor_ref"; HEADING_OF="heading_of"
                         DERIVED_FROM="derived_from"; SUPERSEDES="supersedes"

# ---- identity ----
BlockId = NewType("BlockId", int)   # store-local, durable, FK target. NOT in prompts or archives.
Addr    = NewType("Addr", str)      # 'p14/3' | 'p14/3/r2c5'. TYPE-FREE. Archive references.
Cite    = NewType("Cite", str)      # 'd7#412'. The ONLY id an LLM may emit or receive.
DocKey  = NewType("DocKey", bytes)  # sha256(normalized source bytes)[:16]

# ---- geometry: fixed point, one stored frame, one constructor ----
class Quad(NamedTuple):             # 1/1000 pt, TOPLEFT, unrotated page. i32, never float:
    x0:int; y0:int; x1:int; y1:int  #   a float bbox makes layout_digest libm- and platform-
    x2:int; y2:int; x3:int; y3:int  #   dependent, which silently poisons every cache keyed on it.
    def rect(self) -> tuple[int,int,int,int]: ...      # a VIEW, computed on demand
    @classmethod
    def from_driver(cls, pts: Sequence[tuple[float,float]], *,
                    origin: Literal["topleft","bottomleft"], unit: Literal["pt","px","emu"],
                    page_h: float, dpi: float | None, rotation: int) -> "Quad": ...
    # ^ THE ONLY public constructor. There is no way to build a Quad from bare coordinates,
    #   which is how the normalize-once-at-ingest rule survives five years of contributors.

# ---- the three coordinate systems. Distinct types. No implicit conversion, ever. ----
@dataclass(frozen=True, slots=True)
class OriginBytes:    part: str; start: int; length: int; codec: str   # flat text only
@dataclass(frozen=True, slots=True)
class OriginNodePath: part: str; path: tuple[int, ...]                 # OOXML/ODF (ppt-master)
@dataclass(frozen=True, slots=True)
class OriginGlyphs:   page: int; extractor: str; start: int; length: int   # PDF text layer
@dataclass(frozen=True, slots=True)
class OriginPixels:   page: int; quad: Quad                    # OCR/VLM: the polygon IS the address
@dataclass(frozen=True, slots=True)
class OriginNone:     pass                                     # derived or synthetic
OriginSpan = OriginBytes | OriginNodePath | OriginGlyphs | OriginPixels | OriginNone

@dataclass(frozen=True, slots=True)
class TextSpan:   a: int; b: int                    # chars in THIS block's own .text
@dataclass(frozen=True, slots=True)
class RenderSpan: view_id: str; a: int; b: int      # view_id = 'md/1/7c3f' -> manifest.views[]

class SpanMap(Protocol):            # emitted BY the serializer that produced the view
    view_id: str
    def block_at(self, offset: int) -> tuple[BlockId, TextSpan]: ...
    def offsets_of(self, b: BlockId) -> tuple[int, int]: ...
    def to_text(self, s: RenderSpan) -> list[tuple[BlockId, TextSpan]]: ...

def serialize(scope: "Scope", fmt: Literal["md","gfm","html","text","otsl"], *,
              layers: frozenset[Layer] = frozenset({Layer.BODY}),
              contextualize: bool = False) -> tuple[str, SpanMap]: ...
# There is NO text-only serializer. If you have the text you have the map. A serializer that
# cannot emit one declares `spanmap: false`, and its output MAY NEVER BE CITED.

# ---- the block ----
@dataclass(slots=True)
class Block:
    id: BlockId; addr: Addr; cite: Cite
    doc_ord: int; gen: int; page: int
    parent: BlockId | None; ord: int
    kind: Kind; raw_kind: str | None; layer: Layer; title: str | None
    text: str | None
    content_digest: bytes; layout_digest: bytes | None; revision: int
    quad: Quad | None
    origin: OriginSpan
    span: TextSpan | None
    producer_id: int
    method: Method                  # NO DEFAULT. State it.
    trust: Trust                    # NO DEFAULT. Absent on the wire => AMBIGUOUS, and counted.
    quote: Quote                    # NO DEFAULT.
    score: float | None = None; score_kind: str | None = None
    origin_operator: str = ""       # OWNERSHIP, not trust. Set by the runner from StepResult.
    marks: tuple["Mark", ...] = ()
    tombstoned: bool = False
    x: dict[str, Any] = field(default_factory=dict)   # keys MUST be 'x.<vendor>.<key>'
    # There is no `html`, `markdown` or `md` field anywhere in this package. A build-failing
    # test asserts no model class declares one.

@dataclass(frozen=True, slots=True)
class Mark: a: int; b: int; kind: str; value: Any | None = None

# ---- tables: anydoc's exactly-once grid; cells are ordinary Blocks ----
@dataclass(frozen=True, slots=True)
class Origin:  block: BlockId; r: int; c: int; row_span: int = 1; col_span: int = 1
@dataclass(frozen=True, slots=True)
class Covered: origin_r: int; origin_c: int
Slot = Origin | Covered

class Grid:                         # private ctor. build_grid() is the only way in.
    n_rows: int; n_cols: int; row_len: tuple[int, ...]   # raggedness is EXPLICIT
    header_rows: int; header_cols: int
    kind: Literal["data","layout"]  # a layout table is unwrapped by the SERIALIZER, never here
    recon: tuple[str, float | None] | None                # KEPT (marker computes then discards)
    has_merges: bool                # False => zero grid_slot rows; slot() is arithmetic
    native: tuple[str, bytes] | None                      # (part, sha256) => passthrough export
    def slot(self, r: int, c: int) -> Slot | None: ...    # O(1), resolves to exactly one Origin
    def origin(self, r: int, c: int) -> Origin | None: ...
    def up(self, r, c); def down(self, r, c); def left(self, r, c); def right(self, r, c)
    def top_heading(self, c); def left_heading(self, r)
    # ^ exactly olmOCR-Bench TableTest's relational assertions, answerable in O(1).
    # NOTE: no .html and no .markdown. Those are renders: render_grid(g, reader, fmt).

def build_grid(cells: Sequence["CellDraft"], *, header_rows: int = 0, header_cols: int = 0,
               kind: str = "data", recon: tuple[str, float | None] | None = None,
               diag: Callable[["Diag"], None]) -> Grid:
    """SOLE constructor. Registers covered positions; later placements skip them; overlapping
    spans are CLAMPED to what the origin can actually own (anydoc src/model/table.rs:182-186)
    and every clamp emits Diag(code='OW_TABLE_SPAN_CLAMPED') and forces the table's trust to
    INFERRED. Clamping rather than raising: overlapping rowspans are routine in real HTML and
    refusing them would fail legitimate input. Charges the span area against MAX_EXPANSION
    BEFORE expanding, so a tiny document carrying a huge span cannot force unbounded work."""

# ---- provenance, capabilities, diagnostics ----
@dataclass(frozen=True, slots=True)
class Producer:                     # == L5's OperatorIdentity. One type, two layers.
    operator: str; op_version: str; code_fingerprint: str
    model_id: str | None = None; model_rev: str | None = None    # exact sha; "main" = lint error
    runtime: str | None = None; runtime_version: str | None = None
    prompt_fp: str | None = None; options_digest: bytes = b""

@dataclass(frozen=True, slots=True)
class Capabilities:                 # declared by the driver; `achieved` may be LOWER, never higher
    spatial:       Literal["none","page_bbox","block_bbox","line_bbox","char_bbox"]
    origin_span:   Literal["exact","normalized","none"]   # gates serve's byte-exactness claim
    text_span:     bool                                   # intra-block char offsets
    reading_order: Literal["source","char_stream","learned","model_emitted","raster"]
    sections:      Literal["none","markdown_only","typed_levels","outline_from_source"]
    tables:        Literal["none","flat_html","cells","cells_with_spans"]
    math:          Literal["none","latex","mathml"]
    assets:        Literal["none","refs","bytes"]; asset_origin: bool
    notes:         Literal["none","inline","linked"]
    marks:         bool
    confidence:    Literal["none","document","page","element"]
    furniture:     Literal["destroyed","flagged","separated"]
    round_trip:    Literal["none","text","structure","passthrough"]
    spanmap:       bool
# Over-declaring FAILS the shared testkit: `pip install omniweave-driver-testkit &&
# pytest --driver mydriver` runs ~120 property tests derived from the invariants above.
# origin_span='exact' is proved per driver by normalize_k(part_bytes[a:a+len]) == block.text.
# That test is the only mechanism here that makes a third party's honesty machine-checkable.

@dataclass(frozen=True, slots=True)
class Diag:
    code: str; severity: Literal["error","warning","info"]; component: str; message: str
    page: int | None = None; block: BlockId | None = None; part: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict); fatal: bool = False

class OwError(Exception):           # RAISED. `Diag` is RECORDED. Two names for two things.
    code: str                       # stable machine code, unit-tested (bindings publish it)
    def is_fatal(self) -> bool: ...

# CLOSED Diag / OwError code registry. Append-only; CI diffs it; every variant is name-tested.
# OW_ENCRYPTED             encryption is an OUTCOME, not a parse failure
# OW_NEEDS_OCR             names the PAGES: an error used as a routing signal
# OW_MALFORMED             {part}
# OW_MISSING_PART          {part}
# OW_UNSUPPORTED_FORMAT    {format}
# OW_RESOURCE_LIMIT        {limit, value} — names which knob would need raising; a pricing signal
# OW_TIMEOUT               {stage} -> document status 'partial', never an abort
# OW_DRIVER_UNAVAILABLE    capability probe failed; the plan is pruned with a report
# OW_IO
# OW_TRUNCATED_BY_BUDGET
# OW_NORMALIZER_FAILED     doc_key fell back to raw bytes
# OW_INTEGRITY_UNCHECKED   owcheck was skipped on the bulk path
# OW_ORIGIN_SPAN_DOWNGRADE a driver could not honour its declared origin_span here
# OW_TABLE_SPAN_CLAMPED    {table, r, c}
# OW_TABLE_RECON_LOW       {score}
# OW_FURNITURE_UNCLASSIFIED
# OW_MIXED_SEGMENTATION    two drivers segmented two pages of one document
# OW_VIEW_STALE            a RenderSpan's view_id no longer hashes to its recorded sha256
# OW_SCHEMA_UNKNOWN_KIND   a non-'unknown' kind from the future: fail closed on read

# ---- write side: drivers PUSH; they never build a Document ----
class DocSink(Protocol):
    def begin_doc(self, rec: "DocRecord") -> None: ...
    def begin_page(self, page: "PageRecord") -> None: ...
    def add_block(self, b: "BlockDraft") -> BlockId: ...      # assigns ord/addr/cite; returns id
    def add_marks(self, b: BlockId, marks: Sequence[Mark]) -> None: ...
    def add_grid(self, b: BlockId, g: Grid) -> None: ...
    def add_rel(self, src: BlockId, dst: BlockId, kind: RelKind, *, trust: Trust,
                score: float | None = None) -> None: ...
    def add_asset(self, a: "AssetDraft", blob: BinaryIO) -> int: ...   # streams; never bytes
    def add_part(self, path: str, blob: BinaryIO | None, sha256: bytes, byte_len: int) -> None: ...
    def diag(self, d: Diag) -> None: ...
    def end_page(self, stats: Mapping[str, Any]) -> None: ...  # COMMITS ONE TRANSACTION
    def end_doc(self, status: str) -> "DocRecord": ...

class Driver(Protocol):
    NAME: ClassVar[str]; VERSION: ClassVar[str]
    FORMATS: ClassVar[frozenset[str]]
    CAPABILITIES: ClassVar[Capabilities]
    def sniff(self, head: bytes, path: str | None) -> list[str]: ...   # many-to-one, RANKED
    def parse(self, src: "Source", sink: DocSink, ctx: "DriverCtx",
              pages: range | None = None) -> "ParseReport": ...
# A driver NEVER opens a socket: egress is ctx.fetch (one guarded path) or nothing.
# ctx.limits are anydoc's FIXED constants, clamped per tenant: effective = min(tenant_cap, MAX_*).

# ---- read side: a lazy handle, NOT a loaded object ----
class Doc:
    rec: "DocRecord"; declared: Capabilities; achieved: Capabilities
    def block(self, id: BlockId) -> Block: ...
    def by_addr(self, a: Addr) -> Block | None: ...
    def by_cite(self, c: Cite) -> Block | None: ...
    def blocks(self, *, pages: range | None = None, kinds: Iterable[Kind] | None = None,
               layers: Iterable[Layer] = (Layer.BODY,), under: BlockId | None = None,
               trust_below: Trust | None = None) -> Iterator[Block]: ...  # ITERATOR, never a list
    def frames(self) -> Iterator["Frame"]: ...
    def rels(self, id: BlockId, kind: RelKind | None = None, *,
             inbound: bool = False) -> Iterator["Rel"]: ...
    def grid(self, id: BlockId) -> Grid: ...
    def page_render(self, page: int, dpi: int) -> "AssetRef": ...  # LAZY; renders on miss
    def asset(self, ref: "AssetRef") -> BinaryIO: ...              # a STREAM, never bytes
    def serialize(self, fmt: str, **kw) -> tuple[str, SpanMap]: ...
    def verify_quote(self, id: BlockId) -> "QuoteVerdict": ...
# There is deliberately no `Doc.pages: list[Page]` and no `Doc.blocks: list[Block]`.

QuoteVerdict = Literal["match",              # the stored span equals the current source slice
                       "source_ahead",       # source is newer, the slice still matches -> FINE
                       "mismatch",           # matches neither the digest nor the current source
                       "source_unavailable"] # gone, unreadable, or a stream
# `source_ahead` is jcodemunch's `git_sha_uncommitted` for documents and MUST NOT read as
# corruption. The verdict names what it compared against: {sha256, mtime_ns, part}. Both sides
# decode with the SAME codec and error policy (decode symmetry; jcodemunch #400).

# ---- rebind: re-parse identity, as an explicit pass ----
@dataclass(frozen=True, slots=True)
class RebindReport:
    doc_ord: int; from_gen: int; to_gen: int
    carried: int; revised: int; created: int; retired: int
    match_rate_by_page: Mapping[int, float]
    quarantined: bool; threshold: float
def rebind(store, doc_ord: int, to_gen: int, *, threshold: float = 0.80) -> RebindReport: ...
#  1. equal content_digest under the same parent  -> CARRY the block_id
#  2. equal addr and kind, digest changed         -> CARRY the block_id, revision += 1
#  3. neither -> new block_id; the old one goes to block_history with a reason
# Below `threshold` the new generation is QUARANTINED, not committed. Overrides are named per
# check (`--allow-unexplained-rebind`), never one `--force`.
```

```
# ================== the digest recipe (versioned; digest_recipe = 1) ==================
canonical(x) = JSON with sorted keys, no NaN/Inf, geometry as i32 only, and THREE distinct
               encodings for absent / null / "".

content_digest = blake3_128(canonical([
    kind, layer,
    nfc(text) or None,                            # NFC-normalised; None != ""
    canonical(payload),
    [child.content_digest for child in children in `ord` order],     # merkle
]))

layout_digest  = blake3_128(canonical([           # NULL when quad IS NULL
    content_digest, page,
    quad quantised to WHOLE POINTS,               # kills driver jitter; canonicalise-then-hash
]))

NOT digest inputs: block_id, addr, cite, ord, revision, producer_id, method, trust, quote,
                   score, raw_kind, origin_operator, marks, x, and every span.
  - spans out:    a driver changing byte accounting must not orphan unchanged content.
  - producer out: two drivers producing identical content collide ON PURPOSE.
  - x out:        a third party stamping an annotation must not invalidate every cache entry.
  - marks out:    a formatting-only fix must not re-bill an embedding.
CONSTRAINT: every digest input is a STORED field, so a recipe bump is serviced by a re-digest
            pass, never a re-parse.
```

```
# ============ the .owdoc archive: a plain ZIP. `unzip -l` and `jq` both work. ============
report.owdoc
├── manifest.json          {container_version, model_version, min_reader, digest_recipe,
│                           doc_key, source, status, producers[], parts[], assets[], views[],
│                           declared, achieved, confidence, timings_ms, counts, x}
│                          Pretty-printed. The ONLY mandatory member.
├── frames.json            [{lo_page, lo_ord, hi_page, hi_ord, path, blocks, bytes, sha256}]
├── blocks/000000.ndjson.zst   one FRAME: a block-count-bounded run in (page, ord) order,
├── blocks/000001.ndjson.zst   target 8,192 blocks. A frame is NOT a page range, so a page
│                              with 400,000 blocks is harmless and frames stay uniform.
├── marks/000000.ndjson.zst
├── rels.ndjson.zst
├── grids.ndjson.zst
├── diags.json
├── toc.json
├── parts/word/document.xml    original byte streams, hash-pinned; OPTIONAL (present:false)
├── assets/cas/ab/cd/<sha>.png content-addressed; OPTIONAL, separately deletable/storable
└── views/md-1-7c3f.md         + its sha256 and byte length in manifest.views

RULES
- The archive NEVER contains a `block_id`. Every internal reference — parent, rel endpoints,
  grid origins, mark owners, asset links — is an `addr`. Import assigns fresh `block_id`s.
  This is what makes an archive portable between stores.
- Wire keys are short and FROZEN in an append-only registry CI diffs:
  {i,p,pa,o,k,rk,ly,t,ts,os,q,m,tr,sc,pd,oo,cd,ld,rm,x}. A key is never reused with a
  different meaning. Protobuf's field-number discipline with no toolchain.
- Payload is NDJSON + zstd-3, measured at ~75 B/block against msgpack+zstd's ~72 B/block —
  a 4% penalty for `unzip -p x.owdoc blocks/000063.ndjson.zst | zstd -d | jq`, and for
  keeping a C extension out of the read path. That trade is the adoption argument as a number.
- `load()` is tolerant (docling's ConversionAssets.load): a missing or unparseable member
  yields status=partial plus a Diag; only manifest.json is fatal to omit. A `container_version`
  or `model_version` MAJOR above the reader's is REFUSED, naming the version and the upgrade
  command — silent misreading is the failure an operator cannot detect. There is no --force.
- CI gate: import(export(store)) == store over the fixture corpus. That is what stops the
  canonical store and the interchange archive from drifting apart.
```

```yaml
# ============ a driver capability declaration (required; downstream gates read it) ============
driver: omniweave.drivers.pdfium_pdftext
version: "1.4.0"
capabilities:
  spatial:       line_bbox
  origin_span:   none          # <-- PDF: a paragraph has NO byte range into the original file.
  text_span:     true          #     serve MUST NOT claim byte-exact verbatimness for this driver
  reading_order: char_stream   #     (75% vs 56% — marker/builders/line.py:80-82)
  sections:      typed_levels
  tables:        cells_with_spans
  math:          latex
  assets:        bytes
  asset_origin:  false
  notes:         linked
  marks:         true
  confidence:    element
  furniture:     separated
  round_trip:    structure
  spanmap:       true
```

```
# ============ package and directory layout ============
omniweave/
  owdoc/                 # omniweave-core. pydantic + zstandard + stdlib sqlite3. ~15 MB.
    enums.py  ids.py  geom.py  spans.py  block.py  mark.py  grid.py  asset.py
    producer.py  caps.py  diag.py  limits.py  digest.py
    sink.py  read.py  serialize.py  driver.py  check.py  rebind.py
    archive/    write.py  read.py  manifest.py  frames.py   # the .owdoc codec
    store/      schema.sql  migrations/0001_init.sql  sink.py  reader.py
    schema.json            # GENERATED from the Python types, COMMITTED: diffs show in PRs
  drivers/
    anydoc/      # extra: omniweave[anydoc]      tier 0 office, MIT, ms-scale, NO PDF
    docling/     # extra: omniweave[docling]     PDF/HTML/EPUB/domain XML in, DoclingDocument out
    markitdown/  # extra: omniweave[markitdown]  breadth; quote=reconstructed, trust=inferred
    pdfium/      # tier 1 PDF: pdfium text layer + a permissively licensed layout model
  testkit/       # omniweave-driver-testkit: ~120 property tests; fails over-declaration
  cli/           # ow parse | ow store | ow doc | ow check | ow rebind | ow doctor | ow export
fixtures/
  owdoc/v1/*.owdoc               # one per released version; a CI test loads all of them
  docs/  html-no-pages.html  ragged-table.docx  merged-4m-cell.xlsx  rotated-scan.pdf
         spanned-merged.pptx  msg-email.msg  gen-5000p.pdf   # the RSS + block-count fixture
```

## Rationale

All three architects independently overturned the blueprint's "start from `DoclingDocument`", and the
evidence supports them unanimously and checkably: torch and torchvision are base dependencies
(`pyproject.toml:50-51`); `docling-core` — the package that actually defines the type — hard-requires
`pandas` and `typer` and is pulled with a `[chunking]` extra dragging `transformers` and four
tree-sitter grammars (`uv.lock:1347-1377`); 168 releases in 21 months under a whole-major pin means a
`docling-core` minor can redefine our public type between two installs; and the identity scheme is a
JSON pointer into a positional array, which is the one mistake this model cannot afford. docling's
*designs* are worth a great deal — the ZIP-of-one-JSON-per-component envelope with tolerant load, the
`ConversionStatus` + per-page `ErrorItem` shape, `ContentLayer` as a view rather than a deletion, the
grades-published/scores-internal discipline, `contextualize()` — and all of them are copied. The class
is not.

Beyond that the three proposals diverge, and I picked sides rather than averaging.

*One store, not two.* The pragmatist's strongest argument is that an L2 model plus an L4 index over it
is a sync layer, and a sync layer drifts silently — graphrag's `deleted_inputs`, computed and consumed
nowhere, is the shape of that failure. So the `.owstore` is the model. But the ecosystem architect is
right that an archive is a different artifact with different jobs, so `.owdoc` exists as a *lossless
projection* held to `import(export(store)) == store` in CI. That gate is what makes "one store" true
rather than merely asserted.

*Durable identity beats convenient identity.* Both the pragmatist and the ecosystem architect made a
position-bearing arena id (`p14.b3`, `#p12/37`) the foreign-key target, and both then ran into the
consequence: the pragmatist's `BlockId` is stable "one parse generation" while simultaneously being
the citation and the address; the ecosystem architect's own failure mode 4 admits compaction breaks
every external holder and files it Unresolved. Worse, the ecosystem's `BlockRef` embeds a `DocId` that
is a hash of the source bytes, so fixing one typo in a PDF rebinds every citation in it. The systems
architect is right that a position in an identity is codegraph's measured mistake, and the fix costs
one integer column. So `block_id` is the durable surrogate and `addr`/`cite` do the jobs they are good
at. I took the ecosystem architect's refinement that the *type* must not be in the address, because a
processor promoting a paragraph to a heading must not move it.

*Three coordinate systems, correctly sourced.* The systems architect built the most careful span
algebra and mis-sourced its centre: docling's `charspan` is an intra-item range
(`readingorder_model.py:418-421`), not a page-glyph index, so `GlyphSpan` as specified had no source
and `TextSpan` — the space that actually makes "highlight the exact substring" and L3 entity spans
possible — was missing entirely. The page-glyph space is real but comes from marker/pdftext. Folding
`glyphs` into `OriginSpan` as a variant rather than a peer type is not a compromise: a block has
exactly one address in the original, and which flavour that address takes is a property of the format,
not a second question.

*Where the pragmatist and ecosystem architects were pessimistic or optimistic, I split on measurement.*
The ecosystem architect's per-block byte figures are the only measured numbers in the panel and I use
them; the block count they rest on (60,000 for 5,000 pages, 12 blocks/page) is not credible in a model
where cells are blocks, so "the whole document in RAM is legal at document scale" does not survive and
the streaming API is structural, not optional. The systems architect's JSON estimate (1.2–2.5 KB/node
⇒ 12–25 GB at 10M) is 4–7× above the measured 338 B/block, which is most of why the msgpack case
loses. And the systems architect's own budget table puts 5,000 decoded page renders at 7.5 GB when the
same table's 4-page row implies 53 GB; the pragmatist's 56 GB is the right order and is why rendering
follows routing.

*Two places I ruled against all three.* First, `ord_path`: a gap-allocated order key is an abstraction
with one implementation whose only justification is an editing surface that does not exist. Second,
the grid cover map: making it derived and lazily materialized — zero `grid_slot` rows when a table has
no merges — dissolves the 4M-cell spreadsheet that broke every proposal (the pragmatist's admitted
`dataset` downgrade wart, the ecosystem architect's 320 MB frame, the systems architect's outright
refusal) without a second table model, because the cells were always the data and the cover map was
always an index.

## Rejected

- **Inherit `DoclingDocument`** — the type is defined in `docling-core`, which hard-requires `pandas`
  and `typer` (`uv.lock:1347-1360`) while docling's own base deps are torch and torchvision
  (`pyproject.toml:50-51`); 168 releases in 21 months under a `<3.0.0` pin makes a `docling-core`
  minor a change to our public type; and JSON-pointer identity into four parallel type-partitioned
  arrays puts a position inside an identity, which is exactly what `rebind` must not have. The genuine
  benefit is an ecosystem, and an ecosystem is an *export* problem: a two-way adapter behind an extra
  buys all of it on our own release schedule.
- **A position-bearing id as the foreign-key target** (pragmatist's `BlockId`, ecosystem's
  `BlockRef`), **and its mirror, a content hash as the sole identity** — an ordinal is a position, so
  a re-parse or a compaction rebinds every embedding, edge, annotation and already-shipped citation,
  and both proposals concede it in their own failure modes; ecosystem's `BlockRef` additionally embeds
  a hash of the source bytes, so fixing one typo in a PDF rebinds every citation in it. A content hash
  alone fails from the other side: a 5,000-page report with one running footer collapses to one block,
  and any LLM fixing a ligature orphans every reference. `block_id` plus `cite` plus `content_digest`
  costs one integer column and gives all three properties.
- **Redundant ordering machinery: `ord_path`, and a stored `structure` list beside `parent` + `ord`**
  — `ord_path` has one consumer, one implementation, and a motivating workload (interactive insertion
  into a stored document) that does not exist; `ORDER BY page, ord` over an index is the range scan.
  Storing `structure` as well as the order scalar is two representations of reading order plus a
  bijection validator to hold them equal — the "model plus sync layer" failure one level down. Marker's
  75/56 result says *don't re-infer* order, and a driver-written `ord` already satisfies it.
- **A byte range into the decompressed container part as the OOXML round-trip address** (systems'
  `SourceSpan`) — ppt-master's verified answer is a child-index path
  (`SourceRefRecord.source_path: tuple[int,...]`), stable under edits to other subtrees, where a byte
  offset into `word/document.xml` is destroyed by any attribute reordering on re-serialization. A byte
  range is right for flat text and wrong for containers, and systems' own §6 wants PPTX round-trip.
- **`build_grid` raising on overlapping spans, and a separate bulk `dataset` table kind above 50k
  cells** (pragmatist) — anydoc clamps deliberately (`table.rs:182-186`) because overlapping rowspans
  are routine in hand-written HTML, so raising is fail-closed on *common* input, a different thing
  from fail-closed on adversarial input. The `dataset` downgrade is an admitted wart the lazily
  materialized cover map removes outright: a merge-free 4M-cell sheet is 4M ordinary blocks and zero
  `grid_slot` rows, keeping per-cell provenance and geometry.
- **A Frame that is a page range** (ecosystem) — one page with 400,000 blocks makes frames
  non-uniform, forces the "frames may split within a page" exception its own failure mode 3 calls the
  first thing another language's reader will get wrong, and reintroduces the memory problem for
  exactly the pathological document. A block-count-bounded run removes the exception.
- **Binary and columnar formats in the load-bearing positions, and a schema code generator** —
  msgpack measures ~72 vs NDJSON+zstd's ~75 B/block, a 4% win for which you surrender `jq`,
  `curl | head` and browser-console inspection and add a C extension to core; protobuf additionally
  forces a codegen toolchain on every third-party driver in every language and collapses absent with
  default in three places where "unset" is load-bearing (`score`, spans, `trust`); Parquet is 27%
  smaller and ~2,000× slower to point-read (42.8 ms vs 20 µs) and immutable — graphrag's
  `_copy_previous_output` copies a 50 GB index to add one document. And JSON Schema as the source of
  truth with a generator emitting Python, SQL, msgpack and Parquet maps is a fourth build system with
  one consumer. Parquet ships as `ow export parquet`; `schema.json` is generated from the Python types
  and committed so its diff appears in review.
- **Markdown or HTML as the primary representation, a general DAG or a pure object tree as the shape,
  and safety limits as configuration** — `block.html` + `structure = []` forfeits per-cell polygons,
  spans, raggedness and the reconstruction score in one assignment (D#2), and eleven of the
  collection's parsers hand downstream a string (D#4), which is why nothing needing citation-to-pixel
  or round-trip can be built on their output at all. A DAG costs cycle detection, an ambiguous
  serialization order and an unanswerable "what is the reading order"; a tree of typed objects cannot
  seek to page 4,700 and does not fit at corpus scale. And anydoc's stated reasoning on limits holds:
  a knob that turns off the zip-bomb cap will be turned off.

## Consequences

- **L4 (D5) builds on these tables, not beside them.** Indexes, FTS5 weights, the WAL valve and the
  vector sidecar are additions to the `.owstore`; a second block representation is a schema violation,
  not a design choice. D5 inherits `block_id` as the join key and `diag.code` as the input to the
  absence contract.
- **L3 (D7) may not put containment or intra-document references in its own tables.** The seven `rel`
  kinds are L2's; entity, claim, community and cross-document edges are D7's and key on `block_id`.
  D7 also inherits `trust` and `origin_operator` verbatim and must not invent parallel names.
- **L5 (D6) shares `Producer` with L2 as one type.** The `work` table's unit is
  `(unit_uri, unit_part=page)` for parse and `(unit_uri, unit_part=NULL)` for document-level
  structure, which is what `DocSink.end_page()`'s one-transaction-per-page commit makes true. This
  settles the runtime notes' open question #1.
- **The OUT direction (D9) gets what it needs and owes something back.** `OriginNodePath`,
  `table_meta.native_part/native_sha256`, `layout_digest` and `quote` are exactly the inputs
  ppt-master's four fidelity tiers (`passthrough / cloned_passthrough / patched / rebuilt`) require.
  In exchange, `parse_back()` must write through `DocSink` like any other driver and declare
  `Capabilities` like any other driver.
- **Serve (D10) may claim byte-exactness for a minority of blocks, and must say so.** Most PDF drivers
  will declare `origin_span: none` and their blocks will be `quote='normalized'` or lower. That is a
  visible product limitation, and it is the correct one: shipping the verbatimness paragraph over a
  reflowed PDF paragraph is a lie the agent cannot detect.
- **A permanent adapter burden.** `omniweave-docling` must track two `docling-core` minors and one
  major in CI forever, and users will blame omniweave when upstream breaks.
- **The `x` bag is a deliberate loss of central control.** It is how a contributor ships on Tuesday;
  it is also how two vendors ship `x.acme.reading_order` and `x.beta.reading_order` and nothing
  reconciles them. `ow doctor --extensions` reports key frequency so blessing is data-driven.
- **`rebind` is a required step, not an optimization**, and it can block an upgrade. A driver that
  re-segments paragraphs will trip the quarantine and cost a human a decision. That is the correct
  trade against silent mis-attribution, and it is a real operational cost.
- **Fixed-point geometry quantizes at 1/1000 pt = 0.35 µm.** Irrelevant for documents, wrong for CAD.
  Stated here so nobody re-litigates it in year three.
- **A `digest_recipe` bump invalidates every content-addressed cache in the fleet.** Affordable only
  because digest inputs are restricted to stored fields, so it is a re-digest pass rather than a
  re-parse. Budget it as at most annual.
- **One writer per `.owstore`.** Multi-writer is D6's problem, not the model's; bypassed,
  `busy_timeout` plus the UNIQUE constraints produce loud failures rather than corruption — but they
  do produce failures.
- **Engineering cost, stated: ~9–12 engineer-weeks** for L2 (types, DDL and migrations, `DocSink`,
  archive codec, span algebra, `Quad`, `build_grid`, `owcheck`, `rebind`, the `Diag` registry),
  **+2–3 weeks** for the driver testkit, **+2 weeks** for the docling adapter and its fidelity matrix.
  A first `ow parse deck.pptx -o deck.owdoc && ow doc show deck.owdoc --page 3` lands in week 2 on the
  anydoc driver, before the store exists.

## Risks

- **`quote='verbatim'` is rare and someone will forget to surface it.** The testkit proves a driver's
  `origin_span` declaration, but nothing stops a UI from rendering a `reflowed` block under a
  "byte-identical, safe to edit" heading. The invariant is enforced at the model boundary; the product
  boundary is a review item, which is weaker.
- **The block-count envelope (60–120/page) is an estimate, not a measurement.** Every storage, frame
  and RSS number scales off it. If dense corpora land at 300/page, the 5,000-page fixture's peak RSS
  gate and the 8,192-block frame target both need retuning.
- **A driver upgrade that re-segments paragraphs orphans annotations with no automatic fix.** The
  quarantine converts silent corruption into a blocked upgrade, which is better and still costs a
  human every time.
- **`x` becomes a shadow schema.** In three years something load-bearing will live in
  `x.acme.something` with no validator behind it. Namespacing and frequency reporting slow it; they do
  not stop it.
- **The frozen wire-key registry is only as good as its reviewers.** Reusing a key with a new meaning
  is undetectable by a diff that only sees the new line. The CI diff must be paired with a
  never-remove, never-redefine rule that a human enforces.
- **Clamping table spans hides real damage in aggregate.** `OW_TABLE_SPAN_CLAMPED` plus a trust
  downgrade makes each instance visible, but a corpus with 40,000 clamps reads as forty thousand
  warnings nobody opens.
- **`nodepath` addresses are stable under edits to other subtrees and not under a re-write of the
  containing part.** An OOXML writer that renumbers children invalidates them, and nothing in the
  model detects that except a failed resolve.
- **A single page with millions of blocks still bounds one transaction.** Frames fix streaming and
  archive reads; `DocSink.end_page()` still commits a whole page, so a 4M-cell sheet is one very large
  transaction. A sub-page commit boundary may be forced later, and it complicates the work-table unit.
- **`owcheck` on by default costs ~2.4 s per 10M-block load.** Acceptable, but the `--no-check` bulk
  path means some archives in the wild are unverified; they say so, and someone will ignore it.
- **Two version numbers plus `min_reader` will generate refusals operators consider pedantic**, and a
  demand for `--force` that must be refused — an override whose scope is "skip whatever complained" is
  an off switch, not an override.

## Terminology

- owdoc := omniweave's canonical document model and its normative schema; the type layer every other layer of the framework reads and writes.
- .owstore := the SQLite file holding one corpus. The canonical, mutable form of the model; L4's indexes live in the same file, over the same tables.
- .owdoc := the single-document interchange archive: a plain ZIP of zstd-framed NDJSON Frames plus a pretty-printed manifest.json. A lossless projection of one document's rows out of an .owstore, held to import(export(store)) == store in CI.
- Block := the single node type of the model. A row in `block`. Paragraphs, headings, figures, tables and table cells are all Blocks.
- block_id := INTEGER, store-local, assigned once and never re-derived. The only foreign-key target in the framework. Never appears in a prompt and never appears in a .owdoc archive.
- addr := the type-free path-like address of a Block, `p14/3` or `p14/3/r2c5`. Unique per (doc_ord, gen). The archive's internal reference and the CLI, URL, log and round-trip address. The Block's kind is deliberately not in it.
- cite := the short per-document token `d7#412`. The only identifier that may appear in a prompt or in model output.
- doc_key := sha256 of a document's normalized source bytes, truncated to 16 bytes. Global content identity of a document, computed after a per-format normalizer strips volatile metadata.
- gen := the per-document parse generation, a monotonic integer. The previous generation is retained until the next successful parse.
- content_digest := blake3-128 over (kind, layer, NFC text, kind payload, children's content_digests in ord order). Geometry is deliberately not an input. Used for rebind, dedup and cache keys.
- layout_digest := blake3-128 over (content_digest, page, quad quantized to whole points). NULL when the Block has no geometry. Used for round-trip change detection, which is a different question from content change.
- OriginSpan := the address of a Block in its original container. A tagged union: bytes(part, start, len, codec) | nodepath(part, child-index path) | glyphs(page, extractor, start, len) | pixels(page, quad) | none.
- TextSpan := a character range inside one Block's own `text`. This is what docling's ProvenanceItem.charspan actually is, and it is what makes sub-block bbox attribution and L3 entity spans possible.
- RenderSpan := a character range inside a hash-pinned named view, carrying a view_id of serializer name / version / options digest. Never stored on a Block; produced and consumed at the serializer boundary.
- SpanMap := the lift from RenderSpan back to (block_id, TextSpan), emitted by the serializer that produced that view. A serializer returns (text, SpanMap) or declares spanmap:false, and spanmap:false output may never be cited.
- quote := a Block's quotability tier: verbatim | normalized | reflowed | reconstructed | synthetic. `verbatim` requires an OriginBytes span and a retained content-addressed copy of that part, and is the only tier for which serve may claim byte-exactness.
- Frame := a block-count-bounded run of Blocks in (page, ord) order, target 8,192 blocks, indexed in frames.json. The unit of streaming and of archive seek. Deliberately not a page range.
- Grid := the exactly-once table cover, built only by build_grid. Slots are Origin (a cell Block with its spans) or Covered (pointing at its origin). The cover map is derived and materialized only when the table has merges.
- Mark := a sparse inline annotation over a character range of a Block's text — bold, italic, link, math, anchor, note_ref, dehyphenated, raw_style, lang. Overlapping Marks are representable, which is why formatting cannot be collapsed.
- owcheck := the invariant validator. Runs before an archive is sealed and on read by default, at ~240 ns/block, checking the parent/ord bijection, arena density, grid exactly-once, rel referential integrity and the verbatim-implies-retained-part rule.

## Open questions

- Does the 60–120 blocks/page envelope hold on real dense corpora? — build `fixtures/docs/gen-5000p.pdf` plus ten real 200-page documents (a 10-K, a court filing, a scientific review, a spreadsheet-heavy report), parse them with the tier-0 and tier-1 drivers, and count Blocks per page including cells. The answer retunes the 8,192-block frame target, the peak-RSS gate and every storage projection.
- Will an editing surface ever mutate a stored generation in place, resurrecting the case for a gap-allocated order key? — settled by D9's ruling on whether `parse_back()` and OUT-direction edits write a new `gen` (the assumption here) or patch the current one. If they patch, `ord` rebalancing becomes a hot path and `ord_path` returns.
- Should L3 entity spans live in `mark` or in a separate annotation table? — settled by D7's entity model: if a span carries its own provenance, trust and producer, it is not a Mark and needs its own table with its own `origin_operator`; if it is a pointer with a label, `mark` absorbs it at zero cost.
- Do embedding rows key on `block_id` or on `content_digest`? — LEANN's `passage_id_scheme ∈ {sequential, content_hash}` fork, restated. Settle it by measuring re-embed cost on a real re-parse: run `rebind` over a corpus after a driver upgrade and count how many blocks carry their `block_id` but change their `content_digest`, and vice versa. D5 owns the call.
- Is whole-point quantization coarse enough to absorb driver geometry jitter in `layout_digest`? — run two pdfium versions and two layout-model revisions over the same 500-page fixture and plot the per-corner delta distribution. If the 99th percentile exceeds half a point, the quantum must widen, and widening it is a `digest_recipe` bump.
- Does a T3 (Postgres) tier need a different `block_id` allocation scheme? — a corpus-local sequence does not survive sharding. Settled by D6's distribution ruling; if T3 is in scope for v1, `block_id` becomes a 64-bit composite (shard, sequence) and that must be decided before any FK ships.
- Should `part` bytes be retained by default? — retaining every original part is what makes `quote='verbatim'` verifiable (jcodemunch keeps a full byte-for-byte copy beside its index) and it roughly doubles corpus storage. Settled by measuring the fraction of Blocks that actually achieve `origin_span: exact` across the driver roster: if it is under ~20%, retention becomes opt-in per corpus.
