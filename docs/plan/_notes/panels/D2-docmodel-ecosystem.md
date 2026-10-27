# D2 — The canonical document model (L2 pivot)
## Panel proposal: the ecosystem-and-operator position

Author prior: adoption, third-party extensibility, agent/developer ergonomics, production
operability, total cost of ownership. Hostile to designs that are elegant internally and hostile at
the boundary.

---

## Headline

**Do not inherit `DoclingDocument`. Define `OwDoc`: a per-page append-only block *arena* with
path-like identity plus a separate content digest, three explicitly named coordinate systems
(original-container bytes / in-block chars / hash-pinned rendered view), anydoc's exactly-once table
grid whose cells are ordinary blocks, four separated provenance axes, and exactly one serialization
— a seekable ZIP of zstd-framed NDJSON (`.owdoc`) with a two-number version contract and a
mandatory unknown-field preservation test. Ship the docling ecosystem as a versioned *adapter
package*, not as a base class.**

Measured on this machine (CPython 3.11.9, pydantic 2.12.5; 200k-block sample scaled ×50, honest
varied text): a 5,000-page document is **60,000 blocks / 3.4 MB / 0.95 ms random page-range seek /
0.2 MB peak working set per frame**; a 10M-block corpus is **2.60 GB** as a SQLite block table
(3.29 GB with FTS5) with **20 µs** page fetches — against **25.3 GB** if you materialize the same
blocks as pydantic objects. The design exists to make the second number never happen.

---

## 1. Why not inherit `DoclingDocument` — the dependency and governance trap

The blueprint says "start from `DoclingDocument`… it has the widest format coverage and an existing
ecosystem". Both halves of that are true and neither is an argument for *inheritance*. Six checkable
facts:

1. **`DoclingDocument` is not in `docling`; it is in `docling-core`.** `docling/pyproject.toml:47`
   pins `docling-core[chunking] (>=2.73.0,<3.0.0)`. So the type omniweave would inherit is governed
   by a package we do not depend on directly and cannot pin tightly without fighting docling itself.
2. **`docling-core`'s *base* dependency set contains `pandas` and `typer`.** From
   `docling/uv.lock`, `docling-core 2.73.0` requires: `defusedxml, jsonref, jsonschema,
   latex2mathml, pandas (3.0.1 on py>=3.11), pillow, pydantic, pyyaml, tabulate, typer,
   typing-extensions`. A *data-model* package hard-requiring a dataframe library and a CLI framework
   is a boundary cost every consumer of omniweave's core type pays forever. The `[chunking]` extra
   that docling itself requires adds `semchunk, transformers, tree-sitter, tree-sitter-c,
   tree-sitter-javascript, tree-sitter-python, tree-sitter-typescript`.
3. **Release velocity is 8/month and the pin is a whole major.** `docling/CHANGELOG.md` has **168
   releases** from `v0.2.0` (2024-07-16) to `v2.90.0` (2026-04-17) — ≈8/month — with **24 minor
   releases in 2026 alone through April** (v2.87→v2.90 landed 2026-04-13…04-17, four minors in five
   days). Repo HEAD is `d6e0f881 chore: breaking release guards (#3347)`. Because docling accepts
   any `docling-core` 2.x, a `docling-core` minor can change the semantics of *our* public type
   between two `pip install`s of omniweave.
4. **Subclassing a pydantic model transfers their validators, their `model_config`, and their
   serialization contract to our API.** docling's own envelope writer admits where the stable
   surface is: `document.py:319` — `# For the document, ensure stable schema via export_to_dict`.
   The stable thing is a *dict projection*, not the class. Inherit the class and a `docling-core`
   3.0 is automatically a breaking change to every third-party omniweave driver.
5. **`DoclingDocument` addresses items by JSON pointer (`#/texts/1`) into flat arrays**
   (`docs/concepts/docling_document.md:23-41`). A JSON pointer is a *position in a serialized array*:
   inserting or reordering invalidates every held reference. marker runs **30 processors** mutating
   one tree and solved this with an arena + tombstones (`marker/schema/groups/page.py:173-185`); the
   parse mine calls that "the right call for a mutable parse tree". JSON-pointer identity is the
   wrong substrate for the pipeline we are actually building.
6. **The whole-document JSON is the serialization.** `ConversionAssets.save()`
   (`docling/datamodel/document.py:261-330`) writes one ZIP member per component — genuinely worth
   copying — but the document itself is a single `document.json`, and `load()` does
   `DoclingDocument.model_validate(data)` on the whole thing (`:396-400`). Measured: whole-file JSON
   load of 200k blocks is **249 ms** and materializing 10M blocks as pydantic is **25.3 GB**. There
   is no seek to page 4,700.

**What we do instead, and why it keeps the ecosystem.** `omniweave-docling` is a separate,
separately-versioned adapter package with `to_docling(OwDoc) -> DoclingDocument` /
`from_docling(DoclingDocument) -> OwDoc`, a published per-field fidelity matrix
(`fidelity.json`), and a CI job that runs against the two newest `docling-core` minors and the
newest major. It may lag a docling-core major by weeks without freezing omniweave's core. Anyone
wanting docling's serializers, chunkers, or LangChain/LlamaIndex integrations gets them with one
extra install; nobody parsing a spreadsheet installs `pandas` + `transformers` to hold a block.

Corollary, and it is the load-bearing packaging rule of this proposal:

> **`omniweave-core` depends on `pydantic` and `zstandard`. Nothing else. No torch, no onnx, no
> pandas, no pyarrow, no transformers, no HTTP client.** ≈15 MB installed. It is a CI gate
> (`test_core_import_graph.py` asserts the resolved dependency closure by name), not an aspiration.
> Compare docling's ≈2.5–3.5 GB (torch is a *base* dep) and the 250 MB Lambda-layer target from the
> risk digest.

---

## 2. Identity — both, with separated jobs, and a defect in the blueprint's own example fixed

Three identifiers, each with one job. This is not indecision; conflating any two of them is a named
bug in the mine.

| name | shape | job | stability |
|---|---|---|---|
| `DocId` | `ow:d:<b32(sha256(normalized bytes))[:26]>` | content identity of the *source document* | changes iff load-bearing bytes change |
| `BlockRef` | `<DocId>#p{page}/{ordinal}` | **the** address; the only id an LLM cites; the FK everywhere | never reused, never reassigned |
| `cid` | `sha256(canonical block content)` truncated to 16 bytes | cache key, dedup, drift proof | changes on any content edit |

- **`DocId` hashes the load-bearing bytes, not the file.** Per-format normalisers strip volatile
  metadata before hashing — Markdown frontmatter, PDF `/ModDate` + `/ID`, OOXML `cp:revision` /
  `w:rsid*` / `TotalTime`, EXIF timestamps — so a metadata-only touch does not re-bill a VLM pass
  (mine-runtime §7.5.1). A normaliser that throws falls back to raw bytes and records
  `normaliser_failed` in `Diag`. **L2 owns the registry and the `DocId` field; L5 owns the policy.**
