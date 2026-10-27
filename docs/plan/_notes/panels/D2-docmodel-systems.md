# D2 — The canonical document model (`owdoc`)

**Panel:** D2, the L2 pivot. **Architect prior:** systems purist.
**Position:** own the schema, vendor nothing as a base class, and make identity, spans, and
serialization three separate decisions instead of one.

---

## Headline

**omniweave defines its own normative wire schema — `owdoc` — as a flat, ordinally-addressed node
table with one strict spine plus a typed relation table; DoclingDocument becomes an importer and an
export target, never a base class. Identity is four fields with four written-down jobs (`uid`,
`path`, `content_digest`, `cite`), text is addressed in three explicitly distinct span spaces
(`SourceSpan` / `GlyphSpan` / `RenderSpan`) that the type system refuses to mix, and the model is a
handle over a SQLite store so a 5,000-page document never exists in memory at once.**

---

## 1. Why not inherit `DoclingDocument`

The blueprint says "start from `DoclingDocument`, extend with marker's spatial fields." I am
overturning the first half and keeping the second. Five checkable reasons.

**1.1 The pivot type would be defined outside the repository.**
`docling/pyproject.toml:46` pins `docling-core[chunking] (>=2.73.0,<3.0.0)`. That is a moving floor
inside a major version on the one type every other layer of omniweave reads and writes. `mine-parse.md`
§A1.11 states plainly that *"`DoclingDocument` is defined in `docling-core` (not vendored here)"* —
so its transitive closure, its licence surface, and its evolution policy cannot be audited from this
collection at all. The single most irreversible decision in the framework cannot rest on a type we
have not read.

**1.2 The type is one import away from a 2.5–3.5 GB install.**
`docling/pyproject.toml:48-49` lists `torch (>=2.2.2,<3.0.0)` and `torchvision (>=0,<1)` as **base**
dependencies, and the `[chunking]` extra on docling-core drags a tokenizer stack. The risk digest's
rule — *"an L5 orchestration layer must never be a dependency of an L1 parser, or every consumer of
your DOCX reader installs Chromium"* — applies with full force to the L2 type: every consumer of the
document model would sit one careless `from docling...` away from the tensor stack. `omniweave-core`
must fit a 250 MB Lambda layer; `owdoc`'s runtime dependency set is `msgpack`, `blake3`, and stdlib
`sqlite3`.

**1.3 The model has structural gaps that cannot be fixed from a subclass.**
- No per-element extraction method. `mine-parse.md` PART D loss #10: per-page `ErrorItem`s exist but
  there is *"no per-element 'this came from OCR' flag comparable to marker's
  `text_extraction_method`."* That field is the whole basis of selective re-parse and of honest
  citation.
- No asset provenance. PART D #15: marker and docling both carry asset bytes without the package part
  they came from; anydoc's `origin_part` (`anydoc/src/model/asset.rs`) is unique in the collection.
- `table_score` is declared and **never assigned anywhere** (`mine-parse.md` §A1.6, confirmed by
  grep), and docling still grades documents on it.
- Child references are **JSON pointers into arrays** (`#/texts/1`). An array index is a position, and
  a position in an identity is precisely the mistake codegraph paid for (`mine-graph.md` §3.3: `line`
  in the node id forced a `(path, kind, name)` rebind dance on every docstring edit). Inserting one
  footnote on re-parse renumbers every pointer after it.

**1.4 The ecosystem argument is an importer argument, not an inheritance argument.**
docling's serializers, chunkers and framework integrations are real value. We get all of them by
*exporting* `owdoc → DoclingDocument`, paying the loss once, at a boundary we control, with a
capability declaration recording exactly what was dropped. Inheritance buys the same integrations and
additionally hands docling a veto on our schema evolution.

**1.5 What we take from docling instead, and it is a lot.**
`ProvenanceItem.charspan` (the only charspan in the collection), `CoordOrigin` in the geometry type,
the `body`/`furniture` two-layer split, `ConversionStatus` + per-page `ErrorItem`, the
`ConfidenceReport` shape, the `ConversionAssets` ZIP-of-one-JSON-per-component envelope with a
tolerant `load()`, the `_build_document` page-batch memory discipline, and the API discipline of
publishing grades while keeping scores internal. Those are *designs*. We copy designs. We do not
inherit classes.

---

## 2. Shape: flat, one spine, relations on top

**Not a tree. Not a DAG. A flat ordered node table with one strict spine (`parent_uid` + `ord`) and a
typed `rel` table for everything the spine cannot express.** The tree is a *view*; the DAG is the
`rel` table.

Why the spine is strict and single:
- Reading order is the most-read property of a document. A model that cannot answer "the next 200
  body blocks" with one index scan is wrong for its dominant query. A property graph makes that a
  traversal; `ORDER BY ord_path` makes it a range scan.
- Every model in the collection that tried to put everything in one tree needed a second one:
  docling has `body` **and** `furniture` **and** `groups`; marker has to copy
  `section_hierarchy: {level: BlockId}` onto *every* rendered block because the tree cannot express
  it. Both are the same admission.

Why the relations are a separate table and not more tree:
`caption_of`, `continues_from` (a table crossing a page break), `note_ref`, `anchor_target`,
`heading_of`, `derived_from`, `supersedes`. These are genuinely many-to-many and genuinely not
containment. Forcing them into containment is where cross-page tables and captions get duplicated or
lost.

Why flat and not a materialized object tree:
5,000 pages × ~120 nodes/page ≈ 600k nodes; the 10M-block target is 16× that. graphrag's own wall is
instructive — 20M edges as Python tuples is *"~4–6 GB of interpreter objects before the algorithm
allocates anything"* (`mine-graph.md` §1.10). A pointer tree of 10M pydantic objects is not a design,
it is an OOM. marker's per-page arena (append-only, `id == index`, tombstones, self-healing
`_structure_index`) is the correct *mutation* discipline and we adopt it — **for the in-flight
per-page arena only**, not for the durable store. Tombstones in a 10M-row table are a permanent leak;
at commit the arena compacts and retirement is recorded in `node_history`.

`ord_path` is a gap-allocated, lexicographically sortable byte string whose parent's value is a strict
prefix. Full-document render is one index scan; a subtree is a prefix range; no recursive CTE on the
hot path. That is the concession flatness must pay for and it is cheap.

---

## 3. Identity: four fields, four jobs, and a rule saying which is which

The question "path-like or content hash" is a false binary — the two schemes fail in opposite
directions and both failures are silent.

- Content hash alone: a 5,000-page report with an identical running footer collapses 5,000 nodes into
  one, and any edit orphans every annotation. graphrag proves the surface-form-key failure from the
  other end — it keys edges on uppercased entity **titles**, so *"an entity whose spelling drifts
  between chunks becomes two nodes"* (`mine-graph.md` §1.1).
- Path alone: inserting one footnote on re-parse renumbers siblings, and every index row, embedding
  and human review decision downstream silently rebinds to the *wrong content*. That is the worst
  failure class available, because nothing reports it.

So: four fields.

| field | type | job | may appear in |
|---|---|---|---|
| `uid` | `int64`, assigned once, never re-derived | the durable surrogate key. Everything foreign-keys to this: index rows, embeddings, edges, annotations, review decisions | database columns only |
| `path` | `"/p12/tbl0/r3/c2"` | human/agent addressing, prefix range queries, and the OUT-direction round-trip address | URLs, CLI arguments, logs |
| `content_digest` | blake3-128, Merkle over children | change detection, dedupe, cache keys, reconciliation | cache keys, diffs |
| `cite` | `"d7#412"`, short, per-doc monotonic | the **only** id an LLM may emit or receive | prompts and model output only |

