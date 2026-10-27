# D2 — The canonical document model (L2). Proposal from the shipping pragmatist.

**Author prior:** working system a small team can build and maintain; reuse `_collections/` rather
than rewrite it; hostile to abstractions with one implementation and to milestones nine months out.
Every phase below ships something a user runs.

---

## Headline

**Do not inherit `DoclingDocument`. Define `omniweave.model` as a flat, page-partitioned block
table with parent pointers, whose canonical form is the SQLite file the index already lives in —
one store, not a model plus a sync layer — with a streamed ZIP-of-JSONL `.owdoc` as the interchange
format. Docling, anydoc, markitdown and marker become adapters written *against* the model, not
base classes above it. Identity is two ids with two jobs: a short path-like `BlockId` for citation
and addressing, and a `content_key` for cache and cross-generation diff. Phase 0 is two weeks and
ships a CLI.**

The whole design follows from one measured fact: **the model is small and the pixels are enormous.**
A 5,000-page PDF is ~200k blocks ≈ **40 MB of model** and, at 192 DPI, ≈ **56 GB of decoded page
images**. So the model must be cheap to write incrementally and must never own an image.

---

## 1. Why inheriting `DoclingDocument` is a dependency trap

The blueprint says "Start from `DoclingDocument`" (`_index/framework-blueprint.md:127`). Five
specific reasons to overturn it. Note the distinction throughout: **reject inheritance, keep the
ideas, and ship a two-way adapter.**

1. **Nobody on this project has read it.** `mine-parse.md` §A1.11 states plainly:
   "`DoclingDocument` is defined in `docling-core` (**not vendored here**), but the backends pin
   down its API precisely." The mining pass reconstructed the model from docling's *call sites*
   (`doc.add_text` ×60, `doc.add_group` ×21, …). Making our core representation a subclass of a
   class whose source is outside `_collections/` is disqualifying on its own.