- **`BlockRef` deliberately omits the block type.** marker's `/page/{p}/{Type}/{n}`
  (`marker/schema/blocks/base.py`, `BlockId.__str__`) is human-readable but *the type is mutable*:
  a processor promoting `Text` → `SectionHeader` changes the id, and every edge, embedding and
  citation pointing at it. Our `BlockRef` is `#p12/37`; the type is available as `block.kind` and
  `BlockRef.display()` renders `#p12/37 SectionHeader` for logs. Seven characters is short enough
  for a model to emit reliably, which is the property graphrag needed a separate `short_id` for
  (`data_model/`: `id` UUID for joins, `short_id` "the only id an LLM may cite"). We get both from
  one id because the ordinal *is* a small int.
- **`cid` is a field, never the identity.** A content-hash identity means an LLM processor fixing one
  ligature rewrites the id of that block, and therefore every graph edge, every embedding row, every
  citation already shipped in a deck. With `cid` as a field you still get: content-addressed cache
  keys, dedup of identical blocks across re-parses, and codegraph's fingerprint-proven
  back-reference ("you already have this block, unchanged since — do not re-Read"), which the serve
  mine names as its single most novel idea.

**Invariant I-ID1: `BlockRef` ordinals are allocated by `Page.alloc()` and never reused.** Deletion
is `block.removed = True` (marker's tombstone). Enforced by: `Page.blocks` is a `tuple`-typed
property with no public mutator; a CI grep gate (`no_arena_delete`) forbidding `del`/`.pop(`/`.remove(`
on it; and `checkdoc` asserting `max(ordinal) == len(blocks) - 1` on every archive read and write.

**Invariant I-ID2: exactly one parent.** A block has one `parent` and appears in exactly one
container's `structure`. Two parents makes every serializer ambiguous and every coverage metric
double-count — mine-graph §4.2.2 measured **33.4% overall / 2.28× on one file** inflation from
exactly that mistake. Multi-parent relationships live in `refs` (§4).

---

## 3. Addressing the original bytes vs the reconstructed text — three named coordinate systems

This is the part that decides whether "byte-exact, safe to Edit from" is a real promise. The serve
mine is blunt: if serve says "byte-for-byte identical to what Read returns", the pipeline must hand
back original bytes, not normalized markdown. So the model names all three coordinate systems and
never mixes them.

1. **`SourceSpan{part, start, end}` — bytes in a *named byte stream of the original container*, not
   "the file".** "Byte range in the original file" is only meaningful for flat text. `part` is a
   container-part path — `"file"`, `"word/document.xml"`, `"xl/worksheets/sheet1.xml"`,
   `"pdf:page=12/content=0"` — generalizing anydoc's per-asset `origin_part`
   (`anydoc/src/model/asset.rs`) to text. Every `part` must appear in the archive's `parts` table
   with a `sha256` and a `bytes` length, so a span is verifiable without the original file present.
2. **`CharSpan{start, end}` — character offsets into *this block's own* `text`.** docling's
   `ProvenanceItem.charspan` (`docling/backend/mspowerpoint_backend.py:132`), which the parse mine
   identifies as the one thing that makes "highlight the exact substring" possible and which marker
   lacks entirely. Used by L3 for entity spans and by annotations.
3. **`RenderSpan{view, start, end}` — offsets into a hash-pinned *named rendered view*.** A citation
   into "the reconstructed markdown" is meaningless unless you say which serializer at which version
   produced it. `view = (name, version, options_hash)`, e.g. `md/v1/7c3f`; the archive stores the
   view's `sha256` and byte length. A stale offset is therefore *detectable*, not silently wrong.

**Invariant I-SP1: a `SourceSpan` is byte-exact under the driver's declared `span_fidelity`, or it
is `None`.** `span_fidelity ∈ {exact, whitespace_normalized, none}`, declared per driver in
`Capabilities`. Enforced by a property test in the shared driver testkit: for every block with both
`text` and `source_span`, `normalize_k(part_bytes[start:end]) == normalize_k(block.text)` where `k`
is the declared level. **A driver that over-declares fails the testkit.** No guesses, ever.

**Invariant I-SP2: `0` is never a sentinel.** mine-graph §4.2.2 states it directly —
`byte_offset == 0` cannot distinguish "unset" from "starts at byte 0". All spans are nullable
structs; the SQL projection carries
`CHECK ((src_start IS NULL) = (src_end IS NULL))`.

Honest consequence: soft hyphens, ligatures, and the `-\n` joins that every PDF pipeline performs
(docling shipped "Strip soft hyphen when joining merged text elements" #3232; marker does
`text.replace("-\n","")`, listed as irrecoverable loss D#7) mean many PDF drivers will legitimately
declare `whitespace_normalized`. Citation-to-byte then degrades to citation-to-block, *visibly*, in
`Capabilities.achieved` — which is exactly the behaviour we want and the opposite of a silent lie.

---

## 4. Shape: flat arena + parent pointer + explicit order list; DAG only for references

Not a tree, not a general DAG. A **per-page arena of blocks** (flat list, append-only, ordinal ==
index) where containment is `parent: BlockRef | None` **and** `structure: [BlockRef] | None` on
containers, and *`structure` is the reading order*.

Why store the order rather than derive it: marker's measured result is that reading order is *data*
— the PDF character stream beats a learned order head **75% vs 56%** on olmOCR-bench order tests
(`marker/builders/line.py:80-82`), and native formats (DOCX/PPTX/HTML/EPUB) have a canonical order
that must never be re-inferred. A sort key cannot carry that.

Why the redundancy (`parent` *and* `structure`): they serve different query engines. `parent` is what
SQL and the graph layer need (`WHERE parent = ?`); `structure` is what serialization, chunking and
round-trip need. The redundancy costs ~8 bytes/block in the wire and is kept honest by one
validator:

**Invariant I-SH1:** for every container `c`, `structure(c)` is a permutation of
`{b : b.parent == c, not b.removed}` and `parent(structure(c)[i]) == c` for all `i`.
Enforced by `checkdoc`, which the archive writer runs **before sealing** and the reader runs by
default. Measured cost in pure Python: **236 ns/block → 14 ms for a 5,000-page document, 2.4 s for
10M blocks.** Cheap enough to be always-on; `--no-check` exists for the corpus-scale bulk path and
records `Diag{code:"integrity_unchecked"}`.

**References are a side table forming a DAG (cycles permitted, because it is not containment):**
`refs: [Ref{src, dst, role}]` with `role ∈ {caption_of, note_ref, anchor_ref, continues,
derived_from, replaces, cell_of, alt_text_of}`. Caption→figure, footnote-ref→note body,
cross-reference→heading anchor, table-continues-across-pages, and "this block was produced by an LLM
from that block" all live here. anydoc's `Inline::Anchor(AnchorId)` + `Heading{anchor}` is the
evidence that internal cross-references only survive if they are first-class.

**Furniture is a layer, never a deletion.** `layer: BODY | FURNITURE` (docling's `ContentLayer`,
set from the label at `readingorder_model.py:104-115`). HunyuanOCR's prompt telling the model to
ignore headers and footers is the counter-example: the furniture never exists, irrecoverably
(parse mine D#5). **Suppression belongs in the serializer**, and serializers take an explicit
`layers=` argument with no silently-dropping default.

---

## 5. Tables — one representation that round-trips to PPTX, chunks, and answers "which cell is above"

Adopt anydoc's grid invariant (`anydoc/src/model/table.rs`: every logical position appears exactly
once; `CellSlot::Origin(Cell)` / `CellSlot::Covered{origin_row, origin_col}`; `GridBuilder` the sole
constructor) with three changes that make it serve all three consumers:

1. **Cells are ordinary blocks in the same arena.** A cell therefore has a `BlockRef`, a `bbox`, a
   `SourceSpan`, a `producer`, a `trust` and a `score` — so citation-to-cell works, and cell content
   is `[Block]` (paragraphs, lists, nested tables) rather than a string. This is the fix for the
   worst table loss in the collection: marker's digital path sets `block.html` and `structure = []`
   (parse mine D#2), destroying per-cell polygons, spans and citability in one assignment.
2. **`slots` is a flat row-major array with `row_len: [int]`,** not `Vec<Vec<...>>`. It serializes as
   two integer arrays (great for zstd), expresses raggedness explicitly ("rows may differ in length
   when the source is ragged" — anydoc), and makes `slot(r,c)` index arithmetic.
3. **`recon: {strategy, score}` lives on the table.** marker computes a reconstruction confidence,
   uses it for the gate, and throws it away (parse mine D#9). Strategy is a closed vocabulary:
   `native_xml | span_x0 | span_center | proj_1 | proj_3 | proj_10 | tableformer | vlm | human`.

How each consumer is served:

- **PPTX round-trip.** `slots` + spans + `header_rows` + per-cell `[Block]` gives a DrawingML
  `graphicFrame` directly. Additionally the table may carry `native: NativeRef{part, sha256}` — a
  hash-pinned pointer to the original OOXML part — which is what lets ppt-master's `passthrough`
  fidelity tier (part copied byte-for-byte) exist at all, and what lets a rebuild that would drop an
  opaque relationship **refuse** rather than silently degrade.
- **Chunkable.** A chunker walks `slots` row-major with `header_rows` to repeat; docling's two knobs
  transfer verbatim — `repeat_table_header=True` and `omit_header_on_overflow=False` (the second one
  is the 40-column-table detail nobody invents in advance).
- **Queryable.** `slot(r,c)` resolves in O(1) to exactly one origin, so olmOCR-bench's relational
  `TableTest{cell, up/down/left/right, top_heading, left_heading}` assertions are arithmetic, and the
  SQL projection is one table with `UNIQUE(doc_id, table_ref, r, c)`.
- **`kind: Data | Layout`** (anydoc, unique in the collection). DOCX and HTML use tables for
  positioning; the serializer unwraps trivial layout tables, the parser never does.

**Invariant I-TB1: every `(r, c)` with `c < row_len[r]` resolves to exactly one `Origin`.** Enforced
by construction (`GridBuilder` is the only constructor; `Table.__init__` is private and clamps
overlapping spans rather than double-counting), plus a `checkdoc` pass, plus one fuzz target.
**Render HTML/markdown *from* the cells; never store HTML as the primary representation.**

---

## 6. Provenance and confidence — four axes, because four different consumers ask

The blueprint proposes two new fields, `driver` and `confidence`. That is one field too few and one
conflation too many; mine-runtime states it flatly: *"`confidence` and `origin_operator` are
different axes and must not be conflated — trust vs ownership."*

| axis | field | closed vocabulary | consumer |
|---|---|---|---|
| ownership | `prod: u16` → `producers[]` | `{operator, op_version, model_id?, prompt_version?, runtime?, runtime_version?}` | L5 stage-ownership eviction: an operator's re-run may replace **only rows it owns** |
| mechanism | `method` | `native · text_layer · ocr_page · ocr_block · vlm_page · heuristic · llm · human` | the router's selective re-parse; the cost report |
| trust | `trust` | `EXTRACTED · INFERRED · AMBIGUOUS` (graphify) | answer rendering, ranking, the review surface |
| magnitude | `score: f32?` | — | rankers and gates only |

Rules carried verbatim from the mines:

- **Missing `trust` ⇒ the weakest tier.** graphify's own `default="EXTRACTED"` is named as the bug to
  fix. Enforced in the reader: absent ⇒ `AMBIGUOUS`.
- **Migrations may only downgrade trust.** *"Alias recovery is not provenance."* Enforced by a
  migration-review checklist item and a test over fixture pairs.
- **Every producer that computes a confidence writes it to the element.** docling's `table_score` is
  *never computed* while documents are still graded EXCELLENT on it; marker's `top_k` exists only on
  layout blocks. Enforced by the testkit: a driver declaring `confidence: element` must populate
  `score` on ≥95% of non-furniture blocks in the conformance corpus.
- **Publish grades, keep scores internal** (docling's own stated API discipline). The serve
  projection exposes `trust` + an ordinal grade; `score` is available to rankers.
- **`raw_kind` survives canonicalization** (surya keeps `raw_label`; marker drops it, parse mine
  D#16). An unknown `kind` from a third-party driver becomes `kind: "Unknown"` +
  `raw_kind: "ChemicalStructure"` rather than an exception.

`producers` is interned per document as a small table referenced by `u16`. At 10M blocks that is
20 MB instead of ~1 GB of repeated structs — the kind of decision that is free at design time and
impossible to retrofit.

---

## 7. Schema evolution — the section most designs hand-wave, and my strongest ecosystem argument

An outside contributor must be able to ship a field on Tuesday without a PR to core, and an old
reader must not drop it. Five rules, each with an enforcement mechanism.

1. **Two version numbers with different meanings.** `container: int` (archive layout; bump ⇒ old
   readers *refuse*, naming the version and printing the exact upgrade command) and
   `model: "MAJOR.MINOR"` (block schema; minor ⇒ additive, readers tolerate; major ⇒ readers refuse).
   Plus `min_reader: "1.4"` written by the producer. docling's tolerant `load()` (missing and
   unparseable members survive) is the right shape and has no version *contract* — it logs an error
   and substitutes a default. We refuse instead, because silently reading a 2.0 archive as 1.x is the
   failure operators cannot detect.
2. **Unknown-field preservation is mandatory and tested.** Every record carries `x: dict[str, Any]`;
   the reader routes unrecognized keys there and the writer writes them back in sorted order.
   Property test: `write(read(bytes)) == bytes` over a fixture set of *hand-authored future-version
   archives*. This one test is what makes third-party fields safe to depend on.
3. **Namespaced extension keys.** A driver writes `x["acme.reading_order"]`. The framework never
   interprets it, never drops it; `omniweave doctor --extensions` reports key frequency across a
   corpus. Blessing a field = promoting it out of `x.` in a minor bump, with the `x.` alias readable
   for two majors.
4. **Enum values are the names, as strings.** marker's `BlockTypes(str, Enum)` with `auto()` yields
   values `"1"`, `"2"`, … so any serializer writing `.value` emits garbage (parse mine trap, C2.2).
   `Kind` is `class Kind(str, Enum): Paragraph = "Paragraph"`. Enforced by a test iterating every
   enum in the package asserting `member.value == member.name`.
5. **Short but *stable* wire keys, and a frozen key registry.** `{"i","p","k","pa","st","bb","t",
   "cs","ss","rs","m","tr","sc","pd","rm","x"}`. A key is never reused with a different meaning; the
   registry file is append-only and CI diffs it. This buys protobuf's field-number discipline
   without protobuf's toolchain.

---

## 8. Serialization and memory — the measured decision

Two artefacts with different jobs, and refusing to conflate them is the point.

**`.owdoc` — the interchange unit (one per document).** A plain ZIP (stdlib `zipfile`; `unzip -l`
works; no dependency; browsable in any OS file manager) containing one JSON per component
(docling's `ConversionAssets` shape) plus **zstd-framed NDJSON block frames**, one frame per page
range. Measured on a synthetic 5,000-page document:

| | value |
|---|---|
| blocks | 60,000 |
| archive size | **3.4 MB** (57 B/block compressed) |
| frames | 79 × 64 pages |
| random page-range seek (decompress + parse 768 blocks) | **0.95 ms** |
| peak uncompressed working set per frame | **0.20 MB** |
| full streaming decode of the document | **0.02 s** |

**The corpus store — SQLite + FTS5.** The DDL below is a *projection* of the same schema; `.owdoc`
is the unit of insert. Measured at 200k blocks and scaled to 10M:

| format | B/block | GB @ 10M blocks | one-page fetch |
|---|---|---|---|
| pydantic objects, resident | 2,527 | **25.27** | — |
| plain dicts, resident | 808 | 8.08 | — |
| JSON (orjson) | 338.5 | 3.38 | whole-file load 249 ms/200k |
| JSON + zstd-3 | 75.2 | 0.75 | frame seek 0.95 ms |
| msgpack | 296.9 | 2.97 | — |
| msgpack + zstd-3 | 72.3 | 0.72 | — |
| Parquet + zstd-3 | 54.9 | 0.55 | **42.8 ms** row-filter |
| SQLite WAL + page index | 260.3 | 2.60 | **20 µs** |
| + FTS5 external-content | 328.6 | 3.29 | MATCH top-20 **250 µs** |

Readings that decide the design:

- **msgpack buys 4%.** 72.3 vs 75.2 B/block after zstd. For 4% you give up `jq`, `curl | head`,
  reading a frame in a browser devtools console, and you add a C extension to the core. That trade is
  wrong for a framework whose adoption depends on a stranger debugging a bad parse at 2 a.m. This is
  the ecosystem argument stated as a number.
- **Parquet is 27% smaller and ~2,000× slower to point-read** (42.8 ms vs 20 µs; caveat: single
  unpartitioned file reopened per query — a partitioned dataset with row-group statistics would
  improve it materially, but it remains a scan format), and it drags `pyarrow` (~90 MB wheel) into
  core. Parquet is the right *export* (`omniweave export parquet` for analytics and for feeding
  graphrag-shaped tooling), never the representation.
- **Nothing may require whole-document materialization.** 25.3 GB at 10M blocks as pydantic is the
  number that kills the tree-of-objects design. At *document* scale it is fine — 60k × 2,527 B =
  **152 MB** — so "the whole document in RAM" is legal at document scale and illegal at corpus scale,
  and the API makes that structural.

**Invariant I-MEM1: no core read API materializes more than one frame (default 64 pages) unless the
caller passes `eager=True`.** The reader returns iterators only. Enforced by a CI gate that parses a
generated 5,000-page archive under a **256 MB RSS ceiling** and fails the build if exceeded — a
checkable condition, not a promise.

**Page images and assets are never in the model.** `Asset{id, media_type, origin_part, sha256, bytes
| ref, present}` — anydoc's `origin_part` plus a hash — and `page.image(dpi=192)` is a lazy loader
that renders or fetches on demand and caches under a `(page, dpi, renderer, renderer_version)` key.
Rendering happens **after** the routing decision and only for pages that need it — marker calls this
the cheapest optimization in its repo. **The archive is valid with `assets/` absent**
(`present: false`), which is what lets an operator ship a 3.4 MB text archive and a 400 MB image
sidecar on different storage tiers, and what makes "delete the page images for this customer" a
supported operation rather than a re-parse.

---

## 9. Status, errors, and capabilities — the operator's half of the model

**Failure is a field, not an exception**, at two levels. Document `status: OK | PARTIAL | FAILED |
SKIPPED` (docling's `ConversionStatus`) *and* `Page.status`, because anydoc's all-or-nothing
`ConvertError` fails a 5,000-page document for one bad page while docling's `PARTIAL_SUCCESS` + page
list keeps the work (parse mine A6.4). `Diag{code, severity, part?, page?, block?, message, detail}`
with a **closed code registry whose strings are stable and unit-tested**, because the codes are what
callers branch on and what the serve layer's absence contract consumes:

```
needs_ocr(pages)   encrypted        malformed(part)   missing_part(part)   io
resource_limit(limit)               truncated_by_budget                    driver_unavailable
normaliser_failed  integrity_unchecked                span_fidelity_downgraded
table_recon_low(score)              furniture_unclassified                 view_stale
```

anydoc's four rules are adopted verbatim: a stable `code()` separate from the human message, both
tested (`codes_name_every_variant`); recoverable producer quirks are recovered and *logged*, never
raised; `needs_ocr` **names the pages** so it is a routing signal; and `is_fatal()` so a
"try the optional part" helper cannot swallow a resource-limit breach.

**`Capabilities` is a field of the document, not documentation.** Every driver declares what it
produces; the document records what was `achieved` (which may be lower). Downstream features check
`doc.achieved.charspan` instead of discovering NULL at runtime. And this is the third-party
contributor's contract:

> To add a driver you implement one function and fill one struct. `pip install
> omniweave-driver-testkit && pytest --driver mydriver` runs the ~120 property tests derived from
> the invariants in this document **and fails you if you over-declare a capability.** That is the
> afternoon.

---

## Concrete shape

```python
# ============ omniweave-core: deps are pydantic + zstandard. Nothing else. ============
# omniweave/model.py

from enum import Enum
from typing import Annotated, Any, Iterator, Literal, Optional
from pydantic import BaseModel, Field

# ---- identity -------------------------------------------------------------------------
class DocId(str):                      # "ow:d:<26 chars base32 of sha256(normalized bytes)>"
    @classmethod
    def of(cls, normalized: bytes) -> "DocId": ...

class BlockRef(str):                   # "<DocId>#p{page}/{ordinal}"  -- type NOT in the id
    doc: DocId; page: int; ordinal: int
    def display(self, doc: "OwDoc") -> str: ...        # "#p12/37 SectionHeader" for logs only
    @classmethod
    def parse(cls, s: str) -> "BlockRef": ...

# ---- closed vocabularies (values == names; tested) ------------------------------------
class Kind(str, Enum):
    Title="Title"; SectionHeader="SectionHeader"; Paragraph="Paragraph"; ListItem="ListItem"
    ListGroup="ListGroup"; Table="Table"; TableCell="TableCell"; Figure="Figure"
    Caption="Caption"; Formula="Formula"; Code="Code"; Footnote="Footnote"; Reference="Reference"
    PageHeader="PageHeader"; PageFooter="PageFooter"; TableOfContents="TableOfContents"
    Form="Form"; KeyValueRegion="KeyValueRegion"; Checkbox="Checkbox"; Handwriting="Handwriting"
    Page="Page"; Note="Note"; Unknown="Unknown"          # Unknown + raw_kind = forward compat

class Layer(str, Enum):    BODY="BODY"; FURNITURE="FURNITURE"
class Method(str, Enum):
    native="native"; text_layer="text_layer"; ocr_page="ocr_page"; ocr_block="ocr_block"
    vlm_page="vlm_page"; heuristic="heuristic"; llm="llm"; human="human"
class Trust(str, Enum):    EXTRACTED="EXTRACTED"; INFERRED="INFERRED"; AMBIGUOUS="AMBIGUOUS"
class Status(str, Enum):   OK="OK"; PARTIAL="PARTIAL"; FAILED="FAILED"; SKIPPED="SKIPPED"
class Origin(str, Enum):   TOPLEFT="TOPLEFT"; BOTTOMLEFT="BOTTOMLEFT"   # origin lives IN the type

# ---- geometry and the three coordinate systems ---------------------------------------
class Bbox(BaseModel):
    o: Origin; x0: float; y0: float; x1: float; y1: float
    poly: Optional[list[tuple[float, float]]] = None      # 4+ corners when the producer has them
    def to_topleft(self, page_h: float) -> "Bbox": ...    # normalize ONCE at ingest

class SourceSpan(BaseModel):     # bytes in a NAMED part of the original container
    part: str                    # "file" | "word/document.xml" | "pdf:page=12/content=0"
    start: int; end: int
class CharSpan(BaseModel):       # chars within THIS block's own .text  (docling charspan)
    start: int; end: int
class RenderSpan(BaseModel):     # offsets into a hash-pinned named view
    view: str                    # "md/v1/7c3f"  -> manifest.views[view].sha256
    start: int; end: int

# ---- the block ------------------------------------------------------------------------
class Block(BaseModel):
    i:  int                                   # ordinal within the page arena; index == i
    p:  int                                   # ORIGINAL source page index, never a batch index
    k:  Kind
    raw_kind: Optional[str]  = None           # the producer's own string (surya raw_label)
    pa: Optional[int]        = None           # parent ordinal; None only for the page root
    st: Optional[list[int]]  = None           # ORDERED child ordinals == the reading order
    bb: Optional[Bbox]       = None
    t:  Optional[str]        = None           # reconstructed text of THIS block
    cs: Optional[CharSpan]   = None
    ss: Optional[SourceSpan] = None
    rs: Optional[RenderSpan] = None
    ly: Layer                = Layer.BODY     # furniture is a LAYER, never a deletion
    m:  Method               = Method.native
    tr: Trust                = Trust.AMBIGUOUS   # absent => WEAKEST tier, not strongest
    sc: Optional[float]      = None              # score: internal; grades are published
    pd: int                  = 0                 # index into OwDoc.producers  (u16 interned)
    cid: Optional[str]       = None               # 16-byte content digest, hex; NOT the identity
    tbl: Optional["Table"]   = None               # only when k == Kind.Table
    asset: Optional[str]     = None               # AssetId when k in {Figure, Formula(image)}
    native: Optional["NativeRef"] = None          # opaque original part, for passthrough export
    rm: bool                 = False              # tombstone. NOTHING is ever deleted.
    x:  dict[str, Any]       = Field(default_factory=dict)   # namespaced third-party fields

class NativeRef(BaseModel): part: str; sha256: str; media_type: str

# ---- tables: anydoc's exactly-once grid, cells are ordinary blocks --------------------
class Slot(BaseModel):
    kind: Literal["origin", "covered"]
    ref:  Optional[int] = None                 # origin: the cell block's ordinal
    cs:   int = 1                              # origin: col_span >= 1
    rs:   int = 1                              # origin: row_span >= 1
    o:    Optional[int] = None                 # covered: flat index of its origin slot

class Table(BaseModel):
    rows: int; cols: int
    row_len: list[int]                         # raggedness is explicit, not implied
    header_rows: int = 0
    kind: Literal["data", "layout"] = "data"   # layout tables unwrapped by the SERIALIZER
    slots: list[Slot]                          # FLAT row-major; two int arrays after zstd
    recon: Optional["Recon"] = None
    def slot(self, r: int, c: int) -> Slot: ...            # O(1), exactly one Origin
    def up(self, r, c) -> Optional[int]: ...               # olmOCR-bench TableTest, as arithmetic
    def top_heading(self, c: int) -> Optional[int]: ...

class Recon(BaseModel):
    strategy: Literal["native_xml","span_x0","span_center","proj_1","proj_3","proj_10",
                      "tableformer","vlm","human"]
    score: Optional[float] = None              # marker computes this and throws it away

# ---- the document ---------------------------------------------------------------------
class Producer(BaseModel):
    operator: str; op_version: str
    model_id: Optional[str] = None; prompt_version: Optional[str] = None
    runtime: Optional[str]  = None; runtime_version: Optional[str] = None
    weights_sha256: Optional[str] = None       # revision="main" is a LINT ERROR upstream

class Part(BaseModel):   path: str; sha256: str; bytes: int; present: bool = True
class Asset(BaseModel):
    id: str; media_type: str; origin_part: Optional[str] = None
    sha256: str; bytes: int; present: bool = True
    licence: Optional[str] = None; licence_url: Optional[str] = None; source_url: Optional[str] = None
class View(BaseModel):   name: str; version: str; options_hash: str; sha256: str; bytes: int
class Ref(BaseModel):
    src: int; dst: int; page_src: int; page_dst: int
    role: Literal["caption_of","note_ref","anchor_ref","continues","derived_from","replaces",
                  "cell_of","alt_text_of"]
class Diag(BaseModel):
    code: str; severity: Literal["error","warning","info"]
    part: Optional[str]=None; page: Optional[int]=None; block: Optional[int]=None
    message: str; detail: dict[str, Any] = Field(default_factory=dict)
class Capabilities(BaseModel):
    spatial: Literal["none","page_bbox","block_bbox","line_bbox","char_bbox"]
    charspan: bool
    span_fidelity: Literal["exact","whitespace_normalized","none"]
    reading_order: Literal["source","char_stream","learned","model_emitted","raster"]
    sections: Literal["none","markdown_only","typed_levels","outline_from_source"]
    tables: Literal["none","flat_html","cells","cells_with_spans"]
    math: Literal["none","latex","mathml"]
    assets: Literal["none","refs","bytes"]
    notes: Literal["none","inline","linked"]
    confidence: Literal["none","document","page","element"]
    furniture: Literal["destroyed","flagged","separated"]
    round_trip: Literal["none","text","structure","passthrough"]

class Page(BaseModel):
    p: int                                    # ORIGINAL index. Page ranges must cite correctly.
    w: float; h: float; rotation: int = 0
    status: Status = Status.OK
    method: Method = Method.native            # the branch actually taken for this page
    ocr_error_score: Optional[float] = None   # keep the SCORE (surya), not the label
    blocks: tuple[Block, ...]                 # ARENA: append-only, ordinal == index
    root: int = 0
    def alloc(self, **kw) -> Block: ...       # THE ONLY allocator
    def replace(self, old: int, new: Block) -> Block: ...   # append + rewrite st + old.rm = True
    def image(self, dpi: int = 192): ...      # LAZY. Rendered after routing, cached as an Asset.

class OwDoc(BaseModel):
    container: int = 1                        # archive layout; bump => old readers REFUSE
    model: str = "1.0"                        # block schema; minor additive, major refuses
    min_reader: str = "1.0"
    doc_id: DocId
    source: "Source"                          # uri, sha256_raw, sha256_normalized, normaliser,
                                              # size, media_type, detected_format, detector_evidence
    status: Status
    producers: list[Producer]
    parts: list[Part]; assets: list[Asset]; views: list[View]
    notes: list[int] = []                     # BlockRef ordinals of Kind.Note roots (anydoc)
    refs: list[Ref] = []                      # the DAG. containment is NOT here.
    toc: list["TocItem"] = []
    diags: list[Diag] = []
    declared: Capabilities; achieved: Capabilities
    confidence: "ConfidenceReport"            # per-page {parse, layout, table, ocr} + grades
    timings: dict[str, float] = {}
    x: dict[str, Any] = Field(default_factory=dict)
    # ---- streaming API: NOTHING here materializes the whole document ------------------
    def page(self, p: int) -> Page: ...                     # decompresses ONE frame
    def pages(self, lo: int = 0, hi: int | None = None) -> Iterator[Page]: ...
    def blocks(self, *, pages=None, kinds=None, layers=(Layer.BODY,)) -> Iterator[Block]: ...
    def get(self, ref: BlockRef) -> Block: ...
    def eager(self) -> "OwDoc": ...                         # opt IN to full materialization
```

```
# ============ the .owdoc archive: a plain ZIP. `unzip -l` works. ============
report.owdoc
├── manifest.json          {container, model, min_reader, doc_id, source, status,
│                           producers[], parts[], assets[], views[], declared, achieved,
│                           confidence, timings, x}          <- one JSON per component,
├── diags.json             [Diag]                               tolerant load (docling)
├── refs.json              [Ref]
├── toc.json               [TocItem]
├── frames.json            [{lo, hi, path, blocks, bytes, sha256}]   <- the seek index
├── blocks/
│   ├── 000000.ndjson.zst  pages    0..63    (768 blocks, 0.95 ms to open)
│   ├── 000001.ndjson.zst  pages   64..127
│   └── ...                79 frames for a 5,000-page document; 3.4 MB total
├── parts/                 original byte streams, hash-pinned; OPTIONAL (present: false)
│   ├── file
│   └── word/document.xml
├── assets/                raw bytes; OPTIONAL, separately deletable, separately storable
│   └── a7f3...c1.png
└── views/                 md/v1/7c3f.md + its sha256 in manifest.views
```

```sql
-- ============ the corpus projection (L4 owns the store; L2 owns this shape) ============
-- measured: 10M blocks => 2.60 GB (+ FTS5 external-content => 3.29 GB)
-- one-page fetch 20 us; FTS5 MATCH top-20 250 us
PRAGMA busy_timeout = 5000;        -- FIRST, before journal_mode (codegraph #238)
PRAGMA foreign_keys = ON;  PRAGMA journal_mode = WAL;  PRAGMA synchronous = NORMAL;

CREATE TABLE doc(
  doc_id TEXT PRIMARY KEY, uri TEXT NOT NULL, sha256_raw TEXT NOT NULL,
  sha256_norm TEXT NOT NULL, normaliser TEXT, media_type TEXT, status TEXT NOT NULL,
  model_ver TEXT NOT NULL, achieved JSON NOT NULL, indexed_at_ns INTEGER NOT NULL);

CREATE TABLE producer(
  doc_id TEXT NOT NULL REFERENCES doc ON DELETE CASCADE, pd INTEGER NOT NULL,
  operator TEXT NOT NULL, op_version TEXT NOT NULL, model_id TEXT, prompt_version TEXT,
  weights_sha256 TEXT, PRIMARY KEY(doc_id, pd)) WITHOUT ROWID;

CREATE TABLE block(
  doc_id TEXT NOT NULL REFERENCES doc ON DELETE CASCADE,
  page INTEGER NOT NULL, ord INTEGER NOT NULL,
  kind TEXT NOT NULL, raw_kind TEXT, parent INTEGER, seq INTEGER,       -- seq = index in parent.st
  layer TEXT NOT NULL DEFAULT 'BODY',
  bb_o TEXT, bb_x0 REAL, bb_y0 REAL, bb_x1 REAL, bb_y1 REAL,
  text TEXT,
  cs_start INTEGER, cs_end INTEGER,
  ss_part TEXT, ss_start INTEGER, ss_end INTEGER,
  method TEXT NOT NULL, trust TEXT NOT NULL, score REAL, pd INTEGER NOT NULL,
  cid TEXT, removed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(doc_id, page, ord),
  CHECK ((cs_start IS NULL) = (cs_end IS NULL)),      -- 0 is never a sentinel (I-SP2)
  CHECK ((ss_start IS NULL) = (ss_end IS NULL)),
  CHECK (trust IN ('EXTRACTED','INFERRED','AMBIGUOUS'))
) WITHOUT ROWID;
CREATE INDEX block_parent ON block(doc_id, page, parent, seq);
CREATE INDEX block_kind   ON block(doc_id, kind) WHERE removed = 0;
CREATE INDEX block_trust  ON block(doc_id, trust) WHERE trust <> 'EXTRACTED' AND removed = 0;

CREATE TABLE table_slot(                              -- "which cell is above this one", as SQL
  doc_id TEXT NOT NULL, page INTEGER NOT NULL, tbl INTEGER NOT NULL,
  r INTEGER NOT NULL, c INTEGER NOT NULL,
  origin_ord INTEGER NOT NULL, col_span INTEGER NOT NULL DEFAULT 1,
  row_span INTEGER NOT NULL DEFAULT 1, is_covered INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(doc_id, page, tbl, r, c),               -- exactly-once, enforced by the SCHEMA
  FOREIGN KEY(doc_id, page, origin_ord) REFERENCES block(doc_id, page, ord) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE ref(                                     -- the DAG; containment is NOT here
  doc_id TEXT NOT NULL, src_page INTEGER NOT NULL, src_ord INTEGER NOT NULL,
  dst_page INTEGER NOT NULL, dst_ord INTEGER NOT NULL, role TEXT NOT NULL,
  UNIQUE(doc_id, src_page, src_ord, dst_page, dst_ord, role));   -- identity in the SCHEMA,
                                                                 -- or INSERT OR IGNORE is a no-op
CREATE TABLE diag(
  doc_id TEXT NOT NULL REFERENCES doc ON DELETE CASCADE, code TEXT NOT NULL,
  severity TEXT NOT NULL, page INTEGER, ord INTEGER, part TEXT, message TEXT, detail JSON);
CREATE INDEX diag_code ON diag(code);                 -- the absence contract reads this

CREATE VIRTUAL TABLE block_fts USING fts5(
  text, content='block', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
```

```python
# ============ the driver contract: one function, one struct ============
# omniweave/driver.py
class Driver(Protocol):
    name: str; version: str
    capabilities: Capabilities                 # over-declaring FAILS the testkit
    def sniff(self, head: bytes, path: str | None) -> list[Format]: ...   # many-to-one, ranked
    def parse(self, src: SourceBytes, budget: Budget, ctx: DriverCtx) -> OwDoc: ...
# ctx.limits are FIXED constants (anydoc limits.rs), clamped per tenant: min(tenant_cap, MAX_*)
# ctx.asset_sink lets a driver stream bytes out instead of holding them
# a driver NEVER opens a socket; egress is ctx.fetch (one guarded path) or nothing

# $ omniweave doctor report.owdoc
#   container 1 · model 1.0 · status PARTIAL · 5,000 pages · 60,000 blocks · 3.4 MB
#   integrity  OK (checkdoc 14 ms: parent/structure bijection, arena density, grid exactly-once)
#   achieved   spatial=block_bbox charspan=yes span_fidelity=whitespace_normalized
#              tables=cells_with_spans confidence=element furniture=separated round_trip=structure
#   diags      needs_ocr(pages 12-40) x1 · table_recon_low(0.61) x3 · span_fidelity_downgraded x1
#   extensions x["acme.reading_order"] on 41,208 blocks   <- unblessed, preserved, reported
```

---

## Rationale

The blueprint's own thesis is that L2 is the pivot and everything downstream is a view over it. If
that is true, then the thing that decides omniweave's fate is not the elegance of the model but
**how many parties can produce and consume it cheaply, and how loudly it fails when one of them
lies.** Every choice above is that trade:

- **A separate type with an adapter, not inheritance**, because the cost of inheritance is paid by
  every third party forever (a dataframe library in a data-model package; an 8-releases-per-month
  upstream that can redefine our public API) while the cost of an adapter is paid once by us, on our
  schedule, with a published fidelity matrix.
- **Path identity + content digest as separate fields**, because the two camps want two different
  properties and both are cheap: references survive 30 mutating processors, and cache/dedup/drift
  still work. Choosing one is choosing to reimplement the other badly later.
- **Flat arena over a tree**, because the measurement is unambiguous: a tree of typed objects is
  25.3 GB at 10M blocks and cannot seek. A flat arena is a ZIP of 79 frames you can open in 0.95 ms
  and a SQLite table you can point-read in 20 µs.
- **NDJSON+zstd in a ZIP over msgpack/protobuf/Parquet**, because the binary formats buy 4–27% of
  bytes at the cost of the exact property that makes a framework adoptable: a stranger can read a
  frame with `unzip -p x.owdoc blocks/000063.ndjson.zst | zstd -d | jq`. Operability at the boundary
  beats 4% on disk.
- **Four provenance axes with interned producers**, because the runtime mine already proved what
  happens when ownership and trust are one field: a free re-extraction silently deletes billable LLM
  output. 2 bytes per block prevents that.
- **Every invariant has a named enforcement mechanism** — type, constructor, `checkdoc`, SQL CHECK,
  testkit property test, or CI gate — because an invariant with no enforcer is a comment, and the
  mines are full of them (`skills-lock.json` hashes recorded and never verified; docling's
  `table_score` never computed while documents are graded on it; prose rules with no checker behind
  them in ppt-master).
- **`Capabilities.declared` vs `achieved` plus a testkit that fails over-declaration**, because that
  is the only mechanism in this design that makes a third-party driver's *honesty* mechanically
  checkable — and 11 of the collection's parsers hand downstream a string while their READMEs imply
  more.

---

## Tradeoffs (what this costs)

1. **Engineering: ≈8–10 engineer-weeks for the core** (types, archive reader/writer, `checkdoc`,
   `GridBuilder`, `Diag` registry, the streaming API), **+2–3 weeks for the driver testkit**, **+2
   weeks for the docling adapter and its fidelity matrix**. The three-coordinate span system is the
   expensive part: per-driver `span_fidelity` proofs need fixtures, and each new driver pays that
   toll again.
2. **A permanent adapter maintenance burden.** Two docling minors and one major in CI, forever. If
   `docling-core` 3.0 restructures items, we owe users an adapter release fast, and they will blame
   omniweave for the breakage regardless of whose change it was.
3. **Wire overhead of ~30 B/block** for the four provenance axes and the parent/structure redundancy
   — ≈9% of the measured 338 B/block raw JSON, and a larger *relative* share (~12%) after zstd
   because the redundant integers compress well but not to nothing.
4. **`checkdoc` always-on costs 236 ns/block**: 14 ms per 5,000-page document, 2.4 s per 10M-block
   bulk load. Acceptable; the `--no-check` bulk path exists and stamps `integrity_unchecked`, which
   means some archives in the wild are unverified and say so.
5. **Two version numbers is more machinery than one**, and `min_reader` is a third. Operators will
   occasionally see a refusal they consider pedantic. That is the deliberate trade against silent
   misreading.
6. **The `x.` extension bag is an intentional loss of central control.** It is how a contributor
   ships on Tuesday; it is also how two vendors ship `x.acme.reading_order` and
   `x.beta.reading_order` and nothing reconciles them.
7. **Tombstones cost space in long-lived archives** and `compact` is a genuinely dangerous
   operation (see failure 4). We pay space to avoid dangling references.
8. **Rejecting msgpack/Parquet as the representation costs real bytes**: 3.4 MB vs 2.6 MB for a
   5,000-page document, and 0.75 GB vs 0.55 GB at 10M blocks. We pay ~30% of archive size for
   `jq`-ability.

---

## Failure modes (including the input that breaks it)

1. **The adapter lies.** A `to_docling()` that silently flattens table spans is worse than no
   adapter, because users will believe the round trip. Mitigation: `fidelity.json` per field plus a
   published matrix and a round-trip test corpus. Residual risk: docling-core adds a field we do not
   map, and our `from_docling` drops it — caught only if we notice the field.
2. **`span_fidelity` over-declaration in the wild.** The testkit catches it only where fixtures
   exist. A driver that declares `exact` and is off by a soft hyphen produces citations that
   highlight the wrong substring — and the serve layer will have promised "byte-identical, safe to
   Edit from". The honest floor is that most PDF drivers land on `whitespace_normalized` and
   citation-to-byte is unavailable for them; if anyone forgets to surface that in the UI, we have
   shipped a confident lie.
3. **The input that breaks the clean design: one page with 400,000 blocks.** A 4M-cell XLSX sheet or
   a spreadsheet-printed-to-PDF. The frame unit is a page range, so the *page* must fit in RAM;
   anydoc's own `MAX_GRID_SLOTS = 4_000_000` at ~80 B/slot is 320 MB, over the 256 MB CI ceiling.
   Mitigation: frames may split *within* a page above 50,000 blocks (`frame = (page, part_lo,
   part_hi)`) and `Table.slots` serializes as two integer arrays rather than records. This
   complicates the "frame == page range" story, breaks the `frames.json` invariant that frames
   partition pages, and is the first place a reader implementation in another language will get it
   wrong.
4. **Compaction versus external references.** A document re-OCR'd 50 times accumulates 50 generations
   of tombstones. `omniweave compact` rewrites the arena and emits `remap.json`, but any *external*
   holder of an old `BlockRef` — an embedding row, a graph edge, a citation inside a shipped deck —
   breaks. So compaction bumps `arena_epoch` and must refuse when an index references the archive,
   which requires L4 cooperation this decision cannot guarantee. Unresolved.
5. **A table straddling a frame boundary.** A 200-page table crosses the 64-page frame line. The
   writer chooses frame boundaries greedily so no `Table` or `Note` group straddles, which means
   frame sizes vary (63, 66, 200 pages) and the worst case is one enormous frame — reintroducing the
   memory problem for exactly the pathological document.
6. **Refusal-on-major strands users.** A vendor ships `model: 2.0` archives to an omniweave 1.x
   reader and every read fails. Deliberate, but it will generate angry issues and a demand for a
   `--force` flag, which we must refuse (mine-runtime: *"an override flag whose scope is 'skip
   whatever check just complained' is not an override, it is an off switch"*).
7. **Four provenance axes rot into decoration** if any one of them lacks three consumers — the exact
   trap the graph mine names. `score` is the one at risk: if no ranker consumes it, it becomes a
   field every driver fills and nobody reads. Mitigation is a consumer census in review, which is
   process, not enforcement.
8. **The extension bag becomes a shadow schema** (see tradeoff 6). `omniweave doctor --extensions`
   reports frequency so blessing is data-driven, but for some period two incompatible conventions
   for the same concept will coexist in real corpora.
9. **`refs` has no referential-integrity gate at write time by default.** A `Ref` to a tombstoned or
   nonexistent block is possible; `checkdoc` reports it as a warning rather than refusing, because
   refusing would fail archives from a driver mid-development. graphrag's quarantine pattern (keep
   dropped edges, do not delete) is the fallback, and it means some archives carry dead refs.

---

## Why I reject the alternatives

**(a) Inherit `DoclingDocument` (the blueprint's proposal).** Rejected on six checkable grounds in
§1: the type lives in `docling-core`, whose base deps include `pandas` and `typer` and whose
`[chunking]` extra pulls `transformers` + 4 tree-sitter grammars; 168 releases in 21 months with a
whole-major pin (`>=2.73.0,<3.0.0`); JSON-pointer identity that breaks under insertion in a pipeline
with 30 mutating processors; their validators and `model_config` governing our data; a whole-document
`document.json` with no seek; and a `docling-core` 3.0 automatically becoming a breaking change to
every third-party omniweave driver. We keep 100% of the ecosystem benefit via `omniweave-docling`
and pay it on our own release schedule. **This is the one place I overturn the blueprint outright.**

**(b) Content-hash-only identity.** Rejected: any content edit — an LLM fixing a ligature, a
processor merging two lines — rewrites the id and therefore every edge, embedding, annotation and
already-shipped citation that pointed at it. It also is not emittable by a model, which is why
graphrag needed a separate `short_id` ("the only id an LLM may cite") next to its UUID. We keep the
hash as `cid`, which delivers every property the hash-identity camp actually wants.

**(c) Path-only identity.** Rejected: loses content-addressed cache keys, cross-reparse dedup, and
codegraph's fingerprint-proven "you already have this, unchanged" back-reference — the serve mine's
single most novel mechanism, which is a *content* fingerprint precisely because index staleness is
the wrong signal.

**(d) A pure tree (docling's `body`/`furniture` trees).** Rejected on measurement: materializing 10M
blocks as pydantic objects is **25.3 GB** and there is no way to answer "give me page 4,700" without
loading page 1. A tree is a *view* our flat arena computes in O(page) from `parent`/`structure`; the
reverse is not true.

**(e) Flat list with parent pointers only, no order list.** Rejected: reading order becomes a sort
key someone must invent, and marker's measurement says order is *data* — the PDF character stream
beats a learned order head **75% vs 56%**, and native formats have a canonical order that must never
be re-inferred. An unstored order guarantees the framework re-derives a worse one.

**(f) msgpack or protobuf as the wire format.** Rejected: measured, msgpack+zstd-3 is **72.3 vs 75.2
B/block** — a 4% win — for which you give up `jq`, `curl | head`, browser-console inspection, and you
add a C extension to the core. protobuf's field-number discipline is a genuine forward-compat win,
but it puts a codegen toolchain and a schema-compilation step in front of every third-party driver in
every language — precisely the tax that stops the afternoon contributor. Short stable keys + the `x`
extension bag + the `write(read(bytes)) == bytes` preservation test give the same property with no
toolchain.

**(g) Arrow/Parquet as the representation.** Rejected: 27% smaller (54.9 B/block) but a single-page
point read measured **42.8 ms vs SQLite's 20 µs** (caveat stated in §8), and it forces `pyarrow`
(~90 MB) into a core we have promised to keep at ~15 MB. Parquet ships as `omniweave export parquet`
for analytics and for feeding graphrag-shaped tooling — the right job for a scan format.

**(h) Markdown or HTML as the primary representation.** Rejected by the blueprint's own thesis and by
the mine's severity ranking: marker's `block.html` + `structure = []` is irrecoverable loss D#2, and
11 of the collection's parsers hand downstream a string, which is why "no feature needing
citation-to-pixel, layout-faithful rendering, or round-trip can be built on their output at all."

**(i) One JSON per document (docling's `ConversionAssets` as-is).** The one-JSON-per-component
envelope with tolerant load is adopted wholesale — it is the best thing in that file. What is
rejected is `document.json` as a single member and `model_validate` on the whole thing: measured
249 ms per 200k blocks to load and 8.1 GB at 10M even as plain dicts, with no seek. Frames fix it for
the price of a `frames.json` index.

**(j) Safety limits as configuration.** Rejected on anydoc's stated reasoning — a knob that turns off
the zip-bomb cap will be turned off. `limits` are fixed constants enforced at the read boundary with
`take(N+1)`-then-check, and multi-tenancy clamps *below* them: `min(tenant_cap, MAX_*)`, so a limit
hit is a pricing signal and `resource_limit{limit}` names which knob would need raising.