`cite` is graphrag's `short_id` generalized — *"the only id an LLM may cite"* (`mine-graph.md` §1.1) —
and the asymmetry graphrag also gets right rides along: a chunk is *addressed*, never *named*, so
`title` is NULL on text nodes and present on headings, tables and figures.

**Two digests, not one.** This is the detail that decides whether reconciliation works:

- `content_digest` = f(kind, layer, NFC text, kind payload, child content digests). **Geometry is
  not an input.** A better driver re-segmenting the same page jitters every bbox; if geometry were in
  the reconciliation digest, a driver upgrade would orphan the entire document.
- `layout_digest` = f(content_digest, page, geometry **quantized to whole points**). This is the
  ppt-master question — *"round-trip change detection is canonicalize-then-hash; byte comparison is
  useless"* (`mine-out.md` §1.6.4, `normalized_authoring_subtree_sha256`) — and it is a different
  question from reconciliation, so it gets a different hash.

Both live under one **`digest_recipe: int`** stored on the document, because adding a field must not
silently change every digest in the world. Constraint that falls out and must be enforced by the
generator: **only stored fields may be digest inputs**, so a recipe bump can be serviced by a
re-digest pass rather than a re-parse.

**Reconciliation** (re-parse of the same source, or a driver upgrade) is an explicit pass, not a
side effect:

1. equal `content_digest` under equal parent `uid` → carry the `uid`.
2. equal `path` and equal `kind`, digest changed → carry the `uid`, `revision += 1`.
3. neither → new `uid`; the old `uid` goes to `node_history` with `superseded_by` when a 1:1 match is
   defensible, `reason='reparse_resegmented'` otherwise.

It emits a `RebindReport` with per-page match rates, and **a re-parse whose match rate falls below a
threshold is quarantined pending confirmation, not committed** — the runtime layer's shrink-guard
shape (`mine-runtime.md` §7.6.3) applied to identity. This is the document analogue of codegraph's
`definitionDelta` and graphify's tier-scoped `build_merge`, and it owes L5 a CI
incremental-vs-full-rebuild equivalence test. codegraph measured what skipping that costs: **4.3% of
distinct edges wrong, in both directions, silently, forever until a full rebuild**
(`mine-runtime.md` §1, from codegraph CG-33).

---

## 4. Text addressing: three span spaces, and the honest hole

This is the part the blueprint does not engage and it is where a wrong answer is unrecoverable.
There are three distinct coordinate systems for text and conflating any two produces citations that
point at the wrong characters.

**`SourceSpan` — a byte range in the original file.**
`(part, byte_start, byte_len, decode)`. Exists only when the format's bytes *are* the text: txt, md,
html, csv, xml, source code. jcodemunch's mechanism is the reference: `"rb"` + `seek` +
`read(n)`, *"O(1) in file size … on a 40 MB file this is the difference between 1 ms and 200 ms"*
(`mine-graph.md` §4.2), and its span semantics are stated precisely — a byte range from the
declaration's first token *"carries no leading indentation on its first line"* and is **not** a line
range.

**The honest hole: for PDF, DOCX, PPTX, XLSX there is no such thing.** The "original bytes" of a
DOCX paragraph are a fragment of a deflate stream inside a ZIP. Any design that offers a byte range
into the original PDF for a paragraph is lying. For container formats `SourceSpan.part` names the
package part (`word/document.xml`) — anydoc's `origin_part`, generalized from assets to text — and
`byte_start/len` address the *decompressed part*, which is reproducible because the part is
content-addressed. For PDF, `SourceSpan` is NULL and that is recorded in the driver's capability
declaration.

That gate is load-bearing for the serve layer. `mine-serve.md` records that the paragraph asserting
verbatimness — *"byte-for-byte identical to what the Read tool returns … treat each block as a Read
you have already performed"* — is what stops the agent's second read. **omniweave may make that claim
only for nodes whose driver declares `source_span: true`.** For a PDF-sourced node the claim is
false, and shipping it would be shipping a lie the agent cannot detect.

**`GlyphSpan` — a range in the extracted character stream of a page.**
`(page, extractor, char_start, char_len)`. This is docling's `ProvenanceItem.charspan` with the
extractor identity attached, and it is what makes marker's finding usable: the PDF's own character
stream order beats a learned reading-order head **75% vs 56%** on olmOCR-bench order tests
(`marker/builders/line.py:80-82`). The extractor id must be stored because pdftext's char indices and
a VLM's are different spaces on the same page.

**`RenderSpan` — a range in a serialized render.**
`(render_id, char_start, char_len)` where `render_id` = serializer + version + options digest.
Markdown output, chunk text, contextualized embedding text all live here. An LLM's answer cites
`RenderSpan`s and they must be *lifted* to `(uid, GlyphSpan)` before anything is highlighted.

**The invariant: a span is never stored without the identity of the space it lives in.** Three
distinct frozen types, no implicit conversion, no `int` offsets in any signature. The only path from
`RenderSpan` to `GlyphSpan` is a `SpanMap` emitted by the serializer that produced that render;
a serializer either emits one or declares `spanmap: none`, and **`spanmap: none` output may never be
cited.**

Two derived rules from the evidence:
- `byte_offset == 0` cannot distinguish "unset" from "starts at byte 0" (`mine-graph.md` §4.2.2), so a
  span is nullable **as a whole** — paired-NULL CHECK constraints, never a zero default.
- Nested spans double-count: summing `byte_length` over nested symbols inflated real source mass by
  **33.4% overall and 2.28× on one file**, non-uniformly (`mine-graph.md` §4.2.2). Documents nest
  page ⊃ section ⊃ paragraph ⊃ table ⊃ cell, so every coverage or savings metric merges intervals
  first, and reports a third **`unmeasurable`** bucket that is neither 0 nor a guess.