2. **The dependency weight is not negotiable away.** `_collections/docling/pyproject.toml:44-77`
   lists `torch (>=2.2.2,<3.0.0)` and `torchvision` in `[project].dependencies` — **base**, not an
   extra. ≈2.5–3.5 GB installed with CUDA wheels. `mine-risk`'s rule — "an L5 orchestration layer
   must never be a dependency of an L1 parser" — applies harder to L2: if the *representation*
   imports docling, `omniweave-core` imports torch and the 250 MB core-install target is dead on
   day one. (You could depend on `docling-core` alone. Then you have taken a class hierarchy from a
   package you cannot read, on a release cadence you do not control, for an *export* benefit — see
   #3.)

3. **The ecosystem claim is an export problem, not an inheritance problem.** "Serializers, chunkers
   and framework integrations already read `DoclingDocument`" is true and worth having.
   `to_docling_document()` is a bounded, testable, ~400-line function behind an extra. Inheritance
   means every field docling adds is a field we must have an opinion about, forever, and every field
   *we* add is either an `x`-bag hack or a fork.

4. **Its identity scheme is structurally wrong for us.** `DoclingDocument` addresses children by
   **JSON pointers** (`#/texts/1`) into four parallel type-partitioned lists (`texts`, `tables`,
   `pictures`, `key_value_items`). That means (a) the id encodes a list index, so inserting into
   `texts` renumbers references — exactly the defect codegraph names ("never put a position inside a
   node id without a position-free logical key", `mine-graph` §3.3); (b) it cannot be a SQLite
   primary key without a parse; (c) it has no notion of a parse generation. And four parallel lists
   by type is the "parallel index-aligned arrays" anti-pattern `mine-out.md` flags in open-slide
   ("silently attaches the wrong script to every page after it"). One block table with a `type`
   column is strictly better in SQL and admits no misalignment.

5. **Its confidence model has a field nobody fills.** `table_score` is never computed and docling
   grades documents `EXCELLENT` on it (`mine-parse` §A1.6, §A1.13). Inheriting a confidence report
   with an uncomputed member is inheriting a lie, and the fix inside an inherited hierarchy is a
   fork of the enum.

**What we take from docling as designs, at zero dependency cost:** `ProvenanceItem.charspan`;
`CoordOrigin` in the *type* with `.to_top_left_origin()`; `ContentLayer` as a *view* not a deletion;
`ConversionStatus{SUCCESS,PARTIAL_SUCCESS,FAILURE,SKIPPED}` + per-page `ErrorItem`; the
`ConversionAssets` ZIP-of-JSON envelope with tolerant `load()`; `chunk()` + `contextualize()` as the
chunker contract; `repeat_table_header` / `omit_header_on_overflow`. Eight borrowed designs, zero
lines of import.

---

## 2. Shape: flat block table with parent pointers (a forest, never a DAG)

**Decision: a flat, page-partitioned block list with `parent_pk` + `ord`. Tree semantics are a
view. There is no DAG.**

- Reading order **is** `ord` among siblings under `parent_pk`. There is no separate position field.
  (docling gets this right — reading order is the `body` tree plus child order — and marker gets it
  right differently, as an ordered `page.structure` list of `BlockId`. Mine normalises marker's
  parallel structure list into the row itself, so the two representations cannot drift.)
- **Why flat, concretely:** a nested JSON tree cannot be streamed, cannot be partially loaded,
  cannot be appended to page-by-page, and cannot be a SQLite table without a shredder. At 5,000
  pages every operation on a tree model is O(document). marker's `PageGroup.children` holds every
  block ever created on a page *including tombstones*, optionally with two PIL images per page —
  correct for a 200-page PDF in one process, structurally impossible at 5,000.
- **Why not a DAG:** the only recurring motive is "a caption belongs to both the figure and the
  section". That is a typed relation (`mark`/edge), not a second parent. A DAG costs cycle
  detection, an ambiguous serialisation order, and an unanswerable "what is the reading order"
  question. Cross-references, citations, figure refs and entity links are **L3 edges** (D7's
  decision) keyed on `BlockId` — they do not belong in the parent graph.
- **Furniture is a column, not a second tree.** docling roots headers/footers under a separate
  `furniture` node. I use `layer ∈ {body, furniture, note, annotation, hidden}`. Suppression is
  `WHERE layer='body'`; nothing is ever deleted (HunyuanOCR's prompt-level deletion of headers is
  Part D loss #5 and is unrecoverable). Notes are blocks with `layer='note'` addressed by a
  `noteref` mark — anydoc's first-class `Note` without a parallel type.
- **Mutation is marker's arena, verbatim in spirit:** slots are append-only, `slot == arena index`,
  replacement is append-new + rewrite `ord` + set `state='tombstone'`. Nothing is deleted, so ids
  stay stable and held references stay valid. This is the right call for a parse tree 30 processors
  mutate, and it is the reason `block_id` can be a citation.

---

## 3. Identity: both, with two distinct jobs

The question was "path-like stable ID, content hash, or both?" **Both, and the split is not a
compromise — the two ids answer different questions and neither can answer the other's.**

| id | form | job | stable across |
|---|---|---|---|
| `doc_ord` | small int, corpus-local | the document id an LLM cites | corpus lifetime |
| `doc_id` | `sha256(normalised source bytes)[:16]` | global identity, cache key | forever |
| `BlockId` | `p{page_ord}.b{slot}` | **address and citation** | one parse generation |
| `content_key` | `sha256(normalise(text))[:16]` (16-byte BLOB) | cache/embedding reuse, generation diff | across re-parses |

- **Citation form:** `[[7#p14.b3]]` — `doc_ord` + `BlockId`. Ten characters, meaningful,
  self-checking, and a model emits it reliably. This satisfies graphrag's rule
  (`short_id` is "*the only id an LLM may cite*", `mine-graph` §1.1) **without a separate
  `short_id`**, because our block id is already short and meaningful — graphrag needed `short_id`
  only because its `id` was a UUID. Full URI form for the serve layer: `ow://{doc_id}#p14.b3`.
- **`content_key` is never a foreign-key target.** Identical boilerplate in 10,000 contracts
  collapses to one key — a *feature* for embedding dedup (LEANN: content-hash passage ids "dedupe
  identical passages for free", `mine-graph` §5.4) and a hazard if anyone treats it as an address.
  Enforced by schema: no FK references `content_key`.
- **`content_key` covers normalised *text only*** — not geometry, not type, not bbox. So a better
  layout model that fixes a polygon costs nothing; a change to block *boundaries* is a genuine miss
  and should be. This is the answer to LEANN's `passage_id_scheme ∈ {sequential, content_hash}`
  fork: carry both, don't choose.
- **`gen`** (generation) is a per-document integer bumped by a re-parse. Default
  `keep_generations=1`: the prior generation is retained until the next successful parse, so a
  citation issued yesterday still resolves and reports `superseded_by`. Cost: 2× storage for the
  document being re-parsed, swept automatically.
- **`page_ord` is the SOURCE page index, never a batch index** (marker's rule). The sink API takes
  `source_page_ord` explicitly; there is no auto-increment. This is the difference between citations
  that survive a `--pages 40-45` partial run and citations that lie.

---

## 4. Addressing the original file vs. a span in reconstructed text

This is the question `jcodemunch` cares about, and the honest answer has three parts.

**(a) `SourceSpan` is a discriminated union, because a paragraph in a PDF has no byte range.**

```
bytes(start, len)                → text-ish originals: md, txt, html, csv, code, json
charstream(page, start, len)     → PDF with a text layer; pdftext's char-stream index
                                   (marker's span.char_start_idx). NOT a byte offset.
part(part_name, child_index_path)→ OOXML/ODF: "word/document.xml" + (0,3,1,7)
pixels(page, bbox)               → OCR/VLM output: there is no source text; the polygon IS the address
none                             → derived or synthetic
```

The `part` variant uses ppt-master's insight (`authoring_roundtrip.py`, `mine-out` §1.6.4): the
source address is a **child-index path `tuple[int,...]`**, not an id and not an XPath — "stable under
edits to *other* subtrees, and cheap to resolve".

**(b) There is no stored offset into reconstructed text. Ever.**

Offsets into a markdown/HTML rendering depend on the serialiser version, so storing them
guarantees silent drift. Instead the serialiser's *return type* forces the map out with the text:

```python
def serialize(scope, fmt) -> tuple[str, SpanMap]     # there is no text-only serializer
```

`SpanMap` answers `block_at(offset) -> (BlockId, TextSpan)` and `offsets_of(BlockId) -> (a,b)`.
A one-line type-level enforcement that kills a whole bug class. `TextSpan` (char offsets into
`block.text`) is the only span we store besides `SourceSpan`, and it is *within* a block.

**(c) `fidelity` is the field that makes serve's verbatimness claim honest.**

`mine-serve.md` §1.6 says "the paragraph asserting verbatimness is load-bearing … if serve says
'byte-identical, safe to Edit from', the pipeline must hand back line-numbered original bytes, not
normalized markdown." So every block carries:

```
fidelity ∈ { verbatim, reflowed, reconstructed, synthetic }
```

`verbatim` **implies** a `SourceSpan` that reproduces the bytes; serve may only make the
byte-identical claim for `verbatim` blocks. `ow doctor --verify-verbatim` re-reads the source and
returns jcodemunch's four-valued answer with the *same codec and error policy on both sides*
(§4.2.1's decode-symmetry rule):

| verdict | meaning |
|---|---|
| `match` | the stored span equals the current source slice |
| `source_ahead` | source mtime is newer, the slice still matches — **nothing is wrong** |
| `mismatch` | matches neither the recorded digest nor the current source — real divergence |
| `source_unavailable` | source gone, unreadable, or a stream |

`source_ahead` is the document analogue of `git_sha_uncommitted`, and it must not read as
corruption. The verdict names *what it compared against* (`compared_to: {sha256, mtime_ns}`).

---

## 5. Tables: cells are blocks; the grid is relational; HTML is a function

A table must (i) round-trip into PPTX, (ii) chunk, (iii) be queried. All three fall out of one
choice: **`TableCell` is a `Block`, and the grid is a relation, not a nested `Vec<Vec<CellSlot>>`.**

- Origin cells only carry `(row, col, row_span, col_span)`. A materialised `table_slot(table_pk,
  row, col) → origin_pk` view holds anydoc's exactly-once invariant. `build_grid(cells)` is the
  **sole** constructor and raises `GridOverlap` (anydoc's `GridBuilder` clamps; I raise and record,
  because a clamp is a silent loss).
- **PPTX round-trip** needs per-cell geometry, per-cell text runs and per-cell provenance. Cells
  being blocks gives all three free — no parallel type, no second confidence field.
- **Chunking** a 40-column table becomes a query: docling's `repeat_table_header=True` is
  `SELECT ... WHERE row < header_rows`, and `omit_header_on_overflow` is a decision the chunker
  makes with the real row widths in hand rather than against a rendered HTML string.
- **Querying** — olmOCR-Bench's relational `TableTest{cell, up/down/left/right, top_heading,
  left_heading}` is one indexed lookup through `table_slot`. "Which cell is above this one" is
  `WHERE table_pk=? AND col=? AND row=?-1`.
- `header_rows`, `header_cols`, `kind ∈ {data, layout, dataset}` (anydoc's `TableKind` plus a third
  — see failure mode #1). Layout tables are unwrapped by the **serialiser**, never the parser.
- `recon_strategy ∈ {span_x0, span_center, proj_1, proj_3, proj_10, vlm, native_xml, tableformer}`
  and `recon_score` — marker computes the judge score `(purity + no_compound + fill + hdr +
  2*one_span)/6`, gates on it, then **discards it** (Part D loss #9). We keep it.
- **There is no `html` field on any type.** marker's digital path sets `block.html` and
  `block.structure = []`, forfeiting per-cell polygons, spans, raggedness and the score in one
  assignment (Part D loss #2). In this schema that is *unexpressible*. CI enforcement: a test that
  fails the build if any model class declares a field named `html`, `markdown` or `md`.

---

## 6. Inline formatting: a sparse `mark` table, not a nested `Inline` enum

`block.text` is **plain text — the truth.** Formatting, links, math, anchors, note refs and raw
style live in `mark(block_pk, start, end, kind, value)`.

- Plain text is what FTS5 indexes, what an embedder embeds, what a citation quotes. Recovering it
  from a nested inline tree is 15 lines every consumer must get right; anydoc ships
  `inlines_to_plain_text()` precisely because of this.
- **Overlaps are representable**, so marker's Part D loss #8 (`Span.assemble_html`'s `elif` chain
  turning bold+italic into italic) is structurally impossible.
- **Hyphenation is recoverable.** marker does `text.replace("-\n","")` and loses it forever (loss
  #7). We store the joined text plus `mark(kind='dehyphenated', start, end)`, so the original line
  break is reconstructible at zero storage cost for the 99% of blocks with none.
- **Math is LaTeX without delimiters** at both levels (anydoc's rule): inline as
  `mark(kind='math')`, display as a `Formula` block with `latex`. Delimiters are a rendering choice.
- Cost: ~0.5 marks per block average ⇒ 5M rows at ~30 B = **150 MB at 10M blocks**. A nested
  representation pays on every block; this pays only where there is formatting.

---

## 7. Provenance, confidence, and the two-axis rule

Two orthogonal axes, never conflated (`mine-graph` §2.2 vs codegraph §3.1; `mine-runtime` §7.6.1
says explicitly that trust and ownership "are different axes and must not be conflated"):

```
producer_id → producer(name, schema_version, code_fingerprint, model_id, prompt_fp)
              WHICH MECHANISM made this.  Interned ⇒ 2 bytes per block.
              This tuple IS the runtime's OperatorIdentity — L2 and L5 share one type.

trust  ∈ {AMBIGUOUS=0, INFERRED=1, EXTRACTED=2}    HOW MUCH TO BELIEVE IT
score  ∈ float | None                              the producer's own number, kept
fidelity, extraction                               see §4(c) and below
```

- **Missing `trust` reads as AMBIGUOUS (0), not EXTRACTED.** graphify's own `default="EXTRACTED"`
  is the bug the notes tell us to fix. The column is `NOT NULL`, the Python field has **no
  default**, and the loader maps absent → AMBIGUOUS while incrementing a counter surfaced in the run
  manifest. Migrations may only **downgrade** — "alias recovery is not provenance".
- The integers are **ordered with AMBIGUOUS lowest** so `MIN(trust)` over a chunk's blocks is the
  chunk's trust. Free, and it is what makes a chunk-level annotation cheap.
- **Three named consumers each, or the field rots into decoration** (an explicit trap in
  `mine-graph`):
  - `trust` → (1) retrieval ranking and the verdict envelope, (2) the per-item annotation in the
    serve response, (3) the OUT validator refusing to compile an `AMBIGUOUS` numeric into a chart.
  - `fidelity` → (1) serve's "safe to Edit from" claim, (2) `parse_back`'s four-tier fidelity
    classification (`passthrough/cloned_passthrough/patched/rebuilt`), (3) citation UI choosing
    highlight-the-substring vs. paraphrase.
- `extraction ∈ {text_layer, native_xml, ocr_page, ocr_block, vlm_page, heuristic, llm, roundtrip}`
  — marker's `text_extraction_method` generalised, per block **and** per page. docling has no
  per-element equivalent (Part D loss #10).
- `raw_type` keeps the producer's own label string after canonicalisation (surya keeps `raw_label`,
  marker discards it — Part D loss #16).
- **Driver capability declaration** (`mine-parse` E11): each driver declares
  `CAPABILITIES: frozenset[Cap]` over `{bbox, charspan, cell_identity, notes, speaker_notes,
  tracked_changes, marks, verbatim_bytes}`. `Page.segmentation → producer → caps` lets a consumer
  distinguish **"this field is absent because the driver cannot produce it"** from **"absent because
  the document does not contain it."** That distinction is currently unavailable in every repo here
  and it costs one interned column.

---

## 8. Assets: never inline bytes

```
Asset { asset_id, doc_ord, media_type, origin_part, sha256, size, width, height,
        store_ref, licence, licence_url, source_url, retrieved_at }
```

- `origin_part` is anydoc's idea and it is unique in the collection (Part D loss #15) — provenance
  for a binary blob at ~20 bytes.
- **`Asset` has no `bytes` field.** Type-enforced. anydoc's inline `bytes: Vec<u8>` is right for a
  one-shot Rust function and wrong for a framework: with `MAX_ASSET_TOTAL_BYTES = 128 MiB`
  (`anydoc/src/package/limits.rs:38`) anydoc structurally cannot hold a 5,000-page scan's images.
  `store_ref` points at `blobs/<sha[0:2]>/<sha256>`, content-addressed, so N documents embedding the
  same logo store it once.
- The four licence fields turn hyperframes' media ledger into a compliance control at near-zero
  cost, and the OUT pipeline refuses to embed an asset with an unknown licence.
- **Page images are not assets.** They are a *derived cache* keyed `(doc_id, gen, page_ord, dpi)`,
  produced on miss by `ctx.blobs.page_image(...)`, and **evictable**. marker's per-page
  `_highres_loader` (non-persistent lazy loader) is the pattern; make it a store-level function so
  a late consumer (a citation renderer, a table VLM crop) can ask for page 4,312 at 192 DPI without
  the parse having kept it. Render **after** the routing decision and only for pages that need it —
  marker calls this the cheapest optimisation in its repo.

---

## 9. Serialisation and the 10M-block cost

**Canonical form: SQLite — the same file the L4 index lives in. Interchange: `.owdoc`, a ZIP of
JSONL, one member per page.**

The pragmatist's key move: the blueprint implies an L2 document model *and then* an L4 SQLite index
"over it". Two representations means a sync layer, and the sync layer will drift — silently, the way
graphrag's `deleted_inputs` is "computed and consumed nowhere". **One store. The document model is
the schema.** The L2 API is a lazy handle over it; D5 designs the indexes and the WAL valve on top
of the same tables.

### Measured / calculated costs at 10M blocks

Per-row structural cost: `block_id` 10 B + 5 small ints ~10 B + type/layer/trust/fidelity/extraction
(interned ints) ~8 B + 4 REAL bbox 32 B + `content_key` 16 B + row overhead ~25 B ≈ **~120 B**.
Text at ~170 chars/block average (a prose page ≈ 2,500 chars in ~15 blocks).

| representation | 10M blocks on disk | point lookup by id | one page read | append 200k blocks | greppable |
|---|---|---|---|---|---|
| **SQLite (chosen)** | **~3.6 GB** (1.2 struct + 1.7 text + ~0.7 FTS5) | ~0.05 ms | ~0.4 ms | 3–6 s | via `sqlite3` / `ow doc show` |
| `.owdoc` ZIP-of-JSONL | ~4.5 GB raw / **~0.9 GB deflated** | O(page) after manifest | ~1 ms | rewrite one member | **yes** |
| one JSON tree per doc | ~5 GB raw | parse whole doc | parse whole doc | rewrite file | nominally |
| msgpack | ~3 GB raw / ~0.85 GB deflated | as JSONL | as JSONL | as JSONL | no |
| Arrow/Parquet | ~1.1 GB | ~10 ms (row-group scan) | ~5 ms | **rewrite partition** | no |
| protobuf | ~2.6 GB raw | needs a side index | needs a side index | appendable | no |

Independent calibration: codegraph measured 2,000,000 symbols + 6,400,000 relationships indexed in
under 12 minutes on a 2-core 6 GB VPS, and `mine-graph` §3.8 projects 10M blocks at a 10–40 GB
SQLite file *including edges*. My 3.6 GB excludes edges (D5's). 224k edge inserts took 2.8 s (1.1 s
with indexes dropped), which is what calibrates the 3–6 s append.

### Rejections, with the receipt

- **Parquet/Arrow as primary: rejected.** Best on size, worst on the operations we perform — point
  lookup by block id, tree walk, per-page mutation during parse, incremental append. Parquet has no
  update. The measured tax: graphrag stores its index as Parquet and `_copy_previous_output` is *a
  full physical copy of the whole index per update* — adding one document to a 50 GB index copies
  50 GB (`mine-runtime` §2.7). That is not an implementation flaw; it is what an immutable columnar
  file forces. Keep Arrow/Parquet as an **export** for analytics (`ow store export --parquet`).
- **protobuf as primary: rejected.** Buys a compact wire and forward-compat; costs a schema
  compiler, a codegen build step, and readability. I get forward-compat from JSONL + an explicit
  unknown-field bag + a version pair (§10), and readability is how a two-person team actually
  debugs a parse at 3 a.m.
- **msgpack as primary: rejected on arithmetic.** ~35% smaller raw, but **after deflate the gap is
  under 20%** because our payload is mostly natural-language text. jcodemunch's MUNCH measured
  39–55% savings on *row-shaped* results and **0% on verbatim text** — and our archive is verbatim
  text. Offer msgpack as an optional *transport* encoding at the MCP/HTTP boundary (D10's call), not
  as the archive.
- **A tree of Pydantic models in memory as primary: rejected.** See §2.

### `.owdoc` layout

```
report.owdoc                     (ZIP)
  manifest.json                  schema_version, min_reader_version, doc record, status,
                                 errors[], confidence, producers[], timings{}, degradations[]
  pages/000014.jsonl             one JSON object per line: {"k":"block",...} then "mark", "cell"
  pages/000015.jsonl
  assets/index.jsonl
  blobs/ab/abcdef…               optional; a "thin" export references an external blob store
```

Streamed both directions: writing a 5,000-page document never holds more than one page in memory,
and reading page 4,312 seeks one ZIP member. `load()` is **tolerant** — a missing or unparseable
page member yields `status=partial` plus an `ErrorItem` for that page and the rest loads. That is
docling's `ConversionAssets.save()/load()` envelope, refined from ZIP-of-JSON to
ZIP-of-JSONL-per-page so a 5,000-page document does not need one 40 MB JSON parse.

---

## 10. Schema evolution and forward compatibility

Two integers, one bag, four CI gates.

```
schema_version    : int   what wrote this file. Monotonic int, NOT semver (semver invites debate).
min_reader_version: int   refuse to load below this.
x                 : dict  per-node extension bag; unknown keys land here and are WRITTEN BACK.
```

- **Additive-only by default.** Adding an optional field or an enum member bumps `schema_version`
  and leaves `min_reader_version` alone. An old reader loads a new file, round-trips the unknown
  fields through `x`, and loses nothing.
- **A semantic change bumps `min_reader_version`** and CI requires a migration function plus a
  fixture pair (`before.owdoc`, `after.owdoc`).
- **Unknown enum members never crash.** An unrecognised block type becomes `BlockType.UNKNOWN` with
  the original string in `raw_type`. Same for `extraction` and `mark.kind`.
- **Enum values are strings on the wire, integers in SQLite.** marker's `BlockTypes(str, Enum)`
  with `auto()` yields *values* `"1"`, `"2"`, … (verified: `marker/marker/schema/__init__.py:1-6`)
  so any serialiser writing `.value` emits garbage. Our wire form always writes the member name; the
  SQLite column is an INTEGER FK into a `block_type(type_id, name)` table generated from the Python
  enum at migration time — 10 MB instead of 140 MB at 10M blocks — with a CI test asserting the
  round-trip. Both lessons satisfied, neither paid for.
- **The `x` bag is policed**, because otherwise it becomes a second untyped schema: keys must be
  namespaced `x.<vendor>.<key>` (CI fails on an unnamespaced key), and a lint fails if any `x` key
  appears in >20% of blocks in the fixture corpus — that means it should be a real field.

**The four CI gates:**

| gate | mechanism |
|---|---|
| Round-trip preserves unknowns | property test `load(save(load(b))) == load(b)` over fixtures containing future fields |
| Every released version still loads | `fixtures/owdoc/v{n}/*.owdoc`, test parameterised over the directory; a new version without a fixture fails the build |
| Schema changes are visible in review | `schema.json` (JSON Schema 2020-12) generated from the Pydantic models and **committed**; a PR diff shows the change |
| New fields are optional | test asserting every field added since the last tag is `Optional` or has a default |

---

## 11. Memory and streaming for a 5,000-page document

**The numbers first.** 5,000 pages × ~15–40 blocks/page = **75k–200k blocks**. Text ≈ 5,000 ×
2,500 chars = **12.5 MB**. Structural ≈ 200k × 120 B = **24 MB**. Marks ≈ 100k × 30 B = 3 MB.
**The entire parsed document is ~40 MB of model.** Decoded page images at 192 DPI are
~1700 × 2200 × 3 = **11 MB per page ⇒ 56 GB** for the document.

Therefore the design:

1. **Drivers push into a sink; they never build a `Document`.**

   ```python
   class DocSink(Protocol):
       def begin_doc(self, rec: DocRecord) -> None: ...
       def begin_page(self, page: PageRecord) -> None: ...
       def add_block(self, b: BlockDraft) -> BlockId: ...      # returns the assigned slot
       def add_marks(self, bid: BlockId, marks: Sequence[Mark]) -> None: ...
       def add_asset(self, a: AssetDraft, blob: BinaryIO) -> AssetId: ...
       def end_page(self, stats: PageStats) -> None: ...        # commits ONE transaction
       def error(self, e: ErrorItem) -> None: ...
       def end_doc(self, status: Status) -> DocRecord: ...
   ```

   `end_page()` commits one transaction. Crash recovery is the runtime's `work` table: the pending
   `(doc_id, page_ord)` rows *are* the checkpoint (`mine-runtime` §7.4) — there is no checkpoint
   file, and this settles the runtime's **open question #1**: **the parse unit is
   `(unit_uri, unit_part=page_ord)`; the structure unit is `(unit_uri, unit_part=NULL)`.** Mixed
   granularity is expressible because `page` rows and document-level rows carry separate
   `producer_id`s and the shrink guard is per-unit.

2. **Reads are lazy by default.** There is no `Document.pages: list[Page]` field. `Doc` is a handle:

   ```python
   doc = store.doc(7)                     # 1 row
   doc.page(14).blocks()                  # 1 indexed query, ~0.4 ms
   for b in doc.blocks(layer=Layer.BODY): # generator, page-batched, bounded memory
   text, spans = doc.serialize("md", pages=range(10, 20))
   ```

   Peak Python heap for the model layer on a 5,000-page parse stays **under 200 MB**; the images
   dominate and are bounded by the page batch (docling's `page_batch_size=4`).

3. **Ingest limits are fixed constants, adopted verbatim from
   `anydoc/src/package/limits.rs`** (verified): `MAX_ENTRY_BYTES` 128 MiB, `MAX_TOTAL_BYTES`
   512 MiB, `MAX_ENTRY_COUNT` 100_000, `MAX_XML_DEPTH` 256, `MAX_XML_NODES` 2_000_000,
   `MAX_GRID_SLOTS` 4_000_000, `MAX_EXPANSION` 4_000_000, `MAX_EXPANSION_TEXT_BYTES` 64 MiB,
   `MAX_ASSET_TOTAL_BYTES` 128 MiB, `MAX_RECORD_DEPTH` 64, `MAX_RECORDS` 16_000_000. Enforced at the
   read boundary with `take(N+1)`-then-check so the bomb is never allocated. Per-tenant caps clamp
   *below* these, never above: `effective = min(tenant_cap, MAX_*)`.

4. **No page limit and no file-size limit by default is the anti-pattern.** docling's
   `DocumentLimits.max_num_pages = sys.maxsize`. Our defaults are fail-closed
   (`max_pages=2000`, `max_bytes=256 MiB`) with an explicit widening call, and the limit hit is a
   typed `ResourceLimit{limit, detail}` naming which knob would need raising — anydoc's shape.

---

## 12. Invariants and how each is enforced

| # | invariant | enforced by |
|---|---|---|
| I1 | Every block has exactly one parent; the parent graph is a forest rooted at pages. | SQLite FK `parent_pk REFERENCES block(block_pk) ON DELETE CASCADE` + `ow doctor` cycle check + constructors that only append |
| I2 | `(doc_ord, gen, page_ord, slot)` unique; slots append-only; removal is `state='tombstone'`. | `CREATE UNIQUE INDEX block_ident`; the writer API exposes `tombstone()` and no delete; a semgrep rule bans `DELETE FROM block` outside the sweeper |
| I3 | Every stored bbox is TOPLEFT, points. | `Bbox` has no public coordinate constructor — only `Bbox.topleft_pt(...)` and `Bbox.convert(origin, page_height_pt, unit)`; runtime assert on write; property test over BOTTOMLEFT fixtures |
| I4 | Enum values are member names on the wire; INTEGER in SQLite. | test that `json.loads(save(doc))` contains no numeric type codes; test that every enum member has a `block_type` row |
| I5 | No block stores rendered markup. | build-failing test: no model class may declare a field named `html`, `markdown`, `md` |
| I6 | A table's grid resolves exactly once per `(row,col)`. | `build_grid()` is the sole constructor and raises `GridOverlap`; `ow doctor` re-runs it over the whole store; fixtures for ragged, spanned, overlapping |
| I7 | Absent `trust` reads as AMBIGUOUS; migrations may only downgrade. | column `NOT NULL`; Python field has **no default**; loader counts the substitution into the run manifest; a migration test asserts monotone non-increase |
| I8 | `fidelity=verbatim` ⇒ the `SourceSpan` reproduces the bytes. | writer check; `ow doctor --verify-verbatim` with the four-valued verdict and symmetric decode |
| I9 | You cannot get serialised text without its `SpanMap`. | the return type `tuple[str, SpanMap]`; there is no other serialiser |
| I10 | Unknown fields survive a round trip. | property test `load(save(load(b))) == load(b)` |
| I11 | Every released schema version still loads. | CI test parameterised over `fixtures/owdoc/v*/` |
| I12 | Assets are never inline bytes in the model. | the `Asset` type has no `bytes` field |
| I13 | `omniweave.model` imports no tensor library and no imaging library. | import test: `import omniweave.model` with `torch`, `PIL`, `numpy` blocked in `sys.modules` must succeed |
| I14 | `page_ord` is the source page index. | the sink takes `source_page_ord` explicitly; test on a `--pages 40-45` slice asserting ords 40..45 |
| I15 | `content_key` is never a foreign-key target. | schema review + a test that no FK column references `content_key` |
| I16 | Every `x` key is `x.<vendor>.<key>` and appears in ≤20% of fixture blocks. | lint |

---

## 13. Build order — every phase ships a command a user runs

| phase | weeks | contents | the command a user runs |
|---|---|---|---|
| **P0** | 1–2 | `omniweave.model` (~700 LOC Pydantic), `.owdoc` reader/writer, `DocSink`, `ow.adapters.anydoc` | `ow parse deck.pptx -o deck.owdoc && ow doc show deck.owdoc --page 3` — a millisecond office parser with an inspectable model |
| **P1** | 3–5 | SQLite schema + numbered migrations + `ow store add`; `ow.adapters.docling` behind an extra (PDF, HTML, USPTO/JATS/XBRL); FTS5 | `ow store add ./corpus && ow find "termination for convenience" --cite` — citations resolve to `[[7#p14.b3]]` |
| **P2** | 6–8 | tables (`build_grid`, `table_slot`, `ow doctor`), marks, notes/furniture, page stats, `verify-verbatim` | `ow doc table 7#p14.b3 --format csv\|html\|pptx-fragment` — the round-trip probe |
| **P3** | 9–11 | own PDF driver (pdfium text layer + a permissively-licensed layout model; olmocr as the VLM escalation tier — Apache-2.0 **code and weights**), per-page routing metadata | `ow parse scan.pdf --explain` prints the branch taken per page |

~11 weeks, 1.5 engineers, to a document model + store + three drivers + tables. Nothing is nine
months out. P0 is standalone-useful without a database.

### What we reuse instead of writing (the adapter roster)

| adapter | licence status | what it buys | on the default path? |
|---|---|---|---|
| `ow.adapters.anydoc` | MIT, Rust + Python/Node/WASM bindings | tier-0 office decode in single-digit ms, no Python deps. **Caveat verified:** `to_document` is unsupported for PDF (`anydoc/src/lib.rs`), so anydoc is office-only for us | **yes**, tier 0 |
| `ow.adapters.docling` | MIT code; pulls torch as a **base** dep, so it lives behind an extra | PDF, HTML, EPUB, and the domain XMLs nobody else does; plus `to_docling_document()` for the export ecosystem | yes, behind `pip install omniweave[docling]` |
| `ow.adapters.markitdown` | MIT, **core only** — never `markitdown-ocr`, which hard-requires AGPL PyMuPDF (`markitdown/packages/markitdown-ocr/pyproject.toml:31`) | breadth: `.msg`, RSS, YouTube, Wikipedia, ipynb. Hands back a string, so its blocks are `fidelity=reconstructed`, `trust=INFERRED` — **lossy-by-construction, and the model says so** | yes, breadth tier |
| `ow.adapters.marker` | code Apache-2.0; **weights vetoed** by `MODEL_LICENSE` clause 2(c) *and* clause 8's viral-on-Output term | we reimplement its *algorithms* (LineBuilder routing, the table judge, arena mechanics) clean-room; the adapter reads a marker `Document` only if the user already runs marker under weights they are licensed for | no |

`ow.adapters.docling` is bidirectional, which is the whole reuse answer: we get docling's readers
*and* its serializer/chunker ecosystem without inheriting its class hierarchy.

### Cost, stated plainly

- **Engineering:** ~11 weeks / 1.5 engineers to P3. The inherit-DoclingDocument alternative looks
  three weeks faster and then costs a fork the first time we need a field docling will not add.
- **Runtime:** 200k inserts for a 5,000-page document, batched 5k/transaction at
  `synchronous=NORMAL` ⇒ 3–6 s on SSD. One page read <1 ms. `content_key` hashing adds ~1 µs/block.
- **Memory:** model layer <200 MB peak on 5,000 pages; images bounded by the page batch.
- **Dependency weight:** `omniweave-core` = `pydantic` + stdlib `sqlite3` + `orjson`. **≈15 MB
  installed.** Every driver is an extra. This is the number the 250 MB Lambda-layer target needs.
- **Operational:** one SQLite file per corpus plus a `blobs/` directory. Backup is `cp`. No service,
  no daemon, no migration server.

---

## 14. Failure modes — including the input that breaks it

1. **A 200k-row spreadsheet.** 200k × 20 = 4M cells, each a block, in one Table. That lands exactly
   at anydoc's `MAX_GRID_SLOTS = 4_000_000`, and one document becomes 40% of a mid-size corpus. My
   model does **not** degrade gracefully. Admitted mitigation and admitted wart: a third
   `TableKind.dataset` above a 50k-cell threshold, where cells become rows in a `cell_bulk` table
   with **no per-cell provenance and no bbox** — a documented, reported fidelity drop
   (`ErrorItem{code="table_bulk_downgrade"}`), not a silent one. I would rather ship the wart than
   claim a uniform model I cannot afford.
2. **A document with no pages** — HTML, email, a chat log. `page_ord` is mandatory in the identity
   scheme, so these get `page_ord=0`, `page_kind='stream'`, `width_pt/height_pt = NULL`, and every
   bbox NULL. Any consumer that assumed a bbox breaks. Control: an HTML and an `.msg` fixture must
   pass every invariant in CI, and `Bbox | None` is the declared type everywhere.
3. **Re-parse churn on a layout upgrade.** `content_key` is stable only if block *boundaries* are.
   A better layout model that merges two paragraphs changes both keys, so the embedding cache misses
   for that page even though the text is identical. Keying on normalised text only (not geometry)
   makes geometry-only improvements free, but a boundary change is a real miss and will surprise
   someone the first time a model bump re-bills embeddings for 3% of a corpus.
4. **PPTX text-run fidelity.** An OOXML run carries font, size, colour, spacing, language and a
   dozen more properties. Modelling all of it as typed marks means a huge vocabulary; I instead
   allow `mark(kind='raw_style', value={'ooxml': '<a:rPr …/>'})` — an opaque blob. If a rebuild
   drops the blob, the block's `fidelity` drops to `reflowed`, which is what lets `parse_back`
   classify the page as `patched` rather than `rebuilt`. Ugly and honest.
5. **Two adapters, two segmentations, one document.** Page 1 by anydoc, page 2 by docling ⇒
   different type vocabularies and different granularity. Not solved — made *visible*:
   `page.segmentation` records the producer, and the run manifest reports a mixed-segmentation
   warning. A chunker that ignores it will produce uneven chunks.
6. **The `x` bag as an abstraction leak.** Adapters will dump everything there. The namespacing rule
   and the 20% lint slow it down; they do not stop a determined adapter author. Review is the
   backstop, and that is a weaker enforcement than I would like.
7. **A 5,000-page single table.** `Table.continued_from` chains per-page tables, so the exactly-once
   invariant holds *per Table* but "which cell is above this one" across a page break needs chain
   resolution. Cross-page merge is a separate P2 pass (marker's design: geometry pre-filter, LLM
   only for adjudication), so an unmerged table is correct-but-fragmented — never wrong, sometimes
   incomplete.
8. **`content_key` collisions at 128 bits** are negligible (~1e-19 at 10M items), but the *semantic*
   collision — identical boilerplate across 10,000 contracts — is real and by design. It is safe only
   because I forbade `content_key` as an FK target (I15). If a future panel reaches for it as an
   address, that invariant is the only thing standing in the way.
9. **The single-file store is a single writer.** One SQLite file per corpus means one writer; a
   200-page-per-second ingest fleet needs the T2/T3 story from D6, and the WAL valve from codegraph
   is mandatory, not optional (22 GB WAL and an OOM-kill measured without it).

---

## 15. Why I reject the alternatives

**Inherit `DoclingDocument`** — §1. Unread source, torch as a base dependency, JSON-pointer identity
that encodes a list index, four parallel type-partitioned lists, and an inherited confidence field
nobody computes. The genuine benefit (its ecosystem) is captured by a two-way adapter at ~400 lines.

**Marker's in-memory Pydantic tree as the model** — correct mechanics (arena, tombstones, stable ids,
ordered structure list — I take all four) and the wrong container. `PageGroup.children` retains every
block ever created including tombstones, plus optionally two PIL images per page; `Document.pages` is
a `list`. It cannot stream, cannot partially load, and cannot be appended to page-by-page. Take the
mechanics, reject the container.

**anydoc's `Document{blocks, notes, assets}` as the model** — the best *fully-resolved* model here
and the source of my table grid, note model and asset provenance. Rejected as the container because
`to_document` is unsupported for PDF (`anydoc/src/lib.rs` — the index's claim that `toDocument()` is
the great reusable API needs that asterisk), it has no geometry at all (no bbox anywhere), no
per-item confidence, no charspan, and inline asset bytes with a 128 MiB document cap.

**A DAG** — no use case survives contact with "cross-references are L3 edges". Costs cycle
detection, ambiguous serialisation order, and an unanswerable reading-order question.

**Arrow/Parquet or protobuf as the canonical form** — §9, with graphrag's measured 50 GB-copy-per-
update as the empirical counter-evidence for immutable columnar files, and a schema compiler plus
unreadability as the cost of protobuf. Both remain available as *exports*.

**msgpack as the archive** — after deflate the win is under 20% on text-dominated payloads, and
jcodemunch measured 0% savings from tabular encoding on verbatim text. Not worth an unreadable
archive.

**Content-hash-only identity** — breaks citation. graphrag's `short_id` exists precisely because
"a citation must be short enough for a model to emit reliably"; a 16-hex-char key is not, and
"page 14, third paragraph" becomes unaddressable.

**Path-id-only identity** — every re-parse invalidates every embedding, and there is no way to diff
two parse generations. LEANN's `sequential` scheme "breaks on any re-chunk"; that is this failure
with a different name.

**Markdown strings plus sidecars** — the blueprint already refutes it, and `mine-parse` §B1 quantifies
it: six of eleven parsing repos hand downstream a string, so citation-to-pixel, layout-faithful
rendering and round-trip are unbuildable on their output at all.

---

## Appendix A — the SQLite DDL (schema_version 1)

This is the canonical form. D5 adds indexes, the WAL valve and the edge tables on top of these
tables; it does not add a second representation.

```sql
-- Pragma ORDER is load-bearing: busy_timeout FIRST, before journal_mode
-- (codegraph #238: setting journal_mode first crashes on a contended open).
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA cache_size   = -64000;      -- 64 MB
PRAGMA mmap_size    = 268435456;   -- 256 MB

CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
-- rows: schema_version, min_reader_version, corpus_id, created_at, writer_version

-- Generated from the Python enums at migration time; a CI test asserts parity.
CREATE TABLE block_type (type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE enum_val   (domain TEXT NOT NULL, ord INTEGER NOT NULL, name TEXT NOT NULL,
                         PRIMARY KEY (domain, ord)) WITHOUT ROWID;
-- domains: layer, trust, fidelity, extraction, span_kind, page_kind, table_kind

CREATE TABLE doc (
  doc_ord        INTEGER PRIMARY KEY,        -- corpus-local; the id an LLM cites
  doc_id         TEXT    NOT NULL UNIQUE,    -- sha256(NORMALISED source bytes)[:16]
  source_sha256  TEXT    NOT NULL,           -- sha256 of the RAW bytes, un-normalised
  uri            TEXT    NOT NULL,           -- canonical_uri(): realpath+normcase+forward slashes
  mime           TEXT    NOT NULL,
  format         TEXT    NOT NULL,
  format_evidence TEXT   NOT NULL,           -- JSON: how detection decided (magic/probe/OPC root)
  source_bytes   INTEGER NOT NULL,
  gen            INTEGER NOT NULL DEFAULT 1, -- current parse generation
  status         TEXT    NOT NULL,           -- ok|partial|failed|skipped
  page_count     INTEGER,
  schema_version INTEGER NOT NULL,
  confidence     TEXT    NOT NULL DEFAULT '{}',  -- ConfidenceReport, docling shape
  timings        TEXT    NOT NULL DEFAULT '{}',
  x              TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE page (
  doc_ord    INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen        INTEGER NOT NULL,
  page_ord   INTEGER NOT NULL,          -- SOURCE index, 0-based. NEVER a batch index.
  page_kind  INTEGER NOT NULL,          -- page|slide|sheet|frame|stream
  label      TEXT,                      -- printed page label: "iv", "A-3"
  width_pt   REAL, height_pt REAL,      -- NULL when page_kind='stream'
  rotation   INTEGER NOT NULL DEFAULT 0,
  extraction INTEGER NOT NULL,          -- the branch that ran on THIS page
  ocr_error_score REAL,                 -- keep the SCORE, not the label (surya)
  segmentation INTEGER NOT NULL REFERENCES producer(producer_id),
  stats      TEXT NOT NULL DEFAULT '{}',-- marker page_stats shape: counts, llm tokens, timings
  PRIMARY KEY (doc_ord, gen, page_ord)
) WITHOUT ROWID;

-- Interned OperatorIdentity. Shared verbatim with the L5 runtime.
CREATE TABLE producer (
  producer_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, schema_version INTEGER NOT NULL, code_fingerprint TEXT NOT NULL,
  model_id TEXT, prompt_fp TEXT,
  -- SQL NULLs are each distinct, so a nullable natural key needs IFNULL sentinels
  -- or INSERT OR IGNORE degenerates to a plain INSERT (codegraph #1034).
  UNIQUE (name, schema_version, code_fingerprint, IFNULL(model_id,''), IFNULL(prompt_fp,''))
);

CREATE TABLE block (
  block_pk   INTEGER PRIMARY KEY,            -- internal only; NEVER cited, NEVER exported
  doc_ord    INTEGER NOT NULL,
  gen        INTEGER NOT NULL,
  page_ord   INTEGER NOT NULL,
  slot       INTEGER NOT NULL,               -- arena index, append-only within (doc,gen,page)
  block_id   TEXT    NOT NULL,               -- 'p{page_ord}.b{slot}' -- the citation form
  parent_pk  INTEGER REFERENCES block(block_pk) ON DELETE CASCADE,
  ord        INTEGER NOT NULL,               -- position among siblings == READING ORDER
  type_id    INTEGER NOT NULL REFERENCES block_type(type_id),
  raw_type   TEXT,                           -- the producer's own label, kept (surya raw_label)
  layer      INTEGER NOT NULL,               -- body|furniture|note|annotation|hidden
  text       TEXT,                           -- PLAIN text, the truth. NULL for containers.
  content_key BLOB,                          -- sha256(normalise(text))[:16]; NULL iff text NULL
  -- geometry: always TOPLEFT, always points
  bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
  quad    BLOB,                              -- 8 x float32, only when rotation != 0
  -- source addressing (section 4a)
  span_kind INTEGER NOT NULL,                -- bytes|charstream|part|pixels|none
  span_a    INTEGER, span_b INTEGER,         -- (start, len) for bytes / charstream
  span_part TEXT, span_path TEXT,            -- OOXML part name + child-index path "0.3.1.7"
  -- provenance (section 7)
  producer_id INTEGER NOT NULL REFERENCES producer(producer_id),
  trust      INTEGER NOT NULL,               -- 0=AMBIGUOUS 1=INFERRED 2=EXTRACTED (MIN() is useful)
  score      REAL,                           -- the producer's own number, never the tier
  fidelity   INTEGER NOT NULL,               -- verbatim|reflowed|reconstructed|synthetic
  extraction INTEGER NOT NULL,
  state      INTEGER NOT NULL DEFAULT 0,     -- 0=live 1=tombstone. There is no DELETE.
  x          TEXT    NOT NULL DEFAULT '{}',
  FOREIGN KEY (doc_ord, gen, page_ord)
    REFERENCES page(doc_ord, gen, page_ord) ON DELETE CASCADE
);
CREATE UNIQUE INDEX block_ident  ON block(doc_ord, gen, page_ord, slot);
CREATE UNIQUE INDEX block_cite   ON block(doc_ord, gen, block_id);
CREATE INDEX block_order  ON block(doc_ord, gen, page_ord, ord)  WHERE state = 0;
CREATE INDEX block_parent ON block(parent_pk, ord)               WHERE state = 0;
CREATE INDEX block_ckey   ON block(content_key)                  WHERE content_key IS NOT NULL;
CREATE INDEX block_bytype ON block(doc_ord, gen, type_id)        WHERE state = 0;

CREATE TABLE mark (
  block_pk INTEGER NOT NULL REFERENCES block(block_pk) ON DELETE CASCADE,
  start    INTEGER NOT NULL,       -- char offsets into block.text
  end      INTEGER NOT NULL,
  kind     TEXT    NOT NULL,       -- bold|italic|code|link|math|anchor|noteref|
                                   -- dehyphenated|raw_style|redaction|lang|...
  value    TEXT,                   -- JSON; NULL for valueless marks
  PRIMARY KEY (block_pk, start, end, kind)
) WITHOUT ROWID;

CREATE TABLE table_meta (
  block_pk    INTEGER PRIMARY KEY REFERENCES block(block_pk) ON DELETE CASCADE,
  n_rows INTEGER NOT NULL, n_cols INTEGER NOT NULL,
  header_rows INTEGER NOT NULL DEFAULT 0, header_cols INTEGER NOT NULL DEFAULT 0,
  kind        INTEGER NOT NULL,          -- data|layout|dataset
  recon_strategy TEXT,                   -- span_x0|span_center|proj_1|proj_3|proj_10|
                                         -- vlm|native_xml|tableformer
  recon_score REAL,                      -- marker's judge score, KEPT (marker discards it)
  continued_from INTEGER REFERENCES block(block_pk)
);
CREATE TABLE cell (                      -- ORIGIN cells only; a cell IS a block
  block_pk INTEGER PRIMARY KEY REFERENCES block(block_pk) ON DELETE CASCADE,
  table_pk INTEGER NOT NULL REFERENCES table_meta(block_pk) ON DELETE CASCADE,
  row INTEGER NOT NULL, col INTEGER NOT NULL,
  row_span INTEGER NOT NULL DEFAULT 1, col_span INTEGER NOT NULL DEFAULT 1,
  UNIQUE (table_pk, row, col)
);
CREATE TABLE table_slot (                -- materialised cover map; built ONLY by build_grid()
  table_pk  INTEGER NOT NULL REFERENCES table_meta(block_pk) ON DELETE CASCADE,
  row INTEGER NOT NULL, col INTEGER NOT NULL,
  origin_pk INTEGER NOT NULL REFERENCES cell(block_pk) ON DELETE CASCADE,
  PRIMARY KEY (table_pk, row, col)
) WITHOUT ROWID;
-- "which cell is above this one":
--   SELECT origin_pk FROM table_slot WHERE table_pk=?1 AND col=?2 AND row=?3-1;

CREATE TABLE asset (
  asset_id   INTEGER PRIMARY KEY,
  doc_ord    INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  origin_part TEXT,                      -- anydoc's origin_part: which package part/stream
  sha256     TEXT NOT NULL, size INTEGER NOT NULL,
  width INTEGER, height INTEGER,
  store_ref  TEXT NOT NULL,              -- blobs/<sha[0:2]>/<sha256>   NO INLINE BYTES
  licence TEXT, licence_url TEXT, source_url TEXT, retrieved_at TEXT,   -- media ledger
  UNIQUE (doc_ord, sha256, IFNULL(origin_part,''))
);
CREATE TABLE block_asset (
  block_pk INTEGER NOT NULL REFERENCES block(block_pk) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES asset(asset_id) ON DELETE CASCADE,
  role TEXT NOT NULL,                    -- image|thumbnail|source_crop|ole|chart_data
  PRIMARY KEY (block_pk, asset_id, role)
) WITHOUT ROWID;

CREATE TABLE doc_error (                 -- docling ErrorItem + anydoc stable codes
  doc_ord INTEGER NOT NULL REFERENCES doc(doc_ord) ON DELETE CASCADE,
  gen INTEGER NOT NULL, page_ord INTEGER,
  component TEXT NOT NULL,
  code      TEXT NOT NULL,               -- unsupported|needs_ocr|malformed|encrypted|
                                         -- resource_limit|missing_part|io|table_bulk_downgrade
  message   TEXT NOT NULL,
  fatal     INTEGER NOT NULL             -- anydoc's is_fatal(): resource limits never swallowed
);

-- Lexical channel. External-content: NO second copy of the text.
CREATE VIRTUAL TABLE block_fts USING fts5(
  text, content='block', content_rowid='block_pk',
  tokenize='unicode61 remove_diacritics 2'
);
-- + the three standard AFTER INSERT/DELETE/UPDATE sync triggers (D5 owns the BM25 weights).
```

## Appendix B — the Python surface (`omniweave.model`, torch-free, PIL-free)

```python
# omniweave/model/enums.py  --  values are MEMBER NAMES on the wire, always.
class Trust(IntEnum):      AMBIGUOUS = 0; INFERRED = 1; EXTRACTED = 2
class Fidelity(StrEnum):   VERBATIM="verbatim"; REFLOWED="reflowed"
                           RECONSTRUCTED="reconstructed"; SYNTHETIC="synthetic"
class Layer(StrEnum):      BODY="body"; FURNITURE="furniture"; NOTE="note"
                           ANNOTATION="annotation"; HIDDEN="hidden"
class Extraction(StrEnum): TEXT_LAYER="text_layer"; NATIVE_XML="native_xml"
                           OCR_PAGE="ocr_page"; OCR_BLOCK="ocr_block"; VLM_PAGE="vlm_page"
                           HEURISTIC="heuristic"; LLM="llm"; ROUNDTRIP="roundtrip"
class PageKind(StrEnum):   PAGE="page"; SLIDE="slide"; SHEET="sheet"; FRAME="frame"; STREAM="stream"
class BlockType(StrEnum):
    # 34 members; every value == its own name. UNKNOWN is mandatory (forward compat).
    DOCUMENT="document"; SECTION="section"; PARAGRAPH="paragraph"; HEADING="heading"
    TITLE="title"; LIST="list"; LIST_ITEM="list_item"; TABLE="table"; TABLE_CELL="table_cell"
    FIGURE="figure"; PICTURE="picture"; CAPTION="caption"; FORMULA="formula"; CODE="code"
    QUOTE="quote"; RULE="rule"; PAGE_HEADER="page_header"; PAGE_FOOTER="page_footer"
    FOOTNOTE="footnote"; ENDNOTE="endnote"; SPEAKER_NOTE="speaker_note"; COMMENT="comment"
    FORM="form"; FORM_FIELD="form_field"; CHECKBOX="checkbox"; KEY_VALUE="key_value"
    TOC="toc"; TOC_ENTRY="toc_entry"; REFERENCE="reference"; BIBLIOGRAPHY="bibliography"
    HANDWRITING="handwriting"; CHEMICAL="chemical"; DIAGRAM="diagram"; UNKNOWN="unknown"

# omniweave/model/geom.py
class CoordOrigin(StrEnum): TOPLEFT="topleft"; BOTTOMLEFT="bottomleft"
class Unit(StrEnum):        PT="pt"; PX="px"; EMU="emu"; NORM1000="norm1000"

@dataclass(frozen=True, slots=True)
class Bbox:
    x0: float; y0: float; x1: float; y1: float          # ALWAYS topleft, ALWAYS points
    def __post_init__(self): assert self.x1 >= self.x0 and self.y1 >= self.y0
    @staticmethod
    def topleft_pt(x0, y0, x1, y1) -> "Bbox": ...
    @staticmethod
    def convert(x0, y0, x1, y1, *, origin: CoordOrigin, unit: Unit,
                page_height: float | None) -> "Bbox":
        """The ONLY way to build a Bbox from foreign coordinates. Flips and rescales once,
        at ingest. docling reconciles three live conventions per call site: a bug farm."""
# There is no constructor taking raw coords without an origin. That is invariant I3.

# omniweave/model/span.py  --  section 4(a). A tagged union; a PDF paragraph has NO byte range.
@dataclass(frozen=True, slots=True) class ByteSpan:   start: int; length: int
@dataclass(frozen=True, slots=True) class CharStream: page: int; start: int; length: int
@dataclass(frozen=True, slots=True) class PartSpan:   part: str; path: tuple[int, ...]
@dataclass(frozen=True, slots=True) class PixelSpan:  page: int; bbox: Bbox
@dataclass(frozen=True, slots=True) class NoSpan:     pass
SourceSpan = ByteSpan | CharStream | PartSpan | PixelSpan | NoSpan

@dataclass(frozen=True, slots=True) class TextSpan: start: int; end: int   # into block.text

# omniweave/model/block.py
BlockId = NewType("BlockId", str)          # "p14.b3"
DocId   = NewType("DocId", str)            # sha256(normalised)[:16]

@dataclass(slots=True)
class Block:
    block_id: BlockId
    doc_ord: int; gen: int; page_ord: int; slot: int
    parent: BlockId | None; ord: int
    type: BlockType
    layer: Layer
    text: str | None
    content_key: bytes | None                    # 16 bytes
    bbox: Bbox | None
    quad: tuple[float, ...] | None               # 8 floats, only when rotated
    span: SourceSpan
    producer: ProducerRef
    trust: Trust                                 # NO DEFAULT. State it. (I7)
    fidelity: Fidelity                           # NO DEFAULT.
    extraction: Extraction                       # NO DEFAULT.
    score: float | None = None
    raw_type: str | None = None
    marks: tuple[Mark, ...] = ()
    tombstoned: bool = False
    x: dict[str, Any] = field(default_factory=dict)   # keys MUST be x.<vendor>.<key>

@dataclass(frozen=True, slots=True)
class ProducerRef:                               # == the L5 runtime's OperatorIdentity
    name: str; schema_version: int; code_fingerprint: str
    model_id: str | None = None; prompt_fp: str | None = None

@dataclass(frozen=True, slots=True)
class Mark:
    start: int; end: int; kind: str; value: Any | None = None

# omniweave/model/table.py
@dataclass(frozen=True, slots=True)
class TableGrid:
    n_rows: int; n_cols: int
    header_rows: int; header_cols: int
    kind: Literal["data", "layout", "dataset"]
    origins: Mapping[tuple[int, int], BlockId]      # origin cells only
    slots:   Mapping[tuple[int, int], BlockId]      # EVERY (row,col) -> its origin
    def above(self, r, c) -> BlockId | None: return self.slots.get((r - 1, c))
    def top_heading(self, c) -> tuple[BlockId, ...]: ...

class GridOverlap(ValueError): ...

def build_grid(cells: Sequence[CellDraft], *, header_rows: int = 0,
               header_cols: int = 0, kind="data") -> TableGrid:
    """SOLE constructor of a TableGrid (invariant I6). Registers covered positions,
    skips them on later placement, and RAISES GridOverlap rather than clamping --
    anydoc clamps, which is a silent loss. Every (row,col) in
    [0,n_rows) x [0,n_cols) resolves to exactly one origin, or this raises."""

# There is NO html/markdown field anywhere. Rendering is a function:
def render_table(g: TableGrid, blocks: BlockReader,
                 fmt: Literal["html", "gfm", "otsl", "csv", "pptx_fragment"]) -> str: ...

# omniweave/model/serialize.py  --  invariant I9
class SpanMap:
    def block_at(self, offset: int) -> tuple[BlockId, TextSpan]: ...
    def offsets_of(self, b: BlockId) -> tuple[int, int]: ...
    def slice_for(self, b: BlockId) -> str: ...

def serialize(scope: Scope, fmt: Literal["md", "gfm", "html", "text", "otsl"],
              *, layers: frozenset[Layer] = frozenset({Layer.BODY}),
              contextualize: bool = False) -> tuple[str, SpanMap]:
    """There is no text-only serializer. If you have the text you have the map."""

# omniweave/model/sink.py  --  section 11. Drivers PUSH; they never build a Document.
class DocSink(Protocol):
    def begin_doc(self, rec: DocRecord) -> None: ...
    def begin_page(self, page: PageRecord) -> None: ...
    def add_block(self, b: BlockDraft) -> BlockId: ...       # assigns the slot; returns the id
    def add_marks(self, bid: BlockId, marks: Sequence[Mark]) -> None: ...
    def add_table(self, bid: BlockId, grid: TableGrid) -> None: ...
    def add_asset(self, a: AssetDraft, blob: BinaryIO) -> AssetId: ...
    def error(self, e: ErrorItem) -> None: ...
    def end_page(self, stats: PageStats) -> None: ...        # commits ONE transaction
    def end_doc(self, status: Status) -> DocRecord: ...

# omniweave/model/driver.py  --  mine-parse E11: capability declaration
class Cap(StrEnum):
    BBOX="bbox"; CHARSPAN="charspan"; CELL_IDENTITY="cell_identity"; MARKS="marks"
    NOTES="notes"; SPEAKER_NOTES="speaker_notes"; TRACKED_CHANGES="tracked_changes"
    VERBATIM_BYTES="verbatim_bytes"; PAGE_IMAGES="page_images"

class Driver(Protocol):
    NAME: ClassVar[str]; SCHEMA_VERSION: ClassVar[int]
    FORMATS: ClassVar[frozenset[str]]
    CAPABILITIES: ClassVar[frozenset[Cap]]
    def parse(self, src: Source, sink: DocSink,
              pages: range | None = None) -> ParseReport: ...
# Because caps are declared, a consumer can distinguish "this driver cannot produce a bbox"
# from "this document has no bbox". No repo in _collections/ can answer that today.

# omniweave/model/read.py  --  a lazy handle, NOT a loaded object
class Doc:
    rec: DocRecord
    def page(self, page_ord: int) -> PageView: ...           # 1 indexed query
    def block(self, bid: BlockId) -> Block: ...              # ~0.05 ms
    def blocks(self, *, layer=Layer.BODY, types=None,
               pages: range | None = None) -> Iterator[Block]: ...   # generator, page-batched
    def table(self, bid: BlockId) -> TableGrid: ...
    def serialize(self, fmt, **kw) -> tuple[str, SpanMap]: ...
    def verify_verbatim(self, bid: BlockId) -> VerbatimVerdict: ...
# There is deliberately NO `Doc.pages: list[Page]` attribute. That field is why marker
# cannot parse a 5,000-page document.
```

## Appendix C — directory tree

```
omniweave/
  model/                 # omniweave-core. pydantic + sqlite3 + orjson. ~15 MB installed.
    enums.py  geom.py  span.py  block.py  table.py  mark.py  asset.py
    sink.py  read.py  serialize.py  driver.py  errors.py  limits.py
    owdoc/               # the ZIP-of-JSONL interchange codec
      write.py  read.py  manifest.py
    store/               # the canonical form
      schema.sql  migrations/0001_init.sql  ...  sqlite_sink.py  sqlite_reader.py
    schema.json          # GENERATED from the models, COMMITTED -- schema diffs show in PRs
  adapters/
    anydoc/              # extra: omniweave[anydoc]      tier 0, MIT, ms-scale office
    docling/             # extra: omniweave[docling]     PDF/HTML/XML in, DoclingDocument out
    markitdown/          # extra: omniweave[markitdown]  breadth; fidelity=reconstructed
    marker/              # extra: omniweave[marker]      code only; weights are the user's problem
  cli/
    doc.py  store.py  doctor.py
fixtures/
  owdoc/v1/*.owdoc       # one per released schema version; I11 loads all of them
  docs/                  # html-no-pages.html, ragged-table.docx, 200k-row.xlsx,
                         # rotated-scan.pdf, spanned-merged.pptx, msg-email.msg
```

## Appendix D — the one-paragraph version, for whoever has to build it

One SQLite file per corpus is the document model. A block is a row. Its parent is a column, its
reading order is a column, its page is a column. It is addressed by `p14.b3` for citation and by a
16-byte `content_key` for caching, and those two ids never do each other's job. Its geometry is
always top-left points because `Bbox` has no other constructor. Its source address is a tagged union
because a PDF paragraph has no byte range. It carries five provenance fields — who made it, how much
to trust it, that producer's own score, whether its bytes are quotable, and which branch of the
router ran — each with three named consumers. Tables are cells, cells are blocks, the grid is a
relation built by one function that raises on overlap, and no type anywhere has an `html` field.
Assets are hashes into a blob directory, page images are an evictable cache, and drivers push into a
sink one page per transaction so a 5,000-page document never exists in memory. Docling, anydoc and
markitdown are adapters. Two weeks to the first working CLI.