- Decode symmetry is an invariant, not a nicety: both sides of any fidelity comparison use the same
  codec and error policy, and never `text=True` on a subprocess whose bytes you intend to compare
  (`mine-graph.md` §4.2.1, jcodemunch #400).

---

## 5. Geometry

`Quad`, not `Rect`: four corners (marker's `PolygonBox`), because rotated scans and skewed columns
exist and a rectangle is a lossy *view* computed on demand.

**Fixed-point `i32` in 1/1000 pt, not float.** A float64 bbox makes `layout_digest` platform- and
libm-dependent, which silently poisons every content-addressed cache. This is exactly the class of
mistake that cannot be fixed later.

**Origin in the type, normalized exactly once at the driver boundary.** docling carries
`CoordOrigin` (`BOTTOMLEFT` for PDF/PPTX, `TOPLEFT` for images) with `.to_top_left_origin(page_height)`
at each use site; marker avoids the whole bug class by fiat. The digest's ruling is right: *"put the
origin in the type but normalize once at ingest — docling's three live conventions reconciled per-call
is a bug farm."* So the stored frame is always `(TOPLEFT, 1/1000 pt, unrotated page)`, and
`quad_origin` records what the driver handed us so the transform is auditable and reversible.
`Quad.from_driver(...)` is the only public constructor.

---

## 6. Tables — one representation, three consumers

anydoc's grid in shape (`anydoc/src/model/table.rs`, verified: `CellSlot::Origin(Cell)` /
`CellSlot::Covered { origin_row, origin_col }`, `GridBuilder` documented as *"Sole constructor for
Table grids. Enforces the exactly-once invariant"*), plus the three things anydoc lacks.

Cells are **real nodes** with their own `uid`, `path`, `quad` and spans — so citation-to-cell works —
and the grid is a dense slot table over them. That is the fix for the worst loss in the collection:
marker's digital path sets `block.html` and `block.structure = []`, and *"everything cell-level —
polygons, citation to a cell, span structure — is gone"* (`mine-parse.md` PART D #2, B4).

**HTML and markdown are renders, never storage.** The `owdoc` Table has no `html` field. anydoc gets
this right and says why: *"the loss is at render time only; the model keeps everything."*

How one representation serves three consumers:

| consumer | needs | supplied by |
|---|---|---|
| **PPTX round-trip** | `(row, col, rowspan, colspan)`, cell runs, cell geometry | `Origin(Cell{row_span,col_span})`; `Covered` slots map 1:1 onto OOXML `hMerge`/`vMerge` |
| **Chunking** | header rows repeatable, section path | `header_rows`, plus docling's `repeat_table_header=True` / `omit_header_on_overflow` knobs |
| **Query** | relational neighbours | `grid[r][c]` is O(1) and every coordinate resolves to exactly one origin — precisely what olmOCR-Bench's `TableTest.up/down/left/right/top_heading/left_heading` asks |

Three additions on top of anydoc:
1. **`recon: (strategy, score)` is stored.** marker computes a per-table reconstruction confidence,
   uses it for the accept gate at ≥0.75 balanced / ≥0.50 fast, and then *logs an aggregate Counter*
   (PART D #9). It goes on the table. `strategy ∈ {native_xml, span_x0, span_center, proj_1, proj_3,
   proj_10, tableformer, vlm}`.
2. **`kind: data | layout`** (anydoc's distinction, unique in the collection): DOCX and HTML both use
   tables for positioning, and unwrapping a layout table is a *serializer* decision, never a parser
   one.
3. **Cross-page continuation is a `continues_from` relation, not a merge.** Merging destroys the page
   attribution citation needs. The *render* merges; the model does not. marker's geometry pre-filter
   (first table ≥0.6 page height, ≤20 px vertical / ≤10 px horizontal edge distance, ≤0.25 dimension
   tolerance) becomes the edge's proposal gate with an LLM only for adjudication.

Raggedness is preserved (anydoc: *"rows may differ in length when the source is ragged"*). `n_cols`
is `max(len(row))`, and a missing slot is NULL, not an empty cell.

---

## 7. Assets and page images

`Asset` is content-addressed, out of line, and refcounted. **Bytes never live in a node record and
never in the JSON.** base64 images inline (marker's `images` dict, omniparse's base64 JPEG q85) is how
a 5,000-page document's serialization becomes 8 GB.

`Asset` carries `origin_part` (anydoc) and the licence block the risk digest demands —
`{licence, licence_url, spdx, source_url, retrieved_at_ns}` — which turns hyperframes' media ledger
into a compliance control at near-zero cost, and lets the OUT validator **refuse to embed an asset
with an unknown licence.**

**Page images are not a model field, by construction.** docling's `Page._image_cache: dict[float, Image]`
is a field on the page object, and docling itself has to defensively clear it every batch
(`if not self.keep_images: p._image_cache = {}`, `base_pipeline.py:239-325`). A `Page` in `owdoc`
holds `renders: [{dpi, colorspace, asset_uid}]` and `doc.page_render(page, dpi)` returns an
`AssetRef`; `doc.asset(ref)` returns a **stream**, never `bytes`. The model is *unable* to hold a
decoded image, which is the only version of this rule that survives five years of contributors.

Rendering stays lazy in the routing sense too: render high-res only for pages the router flagged
(`page_needs_highres` = escalated OR holds Table/Form/TOC/Equation/Chemical), plus a non-persistent
per-page loader for late consumers — marker calls this the cheapest optimization in its repo.

---

## 8. Provenance, method, trust, score — four axes, never conflated

The recurring bug in the collection is collapsing these. codegraph's `edges.provenance ∈
{tree-sitter, scip, heuristic}` answers *which mechanism*; graphify's `confidence ∈ {EXTRACTED,
INFERRED, AMBIGUOUS}` answers *how much to trust it*; `mine-runtime.md` §3.4 states outright that
*"`confidence` and `origin_operator` are different axes and must not be conflated — trust vs
ownership."*

1. **`producer`** — a foreign key into a `producer` table whose row is the full reproduction tuple:
   `(driver, driver_ver, model_id, model_rev, runtime, runtime_ver, prompt_ver, options_digest)`.
   Not a string. HunyuanOCR is the cautionary case: its published **94.10** OmniDocBench was measured
   on TensorRT while the repo ships Transformers and vLLM, which it admits disagree. `model_rev` is
   an exact commit SHA; `revision="main"` is a lint error.
2. **`method`** — `native | text_layer | ocr_page | ocr_block | vlm_page | llm_repair | heuristic |
   user`. marker's `text_extraction_method` generalized, **per node**, which is the field docling
   lacks (PART D #10).
3. **`trust`** — `extracted | inferred | ambiguous` (graphify). Rules that ride along: missing ⇒
   weakest tier (graphify's own `default="EXTRACTED"` is the bug to fix), migrations may only
   **downgrade**, and it must have ≥3 consumers — ranking, review surface, rendering — or it rots into
   decoration.
4. **`score` + `score_kind`** — nullable together, and the *scale* is named, because a layout softmax
   and a mean token probability are not comparable. Keep the score, not the label: marker gates the
   expensive per-block recheck on P(bad) ≥ 0.05, which is only possible because surya's
   `OCRErrorDetectionResult` returns `scores` as well as argmax.

Plus `origin_operator` from the runtime contract, so a free structure re-extraction cannot delete
LLM-derived rows it does not own.

`raw_label` survives canonicalization (surya keeps it, marker drops it — PART D #16).

Document-level confidence keeps docling's shape verbatim: per-page `{parse, layout, table, ocr}`,
`nanmean` for optimistic components and a low quantile for pessimistic ones, ordinal grades published
and numeric scores internal. Difference from docling: **`table_score` is actually computed**, from the
`recon` scores of the page's tables, or it is NULL — never a declared-and-never-assigned field that
grades a document EXCELLENT.

---

## 9. Schema evolution

1. **One machine-readable schema, code generated from it.** `owdoc.schema.json` (JSON Schema 2020-12)
   is the source of truth; a generator emits the Python dataclasses, the SQL DDL, the msgpack field
   maps, and the Parquet field maps. A field cannot exist in the reader and not the writer.
2. **No inheritance.** One `Node` struct with a `kind` tag and a discriminated payload. A class
   hierarchy (`DocItem`/`TextItem`/`TableItem`) makes adding a kind a breaking change for every
   `isinstance` in every consumer and ties the wire format to Python's MRO.
3. **Enum values are strings.** marker's `BlockTypes(str, Enum)` with `auto()` has values `"1"`,
   `"2"`, …, so *"any JSON that serializes the raw value is garbage"* (`mine-parse.md` §A2.3). CI test.
4. **Closed vocabulary with an `x-` escape hatch.** `kind` is a closed-set member **or** a string
   beginning `x-`. An unknown non-`x-` kind is a hard read error (fail closed); an `x-` kind is
   preserved verbatim and treated as `Text` by serializers. A new driver has somewhere to put
   something without forking the vocabulary.
5. **`ext: map<namespace, bytes>` on every node and relation**, opaque and round-trip-preserved. A
   reader that does not understand `ext["ow.pptx.v1"]` must write it back unchanged. This is the one
   field that makes round-trip survive version skew.
6. **Additive-only within a major, enforced in CI.** `owdoc-schema diff` fails a PR that removes a
   field, narrows a type, adds a required field, changes an existing enum value, or changes a digest
   input without bumping `digest_recipe`.
7. **Tolerant bundle load** (docling's `ConversionAssets.load()`): a missing or unparseable member
   logs and degrades; only `manifest.json` is mandatory. *"Partial forward/backward compatibility for
   free, and the environment that produced the parse travels with the parse."*

---

## 10. Serialization — three formats, three named roles, one schema

The question as posed (JSON vs msgpack vs Arrow/Parquet vs protobuf) is a false choice: there are
three different jobs and no format does all three.

| role | format | why |
|---|---|---|
| **Store** — queried, mutated, incrementally written | **SQLite, WAL, one file per corpus** | Random access, partial reads, single-node updates, transactions, FTS5. codegraph's measured envelope: **70,000 files / 2,000,000 symbols / 6,400,000 relationships in under 12 minutes on a 2-core 6 GB VPS**; 10M blocks lands a 10–40 GB file. Neither JSON nor Parquet can update one node. |
| **Interchange / archive** — `.owdoc` bundle | **ZIP (stored, not deflated) of msgpack shards + one JSON manifest** | docling's ZIP-of-one-JSON-per-component envelope with tolerant load, with the *payload* switched to msgpack and an interned field-name table. Shard per 1M nodes so load streams. Manifest stays JSON so a human and `less` can read it. |
| **Analytics / bulk export** | **Parquet, one file per table** | Columnar scans, DuckDB/Spark, embedding pipelines. Write-once, so an **export**, never the store. |

**Why not JSON as the archive payload.** Arithmetic, not a citation, and flagged as such: `owdoc`'s
node record is ~30 fields; JSON repeats every field name in every record. At ~1.2–2.5 KB/node that is
**12–25 GB for 10M nodes**, and the load is CPU-bound on number and string decoding. msgpack with an
interned key table lands ~200–400 B/node ⇒ **2–4 GB**. This projection must be measured against a
real 5,000-page fixture before the format is frozen; the *structural* argument (field names repeated
10M times, no streaming shard boundary, no binary geometry) stands regardless of where the constant
lands.

**Why not Parquet/Arrow as the store.** graphrag's update path is the counter-example and it is
measured in its own repo: `TableProvider.write_dataframe(name, df)` rewrites a whole table, there is
no row-level update path anywhere, and an update needs **three live table providers at once**, i.e.
*"three full copies of every table on disk during an update"* (`mine-graph.md` §1.10). Adding one
document to a 50 GB index copies 50 GB (`mine-runtime.md` §2.7). Arrow stays as an **optional
in-process batch accelerator behind a capability probe**, never a base dependency — the base install
has a 250 MB budget.

**Why not protobuf as the primary.** (a) It forces a second schema language beside JSON Schema, and
the whole point of §9.1 is one source of truth. (b) proto3 collapses absent and default, and `owdoc`
has at least three places where "unset" is semantically load-bearing and named as a bug when
collapsed: `score` vs `0.0`, `byte_offset` vs unset (`mine-graph.md` §4.2.2), and `trust` with no
default. `optional` mitigates it only if every future author remembers, which is not an invariant.
(c) It buys nothing over msgpack-with-interned-keys because we are not doing per-node RPC. If an RPC
surface later needs proto, it is **generated** from `owdoc.schema.json` like everything else.

---

## 11. Memory and streaming for a 5,000-page document

**The invariant: `Doc` is a handle, not a payload. Nothing in the model can hold a decoded image, a
page's raw glyph array, or the whole node list.**

- `Doc` holds `{doc_uid, source, manifest, store}` — O(1), under 10 KB regardless of page count.
- `doc.nodes(...)`, `doc.children(...)`, `doc.rels(...)` return **cursors**, never lists.
- Drivers write through a `NodeSink` that commits every N nodes in one transaction. Nothing
  accumulates; the caller never batches.
- Page batching and release copied from docling's `_build_document` (`base_pipeline.py:239-325`):
  `page_batch_size = 4`, per-page backend unloaded and image cache dropped as soon as the batch is
  consumed, partially-initialized pages filtered out rather than left to assert downstream, and a
  document timeout that produces `PARTIAL_SUCCESS` rather than an exception.
- Bulk-load window from codegraph: drop and recreate the non-identity indexes around a full parse —
  measured **2.8 s → 1.1 s** inserting a 224k-edge set, ~0.3 s to recreate.
- WAL discipline is not optional at this size: `busy_timeout` set **before** `journal_mode`
  (codegraph #238), and the WAL valve with its futility latch, because default autocheckpointing
  during a bulk index is **~95% of all disk I/O** (19+ min → 45 s on 150-IOPS storage) and an
  un-valved run has been observed producing **22 GB of WAL and an OOM-kill**.

**Stated budget for the flagship case, with the arithmetic.** 5,000-page A4 PDF, 192 DPI, single
worker, ~120 nodes/page ⇒ ~600k nodes:

| item | bytes |
|---|---|
| 4 decoded page images @ 192 DPI A4 RGB (1587×2245×3) | ~43 MB |
| pdfium/pdftext page objects for those 4 pages | ~50–150 MB |
| node write buffer (10k nodes × ~1 KB) | ~10 MB |
| inference client (thin predictor, weights out of process — surya's pattern) | ~50 MB |
| Python interpreter + deps | ~150 MB |
| **target peak RSS** | **≤ 1.5 GB** |
| store on disk (~600k × ~600 B + FTS) | ~400–600 MB |
| all 5,000 page renders if you rendered them (you do not) | ~7.5 GB — which is why rendering follows routing |

`I17` below makes the 1.5 GB a CI test against a generated 5,000-page fixture, not a hope.

---

## 12. Costs, stated

- **Engineering:** ~10–14 engineer-weeks for L2 alone — schema + generator, SQL DDL + migrations,
  `NodeSink`, span algebra, `Quad`, `GridBuilder`, reconciliation + `RebindReport`, three serializers
  (SQLite / bundle / Parquet), the DoclingDocument import+export driver, and the invariant test suite.
  Against ~2 weeks to `pip install docling-core` and subclass. **The 8–12 week delta is the price of
  not having the pivot type defined outside the repository.**
- **Runtime:** fixed-point conversion is negligible; blake3-128 at ~1–3 GB/s makes a full-document
  digest pass seconds for 600k nodes; the four provenance axes add ~40 B/node (~400 MB at 10M nodes,
  ~4% of a 10 GB store).
- **Dependency weight:** `omniweave-core` = `msgpack`, `blake3`, stdlib `sqlite3`, plus dataclasses.
  Target < 30 MB installed. No torch, no numpy required.
- **Operational:** a schema registry and a `digest_recipe` version to maintain forever; `ext`
  namespaces to register; a reconciliation pass that must be held to full-rebuild equivalence in CI;
  the WAL valve to operate.

---

## 13. Failure modes, honestly

1. **The input that breaks it: one logical table spanning 4,800 pages with merged header cells.** The
   grid is dense, so anydoc's `MAX_GRID_SLOTS = 4_000_000` (verified, `anydoc/src/package/limits.rs:27`)
   binds. Per-page fragments keep each grid small, but the *rendered* cross-page merge is unbounded
   and must itself be capped, returning a typed `OW_RESOURCE_LIMIT{limit: grid_slots, value}` that
   names which knob would need raising. A legitimate outsized document therefore fails loudly rather
   than silently truncating — and that is the correct trade, but it is a real refusal.
2. **Reconciliation churn on a re-segmenting driver upgrade.** If a new driver splits one paragraph
   into two, neither digest nor path matches, and every annotation, embedding and edge in that region
   is orphaned. There is no automatic fix. The mitigation (quarantine on low match rate) converts a
   silent corruption into a blocked upgrade, which is better and still costs a human.
3. **`ext` becomes a shadow schema.** In three years something load-bearing will live in
   `ext["ow.pptx.v1"]` with no validator behind it. Registered namespaces with an owner and a schema
   catch omniweave's own; third-party namespaces are preserved and unchecked. That residual is real.
4. **Fixed-point geometry quantizes at 1/1000 pt = 0.35 µm.** Irrelevant for documents, wrong for CAD.
   Named so nobody re-litigates it in year three.
5. **`SourceSpan` genuinely does not exist for PDF.** The verbatim-bytes promise the serve layer wants
   to make is unavailable there, and the capability declaration is the only thing stopping us from
   making it anyway.
6. **A `digest_recipe` bump invalidates every content-addressed cache in the fleet.** Budgeted as an
   at-most-annual, migration-serviced operation, and only affordable because digest inputs are
   restricted to stored fields.
7. **Flat + parent pointers makes a full render a sort.** `ord_path` solves the read path but must be
   rebalanced under pathological interactive insertion. A re-parse writes it fresh, so only a live
   editing surface hits it — and that surface does not exist yet, which means the cost is deferred,
   not avoided.
8. **Two concurrent writers.** Excluded by the runtime work-table claim, not by the model. Bypassed,
   `busy_timeout` and the UNIQUE constraints produce loud failures rather than corruption — but they
   do produce failures.
9. **A 10M-block corpus with 400 near-identical footers per document** dedupes beautifully on
   `content_digest` and then makes `node_digest` index scans hot. Measured before the index list is
   frozen; the escape hatch is a partial index, not a schema change.

---

## 14. Invariants and how each is enforced

| # | invariant | enforced by |
|---|---|---|
| I1 | Exactly one spine parent; no cycles | FK + `CHECK(parent_uid <> node_uid)`; CI validator recursive-CTE cycle query |
| I2 | Sibling order total and unique | `UNIQUE INDEX node(doc_uid, IFNULL(parent_uid,-1), ord)` — the `IFNULL` sentinel is mandatory because SQL NULLs are each distinct (codegraph #1034) |
| I3 | `ord_path` is prefix-ordered by the tree | write-time assertion in `NodeSink.flush` + CI validator |
| I4 | Enum values are their names, never ordinals | schema-generated; CI test rejecting `auto()`-style values (marker `BlockTypes`) |
| I5 | No span without its space's identity | three distinct frozen types; paired-NULL `CHECK`s; semgrep rule banning bare `int` offsets in span positions |
| I6 | One stored geometry frame; driver origin recorded | `Quad.from_driver` is the only public constructor; round-trip test per driver |
| I7 | Every grid position is exactly one of Origin/Covered, and every Covered resolves to a spanning Origin | `grid_slot` `CHECK`s (local half) + `GridBuilder` as sole constructor + CI validator query (global half) |
| I8 | HTML/markdown are never primary | no `html` field in the schema; CI grep that no serializer output is written into `node.text` |
| I9 | A producer that computes a confidence writes it, with its scale | `CHECK((score IS NULL)=(score_kind IS NULL))`; per-driver conformance test against its capability declaration |
| I10 | Missing `trust` ⇒ weakest; migrations may only downgrade | `trust` NOT NULL with no default; migration lint rejecting any UPDATE that moves trust toward `extracted` |
| I11 | `cite` in prompts only; `uid` in FKs only; `path` in URLs/CLI only | semgrep rules on the prompt-builder and HTTP router; test asserting no rendered prompt contains a `uid` |
| I12 | `ext` survives read→write byte-identically | property test over a fuzz corpus |
| I13 | Unknown non-`x-` `kind` is a hard read error | reader; test with a synthetic future bundle |
| I14 | Additive-only schema evolution within a major | `owdoc-schema diff` CI gate against every released version |
| I15 | Only stored fields may be digest inputs | `x-digest: true` schema annotation; generator refuses a recipe referencing a derived field |
| I16 | `Doc`/`Node` hold no bytes and no images | semgrep rule banning `Image`/`bytes` fields; size-walk test on a 5,000-page fixture (< 64 KB) |
| I17 | Peak RSS ≤ 1.5 GB on the 5,000-page fixture at 192 DPI, one worker | CI perf test with RSS sampling on a generated fixture |
| I18 | One writer per store | runtime work-table claim; SQLite `busy_timeout` + UNIQUE constraints make contention loud |
| I19 | Failure is a field, not an exception; one bad page never aborts the other 4,999 | `status ∈ {ok, partial, failed, skipped}` + per-page `ErrorItem`; timeout ⇒ `partial` |
| I20 | Every driver publishes a capability declaration and downstream features check it, not the runtime | declaration is a required manifest member; feature gates read it; test per driver asserting the declaration matches observed output |

---

## Concrete shape

### 15.1 The store DDL (generated from `owdoc.schema.json` — do not hand-edit)

```sql
-- ==== pragmas: order is load-bearing (codegraph #238: journal_mode before busy_timeout crashes
--      on a contended open) ====
PRAGMA busy_timeout = 5000;      -- FIRST
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;      -- 64 MB
PRAGMA mmap_size  = 268435456;   -- 256 MB

CREATE TABLE source (
  source_uid      INTEGER PRIMARY KEY,
  uri             TEXT    NOT NULL,
  sha256          BLOB    NOT NULL,   -- raw bytes exactly as delivered
  norm_sha256     BLOB    NOT NULL,   -- load-bearing bytes: PDF /ModDate+/ID, OOXML cp:revision /
  norm_recipe     INTEGER NOT NULL,   --   w:rsid* / TotalTime, MD frontmatter, EXIF stripped first
  byte_len        INTEGER NOT NULL,
  media_type      TEXT    NOT NULL,
  format          TEXT    NOT NULL,
  format_evidence TEXT    NOT NULL,   -- JSON: magic bytes, content probe, OPC root element
  UNIQUE(sha256, norm_recipe)
);

CREATE TABLE producer (                -- the reproduction tuple, as a row, not a string
  producer_uid   INTEGER PRIMARY KEY,
  driver         TEXT NOT NULL,
  driver_ver     TEXT NOT NULL,
  model_id       TEXT, model_rev TEXT, -- model_rev = exact commit sha; "main" is a lint error
  runtime        TEXT, runtime_ver TEXT,
  prompt_ver     TEXT,
  options_digest BLOB NOT NULL,
  UNIQUE(driver, driver_ver, IFNULL(model_id,''), IFNULL(model_rev,''),
         IFNULL(runtime,''), IFNULL(runtime_ver,''), IFNULL(prompt_ver,''), options_digest)
);

CREATE TABLE doc (
  doc_uid       INTEGER PRIMARY KEY,
  source_uid    INTEGER NOT NULL REFERENCES source ON DELETE CASCADE,
  schema_ver    TEXT    NOT NULL,                 -- "owdoc/1"
  digest_recipe INTEGER NOT NULL,
  status        TEXT    NOT NULL CHECK(status IN ('ok','partial','failed','skipped')),
  generation    INTEGER NOT NULL,                 -- monotonic int, never a wall clock
  root_uid      INTEGER,
  created_at_ns INTEGER NOT NULL,
  manifest      BLOB    NOT NULL   -- msgpack: capabilities, confidence, timings, counts, errors
);

CREATE TABLE page (
  doc_uid    INTEGER NOT NULL REFERENCES doc ON DELETE CASCADE,
  page       INTEGER NOT NULL,     -- ORIGINAL source index, never the batch index (marker)
  w_mpt      INTEGER NOT NULL, h_mpt INTEGER NOT NULL,   -- 1/1000 pt
  rotation   INTEGER NOT NULL,
  method     TEXT    NOT NULL,     -- text_layer|ocr_page|ocr_block|vlm_page|native
  ocr_error_score REAL,            -- the SCORE, not the label (surya)
  parse_score REAL, layout_score REAL, table_score REAL, ocr_score REAL,
  PRIMARY KEY (doc_uid, page)
) WITHOUT ROWID;

CREATE TABLE node (
  node_uid       INTEGER PRIMARY KEY,        -- durable surrogate. FKs point here and nowhere else.
  doc_uid        INTEGER NOT NULL REFERENCES doc ON DELETE CASCADE,
  parent_uid     INTEGER          REFERENCES node(node_uid) ON DELETE CASCADE,
  ord            INTEGER NOT NULL,
  ord_path       BLOB    NOT NULL,           -- gap-allocated, lexicographic; parent is a prefix
  path           TEXT    NOT NULL,           -- '/p12/tbl0/r3/c2'  (URLs, CLI, logs)
  cite           TEXT    NOT NULL,           -- 'd7#412'           (prompts ONLY)
  kind           TEXT    NOT NULL,           -- closed vocab, or 'x-*'
  layer          TEXT    NOT NULL CHECK(layer IN ('body','furniture','annotation','hidden')),
  title          TEXT,                       -- NULL for text nodes: a chunk is addressed, not named
  content_digest BLOB    NOT NULL,           -- blake3-128, merkle; geometry NOT an input
  layout_digest  BLOB    NOT NULL,           -- content_digest + page + geometry @ whole-pt
  revision       INTEGER NOT NULL DEFAULT 0,
  -- geometry: stored frame is always (TOPLEFT, 1/1000 pt, unrotated page)
  page           INTEGER,
  quad           BLOB,                       -- 8 x i32 LE, or NULL
  quad_origin    TEXT    CHECK(quad_origin IN ('topleft','bottomleft')),  -- what the driver gave
  -- text
  text           TEXT,                       -- fully resolved (styles/numbering/refs collapsed)
  -- the three span spaces. never mixed. nullable as a whole, never zero-defaulted.
  src_part       TEXT,   src_byte_start  INTEGER, src_byte_len  INTEGER, src_decode TEXT,
  glyph_extractor TEXT,  glyph_start     INTEGER, glyph_len     INTEGER,
  -- provenance: four axes
  producer_uid   INTEGER NOT NULL REFERENCES producer,
  method         TEXT    NOT NULL,           -- native|text_layer|ocr_page|ocr_block|vlm_page|
                                             -- llm_repair|heuristic|user
  trust          TEXT    NOT NULL CHECK(trust IN ('extracted','inferred','ambiguous')),
  score          REAL,   score_kind TEXT,    -- the scale is named, or both are NULL
  raw_label      TEXT,                       -- the model's own string, pre-canonicalisation
  origin_operator TEXT   NOT NULL,           -- ownership, NOT trust (mine-runtime §3.4)
  payload        BLOB,                       -- msgpack, kind-discriminated
  ext            BLOB,                       -- msgpack map<ns,bytes>, round-trip preserved
  CHECK (parent_uid IS NULL OR parent_uid <> node_uid),
  CHECK ((src_byte_start IS NULL) = (src_byte_len IS NULL)),
  CHECK ((glyph_start   IS NULL) = (glyph_len   IS NULL)),
  CHECK ((score         IS NULL) = (score_kind  IS NULL)),
  CHECK (quad IS NULL OR (page IS NOT NULL AND quad_origin IS NOT NULL))
);
-- IFNULL sentinel is mandatory: SQL NULLs are each distinct, so a nullable natural key
-- silently admits duplicates (codegraph #1034).
CREATE UNIQUE INDEX node_sibling_ord ON node(doc_uid, IFNULL(parent_uid,-1), ord);
CREATE UNIQUE INDEX node_path_uq     ON node(doc_uid, path);
CREATE UNIQUE INDEX node_cite_uq     ON node(doc_uid, cite);
CREATE INDEX node_ordpath ON node(doc_uid, ord_path);            -- full render = one scan
CREATE INDEX node_page    ON node(doc_uid, page, ord_path);
CREATE INDEX node_cdig    ON node(doc_uid, content_digest);      -- reconciliation
CREATE INDEX node_kind    ON node(doc_uid, kind, ord_path);
CREATE INDEX node_review  ON node(doc_uid, page) WHERE trust <> 'extracted';   -- partial

CREATE TABLE rel (                             -- everything the spine cannot express
  doc_uid   INTEGER NOT NULL REFERENCES doc ON DELETE CASCADE,
  src_uid   INTEGER NOT NULL REFERENCES node(node_uid) ON DELETE CASCADE,
  dst_uid   INTEGER NOT NULL REFERENCES node(node_uid) ON DELETE CASCADE,
  kind      TEXT    NOT NULL,   -- caption_of|continues_from|note_ref|anchor_target|heading_of|
                                -- derived_from|supersedes|reads_after
  producer_uid INTEGER NOT NULL REFERENCES producer,
  trust     TEXT    NOT NULL, score REAL, score_kind TEXT,
  origin_operator TEXT NOT NULL,
  ext       BLOB
);
CREATE UNIQUE INDEX rel_identity ON rel(src_uid, dst_uid, kind, producer_uid);
CREATE INDEX rel_dst ON rel(dst_uid, kind);

CREATE TABLE grid_slot (                       -- the exactly-once invariant, half of it in SQL
  table_uid  INTEGER NOT NULL REFERENCES node(node_uid) ON DELETE CASCADE,
  row        INTEGER NOT NULL,
  col        INTEGER NOT NULL,
  cell_uid   INTEGER REFERENCES node(node_uid) ON DELETE CASCADE,  -- NOT NULL <=> Origin
  origin_row INTEGER, origin_col INTEGER,                          -- NOT NULL <=> Covered
  PRIMARY KEY (table_uid, row, col),
  CHECK ((cell_uid IS NULL) = (origin_row IS NOT NULL)),           -- exactly one of the two
  CHECK ((origin_row IS NULL) = (origin_col IS NULL))
) WITHOUT ROWID;

CREATE TABLE asset (
  asset_uid  INTEGER PRIMARY KEY,
  sha256     BLOB NOT NULL UNIQUE,
  media_type TEXT NOT NULL,
  byte_len   INTEGER NOT NULL,
  store_ref  TEXT NOT NULL,        -- 'cas://ab/cd/abcd…'  -- bytes are NEVER inline
  origin_part TEXT,                -- anydoc: which package part / stream (PART D #15)
  licence TEXT, licence_url TEXT, spdx TEXT, source_url TEXT, retrieved_at_ns INTEGER
);
CREATE TABLE node_asset (
  node_uid  INTEGER NOT NULL REFERENCES node ON DELETE CASCADE,
  asset_uid INTEGER NOT NULL REFERENCES asset,
  role      TEXT    NOT NULL,      -- image|page_render|embedded_object|thumbnail
  dpi       INTEGER, colorspace TEXT
);
CREATE UNIQUE INDEX node_asset_uq ON node_asset(node_uid, asset_uid, role, IFNULL(dpi,-1));

CREATE TABLE node_history (        -- retirement, instead of durable tombstones
  node_uid      INTEGER PRIMARY KEY,
  doc_uid       INTEGER NOT NULL,
  retired_at_ns INTEGER NOT NULL,
  superseded_by INTEGER,           -- NULL = retired with no successor
  reason        TEXT NOT NULL      -- reparse_resegmented|driver_upgrade|source_deleted
);

CREATE TABLE doc_error (           -- failure is a field, not an exception
  doc_uid   INTEGER NOT NULL REFERENCES doc ON DELETE CASCADE,
  code      TEXT NOT NULL,         -- OW_ENCRYPTED | OW_NEEDS_OCR | OW_RESOURCE_LIMIT | ...
  component TEXT NOT NULL, module TEXT NOT NULL,
  page      INTEGER, message TEXT NOT NULL, detail BLOB
);
```

### 15.2 The public Python API — the only module a consumer imports

```python
# omniweave.doc — no torch, no numpy, no pillow required.
Kind   = Literal[  # closed, STRING values, generated. Adding a member is additive; 'x-*' is legal.
  "document","page","title","heading","paragraph","text","list","list_item","table","table_cell",
  "figure","picture","caption","equation","code","footnote","endnote","note_ref","anchor",
  "page_header","page_footer","toc","toc_item","form","form_field","key_value","reference",
  "bibliography","handwriting","chemical","diagram","checkbox","rule","container","x-*"]
Layer  = Literal["body","furniture","annotation","hidden"]
Trust  = Literal["extracted","inferred","ambiguous"]
Method = Literal["native","text_layer","ocr_page","ocr_block","vlm_page","llm_repair",
                 "heuristic","user"]

class Quad(NamedTuple):            # fixed point 1/1000 pt, TOPLEFT, unrotated page frame
    x0:int; y0:int; x1:int; y1:int; x2:int; y2:int; x3:int; y3:int
    def rect(self) -> tuple[int,int,int,int]: ...          # a VIEW, computed
    @classmethod
    def from_driver(cls, pts: Sequence[tuple[float,float]], *,
                    origin: Literal["topleft","bottomleft"],
                    page_h_mpt: int, rotation: int) -> "Quad": ...   # the ONLY public ctor

# --- three span spaces. distinct types. no implicit conversion, ever. ---
@dataclass(frozen=True, slots=True)
class SourceSpan:  part: str | None; byte_start: int; byte_len: int; decode: str
@dataclass(frozen=True, slots=True)
class GlyphSpan:   page: int; extractor: str; char_start: int; char_len: int
@dataclass(frozen=True, slots=True)
class RenderSpan:  render_id: str; char_start: int; char_len: int

class SpanMap(Protocol):           # emitted BY the serializer that produced the render
    render_id: str
    def to_glyph(self, s: RenderSpan) -> list[tuple[int, GlyphSpan | None]]: ...
    def to_render(self, node_uid: int, s: GlyphSpan | None) -> list[RenderSpan]: ...

@dataclass(frozen=True, slots=True)
class Node:                        # a value object. holds no bytes, no images, no children.
    uid: int; doc: int; parent: int | None; ord: int
    path: str; cite: str; kind: str; layer: str; title: str | None
    content_digest: bytes; layout_digest: bytes; revision: int
    page: int | None; quad: Quad | None; quad_origin: str | None
    text: str | None
    src: SourceSpan | None; glyph: GlyphSpan | None
    producer: int; method: str; trust: str
    score: float | None; score_kind: str | None; raw_label: str | None
    origin_operator: str
    ext: Mapping[str, bytes]
    def as_table(self) -> "Table": ...          # raises unless kind == 'table'
    def as_list(self)  -> "ListSpec": ...

class Doc:                         # A HANDLE. O(1) in page count. < 10 KB for 5,000 pages.
    uid: int; source: "Source"; schema_ver: str; digest_recipe: int
    status: Literal["ok","partial","failed","skipped"]
    capabilities: "Capabilities"; confidence: "ConfidenceReport"
    # --- addressing ---
    def node(self, uid: int) -> Node: ...
    def by_path(self, path: str) -> Node | None: ...
    def by_cite(self, cite: str) -> Node | None: ...
    # --- traversal: CURSORS, never lists ---
    def nodes(self, *, page: int | None = None, kind: Iterable[str] | None = None,
              layer: Iterable[str] = ("body",), under: int | None = None,
              trust_at_most: str | None = None) -> Iterator[Node]: ...
    def children(self, uid: int) -> Iterator[Node]: ...
    def rels(self, uid: int, kind: str | None = None, *, inbound: bool = False
             ) -> Iterator["Rel"]: ...
    def pages(self) -> Iterator["Page"]: ...
    # --- assets: lazy, streamed, never bytes ---
    def page_render(self, page: int, dpi: int) -> "AssetRef": ...   # may render on demand
    def asset(self, ref: "AssetRef") -> BinaryIO: ...
    # --- renders always come with their span map ---
    def render(self, serializer: str, **opts) -> tuple[Iterator[str], SpanMap | None]: ...

class NodeSink(Protocol):          # every driver writes through this. it commits; it never returns
    def open_page(self, page: int, size_mpt: tuple[int,int], rotation: int) -> "PageSink": ...
    def note(self, kind: Literal["footnote","endnote"], parent: int | None) -> "PageSink": ...
    def asset(self, data: BinaryIO, media_type: str, origin_part: str | None,
              licence: str | None = None) -> int: ...
    def rel(self, src: int, dst: int, kind: str, *, trust: str, score: float | None = None) -> None
    def error(self, e: "OwError", page: int | None = None) -> None: ...
    def flush(self) -> None: ...   # one transaction per N nodes. the caller never batches.

class PageSink(Protocol):
    def node(self, kind: str, *, layer: str = "body", parent: int | None = None,
             text: str | None = None, quad: Quad | None = None,
             src: SourceSpan | None = None, glyph: GlyphSpan | None = None,
             method: str, trust: str, score: float | None = None, score_kind: str | None = None,
             raw_label: str | None = None, payload: Mapping | None = None,
             ext: Mapping[str, bytes] | None = None) -> int: ...
    def grid(self, table_uid: int) -> "GridBuilder": ...
    def close(self, *, method: str, ocr_error_score: float | None = None,
              scores: Mapping[str, float] | None = None) -> None: ...
```

### 15.3 Tables — `GridBuilder` is the sole constructor

```python
@dataclass(frozen=True, slots=True)
class Cell:    uid:int; row:int; col:int; row_span:int; col_span:int
@dataclass(frozen=True, slots=True)
class Covered: origin_row:int; origin_col:int
Slot = Cell | Covered

class Table:                        # private ctor. GridBuilder.build() is the only way in.
    header_rows: int
    kind: Literal["data","layout"]  # anydoc: a layout table unwrapped by the SERIALIZER, not here
    recon: tuple[str, float] | None # (strategy, score) — NEVER discarded (PART D #9)
                                    # strategy in {native_xml, span_x0, span_center, proj_1,
                                    #              proj_3, proj_10, tableformer, vlm}
    n_rows: int; n_cols: int        # n_cols = max(len(row)); rows may be RAGGED
    def slot(self, r:int, c:int) -> Slot | None
    def origin(self, r:int, c:int) -> Cell | None       # resolves Covered -> its Origin
    def up(self,r,c)->Cell|None; def down(self,r,c)->Cell|None
    def left(self,r,c)->Cell|None; def right(self,r,c)->Cell|None
    def top_heading(self,c)->Cell|None; def left_heading(self,r)->Cell|None
    # ^ exactly olmOCR-Bench TableTest's relational assertions, answerable in O(1)
    # NOTE: there is no .html and no .markdown. those are renders.

class GridBuilder:
    def place(self, r:int, c:int, cell_uid:int, row_span:int=1, col_span:int=1) -> None
        # registers covered positions; later placements skip them; overlapping spans are
        # CLAMPED, never double-counted (anydoc GridBuilder)
    def build(self, *, header_rows:int, kind:str,
              recon: tuple[str,float] | None) -> Table
        # asserts: every (r,c) in [0,n_rows)x[0,len(row)) is exactly one of Origin|Covered,
        #          and every Covered points at an Origin whose span reaches it.
```

### 15.4 The digest recipe (versioned; `digest_recipe: 1`)

```
canonical(x) = msgpack, map keys sorted bytewise, no NaN/Inf, geometry as i32 only,
               and THREE distinct encodings for absent / null / "" .

content_digest = blake3_128(canonical([
    kind, layer,
    nfc(text) or None,                      # NFC-normalised; None != ""
    canonical(payload),
    [child.content_digest for child in children in ord order],   # merkle
]))

layout_digest  = blake3_128(canonical([
    content_digest, page,
    quad quantised to whole points,         # kills driver jitter; ppt-master's canonicalise-then-hash
]))

NOT digest inputs: node_uid, cite, path, ord, ord_path, revision, producer, method,
                   trust, score, raw_label, origin_operator, ext, spans.
  - spans out: a driver changing byte accounting must not orphan unchanged content.
  - producer out: two drivers producing identical content collide ON PURPOSE (graphify ids.py).
  - ext out: a third party stamping an annotation must not invalidate every cache entry.
CONSTRAINT (I15): every digest input is a STORED field, so a recipe bump is serviced by a
                  re-digest pass, never a re-parse.
```

### 15.5 The `.owdoc` interchange bundle

```
report.owdoc                          # ZIP, entries STORED (not deflated) for mmap-friendly reads
├── manifest.json                     # the ONLY mandatory member. human-readable.
│     { "schema": "owdoc/1", "digest_recipe": 1, "status": "partial",
│       "source": {...}, "producers": [...], "capabilities": {...},
│       "counts": {"nodes": 612_004, "rels": 41_882, "assets": 3_119},
│       "confidence": {...}, "timings_ms": {...}, "shards": {"nodes": 1, "rels": 1} }
├── nodes/000000.msgpack              # one shard per 1,000,000 nodes, ord_path order, interned
├── rels/000000.msgpack               #   field-name table in the shard header
├── grid/000000.msgpack
├── assets/manifest.msgpack
├── assets/cas/ab/cd/abcd….png        # content-addressed, deduped
├── errors.json
├── spanmaps/<render_id>.msgpack      # optional, per serializer
└── source/0001.bin                   # optional: the original bytes, exactly as delivered
```
`load()` tolerates missing and unparseable members (docling `ConversionAssets.load()`): logs a
`degradation`, keeps the default. Only `manifest.json` is fatal to omit.

### 15.6 Driver capability declaration (required manifest member; downstream gates read it)

```yaml
driver: owdoc.drivers.pdfium_pdftext
version: "1.4.0"
capabilities:
  source_span:    false          # <-- PDF: there is no byte range into the original for a paragraph
  glyph_span:     true           #     so serve MUST NOT claim byte-exact verbatimness here
  spatial:        line_bbox      # none|page_bbox|block_bbox|line_bbox|char_bbox
  reading_order:  char_stream    # source|char_stream|learned|model_emitted|raster
  sections:       typed_levels   # none|markdown_only|typed_levels|outline_from_source
  tables:         cells_with_spans
  math:           latex
  assets:         bytes
  asset_origin:   true           # anydoc origin_part
  notes:          linked
  confidence:     element        # none|document|page|element
  furniture:      separated      # destroyed|flagged|separated
  round_trip:     structure      # none|text|structure
  spanmap:        true           # a serializer with spanmap:none may NEVER be cited
```

### 15.7 Error taxonomy (anydoc-shaped, docling-tolerant)

```python
class OwError(Exception):
    code: str                     # stable machine code, unit-tested (Node/WASM bindings publish it)
    def is_fatal(self) -> bool    # so a "try the optional part" helper cannot swallow a limit breach

# OW_ENCRYPTED                    encryption is an OUTCOME, not a parse failure
# OW_NEEDS_OCR{pages, page_count} an error used as a ROUTING signal — it names the pages
# OW_RESOURCE_LIMIT{limit, value} names which knob would need raising; a pricing signal
# OW_UNSUPPORTED_FORMAT{format}
# OW_CORRUPT{part}
# OW_TIMEOUT{stage}               -> document status 'partial', never an abort
# OW_DRIVER_FAILED{driver}
# OW_SCHEMA_UNKNOWN_KIND{kind}    fail closed on a non-'x-' kind from the future
```

Resource limits are **fixed constants enforced at the read boundary**, adopted verbatim from
`anydoc/src/package/limits.rs` (verified in-tree): `MAX_ENTRY_BYTES = 128 MiB`,
`MAX_TOTAL_BYTES = 512 MiB`, `MAX_ENTRY_COUNT = 100_000`, `MAX_XML_DEPTH = 256`,
`MAX_XML_NODES = 2_000_000`, `MAX_GRID_SLOTS = 4_000_000`, `MAX_EXPANSION = 4_000_000`,
`MAX_EXPANSION_TEXT_BYTES = 64 MiB`, `MAX_ASSET_TOTAL_BYTES = 128 MiB`,
`MAX_RECORD_DEPTH = 64`, `MAX_RECORDS = 16_000_000`. These are the **maximum**; a tenant cap clamps
below via `min(tenant_cap, MAX_*)`. No knob widens them — `DocumentLimits.max_num_pages =
sys.maxsize` is the anti-pattern this replaces.

---

## Why I reject each alternative

**Inherit `DoclingDocument`** — §1. Five reasons, four of them checkable in this repository:
`pyproject.toml:46` (`docling-core <3.0.0`, a moving floor on the pivot type),
`pyproject.toml:48-49` (torch and torchvision as base deps), `mine-parse.md` §A1.11 (docling-core is
not vendored, so unauditable), PART D #10/#15 and §A1.6 (per-element method, asset `origin_part`, and
`table_score` are structural gaps a subclass cannot fill), and JSON-pointer array-index child
references that break on insertion — the exact property reconciliation needs. Keep it as an importer
and an export target.

**A flat block list with markdown text plus offsets** (markitdown / olmocr / omniparse shape) —
PART D #4: *"all structure, everywhere,"* unrecoverable. It forfeits citation-to-pixel, PPTX
round-trip and per-cell query in one step. markitdown is a *breadth* driver whose output must be
marked lossy-by-construction, not a model.

**A pure object tree (marker's shape) as the durable model** — needs `section_hierarchy` duplicated
onto every block, needs a second tree for furniture, cannot express caption↔figure or cross-page
table continuation without duplication, and 10M pydantic objects do not fit in memory. Its *mutation*
discipline (arena, tombstones, self-healing index) is excellent and is adopted for the in-flight
per-page arena.

**A property graph with no spine** — reading order becomes a traversal. A document has a canonical
linear order and the dominant query is "the next N body blocks"; a model that cannot serve that with
an index scan is optimizing the wrong axis.

**Parquet or Arrow as the store** — write-once. graphrag needs three full copies of every table on
disk during an update and rewrites a whole table per write (`mine-graph.md` §1.10); adding one
document to a 50 GB index copies 50 GB. Excellent as an export.

**Protobuf as the schema language** — a second source of truth, and proto3's absent/default collapse
fights a model where "unset" is load-bearing in `score`, `byte_offset` and `trust`. Generate proto
from `owdoc.schema.json` if an RPC surface ever needs it.

**Content hash as the sole identity** — collapses 5,000 identical running footers into one node, and
any edit orphans every annotation.

**Path as the sole identity** — inserting one footnote renumbers siblings and silently rebinds every
downstream index row, embedding and human review decision to the wrong content. Silent
mis-attribution is the worst available failure because nothing reports it.

**One span space with a `kind` tag instead of three types** — the type system stops being able to
prevent the conflation, and the conflation is exactly the bug (an LLM's markdown offset applied to a
glyph stream highlights the wrong characters, confidently). Three types cost three dataclasses.

**One digest instead of two** — either driver geometry jitter orphans the whole document on upgrade
(if geometry is in the reconciliation digest) or round-trip change detection cannot see a moved shape
(if it is not). Two digests, one recipe version.
